"""/feedback, /feedback/datasets, /model-releases (FR-FBK-001/003, FR-MAT-005)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require
from app.api.serialize import row, rows
from app.core.errors import NotFound, ValidationFailed
from app.core.rbac import Perm
from app.core.security import Principal
from app.materiality.tuning import evaluate_thresholds, freeze_dataset, labelled_examples, suggest_thresholds
from app.models import Feedback, FeedbackDataset, IntelligenceEvent, Landscape, ModelRelease
from app.services import audit
from app.services.landscapes import update_landscape

router = APIRouter(tags=["feedback"])

Label = Literal["USEFUL", "NOT_USEFUL", "MATERIAL", "NOT_MATERIAL", "WRONG_MAPPING", "INCORRECT_INTERPRETATION",
                "ALREADY_KNOWN", "ESCALATE"]


class FeedbackIn(BaseModel):
    intel_event_id: uuid.UUID
    label: Label
    reason: str | None = Field(None, max_length=500)
    comment: str | None = Field(None, max_length=4000)
    claim_id: uuid.UUID | None = None


@router.post("/feedback", status_code=201)
def create_feedback(body: FeedbackIn, p: Principal = Depends(require(Perm.FEEDBACK_WRITE)), db: Session = Depends(get_db)) -> dict:
    ev = db.get(IntelligenceEvent, body.intel_event_id)
    if ev is None or ev.tenant_id != p.tenant_id:
        raise NotFound("event not found")
    fb = Feedback(tenant_id=p.tenant_id, user_id=p.user_id, intel_event_id=ev.id, claim_id=body.claim_id,
                  label=body.label, reason=body.reason, comment=body.comment, event_version=ev.version,
                  band_at_feedback=ev.band, score_at_feedback=ev.materiality_score)
    db.add(fb)
    if body.label == "ESCALATE" and ev.status != "escalated":
        ev.status = "escalated"
    db.flush()
    audit.record(db, action="feedback.create", resource_type="feedback", resource_id=fb.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after=row(fb))
    return row(fb)


class FeedbackPatch(BaseModel):
    label: Label | None = None
    reason: str | None = None
    comment: str | None = None


@router.patch("/feedback/{feedback_id}")
def update_feedback(feedback_id: uuid.UUID, body: FeedbackPatch, p: Principal = Depends(require(Perm.FEEDBACK_WRITE)),
                    db: Session = Depends(get_db)) -> dict:
    fb = db.get(Feedback, feedback_id)
    if fb is None or fb.user_id != p.user_id:
        raise NotFound("feedback not found")
    before = row(fb)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(fb, k, v)
    audit.record(db, action="feedback.update", resource_type="feedback", resource_id=fb.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, before=before, after=row(fb))
    return row(fb)


@router.get("/feedback")
def list_feedback(intel_event_id: uuid.UUID | None = None, mine: bool = False, p: Principal = Depends(require(Perm.EVENT_READ)),
                  db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Feedback).where(Feedback.tenant_id == p.tenant_id)
    if intel_event_id:
        stmt = stmt.where(Feedback.intel_event_id == intel_event_id)
    if mine:
        stmt = stmt.where(Feedback.user_id == p.user_id)
    return rows(db.scalars(stmt.order_by(Feedback.created_at.desc()).limit(500)).all())


@router.get("/feedback/tuning-suggestions")
def tuning(landscape_id: uuid.UUID, target_precision: float = 0.8, p: Principal = Depends(require(Perm.TRAINING_DATA)),
           db: Session = Depends(get_db)) -> dict:
    ls = db.get(Landscape, landscape_id)
    if ls is None:
        raise NotFound("landscape not found")
    ex = labelled_examples(db, p.tenant_id, landscape_id)
    return suggest_thresholds(ex, (ls.config or {}).get("band_thresholds"), target_precision)


class DatasetIn(BaseModel):
    name: str = Field(..., max_length=120)
    landscape_id: uuid.UUID | None = None


@router.post("/feedback/datasets", status_code=201)
def create_dataset(body: DatasetIn, p: Principal = Depends(require(Perm.TRAINING_DATA)), db: Session = Depends(get_db)) -> dict:
    ds = freeze_dataset(db, p.tenant_id, body.name, p.actor, body.landscape_id)
    audit.record(db, action="training_dataset.freeze", resource_type="feedback_dataset", resource_id=ds.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, after={"name": ds.name, "version": ds.version,
                                                                   "records": ds.record_count, "hash": ds.content_hash})
    return row(ds, exclude={"records"})


@router.get("/feedback/datasets")
def list_datasets(p: Principal = Depends(require(Perm.TRAINING_DATA)), db: Session = Depends(get_db)) -> list[dict]:
    return rows(db.scalars(select(FeedbackDataset).where(FeedbackDataset.tenant_id == p.tenant_id)
                           .order_by(FeedbackDataset.created_at.desc())).all(), exclude={"records"})


class ReleaseIn(BaseModel):
    component: Literal["materiality_thresholds"] = "materiality_thresholds"
    landscape_id: uuid.UUID
    dataset_id: uuid.UUID
    band_thresholds: dict[str, float]
    version: str


@router.post("/model-releases", status_code=201)
def create_release(body: ReleaseIn, p: Principal = Depends(require(Perm.TRAINING_DATA)), db: Session = Depends(get_db)) -> dict:
    ds = db.get(FeedbackDataset, body.dataset_id)
    ls = db.get(Landscape, body.landscape_id)
    if ds is None or ls is None:
        raise NotFound("dataset or landscape not found")
    evaluation = {"candidate": evaluate_thresholds(ds.records, body.band_thresholds),
                  "current": evaluate_thresholds(ds.records, (ls.config or {}).get("band_thresholds") or {}),
                  "dataset": {"id": str(ds.id), "name": ds.name, "version": ds.version, "hash": ds.content_hash}}
    rel = ModelRelease(tenant_id=p.tenant_id, component=body.component, version=body.version, dataset_id=ds.id,
                       config={"landscape_id": str(ls.id), "band_thresholds": body.band_thresholds}, evaluation=evaluation)
    db.add(rel)
    db.flush()
    audit.record(db, action="model_release.create", resource_type="model_release", resource_id=rel.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, after=row(rel))
    return row(rel)


@router.get("/model-releases")
def list_releases(p: Principal = Depends(require(Perm.TRAINING_DATA)), db: Session = Depends(get_db)) -> list[dict]:
    return rows(db.scalars(select(ModelRelease).where(ModelRelease.tenant_id == p.tenant_id)
                           .order_by(ModelRelease.created_at.desc())).all())


@router.post("/model-releases/{release_id}/promote")
def promote(release_id: uuid.UUID, p: Principal = Depends(require(Perm.CONFIG_ADMIN)), db: Session = Depends(get_db)) -> dict:
    rel = db.get(ModelRelease, release_id)
    if rel is None:
        raise NotFound("release not found")
    if rel.status != "candidate":
        raise ValidationFailed("only candidate releases can be promoted")
    cand = (rel.evaluation or {}).get("candidate", {})
    cur = (rel.evaluation or {}).get("current", {})
    if cand.get("alert_precision") is not None and cur.get("alert_precision") is not None and \
            cand["alert_precision"] + 1e-9 < cur["alert_precision"] - 0.05:
        raise ValidationFailed("evaluation gate: candidate precision regresses by more than 5 points")
    ls = db.get(Landscape, uuid.UUID(rel.config["landscape_id"]))
    update_landscape(db, ls, p.actor, {"config": {"band_thresholds": rel.config["band_thresholds"],
                                                  "thresholds_release": {"id": str(rel.id), "version": rel.version}}},
                     reason=f"promote model release {rel.version}")
    for old in db.scalars(select(ModelRelease).where(ModelRelease.tenant_id == p.tenant_id,
                                                     ModelRelease.component == rel.component,
                                                     ModelRelease.status == "promoted")).all():
        old.status = "retired"
    rel.status, rel.promoted_by, rel.promoted_at = "promoted", p.actor, datetime.now(UTC)
    audit.record(db, action="model_release.promote", resource_type="model_release", resource_id=rel.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, after=row(rel))
    return row(rel)
