// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { encode } from "next-auth/jwt";
import { safeReturnTo, sessionCookie } from "@/lib/auth/session";
import { proxy } from "@/proxy";
import { GET, POST } from "@/app/api/backend/[...path]/route";

const secret = "test-only-secret-with-at-least-thirty-two-characters";
async function request(path = "/api/backend/api/v1/me", init: RequestInit = {}) {
  const token = await encode({
    secret,
    salt: sessionCookie,
    token: {
      sub: "test-subject",
      accessToken: "test-access",
      refreshToken: crypto.randomUUID(),
      expiresAt: Date.now() + 300000,
    },
  });
  return new NextRequest(`http://localhost:3000${path}`, {
    ...init,
    signal: init.signal ?? undefined,
    headers: { cookie: `${sessionCookie}=${token}`, ...init.headers },
  });
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("OIDC route and API boundary", () => {
  it("redirects unauthenticated protected routes with a safe return path", async () => {
    vi.stubEnv("AUTH_SECRET", secret);
    const response = await proxy(new NextRequest("http://localhost:3000/trips/new?mode=CAR"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/login?callbackUrl=%2Ftrips%2Fnew%3Fmode%3DCAR",
    );
    expect(safeReturnTo("//evil.example")).toBe("/dashboard");
    expect(safeReturnTo("/trips\\evil")).toBe("/dashboard");
    expect(safeReturnTo("/trips/new")).toBe("/trips/new");
  });
  it("allows authenticated routes", async () => {
    vi.stubEnv("AUTH_SECRET", secret);
    expect((await proxy(await request("/dashboard"))).headers.get("x-middleware-next")).toBe("1");
  });
  it("refuses anonymous API access and cross-origin mutations", async () => {
    vi.stubEnv("AUTH_SECRET", secret);
    expect((await GET(new NextRequest("http://localhost:3000/api/backend/api/v1/me"))).status).toBe(
      401,
    );
    expect(
      (
        await POST(
          await request(undefined, { method: "POST", headers: { origin: "https://evil.example" } }),
        )
      ).status,
    ).toBe(403);
  });
  it("refreshes once after 401, retries with the new bearer and persists only an HttpOnly cookie", async () => {
    vi.stubEnv("AUTH_SECRET", secret);
    vi.stubEnv("API_BASE_URL", "http://api:8000");
    vi.stubEnv("AUTH_KEYCLOAK_ISSUER", "http://keycloak/realms/test");
    const authorization: (string | null)[] = [];
    const fetcher = vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.body instanceof URLSearchParams)
        return Response.json({
          access_token: "rotated-access",
          refresh_token: "rotated-refresh",
          expires_in: 300,
        });
      authorization.push(new Headers(init?.headers).get("authorization"));
      return authorization.length === 1
        ? new Response(null, { status: 401 })
        : Response.json({ data: { display_name: "Test" } });
    });
    vi.stubGlobal("fetch", fetcher);
    const response = await GET(await request());
    expect(response.status).toBe(200);
    expect(authorization).toEqual(["Bearer test-access", "Bearer rotated-access"]);
    expect(response.headers.get("set-cookie")).toContain("HttpOnly");
    expect(JSON.stringify(await response.json())).not.toContain("rotated");
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
  it("clears the session after failed refresh without leaking token errors", async () => {
    vi.stubEnv("AUTH_SECRET", secret);
    vi.stubEnv("API_BASE_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    const response = await GET(await request());
    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
    expect(await response.json()).toMatchObject({ error: { code: "AUTHENTICATION_REQUIRED" } });
  });
  it("clears the session when the refreshed token is also rejected", async () => {
    vi.stubEnv("AUTH_SECRET", secret);
    vi.stubEnv("API_BASE_URL", "http://api:8000");
    vi.stubEnv("AUTH_KEYCLOAK_ISSUER", "http://keycloak/realms/test");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response(null, { status: 401 }))
        .mockResolvedValueOnce(Response.json({ access_token: "rejected", expires_in: 300 }))
        .mockResolvedValueOnce(new Response(null, { status: 401 })),
    );
    const response = await GET(await request());
    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
  });

  it("forwards SSE replay headers and cancellation without buffering", async () => {
    vi.stubEnv("AUTH_SECRET", secret);
    vi.stubEnv("API_BASE_URL", "http://api:8000");
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(": heartbeat\n\n"));
        controller.close();
      },
    });
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(body, { headers: { "Content-Type": "text/event-stream" } }));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    const response = await GET(
      await request("/api/backend/api/v1/runs/test/events", {
        signal: controller.signal,
        headers: { "Last-Event-ID": "42" },
      }),
    );
    expect(response.body).toBe(body);
    expect(fetcher.mock.calls[0][1].headers.get("Last-Event-ID")).toBe("42");
    expect(fetcher.mock.calls[0][1].headers.get("traceparent")).toMatch(
      /^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/,
    );
    controller.abort();
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  });
});
