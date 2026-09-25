"""Explainability layer (XAI).

Structured after the NIST IR 8312 "Four Principles of Explainable AI":

1. **Explanation.** Every intelligence event and answer carries the reasons behind it: score drivers, mapping path,
   cited evidence and validation outcome.
2. **Meaningful.** A plain-language summary for executives, alongside the full technical breakdown for analysts.
3. **Explanation accuracy.** Explanations are computed from the *same* deterministic data that produced the output
   (score components, proximity dimensions, validator verdicts). They are never an LLM's after-the-fact
   rationalisation.
4. **Knowledge limits.** Each output states what the system does not know: unknowns, withheld claims, stale or
   failing sources, low mapping confidence, the absence of calibrated probabilities, and indirect comparisons.

Counterfactuals ("what would change the band") make the scoring contestable (the right-to-explanation style
requirements in the EU AI Act transparency obligations and GDPR Art. 22 guidance).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.materiality.scoring import BAND_ORDER, DEFAULT_BANDS
from app.models import Claim, GeneratedArtifact, GenerationRecord, IntelligenceEvent
from app.services.health import health_summary

DIM_NAMES = {"R": "Relevance to your portfolio", "C": "Size of the change", "P": "Competitive proximity",
             "T": "Timing / nearness to catalyst", "N": "Novelty"}
PRINCIPLES = ["explanation", "meaningful", "explanation_accuracy", "knowledge_limits"]


def _band_counterfactuals(score: float, bands: dict[str, float], raw: float | None, gate: float | None) -> list[str]:
    b = {**DEFAULT_BANDS, **(bands or {})}
    out = []
    order = BAND_ORDER[1:]
    higher = [n for n in order if b[n] > score]
    lower = [n for n in reversed(order) if b[n] <= score]
    if higher:
        nxt = higher[0]
        out.append(f"{b[nxt] - score:.1f} more points would move this event to '{nxt}' (threshold {b[nxt]:.0f}).")
    if lower:
        cur = lower[0]
        out.append(f"It would drop out of '{cur}' if the score fell by {score - b[cur] + 0.1:.1f} points "
                   f"(threshold {b[cur]:.0f}).")
    if gate is not None and gate < 1 and raw is not None:
        out.append(f"The change-size gate reduced the score from {raw:.1f} to {score:.1f}; a larger change would "
                   "remove this reduction.")
    return out


def explain_event(db: Session, ev: IntelligenceEvent) -> dict[str, Any]:
    comp = ev.score_components or {}
    dims = comp.get("dimensions", {})
    drivers = sorted(
        ({"dimension": k, "name": DIM_NAMES.get(k, k), "score": v.get("score"), "weight": v.get("weight"),
          "contribution": v.get("contribution"), "reasons": v.get("rule_hits", [])} for k, v in dims.items()),
        key=lambda d: -(d["contribution"] or 0))
    # What-if: remove each dimension's contribution (sensitivity) - computed from the same formula.
    total_w = sum((d["weight"] or 0) for d in drivers) or 1.0
    gate = comp.get("magnitude_gate", 1.0) or 1.0
    sensitivity = []
    for d in drivers:
        without = (sum((x["weight"] or 0) * (x["score"] or 0) for x in drivers if x is not d) / total_w) * gate
        sensitivity.append({"dimension": d["dimension"], "score_if_zero": round(without, 1),
                            "delta": round(ev.materiality_score - without, 1)})

    art = db.get(GeneratedArtifact, ev.current_narrative_id) if ev.current_narrative_id else None
    claims = db.scalars(select(Claim).where(Claim.artifact_id == art.id)).all() if art else []
    facts = [c for c in claims if c.statement_type == "FACT"]
    val = (art.validation or {}) if art else {}
    gen = db.get(GenerationRecord, art.generation_id) if art and art.generation_id else None

    top = drivers[0] if drivers else None
    impacts = ev.impacted_assets or []
    summary_parts = [f"Scored {ev.materiality_score:.0f}/100 ({ev.band})."]
    if top:
        summary_parts.append(f"The biggest factor was {top['name'].lower()}"
                             + (f": {top['reasons'][0]}." if top["reasons"] else "."))
    if impacts:
        m = impacts[0]
        summary_parts.append(f"It maps to {m['asset_name']} because they {m['detail'].get('rationale', 'share attributes')}"
                             f" (proximity {m['proximity']:.2f}).")
    else:
        summary_parts.append("It was not mapped to any of your internal assets.")
    summary_parts.append(f"{len(facts)} factual statement(s) are each backed by retained source evidence"
                         + (f"; {len(val.get('withheld', []))} unverifiable statement(s) were withheld." if val.get("withheld") else "."))

    limits = []
    unknowns = [c.statement for c in claims if c.statement_type == "UNKNOWN"]
    limits += unknowns
    mc = comp.get("mapping_confidence")
    if mc is not None and mc < 0.9:
        limits.append(f"Entity links behind this event have confidence {mc:.2f}; mapping may need analyst review.")
    if val.get("fallback_used") or ev.publication_blocked_reason:
        limits.append("The AI interpretation failed evidence validation; a fact-only narrative is shown instead.")
    if gen and gen.status.startswith("degraded"):
        limits.append("The language model was unavailable; interpretations are template-based.")
    health = health_summary(db)
    stale = [s["display_name"] for s in health["stale_or_failing"]]
    if stale:
        limits.append(f"Some sources are stale or failing ({', '.join(stale)}); related developments may be missing.")
    limits.append("Confidence labels are policy-based, not calibrated probabilities.")
    if ev.object_type == "trial":
        limits.append("Cross-trial comparisons are indirect and do not establish superiority.")

    return {
        "principles": PRINCIPLES,
        "summary": " ".join(summary_parts),
        "score": {
            "method": "Deterministic rule-based scoring (no machine-learned model). The explanation below is computed "
                      "from the same values that produced the score.",
            "formula": comp.get("formula"), "version": comp.get("version"),
            "raw_score": comp.get("raw_score"), "magnitude_gate": gate,
            "drivers": drivers, "sensitivity": sensitivity,
            "counterfactuals": _band_counterfactuals(ev.materiality_score, comp.get("band_thresholds") or {},
                                                     comp.get("raw_score"), gate),
            "model_confidence": comp.get("model_confidence"),
        },
        "mapping": [{"asset": m["asset_name"], "proximity": m["proximity"], "rationale": m["rationale"],
                     "shared_dimensions": {k: v for k, v in (m.get("detail", {}).get("dimensions") or {}).items()
                                           if v.get("score", 0) > 0},
                     "path": [f"{h.get('from_label')} —{h['predicate']}→ {h.get('to_label')}" for h in m.get("path", [])],
                     "rule": m.get("detail", {}).get("rule")} for m in impacts],
        "evidence": {"facts": len(facts), "facts_with_evidence": sum(1 for c in facts if c.evidence_links),
                     "supported": sum(1 for c in facts if c.validation_status == "supported"),
                     "withheld": len(val.get("withheld", [])), "validator": val.get("validator_version"),
                     "independent_judge_used": bool(val.get("judge_generation_id"))},
        "generation": {"ai_generated": bool(art and not art.is_human_edited),
                       "human_edited": bool(art and art.is_human_edited), "review_status": ev.review_status,
                       "model": gen.served_model if gen else None, "workflow": art.model_workflow_version if art else None,
                       "prompt_version": gen.prompt_version if gen else None,
                       "generation_id": str(gen.id) if gen else None},
        "knowledge_limits": limits,
    }


def explain_answer(content: dict[str, Any], retrieval: dict[str, int], served_model: str, degraded: bool) -> dict[str, Any]:
    stmts = content.get("statements", [])
    facts = [s for s in stmts if s["statement_type"] == "FACT"]
    val = content.get("validation", {})
    limits = list(content.get("limitations", []))
    if content.get("abstained"):
        limits.insert(0, "The system abstained because retained evidence did not support a verified answer.")
    if content.get("comparison_warning"):
        limits.append(content["comparison_warning"])
    if degraded or served_model == "offline-deterministic":
        limits.append("Answer produced in extractive mode (no language-model interpretation).")
    limits.append("Confidence labels are policy-based, not calibrated probabilities.")
    steps = [
        f"Understood the question: entities {list(content.get('resolved_context', {}).get('entity_labels', {}).values()) or 'none'}"
        f"{', time window from ' + content['resolved_context']['since'][:10] if content.get('resolved_context', {}).get('since') else ''}"
        f"{', comparison' if content.get('resolved_context', {}).get('comparison') else ''}.",
        f"Retrieved {retrieval.get('structured', 0)} structured record(s), {retrieval.get('changes', 0)} change record(s) "
        f"from version history and {retrieval.get('passages', 0)} source passage(s) (hybrid semantic + keyword search, "
        "limited to your tenant and public sources).",
        f"Generated typed statements with {served_model}.",
        f"Validated {len(facts)} factual statement(s) against their cited evidence; "
        f"{len(val.get('withheld', []))} withheld as unsupported.",
    ]
    return {"principles": PRINCIPLES, "steps": steps, "knowledge_limits": limits,
            "evidence_coverage": {"facts": len(facts), "facts_with_evidence": sum(1 for s in facts if s["evidence_ids"])}}


def transparency_card() -> dict[str, Any]:
    from app.ai.prompts import all_prompts
    from app.core.config import get_settings

    s = get_settings()
    return {
        "system": "XData Competitive & Clinical Intelligence Agent",
        "purpose": "Decision support for competitive and clinical intelligence: detect public-source changes, assess "
                   "materiality to the customer's assets, and present evidence-linked facts with labelled AI interpretations.",
        "not_intended_for": ["Clinical, medical, regulatory, safety or investment decisions",
                             "Patient-level diagnosis or treatment", "Pharmacovigilance case processing",
                             "Claims of clinical superiority from indirect comparisons"],
        "components": [
            {"name": "Change detection", "type": "deterministic", "explainability": "field-level old/new values from retained snapshots"},
            {"name": "Entity resolution", "type": "deterministic + human review", "explainability": "method and confidence per link; low confidence goes to review"},
            {"name": "Materiality scoring", "type": "transparent rule-based formula", "explainability": "per-dimension scores, weights, rule hits, sensitivity and counterfactuals"},
            {"name": "Impact mapping", "type": "weighted proximity rules + knowledge graph", "explainability": "shared dimensions and graph path per mapped asset"},
            {"name": "Interpretation (Impact / Ask / Briefing agents)", "type": "large language model",
             "model": s.llm_model if s.llm_provider == "anthropic" else "offline deterministic templates",
             "explainability": "typed statements (fact / inference / unknown / investigation) with claim-level evidence"},
            {"name": "Evidence validation", "type": "deterministic checks + independent LLM judge",
             "explainability": "verdict and reason per factual claim; unsupported claims withheld"},
            {"name": "Retrieval", "type": "hybrid (dense embeddings + keyword) with rank fusion",
             "model": s.embedding_model if s.embedding_provider == "voyage" else f"hashing-v1-{s.embedding_dim}"},
        ],
        "human_oversight": ["Analyst review and approval status on every narrative", "Editorial override retains the machine original",
                            "Executive briefs require approval before distribution", "Feedback labels on every event",
                            "Threshold changes require an evaluated, promoted release"],
        "data": {"sources": ["ClinicalTrials.gov", "PubMed", "openFDA", "SEC EDGAR", "permitted IR/conference feeds"],
                 "customer_data_used_for_training": False},
        "known_limitations": ["Public sources may lag or be incomplete; freshness is shown per source",
                              "Confidence labels are policy-based, not calibrated probabilities",
                              "Cross-trial comparisons are indirect",
                              "Materiality weights are configurable heuristics validated on a golden set, not learned"],
        "evaluation": {"suite": "evals/golden", "gate": "required before model, prompt or ranking promotion",
                       "metrics": ["change detection accuracy", "noise suppression", "entity precision/recall",
                                   "material-event recall", "high-priority precision", "source attribution",
                                   "unsupported-fact rate", "hallucination blocking", "abstention accuracy"]},
        "prompts": [{"id": p.id, "version": p.version, "hash": p.hash[:12]} for p in all_prompts()],
        "xai_principles": "NIST IR 8312: Explanation, Meaningful, Explanation Accuracy, Knowledge Limits",
    }
