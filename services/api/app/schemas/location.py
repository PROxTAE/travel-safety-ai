"""`LocationRef` and the GeoJSON point inside it.

Mirrors `packages/contracts/jsonschema/common/location-ref.schema.json`; the field names and
required set are asserted against it in `tests/test_contract_parity.py`.

The coordinate order is the one place in this file worth slowing down for. GeoJSON RFC 7946 and the
shared context both say `[longitude, latitude]`, and the two are indistinguishable inside Thailand,
where longitude and latitude are both plausible small positive numbers. A swap that validates is a
swap that ships, so the two elements are bounded separately: 100.5 as a latitude fails.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GeoPoint(BaseModel):
    """A GeoJSON Point. Exactly two elements, `[longitude, latitude]`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["Point"] = "Point"
    coordinates: tuple[
        Annotated[float, Field(ge=-180.0, le=180.0)],
        Annotated[float, Field(ge=-90.0, le=90.0)],
    ]

    @property
    def longitude(self) -> float:
        return self.coordinates[0]

    @property
    def latitude(self) -> float:
        return self.coordinates[1]


class LocationRef(BaseModel):
    """A place resolved by a real geocoding provider, or a pin the user dropped.

    `confirmed_by_user` is set by the client after the traveller has seen the pin on the map. This
    service never sets it true on the caller's behalf: the whole point is that a person looked.
    """

    model_config = ConfigDict(extra="forbid")

    place_id: Annotated[str | None, Field(max_length=256)] = None
    display_name: Annotated[str, Field(min_length=1, max_length=512)]
    coordinates: GeoPoint
    country_code: Annotated[str | None, Field(pattern=r"^[A-Z]{2}$")] = None
    admin1: Annotated[str | None, Field(max_length=256)] = None
    timezone: Annotated[str | None, Field(max_length=64)] = None
    provider: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    confirmed_by_user: bool = False

    @field_validator("country_code", mode="before")
    @classmethod
    def _uppercase_country_code(cls, value: object) -> object:
        """`th` means Thailand as clearly as `TH` does.

        Normalised rather than rejected: the contract describes what is stored, and a client that
        lower-cased it has made a formatting mistake, not a factual one.
        """
        if isinstance(value, str):
            return value.upper()
        return value
