import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  ActionBadge,
  DataFreshness,
  DegradedBanner,
  RiskBadge,
  SourceList,
} from "@/components/ui/data-states";
describe("sourced data states", () => {
  it("keeps unknown risk and the server action independent", () => {
    render(
      <>
        <RiskBadge risk="UNKNOWN" />
        <ActionBadge action="AVOID" />
      </>,
    );
    expect(screen.getByText(/Unknown risk/)).toBeInTheDocument();
    expect(screen.getByText(/Avoid travel/)).toBeInTheDocument();
  });
  it("marks expired data stale without inventing an observation time", () => {
    render(
      <DataFreshness
        freshness={{
          fetched_at: "2020-01-01T00:00:00Z",
          observed_at: null,
          expires_at: "2020-01-02T00:00:00Z",
        }}
      />,
    );
    expect(screen.getByText("Stale data")).toBeInTheDocument();
    expect(screen.getByText(/Observed: Not available/)).toBeInTheDocument();
  });
  it("announces degradation and absent sources", () => {
    render(
      <>
        <DegradedBanner services={["weather"]} />
        <SourceList sources={[]} />
      </>,
    );
    expect(screen.getByText(/Partial data: weather/)).toBeInTheDocument();
    expect(screen.getByText("Sources not available.")).toBeInTheDocument();
  });
});
