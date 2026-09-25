"""Ask-the-Landscape (FR-QA-001..006): retrieval-augmented, evidence-validated answers.

Pipeline: understand question (entities, referents from session memory, time window, comparison intent)
-> assemble evidence from three channels:
   S* structured landscape-matrix rows (current canonical state, with snapshot provenance)
   C* change records from version history within the time window (temporal questions, FR-QA-003)
   E* hybrid-retrieved passages (dense + lexical + entity-scoped)
-> grounded generation (typed statements, answer contract) -> Evidence Agent validation -> abstain when
   support is insufficient (FR-AI-008) -> persist answer, claims and session context.
All retrieval is tenant-scoped (only the caller's landscapes/events + the public corpus).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai.agents.impact import describe_change, object_label
from app.ai.explain import explain_answer
from app.ai.llm import LLMService
from app.ai.prompts import load_prompt
from app.ai.statements import STATEMENT_SCHEMA, Statement
from app.ai.validator import EvidenceValidator, lexical_support
from app.entities.graph import neighbours
from app.entities.resolver import normalize_alias
from app.models import (
    AskSession,
    AskTurn,
    Asset,
    Catalyst,
    ChangeEvent,
    Claim,
    Company,
    EntityAlias,
    GeneratedArtifact,
    IntelligenceEvent,
    Landscape,
    LandscapeMember,
    SourceDocument,
    SourceSnapshot,
    Trial,
)
from app.rag.evidence import SOURCE_LABELS, Evidence, render_for_prompt
from app.rag.retriever import HybridRetriever, RetrievalQuery

WORKFLOW = "ask_landscape"
WORKFLOW_VERSION = "1.0.0"
COMPARISON_WARNING = (
    "Cross-trial comparisons are indirect: trials differ in populations, lines of therapy, biomarker selection, "
    "endpoints, designs and follow-up. Side-by-side values do not establish superiority or inferiority."
)

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "statements": {"type": "array", "items": STATEMENT_SCHEMA},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "comparison_warning": {"type": "string"},
        "abstained": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["High", "Medium", "Low", "Not applicable"]},
    },
    "required": ["answer", "statements", "limitations", "comparison_warning", "abstained", "confidence"],
    "additionalProperties": False,
}

_REFERENT = re.compile(r"\b(those|these|them|they|their|it|its|that asset|those competitors|same)\b", re.I)
_COMPARE = re.compile(r"\b(compare|comparison|compared|versus|vs\.?|differ\w*|side[- ]by[- ]side|against|better|worse|superior|inferior|outperform\w*|beat|stronger|weaker|best-in-class)\b", re.I)
_TIMELINE = re.compile(r"\b(timeline|readout|completion|catalyst|when|date|delay|moved|slip)\w*", re.I)
_NCT = re.compile(r"\bNCT\d{8}\b", re.I)


@dataclass
class QueryPlan:
    question: str
    entity_ids: list[uuid.UUID] = field(default_factory=list)
    entity_labels: dict[str, str] = field(default_factory=dict)
    used_referents: bool = False
    since: datetime | None = None
    until: datetime | None = None
    temporal: bool = False
    comparison: bool = False
    timeline: bool = False

    def to_context(self) -> dict[str, Any]:
        return {"entity_ids": [str(e) for e in self.entity_ids], "entity_labels": self.entity_labels,
                "since": self.since.isoformat() if self.since else None, "comparison": self.comparison}


def parse_time_window(q: str, now: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    now = now or datetime.now(UTC)
    s = q.lower()
    if "today" in s:
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    if "yesterday" in s:
        d = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return d, d + timedelta(days=1)
    if "this week" in s:
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if "last week" in s:
        start = (now - timedelta(days=now.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=7)
    if "this month" in s:
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
    if "last month" in s:
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev = (first - timedelta(days=1)).replace(day=1)
        return prev, first
    m = re.search(r"(?:past|last)\s+(\d+)\s+(day|week|month)s?", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now - timedelta(days=n * {"day": 1, "week": 7, "month": 30}[unit]), now
    m = re.search(r"since\s+(\d{4}-\d{2}-\d{2})", s)
    if m:
        return datetime.fromisoformat(m.group(1)).replace(tzinfo=UTC), now
    if re.search(r"\b(recent(ly)?|latest|new)\b", s):
        return now - timedelta(days=30), now
    return None, None


def landscape_entities(db: Session, tenant_id: uuid.UUID, landscape_id: uuid.UUID | None) -> dict[uuid.UUID, str]:
    stmt = select(LandscapeMember).where(LandscapeMember.tenant_id == tenant_id)
    if landscape_id:
        stmt = stmt.where(LandscapeMember.landscape_id == landscape_id)
    out: dict[uuid.UUID, str] = {}
    for m in db.scalars(stmt).all():
        obj = db.get({"asset": Asset, "company": Company, "trial": Trial}.get(m.entity_type, Asset), m.entity_id)
        if obj is None:
            continue
        out[m.entity_id] = getattr(obj, "canonical_name", None) or getattr(obj, "nct_id", None) or str(m.entity_id)
        if m.entity_type == "asset":
            for t in neighbours(db, m.entity_id, predicate="evaluated_in"):
                tr = db.get(Trial, t)
                if tr:
                    out.setdefault(t, tr.nct_id or tr.title[:40])
    return out


def plan_query(db: Session, tenant_id: uuid.UUID, question: str, session: AskSession | None,
               landscape_id: uuid.UUID | None) -> QueryPlan:
    plan = QueryPlan(question=question)
    plan.since, plan.until = parse_time_window(question)
    plan.temporal = plan.since is not None or bool(re.search(r"\bchang|moved|updat|new\b", question, re.I))
    plan.comparison = bool(_COMPARE.search(question))
    plan.timeline = bool(_TIMELINE.search(question))
    qn = f" {normalize_alias(re.sub(r'[?!,;]', ' ', question))} "
    scope = landscape_entities(db, tenant_id, landscape_id)
    found: dict[uuid.UUID, str] = {}
    if scope:
        aliases = db.scalars(select(EntityAlias).where(
            EntityAlias.entity_id.in_(list(scope)),
            or_(EntityAlias.tenant_id.is_(None), EntityAlias.tenant_id == tenant_id))).all()
        for a in aliases:
            if len(a.alias_norm) >= 3 and f" {a.alias_norm} " in qn:
                found[a.entity_id] = scope[a.entity_id]
    for nct in _NCT.findall(question):
        t = db.scalar(select(Trial).where(Trial.nct_id == nct.upper()))
        if t:
            found[t.id] = t.nct_id
    if re.search(r"\bcompetitor", question, re.I) and not found and landscape_id:
        for m in db.scalars(select(LandscapeMember).where(LandscapeMember.landscape_id == landscape_id,
                                                          LandscapeMember.role == "competitor",
                                                          LandscapeMember.entity_type == "asset")).all():
            if m.entity_id in scope:
                found[m.entity_id] = scope[m.entity_id]
    if not found and session and _REFERENT.search(question):
        prev = (session.context or {}).get("entity_labels", {})
        for k, v in prev.items():
            found[uuid.UUID(k)] = v
        plan.used_referents = bool(prev)
        if not plan.since and (session.context or {}).get("since"):
            plan.since = datetime.fromisoformat(session.context["since"])
    plan.entity_ids = list(found)
    plan.entity_labels = {str(k): v for k, v in found.items()}
    return plan


def _matrix_rows(db: Session, tenant_id: uuid.UUID, landscape_id: uuid.UUID | None,
                 asset_ids: list[uuid.UUID], limit: int = 12) -> list[Evidence]:
    rows: list[Evidence] = []
    if not asset_ids and landscape_id:
        asset_ids = list(db.scalars(select(LandscapeMember.entity_id).where(
            LandscapeMember.landscape_id == landscape_id, LandscapeMember.entity_type == "asset")).all())
    for aid in asset_ids[:limit]:
        a = db.get(Asset, aid)
        if a is None:
            continue
        comp = db.get(Company, a.owner_company_id) if a.owner_company_id else None
        p = a.profile or {}
        trials = [db.get(Trial, t) for t in neighbours(db, aid, predicate="evaluated_in")]
        trial_txt = "; ".join(
            f"{t.nct_id}: {t.phase or 'phase n/a'}, status {t.status}, enrollment {t.enrollment}, primary completion "
            f"{(t.current or {}).get('primary_completion_date')}, primary endpoint "
            f"{', '.join(o.get('measure', '') for o in (t.current or {}).get('primary_endpoints', []))}"
            for t in trials if t)
        def fv(v: Any) -> str:
            if v in (None, "", []):
                return "not reported"
            return ", ".join(map(str, v)) if isinstance(v, list) else str(v)

        text = (f"{a.canonical_name} ({'internal asset' if a.is_internal else 'competitor asset'}; owner "
                f"{comp.canonical_name if comp else 'not reported'}). Mechanism/target: {fv(p.get('mechanism') or p.get('targets'))}. "
                f"Modality: {fv(a.modality or p.get('modality'))}. Stage: {fv(a.stage or p.get('stage'))}. Indication: "
                f"{fv(p.get('indications') or p.get('indication'))}. Population/line: {fv(p.get('population') or p.get('line_of_therapy'))}. "
                f"Biomarker: {fv(p.get('biomarkers') or p.get('biomarker'))}. Primary endpoint: {fv(p.get('endpoint'))}. "
                f"Dosing: {fv(p.get('dosing'))}. Trials: {trial_txt or 'none linked'}.")
        t0 = next((t for t in trials if t and t.current_snapshot_id), None)
        snap = db.get(SourceSnapshot, t0.current_snapshot_id) if t0 else None
        doc = db.get(SourceDocument, snap.source_document_id) if snap else None
        rows.append(Evidence(
            evidence_id=f"S{len(rows) + 1}", kind="structured_field",
            source="internal" if a.is_internal else (doc.source if doc else "ctgov"),
            source_type="Customer internal asset profile" if a.is_internal else SOURCE_LABELS.get(doc.source if doc else "ctgov"),
            text=text, source_document_id=str(doc.id) if doc else None, snapshot_id=str(snap.id) if snap else None,
            object_type="asset", object_id=str(a.id), uri=doc.uri if doc else None, title=a.canonical_name,
            section="landscape_matrix", field_path=f"asset.profile@v{a.profile_version}",
            retrieved_at=snap.retrieved_at if snap else a.updated_at))
    return rows


def _change_records(db: Session, tenant_id: uuid.UUID, landscape_id: uuid.UUID | None, plan: QueryPlan,
                    limit: int = 25) -> list[Evidence]:
    since = plan.since or (datetime.now(UTC) - timedelta(days=30))
    stmt = select(IntelligenceEvent).where(IntelligenceEvent.tenant_id == tenant_id,
                                           IntelligenceEvent.detected_at >= since)
    if plan.until:
        stmt = stmt.where(IntelligenceEvent.detected_at <= plan.until)
    if landscape_id:
        stmt = stmt.where(IntelligenceEvent.landscape_id == landscape_id)
    events = db.scalars(stmt.order_by(IntelligenceEvent.materiality_score.desc()).limit(limit)).all()
    if plan.entity_ids:
        ids = set(plan.entity_ids)
        events = [e for e in events if ids & {e.object_id, e.asset_id, e.company_id, *(e.related_entity_ids or [])}]
    out: list[Evidence] = []
    for e in events:
        for ch in db.scalars(select(ChangeEvent).where(ChangeEvent.id.in_(e.change_ids))).all():
            snap = db.get(SourceSnapshot, ch.to_snapshot_id)
            doc = db.get(SourceDocument, snap.source_document_id) if snap else None
            txt = (f"Detected {ch.detected_at.date().isoformat()}: {describe_change(ch, object_label(db, e))} "
                   f"Intelligence event materiality {e.materiality_score:.0f} ({e.band}).")
            out.append(Evidence(
                evidence_id=f"C{len(out) + 1}", kind="change_event", source=ch.source,
                source_type=SOURCE_LABELS.get(ch.source, ch.source), text=txt, change_id=str(ch.id),
                source_document_id=str(doc.id) if doc else None, snapshot_id=str(snap.id) if snap else None,
                object_type=ch.object_type, object_id=str(ch.object_id), uri=doc.uri if doc else None,
                title=e.title, section=ch.field, field_path=ch.field, retrieved_at=ch.source_fetched_at,
                published_at=ch.detected_at, rights=doc.rights if doc else {}))
    return out


def _catalyst_records(db: Session, plan: QueryPlan, start_index: int) -> list[Evidence]:
    stmt = select(Catalyst).where(Catalyst.status == "upcoming")
    if plan.entity_ids:
        stmt = stmt.where(or_(Catalyst.asset_id.in_(plan.entity_ids), Catalyst.trial_id.in_(plan.entity_ids)))
    out = []
    for c in db.scalars(stmt.order_by(Catalyst.expected_date.nulls_last()).limit(15)).all():
        when = c.expected_date.isoformat() if c.expected_date else f"{c.window_start} to {c.window_end}"
        out.append(Evidence(
            evidence_id=f"S{start_index + len(out)}", kind="structured_field", source="ctgov",
            source_type="Catalyst calendar", text=f"{c.title}: expected {when} (date basis {c.date_basis}, "
                                                  f"confidence {c.confidence}).",
            source_document_id=str(c.source_document_id) if c.source_document_id else None,
            object_type="catalyst", object_id=str(c.id), section="catalyst", field_path=c.event_type,
            retrieved_at=c.updated_at))
    return out


def _offline_answer(plan: QueryPlan, structured: list[Evidence], changes: list[Evidence],
                    passages: list[Evidence]) -> dict[str, Any]:
    st: list[dict[str, Any]] = []
    lim: list[str] = []
    if plan.temporal and changes:
        for c in changes[:10]:
            st.append({"section": "answer", "statement": c.text.split(" Intelligence event")[0],
                       "statement_type": "FACT", "confidence": "Verified", "evidence_ids": [c.evidence_id],
                       "affected_entity_ids": []})
        answer = f"{len(changes)} change record(s) were detected in the requested window; the most material are listed below."
    elif plan.comparison and structured:
        for s in structured[:6]:
            st.append({"section": "answer", "statement": s.text, "statement_type": "FACT", "confidence": "Verified",
                       "evidence_ids": [s.evidence_id], "affected_entity_ids": []})
        answer = "Side-by-side attributes for the requested assets are listed below with their sources."
    else:
        good = [p for p in passages if lexical_support(plan.question, p.text) >= 0.3][:3]
        if not good and structured and plan.entity_ids:
            good = structured[:2]
        for p in good:
            st.append({"section": "answer", "statement": _best_sentence(plan.question, p.text), "statement_type": "FACT",
                       "confidence": "Verified", "evidence_ids": [p.evidence_id], "affected_entity_ids": []})
        if not good:
            return {"answer": "The available evidence in this landscape is insufficient to answer this question.",
                    "statements": [{"section": "limitations", "statement": "No retained source evidence addresses this "
                                    "question.", "statement_type": "UNKNOWN", "confidence": "Not applicable",
                                    "evidence_ids": [], "affected_entity_ids": []}],
                    "limitations": ["Answer generated in deterministic extractive mode."],
                    "comparison_warning": "", "abstained": True, "confidence": "Not applicable"}
        answer = "Relevant retained evidence is summarised below."
    lim.append("Answer generated in deterministic extractive mode (no language model interpretation).")
    return {"answer": answer, "statements": st, "limitations": lim,
            "comparison_warning": COMPARISON_WARNING if plan.comparison else "", "abstained": False,
            "confidence": "Medium"}


def _best_sentence(question: str, text: str) -> str:
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 20] or [text]
    return max(sents, key=lambda s: lexical_support(question, s))[:600]


def ask(db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID, question: str,
        session_id: uuid.UUID | None = None, landscape_id: uuid.UUID | None = None,
        progress=None) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    def emit(stage: str, **kw: Any) -> None:
        if progress:
            progress({"stage": stage, **kw})

    session = db.get(AskSession, session_id) if session_id else None
    if session is not None and (session.user_id != user_id or session.tenant_id != tenant_id):
        session = None  # never cross user/tenant boundaries (FR-QA-005)
    if landscape_id and db.get(Landscape, landscape_id) is None:
        landscape_id = None
    if session is None:
        session = AskSession(tenant_id=tenant_id, user_id=user_id, landscape_id=landscape_id, context={},
                             title=question[:120])
        db.add(session)
        db.flush()
    landscape_id = landscape_id or session.landscape_id

    plan = plan_query(db, tenant_id, question, session, landscape_id)
    emit("planned", entities=plan.entity_labels, temporal=plan.temporal, comparison=plan.comparison)
    structured = _matrix_rows(db, tenant_id, landscape_id, plan.entity_ids) if (plan.comparison or plan.entity_ids) else []
    if plan.timeline:
        structured += _catalyst_records(db, plan, len(structured) + 1)
    changes = _change_records(db, tenant_id, landscape_id, plan) if plan.temporal else []
    passages = HybridRetriever(db).search(RetrievalQuery(
        text=question, tenant_id=tenant_id, entity_ids=plan.entity_ids, top_k=10,
        published_after=plan.since if plan.temporal and plan.since else None, current_only=not plan.temporal))
    evidence = structured + changes + passages
    emit("retrieved", structured=len(structured), changes=len(changes), passages=len(passages))

    user = (f"<question>{question}</question>\n<resolved_context>{plan.to_context()}</resolved_context>\n"
            f"<structured_records>\n{render_for_prompt(structured)}\n</structured_records>\n"
            f"<changes>\n{render_for_prompt(changes)}\n</changes>\n<evidence>\n{render_for_prompt(passages)}\n</evidence>")
    svc = LLMService(db, tenant_id)
    res = svc.generate(workflow=WORKFLOW, workflow_version=WORKFLOW_VERSION, prompt=load_prompt("ask_landscape"),
                       user_content=user, schema=ANSWER_SCHEMA,
                       offline=lambda: _offline_answer(plan, structured, changes, passages),
                       retrieval_set=[e.manifest() for e in evidence])
    emit("generated", model=res.served_model)
    data = res.data
    statements = [Statement.from_dict(s) for s in data.get("statements", [])]
    report = EvidenceValidator(db, tenant_id).validate(statements, evidence, use_judge=res.provider != "offline")
    emit("validated", counts=report.counts)
    facts = [s for s in report.statements if s.statement_type == "FACT"]
    abstained = bool(data.get("abstained")) or (not facts and not evidence)
    answer_text = data.get("answer", "")
    if report.withheld and not facts:
        abstained = True
        answer_text = ("The available evidence was insufficient to support a verified answer; unsupported statements "
                       "were withheld.")
    comparison_warning = data.get("comparison_warning") or (COMPARISON_WARNING if plan.comparison else "")
    ev_by_id = {e.evidence_id: e for e in evidence}
    cited = sorted({eid for s in report.statements for eid in s.evidence_ids if eid in ev_by_id})
    confidence = "Not applicable" if abstained else data.get("confidence", "Medium")
    if confidence == "High" and (report.withheld or report.counts.get("partially_supported")):
        confidence = "Medium"
    limitations = list(data.get("limitations") or [])
    stale = [e for e in evidence if e.retrieved_at and (datetime.now(UTC) - e.retrieved_at).days > 14]
    if stale:
        limitations.append(f"{len(stale)} evidence item(s) were retrieved more than 14 days ago; check source freshness.")
    content = {
        "question": question,
        "answer": answer_text,
        "statements": [s.to_dict() for s in report.statements],
        "evidence": {eid: ev_by_id[eid].link() for eid in cited},
        "sources": [{"source_type": st, "uri": uri} for st, uri in
                    sorted({(ev_by_id[e].source_type, ev_by_id[e].uri or "") for e in cited})],
        "confidence": confidence,
        "limitations": limitations,
        "comparison_warning": comparison_warning,
        "abstained": abstained,
        "resolved_context": plan.to_context(),
        "generated_at": datetime.now(UTC).isoformat(),
        "model_workflow_version": res.model_workflow_version,
        "validation": report.summary(),
    }
    content["explanation"] = explain_answer(content, {"structured": len(structured), "changes": len(changes),
                                                       "passages": len(passages)}, res.served_model, res.degraded)
    art = GeneratedArtifact(tenant_id=tenant_id, kind="ask_answer", content=content, generation_id=res.generation_id,
                            validation_generation_id=report.judge_generation_id, validation=report.summary(),
                            publishable=report.publishable or abstained, model_workflow_version=res.model_workflow_version,
                            evidence_snapshot_ids=[uuid.UUID(e.snapshot_id) for e in evidence if e.snapshot_id])
    db.add(art)
    db.flush()
    for i, s in enumerate(report.statements):
        db.add(Claim(tenant_id=tenant_id, artifact_id=art.id, ordinal=i, section=s.section, statement=s.statement,
                     statement_type=s.statement_type, confidence=s.confidence, evidence_ids=s.evidence_ids,
                     evidence_links=[ev_by_id[e].link() for e in s.evidence_ids if e in ev_by_id],
                     affected_entities=[], validation_status=s.validation_status,
                     validation_detail=s.validation_detail, model_workflow_version=res.model_workflow_version))
    turn = AskTurn(tenant_id=tenant_id, session_id=session.id, question=question, artifact_id=art.id,
                   resolved_context=plan.to_context())
    db.add(turn)
    ctx = dict(session.context or {})
    if plan.entity_ids:
        ctx["entity_labels"] = plan.entity_labels
    if plan.since:
        ctx["since"] = plan.since.isoformat()
    session.context = ctx
    db.flush()
    return {"session_id": str(session.id), "turn_id": str(turn.id), "artifact_id": str(art.id), **content}
