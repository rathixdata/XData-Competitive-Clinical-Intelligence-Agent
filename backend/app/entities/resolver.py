"""Entity resolution (FR-ENT-002/004/005).

Resolution order for a mention:
1. Analyst decisions (approved / rejected) for the same normalized mention are honoured first -
   corrections are reused in future resolution.
2. Exact alias match (after normalization) -> high confidence auto-link, unless the alias is shared by
   several canonical entities (ambiguous -> review).
3. Fuzzy match (pg_trgm candidates re-scored with rapidfuzz). Development codes (e.g. "XD-101") never
   fuzzy-auto-link - "XD-101" vs "XD-102" is a different molecule.
4. Links scoring below the auto-link threshold are never silently promoted: they enter review.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Asset, Company, Concept, EntityAlias, EntityLink

AUTO_LINK_THRESHOLD = 0.92
REVIEW_THRESHOLD = 0.72
MIN_MARGIN = 0.04

_STRIP_MARKS = re.compile(r"[®™©]")
_PUNCT = re.compile(r"[\-_/.,;:()\[\]{}'\"+&]")
_WS = re.compile(r"\s+")
_DEV_CODE = re.compile(r"^[a-z]{1,6}\s?-?\s?\d{2,7}[a-z]?$", re.I)
_CORP_SUFFIX = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|plc|ag|sa|nv|gmbh|kk|bv|holdings?|group)\b"
)

CONCEPT_TYPES = {"target", "mechanism", "indication", "biomarker", "endpoint", "modality", "line_of_therapy",
                 "conference", "kol"}


def normalize_alias(text: str, entity_type: str | None = None) -> str:
    s = unicodedata.normalize("NFKC", text or "").lower()
    s = _STRIP_MARKS.sub("", s)
    s = _PUNCT.sub(" ", s)
    if entity_type == "company":
        s = _CORP_SUFFIX.sub(" ", s)
    return _WS.sub(" ", s).strip()


def compact(norm: str) -> str:
    return norm.replace(" ", "")


def is_dev_code(text: str) -> bool:
    return bool(_DEV_CODE.match((text or "").strip()))


@dataclass
class Resolution:
    mention: str
    entity_type: str
    entity_id: uuid.UUID | None
    confidence: float
    method: str
    status: str  # auto_linked | pending_review | unresolved | approved
    candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def linked(self) -> bool:
        return self.entity_id is not None and self.status in ("auto_linked", "approved")


def _visible(stmt, model, tenant_id: uuid.UUID | None):  # type: ignore[no-untyped-def]
    if tenant_id is None:
        return stmt.where(model.tenant_id.is_(None))
    return stmt.where(or_(model.tenant_id.is_(None), model.tenant_id == tenant_id))


def _alias_entity_type(entity_type: str) -> str:
    return entity_type


class EntityResolver:
    def __init__(self, db: Session, tenant_id: uuid.UUID | None = None,
                 auto_threshold: float = AUTO_LINK_THRESHOLD, review_threshold: float = REVIEW_THRESHOLD):
        self.db = db
        self.tenant_id = tenant_id
        self.auto_threshold = auto_threshold
        self.review_threshold = review_threshold
        self._cache: dict[tuple[str, str], Resolution] = {}

    # ------------------------------------------------------------------ core
    def resolve(self, mention: str, entity_type: str) -> Resolution:
        norm = normalize_alias(mention, entity_type)
        key = (entity_type, norm)
        if key in self._cache:
            return self._cache[key]
        res = self._resolve(mention, norm, entity_type)
        self._cache[key] = res
        return res

    def _decisions(self, norm: str, entity_type: str) -> tuple[uuid.UUID | None, set[uuid.UUID]]:
        stmt = select(EntityLink).where(
            EntityLink.mention_norm == norm,
            EntityLink.entity_type == entity_type,
            EntityLink.status.in_(("approved", "rejected")),
        )
        rows = self.db.scalars(_visible(stmt, EntityLink, self.tenant_id)).all()
        approved = None
        rejected: set[uuid.UUID] = set()
        # tenant decisions override global decisions
        for r in sorted(rows, key=lambda r: (r.tenant_id is not None, r.reviewed_at or datetime.min.replace(tzinfo=UTC))):
            if r.status == "approved" and r.entity_id:
                approved = r.entity_id
                rejected.discard(r.entity_id)
            elif r.status == "rejected" and r.entity_id:
                rejected.add(r.entity_id)
                if approved == r.entity_id:
                    approved = None
        return approved, rejected

    def _resolve(self, mention: str, norm: str, entity_type: str) -> Resolution:
        if not norm:
            return Resolution(mention, entity_type, None, 0.0, "none", "unresolved")
        approved, rejected = self._decisions(norm, entity_type)
        if approved and self._is_active(entity_type, approved):
            return Resolution(mention, entity_type, approved, 1.0, "analyst", "approved")

        cmp = compact(norm)
        stmt = select(EntityAlias).where(
            EntityAlias.entity_type == _alias_entity_type(entity_type),
            or_(EntityAlias.alias_norm == norm, func.replace(EntityAlias.alias_norm, " ", "") == cmp),
        )
        exact = [a for a in self.db.scalars(_visible(stmt, EntityAlias, self.tenant_id)).all()
                 if a.entity_id not in rejected and self._is_active(entity_type, a.entity_id)]
        ids = {a.entity_id for a in exact}
        if len(ids) == 1:
            a = max(exact, key=lambda x: x.confidence)
            method = "exact_alias" if a.alias_norm == norm else "normalized_alias"
            conf = min(1.0, a.confidence * (0.99 if method == "exact_alias" else 0.96))
            status = "auto_linked" if conf >= self.auto_threshold else "pending_review"
            return Resolution(mention, entity_type, a.entity_id, round(conf, 3), method, status,
                              [{"entity_id": str(a.entity_id), "alias": a.alias, "score": round(conf, 3)}])
        if len(ids) > 1:
            cands = [{"entity_id": str(a.entity_id), "alias": a.alias, "score": 0.9} for a in exact]
            return Resolution(mention, entity_type, None, 0.5, "ambiguous_alias", "pending_review", cands)

        # fuzzy
        sim = func.similarity(EntityAlias.alias_norm, norm)
        stmt = (
            select(EntityAlias, sim.label("sim"))
            .where(EntityAlias.entity_type == _alias_entity_type(entity_type), sim > 0.3)
            .order_by(sim.desc())
            .limit(15)
        )
        rows = self.db.execute(_visible(stmt, EntityAlias, self.tenant_id)).all()
        best: dict[uuid.UUID, tuple[float, str]] = {}
        for alias, _s in rows:
            if alias.entity_id in rejected or not self._is_active(entity_type, alias.entity_id):
                continue
            score = max(fuzz.token_set_ratio(norm, alias.alias_norm), fuzz.ratio(cmp, compact(alias.alias_norm))) / 100
            score *= alias.confidence
            if score > best.get(alias.entity_id, (0.0, ""))[0]:
                best[alias.entity_id] = (score, alias.alias)
        ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)
        cands = [{"entity_id": str(eid), "alias": al, "score": round(sc, 3)} for eid, (sc, al) in ranked[:5]]
        if not ranked:
            return Resolution(mention, entity_type, None, 0.0, "none", "unresolved")
        top_id, (top, _) = ranked[0]
        margin = top - (ranked[1][1][0] if len(ranked) > 1 else 0.0)
        # token_set_ratio rewards subset matches ("cancer" vs "lung cancer"); penalise large length gaps
        if is_dev_code(mention):
            # dev codes must match exactly - never auto-link fuzzily
            top = min(top, self.auto_threshold - 0.01)
        if top >= self.auto_threshold and margin >= MIN_MARGIN:
            return Resolution(mention, entity_type, top_id, round(top, 3), "fuzzy", "auto_linked", cands)
        if top >= self.review_threshold:
            return Resolution(mention, entity_type, top_id, round(top, 3), "fuzzy", "pending_review", cands)
        return Resolution(mention, entity_type, None, round(top, 3), "fuzzy", "unresolved", cands)

    def _is_active(self, entity_type: str, entity_id: uuid.UUID) -> bool:
        model = model_for(entity_type)
        if model is None:
            return True
        obj = self.db.get(model, entity_id)
        return obj is not None and getattr(obj, "merged_into_id", None) is None

    # ------------------------------------------------------------- persistence
    def record_link(self, res: Resolution, context_type: str | None, context_id: uuid.UUID | None) -> EntityLink:
        norm = normalize_alias(res.mention, res.entity_type)
        stmt = select(EntityLink).where(
            EntityLink.mention_norm == norm,
            EntityLink.entity_type == res.entity_type,
            EntityLink.context_type == context_type,
            EntityLink.context_id == context_id,
            EntityLink.tenant_id.is_(None) if self.tenant_id is None else EntityLink.tenant_id == self.tenant_id,
        )
        link = self.db.scalar(stmt)
        if link is not None and link.status in ("approved", "rejected"):
            return link
        if link is None:
            link = EntityLink(tenant_id=self.tenant_id, mention=res.mention[:300], mention_norm=norm[:300],
                              entity_type=res.entity_type, context_type=context_type, context_id=context_id)
            self.db.add(link)
        link.entity_id = res.entity_id
        link.confidence = res.confidence
        link.method = res.method
        link.status = res.status if res.status != "approved" else "auto_linked"
        link.candidates = res.candidates
        self.db.flush()
        return link


def model_for(entity_type: str):  # type: ignore[no-untyped-def]
    if entity_type == "company":
        return Company
    if entity_type == "asset":
        return Asset
    if entity_type in CONCEPT_TYPES:
        return Concept
    return None


def add_alias(db: Session, *, entity_type: str, entity_id: uuid.UUID, alias: str, alias_type: str = "synonym",
              source: str = "seed", confidence: float = 1.0, tenant_id: uuid.UUID | None = None,
              created_by: str | None = None) -> EntityAlias | None:
    norm = normalize_alias(alias, entity_type)
    if not norm:
        return None
    existing = db.scalar(select(EntityAlias).where(
        EntityAlias.entity_type == entity_type, EntityAlias.alias_norm == norm, EntityAlias.entity_id == entity_id,
        EntityAlias.tenant_id.is_(None) if tenant_id is None else EntityAlias.tenant_id == tenant_id))
    if existing:
        return existing
    a = EntityAlias(entity_type=entity_type, entity_id=entity_id, alias=alias[:300], alias_norm=norm[:300],
                    alias_type=alias_type, source=source, confidence=confidence, tenant_id=tenant_id,
                    created_by=created_by)
    db.add(a)
    db.flush()
    return a
