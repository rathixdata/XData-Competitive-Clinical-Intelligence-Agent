# Architecture

## Layers (SRS §6)

| Layer | Implementation |
|---|---|
| Source adapters | `app/connectors/*`. A versioned `SourceAdapter` contract covers plan, fetch, parse, rights and checkpoint. `SourceHttpClient` adds a token-bucket rate limit (Redis-shared across replicas), exponential backoff with jitter, and `Retry-After` handling. |
| Normalization | Adapter `parse()` produces canonical `NormalizedRecord`s. `pipeline/normalize.py` handles dates, phases, statuses and text canonicalization. |
| Entity resolution | `entities/resolver.py`. Order of precedence: analyst decisions, then exact/normalized alias, then pg_trgm + rapidfuzz fuzzy match. Every link carries a confidence and a method. Links below 0.92 go to a review queue; development codes never fuzzy auto-link. |
| Operational store | PostgreSQL 16 (46 tables), SQLAlchemy 2, Alembic. Row-level security isolates tenants (`alembic/versions/0002`). |
| Object store | `storage/object_store.py`. Raw payloads are content-addressed by sha256 and written once. S3 (SSE-KMS, Object Lock) in production; a read-only local FS in development. |
| Knowledge graph | `relationships` table: typed, temporal (`valid_from`/`valid_to`), with confidence, method and evidence. BFS path finding in `entities/graph.py`. |
| Change engine | `changes/diff.py`: structured field diff, sentence-level document diff, suppression of formatting-only, ordering-only and equivalent changes, and fingerprinted idempotency (`INSERT … ON CONFLICT DO NOTHING`). |
| Materiality engine | `materiality/scoring.py` (R, C, P, T, N plus a magnitude gate, with per-landscape weights and bands), `proximity.py`, `mapping.py`, `tuning.py`. |
| Agent orchestration | `ai/agents/impact.py`, `ask.py`, `briefing.py`. These are bounded services, not an autonomous agent (SRS §12). |
| Evidence validator | `ai/validator.py`: deterministic checks plus an independent LLM judge, with a publication gate. |
| Experience layer | FastAPI (`api/v1`), React SPA (`frontend/`), alerts and exports. |
| Platform services | JWT / OIDC SSO / API keys, RBAC (`core/rbac.py`), hash-chained audit log, Prometheus metrics, OpenTelemetry traces, Celery queues. |

## Agents and write permissions (SRS §12)

| Component | Code | Writes source-of-truth? |
|---|---|---|
| Source Agent | connectors + `pipeline/ingest.py` | Retained artifacts only, through the deterministic pipeline |
| Entity Agent | `EntityResolver` | Auto-links only above the confidence threshold; everything else waits for human approval |
| Trial Change / Literature / Regulatory Agent | `ai/agents/impact.py`, which varies its instructions by object type | No |
| Impact Agent | `materiality/mapping.py` (deterministic) + `impact.py` (hypotheses) | No (only the derived, tenant-scoped `competes_with` edges, with their rule version) |
| Evidence Agent | `ai/validator.py` | No |
| Briefing Agent | `ai/agents/briefing.py` | No (drafts need human approval before distribution) |

## Data flow timing (NFR-ALT-001)

Celery beat triggers `process_changes_task` every 60 s, and every connector run also enqueues it. That keeps a
structured change's path from fetch to alert eligibility well under 15 minutes.

Each event carries its own latency record in `source_fetched_at`, `detected_at`, `scored_at`, `published_at` and
`alert_eligible_at`. Prometheus exposes the same latency as the histogram
`xdata_pipeline_latency_seconds{stage="source_fetch_to_alert"}`, and an alert rule fires above 15 minutes.

## Tenancy model

- **Public corpus:** trials, publications, FDA objects, disclosures, source documents, snapshots and change events.
  Fetched once and shared by every tenant.
- **Shared-with-private-rows:** companies, assets, concepts, aliases, links, relationships, catalysts and chunks.
  `tenant_id IS NULL` marks a public row; a non-null value marks a tenant-private row. The customer's internal
  assets (e.g. XD-101), analyst alias corrections and derived `competes_with` edges live here.
- **Strict tenant tables:** landscapes, intelligence events, narratives, claims, feedback, alerts, reports, users
  and everything else a customer creates.

Every API request opens a session with `set_config('app.current_tenant', …)`, so Postgres enforces isolation even
if an application query forgets a filter. The workers process public data with an explicit RLS bypass, but switch
to the tenant's context (bypass off) before creating tenant intelligence.

## Scalability (NFR-SCL-001)

The API is stateless (HPA). Workers are split across queues (`ingest`, `intel`, `alerts`, `default`) and scale
independently.

- **Connector throttling** is shared through Redis, so adding replicas never multiplies the upstream request rate.
- **Overlapping batch runs** are prevented with advisory locks.
- **Row locks:** `FOR UPDATE SKIP LOCKED` protects the change and notification queues.
- **Vector search** uses an HNSW index; lexical search uses GIN on a stored `tsvector`.

For 10× the pilot volume, scale the worker replicas and RDS instance class. No redesign is needed.
