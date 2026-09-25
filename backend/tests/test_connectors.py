"""Connector contract tests (recorded-fixture shapes) and resilience (Section 19)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.connectors.base import FetchContext, FetchedRecord, FetchPlan
from app.connectors.clinicaltrials import ClinicalTrialsGovAdapter
from app.connectors.corporate import FeedAdapter, SecEdgarAdapter
from app.connectors.http import ConnectorHTTPError, SourceHttpClient
from app.connectors.openfda import OPENFDA_DISCLAIMER, DrugLabelAdapter, DrugsAtFDAAdapter
from app.connectors.pubmed import PubMedAdapter
from app.seed.demo import label_fixture, publication_fixtures, trial_fixtures


def _client(handler, key="test", **kw) -> SourceHttpClient:  # type: ignore[no-untyped-def]
    return SourceHttpClient(key, 1000, transport=httpx.MockTransport(handler), base_backoff=0.01, **kw)


def test_ctgov_parse_contract():
    a = ClinicalTrialsGovAdapter(client=_client(lambda r: httpx.Response(200)))
    st = trial_fixtures(1)[0]
    rec = FetchedRecord("NCT99000001", "u", json.dumps(st).encode(), "application/json", datetime.now(UTC))
    n = a.parse(rec)[0]
    assert n.object_type == "trial" and n.normalized["phase"] == "Phase 3" and n.normalized["status"] == "Recruiting"
    assert n.normalized["primary_endpoints"][0]["measure"] == "Objective Response Rate (ORR)"
    kinds = {(m.entity_type, m.role) for m in n.mentions}
    assert ("company", "sponsor") in kinds and ("asset", "intervention") in kinds and ("indication", "condition") in kinds
    assert {s.section for s in n.sections} >= {"design", "primary_outcomes", "eligibility"}
    assert a.rights()["license"].startswith("public-domain")


def test_ctgov_fetch_monitored_and_discovery_with_pagination():
    study = trial_fixtures(1)[1]
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.url.path.endswith("/studies/NCT99000001"):
            return httpx.Response(200, json=trial_fixtures(1)[0])
        if req.url.path.endswith("/studies/NCT00000000"):
            return httpx.Response(404)
        if "pageToken" not in req.url.params:
            return httpx.Response(200, json={"studies": [study], "nextPageToken": "p2"})
        return httpx.Response(200, json={"studies": [trial_fixtures(1)[2]]})

    a = ClinicalTrialsGovAdapter(client=_client(handler))
    plan = FetchPlan(nct_ids={"NCT99000001", "NCT00000000"}, trial_queries=[{"cond": "nsclc", "intr": "inhibitor"}])
    recs = list(a.fetch(FetchContext(plan=plan, checkpoint={}, settings={})))
    assert [r.source_object_id for r in recs] == ["NCT99000001", "NCT99000002", "NCT99000003"]
    assert recs[1].query_provenance["mode"] == "discovery"


def test_http_retries_on_429_with_retry_after_then_succeeds():
    n = {"i": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        n["i"] += 1
        if n["i"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    res = _client(handler).get("https://example.org/x")
    assert res.json() == {"ok": True} and n["i"] == 3


def test_http_gives_up_after_max_attempts_and_raises():
    c = _client(lambda r: httpx.Response(503), max_attempts=2)
    with pytest.raises(ConnectorHTTPError):
        c.get("https://example.org/x")


def test_http_transport_timeouts_are_retried():
    n = {"i": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        n["i"] += 1
        if n["i"] == 1:
            raise httpx.ReadTimeout("timeout", request=req)
        return httpx.Response(200, json={})

    _client(handler).get("https://example.org/x")
    assert n["i"] == 2


def test_rate_limiter_throttles():
    import time

    from app.connectors.http import _LocalBucket

    b = _LocalBucket(rate=20, burst=1)
    t0 = time.monotonic()
    waits = [b.acquire() for _ in range(5)]
    assert waits[0] == 0 and sum(waits) >= 0.15
    assert time.monotonic() - t0 < 1


def test_pubmed_parse_contract_and_dedup():
    a = PubMedAdapter(client=_client(lambda r: httpx.Response(200)))
    pmid, xml = publication_fixtures()[0]
    n = a.parse(FetchedRecord(pmid, "u", xml, "application/xml", datetime.now(UTC)))[0]
    assert n.normalized["pmid"] == pmid and "objective response rate was 41%" in n.normalized["abstract"]
    assert n.normalized["nct_ids"] == ["NCT99000001"] and n.normalized["doi"]
    assert "Clinical Trial, Phase II" in n.normalized["publication_types"]
    assert any(m.entity_type == "kol" for m in n.mentions)


def test_pubmed_fetch_dedups_pmids_across_queries():
    _, xml = publication_fixtures()[0]

    def handler(req: httpx.Request) -> httpx.Response:
        if "esearch" in req.url.path:
            return httpx.Response(200, json={"esearchresult": {"idlist": ["99100001"]}})
        return httpx.Response(200, content=b"<PubmedArticleSet>" + xml + b"</PubmedArticleSet>")

    a = PubMedAdapter(client=_client(handler))
    plan = FetchPlan(pubmed_queries=[{"query": "q1"}, {"query": "q2"}])
    recs = list(a.fetch(FetchContext(plan=plan, checkpoint={}, settings={})))
    assert len(recs) == 1 and recs[0].query_provenance["query"] == "q1"


def test_openfda_label_and_drugsfda_contract():
    lab = DrugLabelAdapter(client=_client(lambda r: httpx.Response(200)))
    rec = FetchedRecord("demo-set-0001", "u", json.dumps(label_fixture(2)).encode(), "application/json", datetime.now(UTC))
    n = lab.parse(rec)[0]
    assert n.object_type == "label" and "first-line" in n.normalized["sections"]["indications_and_usage"]
    assert lab.rights()["disclaimer"] == OPENFDA_DISCLAIMER
    app_rec = {"application_number": "NDA999001", "sponsor_name": "BRAVO ONCOLOGY", "openfda": {"brand_name": ["BRAVITRA"]},
               "products": [{"brand_name": "BRAVITRA", "dosage_form": "TABLET", "route": "ORAL"}],
               "submissions": [{"submission_type": "ORIG", "submission_number": "1", "submission_status": "AP",
                                "submission_status_date": "20250301", "submission_class_code": "TYPE 1"}]}
    d = DrugsAtFDAAdapter(client=_client(lambda r: httpx.Response(200)))
    dn = d.parse(FetchedRecord("NDA999001", "u", json.dumps(app_rec).encode(), "application/json", datetime.now(UTC)))[0]
    assert dn.normalized["approved_submissions"] == ["ORIG-1"]
    assert dn.normalized["submissions"][0]["status_date"] == "2025-03-01"


def test_sec_edgar_filters_material_forms():
    sub = {"name": "Bravo Oncology", "tickers": ["BRVO"], "filings": {"recent": {
        "accessionNumber": ["0001-26-000001", "0001-26-000002"], "form": ["8-K", "4"],
        "filingDate": ["2026-09-20", "2026-09-21"], "reportDate": ["", ""], "primaryDocument": ["d8k.htm", "f4.xml"],
        "primaryDocDescription": ["8-K", "Form 4"], "items": ["8.01", ""]}}}

    def handler(req: httpx.Request) -> httpx.Response:
        if "submissions" in req.url.path:
            return httpx.Response(200, json=sub)
        return httpx.Response(200, text="<html><body><p>Bravo announces topline <script>x()</script>results</p></body></html>")

    a = SecEdgarAdapter(client=_client(handler))
    recs = list(a.fetch(FetchContext(plan=FetchPlan(sec_ciks={"9990002"}), checkpoint={}, settings={})))
    assert len(recs) == 1
    n = a.parse(recs[0])[0]
    assert n.object_type == "disclosure" and "topline results" in n.sections[0].text and "x()" not in n.sections[0].text


def test_feed_rights_policy_enforced():
    called = []
    a = FeedAdapter("conference", client=_client(lambda r: (called.append(1), httpx.Response(200, json={"items": []}))[1]))
    plan = FetchPlan(feeds=[{"kind": "conference", "url": "https://x/feed.json", "rights": {"policy": "unknown"}},
                            {"kind": "conference", "url": "https://y/feed.json", "rights": {"policy": "public"}}])
    list(a.fetch(FetchContext(plan=plan, checkpoint={}, settings={})))
    assert len(called) == 1  # only the permitted feed was fetched


def test_malformed_record_does_not_abort_run(seeded):
    from app.pipeline.ingest import run_connector
    from app.seed.fixtures import FixtureCTGovAdapter

    good = trial_fixtures(1)[0]
    bad = {"protocolSection": {"identificationModule": {"nctId": "NCT99999999"}, "designModule": {"phases": 5}}}
    run_id = run_connector("ctgov", trigger="manual", adapter=FixtureCTGovAdapter([bad, good]), plan=FetchPlan())
    from app.db.session import session_scope
    from app.models import ConnectorRun

    with session_scope(bypass_rls=True) as db:
        run = db.get(ConnectorRun, run_id)
        assert run.status == "partial" and run.errors == 1 and run.records_new == 1
        assert run.error_detail[0]["source_object_id"] == "NCT99999999"
