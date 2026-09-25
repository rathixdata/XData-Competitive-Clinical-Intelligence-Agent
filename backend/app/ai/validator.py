"""Evidence Agent: claim/evidence alignment before publication (FR-AI-002/006/008, Section 11).

Two independent layers:
1. Deterministic checks - cited ids must exist in the retrieval set; every number, date and registry
   identifier in a FACT must appear in the cited evidence; lexical support must be sufficient.
2. LLM judge (separate model call with its own prompt, never the generator's context) that grades each
   FACT against only its cited passages.

Outcome per FACT: supported | partially_supported | unsupported (+ severity). Unsupported FACTs are
withheld from the published output (retained in the validation record); any *high-severity* unsupported
FACT blocks publication of the artifact.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.ai.llm import LLMService
from app.ai.prompts import load_prompt
from app.ai.statements import Statement, enforce_confidence_policy
from app.core.metrics import VALIDATION_OUTCOMES
from app.rag.evidence import Evidence

WORKFLOW_VERSION = "1.0.0"
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b")
_TEXT_DATE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[\s\-]+(?:(\d{1,2}),?\s+)?(\d{4})\b", re.I)
_DAY_MONTH_DATE = re.compile(r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\b", re.I)
_REGISTRY_ID = re.compile(r"\b(NCT\d{8}|PMID:?\s?\d{6,9}|(?:NDA|BLA|ANDA)\s?\d{6})\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(\s?%)?(?![\w])")
_WORD = re.compile(r"[a-z][a-z\-]{2,}")
_STOP = frozenset(
    ["the", "and", "for", "with", "from", "that", "this", "was", "were", "are", "has", "have", "had", "its", "into", "their", "than", "then", "also", "which", "who", "whom", "been", "being", "per", "not", "but", "all", "any", "may", "might", "could", "would", "should", "will", "can", "trial", "study", "studies", "record", "source", "evidence", "reported", "reports", "listed", "lists", "according", "shows", "show", "changed", "change", "changes", "from", "to"]
)
_HEDGES = ("may", "might", "could", "possibl", "potential", "suggest", "appear", "unclear", "if ", "likely")


def _dates(text: str) -> set[str]:
    out = set()
    for y, m, _d in _ISO_DATE.findall(text):
        if 1 <= int(m) <= 12:
            out.add(f"{y}-{m}")
    for mon, _d, y in _TEXT_DATE.findall(text):
        out.add(f"{y}-{_MONTHS[mon[:3].lower()]:02d}")
    for _d, mon, y in _DAY_MONTH_DATE.findall(text):
        out.add(f"{y}-{_MONTHS[mon[:3].lower()]:02d}")
    return out


def _strip_dates_ids(text: str) -> str:
    t = _ISO_DATE.sub(" ", text)
    t = _TEXT_DATE.sub(" ", t)
    t = _DAY_MONTH_DATE.sub(" ", t)
    return _REGISTRY_ID.sub(" ", t)


def _numbers(text: str) -> set[str]:
    nums = set()
    for n, _pct in _NUMBER.findall(_strip_dates_ids(text)):
        v = n.replace(",", "")
        if v.endswith(".0"):
            v = v[:-2]
        nums.add(v)
    return nums


def _ids(text: str) -> set[str]:
    return {re.sub(r"[\s:]", "", i.upper()) for i in _REGISTRY_ID.findall(text)}


def _stem(w: str) -> str:
    return w[:6]


def lexical_support(statement: str, evidence_text: str) -> float:
    words = [w for w in _WORD.findall(statement.lower()) if w not in _STOP]
    if not words:
        return 1.0
    ev = {_stem(w) for w in _WORD.findall(evidence_text.lower())}
    hits = sum(1 for w in words if _stem(w) in ev)
    return hits / len(words)


@dataclass
class ValidationReport:
    statements: list[Statement]
    withheld: list[Statement] = field(default_factory=list)
    publishable: bool = True
    blocked_reasons: list[str] = field(default_factory=list)
    judge_generation_id: uuid.UUID | None = None
    counts: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "publishable": self.publishable,
            "blocked_reasons": self.blocked_reasons,
            "counts": self.counts,
            "withheld": [s.to_dict() for s in self.withheld],
            "judge_generation_id": str(self.judge_generation_id) if self.judge_generation_id else None,
            "validator_version": WORKFLOW_VERSION,
        }


def deterministic_check(stmt: Statement, cited: list[Evidence], known_ids: set[str]) -> dict[str, Any]:
    missing = [e for e in stmt.evidence_ids if e not in known_ids]
    if not stmt.evidence_ids:
        return {"verdict": "unsupported", "severity": "high", "reason": "fact_without_evidence"}
    if missing:
        return {"verdict": "unsupported", "severity": "high", "reason": "unknown_evidence_ids", "missing": missing}
    ev_text = " \n ".join(e.text for e in cited)
    problems = []
    sn, en = _numbers(stmt.statement), _numbers(ev_text)
    bad_nums = sorted(n for n in sn if n not in en)
    if bad_nums:
        problems.append({"type": "number_not_in_evidence", "values": bad_nums})
    sd, ed = _dates(stmt.statement), _dates(ev_text)
    bad_dates = sorted(d for d in sd if d not in ed and d[:4] not in {x[:4] for x in ed if len(x) == 4})
    if bad_dates:
        problems.append({"type": "date_not_in_evidence", "values": bad_dates})
    si, ei = _ids(stmt.statement), _ids(ev_text)
    bad_ids = sorted(i for i in si if i not in ei)
    if bad_ids:
        problems.append({"type": "identifier_not_in_evidence", "values": bad_ids})
    lex = round(lexical_support(stmt.statement, ev_text), 3)
    if problems:
        return {"verdict": "unsupported", "severity": "high", "reason": "detail_mismatch", "problems": problems,
                "lexical_support": lex}
    if lex >= 0.6:
        return {"verdict": "supported", "severity": "none", "lexical_support": lex}
    if lex >= 0.35:
        return {"verdict": "partially_supported", "severity": "low", "lexical_support": lex}
    return {"verdict": "unsupported", "severity": "medium", "reason": "low_lexical_support", "lexical_support": lex}


JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["supported", "partially_supported", "unsupported"]},
                    "severity": {"type": "string", "enum": ["none", "low", "medium", "high"]},
                    "presented_as_fact_but_is_inference": {"type": "boolean"},
                    "rationale": {"type": "string"},
                },
                "required": ["claim_id", "verdict", "severity", "presented_as_fact_but_is_inference", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

_SEV = {"none": 0, "low": 1, "medium": 2, "high": 3}
_VER = {"supported": 0, "partially_supported": 1, "unsupported": 2}


class EvidenceValidator:
    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id

    def validate(self, statements: list[Statement], evidence: list[Evidence], *, use_judge: bool = True) -> ValidationReport:
        by_id = {e.evidence_id: e for e in evidence}
        facts = [(i, s) for i, s in enumerate(statements) if s.statement_type == "FACT"]
        det: dict[int, dict[str, Any]] = {}
        for i, s in facts:
            det[i] = deterministic_check(s, [by_id[e] for e in s.evidence_ids if e in by_id], set(by_id))

        judge: dict[int, dict[str, Any]] = {}
        judge_gen = None
        judgeable = [(i, s) for i, s in facts if det[i].get("reason") not in ("fact_without_evidence", "unknown_evidence_ids")]
        if use_judge and judgeable:
            judge, judge_gen = self._judge(judgeable, by_id)

        report = ValidationReport(statements=[], judge_generation_id=judge_gen)
        counts = {"supported": 0, "partially_supported": 0, "unsupported": 0, "inference": 0, "unknown": 0,
                  "investigation": 0, "unhedged_inference": 0}
        for i, s in enumerate(statements):
            if s.statement_type != "FACT":
                if s.statement_type == "INFERENCE":
                    counts["inference"] += 1
                    if not any(h in s.statement.lower() for h in _HEDGES):
                        s.validation_detail["warning"] = "unhedged_inference"
                        counts["unhedged_inference"] += 1
                        if s.confidence == "High":
                            s.confidence = "Medium"
                elif s.statement_type == "UNKNOWN":
                    counts["unknown"] += 1
                else:
                    counts["investigation"] += 1
                s.validation_status = "not_applicable"
                report.statements.append(enforce_confidence_policy(s))
                continue
            d, j = det[i], judge.get(i)
            verdict, severity = d["verdict"], d["severity"]
            if j:
                # take the stricter of the two layers
                if _VER[j["verdict"]] > _VER[verdict]:
                    verdict = j["verdict"]
                severity = max(severity, j["severity"], key=lambda x: _SEV[x])
                if j.get("presented_as_fact_but_is_inference"):
                    s.original_statement_type = "FACT"
                    s.statement_type = "INFERENCE"
                    s.validation_detail["reclassified"] = "fact_to_inference"
            s.validation_status = verdict
            s.validation_detail.update({"deterministic": d, "judge": j})
            counts[verdict] += 1
            VALIDATION_OUTCOMES.labels(verdict).inc()
            if verdict == "unsupported":
                report.withheld.append(s)
                if severity == "high":
                    report.publishable = False
                    report.blocked_reasons.append(f"high-severity unsupported claim: {s.statement[:160]}")
                continue
            report.statements.append(enforce_confidence_policy(s))
        if report.withheld:
            report.statements.append(Statement(
                section="known_limitations",
                statement=(f"{len(report.withheld)} generated factual statement(s) could not be verified against the "
                           "retained source evidence and were withheld."),
                statement_type="UNKNOWN", confidence="Not applicable", validation_status="not_applicable"))
        report.counts = counts
        return report

    def _judge(self, facts: list[tuple[int, Statement]], by_id: dict[str, Evidence]) -> tuple[dict[int, dict], uuid.UUID | None]:
        from app.core.config import get_settings

        s = get_settings()
        blocks = []
        used: set[str] = set()
        for i, st in facts:
            refs = ", ".join(st.evidence_ids)
            blocks.append(f'<claim id="c{i}" cites="{refs}">{st.statement}</claim>')
            used.update(st.evidence_ids)
        ev = "\n".join(
            f'<evidence id="{eid}">\n{by_id[eid].text[:2500]}\n</evidence>' for eid in sorted(used) if eid in by_id
        )
        user = f"<claims>\n{chr(10).join(blocks)}\n</claims>\n<cited_evidence>\n{ev}\n</cited_evidence>\n" \
               "Return one verdict per claim id."
        svc = LLMService(self.db, self.tenant_id)
        res = svc.generate(
            workflow="evidence_validation",
            workflow_version=WORKFLOW_VERSION,
            prompt=load_prompt("evidence_validator"),
            user_content=user,
            schema=JUDGE_SCHEMA,
            offline=lambda: {"verdicts": []},
            retrieval_set=[by_id[e].manifest() for e in sorted(used) if e in by_id],
            model=s.llm_validator_model,
            effort=s.llm_validator_effort,
            max_tokens=8000,
        )
        out: dict[int, dict] = {}
        for v in res.data.get("verdicts", []):
            cid = str(v.get("claim_id", ""))
            if cid.startswith("c") and cid[1:].isdigit():
                out[int(cid[1:])] = v
        return out, res.generation_id
