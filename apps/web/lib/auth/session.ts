import type { JWT } from "next-auth/jwt";
import { createHash } from "node:crypto";
import { keycloakFetch } from "./keycloak-fetch";

export const sessionCookie =
  process.env.NODE_ENV === "production" || process.env.AUTH_URL?.startsWith("https:")
    ? "__Secure-authjs.session-token"
    : "authjs.session-token";

export function safeReturnTo(value: unknown): string {
  return typeof value === "string" &&
    /^\/(dashboard|trips|safety-map|assistant|emergency)(\/|\?|$)/.test(value) &&
    !value.includes("\\")
    ? value
    : "/dashboard";
}

// Coalesce rotating refresh tokens within the single web process. Never log keys or tokens.
const refreshing = new Map<string, Promise<JWT>>();
export async function refreshToken(token: JWT): Promise<JWT> {
  if (typeof token.refreshToken !== "string")
    return { ...token, error: "RefreshTokenError", accessToken: undefined };
  const key = createHash("sha256").update(token.refreshToken).digest("hex");
  const existing = refreshing.get(key);
  if (existing) return existing;
  const pending = (async () => {
    try {
      const body = new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: token.refreshToken as string,
        client_id: process.env.AUTH_KEYCLOAK_ID || "web",
      });
      if (process.env.AUTH_KEYCLOAK_SECRET)
        body.set("client_secret", process.env.AUTH_KEYCLOAK_SECRET);
      const response = await keycloakFetch(
        `${process.env.AUTH_KEYCLOAK_ISSUER}/protocol/openid-connect/token`,
        {
          method: "POST",
          body,
          cache: "no-store",
          signal: AbortSignal.timeout(10_000),
        },
      );
      const result = await response.json();
      if (
        !response.ok ||
        typeof result.access_token !== "string" ||
        typeof result.expires_in !== "number"
      )
        throw new Error("refresh failed");
      return {
        ...token,
        accessToken: result.access_token,
        refreshToken: result.refresh_token ?? token.refreshToken,
        expiresAt: Date.now() + result.expires_in * 1000,
        error: undefined,
      };
    } catch {
      return {
        ...token,
        accessToken: undefined,
        refreshToken: undefined,
        error: "RefreshTokenError",
      };
    }
  })();
  refreshing.set(key, pending);
  void pending.finally(() => {
    const timer = setTimeout(() => refreshing.delete(key), 10_000);
    timer.unref?.();
  });
  return pending;
}
