// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient, createSubmission, mapApiError } from "@/lib/api/client";
import { freshnessStaleTime, retryQuery } from "@/lib/api/query";
import { createRequestId } from "@/lib/api/id";

describe("API transport", () => {
  it("creates a UUID when randomUUID is unavailable on an HTTP origin", () => {
    const nativeCrypto = globalThis.crypto;
    vi.stubGlobal("crypto", {
      getRandomValues: nativeCrypto.getRandomValues.bind(nativeCrypto),
    });
    expect(createRequestId()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    vi.unstubAllGlobals();
  });
  it("maps stable errors without displaying arbitrary server content", async () => {
    const response = new Response(
      JSON.stringify({
        error: { code: "RATE_LIMITED", message: "private upstream detail" },
        meta: { request_id: "request" },
      }),
      { status: 429, headers: { "Retry-After": "3" } },
    );
    const error = await mapApiError(response);
    expect(error).toMatchObject({
      status: 429,
      code: "RATE_LIMITED",
      retryAfterMs: 3000,
      requestId: "request",
    });
    expect(error.message).not.toContain("private");
    expect(retryQuery(0, error)).toBe(false);
  });
  it.each([400, 401, 403, 404, 408, 409, 422, 429])("never retries HTTP %i", (status) => {
    expect(retryQuery(0, new ApiError("ERROR", status))).toBe(false);
  });
  it("retries transient failures only within budget and expires stale data", () => {
    expect(retryQuery(1, new ApiError("DEPENDENCY_UNAVAILABLE", 503))).toBe(true);
    expect(retryQuery(2, new ApiError("DEPENDENCY_UNAVAILABLE", 503))).toBe(false);
    expect(retryQuery(0, new Error("AbortError"))).toBe(false);
    expect(freshnessStaleTime("2026-01-01T00:00:10Z", Date.parse("2026-01-01T00:00:00Z"))).toBe(
      10000,
    );
    expect(freshnessStaleTime("invalid")).toBe(0);
    expect(freshnessStaleTime(null)).toBe(0);
  });
  it("coalesces double submit and preserves the idempotency key after a failure", async () => {
    const submit = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValue("created");
    const run = createSubmission(submit);
    const first = run();
    expect(run()).toBe(first);
    await expect(first).rejects.toThrow("network");
    await expect(run()).resolves.toBe("created");
    await expect(run()).resolves.toBe("created");
    expect(submit).toHaveBeenCalledTimes(2);
    expect(submit.mock.calls[0][0]).toBe(submit.mock.calls[1][0]);
  });
  it("forwards cancellation and correlation metadata without a browser token", async () => {
    // Resolve relative browser URLs for Node's Request constructor.
    const NativeRequest = globalThis.Request;
    vi.stubGlobal(
      "Request",
      class extends NativeRequest {
        constructor(input: RequestInfo | URL, init?: RequestInit) {
          super(
            typeof input === "string" && input.startsWith("/") ? `http://localhost${input}` : input,
            init,
          );
        }
      },
    );
    try {
      const controller = new AbortController();
      const fetcher = vi.fn(async (request: Request) => {
        expect(request.headers.get("X-Correlation-ID")).toBeTruthy();
        expect(request.headers.get("Authorization")).toBeNull();
        controller.abort();
        request.signal.throwIfAborted();
        return new Response();
      });
      await expect(
        createApiClient(fetcher as typeof fetch).GET("/api/v1/me", { signal: controller.signal }),
      ).rejects.toMatchObject({ name: "AbortError" });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
