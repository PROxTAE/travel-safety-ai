import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./client";

export function retryQuery(count: number, error: Error) {
  return count < 2 && error instanceof ApiError && [0, 500, 502, 503, 504].includes(error.status);
}
export function freshnessStaleTime(expiresAt?: string | null, now = Date.now()) {
  return expiresAt ? Math.max(0, Date.parse(expiresAt) - now) || 0 : 0;
}
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 0,
        retry: retryQuery,
        retryDelay: (attempt, error) =>
          Math.max(
            error instanceof ApiError ? error.retryAfterMs : 0,
            Math.min(1000 * 2 ** attempt, 10_000),
          ),
        refetchOnWindowFocus: true,
      },
      mutations: { retry: false },
    },
  });
}
