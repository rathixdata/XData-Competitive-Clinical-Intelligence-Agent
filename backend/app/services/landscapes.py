"""Landscape domain services (FR-LND-001..005) shared by the API, CLI and seeding."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.entities.graph import neighbours
from app.entities.resolver import add_alias
from app.materiality.scoring import DEFAULT_BANDS, DEFAULT_WEIGHTS
from app.models import (
    Asset,
    AssetProfileVersion,
    Catalyst,
    Company,
    Landscape,
    LandscapeMember,
    LandscapeTemplate,
    SourceSnapshot,
    Trial,
)
from app.services import audit

# Only non-customer, reusable keys may be copied from a template (FR-LND-005).
TEMPLATE_KEYS = {"trial_queries", "pubmed_queries", "fda_products", "materiality_weights", "band_thresholds",
                 "monitored_fields", "indications", "feeds"}


def create_landscape(db: Session, tenant_id: uuid.UUID, actor: str, data: dict[str, Any]) -> Landscape:
    cfg = dict(data.get("config") or {})
    tpl_id = data.get("template_id")
    if tpl_id:
        tpl = db.get(LandscapeTemplate, tpl_id)
        if tpl is None:
            raise NotFound("template not found")
        cfg = {**{k: v for k, v in (tpl.config or {}).items() if k in TEMPLATE_KEYS}, **cfg}
    cfg.setdefault("materiality_weights", DEFAULT_WEIGHTS)
    cfg.setdefault("band_thresholds", DEFAULT_BANDS)
    ls = Landscape(tenant_id=tenant_id, name=data["name"], description=data.get("description"),
                   disease=data.get("disease"), geographies=data.get("geographies") or [], config=cfg,
                   template_id=tpl_id, created_by=actor)
    db.add(ls)
    db.flush()
    audit.record(db, action="landscape.create", resource_type="landscape", resource_id=ls.id, tenant_id=tenant_id,
                 actor_id=actor, after={"name": ls.name, "config": cfg})
    return ls


def update_landscape(db: Session, ls: Landscape, actor: str, data: dict[str, Any], reason: str | None = None) -> Landscape:
    before = {"name": ls.name, "description": ls.description, "disease": ls.disease, "config": ls.config,
              "geographies": ls.geographies, "status": ls.status}
    for k in ("name", "description", "disease", "geographies"):
        if k in data and data[k] is not None:
            setattr(ls, k, data[k])
    if data.get("config") is not None:
        new_cfg = {**(ls.config or {}), **data["config"]}
        bands = new_cfg.get("band_thresholds") or {}
        order = [bands.get(b, DEFAULT_BANDS[b]) for b in ("Feed", "Analyst Review", "High Priority", "Executive Alert")]
        if order != sorted(order) or any(not 0 <= x <= 100 for x in order):
            raise ValidationFailed("band thresholds must be ascending within 0-100")
        weights = new_cfg.get("materiality_weights") or {}
        if any(float(v) < 0 for v in weights.values()) or (weights and sum(float(v) for v in weights.values()) == 0):
            raise ValidationFailed("materiality weights must be non-negative and not all zero")
        ls.config = new_cfg
    ls.version += 1
    audit.record(db, action="landscape.update", resource_type="landscape", resource_id=ls.id, tenant_id=ls.tenant_id,
                 actor_id=actor, before=before, after={**{k: getattr(ls, k) for k in before}}, reason=reason)
    return ls


def set_members(db: Session, ls: Landscape, actor: str, members: list[dict[str, Any]], replace: bool = False) -> int:
    if replace:
        db.execute(delete(LandscapeMember).where(LandscapeMember.landscape_id == ls.id))
    n = 0
    for m in members:
        etype, eid, role = m["entity_type"], uuid.UUID(str(m["entity_id"])), m.get("role", "competitor")
        model = {"asset": Asset, "company": Company, "trial": Trial}.get(etype)
        if model is None or db.get(model, eid) is None:
            raise ValidationFailed(f"unknown {etype} {eid}")
        exists = db.scalar(select(LandscapeMember).where(LandscapeMember.landscape_id == ls.id,
                                                         LandscapeMember.entity_type == etype,
                                                         LandscapeMember.entity_id == eid))
        if exists:
            exists.role = role
            continue
        db.add(LandscapeMember(tenant_id=ls.tenant_id, landscape_id=ls.id, entity_type=etype, entity_id=eid, role=role,
                               added_by=actor))
        n += 1
    db.flush()
    audit.record(db, action="landscape.members", resource_type="landscape", resource_id=ls.id, tenant_id=ls.tenant_id,
                 actor_id=actor, after={"members": members, "replace": replace})
    return n


def create_internal_asset(db: Session, tenant_id: uuid.UUID, actor: str, data: dict[str, Any]) -> Asset:
    a = Asset(tenant_id=tenant_id, canonical_name=data["name"], is_internal=True, modality=data.get("modality"),
              stage=data.get("stage"), profile=data.get("profile") or {}, owner_company_id=data.get("owner_company_id"))
    db.add(a)
    db.flush()
    add_alias(db, entity_type="asset", entity_id=a.id, alias=a.canonical_name, alias_type="canonical",
              source="analyst", tenant_id=tenant_id, created_by=actor)
    for al in data.get("aliases", []):
        add_alias(db, entity_type="asset", entity_id=a.id, alias=al, alias_type="dev_code", source="analyst",
                  tenant_id=tenant_id, created_by=actor)
    db.add(AssetProfileVersion(tenant_id=tenant_id, asset_id=a.id, version=1, profile=a.profile, changed_by=actor,
                               changed_at=datetime.now(UTC), reason="created"))
    audit.record(db, action="asset.create", resource_type="asset", resource_id=a.id, tenant_id=tenant_id,
                 actor_id=actor, after={"name": a.canonical_name, "profile": a.profile})
    return a


def update_asset_profile(db: Session, a: Asset, actor: str, profile: dict[str, Any], reason: str | None,
                         tenant_id: uuid.UUID) -> Asset:
    before = dict(a.profile or {})
    a.profile = {**before, **profile}
    a.profile_version += 1
    db.add(AssetProfileVersion(tenant_id=a.tenant_id or tenant_id, asset_id=a.id, version=a.profile_version,
                               profile=a.profile, changed_by=actor, changed_at=datetime.now(UTC), reason=reason))
    audit.record(db, action="asset.profile_update", resource_type="asset", resource_id=a.id, tenant_id=tenant_id,
                 actor_id=actor, before=before, after=a.profile, reason=reason)
    return a


def export_landscape(db: Session, ls: Landscape) -> dict[str, Any]:
    members = db.scalars(select(LandscapeMember).where(LandscapeMember.landscape_id == ls.id)).all()
    return {
        "landscape": {"id": str(ls.id), "name": ls.name, "description": ls.description, "disease": ls.disease,
                      "geographies": ls.geographies, "status": ls.status, "config": ls.config, "version": ls.version},
        "members": [{"entity_type": m.entity_type, "entity_id": str(m.entity_id), "role": m.role} for m in members],
        "exported_at": datetime.now(UTC).isoformat(),
    }


def _provenance_for_trial(db: Session, t: Trial, field: str) -> dict[str, Any] | None:
    if not t.current_snapshot_id:
        return None
    snap = db.get(SourceSnapshot, t.current_snapshot_id)
    return {"source": "ctgov", "snapshot_id": str(snap.id), "snapshot_version": snap.version,
            "source_document_id": str(snap.source_document_id), "field": field,
            "retrieved_at": snap.retrieved_at.isoformat(), "uri": f"https://clinicaltrials.gov/study/{t.nct_id}"}


MATRIX_COLUMNS = ["company", "mechanism", "modality", "phase", "population", "biomarker", "primary_endpoints", "dosing",
                  "lead_trial", "trial_status", "enrollment", "primary_completion", "next_milestone"]


def asset_row(db: Session, a: Asset, role: str) -> dict[str, Any]:
    """One matrix row; every populated factual cell carries provenance (FR-UX-003)."""
    now = datetime.now(UTC)
    p = a.profile or {}
    comp = db.get(Company, a.owner_company_id) if a.owner_company_id else None
    prof_prov = {"source": "internal" if a.is_internal else "curated_profile", "field": "asset.profile",
                 "profile_version": a.profile_version, "updated_at": a.updated_at.isoformat()}
    cells: dict[str, Any] = {}

    def cell(key: str, value: Any, prov: dict[str, Any] | None) -> None:
        cells[key] = {"value": None, "provenance": None} if value in (None, "", []) else {"value": value, "provenance": prov}

    cell("company", comp.canonical_name if comp else None, prof_prov if comp else None)
    cell("mechanism", p.get("mechanism") or p.get("targets"), prof_prov)
    cell("modality", a.modality or p.get("modality"), prof_prov)
    cell("population", p.get("population") or p.get("line_of_therapy"), prof_prov)
    cell("biomarker", p.get("biomarkers") or p.get("biomarker"), prof_prov)
    cell("dosing", p.get("dosing"), prof_prov)
    trials = [t for t in (db.get(Trial, x) for x in neighbours(db, a.id, predicate="evaluated_in")) if t]
    lead = max(trials, key=lambda t: (t.phase or "", t.enrollment or 0), default=None)
    if lead:
        cur = lead.current or {}
        cell("phase", lead.phase, _provenance_for_trial(db, lead, "phase"))
        cell("lead_trial", lead.nct_id, _provenance_for_trial(db, lead, "nct_id"))
        cell("trial_status", lead.status, _provenance_for_trial(db, lead, "status"))
        cell("enrollment", lead.enrollment, _provenance_for_trial(db, lead, "enrollment"))
        cell("primary_endpoints", [o.get("measure") for o in cur.get("primary_endpoints", [])],
             _provenance_for_trial(db, lead, "primary_endpoints"))
        cell("primary_completion", cur.get("primary_completion_date"),
             _provenance_for_trial(db, lead, "primary_completion_date"))
    else:
        cell("phase", a.stage or p.get("stage"), prof_prov)
        cell("primary_endpoints", p.get("endpoint"), prof_prov)
        for k in ("lead_trial", "trial_status", "enrollment", "primary_completion"):
            cell(k, None, None)
    nc = db.scalar(select(Catalyst).where(Catalyst.asset_id == a.id, Catalyst.status == "upcoming")
                   .order_by(Catalyst.expected_date.nulls_last()).limit(1))
    if nc:
        d = nc.expected_date or nc.window_start
        cell("next_milestone", {"title": nc.title, "date": d.isoformat() if d else None, "basis": nc.date_basis},
             {"source": "catalyst", "catalyst_id": str(nc.id), "date_basis": nc.date_basis})
    else:
        cell("next_milestone", p.get("milestones"), prof_prov)
    stale = bool(lead and lead.last_seen_at and (now - lead.last_seen_at).days > 7)
    return {"asset_id": str(a.id), "asset": a.canonical_name, "role": role, "is_internal": a.is_internal,
            "status": a.status, "cells": cells, "trials": [t.nct_id for t in trials], "stale": stale}


def landscape_matrix(db: Session, ls: Landscape) -> dict[str, Any]:
    members = db.scalars(select(LandscapeMember).where(LandscapeMember.landscape_id == ls.id,
                                                       LandscapeMember.entity_type == "asset")).all()
    out_rows = [asset_row(db, a, m.role) for m in members if (a := db.get(Asset, m.entity_id)) is not None]
    out_rows.sort(key=lambda r: (r["role"] != "customer", r["asset"].lower()))
    return {"landscape_id": str(ls.id), "columns": MATRIX_COLUMNS, "rows": out_rows,
            "note": "Cross-trial attributes are shown side by side for context only; they do not establish superiority."}
