"""Customer-asset impact mapping (FR-MAT-003) with an explicit graph path + rationale per mapping."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.entities.graph import find_path, neighbours, node_label, upsert_edge
from app.materiality.proximity import (
    DEFAULT_WEIGHTS,
    Features,
    ProximityResult,
    features_from_profile,
    features_from_trial,
    proximity,
)
from app.models import Asset, Concept, Landscape, LandscapeMember, ProximityRule, Trial


@dataclass
class ObjectScope:
    """Canonical entities linked to the object that changed."""

    object_type: str
    object_id: uuid.UUID
    asset_ids: list[uuid.UUID] = field(default_factory=list)
    company_ids: list[uuid.UUID] = field(default_factory=list)
    indication_names: list[str] = field(default_factory=list)
    trial_normalized: dict[str, Any] | None = None
    min_link_confidence: float = 1.0


@dataclass
class ImpactMapping:
    asset_id: uuid.UUID
    asset_name: str
    proximity: float
    detail: dict[str, Any]
    path: list[dict[str, Any]]
    rationale: str
    via_asset_id: uuid.UUID | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"asset_id": str(self.asset_id), "asset_name": self.asset_name, "proximity": round(self.proximity, 3),
                "detail": self.detail, "path": self.path, "rationale": self.rationale,
                "via_asset_id": str(self.via_asset_id) if self.via_asset_id else None}


def active_rule(db: Session, tenant_id: uuid.UUID, landscape_id: uuid.UUID) -> tuple[dict[str, float], float, str]:
    stmt = (select(ProximityRule).where(ProximityRule.tenant_id == tenant_id, ProximityRule.status == "active")
            .order_by(ProximityRule.landscape_id.is_(None), ProximityRule.version.desc()))
    for rule in db.scalars(stmt).all():
        if rule.landscape_id in (None, landscape_id):
            return rule.weights, rule.min_proximity, f"{rule.name}@v{rule.version}"
    return DEFAULT_WEIGHTS, 0.35, "default@v1"


def asset_features(db: Session, asset: Asset) -> Features:
    f = features_from_profile(asset.profile or {})
    # Enrich competitor assets from the graph (targets / indications recorded from sources).
    for pred, dim in (("targets", "target"), ("indicated_for", "indication")):
        for cid in neighbours(db, asset.id, predicate=pred):
            c = db.get(Concept, cid)
            if c is not None:
                from app.entities.resolver import normalize_alias

                f.get(dim).add(normalize_alias(c.canonical_name))
    return f


def known_biomarkers(db: Session, tenant_id: uuid.UUID) -> list[str]:
    rows = db.scalars(select(Concept.canonical_name).where(Concept.kind == "biomarker")).all()
    return list(rows)


def landscape_relevance(db: Session, landscape: Landscape, scope: ObjectScope) -> str:
    members = db.execute(select(LandscapeMember.entity_type, LandscapeMember.entity_id).where(
        LandscapeMember.landscape_id == landscape.id)).all()
    ids = {eid for _, eid in members}
    if scope.object_id in ids:
        return "monitored"
    if ids & set(scope.asset_ids) or ids & set(scope.company_ids):
        return "linked"
    ls_ind = {(landscape.disease or "").lower()} | {str(x).lower() for x in (landscape.config or {}).get("indications", [])}
    for name in scope.indication_names:
        n = name.lower()
        if any(i and (i in n or n in i) for i in ls_ind):
            return "indication"
    return "peripheral"


def map_impacts(db: Session, tenant_id: uuid.UUID, landscape: Landscape, scope: ObjectScope) -> tuple[list[ImpactMapping], str]:
    weights, min_prox, rule_ref = active_rule(db, tenant_id, landscape.id)
    customer_ids = db.scalars(select(LandscapeMember.entity_id).where(
        LandscapeMember.landscape_id == landscape.id, LandscapeMember.entity_type == "asset",
        LandscapeMember.role == "customer")).all()
    customers = [a for a in (db.get(Asset, i) for i in customer_ids) if a is not None]
    competitors = [a for a in (db.get(Asset, i) for i in scope.asset_ids) if a is not None]
    trial_feats = None
    if scope.trial_normalized:
        trial_feats = features_from_trial(scope.trial_normalized, known_biomarkers(db, tenant_id))

    out: list[ImpactMapping] = []
    for cust in customers:
        cf = asset_features(db, cust)
        best: tuple[float, ProximityResult | None, Asset | None, str] = (0.0, None, None, "")
        for comp in competitors:
            if comp.id == cust.id:
                continue
            pr = proximity(cf, asset_features(db, comp), weights)
            if pr.score > best[0]:
                best = (pr.score, pr, comp, "asset")
        if trial_feats is not None:
            # Trial-level features (population, biomarker, line) refine the asset-level comparison.
            tf = Features(**{d: set(trial_feats.get(d)) for d in weights})
            if best[2] is not None:
                comp_f = asset_features(db, best[2])
                for d in ("target", "modality"):
                    tf.get(d).update(comp_f.get(d))
            pr_t = proximity(cf, tf, weights)
            if pr_t.score > best[0]:
                best = (pr_t.score, pr_t, best[2], "trial")
        score, pr, via, basis = best
        if pr is None or score < min_prox:
            continue
        path = _impact_path(db, tenant_id, cust, via, scope, score, rule_ref, pr)
        rationale = f"{cust.canonical_name} {pr.rationale}" + (f" with {via.canonical_name}" if via else "") + \
                    f" (proximity {score:.2f}, {basis}-level, rule {rule_ref})"
        out.append(ImpactMapping(cust.id, cust.canonical_name, score, {**pr.to_dict(), "basis": basis,
                                                                        "rule": rule_ref}, path, rationale,
                                 via.id if via else None))
    out.sort(key=lambda m: m.proximity, reverse=True)
    return out, rule_ref


def _impact_path(db: Session, tenant_id: uuid.UUID, cust: Asset, via: Asset | None, scope: ObjectScope,
                 score: float, rule_ref: str, pr: ProximityResult) -> list[dict[str, Any]]:
    """Persist the derived competes_with edge (tenant-scoped) and return the traversable path."""
    if via is not None:
        upsert_edge(db, subject_type="asset", subject_id=cust.id, predicate="competes_with", object_type="asset",
                    object_id=via.id, confidence=round(score, 3), method=f"proximity_rule:{rule_ref}",
                    status="verified" if score >= 0.6 else "proposed", tenant_id=tenant_id,
                    evidence={"dimensions": pr.to_dict()["dimensions"]})
        db.flush()
    hops = find_path(db, cust.id, scope.object_id, max_depth=4) or []
    labelled = []
    for h in hops:
        labelled.append({**h, "from_label": node_label(db, uuid.UUID(h["from"]))["label"],
                         "to_label": node_label(db, uuid.UUID(h["to"]))["label"]})
    if not labelled:
        tgt = db.get(Trial, scope.object_id)
        labelled = [{"from": str(cust.id), "to": str(scope.object_id), "predicate": "shares_population_with",
                     "from_label": cust.canonical_name,
                     "to_label": (tgt.nct_id if tgt else str(scope.object_id)[:8]), "confidence": round(score, 3),
                     "method": "trial_feature_proximity"}]
    return labelled
