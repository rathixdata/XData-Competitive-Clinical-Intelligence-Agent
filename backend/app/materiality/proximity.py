"""Competitive proximity (FR-LND-004) between assets / trials across weighted dimensions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.entities.resolver import normalize_alias

DEFAULT_WEIGHTS: dict[str, float] = {
    "target": 0.30,
    "indication": 0.25,
    "line_of_therapy": 0.15,
    "biomarker": 0.15,
    "modality": 0.10,
    "geography": 0.05,
}
DIMENSIONS = tuple(DEFAULT_WEIGHTS)

_LINE = re.compile(r"\b([1-5])\s*l(\+)?(?!\w)|\b(first|second|third|fourth)[\s-]line(\s*(?:or later|\+|and beyond))?", re.I)
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def parse_lines(values: list[str] | str | None) -> set[str]:
    """'2L+' -> {L2..L5}; 'first-line' -> {L1}; 'previously treated' -> {L2..L5}; 'treatment-naive' -> {L1}."""
    if not values:
        return set()
    if isinstance(values, str):
        values = [values]
    out: set[str] = set()
    for v in values:
        s = str(v).lower()
        for m in _LINE.finditer(s):
            n = int(m.group(1)) if m.group(1) else _ORD[m.group(3).lower()]
            plus = bool(m.group(2) or m.group(4))
            out |= {f"L{i}" for i in range(n, 6)} if plus else {f"L{n}"}
        if re.search(r"previously treated|after (?:progression|failure)|refractory|relapsed|pretreated", s):
            out |= {f"L{i}" for i in range(2, 6)}
        if re.search(r"treatment[- ]na[iï]ve|untreated|first[- ]line|newly diagnosed", s):
            out.add("L1")
    return out


def _norm_set(values: Any) -> set[str]:
    if not values:
        return set()
    if isinstance(values, str):
        values = [values]
    return {normalize_alias(str(v)) for v in values if str(v).strip()}


@dataclass
class Features:
    target: set[str] = field(default_factory=set)
    indication: set[str] = field(default_factory=set)
    line_of_therapy: set[str] = field(default_factory=set)
    biomarker: set[str] = field(default_factory=set)
    modality: set[str] = field(default_factory=set)
    geography: set[str] = field(default_factory=set)

    def get(self, dim: str) -> set[str]:
        return getattr(self, dim)


# Loose indication matching: "non small cell lung cancer" ~ "nsclc", "carcinoma non small cell lung".
_INDICATION_SYNONYMS = {
    "nsclc": "non small cell lung cancer",
    "carcinoma non small cell lung": "non small cell lung cancer",
    "non small cell lung carcinoma": "non small cell lung cancer",
    "sclc": "small cell lung cancer",
    "crc": "colorectal cancer",
    "mcrc": "colorectal cancer",
}


def _canon_indication(s: str) -> str:
    s = _INDICATION_SYNONYMS.get(s, s)
    for k, v in _INDICATION_SYNONYMS.items():
        if s == k:
            return v
    s = re.sub(r"\b(metastatic|advanced|locally|recurrent|unresectable|stage iv|stage iii[b-c]?)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def features_from_profile(profile: dict[str, Any]) -> Features:
    p = profile or {}
    return Features(
        target=_norm_set(p.get("targets") or p.get("target")),
        indication={_canon_indication(x) for x in _norm_set(p.get("indications") or p.get("indication"))},
        line_of_therapy=parse_lines(p.get("line_of_therapy") or p.get("population")),
        biomarker=_norm_set(p.get("biomarkers") or p.get("biomarker")),
        modality=_norm_set(p.get("modality")),
        geography=_norm_set(p.get("geographies") or p.get("geography")),
    )


def features_from_trial(normalized: dict[str, Any], known_biomarkers: list[str] | None = None) -> Features:
    text = " ".join([normalized.get("eligibility_criteria") or "", normalized.get("brief_title") or "",
                     normalized.get("official_title") or ""]).lower()
    bms = set()
    for b in known_biomarkers or []:
        nb = normalize_alias(b)
        if nb and re.search(rf"\b{re.escape(nb)}\b", normalize_alias(text)):
            bms.add(nb)
    return Features(
        indication={_canon_indication(x) for x in _norm_set(normalized.get("conditions"))},
        line_of_therapy=parse_lines(text),
        biomarker=bms,
        geography=_norm_set(normalized.get("countries")),
    )


def _overlap(a: set[str], b: set[str], dim: str) -> float:
    if not a or not b:
        return 0.0
    if dim == "indication":
        # substring containment counts (e.g. "lung cancer" within "non small cell lung cancer")
        hits = sum(1 for x in a if any(x == y or x in y or y in x for y in b))
        return hits / min(len(a), len(b)) if hits else 0.0
    inter = len(a & b)
    return inter / min(len(a), len(b))


@dataclass
class ProximityResult:
    score: float  # 0..1
    dims: dict[str, dict[str, Any]]
    coverage: float

    @property
    def rationale(self) -> str:
        hits = [d for d, v in self.dims.items() if v["score"] > 0]
        return ("shared " + ", ".join(d.replace("_", " ") for d in hits)) if hits else "no shared dimensions"

    def to_dict(self) -> dict[str, Any]:
        return {"score": round(self.score, 3), "coverage": round(self.coverage, 3), "dimensions": self.dims,
                "rationale": self.rationale}


def proximity(a: Features, b: Features, weights: dict[str, float] | None = None) -> ProximityResult:
    w = {k: float(v) for k, v in (weights or DEFAULT_WEIGHTS).items() if k in DIMENSIONS and float(v) > 0}
    total = sum(w.values()) or 1.0
    known_w = 0.0
    acc = 0.0
    dims: dict[str, dict[str, Any]] = {}
    for d, wt in w.items():
        av, bv = a.get(d), b.get(d)
        known = bool(av) and bool(bv)
        s = _overlap(av, bv, d) if known else 0.0
        if known:
            known_w += wt
            acc += wt * s
        dims[d] = {"weight": wt, "score": round(s, 3), "known": known,
                   "shared": sorted((av & bv) if d != "indication" else {x for x in av if any(x in y or y in x for y in bv)})[:5]}
    coverage = known_w / total
    # Unknown dimensions neither help nor fully hurt: score over known dims, damped by coverage.
    score = (acc / known_w) * (coverage ** 0.5) if known_w else 0.0
    return ProximityResult(min(1.0, score), dims, coverage)
