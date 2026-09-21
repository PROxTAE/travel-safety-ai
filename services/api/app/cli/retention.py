"""The export and deletion worker.

    docker compose run --rm api python -m app.cli.retention --once

A skeleton, and honest about it. Deleting everything about a person means reaching six other
services' schemas, and none of those services exists yet. So every run records exactly which scopes
it could not reach, and the request carries that list forever after. A status of COMPLETED here
means "everything this service owns", never "erased everywhere" — and the one person entitled to
know the difference is the person who asked.

What it does today, within `identity`:

* **Export** — assembles the profile, the consent history and whether an emergency profile exists.
  The emergency profile's *contents* are included only when the consent that authorised storing
  them is still in force; a withdrawn consent means the data stays sealed until the purge.
* **Delete** — hard-deletes the emergency profile, withdraws every standing consent, and
  soft-deletes the profile. The audit log survives with `user_id` nulled: that an account was
  deleted is a fact worth keeping, and it no longer points at anybody.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import create_engine, create_session_factory, dispose_engine, session_scope
from app.observability.logging import configure_logging, get_logger
from app.repositories import audit, consents, data_subject_requests, emergency_profiles
from app.repositories import user_profiles as profiles_repo
from app.security.envelope import DecryptionFailed
from app.services.encryption import build_cipher
from app.settings import Settings, get_settings

logger = get_logger(__name__)


async def _export(session: AsyncSession, settings: Settings, user_id: Any) -> dict[str, Any]:
    """Everything this service holds about one person, as JSON."""
    profile = await profiles_repo.get_owned(session, owner_id=user_id)
    standing = await consents.list_standing(session, owner_id=user_id)
    emergency_row = await emergency_profiles.get_row(session, owner_id=user_id)

    document: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "identity",
        "profile": None
        if profile is None
        else {
            "user_id": str(profile.id),
            "locale": profile.locale,
            "timezone": profile.timezone,
            "home_country_code": profile.home_country_code,
            "created_at": profile.created_at.isoformat(),
            "updated_at": profile.updated_at.isoformat(),
        },
        "consents": [
            {
                "type": row.type,
                "granted": row.granted,
                "policy_version": row.policy_version,
                "granted_at": row.granted_at.isoformat(),
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in standing
        ],
        "emergency_profile": None,
    }

    if emergency_row is None:
        return document

    # The contents come out only if the consent that authorised storing them still stands. An
    # export must not become the way to read data whose consent was withdrawn.
    consent = await consents.get_effective(
        session, owner_id=user_id, consent_type="EMERGENCY_PROFILE"
    )
    cipher = build_cipher(settings)
    if consent is None or cipher is None:
        document["emergency_profile"] = {
            "present": True,
            "contents_withheld_because": (
                "consent_withdrawn" if consent is None else "encryption_not_configured"
            ),
        }
        return document

    try:
        opened = await emergency_profiles.read(session, owner_id=user_id, cipher=cipher)
    except DecryptionFailed:
        document["emergency_profile"] = {
            "present": True,
            "contents_withheld_because": "undecryptable",
        }
        return document

    document["emergency_profile"] = {"present": True, "contents": opened[0] if opened else None}
    return document


async def _delete(session: AsyncSession, user_id: Any) -> None:
    """Remove what this service owns. Other schemas are reported, not pretended."""
    await emergency_profiles.purge(session, owner_id=user_id)
    await consents.revoke_all(session, owner_id=user_id)

    profile = await profiles_repo.get_owned(session, owner_id=user_id)
    if profile is not None:
        profile.deleted_at = datetime.now(UTC)

    await audit.write(
        session,
        user_id=user_id,
        action=audit.ACTION_ACCOUNT_DELETED,
        resource_type="user_profile",
        resource_id=user_id,
        details={"scope": "identity"},
    )


async def process_one(session: AsyncSession, settings: Settings) -> str | None:
    """Take one request and finish it. Returns its kind, or None when the queue is empty."""
    request = await data_subject_requests.claim_next(session)
    if request is None:
        return None

    user_id = request.user_id
    if user_id is None:
        # The account is already gone. Nothing to do, and saying FAILED would be misleading.
        await data_subject_requests.finish(
            session, request, status=data_subject_requests.STATUS_COMPLETED
        )
        return request.kind

    try:
        if request.kind == data_subject_requests.KIND_EXPORT:
            document = await _export(session, settings, user_id)
            # Written to stdout rather than to a file or an object store: where an export lands is
            # a deployment decision, and inventing one here would mean inventing its access
            # control too. The operator redirects it.
            sys.stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
            await audit.write(
                session,
                user_id=user_id,
                action=audit.ACTION_DATA_EXPORTED,
                resource_type="data_subject_request",
                resource_id=request.id,
                details={"scope": "identity"},
            )
        elif request.kind == data_subject_requests.KIND_DELETE:
            await _delete(session, user_id)
        else:
            await data_subject_requests.finish(
                session,
                request,
                status=data_subject_requests.STATUS_FAILED,
                error_code="UNKNOWN_KIND",
            )
            return request.kind
    except Exception as exc:
        logger.exception(
            "data_subject_request_failed",
            event_type="privacy",
            kind=request.kind,
            exception_type=type(exc).__name__,
        )
        await data_subject_requests.finish(
            session,
            request,
            status=data_subject_requests.STATUS_FAILED,
            error_code=type(exc).__name__,
        )
        return request.kind

    await data_subject_requests.finish(
        session,
        request,
        status=data_subject_requests.STATUS_COMPLETED,
        incomplete_scopes=list(data_subject_requests.UNREACHABLE_SCOPES),
    )
    logger.info(
        "data_subject_request_completed",
        event_type="privacy",
        kind=request.kind,
        incomplete_scopes=",".join(data_subject_requests.UNREACHABLE_SCOPES),
    )
    return request.kind


async def run_once(settings: Settings) -> int:
    """Drain the queue. Returns how many requests were processed."""
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    processed = 0
    try:
        while True:
            # One transaction per request, so a failure on one does not roll back the last.
            async with session_scope(factory) as session:
                kind = await process_one(session, settings)
            if kind is None:
                break
            processed += 1
    finally:
        await dispose_engine(engine)
    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain the queue and exit. The only mode today; a scheduler calls it.",
    )
    parser.parse_args(argv)

    settings = get_settings()
    configure_logging(
        service_name=f"{settings.service_name}-retention",
        environment=settings.app_env,
        version=settings.service_version,
        level=settings.log_level,
    )

    processed = asyncio.run(run_once(settings))
    logger.info("retention_run_finished", event_type="privacy", processed=processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
