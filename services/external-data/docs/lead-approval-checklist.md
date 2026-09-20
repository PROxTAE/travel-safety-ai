# Team Lead approval checklist — module 04 providers

Phase 0 deliverable 2. Module 04 cannot approve its own providers or hold its own
credentials. This is the exact list of decisions that belong to the Team Lead,
with the consequence of each still being open.

`AI_EXECUTION_INSTRUCTIONS.md` is explicit that buying an API plan or using a
production secret is out of scope for the implementer, so none of the items below
were actioned — they are recorded, not decided.

## A. Provider approval

| # | Decision | Status | Blocks |
| --- | --- | --- | --- |
| A1 | Approve the five keyless providers (Open-Meteo ×2, USGS, GDACS, EONET) for MVP use | ⬜ | already marked `ACTIVE` — revoke here if not approved |
| A2 | Accept that Open-Meteo's free tier is **non-commercial**, or budget a paid plan | ⬜ | any non-demo use of the project |
| A3 | Approve openrouteservice as the routing + POI provider | ⬜ | Phase 4 |
| A4 | Decide whether flight search is in MVP scope at all | ⬜ | Phase 5 |
| A5 | Choose **one** GTFS-RT region for the demo and confirm its feed terms | ⬜ | Phase 5 — the plan requires at least one working region |

## B. Credentials

Nothing here is a request for the secret value. Module 04 needs an owner name and
the key present in the deployment `.env`; the value never enters the repository,
a log, a trace or a fixture.

| # | Credential | Env var | Owner | Status |
| --- | --- | --- | --- | --- |
| B1 | openrouteservice API key | `ORS_API_KEY` | **unassigned** | ⬜ absent → `ROUTE` and `EMERGENCY_DIRECTORY` unavailable |
| B2 | Amadeus production client | `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET` | **unassigned** | ⬜ absent → `FLIGHT` unavailable |
| B3 | Per-feed GTFS credentials, if the chosen agency requires them | per feed | **unassigned** | ⬜ |

A **production** Amadeus credential is required. The module plan states that test
data must never be served as a real result, so a test key does not unblock B2 — it
would only create the risk of shipping fake flights.

## C. Quota verification

Every `quota` block in `providers.yaml` is transcribed from public documentation
and carries `verification_required: true`. None has been confirmed against a live
account, because no account exists yet for the keyed providers.

| # | Task | Status |
| --- | --- | --- |
| C1 | Confirm the real Open-Meteo rate ceiling for our usage pattern | ⬜ |
| C2 | Confirm the openrouteservice plan's daily and per-minute limits | ⬜ |
| C3 | Confirm the Amadeus production tier limits | ⬜ |
| C4 | Record each chosen GTFS feed's minimum polling interval | ⬜ |

This matters beyond politeness: Phase 1's quota limiter is configured from these
numbers. Wrong numbers mean either throttling ourselves needlessly or getting the
team's account suspended mid-demo.

## D. Licence and attribution

| # | Task | Status |
| --- | --- | --- |
| D1 | Confirm attribution strings are acceptable and decide where they render | ⬜ (see `coverage-and-degraded-ux.md` U3) |
| D2 | Confirm the captured fixtures may be redistributed in a public repository | ⬜ |
| D3 | Confirm the default "do not persist raw provider bodies" retention stands | ⬜ |

On D2 — the five captured fixtures are public, keyless, non-personal payloads under
CC-BY-4.0, US public domain, NASA open data and GDACS terms, which is why capture
proceeded. It is still the Lead's call to confirm before the repository goes public.

## E. Cross-module sign-off

These are not the Lead's to decide alone, but the Lead should see them unblocked:

| # | Question | Owner | Detail |
| --- | --- | --- | --- |
| E1 | Canonical model questions Q1–Q6 | คน 5, คน 6 | [`canonical-field-mapping.md`](canonical-field-mapping.md) § 7 |
| E2 | Degraded-state UX questions U1–U3 | คน 1, คน 2 | [`coverage-and-degraded-ux.md`](coverage-and-degraded-ux.md) |

## Summary of what is blocked

- **Phase 2 and 3 can proceed now** — geocoding, weather and all three disaster
  sources are keyless and reachable.
- **Phase 4 is blocked** on B1 (and A3).
- **Phase 5 is blocked** on A4, A5, B2, B3.
- **Phases 2–3 are partly blocked on E1** — adapters can be written, but `severity`
  and `quality.score` stay `null` with a flag until Q2/Q3/Q5 are answered.
