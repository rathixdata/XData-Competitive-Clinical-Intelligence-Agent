"""Versioned source-adapter contract (FR-SRC-001).

Every external source implements ``SourceAdapter``: *plan* what to fetch, *fetch* raw artifacts
(with checkpointing, retries, throttling), *parse* them into canonical ``NormalizedRecord`` objects,
and declare *provenance/rights*. The intelligence domain model never sees source-specific shapes, so
upstream API changes are absorbed inside a single adapter (Section 1.3, Section 21).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Mention:
    """An entity mention extracted from a source record, to be resolved to a canonical ID."""

    text: str
    entity_type: str  # company | asset | indication | endpoint | biomarker | target | mechanism | kol | conference
    role: str  # sponsor | intervention | condition | primary_endpoint | biomarker | author | ...
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class TextSection:
    """A passage made retrievable in the RAG index; ``field_path`` pins provenance to the source field."""

    section: str
    field_path: str
    text: str
    title: str | None = None


@dataclass
class FetchedRecord:
    source_object_id: str
    uri: str
    raw: bytes
    content_type: str
    retrieved_at: datetime
    title: str | None = None
    source_last_updated: str | None = None
    published_at: datetime | None = None
    query_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedRecord:
    object_type: str  # trial | publication | label | drug_application | disclosure | conference_abstract
    source_object_id: str
    normalized: dict[str, Any]
    mentions: list[Mention] = field(default_factory=list)
    sections: list[TextSection] = field(default_factory=list)
    title: str | None = None
    published_at: datetime | None = None


@dataclass
class FetchPlan:
    """What to fetch, aggregated from all active landscapes (public data is fetched once, shared)."""

    nct_ids: set[str] = field(default_factory=set)
    trial_queries: list[dict[str, str]] = field(default_factory=list)  # {"cond": .., "intr": ..}
    pubmed_queries: list[dict[str, Any]] = field(default_factory=list)  # {"query": .., "landscape_ids": [..]}
    fda_products: set[str] = field(default_factory=set)
    sec_ciks: set[str] = field(default_factory=set)
    feeds: list[dict[str, Any]] = field(default_factory=list)  # corporate IR / conference feeds


@dataclass
class FetchContext:
    plan: FetchPlan
    checkpoint: dict[str, Any]
    settings: dict[str, Any]
    since: datetime | None = None
    run_id: Any = None


class SourceAdapter(ABC):
    key: str
    version: str
    display_name: str
    default_rate_limit_per_sec: float = 1.0
    default_schedule: str = "0 */4 * * *"
    freshness_slo_hours: int = 24
    source_family: str = "public"

    @abstractmethod
    def fetch(self, ctx: FetchContext) -> Iterator[FetchedRecord]:
        """Yield raw records. Must be restartable from ``ctx.checkpoint``."""

    @abstractmethod
    def parse(self, record: FetchedRecord) -> list[NormalizedRecord]:
        """Map a raw artifact to canonical records. Must be pure / deterministic."""

    def rights(self) -> dict[str, Any]:
        """Rights / licensing metadata attached to every SourceDocument (Section 21)."""
        return {"license": "public", "redistribution": "attribution", "attribution": self.display_name}

    def next_checkpoint(self, ctx: FetchContext, started_at: datetime) -> dict[str, Any]:
        return {**ctx.checkpoint, "last_run_started_at": started_at.isoformat()}

    def close(self) -> None:  # noqa: B027 - optional hook
        pass
