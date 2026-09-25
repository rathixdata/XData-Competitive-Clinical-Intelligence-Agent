# Operations runbook

## Service map

| Component | Scale | Health |
|---|---|---|
| `api` (FastAPI/uvicorn) | HPA 2-10 | `/healthz` liveness, `/readyz` (DB + Redis) |
| `worker` (Celery: `ingest`, `intel`, `alerts`, `default`) | HPA 2-8 | queue depth, `xdata_tasks_total` |
| `beat` (scheduler) | exactly 1 (Recreate) | `dispatch-due-connectors` every 60 s |
| `web` (nginx SPA) | 2 | `/` |
| PostgreSQL 16 + pgvector (RDS) | Multi-AZ | RDS metrics |
| Redis (ElastiCache) | primary + replica | broker + shared rate limits |
| S3 raw bucket | Object Lock | versioned, immutable |

## Severity levels and incident process

| Sev | Definition | Response |
|---|---|---|
| SEV1 | Cross-tenant exposure, data loss, platform down, or a published unsupported high-severity claim | Page on-call immediately; incident commander; customer comms within 1 h; postmortem within 5 business days |
| SEV2 | Alert pipeline latency > 15 min for > 1 h, a primary connector failing > SLO, or LLM outage (degraded mode active) | On-call within 30 min; status banner |
| SEV3 | Single connector degraded, UI defect, or elevated validation withholds | Next business day |

Every incident gets:
- an owner and a timeline in the incident channel;
- customer communication through the status page for SEV1/2;
- a blameless postmortem with action items tracked to closure.

## Common procedures

**Connector stale or failing** (`XDataConnectorStale` / `XDataConnectorFailures` alerts)
1. `GET /api/v1/admin/connectors/{key}/runs`. Check `error_detail` and `message`.
2. **Upstream schema change** (parse errors on every record): the adapter version needs updating. Disable the
   connector (`PATCH /admin/connectors/{key} {"enabled": false}`) so the dashboard shows it as disabled rather than
   silently stale. Ship the adapter fix behind a feature flag, then run it on demand
   (`POST /admin/connectors/{key}/run`).
3. **Rate limited** (many 429s in `xdata_connector_http_requests_total`): lower `rate_limit_per_sec`.
4. Users see the stale banner automatically; no manual comms are needed for SEV3.

**LLM provider outage or refusals**
- The platform degrades to deterministic, evidence-only narratives on its own. Generation records show
  `status=degraded:*`, and `xdata_llm_calls_total{status!="succeeded"}` rises.
- Nothing unsupported is published. When the provider recovers, regenerate affected events with
  `POST /events/{id}/regenerate`.

**Alert backlog / pipeline latency** (`XDataAlertLatencyHigh`)
- Scale the `worker` deployment (intel queue).
- Check for a long-running group in the logs (`intel_group_failed`).
- Dead-lettered deliveries: `GET /alerts/deliveries?status=dead`. Fix the destination, then reset the notification
  to `pending`.

**Blocked publications**
- The feed filter `status=blocked` lists the events.
- Each event detail shows `publication_blocked_reason` and the withheld claims. The analyst edits and approves
  the narrative (`PUT /events/{id}/narrative`, then `/review`).

## Deployments and rollback

- **Deploy:** CI builds the images, then `deploy.yml` applies config, runs the migration Job, applies the
  workloads, waits for rollout and smoke-tests.
- **Rollback:** any failed step triggers `kubectl rollout undo` automatically; the workflow also has a manual
  `rollback` action.
- **Migrations:** Alembic, reversible where feasible. CI runs upgrade → check → downgrade → upgrade. Every
  migration must be backward compatible with the previous app version (expand/contract), so an app rollback never
  needs a schema rollback.
- **Feature flags:** new connectors, models and ranking changes ship behind flags (`feature_flags`,
  `connector_configs.enabled`). Model, prompt and ranking promotions also require the golden evaluation suite to
  pass (`python -m evals.run --suite golden`) and a `model_releases` promotion for thresholds.

## Backup and recovery (NFR-DR-001)

- **RPO 15 min.** RDS point-in-time recovery; daily automated snapshots kept 14 days; a weekly logical `pg_dump`
  CronJob to S3.
- **RTO 4 h.** Restore to a new instance, repoint the secret, then roll the deployments.
- **Raw artifacts** are protected by S3 versioning + Object Lock. Everything derivable (snapshots, chunks,
  embeddings) can be rebuilt from the raw artifacts and connector reruns.
- **Quarterly restore test:**
  1. Restore the latest PITR to a scratch instance.
  2. Run `alembic current` and a migration check.
  3. Run `python -m app.cli verify-audit` for each tenant.
  4. Spot-check that five random raw artifacts reconstruct with `/trials/{ref}/snapshots/{v}?include_raw=true`
     (checksum verified).
  5. Record the timings against RPO/RTO in the DR log.

## Performance and load testing (NFR-PERF-001, NFR-SCL-001)

`deploy/loadtest/locustfile.py` simulates analysts working the feed, event detail, dashboard and Ask.
**Target:** p95 under 2 s for reads at 10× pilot volume. Run it against staging before GA:

```
locust -f deploy/loadtest/locustfile.py --host https://staging.xdata.example.com --users 200 --spawn-rate 10
```

## Cost controls

- **Budgets:** monthly LLM budget per tenant (`PATCH /admin/settings {"llm_monthly_budget_usd": ...}`).
- **Usage:** broken down by component and model at `GET /admin/usage`.
- **Model routing:** narratives use the LLM only at Analyst Review and above; lower bands use the deterministic
  builder.
- **Prompt caching:** the stable system prompts are cached.
