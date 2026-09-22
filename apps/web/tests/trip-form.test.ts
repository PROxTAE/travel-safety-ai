import { describe, expect, it } from "vitest";
import {
  isValidTimezone,
  isoToLocalInput,
  toTripPayload,
  tripFormSchema,
  zonedDateTimeToIso,
} from "@/lib/trips/form";

const location = {
  display_name: "Bangkok, Thailand",
  coordinates: { type: "Point" as const, coordinates: [100.5018, 13.7563] as [number, number] },
  country_code: "TH",
  timezone: "Asia/Bangkok",
  provider: "open_meteo_geocoding",
  confirmed_by_user: true,
};

describe("trip form time and payload rules", () => {
  it("converts wall time using the selected trip timezone", () => {
    expect(zonedDateTimeToIso("2099-01-02T09:30", "Asia/Bangkok")).toBe(
      "2099-01-02T09:30:00+07:00",
    );
    expect(isoToLocalInput("2099-01-02T02:30:00Z", "Asia/Bangkok")).toBe("2099-01-02T09:30");
  });

  it("rejects invalid zones, reversed dates, and daylight-saving gaps", () => {
    expect(isValidTimezone("Moon/Sea_of_Tranquility")).toBe(false);
    expect(() => zonedDateTimeToIso("2099-03-08T02:30", "America/New_York")).toThrow();
    const result = tripFormSchema.safeParse({
      departure: "2099-04-05T12:00",
      returnAt: "2099-04-05T11:00",
      timezone: "Asia/Bangkok",
      travelMode: "CAR",
      preferSaferRoute: true,
      preferLowerCost: false,
      preferLowerEmissions: false,
    });
    expect(result.success).toBe(false);
  });

  it("preserves confirmed provider locations and preferences in the contract payload", () => {
    const payload = toTripPayload(
      {
        departure: "2099-01-02T09:30",
        returnAt: "",
        timezone: "Asia/Bangkok",
        travelMode: "CAR",
        preferSaferRoute: true,
        preferLowerCost: false,
        preferLowerEmissions: true,
      },
      location,
      {
        ...location,
        display_name: "Chiang Mai, Thailand",
        coordinates: { ...location.coordinates, coordinates: [98.9853, 18.7883] },
      },
    );
    expect(payload.origin.provider).toBe("open_meteo_geocoding");
    expect(payload.destination.confirmed_by_user).toBe(true);
    expect(payload.travel_modes).toEqual(["CAR"]);
    expect(payload.preferences?.prefer_lower_emissions).toBe(true);
    expect(payload.return_time).toBeNull();
  });
});
