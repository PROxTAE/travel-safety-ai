import createClient from "openapi-fetch";
import type { paths, components } from "./generated/public-api";
import { createRequestId } from "./id";

export class ApiError extends Error {
  constructor(
    public code: string,
    public status: number,
    public retryAfterMs = 0,
    public requestId?: string,
    public fieldErrors: components["schemas"]["FieldError"][] = [],
  ) {
    super(
      code === "AUTHENTICATION_REQUIRED"
        ? "Your session has expired. Please sign in again."
        : code === "DEPENDENCY_TIMEOUT"
          ? "The request timed out. Please try again."
          : "The request could not be completed.",
    );
    this.name = "ApiError";
  }
}

export async function mapApiError(response: Response): Promise<ApiError> {
  const payload = await response
    .clone()
    .json()
    .catch(() => null);
  const header = response.headers.get("Retry-After");
  const retryAfterMs = header
    ? /^\d+$/.test(header)
      ? Number(header) * 1000
      : Math.max(0, Date.parse(header) - Date.now())
    : Number(payload?.error?.retry_after_seconds || 0) * 1000;
  return new ApiError(
    response.status === 401 ? "AUTHENTICATION_REQUIRED" : payload?.error?.code || "INTERNAL_ERROR",
    response.status,
    Number.isFinite(retryAfterMs) ? retryAfterMs : 0,
    payload?.meta?.request_id,
    Array.isArray(payload?.error?.field_errors)
      ? payload.error.field_errors.filter(
          (field: { path?: unknown; code?: unknown }) =>
            typeof field?.path === "string" && typeof field?.code === "string",
        )
      : [],
  );
}

export function createApiClient(fetcher: typeof fetch = fetch) {
  const client = createClient<paths>({ baseUrl: "/api/backend", fetch: fetcher });
  client.use({
    onRequest({ request }) {
      request.headers.set("X-Correlation-ID", createRequestId());
      request.headers.set("X-Contract-Version", "1");
      return new Request(request, {
        credentials: "same-origin",
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(15_000)]),
      });
    },
    async onResponse({ response }) {
      if (!response.ok) throw await mapApiError(response);
    },
    onError({ error, request }) {
      if (request.signal.aborted && request.signal.reason?.name !== "TimeoutError")
        return new DOMException("Request cancelled", "AbortError");
      if (error instanceof DOMException && error.name === "AbortError") return error;
      return new ApiError(
        error instanceof DOMException && error.name === "TimeoutError"
          ? "DEPENDENCY_TIMEOUT"
          : "DEPENDENCY_UNAVAILABLE",
        0,
      );
    },
  });
  return client;
}
export const api = createApiClient();

// One user intent owns one key and promise; explicit retries reuse the key.
export function createSubmission<T>(submit: (key: string) => Promise<T>) {
  const key = createRequestId();
  let pending: Promise<T> | undefined;
  return () => {
    if (!pending)
      pending = submit(key).catch((error) => {
        pending = undefined;
        throw error;
      });
    return pending;
  };
}
