"""/entities: search, resolve, review queue, merge/split, aliases, graph neighbourhood (FR-ENT-*)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.api.deps import Page, get_db, page_params, paged, require
from app.api.serialize import row, rows
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.rbac import Perm
from app.core.security import Principal
from app.entities.graph import neighbourhood, upsert_edge
from app.entities.resolver import CONCEPT_TYPES, EntityResolver, add_alias, model_for, normalize_alias
from app.models import Concept, EntityAlias, EntityLink, Relationship, Trial
from app.services import audit

router = APIRouter(prefix="/entities", tags=["entities"])
EntityType = Literal["company", "asset", "target", "mechanism", "indication", "biomarker", "endpoint", "modality",
                     "line_of_therapy", "conference", "kol"]


def _label(obj) -> str:  # type: ignore[no-untyped-def]
    return getattr(obj, "canonical_name", None) or getattr(obj, "nct_id", None) or str(obj.id)


@router.get("/search")
def search(q: str = Query(..., min_length=2), type: EntityType | None = None, limit: int = Query(20, le=100),
           p: Principal = Depends(require(Perm.ENTITY_READ)), db: Session = Depends(get_db)) -> list[dict]:
    norm = normalize_alias(q)
    sim = func.similarity(EntityAlias.alias_norm, norm)
    stmt = (select(EntityAlias, sim.label("s"))
            .where(or_(EntityAlias.alias_norm.contains(norm), sim > 0.35),
                   or_(EntityAlias.tenant_id.is_(None), EntityAlias.tenant_id == p.tenant_id))
            .order_by(sim.desc()).limit(limit * 3))
    if type:
        stmt = stmt.where(EntityAlias.entity_type == type)
    out: dict[uuid.UUID, dict] = {}
    for alias, s in db.execute(stmt).all():
        if alias.entity_id in out:
            continue
        model = model_for(alias.entity_type)
        obj = db.get(model, alias.entity_id) if model else None
        if obj is None or getattr(obj, "merged_into_id", None):
            continue
        out[alias.entity_id] = {"id": str(alias.entity_id), "type": alias.entity_type, "name": _label(obj),
                                "matched_alias": alias.alias, "score": round(float(s), 3),
                                "status": getattr(obj, "status", None), "private": obj.tenant_id is not None}
    for t in db.scalars(select(Trial).where(or_(Trial.nct_id.ilike(f"%{q}%"), Trial.title.ilike(f"%{q}%"))).limit(10)).all():
        if type in (None,):
            out[t.id] = {"id": str(t.id), "type": "trial", "name": f"{t.nct_id} {t.title[:80]}", "score": 1.0,
                         "status": t.status, "private": False}
    return sorted(out.values(), key=lambda r: -r["score"])[:limit]


class ResolveIn(BaseModel):
    mention: str
    entity_type: EntityType


@router.post("/resolve")
def resolve(body: ResolveIn, p: Principal = Depends(require(Perm.ENTITY_READ)), db: Session = Depends(get_db)) -> dict:
    r = EntityResolver(db, p.tenant_id).resolve(body.mention, body.entity_type)
    return {"mention": r.mention, "entity_type": r.entity_type, "entity_id": str(r.entity_id) if r.entity_id else None,
            "confidence": r.confidence, "method": r.method, "status": r.status, "candidates": r.candidates}


@router.get("/review")
def review_queue(status: str = "pending_review", entity_type: str | None = None, page: Page = Depends(page_params),
                 p: Principal = Depends(require(Perm.ENTITY_READ)), db: Session = Depends(get_db)) -> dict:
    stmt = select(EntityLink).where(EntityLink.status == status)
    if entity_type:
        stmt = stmt.where(EntityLink.entity_type == entity_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = []
    for lk in db.scalars(stmt.order_by(EntityLink.updated_at.desc()).limit(page.limit).offset(page.offset)).all():
        ctx = db.get(Trial, lk.context_id) if lk.context_type == "trial" and lk.context_id else None
        items.append({**row(lk), "context_label": f"{ctx.nct_id} {ctx.title[:60]}" if ctx else None})
    return paged(items, total, page)


class ReviewDecision(BaseModel):
    decision: Literal["approve", "reject"]
    entity_id: uuid.UUID | None = Field(None, description="Target entity when approving (defaults to proposed)")
    reason: str | None = None
    scope: Literal["tenant", "global"] = "tenant"


@router.post("/review/{link_id}")
def decide(link_id: uuid.UUID, body: ReviewDecision, p: Principal = Depends(require(Perm.ENTITY_CURATE)),
           db: Session = Depends(get_db)) -> dict:
    """Approve/reject a machine-proposed match. Decisions are audited and reused by the resolver (FR-ENT-005)."""
    lk = db.get(EntityLink, link_id)
    if lk is None:
        raise NotFound("link not found")
    if body.scope == "global" and not p.has(Perm.PLATFORM_ADMIN):
        raise Forbidden("global curation requires platform administrator")
    tenant_scope = None if body.scope == "global" else p.tenant_id
    target = body.entity_id or lk.entity_id
    if body.decision == "approve" and target is None:
        raise ValidationFailed("entity_id required to approve an unresolved mention")
    before = row(lk)
    now = datetime.now(UTC)
    if lk.tenant_id == tenant_scope:
        decision_link = lk
    else:
        # Tenant decisions on public links are stored as tenant-scoped overrides (never mutate shared rows).
        decision_link = EntityLink(tenant_id=tenant_scope, mention=lk.mention, mention_norm=lk.mention_norm,
                                   entity_type=lk.entity_type, context_type=lk.context_type, context_id=lk.context_id,
                                   method="analyst", confidence=1.0, status="pending_review", candidates=lk.candidates)
        db.add(decision_link)
    decision_link.status = "approved" if body.decision == "approve" else "rejected"
    decision_link.entity_id = target
    decision_link.method, decision_link.confidence = "analyst", 1.0 if body.decision == "approve" else 0.0
    decision_link.reviewed_by, decision_link.reviewed_at, decision_link.review_reason = p.actor, now, body.reason
    db.flush()
    if body.decision == "approve":
        add_alias(db, entity_type=lk.entity_type, entity_id=target, alias=lk.mention, source="analyst",
                  tenant_id=tenant_scope, created_by=p.actor)
        if lk.context_type == "trial" and lk.context_id and lk.entity_type == "asset":
            upsert_edge(db, subject_type="asset", subject_id=target, predicate="evaluated_in", object_type="trial",
                        object_id=lk.context_id, tenant_id=tenant_scope, method="analyst")
    audit.record(db, action=f"entity.review_{body.decision}", resource_type="entity_link", resource_id=lk.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, before=before, after=row(decision_link), reason=body.reason)
    return row(decision_link)


class AliasIn(BaseModel):
    alias: str
    alias_type: Literal["dev_code", "generic", "brand", "legacy", "abbreviation", "spelling", "synonym"] = "synonym"
    reason: str | None = None


@router.post("/{entity_type}/{entity_id}/aliases", status_code=201)
def add_entity_alias(entity_type: EntityType, entity_id: uuid.UUID, body: AliasIn,
                     p: Principal = Depends(require(Perm.ENTITY_CURATE)), db: Session = Depends(get_db)) -> dict:
    model = model_for(entity_type)
    if model is None or db.get(model, entity_id) is None:
        raise NotFound("entity not found")
    a = add_alias(db, entity_type=entity_type, entity_id=entity_id, alias=body.alias, alias_type=body.alias_type,
                  source="analyst", tenant_id=p.tenant_id, created_by=p.actor)
    audit.record(db, action="entity.alias_add", resource_type=entity_type, resource_id=entity_id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after={"alias": body.alias, "alias_type": body.alias_type}, reason=body.reason)
    return row(a)


@router.delete("/aliases/{alias_id}", status_code=204)
def remove_alias(alias_id: uuid.UUID, reason: str | None = None, p: Principal = Depends(require(Perm.ENTITY_CURATE)),
                 db: Session = Depends(get_db)) -> None:
    a = db.get(EntityAlias, alias_id)
    if a is None:
        raise NotFound("alias not found")
    if a.tenant_id is None and not p.has(Perm.PLATFORM_ADMIN):
        raise Forbidden("public aliases can only be removed by platform administrators")
    audit.record(db, action="entity.alias_remove", resource_type=a.entity_type, resource_id=a.entity_id,
                 tenant_id=p.tenant_id, actor_id=p.actor, before=row(a), reason=reason)
    db.delete(a)


class MergeIn(BaseModel):
    entity_type: EntityType
    source_id: uuid.UUID
    target_id: uuid.UUID
    reason: str


def _check_owned(p: Principal, obj) -> None:  # type: ignore[no-untyped-def]
    if obj.tenant_id is None and not p.has(Perm.PLATFORM_ADMIN):
        raise Forbidden("public entities can only be merged/split by platform administrators; "
                        "propose the correction via the review queue")
    if obj.tenant_id is not None and obj.tenant_id != p.tenant_id:
        raise NotFound("entity not found")


@router.post("/merge")
def merge(body: MergeIn, p: Principal = Depends(require(Perm.ENTITY_CURATE)), db: Session = Depends(get_db)) -> dict:
    model = model_for(body.entity_type)
    src, tgt = db.get(model, body.source_id), db.get(model, body.target_id)
    if src is None or tgt is None or src.id == tgt.id:
        raise ValidationFailed("invalid merge pair")
    _check_owned(p, src)
    db.execute(update(EntityAlias).where(EntityAlias.entity_id == src.id).values(entity_id=tgt.id))
    db.execute(update(EntityLink).where(EntityLink.entity_id == src.id).values(entity_id=tgt.id))
    db.execute(update(Relationship).where(Relationship.subject_id == src.id).values(subject_id=tgt.id))
    db.execute(update(Relationship).where(Relationship.object_id == src.id).values(object_id=tgt.id))
    src.merged_into_id = tgt.id
    if hasattr(src, "status"):
        src.status = "merged"
    audit.record(db, action="entity.merge", resource_type=body.entity_type, resource_id=src.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, before={"source": row(src)}, after={"merged_into": str(tgt.id)}, reason=body.reason)
    return {"merged": str(src.id), "into": str(tgt.id)}


class SplitIn(BaseModel):
    entity_type: EntityType
    entity_id: uuid.UUID
    new_name: str
    alias_ids: list[uuid.UUID] = Field(..., min_length=1)
    reason: str


@router.post("/split")
def split(body: SplitIn, p: Principal = Depends(require(Perm.ENTITY_CURATE)), db: Session = Depends(get_db)) -> dict:
    model = model_for(body.entity_type)
    orig = db.get(model, body.entity_id)
    if orig is None:
        raise NotFound("entity not found")
    _check_owned(p, orig)
    kwargs = {"canonical_name": body.new_name, "tenant_id": orig.tenant_id}
    if model is Concept:
        kwargs["kind"] = body.entity_type
    new = model(**kwargs)
    db.add(new)
    db.flush()
    moved = 0
    for aid in body.alias_ids:
        a = db.get(EntityAlias, aid)
        if a is None or a.entity_id != orig.id:
            raise ValidationFailed(f"alias {aid} does not belong to entity")
        a.entity_id = new.id
        moved += 1
    db.execute(update(EntityLink).where(EntityLink.entity_id == orig.id, EntityLink.mention_norm.in_(
        select(EntityAlias.alias_norm).where(EntityAlias.entity_id == new.id))).values(entity_id=new.id))
    audit.record(db, action="entity.split", resource_type=body.entity_type, resource_id=orig.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after={"new_entity": str(new.id), "aliases_moved": moved}, reason=body.reason)
    return {"new_entity_id": str(new.id), "aliases_moved": moved}


@router.get("/{entity_id}/graph")
def entity_graph(entity_id: uuid.UUID, depth: int = Query(1, ge=1, le=3), p: Principal = Depends(require(Perm.ENTITY_READ)),
                 db: Session = Depends(get_db)) -> dict:
    return neighbourhood(db, entity_id, depth=depth)


@router.get("/{entity_type}/{entity_id}")
def get_entity(entity_type: EntityType, entity_id: uuid.UUID, p: Principal = Depends(require(Perm.ENTITY_READ)),
               db: Session = Depends(get_db)) -> dict:
    model = model_for(entity_type)
    obj = db.get(model, entity_id) if model else None
    if obj is None:
        raise NotFound("entity not found")
    aliases = db.scalars(select(EntityAlias).where(EntityAlias.entity_id == entity_id)).all()
    links = db.scalars(select(EntityLink).where(EntityLink.entity_id == entity_id).limit(50)).all()
    return {"entity": row(obj), "type": entity_type, "aliases": rows(aliases), "recent_links": rows(links)}


@router.get("/kinds")
def kinds(p: Principal = Depends(require(Perm.ENTITY_READ))) -> dict:
    return {"entity_types": ["company", "asset", "trial", *sorted(CONCEPT_TYPES)]}

