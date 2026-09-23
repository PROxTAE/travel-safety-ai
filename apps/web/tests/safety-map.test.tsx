import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SafetyMapView } from "@/features/safety-map/safety-map-view";
import { api } from "@/lib/api/client";

describe("SafetyMapView", () => {
  const mockEvents = [
    {
      event_id: "evt-flood-1",
      layer: "WEATHER",
      severity: "HIGH",
      event_type: "FLOOD",
      title: "Flash Flood Warning in Central Valley",
      description: "Severe rainfall causing localized road flooding.",
      geometry: { type: "Point", coordinates: [100.5, 13.75] },
      starts_at: "2026-09-22T00:00:00Z",
      ends_at: "2026-09-23T00:00:00Z",
      official: true,
      source: {
        provider: "Open-Meteo",
        authority: "Thai Meteorological Dept",
        observed_at: "2026-09-22T00:00:00Z",
        fetched_at: "2026-09-22T00:00:00Z",
        expires_at: "2026-09-23T00:00:00Z",
      },
    },
  ];

  it("renders safety map controls, layers, and displays event details on marker selection", async () => {
    vi.spyOn(api, "GET").mockImplementation(async (path) => {
      if (path === "/api/v1/safety/events") {
        return { data: { data: mockEvents } } as never;
      }
      return { data: null } as never;
    });

    render(<SafetyMapView />);

    expect(screen.getByText("Safety & Hazard Map")).toBeInTheDocument();
    expect(screen.getByText("Weather Hazards")).toBeInTheDocument();
    expect(screen.getByText("Natural Disasters")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/active hazard records in region/)).toBeInTheDocument();
    });

    // Find and click the hazard marker
    const marker = await waitFor(() => screen.getByLabelText(/Flash Flood Warning/));
    fireEvent.click(marker);

    // Event details drawer should open
    await waitFor(() => {
      expect(screen.getByText("Flash Flood Warning in Central Valley")).toBeInTheDocument();
    });
    expect(screen.getByText("Thai Meteorological Dept")).toBeInTheDocument();
    expect(screen.getByText("Avoid This Area in Trip Planner")).toBeInTheDocument();
  });
});
