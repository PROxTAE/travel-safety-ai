"""Cache key construction.

No Redis here - only the key contract, which is where a subtle bug would quietly
serve one location's weather for another.
"""

from __future__ import annotations

from app.cache.provider_cache import build_key


def _key(**fields: object) -> str:
    return build_key(
        env="test",
        provider_id="open_meteo_forecast",
        schema_version="1.0.0",
        key_fields=dict(fields),
    )


def test_key_follows_the_documented_prefix() -> None:
    key = _key(lat=13.7, lon=100.5)
    assert key.startswith("sta:test:provider-cache:open_meteo_forecast:1.0.0:")


def test_field_order_does_not_change_the_key() -> None:
    assert _key(lat=13.7, lon=100.5) == _key(lon=100.5, lat=13.7)


def test_different_coordinates_produce_different_keys() -> None:
    assert _key(lat=13.7, lon=100.5) != _key(lat=18.8, lon=98.9)


def test_locale_is_part_of_the_key() -> None:
    assert _key(name="Bangkok", locale="en") != _key(name="Bangkok", locale="th")


def test_schema_version_separates_keys() -> None:
    base = dict(env="test", provider_id="p", key_fields={"a": 1})
    assert build_key(schema_version="1.0.0", **base) != build_key(  # type: ignore[arg-type]
        schema_version="2.0.0",
        **base,  # type: ignore[arg-type]
    )


def test_provider_separates_keys() -> None:
    """Two providers answering the same question must not share a cache entry -
    their payload shapes and licences differ."""
    common = dict(env="test", schema_version="1.0.0", key_fields={"bbox": [1, 2, 3, 4]})
    assert build_key(provider_id="usgs_earthquake", **common) != build_key(  # type: ignore[arg-type]
        provider_id="gdacs",
        **common,  # type: ignore[arg-type]
    )


def test_environment_separates_keys() -> None:
    common = dict(provider_id="p", schema_version="1.0.0", key_fields={"a": 1})
    assert build_key(env="test", **common) != build_key(env="production", **common)  # type: ignore[arg-type]
