"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import type { components } from "@/lib/api/generated/public-api";
import { api, ApiError, createSubmission } from "@/lib/api/client";
import { createRequestId } from "@/lib/api/id";
import { useRunEvents } from "@/features/assessment/use-run-events";
import { LocationSearch } from "./location-search";
import {
  isoToLocalInput,
  toTripPayload,
  tripFormSchema,
  type TripFormValues,
} from "@/lib/trips/form";
import { DegradedBanner, ErrorState } from "@/components/ui/data-states";
import { RouteOptions } from "@/components/trip/route-options";

const TripMap = dynamic(
  () => import("@/components/trip/trip-map").then((module) => module.TripMap),
  {
    ssr: false,
    loading: () => <div className="trip-map-loading">Loading interactive map…</div>,
  },
);

type Schema = components["schemas"];
type Location = Schema["LocationRef"];

const stageLabels: Record<Schema["RunStage"], string> = {
  VALIDATING: "Validating your trip",
  FETCHING_EXTERNAL_DATA: "Checking current weather, transport, and hazards",
  INTEGRATING_DATA: "Matching current conditions to your route",
  ASSESSING_RISK: "Assessing route risk",
  RETRIEVING_GUIDANCE: "Retrieving verified guidance",
  EVALUATING_ROUTES: "Evaluating route options",
  MAKING_DECISION: "Applying travel safety policy",
  EXPLAINING: "Preparing a clear explanation",
  FORMATTING_RESPONSE: "Finalizing route options",
};

function defaultDeparture() {
  const date = new Date(Date.now() + 24 * 60 * 60_000);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function TripPlanner({ tripId = null }: { tripId?: string | null }) {
  const [previewMode, setPreviewMode] = useState<"map" | "list">("map");
  const [origin, setOrigin] = useState<Location | null>(null);
  const [destination, setDestination] = useState<Location | null>(null);
  const [trip, setTrip] = useState<Schema["Trip"] | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [recommendation, setRecommendation] = useState<Schema["RecommendationResponse"] | null>(
    null,
  );
  const [error, setError] = useState<Error | null>(null);
  const [loadingTrip, setLoadingTrip] = useState(Boolean(tripId));
  const [degraded, setDegraded] = useState<string[]>([]);
  const completedRecommendation = useRef<string | null>(null);
  const defaultTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const {
    register,
    handleSubmit,
    reset,
    setError: setFormError,
    formState: { errors, isSubmitting },
  } = useForm<TripFormValues>({
    defaultValues: {
      departure: defaultDeparture(),
      returnAt: "",
      timezone: defaultTimezone,
      travelMode: "CAR",
      preferSaferRoute: true,
      preferLowerCost: false,
      preferLowerEmissions: false,
    },
  });
  const run = useRunEvents(runId);

  useEffect(() => {
    if (!tripId) return;
    const controller = new AbortController();
    void api
      .GET("/api/v1/trips/{trip_id}", {
        params: { path: { trip_id: tripId } },
        signal: controller.signal,
      })
      .then(({ data }) => {
        if (!data) throw new Error("Trip response was empty");
        const loaded = data.data;
        setTrip(loaded);
        setOrigin(loaded.origin);
        setDestination(loaded.destination);
        reset({
          departure: isoToLocalInput(loaded.departure_time, loaded.timezone),
          returnAt: loaded.return_time ? isoToLocalInput(loaded.return_time, loaded.timezone) : "",
          timezone: loaded.timezone,
          travelMode: loaded.travel_modes[0] ?? "CAR",
          preferSaferRoute: loaded.preferences?.prefer_safer_route ?? true,
          preferLowerCost: loaded.preferences?.prefer_lower_cost ?? false,
          preferLowerEmissions: loaded.preferences?.prefer_lower_emissions ?? false,
        });
      })
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") setError(reason);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingTrip(false);
      });
    return () => controller.abort();
  }, [reset, tripId]);

  useEffect(() => {
    const event = run.event;
    if (!event) return;
    if (
      event.event === "run.completed" &&
      completedRecommendation.current !== event.data.recommendation_id
    ) {
      completedRecommendation.current = event.data.recommendation_id;
      void api
        .GET("/api/v1/recommendations/{recommendation_id}", {
          params: { path: { recommendation_id: event.data.recommendation_id } },
        })
        .then(({ data }) => {
          if (!data) throw new Error("Recommendation response was empty");
          setRecommendation(data.data);
          setDegraded((services) =>
            Array.from(
              new Set([
                ...services,
                ...data.data.degraded_services.map((service) => service.service),
              ]),
            ),
          );
        })
        .catch((reason: Error) => setError(reason));
    }
  }, [run.event]);

  const routes = useMemo(
    () =>
      recommendation
        ? [recommendation.primary_route, ...(recommendation.alternatives ?? [])].filter(
            (route): route is Schema["RouteCandidate"] => Boolean(route),
          )
        : [],
    [recommendation],
  );

  const submit = handleSubmit(async (values) => {
    setError(null);
    setRecommendation(null);
    setRunId(null);
    setDegraded([]);
    const parsed = tripFormSchema.safeParse(values);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        const field = issue.path[0] as keyof TripFormValues;
        setFormError(field, { type: "validate", message: issue.message });
      }
      return;
    }
    if (!origin?.confirmed_by_user || !destination?.confirmed_by_user) {
      setError(new Error("Select and confirm both location pins before finding routes."));
      return;
    }
    const payload = toTripPayload(parsed.data, origin, destination);
    const submission = createSubmission(async (tripKey) => {
      let saved: Schema["Trip"];
      if (trip) {
        const { data } = await api.PATCH("/api/v1/trips/{trip_id}", {
          params: {
            path: { trip_id: trip.trip_id },
            header: { "If-Match": `W/"${trip.revision}"` },
          },
          body: payload,
        });
        if (!data) throw new Error("Trip update response was empty");
        saved = data.data;
      } else {
        const { data } = await api.POST("/api/v1/trips", {
          params: { header: { "Idempotency-Key": tripKey } },
          body: payload,
        });
        if (!data) throw new Error("Trip creation response was empty");
        saved = data.data;
      }
      setTrip(saved);
      const assessmentKey = createRequestId();
      const { data: assessment } = await api.POST("/api/v1/trips/{trip_id}/assessments", {
        params: {
          path: { trip_id: saved.trip_id },
          header: { "Idempotency-Key": assessmentKey },
        },
        body: { question: "Find current, safer route options for this trip." },
      });
      if (!assessment) throw new Error("Assessment response was empty");
      setRunId(assessment.data.request_id);
    });
    await submission().catch((reason: Error) => setError(reason));
  });

  const progress = run.event?.event === "run.progress" ? run.event.data : null;
  const needsInput = run.event?.event === "run.needs_input" ? run.event.data : null;
  const runFailure =
    run.event?.event === "run.failed" ? new ApiError(run.event.data.error.code, 502) : null;
  const visibleError = error ?? runFailure;
  const degradedServices = Array.from(new Set([...degraded, ...run.degradedServices]));
  const assessmentActive = Boolean(
    runId &&
      !recommendation &&
      !visibleError &&
      !["completed", "cancelled", "error"].includes(run.connection),
  );

  return (
    <section className="route-screen trip-planner-screen">
      <div className="trip-page-heading">
        <h1>{tripId ? "Update your trip" : "Plan a New Trip"}</h1>
        <p>Confirm real places and let the live services check current route conditions.</p>
      </div>
      <DegradedBanner services={degradedServices} updatedAt={recommendation?.created_at} />
      {loadingTrip ? (
        <div className="trip-panel trip-map-loading">Loading your trip…</div>
      ) : (
        <div className="trip-planner-grid">
          <form className="trip-panel trip-form" onSubmit={submit} noValidate>
            <h2>
              <span className="trip-heading-icon" aria-hidden="true">
                ▦
              </span>{" "}
              Trip Details
            </h2>
            <LocationSearch label="From" value={origin} onChange={setOrigin} />
            <LocationSearch label="To" value={destination} onChange={setDestination} />
            <div className="trip-field-grid">
              <label>
                Departure
                <input type="datetime-local" {...register("departure")} />
                {errors.departure && (
                  <span className="field-error">{errors.departure.message}</span>
                )}
              </label>
              <label>
                Return <span className="optional-label">Optional</span>
                <input type="datetime-local" {...register("returnAt")} />
                {errors.returnAt && <span className="field-error">{errors.returnAt.message}</span>}
              </label>
            </div>
            <label>
              Trip timezone
              <input {...register("timezone")} aria-describedby="timezone-help" />
              <span id="timezone-help" className="field-help">
                IANA timezone for the trip’s local dates.
              </span>
              {errors.timezone && <span className="field-error">{errors.timezone.message}</span>}
            </label>
            <fieldset className="trip-choice-group">
              <legend>Travel mode</legend>
              <div className="choice-row">
                {(["FLIGHT", "TRAIN", "BUS", "CAR"] as const).map((mode) => (
                  <label key={mode}>
                    <input type="radio" value={mode} {...register("travelMode")} />
                    <span>
                      {mode === "FLIGHT" || mode === "TRAIN" ? (
                        <Image
                          src={`/assets/icons/transport-${mode.toLowerCase()}.png`}
                          width={20}
                          height={20}
                          alt=""
                        />
                      ) : (
                        <i aria-hidden="true">{mode === "BUS" ? "▣" : "◆"}</i>
                      )}
                      {mode.charAt(0) + mode.slice(1).toLowerCase()}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="trip-choice-group">
              <legend>Preferences</legend>
              <div className="choice-row preference-row">
                <label>
                  <input type="checkbox" {...register("preferSaferRoute")} />
                  <span>
                    <Image src="/assets/icons/shield-safe.png" width={18} height={18} alt="" />
                    Safer route
                  </span>
                </label>
                <label>
                  <input type="checkbox" {...register("preferLowerEmissions")} />
                  <span>Eco-friendly</span>
                </label>
                <label>
                  <input type="checkbox" {...register("preferLowerCost")} />
                  <span>Lower cost</span>
                </label>
              </div>
            </fieldset>
            {visibleError && <ErrorState error={visibleError} />}
            <button
              className="find-routes-button"
              type="submit"
              disabled={isSubmitting || assessmentActive}
            >
              <span className="search-button-icon" aria-hidden="true" />
              {isSubmitting
                ? "Saving trip…"
                : assessmentActive
                  ? "Assessment running…"
                  : "Find safe routes"}
            </button>
          </form>

          <section className="trip-panel route-preview" aria-labelledby="route-preview-title">
            <div className="trip-panel-heading">
              <div>
                <h2 id="route-preview-title">
                  <span className="trip-heading-icon trip-heading-pin" aria-hidden="true">
                    ●
                  </span>{" "}
                  Route Preview
                </h2>
                <p>
                  {origin?.display_name ?? "Choose an origin"} →{" "}
                  {destination?.display_name ?? "choose a destination"}
                </p>
              </div>
              <div className="preview-mode-switch" aria-label="Route preview mode">
                <button
                  type="button"
                  aria-pressed={previewMode === "map"}
                  onClick={() => setPreviewMode("map")}
                >
                  Map
                </button>
                <button
                  type="button"
                  aria-pressed={previewMode === "list"}
                  onClick={() => setPreviewMode("list")}
                >
                  List
                </button>
              </div>
            </div>
            {previewMode === "map" ? (
              <>
                <TripMap origin={origin} destination={destination} routes={routes} />
                <div className="map-legend" aria-label="Map legend">
                  <span>
                    <i className="legend-line recommended" /> Recommended route
                  </span>
                  <span>
                    <i className="legend-line alternative" /> Alternative route
                  </span>
                  <span>
                    <i className="legend-pin origin" /> Origin
                  </span>
                  <span>
                    <i className="legend-pin destination" /> Destination
                  </span>
                </div>
              </>
            ) : (
              <div className="route-preview-list">
                <RouteOptions recommendation={recommendation} />
              </div>
            )}
          </section>

          <aside className="route-options-column" aria-labelledby="route-options-title">
            <section className="trip-panel route-options">
              <h2 id="route-options-title">
                <span className="route-options-icon" aria-hidden="true">
                  ⎇
                </span>{" "}
                Route Options
              </h2>
              {runId && !recommendation && !visibleError && (
                <div className="assessment-progress" role="status" aria-live="polite">
                  <span className="assessment-spinner" aria-hidden="true" />
                  <strong>
                    {progress ? stageLabels[progress.stage] : "Connecting to the assessment…"}
                  </strong>
                  {progress?.percent != null && (
                    <progress max="100" value={progress.percent}>
                      {progress.percent}%
                    </progress>
                  )}
                  <p>Connection: {run.connection}</p>
                  <button type="button" onClick={run.cancel}>
                    Stop watching progress
                  </button>
                </div>
              )}
              {needsInput && (
                <div role="alert" className="assessment-needs-input">
                  More information is required: {needsInput.missing_fields.join(", ")}.
                </div>
              )}
              <RouteOptions recommendation={recommendation} />
            </section>
            <div className="trip-assistant" aria-label="Trip planning assistant">
              <p>I’ll check current weather, transport, and local risks.</p>
              <Image
                src="/assets/mascot/mascot-welcome.png"
                width={260}
                height={310}
                alt="Smart Travel Assistant"
              />
              <span className="trip-assistant-ground" aria-hidden="true" />
            </div>
          </aside>
        </div>
      )}
    </section>
  );
}
