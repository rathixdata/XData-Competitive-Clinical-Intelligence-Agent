"""Demo / pilot seed based on the SRS Section 5 illustrative case study.

Customer asset XD-101 (Target-X inhibitor, NSCLC, Phase II, 2L+ biomarker-positive, primary endpoint ORR)
monitored against 12 companies / 18 external programs. All names are illustrative.

The seed runs the *real* pipeline: fixture records go through the production adapters' parse(), raw
retention, entity resolution, snapshots, diffing, materiality, mapping, narrative and validation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import FetchPlan
from app.core.crypto import encrypt_json, hash_password
from app.db.session import session_scope
from app.entities.graph import upsert_edge
from app.entities.resolver import add_alias
from app.materiality.proximity import DEFAULT_WEIGHTS
from app.models import (
    AlertPolicy,
    Asset,
    Company,
    Concept,
    Landscape,
    LandscapeTemplate,
    ProfileFieldDefinition,
    ProximityRule,
    Tenant,
    User,
    Watchlist,
    WatchlistItem,
)
from app.pipeline.ingest import ensure_connector_configs, run_connector
from app.pipeline.intelligence import process_pending_changes
from app.seed.fixtures import (
    FixtureCTGovAdapter,
    FixtureLabelAdapter,
    FixturePubMedAdapter,
    ctgov_study,
    pubmed_article,
)
from app.services.landscapes import create_internal_asset, create_landscape, set_members

CONCEPTS: dict[str, list[tuple[str, list[str]]]] = {
    "target": [("Target-X", ["TGX", "target x"]), ("Target-Y", ["TGY"]), ("Target-Z", ["TGZ"])],
    "mechanism": [("Target-X inhibitor", ["TGX inhibitor", "anti-Target-X"]), ("Target-Y inhibitor", []),
                  ("Target-X antibody-drug conjugate", ["Target-X ADC"]), ("Target-Z bispecific", [])],
    "indication": [("Non-small cell lung cancer", ["NSCLC", "non small cell lung cancer", "Carcinoma, Non-Small-Cell Lung",
                                                   "non-small-cell lung carcinoma"]),
                   ("Colorectal cancer", ["CRC", "mCRC"]), ("Small cell lung cancer", ["SCLC"])],
    "biomarker": [("Target-X mutation", ["TGX mutation", "Target-X mutant", "Target-X alteration"]),
                  ("Target-Y amplification", ["TGY amplification"])],
    "endpoint": [("Objective response rate", ["ORR", "Overall response rate", "Objective Response Rate (ORR)"]),
                 ("Progression-free survival", ["PFS", "Progression-Free Survival (PFS)"]),
                 ("Overall survival", ["OS", "Overall Survival (OS)"])],
    "modality": [("Small molecule", ["oral small molecule"]), ("Antibody-drug conjugate", ["ADC"]),
                 ("Bispecific antibody", ["bispecific"])],
}

COMPANIES = [
    ("Competitor A Therapeutics", ["Competitor A", "CompA"], "9990001"),
    ("Bravo Oncology", ["Bravo Onc"], "9990002"), ("Cedar Biopharma", ["Cedar Bio"], None),
    ("Delta Pharmaceuticals", ["Delta Pharma"], "9990004"), ("Echo Biosciences", [], None),
    ("Foxtrot Medicines", [], None), ("Gamma Life Sciences", [], None), ("Helix Therapeutics", [], None),
    ("Iris Oncology", [], None), ("Juniper Bio", [], None), ("Kestrel Pharma", [], None), ("Lumen Therapeutics", [], None),
]

# (name, aliases, company, target, mechanism, modality, indication, line, biomarker, stage, endpoint)
ASSETS = [
    ("CA-201", ["zelvatinib", "CA201"], "Competitor A Therapeutics", "Target-X", "Target-X inhibitor", "Small molecule",
     "Non-small cell lung cancer", "2L+", "Target-X mutation", "Phase 3", "Objective response rate"),
    ("BRV-310", ["brevatinib"], "Bravo Oncology", "Target-X", "Target-X inhibitor", "Small molecule",
     "Non-small cell lung cancer", "1L", "Target-X mutation", "Phase 3", "Progression-free survival"),
    ("CDR-44", ["cedarlimab vedotin"], "Cedar Biopharma", "Target-X", "Target-X antibody-drug conjugate",
     "Antibody-drug conjugate", "Non-small cell lung cancer", "2L+", "Target-X mutation", "Phase 2",
     "Objective response rate"),
    ("DLT-7", ["deltarasib"], "Delta Pharmaceuticals", "Target-Y", "Target-Y inhibitor", "Small molecule",
     "Non-small cell lung cancer", "2L+", "Target-Y amplification", "Phase 2", "Objective response rate"),
    ("ECH-101", [], "Echo Biosciences", "Target-X", "Target-X inhibitor", "Small molecule", "Colorectal cancer", "2L+",
     "Target-X mutation", "Phase 2", "Objective response rate"),
    ("FXT-9", [], "Foxtrot Medicines", "Target-Z", "Target-Z bispecific", "Bispecific antibody",
     "Non-small cell lung cancer", "2L+", None, "Phase 1", "Objective response rate"),
    ("GMA-55", [], "Gamma Life Sciences", "Target-X", "Target-X inhibitor", "Small molecule",
     "Non-small cell lung cancer", "2L+", "Target-X mutation", "Phase 1", "Objective response rate"),
    ("HLX-3", [], "Helix Therapeutics", "Target-Y", "Target-Y inhibitor", "Small molecule", "Colorectal cancer", "3L+",
     "Target-Y amplification", "Phase 2", "Progression-free survival"),
    ("IRS-12", [], "Iris Oncology", "Target-X", "Target-X inhibitor", "Small molecule", "Small cell lung cancer", "2L+",
     None, "Phase 1", "Objective response rate"),
    ("JNP-8", [], "Juniper Bio", "Target-Z", "Target-Z bispecific", "Bispecific antibody", "Colorectal cancer", "2L+",
     None, "Phase 1", "Objective response rate"),
    ("KST-2", [], "Kestrel Pharma", "Target-X", "Target-X inhibitor", "Small molecule", "Non-small cell lung cancer", "1L",
     "Target-X mutation", "Phase 2", "Progression-free survival"),
    ("LMN-60", [], "Lumen Therapeutics", "Target-X", "Target-X antibody-drug conjugate", "Antibody-drug conjugate",
     "Non-small cell lung cancer", "3L+", "Target-X mutation", "Phase 1", "Objective response rate"),
    ("BRV-311", [], "Bravo Oncology", "Target-Y", "Target-Y inhibitor", "Small molecule", "Non-small cell lung cancer",
     "2L+", "Target-Y amplification", "Phase 1", "Objective response rate"),
    ("CA-305", [], "Competitor A Therapeutics", "Target-Z", "Target-Z bispecific", "Bispecific antibody",
     "Non-small cell lung cancer", "1L", None, "Phase 1", "Progression-free survival"),
    ("DLT-9", [], "Delta Pharmaceuticals", "Target-X", "Target-X inhibitor", "Small molecule", "Non-small cell lung cancer",
     "2L+", "Target-X mutation", "Phase 2", "Objective response rate"),
    ("GMA-60", [], "Gamma Life Sciences", "Target-Y", "Target-Y inhibitor", "Small molecule", "Small cell lung cancer",
     "2L+", None, "Phase 1", "Objective response rate"),
    ("HLX-9", [], "Helix Therapeutics", "Target-X", "Target-X antibody-drug conjugate", "Antibody-drug conjugate",
     "Colorectal cancer", "2L+", "Target-X mutation", "Phase 1", "Objective response rate"),
    ("KST-7", [], "Kestrel Pharma", "Target-Y", "Target-Y inhibitor", "Small molecule", "Non-small cell lung cancer", "1L",
     "Target-Y amplification", "Phase 1", "Progression-free survival"),
]

ELIG_2L = ("Inclusion Criteria: Histologically confirmed locally advanced or metastatic NSCLC. Documented Target-X "
           "mutation by an approved test. Previously treated with at least one prior line of systemic therapy. "
           "ECOG performance status 0-1. Exclusion Criteria: Prior Target-X inhibitor therapy. Untreated brain metastases.")

PIVOTAL_NCT = "NCT99000001"


def trial_fixtures(version: int) -> list[dict[str, Any]]:
    """v1 = baseline; v2 = SRS Section 16 acceptance scenario + noise + a halted competitor trial."""
    pivotal = dict(nct=PIVOTAL_NCT, title="Study of CA-201 Versus Docetaxel in Target-X Mutant NSCLC (ZEPHYR-3)",
                   sponsor="Competitor A Therapeutics", phase=["PHASE3"], status="RECRUITING", enrollment=320,
                   start="2025-01-15", pcd="2027-06", cd="2028-06", conditions=["Non-small Cell Lung Cancer"],
                   drug="CA-201", other_names=["zelvatinib"], acronym="ZEPHYR-3",
                   primary=[("Objective Response Rate (ORR)", "Up to 24 months")],
                   secondary=[("Overall Survival (OS)", "Up to 48 months"), ("Duration of response", "Up to 36 months")],
                   eligibility=ELIG_2L, countries=["United States", "Germany", "Japan", "Spain"])
    trials = [
        dict(nct="NCT99000002", title="BRV-310 First-line Target-X NSCLC (BRAVADO-1)", sponsor="Bravo Oncology",
             phase=["PHASE3"], status="RECRUITING", enrollment=600, start="2024-06-01", pcd="2027-12", cd="2029-06",
             conditions=["NSCLC"], drug="BRV-310", other_names=["brevatinib"],
             primary=[("Progression-Free Survival (PFS)", "Up to 36 months")],
             eligibility="Inclusion Criteria: Treatment-naive advanced NSCLC with Target-X mutation.",
             countries=["United States", "China"], comparator="Platinum doublet chemotherapy"),
        dict(nct="NCT99000003", title="CDR-44 in Previously Treated Target-X NSCLC", sponsor="Cedar Biopharma",
             phase=["PHASE2"], status="RECRUITING", enrollment=120, start="2025-03-01", pcd="2026-12", cd="2027-06",
             conditions=["Non-Small Cell Lung Cancer"], drug="CDR-44", other_names=["cedarlimab vedotin"],
             primary=[("Objective Response Rate (ORR)", "Up to 18 months")], eligibility=ELIG_2L, comparator=None),
        dict(nct="NCT99000004", title="DLT-7 in Target-Y Amplified NSCLC", sponsor="Delta Pharmaceuticals",
             phase=["PHASE2"], status="RECRUITING", enrollment=90, start="2025-02-01", pcd="2026-11", cd="2027-05",
             conditions=["NSCLC"], drug="DLT-7", other_names=["deltarasib"],
             primary=[("Objective Response Rate (ORR)", "Up to 12 months")],
             eligibility="Inclusion Criteria: Target-Y amplification. Previously treated advanced NSCLC.", comparator=None),
        dict(nct="NCT99000005", title="GMA-55 First-in-Human Study in Target-X NSCLC", sponsor="Gamma Life Sciences",
             phase=["PHASE1"], status="RECRUITING", enrollment=60, start="2025-05-01", pcd="2026-10", cd="2027-03",
             conditions=["Non-small Cell Lung Cancer"], drug="GMA-55",
             primary=[("Incidence of dose-limiting toxicities", "Cycle 1 (21 days)")], eligibility=ELIG_2L, comparator=None),
        dict(nct="NCT99000006", title="DLT-9 in Target-X Mutant NSCLC After Prior Therapy", sponsor="Delta Pharmaceuticals",
             phase=["PHASE2"], status="RECRUITING", enrollment=150, start="2024-11-01", pcd="2027-02", cd="2027-09",
             conditions=["NSCLC"], drug="DLT-9", primary=[("Objective Response Rate (ORR)", "Up to 18 months")],
             eligibility=ELIG_2L, comparator=None),
        dict(nct="NCT99000007", title="KST-2 First-line Target-X NSCLC", sponsor="Kestrel Pharma", phase=["PHASE2"],
             status="RECRUITING", enrollment=110, start="2025-01-01", pcd="2027-04", cd="2027-12", conditions=["NSCLC"],
             drug="KST-2", primary=[("Progression-Free Survival (PFS)", "Up to 24 months")],
             eligibility="Inclusion Criteria: Treatment-naive NSCLC with Target-X mutation.", comparator=None),
    ]
    if version >= 2:
        pivotal.update(enrollment=480, pcd="2027-11", primary=[("Progression-Free Survival (PFS)", "Up to 30 months")],
                       last_update="2026-09-24")
        # noise: formatting-only / ordering-only edits must not alert (FR-CHG-005)
        trials[0]["title"] = "BRV-310  First-line Target-X NSCLC (BRAVADO-1)"
        trials[0]["countries"] = ["China", "United States"]
        # material: a competitor Phase 2 is terminated
        trials[4].update(status="TERMINATED", last_update="2026-09-23")
    return [ctgov_study(**pivotal)] + [ctgov_study(**t) for t in trials]


def publication_fixtures() -> list[tuple[str, bytes]]:
    today = datetime.now(UTC)
    return [
        ("99100001", pubmed_article(
            "99100001", "Zelvatinib (CA-201) in previously treated Target-X mutant non-small cell lung cancer: "
                        "phase 2 dose-expansion results",
            [("BACKGROUND", "CA-201 is an oral Target-X inhibitor."),
             ("RESULTS", "Among 84 previously treated patients with Target-X mutant NSCLC, the objective response rate "
                         "was 41% and median progression-free survival was 7.9 months. Grade 3 or higher "
                         "treatment-related adverse events occurred in 22% of patients."),
             ("CONCLUSIONS", "CA-201 showed antitumor activity; a phase 3 trial (NCT99000001) is ongoing.")],
            "Journal of Thoracic Oncology Research", today.year, today.month,
            [("Ana", "Rivera", "University Cancer Center"), ("Ken", "Sato", "National Cancer Hospital")],
            chemicals=["zelvatinib"], mesh=["Carcinoma, Non-Small-Cell Lung", "Protein Kinase Inhibitors"],
            nct_ids=[PIVOTAL_NCT], doi="10.9999/xdata.demo.001", pub_types=["Journal Article", "Clinical Trial, Phase II"])),
        ("99100002", pubmed_article(
            "99100002", "Target-X ADCs in lung cancer: a review",
            [("ABSTRACT", "Antibody-drug conjugates directed at Target-X, including CDR-44, are in clinical development "
                          "for previously treated NSCLC.")],
            "Oncology Reviews Demo", today.year, max(1, today.month - 1),
            [("Lee", "Chen", "Institute of Oncology")], chemicals=["cedarlimab vedotin"],
            mesh=["Carcinoma, Non-Small-Cell Lung"], pub_types=["Journal Article", "Review"])),
    ]


def label_fixture(version: int) -> dict[str, Any]:
    ind = "BRAVITRA is indicated for adult patients with metastatic NSCLC whose tumors have a Target-X mutation."
    if version >= 2:
        ind += " BRAVITRA is also indicated as first-line treatment in combination with chemotherapy."
    return {"set_id": "demo-set-0001", "version": str(version), "effective_time": "20260915" if version >= 2 else "20250301",
            "openfda": {"brand_name": ["BRAVITRA"], "generic_name": ["brevatinib"], "manufacturer_name": ["Bravo Oncology"],
                        "application_number": ["NDA999001"]},
            "indications_and_usage": [ind],
            "dosage_and_administration": ["The recommended dosage is 200 mg orally once daily."],
            "warnings_and_cautions": ["Interstitial lung disease has been reported."]}


def seed_reference_data(db: Session) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for kind, items in CONCEPTS.items():
        for name, aliases in items:
            c = db.scalar(select(Concept).where(Concept.kind == kind, Concept.canonical_name == name,
                                                Concept.tenant_id.is_(None)))
            if c is None:
                c = Concept(kind=kind, canonical_name=name)
                db.add(c)
                db.flush()
            ids[f"{kind}:{name}"] = c.id
            for al in [name, *aliases]:
                add_alias(db, entity_type=kind, entity_id=c.id, alias=al, alias_type="synonym", source="seed")
    for name, aliases, cik in COMPANIES:
        co = db.scalar(select(Company).where(Company.canonical_name == name, Company.tenant_id.is_(None)))
        if co is None:
            co = Company(canonical_name=name, identifiers={"cik": cik} if cik else {})
            db.add(co)
            db.flush()
        ids[f"company:{name}"] = co.id
        for al in [name, *aliases]:
            add_alias(db, entity_type="company", entity_id=co.id, alias=al, source="seed")
    for (name, aliases, comp, target, mech, modality, ind, line, bm, stage, ep) in ASSETS:
        a = db.scalar(select(Asset).where(Asset.canonical_name == name, Asset.tenant_id.is_(None)))
        profile = {"targets": [target], "mechanism": mech, "modality": modality, "indications": [ind],
                   "line_of_therapy": line, "population": f"{line} {bm + '-positive' if bm else 'all-comers'}",
                   "biomarkers": [bm] if bm else [], "endpoint": ep, "stage": stage, "geographies": ["United States"]}
        if a is None:
            a = Asset(canonical_name=name, owner_company_id=ids[f"company:{comp}"], modality=modality, stage=stage,
                      profile=profile)
            db.add(a)
            db.flush()
        ids[f"asset:{name}"] = a.id
        for al in [name, *aliases]:
            add_alias(db, entity_type="asset", entity_id=a.id, alias=al,
                      alias_type="dev_code" if al == name else "generic", source="seed")
        upsert_edge(db, subject_type="company", subject_id=ids[f"company:{comp}"], predicate="develops",
                    object_type="asset", object_id=a.id, method="seed")
        upsert_edge(db, subject_type="asset", subject_id=a.id, predicate="targets", object_type="target",
                    object_id=ids[f"target:{target}"], method="seed")
        upsert_edge(db, subject_type="asset", subject_id=a.id, predicate="indicated_for", object_type="indication",
                    object_id=ids[f"indication:{ind}"], method="seed")
    tpl = db.scalar(select(LandscapeTemplate).where(LandscapeTemplate.name == "NSCLC targeted therapy"))
    if tpl is None:
        db.add(LandscapeTemplate(name="NSCLC targeted therapy", therapeutic_area="Thoracic oncology",
                                 description="Targeted-therapy landscape template for non-small cell lung cancer.",
                                 config={"trial_queries": [{"cond": "non-small cell lung cancer", "intr": "inhibitor"}],
                                         "pubmed_queries": ["non-small cell lung cancer[tiab] AND targeted therapy[tiab]"],
                                         "indications": ["non small cell lung cancer", "nsclc"],
                                         "band_thresholds": {"Feed": 30, "Analyst Review": 50, "High Priority": 70,
                                                             "Executive Alert": 85}}))
    db.flush()
    return ids


def seed_tenant(db: Session, ids: dict[str, uuid.UUID], slug: str = "demo-oncology",
                admin_password: str = "ChangeMe-Demo-2026!") -> dict[str, Any]:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        tenant = Tenant(name="Demo Oncology Co. (illustrative)", slug=slug,
                        settings={"llm_monthly_budget_usd": 500, "allow_training_on_customer_data": False})
        db.add(tenant)
        db.flush()
    tid = tenant.id
    users = {}
    for email, name, roles, team in [
        ("admin@demo.example", "Tenant Admin", ["tenant_admin"], "CI"),
        ("analyst@demo.example", "CI Analyst", ["ci_analyst"], "CI"),
        ("lead@demo.example", "Head of CI", ["ci_lead"], "CI"),
        ("clinical@demo.example", "Clinical Strategy", ["clinical_strategy"], "Clinical"),
        ("cso@demo.example", "Chief Scientific Officer", ["executive"], "Leadership"),
        ("auditor@demo.example", "Compliance Reviewer", ["auditor"], "Compliance"),
    ]:
        u = db.scalar(select(User).where(User.tenant_id == tid, User.email == email))
        if u is None:
            u = User(tenant_id=tid, email=email, display_name=name, roles=roles, team=team,
                     password_hash=hash_password(admin_password))
            db.add(u)
            db.flush()
        users[email] = u.id
    admin = str(users["admin@demo.example"])
    for i, (key, label, ftype, req, opts) in enumerate([
        ("mechanism", "Mechanism", "text", True, []), ("indications", "Indications", "list", True, []),
        ("stage", "Development stage", "enum", True, ["Preclinical", "Phase 1", "Phase 2", "Phase 3", "Filed", "Approved"]),
        ("population", "Population", "text", False, []), ("biomarkers", "Biomarkers", "list", False, []),
        ("endpoint", "Primary endpoint", "text", False, []), ("route", "Route", "text", False, []),
        ("dosing", "Dosing", "text", False, []), ("milestones", "Milestones", "text", False, []),
        ("strategic_notes", "Strategic notes", "text", False, [])]):
        if db.scalar(select(ProfileFieldDefinition).where(ProfileFieldDefinition.tenant_id == tid,
                                                          ProfileFieldDefinition.key == key)) is None:
            db.add(ProfileFieldDefinition(tenant_id=tid, key=key, label=label, field_type=ftype, required=req,
                                          options=opts, sort_order=i))
    db.flush()
    xd = db.scalar(select(Asset).where(Asset.tenant_id == tid, Asset.canonical_name == "XD-101"))
    if xd is None:
        xd = create_internal_asset(db, tid, admin, {
            "name": "XD-101", "aliases": ["XD101"], "modality": "Small molecule", "stage": "Phase 2",
            "profile": {"targets": ["Target-X"], "mechanism": "Target-X inhibitor", "modality": "Small molecule",
                        "indications": ["Non-small cell lung cancer"], "line_of_therapy": "2L+",
                        "population": "2L+ biomarker-positive", "biomarkers": ["Target-X mutation"],
                        "endpoint": "Objective response rate", "stage": "Phase 2", "route": "Oral",
                        "dosing": "Once daily", "geographies": ["United States"],
                        "milestones": "Phase 2 topline data expected H2 2027",
                        "strategic_notes": "Internal - differentiated CNS penetration hypothesis."}})
    ls = db.scalar(select(Landscape).where(Landscape.tenant_id == tid, Landscape.name == "NSCLC - Target-X"))
    if ls is None:
        tpl = db.scalar(select(LandscapeTemplate).where(LandscapeTemplate.name == "NSCLC targeted therapy"))
        ls = create_landscape(db, tid, admin, {
            "name": "NSCLC - Target-X", "description": "Competitive landscape for XD-101 (illustrative pilot).",
            "disease": "Non-small cell lung cancer", "geographies": ["US"], "template_id": tpl.id if tpl else None,
            "config": {"nct_ids": [PIVOTAL_NCT], "fda_products": ["brevatinib"], "sec_ciks": [],
                       "pubmed_queries": ["Target-X[tiab] AND non-small cell lung cancer[tiab]"]}})
        members = [{"entity_type": "asset", "entity_id": xd.id, "role": "customer"}]
        members += [{"entity_type": "asset", "entity_id": ids[f"asset:{a[0]}"], "role": "competitor"} for a in ASSETS]
        members += [{"entity_type": "company", "entity_id": ids[f"company:{c[0]}"], "role": "competitor"} for c in COMPANIES]
        set_members(db, ls, admin, members)
    if db.scalar(select(ProximityRule).where(ProximityRule.tenant_id == tid, ProximityRule.status == "active")) is None:
        db.add(ProximityRule(tenant_id=tid, landscape_id=ls.id, name="Default NSCLC proximity", weights=DEFAULT_WEIGHTS,
                             min_proximity=0.35, status="active", version=1, created_by=admin,
                             test_results={"tested_at": datetime.now(UTC).isoformat(), "tested_by": admin, "pairs": []},
                             activated_at=datetime.now(UTC)))
    if db.scalar(select(AlertPolicy).where(AlertPolicy.tenant_id == tid)) is None:
        db.add(AlertPolicy(tenant_id=tid, owner_id=users["cso@demo.example"], name="Executive alerts (immediate)",
                           landscape_id=ls.id, cadence="immediate", min_score=85, channels=["web"],
                           destinations_encrypted=encrypt_json({})))
        db.add(AlertPolicy(tenant_id=tid, owner_id=users["analyst@demo.example"], name="Analyst daily digest",
                           landscape_id=ls.id, cadence="daily", min_score=50, channels=["web"],
                           destinations_encrypted=encrypt_json({})))
        db.add(AlertPolicy(tenant_id=tid, owner_id=users["analyst@demo.example"], name="High priority (immediate)",
                           landscape_id=ls.id, cadence="immediate", min_score=70, channels=["web"],
                           destinations_encrypted=encrypt_json({})))
    if db.scalar(select(Watchlist).where(Watchlist.tenant_id == tid)) is None:
        wl = Watchlist(tenant_id=tid, owner_id=users["analyst@demo.example"], name="Direct Target-X competitors",
                       visibility="tenant", landscape_id=ls.id)
        db.add(wl)
        db.flush()
        for a in ("CA-201", "CDR-44", "DLT-9", "GMA-55"):
            db.add(WatchlistItem(tenant_id=tid, watchlist_id=wl.id, item_type="asset", entity_id=ids[f"asset:{a}"], value=a))
    db.flush()
    return {"tenant_id": tid, "landscape_id": ls.id, "users": users, "xd101": xd.id}


def run_demo_pipeline(*, use_llm: bool = False) -> dict[str, Any]:
    """Baseline ingestion (7 days ago), then the changed source records (today)."""
    plan = FetchPlan()
    t0 = datetime.now(UTC) - timedelta(days=7)
    run_connector("ctgov", trigger="backfill", adapter=FixtureCTGovAdapter(trial_fixtures(1), t0), plan=plan)
    run_connector("openfda_label", trigger="backfill", adapter=FixtureLabelAdapter([label_fixture(1)], t0), plan=plan)
    s1 = process_pending_changes(use_llm=use_llm)
    run_connector("ctgov", trigger="manual", adapter=FixtureCTGovAdapter(trial_fixtures(2)), plan=plan)
    run_connector("pubmed", trigger="manual", adapter=FixturePubMedAdapter(publication_fixtures()), plan=plan)
    run_connector("openfda_label", trigger="manual", adapter=FixtureLabelAdapter([label_fixture(2)]), plan=plan)
    s2 = process_pending_changes(use_llm=use_llm)
    return {"baseline": s1, "update": s2}


def seed_demo(*, with_pipeline: bool = True, use_llm: bool = False) -> dict[str, Any]:
    with session_scope(bypass_rls=True) as db:
        ensure_connector_configs(db)
        ids = seed_reference_data(db)
        info = seed_tenant(db, ids)
    out: dict[str, Any] = {"tenant_id": str(info["tenant_id"]), "landscape_id": str(info["landscape_id"])}
    if with_pipeline:
        out["pipeline"] = run_demo_pipeline(use_llm=use_llm)
    return out
