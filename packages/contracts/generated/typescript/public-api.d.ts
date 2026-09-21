/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source:    packages/contracts/openapi/public-api.yaml
 * Regenerate: cd packages/contracts && npm run generate
 *
 * Editing this file by hand makes the generated client disagree with the contract, which is the
 * exact failure this pipeline exists to prevent.
 */

export interface paths {
    "/api/v1/alert-subscriptions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Opt in to live alerts for a trip
         * @description Requires an active `ALERT_NOTIFICATION` consent, whose id is recorded on the
         *     subscription; revoking that consent cancels it.
         */
        post: operations["createAlertSubscription"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alert-subscriptions/{subscription_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                subscription_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Opt out of live alerts
         * @description Cancels the subscription and stops delivery immediately. The delivery log is retained for
         *     audit; only future notifications are affected.
         */
        delete: operations["deleteAlertSubscription"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/consents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Grant or revoke a consent
         * @description Appends a consent decision against a specific policy version. Revoking writes a new
         *     record rather than deleting the old one, so what was agreed and when stays auditable.
         *     Revoking `LOCATION_LIVE` also cancels any subscription that depends on it.
         */
        post: operations["recordConsent"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List the caller's recent assistant threads
         * @description Powers the recent-chats panel. Summaries only: message bodies are fetched per thread, so
         *     the list view never carries the full transcript.
         */
        get: operations["listConversations"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/conversations/{conversation_id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                conversation_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Ask a follow-up question
         * @description Continues an existing thread and starts a new run. The thread keeps its id, but evidence
         *     is not reused past its freshness window: a question about current conditions triggers a
         *     fresh fetch. The question text is untrusted input and is never treated as an instruction.
         */
        post: operations["postConversationMessage"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/emergency/contacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Verified emergency numbers for a location
         * @description Returns reviewed, dated numbers for the country or subdivision containing the point.
         *     Numbers are never inferred from a neighbouring country and never produced by a language
         *     model. When the directory has no current entry for that country the response is an empty
         *     list with an explicit limitation, so the UI shows "not available" instead of a number
         *     that might not answer.
         *
         *     Coordinates are rounded to the configured precision before use and are not written to
         *     access logs.
         */
        get: operations["getEmergencyContacts"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/emergency/nearby": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Nearby hospitals, police stations or embassies
         * @description Looks up facilities through the configured places provider. Requires an active location
         *     consent (`LOCATION_ONCE` or `LOCATION_LIVE`); without one the request is refused rather
         *     than served from a cached position.
         */
        get: operations["getEmergencyNearby"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit explicit feedback on a recommendation
         * @description Explicit feedback is stored apart from behavioural telemetry. `UNSAFE` opens a safety
         *     review record. Nothing here changes a model or a threshold at runtime.
         */
        post: operations["createFeedback"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/locations/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search places with a real geocoding provider
         * @description Proxies to the external-data service, which calls the configured geocoding provider.
         *     The API never talks to a provider directly and never accepts a provider URL from the
         *     client. Results carry the provider that produced them; the user must still confirm the
         *     pin before the location can be used in an assessment.
         *
         *     When no geocoding provider is configured or reachable, this returns 503 with
         *     `DEPENDENCY_UNAVAILABLE` rather than an empty list, so the UI can distinguish
         *     "nothing matched" from "search is down".
         */
        get: operations["searchLocations"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get the caller's profile and consent summary
         * @description Resolves the OIDC subject to an internal user, creating the profile on first sight.
         *     The emergency profile is not included here: it is fetched separately so that the
         *     common path never decrypts medical data.
         */
        get: operations["getMe"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update locale, timezone or home country
         * @description Changes presentation preferences only. Identity itself lives in Keycloak and is not
         *     editable here, and consent is recorded through `/api/v1/consents` so that each decision
         *     keeps its own policy version.
         */
        patch: operations["updateMe"];
        trace?: never;
    };
    "/api/v1/me/emergency-profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read the caller's emergency profile
         * @description Decrypts and returns the profile to its owner only. Requires an active
         *     `EMERGENCY_PROFILE` consent; if that consent was revoked the stored payload is
         *     retained under the retention policy but is not returned.
         */
        get: operations["getEmergencyProfile"];
        /**
         * Create or replace the caller's emergency profile
         * @description Replaces the whole profile. The payload is sealed with the current application key
         *     version before it reaches the database, and never appears in logs, metrics or traces.
         */
        put: operations["putEmergencyProfile"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/recommendations/{recommendation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                recommendation_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        /**
         * Get a finished assessment result
         * @description The API revalidates the stored response against the contract schema before returning it.
         *     A result that no longer validates is reported as an error rather than rendered, because a
         *     malformed safety answer is worse than a missing one.
         */
        get: operations["getRecommendation"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{request_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: components["parameters"]["RequestIdPath"];
            };
            cookie?: never;
        };
        /**
         * Poll an assessment run
         * @description The fallback for clients that cannot hold an SSE connection open.
         */
        get: operations["getRun"];
        put?: never;
        post?: never;
        /**
         * Cancel an assessment run
         * @description Propagates cancellation to the agent and downstream services. The audit trail of what
         *     already ran is kept; only the work still outstanding is abandoned.
         */
        delete: operations["cancelRun"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/runs/{request_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                request_id: components["parameters"]["RequestIdPath"];
            };
            cookie?: never;
        };
        /**
         * Follow an assessment run over SSE
         * @description Server-sent events for one run. Ownership is checked before the stream opens.
         *
         *     Each event has a monotonic `id`; a client that reconnects with `Last-Event-ID` resumes
         *     after the last event it saw, so a dropped connection never loses the terminal event.
         *     `heartbeat` keeps intermediaries from closing an idle stream. The server closes the
         *     stream after `run.completed`, `run.failed` or cancellation.
         *
         *     Event names and payloads:
         *
         *     | event | payload |
         *     | --- | --- |
         *     | `run.accepted` | `SseRunAccepted` |
         *     | `run.progress` | `SseRunProgress` |
         *     | `run.needs_input` | `SseRunNeedsInput` |
         *     | `run.degraded` | `SseRunDegraded` |
         *     | `run.completed` | `SseRunCompleted` |
         *     | `run.failed` | `SseRunFailed` |
         *     | `heartbeat` | `SseHeartbeat` |
         *
         *     No event carries a raw provider body, a prompt, chain-of-thought, an access token or
         *     personal data. The number of concurrent streams per user and per IP is capped.
         */
        get: operations["streamRunEvents"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/safety/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Hazards inside a viewport for the safety map
         * @description Serves the map layers. The bounding box and time window are bounded server-side so a
         *     client cannot ask for the whole planet; oversized requests are rejected rather than
         *     truncated silently.
         */
        get: operations["listSafetyEvents"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trips": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List the caller's trips
         * @description Every query is filtered by the owner resolved from the token, at the repository layer
         *     rather than in the handler, so an ownership check can never be forgotten. Soft-deleted
         *     trips are excluded unless `status=DELETED` is requested explicitly.
         */
        get: operations["listTrips"];
        put?: never;
        /**
         * Create a trip
         * @description Both endpoints must be confirmed locations. Departure time is validated against the
         *     configured backdating allowance and the travel modes against provider coverage for the
         *     region: a mode with no real data source is rejected here rather than silently assessed.
         */
        post: operations["createTrip"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trips/{trip_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                trip_id: components["parameters"]["TripId"];
            };
            cookie?: never;
        };
        /**
         * Get one trip
         * @description Returns the trip with an `ETag` carrying its revision. Clients send that value back in
         *     `If-Match` when updating.
         */
        get: operations["getTrip"];
        put?: never;
        post?: never;
        /**
         * Soft-delete a trip
         * @description Marks the trip deleted immediately and schedules the purge of its child data. The
         *     response reports the deletion status so the UI can tell the user that removal is in
         *     progress rather than implying it already finished everywhere.
         */
        delete: operations["deleteTrip"];
        options?: never;
        head?: never;
        /**
         * Update a trip
         * @description Requires `If-Match` with the revision the client last read. A stale revision is rejected
         *     with 412 so that a second tab cannot overwrite a change it never saw. Changing anything
         *     that affects the journey invalidates the current assessment: the client must start a new
         *     one rather than keep showing the old result.
         */
        patch: operations["updateTrip"];
        trace?: never;
    };
    "/api/v1/trips/{trip_id}/apply-route": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                trip_id: components["parameters"]["TripId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Apply a route to the trip
         * @description Records the chosen route on a new trip revision, keeps the previous selection for audit,
         *     and starts a fresh assessment — the old score is never carried over to a changed journey.
         *
         *     A route the server knows to be closed is refused even when the client sends an
         *     acknowledgement: accepting a risky-but-open route is the user's call, entering a closed
         *     one is not.
         */
        post: operations["applyRoute"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trips/{trip_id}/assessments": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                trip_id: components["parameters"]["TripId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Start a safety assessment for this trip
         * @description Accepts the work and returns immediately: the assessment itself runs asynchronously and
         *     is followed over SSE or by polling. The request row is committed before the agent is
         *     called, so a run is never lost because a downstream call failed.
         *
         *     `Idempotency-Key` is strongly recommended. The same key with the same payload returns the
         *     original run; the same key with a different payload is `IDEMPOTENCY_CONFLICT`.
         */
        post: operations["createAssessment"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Process liveness
         * @description True whenever the process itself is running. It deliberately touches no dependency:
         *     a database outage must not restart a healthy container.
         */
        get: operations["healthLive"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Dependency readiness
         * @description Checks the dependencies this service cannot serve traffic without — PostgreSQL, Redis and
         *     the OIDC discovery document — each under a short bounded timeout. Returns 503 when any
         *     required dependency is down, so the container is taken out of rotation instead of
         *     answering requests it cannot honour. Optional dependencies are reported but do not fail
         *     readiness.
         */
        get: operations["healthReady"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * ActionCode
         * @description The only four actions the product may recommend. Locked by the decision engine before any LLM call.
         * @enum {string}
         */
        ActionCode: "NORMAL" | "CHANGE_ROUTE" | "DELAY" | "AVOID";
        /**
         * AlertSubscription
         * @description An opt-in to be told when a trip's situation materially changes. Every subscription points at the consent that authorises it; revoking that consent cancels the subscription. A cooldown suppresses repeat notifications, but a higher severity always breaks through.
         */
        AlertSubscription: {
            cancelled_at?: components["schemas"]["NullableTimestamp"];
            channel: components["schemas"]["DeliveryChannel"];
            consent_id: components["schemas"]["Uuid"];
            cooldown_until?: components["schemas"]["NullableTimestamp"];
            created_at: components["schemas"]["Timestamp"];
            expires_at?: components["schemas"]["NullableTimestamp"];
            /** @description Lowest severity that may notify this subscriber. */
            min_severity?: components["schemas"]["Severity"];
            status: components["schemas"]["SubscriptionStatus"];
            subscription_id: components["schemas"]["Uuid"];
            trip_id: components["schemas"]["Uuid"];
        };
        AlertSubscriptionResponse: {
            data: components["schemas"]["AlertSubscription"];
            meta: components["schemas"]["ResponseMeta"];
        };
        ApplyRouteRequest: {
            /** @description The recommendation the route was offered in, so the choice is auditable. */
            recommendation_id: components["schemas"]["Uuid"];
            /**
             * @description Required when the chosen route is MEDIUM or HIGH. Records that the traveller was
             *     shown the risk and accepted it. It never overrides a closure.
             * @default false
             */
            risk_acknowledged?: boolean;
            route_id: components["schemas"]["RecordId"];
        };
        ApplyRouteResponse: {
            data: {
                run: components["schemas"]["RunRef"];
                trip: components["schemas"]["Trip"];
            };
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * Citation
         * @description Every factual claim in the summary must be covered by one of these. Citations are produced from retrieved evidence and provenance records, never written by the language model.
         */
        Citation: {
            authority?: components["schemas"]["SourceAuthority"];
            evidence_id?: components["schemas"]["Uuid"] | null;
            observed_at?: components["schemas"]["NullableTimestamp"];
            source_id: components["schemas"]["RecordId"];
            source_url: components["schemas"]["HttpsUrl"];
            title: string;
        };
        /**
         * ConsentRecord
         * @description One versioned consent decision. Consent is append-only: revoking writes revoked_at rather than deleting the row, so that what the user agreed to and when stays auditable.
         */
        ConsentRecord: {
            consent_id: components["schemas"]["Uuid"];
            /** @description Set for scoped grants such as LOCATION_ONCE and for live-location sessions. */
            expires_at?: components["schemas"]["NullableTimestamp"];
            granted: boolean;
            granted_at: components["schemas"]["Timestamp"];
            /** @description Version of the consent text the user was shown. */
            policy_version: components["schemas"]["SemVer"];
            revoked_at?: components["schemas"]["NullableTimestamp"];
            type: components["schemas"]["ConsentType"];
        };
        ConsentRequest: {
            /**
             * @description Requested expiry for a scoped grant such as a live-location session. The server caps
             *     it at the configured maximum.
             */
            expires_at?: components["schemas"]["NullableTimestamp"];
            granted: boolean;
            policy_version: components["schemas"]["SemVer"];
            type: components["schemas"]["ConsentType"];
        };
        ConsentResponse: {
            data: components["schemas"]["ConsentRecord"];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * ConsentType
         * @enum {string}
         */
        ConsentType: "LOCATION_ONCE" | "LOCATION_LIVE" | "ALERT_NOTIFICATION" | "ANALYTICS" | "EMERGENCY_PROFILE";
        /**
         * ContentHash
         * @description Digest of the payload a record was derived from, prefixed with the algorithm that produced it. The prefix is the point: a bare hex string is ambiguous the moment a second algorithm is introduced, and an unprefixed value silently compares unequal to a prefixed one rather than failing. Used for deduplication and for detecting provider schema drift.
         */
        ContentHash: string;
        /**
         * Conversation
         * @description A thread of assistant turns about a trip. Continuing a conversation reuses its id but never reuses stale evidence: a follow-up that asks about current conditions triggers a fresh assessment when the previous one is past its freshness window.
         */
        Conversation: {
            conversation_id: components["schemas"]["Uuid"];
            created_at: components["schemas"]["Timestamp"];
            last_message_preview?: string | null;
            last_recommendation_id?: components["schemas"]["Uuid"] | null;
            message_count: number;
            /** @description Short label derived from the first question, for the recent-chats list. */
            title?: string | null;
            trip_id?: components["schemas"]["Uuid"] | null;
            updated_at: components["schemas"]["Timestamp"];
        };
        ConversationListResponse: {
            data: components["schemas"]["Conversation"][];
            meta: components["schemas"]["ResponseMeta"];
            page: components["schemas"]["PageMeta"];
        };
        ConversationMessageRequest: {
            locale?: components["schemas"]["Locale"];
            question: string;
            /** @description Trip this question is about, when the thread is not already bound to one. */
            trip_id?: components["schemas"]["Uuid"] | null;
        };
        /**
         * CountryCode
         * @description ISO-3166-1 alpha-2, uppercase.
         */
        CountryCode: string;
        CreateAlertSubscriptionRequest: {
            channel: components["schemas"]["DeliveryChannel"];
            consent_id: components["schemas"]["Uuid"];
            min_severity?: components["schemas"]["Severity"];
            trip_id: components["schemas"]["Uuid"];
        };
        /**
         * @description Everything here is optional: the journey itself comes from the stored trip, so a client
         *     cannot assess one trip while claiming another.
         */
        CreateAssessmentRequest: {
            /**
             * @description Areas the traveller asked to avoid, drawn on the safety map. Advisory input to route
             *     evaluation, not a way to hide an official warning.
             */
            avoid_areas?: components["schemas"]["Polygon"][];
            /** @description Continue an existing thread instead of starting a new one. */
            conversation_id?: components["schemas"]["Uuid"] | null;
            live_location_consent_id?: components["schemas"]["Uuid"] | null;
            locale?: components["schemas"]["Locale"];
            question?: string | null;
        };
        CreateTripRequest: {
            departure_time: components["schemas"]["Timestamp"];
            destination: components["schemas"]["LocationRef"];
            origin: components["schemas"]["LocationRef"];
            preferences?: components["schemas"]["TravelPreference"];
            return_time?: components["schemas"]["NullableTimestamp"];
            timezone: components["schemas"]["Timezone"];
            title?: string | null;
            travel_modes: components["schemas"]["TravelMode"][];
        };
        /**
         * DataQuality
         * @description Quality envelope attached to every canonical record. The score never replaces the flags: a consumer that reads score alone and ignores flags is non-conforming. score is nullable, and a null score is not a quality problem — it means no agreed formula has been applied yet. A producer must leave it null rather than invent a number, because a fabricated score is indistinguishable from a measured one once it is downstream.
         */
        DataQuality: {
            /** @description Share of required fields the provider supplied. */
            completeness?: components["schemas"]["UnitInterval"] | null;
            /**
             * @description Conflicting values seen for the same fact across sources.
             * @default []
             */
            conflicts?: components["schemas"]["QualityConflict"][];
            /** @description Share of the requested area and time window the source actually covers. */
            coverage?: components["schemas"]["UnitInterval"] | null;
            /** @default [] */
            flags: components["schemas"]["QualityFlag"][];
            /** @description Age of the underlying observation at generation time. Null when the source publishes no observation time. */
            freshness_seconds?: number | null;
            /** @default [] */
            notes?: string[];
            /** @description Weighted quality score. Null until a producer applies an agreed formula; never a placeholder. */
            score: components["schemas"]["UnitInterval"] | null;
            /** @description Version of the scoring formula and weights that produced `score` — not a revision counter for the value itself. Required whenever `score` is non-null, and null alongside a null score: a number that cannot be attributed to a formula cannot be compared across time. */
            score_version: components["schemas"]["SemVer"] | null;
            status: components["schemas"]["DataStatus"];
        } & unknown;
        /**
         * DataStatus
         * @enum {string}
         */
        DataStatus: "FRESH" | "STALE" | "UNAVAILABLE" | "CONFLICTING" | "PARTIAL";
        /** DecisionReason */
        DecisionReason: {
            code: components["schemas"]["RiskReasonCode"];
            severity?: components["schemas"]["Severity"];
            /** @default [] */
            source_ids?: components["schemas"]["RecordId"][];
            text: string;
        };
        /**
         * DegradationReason
         * @enum {string}
         */
        DegradationReason: "TIMEOUT" | "UNAVAILABLE" | "RATE_LIMITED" | "STALE_DATA" | "PARTIAL_COVERAGE" | "NOT_CONFIGURED" | "SCHEMA_MISMATCH";
        /** DegradedService */
        DegradedService: {
            reason: components["schemas"]["DegradationReason"];
            /** @default false */
            retrying?: boolean;
            service: string;
            since?: components["schemas"]["NullableTimestamp"];
        };
        /**
         * DeletionStatus
         * @description Reported by soft-delete endpoints; purge happens asynchronously across owned schemas.
         * @enum {string}
         */
        DeletionStatus: "PENDING" | "IN_PROGRESS" | "COMPLETED" | "FAILED";
        DeletionStatusResponse: {
            data: {
                completed_at?: components["schemas"]["NullableTimestamp"];
                requested_at: components["schemas"]["Timestamp"];
                resource_id: components["schemas"]["Uuid"];
                status: components["schemas"]["DeletionStatus"];
            };
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * DeliveryChannel
         * @enum {string}
         */
        DeliveryChannel: "IN_APP" | "EMAIL" | "SMS" | "PUSH";
        /**
         * DisasterEvent
         * @description A hazard published by a real feed. An OfficialAlert is the same shape with official = true and an authority of OFFICIAL or INTERGOVERNMENTAL; an active official alert is never dropped because a different provider stopped answering.
         */
        DisasterEvent: {
            /**
             * @description True when the alert itself declares a route, airport or corridor closed.
             * @default false
             */
            closes_transport?: boolean;
            /** @description Hypocentre depth in kilometres, where the hazard type has one. A shallow earthquake and a deep one of equal magnitude do very different things at the surface, so the depth is part of the evidence rather than a detail. May be negative: USGS reports hypocentres above the sea-level reference (for example -3.48 km in mountain regions; 289 of 10,642 events in one month), and dropping them would lose real evidence. -15 km leaves a wide margin below the shallowest observed value. There is no upper bound, because deep subduction earthquakes reach about 700 km. */
            depth_km?: number | null;
            /** @description Provider text. Untrusted: sanitised before display and never treated as an instruction to the system. */
            description: string | null;
            effective_at: components["schemas"]["NullableTimestamp"];
            ends_at: components["schemas"]["NullableTimestamp"];
            event_id: components["schemas"]["RecordId"];
            event_type: components["schemas"]["DisasterEventType"];
            geometry: components["schemas"]["Geometry"];
            /** @description Protective action text as published by the issuing authority, verbatim. */
            instruction: string | null;
            /** @description Provider's own magnitude number, carried through rather than interpreted. Meaningless on its own: it must be read together with magnitude_unit, because 5.8 Mw and 5.8 mb are different measurements of different things. */
            magnitude?: number | null;
            /** @description Scale the magnitude is expressed on, as the provider names it — Mw, mb, Ms, ml for earthquakes, or a provider-specific scale for other hazards. Required whenever magnitude is non-null: a bare number invites a consumer to compare two scales as though they were one, and for a hazard that is a safety error, not a rounding one. */
            magnitude_unit?: string | null;
            /** @description True when the issuing body is a government or intergovernmental authority. */
            official: boolean;
            quality: components["schemas"]["DataQuality"];
            severity: components["schemas"]["Severity"];
            source: components["schemas"]["SourceProvenance"];
            title: string;
        } & unknown;
        /**
         * DisasterEventType
         * @enum {string}
         */
        DisasterEventType: "EARTHQUAKE" | "CYCLONE" | "STORM" | "FLOOD" | "WILDFIRE" | "VOLCANO" | "LANDSLIDE" | "EXTREME_TEMPERATURE" | "HEALTH" | "TRANSPORT_CLOSURE" | "OTHER";
        /** EmergencyContactPerson */
        EmergencyContactPerson: {
            locale?: components["schemas"]["Locale"] | null;
            name: string;
            /** @description E.164 where possible. Redacted from logs. */
            phone: string;
            relationship?: string | null;
        };
        /**
         * EmergencyInstruction
         * @description Protective guidance quoted from an approved document, with its citation. Never generated free-hand.
         */
        EmergencyInstruction: {
            citation?: components["schemas"]["Citation"];
            evidence_id: components["schemas"]["Uuid"];
            hazard_type?: components["schemas"]["DisasterEventType"] | null;
            text: string;
        };
        /**
         * EmergencyPoi
         * @description A nearby hospital, police station or embassy returned by a licensed places provider. A POI is a navigation aid, not a verified phone directory: any number shown here is the provider's and is labelled as such, while dialable emergency numbers come from OfficialContact.
         */
        EmergencyPoi: {
            address?: string | null;
            /** @description Straight-line metres from the query point, not travel distance — there may be no road. Null when the provider did not give one, rather than zero, which would read as 'you are here'. */
            distance_m: number | null;
            location: components["schemas"]["Point"];
            /** @description Null when the provider has no name for the place. OpenStreetMap leaves roughly one emergency POI in ten untagged, including real hospitals; the shared context calls this data 'frequently stale or missing'. The two alternatives were both worse: dropping the record hides the nearest hospital from somebody who needs it, and synthesising 'Unnamed hospital' puts words in the provider's mouth inside a data field. A consumer renders the type and the distance, and says the name is unknown. */
            name: string | null;
            /** @description Null unless the provider supplies opening hours; unknown is not open. */
            open_now?: boolean | null;
            /** @description As published by the places provider. Never presented as an official emergency number. */
            phone?: string | null;
            poi_id: components["schemas"]["RecordId"];
            /**
             * @description OTHER is the required escape hatch: a provider category this contract does not model is mapped to OTHER and kept, never discarded and never guessed into a neighbouring type. provider_category, where a producer supplies it, records what the provider actually said.
             * @enum {string}
             */
            poi_type: "HOSPITAL" | "CLINIC" | "DOCTOR" | "PHARMACY" | "POLICE" | "FIRE_STATION" | "EMBASSY" | "CONSULATE" | "TOWNHALL" | "SHELTER" | "OTHER";
            quality: components["schemas"]["DataQuality"];
            source: components["schemas"]["SourceProvenance"];
        };
        EmergencyPoiListResponse: {
            data: components["schemas"]["EmergencyPoi"][];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * EmergencyProfile
         * @description Medical and next-of-kin details the traveller chooses to store for an emergency. Stored encrypted at the application layer under a key that does not live in the same database; returned only to its owner, never logged, never traced, never sent to an LLM.
         */
        EmergencyProfile: {
            /** @default [] */
            allergies?: string[];
            /** @enum {string|null} */
            blood_type?: "A+" | "A-" | "B+" | "B-" | "AB+" | "AB-" | "O+" | "O-" | "UNKNOWN" | null;
            /** @default [] */
            contacts?: components["schemas"]["EmergencyContactPerson"][];
            insurance?: components["schemas"]["InsuranceRef"] | null;
            /** @description Encryption key version the stored payload was sealed with. Echoed so that key rotation is auditable; the key itself is never exposed. */
            key_version?: string | null;
            /** @description Free text. Redacted from every log, metric and trace. */
            medical_notes?: string | null;
            /** @default [] */
            medications?: string[];
            updated_at: components["schemas"]["Timestamp"];
        };
        EmergencyProfileResponse: {
            data: components["schemas"]["EmergencyProfile"];
            meta: components["schemas"]["ResponseMeta"];
        };
        EmergencyProfileUpsertRequest: {
            allergies?: string[];
            /** @enum {string|null} */
            blood_type?: "A+" | "A-" | "B+" | "B-" | "AB+" | "AB-" | "O+" | "O-" | "UNKNOWN" | null;
            contacts?: components["schemas"]["EmergencyContactPerson"][];
            insurance?: components["schemas"]["InsuranceRef"] | null;
            medical_notes?: string | null;
            medications?: string[];
        };
        /**
         * EmergencyServiceType
         * @enum {string}
         */
        EmergencyServiceType: "GENERAL_EMERGENCY" | "POLICE" | "AMBULANCE" | "FIRE" | "TOURIST_POLICE" | "COAST_GUARD" | "POISON_CONTROL" | "EMBASSY" | "HOSPITAL" | "DISASTER_HOTLINE";
        /** ErrorBody */
        ErrorBody: {
            code: components["schemas"]["ErrorCode"];
            /** @default [] */
            field_errors?: components["schemas"]["FieldError"][];
            /** @description Human-readable and safe to display. Never carries a stack trace, SQL, provider credential or internal host name. */
            message: string;
            retry_after_seconds?: number | null;
            retryable: boolean;
        };
        /**
         * ErrorCode
         * @description Stable error codes. Adding a member is a minor contract change; removing or renaming one is breaking.
         * @enum {string}
         */
        ErrorCode: "VALIDATION_ERROR" | "AUTHENTICATION_REQUIRED" | "FORBIDDEN" | "NOT_FOUND" | "CONFLICT" | "IDEMPOTENCY_CONFLICT" | "RATE_LIMITED" | "DEPENDENCY_TIMEOUT" | "DEPENDENCY_UNAVAILABLE" | "INSUFFICIENT_EVIDENCE" | "UNSUPPORTED_COVERAGE" | "POLICY_VALIDATION_FAILED" | "INTERNAL_ERROR";
        /** ErrorResponse */
        ErrorResponse: {
            error: components["schemas"]["ErrorBody"];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * FeedbackCategory
         * @enum {string}
         */
        FeedbackCategory: "HELPFUL" | "INCORRECT" | "STALE" | "UNSAFE" | "ROUTE_ISSUE" | "SOURCE_ISSUE" | "OTHER";
        /**
         * FeedbackEvent
         * @description Explicit feedback on a recommendation, kept separate from behavioural telemetry. UNSAFE feedback opens a safety review record; nothing here retrains a model automatically.
         */
        FeedbackEvent: {
            category: components["schemas"]["FeedbackCategory"];
            created_at: components["schemas"]["Timestamp"];
            feedback_id: components["schemas"]["Uuid"];
            recommendation_id: components["schemas"]["Uuid"];
            /** @enum {string} */
            review_status: "NEW" | "TRIAGED" | "IN_REVIEW" | "RESOLVED" | "DISMISSED";
            /** @description Set when the category is UNSAFE and a safety review record was created. */
            safety_review_id?: components["schemas"]["Uuid"] | null;
            /** @description Free text after redaction of phone numbers, e-mail addresses and precise coordinates. */
            text_redacted?: string | null;
        };
        FeedbackRequest: {
            category: components["schemas"]["FeedbackCategory"];
            recommendation_id: components["schemas"]["Uuid"];
            /**
             * @description Free text. Redacted for phone numbers, e-mail addresses and precise coordinates
             *     before storage.
             */
            text?: string | null;
        };
        FeedbackResponse: {
            data: components["schemas"]["FeedbackEvent"];
            meta: components["schemas"]["ResponseMeta"];
        };
        /** FieldError */
        FieldError: {
            /** @enum {string} */
            code: "REQUIRED" | "INVALID_FORMAT" | "OUT_OF_RANGE" | "TOO_LONG" | "TOO_SHORT" | "UNKNOWN_FIELD" | "UNSUPPORTED_VALUE" | "NOT_CONFIRMED" | "INCONSISTENT";
            /** @description Optional user-safe detail. Never echoes a rejected value that is itself sensitive. */
            message?: string | null;
            /** @description Dotted or indexed path into the rejected request, for example destination.coordinates. */
            path: string;
        };
        /** Freshness */
        Freshness: {
            expires_at?: components["schemas"]["NullableTimestamp"];
            fetched_at: components["schemas"]["Timestamp"];
            /** @description Oldest observation time behind this answer, or null when no source publishes one. */
            observed_at?: components["schemas"]["NullableTimestamp"];
        };
        /**
         * GeoJsonGeometry
         * @description Any geometry a hazard, corridor or route may carry.
         */
        Geometry: components["schemas"]["Point"] | components["schemas"]["LineString"] | components["schemas"]["Polygon"] | components["schemas"]["MultiPolygon"];
        HealthLiveResponse: {
            service: string;
            /** @enum {string} */
            status: "alive";
            version: string;
        };
        HealthReadyResponse: {
            checked_at: components["schemas"]["Timestamp"];
            checks: {
                /** @description Short, user-safe reason. Never a connection string or credential. */
                detail?: string | null;
                duration_ms: number;
                /** @description Dependency key, for example postgres, redis, oidc, agent. */
                name: string;
                /** @description Whether a failure here makes the service unready. */
                required: boolean;
                /** @enum {string} */
                status: "up" | "down" | "degraded" | "skipped";
            }[];
            /** @enum {string} */
            status: "ready" | "not_ready";
        };
        /**
         * HeartbeatEvent
         * @description Keeps intermediaries from closing an idle stream. Never rendered.
         */
        Heartbeat: {
            server_time: components["schemas"]["Timestamp"];
        };
        /**
         * HttpsUrl
         * Format: uri
         */
        HttpsUrl: string;
        /** ImmediateAction */
        ImmediateAction: {
            evidence_id?: components["schemas"]["Uuid"] | null;
            /** @default 5 */
            priority?: number;
            text: string;
        };
        /** InsuranceRef */
        InsuranceRef: {
            emergency_phone?: string | null;
            policy_reference?: string | null;
            provider_name: string;
        };
        /** Limitation */
        Limitation: {
            /** @enum {string} */
            code: "NO_RELIABLE_KNOWLEDGE_EVIDENCE" | "PARTIAL_PROVIDER_COVERAGE" | "STALE_EVIDENCE_USED" | "NO_ROUTE_ALTERNATIVE_AVAILABLE" | "MODE_NOT_SUPPORTED_IN_REGION" | "FORECAST_HORIZON_EXCEEDED" | "MODEL_UNAVAILABLE_CONSERVATIVE_RESULT" | "EXPLANATION_FALLBACK_TEMPLATE" | "CONFLICTING_SOURCES";
            text?: string | null;
        };
        /** GeoJsonLineString */
        LineString: {
            coordinates: components["schemas"]["Position"][];
            /** @constant */
            type: "LineString";
        };
        /**
         * Locale
         * @description BCP-47 language tag, e.g. th-TH or en-GB.
         */
        Locale: string;
        /**
         * LocationRef
         * @description A place resolved by a real geocoding provider. An assessment may only be started when both origin and destination have confirmed_by_user = true. Exact coordinates are personal data: keep them only as long as the trip and consent require, and never write them to logs or traces.
         */
        LocationRef: {
            /** @description First-level administrative area as the provider names it. */
            admin1?: string | null;
            /** @description True once the user has seen the pin on the map and accepted it. */
            confirmed_by_user: boolean;
            coordinates: components["schemas"]["Point"];
            country_code?: components["schemas"]["CountryCode"] | null;
            display_name: string;
            /** @description Provider-scoped place identifier. Null when the user dropped a pin instead of choosing a suggestion. */
            place_id?: string | null;
            /** @description Geocoding provider key, or user_pin when the coordinates came from the map rather than a provider. */
            provider: string;
            timezone?: components["schemas"]["Timezone"] | null;
        };
        LocationSearchResponse: {
            data: components["schemas"]["LocationRef"][];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * MessageKey
         * @description i18n key the web app resolves. Servers never send pre-translated progress copy.
         */
        MessageKey: string;
        /** GeoJsonMultiPolygon */
        MultiPolygon: {
            coordinates: components["schemas"]["Position"][][][];
            /** @constant */
            type: "MultiPolygon";
        };
        /**
         * NullableTimestamp
         * Format: date-time
         */
        NullableTimestamp: string | null;
        /**
         * OfficialContact
         * @description A verified emergency number for a specific country or subdivision. Numbers come from a reviewed directory with an effective and verified date, never from a language model and never from a neighbouring country as a fallback. A contact past its review date is withheld and the caller shows an unavailable state.
         */
        OfficialContact: {
            authority: components["schemas"]["SourceAuthority"];
            contact_id: components["schemas"]["Uuid"];
            country_code: components["schemas"]["CountryCode"];
            effective_at: components["schemas"]["Timestamp"];
            /** @description Display name in the requested locale, for example Tourist Police. */
            label: string;
            /** @default [] */
            languages?: components["schemas"]["Locale"][];
            /** @description Dialable string as published by the authority, including short codes. */
            phone: string;
            review_due_at?: components["schemas"]["NullableTimestamp"];
            service_type: components["schemas"]["EmergencyServiceType"];
            source_url: components["schemas"]["HttpsUrl"];
            /** @description ISO-3166-2 subdivision code when the number is regional rather than national. */
            subdivision?: string | null;
            verified_at: components["schemas"]["Timestamp"];
        };
        OfficialContactListResponse: {
            data: components["schemas"]["OfficialContact"][];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * PageMeta
         * @description Opaque cursor pagination. Cursors are server-generated and must not be parsed by clients.
         */
        PageMeta: {
            cursor: string | null;
            has_more: boolean;
            next_cursor: string | null;
        };
        /** GeoJsonPoint */
        Point: {
            coordinates: components["schemas"]["Position"];
            /** @constant */
            type: "Point";
        };
        /** GeoJsonPolygon */
        Polygon: {
            coordinates: components["schemas"]["Position"][][];
            /** @constant */
            type: "Polygon";
        };
        /**
         * Position
         * @description [longitude, latitude] in WGS84. RFC 7946 also permits an elevation element; this contract does not carry one, because nothing in the system consumes altitude and an optional third element would make every generated type ambiguous.
         */
        Position: [
            number,
            number
        ];
        /** QualityConflict */
        QualityConflict: {
            field_path: string;
            /** @enum {string|null} */
            resolution?: "HIGHEST_AUTHORITY" | "MOST_RECENT" | "MOST_CONSERVATIVE" | "UNRESOLVED" | null;
            source_ids: components["schemas"]["RecordId"][];
        };
        /**
         * QualityFlag
         * @enum {string}
         */
        QualityFlag: "MISSING" | "STALE" | "CONFLICTING" | "INFERRED" | "INCOMPLETE" | "OUTSIDE_COVERAGE";
        /**
         * RecommendationResponse
         * @description The object the web app renders. Every displayed fact carries its source and freshness; when a dependency could not be reached the response says so in degraded_services and limitations rather than filling the gap. The public API revalidates this against the schema before it reaches the browser.
         */
        RecommendationResponse: {
            action_code: components["schemas"]["ActionCode"];
            /**
             * @description Hazards and official alerts that intersect this journey.
             * @default []
             */
            alerts?: components["schemas"]["DisasterEvent"][];
            /** @default [] */
            alternatives?: components["schemas"]["RouteCandidate"][];
            confidence: components["schemas"]["UnitInterval"];
            conversation_id?: components["schemas"]["Uuid"] | null;
            created_at: components["schemas"]["Timestamp"];
            decision_id?: components["schemas"]["Uuid"] | null;
            degraded_services: components["schemas"]["DegradedService"][];
            /** @default [] */
            emergency_instructions?: components["schemas"]["EmergencyInstruction"][];
            /** @description After this instant the result must be re-assessed before being presented as current. */
            expires_at?: components["schemas"]["NullableTimestamp"];
            freshness: components["schemas"]["Freshness"];
            /** @default [] */
            immediate_actions?: components["schemas"]["ImmediateAction"][];
            limitations: components["schemas"]["Limitation"][];
            /** @default [] */
            official_contacts?: components["schemas"]["OfficialContact"][];
            primary_route?: components["schemas"]["RouteCandidate"] | null;
            reasons: components["schemas"]["DecisionReason"][];
            recommendation_id: components["schemas"]["Uuid"];
            request_id: components["schemas"]["Uuid"];
            risk_level: components["schemas"]["RiskLevel"];
            short_summary: string;
            snapshot_id?: components["schemas"]["Uuid"] | null;
            sources: components["schemas"]["SourceProvenance"][];
            /** @description COMPLETED or PARTIAL. A PARTIAL result is still safe to show but must be labelled as incomplete in the UI. */
            status: components["schemas"]["RunStatus"];
            trip_id: components["schemas"]["Uuid"];
            versions: components["schemas"]["ResponseVersions"];
        };
        RecommendationResponseEnvelope: {
            data: components["schemas"]["RecommendationResponse"];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * RecordId
         * @description Identifier of a record as the producer mints it. Stable and reproducible: fetching the same fact twice must yield the same RecordId, because that is what lets module 05 deduplicate across sources and what lets an operator trace one fact back through a log. A provider adapter therefore derives it from the provider key and the provider's own record id (for example `usgs:us7000abcd`), never from a random UUID, which would differ on every fetch and defeat both. A service that mints a record with no upstream identity may use a UUID here; the format is deliberately wide enough for both.
         */
        RecordId: string;
        /** ResponseMeta */
        ResponseMeta: {
            contract_version: components["schemas"]["SemVer"];
            correlation_id?: components["schemas"]["Uuid"] | null;
            /**
             * @description Dependencies that answered late, partially or not at all while producing this response.
             * @default []
             */
            degraded_services?: components["schemas"]["DegradedService"][];
            generated_at: components["schemas"]["Timestamp"];
            request_id: components["schemas"]["Uuid"];
        };
        /** ResponseVersions */
        ResponseVersions: {
            contract: components["schemas"]["SemVer"];
            knowledge_collection?: string | null;
            llm_model?: string | null;
            policy?: string | null;
            prompt?: string | null;
            risk_model?: string | null;
        };
        /**
         * RiskLevel
         * @enum {string}
         */
        RiskLevel: "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN";
        /**
         * RiskReasonCode
         * @enum {string}
         */
        RiskReasonCode: "SEVERE_WEATHER_CORRIDOR" | "HEAVY_PRECIPITATION" | "HIGH_WIND" | "LOW_VISIBILITY" | "SNOW_OR_ICE" | "EXTREME_TEMPERATURE" | "ACTIVE_DISASTER_ON_CORRIDOR" | "RECENT_EARTHQUAKE" | "FLOOD_RISK" | "WILDFIRE_SMOKE" | "OFFICIAL_CLOSURE" | "OFFICIAL_WARNING_ACTIVE" | "TRANSPORT_DISRUPTION" | "TRANSPORT_CANCELLED" | "NIGHT_TRAVEL" | "LONG_EXPOSURE_WINDOW" | "SPARSE_DATA_COVERAGE" | "STALE_EVIDENCE" | "CONFLICTING_EVIDENCE";
        /**
         * RouteCandidate
         * @description One way of making the journey, with the hazard exposure measured along its corridor rather than at the endpoints. A route whose corridor carries an official closure must have exposure.closed = true and can never be labelled RECOMMENDED. A raw route straight from a routing provider carries exposure: null and risk_level: UNKNOWN until modules 05/06 evaluate it; the two are bound together so an unevaluated route cannot be mistaken for a safe one.
         */
        RouteCandidate: {
            distance_m: number;
            duration_seconds: number;
            /** @description Null until a route has been evaluated against hazards and weather. A routing provider knows road geometry and travel time and has no view on danger, so module 04 emits null here and modules 05/06 fill it in. Null does NOT mean 'no exposure': an unevaluated route must never be rendered as safe, which is why the schema requires risk_level to be UNKNOWN whenever this is null. */
            exposure: components["schemas"]["RouteExposure"] | null;
            geometry: components["schemas"]["LineString"];
            label: components["schemas"]["RouteLabel"];
            mode: components["schemas"]["TravelMode"];
            /** @description Opaque provider handle, kept so the same route can be re-fetched or audited. */
            provider_route_id?: string | null;
            quality: components["schemas"]["DataQuality"];
            risk_level: components["schemas"]["RiskLevel"];
            /** @description Reproducible on purpose: asking for the same route twice must yield the same value, so a route served from cache and one fetched fresh are recognisably the same route rather than two. A provider adapter derives it from the provider key and a fingerprint of the question (waypoints, mode, preference). Same reasoning as source_id and event_id. */
            route_id: components["schemas"]["RecordId"];
            /** @default [] */
            segments?: components["schemas"]["RouteSegment"][];
            /** @description Plural, unlike the singular `source` on records that come from exactly one provider. A route survives stitching: module 05 joins legs from different providers into one itinerary, and each leg's provenance has to survive that join. A single-provider route sends a one-element array. */
            sources: components["schemas"]["SourceProvenance"][];
            transfers?: number | null;
        } & unknown;
        /**
         * RouteExposure
         * @description What this route is exposed to along its corridor within the travel window.
         */
        RouteExposure: {
            /** @description True when an official closure covers part of this route. */
            closed: boolean;
            /** @default [] */
            closure_source_ids?: components["schemas"]["RecordId"][];
            /** @default [] */
            hazard_event_ids?: components["schemas"]["Uuid"][];
            score: components["schemas"]["UnitInterval"];
            /** @default [] */
            weather_window_ids?: components["schemas"]["Uuid"][];
        };
        /**
         * RouteLabel
         * @enum {string}
         */
        RouteLabel: "ORIGINAL" | "RECOMMENDED" | "FASTEST" | "LOWEST_RISK" | "ALTERNATIVE";
        /** RouteSegment */
        RouteSegment: {
            arrival_time?: components["schemas"]["NullableTimestamp"];
            departure_time?: components["schemas"]["NullableTimestamp"];
            distance_m: number;
            duration_seconds: number;
            from_name?: string | null;
            geometry?: components["schemas"]["LineString"] | null;
            mode: components["schemas"]["TravelMode"];
            /** @description Reproducible within its route, for the same reason as route_id. */
            segment_id: components["schemas"]["RecordId"];
            to_name?: string | null;
            transport_status_id?: components["schemas"]["Uuid"] | null;
        };
        /** RunAcceptedEvent */
        RunAccepted: {
            request_id: components["schemas"]["Uuid"];
            status: components["schemas"]["RunStatus"];
            submitted_at: components["schemas"]["Timestamp"];
        };
        /** RunCompletedEvent */
        RunCompleted: {
            recommendation_id: components["schemas"]["Uuid"];
            request_id: components["schemas"]["Uuid"];
            result_url: string;
            status: components["schemas"]["RunStatus"];
        };
        /** RunDegradedEvent */
        RunDegraded: {
            reason: components["schemas"]["DegradationReason"];
            request_id: components["schemas"]["Uuid"];
            retrying: boolean;
            service: string;
        };
        /** RunFailedEvent */
        RunFailed: {
            error: components["schemas"]["ErrorBody"];
            request_id: components["schemas"]["Uuid"];
        };
        /** RunNeedsInputEvent */
        RunNeedsInput: {
            missing_fields: string[];
            prompt_key: components["schemas"]["MessageKey"];
            request_id: components["schemas"]["Uuid"];
        };
        /** RunProgressEvent */
        RunProgress: {
            message_key: components["schemas"]["MessageKey"];
            occurred_at?: components["schemas"]["Timestamp"];
            /** @description Null whenever remaining work cannot be estimated honestly. */
            percent?: number | null;
            request_id: components["schemas"]["Uuid"];
            stage: components["schemas"]["RunStage"];
        };
        /**
         * RunRef
         * @description Returned by every endpoint that starts asynchronous work. The caller follows the run over SSE and falls back to polling; the assessment itself never blocks the HTTP request that started it.
         */
        RunRef: {
            conversation_id?: components["schemas"]["Uuid"] | null;
            /** @description Relative URL of the SSE stream for this run. */
            events_url: string;
            /** @description Relative URL of the polling endpoint for this run. */
            poll_url: string;
            request_id: components["schemas"]["Uuid"];
            status: components["schemas"]["RunStatus"];
            submitted_at: components["schemas"]["Timestamp"];
            trip_id?: components["schemas"]["Uuid"] | null;
        };
        RunRefResponse: {
            data: components["schemas"]["RunRef"];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * RunStage
         * @description Controlled progress stages surfaced over SSE (00_API_AND_DATA_CONTRACTS.md section 6).
         * @enum {string}
         */
        RunStage: "VALIDATING" | "FETCHING_EXTERNAL_DATA" | "INTEGRATING_DATA" | "ASSESSING_RISK" | "RETRIEVING_GUIDANCE" | "EVALUATING_ROUTES" | "MAKING_DECISION" | "EXPLAINING" | "FORMATTING_RESPONSE";
        /**
         * RunState
         * @description Pollable state of an assessment run. It reports progress and where the result will appear; it never exposes the agent's reasoning, prompts or raw provider payloads.
         */
        RunState: {
            completed_at?: components["schemas"]["NullableTimestamp"];
            conversation_id?: components["schemas"]["Uuid"] | null;
            /** @default [] */
            degraded_services?: components["schemas"]["DegradedService"][];
            error?: components["schemas"]["ErrorBody"] | null;
            message_key?: components["schemas"]["MessageKey"] | null;
            /**
             * @description Populated when status is NEEDS_INPUT. The system asks rather than guessing.
             * @default []
             */
            missing_fields?: string[];
            /** @description Null whenever the remaining work cannot be estimated honestly. */
            percent?: number | null;
            recommendation_id?: components["schemas"]["Uuid"] | null;
            request_id: components["schemas"]["Uuid"];
            result_url?: string | null;
            stage?: components["schemas"]["RunStage"] | null;
            status: components["schemas"]["RunStatus"];
            submitted_at: components["schemas"]["Timestamp"];
            trip_id?: components["schemas"]["Uuid"] | null;
            updated_at: components["schemas"]["Timestamp"];
        };
        RunStateResponse: {
            data: components["schemas"]["RunState"];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * RunStatus
         * @enum {string}
         */
        RunStatus: "QUEUED" | "RUNNING" | "NEEDS_INPUT" | "COMPLETED" | "PARTIAL" | "FAILED" | "CANCELLED";
        /**
         * SafetyEvent
         * @description Map-sized summary of one hazard for the safety map. It is a projection of a canonical DisasterEvent or weather window: enough to draw a marker and open a detail panel, with the freshness the UI is required to show, and never a substitute for the full record.
         */
        SafetyEvent: {
            /** @description Relative public API path for the full canonical record. */
            detail_url?: string | null;
            event_id: components["schemas"]["RecordId"];
            event_type: components["schemas"]["DisasterEventType"];
            geometry: components["schemas"]["Geometry"];
            layer: components["schemas"]["SafetyLayer"];
            official: boolean;
            quality: components["schemas"]["DataQuality"];
            severity: components["schemas"]["Severity"];
            source: components["schemas"]["SourceProvenance"];
            title: string;
            valid_from: components["schemas"]["NullableTimestamp"];
            valid_to: components["schemas"]["NullableTimestamp"];
        };
        SafetyEventListResponse: {
            data: components["schemas"]["SafetyEvent"][];
            meta: components["schemas"]["ResponseMeta"];
            page: components["schemas"]["PageMeta"];
        };
        /**
         * SafetyLayer
         * @description Layers requestable from the public safety map endpoint.
         * @enum {string}
         */
        SafetyLayer: "WEATHER" | "DISASTER" | "TRANSPORT" | "OFFICIAL_ALERT";
        /** SemVer */
        SemVer: string;
        /**
         * Severity
         * @enum {string}
         */
        Severity: "INFO" | "MINOR" | "MODERATE" | "SEVERE" | "EXTREME" | "UNKNOWN";
        /**
         * SourceAuthority
         * @enum {string}
         */
        SourceAuthority: "OFFICIAL" | "INTERGOVERNMENTAL" | "LICENSED_PROVIDER" | "COMMUNITY" | "UNKNOWN";
        /**
         * SourceProvenance
         * @description Every fact that can influence a decision must resolve back to one of these. When a provider publishes no observation time, observed_at is null and the record carries a quality flag; fetched_at is never presented as an observation time.
         */
        SourceProvenance: {
            /** @description Attribution text that must be displayed wherever this source is shown. */
            attribution?: string | null;
            authority: components["schemas"]["SourceAuthority"];
            /** @description Digest of the upstream payload this record was derived from, so provider schema drift is detectable rather than silent. Null when the adapter had no raw payload to hash, which is the case for a record assembled from several responses. */
            content_hash: components["schemas"]["ContentHash"] | null;
            expires_at?: components["schemas"]["NullableTimestamp"];
            fetched_at: components["schemas"]["Timestamp"];
            /** @description Licence or terms identifier the provider publishes under. */
            license?: string | null;
            observed_at?: components["schemas"]["NullableTimestamp"];
            /** @description Stable provider key from the provider catalogue, for example open_meteo, usgs, gdacs, openrouteservice. */
            provider: string;
            /** @description Provider-scoped identifier for the record, for example a USGS event id. */
            provider_record_id?: string | null;
            published_at?: components["schemas"]["NullableTimestamp"];
            schema_version: components["schemas"]["SemVer"];
            /** @description Stable identifier for this source record. Reproducible on purpose: fetching the same fact twice must produce the same value, because deduplication in module 05 and tracing one fact through a log both depend on it. A random UUID per fetch would defeat both. */
            source_id: components["schemas"]["RecordId"];
            /** @description Canonical URL for the record, or the request URL the adapter used. Null only when the provider publishes neither — a bulk feed with no per-record address, for example. */
            source_url: components["schemas"]["HttpsUrl"] | null;
        };
        SseHeartbeat: components["schemas"]["Heartbeat"];
        SseRunAccepted: components["schemas"]["RunAccepted"];
        SseRunCompleted: components["schemas"]["RunCompleted"];
        SseRunDegraded: components["schemas"]["RunDegraded"];
        SseRunFailed: components["schemas"]["RunFailed"];
        SseRunNeedsInput: components["schemas"]["RunNeedsInput"];
        SseRunProgress: components["schemas"]["RunProgress"];
        /**
         * SubscriptionStatus
         * @enum {string}
         */
        SubscriptionStatus: "ACTIVE" | "PAUSED" | "CANCELLED" | "EXPIRED";
        /**
         * Timestamp
         * Format: date-time
         * @description ISO-8601 instant with an explicit offset, e.g. 2026-09-17T08:30:00Z.
         */
        Timestamp: string;
        /**
         * Timezone
         * @description IANA time zone identifier, e.g. Asia/Bangkok. Validated against the tz database at the boundary, not by pattern alone.
         */
        Timezone: string;
        /**
         * TravelMode
         * @enum {string}
         */
        TravelMode: "FLIGHT" | "TRAIN" | "BUS" | "CAR" | "WALK" | "BICYCLE" | "MULTIMODAL";
        /**
         * TravelPreference
         * @description User routing preferences. Preferences never weaken a safety decision: they rank acceptable options, they do not make an unacceptable option acceptable.
         */
        TravelPreference: {
            /** @default [] */
            accessibility?: ("STEP_FREE" | "WHEELCHAIR" | "LOW_FLOOR_VEHICLE" | "AVOID_STAIRS" | "ASSISTANCE_REQUIRED" | "VISUAL_IMPAIRMENT" | "HEARING_IMPAIRMENT")[];
            /** @default false */
            avoid_tolls?: boolean;
            /**
             * @description How much extra travel time the user will accept for a safer route.
             * @default 90
             */
            max_extra_duration_minutes?: number | null;
            /** @default false */
            prefer_lower_cost?: boolean;
            /** @default false */
            prefer_lower_emissions?: boolean;
            /** @default true */
            prefer_safer_route?: boolean;
        };
        /**
         * Trip
         * @description A traveller's saved journey. revision backs optimistic concurrency: every mutation increments it and PATCH requires a matching If-Match header, so two tabs cannot silently overwrite each other.
         */
        Trip: {
            created_at: components["schemas"]["Timestamp"];
            /** @description Set by soft delete. Purge of the underlying rows happens asynchronously under the retention policy. */
            deleted_at?: components["schemas"]["NullableTimestamp"];
            departure_time: components["schemas"]["Timestamp"];
            destination: components["schemas"]["LocationRef"];
            /** @description Most recent assessment started for this trip revision. */
            latest_request_id?: components["schemas"]["Uuid"] | null;
            origin: components["schemas"]["LocationRef"];
            preferences?: components["schemas"]["TravelPreference"];
            /** @description The route this trip had applied before the current one, kept so a reassessment can say what changed. Same type as selected_route_id for the same reason. */
            previous_selected_route_id?: components["schemas"]["RecordId"] | null;
            return_time?: components["schemas"]["NullableTimestamp"];
            /** @description Monotonic revision counter, also served as the ETag. */
            revision: number;
            /** @description Route the traveller applied. Set only by apply-route, never by the client directly. A RecordId rather than a Uuid because it holds a RouteCandidate.route_id, and those are producer-minted and reproducible (`openrouteservice:3ca4459b8d41b503`) so that the same route asked for twice is recognisably the same route. */
            selected_route_id?: components["schemas"]["RecordId"] | null;
            status: components["schemas"]["TripStatus"];
            timezone: components["schemas"]["Timezone"];
            title?: string | null;
            travel_modes: components["schemas"]["TravelMode"][];
            trip_id: components["schemas"]["Uuid"];
            updated_at: components["schemas"]["Timestamp"];
        };
        TripListResponse: {
            data: components["schemas"]["Trip"][];
            meta: components["schemas"]["ResponseMeta"];
            page: components["schemas"]["PageMeta"];
        };
        TripResponse: {
            data: components["schemas"]["Trip"];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * TripStatus
         * @enum {string}
         */
        TripStatus: "DRAFT" | "PLANNED" | "ACTIVE" | "COMPLETED" | "CANCELLED" | "DELETED";
        /**
         * UnitInterval
         * @description Normalised score in [0, 1].
         */
        UnitInterval: number;
        UpdateProfileRequest: {
            home_country_code?: components["schemas"]["CountryCode"] | null;
            locale?: components["schemas"]["Locale"];
            timezone?: components["schemas"]["Timezone"];
        };
        /** @description Only the supplied fields change. Every change increments the trip revision. */
        UpdateTripRequest: {
            departure_time?: components["schemas"]["Timestamp"];
            destination?: components["schemas"]["LocationRef"];
            origin?: components["schemas"]["LocationRef"];
            preferences?: components["schemas"]["TravelPreference"];
            return_time?: components["schemas"]["NullableTimestamp"];
            status?: components["schemas"]["TripStatus"];
            timezone?: components["schemas"]["Timezone"];
            title?: string | null;
            travel_modes?: components["schemas"]["TravelMode"][];
        };
        /**
         * UserProfile
         * @description The caller's own profile. user_id is an internal UUID; the OIDC subject is never exposed to the browser and email is never a primary key.
         */
        UserProfile: {
            /** @description Current effective consent state, one entry per ConsentType the user has ever acted on. */
            consents: components["schemas"]["ConsentRecord"][];
            created_at: components["schemas"]["Timestamp"];
            deleted_at?: components["schemas"]["NullableTimestamp"];
            /** @description Name taken from the identity provider, shown only back to the owner. */
            display_name?: string | null;
            /**
             * @description Whether an encrypted emergency profile exists. The profile content itself is never included here.
             * @default false
             */
            has_emergency_profile?: boolean;
            home_country_code?: components["schemas"]["CountryCode"] | null;
            locale: components["schemas"]["Locale"];
            timezone: components["schemas"]["Timezone"];
            updated_at: components["schemas"]["Timestamp"];
            user_id: components["schemas"]["Uuid"];
        };
        UserProfileResponse: {
            data: components["schemas"]["UserProfile"];
            meta: components["schemas"]["ResponseMeta"];
        };
        /**
         * Uuid
         * Format: uuid
         * @description UUID, serialised in lowercase canonical form. Expressed as `format: uuid` alone rather than as a pattern as well: generators map the format onto a real UUID type whose canonical serialisation is already lowercase, whereas a pattern beside it forces the value back to a bare string.
         */
        Uuid: string;
    };
    responses: {
        /** @description A dependency did not answer inside its timeout budget. */
        DependencyTimeout: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
        /**
         * @description A dependency this operation needs is unavailable. The response says which capability is
         *     degraded; it never substitutes a plausible value for missing data.
         */
        DependencyUnavailable: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
        /** @description Authenticated, but not permitted — typically a missing consent or scope. */
        Forbidden: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
        /** @description The idempotency key was reused with a different payload. */
        IdempotencyConflict: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
        /**
         * @description No such resource for this caller. Resources owned by another user are reported as not
         *     found rather than forbidden, so that ids cannot be probed.
         */
        NotFound: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
        /** @description The `If-Match` revision is stale. Re-read the resource and retry. */
        PreconditionFailed: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
        /** @description `If-Match` is required for this operation and was not supplied. */
        PreconditionRequired: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
        /** @description Rate limit exceeded for this user, IP or endpoint bucket. */
        RateLimited: {
            headers: {
                /** @description Seconds to wait before retrying. */
                "Retry-After"?: number;
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
        /** @description No token, or a token that failed verification. */
        Unauthorized: {
            headers: {
                "WWW-Authenticate"?: string;
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
        /** @description The request failed validation. `field_errors` names each rejected path. */
        ValidationError: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/json": components["schemas"]["ErrorResponse"];
            };
        };
    };
    parameters: {
        /** @description Major contract version the client was built against. Currently `1`. */
        ContractVersion: string;
        /** @description Opaque cursor from a previous page. Not to be constructed by the client. */
        Cursor: string;
        /**
         * @description Client-generated key that makes a retry safe. The same key with the same payload returns
         *     the original result; the same key with a different payload is rejected with
         *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
         */
        IdempotencyKey: string;
        /** @description The ETag (trip revision) the client last read. */
        IfMatch: string;
        Latitude: number;
        Limit: number;
        Longitude: number;
        /**
         * @description Client-supplied correlation handle. The server generates one when absent and always
         *     echoes the value it used in `meta.request_id`.
         */
        RequestId: components["schemas"]["Uuid"];
        RequestIdPath: components["schemas"]["Uuid"];
        TripId: components["schemas"]["Uuid"];
    };
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    createAlertSubscription: {
        parameters: {
            query?: never;
            header?: {
                /**
                 * @description Client-generated key that makes a retry safe. The same key with the same payload returns
                 *     the original result; the same key with a different payload is rejected with
                 *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateAlertSubscriptionRequest"];
            };
        };
        responses: {
            /** @description Subscription created. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AlertSubscriptionResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            /** @description The required consent is missing or revoked. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            409: components["responses"]["IdempotencyConflict"];
        };
    };
    deleteAlertSubscription: {
        parameters: {
            query?: never;
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                subscription_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Subscription cancelled. Delivery stops immediately. */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
        };
    };
    recordConsent: {
        parameters: {
            query?: never;
            header?: {
                /**
                 * @description Client-generated key that makes a retry safe. The same key with the same payload returns
                 *     the original result; the same key with a different payload is rejected with
                 *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConsentRequest"];
            };
        };
        responses: {
            /** @description Consent recorded. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConsentResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            409: components["responses"]["IdempotencyConflict"];
            429: components["responses"]["RateLimited"];
        };
    };
    listConversations: {
        parameters: {
            query?: {
                /** @description Opaque cursor from a previous page. Not to be constructed by the client. */
                cursor?: components["parameters"]["Cursor"];
                limit?: components["parameters"]["Limit"];
            };
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Conversations, most recently updated first. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConversationListResponse"];
                };
            };
            401: components["responses"]["Unauthorized"];
        };
    };
    postConversationMessage: {
        parameters: {
            query?: never;
            header?: {
                /**
                 * @description Client-generated key that makes a retry safe. The same key with the same payload returns
                 *     the original result; the same key with a different payload is rejected with
                 *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                conversation_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConversationMessageRequest"];
            };
        };
        responses: {
            /** @description Follow-up accepted. */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRefResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["IdempotencyConflict"];
            429: components["responses"]["RateLimited"];
        };
    };
    getEmergencyContacts: {
        parameters: {
            query: {
                lat: components["parameters"]["Latitude"];
                locale?: components["schemas"]["Locale"];
                lon: components["parameters"]["Longitude"];
            };
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /**
             * @description Verified contacts. An empty list means the directory has no current entry for that
             *     country, which the client must show as unavailable.
             */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OfficialContactListResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            503: components["responses"]["DependencyUnavailable"];
        };
    };
    getEmergencyNearby: {
        parameters: {
            query: {
                lat: components["parameters"]["Latitude"];
                limit?: components["parameters"]["Limit"];
                lon: components["parameters"]["Longitude"];
                radius_m?: number;
                type: "HOSPITAL" | "CLINIC" | "PHARMACY" | "POLICE" | "FIRE_STATION" | "EMBASSY" | "CONSULATE" | "SHELTER";
            };
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Facilities found, nearest first. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmergencyPoiListResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            /** @description No active location consent. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            503: components["responses"]["DependencyUnavailable"];
        };
    };
    createFeedback: {
        parameters: {
            query?: never;
            header?: {
                /**
                 * @description Client-generated key that makes a retry safe. The same key with the same payload returns
                 *     the original result; the same key with a different payload is rejected with
                 *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FeedbackRequest"];
            };
        };
        responses: {
            /** @description Feedback stored. */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FeedbackResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["IdempotencyConflict"];
        };
    };
    searchLocations: {
        parameters: {
            query: {
                country_code?: components["schemas"]["CountryCode"];
                limit?: number;
                /** @description Preferred result language. Defaults to the caller's profile locale. */
                locale?: components["schemas"]["Locale"];
                /** @description Free-text place query. */
                q: string;
            };
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Matching places, best first. An empty list means the provider matched nothing. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LocationSearchResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            429: components["responses"]["RateLimited"];
            503: components["responses"]["DependencyUnavailable"];
            504: components["responses"]["DependencyTimeout"];
        };
    };
    getMe: {
        parameters: {
            query?: never;
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The caller's profile. */
            200: {
                headers: {
                    /** @description Always `private, no-store`. This response is never shared across users. */
                    "Cache-Control"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserProfileResponse"];
                };
            };
            401: components["responses"]["Unauthorized"];
            429: components["responses"]["RateLimited"];
            503: components["responses"]["DependencyUnavailable"];
        };
    };
    updateMe: {
        parameters: {
            query?: never;
            header?: {
                /**
                 * @description Client-generated key that makes a retry safe. The same key with the same payload returns
                 *     the original result; the same key with a different payload is rejected with
                 *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateProfileRequest"];
            };
        };
        responses: {
            /** @description Updated profile. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserProfileResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            409: components["responses"]["IdempotencyConflict"];
            429: components["responses"]["RateLimited"];
        };
    };
    getEmergencyProfile: {
        parameters: {
            query?: never;
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The decrypted profile. */
            200: {
                headers: {
                    /** @description Always `private, no-store`. */
                    "Cache-Control"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmergencyProfileResponse"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    putEmergencyProfile: {
        parameters: {
            query?: never;
            header?: {
                /**
                 * @description Client-generated key that makes a retry safe. The same key with the same payload returns
                 *     the original result; the same key with a different payload is rejected with
                 *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EmergencyProfileUpsertRequest"];
            };
        };
        responses: {
            /** @description Stored profile. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EmergencyProfileResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            /** @description `EMERGENCY_PROFILE` consent has not been granted. The profile is not stored. */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            409: components["responses"]["IdempotencyConflict"];
        };
    };
    getRecommendation: {
        parameters: {
            query?: never;
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                recommendation_id: components["schemas"]["Uuid"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The recommendation. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationResponseEnvelope"];
                };
            };
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            /** @description The stored response failed contract validation and was withheld. */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    getRun: {
        parameters: {
            query?: never;
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                request_id: components["parameters"]["RequestIdPath"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Current run state. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunStateResponse"];
                };
            };
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
        };
    };
    cancelRun: {
        parameters: {
            query?: never;
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                request_id: components["parameters"]["RequestIdPath"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Cancellation recorded. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunStateResponse"];
                };
            };
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            /** @description The run already reached a terminal state. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    streamRunEvents: {
        parameters: {
            query?: never;
            header?: {
                /** @description Resume point from a previous connection. */
                "Last-Event-ID"?: string;
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
            };
            path: {
                request_id: components["parameters"]["RequestIdPath"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /**
             * @description An open `text/event-stream`. Sent with `Cache-Control: no-cache` and
             *     `X-Accel-Buffering: no` so no proxy buffers the progress events.
             */
            200: {
                headers: {
                    "Cache-Control"?: string;
                    "X-Accel-Buffering"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "text/event-stream": string;
                };
            };
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            /** @description Too many concurrent streams for this user or IP. */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listSafetyEvents: {
        parameters: {
            query: {
                /** @description Instant to evaluate, defaulting to now. Drives the Now / +6h / +12h switch. */
                at?: components["schemas"]["Timestamp"];
                /** @description `west,south,east,north` in degrees. Maximum span is configured server-side. */
                bbox: string;
                /** @description Layers to include. All layers when omitted. */
                layers?: components["schemas"]["SafetyLayer"][];
                limit?: components["parameters"]["Limit"];
            };
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Hazards intersecting the viewport and instant. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SafetyEventListResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            429: components["responses"]["RateLimited"];
            503: components["responses"]["DependencyUnavailable"];
        };
    };
    listTrips: {
        parameters: {
            query?: {
                /** @description Opaque cursor from a previous page. Not to be constructed by the client. */
                cursor?: components["parameters"]["Cursor"];
                limit?: components["parameters"]["Limit"];
                status?: components["schemas"]["TripStatus"];
            };
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Trips owned by the caller, newest departure first. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TripListResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
        };
    };
    createTrip: {
        parameters: {
            query?: never;
            header?: {
                /**
                 * @description Client-generated key that makes a retry safe. The same key with the same payload returns
                 *     the original result; the same key with a different payload is rejected with
                 *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateTripRequest"];
            };
        };
        responses: {
            /** @description Trip created at revision 1. */
            201: {
                headers: {
                    /** @description Weak ETag carrying the trip revision, e.g. `W/"1"`. */
                    ETag?: string;
                    Location?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TripResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            409: components["responses"]["IdempotencyConflict"];
            /**
             * @description The request is well-formed but cannot be served: for example a travel mode with no
             *     provider coverage in that region (`UNSUPPORTED_COVERAGE`).
             */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            429: components["responses"]["RateLimited"];
        };
    };
    getTrip: {
        parameters: {
            query?: never;
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                trip_id: components["parameters"]["TripId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The trip. */
            200: {
                headers: {
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TripResponse"];
                };
            };
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
        };
    };
    deleteTrip: {
        parameters: {
            query?: never;
            header?: {
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                trip_id: components["parameters"]["TripId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Deletion accepted, with its current status. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeletionStatusResponse"];
                };
            };
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
        };
    };
    updateTrip: {
        parameters: {
            query?: never;
            header: {
                /** @description The ETag (trip revision) the client last read. */
                "If-Match": components["parameters"]["IfMatch"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                trip_id: components["parameters"]["TripId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateTripRequest"];
            };
        };
        responses: {
            /** @description Updated trip at the next revision. */
            200: {
                headers: {
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TripResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            412: components["responses"]["PreconditionFailed"];
            428: components["responses"]["PreconditionRequired"];
        };
    };
    applyRoute: {
        parameters: {
            query?: never;
            header: {
                /**
                 * @description Client-generated key that makes a retry safe. The same key with the same payload returns
                 *     the original result; the same key with a different payload is rejected with
                 *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
                /** @description The ETag (trip revision) the client last read. */
                "If-Match": components["parameters"]["IfMatch"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                trip_id: components["parameters"]["TripId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApplyRouteRequest"];
            };
        };
        responses: {
            /** @description Route applied; a new assessment was started for the new revision. */
            202: {
                headers: {
                    ETag?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplyRouteResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["IdempotencyConflict"];
            412: components["responses"]["PreconditionFailed"];
            /**
             * @description The route is closed by an official source, or the acknowledgement required for a
             *     MEDIUM/HIGH route is missing (`POLICY_VALIDATION_FAILED`).
             */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    createAssessment: {
        parameters: {
            query?: never;
            header?: {
                /**
                 * @description Client-generated key that makes a retry safe. The same key with the same payload returns
                 *     the original result; the same key with a different payload is rejected with
                 *     `IDEMPOTENCY_CONFLICT`. Keys expire after the configured retention window.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
                /** @description Major contract version the client was built against. Currently `1`. */
                "X-Contract-Version"?: components["parameters"]["ContractVersion"];
                /**
                 * @description Client-supplied correlation handle. The server generates one when absent and always
                 *     echoes the value it used in `meta.request_id`.
                 */
                "X-Request-ID"?: components["parameters"]["RequestId"];
            };
            path: {
                trip_id: components["parameters"]["TripId"];
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["CreateAssessmentRequest"];
            };
        };
        responses: {
            /** @description Run accepted. */
            202: {
                headers: {
                    /** @description Polling URL for the run. */
                    Location?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunRefResponse"];
                };
            };
            400: components["responses"]["ValidationError"];
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["IdempotencyConflict"];
            /**
             * @description The trip cannot be assessed as it stands — for example an endpoint the user never
             *     confirmed, or a mode without coverage.
             */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            429: components["responses"]["RateLimited"];
            503: components["responses"]["DependencyUnavailable"];
        };
    };
    healthLive: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Process is alive. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthLiveResponse"];
                };
            };
        };
    };
    healthReady: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description All required dependencies are reachable. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthReadyResponse"];
                };
            };
            /** @description At least one required dependency is unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthReadyResponse"];
                };
            };
        };
    };
}
