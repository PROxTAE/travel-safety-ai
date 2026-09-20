"""Calling module 04, the external-data service.

This API never talks to a geocoding provider itself. It calls `/internal/v1/geocode/search`, which
owns provider selection, quota, caching and provenance. Two consequences worth stating, because
both are easy to erode later:

* **No provider key lives in this service.** There is nothing here to leak.
* **No URL comes from the caller.** The base URL is configuration; the path is a constant.

Failure is reported, never papered over. A geocoding provider that is down produces 503 with
`DEPENDENCY_UNAVAILABLE`, not an empty list — "nothing matched your search" and "search is broken"
lead a traveller to do completely different things, and an empty list says the first while meaning
the second.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.errors.exceptions import DependencyTimeout, DependencyUnavailable
from app.observability.logging import get_logger
from app.settings import Settings

logger = get_logger(__name__)

#: The dependency name reported in `meta.degraded_services` and in the error log.
DEPENDENCY = "external-data"

GEOCODE_PATH = "/internal/v1/geocode/search"


class ExternalDataClient:
    """A thin, typed wrapper over the calls this service makes to module 04."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    @property
    def _headers(self) -> dict[str, str]:
        """Service credential plus the correlation headers every internal call carries.

        The request and correlation ids are read from the context the middleware bound, so a trace
        started in the browser reaches the provider adapter without a handler having to thread them
        through by hand.
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

    async def geocode_search(
        self,
        *,
        query: str,
        limit: int,
        language: str,
        country_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve a place name to canonical `LocationRef` records.

        Returns the provider's results, which may legitimately be empty. Anything that is not a
        clean answer becomes an exception: the caller must not be able to mistake a failure for a
        successful search that found nothing.
        """
        if self._settings.internal_service_token is None:
            # Fail closed and say so. Calling without the credential would get a 401 from module 04
            # and be reported as though that service were broken, sending an operator to look at
            # the wrong thing.
            logger.error(
                "internal_service_token_missing",
                event_type="configuration",
                dependency=DEPENDENCY,
            )
            raise DependencyUnavailable(
                DEPENDENCY,
                message="Place search is not available. Nothing was guessed.",
            )

        url = f"{self._settings.external_data_service_url.rstrip('/')}{GEOCODE_PATH}"
        payload = {
            "query": query,
            "count": limit,
            "language": language,
        }
        if country_code is not None:
            payload["country_code"] = country_code

        try:
            response = await self._client.post(url, json=payload, headers=self._headers)
        except httpx.TimeoutException as exc:
            logger.warning(
                "dependency_timeout",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=GEOCODE_PATH,
            )
            raise DependencyTimeout(
                DEPENDENCY, message="Place search did not answer in time."
            ) from exc
        except httpx.HTTPError as exc:
            # The exception text can contain the internal host and port. It goes to the log, which
            # is where an operator needs it, and never into the response.
            logger.warning(
                "dependency_unreachable",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=GEOCODE_PATH,
                error_type=type(exc).__name__,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Place search is unavailable.") from exc

        if response.status_code >= 500:
            logger.warning(
                "dependency_error_status",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Place search is unavailable.")

        if response.status_code >= 400:
            # A 4xx from an internal service is our bug, not the caller's: we built the request.
            # Reported as unavailable rather than passed through, so a contract drift between the
            # two services never reaches a user as "your search was invalid".
            logger.error(
                "dependency_rejected_request",
                event_type="dependency",
                dependency=DEPENDENCY,
                status=response.status_code,
            )
            raise DependencyUnavailable(DEPENDENCY, message="Place search is unavailable.")

        return self._results_from(response)

    def _results_from(self, response: httpx.Response) -> list[dict[str, Any]]:
        """Pull the result list out of module 04's envelope.

        A body that does not have the shape the contract describes is a schema drift between two
        services, and is reported as a dependency failure rather than half-parsed.
        """
        try:
            body = response.json()
            results = body["data"]["results"]
        except (ValueError, KeyError, TypeError) as exc:
            logger.error(
                "dependency_schema_mismatch",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=GEOCODE_PATH,
            )
            raise DependencyUnavailable(
                DEPENDENCY, message="Place search returned an unexpected response."
            ) from exc

        if not isinstance(results, list):
            logger.error(
                "dependency_schema_mismatch",
                event_type="dependency",
                dependency=DEPENDENCY,
                path=GEOCODE_PATH,
            )
            raise DependencyUnavailable(
                DEPENDENCY, message="Place search returned an unexpected response."
            )

        return results


def get_external_data_client(request: Any) -> ExternalDataClient:
    """Build a client over the shared HTTP connection pool opened at startup."""
    return ExternalDataClient(request.app.state.internal_http, request.app.state.settings)
