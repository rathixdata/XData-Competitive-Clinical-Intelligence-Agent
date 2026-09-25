# XData Competitive & Clinical Intelligence Agent

Evidence-grounded, continuously updated competitive intelligence for life sciences.

> **Product principle:** detect what changed, decide whether it matters to the customer's assets, show the
> evidence, keep fact and inference separate, and route the right intelligence to the right person.

This repository implements the full SRS v1.0 baseline (`docs/traceability.md` maps every requirement to its code and tests).
It covers source connectors, entity resolution and a knowledge graph, versioned snapshots and change detection,
materiality scoring and impact mapping, and a **RAG layer** with hybrid retrieval, claim-level provenance and an
independent evidence validator. On top of that sit Ask-the-Landscape, alerts, executive briefs, feedback learning, an
audit trail, multi-tenant isolation, and the deployment/CI needed to run it in production.

It is a decision-support system. It does not make clinical, regulatory, medical or investment decisions.

## Architecture at a glance

```
 ClinicalTrials.gov  PubMed  openFDA  SEC EDGAR  IR/Conference feeds
          │            │        │         │            │
          ▼            ▼        ▼         ▼            ▼
   ┌──────────── versioned source adapters (rate limits, retries, checkpoints, rights) ─────────────┐
   │ raw payload → content-addressed immutable object store (sha256) → SourceDocument             │
   └─────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 ▼
  normalize → entity resolution (aliases, confidence, review queue) → canonical store + knowledge graph
                                                 ▼
  SourceSnapshot (only when normalized state changes) → structured/document diff → ChangeEvent (fingerprinted)
                                                 │                    └──► RAG index (chunks + pgvector + tsvector)
                                                 ▼
  per-tenant landscape relevance → impact mapping (proximity rules + graph path) → materiality score (R,C,P,T,N)
                                                 ▼
  Impact Agent (Claude, grounded in S*/E* evidence) → Evidence Agent (deterministic + independent LLM judge)
                                                 ▼
  publish / block → alerts (web, email, Slack, Teams, signed webhook) · feed · dashboard · briefs · Ask
```

The LLM is never the system of record. Structured facts come from deterministic code; generated text is always
validated against retained evidence before anyone sees it. See `docs/architecture.md` and `docs/rag.md`.

## Repository layout

| Path | Contents |
|---|---|
| `backend/app/connectors` | Source adapters: ClinicalTrials.gov v2, PubMed E-utilities, openFDA Drugs@FDA + SPL labels, SEC EDGAR, permitted RSS/JSON feeds |
| `backend/app/pipeline` | Ingestion (raw retention → snapshot → diff → index → catalysts) and the intelligence pipeline |
| `backend/app/entities` | Alias normalization and resolution, review decisions, typed temporal knowledge graph |
| `backend/app/changes` | Change taxonomy, structured and document diff, noise suppression, fingerprints |
| `backend/app/materiality` | Proximity rules, explainable scoring, impact mapping, feedback-driven threshold tuning |
| `backend/app/rag` | Chunking, embeddings (Voyage / offline hashing), indexer, hybrid retriever, evidence objects |
| `backend/app/ai` | Claude client + governance, versioned prompts, Impact / Ask / Briefing agents, Evidence validator |
| `backend/app/alerts`, `reports` | Alert policies, digests, delivery channels; DOCX/PDF/PPTX/Markdown exports |
| `backend/app/api/v1` | FastAPI routers (123 operations, OpenAPI at `/api/v1/docs`) |
| `backend/alembic` | Migrations, including Postgres row-level security and the immutable audit log |
| `backend/tests` | 92 tests: unit, contract, regression, E2E acceptance, security/isolation, RAG, AI safety, explainability |
| `evals/` | Golden evaluation suite; the release gate for model, prompt and ranking changes |
| `frontend/` | React + TypeScript web app (all SRS §13 screens) |
| `deploy/` | docker compose, Kubernetes (kustomize), Terraform (AWS), observability |
| `docs/` | Architecture, RAG design, SRS traceability, security, runbook, OpenAPI |

## Quick start (local, no API keys needed)

Requirements: Docker with compose, or Python 3.11 + PostgreSQL 16 with pgvector + Redis 7.

```bash
cp .env.example .env
make up          # postgres+pgvector, redis, minio, migrate, api, worker, beat, web
make seed        # demo tenant: XD-101 vs 12 companies / 18 programs, runs the real pipeline
open http://localhost:8080    # tenant: demo-oncology  user: analyst@demo.example  pw: ChangeMe-Demo-2026!
```

By default the stack runs **offline**: `XDATA_LLM_PROVIDER=offline` produces deterministic, fact-only,
evidence-bound narratives, and `XDATA_EMBEDDING_PROVIDER=hashing` needs no model weights. For production RAG, set:

```bash
XDATA_LLM_PROVIDER=anthropic       XDATA_ANTHROPIC_API_KEY=...   # Claude (claude-opus-5 by default)
XDATA_EMBEDDING_PROVIDER=voyage    XDATA_VOYAGE_API_KEY=...      # voyage-3.5, 1024-d
XDATA_RERANK_ENABLED=true                                        # optional cross-encoder rerank
```

### Developing without Docker

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
# Postgres: CREATE ROLE xdata LOGIN PASSWORD 'xdata' (NOT superuser, so RLS applies);
#           CREATE DATABASE xdata OWNER xdata; CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;
cd backend && ../.venv/bin/alembic upgrade head && ../.venv/bin/python -m app.cli seed-demo
../.venv/bin/uvicorn app.main:app --reload          # API on :8000, docs at /api/v1/docs
cd ../frontend && npm ci && npm run dev              # UI on :5173
```

## Quality gates

```bash
make lint                      # ruff
make test                      # pytest against real Postgres, as the non-superuser role (RLS enforced)
python -m evals.run --suite golden --offline   # SRS §18 metrics; non-zero exit fails CI
```

The CI workflow (`.github/workflows/ci.yml`) runs:
- lint, migration reversibility and drift checks, backend tests with coverage, and the AI evaluation gate;
- frontend lint, typecheck, tests and build;
- security: gitleaks secret scanning, pip-audit, npm audit, Trivy, CodeQL;
- image builds.

Deploys (`deploy.yml`) go to staging automatically, to production after manual approval, and roll back automatically if anything fails.

## Key operational commands

```bash
python -m app.cli bootstrap --tenant acme --admin-email admin@acme.com   # onboard a tenant
python -m app.cli run-connector ctgov                                     # on-demand refresh
python -m app.cli process-changes                                         # drain the change queue
python -m app.cli verify-audit --tenant-id <uuid>                         # audit hash-chain check
python -m app.cli reembed                                                 # after an embedding-model upgrade
```

See `docs/runbook.md` for incident response, rollback, backups and restore tests.
