"""Knowledge-graph operations (FR-ENT-003/006): typed edges, neighbourhoods, path finding."""

from __future__ import annotations

import uuid
from collections import deque
from datetime import date
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    Catalyst,
    Company,
    Concept,
    Disclosure,
    Publication,
    RegulatoryEvent,
    Relationship,
    Trial,
)


def upsert_edge(
    db: Session,
    *,
    subject_type: str,
    subject_id: uuid.UUID,
    predicate: str,
    object_type: str,
    object_id: uuid.UUID,
    confidence: float = 1.0,
    method: str = "source",
    status: str = "verified",
    tenant_id: uuid.UUID | None = None,
    evidence: dict | None = None,
    valid_from: date | None = None,
) -> Relationship:
    stmt = select(Relationship).where(
        Relationship.subject_id == subject_id,
        Relationship.predicate == predicate,
        Relationship.object_id == object_id,
        Relationship.valid_to.is_(None),
        Relationship.tenant_id.is_(None) if tenant_id is None else Relationship.tenant_id == tenant_id,
    )
    rel = db.scalar(stmt)
    if rel is None:
        rel = Relationship(subject_type=subject_type, subject_id=subject_id, predicate=predicate,
                           object_type=object_type, object_id=object_id, confidence=confidence, method=method,
                           status=status, tenant_id=tenant_id, evidence=evidence or {}, valid_from=valid_from)
        db.add(rel)
    else:
        if confidence > rel.confidence:
            rel.confidence, rel.method = confidence, method
        if status == "verified":
            rel.status = "verified"
        if evidence:
            rel.evidence = {**(rel.evidence or {}), **evidence}
    db.flush()
    return rel


def end_edge(db: Session, rel: Relationship, on: date) -> None:
    """Close a temporal edge (e.g. asset ownership transferred) rather than deleting it."""
    rel.valid_to = on
    db.flush()


def _active(as_of: date | None):  # type: ignore[no-untyped-def]
    if as_of is None:
        return Relationship.valid_to.is_(None)
    return and_(
        or_(Relationship.valid_from.is_(None), Relationship.valid_from <= as_of),
        or_(Relationship.valid_to.is_(None), Relationship.valid_to > as_of),
    )


def edges_for(db: Session, node_id: uuid.UUID, *, as_of: date | None = None,
              predicates: list[str] | None = None) -> list[Relationship]:
    stmt = select(Relationship).where(
        or_(Relationship.subject_id == node_id, Relationship.object_id == node_id),
        Relationship.status != "rejected",
        _active(as_of),
    )
    if predicates:
        stmt = stmt.where(Relationship.predicate.in_(predicates))
    return list(db.scalars(stmt).all())


def neighbours(db: Session, node_id: uuid.UUID, *, predicate: str, direction: str = "out",
               as_of: date | None = None) -> list[uuid.UUID]:
    col_from, col_to = (
        (Relationship.subject_id, Relationship.object_id) if direction == "out"
        else (Relationship.object_id, Relationship.subject_id)
    )
    stmt = select(col_to).where(col_from == node_id, Relationship.predicate == predicate,
                                Relationship.status != "rejected", _active(as_of))
    return list(db.scalars(stmt).all())


def find_path(db: Session, start: uuid.UUID, goal: uuid.UUID, *, max_depth: int = 4,
              as_of: date | None = None) -> list[dict[str, Any]] | None:
    """Breadth-first shortest path over typed edges (both directions). Returns list of hops."""
    if start == goal:
        return []
    frontier = deque([start])
    parent: dict[uuid.UUID, tuple[uuid.UUID, Relationship]] = {}
    depth = {start: 0}
    while frontier:
        node = frontier.popleft()
        if depth[node] >= max_depth:
            continue
        for rel in edges_for(db, node, as_of=as_of):
            nxt = rel.object_id if rel.subject_id == node else rel.subject_id
            if nxt in depth:
                continue
            depth[nxt] = depth[node] + 1
            parent[nxt] = (node, rel)
            if nxt == goal:
                hops = []
                cur = goal
                while cur != start:
                    prev, r = parent[cur]
                    hops.append({"from": str(prev), "to": str(cur), "predicate": r.predicate,
                                 "confidence": r.confidence, "method": r.method, "edge_id": str(r.id)})
                    cur = prev
                return list(reversed(hops))
            frontier.append(nxt)
    return None


_LABEL_MODELS = [
    ("asset", Asset, "canonical_name"),
    ("company", Company, "canonical_name"),
    ("trial", Trial, "nct_id"),
    ("publication", Publication, "title"),
    ("regulatory_event", RegulatoryEvent, "product_name"),
    ("disclosure", Disclosure, "title"),
    ("catalyst", Catalyst, "title"),
]


def node_label(db: Session, node_id: uuid.UUID, node_type: str | None = None) -> dict[str, Any]:
    for t, model, attr in _LABEL_MODELS:
        if node_type and node_type != t:
            continue
        obj = db.get(model, node_id)
        if obj is not None:
            label = getattr(obj, attr)
            if t == "trial":
                label = f"{obj.nct_id} {obj.title[:80]}" if obj.nct_id else obj.title[:80]
            return {"id": str(node_id), "type": t, "label": label}
    c = db.get(Concept, node_id)
    if c is not None:
        return {"id": str(node_id), "type": c.kind, "label": c.canonical_name}
    return {"id": str(node_id), "type": node_type or "unknown", "label": str(node_id)[:8]}


def neighbourhood(db: Session, node_id: uuid.UUID, depth: int = 1, limit: int = 200) -> dict[str, Any]:
    nodes: dict[uuid.UUID, dict[str, Any]] = {node_id: node_label(db, node_id)}
    edges: list[dict[str, Any]] = []
    frontier = [node_id]
    for _ in range(depth):
        nxt: list[uuid.UUID] = []
        for n in frontier:
            for rel in edges_for(db, n):
                if len(edges) >= limit:
                    break
                edges.append({"id": str(rel.id), "source": str(rel.subject_id), "target": str(rel.object_id),
                              "predicate": rel.predicate, "confidence": rel.confidence, "method": rel.method,
                              "status": rel.status, "valid_from": rel.valid_from, "valid_to": rel.valid_to})
                for other, t in ((rel.subject_id, rel.subject_type), (rel.object_id, rel.object_type)):
                    if other not in nodes:
                        nodes[other] = node_label(db, other, t)
                        nxt.append(other)
        frontier = nxt
    return {"nodes": list(nodes.values()), "edges": edges}
