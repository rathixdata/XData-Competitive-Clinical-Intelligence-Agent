"""Evidence objects - the unit of provenance for every factual claim (FR-AI-003, Section 8.2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.core.crypto import sha256_hex


@dataclass
class Evidence:
    evidence_id: str  # stable per retrieval set: E1, E2 ... (passages) / S1.. (structured fields)
    kind: str  # passage | structured_field | change_event
    source: str  # ctgov | pubmed | openfda_label | ...
    source_type: str  # human label, e.g. "ClinicalTrials.gov record"
    text: str
    source_document_id: str | None = None
    snapshot_id: str | None = None
    chunk_id: str | None = None
    change_id: str | None = None
    object_type: str | None = None
    object_id: str | None = None
    uri: str | None = None
    title: str | None = None
    section: str | None = None
    field_path: str | None = None
    span: list[int] | None = None
    retrieved_at: datetime | None = None
    published_at: datetime | None = None
    score: float = 0.0
    is_current: bool = True
    rights: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return sha256_hex(self.text)

    def link(self) -> dict[str, Any]:
        """Serializable provenance attached to claims."""
        d = asdict(self)
        d.pop("text")
        d["excerpt"] = self.text[:600]
        d["content_hash"] = self.content_hash
        for k in ("retrieved_at", "published_at"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        return d

    def manifest(self) -> dict[str, Any]:
        """Compact retrieval-set entry recorded on GenerationRecord (FR-AI-007)."""
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "chunk_id": self.chunk_id,
            "snapshot_id": self.snapshot_id,
            "source_document_id": self.source_document_id,
            "change_id": self.change_id,
            "content_hash": self.content_hash,
            "score": round(self.score, 5),
        }


SOURCE_LABELS = {
    "ctgov": "ClinicalTrials.gov record",
    "pubmed": "PubMed publication",
    "openfda_label": "FDA drug label (openFDA)",
    "openfda_drugsfda": "Drugs@FDA application (openFDA)",
    "sec_edgar": "SEC EDGAR filing",
    "corporate_feed": "Company press release",
    "conference_feed": "Conference abstract",
    "internal": "Customer internal record",
}


def render_for_prompt(evidence: list[Evidence], max_chars: int = 1800) -> str:
    """Render evidence as clearly-delimited *untrusted data* (prompt-injection isolation, Section 11)."""
    blocks = []
    for e in evidence:
        meta = [f'id="{e.evidence_id}"', f'source="{SOURCE_LABELS.get(e.source, e.source)}"']
        if e.title:
            meta.append(f'title="{_attr(e.title)}"')
        if e.section:
            meta.append(f'section="{e.section}"')
        if e.published_at:
            meta.append(f'published="{e.published_at.date().isoformat()}"')
        if e.retrieved_at:
            meta.append(f'retrieved="{e.retrieved_at.date().isoformat()}"')
        if not e.is_current:
            meta.append('superseded="true"')
        text = e.text[:max_chars].replace("</evidence>", "</ evidence>")
        blocks.append(f"<evidence {' '.join(meta)}>\n{text}\n</evidence>")
    return "\n".join(blocks)


def _attr(s: str) -> str:
    return s.replace('"', "'").replace("<", "(").replace(">", ")")[:200]
