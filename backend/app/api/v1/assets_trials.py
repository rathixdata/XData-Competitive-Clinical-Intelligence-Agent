"""/assets (profiles, detail, timeline), /trials (snapshots, field history, raw), /sources (evidence context)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Page, get_db, page_params, paged, require
from app.api.serialize import redact_provenance, row, rows
from app.core.errors import NotFound, ValidationFailed
from app.core.rbac import Perm
from app.core.security import Principal
from app.entities.graph import neighbours
from app.models import (
    Asset,
    AssetProfileVersion,
    Catalyst,
    ChangeEvent,
    Company,
    DocumentChunk,
    IntelligenceEvent,
    ProfileFieldDefinition,
    Publication,
    RegulatoryEvent,
    SourceDocument,
    SourceSnapshot,
    Trial,
)
from app.services import audit
from app.services.landscapes import create_internal_asset, update_asset_profile
from app.storage.object_store import get_object_store

router = APIRouter(tags=["assets", "trials", "sources"])


# ------------------------------------------------------------------ assets
class AssetIn(BaseModel):
    name: str
    modality: str | None = None
    stage: str | None = None
    owner_company_id: uuid.UUID | None = None
    aliases: list[str] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)


class ProfilePatch(BaseModel):
    profile: dict[str, Any]
    reason: str | None = None


def _validate_profile(db: Session, tenant_id: uuid.UUID, profile: dict[str, Any]) -> None:
    for fd in db.scalars(select(ProfileFieldDefinition).where(ProfileFieldDefinition.tenant_id == tenant_id)).all():
        v = profile.get(fd.key)
        if fd.required and v in (None, "", []):
            raise ValidationFailed(f"profile field '{fd.key}' is required")
        if v is not None and fd.field_type == "enum" and fd.options and v not in fd.options:
            raise ValidationFailed(f"profile field '{fd.key}' must be one of {fd.options}")
        if v is not None and fd.field_type == "number" and not isinstance(v, int | float):
            raise ValidationFailed(f"profile field '{fd.key}' must be numeric")
        if v is not None and fd.field_type == "list" and not isinstance(v, list):
            raise ValidationFailed(f"profile field '{fd.key}' must be a list")


@router.get("/assets")
def list_assets(q: str | None = None, internal: bool | None = None, status: str | None = None,
                page: Page = Depends(page_params), p: Principal = Depends(require(Perm.ENTITY_READ)),
                db: Session = Depends(get_db)) -> dict:
    stmt = select(Asset).where(Asset.merged_into_id.is_(None))
    if q:
        stmt = stmt.where(Asset.canonical_name.ilike(f"%{q}%"))
    if internal is not None:
        stmt = stmt.where(Asset.is_internal.is_(internal))
    if status:
        stmt = stmt.where(Asset.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Asset.is_internal.desc(), Asset.canonical_name).limit(page.limit).offset(page.offset)).all()
    return paged(rows(items), total, page)


@router.post("/assets", status_code=201)
def create_asset(body: AssetIn, p: Principal = Depends(require(Perm.LANDSCAPE_WRITE)), db: Session = Depends(get_db)) -> dict:
    _validate_profile(db, p.tenant_id, body.profile)
    return row(create_internal_asset(db, p.tenant_id, p.actor, body.model_dump()))


@router.get("/assets/{asset_id}")
def asset_detail(asset_id: uuid.UUID, p: Principal = Depends(require(Perm.ENTITY_READ)), db: Session = Depends(get_db)) -> dict:
    """Asset Detail screen: profile, trials, publications, regulatory events, catalysts, timeline."""
    a = db.get(Asset, asset_id)
    if a is None:
        raise NotFound("asset not found")
    comp = db.get(Company, a.owner_company_id) if a.owner_company_id else None
    trials = [t for t in (db.get(Trial, x) for x in neighbours(db, a.id, predicate="evaluated_in")) if t]
    pubs = [x for x in (db.get(Publication, i) for i in neighbours(db, a.id, predicate="mentions", direction="in")) if x]
    regs = db.scalars(select(RegulatoryEvent).where(RegulatoryEvent.asset_id == a.id).order_by(RegulatoryEvent.event_date.desc())).all()
    cats = db.scalars(select(Catalyst).where(or_(Catalyst.asset_id == a.id, Catalyst.trial_id.in_([t.id for t in trials])))
                      .order_by(Catalyst.expected_date.nulls_last())).all()
    events = db.scalars(select(IntelligenceEvent).where(
        IntelligenceEvent.tenant_id == p.tenant_id,
        or_(IntelligenceEvent.asset_id == a.id, IntelligenceEvent.impacted_asset_ids.any(a.id),
            IntelligenceEvent.object_id.in_([t.id for t in trials] or [uuid.uuid4()])))
        .order_by(IntelligenceEvent.detected_at.desc()).limit(50)).all()
    timeline = sorted(
        [{"date": e.detected_at.isoformat(), "kind": "event", "title": e.title, "id": str(e.id), "band": e.band}
         for e in events]
        + [{"date": (r.event_date.isoformat() if r.event_date else None), "kind": "regulatory", "title":
            f"{r.event_type} {r.product_name}", "id": str(r.id)} for r in regs]
        + [{"date": (x.pub_date.isoformat() if x.pub_date else None), "kind": "publication", "title": x.title,
            "id": str(x.id)} for x in pubs],
        key=lambda i: i["date"] or "", reverse=True)
    return {
        "asset": row(a), "company": row(comp) if comp else None,
        "trials": [{**row(t, exclude={"current"}), "primary_endpoints": [o.get("measure") for o in (t.current or {}).get(
            "primary_endpoints", [])]} for t in trials],
        "publications": [redact_provenance(x, platform_admin=p.has(Perm.PLATFORM_ADMIN))
                         for x in rows(pubs, exclude={"abstract"})],
        "regulatory_events": rows(regs), "catalysts": rows(cats),
        "timeline": timeline[:100],
    }


@router.patch("/assets/{asset_id}/profile")
def patch_profile(asset_id: uuid.UUID, body: ProfilePatch, p: Principal = Depends(require(Perm.LANDSCAPE_WRITE)),
                  db: Session = Depends(get_db)) -> dict:
    a = db.get(Asset, asset_id)
    if a is None:
        raise NotFound("asset not found")
    if a.tenant_id is None and not p.has(Perm.PLATFORM_ADMIN) and not p.has(Perm.ENTITY_CURATE):
        raise ValidationFailed("public asset profiles require curator permission")
    if a.is_internal:
        _validate_profile(db, p.tenant_id, {**(a.profile or {}), **body.profile})
    return row(update_asset_profile(db, a, p.actor, body.profile, body.reason, p.tenant_id))


@router.get("/assets/{asset_id}/profile/versions")
def profile_versions(asset_id: uuid.UUID, p: Principal = Depends(require(Perm.ENTITY_READ)), db: Session = Depends(get_db)) -> list[dict]:
    return rows(db.scalars(select(AssetProfileVersion).where(AssetProfileVersion.asset_id == asset_id)
                           .order_by(AssetProfileVersion.version.desc())).all())


class FieldDefIn(BaseModel):
    key: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,59}$")
    label: str
    field_type: str = Field("text", pattern="^(text|number|date|enum|list)$")
    required: bool = False
    options: list[str] = Field(default_factory=list)
    sort_order: int = 0
    description: str | None = None


@router.get("/profile-fields")
def list_fields(p: Principal = Depends(require(Perm.ENTITY_READ)), db: Session = Depends(get_db)) -> list[dict]:
    return rows(db.scalars(select(ProfileFieldDefinition).where(ProfileFieldDefinition.tenant_id == p.tenant_id)
                           .order_by(ProfileFieldDefinition.sort_order)).all())


@router.put("/profile-fields")
def put_fields(body: list[FieldDefIn], p: Principal = Depends(require(Perm.CONFIG_ADMIN)), db: Session = Depends(get_db)) -> list[dict]:
    """Code-free configuration of internal-asset profile fields (FR-LND-003)."""
    existing = {f.key: f for f in db.scalars(select(ProfileFieldDefinition).where(
        ProfileFieldDefinition.tenant_id == p.tenant_id)).all()}
    before = rows(list(existing.values()))
    for f in body:
        rec = existing.pop(f.key, None) or ProfileFieldDefinition(tenant_id=p.tenant_id, key=f.key)
        for k, v in f.model_dump().items():
            setattr(rec, k, v)
        db.add(rec)
    for stale in existing.values():
        db.delete(stale)
    db.flush()
    audit.record(db, action="profile_fields.update", resource_type="profile_fields", tenant_id=p.tenant_id,
                 actor_id=p.actor, before={"fields": before}, after={"fields": [f.model_dump() for f in body]})
    return list_fields(p, db)


# ------------------------------------------------------------------ trials
def _trial(db: Session, ref: str) -> Trial:
    t = db.scalar(select(Trial).where(Trial.nct_id == ref.upper())) if ref.upper().startswith("NCT") else None
    if t is None:
        try:
            t = db.get(Trial, uuid.UUID(ref))
        except ValueError:
            t = None
    if t is None:
        raise NotFound("trial not found")
    return t


@router.get("/trials")
def list_trials(q: str | None = None, page: Page = Depends(page_params), p: Principal = Depends(require(Perm.SOURCE_READ)),
                db: Session = Depends(get_db)) -> dict:
    stmt = select(Trial)
    if q:
        stmt = stmt.where(or_(Trial.nct_id.ilike(f"%{q}%"), Trial.title.ilike(f"%{q}%"), Trial.sponsor_name.ilike(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return paged(rows(db.scalars(stmt.order_by(Trial.updated_at.desc()).limit(page.limit).offset(page.offset)).all(),
                      exclude={"current"}), total, page)


@router.get("/trials/{ref}")
def get_trial(ref: str, p: Principal = Depends(require(Perm.SOURCE_READ)), db: Session = Depends(get_db)) -> dict:
    t = _trial(db, ref)
    return {**row(t), "assets": [row(a, include={"id", "canonical_name", "status", "is_internal"}) for a in
                                 (db.get(Asset, i) for i in neighbours(db, t.id, predicate="evaluated_in", direction="in")) if a]}


@router.get("/trials/{ref}/snapshots")
def trial_snapshots(ref: str, p: Principal = Depends(require(Perm.SOURCE_READ)), db: Session = Depends(get_db)) -> list[dict]:
    t = _trial(db, ref)
    snaps = db.scalars(select(SourceSnapshot).where(SourceSnapshot.object_type == "trial", SourceSnapshot.object_id == t.id)
                       .order_by(SourceSnapshot.version.desc())).all()
    return [row(s, exclude={"normalized"}) for s in snaps]


@router.get("/trials/{ref}/snapshots/{version}")
def trial_snapshot(ref: str, version: int, include_raw: bool = False, p: Principal = Depends(require(Perm.SOURCE_READ)),
                   db: Session = Depends(get_db)) -> dict:
    """Reconstruct a monitored record for any retained snapshot (FR-SRC-002 acceptance)."""
    t = _trial(db, ref)
    s = db.scalar(select(SourceSnapshot).where(SourceSnapshot.object_type == "trial", SourceSnapshot.object_id == t.id,
                                               SourceSnapshot.version == version))
    if s is None:
        raise NotFound("snapshot not found")
    doc = db.get(SourceDocument, s.source_document_id)
    out = {"snapshot": row(s),
           "source_document": redact_provenance(row(doc), platform_admin=p.has(Perm.PLATFORM_ADMIN))}
    if include_raw:
        import json

        store = get_object_store()
        raw = store.get(doc.storage_key)
        out["raw"] = json.loads(raw)
        out["checksum_verified"] = store.verify(doc.storage_key, doc.checksum)
    return out


@router.get("/trials/{ref}/history")
def field_history(ref: str, field: str | None = None, p: Principal = Depends(require(Perm.SOURCE_READ)),
                  db: Session = Depends(get_db)) -> dict:
    """Per-field value history across snapshots (current vs prior with retrieval dates, FR-CHG-001)."""
    t = _trial(db, ref)
    snaps = db.scalars(select(SourceSnapshot).where(SourceSnapshot.object_type == "trial", SourceSnapshot.object_id == t.id)
                       .order_by(SourceSnapshot.version)).all()
    fields = [field] if field else ["status", "phase", "enrollment", "start_date", "primary_completion_date",
                                    "completion_date", "primary_endpoints", "sponsor", "countries"]
    hist: dict[str, list[dict]] = {}
    for f in fields:
        prev = object()
        for s in snaps:
            v = s.normalized.get(f)
            if v != prev:
                hist.setdefault(f, []).append({"value": v, "snapshot_version": s.version, "snapshot_id": str(s.id),
                                               "retrieved_at": s.retrieved_at.isoformat()})
                prev = v
    return {"trial_id": str(t.id), "nct_id": t.nct_id, "history": hist}


@router.get("/trials/{ref}/changes")
def trial_changes(ref: str, include_suppressed: bool = False, p: Principal = Depends(require(Perm.SOURCE_READ)),
                  db: Session = Depends(get_db)) -> list[dict]:
    t = _trial(db, ref)
    stmt = select(ChangeEvent).where(ChangeEvent.object_id == t.id)
    if not include_suppressed:
        stmt = stmt.where(ChangeEvent.suppressed.is_(False))
    return rows(db.scalars(stmt.order_by(ChangeEvent.detected_at.desc())).all())


# ------------------------------------------------------------------ sources / evidence context
@router.get("/sources/documents/{doc_id}")
def source_document(doc_id: uuid.UUID, p: Principal = Depends(require(Perm.SOURCE_READ)), db: Session = Depends(get_db)) -> dict:
    d = db.get(SourceDocument, doc_id)
    if d is None:
        raise NotFound("document not found")
    snaps = db.scalars(select(SourceSnapshot).where(SourceSnapshot.source_document_id == d.id)).all()
    return {**redact_provenance(row(d), platform_admin=p.has(Perm.PLATFORM_ADMIN)),
            "snapshots": [row(s, exclude={"normalized"}) for s in snaps]}


@router.get("/sources/documents/{doc_id}/raw")
def source_raw(doc_id: uuid.UUID, p: Principal = Depends(require(Perm.SOURCE_READ)), db: Session = Depends(get_db)) -> Response:
    d = db.get(SourceDocument, doc_id)
    if d is None:
        raise NotFound("document not found")
    redistribution = (d.rights or {}).get("redistribution", "")
    if redistribution in ("none", "prohibited"):
        raise ValidationFailed("source rights do not permit raw redistribution")
    audit.record(db, action="source.raw_download", resource_type="source_document", resource_id=d.id,
                 tenant_id=p.tenant_id, actor_id=p.actor)
    return Response(get_object_store().get(d.storage_key), media_type=d.content_type,
                    headers={"X-Checksum-SHA256": d.checksum, "X-Retrieved-At": d.retrieved_at.isoformat()})


@router.get("/sources/chunks/{chunk_id}")
def evidence_context(chunk_id: uuid.UUID, window: int = Query(1, ge=0, le=3), p: Principal = Depends(require(Perm.SOURCE_READ)),
                     db: Session = Depends(get_db)) -> dict:
    """Clicking evidence opens the relevant source context (FR-AI-003): chunk + neighbours + document metadata."""
    c = db.get(DocumentChunk, chunk_id)
    if c is None:
        raise NotFound("evidence not found")
    around = db.scalars(select(DocumentChunk).where(
        DocumentChunk.source_document_id == c.source_document_id, DocumentChunk.embedding_model == c.embedding_model,
        DocumentChunk.chunk_index.between(c.chunk_index - window, c.chunk_index + window)).order_by(DocumentChunk.chunk_index)).all()
    d = db.get(SourceDocument, c.source_document_id)
    if c.tenant_id is not None and c.tenant_id != p.tenant_id:
        raise NotFound("evidence not found")
    return {"chunk": row(c, exclude={"embedding", "tsv"}), "context": [
        {"chunk_id": str(x.id), "index": x.chunk_index, "section": x.section, "text": x.text, "is_target": x.id == c.id}
        for x in around], "document": redact_provenance(row(d), platform_admin=p.has(Perm.PLATFORM_ADMIN))}
