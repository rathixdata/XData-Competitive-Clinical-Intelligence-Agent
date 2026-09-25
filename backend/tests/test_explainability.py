"""Explainable-AI contract (NIST IR 8312 four principles) + fixes reported by frontend integration."""

from __future__ import annotations

from tests.conftest import login


def _exec_event(client, h):  # type: ignore[no-untyped-def]
    items = client.get("/api/v1/events?band=Executive%20Alert", headers=h).json()["items"]
    return next(e for e in items if e["primary_type"] == "ENDPOINT_CHANGED")


def test_event_explanation_covers_four_principles(client, demo_pipeline):
    h = login(client, "cso@demo.example")
    ev = _exec_event(client, h)
    x = client.get(f"/api/v1/events/{ev['id']}/explanation", headers=h).json()
    assert x["principles"] == ["explanation", "meaningful", "explanation_accuracy", "knowledge_limits"]
    # Meaningful: plain-language summary naming the score, main driver and mapped asset
    assert "Scored" in x["summary"] and "XD-101" in x["summary"]
    # Explanation accuracy: drivers reproduce the stored score exactly
    s = x["score"]
    total_w = sum(d["weight"] for d in s["drivers"])
    recomputed = sum(d["weight"] * d["score"] for d in s["drivers"]) / total_w * s["magnitude_gate"]
    assert abs(recomputed - ev["materiality_score"]) < 0.2
    assert "Deterministic" in s["method"]
    assert s["counterfactuals"] and all(v["delta"] >= 0 for v in s["sensitivity"])
    # Explanation: mapping path + evidence coverage
    assert x["mapping"][0]["path"] and "competes_with" in x["mapping"][0]["path"][0]
    assert x["evidence"]["facts"] == x["evidence"]["facts_with_evidence"] > 0
    # Knowledge limits
    assert any("not calibrated" in k for k in x["knowledge_limits"])
    assert any("stale" in k for k in x["knowledge_limits"])  # sec_edgar never ran in the demo
    detail = client.get(f"/api/v1/events/{ev['id']}", headers=h).json()
    assert detail["explanation"]["summary"] == x["summary"]


def test_answer_explanation_and_transparency_card(client, demo_pipeline):
    h = login(client)
    out = client.post("/api/v1/ask", json={"question": "Is CA-201 better than XD-101?"}, headers=h).json()
    assert out["comparison_warning"], "superiority-style questions must carry the indirect-comparison warning"
    assert set(out["resolved_context"]["entity_labels"].values()) >= {"CA-201", "XD-101"}
    ex = out["explanation"]
    assert len(ex["steps"]) == 4 and any("Validated" in s for s in ex["steps"])
    assert any("indirect" in k.lower() for k in ex["knowledge_limits"])
    card = client.get("/api/v1/auth/ai-transparency", headers=h).json()
    assert card["data"]["customer_data_used_for_training"] is False
    assert card["not_intended_for"] and card["human_oversight"] and card["prompts"]


def test_comparison_warning_text_and_brief_submit(client, demo_pipeline):
    h = login(client)
    c = client.post("/api/v1/comparisons", json={"asset_ids": [str(demo_pipeline["xd101"]),
                                                               str(demo_pipeline["ids"]["asset:CA-201"])]}, headers=h).json()
    assert not any("['" in w for w in c["context_warnings"])
    rep = client.post("/api/v1/reports/briefs", json={"landscape_id": str(demo_pipeline["landscape_id"])}, headers=h).json()
    assert client.post(f"/api/v1/reports/{rep['id']}/submit", headers=h).json()["status"] == "in_review"
