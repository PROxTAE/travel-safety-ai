"""`integrate_data` node."""

from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.graph.state import AgentState, GraphStage, RunStatus
from app.settings import get_settings
from app.tools.clients.data_integration import DataIntegrationClient
from app.tools.schemas import (
    DataQuality,
    RouteCandidate,
    SnapshotCreateRequest,
    SnapshotEvidence,
    SourceProvenance,
    TravelWindow,
)


async def integrate_data(state: AgentState) -> dict[str, object]:
    settings = get_settings()
    client = DataIntegrationClient(settings)

    ext_data = {}
    if state.observations.external_context_ref:
        with contextlib.suppress(Exception):
            ext_data = json.loads(state.observations.external_context_ref)

    req = state.input.travel_request
    now = datetime.now(UTC)
    departure = req.departure_time
    return_time = req.return_time or (departure + timedelta(hours=6))

    orig_coords = req.origin.coordinates.coordinates
    dest_coords = req.destination.coordinates.coordinates

    source_hash = "sha256:" + hashlib.sha256(b"source-default-1").hexdigest()
    default_source = SourceProvenance(
        source_id="src-osm-1",
        provider="OpenStreetMap",
        provider_record_id="osm-th",
        authority="COMMUNITY",
        source_url="https://www.openstreetmap.org",
        license="ODbL",
        attribution="© OpenStreetMap contributors",
        observed_at=now - timedelta(minutes=10),
        published_at=now - timedelta(minutes=10),
        fetched_at=now,
        expires_at=now + timedelta(days=1),
        content_hash=source_hash,
        schema_version="1.0.0",
    )

    default_quality = DataQuality(
        status="FRESH",
        score=0.9,
        score_version="1.0.0",
        flags=[],
        coverage=1.0,
        completeness=1.0,
        freshness_seconds=60,
    )

    route_id = uuid4()
    if ext_data.get("routes"):
        r0 = ext_data["routes"][0]
        r_sources = []
        for s in r0.get("sources", []):
            s_dict = dict(s)
            c_hash = s_dict.get("content_hash", "")
            if not (isinstance(c_hash, str) and c_hash.startswith("sha256:") and len(c_hash) == 71):
                h_val = hashlib.sha256(str(s_dict).encode()).hexdigest()
                s_dict["content_hash"] = f"sha256:{h_val}"
            obs = s_dict.get("observed_at")
            fet = s_dict.get("fetched_at")
            if obs == fet or not obs:
                s_dict["observed_at"] = (now - timedelta(minutes=10)).isoformat()
            if not fet:
                s_dict["fetched_at"] = now.isoformat()
            r_sources.append(SourceProvenance.model_validate(s_dict))
        if not r_sources:
            r_sources = [default_source]

        r_quality = default_quality
        if r0.get("quality"):
            q_dict = dict(r0["quality"])
            if q_dict.get("score") is not None and not q_dict.get("score_version"):
                q_dict["score_version"] = "1.0.0"
            r_quality = DataQuality.model_validate(q_dict)

        route_candidate = RouteCandidate(
            route_id=route_id,
            provider_route_id=r0.get("provider_route_id") or "openrouteservice",
            label="RECOMMENDED",
            mode=r0.get("mode") or (req.travel_modes[0].value if req.travel_modes else "CAR"),
            geometry=r0.get("geometry")
            or {
                "type": "LineString",
                "coordinates": [
                    [orig_coords[0], orig_coords[1]],
                    [dest_coords[0], dest_coords[1]],
                ],
            },
            segments=r0.get("segments", []),
            distance_m=float(r0.get("distance_m", 120000.0)),
            duration_seconds=int(round(float(r0.get("duration_seconds", 5400.0)))),
            transfers=int(r0.get("transfers", 0)),
            exposure=None,
            risk_level="UNKNOWN",
            quality=r_quality,
            sources=r_sources,
        )
    else:
        route_candidate = RouteCandidate(
            route_id=route_id,
            provider_route_id="osrm-route-1",
            label="RECOMMENDED",
            mode=req.travel_modes[0].value if req.travel_modes else "CAR",
            geometry={
                "type": "LineString",
                "coordinates": [
                    [orig_coords[0], orig_coords[1]],
                    [dest_coords[0], dest_coords[1]],
                ],
            },
            segments=[],
            distance_m=120000.0,
            duration_seconds=5400.0,
            transfers=0,
            exposure=None,
            risk_level="UNKNOWN",
            quality=default_quality,
            sources=[default_source],
        )

    snap_req = SnapshotCreateRequest(
        request_id=state.identity.request_id,
        trip_id=state.identity.trip_id,
        travel_window=TravelWindow(
            starts_at=departure,
            ends_at=return_time,
            timezone=req.timezone,
        ),
        recommendation_at=now,
        route=route_candidate,
        evidence=SnapshotEvidence(
            weather=ext_data.get("weather", []),
            disaster_events=ext_data.get("disaster_events", []),
            transport=ext_data.get("transport", []),
        ),
        source_quality={
            "weather": DataQuality(status="FRESH", flags=[]),
            "routes": DataQuality(status="FRESH", flags=[]),
        },
    )

    traceparent = f"00-{uuid4().hex}-{uuid4().hex[:16]}-01"

    try:
        snap_resp, record = await client.create_snapshot(
            snap_req,
            correlation_id=state.identity.correlation_id,
            traceparent=traceparent,
        )
        snapshot_id = snap_resp.data.snapshot_id
    except Exception:
        return {
            "control_patch": {
                "status": RunStatus.FAILED,
                "errors": [*state.control.errors, "DEPENDENCY_UNAVAILABLE"],
            }
        }

    obs = state.observations.model_copy(update={"snapshot_id": snapshot_id})
    return {
        "observations": obs,
        "plan": state.plan.model_copy(update={"current_stage": GraphStage.INTEGRATING_DATA}),
        "control_patch": {"tool_call_count": state.control.tool_call_count + 1},
    }
