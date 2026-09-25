"""Typed statement schema shared by all generating agents (Section 12.1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

STATEMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "section": {"type": "string"},
        "statement": {"type": "string"},
        "statement_type": {"type": "string", "enum": ["FACT", "INFERENCE", "UNKNOWN", "RECOMMENDED_INVESTIGATION"]},
        "confidence": {"type": "string", "enum": ["Verified", "High", "Medium", "Low", "Not applicable"]},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "affected_entity_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["section", "statement", "statement_type", "confidence", "evidence_ids", "affected_entity_ids"],
    "additionalProperties": False,
}


@dataclass
class Statement:
    section: str
    statement: str
    statement_type: str
    confidence: str
    evidence_ids: list[str] = field(default_factory=list)
    affected_entity_ids: list[str] = field(default_factory=list)
    validation_status: str = "not_checked"
    validation_detail: dict[str, Any] = field(default_factory=dict)
    original_statement_type: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Statement:
        return cls(
            section=str(d.get("section") or "context"),
            statement=str(d.get("statement") or "").strip(),
            statement_type=str(d.get("statement_type") or "INFERENCE").upper(),
            confidence=str(d.get("confidence") or "Not applicable"),
            evidence_ids=[str(x) for x in d.get("evidence_ids") or []],
            affected_entity_ids=[str(x) for x in d.get("affected_entity_ids") or []],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def enforce_confidence_policy(s: Statement) -> Statement:
    """Policy-based confidence (FR-AI-005): no false precision, labels consistent with statement type."""
    if s.statement_type in ("UNKNOWN", "RECOMMENDED_INVESTIGATION"):
        s.confidence = "Not applicable"
    elif s.statement_type == "FACT":
        s.confidence = "Verified" if s.validation_status == "supported" else (
            "Medium" if s.validation_status == "partially_supported" else s.confidence)
    elif s.statement_type == "INFERENCE" and s.confidence in ("Verified", "Not applicable"):
        s.confidence = "Medium"
    return s
