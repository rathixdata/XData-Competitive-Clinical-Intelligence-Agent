"""User-story level API workflows (Section 14 US-001..US-010)."""

from __future__ import annotations

from tests.conftest import login


def _exec_event(client, h):  # type: ignore[no-untyped-def]
    items = client.get("/api/v1/events?band=Executive%20Alert&sort=score", headers=h).json()["items"]
    return next(e for e in items if e["primary_type"] == "ENDPOINT_CHANGED")


def test_us001_landscape_configuration(client, seeded):
    h = login(client)
    tpl = client.get("/api/v1/templates", headers=h).json()[0]
    ls = client.post("/api/v1/landscapes", json={"name": "From template", "template_id": tpl["id"],
                                                 "members": [{"entity_type": "asset", "entity_id": str(seeded["xd101"]),
                                                              "role": "customer"}]}, headers=h).json()
    assert ls["config"]["band_thresholds"]["Executive Alert"] == 85
    assert "nct_ids" not in ls["config"]  # templates never copy customer-private data
    r = client.patch(f"/api/v1/landscapes/{ls['id']}", json={"config": {"band_thresholds": {"Feed": 60, "Analyst Review": 50}}},
                     headers=h)
    assert r.status_code == 422  # thresholds must ascend
    assert client.post(f"/api/v1/landscapes/{ls['id']}/archive", headers=h).json()["status"] == "archived"
    exp = client.get(f"/api/v1/landscapes/{ls['id']}/export", headers=h).json()
    assert exp["members"][0]["role"] == "customer"


def test_us002_trial_diff_and_history(client, demo_pipeline):
    h = login(client, "clinical@demo.example")
    hist = client.get("/api/v1/trials/NCT99000001/history?field=enrollment", headers=h).json()
    assert [x["value"] for x in hist["history"]["enrollment"]] == [320, 480]
    snap = client.get("/api/v1/trials/NCT99000001/snapshots/1?include_raw=true", headers=h).json()
    assert snap["checksum_verified"] and snap["raw"]["protocolSection"]["identificationModule"]["nctId"] == "NCT99000001"
    ev = _exec_event(client, h)
    d = client.get(f"/api/v1/events/{ev['id']}", headers=h).json()
    enr = next(c for c in d["changes"] if c["field"] == "enrollment")
    assert (enr["old_value"], enr["new_value"]) == (320, 480)
    assert enr["from_snapshot"]["version"] == 1 and enr["to_snapshot"]["version"] == 2
    assert enr["source_document"]["uri"].startswith("https://clinicaltrials.gov/study/")


def test_us003_us004_mapping_and_executive_alert(client, demo_pipeline):
    h = login(client, "cso@demo.example")
    ev = _exec_event(client, h)
    d = client.get(f"/api/v1/events/{ev['id']}", headers=h).json()
    assert d["impacts"][0]["asset_name"] == "XD-101" and d["impacts"][0]["path"]
    assert d["score_explanation"]["dimensions"]["C"]["rule_hits"]
    claims = d["narrative"]["claims"]
    assert {c["statement_type"] for c in claims} >= {"FACT", "INFERENCE", "UNKNOWN"}
    inbox = client.get("/api/v1/alerts/inbox", headers=h).json()
    assert any(n["payload"]["title"].startswith("EXECUTIVE ALERT") for n in inbox)
    evid = next(c for c in claims if c["statement_type"] == "FACT")["evidence_links"][0]
    doc = client.get(f"/api/v1/sources/documents/{evid['source_document_id']}", headers=h)
    assert doc.status_code == 200


def test_us005_publication_summarized_with_citation(client, demo_pipeline):
    h = login(client)
    items = client.get("/api/v1/events?event_type=NEW_PUBLICATION", headers=h).json()["items"]
    assert items
    pub = next(e for e in items if "Zelvatinib" in e["title"])
    d = client.get(f"/api/v1/events/{pub['id']}", headers=h).json()
    ev_links = [lk for c in d["narrative"]["claims"] for lk in c["evidence_links"]]
    assert any(lk["source"] == "pubmed" for lk in ev_links)
    chunk = next((lk for lk in ev_links if lk.get("chunk_id")), None)
    if chunk:
        ctx = client.get(f"/api/v1/sources/chunks/{chunk['chunk_id']}", headers=h).json()
        assert any(c["is_target"] for c in ctx["context"])


def test_us006_alias_correction_reused(client, demo_pipeline):
    h = login(client)
    r = client.post("/api/v1/entities/resolve", json={"mention": "Zelva XR", "entity_type": "asset"}, headers=h).json()
    assert r["status"] != "auto_linked"
    ca = str(demo_pipeline["ids"]["asset:CA-201"])
    assert client.post(f"/api/v1/entities/asset/{ca}/aliases", json={"alias": "Zelva XR", "alias_type": "brand",
                                                                     "reason": "brand name"}, headers=h).status_code == 201
    r2 = client.post("/api/v1/entities/resolve", json={"mention": "zelva-xr", "entity_type": "asset"}, headers=h).json()
    assert r2["entity_id"] == ca and r2["status"] == "auto_linked"


def test_us007_ask_what_changed_this_week(client, demo_pipeline):
    h = login(client)
    r = client.post("/api/v1/ask", json={"question": "What changed this week?",
                                         "landscape_id": str(demo_pipeline["landscape_id"])}, headers=h)
    assert r.status_code == 200
    out = r.json()
    assert out["statements"] and out["evidence"] and not out["abstained"]
    for fmt in ("docx", "pdf", "pptx", "md"):
        ex = client.get(f"/api/v1/ask/answers/{out['artifact_id']}/export?format={fmt}", headers=h)
        assert ex.status_code == 200 and len(ex.content) > 200


def test_ask_streaming_sse(client, demo_pipeline):
    h = login(client)
    with client.stream("POST", "/api/v1/ask/stream", json={"question": "What changed this week?"}, headers=h) as r:
        body = "".join(r.iter_text())
    assert "event: progress" in body and "event: answer" in body


def test_us008_connector_health_visible(client, demo_pipeline):
    h = login(client, "admin@demo.example")
    cons = {c["key"]: c for c in client.get("/api/v1/admin/connectors", headers=h).json()}
    assert cons["ctgov"]["last_success_at"] and cons["ctgov"]["last_run"]["records_fetched"] > 0
    assert cons["sec_edgar"]["stale"]
    dash = client.get("/api/v1/dashboard", headers=h).json()
    assert dash["health"]["banner"] and dash["assets"][0]["name"] == "XD-101"
    assert dash["material_developments"] and dash["upcoming_catalysts"] is not None
    runs = client.get("/api/v1/admin/connectors/ctgov/runs", headers=h).json()
    assert runs["total"] >= 2


def test_us009_audit_of_edits_and_generation(client, demo_pipeline):
    h = login(client)
    ev = _exec_event(client, h)
    d = client.get(f"/api/v1/events/{ev['id']}", headers=h).json()
    orig_claims = d["narrative"]["claims"]
    stmts = [{k: c[k] for k in ("section", "statement", "statement_type", "confidence", "evidence_ids")}
             | {"affected_entity_ids": []} for c in orig_claims]
    stmts[0]["statement"] = stmts[0]["statement"] + " (analyst note: confirmed in registry)"
    bad = [dict(stmts[0], evidence_ids=["E999"])]
    assert client.put(f"/api/v1/events/{ev['id']}/narrative", json={"statements": bad, "reason": "x y z"},
                      headers=h).status_code == 422
    r = client.put(f"/api/v1/events/{ev['id']}/narrative", json={"statements": stmts, "reason": "clarify"}, headers=h)
    assert r.status_code == 200 and r.json()["is_human_edited"] and r.json()["parent_id"] == d["narrative"]["id"]
    d2 = client.get(f"/api/v1/events/{ev['id']}", headers=h).json()
    assert d2["event"]["review_status"] == "Analyst-reviewed" and len(d2["narrative_history"]) >= 2
    orig = client.get(f"/api/v1/events/{ev['id']}/artifacts/{d['narrative']['id']}", headers=h).json()
    assert orig["claims"][0]["statement"] == orig_claims[0]["statement"]  # original retained
    assert client.post(f"/api/v1/events/{ev['id']}/review", json={"action": "approve"}, headers=h).json()["review_status"] == "Approved"
    audit = client.get("/api/v1/audit?action=narrative", headers=login(client, "auditor@demo.example")).json()
    assert {a["action"] for a in audit["items"]} >= {"narrative.edit", "narrative.approve"}
    gen_id = d["narrative"]["generation_id"]
    g = client.get(f"/api/v1/admin/generations/{gen_id}", headers=login(client, "auditor@demo.example")).json()
    assert g["prompt_version"] and g["model"]


def test_us010_feedback_and_kpis(client, demo_pipeline):
    h = login(client)
    ev = _exec_event(client, h)
    for label in ("USEFUL", "MATERIAL"):
        assert client.post("/api/v1/feedback", json={"intel_event_id": ev["id"], "label": label, "reason": "relevant"},
                           headers=h).status_code == 201
    k = client.get("/api/v1/kpis", headers=h).json()
    assert k["source_attribution_rate"] == 1.0 and k["high_priority_precision"] == 1.0
    assert k["events"] >= 5 and k["median_fetch_to_publish_minutes"] is not None
    lead = login(client, "lead@demo.example")
    ds = client.post("/api/v1/feedback/datasets", json={"name": "pilot"}, headers=lead).json()
    assert ds["record_count"] == 1 and ds["content_hash"]


def test_feed_filters_and_personalization(client, demo_pipeline):
    h = login(client)
    all_ = client.get("/api/v1/events", headers=h).json()
    assert all_["total"] >= 5
    hp = client.get("/api/v1/events?min_score=85", headers=h).json()
    assert all(e["materiality_score"] >= 85 for e in hp["items"])
    xd = str(demo_pipeline["xd101"])
    imp = client.get(f"/api/v1/events?impacted_asset_id={xd}", headers=h).json()
    assert imp["total"] >= 1
    ind = client.get("/api/v1/events?indication=NSCLC", headers=h).json()
    facets = client.get("/api/v1/events/facets", headers=h).json()
    assert "indication" in facets and "type" in facets
    assert ind["total"] >= 0
    pers = client.get("/api/v1/events?personalize=true", headers=h).json()
    assert all("personal_boost" in e for e in pers["items"])
    view = client.post("/api/v1/saved-views", json={"name": "HP", "view": "feed", "filters": {"min_score": 70},
                                                    "visibility": "tenant"}, headers=h).json()
    other = client.get("/api/v1/saved-views", headers=login(client, "cso@demo.example")).json()
    assert any(v["id"] == view["id"] and not v["owned"] for v in other["items"])


def test_alert_policy_preview_and_digest_dedup(client, demo_pipeline):
    from app.alerts.dispatcher import build_digests
    from app.db.session import session_scope

    h = login(client)
    pv = client.post("/api/v1/alerts/policies/preview", json={"min_score": 70, "days": 30}, headers=h).json()
    assert pv["matching_events"] >= 3 and pv["events_per_week"] > 0
    tid = demo_pipeline["tenant_id"]
    with session_scope(tid) as db:
        first = build_digests(db, tid, "daily")
    with session_scope(tid) as db:
        from app.models import AlertPolicy

        for p in db.query(AlertPolicy).all():
            p.last_digest_at = None
        second = build_digests(db, tid, "daily")
    assert first and not second  # same events at same version are not repeated


def test_executive_brief_review_before_distribution(client, demo_pipeline):
    h = login(client)
    rep = client.post("/api/v1/reports/briefs", json={"landscape_id": str(demo_pipeline["landscape_id"])}, headers=h).json()
    assert rep["status"] == "draft" and rep["content"]["top_developments"]
    assert "low_materiality_summary" in rep["content"]["sections"]
    lead = login(client, "lead@demo.example")
    assert client.post(f"/api/v1/reports/{rep['id']}/distribute", json={"distribution_list": ["cso@demo.example"]},
                       headers=lead).status_code == 422
    ed = client.patch(f"/api/v1/reports/{rep['id']}", json={"executive_summary": "Edited summary.", "reason": "tone"},
                      headers=h).json()
    assert ed["content"]["executive_summary"] == "Edited summary."
    assert client.post(f"/api/v1/reports/{rep['id']}/approve", headers=h).status_code == 403
    assert client.post(f"/api/v1/reports/{rep['id']}/approve", headers=lead).json()["status"] == "approved"
    assert client.post(f"/api/v1/reports/{rep['id']}/distribute", json={"distribution_list": ["cso@demo.example"]},
                       headers=lead).json()["status"] == "distributed"
    for fmt in ("docx", "pdf", "pptx"):
        assert client.get(f"/api/v1/reports/{rep['id']}/export?format={fmt}", headers=h).status_code == 200
    got = client.get(f"/api/v1/reports/{rep['id']}", headers=h).json()
    assert got["original_content"]["executive_summary"] != "Edited summary."


def test_matrix_comparison_and_calendar(client, demo_pipeline):
    h = login(client)
    m = client.get(f"/api/v1/landscapes/{demo_pipeline['landscape_id']}/matrix", headers=h).json()
    ca = next(r for r in m["rows"] if r["asset"] == "CA-201")
    assert ca["cells"]["enrollment"]["value"] == 480 and ca["cells"]["enrollment"]["provenance"]["snapshot_id"]
    assert all(c["provenance"] for r in m["rows"] for c in r["cells"].values() if c["value"] is not None)
    cmp_ = client.post("/api/v1/comparisons", json={"asset_ids": [str(demo_pipeline["xd101"]),
                                                                  str(demo_pipeline["ids"]["asset:BRV-310"])]}, headers=h).json()
    assert any("indirect" in w for w in cmp_["context_warnings"])
    assert any("differ" in w for w in cmp_["context_warnings"])
    cal = client.get("/api/v1/catalysts?to=2029-12-31", headers=h).json()
    bases = {c["date_basis"] for c in cal["items"]}
    assert bases == {"SOURCED", "INFERRED"} and any(c["changed"] for c in cal["items"])
    g = client.get(f"/api/v1/landscapes/{demo_pipeline['landscape_id']}/graph", headers=h).json()
    assert g["nodes"] and g["edges"]


def test_proximity_rule_requires_test_before_activation(client, demo_pipeline):
    h = login(client, "admin@demo.example")
    r = client.post("/api/v1/admin/proximity-rules", json={"name": "target-heavy", "landscape_id": str(demo_pipeline["landscape_id"]),
                                                           "weights": {"target": 0.6, "indication": 0.4}}, headers=h).json()
    assert client.post(f"/api/v1/admin/proximity-rules/{r['id']}/activate", headers=h).status_code == 422
    t = client.post(f"/api/v1/admin/proximity-rules/{r['id']}/test", json={}, headers=h).json()
    assert t["pairs"] and t["pairs"][0]["competitor"] in ("CA-201", "CDR-44", "DLT-9", "GMA-55", "LMN-60", "BRV-310", "KST-2")
    assert client.post(f"/api/v1/admin/proximity-rules/{r['id']}/activate", headers=h).json()["status"] == "active"


def test_watchlist_bulk_import_and_sharing(client, demo_pipeline):
    h = login(client)
    wl = client.post("/api/v1/watchlists", json={"name": "BD scan", "visibility": "team"}, headers=h).json()
    csv_body = "item_type,value\nasset,CA-201\ncompany,Bravo Oncology\nasset,Unknown-Thing-9\n"
    r = client.post(f"/api/v1/watchlists/{wl['id']}/import", content=csv_body, headers={**h, "Content-Type": "text/csv"}).json()
    assert r["added"] == 3 and len(r["unresolved"]) == 1
    other = login(client, "lead@demo.example")  # same team (CI)
    assert client.get(f"/api/v1/watchlists/{wl['id']}", headers=other).status_code == 200
    assert client.post(f"/api/v1/watchlists/{wl['id']}/items", json=[], headers=other).status_code == 403


def test_openapi_documented(client):
    spec = client.get("/api/v1/openapi.json").json()
    for path in ("/api/v1/landscapes", "/api/v1/entities/search", "/api/v1/trials/{ref}", "/api/v1/events",
                 "/api/v1/comparisons", "/api/v1/catalysts", "/api/v1/ask", "/api/v1/feedback", "/api/v1/alerts/policies",
                 "/api/v1/reports/briefs", "/api/v1/admin/connectors", "/api/v1/audit"):
        assert path in spec["paths"], path


def test_health_endpoints(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code in (200, 503)
    assert b"xdata_http_requests_total" in client.get("/metrics").content
