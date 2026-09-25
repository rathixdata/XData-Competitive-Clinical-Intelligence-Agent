"""Transparent rule-based materiality scoring (FR-MAT-001/002/004, Section 15).

M = (wR*R + wC*C + wP*P + wT*T + wN*N) / sum(w), each dimension on 0-100.
Every dimension returns its score *and* the rule hits that produced it, so analysts can see exactly
why an event scored as it did. Weights and band thresholds are configurable per landscape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from app.changes.taxonomy import BASE_MAGNITUDE, ChangeType
from app.pipeline.normalize import partial_date_to_date

SCORING_VERSION = "mat-rules-1.0.0"
DEFAULT_WEIGHTS = {"R": 0.25, "C": 0.25, "P": 0.25, "T": 0.15, "N": 0.10}
DEFAULT_BANDS = {"Feed": 30, "Analyst Review": 50, "High Priority": 70, "Executive Alert": 85}
BAND_ORDER = ["Archive", "Feed", "Analyst Review", "High Priority", "Executive Alert"]


@dataclass
class ChangeInput:
    change_type: str
    field: str
    tags: list[str]
    magnitude: dict[str, Any]
    old: Any = None
    new: Any = None


@dataclass
class ScoringContext:
    changes: list[ChangeInput]
    relevance_level: str  # monitored | linked | indication | peripheral
    max_proximity: float  # 0..1 to any customer asset
    catalyst_date: date | None = None
    catalyst_kind: str | None = None
    object_type: str = "trial"
    phase: str | None = None
    prior_similar_events: int = 0
    already_known_feedback: int = 0
    mapping_confidence: float = 1.0
    now: date = field(default_factory=lambda: datetime.now(UTC).date())


@dataclass
class ScoreResult:
    score: float
    band: str
    components: dict[str, Any]


def change_magnitude(c: ChangeInput) -> tuple[float, list[str]]:
    t, m, tags = c.change_type, c.magnitude or {}, set(c.tags or [])
    base = float(BASE_MAGNITUDE.get(t, 40))
    hits: list[str] = []
    if t == ChangeType.ENROLLMENT_CHANGED and m.get("pct_change") is not None:
        pct = abs(float(m["pct_change"]))
        base = min(95.0, 35 + pct * 1.1)
        hits.append(f"enrollment {m['pct_change']:+.0f}%")
    elif t == ChangeType.DATE_CHANGED:
        shift = m.get("shift_months")
        if "DATE_ACTUALIZED" in tags:
            base = 35.0
            hits.append("anticipated date confirmed as actual")
        elif shift is not None:
            weight = 1.0 if m.get("date_field") == "primary_completion_date" else 0.7
            base = min(95.0, 30 + abs(float(shift)) * 6 * weight)
            hits.append(f"{m.get('date_field', 'date')} moved {shift:+.1f} months")
    elif t == ChangeType.ENDPOINT_CHANGED:
        if m.get("endpoint_level") == "secondary":
            base = 45.0
            hits.append("secondary endpoint change")
        elif m.get("replaced") or "ENDPOINT_REPLACED" in tags:
            base = 95.0
            hits.append("primary endpoint replaced")
        elif tags & {"ENDPOINT_ADDED", "ENDPOINT_REMOVED"}:
            base = 85.0
            hits.append("primary endpoint added/removed")
        elif "ENDPOINT_TIMEFRAME" in tags:
            base = 60.0
            hits.append("primary endpoint time frame changed")
        else:
            base = 25.0
            hits.append("endpoint description edited")
    elif t in (ChangeType.STATUS_CHANGED, ChangeType.TRIAL_STARTED):
        if "TRIAL_HALTED" in tags:
            base = 95.0
            hits.append(f"trial halted ({c.new})")
        elif "TRIAL_COMPLETED" in tags:
            base = 70.0
            hits.append("trial completed")
        elif t == ChangeType.TRIAL_STARTED:
            hits.append("trial started recruiting")
    elif t == ChangeType.SUPPLEMENTAL_APPROVAL and "NEW_INDICATION_OR_EFFICACY" in tags:
        base = 85.0
        hits.append("efficacy supplement approved")
    elif t == ChangeType.LABEL_CHANGED:
        sim = float(m.get("similarity", 0.9))
        if "BOXED_WARNING" in tags:
            base = 90.0
            hits.append("boxed warning text changed")
        elif "INDICATION_UPDATE" in tags:
            base = 80.0
            hits.append("indications & usage changed")
        else:
            base = min(75.0, 35 + (1 - sim) * 200)
            hits.append(f"label section changed (similarity {sim:.2f})")
    elif t == ChangeType.ELIGIBILITY_CHANGED:
        sim = float(m.get("similarity", 0.9))
        base = min(80.0, 30 + (1 - sim) * 150)
        hits.append(f"eligibility text changed (similarity {sim:.2f})")
    elif t == ChangeType.APPROVAL:
        hits.append("original application approved")
    elif t == ChangeType.NEW_PUBLICATION:
        if "REVIEW" in tags:
            base = 30.0
            hits.append("review article (no new primary data)")
        elif tags & {"CLINICAL_TRIAL", "PRIMARY_RESULTS"}:
            base = 65.0
            hits.append("publication reports clinical trial results")
    if not hits:
        hits.append(t.lower().replace("_", " "))
    return base, hits


def _temporal(ctx: ScoringContext) -> tuple[float, list[str]]:
    if ctx.object_type in ("drug_application", "label"):
        return 90.0, ["regulatory decision already taken (event is current)"]
    if ctx.object_type in ("publication", "conference_abstract", "disclosure"):
        return 60.0, ["new public disclosure"]
    if ctx.catalyst_date is None:
        return 30.0, ["no dated catalyst"]
    months = (ctx.catalyst_date - ctx.now).days / 30.4375
    if months < 0:
        return 55.0, [f"{ctx.catalyst_kind or 'catalyst'} date passed {abs(months):.0f} months ago; readout may be pending"]
    for limit, score in ((1, 100.0), (3, 90.0), (6, 80.0), (12, 65.0), (18, 55.0), (24, 45.0)):
        if months <= limit:
            return score, [f"{ctx.catalyst_kind or 'catalyst'} in {months:.0f} months"]
    return 25.0, [f"{ctx.catalyst_kind or 'catalyst'} more than 24 months away"]


def score_event(ctx: ScoringContext, weights: dict[str, float] | None = None,
                bands: dict[str, float] | None = None) -> ScoreResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    b = {**DEFAULT_BANDS, **(bands or {})}
    rule_hits: dict[str, list[str]] = {}

    # R - relevance to the customer's portfolio / landscape
    r = {"monitored": 100.0, "linked": 85.0, "indication": 60.0, "peripheral": 30.0}.get(ctx.relevance_level, 30.0)
    rule_hits["R"] = [f"object is {ctx.relevance_level} in landscape"]
    if ctx.max_proximity > 0:
        r = max(r, 60 + 40 * ctx.max_proximity)
        rule_hits["R"].append(f"maps to internal asset (proximity {ctx.max_proximity:.2f})")

    # C - change magnitude (max change + bonus for concurrent material changes)
    mags = [change_magnitude(c) for c in ctx.changes] or [(0.0, ["no changes"])]
    mags.sort(key=lambda x: x[0], reverse=True)
    c = mags[0][0]
    rule_hits["C"] = [h for _, hs in mags for h in hs]
    concurrent = sum(1 for m, _ in mags[1:] if m >= 50)
    if concurrent:
        c = min(100.0, c + 5 * min(concurrent, 2))
        rule_hits["C"].append(f"{concurrent} additional concurrent material change(s)")
    if ctx.phase and "3" in ctx.phase:
        c = min(100.0, c + 5)
        rule_hits["C"].append(f"pivotal-stage program ({ctx.phase})")

    # P - competitive proximity
    p = round(100 * ctx.max_proximity, 1)
    rule_hits["P"] = [f"max proximity to customer assets {ctx.max_proximity:.2f}"]

    # T - temporal importance
    t, rule_hits["T"] = _temporal(ctx)

    # N - novelty
    n = 100.0
    rule_hits["N"] = ["first observation"]
    if ctx.prior_similar_events:
        n = max(30.0, 100 - 30 * ctx.prior_similar_events)
        rule_hits["N"] = [f"{ctx.prior_similar_events} similar event(s) in last 90 days"]
    if ctx.already_known_feedback:
        n = min(n, 40.0)
        rule_hits["N"].append("analysts marked similar events as already known")

    dims = {"R": r, "C": c, "P": p, "T": t, "N": n}
    total_w = sum(w.values()) or 1.0
    raw = sum(w[k] * dims[k] for k in dims) / total_w
    # Magnitude gate: a trivial change (e.g. site-list churn) on a close competitor must not reach review
    # bands purely through relevance/proximity. Factor is 1.0 for C >= 50 and 0.6 at C = 10.
    gate = min(1.0, 0.5 + c / 100)
    score = round(raw * gate, 1)
    band = band_for(score, b)
    conf = "High" if ctx.mapping_confidence >= 0.9 else ("Medium" if ctx.mapping_confidence >= 0.75 else "Low")
    components = {
        "version": SCORING_VERSION,
        "formula": "M = gate(C) * sum(w_i * d_i) / sum(w_i); gate(C) = min(1, 0.5 + C/100)",
        "raw_score": round(raw, 1),
        "magnitude_gate": round(gate, 3),
        "dimensions": {k: {"score": round(v, 1), "weight": w[k], "contribution": round(w[k] * v / total_w, 1),
                           "rule_hits": rule_hits[k]} for k, v in dims.items()},
        "band_thresholds": b,
        "model_confidence": conf,
        "mapping_confidence": round(ctx.mapping_confidence, 3),
    }
    return ScoreResult(score, band, components)


def band_for(score: float, bands: dict[str, float] | None = None) -> str:
    b = {**DEFAULT_BANDS, **(bands or {})}
    band = "Archive"
    for name in BAND_ORDER[1:]:
        if score >= float(b[name]):
            band = name
    return band


def catalyst_from_trial(normalized: dict[str, Any]) -> tuple[date | None, str | None]:
    d = partial_date_to_date(normalized.get("primary_completion_date"), end_of_period=True)
    if d:
        return d, "primary completion"
    d = partial_date_to_date(normalized.get("completion_date"), end_of_period=True)
    return (d, "study completion") if d else (None, None)
