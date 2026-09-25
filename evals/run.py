"""Golden-set evaluation runner - the evaluation gate before model/prompt/ranking promotion (Section 20).

    python -m evals.run --suite golden --offline            # CI gate (deterministic)
    python -m evals.run --suite golden                      # uses the configured LLM (costs money)

Measures the SRS Section 18 acceptance metrics that are measurable offline:
structured change detection, noise suppression, entity-resolution precision/recall, material-event recall
and high-priority precision, source attribution, unsupported-fact rate, hallucination blocking,
abstention, comparison warnings and temporal answers. Exits non-zero if any threshold is missed.

The runner RESETS the target database; it refuses to run unless the database name ends in _test/_eval
or --allow-reset is given.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent


def _prepare_env(offline: bool) -> None:
    os.environ.setdefault("XDATA_ENV", "test")
    os.environ.setdefault("XDATA_DATABASE_URL", "postgresql+psycopg://xdata:xdata@127.0.0.1:5432/xdata_test")
    os.environ.setdefault("XDATA_EMBEDDING_PROVIDER", "hashing")
    os.environ.setdefault("XDATA_OBJECT_STORE_BACKEND", "local")
    os.environ.setdefault("XDATA_OBJECT_STORE_LOCAL_PATH", "/tmp/xdata-eval-objects")
    os.environ.setdefault("XDATA_LOG_LEVEL", "WARNING")
    os.environ.setdefault("XDATA_LOG_JSON", "false")
    if offline:
        os.environ["XDATA_LLM_PROVIDER"] = "offline"


def _reset_db(allow: bool) -> None:
    from sqlalchemy import text

    import app.models  # noqa: F401
    from app.db.base import Base
    from app.db.session import get_engine

    name = get_engine().url.database or ""
    if not (allow or name.endswith(("_test", "_eval"))):
        sys.exit(f"refusing to reset database '{name}'; use a *_test/*_eval database or --allow-reset")
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with get_engine().begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


def eval_change_detection(gs: dict[str, Any]) -> dict[str, Any]:
    from app.changes.diff import diff_trial

    ok, fails = 0, []
    for case in gs["change_detection"]:
        got = sorted((c.field, str(c.change_type)) for c in diff_trial(case["old"], case["new"]) if not c.suppressed)
        exp = sorted(tuple(x) for x in case["expected"])
        if got == exp:
            ok += 1
        else:
            fails.append({"id": case["id"], "expected": exp, "got": got})
    quiet, noisy = 0, []
    for case in gs["noise"]:
        emitted = [c.field for c in diff_trial(case["old"], case["new"]) if not c.suppressed]
        if emitted:
            noisy.append({"id": case["id"], "emitted": emitted})
        else:
            quiet += 1
    return {"change_detection_accuracy": ok / len(gs["change_detection"]),
            "noise_suppression_rate": quiet / len(gs["noise"]), "failures": fails + noisy}


def eval_entity_resolution(gs: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import session_scope
    from app.entities.resolver import EntityResolver, model_for

    tp = fp = fn = tn = 0
    fails = []
    with session_scope(bypass_rls=True) as db:
        r = EntityResolver(db)
        for case in gs["entity_resolution"]:
            res = r.resolve(case["mention"], case["type"])
            got = None
            if res.linked:
                got = db.get(model_for(case["type"]), res.entity_id).canonical_name
            exp = case["expected"]
            if got is not None and got == exp:
                tp += 1
            elif got is not None and got != exp:
                fp += 1
                fails.append({**case, "got": got})
            elif got is None and exp is not None:
                fn += 1
                fails.append({**case, "got": None, "status": res.status})
            else:
                tn += 1
    return {"entity_resolution_precision": tp / (tp + fp) if tp + fp else 1.0,
            "entity_resolution_recall": tp / (tp + fn) if tp + fn else 1.0, "failures": fails,
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}}


def eval_materiality(gs: dict[str, Any]) -> dict[str, Any]:
    from app.materiality.scoring import ChangeInput, ScoringContext, score_event

    today = date(2026, 9, 25)
    alert_bands = {"High Priority", "Executive Alert"}
    tp = fp = fn = 0
    rows = []
    for c in gs["materiality"]:
        months = c.get("months_to_catalyst")
        ctx = ScoringContext(
            changes=[ChangeInput(t, f, tags, mag) for t, f, tags, mag in c["changes"]],
            relevance_level=c["relevance"], max_proximity=c["proximity"],
            catalyst_date=today + timedelta(days=int(months * 30.4)) if months is not None else None,
            catalyst_kind="primary completion", object_type=c.get("object_type", "trial"), phase=c.get("phase"), now=today)
        r = score_event(ctx)
        alerted = r.band in alert_bands
        rows.append({"id": c["id"], "material": c["material"], "score": r.score, "band": r.band})
        if c["material"] and alerted:
            tp += 1
        elif c["material"]:
            fn += 1
        elif alerted:
            fp += 1
    return {"material_event_recall": tp / (tp + fn) if tp + fn else 1.0,
            "high_priority_precision": tp / (tp + fp) if tp + fp else 1.0, "cases": rows,
            "failures": [r for r in rows if (r["band"] in alert_bands) != r["material"]]}


def eval_pipeline_grounding() -> dict[str, Any]:
    """Run the demo pipeline end-to-end and audit every published factual claim."""
    from sqlalchemy import select

    from app.db.session import session_scope
    from app.models import Claim, GeneratedArtifact
    from app.seed.demo import seed_demo

    info = seed_demo(with_pipeline=True, use_llm=os.environ.get("XDATA_LLM_PROVIDER") != "offline")
    with session_scope(bypass_rls=True) as db:
        pub_ids = [a.id for a in db.scalars(select(GeneratedArtifact).where(GeneratedArtifact.publishable.is_(True),
                                                                            GeneratedArtifact.kind == "impact_narrative"))]
        facts = db.scalars(select(Claim).where(Claim.artifact_id.in_(pub_ids), Claim.statement_type == "FACT")).all()
        linked = [c for c in facts if c.evidence_ids and c.evidence_links]
        unsupported = [c for c in facts if c.validation_status == "unsupported"]
    return {"tenant_id": info["tenant_id"], "published_facts": len(facts),
            "source_attribution_rate": len(linked) / len(facts) if facts else 0.0,
            "unsupported_fact_rate": len(unsupported) / len(facts) if facts else 1.0,
            "pipeline": info.get("pipeline")}


def eval_hallucination_blocking() -> dict[str, Any]:
    """Inject fabricated model outputs; every one must be withheld and block publication."""
    import uuid

    from sqlalchemy import select

    from app.ai import llm as llm_mod
    from app.ai.agents.impact import generate_narrative
    from app.db.session import session_scope
    from app.models import IntelligenceEvent

    fabrications = [
        "The sponsor reported a 72% objective response rate in the trial.",
        "Enrollment was increased to 900 patients in NCT99000001.",
        "The FDA granted Breakthrough Therapy designation on 2026-08-01.",
        "NCT12345678 was terminated for safety reasons.",
    ]
    original = llm_mod.LLMService.generate
    blocked = 0
    try:
        for fab in fabrications:
            def fake(self, _fab=fab, **kw):  # type: ignore[no-untyped-def]
                data = ({"headline": "h", "statements": [{"section": "context", "statement": _fab, "statement_type": "FACT",
                                                          "confidence": "Verified", "evidence_ids": ["S1"],
                                                          "affected_entity_ids": []}]}
                        if kw["workflow"] == "impact_narrative" else kw["offline"]())
                return llm_mod.LLMResult(data, "anthropic", "eval-fake", "eval-fake", config={"model_workflow_version": "eval"})

            llm_mod.LLMService.generate = fake  # type: ignore[method-assign]
            with session_scope(bypass_rls=True) as db:
                ev = db.scalar(select(IntelligenceEvent).where(IntelligenceEvent.primary_type == "ENDPOINT_CHANGED"))
                from app.db.session import set_tenant

                set_tenant(db, ev.tenant_id, bypass_rls=False)
                art, report = generate_narrative(db, ev.tenant_id, ev, use_llm=True)
                if not report.publishable and _fab_absent(art.content, fab):
                    blocked += 1
                db.rollback()
                _ = uuid
    finally:
        llm_mod.LLMService.generate = original  # type: ignore[method-assign]
    return {"hallucination_block_rate": blocked / len(fabrications), "cases": len(fabrications)}


def _fab_absent(content: dict[str, Any], fab: str) -> bool:
    return fab not in json.dumps(content)


def eval_ask(gs: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    import uuid

    from sqlalchemy import select

    from app.ai.agents.ask import ask
    from app.db.session import session_scope
    from app.models import Landscape, User

    tid = uuid.UUID(tenant_id)
    abst_ok = cmp_ok = cmp_n = tmp_ok = tmp_n = 0
    rows = []
    with session_scope(tid) as db:
        user = db.scalar(select(User).where(User.email == "analyst@demo.example"))
        ls = db.scalar(select(Landscape))
        for q in gs["ask"]:
            out = ask(db, tenant_id=tid, user_id=user.id, question=q["question"], landscape_id=ls.id)
            facts = " ".join(s["statement"] for s in out["statements"] if s["statement_type"] == "FACT")
            ok_abst = out["abstained"] == q["expect_abstain"]
            abst_ok += ok_abst
            ok_contains = all(m in facts for m in q.get("must_contain", []))
            if q.get("expect_comparison_warning"):
                cmp_n += 1
                cmp_ok += bool(out["comparison_warning"])
            if q.get("temporal"):
                tmp_n += 1
                tmp_ok += ok_contains
            rows.append({"id": q["id"], "abstained": out["abstained"], "abstention_ok": ok_abst,
                         "contains_ok": ok_contains, "confidence": out["confidence"]})
    return {"abstention_accuracy": abst_ok / len(gs["ask"]), "comparison_warning_rate": cmp_ok / cmp_n if cmp_n else 1.0,
            "temporal_answer_accuracy": tmp_ok / tmp_n if tmp_n else 1.0, "cases": rows,
            "failures": [r for r in rows if not (r["abstention_ok"] and r["contains_ok"])]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--suite", default="golden")
    p.add_argument("--offline", action="store_true", help="deterministic offline LLM provider (CI gate)")
    p.add_argument("--allow-reset", action="store_true")
    args = p.parse_args(argv)
    _prepare_env(args.offline)
    sys.path.insert(0, str(HERE.parent / "backend"))
    gs = json.loads((HERE / args.suite / "golden_set.json").read_text())
    t0 = time.time()
    _reset_db(args.allow_reset)

    results: dict[str, Any] = {}
    results["change_detection"] = eval_change_detection(gs)
    grounding = eval_pipeline_grounding()  # seeds reference data used by entity/ask evals
    results["grounding"] = grounding
    results["entity_resolution"] = eval_entity_resolution(gs)
    results["materiality"] = eval_materiality(gs)
    results["ask"] = eval_ask(gs, grounding["tenant_id"])
    results["hallucination"] = eval_hallucination_blocking()

    metrics = {
        "change_detection_accuracy": results["change_detection"]["change_detection_accuracy"],
        "noise_suppression_rate": results["change_detection"]["noise_suppression_rate"],
        "entity_resolution_precision": results["entity_resolution"]["entity_resolution_precision"],
        "entity_resolution_recall": results["entity_resolution"]["entity_resolution_recall"],
        "material_event_recall": results["materiality"]["material_event_recall"],
        "high_priority_precision": results["materiality"]["high_priority_precision"],
        "source_attribution_rate": grounding["source_attribution_rate"],
        "unsupported_fact_rate_max": grounding["unsupported_fact_rate"],
        "hallucination_block_rate": results["hallucination"]["hallucination_block_rate"],
        "abstention_accuracy": results["ask"]["abstention_accuracy"],
        "comparison_warning_rate": results["ask"]["comparison_warning_rate"],
        "temporal_answer_accuracy": results["ask"]["temporal_answer_accuracy"],
    }
    th = gs["thresholds"]
    verdict = {}
    for k, v in metrics.items():
        passed = v <= th[k] if k.endswith("_max") else v >= th[k]
        verdict[k] = {"value": round(v, 4), "threshold": th[k], "passed": passed}
    ok = all(x["passed"] for x in verdict.values())
    report = {"suite": args.suite, "golden_version": gs["version"], "offline": args.offline,
              "generated_at": datetime.now(UTC).isoformat(), "duration_s": round(time.time() - t0, 1),
              "passed": ok, "metrics": verdict, "details": results}
    out_dir = HERE / "reports"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "latest.json").write_text(json.dumps(report, indent=2, default=str))
    width = max(len(k) for k in verdict)
    print(f"Golden suite {gs['version']} ({'offline' if args.offline else 'live model'}):")
    for k, v in verdict.items():
        print(f"  {'PASS' if v['passed'] else 'FAIL'}  {k:<{width}}  {v['value']:.3f}  (threshold {v['threshold']})")
    print(f"=> {'PASSED' if ok else 'FAILED'}; report: evals/reports/latest.json")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
