"""Approved-source ingestion and hybrid retrieval for Phase 5."""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import HashingVectorizer

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
ALLOWED_AUTHORITIES = {"GOVERNMENT", "INTERGOVERNMENTAL", "WHO", "UN"}


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return tuple(value)


@dataclass(frozen=True)
class KnowledgeChunk:
    document_id: str
    text: str
    page: int | None
    section: str | None
    authority: str
    source_url: str
    language: str
    regions: tuple[str, ...]
    hazards: tuple[str, ...]
    effective_at: datetime
    expires_at: datetime
    content_hash: str


async def download_approved_source(source: dict[str, object], allowed_hosts: set[str]) -> bytes:
    url = str(source["source_url"])
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise ValueError("SOURCE_URL_NOT_ALLOWLISTED")
    if (
        source.get("review_status") != "APPROVED"
        or source.get("authority") not in ALLOWED_AUTHORITIES
    ):
        raise ValueError("SOURCE_NOT_APPROVED")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        final = urlparse(str(response.url))
        if final.scheme != "https" or final.hostname not in allowed_hosts:
            raise ValueError("SOURCE_REDIRECT_NOT_ALLOWLISTED")
        content = response.content
    if len(content) > MAX_DOCUMENT_BYTES or not content.startswith(b"%PDF"):
        raise ValueError("SOURCE_TYPE_OR_SIZE_REJECTED")
    expected = str(source["checksum"])
    actual = "sha256:" + hashlib.sha256(content).hexdigest()
    if expected != actual:
        raise ValueError("SOURCE_CHECKSUM_MISMATCH")
    return content


def chunk_pdf(content: bytes, source: dict[str, object]) -> list[KnowledgeChunk]:
    reader = PdfReader(io.BytesIO(content))
    chunks: list[KnowledgeChunk] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = re.sub(r"[ \t]+", " ", page.extract_text() or "").strip()
        if not text:
            continue
        blocks = re.split(r"\n(?=[A-Z0-9][^\n]{2,80}\n|\d+[.)]\s)", text)
        for block in blocks:
            normalized = re.sub(r"\n{3,}", "\n\n", block).strip()
            if not normalized:
                continue
            digest = "sha256:" + hashlib.sha256(normalized.encode()).hexdigest()
            chunks.append(
                KnowledgeChunk(
                    document_id=str(source["document_id"]),
                    text=normalized,
                    page=page_number,
                    section=None,
                    authority=str(source["authority"]),
                    source_url=str(source["source_url"]),
                    language=_strings(source["languages"], "languages")[0],
                    regions=_strings(source["regions"], "regions"),
                    hazards=_strings(source["hazards"], "hazards"),
                    effective_at=datetime.fromisoformat(
                        str(source["effective_at"]).replace("Z", "+00:00")
                    ),
                    expires_at=datetime.fromisoformat(
                        str(source["expires_at"]).replace("Z", "+00:00")
                    ),
                    content_hash=digest,
                )
            )
    return chunks


class HybridRetriever:
    def __init__(self, chunks: list[KnowledgeChunk], model_name: str) -> None:
        self.chunks = chunks
        self.tokens = [chunk.text.lower().split() for chunk in chunks]
        self.bm25 = BM25Okapi(self.tokens)
        if model_name != "multilingual-char-ngram-v1":
            raise ValueError("DENSE_ENCODER_NOT_APPROVED")
        self.encoder = HashingVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), n_features=2048, norm="l2"
        )
        self.vectors = self.encoder.transform([chunk.text for chunk in chunks])

    def search(
        self, query: str, *, region: str, language: str, hazard: str, at: datetime, limit: int = 5
    ) -> list[dict[str, object]]:
        candidates = [
            i
            for i, chunk in enumerate(self.chunks)
            if region in chunk.regions
            and language == chunk.language
            and hazard in chunk.hazards
            and chunk.effective_at <= at <= chunk.expires_at
        ]
        if not candidates:
            return []
        bm25 = self.bm25.get_scores(query.lower().split())
        query_vector = self.encoder.transform([query])
        dense = (self.vectors @ query_vector.T).toarray().ravel()
        ranked = sorted(candidates, key=lambda i: float(bm25[i]) + float(dense[i]), reverse=True)[
            :limit
        ]
        return [
            {
                "document_id": self.chunks[i].document_id,
                "passage": self.chunks[i].text,
                "source_url": self.chunks[i].source_url,
                "page": self.chunks[i].page,
                "section": self.chunks[i].section,
                "authority": self.chunks[i].authority,
                "content_hash": self.chunks[i].content_hash,
                "retrieval_score": float(bm25[i]),
                "rerank_score": float(dense[i]),
            }
            for i in ranked
            if float(dense[i]) >= 0.25
        ]


def resolve_citation(result: dict[str, object]) -> str:
    page = f"#page={result['page']}" if result.get("page") else ""
    return f"{result['source_url']}{page}"


def dense_vector(text: str, *, dimensions: int = 768) -> list[float]:
    encoder = HashingVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), n_features=dimensions, norm="l2"
    )
    return cast(list[float], encoder.transform([text]).toarray()[0].astype(float).tolist())


def qdrant_points(
    chunks: list[KnowledgeChunk], *, dimensions: int = 768
) -> list[dict[str, object]]:
    """Produce deterministic Qdrant points with every citation/filter field retained."""
    return [
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.document_id}:{chunk.content_hash}")),
            "vector": dense_vector(chunk.text, dimensions=dimensions),
            "payload": {
                "document_id": chunk.document_id,
                "passage": chunk.text,
                "page": chunk.page,
                "section": chunk.section,
                "authority": chunk.authority,
                "source_url": chunk.source_url,
                "language": chunk.language,
                "regions": list(chunk.regions),
                "hazards": list(chunk.hazards),
                "effective_at_epoch": chunk.effective_at.timestamp(),
                "expires_at_epoch": chunk.expires_at.timestamp(),
                "content_hash": chunk.content_hash,
            },
        }
        for chunk in chunks
    ]


def evaluate_retrieval(
    retriever: HybridRetriever, cases: list[dict[str, object]], *, at: datetime
) -> dict[str, object]:
    outcomes: list[dict[str, object]] = []
    for case in cases:
        limit_value = case.get("limit", 5)
        if not isinstance(limit_value, int):
            raise ValueError("retrieval evaluation limit must be an integer")
        results = retriever.search(
            str(case["query"]),
            region=str(case["region"]),
            language=str(case["language"]),
            hazard=str(case["hazard"]),
            at=at,
            limit=limit_value,
        )
        expected = case.get("expected_document_id")
        passed = (not results) if expected is None else results[0]["document_id"] == expected
        outcomes.append({"name": case["name"], "passed": passed, "count": len(results)})
    return {
        "passed": all(bool(outcome["passed"]) for outcome in outcomes),
        "cases": outcomes,
    }
