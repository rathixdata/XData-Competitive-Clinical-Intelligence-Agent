"""End-to-end acceptance scenario (SRS Section 16) through the real pipeline + idempotency + provenance."""

from __future__ import annotations

import json

from sqlalchemy import func, select

from app.connectors.base import FetchPlan
from app.db.session import session_scope
from app.models import (
    ChangeEvent,
    Claim,
    DocumentChunk,
    GeneratedArtifact,
    GenerationRecord,
    IntelligenceEvent,
    Notification,
    SourceDocument,
    SourceSnapshot,
    Trial,
)
from app.pipeline.ingest import run_connector
from app.pipeline.intelligence import process_pending_changes
from app.seed.demo import PIVOTAL_NCT, trial_fixtures
from app.seed.fixtures import FixtureCTGovAdapter
from app.storage.object_store import get_object_store


def _pivotal_event(db, tenant_id):  # type: ignore[no-untyped-def]
    trial = db.scalar(select(Trial).where(Trial.nct_id == PIVOTAL_NCT))
    return trial, db.scalar(select(IntelligenceEvent).where(IntelligenceEvent.tenant_id == tenant_id,
                                                           IntelligenceEvent.object_id == trial.id))


def test_acceptance_scenario_end_to_end(demo_pipeline):
    tid = demo_pipeline["tenant_id"]
    with session_scope(tid) as db:
        trial, ev = _pivotal_event(db, tid)
        # 1-2 ingest + normalize: two retained snapshots with raw artifacts
        snaps = db.scalars(select(SourceSnapshot).where(SourceSnapshot.object_id == trial.id)
                           .order_by(SourceSnapshot.version)).all()
        assert [s.version for s in snaps] == [1, 2]
        assert snaps[0].normalized["enrollment"] == 320 and snaps[1].normalized["enrollment"] == 480
        # 3 resolve: sponsor + asset linked to canonical ids
        assert trial.sponsor_company_id == demo_pipeline["ids"]["company:Competitor A Therapeutics"]
        # 4 diff: exactly three structured change events with old/new values
        changes = db.scalars(select(ChangeEvent).where(ChangeEvent.object_id == trial.id,
                                                       ChangeEvent.suppressed.is_(False))).all()
        assert sorted(c.field for c in changes) == ["enrollment", "primary_completion_date", "primary_endpoints"]
        # 5-6 one deduplicated intelligence event, scored with explanation
        assert ev is not None and len(ev.change_ids) == 3
        assert ev.band == "Executive Alert" and ev.materiality_score >= 85
        assert set(ev.score_components["dimensions"]) == {"R", "C", "P", "T", "N"}
        # 7 mapped to XD-101 with a graph path
        assert ev.impacted_assets[0]["asset_name"] == "XD-101"
        preds = [h["predicate"] for h in ev.impacted_assets[0]["path"]]
        assert preds == ["competes_with", "evaluated_in"]
        # 8-10 retrieved evidence, bounded interpretation, validated claims
        art = db.get(GeneratedArtifact, ev.current_narrative_id)
        assert art.publishable and art.validation["publishable"]
        claims = db.scalars(select(Claim).where(Claim.artifact_id == art.id)).all()
        types = {c.statement_type for c in claims}
        assert {"FACT", "INFERENCE", "UNKNOWN", "RECOMMENDED_INVESTIGATION"} <= types
        facts = [c for c in claims if c.statement_type == "FACT"]
        assert len(facts) >= 3 and all(c.evidence_ids and c.evidence_links for c in facts)
        assert all(c.validation_status == "supported" for c in facts)
        for c in facts:  # claim-level provenance (FR-AI-003)
            link = c.evidence_links[0]
            assert link["source_document_id"] and link["snapshot_id"] and link["retrieved_at"] and link["field_path"]
        assert any("480" in c.statement for c in facts) and any("2027-11" in c.statement for c in facts)
        # FR-AI-007: governance record for the generation
        gen = db.get(GenerationRecord, art.generation_id)
        assert gen.prompt_version and gen.prompt_hash and gen.retrieval_set_hash and gen.workflow_version
        # 11 published + alert eligible
        assert ev.status == "published" and ev.published_at is not None
        notes = db.scalars(select(Notification).where(Notification.intel_event_ids.any(ev.id))).all()
        assert notes and notes[0].payload["title"].startswith("EXECUTIVE ALERT")
        assert notes[0].payload["verified_change"] and notes[0].payload["unknown"]
        assert ev.alert_eligible_at is not None
        assert (ev.alert_eligible_at - ev.source_fetched_at).total_seconds() < 15 * 60


def test_noise_changes_do_not_create_events(demo_pipeline):
    tid = demo_pipeline["tenant_id"]
    with session_scope(tid) as db:
        titles = [e.title for e in db.scalars(select(IntelligenceEvent)).all()]
        assert not any("title changed" in t.lower() for t in titles)
        # ordering-only country edit on NCT99000002 produced no country change event
        trial = db.scalar(select(Trial).where(Trial.nct_id == "NCT99000002"))
        country_changes = db.scalars(select(ChangeEvent).where(ChangeEvent.object_id == trial.id,
                                                               ChangeEvent.field == "countries")).all()
        assert not [c for c in country_changes if not c.suppressed]


def test_reruns_are_idempotent(demo_pipeline):
    tid = demo_pipeline["tenant_id"]
    with session_scope(bypass_rls=True) as db:
        counts = {m.__name__: db.scalar(select(func.count()).select_from(m))
                  for m in (SourceDocument, SourceSnapshot, ChangeEvent, IntelligenceEvent, DocumentChunk)}
    # identical re-fetch (connector rerun / retry) must not create anything new
    run_connector("ctgov", trigger="manual", adapter=FixtureCTGovAdapter(trial_fixtures(2)), plan=FetchPlan())
    process_pending_changes(use_llm=False)
    with session_scope(bypass_rls=True) as db:
        after = {m.__name__: db.scalar(select(func.count()).select_from(m))
                 for m in (SourceDocument, SourceSnapshot, ChangeEvent, IntelligenceEvent, DocumentChunk)}
    assert counts == after
    with session_scope(tid) as db:
        _, ev = _pivotal_event(db, tid)
        assert ev is not None


def test_raw_artifact_reconstruction_and_checksum(demo_pipeline):
    with session_scope(bypass_rls=True) as db:
        trial = db.scalar(select(Trial).where(Trial.nct_id == PIVOTAL_NCT))
        for snap in db.scalars(select(SourceSnapshot).where(SourceSnapshot.object_id == trial.id)).all():
            doc = db.get(SourceDocument, snap.source_document_id)
            store = get_object_store()
            assert store.verify(doc.storage_key, doc.checksum)
            raw = json.loads(store.get(doc.storage_key))
            assert raw["protocolSection"]["designModule"]["enrollmentInfo"]["count"] == snap.normalized["enrollment"]
            assert doc.rights.get("license") and doc.connector_version


def test_raw_artifacts_are_immutable(demo_pipeline):
    import pytest
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError), session_scope(bypass_rls=True) as db:
        doc = db.scalar(select(SourceDocument).limit(1))
        doc.checksum = "0" * 64
        db.flush()


def test_catalysts_track_changed_dates(demo_pipeline):
    from app.models import Catalyst

    with session_scope(bypass_rls=True) as db:
        trial = db.scalar(select(Trial).where(Trial.nct_id == PIVOTAL_NCT))
        pc = db.scalar(select(Catalyst).where(Catalyst.trial_id == trial.id, Catalyst.event_type == "PRIMARY_COMPLETION"))
        assert pc.date_basis == "SOURCED" and pc.expected_date.isoformat() == "2027-11-30"
        assert pc.history and pc.history[-1]["expected_date"] == "2027-06-30"
        inferred = db.scalar(select(Catalyst).where(Catalyst.trial_id == trial.id, Catalyst.event_type == "TOPLINE_READOUT"))
        assert inferred.date_basis == "INFERRED" and inferred.confidence == "Low"


def test_connector_run_health_recorded(demo_pipeline):
    from app.services.health import connector_health

    with session_scope(bypass_rls=True) as db:
        h = {x["key"]: x for x in connector_health(db)}
        assert h["ctgov"]["state"] == "healthy" and h["ctgov"]["last_run"]["records_fetched"] == 7
        assert h["sec_edgar"]["state"] == "never_run" and h["sec_edgar"]["stale"]
