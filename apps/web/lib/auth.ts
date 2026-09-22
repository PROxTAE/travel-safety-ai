import NextAuth, { customFetch } from "next-auth";
import Keycloak from "next-auth/providers/keycloak";
import { sessionCookie } from "./auth/session";
import { keycloakFetch } from "./auth/keycloak-fetch";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Keycloak({
      [customFetch]: keycloakFetch,
      clientId: process.env.AUTH_KEYCLOAK_ID || "web",
      clientSecret: process.env.AUTH_KEYCLOAK_SECRET || undefined,
      issuer: process.env.AUTH_KEYCLOAK_ISSUER,
      client: {
        token_endpoint_auth_method: process.env.AUTH_KEYCLOAK_SECRET
          ? "client_secret_post"
          : "none",
      },
      checks: ["pkce", "state"],
      authorization: { params: { scope: "openid profile email travel" } },
    }),
  ],
  pages: { signIn: "/login", error: "/login" },
  session: { strategy: "jwt", maxAge: 36_000 },
  cookies: {
    sessionToken: {
      name: sessionCookie,
      options: {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: sessionCookie.startsWith("__Secure-"),
      },
    },
  },
  callbacks: {
    jwt({ token, account }) {
      if (account)
        return {
          ...token,
          accessToken: account.access_token,
          refreshToken: account.refresh_token,
          expiresAt: (account.expires_at ?? 0) * 1000,
        };
      return token;
    },
    session({ session }) {
      // Auth.js's public session endpoint must never expose OAuth credentials.
      return { expires: session.expires, user: { name: session.user?.name } };
    },
  },
});
