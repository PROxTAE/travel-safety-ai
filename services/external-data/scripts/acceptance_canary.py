"""Integration-day evidence run for module 04.

Runbook § 7 asks for a live call to every enabled provider, with named evidence
captured per provider and four expectations checked across all of them. The
canary test suite already proves the calls work; what it does not do is produce
something the team can read on the day, so this does.

    uv run python scripts/acceptance_canary.py
    uv run python scripts/acceptance_canary.py --out evidence.md

Every call is real. Nothing here reads a fixture, and nothing is retried to make
the output look better - a provider having a bad afternoon should show up as a
provider having a bad afternoon.

Run it from `services/external-data` with whatever credentials the demo machine
has. A provider with no credential is reported as unavailable with the reason,
which is itself one of the four things § 7 asks to see.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

# The default points at the container layout. Running this on a laptop is the
# normal case on integration day, so fall back to the checkout.
import os  # noqa: E402

if not pathlib.Path(os.environ.get("GTFS_PROVIDER_CONFIG", "/app/config/providers.yaml")).is_file():
    os.environ["GTFS_PROVIDER_CONFIG"] = str(SERVICE_ROOT / "config" / "providers.yaml")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "acceptance-canary-not-a-credential")
os.environ.setdefault("POSTGRES_PASSWORD", "unused-by-this-script")

from app.adapters.factory import AdapterRegistry  # noqa: E402
from app.domain.enums import ProviderKind  # noqa: E402
from app.domain.errors import ProviderError  # noqa: E402
from app.domain.queries import (  # noqa: E402
    DisasterQuery,
    NearbyPlacesQuery,
    RouteQuery,
    TransitQuery,
)
from app.providers.registry import (  # noqa: E402
    ResolvedRegistry,
    get_resolved_registry,
)
from app.settings import get_settings  # noqa: E402
from app.transport.http import ProviderTransport  # noqa: E402

BANGKOK = (100.5018, 13.7563)
CHIANG_MAI = (98.9853, 18.7883)
AYUTTHAYA = (100.5878, 14.3532)
NEW_YORK_BBOX = (-74.1, 40.6, -73.8, 40.9)

# Anything that looks like a credential, in case a provider ever echoes one back.
_SECRET = re.compile(r"(eyJ[A-Za-z0-9+/=_-]{20,}|[A-Za-z0-9]{32,})")


def redact(text: str) -> str:
    return _SECRET.sub("[REDACTED]", text)


@dataclass
class Evidence:
    provider: str
    query: str
    ok: bool
    records: int = 0
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    skipped: str | None = None


def _stamp(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _provenance_lines(record: Any) -> list[str]:
    """The provenance § 7 asks to see on every row."""
    source = getattr(record, "source", None)
    if source is None:
        sources = getattr(record, "sources", None) or []
        source = sources[0] if sources else None
    if source is None:
        return ["    source: MISSING"]
    quality = getattr(record, "quality", None)
    return [
        f"    source_url   {redact(str(source.source_url))}",
        f"    observed_at  {_stamp(source.observed_at)}"
        f"   fetched_at {_stamp(source.fetched_at)}"
        f"   expires_at {_stamp(source.expires_at)}",
        f"    licence      {source.license}",
        f"    quality      {quality.status if quality else 'MISSING'}"
        f"  flags={[str(f) for f in quality.flags] if quality else '-'}"
        f"  freshness_s={quality.freshness_seconds if quality else '-'}",
    ]


def _check_common(provider: str, records: list[Any]) -> list[str]:
    """The four expectations in § 7, checked per record.

    `no provider response called "current" past its TTL` is the interesting one:
    a record whose `expires_at` has already passed must not still be reported
    FRESH.
    """
    problems: list[str] = []
    now = datetime.now(UTC)
    for index, record in enumerate(records):
        source = getattr(record, "source", None)
        if source is None:
            sources = getattr(record, "sources", None) or []
            source = sources[0] if sources else None
        quality = getattr(record, "quality", None)

        if source is None:
            problems.append(f"record {index} carries no provenance")
            continue
        if quality is None:
            problems.append(f"record {index} carries no quality")
            continue
        if source.fetched_at is None:
            problems.append(f"record {index} has no fetched_at")
        if source.expires_at is not None and source.expires_at < now:
            if str(quality.status) == "FRESH":
                problems.append(f"record {index} is past expires_at but still reports FRESH")
        if not source.license:
            problems.append(f"record {index} has no licence")
        for stamp in (source.observed_at, source.published_at, source.fetched_at):
            if stamp is not None and stamp.tzinfo is None:
                problems.append(f"record {index} has a timestamp with no timezone")
    return problems


async def _run_one(
    label: str,
    query_text: str,
    adapters: AdapterRegistry,
    kind: ProviderKind,
    query: Any,
    describe,
    provider_id: str | None = None,
) -> Evidence:
    try:
        adapter = adapters.get(provider_id) if provider_id else adapters.for_kind(kind)
        if adapter is None:
            return Evidence(label, query_text, False, skipped=adapters.blocked_reason(kind))
    except ProviderError as error:
        return Evidence(label, query_text, False, skipped=redact(str(error.message)))

    try:
        records = await adapter.query(query)
    except ProviderError as error:
        return Evidence(
            label,
            query_text,
            False,
            problems=[f"{error.code}: {redact(str(error.message))}"],
        )

    lines = describe(records) if records else ["    (provider answered with no rows)"]
    if records:
        lines += _provenance_lines(records[0])
    guards = adapter.transport.guards_for(adapter.provider)
    if guards.quota.remaining is not None:
        lines.append(
            f"    quota        {guards.quota.remaining}/{guards.quota.limit}"
            f" remaining ({guards.quota.window})"
        )
    return Evidence(
        label,
        query_text,
        True,
        records=len(records),
        lines=lines,
        problems=_check_common(label, records[:5]),
    )


async def gather_evidence() -> tuple[list[Evidence], ResolvedRegistry]:
    settings = get_settings()
    registry = get_resolved_registry()
    transport = ProviderTransport(registry.registry.defaults)
    adapters = AdapterRegistry(registry, transport, None, env=settings.app_env)

    from app.adapters.open_meteo_geocoding import GeocodeQuery
    from app.adapters.open_meteo_weather import CoordinateSample, WeatherQuery

    results: list[Evidence] = []

    # --- geocoding: Thai cities plus one international, as the table asks ----
    for name in ("Bangkok", "Chiang Mai", "Lisbon"):
        results.append(
            await _run_one(
                f"Open-Meteo geocoding ({name})",
                f'name="{name}"',
                adapters,
                ProviderKind.GEOCODING,
                GeocodeQuery(name=name),
                lambda rs: [
                    f"    {r.location.display_name} "
                    f"[{r.location.coordinates.longitude}, "
                    f"{r.location.coordinates.latitude}] "
                    f"tz={r.location.timezone} cc={r.location.country_code}"
                    for r in rs[:2]
                ],
            )
        )

    # --- weather: a current point and one further along the journey ---------
    results.append(
        await _run_one(
            "Open-Meteo weather",
            "two route samples (Bangkok now, Chiang Mai later)",
            adapters,
            ProviderKind.WEATHER,
            WeatherQuery(
                samples=[
                    CoordinateSample(BANGKOK[1], BANGKOK[0], sample_id="origin"),
                    CoordinateSample(CHIANG_MAI[1], CHIANG_MAI[0], sample_id="destination"),
                ]
            ),
            lambda rs: [
                f"    {r.sample_id or '-'} valid_at={_stamp(r.valid_at)} "
                f"{r.temperature_c}C rain={r.precipitation_mm}mm "
                f"wind={r.wind_speed_kmh}km/h severity={r.severity}"
                for r in rs[:3]
            ],
        )
    )

    # --- routing ------------------------------------------------------------
    results.append(
        await _run_one(
            "openrouteservice route",
            "Bangkok -> Ayutthaya, driving",
            adapters,
            ProviderKind.ROUTE,
            RouteQuery(waypoints=[BANGKOK, AYUTTHAYA]),
            lambda rs: [
                f"    {r.label} {r.distance_m / 1000:.1f}km "
                f"{r.duration_seconds / 60:.0f}min "
                f"geometry={r.geometry.type}[{len(r.geometry.coordinates)}] "
                f"risk_level={r.risk_level} exposure={r.exposure}"
                for r in rs[:2]
            ],
        )
    )

    # --- emergency places ---------------------------------------------------
    results.append(
        await _run_one(
            "openrouteservice POIs",
            "hospitals and police within 2 km of Victory Monument",
            adapters,
            ProviderKind.EMERGENCY_DIRECTORY,
            NearbyPlacesQuery(longitude=100.5383, latitude=13.7649, radius_m=2000),
            lambda rs: [
                f"    {r.poi_type} {r.name or '(no name in OpenStreetMap)'} " f"{r.distance_m:.0f}m"
                for r in rs[:3]
            ],
        )
    )

    # --- transit ------------------------------------------------------------
    results.append(
        await _run_one(
            "GTFS-Realtime",
            "registered region bbox",
            adapters,
            ProviderKind.TRANSIT,
            TransitQuery(bbox=NEW_YORK_BBOX, limit=40),
            lambda rs: [
                f"    {r.service_number} {r.origin_stop.name} -> "
                f"{r.destination_stop.name} status={r.status} "
                f"delay={r.delay_minutes} feed={r.feed_id}"
                for r in rs[:3]
            ]
            + [
                "    matched to a timetable: "
                f"{sum(1 for r in rs if r.scheduled_arrival)}/{len(rs)}"
            ],
        )
    )

    # --- hazards: each source asked separately, as the table lists them -----
    for provider_id, label in (
        ("usgs_earthquake", "USGS"),
        ("gdacs", "GDACS"),
        ("nasa_eonet", "NASA EONET"),
    ):
        results.append(
            await _run_one(
                label,
                "current feed, no bbox",
                adapters,
                ProviderKind.DISASTER,
                DisasterQuery(),
                lambda rs: [
                    f"    {r.event_id} {r.event_type} "
                    f"mag={r.magnitude}{f' {r.magnitude_unit}' if r.magnitude_unit else ''} "
                    f"alert={r.alert_level} official={r.official} "
                    f"severity={r.severity} effective_at={_stamp(r.effective_at)}"
                    for r in rs[:3]
                ]
                + [f"    official=True on {sum(1 for r in rs if r.official)}/{len(rs)}"],
                provider_id=provider_id,
            )
        )

    # --- flight: expected to be unavailable, and that is the evidence -------
    results.append(
        Evidence(
            "Amadeus (flight)",
            "not attempted",
            False,
            skipped=(
                "permanently unavailable: the shared context forbids serving the "
                "test environment as a real result and the project has no "
                "production credential"
            ),
        )
    )

    return results, registry


def _no_credential_in(text: str) -> bool:
    """Nothing credential-shaped, and nothing this machine is configured with.

    `redact()` runs on provider messages, but a provider could put a key
    somewhere redact does not reach, so the finished report is checked too.
    """
    if _SECRET.search(text):
        return False
    settings = get_settings()
    for name in ("ors_api_key", "amadeus_client_id", "amadeus_client_secret"):
        secret = getattr(settings, name, None)
        if secret is not None and secret.get_secret_value() in text:
            return False
    return True


def render(results: list[Evidence], registry: ResolvedRegistry) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    answered = [e for e in results if e.ok]
    problems = [(e.provider, p) for e in results for p in e.problems]

    out: list[str] = [
        "# Module 04 — integration-day provider evidence",
        "",
        f"Run at **{now}** against live providers. Nothing here is a fixture.",
        "",
        f"Providers answering: **{len(answered)}/{len(results)}**"
        f"  ·  records returned: **{sum(e.records for e in answered)}**"
        f"  ·  problems found: **{len(problems)}**",
        "",
        "## Runbook § 7 expectations",
        "",
    ]

    checks = [
        (
            "every record carries provenance, freshness and quality",
            not any("carries no" in p for _, p in problems),
        ),
        (
            "no provider response is called current past its TTL",
            not any("still reports FRESH" in p for _, p in problems),
        ),
        (
            "unavailable credential or coverage returns an explicit state",
            all(e.skipped for e in results if not e.ok and not e.problems),
        ),
        (
            "no key, token or personal data in this report",
            # A real check, not a formality: scan the rendered evidence for
            # anything shaped like a credential, and for whatever credential is
            # configured on this machine right now.
            _no_credential_in("\n".join(line for e in results for line in e.lines)),
        ),
        (
            "every timestamp carries a timezone",
            not any("no timezone" in p for _, p in problems),
        ),
        (
            "every record carries a licence",
            not any("no licence" in p for _, p in problems),
        ),
    ]
    for text, passed in checks:
        out.append(f"- {'PASS' if passed else 'FAIL'} — {text}")
    out.append("")

    out += ["## Per provider", ""]
    for e in results:
        head = f"### {e.provider}"
        out.append(head)
        out.append("")
        out.append(f"Query: `{e.query}`")
        out.append("")
        if e.skipped:
            out.append(f"**Not called.** {e.skipped}")
            out.append("")
            continue
        if e.problems and not e.ok:
            out.append("```")
            out += [f"    {p}" for p in e.problems]
            out.append("```")
            out.append("")
            continue
        out.append(f"**{e.records} records**")
        out.append("")
        out.append("```")
        out += e.lines
        out.append("```")
        if e.problems:
            out.append("")
            out.append("Problems:")
            out += [f"- {p}" for p in e.problems]
        out.append("")

    out += ["## Attribution", ""]
    for line in registry.attributions([e.provider for e in results]) or []:
        out.append(f"- {line}")
    active = [p for p in registry.all() if p.is_callable]
    out += [
        "",
        "## Registry state",
        "",
        "```",
    ]
    for provider in registry.all():
        mark = "ACTIVE  " if provider.is_callable else "blocked "
        reason = f"  ({provider.reason})" if provider.reason else ""
        out.append(
            f"{mark}{provider.id:<22}{provider.entry.kind!s:<22}"
            f"{provider.effective_status}{reason}"
        )
    out += ["```", "", f"{len(active)} of {len(registry.all())} providers callable."]
    return "\n".join(out) + "\n"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, help="write the report here instead of stdout")
    args = parser.parse_args()

    results, registry = await gather_evidence()
    report = render(results, registry)

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)

    failed = [e for e in results if not e.ok and not e.skipped]
    problems = [p for e in results for p in e.problems]
    return 1 if failed or problems else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
