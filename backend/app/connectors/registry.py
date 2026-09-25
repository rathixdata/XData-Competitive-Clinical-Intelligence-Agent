"""Connector registry. Adapters are independently enabled/disabled/upgraded (FR-SRC-001)."""

from __future__ import annotations

from collections.abc import Callable

from app.connectors.base import SourceAdapter
from app.connectors.clinicaltrials import ClinicalTrialsGovAdapter
from app.connectors.corporate import FeedAdapter, SecEdgarAdapter
from app.connectors.openfda import DrugLabelAdapter, DrugsAtFDAAdapter
from app.connectors.pubmed import PubMedAdapter

_FACTORIES: dict[str, Callable[..., SourceAdapter]] = {
    "ctgov": ClinicalTrialsGovAdapter,
    "pubmed": PubMedAdapter,
    "openfda_drugsfda": DrugsAtFDAAdapter,
    "openfda_label": DrugLabelAdapter,
    "sec_edgar": SecEdgarAdapter,
    "corporate_feed": lambda **kw: FeedAdapter("corporate", **kw),
    "conference_feed": lambda **kw: FeedAdapter("conference", **kw),
}

# Allows tests / fixtures to swap an adapter implementation.
_OVERRIDES: dict[str, Callable[..., SourceAdapter]] = {}

META = {
    "ctgov": ("ClinicalTrials.gov", "2.1.0", "15 */2 * * *", 0.8, 12),
    "pubmed": ("NCBI PubMed", "1.3.0", "30 */6 * * *", 2.5, 24),
    "openfda_drugsfda": ("FDA Drugs@FDA (openFDA)", "1.1.0", "0 5 * * *", 0.6, 48),
    "openfda_label": ("FDA Drug Labeling (openFDA SPL)", "1.1.0", "20 5 * * *", 0.6, 48),
    "sec_edgar": ("SEC EDGAR", "1.0.2", "10 * * * *", 5.0, 6),
    "corporate_feed": ("Corporate IR feeds", "1.0.0", "45 */3 * * *", 1.0, 24),
    "conference_feed": ("Conference abstract feeds", "1.0.0", "50 */6 * * *", 1.0, 72),
}


def available_connectors() -> list[str]:
    return list(_FACTORIES)


def get_adapter(key: str, **kwargs) -> SourceAdapter:  # type: ignore[no-untyped-def]
    factory = _OVERRIDES.get(key) or _FACTORIES.get(key)
    if factory is None:
        raise KeyError(f"unknown connector {key}")
    return factory(**kwargs)


def override_adapter(key: str, factory: Callable[..., SourceAdapter] | None) -> None:
    if factory is None:
        _OVERRIDES.pop(key, None)
    else:
        _OVERRIDES[key] = factory
