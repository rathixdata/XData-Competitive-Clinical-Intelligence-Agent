"""Impact Agent / Trial-Change / Literature / Regulatory interpretation (FR-AI-004, Section 12).

Bounded service: it reads verified ChangeEvents + mapping rationale + retrieved evidence and returns
typed statements. It cannot write source-of-truth data; its output is validated by the Evidence Agent
before anything is published.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm import LLMService
from app.ai.prompts import load_prompt
from app.ai.statements import STATEMENT_SCHEMA, Statement
from app.ai.validator import EvidenceValidator, ValidationReport
from app.changes.taxonomy import ChangeType
from app.models import (
    ChangeEvent,
    Claim,
    GeneratedArtifact,
    IntelligenceEvent,
    SourceDocument,
    SourceSnapshot,
    Trial,
)
from app.rag.evidence import SOURCE_LABELS, Evidence, render_for_prompt
from app.rag.retriever import HybridRetriever, RetrievalQuery

WORKFLOW = "impact_narrative"
WORKFLOW_VERSION = "1.0.0"

NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"headline": {"type": "string"}, "statements": {"type": "array", "items": STATEMENT_SCHEMA}},
    "required": ["headline", "statements"],
    "additionalProperties": False,
}

FIELD_LABELS = {
    "enrollment": "Enrollment",
    "status": "Overall status",
    "phase": "Phase",
    "primary_completion_date": "Primary completion date",
    "completion_date": "Study completion date",
    "start_date": "Start date",
    "primary_endpoints": "Primary endpoint",
    "secondary_endpoints": "Secondary endpoints",
    "sponsor": "Lead sponsor",
    "collaborators": "Collaborators",
    "eligibility_criteria": "Eligibility criteria",
    "arms": "Arms",
    "interventions": "Interventions",
    "countries": "Countries",
    "locations": "Sites",
    "conditions": "Conditions",
    "brief_title": "Title",
    "official_title": "Official title",
    "primary_completion_date_type": "Primary completion date type",
}


def _fmt(v: Any) -> str:
    if v is None:
        return "not reported"
    if isinstance(v, list):
        if v and isinstance(v[0], dict):
            return "; ".join(str(x.get("measure") or x.get("name") or x.get("label") or x.get("facility") or x) for x in v)
        return ", ".join(str(x) for x in v) or "none"
    if isinstance(v, dict):
        return ", ".join(f"{k}: {x}" for k, x in v.items() if x is not None)
    return str(v)


def describe_change(ch: ChangeEvent, object_label: str) -> str:
    f = ch.field
    label = FIELD_LABELS.get(f, f.replace("_", " ").replace("sections.", "label section ").capitalize())
    t = ch.change_type
    if t in (ChangeType.ENDPOINT_CHANGED,) and ch.diff_detail:
        parts = []
        if ch.diff_detail.get("removed"):
            parts.append(f"removed {', '.join(ch.diff_detail['removed'])}")
        if ch.diff_detail.get("added"):
            parts.append(f"added {', '.join(ch.diff_detail['added'])}")
        for tf in ch.diff_detail.get("time_frame_changed", []):
            parts.append(f"time frame for {tf['measure']} changed from {tf['old']} to {tf['new']}")
        detail = "; ".join(parts) or "description edited"
        return f"{object_label}: {label} changed from {_fmt(ch.old_value)} to {_fmt(ch.new_value)} ({detail})."
    if t == ChangeType.LABEL_CHANGED:
        n = len((ch.diff_detail or {}).get("passages", []))
        return f"{object_label}: {label} text changed ({n} passage(s) modified) in the label version effective " \
               f"{_fmt((ch.new_value or {}).get('effective_date'))}."
    if t in (ChangeType.APPROVAL, ChangeType.SUPPLEMENTAL_APPROVAL):
        s = ch.new_value or {}
        return (f"{object_label}: FDA submission {s.get('submission_type')} {s.get('submission_number')} has status "
                f"{s.get('status')} dated {s.get('status_date')} ({s.get('class_description') or s.get('class_code')}).")
    if t in (ChangeType.NEW_PUBLICATION, ChangeType.CORPORATE_EVENT, ChangeType.CONFERENCE_ABSTRACT,
             ChangeType.TRIAL_REGISTERED):
        return f"{object_label}: newly observed - {_fmt(ch.new_value)}."
    if isinstance(ch.old_value, list) or isinstance(ch.new_value, list):
        dd = ch.diff_detail or {}
        return (f"{object_label}: {label} changed; added: {_fmt(dd.get('added')) if dd.get('added') else 'none'}; "
                f"removed: {_fmt(dd.get('removed')) if dd.get('removed') else 'none'}.")
    return f"{object_label}: {label} changed from {_fmt(ch.old_value)} to {_fmt(ch.new_value)}."


def structured_evidence(db: Session, changes: list[ChangeEvent], object_label: str) -> list[Evidence]:
    out = []
    for i, ch in enumerate(changes, 1):
        snap = db.get(SourceSnapshot, ch.to_snapshot_id)
        prev = db.get(SourceSnapshot, ch.from_snapshot_id) if ch.from_snapshot_id else None
        doc = db.get(SourceDocument, snap.source_document_id) if snap else None
        text = describe_change(ch, object_label)
        if prev and snap:
            text += (f" Compared snapshot v{prev.version} (retrieved {prev.retrieved_at.date().isoformat()}) with "
                     f"snapshot v{snap.version} (retrieved {snap.retrieved_at.date().isoformat()}).")
        out.append(Evidence(
            evidence_id=f"S{i}", kind="structured_field", source=ch.source,
            source_type=SOURCE_LABELS.get(ch.source, ch.source), text=text,
            source_document_id=str(doc.id) if doc else None, snapshot_id=str(snap.id) if snap else None,
            change_id=str(ch.id), object_type=ch.object_type, object_id=str(ch.object_id), uri=doc.uri if doc else None,
            title=doc.title if doc else None, section=ch.field, field_path=ch.field,
            retrieved_at=snap.retrieved_at if snap else None, rights=doc.rights if doc else {},
        ))
    return out


def object_label(db: Session, event: IntelligenceEvent) -> str:
    if event.object_type == "trial":
        t = db.get(Trial, event.object_id)
        if t:
            return f"{t.nct_id} ({t.sponsor_name or 'sponsor n/a'})"
    return event.title.split(":")[0][:80]


def _why(ch: ChangeEvent) -> str | None:
    t, tags, m = ch.change_type, set(ch.secondary_tags or []), ch.magnitude or {}
    if t == ChangeType.ENDPOINT_CHANGED and m.get("endpoint_level") == "primary":
        return ("The change in primary endpoint may indicate a revised statistical design or regulatory strategy, "
                "and could change what the eventual readout demonstrates.")
    if t == ChangeType.DATE_CHANGED and "DELAY" in tags:
        return "The later date may shift the expected timing of data availability for this program."
    if t == ChangeType.DATE_CHANGED and "ACCELERATION" in tags:
        return "The earlier date may bring forward the expected timing of data availability for this program."
    if t == ChangeType.ENROLLMENT_CHANGED and "ENROLLMENT_INCREASE" in tags:
        return "A larger enrollment target may reflect revised powering assumptions and could extend the timeline."
    if t == ChangeType.ENROLLMENT_CHANGED:
        return "A reduced enrollment target may reflect recruitment challenges or a revised design."
    if t == ChangeType.STATUS_CHANGED and "TRIAL_HALTED" in tags:
        return "The halted status may remove or delay a competitor in the overlapping population."
    if t == ChangeType.TRIAL_STARTED:
        return "Recruitment start may increase competition for patients and sites in the overlapping population."
    if t in (ChangeType.APPROVAL, ChangeType.SUPPLEMENTAL_APPROVAL):
        return "The regulatory action may change the treatment landscape for overlapping populations."
    if t == ChangeType.LABEL_CHANGED:
        return "The label change may affect the product's positioning or use in overlapping populations."
    if t == ChangeType.NEW_PUBLICATION:
        return "The publication may contain new evidence relevant to competitive positioning in this indication."
    if t == ChangeType.TRIAL_REGISTERED:
        return "A newly registered trial may signal a new entrant or expanded development in this indication."
    if t == ChangeType.CORPORATE_EVENT:
        return "The disclosure may contain strategic or pipeline information relevant to this landscape."
    return None


def deterministic_narrative(event: IntelligenceEvent, changes: list[ChangeEvent], sev: list[Evidence],
                            label: str) -> dict[str, Any]:
    st: list[dict[str, Any]] = []
    for ev in sev:
        st.append({"section": "what_changed", "statement": ev.text.split(" Compared snapshot")[0],
                   "statement_type": "FACT", "confidence": "Verified", "evidence_ids": [ev.evidence_id],
                   "affected_entity_ids": []})
    seen = set()
    for ch, ev in zip(changes, sev, strict=True):
        w = _why(ch)
        if w and w not in seen:
            seen.add(w)
            st.append({"section": "why_it_may_matter", "statement": w, "statement_type": "INFERENCE",
                       "confidence": "Medium", "evidence_ids": [ev.evidence_id], "affected_entity_ids": []})
    for m in event.impacted_assets or []:
        st.append({"section": "affected_assets",
                   "statement": f"{m['asset_name']} may be affected: {m['rationale']}.",
                   "statement_type": "INFERENCE", "confidence": "Medium" if m["proximity"] >= 0.6 else "Low",
                   "evidence_ids": [], "affected_entity_ids": [m["asset_id"]]})
    st.append({"section": "known_limitations",
               "statement": "Public evidence reviewed does not establish the rationale for these changes.",
               "statement_type": "UNKNOWN", "confidence": "Not applicable", "evidence_ids": [], "affected_entity_ids": []})
    if event.object_type == "trial":
        st.append({"section": "recommended_investigation",
                   "statement": "Review the registry version history and the sponsor's latest management commentary "
                                "or investor materials for context on these changes.",
                   "statement_type": "RECOMMENDED_INVESTIGATION", "confidence": "Not applicable",
                   "evidence_ids": [], "affected_entity_ids": []})
    else:
        st.append({"section": "recommended_investigation",
                   "statement": "Review the full source document and assess relevance to the affected internal assets.",
                   "statement_type": "RECOMMENDED_INVESTIGATION", "confidence": "Not applicable",
                   "evidence_ids": [], "affected_entity_ids": []})
    return {"headline": event.title, "statements": st}


def build_user_content(event: IntelligenceEvent, sev: list[Evidence], passages: list[Evidence]) -> str:
    mappings = "\n".join(
        f'- asset_id="{m["asset_id"]}" name="{m["asset_name"]}" proximity={m["proximity"]:.2f} rationale="{m["rationale"]}"'
        for m in event.impacted_assets or []
    ) or "- none mapped"
    comp = event.score_components.get("dimensions", {}) if event.score_components else {}
    return (
        f"<event id=\"{event.id}\" type=\"{event.primary_type}\" tags=\"{', '.join(event.secondary_tags or [])}\" "
        f"materiality=\"{event.materiality_score}\" band=\"{event.band}\">{event.title}</event>\n"
        f"<structured_changes>\n{render_for_prompt(sev)}\n</structured_changes>\n"
        f"<customer_asset_mappings>\n{mappings}\n</customer_asset_mappings>\n"
        f"<materiality_rationale>{ {k: v.get('rule_hits') for k, v in comp.items()} }</materiality_rationale>\n"
        f"<retrieved_evidence>\n{render_for_prompt(passages)}\n</retrieved_evidence>\n"
        "Write the impact narrative now. Use only the evidence ids shown above."
    )


def generate_narrative(db: Session, tenant_id: uuid.UUID, event: IntelligenceEvent,
                       *, use_llm: bool = True) -> tuple[GeneratedArtifact, ValidationReport]:
    changes = list(db.scalars(select(ChangeEvent).where(ChangeEvent.id.in_(event.change_ids))).all())
    changes.sort(key=lambda c: (c.field, str(c.id)))
    label = object_label(db, event)
    sev = structured_evidence(db, changes, label)
    retr = HybridRetriever(db)
    passages = retr.search(RetrievalQuery(
        text=f"{event.title} {' '.join(c.change_type.replace('_', ' ').lower() for c in changes)}",
        tenant_id=tenant_id, object_ids=[event.object_id], entity_ids=list(event.related_entity_ids or [])[:20],
        top_k=8, current_only=False))
    evidence = sev + passages
    fallback = lambda: deterministic_narrative(event, changes, sev, label)  # noqa: E731

    svc = LLMService(db, tenant_id)
    res = svc.generate(workflow=WORKFLOW, workflow_version=WORKFLOW_VERSION, prompt=load_prompt("impact_narrative"),
                       user_content=build_user_content(event, sev, passages), schema=NARRATIVE_SCHEMA,
                       offline=fallback, retrieval_set=[e.manifest() for e in evidence], force_offline=not use_llm)
    data = res.data
    statements = [Statement.from_dict(s) for s in data.get("statements", [])]
    if res.provider != "offline":
        # Platform-rendered FACTs for the verified changes always lead the narrative.
        det = [Statement.from_dict(s) for s in fallback()["statements"] if s["section"] == "what_changed"]
        statements = det + [s for s in statements if s.section != "what_changed"]
        if not any(s.statement_type == "UNKNOWN" for s in statements):
            statements.append(Statement("known_limitations", "Public evidence reviewed does not establish the "
                                        "rationale for these changes.", "UNKNOWN", "Not applicable"))
    valid_entity_ids = {m["asset_id"] for m in event.impacted_assets or []} | {str(x) for x in event.related_entity_ids or []}
    for s in statements:
        s.affected_entity_ids = [x for x in s.affected_entity_ids if x in valid_entity_ids]
    report = EvidenceValidator(db, tenant_id).validate(statements, evidence, use_judge=res.provider != "offline")
    artifact = persist_artifact(db, tenant_id, event, data.get("headline") or event.title, report, evidence, res)
    if not report.publishable:
        # The unsupported output is retained for audit but never published; publish the validated,
        # platform-rendered narrative instead and flag for analyst review.
        fb = fallback()
        fb_statements = [Statement.from_dict(s) for s in fb["statements"]]
        fb_report = EvidenceValidator(db, tenant_id).validate(fb_statements, evidence, use_judge=False)
        fb_art = persist_artifact(db, tenant_id, event, fb["headline"], fb_report, evidence, res, fallback_of=artifact)
        return fb_art, report
    return artifact, report


def persist_artifact(db: Session, tenant_id: uuid.UUID, event: IntelligenceEvent, headline: str,
                     report: ValidationReport, evidence: list[Evidence], res, fallback_of: GeneratedArtifact | None = None
                     ) -> GeneratedArtifact:  # type: ignore[no-untyped-def]
    ev_by_id = {e.evidence_id: e for e in evidence}
    sections: dict[str, list[dict[str, Any]]] = {}
    for s in report.statements:
        sections.setdefault(s.section, []).append(s.to_dict())
    cited = sorted({eid for s in report.statements for eid in s.evidence_ids if eid in ev_by_id},
                   key=lambda x: (x[0], int(x[1:]) if x[1:].isdigit() else 0))
    mwv = res.model_workflow_version if fallback_of is None else f"{WORKFLOW}@{WORKFLOW_VERSION}/deterministic-fallback"
    content = {
        "headline": headline,
        "sections": sections,
        "evidence": {eid: ev_by_id[eid].link() for eid in cited},
        "mappings": event.impacted_assets,
        "fallback_of": str(fallback_of.id) if fallback_of else None,
    }
    art = GeneratedArtifact(
        tenant_id=tenant_id, kind="impact_narrative", intel_event_id=event.id, content=content,
        generation_id=res.generation_id, validation_generation_id=report.judge_generation_id,
        validation=report.summary() | ({"fallback_used": True} if fallback_of else {}),
        publishable=report.publishable, review_status="Machine", model_workflow_version=mwv,
        evidence_snapshot_ids=[uuid.UUID(e.snapshot_id) for e in evidence if e.snapshot_id],
    )
    db.add(art)
    db.flush()
    for i, s in enumerate(report.statements):
        db.add(Claim(
            tenant_id=tenant_id, artifact_id=art.id, intel_event_id=event.id, ordinal=i, section=s.section,
            statement=s.statement, statement_type=s.statement_type, confidence=s.confidence,
            evidence_ids=s.evidence_ids, evidence_links=[ev_by_id[e].link() for e in s.evidence_ids if e in ev_by_id],
            affected_entities=[uuid.UUID(x) for x in s.affected_entity_ids],
            validation_status=s.validation_status, validation_detail=s.validation_detail,
            original_statement_type=s.original_statement_type, model_workflow_version=mwv,
        ))
    db.flush()
    return art
