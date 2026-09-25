"""LLM access layer.

* Claude via the official Anthropic SDK, structured JSON outputs (``output_config.format``), adaptive
  thinking with an explicit effort level, and server-side refusal fallbacks.
* Every call is recorded as a ``GenerationRecord`` (model, served model, prompt id/version/hash,
  configuration, retrieval-set hash, tokens, cost, latency) - FR-AI-007 / NFR-AI-001.
* Per-tenant monthly budgets (Section 20 cost controls).
* ``offline`` provider: callers supply a deterministic builder, so the platform keeps producing
  evidence-bound (fact-only) outputs without a model - also the degraded mode on model outage.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.prompts import Prompt
from app.core.config import get_settings
from app.core.crypto import stable_hash
from app.core.errors import BudgetExceeded
from app.core.logging import get_logger
from app.core.metrics import LLM_CALLS, LLM_LATENCY, LLM_TOKENS
from app.models import GenerationRecord, Tenant, UsageRecord

log = get_logger(__name__)

# USD per 1M tokens (input, output). Used for cost telemetry/budgets only.
PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
}


class LLMUnavailable(Exception):
    pass


class LLMRefusal(Exception):
    pass


@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    served_model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    latency_ms: int = 0
    request_id: str | None = None
    stop_reason: str | None = None
    generation_id: uuid.UUID | None = None
    degraded: bool = False
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def model_workflow_version(self) -> str:
        return self.config.get("model_workflow_version", self.model)


@lru_cache
def _anthropic_client():  # type: ignore[no-untyped-def]
    import anthropic

    s = get_settings()
    kwargs: dict[str, Any] = {"timeout": s.llm_timeout_seconds, "max_retries": 3}
    if s.anthropic_api_key:
        kwargs["api_key"] = s.anthropic_api_key.get_secret_value()
    return anthropic.Anthropic(**kwargs)


def _cost(model: str, inp: int, out: int, cache_read: int) -> float:
    pin, pout = PRICING.get(model, (5.0, 25.0))
    return round((inp * pin + cache_read * pin * 0.1 + out * pout) / 1_000_000, 6)


def check_budget(db: Session, tenant_id: uuid.UUID) -> None:
    s = get_settings()
    tenant = db.get(Tenant, tenant_id)
    budget = float((tenant.settings or {}).get("llm_monthly_budget_usd", s.llm_monthly_budget_usd)) if tenant else 0.0
    if budget <= 0:
        return
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = db.scalar(
        select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
            UsageRecord.tenant_id == tenant_id, UsageRecord.kind == "llm", UsageRecord.created_at >= month_start
        )
    )
    if spent >= budget:
        raise BudgetExceeded(f"monthly LLM budget of ${budget:.2f} reached", details={"spent": spent})


class LLMService:
    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.settings = get_settings()

    @property
    def provider(self) -> str:
        return self.settings.llm_provider

    def generate(
        self,
        *,
        workflow: str,
        workflow_version: str,
        prompt: Prompt,
        user_content: str,
        schema: dict[str, Any],
        offline: Callable[[], dict[str, Any]],
        retrieval_set: list[dict[str, Any]] | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int | None = None,
        force_offline: bool = False,
    ) -> LLMResult:
        s = self.settings
        model = model or s.llm_model
        effort = effort or s.llm_effort
        max_tokens = max_tokens or s.llm_max_tokens
        retrieval_set = retrieval_set or []
        config = {
            "effort": effort,
            "max_tokens": max_tokens,
            "thinking": "adaptive",
            "structured_output": True,
            "server_side_fallback": s.llm_server_side_fallback,
            "embedding_model": None,
            "model_workflow_version": f"{workflow}@{workflow_version}/{prompt.id}@{prompt.version}/{model}",
        }
        t0 = time.perf_counter()
        result: LLMResult
        status, error = "succeeded", None
        if self.provider == "offline" or force_offline:
            result = LLMResult(offline(), "offline", "offline-deterministic", "offline-deterministic", config={
                **config, "model_workflow_version": f"{workflow}@{workflow_version}/{prompt.id}@{prompt.version}/offline"})
        else:
            try:
                check_budget(self.db, self.tenant_id)
                result = self._call_anthropic(model, effort, max_tokens, prompt, user_content, schema, config)
            except BudgetExceeded as e:
                status, error = "budget_exceeded", str(e)
                result = self._degraded(offline, workflow, workflow_version, prompt, config)
            except LLMRefusal as e:
                status, error = "refused", str(e)
                result = self._degraded(offline, workflow, workflow_version, prompt, config)
            except Exception as e:  # noqa: BLE001 - model outage => deterministic degraded mode
                log.error("llm_call_failed", workflow=workflow, error=str(e))
                status, error = "failed", str(e)[:1000]
                result = self._degraded(offline, workflow, workflow_version, prompt, config)
        result.latency_ms = int((time.perf_counter() - t0) * 1000)
        cost = _cost(result.served_model, result.input_tokens, result.output_tokens, result.cache_read_tokens)
        rec = GenerationRecord(
            tenant_id=self.tenant_id,
            workflow=workflow,
            workflow_version=workflow_version,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            prompt_hash=prompt.hash,
            provider=result.provider,
            model=model if result.provider != "offline" else result.model,
            served_model=result.served_model,
            config=result.config,
            retrieval_set=retrieval_set,
            retrieval_set_hash=stable_hash(retrieval_set) if retrieval_set else None,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cost_usd=cost if result.provider == "anthropic" else 0.0,
            latency_ms=result.latency_ms,
            request_id=result.request_id,
            stop_reason=result.stop_reason,
            status=status if not result.degraded else f"degraded:{status}",
            error=error,
        )
        self.db.add(rec)
        if result.provider == "anthropic":
            self.db.add(UsageRecord(tenant_id=self.tenant_id, kind="llm", component=workflow, model=result.served_model,
                                    input_units=result.input_tokens, output_units=result.output_tokens, cost_usd=cost))
        self.db.flush()
        result.generation_id = rec.id
        LLM_CALLS.labels(workflow, result.served_model, rec.status).inc()
        LLM_TOKENS.labels(workflow, "input").inc(result.input_tokens)
        LLM_TOKENS.labels(workflow, "output").inc(result.output_tokens)
        LLM_LATENCY.labels(workflow).observe(result.latency_ms / 1000)
        return result

    def _degraded(self, offline, workflow, workflow_version, prompt, config) -> LLMResult:  # type: ignore[no-untyped-def]
        return LLMResult(offline(), "offline", "offline-deterministic", "offline-deterministic", degraded=True,
                         config={**config, "degraded": True,
                                 "model_workflow_version": f"{workflow}@{workflow_version}/{prompt.id}@{prompt.version}/offline"})

    def _call_anthropic(self, model: str, effort: str, max_tokens: int, prompt: Prompt, user_content: str,
                        schema: dict[str, Any], config: dict[str, Any]) -> LLMResult:
        client = _anthropic_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            # Stable, cacheable system prompt; untrusted evidence only ever appears in the user turn.
            "system": [{"type": "text", "text": prompt.text, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_content}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        }
        if self.settings.llm_server_side_fallback:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
            response = client.beta.messages.create(**kwargs)
        else:
            response = client.messages.create(**kwargs)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusal(f"model declined: {getattr(details, 'category', None)}")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailable("output truncated at max_tokens")
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        data = json.loads(text)
        usage = response.usage
        return LLMResult(
            data=data,
            provider="anthropic",
            model=model,
            served_model=getattr(response, "model", model),
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            request_id=getattr(response, "_request_id", None),
            stop_reason=response.stop_reason,
            config=config,
        )
