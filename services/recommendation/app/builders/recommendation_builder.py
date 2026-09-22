from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.directory.resolver import resolve_emergency_contacts
from app.domain.recommendation import (
    Citation,
    DecisionReason,
    DegradedService,
    DisasterEvent,
    EmergencyInstruction,
    Freshness,
    ImmediateAction,
    Limitation,
    OfficialContact,
    RecommendationResponse,
    ResponseVersions,
    RouteCandidate,
    SourceProvenance,
)
from app.observability import RECOMMENDATION_LATENCY_SECONDS, RECOMMENDATION_REQUESTS_TOTAL


class PolicyValidationError(Exception):
    """Raised when decision validation.locked_action is false or tampered with."""


class RecommendationBuilder:
    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def build_recommendation(
        self,
        request_id: str,
        trip_id: str,
        decision: dict[str, Any],
        context: dict[str, Any],
        conversation_id: str | None = None,
        locale: str = "th-TH",
        now: datetime | None = None,
    ) -> RecommendationResponse:
        """Composes an immutable RecommendationResponse following strict contract rules."""
        with RECOMMENDATION_LATENCY_SECONDS.time():
            current_time = now or datetime.now(UTC)

            # 1. Validate Decision Integrity
            validation_info = decision.get("validation", {})
            if not validation_info.get("locked_action", False):
                msg = (
                    "Decision locked_action validation is false or missing. "
                    "Downstream tampering detected."
                )
                raise PolicyValidationError(msg)

            action_code = decision.get("action_code", "NORMAL")
            risk_level = decision.get("risk_level", "UNKNOWN")
            confidence = float(decision.get("confidence", 0.0))
            decision_id = decision.get("decision_id")
            snapshot_id = decision.get("snapshot_id")

            # 2. Extract and Deduplicate Reasons
            raw_reasons = decision.get("reasons", [])
            reasons: list[DecisionReason] = []
            seen_reason_codes: set[str] = set()
            for r in raw_reasons:
                code = r.get("code", "GENERAL")
                if code not in seen_reason_codes:
                    seen_reason_codes.add(code)
                    reasons.append(
                        DecisionReason(
                            code=code,
                            message=r.get("message", ""),
                            severity=r.get("severity", "INFO"),
                            evidence_ids=r.get("evidence_ids", []),
                        )
                    )

            # 3. Extract Immediate Actions
            raw_immediate = decision.get("immediate_actions", [])
            immediate_actions: list[ImmediateAction] = [
                ImmediateAction(
                    action_type=ia.get("action_type", "INFO"),
                    description=ia.get("description", ""),
                    priority=ia.get("priority", 1),
                    target_time=ia.get("target_time"),
                )
                for ia in raw_immediate
            ]

            # 4. Resolve Route Candidates and Route/Action Consistency
            routes_data = context.get("routes", [])
            route_candidates: list[RouteCandidate] = []
            for rd in routes_data:
                route_candidates.append(RouteCandidate(**rd))

            primary_route: RouteCandidate | None = None
            alternatives: list[RouteCandidate] = []

            # Selected route from decision
            selected_route_id = decision.get("selected_route_id")
            if selected_route_id and route_candidates:
                for r in route_candidates:
                    if r.route_id == selected_route_id:
                        primary_route = r
                    else:
                        alternatives.append(r)
            elif route_candidates:
                primary_route = route_candidates[0]
                alternatives = route_candidates[1:]

            # Route/Action Consistency Validations
            limitations_list: list[Limitation] = []
            raw_limits = decision.get("limitations", [])
            for lim in raw_limits:
                limitations_list.append(
                    Limitation(
                        code=lim.get("code", "GENERAL_LIMITATION"),
                        message=lim.get("message", ""),
                        severity=lim.get("severity", "INFO"),
                    )
                )

            is_closed = bool(
                primary_route
                and primary_route.exposure
                and primary_route.exposure.get("closed")
            )
            if action_code == "CHANGE_ROUTE" and (not primary_route or is_closed):
                limitations_list.append(
                    Limitation(
                        code="NO_VIABLE_SAFER_ROUTE",
                        message=(
                            "Recommended action is CHANGE_ROUTE but no unclosed route is available."
                        ),
                        severity="WARNING",
                    )
                )

            if action_code == "AVOID" and primary_route and primary_route.label == "RECOMMENDED":
                primary_route.label = "ORIGINAL"

            # 5. Extract Alerts & Deduplicate
            alerts_data = context.get("alerts", [])
            alerts: list[DisasterEvent] = []
            seen_alerts: set[str] = set()
            for ad in alerts_data:
                eid = ad.get("event_id")
                if eid and eid not in seen_alerts:
                    seen_alerts.add(eid)
                    alerts.append(DisasterEvent(**ad))

            # 6. Extract Emergency Instructions & Citations
            raw_instructions = context.get("emergency_instructions", [])
            emergency_instructions: list[EmergencyInstruction] = []
            for inst in raw_instructions:
                cit_data = inst.get("citation")
                cit = Citation(**cit_data) if cit_data else None
                emergency_instructions.append(
                    EmergencyInstruction(
                        text=inst.get("text", ""),
                        evidence_id=inst.get("evidence_id", str(uuid.uuid4())),
                        hazard_type=inst.get("hazard_type"),
                        citation=cit,
                    )
                )

            # 7. Resolve Verified Emergency Contacts
            country_code = context.get("country_code", "TH")
            subdivision = context.get("subdivision")
            official_contacts: list[OfficialContact] = []
            if country_code:
                official_contacts = await resolve_emergency_contacts(
                    country_code=country_code,
                    subdivision=subdivision,
                    locale=locale,
                    session=self.session,
                    now=current_time,
                )

            if country_code and not official_contacts:
                msg = f"No verified official emergency directory available for '{country_code}'."
                limitations_list.append(
                    Limitation(
                        code="UNSUPPORTED_EMERGENCY_DIRECTORY_COVERAGE",
                        message=msg,
                        severity="INFO",
                    )
                )

            # 8. Extract Sources & Deduplicate
            sources_data = context.get("sources", [])
            sources: list[SourceProvenance] = []
            seen_sources: set[str] = set()
            for sd in sources_data:
                sid = sd.get("source_id")
                if sid and sid not in seen_sources:
                    seen_sources.add(sid)
                    sources.append(SourceProvenance(**sd))

            # 9. Compute Expiration and Freshness
            # Expiration is minimum of critical evidence expiry dates and policy TTL
            default_ttl = current_time + timedelta(hours=6)
            expiry_candidates: list[datetime] = [default_ttl]

            if context.get("expires_at"):
                ctx_exp = context.get("expires_at")
                if isinstance(ctx_exp, str):
                    ctx_exp = datetime.fromisoformat(ctx_exp.replace("Z", "+00:00"))
                if isinstance(ctx_exp, datetime):
                    expiry_candidates.append(ctx_exp)

            for s in sources:
                if s.expires_at:
                    expiry_candidates.append(s.expires_at)

            for a in alerts:
                if a.ends_at:
                    expiry_candidates.append(a.ends_at)

            computed_expires_at = min(expiry_candidates)

            # Compute observed_at (oldest observed time among sources)
            observed_times = [s.observed_at for s in sources if s.observed_at]
            oldest_observed = min(observed_times) if observed_times else None

            freshness = Freshness(
                observed_at=oldest_observed,
                fetched_at=current_time,
                expires_at=computed_expires_at,
            )

            # 10. Degraded Services
            degraded_services_data = context.get("degraded_services", [])
            degraded_services: list[DegradedService] = [
                DegradedService(**ds) for ds in degraded_services_data
            ]

            lim_codes = {lim.code for lim in limitations_list}
            status = (
                "PARTIAL"
                if degraded_services or "UNSUPPORTED_EMERGENCY_DIRECTORY_COVERAGE" in lim_codes
                else "COMPLETED"
            )

            # 11. Versions Metadata
            decision_versions = decision.get("versions", {})
            versions = ResponseVersions(
                contract="1.0.0",
                policy=decision_versions.get("policy", "1.0.0"),
                prompt=decision_versions.get("prompt", "1.0.0"),
                llm_model=decision_versions.get("llm_model"),
                risk_model=decision_versions.get("risk_model"),
                knowledge_collection=decision_versions.get("knowledge_collection"),
            )

            # 12. Short Summary
            short_summary = decision.get("summary", "").strip()
            if not short_summary:
                if action_code == "NORMAL":
                    short_summary = "Route is clear and travel can proceed as planned."
                elif action_code == "CHANGE_ROUTE":
                    short_summary = (
                        "Use the safer alternative route to avoid hazards along the corridor."
                    )
                elif action_code == "DELAY":
                    short_summary = "Delay departure until conditions improve."
                elif action_code == "AVOID":
                    short_summary = "Avoid travel due to severe hazards and route closures."

            response = RecommendationResponse(
                recommendation_id=str(uuid.uuid4()),
                request_id=request_id,
                trip_id=trip_id,
                conversation_id=conversation_id,
                decision_id=decision_id,
                snapshot_id=snapshot_id,
                status=status,
                action_code=action_code,
                risk_level=risk_level,
                confidence=confidence,
                short_summary=short_summary[:1000],
                immediate_actions=immediate_actions,
                reasons=reasons,
                primary_route=primary_route,
                alternatives=alternatives,
                alerts=alerts,
                emergency_instructions=emergency_instructions,
                official_contacts=official_contacts,
                sources=sources,
                freshness=freshness,
                limitations=limitations_list,
                degraded_services=degraded_services,
                versions=versions,
                expires_at=computed_expires_at,
                created_at=current_time,
            )

            # Record metric
            RECOMMENDATION_REQUESTS_TOTAL.labels(
                action=action_code,
                risk=risk_level,
                status=status,
            ).inc()

            return response
