"""/admin: connectors, users/roles, proximity rules, model/workflow governance, settings, usage, retention;
/audit: authorized search/export/verification (FR-SRC-007, FR-LND-004, NFR-AUD-001, NFR-AI-001, NFR-PRV-001)."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from croniter import croniter
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.prompts import all_prompts
from app.api.deps import Page, get_db, page_params, paged, require
from app.api.serialize import row, rows
from app.connectors.registry import available_connectors
from app.core.config import get_settings
from app.core.crypto import hash_password
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.rbac import ALL_ROLES, ROLE_PERMISSIONS, Perm
from app.core.security import Principal
from app.db.session import session_scope
from app.materiality.mapping import asset_features
from app.materiality.proximity import DEFAULT_WEIGHTS, DIMENSIONS, proximity
from app.models import (
    Asset,
    AuditLog,
    ConnectorConfig,
    ConnectorRun,
    GenerationRecord,
    LandscapeMember,
    ProximityRule,
    Tenant,
    UsageRecord,
    User,
)
from app.services import audit
from app.services.health import connector_health

router = APIRouter(tags=["admin"])


# ------------------------------------------------------------------ connectors
@router.get("/admin/connectors")
def connectors(p: Principal = Depends(require(Perm.SOURCE_READ))) -> list[dict]:
    with session_scope(bypass_rls=True) as db:  # connector state is platform-level, read-only here
        return connector_health(db)


class ConnectorPatch(BaseModel):
    enabled: bool | None = None
    schedule_cron: str | None = None
    rate_limit_per_sec: float | None = Field(None, gt=0, le=20)
    freshness_slo_hours: int | None = Field(None, ge=1, le=24 * 30)
    settings: dict[str, Any] | None = None


@router.patch("/admin/connectors/{key}")
def patch_connector(key: str, body: ConnectorPatch, p: Principal = Depends(require(Perm.PLATFORM_ADMIN))) -> dict:
    if body.schedule_cron and not croniter.is_valid(body.schedule_cron):
        raise ValidationFailed("invalid cron expression")
    with session_scope(bypass_rls=True) as db:
        c = db.scalar(select(ConnectorConfig).where(ConnectorConfig.key == key))
        if c is None:
            raise NotFound("connector not found")
        before = row(c)
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(c, k, v)
        if body.schedule_cron:
            c.next_run_at = croniter(c.schedule_cron, datetime.now(UTC)).get_next(datetime)
        c.updated_by = p.actor
        audit.record(db, action="connector.update", resource_type="connector", resource_id=key, tenant_id=None,
                     actor_id=p.actor, before=before, after=row(c))
        return row(c)


@router.post("/admin/connectors/{key}/run", status_code=202)
def run_connector_now(key: str, p: Principal = Depends(require(Perm.CONNECTOR_ADMIN))) -> dict:
    """On-demand refresh (FR-SRC-007). Enqueued; progress visible in run history."""
    if key not in available_connectors():
        raise NotFound("connector not found")
    from app.workers.tasks import run_connector_task

    with session_scope(bypass_rls=True) as db:
        running = db.scalar(select(ConnectorRun).where(ConnectorRun.connector_key == key, ConnectorRun.status == "running",
                                                       ConnectorRun.started_at >= datetime.now(UTC) - timedelta(hours=2)))
        if running:
            raise Conflict("a run is already in progress")
        audit.record(db, action="connector.run", resource_type="connector", resource_id=key, tenant_id=p.tenant_id,
                     actor_id=p.actor)
    res = run_connector_task.apply_async(args=[key], kwargs={"trigger": "manual", "requested_by": p.actor}, queue="ingest")
    return {"queued": True, "task_id": res.id}


@router.get("/admin/connectors/{key}/runs")
def connector_runs(key: str, page: Page = Depends(page_params), p: Principal = Depends(require(Perm.SOURCE_READ))) -> dict:
    with session_scope(bypass_rls=True) as db:
        stmt = select(ConnectorRun).where(ConnectorRun.connector_key == key)
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        items = db.scalars(stmt.order_by(ConnectorRun.started_at.desc()).limit(page.limit).offset(page.offset)).all()
        out = rows(items)
        if not p.has(Perm.PLATFORM_ADMIN):
            # Run params/errors reference records fetched for every tenant's landscapes: counts only.
            for r in out:
                r["error_detail"] = [{"error": (e.get("error") or e.get("fatal") or "")[:200]} for e in r["error_detail"]]
                r["params"] = {}
        return paged(out, total, page)


# ------------------------------------------------------------------ users
class UserIn(BaseModel):
    email: EmailStr
    display_name: str
    roles: list[str] = Field(default_factory=lambda: ["viewer"])
    team: str | None = None
    password: str | None = Field(None, min_length=12)


@router.get("/admin/users")
def users(p: Principal = Depends(require(Perm.USER_ADMIN)), db: Session = Depends(get_db)) -> list[dict]:
    return rows(db.scalars(select(User).where(User.tenant_id == p.tenant_id).order_by(User.email)).all())


@router.post("/admin/users", status_code=201)
def create_user(body: UserIn, p: Principal = Depends(require(Perm.USER_ADMIN)), db: Session = Depends(get_db)) -> dict:
    bad = [r for r in body.roles if r not in ALL_ROLES or r == "platform_admin"]
    if bad:
        raise ValidationFailed(f"invalid roles {bad}")
    if db.scalar(select(User).where(User.tenant_id == p.tenant_id, User.email == body.email.lower())):
        raise Conflict("user exists")
    u = User(tenant_id=p.tenant_id, email=body.email.lower(), display_name=body.display_name, roles=body.roles,
             team=body.team, password_hash=hash_password(body.password) if body.password else None)
    db.add(u)
    db.flush()
    audit.record(db, action="user.create", resource_type="user", resource_id=u.id, tenant_id=p.tenant_id, actor_id=p.actor,
                 after=row(u))
    return row(u)


class UserPatch(BaseModel):
    roles: list[str] | None = None
    team: str | None = None
    is_active: bool | None = None
    display_name: str | None = None


@router.patch("/admin/users/{user_id}")
def patch_user(user_id: uuid.UUID, body: UserPatch, p: Principal = Depends(require(Perm.USER_ADMIN)),
               db: Session = Depends(get_db)) -> dict:
    u = db.get(User, user_id)
    if u is None or u.tenant_id != p.tenant_id:
        raise NotFound("user not found")
    if body.roles is not None and any(r not in ALL_ROLES or r == "platform_admin" for r in body.roles):
        raise ValidationFailed("invalid roles")
    if u.id == p.user_id and body.is_active is False:
        raise ValidationFailed("cannot deactivate yourself")
    before = row(u)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(u, k, v)
    audit.record(db, action="user.update", resource_type="user", resource_id=u.id, tenant_id=p.tenant_id, actor_id=p.actor,
                 before=before, after=row(u))
    return row(u)


@router.get("/admin/roles")
def roles(p: Principal = Depends(require(Perm.USER_ADMIN))) -> dict:
    return {r: sorted(x.value for x in perms) for r, perms in ROLE_PERMISSIONS.items()}


# ------------------------------------------------------------------ proximity rules (FR-LND-004)
class RuleIn(BaseModel):
    name: str
    landscape_id: uuid.UUID | None = None
    weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    min_proximity: float = Field(0.35, ge=0, le=1)


@router.get("/admin/proximity-rules")
def list_rules(p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> list[dict]:
    return rows(db.scalars(select(ProximityRule).where(ProximityRule.tenant_id == p.tenant_id)
                           .order_by(ProximityRule.created_at.desc())).all())


@router.post("/admin/proximity-rules", status_code=201)
def create_rule(body: RuleIn, p: Principal = Depends(require(Perm.CONFIG_ADMIN)), db: Session = Depends(get_db)) -> dict:
    bad = [k for k in body.weights if k not in DIMENSIONS]
    if bad or any(v < 0 for v in body.weights.values()) or sum(body.weights.values()) <= 0:
        raise ValidationFailed(f"weights must use dimensions {list(DIMENSIONS)} with non-negative values")
    version = (db.scalar(select(func.max(ProximityRule.version)).where(ProximityRule.tenant_id == p.tenant_id,
                                                                       ProximityRule.name == body.name)) or 0) + 1
    r = ProximityRule(tenant_id=p.tenant_id, landscape_id=body.landscape_id, name=body.name, weights=body.weights,
                      min_proximity=body.min_proximity, status="draft", version=version, created_by=p.actor)
    db.add(r)
    db.flush()
    audit.record(db, action="proximity_rule.create", resource_type="proximity_rule", resource_id=r.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, after=row(r))
    return row(r)


class RuleTestIn(BaseModel):
    customer_asset_ids: list[uuid.UUID] = Field(default_factory=list)
    competitor_asset_ids: list[uuid.UUID] = Field(default_factory=list)


@router.post("/admin/proximity-rules/{rule_id}/test")
def test_rule(rule_id: uuid.UUID, body: RuleTestIn, p: Principal = Depends(require(Perm.CONFIG_ADMIN)),
              db: Session = Depends(get_db)) -> dict:
    """Evaluate a draft rule against sample assets before activation (FR-LND-004 acceptance)."""
    r = db.get(ProximityRule, rule_id)
    if r is None:
        raise NotFound("rule not found")
    cust, comp = body.customer_asset_ids, body.competitor_asset_ids
    if r.landscape_id and not (cust and comp):
        ms = db.scalars(select(LandscapeMember).where(LandscapeMember.landscape_id == r.landscape_id,
                                                      LandscapeMember.entity_type == "asset")).all()
        cust = cust or [m.entity_id for m in ms if m.role == "customer"]
        comp = comp or [m.entity_id for m in ms if m.role != "customer"]
    results = []
    for c in cust:
        ca = db.get(Asset, c)
        if ca is None:
            continue
        cf = asset_features(db, ca)
        for o in comp:
            oa = db.get(Asset, o)
            if oa is None or oa.id == ca.id:
                continue
            pr = proximity(cf, asset_features(db, oa), r.weights)
            results.append({"customer": ca.canonical_name, "competitor": oa.canonical_name, **pr.to_dict(),
                            "mapped": pr.score >= r.min_proximity})
    results.sort(key=lambda x: -x["score"])
    r.test_results = {"tested_at": datetime.now(UTC).isoformat(), "tested_by": p.actor, "pairs": results[:200]}
    return r.test_results


@router.post("/admin/proximity-rules/{rule_id}/activate")
def activate_rule(rule_id: uuid.UUID, p: Principal = Depends(require(Perm.CONFIG_ADMIN)), db: Session = Depends(get_db)) -> dict:
    r = db.get(ProximityRule, rule_id)
    if r is None:
        raise NotFound("rule not found")
    if not (r.test_results or {}).get("tested_at"):
        raise ValidationFailed("rule must be tested against sample assets before activation")
    for other in db.scalars(select(ProximityRule).where(ProximityRule.tenant_id == p.tenant_id,
                                                        ProximityRule.landscape_id == r.landscape_id,
                                                        ProximityRule.status == "active")).all():
        other.status = "retired"
    r.status, r.activated_at = "active", datetime.now(UTC)
    audit.record(db, action="proximity_rule.activate", resource_type="proximity_rule", resource_id=r.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, after=row(r))
    return row(r)


# ------------------------------------------------------------------ model / workflow governance (NFR-AI-001)
@router.get("/admin/models")
def models(p: Principal = Depends(require(Perm.CONFIG_ADMIN)), db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    since = datetime.now(UTC) - timedelta(days=30)
    stats = db.execute(select(GenerationRecord.workflow, GenerationRecord.served_model, GenerationRecord.status,
                              func.count(), func.avg(GenerationRecord.latency_ms), func.sum(GenerationRecord.cost_usd))
                       .where(GenerationRecord.tenant_id == p.tenant_id, GenerationRecord.created_at >= since)
                       .group_by(GenerationRecord.workflow, GenerationRecord.served_model, GenerationRecord.status)).all()
    return {
        "config": {"provider": s.llm_provider, "model": s.llm_model, "validator_model": s.llm_validator_model,
                   "effort": s.llm_effort, "validator_effort": s.llm_validator_effort,
                   "server_side_fallback": s.llm_server_side_fallback, "embedding_provider": s.embedding_provider,
                   "embedding_model": s.embedding_model if s.embedding_provider == "voyage" else f"hashing-v1-{s.embedding_dim}",
                   "rerank_enabled": s.rerank_enabled, "training_on_customer_data": False},
        "prompts": [{"id": x.id, "version": x.version, "hash": x.hash} for x in all_prompts()],
        "usage_30d": [{"workflow": w, "model": m, "status": st, "calls": n, "avg_latency_ms": round(float(lat or 0)),
                       "cost_usd": round(float(cost or 0), 4)} for w, m, st, n, lat, cost in stats],
    }


@router.get("/admin/generations/{generation_id}")
def generation(generation_id: uuid.UUID, p: Principal = Depends(require(Perm.AUDIT_READ)), db: Session = Depends(get_db)) -> dict:
    """Trace a generated artifact to its full generation configuration (NFR-AI-001 acceptance)."""
    g = db.get(GenerationRecord, generation_id)
    if g is None:
        raise NotFound("generation not found")
    return row(g)


# ------------------------------------------------------------------ tenant settings / usage / retention
class SettingsPatch(BaseModel):
    llm_monthly_budget_usd: float | None = Field(None, ge=0)
    retention_days: dict[Literal["ask_sessions", "notifications", "generation_records", "usage_records",
                                 "feedback"], int] | None = None


@router.get("/admin/settings")
def get_tenant_settings(p: Principal = Depends(require(Perm.CONFIG_ADMIN)), db: Session = Depends(get_db)) -> dict:
    t = db.get(Tenant, p.tenant_id)
    return {"tenant": row(t), "allow_training_on_customer_data": False}


@router.patch("/admin/settings")
def patch_tenant_settings(body: SettingsPatch, p: Principal = Depends(require(Perm.CONFIG_ADMIN)),
                          db: Session = Depends(get_db)) -> dict:
    with session_scope(bypass_rls=True) as sdb:
        t = sdb.get(Tenant, p.tenant_id)
        before = dict(t.settings or {})
        new = dict(before)
        if body.llm_monthly_budget_usd is not None:
            new["llm_monthly_budget_usd"] = body.llm_monthly_budget_usd
        if body.retention_days is not None:
            if any(v < 7 for v in body.retention_days.values()):
                raise ValidationFailed("retention must be at least 7 days")
            new["retention_days"] = {**(before.get("retention_days") or {}), **body.retention_days}
        t.settings = new
        audit.record(sdb, action="tenant.settings_update", resource_type="tenant", resource_id=t.id, tenant_id=t.id,
                     actor_id=p.actor, before=before, after=new)
        return row(t)


@router.get("/admin/usage")
def usage(days: int = Query(30, ge=1, le=365), p: Principal = Depends(require(Perm.CONFIG_ADMIN)),
          db: Session = Depends(get_db)) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    rows_ = db.execute(select(UsageRecord.kind, UsageRecord.component, UsageRecord.model, func.sum(UsageRecord.input_units),
                              func.sum(UsageRecord.output_units), func.sum(UsageRecord.cost_usd))
                       .where(UsageRecord.tenant_id == p.tenant_id, UsageRecord.created_at >= since)
                       .group_by(UsageRecord.kind, UsageRecord.component, UsageRecord.model)).all()
    t = db.get(Tenant, p.tenant_id)
    return {"window_days": days, "budget_usd": (t.settings or {}).get("llm_monthly_budget_usd"),
            "items": [{"kind": k, "component": c, "model": m, "input_units": int(i or 0), "output_units": int(o or 0),
                       "cost_usd": round(float(cost or 0), 4)} for k, c, m, i, o, cost in rows_]}


# ------------------------------------------------------------------ audit (NFR-AUD-001, US-009)
def _audit_query(p: Principal, action: str | None, resource_type: str | None, resource_id: str | None,
                 actor_id: str | None, since: datetime | None, until: datetime | None):  # type: ignore[no-untyped-def]
    stmt = select(AuditLog).where(AuditLog.tenant_id == p.tenant_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
    if until:
        stmt = stmt.where(AuditLog.created_at <= until)
    return stmt


@router.get("/audit")
def audit_search(action: str | None = None, resource_type: str | None = None, resource_id: str | None = None,
                 actor_id: str | None = None, since: datetime | None = None, until: datetime | None = None,
                 page: Page = Depends(page_params), p: Principal = Depends(require(Perm.AUDIT_READ)),
                 db: Session = Depends(get_db)) -> dict:
    stmt = _audit_query(p, action, resource_type, resource_id, actor_id, since, until)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return paged(rows(db.scalars(stmt.order_by(AuditLog.id.desc()).limit(page.limit).offset(page.offset)).all()), total, page)


@router.get("/audit/export")
def audit_export(format: Literal["csv", "json"] = "csv", action: str | None = None, resource_type: str | None = None,
                 since: datetime | None = None, until: datetime | None = None,
                 p: Principal = Depends(require(Perm.AUDIT_EXPORT)), db: Session = Depends(get_db)) -> Response:
    items = rows(db.scalars(_audit_query(p, action, resource_type, None, None, since, until)
                            .order_by(AuditLog.id).limit(100_000)).all())
    audit.record(db, action="audit.export", resource_type="audit_log", tenant_id=p.tenant_id, actor_id=p.actor,
                 after={"format": format, "rows": len(items)})
    if format == "json":
        return Response(json.dumps(items, default=str), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="audit.json"'})
    buf = io.StringIO()
    cols = ["id", "created_at", "actor_type", "actor_id", "action", "resource_type", "resource_id", "reason",
            "request_id", "ip", "before", "after", "prev_hash", "hash"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for it in items:
        w.writerow({**it, "before": json.dumps(it.get("before")), "after": json.dumps(it.get("after"))})
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="audit.csv"'})


@router.get("/audit/verify")
def audit_verify(p: Principal = Depends(require(Perm.AUDIT_READ)), db: Session = Depends(get_db)) -> dict:
    return audit.verify_chain(db, p.tenant_id)
