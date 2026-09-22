from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models import Base


# Use SQLite in-memory for fast unit/contract testing
@pytest_asyncio.fixture
async def test_db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        execution_options={"schema_translate_map": {"recommendation": None}},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def sample_decision() -> dict[str, Any]:
    return {
        "decision_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "snapshot_id": str(uuid.uuid4()),
        "action_code": "NORMAL",
        "risk_level": "LOW",
        "confidence": 0.95,
        "selected_route_id": str(uuid.uuid4()),
        "rules_fired": ["NO_CRITICAL_HAZARDS", "WEATHER_OPTIMAL"],
        "escalation_required": False,
        "summary": "The route is clear and travel can proceed normally.",
        "reasons": [
            {
                "code": "WEATHER_OPTIMAL",
                "message": "Mild conditions throughout travel corridor.",
                "severity": "INFO",
                "evidence_ids": [],
            }
        ],
        "immediate_actions": [],
        "citations": [],
        "limitations": [],
        "versions": {
            "policy": "1.0.0",
            "prompt": "1.0.0",
            "llm_model": "gpt-4o-mini",
            "contract": "1.0.0",
        },
        "validation": {
            "schema": True,
            "citations": True,
            "locked_action": True,
        },
        "created_at": datetime.now(UTC).isoformat(),
    }


@pytest.fixture
def sample_context(sample_decision: dict[str, Any]) -> dict[str, Any]:
    route_id = sample_decision["selected_route_id"]
    now = datetime.now(UTC)
    return {
        "country_code": "TH",
        "subdivision": None,
        "routes": [
            {
                "route_id": route_id,
                "provider_route_id": "ors-12345",
                "label": "RECOMMENDED",
                "mode": "CAR",
                "distance_m": 120000,
                "duration_seconds": 5400,
                "exposure": {"score": 0.1, "closed": False},
                "risk_level": "LOW",
                "sources": [],
            }
        ],
        "alerts": [],
        "emergency_instructions": [],
        "sources": [
            {
                "source_id": str(uuid.uuid4()),
                "provider": "open_meteo",
                "authority": "OFFICIAL",
                "source_url": "https://api.open-meteo.com",
                "observed_at": (now - timedelta(minutes=10)).isoformat(),
                "fetched_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=2)).isoformat(),
            }
        ],
        "observed_at": (now - timedelta(minutes=10)).isoformat(),
        "expires_at": (now + timedelta(hours=2)).isoformat(),
        "degraded_services": [],
    }
