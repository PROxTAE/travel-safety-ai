import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RouteOptions } from "@/components/trip/route-options";
import type { components } from "@/lib/api/generated/public-api";

type Recommendation = components["schemas"]["RecommendationResponse"];

describe("route options", () => {
  it("shows unavailable instead of inventing a route", () => {
    render(
      <RouteOptions
        recommendation={
          {
            primary_route: null,
            alternatives: [],
          } as unknown as Recommendation
        }
      />,
    );
    expect(screen.getByText(/No route options are available/)).toBeInTheDocument();
  });

  it("renders the server risk separately from route metrics", () => {
    const route = {
      route_id: "provider:route-1",
      provider_route_id: "route-1",
      label: "RECOMMENDED",
      mode: "CAR",
      geometry: {
        type: "LineString",
        coordinates: [
          [100, 13],
          [99, 18],
        ],
      },
      distance_m: 700000,
      duration_seconds: 36000,
      transfers: 0,
      exposure: null,
      risk_level: "UNKNOWN",
      quality: { flags: ["INCOMPLETE"] },
      sources: [],
    };
    render(
      <RouteOptions
        recommendation={
          {
            trip_id: "00000000-0000-4000-8000-000000000001",
            primary_route: route,
            alternatives: [],
            freshness: { observed_at: null, fetched_at: "2099-01-01T00:00:00Z", expires_at: null },
          } as unknown as Recommendation
        }
      />,
    );
    expect(screen.getByText("Unknown risk")).toBeInTheDocument();
    expect(screen.getByText("700 km")).toBeInTheDocument();
    expect(screen.getByText(/INCOMPLETE/)).toBeInTheDocument();
  });
});
