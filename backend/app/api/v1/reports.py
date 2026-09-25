"""/reports: executive brief generation, editable review, approval, distribution, export (FR-ALT-003)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents.briefing import generate_brief
from app.api.deps import get_db, require
from app.api.serialize import row, rows
from app.core.errors import NotFound, ValidationFailed
from app.core.rbac import Perm
from app.core.security import Principal
from app.models import GeneratedArtifact, Landscape, Notification, Report
from app.reports.export import EXPORTERS
from app.services import audit

router = APIRouter(prefix="/reports", tags=["reports"])


class BriefIn(BaseModel):
    landscape_id: uuid.UUID
    period_start: date | None = None
    period_end: date | None = None


def _get(db: Session, p: Principal, rid: uuid.UUID) -> Report:
    r = db.get(Report, rid)
    if r is None or r.tenant_id != p.tenant_id:
        raise NotFound("report not found")
    return r


def _content(db: Session, r: Report) -> dict[str, Any]:
    aid = r.edited_artifact_id or r.artifact_id
    art = db.get(GeneratedArtifact, aid) if aid else None
    return art.content if art else {}


@router.post("/briefs", status_code=201)
def create_brief(body: BriefIn, p: Principal = Depends(require(Perm.REPORT_WRITE)), db: Session = Depends(get_db)) -> dict:
    ls = db.get(Landscape, body.landscape_id)
    if ls is None:
        raise NotFound("landscape not found")
    end = body.period_end or datetime.now(UTC).date()
    start = body.period_start or end - timedelta(days=7)
    if start > end:
        raise ValidationFailed("period_start must be before period_end")
    rep = generate_brief(db, p.tenant_id, ls, start, end, p.actor)
    audit.record(db, action="report.generate", resource_type="report", resource_id=rep.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after={"landscape_id": str(ls.id), "period": [start.isoformat(), end.isoformat()]})
    return {**row(rep), "content": _content(db, rep)}


@router.get("")
def list_reports(landscape_id: uuid.UUID | None = None, p: Principal = Depends(require(Perm.REPORT_READ)),
                 db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Report).where(Report.tenant_id == p.tenant_id)
    if landscape_id:
        stmt = stmt.where(Report.landscape_id == landscape_id)
    return rows(db.scalars(stmt.order_by(Report.created_at.desc()).limit(100)).all())


@router.get("/{report_id}")
def get_report(report_id: uuid.UUID, p: Principal = Depends(require(Perm.REPORT_READ)), db: Session = Depends(get_db)) -> dict:
    r = _get(db, p, report_id)
    orig = db.get(GeneratedArtifact, r.artifact_id) if r.artifact_id else None
    return {**row(r), "content": _content(db, r), "original_content": orig.content if orig and r.edited_artifact_id else None}


class ReportEdit(BaseModel):
    executive_summary: str | None = None
    top_developments: list[dict[str, Any]] | None = None
    watch_items: list[str] | None = None
    reason: str = Field(..., min_length=3)


@router.patch("/{report_id}")
def edit_report(report_id: uuid.UUID, body: ReportEdit, p: Principal = Depends(require(Perm.REPORT_WRITE)),
                db: Session = Depends(get_db)) -> dict:
    r = _get(db, p, report_id)
    if r.status in ("approved", "distributed"):
        raise ValidationFailed("approved reports are immutable; generate a new brief")
    base = _content(db, r)
    content = {**base, **{k: v for k, v in body.model_dump(exclude={"reason"}).items() if v is not None},
               "edited_by": p.actor, "edited_at": datetime.now(UTC).isoformat()}
    orig = db.get(GeneratedArtifact, r.artifact_id)
    art = GeneratedArtifact(tenant_id=p.tenant_id, kind="executive_brief", content=content, publishable=True,
                            review_status="Analyst-reviewed", is_human_edited=True, parent_id=r.artifact_id,
                            edited_by=p.actor, edit_reason=body.reason, generation_id=orig.generation_id if orig else None,
                            model_workflow_version=f"{orig.model_workflow_version if orig else 'brief'}+analyst-edit")
    db.add(art)
    db.flush()
    r.edited_artifact_id = art.id
    r.status = "in_review"
    audit.record(db, action="report.edit", resource_type="report", resource_id=r.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, before=base, after=content, reason=body.reason)
    return {**row(r), "content": content}


@router.post("/{report_id}/approve")
def approve(report_id: uuid.UUID, p: Principal = Depends(require(Perm.REPORT_APPROVE)), db: Session = Depends(get_db)) -> dict:
    r = _get(db, p, report_id)
    if r.status == "distributed":
        raise ValidationFailed("already distributed")
    r.status, r.approved_by, r.approved_at = "approved", p.actor, datetime.now(UTC)
    audit.record(db, action="report.approve", resource_type="report", resource_id=r.id, tenant_id=p.tenant_id, actor_id=p.actor)
    return row(r)


class DistributeIn(BaseModel):
    distribution_list: list[EmailStr] = Field(..., min_length=1)


@router.post("/{report_id}/distribute")
def distribute(report_id: uuid.UUID, body: DistributeIn, p: Principal = Depends(require(Perm.REPORT_APPROVE)),
               db: Session = Depends(get_db)) -> dict:
    """Distribution only after review/approval (FR-ALT-003 acceptance)."""
    r = _get(db, p, report_id)
    if r.status != "approved":
        raise ValidationFailed("brief must be approved before distribution")
    content = _content(db, r)
    r.distribution_list = [str(e) for e in body.distribution_list]
    r.status, r.distributed_at = "distributed", datetime.now(UTC)
    db.add(Notification(tenant_id=p.tenant_id, dedupe_key=f"brief:{r.id}", kind="brief", channel="email",
                        status="pending", next_attempt_at=datetime.now(UTC), user_id=p.user_id,
                        payload={"title": content.get("title", r.title), "verified_change": [content.get("executive_summary", "")],
                                 "items": [{"title": d.get("headline"), "interpretation": d.get("so_what")}
                                           for d in content.get("top_developments", [])],
                                 "recipients": r.distribution_list, "report_id": str(r.id)}))
    audit.record(db, action="report.distribute", resource_type="report", resource_id=r.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after={"recipients": r.distribution_list})
    return row(r)


@router.get("/{report_id}/export")
def export(report_id: uuid.UUID, format: Literal["md", "docx", "pdf", "pptx"] = "docx",
           p: Principal = Depends(require(Perm.REPORT_READ)), db: Session = Depends(get_db)) -> Response:
    r = _get(db, p, report_id)
    fn, media = EXPORTERS[format]
    data = fn("executive_brief", _content(db, r))
    audit.record(db, action="report.export", resource_type="report", resource_id=r.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after={"format": format})
    return Response(data.encode() if isinstance(data, str) else data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="xdata-brief-{r.period_end}.{format}"'})
