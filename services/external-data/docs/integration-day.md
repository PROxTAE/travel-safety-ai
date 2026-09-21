# Integration day — module 04

What to run, what it should say, and what to do when it does not.

Runbook § 7 asks for a live call to every enabled provider with named evidence
per provider. `scripts/acceptance_canary.py` does exactly that table and writes
a report you can attach to the acceptance record.

## The one command

```bash
cd services/external-data
uv run python scripts/acceptance_canary.py --out evidence.md
```

Exit code 0 means every provider that should have answered did, and none of the
§ 7 expectations failed. Non-zero means read the report — it names what broke.

It takes about forty seconds. Eleven live calls, no retries added to flatter the
result: a provider having a bad afternoon shows up as a provider having a bad
afternoon, which is the point of running it on the day.

Set `ORS_API_KEY` if the demo machine has one. Without it, routing and emergency
places report themselves unavailable with the reason, and that is itself one of
the four things § 7 asks to see.

## What a good report looks like

```
Providers answering: 10/11  ·  records returned: 679  ·  problems found: 0

- PASS — every record carries provenance, freshness and quality
- PASS — no provider response is called current past its TTL
- PASS — unavailable credential or coverage returns an explicit state
- PASS — no key, token or personal data in this report
- PASS — every timestamp carries a timezone
- PASS — every record carries a licence
```

**10 of 11 is the healthy number**, not 11 of 11. The eleventh is the flight
provider, which is permanently unavailable: § 5 of the shared context forbids
serving its test environment as a real result and the project has no production
credential. The report states that reason rather than omitting the row, because
"we chose not to" and "it broke" need to look different.

## Numbers that look alarming and are not

**Most transit trips report `UNKNOWN`.** Roughly a third of live trips match a
published timetable; the rest are running trips with no scheduled counterpart,
so no delay can be measured. The report prints `matched to a timetable: 34/40`
for exactly this reason. Contract § 3.6 forbids inferring `ON_TIME` from the
absence of an alert, so an unmatched trip stays UNKNOWN.

**`severity` is `UNKNOWN` on every hazard, and `risk_level` on every route.**
That is the module working correctly. Turning a magnitude into a danger level is
module 06/07's judgement. The raw numbers are all there in `magnitude`,
`magnitude_unit`, `alert_level` and `depth_km`.

**`official` is false on most hazards.** It means a warning has actually been
issued, not that a government body published the record — decided in issue #32.
Expect roughly one in five, all of them GDACS Orange or Red.

**A POI with no name.** Two of nineteen real hospitals near Victory Monument
carry no name tag in OpenStreetMap, one of them 335 m away. The record is kept
and flagged rather than dropped, because hiding the nearest hospital from
someone who needs one is worse than showing an unnamed pin.

**Geocoding shows `freshness_s=None`.** A place name has no observation time.
The field is null rather than invented.

## If something fails

**A provider times out.** Run it again. The report is a snapshot of one moment
and third-party services have bad minutes; the retry and circuit breaker are
already doing their work underneath. If it fails twice, that is real — say so
rather than running until it passes.

**A record is past `expires_at` but still reports FRESH.** This is the check
worth taking seriously. It means something is serving a cached answer as current,
which is the failure the freshness rules exist to prevent.

**Routing or places are unavailable.** Check `ORS_API_KEY` is set. The free plan
allows 200 directions calls and 50 places calls per day, on separate budgets, so
a day of heavy rehearsal can exhaust it — `providers/health` reports the
remaining quota.

**Something looks like a credential in the output.** The report scans itself for
that and fails if it finds one. If it ever does, stop and tell whoever owns the
key before attaching the file anywhere.

## The scenario in § 13 that involves this module

Scenario 3 — *official closure or high alert forces `AVOID` even when the model
score is low*. What this module contributes is `official` and `alert_level` on
each hazard; the decision itself belongs to module 07.

If nothing with a high alert is happening anywhere in the world on the day, the
honest options are to demonstrate the scenario against a recorded event and
label it as historical, or to show that the rule fires by pointing at the
records the module is actually returning. Do not adjust provider data to force
the outcome — § 8 of the runbook says so and it is the one instruction here that
matters more than a tidy demo.

## Beyond the canary

```bash
uv run pytest                    # 645 tests, no network
uv run pytest -m canary          # 28 tests against live providers
curl localhost:8002/internal/v1/providers/health -H "Authorization: Bearer $TOKEN"
```

`providers/health` is the fastest way to answer "what actually works on this
machine". It reports per provider: registry status, effective status, last
observed health, remaining quota, and which credentials are missing by name.
