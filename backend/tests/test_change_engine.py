"""Unit + regression tests: normalization, structured/document diff, noise suppression, fingerprints
(FR-CHG-002/003/004/005/006)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.changes.diff import diff_label, diff_objects, diff_trial, document_diff, fingerprint
from app.changes.taxonomy import ChangeType, primary_of
from app.connectors.base import FetchedRecord
from app.connectors.clinicaltrials import ClinicalTrialsGovAdapter
from app.pipeline.normalize import months_between, normalize_partial_date, normalize_phase, normalize_status
from app.seed.demo import PIVOTAL_NCT, trial_fixtures


def _normalized(study: dict) -> dict:
    a = ClinicalTrialsGovAdapter.__new__(ClinicalTrialsGovAdapter)
    nct = study["protocolSection"]["identificationModule"]["nctId"]
    rec = FetchedRecord(nct, "u", json.dumps(study).encode(), "application/json", datetime.now(UTC))
    return a.parse(rec)[0].normalized


def _pivotal(version: int) -> dict:
    return _normalized(next(s for s in trial_fixtures(version)
                            if s["protocolSection"]["identificationModule"]["nctId"] == PIVOTAL_NCT))


def test_normalizers():
    assert normalize_partial_date("June 2027") == "2027-06"
    assert normalize_partial_date("2027-06") == "2027-06"
    assert normalize_partial_date("June 30, 2027") == "2027-06-30"
    assert normalize_partial_date("2027") == "2027"
    assert normalize_phase(["PHASE2", "PHASE3"]) == "Phase 2/3"
    assert normalize_status("ACTIVE_NOT_RECRUITING") == "Active, not recruiting"
    assert months_between("2027-06", "2027-11") == 5.0


def test_acceptance_scenario_emits_three_typed_changes():
    """SRS Section 16: enrollment 320->480, completion Jun-2027->Nov-2027, endpoint ORR->PFS."""
    changes = [c for c in diff_trial(_pivotal(1), _pivotal(2)) if not c.suppressed]
    by_field = {c.field: c for c in changes}
    assert set(by_field) == {"enrollment", "primary_completion_date", "primary_endpoints"}
    assert by_field["enrollment"].change_type == ChangeType.ENROLLMENT_CHANGED
    assert (by_field["enrollment"].old, by_field["enrollment"].new) == (320, 480)
    assert by_field["enrollment"].magnitude["pct_change"] == 50.0
    assert by_field["primary_completion_date"].change_type == ChangeType.DATE_CHANGED
    assert by_field["primary_completion_date"].magnitude["shift_months"] == 5.0
    assert "DELAY" in by_field["primary_completion_date"].tags
    ep = by_field["primary_endpoints"]
    assert ep.change_type == ChangeType.ENDPOINT_CHANGED and "ENDPOINT_REPLACED" in ep.tags
    assert ep.detail["removed"] == ["Objective Response Rate (ORR)"]
    assert ep.detail["added"] == ["Progression-Free Survival (PFS)"]
    assert primary_of([c.change_type for c in changes]) == ChangeType.ENDPOINT_CHANGED


def test_formatting_and_ordering_changes_are_suppressed():
    old = {"brief_title": "BRV-310 First-line Target-X NSCLC", "countries": ["United States", "China"],
           "primary_completion_date": "2027-06", "conditions": ["NSCLC", "Lung Cancer"],
           "eligibility_criteria": "Inclusion Criteria: Adults with NSCLC."}
    new = {"brief_title": "BRV-310  first-line target-X NSCLC", "countries": ["China", "United States"],
           "primary_completion_date": "June 2027", "conditions": ["lung cancer", "NSCLC"],
           "eligibility_criteria": "Inclusion criteria: adults with NSCLC"}
    changes = diff_trial(old, new)
    assert changes, "differences should be observed"
    assert all(c.suppressed for c in changes), [(c.field, c.suppression_reason) for c in changes if not c.suppressed]
    reasons = {c.field: c.suppression_reason for c in changes}
    assert reasons["countries"] == "ordering_only"
    assert reasons["primary_completion_date"] == "formatting_only"


def test_status_halt_and_start():
    ch = diff_trial({"status": "Recruiting"}, {"status": "Terminated", "why_stopped": "Business decision"})[0]
    assert ch.change_type == ChangeType.STATUS_CHANGED and "TRIAL_HALTED" in ch.tags
    assert ch.detail["why_stopped"] == "Business decision"
    st = diff_trial({"status": "Not yet recruiting"}, {"status": "Recruiting"})[0]
    assert st.change_type == ChangeType.TRIAL_STARTED


def test_document_diff_highlights_passages():
    dd = document_diff("Indicated for NSCLC with Target-X mutation. Take once daily.",
                       "Indicated for NSCLC with Target-X mutation. Also indicated first-line. Take once daily.")
    assert dd["passages"] and dd["passages"][0]["op"] == "insert"
    assert "first-line" in dd["passages"][0]["new"]
    assert 0 < dd["similarity"] < 1


def test_label_diff_tags_indication_update():
    old = {"effective_date": "2025-03-01", "sections": {"indications_and_usage": "Indicated for 2L NSCLC."}}
    new = {"effective_date": "2026-09-15", "sections": {"indications_and_usage": "Indicated for 1L and 2L NSCLC."}}
    ch = diff_label(old, new)[0]
    assert ch.change_type == ChangeType.LABEL_CHANGED and "INDICATION_UPDATE" in ch.tags
    # whitespace-only edits produce nothing
    assert diff_label(old, {"sections": {"indications_and_usage": "Indicated  for 2L NSCLC. "}}) == []


def test_first_observation_baseline_vs_new_entrant():
    old_trial = {"nct_id": "NCT1", "start_date": "2020-01", "status": "Recruiting"}
    ch = diff_objects("trial", None, old_trial)[0]
    assert ch.change_type == ChangeType.TRIAL_REGISTERED and ch.suppressed
    fresh = {"nct_id": "NCT2", "start_date": datetime.now(UTC).strftime("%Y-%m"), "status": "Not yet recruiting"}
    assert not diff_objects("trial", None, fresh)[0].suppressed


def test_fingerprint_is_stable_and_formatting_insensitive():
    a = fingerprint("obj", "enrollment", 320, 480, "snap1")
    assert a == fingerprint("obj", "enrollment", 320, 480, "snap1")
    assert a != fingerprint("obj", "enrollment", 320, 480, "snap2")
    assert fingerprint("o", "f", ["A", "b"], "X", "s") == fingerprint("o", "f", ["B", "a"], "x", "s")


def test_drug_application_new_approval():
    old = {"approved_submissions": ["ORIG-1"], "submissions": []}
    new = {"approved_submissions": ["ORIG-1", "SUPPL-5"], "submissions": [
        {"submission_type": "SUPPL", "submission_number": "5", "status": "AP", "status_date": "2026-09-20",
         "class_code": "EFFICACY", "class_description": "Efficacy"}]}
    ch = diff_objects("drug_application", old, new)[0]
    assert ch.change_type == ChangeType.SUPPLEMENTAL_APPROVAL and "NEW_INDICATION_OR_EFFICACY" in ch.tags
