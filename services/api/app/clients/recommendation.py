"""Calling module 08, and refusing to expose what it cannot vouch for.

One job in phase 5: before a run is reported COMPLETED, fetch the recommendation the agent says it
produced and check it against the contract. If the check fails, the run does not complete. The
traveller is told the assessment failed rather than handed an id that leads to an object this
service could not parse.

**Why a failed check becomes FAILED and not COMPLETED-with-a-warning.** A recommendation is a
safety verdict. "Here is your assessment, but we could not read part of it" invites the traveller
to act on the part that rendered, and the part that did not render is exactly the part nobody
checked. Refusing is the conservative direction and it is the one the contract asks for.

**Why the ownership fields are checked and not assumed.** `request_id` and `trip_id` in the
returned object must match the run that asked. They are compared rather than trusted because a
mismatch — from a cache key collision, a retry landing on the wrong row, an id reused after a
restore — would show one traveller another traveller's journey.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from pydantic import ValidationError

from app.errors.exceptions import DependencyTimeout, DependencyUnavailable
from app.observability.logging import get_logger
from app.observability.metrics import (
    downstream_request_duration_seconds,
    downstream_request_errors_total,
)
from app.schemas.recommendation import RecommendationResponseModel
from app.security.outbound import validate_outbound_url
from app.settings import Settings

logger = get_logger(__name__)

DEPENDENCY = "recommendation"

RECOMMENDATIONS_PATH = "/internal/v1/recommendations"


class RecommendationInvalid(Exception):
    """Module 08 answered, but not with something this service will expose.

    Carries a short reason for the log. The reason never reaches the client: it describes another
    service's internals, and the traveller's answer is the same either way.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RecommendationClient:
    """A thin, typed wrapper over the calls this service makes to module 08."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    @property
    def _base(self) -> str:
        return self._settings.recommendation_service_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        from app.middleware.request_context import current_correlation_id, current_request_id

        headers = {
            "X-Request-ID": str(current_request_id()),
            "X-Correlation-ID": str(current_correlation_id()),
            "X-Contract-Version": self._settings.contract_version.split(".")[0],
        }
        token = self._settings.internal_service_token
        if token is not None:
            headers["Authorization"] = f"Bearer {token.get_secret_value()}"
        return headers

    async def fetch_validated(
        self,
        recommendation_id: uuid.UUID,
        *,
        request_id: uuid.UUID,
        trip_id: uuid.UUID | None,
    ) -> RecommendationResponseModel:
        """The recommendation, checked against the contract and against who asked for it.

        Raises `RecommendationInvalid` when the object is not one this service will stand behind,
        and the usual dependency errors when module 08 cannot be reached at all. The two are
        different: unreachable may succeed on a retry, invalid will not.
        """
        if self._settings.internal_service_token is None:
            logger.error(
                "internal_service_token_missing",
                event_type="configuration",
                dependency=DEPENDENCY,
            )
            raise DependencyUnavailable(DEPENDENCY, message="The assessment result is unavailable.")

        path = f"{RECOMMENDATIONS_PATH}/{recommendation_id}"
        url = f"{self._base}{path}"
        validate_outbound_url(url, self._settings)

        import time

        start_time = time.monotonic()
        try:
            response = await self._client.get(url, headers=self._headers)
            downstream_request_duration_seconds.labels(
                dependency=DEPENDENCY, operation="fetch_recommendation"
            ).observe(time.monotonic() - start_time)
        except httpx.TimeoutException as exc:
            downstream_request_errors_total.labels(
                dependency=DEPENDENCY, error_kind="timeout"
            ).inc()
            raise DependencyTimeout(
                DEPENDENCY, message="The assessment result did not arrive in time."
            ) from exc
        except httpx.HTTPError as exc:
            downstream_request_errors_total.labels(
                dependency=DEPENDENCY, error_kind="http_error"
            ).inc()
            logger.warning(
                "dependency_unreachable",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=path,
                error_type=type(exc).__name__,
            )
            raise DependencyUnavailable(
                DEPENDENCY, message="The assessment result is unavailable."
            ) from exc

        if response.status_code == 404:
            # The agent named a recommendation that module 08 does not have. That is a real
            # inconsistency between two services, not a transient failure.
            raise RecommendationInvalid(
                "module 08 does not have the recommendation the agent named"
            )

        if response.status_code >= 500:
            downstream_request_errors_total.labels(
                dependency=DEPENDENCY, error_kind=f"status_{response.status_code}"
            ).inc()
            logger.warning(
                "dependency_error_status",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
                path=path,
            )
            raise DependencyUnavailable(DEPENDENCY, message="The assessment result is unavailable.")

        if response.status_code >= 400:
            logger.warning(
                "dependency_error_status",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
                path=path,
            )
            raise DependencyUnavailable(DEPENDENCY, message="The assessment result is unavailable.")

        return self._validate(response, request_id=request_id, trip_id=trip_id)

    def _validate(
        self,
        response: httpx.Response,
        *,
        request_id: uuid.UUID,
        trip_id: uuid.UUID | None,
    ) -> RecommendationResponseModel:
        try:
            body = response.json()
            data: Any = body["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RecommendationInvalid("response was not the contract envelope") from exc

        try:
            model = RecommendationResponseModel.model_validate(data)
        except ValidationError as exc:
            # The count, not the errors: a pydantic error message quotes the offending values, and
            # those values are somebody's journey.
            logger.error(
                "recommendation_schema_mismatch",
                event_type="dependency",
                dependency=DEPENDENCY,
                error_count=exc.error_count(),
                fields=sorted({str(item["loc"][0]) for item in exc.errors() if item["loc"]}),
            )
            raise RecommendationInvalid("recommendation did not match the contract") from exc

        if model.request_id != request_id:
            raise RecommendationInvalid("recommendation belongs to a different run")

        if trip_id is not None and model.trip_id != trip_id:
            raise RecommendationInvalid("recommendation belongs to a different trip")

        if not model.sources:
            # Every displayed fact carries its source. A verdict with no provenance cannot be
            # checked by the person acting on it, which is the property that makes it safe to show.
            raise RecommendationInvalid("recommendation carried no sources")

        return model

    async def create_feedback(
        self,
        *,
        feedback_id: uuid.UUID,
        recommendation_id: uuid.UUID,
        category: str,
        text: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Submit feedback to module 08."""
        if self._settings.internal_service_token is None:
            logger.error(
                "internal_service_token_missing",
                event_type="configuration",
                dependency=DEPENDENCY,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Feedback service is unavailable.")

        path = "/internal/v1/feedback"
        headers = dict(self._headers)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = {
            "feedback_id": str(feedback_id),
            "recommendation_id": str(recommendation_id),
            "category": category,
            "text": text,
        }

        try:
            response = await self._client.post(f"{self._base}{path}", json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise DependencyTimeout(
                DEPENDENCY, message="Feedback service did not answer in time."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "dependency_unreachable",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=path,
                error_type=type(exc).__name__,
            )
            raise DependencyUnavailable(
                DEPENDENCY, message="Feedback service is unavailable."
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "dependency_error_status",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
                path=path,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Feedback service is unavailable.")

        try:
            data = response.json().get("data")
            if isinstance(data, dict):
                return data
            return payload
        except Exception:
            return payload

    async def create_alert_subscription(
        self,
        *,
        subscription_id: uuid.UUID,
        trip_id: uuid.UUID,
        channel: str,
        consent_id: uuid.UUID,
        min_severity: str = "MODERATE",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Register an alert subscription with module 08."""
        if self._settings.internal_service_token is None:
            logger.error(
                "internal_service_token_missing",
                event_type="configuration",
                dependency=DEPENDENCY,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Alert service is unavailable.")

        path = "/internal/v1/alert-subscriptions"
        headers = dict(self._headers)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = {
            "subscription_id": str(subscription_id),
            "trip_id": str(trip_id),
            "channel": channel,
            "consent_id": str(consent_id),
            "min_severity": min_severity,
        }

        try:
            response = await self._client.post(f"{self._base}{path}", json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise DependencyTimeout(
                DEPENDENCY, message="Alert service did not answer in time."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "dependency_unreachable",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=path,
                error_type=type(exc).__name__,
            )
            raise DependencyUnavailable(
                DEPENDENCY, message="Alert service is unavailable."
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "dependency_error_status",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
                path=path,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Alert service is unavailable.")

        try:
            data = response.json().get("data")
            if isinstance(data, dict):
                return data
            return payload
        except Exception:
            return payload

    async def delete_alert_subscription(self, subscription_id: uuid.UUID) -> None:
        """Cancel an alert subscription in module 08."""
        if self._settings.internal_service_token is None:
            logger.error(
                "internal_service_token_missing",
                event_type="configuration",
                dependency=DEPENDENCY,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Alert service is unavailable.")

        path = f"/internal/v1/alert-subscriptions/{subscription_id}"
        try:
            response = await self._client.delete(f"{self._base}{path}", headers=self._headers)
        except httpx.TimeoutException as exc:
            raise DependencyTimeout(
                DEPENDENCY, message="Alert service did not answer in time."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning(
                "dependency_unreachable",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=path,
                error_type=type(exc).__name__,
            )
            raise DependencyUnavailable(
                DEPENDENCY, message="Alert service is unavailable."
            ) from exc

        if response.status_code not in (200, 204, 404):
            logger.warning(
                "dependency_error_status",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
                path=path,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Alert service is unavailable.")
