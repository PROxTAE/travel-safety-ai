from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import FeedbackModel


def pseudonymize_id(raw_id: str, salt: str = "sta-feedback-salt-v1") -> str:
    return hashlib.sha256(f"{raw_id}:{salt}".encode()).hexdigest()[:16]


async def export_feedback_dataset(
    output_path: str,
    status_filter: str | None = None,
    session: AsyncSession | None = None,
) -> int:
    print(f"Exporting reviewed feedback dataset to: {output_path}")
    now = datetime.now(UTC)

    async def _do_export(s: AsyncSession) -> int:
        query = select(FeedbackModel)
        if status_filter:
            query = query.where(FeedbackModel.review_status == status_filter)

        res = await s.execute(query)
        rows = res.scalars().all()

        manifest = {
            "metadata": {
                "exported_at": now.isoformat(),
                "total_records": len(rows),
                "live_online_learning": False,
                "offline_evaluation_only": True,
                "note": (
                    "Governed feedback dataset exported for offline evaluation "
                    "and benchmark analysis."
                ),
            },
            "records": [
                {
                    "feedback_id": str(r.id),
                    "pseudo_user_id": pseudonymize_id(str(r.user_id)),
                    "recommendation_id": str(r.recommendation_id),
                    "category": r.category,
                    "text_redacted": r.text_redacted,
                    "review_status": r.review_status,
                    "safety_review_id": str(r.safety_review_id) if r.safety_review_id else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        print(f" Successfully exported {len(rows)} records to {output_path}.")
        return 0

    if session is not None:
        return await _do_export(session)

    factory = get_session_factory()
    async with factory() as s:
        return await _do_export(s)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export reviewed feedback dataset for offline evaluation."
    )
    parser.add_argument(
        "--output",
        default="feedback_export.json",
        help="Path for output JSON file",
    )
    parser.add_argument(
        "--status",
        default=None,
        help="Optional status filter (e.g. RESOLVED, TRIAGED)",
    )
    args = parser.parse_args()
    code = asyncio.run(export_feedback_dataset(args.output, args.status))
    sys.exit(code)


if __name__ == "__main__":
    main()
