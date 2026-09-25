"""Intelligence pipeline (Section 5.1 / Section 16 steps 5-11).

For each group of new ChangeEvents (one object, one snapshot transition) and each active landscape:
dedupe -> relevance -> impact mapping (graph path) -> materiality score -> intelligence event ->
evidence retrieval + bounded interpretation -> evidence validation -> publication -> alerting.
Idempotent: the intelligence-event fingerprint is derived from the change fingerprints + landscape.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.agents.impact import generate_narrative
from app.alerts.dispatcher import dispatch_immediate
from app.changes.taxonomy import primary_of
from app.core.crypto import stable_hash
from app.core.logging import get_logger
from app.core.metrics import INTEL_EVENTS, PIPELINE_LATENCY
from app.db.session import session_scope, set_tenant
from app.entities.graph import neighbours, upsert_edge
from app.entities.resolver import EntityResolver
from app.materiality.mapping import ObjectScope, landscape_relevance, map_impacts
from app.materiality.scoring import ChangeInput, ScoringContext, catalyst_from_trial, score_event
from app.models import (
    Asset,
    ChangeEvent,
    Company,
    Concept,
    Disclosure,
    EntityLink,
    Feedback,
    IntelligenceEvent,
    Landscape,
    Publication,
    SourceSnapshot,
    Trial,
)

log = get_logger(__name__)
NARRATIVE_MIN_BAND_SCORE = 30.0  # Feed and above get a validated narrative
LLM_MIN_SCORE = 50.0  # Analyst Review and above use the LLM (cost control); below: deterministic


def _scope(db: Session, object_type: str, object_id: uuid.UUID, snapshot: SourceSnapshot | None) -> ObjectScope:
    sc = ObjectScope(object_type=object_type, object_id=object_id)
    if object_type == "trial":
        sc.asset_ids = neighbours(db, object_id, predicate="evaluated_in", direction="in")
        sc.company_ids = neighbours(db, object_id, predicate="sponsors", direction="in")
        sc.indication_names = [c.canonical_name for c in (db.get(Concept, i) for i in
                               neighbours(db, object_id, predicate="studies")) if c]
        sc.trial_normalized = snapshot.normalized if snapshot else (db.get(Trial, object_id).current or {})
        if sc.trial_normalized:
            sc.indication_names += sc.trial_normalized.get("conditions", [])
    elif object_type == "publication":
        sc.asset_ids = [a for a in neighbours(db, object_id, predicate="mentions") if db.get(Asset, a)]
        trials = [t for t in neighbours(db, object_id, predicate="mentions") if db.get(Trial, t)]
        for t in trials:
            sc.asset_ids += neighbours(db, t, predicate="evaluated_in", direction="in")
        p = db.get(Publication, object_id)
        sc.indication_names = (snapshot.normalized.get("mesh_terms", []) if snapshot else []) + ([p.title] if p else [])
    elif object_type in ("disclosure", "conference_abstract"):
        d = db.get(Disclosure, object_id)
        if d and d.company_id:
            sc.company_ids = [d.company_id]
            sc.asset_ids = neighbours(db, d.company_id, predicate="develops")
        sc.indication_names = [d.title] if d else []
    elif object_type in ("drug_application", "label"):
        links = db.scalars(select(EntityLink).where(EntityLink.context_id == object_id,
                                                    EntityLink.entity_type == "asset",
                                                    EntityLink.status.in_(("auto_linked", "approved")))).all()
        sc.asset_ids = list({lk.entity_id for lk in links if lk.entity_id})
        if snapshot:
            sc.indication_names = [snapshot.normalized.get("sections", {}).get("indications_and_usage", "")[:300]]
    sc.asset_ids = list(dict.fromkeys(sc.asset_ids))
    confs = db.scalars(select(EntityLink.confidence).where(EntityLink.context_id == object_id,
                                                           EntityLink.status.in_(("auto_linked", "approved")))).all()
    sc.min_link_confidence = min(confs) if confs else 1.0
    return sc


def _tenant_reresolve(db: Session, tenant_id: uuid.UUID, scope: ObjectScope) -> None:
    """Apply tenant-private aliases/corrections to mentions the global pass could not link (FR-ENT-005)."""
    pending = db.scalars(select(EntityLink).where(EntityLink.context_id == scope.object_id,
                                                  EntityLink.tenant_id.is_(None),
                                                  EntityLink.status.in_(("unresolved", "pending_review")),
                                                  EntityLink.entity_type == "asset")).all()
    if not pending:
        return
    resolver = EntityResolver(db, tenant_id)
    for lk in pending:
        res = resolver.resolve(lk.mention, "asset")
        if res.linked and res.entity_id not in scope.asset_ids:
            resolver.record_link(res, lk.context_type, lk.context_id)
            scope.asset_ids.append(res.entity_id)
            if scope.object_type == "trial":
                upsert_edge(db, subject_type="asset", subject_id=res.entity_id, predicate="evaluated_in",
                            object_type="trial", object_id=scope.object_id, tenant_id=tenant_id,
                            confidence=res.confidence, method=f"tenant_{res.method}")


def _title(db: Session, object_type: str, object_id: uuid.UUID, changes: list[ChangeEvent]) -> tuple[str, uuid.UUID | None]:
    company_id = None
    if object_type == "trial":
        t = db.get(Trial, object_id)
        company_id = t.sponsor_company_id if t else None
        sponsor = t.sponsor_name if t else "Sponsor"
        parts = []
        for c in sorted(changes, key=lambda c: c.field):
            if c.field == "enrollment":
                parts.append(f"enrollment {c.old_value}→{c.new_value}")
            elif c.field in ("primary_completion_date", "completion_date", "start_date"):
                parts.append(f"{c.field.replace('_date', '').replace('_', ' ')} {c.old_value}→{c.new_value}")
            elif c.field == "primary_endpoints":
                old = ", ".join(x.get("measure", "") for x in (c.old_value or []))
                new = ", ".join(x.get("measure", "") for x in (c.new_value or []))
                parts.append(f"primary endpoint {old[:60]}→{new[:60]}")
            elif c.field == "status":
                parts.append(f"status {c.old_value}→{c.new_value}")
            elif c.field == "trial":
                parts.append("new trial registered")
            else:
                parts.append(c.change_type.replace("_", " ").lower())
        phase = f" {t.phase}" if t and t.phase else ""
        return f"{sponsor}{phase} trial {t.nct_id if t else ''}: {'; '.join(dict.fromkeys(parts))}", company_id
    if object_type == "publication":
        p = db.get(Publication, object_id)
        return f"New publication: {(p.title if p else '')[:160]}", None
    if object_type in ("disclosure", "conference_abstract"):
        d = db.get(Disclosure, object_id)
        if d and d.company_id:
            comp = db.get(Company, d.company_id)
            return f"{comp.canonical_name if comp else ''} {d.form_type or ''}: {d.title[:150]}", d.company_id
        return f"Disclosure: {d.title[:160] if d else ''}", None
    snap = db.get(SourceSnapshot, changes[0].to_snapshot_id)
    names = ", ".join((snap.normalized.get("brand_names") or snap.normalized.get("generic_names") or [])[:2]) if snap else ""
    kinds = ", ".join(sorted({c.change_type.replace("_", " ").lower() for c in changes}))
    return f"FDA {kinds}: {names or 'product'}", None


def _prior_similar(db: Session, tenant_id: uuid.UUID, object_id: uuid.UUID, primary: str, before: datetime) -> int:
    return db.scalar(select(func.count()).select_from(IntelligenceEvent).where(
        IntelligenceEvent.tenant_id == tenant_id, IntelligenceEvent.object_id == object_id,
        IntelligenceEvent.primary_type == primary, IntelligenceEvent.detected_at >= before - timedelta(days=90),
        IntelligenceEvent.detected_at < before)) or 0


def _already_known(db: Session, tenant_id: uuid.UUID, object_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Feedback).join(
        IntelligenceEvent, IntelligenceEvent.id == Feedback.intel_event_id).where(
        Feedback.tenant_id == tenant_id, Feedback.label == "ALREADY_KNOWN", IntelligenceEvent.object_id == object_id)) or 0


def _facets(db: Session, scope: ObjectScope, source: str, primary: str) -> list[str]:
    from app.entities.resolver import normalize_alias

    terms = {f"source:{source}", f"type:{primary}"}
    for name in scope.indication_names[:10]:
        if name and len(name) < 150:
            terms.add(f"indication:{normalize_alias(name)}")
    for aid in scope.asset_ids:
        a = db.get(Asset, aid)
        if a is None:
            continue
        mech = (a.profile or {}).get("mechanism")
        if mech:
            terms.add(f"mechanism:{normalize_alias(str(mech))}")
        for t in (a.profile or {}).get("targets") or []:
            terms.add(f"target:{normalize_alias(str(t))}")
    for cid in scope.company_ids:
        c = db.get(Company, cid)
        if c:
            terms.add(f"company:{normalize_alias(c.canonical_name)}")
    return sorted(t[:200] for t in terms)


def process_group(db: Session, changes: list[ChangeEvent], *, use_llm: bool = True) -> list[uuid.UUID]:
    """Create/score/publish intelligence events for one change group across all tenants' landscapes."""
    first = changes[0]
    snapshot = db.get(SourceSnapshot, first.to_snapshot_id)
    base_scope = _scope(db, first.object_type, first.object_id, snapshot)
    types = [c.change_type for c in changes]
    primary = primary_of(types)
    tags = sorted({t for t in types if t != primary} | {tag for c in changes for tag in (c.secondary_tags or [])})
    title, company_id = _title(db, first.object_type, first.object_id, changes)
    created: list[uuid.UUID] = []

    for ls in db.scalars(select(Landscape).where(Landscape.status == "active")).all():
        set_tenant(db, ls.tenant_id, bypass_rls=False)
        try:
            scope = ObjectScope(**{**base_scope.__dict__, "asset_ids": list(base_scope.asset_ids)})
            _tenant_reresolve(db, ls.tenant_id, scope)
            relevance = landscape_relevance(db, ls, scope)
            impacts, rule_ref = map_impacts(db, ls.tenant_id, ls, scope)
            if relevance == "peripheral" and not impacts:
                continue
            fp = stable_hash(["intel", str(ls.id), sorted(c.fingerprint for c in changes)])
            if db.scalar(select(IntelligenceEvent.id).where(IntelligenceEvent.tenant_id == ls.tenant_id,
                                                           IntelligenceEvent.fingerprint == fp)):
                continue
            cfg = ls.config or {}
            cat_date, cat_kind = catalyst_from_trial(snapshot.normalized) if first.object_type == "trial" and snapshot else (None, None)
            now = datetime.now(UTC)
            ctx = ScoringContext(
                changes=[ChangeInput(c.change_type, c.field, c.secondary_tags or [], c.magnitude or {}, c.old_value,
                                     c.new_value) for c in changes],
                relevance_level=relevance,
                max_proximity=max((m.proximity for m in impacts), default=0.0),
                catalyst_date=cat_date, catalyst_kind=cat_kind, object_type=first.object_type,
                phase=(snapshot.normalized.get("phase") if snapshot and first.object_type == "trial" else None),
                prior_similar_events=_prior_similar(db, ls.tenant_id, first.object_id, primary, now),
                already_known_feedback=_already_known(db, ls.tenant_id, first.object_id),
                mapping_confidence=base_scope.min_link_confidence,
            )
            result = score_event(ctx, cfg.get("materiality_weights"), cfg.get("band_thresholds"))
            result.components["proximity_rule"] = rule_ref
            asset_id = scope.asset_ids[0] if scope.asset_ids else None
            facets = _facets(db, scope, first.source, primary)
            ev = IntelligenceEvent(
                facet_terms=facets,
                tenant_id=ls.tenant_id, fingerprint=fp, landscape_id=ls.id, object_type=first.object_type,
                object_id=first.object_id, source=first.source, primary_type=primary, secondary_tags=tags,
                title=title[:500], change_ids=[c.id for c in changes],
                related_entity_ids=list(dict.fromkeys([*scope.asset_ids, *scope.company_ids])),
                company_id=company_id or (scope.company_ids[0] if scope.company_ids else None), asset_id=asset_id,
                impacted_asset_ids=[m.asset_id for m in impacts], impacted_assets=[m.to_dict() for m in impacts],
                materiality_score=result.score, band=result.band, score_components=result.components,
                status="pending_validation", occurred_at=snapshot.retrieved_at if snapshot else None,
                source_fetched_at=first.source_fetched_at, detected_at=first.detected_at, scored_at=now,
            )
            db.add(ev)
            db.flush()
            INTEL_EVENTS.labels(result.band).inc()
            PIPELINE_LATENCY.labels("source_fetch_to_score").observe((now - first.source_fetched_at).total_seconds())
            publish_event(db, ev, use_llm=use_llm)
            created.append(ev.id)
        finally:
            if db.is_active:
                set_tenant(db, None, bypass_rls=True)
    return created


def publish_event(db: Session, ev: IntelligenceEvent, *, use_llm: bool = True) -> None:
    if ev.materiality_score < NARRATIVE_MIN_BAND_SCORE:
        ev.status = "archived"
        return
    art, report = generate_narrative(db, ev.tenant_id, ev, use_llm=use_llm and ev.materiality_score >= LLM_MIN_SCORE)
    ev.current_narrative_id = art.id
    if not report.publishable:
        ev.publication_blocked_reason = "; ".join(report.blocked_reasons)[:2000]
    ev.status = "published" if art.publishable else "blocked"
    ev.published_at = datetime.now(UTC) if art.publishable else None
    db.flush()
    if ev.status == "published":
        dispatch_immediate(db, ev)


def process_pending_changes(limit_groups: int = 200, *, use_llm: bool = True) -> dict[str, Any]:
    stats = {"groups": 0, "events": 0, "errors": 0}
    with session_scope(bypass_rls=True) as db:
        rows = db.scalars(select(ChangeEvent).where(ChangeEvent.processed.is_(False), ChangeEvent.suppressed.is_(False))
                          .order_by(ChangeEvent.detected_at).limit(limit_groups * 10)).all()
        groups: dict[tuple, list[uuid.UUID]] = defaultdict(list)
        for c in rows:
            groups[(c.object_type, c.object_id, c.to_snapshot_id)].append(c.id)
    for _key, ids in list(groups.items())[:limit_groups]:
        try:
            with session_scope(bypass_rls=True) as db:
                changes = list(db.scalars(select(ChangeEvent).where(ChangeEvent.id.in_(ids))
                                          .with_for_update(skip_locked=True)).all())
                changes = [c for c in changes if not c.processed]
                if not changes:
                    continue
                created = process_group(db, changes, use_llm=use_llm)
                for c in changes:
                    c.processed = True
                stats["groups"] += 1
                stats["events"] += len(created)
        except Exception as e:  # noqa: BLE001 - isolate failing groups; they are retried next cycle
            stats["errors"] += 1
            log.exception("intel_group_failed", error=str(e))
    return stats
