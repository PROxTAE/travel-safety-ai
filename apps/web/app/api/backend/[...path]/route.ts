import { encode, getToken, type JWT } from "next-auth/jwt";
import { NextRequest, NextResponse } from "next/server";
import { refreshToken, sessionCookie } from "@/lib/auth/session";

export const runtime = "nodejs";
const failure = (status: number, code: string) =>
  NextResponse.json(
    {
      error: {
        code,
        message:
          code === "AUTHENTICATION_REQUIRED"
            ? "Please sign in again."
            : "The service is unavailable.",
        retryable: status >= 500,
      },
      meta: {
        request_id: crypto.randomUUID(),
        correlation_id: crypto.randomUUID(),
        contract_version: "1.0.0",
        generated_at: new Date().toISOString(),
        degraded_services: [],
      },
    },
    { status, headers: { "Cache-Control": "no-store" } },
  );

async function forward(request: NextRequest) {
  const secret = process.env.AUTH_SECRET;
  if (!secret) return failure(503, "DEPENDENCY_UNAVAILABLE");
  if (
    !["GET", "HEAD"].includes(request.method) &&
    request.headers.get("origin") !== new URL(process.env.AUTH_URL || request.url).origin
  )
    return failure(403, "FORBIDDEN");
  let token = await getToken({
    req: request,
    secret,
    cookieName: sessionCookie,
    salt: sessionCookie,
  });
  if (!token || token.error || !token.accessToken) return failure(401, "AUTHENTICATION_REQUIRED");
  let changed = false;
  const persist = async (response: NextResponse, value: JWT | null) => {
    for (const cookie of request.cookies.getAll())
      if (cookie.name === sessionCookie || cookie.name.startsWith(sessionCookie + "."))
        response.cookies.set(cookie.name, "", { maxAge: 0, path: "/" });
    if (value) {
      const jwt = await encode({
        token: value,
        secret,
        salt: sessionCookie,
        maxAge: Math.max(0, Number(value.exp) - Math.floor(Date.now() / 1000)),
      });
      const chunks = jwt.match(/.{1,3800}/g) || [];
      chunks.forEach((chunk, index) =>
        response.cookies.set(
          chunks.length === 1 ? sessionCookie : `${sessionCookie}.${index}`,
          chunk,
          {
            httpOnly: true,
            secure: sessionCookie.startsWith("__Secure-"),
            sameSite: "lax",
            path: "/",
          },
        ),
      );
    }
    return response;
  };
  if (Number(token.expiresAt) <= Date.now() + 30_000) {
    token = await refreshToken(token);
    changed = true;
  }
  if (token.error) return persist(failure(401, "AUTHENTICATION_REQUIRED"), null);
  const suffix = request.nextUrl.pathname.slice("/api/backend".length);
  if (!suffix.startsWith("/api/v1/") || /%2f|%5c|\\/i.test(suffix))
    return failure(404, "NOT_FOUND");
  const base = process.env.API_BASE_URL;
  if (!base) return failure(503, "DEPENDENCY_UNAVAILABLE");
  const headers = new Headers({
    "X-Contract-Version": "1",
    "X-Correlation-ID": request.headers.get("X-Correlation-ID") || crypto.randomUUID(),
    "X-Request-ID": crypto.randomUUID(),
    traceparent: `00-${crypto.randomUUID().replaceAll("-", "")}-${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}-01`,
  });
  for (const name of [
    "Content-Type",
    "Accept",
    "Idempotency-Key",
    "If-Match",
    "Last-Event-ID",
    "traceparent",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();
  const streaming = suffix.endsWith("/events");
  const signal = streaming
    ? request.signal
    : AbortSignal.any([request.signal, AbortSignal.timeout(15_000)]);
  const send = () => {
    headers.set("Authorization", `Bearer ${token!.accessToken}`);
    return fetch(new URL(suffix + request.nextUrl.search, base), {
      method: request.method,
      headers,
      body,
      signal,
      cache: "no-store",
      redirect: "error",
    });
  };
  try {
    let upstream = await send();
    if (upstream.status === 401) {
      await upstream.body?.cancel();
      token = await refreshToken(token);
      changed = true;
      if (token.error) return persist(failure(401, "AUTHENTICATION_REQUIRED"), null);
      upstream = await send();
    }
    if (upstream.status === 401) {
      await upstream.body?.cancel();
      return persist(failure(401, "AUTHENTICATION_REQUIRED"), null);
    }
    const outputHeaders = new Headers({ "Cache-Control": "no-store", "X-Accel-Buffering": "no" });
    for (const name of ["Content-Type", "Retry-After", "X-Request-ID", "X-Correlation-ID"]) {
      const value = upstream.headers.get(name);
      if (value) outputHeaders.set(name, value);
    }
    const response = new NextResponse(upstream.body, {
      status: upstream.status,
      headers: outputHeaders,
    });
    return changed ? persist(response, token) : response;
  } catch {
    const response = failure(
      signal.aborted ? 504 : 503,
      signal.aborted ? "DEPENDENCY_TIMEOUT" : "DEPENDENCY_UNAVAILABLE",
    );
    return changed ? persist(response, token) : response;
  }
}
export { forward as GET, forward as POST, forward as PATCH, forward as PUT, forward as DELETE };
