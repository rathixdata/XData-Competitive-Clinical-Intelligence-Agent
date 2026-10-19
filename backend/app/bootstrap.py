"""First-run workspace for a fresh production deployment (no demo data).

When ``XDATA_BOOTSTRAP_TENANT`` is set and that tenant does not exist yet, this creates:

* the tenant and its administrator (``XDATA_BOOTSTRAP_ADMIN_EMAIL`` / ``XDATA_BOOTSTRAP_ADMIN_PASSWORD``);
* real reference vocabulary (indications, endpoints, modalities with their common synonyms), so source
  records written in different ways resolve to the same concept;
* the customer asset profile fields, a starter customer asset (XD-101, NSCLC, editable in the UI) and a
  starter competitor watch that monitors live ClinicalTrials.gov, PubMed and openFDA records for NSCLC;
* an active proximity rule and an immediate in-app alert policy for the administrator.

It is idempotent: on later starts it does nothing. The first connector runs are triggered by the caller
(``python -m app.cli first-run``) so the workspace fills with real data within minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import encrypt_json, hash_password
from app.core.logging import get_logger
from app.entities.resolver import add_alias
from app.materiality.proximity import DEFAULT_WEIGHTS
from app.models import (
    AlertPolicy,
    Asset,
    Concept,
    ConnectorConfig,
    LandscapeTemplate,
    ProfileFieldDefinition,
    ProximityRule,
    Tenant,
    User,
)
from app.pipeline.ingest import ensure_connector_configs
from app.services import audit
from app.services.landscapes import create_internal_asset, create_landscape, set_members

log = get_logger(__name__)

REFERENCE_CONCEPTS: dict[str, list[tuple[str, list[str]]]] = {
    "indication": [
        ("Non-small cell lung cancer", ["NSCLC", "non small cell lung cancer", "Carcinoma, Non-Small-Cell Lung",
                                        "non-small-cell lung carcinoma", "non-small cell lung carcinoma"]),
        ("Small cell lung cancer", ["SCLC", "Small Cell Lung Carcinoma"]),
        ("Breast cancer", ["Breast Neoplasms", "breast carcinoma"]),
        ("Colorectal cancer", ["CRC", "mCRC", "Colorectal Neoplasms"]),
    ],
    "endpoint": [
        ("Objective response rate", ["ORR", "Overall response rate", "Objective Response Rate (ORR)"]),
        ("Progression-free survival", ["PFS", "Progression-Free Survival (PFS)"]),
        ("Overall survival", ["OS", "Overall Survival (OS)"]),
        ("Duration of response", ["DOR", "DoR"]),
    ],
    "modality": [
        ("Small molecule", ["oral small molecule"]),
        ("Monoclonal antibody", ["mAb", "antibody"]),
        ("Antibody-drug conjugate", ["ADC"]),
        ("Bispecific antibody", ["bispecific"]),
    ],
}

PROFILE_FIELDS: list[tuple[str, str, str, bool, list[str]]] = [
    ("mechanism", "Mechanism", "text", True, []), ("indications", "Indications", "list", True, []),
    ("stage", "Development stage", "enum", True, ["Preclinical", "Phase 1", "Phase 2", "Phase 3", "Filed", "Approved"]),
    ("population", "Population", "text", False, []), ("biomarkers", "Biomarkers", "list", False, []),
    ("endpoint", "Primary endpoint", "text", False, []), ("route", "Route", "text", False, []),
    ("dosing", "Dosing", "text", False, []), ("milestones", "Milestones", "text", False, []),
    ("strategic_notes", "Strategic notes", "text", False, []),
]

NSCLC_TEMPLATE: dict[str, Any] = {
    "trial_queries": [{"cond": "non-small cell lung cancer", "intr": "inhibitor"}],
    "pubmed_queries": ["non-small cell lung cancer[tiab] AND (targeted therapy[tiab] OR inhibitor[tiab])"],
    "fda_products": ["osimertinib", "lorlatinib", "amivantamab", "sotorasib", "adagrasib"],
    "indications": ["non small cell lung cancer", "nsclc"],
    "band_thresholds": {"Feed": 30, "Analyst Review": 50, "High Priority": 70, "Executive Alert": 85},
}


def ensure_reference_concepts(db: Session) -> None:
    for kind, items in REFERENCE_CONCEPTS.items():
        for name, aliases in items:
            c = db.scalar(select(Concept).where(Concept.kind == kind, Concept.canonical_name == name,
                                                Concept.tenant_id.is_(None)))
            if c is None:
                c = Concept(kind=kind, canonical_name=name)
                db.add(c)
                db.flush()
            for al in [name, *aliases]:
                add_alias(db, entity_type=kind, entity_id=c.id, alias=al, alias_type="synonym", source="reference")
    if db.scalar(select(LandscapeTemplate).where(LandscapeTemplate.name == "NSCLC targeted therapy")) is None:
        db.add(LandscapeTemplate(name="NSCLC targeted therapy", therapeutic_area="Thoracic oncology",
                                 description="Targeted-therapy landscape template for non-small cell lung cancer.",
                                 config=NSCLC_TEMPLATE))
    db.flush()


def bootstrap_workspace(db: Session) -> dict[str, Any] | None:
    """Create the first-run workspace if configured and missing. Returns what was created, or None."""
    s = get_settings()
    if not s.bootstrap_tenant:
        return None
    if db.scalar(select(Tenant).where(Tenant.slug == s.bootstrap_tenant)) is not None:
        return None
    email = (s.bootstrap_admin_email or "").strip().lower()
    password = s.bootstrap_admin_password.get_secret_value() if s.bootstrap_admin_password else ""
    if not email or len(password) < 12:
        raise RuntimeError("XDATA_BOOTSTRAP_ADMIN_EMAIL and XDATA_BOOTSTRAP_ADMIN_PASSWORD (12+ characters) are required "
                           "to create the first workspace")

    ensure_connector_configs(db)
    ensure_reference_concepts(db)
    tenant = Tenant(name=s.bootstrap_tenant_name, slug=s.bootstrap_tenant,
                    settings={"llm_monthly_budget_usd": 200, "allow_training_on_customer_data": False})
    db.add(tenant)
    db.flush()
    tid = tenant.id
    admin = User(tenant_id=tid, email=email, display_name="Administrator", roles=["tenant_admin", "ci_lead"],
                 team="CI", password_hash=hash_password(password))
    db.add(admin)
    db.flush()
    actor = str(admin.id)
    for i, (key, label, ftype, req, opts) in enumerate(PROFILE_FIELDS):
        db.add(ProfileFieldDefinition(tenant_id=tid, key=key, label=label, field_type=ftype, required=req,
                                      options=opts, sort_order=i))
    db.flush()

    asset = db.scalar(select(Asset).where(Asset.tenant_id == tid, Asset.is_internal.is_(True)))
    if asset is None:
        asset = create_internal_asset(db, tid, actor, {
            "name": "XD-101", "aliases": ["XD101"], "modality": "Small molecule", "stage": "Phase 2",
            "profile": {"targets": [], "mechanism": "Targeted kinase inhibitor", "modality": "Small molecule",
                        "indications": ["Non-small cell lung cancer"], "line_of_therapy": "2L+",
                        "population": "2L+ biomarker-positive", "biomarkers": [],
                        "endpoint": "Objective response rate", "stage": "Phase 2", "route": "Oral",
                        "geographies": ["United States"],
                        "strategic_notes": "Starter profile - edit it on the asset page to match your own drug."}})
    tpl = db.scalar(select(LandscapeTemplate).where(LandscapeTemplate.name == "NSCLC targeted therapy"))
    ls = create_landscape(db, tid, actor, {
        "name": "Non-small cell lung cancer", "disease": "Non-small cell lung cancer", "geographies": ["US"],
        "description": "Starter competitor watch: live ClinicalTrials.gov, PubMed and FDA records for NSCLC "
                       "targeted therapies. Change the searches in Settings to fit your portfolio.",
        "template_id": tpl.id if tpl else None, "config": {}})
    set_members(db, ls, actor, [{"entity_type": "asset", "entity_id": asset.id, "role": "customer"}])
    db.add(ProximityRule(tenant_id=tid, landscape_id=ls.id, name="Default proximity", weights=DEFAULT_WEIGHTS,
                         min_proximity=0.35, status="active", version=1, created_by=actor,
                         test_results={"tested_at": datetime.now(UTC).isoformat(), "tested_by": actor, "pairs": []},
                         activated_at=datetime.now(UTC)))
    db.add(AlertPolicy(tenant_id=tid, owner_id=admin.id, name="High priority and above (immediate)",
                       landscape_id=ls.id, cadence="immediate", min_score=70, channels=["web"],
                       destinations_encrypted=encrypt_json({})))
    # Run every enabled connector on the next scheduler tick instead of waiting for its cron slot.
    for cfg in db.scalars(select(ConnectorConfig).where(ConnectorConfig.enabled.is_(True))).all():
        cfg.next_run_at = datetime.now(UTC)
    db.flush()
    audit.record(db, action="tenant.bootstrap", resource_type="tenant", resource_id=tid, tenant_id=tid,
                 actor_id="bootstrap", actor_type="system", after={"slug": tenant.slug, "admin": email})
    log.info("workspace_bootstrapped", tenant=tenant.slug, admin=email)
    return {"tenant_id": str(tid), "landscape_id": str(ls.id), "asset_id": str(asset.id)}
