"""/ask: grounded landscape Q&A with optional SSE streaming and exports (FR-QA-*)."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.ai.agents.ask import ask
from app.api.deps import get_db, rate_limit, require
from app.api.serialize import row
from app.core.errors import NotFound
from app.core.rbac import Perm
from app.core.security import Principal
from app.db.session import session_scope
from app.models import AskSession, AskTurn, GeneratedArtifact
from app.reports.export import EXPORTERS
from app.services import audit

router = APIRouter(prefix="/ask", tags=["ask"])


class AskIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    session_id: uuid.UUID | None = None
    landscape_id: uuid.UUID | None = None


@router.post("")
def ask_question(body: AskIn, p: Principal = Depends(require(Perm.ASK)), _rl: Principal = Depends(rate_limit("ask")),
                 db: Session = Depends(get_db)) -> dict:
    out = ask(db, tenant_id=p.tenant_id, user_id=p.user_id, question=body.question, session_id=body.session_id,
              landscape_id=body.landscape_id)
    audit.record(db, action="ask.question", resource_type="ask_turn", resource_id=out["turn_id"], tenant_id=p.tenant_id,
                 actor_id=p.actor, after={"question": body.question, "abstained": out["abstained"]})
    return out


@router.post("/stream")
async def ask_stream(body: AskIn, p: Principal = Depends(require(Perm.ASK)),
                     _rl: Principal = Depends(rate_limit("ask"))) -> EventSourceResponse:
    """Server-sent events: planned -> retrieved -> generated -> validated -> answer (NFR-PERF-001: AI may stream)."""
    q: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            with session_scope(p.tenant_id) as db:
                out = ask(db, tenant_id=p.tenant_id, user_id=p.user_id, question=body.question,
                          session_id=body.session_id, landscape_id=body.landscape_id, progress=lambda e: q.put(("progress", e)))
                audit.record(db, action="ask.question", resource_type="ask_turn", resource_id=out["turn_id"],
                             tenant_id=p.tenant_id, actor_id=p.actor,
                             after={"question": body.question, "abstained": out["abstained"]})
            q.put(("answer", out))
        except Exception as e:  # noqa: BLE001
            q.put(("error", {"message": str(e)[:300]}))
        finally:
            q.put(("done", {}))

    threading.Thread(target=work, daemon=True).start()

    async def events() -> AsyncIterator[dict]:
        while True:
            try:
                kind, payload = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if kind == "done":
                break
            yield {"event": kind, "data": json.dumps(payload, default=str)}

    return EventSourceResponse(events(), ping=15)


@router.get("/sessions")
def sessions(p: Principal = Depends(require(Perm.ASK)), db: Session = Depends(get_db)) -> list[dict]:
    rows_ = db.scalars(select(AskSession).where(AskSession.user_id == p.user_id, AskSession.tenant_id == p.tenant_id)
                       .order_by(AskSession.updated_at.desc()).limit(50)).all()
    return [row(s) for s in rows_]


@router.get("/sessions/{session_id}")
def session_detail(session_id: uuid.UUID, p: Principal = Depends(require(Perm.ASK)), db: Session = Depends(get_db)) -> dict:
    s = db.get(AskSession, session_id)
    if s is None or s.user_id != p.user_id:
        raise NotFound("session not found")
    turns = db.scalars(select(AskTurn).where(AskTurn.session_id == s.id).order_by(AskTurn.created_at)).all()
    out = []
    for t in turns:
        art = db.get(GeneratedArtifact, t.artifact_id) if t.artifact_id else None
        out.append({"turn_id": str(t.id), "question": t.question, "created_at": t.created_at.isoformat(),
                    "artifact_id": str(t.artifact_id) if t.artifact_id else None, "answer": art.content if art else None})
    return {**row(s), "turns": out}


@router.get("/answers/{artifact_id}/export")
def export_answer(artifact_id: uuid.UUID, format: Literal["md", "docx", "pdf", "pptx"] = "docx",
                  p: Principal = Depends(require(Perm.ASK)), db: Session = Depends(get_db)) -> Response:
    art = db.get(GeneratedArtifact, artifact_id)
    if art is None or art.tenant_id != p.tenant_id or art.kind != "ask_answer":
        raise NotFound("answer not found")
    fn, media = EXPORTERS[format]
    data = fn(art.kind, art.content)
    audit.record(db, action="ask.export", resource_type="generated_artifact", resource_id=art.id, tenant_id=p.tenant_id,
                 actor_id=p.actor, after={"format": format})
    body = data.encode() if isinstance(data, str) else data
    return Response(body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="xdata-answer-{str(art.id)[:8]}.{format}"'})
