"""Materiality scoring, bands, proximity (FR-MAT-001/002/004, FR-LND-004, Section 15)."""

from __future__ import annotations

from datetime import date

from app.materiality.proximity import Features, features_from_profile, parse_lines, proximity
from app.materiality.scoring import ChangeInput, ScoringContext, band_for, score_event
from app.materiality.tuning import evaluate_thresholds, suggest_thresholds

XD101 = {"targets": ["Target-X"], "indications": ["Non-small cell lung cancer"], "line_of_therapy": "2L+",
         "biomarkers": ["Target-X mutation"], "modality": "Small molecule", "geographies": ["United States"]}
CA201 = {**XD101}
ECH101 = {**XD101, "indications": ["Colorectal cancer"]}
DLT7 = {"targets": ["Target-Y"], "indications": ["NSCLC"], "line_of_therapy": "2L+",
        "biomarkers": ["Target-Y amplification"], "modality": "Small molecule"}


def scenario_ctx(**kw) -> ScoringContext:  # type: ignore[no-untyped-def]
    base = dict(
        changes=[ChangeInput("ENROLLMENT_CHANGED", "enrollment", ["ENROLLMENT_INCREASE"], {"pct_change": 50.0}, 320, 480),
                 ChangeInput("DATE_CHANGED", "primary_completion_date", ["DELAY"],
                             {"shift_months": 5.0, "date_field": "primary_completion_date"}),
                 ChangeInput("ENDPOINT_CHANGED", "primary_endpoints", ["ENDPOINT_REPLACED"],
                             {"endpoint_level": "primary", "replaced": True})],
        relevance_level="monitored", max_proximity=0.95, catalyst_date=date(2027, 11, 30),
        catalyst_kind="primary completion", phase="Phase 3", now=date(2026, 9, 25))
    base.update(kw)
    return ScoringContext(**base)


def test_acceptance_scenario_is_executive_alert_with_explanation():
    r = score_event(scenario_ctx())
    assert r.band == "Executive Alert" and r.score >= 85
    dims = r.components["dimensions"]
    assert set(dims) == {"R", "C", "P", "T", "N"}
    assert any("primary endpoint replaced" in h for h in dims["C"]["rule_hits"])
    assert all({"score", "weight", "contribution", "rule_hits"} <= set(d) for d in dims.values())
    assert r.components["model_confidence"] in ("High", "Medium", "Low")


def test_trivial_change_on_close_competitor_is_gated_below_review():
    r = score_event(scenario_ctx(changes=[ChangeInput("LOCATION_CHANGED", "locations", ["SITE_UPDATE"], {})],
                                 phase="Phase 2"))
    assert r.band in ("Archive", "Feed"), r.score
    assert r.components["magnitude_gate"] < 1


def test_novelty_and_already_known_reduce_score():
    first = score_event(scenario_ctx()).score
    repeat = score_event(scenario_ctx(prior_similar_events=2, already_known_feedback=1)).score
    assert repeat < first


def test_bands_are_configurable_per_landscape():
    assert band_for(72) == "High Priority"
    assert band_for(72, {"High Priority": 75, "Executive Alert": 90}) == "Analyst Review"
    r = score_event(scenario_ctx(), bands={"Executive Alert": 99})
    assert r.band == "High Priority"


def test_weights_are_configurable():
    heavy_p = score_event(scenario_ctx(max_proximity=0.1), weights={"P": 5.0}).score
    light_p = score_event(scenario_ctx(max_proximity=0.1), weights={"P": 0.01}).score
    assert heavy_p < light_p


def test_line_of_therapy_parsing():
    assert parse_lines("2L+") == {"L2", "L3", "L4", "L5"}
    assert parse_lines("first-line") == {"L1"}
    assert "L2" in parse_lines("patients previously treated with platinum")
    assert parse_lines("treatment-naive") == {"L1"}


def test_proximity_ranks_direct_competitor_highest():
    xd = features_from_profile(XD101)
    direct = proximity(xd, features_from_profile(CA201))
    other_indication = proximity(xd, features_from_profile(ECH101))
    other_target = proximity(xd, features_from_profile(DLT7))
    assert direct.score > 0.9
    assert direct.score > other_indication.score > 0
    assert direct.score > other_target.score
    assert "target" in direct.rationale


def test_proximity_unknown_dimensions_do_not_inflate():
    sparse = proximity(Features(target={"target x"}), Features(target={"target x"}))
    assert sparse.coverage < 0.5 and sparse.score < 0.6


def test_threshold_tuning_suggestion_reaches_target_precision():
    examples = [{"score": s, "material": s >= 78} for s in range(40, 100, 2)]
    out = suggest_thresholds(examples, target_precision=0.9, min_examples=10)
    assert out["suggested"] is not None
    assert out["suggested_metrics"]["alert_precision"] >= 0.9
    assert evaluate_thresholds(examples, out["suggested"])["n"] == len(examples)
