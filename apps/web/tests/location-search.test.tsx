import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocationSearch } from "@/features/trips/location-search";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ api: { GET: get } }));

const result = {
  display_name: "Bangkok, Thailand",
  coordinates: { type: "Point", coordinates: [100.5018, 13.7563] },
  country_code: "TH",
  timezone: "Asia/Bangkok",
  provider: "open_meteo_geocoding",
  place_id: "bangkok",
  confirmed_by_user: false,
};

describe("location search", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    get.mockReset().mockResolvedValue({ data: { data: [result] } });
  });

  it("debounces real search, supports keyboard selection, and requires confirmation", async () => {
    const change = vi.fn();
    render(<LocationSearch label="From" value={null} onChange={change} />);
    const input = screen.getByRole("combobox", { name: "From" });
    fireEvent.change(input, { target: { value: "Bangkok" } });
    expect(get).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(400));
    expect(get).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("option")).toHaveTextContent("Bangkok, Thailand");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(change).toHaveBeenLastCalledWith(expect.objectContaining({ confirmed_by_user: false }));
  });

  it("does not query below the minimum length", async () => {
    render(<LocationSearch label="To" value={null} onChange={() => {}} />);
    fireEvent.change(screen.getByRole("combobox", { name: "To" }), { target: { value: "B" } });
    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(get).not.toHaveBeenCalled();
  });
});
