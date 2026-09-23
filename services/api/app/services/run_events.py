"""The run event stream, and the bridge between Redis and SSE.

Progress for a run is published to a Redis stream, `sta:{env}:run:{request_id}:events`, per §7 of
the contract document. A Redis *stream* and not pub/sub, and that choice is the whole design: a
stream keeps what was published, so a client whose connection dropped can reconnect with
`Last-Event-ID` and receive what it missed. Pub/sub would deliver only to whoever happened to be
connected, which means a dropped connection can lose the terminal event — the one event that
decides what the traveller is told.

Who writes to it. This service writes the events it knows first-hand: `run.accepted` when it
commits the request, and the terminal event when it records a terminal state. Module 03 writes the
progress in between. Both use the same envelope, so a consumer cannot tell — and does not need to
tell — which service produced a given event.

What the bridge refuses to forward:

* an event whose name is not in the contract's list;
* an event whose payload does not validate against that name's model;
* any field the model does not declare, because the models forbid extras.

That is deliberate and it is the point of the bridge. The agent handles provider payloads, prompts
and model output. If any of that ever leaks into an event — through a bug, a new field, a version
skew — the stream is the last place it can be stopped before it reaches a browser. Dropping an
event a traveller will not see is a far smaller harm than forwarding one nobody validated.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import ValidationError
from redis.asyncio import Redis

from app.observability.logging import get_logger
from app.schemas.run import SSE_PAYLOAD_MODELS
from app.settings import Settings

logger = get_logger(__name__)

#: Envelope version, per the pub/sub conventions in §7. Bumped if the envelope itself changes.
ENVELOPE_SCHEMA_VERSION = "1"

PRODUCER = "api"


def stream_key(settings: Settings, request_id: uuid.UUID) -> str:
    """`sta:{env}:run:{request_id}:events`."""
    return f"{settings.redis_namespace}:run:{request_id}:events"


def status_key(settings: Settings, request_id: uuid.UUID) -> str:
    """`sta:{env}:run:{request_id}:status`."""
    return f"{settings.redis_namespace}:run:{request_id}:status"


def streams_key(settings: Settings, user_id: uuid.UUID) -> str:
    """Counter of a user's currently open streams, for the per-user cap."""
    return f"{settings.redis_namespace}:sse:{user_id}:streams"


def _envelope(
    event_type: str, payload: dict[str, Any], *, correlation_id: str | None
) -> dict[str, str]:
    """The §7 event envelope, flattened for a Redis stream entry.

    `payload` is carried as JSON in one field rather than spread across fields, so a payload key
    can never collide with an envelope key and quietly overwrite `event_type`.
    """
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "producer": PRODUCER,
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "correlation_id": correlation_id or "",
        "payload": json.dumps(payload, separators=(",", ":"), default=str),
    }


async def publish(
    redis: Redis,
    settings: Settings,
    *,
    request_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
) -> str | None:
    """Append one event, validating it first.

    Validation happens on the way in as well as on the way out. An invalid event that is never
    written cannot be read back by a reconnecting client, and catching it here names the code that
    produced it rather than leaving a mystery entry in the stream.

    Returns the stream id, or None if Redis was unavailable. A failed publish never fails the
    request that caused it: the state is in PostgreSQL, and a client that polls still gets the
    truth. Losing a progress event degrades the experience; failing the request loses the run.
    """
    model = SSE_PAYLOAD_MODELS.get(event_type)
    if model is None:
        logger.error(
            "run_event_unknown_type",
            event_type="sse",
            sse_event=event_type,
            request_id=str(request_id),
        )
        return None

    try:
        validated = model.model_validate(payload)
    except ValidationError:
        # The payload, not the exception: a pydantic error message quotes the offending values.
        logger.error(
            "run_event_invalid_payload",
            event_type="sse",
            sse_event=event_type,
            request_id=str(request_id),
        )
        return None

    entry = _envelope(event_type, validated.model_dump(mode="json"), correlation_id=correlation_id)
    key = stream_key(settings, request_id)

    try:
        # redis-py types the field mapping as invariant over its key/value union, so a plain
        # dict[str, str] — which is exactly what it accepts at runtime — does not satisfy it.
        stream_id = await redis.xadd(
            key,
            cast("dict[Any, Any]", entry),
            maxlen=settings.run_event_stream_max_length,
            approximate=True,
        )
        await redis.expire(key, settings.run_event_stream_ttl_seconds)
    except Exception:  # any Redis failure leads to the same decision here
        logger.warning(
            "run_event_not_published",
            event_type="sse",
            sse_event=event_type,
            request_id=str(request_id),
            detail="progress will be reported by polling instead",
        )
        return None

    return str(stream_id)


def decode(entry: dict[Any, Any]) -> tuple[str, dict[str, Any]] | None:
    """Turn a raw stream entry into `(event_type, payload)`, or None if it cannot be trusted.

    Everything that is not exactly what the contract describes is dropped rather than repaired.
    A half-understood event from another service is the case this function exists to stop.
    """
    raw_type = entry.get("event_type")
    raw_payload = entry.get("payload")
    if not isinstance(raw_type, str) or not isinstance(raw_payload, str):
        return None

    model = SSE_PAYLOAD_MODELS.get(raw_type)
    if model is None:
        logger.warning("run_event_dropped_unknown_type", event_type="sse", sse_event=raw_type)
        return None

    try:
        payload = json.loads(raw_payload)
    except ValueError:
        logger.warning("run_event_dropped_unparseable", event_type="sse", sse_event=raw_type)
        return None

    if not isinstance(payload, dict):
        return None

    try:
        validated = model.model_validate(payload)
    except ValidationError:
        # This is the leak guard. An event carrying a field the contract never declared — a
        # provider body, a prompt, a token — fails `extra="forbid"` here and is dropped.
        logger.warning(
            "run_event_dropped_invalid",
            event_type="sse",
            sse_event=raw_type,
            detail="payload did not match the contract for this event",
        )
        return None

    return raw_type, validated.model_dump(mode="json")


def format_sse(event_id: str, event_type: str, payload: dict[str, Any]) -> str:
    """One event as the wire format.

    The `id` is the Redis stream id, which is what makes `Last-Event-ID` work: it is monotonic and
    it is exactly what `read_after` expects back.
    """
    body = json.dumps(payload, separators=(",", ":"), default=str)
    return f"id: {event_id}\nevent: {event_type}\ndata: {body}\n\n"


async def read_after(
    redis: Redis,
    settings: Settings,
    *,
    request_id: uuid.UUID,
    last_id: str,
    block_ms: int,
) -> list[tuple[str, dict[Any, Any]]]:
    """Entries after `last_id`, waiting up to `block_ms` for one to arrive.

    Blocking rather than polling in a loop: it costs one idle connection instead of a busy wait,
    and it means an event reaches the traveller as soon as it is published rather than up to a
    poll interval later.
    """
    key = stream_key(settings, request_id)
    try:
        result = await redis.xread({key: last_id}, count=64, block=block_ms)
    except Exception as exc:  # the caller degrades to heartbeats and polling
        logger.warning(
            "run_event_read_failed",
            event_type="sse",
            request_id=str(request_id),
            error_type=type(exc).__name__,
        )
        return []

    entries: list[tuple[str, dict[Any, Any]]] = []
    for _key, items in result or []:
        for stream_id, fields in items:
            entries.append((str(stream_id), fields))
    return entries


def validate_last_event_id(value: str | None) -> str:
    """Where to resume from.

    A Redis stream id is `<milliseconds>-<sequence>`. Anything else is refused and the stream
    starts from the beginning of what is retained, which is the safe direction: replaying an event
    the client already saw is harmless, and a malformed id must not become an XREAD argument.
    """
    if value is None:
        return "0-0"
    candidate = value.strip()
    if len(candidate) > 64:
        return "0-0"
    parts = candidate.split("-")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return "0-0"
    return candidate
