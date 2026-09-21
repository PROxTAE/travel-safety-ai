from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.repositories.registry import ActiveModel
from app.risk.artifact_loader import ArtifactUnavailable, ArtifactVerifier
from app.settings import Settings


def _record(path: Path, checksum: str, signature: bytes | None) -> ActiveModel:
    return ActiveModel(
        id=uuid4(),
        name="route-risk-baseline",
        version="1.0.0",
        stage="ACTIVE",
        feature_schema="1.0.0",
        artifact_uri=path.name,
        checksum=checksum,
        signature=signature,
        signature_algorithm="ED25519" if signature else None,
        signature_key_id="test-key" if signature else None,
        approved_by="safety-reviewer",
        approved_at=datetime.now(UTC),
    )


def test_verified_active_signed_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"verified deterministic artifact")
    private_key = Ed25519PrivateKey.generate()
    public_key_path = tmp_path / "public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    checksum = f"sha256:{hashlib.sha256(artifact.read_bytes()).hexdigest()}"
    signature = private_key.sign(artifact.read_bytes())
    settings = Settings(
        RISK_KNOWLEDGE_ARTIFACT_ROOT=tmp_path,
        RISK_KNOWLEDGE_ARTIFACT_PUBLIC_KEY_PATH=public_key_path,
    )
    verified = ArtifactVerifier(settings).verify(_record(artifact, checksum, signature))
    assert verified.checksum == checksum
    assert verified.path == artifact


def test_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"tampered")
    settings = Settings(
        RISK_KNOWLEDGE_ARTIFACT_ROOT=tmp_path,
        RISK_KNOWLEDGE_REQUIRE_ARTIFACT_SIGNATURE=False,
    )
    with pytest.raises(ArtifactUnavailable, match="ARTIFACT_CHECKSUM_MISMATCH"):
        ArtifactVerifier(settings).verify(_record(artifact, "sha256:" + "0" * 64, None))


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.bin"
    outside.write_bytes(b"outside")
    record = replace(
        _record(outside, "sha256:" + hashlib.sha256(b"outside").hexdigest(), None),
        artifact_uri=str(outside),
    )
    settings = Settings(
        RISK_KNOWLEDGE_ARTIFACT_ROOT=tmp_path,
        RISK_KNOWLEDGE_REQUIRE_ARTIFACT_SIGNATURE=False,
    )
    with pytest.raises(ArtifactUnavailable, match="ARTIFACT_PATH_OUTSIDE_ROOT"):
        ArtifactVerifier(settings).verify(record)
