from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from app.metrics import ARTIFACT_VERIFICATION
from app.repositories.registry import ActiveModel
from app.settings import Settings


class ArtifactUnavailable(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VerifiedArtifact:
    path: Path
    checksum: str
    size_bytes: int


class ArtifactVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def verify(self, model: ActiveModel) -> VerifiedArtifact:
        try:
            return self._verify(model)
        except ArtifactUnavailable as exc:
            ARTIFACT_VERIFICATION.labels("failed", exc.reason).inc()
            raise

    def _verify(self, model: ActiveModel) -> VerifiedArtifact:
        if model.stage != "ACTIVE" or not model.approved_by or not model.approved_at:
            raise ArtifactUnavailable("MODEL_NOT_APPROVED_ACTIVE")
        if model.feature_schema != "1.0.0":
            raise ArtifactUnavailable("FEATURE_SCHEMA_MISMATCH")

        path = self._resolve_path(model.artifact_uri)
        if not path.is_file():
            raise ArtifactUnavailable("ARTIFACT_NOT_FOUND")
        checksum = self._sha256(path)
        if model.checksum != f"sha256:{checksum}":
            raise ArtifactUnavailable("ARTIFACT_CHECKSUM_MISMATCH")
        self._verify_signature(path, model)
        ARTIFACT_VERIFICATION.labels("verified", "OK").inc()
        return VerifiedArtifact(path=path, checksum=model.checksum, size_bytes=path.stat().st_size)

    def _resolve_path(self, artifact_uri: str) -> Path:
        parsed = urlparse(artifact_uri)
        if parsed.scheme not in ("", "file"):
            raise ArtifactUnavailable("ARTIFACT_URI_SCHEME_UNSUPPORTED")
        raw_path = unquote(parsed.path) if parsed.scheme == "file" else artifact_uri
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.settings.artifact_root / candidate
        root = self.settings.artifact_root.resolve()
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise ArtifactUnavailable("ARTIFACT_PATH_OUTSIDE_ROOT")
        return resolved

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_signature(self, path: Path, model: ActiveModel) -> None:
        signature_required = self.settings.artifact_signature_required
        if not model.signature:
            if signature_required:
                raise ArtifactUnavailable("ARTIFACT_SIGNATURE_MISSING")
            return
        if model.signature_algorithm != "ED25519":
            raise ArtifactUnavailable("ARTIFACT_SIGNATURE_ALGORITHM_UNSUPPORTED")
        key_path = self.settings.artifact_public_key_path
        if key_path is None or not key_path.is_file():
            raise ArtifactUnavailable("ARTIFACT_PUBLIC_KEY_UNAVAILABLE")
        key = load_pem_public_key(key_path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ArtifactUnavailable("ARTIFACT_PUBLIC_KEY_TYPE_INVALID")
        try:
            key.verify(model.signature, path.read_bytes())
        except InvalidSignature as exc:
            raise ArtifactUnavailable("ARTIFACT_SIGNATURE_INVALID") from exc
