"""Entity resolution, review/correction memory, graph traversal (FR-ENT-002/003/004/005)."""

from __future__ import annotations

from app.db.session import session_scope
from app.entities.graph import find_path
from app.entities.resolver import EntityResolver, add_alias, normalize_alias
from app.models import Asset, EntityLink


def test_alias_normalization():
    assert normalize_alias("XD-101") == normalize_alias("xd 101") == "xd 101"
    assert normalize_alias("Bravo Oncology, Inc.", "company") == "bravo oncology"
    assert normalize_alias("Zelvatinib®") == "zelvatinib"


def test_exact_and_normalized_alias_resolution(seeded):
    with session_scope(bypass_rls=True) as db:
        r = EntityResolver(db)
        a = r.resolve("zelvatinib", "asset")
        assert a.linked and a.method == "exact_alias" and a.confidence >= 0.92
        assert a.entity_id == seeded["ids"]["asset:CA-201"]
        b = r.resolve("CA 201", "asset")
        assert b.linked and b.entity_id == a.entity_id
        ind = r.resolve("Carcinoma, Non-Small-Cell Lung", "indication")
        assert ind.linked


def test_dev_codes_never_fuzzy_autolink(seeded):
    with session_scope(bypass_rls=True) as db:
        r = EntityResolver(db).resolve("CA-202", "asset")
        assert not r.linked, "a different development code must not be auto-linked"


def test_ambiguous_alias_enters_review(seeded):
    with session_scope(bypass_rls=True) as db:
        add_alias(db, entity_type="asset", entity_id=seeded["ids"]["asset:BRV-310"], alias="TGX-drug", source="seed")
        add_alias(db, entity_type="asset", entity_id=seeded["ids"]["asset:KST-2"], alias="TGX-drug", source="seed")
        r = EntityResolver(db).resolve("TGX-drug", "asset")
        assert r.status == "pending_review" and r.entity_id is None and len(r.candidates) == 2


def test_low_confidence_not_promoted_and_corrections_are_reused(seeded):
    tid = seeded["tenant_id"]
    with session_scope(tid) as db:
        res = EntityResolver(db, tid).resolve("zelvatinib hydrochloride tablets", "asset")
        assert not (res.linked and res.method == "fuzzy" and res.confidence < 0.92)
        # analyst correction (tenant-scoped): approve mention -> CA-201
        db.add(EntityLink(tenant_id=tid, mention="Zelva-HCl", mention_norm=normalize_alias("Zelva-HCl"),
                          entity_type="asset", entity_id=seeded["ids"]["asset:CA-201"], confidence=1.0,
                          method="analyst", status="approved"))
        db.flush()
        again = EntityResolver(db, tid).resolve("zelva hcl", "asset")
        assert again.linked and again.method == "analyst" and again.entity_id == seeded["ids"]["asset:CA-201"]
    # the correction is tenant-private: the global resolver does not see it
    with session_scope(bypass_rls=True) as db:
        assert not EntityResolver(db).resolve("zelva hcl", "asset").linked


def test_rejection_is_honoured(seeded):
    tid = seeded["tenant_id"]
    with session_scope(tid) as db:
        db.add(EntityLink(tenant_id=tid, mention="zelvatinib", mention_norm="zelvatinib", entity_type="asset",
                          entity_id=seeded["ids"]["asset:CA-201"], confidence=0.0, method="analyst", status="rejected"))
        db.flush()
        assert not EntityResolver(db, tid).resolve("zelvatinib", "asset").linked


def test_merged_entities_are_not_targets(seeded):
    with session_scope(bypass_rls=True) as db:
        a = db.get(Asset, seeded["ids"]["asset:GMA-55"])
        a.merged_into_id = seeded["ids"]["asset:CA-201"]
        db.flush()
        assert not EntityResolver(db).resolve("GMA-55", "asset").linked


def test_graph_traversal_customer_to_trial(demo_pipeline):
    from sqlalchemy import select

    from app.models import Trial

    tid = demo_pipeline["tenant_id"]
    with session_scope(tid) as db:
        trial = db.scalar(select(Trial).where(Trial.nct_id == "NCT99000001"))
        path = find_path(db, demo_pipeline["xd101"], trial.id)
        assert [h["predicate"] for h in path] == ["competes_with", "evaluated_in"]
