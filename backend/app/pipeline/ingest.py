"""Source ingestion pipeline (Section 5.1 steps 1-5).

fetch -> retain raw (content-addressed, immutable) -> normalize -> resolve entities -> upsert canonical
object -> snapshot (only when the normalized state changed) -> structured/document diff -> ChangeEvents
(fingerprinted, idempotent) -> index evidence for RAG -> maintain catalysts.
"""

from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.changes.diff import FieldChange, diff_objects, fingerprint
from app.connectors.base import FetchContext, FetchedRecord, FetchPlan, NormalizedRecord, SourceAdapter
from app.connectors.registry import META, get_adapter
from app.core.crypto import stable_hash
from app.core.logging import get_logger
from app.core.metrics import CHANGE_EVENTS, CONNECTOR_LAST_SUCCESS, CONNECTOR_RECORDS, CONNECTOR_RUNS
from app.db.session import session_scope
from app.entities.graph import neighbours, upsert_edge
from app.entities.resolver import EntityResolver, add_alias
from app.models import (
    Asset,
    Catalyst,
    ChangeEvent,
    Company,
    Concept,
    ConnectorConfig,
    ConnectorRun,
    Disclosure,
    Landscape,
    LandscapeMember,
    Publication,
    RegulatoryEvent,
    SourceDocument,
    SourceSnapshot,
    Trial,
)
from app.pipeline.normalize import parse_datetime, partial_date_to_date
from app.rag.indexer import index_sections
from app.storage.object_store import get_object_store

log = get_logger(__name__)
NS = uuid.UUID("5b0f7a52-3c1e-4a8e-9a57-0d7c1f5e2b11")


def object_uuid(object_type: str, source_object_id: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"{object_type}:{source_object_id}")


@dataclass
class RecordOutcome:
    status: str  # new | changed | unchanged | error
    object_id: uuid.UUID | None = None
    change_ids: list[uuid.UUID] = field(default_factory=list)
    snapshot_id: uuid.UUID | None = None


# ----------------------------------------------------------------------------- plan
def build_fetch_plan(db: Session) -> FetchPlan:
    """Aggregate what to monitor from every active landscape (runs with RLS bypass)."""
    plan = FetchPlan()
    for ls in db.scalars(select(Landscape).where(Landscape.status == "active")).all():
        cfg = ls.config or {}
        plan.nct_ids.update(x.upper() for x in cfg.get("nct_ids", []))
        for q in cfg.get("trial_queries", []):
            if q not in plan.trial_queries:
                plan.trial_queries.append(q)
        for q in cfg.get("pubmed_queries", []):
            existing = next((p for p in plan.pubmed_queries if p["query"] == q), None)
            if existing:
                existing["landscape_ids"].append(str(ls.id))
            else:
                plan.pubmed_queries.append({"query": q, "landscape_ids": [str(ls.id)]})
        plan.fda_products.update(cfg.get("fda_products", []))
        plan.sec_ciks.update(str(c) for c in cfg.get("sec_ciks", []))
        plan.feeds.extend(f for f in cfg.get("feeds", []) if f not in plan.feeds)
        members = db.execute(select(LandscapeMember.entity_type, LandscapeMember.entity_id).where(
            LandscapeMember.landscape_id == ls.id)).all()
        for etype, eid in members:
            if etype == "trial":
                t = db.get(Trial, eid)
                if t and t.nct_id:
                    plan.nct_ids.add(t.nct_id)
            elif etype == "company":
                c = db.get(Company, eid)
                if c and (c.identifiers or {}).get("cik"):
                    plan.sec_ciks.add(str(c.identifiers["cik"]))
    return plan


# ----------------------------------------------------------------------------- run
def ensure_connector_configs(db: Session) -> None:
    for key, (name, version, cron, rate, slo) in META.items():
        if db.scalar(select(ConnectorConfig).where(ConnectorConfig.key == key)) is None:
            db.add(ConnectorConfig(key=key, display_name=name, adapter_version=version, schedule_cron=cron,
                                   rate_limit_per_sec=rate, freshness_slo_hours=slo,
                                   enabled=key not in ("corporate_feed", "conference_feed"),
                                   next_run_at=croniter(cron, datetime.now(UTC)).get_next(datetime)))
    db.flush()


def run_connector(key: str, *, trigger: str = "schedule", requested_by: str | None = None,
                  adapter: SourceAdapter | None = None, since: datetime | None = None,
                  plan: FetchPlan | None = None) -> uuid.UUID:
    """Execute one connector run end-to-end. Safe to re-run: idempotent by construction."""
    with session_scope(bypass_rls=True) as db:
        ensure_connector_configs(db)
        cfg = db.scalar(select(ConnectorConfig).where(ConnectorConfig.key == key))
        if cfg is None or (not cfg.enabled and trigger != "manual"):
            raise RuntimeError(f"connector {key} disabled or unknown")
        run = ConnectorRun(connector_key=key, adapter_version=cfg.adapter_version, trigger=trigger,
                           requested_by=requested_by, status="running")
        db.add(run)
        db.flush()
        run_id = run.id
        plan = plan or build_fetch_plan(db)
        checkpoint = dict(cfg.checkpoint or {})
        settings = dict(cfg.settings or {})
        rate = cfg.rate_limit_per_sec
    started = datetime.now(UTC)
    adapter = adapter or get_adapter(key, rate_per_sec=rate)
    ctx = FetchContext(plan=plan, checkpoint=checkpoint, settings=settings, since=since, run_id=run_id)
    stats = {"fetched": 0, "new": 0, "changed": 0, "unchanged": 0, "changes": 0, "errors": 0}
    errors: list[dict[str, Any]] = []
    fatal: str | None = None
    try:
        for fetched in adapter.fetch(ctx):
            stats["fetched"] += 1
            try:
                with session_scope(bypass_rls=True) as db:
                    for outcome in process_record(db, adapter, fetched, run_id):
                        stats[outcome.status] = stats.get(outcome.status, 0) + 1
                        stats["changes"] += len(outcome.change_ids)
                        CONNECTOR_RECORDS.labels(key, outcome.status).inc()
            except Exception as e:  # noqa: BLE001 - malformed payloads must not abort the run
                stats["errors"] += 1
                CONNECTOR_RECORDS.labels(key, "error").inc()
                errors.append({"source_object_id": fetched.source_object_id, "error": str(e)[:500],
                               "trace": traceback.format_exc(limit=3)[-1500:]})
                log.warning("record_failed", connector=key, object=fetched.source_object_id, error=str(e))
    except Exception as e:  # noqa: BLE001 - upstream outage etc.
        fatal = str(e)[:1000]
        log.error("connector_run_failed", connector=key, error=fatal)
    finally:
        adapter.close()

    with session_scope(bypass_rls=True) as db:
        run = db.get(ConnectorRun, run_id)
        cfg = db.scalar(select(ConnectorConfig).where(ConnectorConfig.key == key))
        run.finished_at = datetime.now(UTC)
        run.records_fetched = stats["fetched"]
        run.records_new = stats.get("new", 0)
        run.records_changed = stats.get("changed", 0)
        run.records_unchanged = stats.get("unchanged", 0)
        run.changes_emitted = stats["changes"]
        run.errors = stats["errors"] + (1 if fatal else 0)
        run.error_detail = errors[:50] + ([{"fatal": fatal}] if fatal else [])
        if fatal:
            run.status = "failed" if stats["fetched"] == 0 else "partial"
            run.message = fatal
        else:
            run.status = "succeeded" if stats["errors"] == 0 else "partial"
        if run.status in ("succeeded", "partial") and not fatal:
            cfg.last_success_at = run.finished_at
            cfg.checkpoint = {**adapter.next_checkpoint(ctx, started), "last_success_at": started.isoformat()}
            CONNECTOR_LAST_SUCCESS.labels(key).set(run.finished_at.timestamp())
        cfg.next_run_at = croniter(cfg.schedule_cron, datetime.now(UTC)).get_next(datetime)
        CONNECTOR_RUNS.labels(key, run.status).inc()
    return run_id


# ----------------------------------------------------------------------------- record
def store_raw(db: Session, adapter: SourceAdapter, fetched: FetchedRecord, run_id: uuid.UUID | None) -> SourceDocument:
    store = get_object_store()
    key, checksum = store.put_content_addressed(adapter.key, fetched.raw, fetched.content_type)
    existing = db.scalar(select(SourceDocument).where(SourceDocument.source == adapter.key,
                                                      SourceDocument.source_object_id == fetched.source_object_id,
                                                      SourceDocument.checksum == checksum))
    if existing:
        return existing
    doc = SourceDocument(
        source=adapter.key, source_object_id=fetched.source_object_id, uri=fetched.uri,
        content_type=fetched.content_type, checksum=checksum, storage_key=key, byte_size=len(fetched.raw),
        retrieved_at=fetched.retrieved_at, published_at=fetched.published_at,
        source_last_updated=fetched.source_last_updated, connector_key=adapter.key,
        connector_version=adapter.version, run_id=run_id, rights=adapter.rights(),
        query_provenance=fetched.query_provenance, title=fetched.title,
    )
    db.add(doc)
    db.flush()
    return doc


def process_record(db: Session, adapter: SourceAdapter, fetched: FetchedRecord,
                   run_id: uuid.UUID | None = None) -> list[RecordOutcome]:
    doc = store_raw(db, adapter, fetched, run_id)
    outcomes = []
    for rec in adapter.parse(fetched):
        outcomes.append(_process_normalized(db, adapter, doc, rec, fetched))
    return outcomes


def _process_normalized(db: Session, adapter: SourceAdapter, doc: SourceDocument, rec: NormalizedRecord,
                        fetched: FetchedRecord) -> RecordOutcome:
    resolver = EntityResolver(db)
    object_id, entity_ids = upsert_canonical(db, resolver, rec, doc)
    latest = db.scalar(select(SourceSnapshot).where(SourceSnapshot.object_type == rec.object_type,
                                                    SourceSnapshot.object_id == object_id)
                       .order_by(SourceSnapshot.version.desc()).limit(1))
    nhash = stable_hash(rec.normalized)
    if latest is not None and latest.normalized_hash == nhash:
        if rec.object_type == "trial":
            t = db.get(Trial, object_id)
            if t:
                t.last_seen_at = doc.retrieved_at
        return RecordOutcome("unchanged", object_id, snapshot_id=latest.id)

    snap = SourceSnapshot(object_type=rec.object_type, object_id=object_id, source=adapter.key,
                          source_object_id=rec.source_object_id, source_document_id=doc.id,
                          version=(latest.version + 1) if latest else 1, normalized=rec.normalized,
                          normalized_hash=nhash, retrieved_at=doc.retrieved_at,
                          source_last_updated=fetched.source_last_updated)
    db.add(snap)
    db.flush()
    if rec.object_type == "trial":
        t = db.get(Trial, object_id)
        t.current_snapshot_id = snap.id

    changes = diff_objects(rec.object_type, latest.normalized if latest else None, rec.normalized)
    change_ids = persist_changes(db, rec.object_type, object_id, adapter.key, changes,
                                 latest.id if latest else None, snap.id, doc.retrieved_at)
    index_sections(db, source_document=doc, object_type=rec.object_type, object_id=object_id, sections=rec.sections,
                   snapshot_id=snap.id, entity_ids=[object_id, *entity_ids],
                   published_at=rec.published_at or doc.published_at)
    if rec.object_type == "trial":
        update_trial_catalysts(db, object_id, rec.normalized, snap, doc)
    if rec.object_type in ("drug_application", "label"):
        _regulatory_events(db, rec, object_id, entity_ids, changes, doc)
    return RecordOutcome("new" if latest is None else "changed", object_id, change_ids, snap.id)


def persist_changes(db: Session, object_type: str, object_id: uuid.UUID, source: str, changes: list[FieldChange],
                    from_snapshot_id: uuid.UUID | None, to_snapshot_id: uuid.UUID, fetched_at: datetime) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for ch in changes:
        fp = fingerprint(object_id, ch.field, ch.old, ch.new, from_snapshot_id)
        new_id = uuid.uuid4()
        stmt = pg_insert(ChangeEvent).values(
            id=new_id, fingerprint=fp, object_type=object_type, object_id=object_id, source=source, field=ch.field,
            change_type=str(ch.change_type), secondary_tags=ch.tags, old_value=ch.old, new_value=ch.new,
            magnitude=ch.magnitude, diff_detail=ch.detail, from_snapshot_id=from_snapshot_id,
            to_snapshot_id=to_snapshot_id, suppressed=ch.suppressed, suppression_reason=ch.suppression_reason,
            source_fetched_at=fetched_at, detected_at=datetime.now(UTC), processed=ch.suppressed,
        ).on_conflict_do_nothing(index_elements=["fingerprint"]).returning(ChangeEvent.id)
        inserted = db.execute(stmt).scalar()
        if inserted:
            CHANGE_EVENTS.labels(str(ch.change_type), str(ch.suppressed).lower()).inc()
            if not ch.suppressed:
                ids.append(inserted)
    return ids


# ----------------------------------------------------------------------------- canonical upserts
def _resolve_or_create_company(db: Session, resolver: EntityResolver, name: str, context_type: str,
                               context_id: uuid.UUID) -> uuid.UUID | None:
    if not name:
        return None
    res = resolver.resolve(name, "company")
    resolver.record_link(res, context_type, context_id)
    if res.linked:
        return res.entity_id
    if res.status == "pending_review":
        return None
    comp = Company(canonical_name=name[:300], identifiers={}, status="active")
    db.add(comp)
    db.flush()
    add_alias(db, entity_type="company", entity_id=comp.id, alias=name, alias_type="canonical", source="source",
              confidence=0.95)
    resolver._cache.clear()
    return comp.id


def _resolve_concept(db: Session, resolver: EntityResolver, kind: str, name: str, context_type: str,
                     context_id: uuid.UUID, create: bool) -> uuid.UUID | None:
    if not name:
        return None
    res = resolver.resolve(name, kind)
    resolver.record_link(res, context_type, context_id)
    if res.linked:
        return res.entity_id
    if not create or res.status == "pending_review":
        return None
    c = Concept(kind=kind, canonical_name=name[:300], attributes={"provisional": True})
    db.add(c)
    db.flush()
    add_alias(db, entity_type=kind, entity_id=c.id, alias=name, alias_type="canonical", source="source", confidence=0.9)
    resolver._cache.clear()
    return c.id


def upsert_canonical(db: Session, resolver: EntityResolver, rec: NormalizedRecord,
                     doc: SourceDocument) -> tuple[uuid.UUID, list[uuid.UUID]]:
    n = rec.normalized
    linked: list[uuid.UUID] = []
    if rec.object_type == "trial":
        t = db.scalar(select(Trial).where(Trial.nct_id == n["nct_id"]))
        if t is None:
            t = Trial(id=object_uuid("trial", n["nct_id"]), nct_id=n["nct_id"], source_ids={"ctgov": n["nct_id"]},
                      title=n.get("brief_title") or n["nct_id"])
            db.add(t)
            db.flush()
        t.title = n.get("brief_title") or t.title
        t.sponsor_name = n.get("sponsor")
        t.phase, t.status, t.enrollment = n.get("phase"), n.get("status"), n.get("enrollment")
        t.start_date = partial_date_to_date(n.get("start_date"))
        t.primary_completion_date = partial_date_to_date(n.get("primary_completion_date"), end_of_period=True)
        t.completion_date = partial_date_to_date(n.get("completion_date"), end_of_period=True)
        t.current = n
        t.last_seen_at = doc.retrieved_at
        sponsor_id = None
        for m in rec.mentions:
            if m.entity_type == "company":
                cid = _resolve_or_create_company(db, resolver, m.text, "trial", t.id)
                if cid:
                    linked.append(cid)
                    upsert_edge(db, subject_type="company", subject_id=cid, predicate="sponsors", object_type="trial",
                                object_id=t.id, evidence={"source_document_id": str(doc.id), "role": m.role})
                    if m.role == "sponsor":
                        sponsor_id = cid
            elif m.entity_type == "asset":
                aid = _resolve_or_create_asset(db, resolver, m.text, m.attributes.get("other_names", []), t.id, sponsor_id)
                if aid:
                    linked.append(aid)
                    upsert_edge(db, subject_type="asset", subject_id=aid, predicate="evaluated_in", object_type="trial",
                                object_id=t.id, evidence={"source_document_id": str(doc.id)})
            elif m.entity_type == "indication":
                iid = _resolve_concept(db, resolver, "indication", m.text, "trial", t.id, create=True)
                if iid:
                    linked.append(iid)
                    upsert_edge(db, subject_type="trial", subject_id=t.id, predicate="studies",
                                object_type="indication", object_id=iid)
            elif m.entity_type == "endpoint":
                eid = _resolve_concept(db, resolver, "endpoint", m.text, "trial", t.id, create=False)
                if eid:
                    upsert_edge(db, subject_type="trial", subject_id=t.id, predicate="uses_endpoint",
                                object_type="endpoint", object_id=eid)
        t.sponsor_company_id = sponsor_id
        return t.id, linked

    if rec.object_type == "publication":
        p = db.scalar(select(Publication).where(Publication.pmid == n["pmid"]))
        if p is None:
            p = Publication(id=object_uuid("publication", n["pmid"]), pmid=n["pmid"], title=n["title"] or n["pmid"])
            db.add(p)
        p.doi, p.title, p.authors, p.journal = n.get("doi"), n.get("title") or p.title, n.get("authors"), n.get("journal")
        p.pub_date = partial_date_to_date(n.get("pub_date"))
        p.abstract = n.get("abstract")
        p.source_document_id = doc.id
        prov = list(p.query_provenance or [])
        qp = doc.query_provenance or {}
        if qp and qp not in prov:
            prov.append(qp)
        p.query_provenance = prov
        db.flush()
        for m in rec.mentions:
            if m.entity_type == "asset":
                res = resolver.resolve(m.text, "asset")
                if res.linked:
                    linked.append(res.entity_id)
                    upsert_edge(db, subject_type="publication", subject_id=p.id, predicate="mentions",
                                object_type="asset", object_id=res.entity_id)
            elif m.entity_type == "indication":
                res = resolver.resolve(m.text, "indication")
                if res.linked:
                    linked.append(res.entity_id)
            elif m.entity_type == "kol":
                kid = _resolve_concept(db, resolver, "kol", m.text, "publication", p.id, create=True)
                if kid:
                    upsert_edge(db, subject_type="kol", subject_id=kid, predicate="authored", object_type="publication",
                                object_id=p.id, evidence={"affiliation": m.attributes.get("affiliation")})
        for nct in n.get("nct_ids", []):
            t = db.scalar(select(Trial).where(Trial.nct_id == nct))
            if t:
                linked.append(t.id)
                upsert_edge(db, subject_type="publication", subject_id=p.id, predicate="mentions", object_type="trial",
                            object_id=t.id)
        return p.id, linked

    if rec.object_type in ("drug_application", "label"):
        oid = object_uuid(rec.object_type, rec.source_object_id)
        for m in rec.mentions:
            if m.entity_type == "asset":
                res = resolver.resolve(m.text, "asset")
                resolver.record_link(res, rec.object_type, oid)
                if res.linked:
                    linked.append(res.entity_id)
            elif m.entity_type == "company":
                cid = _resolve_or_create_company(db, resolver, m.text, rec.object_type, oid)
                if cid:
                    linked.append(cid)
        return oid, list(dict.fromkeys(linked))

    if rec.object_type in ("disclosure", "conference_abstract"):
        key = f"{doc.source}:{rec.source_object_id}"
        d = db.scalar(select(Disclosure).where(Disclosure.dedupe_key == key))
        company_id = None
        for m in rec.mentions:
            if m.entity_type == "company" and m.text:
                company_id = _resolve_or_create_company(db, resolver, m.text, "disclosure", object_uuid("disclosure", key))
        if d is None:
            d = Disclosure(id=object_uuid("disclosure", key), dedupe_key=key, title=n.get("title") or rec.title or key)
            db.add(d)
        d.company_id = company_id
        d.form_type = n.get("form") or ("CONFERENCE_ABSTRACT" if rec.object_type == "conference_abstract" else None)
        d.url = n.get("url") or n.get("link")
        d.published_at = rec.published_at or parse_datetime(n.get("filing_date"))
        d.source_document_id = doc.id
        db.flush()
        if company_id:
            linked.append(company_id)
            upsert_edge(db, subject_type="company", subject_id=company_id, predicate="disclosed",
                        object_type="disclosure", object_id=d.id)
        return d.id, linked
    raise ValueError(f"unsupported object_type {rec.object_type}")


def _resolve_or_create_asset(db: Session, resolver: EntityResolver, name: str, other_names: list[str],
                             trial_id: uuid.UUID, sponsor_id: uuid.UUID | None) -> uuid.UUID | None:
    for candidate in [name, *other_names]:
        res = resolver.resolve(candidate, "asset")
        resolver.record_link(res, "trial", trial_id)
        if res.linked:
            for alias in [name, *other_names]:
                if alias != candidate:
                    add_alias(db, entity_type="asset", entity_id=res.entity_id, alias=alias, source="source",
                              confidence=0.9)
            return res.entity_id
        if res.status == "pending_review":
            return None
    # New entrant: provisional public asset; analysts can merge/approve (FR-ENT-005).
    a = Asset(canonical_name=name[:300], owner_company_id=sponsor_id, status="provisional",
              profile={"source": "ctgov_intervention"})
    db.add(a)
    db.flush()
    add_alias(db, entity_type="asset", entity_id=a.id, alias=name, alias_type="canonical", source="source", confidence=0.9)
    for alt in other_names:
        add_alias(db, entity_type="asset", entity_id=a.id, alias=alt, source="source", confidence=0.85)
    if sponsor_id:
        upsert_edge(db, subject_type="company", subject_id=sponsor_id, predicate="develops", object_type="asset",
                    object_id=a.id, confidence=0.6, method="sponsor_inference", status="proposed")
    resolver._cache.clear()
    return a.id


def _regulatory_events(db: Session, rec: NormalizedRecord, object_id: uuid.UUID, entity_ids: list[uuid.UUID],
                       changes: list[FieldChange], doc: SourceDocument) -> None:
    asset_id = next((e for e in entity_ids if db.get(Asset, e) is not None), None)
    n = rec.normalized
    for ch in changes:
        if ch.suppressed and ch.suppression_reason != "baseline_historical":
            continue
        if rec.object_type == "drug_application":
            s = ch.new or {}
            key = f"FDA:{n.get('application_number')}:{s.get('submission_type')}-{s.get('submission_number')}"
            etype = str(ch.change_type)
            product = ", ".join(n.get("brand_names") or n.get("generic_names") or [n.get("application_number")])
            edate = partial_date_to_date(s.get("status_date"))
            details = {"submission": s, "application_number": n.get("application_number"), "sponsor": n.get("sponsor")}
        else:
            key = f"FDA-LABEL:{n.get('set_id')}:{n.get('version')}:{ch.field}"
            etype = "LABEL_CHANGED"
            product = ", ".join(n.get("brand_names") or n.get("generic_names") or [])
            edate = partial_date_to_date(n.get("effective_date"))
            details = {"section": ch.magnitude.get("section"), "set_id": n.get("set_id"), "version": n.get("version")}
        stmt = pg_insert(RegulatoryEvent).values(
            id=uuid.uuid4(), dedupe_key=key[:200], agency="FDA", event_type=etype, product_name=product[:300] or "unknown",
            application_number=n.get("application_number") or (n.get("application_numbers") or [None])[0],
            asset_id=asset_id, event_date=edate, details=details, source_document_id=doc.id,
        ).on_conflict_do_nothing(index_elements=["dedupe_key"])
        db.execute(stmt)
        if asset_id:
            reg = db.scalar(select(RegulatoryEvent).where(RegulatoryEvent.dedupe_key == key[:200]))
            if reg:
                upsert_edge(db, subject_type="asset", subject_id=asset_id, predicate="received_regulatory_event",
                            object_type="regulatory_event", object_id=reg.id)


# ----------------------------------------------------------------------------- catalysts
def update_trial_catalysts(db: Session, trial_id: uuid.UUID, n: dict[str, Any], snap: SourceSnapshot,
                           doc: SourceDocument) -> None:
    """Sourced completion catalysts + a model-inferred readout window, clearly labelled (FR-UX-005)."""
    t = db.get(Trial, trial_id)
    assets = [db.get(Asset, a) for a in neighbours(db, trial_id, predicate="evaluated_in", direction="in")]
    assets = [a for a in assets if a is not None]
    confirmed = [a for a in assets if a.status != "provisional"]
    asset_id = (confirmed or assets or [None])[0]
    asset_id = asset_id.id if asset_id is not None else None
    specs = [("PRIMARY_COMPLETION", "primary_completion_date", "Primary completion"),
             ("STUDY_COMPLETION", "completion_date", "Study completion")]
    for kind, fld, label in specs:
        raw = n.get(fld)
        d = partial_date_to_date(raw, end_of_period=True)
        if d is None:
            continue
        precision = "day" if raw and len(raw) == 10 else "month"
        anticipated = (n.get("primary_completion_date_type") or "").upper() == "ANTICIPATED"
        _upsert_catalyst(db, f"trial:{trial_id}:{kind}", kind=kind,
                         title=f"{label}: {t.nct_id} ({(n.get('acronym') or t.title)[:80]})",
                         trial_id=trial_id, asset_id=asset_id, company_id=t.sponsor_company_id, expected=d,
                         basis="SOURCED", precision=precision,
                         confidence="Verified" if not anticipated or kind != "PRIMARY_COMPLETION" else "High",
                         evidence={"snapshot_id": str(snap.id), "source_document_id": str(doc.id), "field": fld,
                                   "value": raw, "anticipated": anticipated, "uri": doc.uri},
                         source_document_id=doc.id, changed_at=snap.retrieved_at)
    pcd = partial_date_to_date(n.get("primary_completion_date"), end_of_period=True)
    if pcd and any(p in (n.get("phase") or "") for p in ("2", "3")):
        ws, we = pcd + timedelta(days=90), pcd + timedelta(days=270)
        _upsert_catalyst(db, f"trial:{trial_id}:TOPLINE_READOUT", kind="TOPLINE_READOUT",
                         title=f"Expected topline readout window: {t.nct_id}", trial_id=trial_id, asset_id=asset_id,
                         company_id=t.sponsor_company_id, expected=None, window=(ws, we), basis="INFERRED",
                         precision="quarter", confidence="Low",
                         evidence={"method": "primary completion + 3-9 months heuristic", "snapshot_id": str(snap.id),
                                   "based_on": n.get("primary_completion_date")},
                         source_document_id=doc.id, changed_at=snap.retrieved_at)


def _upsert_catalyst(db: Session, key: str, *, kind: str, title: str, trial_id: uuid.UUID | None,
                     asset_id: uuid.UUID | None, company_id: uuid.UUID | None, expected: date | None,
                     basis: str, precision: str, confidence: str, evidence: dict, source_document_id: uuid.UUID,
                     changed_at: datetime, window: tuple[date, date] | None = None) -> Catalyst:
    c = db.scalar(select(Catalyst).where(Catalyst.dedupe_key == key))
    today = datetime.now(UTC).date()
    if c is None:
        c = Catalyst(dedupe_key=key, event_type=kind, title=title, history=[])
        db.add(c)
    elif (c.expected_date, c.window_start, c.window_end) != (expected, window[0] if window else None,
                                                             window[1] if window else None):
        c.history = [*(c.history or []), {"expected_date": c.expected_date.isoformat() if c.expected_date else None,
                                          "window_start": c.window_start.isoformat() if c.window_start else None,
                                          "window_end": c.window_end.isoformat() if c.window_end else None,
                                          "replaced_at": changed_at.isoformat()}]
    c.title, c.trial_id, c.asset_id, c.company_id = title, trial_id, asset_id, company_id
    c.expected_date = expected
    c.window_start, c.window_end = (window if window else (None, None))
    c.date_basis, c.date_precision, c.confidence = basis, precision, confidence
    c.evidence, c.source_document_id = evidence, source_document_id
    ref = expected or (window[1] if window else None)
    c.status = "past" if ref and ref < today else "upcoming"
    db.flush()
    return c
