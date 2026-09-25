"""Hybrid, authorization-aware retrieval (FR-QA-001, FR-AI-002, Section 11).

Dense (pgvector cosine / HNSW) and lexical (Postgres full-text, OR-semantics) candidate lists are
fused with Reciprocal Rank Fusion, boosted for entity overlap and recency, optionally re-ranked by a
cross-encoder, and diversified (max passages per source document). Every query is constrained to the
caller's tenant (public corpus + own tenant rows) both here and by Postgres RLS.
"""

from __future__ import annotations

import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import Select, and_, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import RETRIEVAL_LATENCY
from app.models import DocumentChunk
from app.rag.embeddings import get_embedder
from app.rag.evidence import SOURCE_LABELS, Evidence

log = get_logger(__name__)
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{1,40}")
_STOP = frozenset(
    ["the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with", "from", "what", "which", "who", "how", "why", "when", "where", "is", "are", "was", "were", "be", "been", "this", "that", "these", "those", "it", "its", "their", "there", "do", "does", "did", "has", "have", "had", "can", "could", "should", "would", "will", "may", "might", "about", "any", "all", "our", "my", "me", "i", "we", "you", "they", "them", "vs", "versus", "than", "into", "over", "under", "more", "most", "less", "least"]
)


@dataclass
class RetrievalQuery:
    text: str
    tenant_id: uuid.UUID
    entity_ids: list[uuid.UUID] = field(default_factory=list)
    object_ids: list[uuid.UUID] = field(default_factory=list)
    sources: list[str] | None = None
    object_types: list[str] | None = None
    published_after: datetime | None = None
    published_before: datetime | None = None
    current_only: bool = True
    top_k: int | None = None
    candidate_k: int | None = None
    max_per_document: int = 3
    require_entity_match: bool = False


def _tsquery_terms(text: str) -> str | None:
    terms = []
    for w in _WORD.findall(text):
        lw = w.lower()
        if lw in _STOP or len(lw) < 2:
            continue
        parts = [p for p in re.split(r"-", lw) if p]
        terms.append(" <-> ".join(parts) if len(parts) > 1 else parts[0])
    terms = list(dict.fromkeys(terms))[:24]
    return " | ".join(f"({t})" for t in terms) if terms else None


class HybridRetriever:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.embedder = get_embedder()

    def _filters(self, q: RetrievalQuery) -> list:
        f = [
            or_(DocumentChunk.tenant_id.is_(None), DocumentChunk.tenant_id == q.tenant_id),
            DocumentChunk.embedding_model == self.embedder.model_name,
        ]
        if q.current_only:
            f.append(DocumentChunk.is_current.is_(True))
        if q.sources:
            f.append(DocumentChunk.source.in_(q.sources))
        if q.object_types:
            f.append(DocumentChunk.object_type.in_(q.object_types))
        if q.published_after:
            f.append(DocumentChunk.published_at >= q.published_after)
        if q.published_before:
            f.append(DocumentChunk.published_at <= q.published_before)
        if q.require_entity_match and (q.entity_ids or q.object_ids):
            ors = []
            if q.entity_ids:
                ors.append(DocumentChunk.entity_ids.overlap(q.entity_ids))
            if q.object_ids:
                ors.append(DocumentChunk.object_id.in_(q.object_ids))
            f.append(or_(*ors))
        return f

    def search(self, q: RetrievalQuery) -> list[Evidence]:
        t0 = time.perf_counter()
        k = q.candidate_k or self.settings.rag_candidate_k
        top_k = q.top_k or self.settings.rag_top_k
        filters = self._filters(q)
        qvec = self.embedder.embed_query(q.text)

        dense: Select = (
            select(DocumentChunk.id.label("id"),
                   func.row_number().over(order_by=DocumentChunk.embedding.cosine_distance(qvec)).label("r"),
                   literal("dense").label("ch"))
            .where(and_(*filters))
            .order_by(DocumentChunk.embedding.cosine_distance(qvec))
            .limit(k)
        )
        parts = [dense]
        tsq = _tsquery_terms(q.text)
        if tsq:
            query = func.to_tsquery("english", tsq)
            rank = func.ts_rank_cd(DocumentChunk.tsv, query, 32)
            lexical = (
                select(DocumentChunk.id.label("id"), func.row_number().over(order_by=rank.desc()).label("r"),
                       literal("lexical").label("ch"))
                .where(and_(*filters), DocumentChunk.tsv.op("@@")(query))
                .order_by(rank.desc())
                .limit(k)
            )
            parts.append(lexical)
        if q.object_ids or q.entity_ids:
            # Structured channel: passages attached to the entities in scope, most recent first.
            ors = []
            if q.object_ids:
                ors.append(DocumentChunk.object_id.in_(q.object_ids))
            if q.entity_ids:
                ors.append(DocumentChunk.entity_ids.overlap(q.entity_ids))
            scoped = (
                select(DocumentChunk.id.label("id"),
                       func.row_number().over(order_by=DocumentChunk.retrieved_at.desc()).label("r"),
                       literal("scoped").label("ch"))
                .where(and_(*filters), or_(*ors))
                .order_by(DocumentChunk.retrieved_at.desc())
                .limit(k)
            )
            parts.append(scoped)
        ranked = self.db.execute(union_all(*parts)).all()

        rrf_k = self.settings.rag_rrf_k
        weights = {"dense": 1.0, "lexical": 1.0, "scoped": 0.6}
        fused: dict[uuid.UUID, float] = {}
        channels: dict[uuid.UUID, set[str]] = {}
        for cid, r, ch in ranked:
            fused[cid] = fused.get(cid, 0.0) + weights[ch] / (rrf_k + r)
            channels.setdefault(cid, set()).add(ch)
        if not fused:
            RETRIEVAL_LATENCY.observe(time.perf_counter() - t0)
            return []
        chunks = {c.id: c for c in self.db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(list(fused)))).all()}
        wanted = set(q.entity_ids) | set(q.object_ids)
        now = datetime.now(UTC)
        scored: list[tuple[float, DocumentChunk]] = []
        for cid, base in fused.items():
            c = chunks.get(cid)
            if c is None:
                continue
            score = base
            if wanted and (wanted & set(c.entity_ids or []) or (c.object_id in wanted)):
                score *= 1.35
            if len(channels[cid]) > 1:
                score *= 1.1
            if c.published_at:
                age_days = max(0.0, (now - c.published_at).days)
                score *= 1.0 + 0.15 * math.exp(-age_days / 180)
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)

        if self.settings.rerank_enabled and self.settings.voyage_api_key:
            scored = self._rerank(q.text, scored[: min(len(scored), 40)])

        per_doc: dict[uuid.UUID, int] = {}
        out: list[Evidence] = []
        for score, c in scored:
            n = per_doc.get(c.source_document_id, 0)
            if n >= q.max_per_document:
                continue
            per_doc[c.source_document_id] = n + 1
            out.append(chunk_to_evidence(c, f"E{len(out) + 1}", score))
            if len(out) >= top_k:
                break
        RETRIEVAL_LATENCY.observe(time.perf_counter() - t0)
        return out

    def _rerank(self, query: str, scored: list[tuple[float, DocumentChunk]]) -> list[tuple[float, DocumentChunk]]:
        try:
            resp = httpx.post(
                "https://api.voyageai.com/v1/rerank",
                headers={"Authorization": f"Bearer {self.settings.voyage_api_key.get_secret_value()}"},  # type: ignore[union-attr]
                json={"query": query, "documents": [c.text for _, c in scored], "model": self.settings.rerank_model,
                      "top_k": len(scored)},
                timeout=20.0,
            )
            resp.raise_for_status()
            order = resp.json()["data"]
            return [(d["relevance_score"], scored[d["index"]][1]) for d in order]
        except Exception as e:  # noqa: BLE001 - reranking is an optimisation; degrade gracefully
            log.warning("rerank_failed", error=str(e))
            return scored


def chunk_to_evidence(c: DocumentChunk, evidence_id: str, score: float = 0.0) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind="passage",
        source=c.source,
        source_type=SOURCE_LABELS.get(c.source, c.source),
        text=c.text,
        source_document_id=str(c.source_document_id),
        snapshot_id=str(c.snapshot_id) if c.snapshot_id else None,
        chunk_id=str(c.id),
        object_type=c.object_type,
        object_id=str(c.object_id) if c.object_id else None,
        uri=c.uri,
        title=c.title,
        section=c.section,
        field_path=c.field_path,
        span=[c.char_start, c.char_end],
        retrieved_at=c.retrieved_at,
        published_at=c.published_at,
        score=score,
        is_current=c.is_current,
        rights=(c.meta or {}).get("rights", {}),
    )
