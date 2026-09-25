"""Feedback-driven threshold tuning (FR-MAT-005, FR-FBK-003).

Raw analyst labels are never overwritten; a frozen, versioned FeedbackDataset is built from them and a
candidate ModelRelease is evaluated on that dataset before an authorized user promotes it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import stable_hash
from app.materiality.scoring import BAND_ORDER, DEFAULT_BANDS, band_for
from app.models import Feedback, FeedbackDataset, IntelligenceEvent

POSITIVE = {"MATERIAL", "USEFUL", "ESCALATE"}
NEGATIVE = {"NOT_MATERIAL", "NOT_USEFUL", "ALREADY_KNOWN"}


def labelled_examples(db: Session, tenant_id: uuid.UUID, landscape_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    stmt = select(Feedback, IntelligenceEvent).join(IntelligenceEvent, IntelligenceEvent.id == Feedback.intel_event_id).where(
        Feedback.tenant_id == tenant_id, Feedback.label.in_(POSITIVE | NEGATIVE))
    if landscape_id:
        stmt = stmt.where(IntelligenceEvent.landscape_id == landscape_id)
    by_event: dict[uuid.UUID, dict[str, Any]] = {}
    for fb, ev in db.execute(stmt).all():
        d = by_event.setdefault(ev.id, {"event_id": str(ev.id), "score": ev.materiality_score,
                                        "primary_type": ev.primary_type, "pos": 0, "neg": 0, "labels": []})
        d["pos" if fb.label in POSITIVE else "neg"] += 1
        d["labels"].append({"feedback_id": str(fb.id), "label": fb.label, "user_id": str(fb.user_id),
                            "created_at": fb.created_at.isoformat()})
    out = []
    for d in by_event.values():
        if d["pos"] == d["neg"]:
            continue  # ambiguous consensus is excluded from training sets
        d["material"] = d["pos"] > d["neg"]
        out.append(d)
    return out


def evaluate_thresholds(examples: list[dict[str, Any]], bands: dict[str, float]) -> dict[str, Any]:
    alert_bands = {"High Priority", "Executive Alert"}
    tp = sum(1 for e in examples if e["material"] and band_for(e["score"], bands) in alert_bands)
    fp = sum(1 for e in examples if not e["material"] and band_for(e["score"], bands) in alert_bands)
    fn = sum(1 for e in examples if e["material"] and band_for(e["score"], bands) not in alert_bands)
    visible_fn = sum(1 for e in examples if e["material"] and band_for(e["score"], bands) == "Archive")
    material_total = sum(1 for e in examples if e["material"])
    return {
        "n": len(examples),
        "alert_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "alert_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "material_archived": visible_fn,
        "feed_recall": round(1 - visible_fn / material_total, 3) if material_total else None,
    }


def suggest_thresholds(examples: list[dict[str, Any]], current: dict[str, float] | None = None,
                       target_precision: float = 0.8, min_examples: int = 20) -> dict[str, Any]:
    current = {**DEFAULT_BANDS, **(current or {})}
    base = evaluate_thresholds(examples, current)
    if len(examples) < min_examples:
        return {"current": current, "current_metrics": base, "suggested": None,
                "reason": f"need at least {min_examples} labelled events (have {len(examples)})"}
    best = None
    for hp in range(50, 96, 2):
        bands = {**current, "High Priority": float(hp), "Executive Alert": float(max(hp + 10, current["Executive Alert"]))}
        bands["Executive Alert"] = min(bands["Executive Alert"], 100.0)
        m = evaluate_thresholds(examples, bands)
        meets = m["alert_precision"] is not None and m["alert_precision"] >= target_precision
        if meets and (best is None or (m["alert_recall"] or 0) > (best[1]["alert_recall"] or 0)):
            best = (bands, m)
    feed = current["Feed"]
    material_scores = sorted(e["score"] for e in examples if e["material"])
    if material_scores and material_scores[0] < feed:
        feed = max(10.0, float(int(material_scores[0]) - 2))
    if best is None:
        return {"current": current, "current_metrics": base, "suggested": None,
                "reason": f"no High Priority threshold reaches precision {target_precision}"}
    suggested = {**best[0], "Feed": min(feed, best[0]["Analyst Review"] - 1)}
    ordered = [suggested[b] for b in BAND_ORDER[1:]]
    if ordered != sorted(ordered):
        suggested["Analyst Review"] = (suggested["Feed"] + suggested["High Priority"]) / 2
    return {"current": current, "current_metrics": base, "suggested": suggested,
            "suggested_metrics": evaluate_thresholds(examples, suggested), "target_precision": target_precision}


def freeze_dataset(db: Session, tenant_id: uuid.UUID, name: str, actor: str,
                   landscape_id: uuid.UUID | None = None) -> FeedbackDataset:
    examples = labelled_examples(db, tenant_id, landscape_id)
    version = (db.scalar(select(FeedbackDataset.version).where(FeedbackDataset.tenant_id == tenant_id,
                                                              FeedbackDataset.name == name)
                         .order_by(FeedbackDataset.version.desc()).limit(1)) or 0) + 1
    ds = FeedbackDataset(tenant_id=tenant_id, name=name, version=version,
                         criteria={"landscape_id": str(landscape_id) if landscape_id else None,
                                   "positive": sorted(POSITIVE), "negative": sorted(NEGATIVE),
                                   "exclude": "tied consensus"},
                         records=examples, record_count=len(examples), content_hash=stable_hash(examples),
                         created_by=actor)
    db.add(ds)
    db.flush()
    return ds
