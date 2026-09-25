"""/landscapes, /templates, /watchlists, /saved-views (FR-LND-*, FR-UX-003/007)."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import Idempotency, Page, get_db, idempotency, page_params, paged, require
from app.api.serialize import row, rows
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.rbac import Perm
from app.core.security import Principal
from app.entities.graph import neighbourhood
from app.models import (
    Asset,
    Company,
    Landscape,
    LandscapeMember,
    LandscapeTemplate,
    SavedView,
    Trial,
    Watchlist,
    WatchlistItem,
)
from app.services import audit
from app.services.landscapes import (
    create_landscape,
    export_landscape,
    landscape_matrix,
    set_members,
    update_landscape,
)

router = APIRouter(tags=["landscapes"])


class MemberIn(BaseModel):
    entity_type: Literal["asset", "company", "trial"]
    entity_id: uuid.UUID
    role: Literal["customer", "competitor", "monitored"] = "competitor"


class LandscapeIn(BaseModel):
    name: str = Field(..., max_length=200)
    description: str | None = None
    disease: str | None = None
    geographies: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict, description="trial_queries, nct_ids, pubmed_queries, "
                                   "fda_products, sec_ciks, feeds, materiality_weights, band_thresholds, indications")
    template_id: uuid.UUID | None = None
    members: list[MemberIn] = Field(default_factory=list)


class LandscapePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    disease: str | None = None
    geographies: list[str] | None = None
    config: dict[str, Any] | None = None
    reason: str | None = None


def _get_ls(db: Session, landscape_id: uuid.UUID) -> Landscape:
    ls = db.get(Landscape, landscape_id)
    if ls is None:
        raise NotFound("landscape not found")
    return ls


@router.get("/landscapes")
def list_landscapes(include_archived: bool = False, p: Principal = Depends(require(Perm.LANDSCAPE_READ)),
                    db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Landscape).where(Landscape.tenant_id == p.tenant_id)
    if not include_archived:
        stmt = stmt.where(Landscape.status == "active")
    out = []
    for ls in db.scalars(stmt.order_by(Landscape.name)).all():
        counts = dict(db.execute(select(LandscapeMember.role, func.count()).where(
            LandscapeMember.landscape_id == ls.id).group_by(LandscapeMember.role)).all())
        out.append({**row(ls), "member_counts": counts})
    return out


@router.post("/landscapes", status_code=201)
def create(body: LandscapeIn, request: Request, idem: Idempotency = Depends(idempotency),
           p: Principal = Depends(require(Perm.LANDSCAPE_WRITE)), db: Session = Depends(get_db)) -> dict:
    if (prev := idem.replay(db)) is not None:
        return prev
    if db.scalar(select(Landscape).where(Landscape.tenant_id == p.tenant_id, Landscape.name == body.name)):
        raise ValidationFailed("a landscape with this name already exists")
    ls = create_landscape(db, p.tenant_id, p.actor, body.model_dump(exclude={"members"}))
    if body.members:
        set_members(db, ls, p.actor, [m.model_dump() for m in body.members])
    out = row(ls)
    idem.store(db, request, out, 201)
    return out


@router.get("/landscapes/{landscape_id}")
def get_landscape(landscape_id: uuid.UUID, p: Principal = Depends(require(Perm.LANDSCAPE_READ)),
                  db: Session = Depends(get_db)) -> dict:
    ls = _get_ls(db, landscape_id)
    members = []
    for m in db.scalars(select(LandscapeMember).where(LandscapeMember.landscape_id == ls.id)).all():
        obj = db.get({"asset": Asset, "company": Company, "trial": Trial}[m.entity_type], m.entity_id)
        label = getattr(obj, "canonical_name", None) or getattr(obj, "nct_id", None) if obj else None
        members.append({**row(m), "label": label, "status": getattr(obj, "status", None)})
    return {**row(ls), "members": members}


@router.patch("/landscapes/{landscape_id}")
def patch_landscape(landscape_id: uuid.UUID, body: LandscapePatch, p: Principal = Depends(require(Perm.LANDSCAPE_WRITE)),
                    db: Session = Depends(get_db)) -> dict:
    ls = _get_ls(db, landscape_id)
    return row(update_landscape(db, ls, p.actor, body.model_dump(exclude={"reason"}), body.reason))


@router.put("/landscapes/{landscape_id}/thresholds")
def configure_thresholds(landscape_id: uuid.UUID, body: dict[str, Any], p: Principal = Depends(require(Perm.CONFIG_ADMIN)),
                         db: Session = Depends(get_db)) -> dict:
    """Configure band thresholds / materiality weights per landscape (FR-MAT-002)."""
    ls = _get_ls(db, landscape_id)
    cfg = {k: body[k] for k in ("band_thresholds", "materiality_weights") if k in body}
    return row(update_landscape(db, ls, p.actor, {"config": cfg}, body.get("reason")))


@router.post("/landscapes/{landscape_id}/archive")
def archive(landscape_id: uuid.UUID, p: Principal = Depends(require(Perm.LANDSCAPE_WRITE)), db: Session = Depends(get_db)) -> dict:
    ls = _get_ls(db, landscape_id)
    ls.status = "archived"
    audit.record(db, action="landscape.archive", resource_type="landscape", resource_id=ls.id, tenant_id=p.tenant_id,
                 actor_id=p.actor)
    return row(ls)


@router.post("/landscapes/{landscape_id}/restore")
def restore(landscape_id: uuid.UUID, p: Principal = Depends(require(Perm.LANDSCAPE_WRITE)), db: Session = Depends(get_db)) -> dict:
    ls = _get_ls(db, landscape_id)
    ls.status = "active"
    audit.record(db, action="landscape.restore", resource_type="landscape", resource_id=ls.id, tenant_id=p.tenant_id,
                 actor_id=p.actor)
    return row(ls)


@router.get("/landscapes/{landscape_id}/export")
def export(landscape_id: uuid.UUID, p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> dict:
    ls = _get_ls(db, landscape_id)
    audit.record(db, action="landscape.export", resource_type="landscape", resource_id=ls.id, tenant_id=p.tenant_id,
                 actor_id=p.actor)
    return export_landscape(db, ls)


@router.post("/landscapes/{landscape_id}/members")
def add_members(landscape_id: uuid.UUID, body: list[MemberIn], replace: bool = False,
                p: Principal = Depends(require(Perm.LANDSCAPE_WRITE)), db: Session = Depends(get_db)) -> dict:
    ls = _get_ls(db, landscape_id)
    return {"added": set_members(db, ls, p.actor, [m.model_dump() for m in body], replace)}


@router.delete("/landscapes/{landscape_id}/members/{entity_id}", status_code=204)
def remove_member(landscape_id: uuid.UUID, entity_id: uuid.UUID, p: Principal = Depends(require(Perm.LANDSCAPE_WRITE)),
                  db: Session = Depends(get_db)) -> None:
    ls = _get_ls(db, landscape_id)
    m = db.scalar(select(LandscapeMember).where(LandscapeMember.landscape_id == ls.id, LandscapeMember.entity_id == entity_id))
    if m is None:
        raise NotFound("member not found")
    db.delete(m)
    audit.record(db, action="landscape.member_remove", resource_type="landscape", resource_id=ls.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, before={"entity_id": str(entity_id), "role": m.role})


@router.get("/landscapes/{landscape_id}/matrix")
def matrix(landscape_id: uuid.UUID, p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> dict:
    return landscape_matrix(db, _get_ls(db, landscape_id))


@router.get("/landscapes/{landscape_id}/graph")
def graph(landscape_id: uuid.UUID, depth: int = 1, p: Principal = Depends(require(Perm.LANDSCAPE_READ)),
          db: Session = Depends(get_db)) -> dict:
    ls = _get_ls(db, landscape_id)
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    for m in db.scalars(select(LandscapeMember).where(LandscapeMember.landscape_id == ls.id,
                                                      LandscapeMember.entity_type.in_(("asset", "company")))).all():
        g = neighbourhood(db, m.entity_id, depth=min(depth, 2), limit=150)
        for n in g["nodes"]:
            nodes[n["id"]] = {**n, "role": m.role if n["id"] == str(m.entity_id) else nodes.get(n["id"], {}).get("role")}
        for e in g["edges"]:
            edges[e["id"]] = e
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


# ------------------------------------------------------------------ templates
@router.get("/templates")
def list_templates(p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> list[dict]:
    return rows(db.scalars(select(LandscapeTemplate).order_by(LandscapeTemplate.name)).all())


# ------------------------------------------------------------------ watchlists (FR-LND-002)
class WatchItemIn(BaseModel):
    item_type: Literal["company", "asset", "mechanism", "indication", "trial", "kol", "conference", "regulatory_event"]
    entity_id: uuid.UUID | None = None
    value: str = ""


class WatchlistIn(BaseModel):
    name: str
    description: str | None = None
    visibility: Literal["private", "team", "tenant"] = "private"
    landscape_id: uuid.UUID | None = None
    alert_policy_id: uuid.UUID | None = None
    items: list[WatchItemIn] = Field(default_factory=list)


def _visible_watchlists(p: Principal):  # type: ignore[no-untyped-def]
    return or_(Watchlist.owner_id == p.user_id, Watchlist.visibility == "tenant",
               (Watchlist.visibility == "team") & (Watchlist.team == p.team))


def _get_wl(db: Session, p: Principal, wid: uuid.UUID, write: bool = False) -> Watchlist:
    wl = db.scalar(select(Watchlist).where(Watchlist.id == wid, _visible_watchlists(p)))
    if wl is None:
        raise NotFound("watchlist not found")
    if write and wl.owner_id != p.user_id and not p.has(Perm.CONFIG_ADMIN):
        raise Forbidden("only the owner can modify this watchlist")
    return wl


@router.get("/watchlists")
def list_watchlists(p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for wl in db.scalars(select(Watchlist).where(_visible_watchlists(p)).order_by(Watchlist.name)).all():
        n = db.scalar(select(func.count()).select_from(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id))
        out.append({**row(wl), "item_count": n, "owned": wl.owner_id == p.user_id})
    return out


@router.post("/watchlists", status_code=201)
def create_watchlist(body: WatchlistIn, p: Principal = Depends(require(Perm.WATCHLIST_WRITE)), db: Session = Depends(get_db)) -> dict:
    wl = Watchlist(tenant_id=p.tenant_id, owner_id=p.user_id, name=body.name, description=body.description,
                   visibility=body.visibility, team=p.team, landscape_id=body.landscape_id,
                   alert_policy_id=body.alert_policy_id)
    db.add(wl)
    db.flush()
    for it in body.items:
        db.add(WatchlistItem(tenant_id=p.tenant_id, watchlist_id=wl.id, added_by=p.actor, **it.model_dump()))
    audit.record(db, action="watchlist.create", resource_type="watchlist", resource_id=wl.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after=body.model_dump(mode="json"))
    return row(wl)


@router.get("/watchlists/{wid}")
def get_watchlist(wid: uuid.UUID, p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> dict:
    wl = _get_wl(db, p, wid)
    return {**row(wl), "items": rows(db.scalars(select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)).all())}


@router.patch("/watchlists/{wid}")
def update_watchlist(wid: uuid.UUID, body: dict[str, Any], p: Principal = Depends(require(Perm.WATCHLIST_WRITE)),
                     db: Session = Depends(get_db)) -> dict:
    wl = _get_wl(db, p, wid, write=True)
    before = row(wl)
    for k in ("name", "description", "visibility", "alert_policy_id", "landscape_id"):
        if k in body:
            setattr(wl, k, body[k])
    if wl.visibility not in ("private", "team", "tenant"):
        raise ValidationFailed("invalid visibility")
    audit.record(db, action="watchlist.update", resource_type="watchlist", resource_id=wl.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, before=before, after=row(wl))
    return row(wl)


@router.post("/watchlists/{wid}/items")
def add_items(wid: uuid.UUID, body: list[WatchItemIn], p: Principal = Depends(require(Perm.WATCHLIST_WRITE)),
              db: Session = Depends(get_db)) -> dict:
    wl = _get_wl(db, p, wid, write=True)
    added = 0
    for it in body:
        exists = db.scalar(select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id,
                                                       WatchlistItem.item_type == it.item_type,
                                                       WatchlistItem.entity_id == it.entity_id,
                                                       WatchlistItem.value == it.value))
        if not exists:
            db.add(WatchlistItem(tenant_id=p.tenant_id, watchlist_id=wl.id, added_by=p.actor, **it.model_dump()))
            added += 1
    audit.record(db, action="watchlist.items_add", resource_type="watchlist", resource_id=wl.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after={"count": added})
    return {"added": added}


@router.post("/watchlists/{wid}/import")
async def bulk_import(wid: uuid.UUID, request: Request, p: Principal = Depends(require(Perm.WATCHLIST_WRITE)),
                      db: Session = Depends(get_db)) -> dict:
    """Bulk import CSV (columns: item_type,value[,entity_id]); names are resolved to canonical entities."""
    from app.entities.resolver import EntityResolver

    wl = _get_wl(db, p, wid, write=True)
    text = (await request.body()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    resolver = EntityResolver(db, p.tenant_id)
    added, unresolved = 0, []
    for r in reader:
        itype = (r.get("item_type") or "").strip()
        value = (r.get("value") or "").strip()
        eid = r.get("entity_id") or None
        if itype not in WatchItemIn.model_fields["item_type"].annotation.__args__:  # type: ignore[union-attr]
            unresolved.append({"row": r, "error": "invalid item_type"})
            continue
        if not eid and value and itype in ("company", "asset", "mechanism", "indication", "kol", "conference"):
            res = resolver.resolve(value, itype)
            if res.linked:
                eid = res.entity_id
            else:
                unresolved.append({"row": r, "error": "not resolved", "candidates": res.candidates[:3]})
        db.add(WatchlistItem(tenant_id=p.tenant_id, watchlist_id=wl.id, item_type=itype,
                             entity_id=uuid.UUID(str(eid)) if eid else None, value=value, added_by=p.actor))
        added += 1
    audit.record(db, action="watchlist.bulk_import", resource_type="watchlist", resource_id=wl.id,
                 tenant_id=p.tenant_id, actor_id=p.actor, after={"added": added, "unresolved": len(unresolved)})
    return {"added": added, "unresolved": unresolved}


@router.delete("/watchlists/{wid}/items/{item_id}", status_code=204)
def remove_item(wid: uuid.UUID, item_id: uuid.UUID, p: Principal = Depends(require(Perm.WATCHLIST_WRITE)),
                db: Session = Depends(get_db)) -> None:
    wl = _get_wl(db, p, wid, write=True)
    it = db.get(WatchlistItem, item_id)
    if it is None or it.watchlist_id != wl.id:
        raise NotFound("item not found")
    db.delete(it)


@router.delete("/watchlists/{wid}", status_code=204)
def delete_watchlist(wid: uuid.UUID, p: Principal = Depends(require(Perm.WATCHLIST_WRITE)), db: Session = Depends(get_db)) -> None:
    wl = _get_wl(db, p, wid, write=True)
    audit.record(db, action="watchlist.delete", resource_type="watchlist", resource_id=wl.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, before=row(wl))
    db.delete(wl)


# ------------------------------------------------------------------ saved views (FR-UX-007)
class SavedViewIn(BaseModel):
    name: str
    view: Literal["feed", "calendar", "matrix", "compare"]
    filters: dict[str, Any] = Field(default_factory=dict)
    visibility: Literal["private", "team", "tenant"] = "private"


@router.get("/saved-views")
def list_views(view: str | None = None, page: Page = Depends(page_params), p: Principal = Depends(require(Perm.LANDSCAPE_READ)),
               db: Session = Depends(get_db)) -> dict:
    stmt = select(SavedView).where(or_(SavedView.owner_id == p.user_id, SavedView.visibility == "tenant",
                                       (SavedView.visibility == "team") & (SavedView.team == p.team)))
    if view:
        stmt = stmt.where(SavedView.view == view)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(SavedView.name).limit(page.limit).offset(page.offset)).all()
    return paged([{**row(v), "owned": v.owner_id == p.user_id} for v in items], total, page)


@router.post("/saved-views", status_code=201)
def create_view(body: SavedViewIn, p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> dict:
    v = SavedView(tenant_id=p.tenant_id, owner_id=p.user_id, team=p.team, **body.model_dump())
    db.add(v)
    db.flush()
    return row(v)


@router.delete("/saved-views/{vid}", status_code=204)
def delete_view(vid: uuid.UUID, p: Principal = Depends(require(Perm.LANDSCAPE_READ)), db: Session = Depends(get_db)) -> None:
    v = db.get(SavedView, vid)
    if v is None or v.owner_id != p.user_id:
        raise NotFound("saved view not found")
    db.delete(v)
