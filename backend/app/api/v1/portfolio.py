"""/dashboard, /catalysts, /comparisons, /kpis (FR-UX-001/004/005, US-010, Section 22)."""

from __future__ import annotations

import statistics
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require
from app.api.serialize import row
from app.core.errors import NotFound
from app.core.rbac import Perm
from app.core.security import Principal
from app.models import (
    Asset,
    Catalyst,
    Claim,
    Feedback,
    IntelligenceEvent,
    Landscape,
    LandscapeMember,
    Trial,
    Watchlist,
)
from app.reports.export import EXPORTERS
from app.services.health import health_summary
from app.services.landscapes import MATRIX_COLUMNS, asset_row

router = APIRouter(tags=["portfolio"])


def _landscape_asset_ids(db: Session, landscape_id: uuid.UUID | None, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = select(LandscapeMember.entity_id).where(LandscapeMember.tenant_id == tenant_id,
                                                   LandscapeMember.entity_type.in_(("asset", "trial")))
    if landscape_id:
        stmt = stmt.where(LandscapeMember.landscape_id == landscape_id)
    return list(db.scalars(stmt).all())


@router.get("/dashboard")
def dashboard(landscape_id: uuid.UUID | None = None, p: Principal = Depends(require(Perm.LANDSCAPE_READ)),
              db: Session = Depends(get_db)) -> dict:
    """Home / Portfolio (FR-UX-001): asset cards, material developments, catalysts, health, watchlists."""
    now = datetime.now(UTC)
    ls_q = select(Landscape).where(Landscape.tenant_id == p.tenant_id, Landscape.status == "active")
    landscapes = db.scalars(ls_q).all()
    ls_ids = [landscape_id] if landscape_id else [x.id for x in landscapes]
    custs = db.scalars(select(LandscapeMember).where(LandscapeMember.landscape_id.in_(ls_ids),
                                                     LandscapeMember.role == "customer",
                                                     LandscapeMember.entity_type == "asset")).all()
    cards = []
    for m in custs:
        a = db.get(Asset, m.entity_id)
        if a is None:
            continue
        open_hp = db.scalar(select(func.count()).select_from(IntelligenceEvent).where(
            IntelligenceEvent.tenant_id == p.tenant_id, IntelligenceEvent.impacted_asset_ids.any(a.id),
            IntelligenceEvent.band.in_(("High Priority", "Executive Alert")),
            IntelligenceEvent.status.in_(("published", "escalated")))) or 0
        last30 = db.scalar(select(func.count()).select_from(IntelligenceEvent).where(
            IntelligenceEvent.tenant_id == p.tenant_id, IntelligenceEvent.impacted_asset_ids.any(a.id),
            IntelligenceEvent.detected_at >= now - timedelta(days=30))) or 0
        cards.append({"asset_id": str(a.id), "name": a.canonical_name, "stage": a.stage, "profile": a.profile,
                      "landscape_id": str(m.landscape_id), "open_high_priority": open_hp, "events_30d": last30})
    top = db.scalars(select(IntelligenceEvent).where(
        IntelligenceEvent.tenant_id == p.tenant_id, IntelligenceEvent.landscape_id.in_(ls_ids),
        IntelligenceEvent.materiality_score >= 50, IntelligenceEvent.detected_at >= now - timedelta(days=30),
        IntelligenceEvent.status.in_(("published", "escalated", "acknowledged", "blocked")))
        .order_by(IntelligenceEvent.materiality_score.desc(), IntelligenceEvent.detected_at.desc()).limit(10)).all()
    ent_ids = [x for lid in ls_ids for x in _landscape_asset_ids(db, lid, p.tenant_id)]
    cats = db.scalars(select(Catalyst).where(
        or_(Catalyst.asset_id.in_(ent_ids or [uuid.uuid4()]), Catalyst.trial_id.in_(ent_ids or [uuid.uuid4()]),
            Catalyst.trial_id.in_(select(IntelligenceEvent.object_id).where(IntelligenceEvent.tenant_id == p.tenant_id))),
        Catalyst.status == "upcoming",
        or_(Catalyst.expected_date <= now.date() + timedelta(days=90), Catalyst.window_start <= now.date() + timedelta(days=90)))
        .order_by(Catalyst.expected_date.nulls_last()).limit(10)).all()
    wls = db.scalars(select(Watchlist).where(or_(Watchlist.owner_id == p.user_id, Watchlist.visibility == "tenant"))
                     .order_by(Watchlist.name).limit(20)).all()
    band_counts = dict(db.execute(select(IntelligenceEvent.band, func.count()).where(
        IntelligenceEvent.tenant_id == p.tenant_id, IntelligenceEvent.landscape_id.in_(ls_ids),
        IntelligenceEvent.detected_at >= now - timedelta(days=30)).group_by(IntelligenceEvent.band)).all())
    return {
        "landscapes": [{"id": str(x.id), "name": x.name} for x in landscapes],
        "assets": cards,
        "material_developments": [row(e, include={"id", "title", "materiality_score", "band", "primary_type", "detected_at",
                                                  "status", "review_status", "impacted_assets"}) for e in top],
        "upcoming_catalysts": [row(c) for c in cats],
        "health": health_summary(db),
        "watchlists": [row(w, include={"id", "name", "visibility"}) for w in wls],
        "band_counts_30d": band_counts,
    }


@router.get("/catalysts")
def catalysts(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
              landscape_id: uuid.UUID | None = None, asset_id: uuid.UUID | None = None,
              basis: Literal["SOURCED", "INFERRED"] | None = None, changed_only: bool = False,
              p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> dict:
    """Catalyst calendar (FR-UX-005): sourced dates vs model-inferred windows; changed catalysts flagged."""
    date_from = date_from or datetime.now(UTC).date() - timedelta(days=30)
    date_to = date_to or datetime.now(UTC).date() + timedelta(days=365)
    stmt = select(Catalyst).where(or_(Catalyst.expected_date.between(date_from, date_to),
                                      Catalyst.window_start.between(date_from, date_to),
                                      Catalyst.window_end.between(date_from, date_to)))
    if landscape_id:
        ids = _landscape_asset_ids(db, landscape_id, p.tenant_id)
        trial_ids = select(IntelligenceEvent.object_id).where(IntelligenceEvent.landscape_id == landscape_id)
        stmt = stmt.where(or_(Catalyst.asset_id.in_(ids or [uuid.uuid4()]), Catalyst.trial_id.in_(ids or [uuid.uuid4()]),
                              Catalyst.trial_id.in_(trial_ids)))
    if asset_id:
        stmt = stmt.where(Catalyst.asset_id == asset_id)
    if basis:
        stmt = stmt.where(Catalyst.date_basis == basis)
    items = []
    for c in db.scalars(stmt.order_by(Catalyst.expected_date.nulls_last(), Catalyst.window_start)).all():
        changed = bool(c.history)
        if changed_only and not changed:
            continue
        a = db.get(Asset, c.asset_id) if c.asset_id else None
        t = db.get(Trial, c.trial_id) if c.trial_id else None
        items.append({**row(c), "asset_name": a.canonical_name if a else None, "nct_id": t.nct_id if t else None,
                      "changed": changed, "previous": c.history[-1] if changed else None})
    return {"from": date_from.isoformat(), "to": date_to.isoformat(), "items": items,
            "legend": {"SOURCED": "Date reported by the source record", "INFERRED": "Model-inferred window (heuristic)"}}


class CompareIn(BaseModel):
    asset_ids: list[uuid.UUID] = Field(..., min_length=2, max_length=8)


def _comparison(db: Session, asset_ids: list[uuid.UUID]) -> dict:
    assets = [db.get(Asset, i) for i in asset_ids]
    if any(a is None for a in assets):
        raise NotFound("asset not found")
    rows_ = [asset_row(db, a, "customer" if a.is_internal else "competitor") for a in assets]  # type: ignore[union-attr]
    warnings = ["Cross-trial comparisons are indirect; attributes are shown for context and do not establish "
                "superiority or inferiority."]
    for col, label in (("primary_endpoints", "Primary endpoints"), ("population", "Populations / lines of therapy"),
                       ("phase", "Development phases"), ("biomarker", "Biomarker selection")):
        vals = {str(r["cells"][col]["value"]) for r in rows_ if r["cells"].get(col, {}).get("value") is not None}
        if len(vals) > 1:
            warnings.append(f"{label} differ across assets ({'; '.join(sorted(vals))[:300]}); values are not directly comparable.")
    return {"columns": MATRIX_COLUMNS, "rows": rows_, "context_warnings": warnings,
            "generated_at": datetime.now(UTC).isoformat()}


@router.post("/comparisons")
def compare(body: CompareIn, p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> dict:
    return _comparison(db, body.asset_ids)


@router.post("/comparisons/export")
def compare_export(body: CompareIn, format: Literal["md", "docx", "pdf", "pptx"] = "docx",
                   p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> Response:
    c = _comparison(db, body.asset_ids)
    statements = []
    for r in c["rows"]:
        attrs = "; ".join(f"{k}: {v['value']}" for k, v in r["cells"].items() if v["value"] is not None)
        statements.append({"section": "comparison", "statement": f"{r['asset']}: {attrs}", "statement_type": "FACT",
                           "confidence": "Verified", "evidence_ids": []})
    content = {"question": "Asset comparison: " + ", ".join(r["asset"] for r in c["rows"]), "answer": "",
               "statements": statements, "limitations": c["context_warnings"], "comparison_warning": c["context_warnings"][0],
               "evidence": {}, "generated_at": c["generated_at"], "model_workflow_version": "comparison@1.0.0"}
    fn, media = EXPORTERS[format]
    data = fn("ask_answer", content)
    return Response(data.encode() if isinstance(data, str) else data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="xdata-comparison.{format}"'})


@router.get("/kpis")
def kpis(landscape_id: uuid.UUID | None = None, days: int = Query(90, ge=7, le=365),
         p: Principal = Depends(require(Perm.REPORT_READ)), db: Session = Depends(get_db)) -> dict:
    """Pilot KPI measurement (Section 18/22): attribution, precision, usefulness, latency."""
    since = datetime.now(UTC) - timedelta(days=days)
    ev_q = select(IntelligenceEvent).where(IntelligenceEvent.tenant_id == p.tenant_id, IntelligenceEvent.detected_at >= since)
    if landscape_id:
        ev_q = ev_q.where(IntelligenceEvent.landscape_id == landscape_id)
    events = db.scalars(ev_q).all()
    ids = [e.id for e in events]
    fb = db.scalars(select(Feedback).where(Feedback.intel_event_id.in_(ids or [uuid.uuid4()]))).all()
    hp_ids = {e.id for e in events if e.band in ("High Priority", "Executive Alert")}
    hp_fb = [f for f in fb if f.intel_event_id in hp_ids and f.label in ("MATERIAL", "NOT_MATERIAL", "USEFUL", "NOT_USEFUL")]
    useful = [f for f in fb if f.label in ("USEFUL", "NOT_USEFUL")]
    facts = db.scalar(select(func.count()).select_from(Claim).where(
        Claim.intel_event_id.in_(ids or [uuid.uuid4()]), Claim.statement_type == "FACT")) or 0
    facts_with_ev = db.scalar(select(func.count()).select_from(Claim).where(
        Claim.intel_event_id.in_(ids or [uuid.uuid4()]), Claim.statement_type == "FACT",
        func.cardinality(Claim.evidence_ids) > 0)) or 0
    lat = [(e.published_at - e.source_fetched_at).total_seconds() / 60 for e in events if e.published_at and e.source_fetched_at]
    return {
        "window_days": days,
        "events": len(events),
        "by_band": {b: sum(1 for e in events if e.band == b) for b in
                    ("Archive", "Feed", "Analyst Review", "High Priority", "Executive Alert")},
        "source_attribution_rate": round(facts_with_ev / facts, 4) if facts else None,
        "high_priority_precision": round(sum(1 for f in hp_fb if f.label in ("MATERIAL", "USEFUL")) / len(hp_fb), 3) if hp_fb else None,
        "useful_alert_rate": round(sum(1 for f in useful if f.label == "USEFUL") / len(useful), 3) if useful else None,
        "blocked_publications": sum(1 for e in events if e.publication_blocked_reason),
        "median_fetch_to_publish_minutes": round(statistics.median(lat), 2) if lat else None,
        "p95_fetch_to_publish_minutes": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 2) if lat else None,
        "feedback_count": len(fb),
        "targets": {"source_attribution_rate": 1.0, "high_priority_precision": 0.8, "useful_alert_rate": 0.75,
                    "alert_latency_minutes": 15},
    }


