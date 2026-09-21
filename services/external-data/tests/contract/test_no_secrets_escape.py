"""Phase 7 verification: nothing sensitive leaves this module.

Security invariant § 11 names four places a secret or a personal detail must
never appear: source, logs, fixtures, and anything returned to a caller. Each
gets a test, because each has a different way of going wrong and none of them
raises an error when it does.

The exact coordinate case is the least obvious and the most personal. A
traveller's position identifies them; a rounded one does not. Logs and cache
keys both outlive the request that created them.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.observability.logging import _redact, _redact_text
from app.settings import get_settings
from tests.conftest import FIXTURE_ROOT, SERVICE_ROOT, TEST_TOKEN, load_fixture

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
APP_ROOT = SERVICE_ROOT / "app"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# A real openrouteservice key is a base64 JSON object; a real Amadeus secret is
# a bare token. Both would be caught by a literal assignment in source.
_HARDCODED_SECRET = re.compile(
    r"""(?ix)
    \b(api[_-]?key|apikey|secret|password|token|credential)\b
    \s*[:=]\s*
    ["'][A-Za-z0-9._\-/+]{12,}["']
    """
)
# Values that look like credentials but are not: test doubles and env lookups.
_ALLOWED = ("test-", "fake-", "dummy-", "example", "os.environ", "getenv", "not-a-real")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def _source_files() -> list[Path]:
    return [p for p in APP_ROOT.rglob("*.py") if "migrations/versions" not in p.as_posix()]


# ------------------------------------------------------------------ source


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_no_credential_is_hardcoded_in_source(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for match in _HARDCODED_SECRET.finditer(text):
        line = text[: match.start()].count("\n") + 1
        snippet = match.group(0)
        if any(allowed in snippet for allowed in _ALLOWED):
            continue
        pytest.fail(f"{path.name}:{line} looks like a hardcoded credential: {snippet}")


def test_no_runtime_mock_switch_exists() -> None:
    """Acceptance runbook § 3: a flag that serves invented data is forbidden,
    because the one time it is left on is the time it matters."""
    banned = re.compile(
        r"(USE_MOCK|MOCK_MODE|mockMode|fakeRecommendation|hardcodedWeather|sampleCurrentData)"
    )
    for path in _source_files():
        assert not banned.search(path.read_text(encoding="utf-8")), path.name


def test_settings_hold_credentials_as_secrets_not_strings() -> None:
    """A plain `str` credential prints itself in every traceback and repr."""
    from pydantic import SecretStr

    settings = get_settings()
    for name in ("ors_api_key", "amadeus_client_id", "amadeus_client_secret"):
        value = getattr(settings, name)
        assert value is None or isinstance(value, SecretStr), name


def test_the_settings_repr_does_not_contain_a_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORS_API_KEY", "leak-me-abcdefghijklmnop")
    get_settings.cache_clear()
    try:
        assert "leak-me-abcdefghijklmnop" not in repr(get_settings())
    finally:
        get_settings.cache_clear()


# -------------------------------------------------------------------- logs


def test_a_credential_in_a_url_is_redacted() -> None:
    redacted = _redact_text("GET https://api.example/v1/x?api_key=sk-live-abc123def456")
    assert "sk-live-abc123def456" not in redacted


def test_a_bearer_token_is_redacted() -> None:
    assert "eyJhbGciOi" not in _redact_text(
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
    )


def test_an_exact_coordinate_is_rounded_in_logs() -> None:
    """Full precision identifies a person and a log line outlives the request."""
    event = _redact(None, "info", {"latitude": 13.756331, "longitude": 100.501762})
    assert event["latitude"] == 13.8
    assert event["longitude"] == 100.5


def test_an_email_and_a_phone_number_are_redacted() -> None:
    redacted = _redact_text("traveller@example.com called +66 81 234 5678")
    assert "traveller@example.com" not in redacted
    assert "234 5678" not in redacted


def test_redaction_leaves_the_things_tracing_depends_on() -> None:
    """Redaction that eats timestamps and request ids makes a log useless
    exactly when it is needed. Both have been broken by it before."""
    stamp = "2026-09-20T08:09:49.757615Z"
    assert _redact_text(stamp) == stamp
    request_id = str(uuid.uuid4())
    assert request_id in _redact_text(f"request_id={request_id} finished")


# ---------------------------------------------------------------- fixtures


def test_no_captured_fixture_contains_a_credential() -> None:
    """The captured payloads, not the prose that describes them.

    MANIFEST.json and README.md legitimately contain words like "Authorization"
    and "api_key": they record that the openrouteservice key travels in a header
    and therefore never reaches a stored body. Scanning them flags the sentences
    documenting the absence of the thing. The manifest is checked separately,
    for values rather than words.
    """
    describes_rather_than_contains = {"MANIFEST.json", "README.md"}
    pattern = re.compile(
        r"(?i)\b(api[_-]?key|apikey|access[_-]?token|client[_-]?secret|authorization)\b"
    )
    for path in FIXTURE_ROOT.rglob("*"):
        if not path.is_file() or path.name in describes_rather_than_contains:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not pattern.search(text), path.name


def test_the_manifest_records_no_credential_value() -> None:
    """The manifest may name a header; it must never carry one.

    Written against the shapes that actually matter rather than an entropy
    guess. A generic "anything long and opaque" rule flagged file paths and
    content hashes, which is the kind of noisy check people learn to ignore.
    """
    text = (FIXTURE_ROOT / "MANIFEST.json").read_text(encoding="utf-8")

    # An openrouteservice key and a JWT are both base64 JSON, so both begin
    # `eyJ`. This is the exact shape of the key this project uses.
    assert not re.search(r"eyJ[A-Za-z0-9+/=_-]{30,}", text)
    # An Amadeus credential is a bare 32-character token assigned to a field
    # whose name says what it is.
    assert not re.search(
        r'(?i)"(api[_-]?key|secret|token|password)"\s*:\s*"[A-Za-z0-9]{16,}"', text
    )
    # And whatever is configured right now must not be in there either.
    settings = get_settings()
    for name in ("ors_api_key", "amadeus_client_id", "amadeus_client_secret"):
        secret = getattr(settings, name)
        if secret is not None:
            assert secret.get_secret_value() not in text


def test_no_captured_fixture_contains_an_email_or_phone_number() -> None:
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for path in FIXTURE_ROOT.rglob("*.json"):
        if path.name == "MANIFEST.json":
            continue
        text = path.read_text(encoding="utf-8")
        found = [m for m in email.findall(text) if not m.endswith((".gov", ".org"))]
        assert found == [], f"{path.name} contains {found}"


# ----------------------------------------------------------------- outward


@respx.mock
def test_a_caller_never_receives_the_provider_credential(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORS_API_KEY", "super-secret-routing-key-123456")
    get_settings.cache_clear()
    respx.get(FORECAST_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("open_meteo_weather/forecast_bangkok.json")
        )
    )
    with TestClient(create_app()) as keyed:
        response = keyed.post(
            "/internal/v1/weather/query",
            headers=AUTH,
            json={"samples": [{"latitude": 13.7563, "longitude": 100.5018}]},
        )
    get_settings.cache_clear()
    assert "super-secret-routing-key-123456" not in response.text


@respx.mock
def test_a_caller_never_learns_which_upstream_failed(client: TestClient) -> None:
    """Naming the upstream tells an attacker what to attack and tells a user
    something they cannot act on."""
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(503, json={}))

    response = client.post(
        "/internal/v1/weather/query",
        headers=AUTH,
        json={"samples": [{"latitude": 13.7563, "longitude": 100.5018}]},
    )
    lowered = response.text.lower()
    assert "open-meteo" not in lowered
    assert "api.open-meteo.com" not in lowered


def test_the_health_endpoint_names_missing_credentials_without_revealing_any(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naming the variable is the point; carrying its value is the danger.

    `missing_credentials: ["ORS_API_KEY"]` is what tells an operator what to
    configure. The first version of this test banned the substring "api_key"
    and failed on exactly that field - it would have forced the endpoint to
    become less useful in the name of security theatre.
    """
    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "amadeus-secret-value-abcdef123456")
    get_settings.cache_clear()
    with TestClient(create_app()) as keyed:
        raw = keyed.get("/internal/v1/providers/health", headers=AUTH).text
    get_settings.cache_clear()

    assert "amadeus-secret-value-abcdef123456" not in raw
    # The variable name is still reported, because that is actionable.
    assert "ORS_API_KEY" in raw
    assert "Bearer " not in raw


def test_the_metrics_endpoint_carries_no_credential(client: TestClient) -> None:
    raw = client.get("/metrics").text.lower()
    for forbidden in ("api_key", "apikey", "secret", "password"):
        assert forbidden not in raw
