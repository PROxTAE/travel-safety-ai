"""Calling module 03, the agent service.

This API decides nothing about risk. It normalises what the traveller asked into the shape §5.1 of
the contract document defines, hands it to the agent, and reports back what the agent says. Three
properties hold here and are easy to erode later:

* **No URL comes from the caller.** The base URL is configuration and the paths are constants.
* **No prompt, model or policy decision lives in this service.** Those belong to module 03.
* **A failure is reported as a failure.** An agent that is down produces 503 with
  `DEPENDENCY_UNAVAILABLE` and a run marked FAILED — never an empty or invented assessment. A
  traveller who is told "we could not check" will look elsewhere; one shown a confident blank will
  not.

**Timeout budget.** `POST /internal/v1/runs` is expected to answer 202 quickly — it accepts work,
it does not do it — so it gets a short, separate budget rather than the general downstream read
timeout. Long processing is followed over status and SSE. Cancellation gets a short budget too,
because the caller is already leaving.

**Retries.** None on create. Creating a run is not idempotent from the agent's side unless it is
given a key, and a retry that the first call actually received would start a second assessment.
Status reads are safe to retry, but the poller already runs again in a moment, so there is nothing
to gain by retrying inside one call.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.errors.exceptions import DependencyTimeout, DependencyUnavailable
from app.observability.logging import get_logger
from app.settings import Settings

logger = get_logger(__name__)

#: The dependency name reported in `meta.degraded_services`, in readiness and in the error log.
DEPENDENCY = "agent"

RUNS_PATH = "/internal/v1/runs"


class AgentRejectedRequest(Exception):
    """The agent refused the request itself, rather than being unavailable.

    Separate from `DependencyUnavailable` because the two mean different things to the run: an
    unavailable agent may succeed on a later attempt, whereas a rejected request will be rejected
    again until something changes. The handler maps this onto a FAILED run rather than a 503.
    """

    def __init__(self, status_code: int, code: str | None = None) -> None:
        super().__init__(f"agent rejected the request with {status_code}")
        self.status_code = status_code
        self.code = code


class AgentClient:
    """A thin, typed wrapper over the calls this service makes to module 03."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    @property
    def _base(self) -> str:
        return self._settings.agent_service_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        """Service credential plus the correlation headers every internal call carries.

        The ids come from the context the middleware bound, so a trace started in the browser
        reaches the agent — and from there the tool calls it makes — without a handler threading
        them through by hand. That is what makes one traveller's report findable afterwards.
        """
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

    def _require_credential(self) -> None:
        """Fail closed, and say which thing is misconfigured.

        Calling without the credential would earn a 401 from module 03 and be reported as though
        the agent were broken, which sends an operator to read the wrong service's logs.
        """
        if self._settings.internal_service_token is None:
            logger.error(
                "internal_service_token_missing",
                event_type="configuration",
                dependency=DEPENDENCY,
            )
            raise DependencyUnavailable(
                DEPENDENCY,
                message="Safety assessment is not available.",
            )

    async def create_run(self, payload: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        """Hand a normalised `TravelRequest` to the agent and get its `RunRef` back.

        `request_id` is this service's id for the run and is sent as the agent's idempotency key,
        so a retry at the HTTP layer cannot start a second assessment for one accepted request.
        """
        self._require_credential()

        headers = {**self._headers, "Idempotency-Key": request_id}
        timeout = httpx.Timeout(
            connect=self._settings.downstream_connect_timeout_seconds,
            read=self._settings.agent_accept_timeout_seconds,
            write=self._settings.downstream_connect_timeout_seconds,
            pool=self._settings.downstream_connect_timeout_seconds,
        )

        try:
            response = await self._client.post(
                f"{self._base}{RUNS_PATH}", json=payload, headers=headers, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "dependency_timeout",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=RUNS_PATH,
            )
            raise DependencyTimeout(
                DEPENDENCY, message="Safety assessment did not start in time."
            ) from exc
        except httpx.HTTPError as exc:
            # The exception text can carry the internal host and port. It goes to the log, where an
            # operator needs it, and never into the response.
            logger.warning(
                "dependency_unreachable",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=RUNS_PATH,
                error_type=type(exc).__name__,
            )
            raise DependencyUnavailable(
                DEPENDENCY, message="Safety assessment is unavailable."
            ) from exc

        if response.status_code >= 500:
            logger.warning(
                "dependency_error_status",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Safety assessment is unavailable.")

        if response.status_code >= 400:
            # A 4xx here is our bug or a contract drift, never the traveller's: we built this body
            # from a trip we had already validated.
            logger.error(
                "dependency_rejected_request",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
            )
            raise AgentRejectedRequest(response.status_code, self._error_code(response))

        return self._envelope(response, RUNS_PATH)

    async def get_run(self, agent_run_id: str) -> dict[str, Any] | None:
        """The agent's view of a run, or None if it has never heard of it.

        None rather than an exception for 404: a run this service committed before the agent call
        failed legitimately does not exist upstream, and that is a state the poller handles rather
        than an error to report.
        """
        self._require_credential()
        path = f"{RUNS_PATH}/{agent_run_id}"

        try:
            response = await self._client.get(f"{self._base}{path}", headers=self._headers)
        except httpx.TimeoutException as exc:
            raise DependencyTimeout(
                DEPENDENCY, message="Safety assessment did not answer in time."
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
                DEPENDENCY, message="Safety assessment is unavailable."
            ) from exc

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            logger.warning(
                "dependency_error_status",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
                path=path,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Safety assessment is unavailable.")

        return self._envelope(response, path)

    async def cancel_run(self, agent_run_id: str, *, reason: str) -> None:
        """Ask the agent to stop.

        Best effort by design. The client is already walking away, and the run is marked CANCELLED
        here whatever the agent says — a cancellation that failed to propagate wastes compute,
        while one that blocked the caller on an unreachable service wastes the traveller's time and
        leaves them unsure whether they cancelled anything.
        """
        self._require_credential()
        path = f"{RUNS_PATH}/{agent_run_id}/cancel"
        timeout = httpx.Timeout(
            connect=self._settings.downstream_connect_timeout_seconds,
            read=self._settings.agent_cancel_timeout_seconds,
            write=self._settings.downstream_connect_timeout_seconds,
            pool=self._settings.downstream_connect_timeout_seconds,
        )

        try:
            response = await self._client.post(
                f"{self._base}{path}",
                json={"reason": reason},
                headers=self._headers,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "cancel_not_propagated",
                event_type="dependency",
                dependency=DEPENDENCY,
                error_type=type(exc).__name__,
                detail="the run is cancelled here; the agent may still be working",
            )
            return

        if response.status_code >= 400:
            logger.warning(
                "cancel_not_propagated",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
                detail="the run is cancelled here; the agent may still be working",
            )

    def _error_code(self, response: httpx.Response) -> str | None:
        try:
            body = response.json()
            code = body["error"]["code"]
        except (ValueError, KeyError, TypeError):
            return None
        return str(code) if isinstance(code, str) else None

    def _envelope(self, response: httpx.Response, path: str) -> dict[str, Any]:
        """Pull the payload out of module 03's envelope.

        A body that does not have the shape the contract describes is a drift between two services
        and is reported as a dependency failure rather than half-parsed. Half-parsing is how a
        missing status becomes a default one.
        """
        try:
            body = response.json()
            data = body["data"]
        except (ValueError, KeyError, TypeError) as exc:
            logger.error(
                "dependency_schema_mismatch",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=path,
            )
            raise DependencyUnavailable(
                DEPENDENCY, message="Safety assessment is unavailable."
            ) from exc

        if not isinstance(data, dict):
            logger.error(
                "dependency_schema_mismatch",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=path,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Safety assessment is unavailable.")

        return data
