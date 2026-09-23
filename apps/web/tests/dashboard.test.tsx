import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DashboardView } from "@/features/dashboard/dashboard-view";
import { api } from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

describe("DashboardView", () => {
  it("renders loading skeleton initially and displays dashboard after API fetch", async () => {
    vi.spyOn(api, "GET").mockImplementation(async (path) => {
      if (path === "/api/v1/me") {
        return {
          data: {
            data: {
              user_id: "u-1",
              email: "traveler@example.com",
              display_name: "Alice Travel",
              consents: [],
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
            meta: { contract_version: "1.0.0" },
          },
        } as never;
      }
      if (path === "/api/v1/trips") {
        return {
          data: {
            data: [
              {
                trip_id: "trip-1",
                user_id: "u-1",
                origin: { display_name: "Bangkok", coordinates: [100.5, 13.75] },
                destination: { display_name: "Chiang Mai", coordinates: [98.98, 18.79] },
                departure_time: "2026-10-01T08:00:00Z",
                status: "ACTIVE",
                travel_modes: ["CAR"],
                preferences: { avoid_tollways: false, prefer_safe_route: true },
                revision: "rev-1",
                latest_request_id: "req-1",
                created_at: "2026-09-01T00:00:00Z",
                updated_at: "2026-09-01T00:00:00Z",
              },
            ],
            meta: { count: 1 },
          },
        } as never;
      }
      if (path === "/api/v1/runs/{request_id}") {
        return {
          data: {
            data: {
              request_id: "req-1",
              status: "COMPLETED",
              recommendation_id: "rec-1",
            },
          },
        } as never;
      }
      if (path === "/api/v1/recommendations/{recommendation_id}") {
        return {
          data: {
            data: {
              recommendation_id: "rec-1",
              trip_id: "trip-1",
              action_code: "NORMAL",
              primary_route: {
                route_id: "r-1",
                provider_route_id: "ors-1",
                label: "RECOMMENDED",
                mode: "CAR",
                geometry: { type: "LineString", coordinates: [[100.5, 13.75], [98.98, 18.79]] },
                distance_m: 690000,
                duration_seconds: 32400,
                transfers: 0,
                exposure: null,
                risk_level: "LOW",
                quality: { flags: [] },
                sources: [],
              },
              alternatives: [],
              advisories: [],
              reasons: ["Weather conditions are clear across route."],
              risk_level: "LOW",
              freshness: {
                observed_at: "2026-09-22T00:00:00Z",
                fetched_at: "2026-09-22T00:00:00Z",
                expires_at: "2026-09-22T06:00:00Z",
              },
              versions: {
                risk_model: "1.0.0",
                policy: "1.0.0",
                contract: "1.0.0",
                prompt: "1.0.0",
                knowledge_collection: "1.0.0",
              },
            },
          },
        } as never;
      }
      return { data: null } as never;
    });

    render(<DashboardView />);

    await waitFor(() => {
      expect(screen.getByText(/Alice Travel/)).toBeInTheDocument();
    });

    expect(screen.getByText("Weather Condition")).toBeInTheDocument();
    expect(screen.getByText("Transit & Routes")).toBeInTheDocument();
    expect(screen.getByText("Clear & Safe")).toBeInTheDocument();
    expect(screen.getByText("Bangkok → Chiang Mai")).toBeInTheDocument();
  });
});
