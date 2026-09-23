import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RouteComparison } from "@/features/trips/route-comparison";
import { api } from "@/lib/api/client";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: vi.fn(),
  }),
}));

describe("RouteComparison", () => {
  const mockTrip = {
    trip_id: "trip-test-1",
    user_id: "u-1",
    origin: { display_name: "Bangkok Central", coordinates: [100.5, 13.75] },
    destination: { display_name: "Hua Hin", coordinates: [99.96, 12.57] },
    departure_time: "2026-10-01T08:00:00Z",
    status: "ACTIVE",
    travel_modes: ["CAR"],
    preferences: {},
    revision: "rev-1",
    latest_request_id: "req-1",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  };

  const mockRecommendation = {
    recommendation_id: "rec-test-1",
    trip_id: "trip-test-1",
    action_code: "CHANGE_ROUTE",
    primary_route: {
      route_id: "route-primary",
      provider_route_id: "ors-p",
      label: "FASTEST",
      mode: "CAR",
      geometry: { type: "LineString", coordinates: [[100.5, 13.75], [99.96, 12.57]] },
      distance_m: 198000,
      duration_seconds: 10800,
      transfers: 0,
      exposure: null,
      risk_level: "HIGH",
      quality: { flags: [] },
      sources: [],
    },
    alternatives: [
      {
        route_id: "route-safer",
        provider_route_id: "ors-s",
        label: "RECOMMENDED",
        mode: "CAR",
        geometry: { type: "LineString", coordinates: [[100.5, 13.75], [99.96, 12.57]] },
        distance_m: 210000,
        duration_seconds: 12000,
        transfers: 0,
        exposure: null,
        risk_level: "LOW",
        quality: { flags: [] },
        sources: [],
      },
    ],
    advisories: [],
    reasons: ["Flood detected along coastal highway."],
    risk_level: "HIGH",
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
  };

  it("renders side by side comparison and handles route selection and risk acknowledgement", async () => {
    vi.spyOn(api, "GET").mockImplementation(async (path) => {
      if (path === "/api/v1/trips/{trip_id}") {
        return { data: { data: mockTrip } } as never;
      }
      if (path === "/api/v1/runs/{request_id}") {
        return { data: { data: { request_id: "req-1", recommendation_id: "rec-test-1" } } } as never;
      }
      if (path === "/api/v1/recommendations/{recommendation_id}") {
        return { data: { data: mockRecommendation } } as never;
      }
      return { data: null } as never;
    });

    render(<RouteComparison tripId="trip-test-1" />);

    await waitFor(() => {
      expect(screen.getByText("Route Safety Comparison")).toBeInTheDocument();
    });

    expect(screen.getByText("Bangkok Central → Hua Hin")).toBeInTheDocument();
    expect(screen.getByText("Original Planned Route")).toBeInTheDocument();
    expect(screen.getByText("Recommended Alternative")).toBeInTheDocument();
    expect(screen.getByText(/I understand this route is flagged as/)).toBeInTheDocument();
  });
});
