"""Prometheus metrics (NFR-OBS-001). Exposed at /metrics."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter("xdata_http_requests_total", "API requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "xdata_http_request_seconds",
    "API latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
CONNECTOR_HTTP_REQUESTS = Counter("xdata_connector_http_requests_total", "Upstream HTTP calls", ["connector", "status"])
CONNECTOR_RUNS = Counter("xdata_connector_runs_total", "Connector runs", ["connector", "status"])
CONNECTOR_RECORDS = Counter("xdata_connector_records_total", "Records processed", ["connector", "outcome"])
CONNECTOR_LAST_SUCCESS = Gauge("xdata_connector_last_success_timestamp", "Last successful run", ["connector"])
CHANGE_EVENTS = Counter("xdata_change_events_total", "Change events emitted", ["change_type", "suppressed"])
INTEL_EVENTS = Counter("xdata_intel_events_total", "Intelligence events", ["band"])
PIPELINE_LATENCY = Histogram(
    "xdata_pipeline_latency_seconds",
    "Latency between pipeline stages",
    ["stage"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 900, 1800, 3600),
)
LLM_CALLS = Counter("xdata_llm_calls_total", "LLM calls", ["workflow", "model", "status"])
LLM_TOKENS = Counter("xdata_llm_tokens_total", "LLM tokens", ["workflow", "direction"])
LLM_LATENCY = Histogram("xdata_llm_latency_seconds", "LLM latency", ["workflow"], buckets=(0.5, 1, 2, 5, 10, 20, 40, 80, 160))
RETRIEVAL_LATENCY = Histogram("xdata_retrieval_seconds", "RAG retrieval latency", buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2))
VALIDATION_OUTCOMES = Counter("xdata_claim_validation_total", "Claim validation outcomes", ["status"])
ALERT_DELIVERIES = Counter("xdata_alert_deliveries_total", "Alert deliveries", ["channel", "status"])
QUEUE_TASKS = Counter("xdata_tasks_total", "Background tasks", ["task", "status"])
