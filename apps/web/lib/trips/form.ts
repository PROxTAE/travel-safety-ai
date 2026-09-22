import { z } from "zod";
import type { components } from "@/lib/api/generated/public-api";

type Schema = components["schemas"];

export const tripFormSchema = z
  .object({
    departure: z.string().min(1, "Choose a departure date and time."),
    returnAt: z.string(),
    timezone: z.string().refine(isValidTimezone, "Choose a valid timezone."),
    travelMode: z.enum(["FLIGHT", "TRAIN", "BUS", "CAR", "WALK", "BICYCLE", "MULTIMODAL"]),
    preferSaferRoute: z.boolean(),
    preferLowerCost: z.boolean(),
    preferLowerEmissions: z.boolean(),
  })
  .superRefine((values, context) => {
    let departure: string;
    try {
      departure = zonedDateTimeToIso(values.departure, values.timezone);
    } catch {
      context.addIssue({
        code: "custom",
        path: ["departure"],
        message: "Departure time is invalid.",
      });
      return;
    }
    if (Date.parse(departure) < Date.now() - 5 * 60_000)
      context.addIssue({
        code: "custom",
        path: ["departure"],
        message: "Departure cannot be in the past.",
      });
    if (values.returnAt) {
      try {
        const returnAt = zonedDateTimeToIso(values.returnAt, values.timezone);
        if (Date.parse(returnAt) <= Date.parse(departure))
          context.addIssue({
            code: "custom",
            path: ["returnAt"],
            message: "Return must be after departure.",
          });
      } catch {
        context.addIssue({
          code: "custom",
          path: ["returnAt"],
          message: "Return time is invalid.",
        });
      }
    }
  });

export type TripFormValues = z.infer<typeof tripFormSchema>;

export function isValidTimezone(timezone: string) {
  try {
    new Intl.DateTimeFormat("en", { timeZone: timezone }).format();
    return true;
  } catch {
    return false;
  }
}

function partsAt(timestamp: number, timezone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(timestamp);
  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}

export function zonedDateTimeToIso(value: string, timezone: string) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) || !isValidTimezone(timezone))
    throw new Error("Invalid local date/time or timezone");
  const [date, time] = value.split("T");
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute] = time.split(":").map(Number);
  const wallUtc = Date.UTC(year, month - 1, day, hour, minute);
  let instant = wallUtc;
  for (let attempt = 0; attempt < 3; attempt++) {
    const parts = partsAt(instant, timezone);
    const renderedUtc = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
      Number(parts.second),
    );
    instant += wallUtc - renderedUtc;
  }
  const verified = partsAt(instant, timezone);
  const rendered = `${verified.year}-${verified.month}-${verified.day}T${verified.hour}:${verified.minute}`;
  if (rendered !== value)
    throw new Error("This local time does not exist in the selected timezone");

  const offsetMinutes = Math.round((wallUtc - instant) / 60_000);
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absolute = Math.abs(offsetMinutes);
  const offset = `${sign}${String(Math.floor(absolute / 60)).padStart(2, "0")}:${String(absolute % 60).padStart(2, "0")}`;
  return `${value}:00${offset}`;
}

export function isoToLocalInput(value: string, timezone: string) {
  const parts = partsAt(Date.parse(value), timezone);
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

export function toTripPayload(
  values: TripFormValues,
  origin: Schema["LocationRef"],
  destination: Schema["LocationRef"],
): Schema["CreateTripRequest"] {
  return {
    title: `${origin.display_name} → ${destination.display_name}`,
    origin: { ...origin, confirmed_by_user: true },
    destination: { ...destination, confirmed_by_user: true },
    departure_time: zonedDateTimeToIso(values.departure, values.timezone),
    return_time: values.returnAt ? zonedDateTimeToIso(values.returnAt, values.timezone) : null,
    timezone: values.timezone,
    travel_modes: [values.travelMode],
    preferences: {
      prefer_safer_route: values.preferSaferRoute,
      prefer_lower_cost: values.preferLowerCost,
      prefer_lower_emissions: values.preferLowerEmissions,
    },
  };
}
