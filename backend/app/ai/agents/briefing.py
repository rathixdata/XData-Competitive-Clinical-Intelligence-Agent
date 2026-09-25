"""Briefing Agent: periodic executive brief assembled only from validated intelligence (FR-ALT-003)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai.llm import LLMService
from app.ai.prompts import load_prompt
from app.models import (
    Asset,
    Catalyst,
    Claim,
    GeneratedArtifact,
    IntelligenceEvent,
    Landscape,
    LandscapeMember,
    Report,
)

WORKFLOW = "executive_brief"
WORKFLOW_VERSION = "1.0.0"

BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "source_event_ids": {"type": "array", "items": {"type": "string"}},
        "top_developments": {"type": "array", "items": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}, "headline": {"type": "string"}, "so_what": {"type": "string"}},
            "required": ["event_id", "headline", "so_what"], "additionalProperties": False}},
        "watch_items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["executive_summary", "source_event_ids", "top_developments", "watch_items"],
    "additionalProperties": False,
}


def _event_digest(db: Session, e: IntelligenceEvent) -> dict[str, Any]:
    claims = db.scalars(select(Claim).where(Claim.artifact_id == e.current_narrative_id).order_by(Claim.ordinal)).all() \
        if e.current_narrative_id else []
    return {
        "event_id": str(e.id), "title": e.title, "type": e.primary_type, "score": e.materiality_score, "band": e.band,
        "detected_at": e.detected_at.date().isoformat(),
        "affected_assets": [m["asset_name"] for m in e.impacted_assets or []],
        "facts": [{"statement": c.statement, "evidence_ids": c.evidence_ids} for c in claims if c.statement_type == "FACT"],
        "inferences": [c.statement for c in claims if c.statement_type == "INFERENCE"],
        "unknowns": [c.statement for c in claims if c.statement_type == "UNKNOWN"],
        "review_status": e.review_status,
    }


def gather(db: Session, tenant_id: uuid.UUID, landscape: Landscape, start: date, end: date) -> dict[str, Any]:
    t0 = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    t1 = datetime.combine(end, datetime.max.time(), tzinfo=UTC)
    events = db.scalars(select(IntelligenceEvent).where(
        IntelligenceEvent.tenant_id == tenant_id, IntelligenceEvent.landscape_id == landscape.id,
        IntelligenceEvent.detected_at.between(t0, t1)).order_by(IntelligenceEvent.materiality_score.desc())).all()
    published = [e for e in events if e.status in ("published", "acknowledged", "escalated")]
    top = [e for e in published if e.materiality_score >= 50][:8]
    low = [e for e in events if e.materiality_score < 50]
    asset_ids = db.scalars(select(LandscapeMember.entity_id).where(LandscapeMember.landscape_id == landscape.id,
                                                                  LandscapeMember.entity_type == "asset")).all()
    horizon = end + timedelta(days=90)
    cats = db.scalars(select(Catalyst).where(
        or_(Catalyst.asset_id.in_(asset_ids), Catalyst.trial_id.in_(
            select(LandscapeMember.entity_id).where(LandscapeMember.landscape_id == landscape.id))),
        or_(Catalyst.expected_date.between(end, horizon), Catalyst.window_start.between(end, horizon)),
    ).order_by(Catalyst.expected_date.nulls_last())).all()
    new_entrants = [e for e in events if e.primary_type == "TRIAL_REGISTERED" or "NEW_ENTRANT_CANDIDATE" in (e.secondary_tags or [])]
    reg_sci = [e for e in published if e.primary_type in ("APPROVAL", "SUPPLEMENTAL_APPROVAL", "LABEL_CHANGED",
                                                           "NEW_PUBLICATION", "CONFERENCE_ABSTRACT")]
    by_type: dict[str, int] = {}
    for e in low:
        by_type[e.primary_type] = by_type.get(e.primary_type, 0) + 1
    return {
        "top": [_event_digest(db, e) for e in top],
        "catalysts": [{"catalyst_id": str(c.id), "title": c.title,
                       "expected_date": c.expected_date.isoformat() if c.expected_date else None,
                       "window": [c.window_start.isoformat(), c.window_end.isoformat()] if c.window_start else None,
                       "date_basis": c.date_basis, "confidence": c.confidence,
                       "asset": (db.get(Asset, c.asset_id).canonical_name if c.asset_id and db.get(Asset, c.asset_id) else None)}
                      for c in cats[:15]],
        "new_entrants": [{"event_id": str(e.id), "title": e.title} for e in new_entrants[:10]],
        "regulatory_scientific": [{"event_id": str(e.id), "title": e.title, "type": e.primary_type} for e in reg_sci[:10]],
        "low_materiality_summary": {"count": len(low), "by_type": by_type,
                                    "note": "Low-materiality items are stored and visible in the feed; listed here for transparency."},
        "event_count": len(events),
    }


def _offline(material: dict[str, Any]) -> dict[str, Any]:
    top = material["top"]
    summary = (f"{len(top)} material development(s) this period." if top else
               "No material developments were detected this period.")
    if top:
        summary += " Highest: " + "; ".join(f"{t['title']} ({t['score']:.0f}, {t['band']})" for t in top[:3]) + "."
    return {
        "executive_summary": summary,
        "source_event_ids": [t["event_id"] for t in top[:3]],
        "top_developments": [{"event_id": t["event_id"], "headline": t["title"],
                              "so_what": (t["inferences"][0] if t["inferences"] else "Analyst assessment pending.")}
                             for t in top[:6]],
        "watch_items": [f"{c['title']} - {c['expected_date'] or 'window ' + ' to '.join(c['window'] or [])} "
                        f"({'sourced' if c['date_basis'] == 'SOURCED' else 'model-inferred window'})"
                        for c in material["catalysts"][:5]],
    }


def generate_brief(db: Session, tenant_id: uuid.UUID, landscape: Landscape, start: date, end: date,
                   created_by: str | None) -> Report:
    material = gather(db, tenant_id, landscape, start, end)
    import json

    user = (f"<period start=\"{start}\" end=\"{end}\" landscape=\"{landscape.name}\"/>\n"
            f"<validated_intelligence>{json.dumps(material, default=str)}</validated_intelligence>")
    res = LLMService(db, tenant_id).generate(
        workflow=WORKFLOW, workflow_version=WORKFLOW_VERSION, prompt=load_prompt("executive_brief"), user_content=user,
        schema=BRIEF_SCHEMA, offline=lambda: _offline(material),
        retrieval_set=[{"event_id": t["event_id"]} for t in material["top"]])
    valid_ids = {t["event_id"] for t in material["top"]}
    data = res.data
    data["top_developments"] = [d for d in data.get("top_developments", []) if d.get("event_id") in valid_ids]
    data["source_event_ids"] = [i for i in data.get("source_event_ids", []) if i in valid_ids]
    content = {
        "title": f"{landscape.name} executive brief: {start.isoformat()} to {end.isoformat()}",
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        **data,
        "sections": material,
        "generated_at": datetime.now(UTC).isoformat(),
        "model_workflow_version": res.model_workflow_version,
        "disclaimer": "Decision-support output. Facts are evidence-linked; 'so what' items are AI-generated "
                      "interpretations. Cross-trial comparisons are indirect.",
    }
    art = GeneratedArtifact(tenant_id=tenant_id, kind="executive_brief", content=content,
                            generation_id=res.generation_id, publishable=True,
                            model_workflow_version=res.model_workflow_version)
    db.add(art)
    db.flush()
    rep = Report(tenant_id=tenant_id, landscape_id=landscape.id, kind="executive_brief", title=content["title"],
                 period_start=start, period_end=end, status="draft", artifact_id=art.id, created_by=created_by)
    db.add(rep)
    db.flush()
    return rep
