"""Outbound URL validation and allowlist enforcement.

Per Phase 7 item 3: outbound allowlist via configured base URLs, no user URL.
This ensures internal HTTP clients (Agent, External Data, Recommendation, JWKS) only call
pre-approved internal service base URLs, preventing Server-Side Request Forgery (SSRF).
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.observability.logging import get_logger
from app.settings import Settings

logger = get_logger(__name__)


class OutboundTargetForbidden(Exception):
    """Raised when an outbound URL is not in the configured allowlist."""


def get_allowed_base_urls(settings: Settings) -> frozenset[str]:
    """Retrieve the set of pre-configured internal base URLs."""
    urls = [
        settings.agent_service_url.rstrip("/"),
        settings.external_data_service_url.rstrip("/"),
        settings.recommendation_service_url.rstrip("/"),
        settings.oidc_issuer.rstrip("/"),
    ]
    return frozenset(urls)


def validate_outbound_url(url: str, settings: Settings) -> str:
    """Validate that an outbound request target starts with an allowed configured base URL.

    Raises OutboundTargetForbidden if the target host/scheme does not match any configured
    service URL.
    """
    allowed_bases = get_allowed_base_urls(settings)
    normalized = url.rstrip("/")

    # Check if URL starts with any configured base URL prefix
    for base in allowed_bases:
        if normalized == base or normalized.startswith(f"{base}/"):
            return url

    # Also verify scheme/host/port exact match
    parsed = urlparse(url)
    target_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    for base in allowed_bases:
        base_parsed = urlparse(base)
        base_origin = f"{base_parsed.scheme}://{base_parsed.netloc}".rstrip("/")
        if target_origin == base_origin:
            return url

    logger.error(
        "outbound_url_not_allowlisted",
        event_type="security",
        target_url=url,
    )
    raise OutboundTargetForbidden(f"Outbound target URL is not in the configured allowlist: {url}")
