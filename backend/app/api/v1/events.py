"""/events: intelligence feed, detail, triage, editorial override (FR-UX-002/006, FR-FBK-002, FR-MAT-004/006)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.explain import explain_event
from app.api.deps import Page, get_db, page_params, paged, require
from app.api.serialize import row, rows
from app.core.errors import NotFound, ValidationFailed
from app.core.rbac import Perm
from app.core.security import Principal
from app.entities.resolver import normalize_alias
from app.models import (
    ChangeEvent,
    Claim,
    Feedback,
    GeneratedArtifact,
    IntelligenceEvent,
    Notification,
    SourceDocument,
    SourceSnapshot,
    Watchlist,
    WatchlistItem,
)
from app.services import audit

router = APIRouter(prefix="/events", tags=["events"])

SORTS = {
    "score": IntelligenceEvent.materiality_score.desc(),
    "-score": IntelligenceEvent.materiality_score.asc(),
    "date": IntelligenceEvent.detected_at.desc(),
    "-date": IntelligenceEvent.detected_at.asc(),
}


def _watched_ids(db: Session, p: Principal) -> set[uuid.UUID]:
    wl = select(Watchlist.id).where(or_(Watchlist.owner_id == p.user_id, Watchlist.visibility == "tenant"))
    return {i for i in db.scalars(select(WatchlistItem.entity_id).where(WatchlistItem.watchlist_id.in_(wl))).all() if i}


@router.get("")
def feed(
    landscape_id: uuid.UUID | None = None,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    min_score: float | None = Query(None, ge=0, le=100),
    max_score: float | None = Query(None, ge=0, le=100),
    band: list[str] = Query(default_factory=list),
    event_type: list[str] = Query(default_factory=list),
    source: list[str] = Query(default_factory=list),
    status: list[str] = Query(default_factory=list),
    company_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    impacted_asset_id: uuid.UUID | None = None,
    mechanism: str | None = None,
    indication: str | None = None,
    q: str | None = None,
    sort: Literal["score", "-score", "date", "-date"] = "date",
    personalize: bool = False,
    include_archived: bool = False,
    page: Page = Depends(page_params),
    p: Principal = Depends(require(Perm.EVENT_READ)),
    db: Session = Depends(get_db),
) -> dict:
    """All filters are plain query parameters so any feed state is bookmarkable/shareable (FR-UX-002)."""
    stmt = select(IntelligenceEvent).where(IntelligenceEvent.tenant_id == p.tenant_id)
    if landscape_id:
        stmt = stmt.where(IntelligenceEvent.landscape_id == landscape_id)
    if date_from:
        stmt = stmt.where(IntelligenceEvent.detected_at >= date_from)
    if date_to:
        stmt = stmt.where(IntelligenceEvent.detected_at <= date_to)
    if min_score is not None:
        stmt = stmt.where(IntelligenceEvent.materiality_score >= min_score)
    if max_score is not None:
        stmt = stmt.where(IntelligenceEvent.materiality_score <= max_score)
    if band:
        stmt = stmt.where(IntelligenceEvent.band.in_(band))
    if event_type:
        stmt = stmt.where(or_(IntelligenceEvent.primary_type.in_(event_type),
                              IntelligenceEvent.secondary_tags.overlap(event_type)))
    if source:
        stmt = stmt.where(IntelligenceEvent.source.in_(source))
    if status:
        stmt = stmt.where(IntelligenceEvent.status.in_(status))
    elif not include_archived:
        stmt = stmt.where(IntelligenceEvent.status != "archived")
    if company_id:
        stmt = stmt.where(IntelligenceEvent.company_id == company_id)
    if asset_id:
        stmt = stmt.where(or_(IntelligenceEvent.asset_id == asset_id, IntelligenceEvent.related_entity_ids.any(asset_id)))
    if impacted_asset_id:
        stmt = stmt.where(IntelligenceEvent.impacted_asset_ids.any(impacted_asset_id))
    if mechanism:
        m = normalize_alias(mechanism)
        stmt = stmt.where(or_(IntelligenceEvent.facet_terms.any(f"mechanism:{m}"), IntelligenceEvent.facet_terms.any(f"target:{m}")))
    if indication:
        stmt = stmt.where(IntelligenceEvent.facet_terms.any(f"indication:{normalize_alias(indication)}"))
    if q:
        stmt = stmt.where(IntelligenceEvent.title.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(SORTS[sort], IntelligenceEvent.id).limit(page.limit).offset(page.offset)).all()
    out = [row(e, exclude={"fingerprint", "score_components"}) | {"model_confidence": (e.score_components or {}).get("model_confidence")}
           for e in items]
    if personalize:
        # Ranking-only personalisation (FR-MAT-006): never changes facts or scores.
        watched = _watched_ids(db, p)
        for o, e in zip(out, items, strict=True):
            hit = bool(watched & {e.object_id, e.asset_id, e.company_id, *(e.related_entity_ids or [])})
            o["personal_boost"] = 10 if hit else 0
        out.sort(key=lambda o: -(o["materiality_score"] + o["personal_boost"]))
    return paged(out, total, page)


@router.get("/facets")
def facets(landscape_id: uuid.UUID | None = None, p: Principal = Depends(require(Perm.EVENT_READ)),
           db: Session = Depends(get_db)) -> dict:
    stmt = select(func.unnest(IntelligenceEvent.facet_terms).label("t"), func.count()).where(
        IntelligenceEvent.tenant_id == p.tenant_id)
    if landscape_id:
        stmt = stmt.where(IntelligenceEvent.landscape_id == landscape_id)
    res: dict[str, list[dict]] = {}
    for term, n in db.execute(stmt.group_by("t").order_by(func.count().desc()).limit(400)).all():
        kind, _, val = term.partition(":")
        res.setdefault(kind, []).append({"value": val, "count": n})
    return res


def _get(db: Session, p: Principal, event_id: uuid.UUID) -> IntelligenceEvent:
    ev = db.get(IntelligenceEvent, event_id)
    if ev is None or ev.tenant_id != p.tenant_id:
        raise NotFound("event not found")
    return ev


def artifact_view(db: Session, art: GeneratedArtifact | None) -> dict | None:
    if art is None:
        return None
    claims = db.scalars(select(Claim).where(Claim.artifact_id == art.id).order_by(Claim.ordinal)).all()
    return {**row(art), "claims": rows(claims)}


@router.get("/{event_id}")
def detail(event_id: uuid.UUID, p: Principal = Depends(require(Perm.EVENT_READ)), db: Session = Depends(get_db)) -> dict:
    """Event Detail: diff, source, score explanation, impact path, claims/evidence, unknowns, feedback (FR-UX-006)."""
    ev = _get(db, p, event_id)
    changes = []
    for c in db.scalars(select(ChangeEvent).where(ChangeEvent.id.in_(ev.change_ids)).order_by(ChangeEvent.field)).all():
        to_s = db.get(SourceSnapshot, c.to_snapshot_id)
        from_s = db.get(SourceSnapshot, c.from_snapshot_id) if c.from_snapshot_id else None
        doc = db.get(SourceDocument, to_s.source_document_id) if to_s else None
        changes.append({**row(c), "to_snapshot": {"id": str(to_s.id), "version": to_s.version,
                                                  "retrieved_at": to_s.retrieved_at.isoformat()} if to_s else None,
                        "from_snapshot": {"id": str(from_s.id), "version": from_s.version,
                                          "retrieved_at": from_s.retrieved_at.isoformat()} if from_s else None,
                        "source_document": row(doc, include={"id", "source", "uri", "retrieved_at", "checksum", "rights",
                                                             "connector_version", "title"}) if doc else None})
    arts = db.scalars(select(GeneratedArtifact).where(GeneratedArtifact.intel_event_id == ev.id)
                      .order_by(GeneratedArtifact.created_at)).all()
    fb = db.scalars(select(Feedback).where(Feedback.intel_event_id == ev.id).order_by(Feedback.created_at.desc())).all()
    counts: dict[str, int] = {}
    for f in fb:
        counts[f.label] = counts.get(f.label, 0) + 1
    current = db.get(GeneratedArtifact, ev.current_narrative_id) if ev.current_narrative_id else None
    return {
        "event": row(ev, exclude={"fingerprint"}),
        "changes": changes,
        "score_explanation": ev.score_components,
        "impacts": ev.impacted_assets,
        "narrative": artifact_view(db, current),
        "narrative_history": [{"id": str(a.id), "created_at": a.created_at.isoformat(), "is_human_edited": a.is_human_edited,
                               "edited_by": a.edited_by, "review_status": a.review_status, "publishable": a.publishable,
                               "parent_id": str(a.parent_id) if a.parent_id else None,
                               "model_workflow_version": a.model_workflow_version,
                               "fallback_used": (a.validation or {}).get("fallback_used", False)} for a in arts],
        "feedback": {"counts": counts, "mine": rows([f for f in fb if f.user_id == p.user_id])},
        "explanation": explain_event(db, ev),
    }


@router.get("/{event_id}/explanation")
def explanation(event_id: uuid.UUID, p: Principal = Depends(require(Perm.EVENT_READ)), db: Session = Depends(get_db)) -> dict:
    """Why am I seeing this? (XAI: explanation, meaningful summary, counterfactuals, knowledge limits)."""
    return explain_event(db, _get(db, p, event_id))


@router.get("/{event_id}/artifacts/{artifact_id}")
def artifact(event_id: uuid.UUID, artifact_id: uuid.UUID, p: Principal = Depends(require(Perm.EVENT_READ)),
             db: Session = Depends(get_db)) -> dict:
    ev = _get(db, p, event_id)
    art = db.get(GeneratedArtifact, artifact_id)
    if art is None or art.intel_event_id != ev.id:
        raise NotFound("artifact not found")
    return artifact_view(db, art)  # type: ignore[return-value]


class TriageIn(BaseModel):
    note: str | None = None


@router.post("/{event_id}/acknowledge")
def acknowledge(event_id: uuid.UUID, body: TriageIn | None = None, p: Principal = Depends(require(Perm.EVENT_TRIAGE)),
                db: Session = Depends(get_db)) -> dict:
    ev = _get(db, p, event_id)
    before = ev.status
    ev.status, ev.acknowledged_by = "acknowledged", p.actor
    audit.record(db, action="event.acknowledge", resource_type="intel_event", resource_id=ev.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, before={"status": before}, after={"status": ev.status}, reason=body.note if body else None)
    return row(ev, exclude={"fingerprint"})


@router.post("/{event_id}/escalate")
def escalate(event_id: uuid.UUID, body: TriageIn | None = None, p: Principal = Depends(require(Perm.EVENT_TRIAGE)),
             db: Session = Depends(get_db)) -> dict:
    ev = _get(db, p, event_id)
    before = ev.status
    ev.status = "escalated"
    db.add(Notification(tenant_id=p.tenant_id, dedupe_key=f"escalation:{ev.id}:{datetime.now(UTC).isoformat()}",
                        intel_event_ids=[ev.id], kind="alert", channel="web", status="sent", sent_at=datetime.now(UTC),
                        payload={"title": f"ESCALATED — {ev.title}", "note": body.note if body else None,
                                 "escalated_by": p.email, "event_id": str(ev.id)}))
    audit.record(db, action="event.escalate", resource_type="intel_event", resource_id=ev.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, before={"status": before}, after={"status": ev.status}, reason=body.note if body else None)
    return row(ev, exclude={"fingerprint"})


class EditedStatement(BaseModel):
    section: str
    statement: str = Field(..., min_length=3)
    statement_type: Literal["FACT", "INFERENCE", "UNKNOWN", "RECOMMENDED_INVESTIGATION"]
    confidence: Literal["Verified", "High", "Medium", "Low", "Not applicable"]
    evidence_ids: list[str] = Field(default_factory=list)
    affected_entity_ids: list[str] = Field(default_factory=list)


class NarrativeEdit(BaseModel):
    headline: str | None = None
    statements: list[EditedStatement]
    reason: str = Field(..., min_length=3)


@router.put("/{event_id}/narrative")
def edit_narrative(event_id: uuid.UUID, body: NarrativeEdit, p: Principal = Depends(require(Perm.NARRATIVE_EDIT)),
                   db: Session = Depends(get_db)) -> dict:
    """Editorial override (FR-FBK-002): creates a new human-edited version; machine output + evidence unchanged."""
    ev = _get(db, p, event_id)
    orig = db.get(GeneratedArtifact, ev.current_narrative_id) if ev.current_narrative_id else None
    if orig is None:
        raise ValidationFailed("event has no narrative to edit")
    evidence = (orig.content or {}).get("evidence", {})
    for s in body.statements:
        if s.statement_type == "FACT":
            if not s.evidence_ids:
                raise ValidationFailed("FACT statements must cite retained evidence")
            missing = [e for e in s.evidence_ids if e not in evidence]
            if missing:
                raise ValidationFailed(f"unknown evidence ids {missing}; edits cannot introduce new evidence")
    sections: dict[str, list[dict[str, Any]]] = {}
    for s in body.statements:
        sections.setdefault(s.section, []).append({**s.model_dump(), "validation_status": "analyst_asserted",
                                                   "validation_detail": {"edited_by": p.actor}})
    content = {**orig.content, "headline": body.headline or orig.content.get("headline"), "sections": sections}
    new = GeneratedArtifact(tenant_id=p.tenant_id, kind=orig.kind, intel_event_id=ev.id, content=content,
                            generation_id=orig.generation_id, validation=orig.validation, publishable=True,
                            review_status="Analyst-reviewed", is_human_edited=True, parent_id=orig.id,
                            edited_by=p.actor, edit_reason=body.reason,
                            model_workflow_version=f"{orig.model_workflow_version}+analyst-edit",
                            evidence_snapshot_ids=orig.evidence_snapshot_ids)
    db.add(new)
    db.flush()
    for i, s in enumerate(body.statements):
        db.add(Claim(tenant_id=p.tenant_id, artifact_id=new.id, intel_event_id=ev.id, ordinal=i, section=s.section,
                     statement=s.statement, statement_type=s.statement_type, confidence=s.confidence,
                     evidence_ids=s.evidence_ids, evidence_links=[evidence[e] for e in s.evidence_ids if e in evidence],
                     affected_entities=[uuid.UUID(x) for x in s.affected_entity_ids],
                     validation_status="analyst_asserted", review_status="Analyst-reviewed",
                     model_workflow_version=new.model_workflow_version))
    ev.current_narrative_id = new.id
    ev.review_status = "Analyst-reviewed"
    ev.version += 1
    ev.update_summary = [f"Narrative edited by analyst: {body.reason}"]
    audit.record(db, action="narrative.edit", resource_type="generated_artifact", resource_id=new.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, before={"artifact_id": str(orig.id), "content": orig.content},
                 after={"artifact_id": str(new.id), "content": content}, reason=body.reason)
    return artifact_view(db, new)  # type: ignore[return-value]


class ReviewIn(BaseModel):
    action: Literal["approve", "request_changes"]
    note: str | None = None


@router.post("/{event_id}/review")
def review(event_id: uuid.UUID, body: ReviewIn, p: Principal = Depends(require(Perm.NARRATIVE_EDIT)),
           db: Session = Depends(get_db)) -> dict:
    ev = _get(db, p, event_id)
    art = db.get(GeneratedArtifact, ev.current_narrative_id) if ev.current_narrative_id else None
    if art is None:
        raise ValidationFailed("no narrative to review")
    before = art.review_status
    if body.action == "approve":
        if not art.publishable:
            raise ValidationFailed("blocked narratives cannot be approved; edit them first")
        art.review_status = ev.review_status = "Approved"
        db.execute(Claim.__table__.update().where(Claim.artifact_id == art.id).values(review_status="Approved"))
    else:
        art.review_status = ev.review_status = "Machine"
    audit.record(db, action=f"narrative.{body.action}", resource_type="generated_artifact", resource_id=art.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, before={"review_status": before},
                 after={"review_status": art.review_status}, reason=body.note)
    return row(ev, exclude={"fingerprint"})


@router.post("/{event_id}/regenerate")
def regenerate(event_id: uuid.UUID, p: Principal = Depends(require(Perm.NARRATIVE_EDIT)), db: Session = Depends(get_db)) -> dict:
    """Re-run retrieval + interpretation + validation (e.g. after new evidence). Increments the event version."""
    from app.ai.agents.impact import generate_narrative

    ev = _get(db, p, event_id)
    art, report = generate_narrative(db, p.tenant_id, ev, use_llm=True)
    ev.current_narrative_id = art.id
    ev.version += 1
    ev.update_summary = ["Interpretation regenerated with current evidence"]
    ev.status = "published" if art.publishable else "blocked"
    audit.record(db, action="narrative.regenerate", resource_type="intel_event", resource_id=ev.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after={"artifact_id": str(art.id), "validation": report.summary()["counts"]})
    return artifact_view(db, art)  # type: ignore[return-value]
