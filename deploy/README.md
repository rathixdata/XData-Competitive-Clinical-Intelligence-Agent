# XData CI Agent: deployment and operations

This directory contains everything needed to run the platform, from a laptop up to production.

```
deploy/
  docker-compose.yml                 dev / pilot stack (postgres+pgvector, redis, minio, api, worker, beat, web)
  docker-compose.observability.yml   Prometheus + Grafana overlay
  postgres/init/01-init.sql          compose-only DB bootstrap (non-superuser app role + extensions)
  observability/                     Prometheus config + alert rules, Grafana provisioning + dashboard
  k8s/base, k8s/overlays/{staging,production}   kustomize manifests
  terraform/aws/                     VPC, EKS, RDS, ElastiCache, S3 (Object Lock), KMS, Secrets Manager, IRSA
```

## Environments

| | dev (local / pilot) | staging | production |
|---|---|---|---|
| Runtime | docker compose | EKS (`xdata-staging` ns) | EKS (`xdata` ns) |
| PostgreSQL 16 + pgvector | `pgvector/pgvector:pg16` container | RDS single-AZ | RDS **Multi-AZ**, 14-day PITR, deletion protection |
| Redis 7 | container | ElastiCache (TLS + AUTH), 1 node | ElastiCache (TLS + AUTH), primary + replica, auto-failover |
| Object store | MinIO (`xdata-ci-raw`) | S3 + Object Lock (30 d) | S3 + Object Lock COMPLIANCE (~7 y) + Glacier tiering |
| LLM / embeddings | `offline` / `hashing` (no keys needed) | Anthropic / Voyage | Anthropic / Voyage |
| Secrets | `.env` (never committed) | Secrets Manager -> external-secrets | Secrets Manager -> external-secrets |
| Deploy | `make up` | auto on `v*` tag / manual | after staging succeeds, **manual approval** (GitHub environment protection) |

### Local quick start

```bash
cp .env.example .env          # defaults run fully offline
make up                       # build + start; migrations run automatically (migrate service)
make seed                     # demo tenant
open http://localhost:8080    # UI;  API: http://localhost:8000/docs
make up-obs                   # + Prometheus :9090 / Grafana :3000 (dashboard "XData CI Agent - Operations")
```

The compose Postgres creates a **non-superuser** role `xdata` that owns the `xdata` database. This matters because tenant isolation uses Row-Level Security and superusers bypass RLS. Never point the app at the `postgres` superuser.

## Production database bootstrap (one time per environment)

RDS is created by Terraform with the admin user `xdata_admin`, whose password RDS manages in Secrets Manager. Connect as that admin once, for example from a bastion pod, and run:

```sql
CREATE ROLE xdata LOGIN PASSWORD '<generated>' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER DATABASE xdata OWNER TO xdata;
\c xdata
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector is a trusted extension on RDS PG16
CREATE EXTENSION IF NOT EXISTS pg_trgm;
ALTER SCHEMA public OWNER TO xdata;
-- read-only role for the logical-backup CronJob (needs BYPASSRLS to see all tenants)
CREATE ROLE xdata_backup LOGIN PASSWORD '<generated>' BYPASSRLS;
GRANT pg_read_all_data TO xdata_backup;
```

Then write the JSON app secret, using the keys listed in `k8s/base/externalsecret.yaml`:

```bash
aws secretsmanager put-secret-value --secret-id xdata/production/app --secret-string file://app-secret.json
```

Generate `XDATA_FIELD_ENCRYPTION_KEY` with `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`. The app refuses to start in production without `XDATA_JWT_SECRET`, `XDATA_FIELD_ENCRYPTION_KEY` and `XDATA_WEBHOOK_SIGNING_SECRET`.

## Deploy flow

1. **PR**: `ci.yml` runs lint, tests (real Postgres with pgvector + Redis), a migration reversibility check (upgrade, check, downgrade base, upgrade), the offline AI evaluation gate (`python -m evals.run --suite golden --offline`), frontend lint/type/test/build, and security scans (gitleaks, pip-audit, npm audit, Trivy, CodeQL).
2. **Merge to `main`**: images are pushed to GHCR as `:<sha>` and `:latest`, then scanned with Trivy.
3. **Tag `vX.Y.Z`, or run `deploy.yml` by hand**:
   - **staging**: GitHub OIDC assumes an AWS role, then `kustomize edit set image ...:<sha>`. The workflow deletes the old `xdata-migrate` Job, applies the new one alone and waits for it, then applies the rest and waits for the rollouts.
   - **production**: the same steps, gated by the `production` environment's required reviewers.
   - If a rollout fails, run the `rollback` job (`kubectl rollout undo`). Schema changes must be backward compatible (expand, then migrate, then contract), so rolling back never needs a schema downgrade.
   - When using Argo CD instead, the migrate Job carries `argocd.argoproj.io/hook: PreSync`.

Cluster prerequisites (installed once per cluster, outside this repo): ingress-nginx, cert-manager (`letsencrypt` / `letsencrypt-staging` ClusterIssuers), external-secrets, metrics-server, kube-prometheus-stack (load `observability/prometheus/alerts.yml` as a PrometheusRule), and the VPC CNI with network policy enabled (Terraform sets this).

## Backup, restore and DR

| Target | Value | Mechanism |
|---|---|---|
| **RPO** | **15 minutes** | RDS automated backups + continuous WAL archiving, which give point-in-time recovery for 14 days. Actual RPO is typically about 5 minutes. |
| **RTO** | **4 hours** | PITR restore to a new instance (about 30-90 min, depending on size), secret/endpoint switch, then app rollout and verification. |
| Secondary | 24 h | Nightly `pg_dump` CronJob to a separate, versioned, KMS-encrypted S3 bucket. Protects against account-level or accidental-deletion events. |
| Raw artifacts | no loss | S3 versioning + Object Lock COMPLIANCE. Objects cannot be deleted or overwritten before their retention expires. |
| Redis | not system of record | Holds queue and rate-limit state only; lost in-flight tasks are re-driven by beat schedules. |

### Quarterly restore test (mandatory; record results in the ops log)

1. **PITR drill**: `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier xdata-production --target-db-instance-identifier xdata-restore-test-<date> --restore-time <T-1h>`, into the same subnet group and security groups.
2. **Logical drill**: take the latest `pg_dump` from `s3://xdata-backups-prod/pg_dump/...` and run `pg_restore --no-owner -d <scratch db>` into a scratch PG16 instance that has `vector` and `pg_trgm` created.
3. Point a staging deployment, or a one-off `kubectl run` using the backend image, at the restored DB and run `alembic current` (it must equal head). Then check:
   - row counts per core table against production at the restore time (±expected delta);
   - that RLS still isolates tenants: query as `xdata` with two tenant contexts;
   - a sample of `source_documents` whose raw S3 objects resolve, with checksums that match.
4. Record the elapsed time for each step. It must stay within the **RTO of 4 h**, and the restore point within the **RPO of 15 min**.
5. Delete the restored instance, file findings, and update this runbook if anything changed.

### Full region / cluster loss

Recreate the infrastructure with `terraform apply -var-file=envs/production.tfvars`, which can target another region using cross-region snapshot copies if they are configured. Restore RDS from snapshot or PITR, re-populate Secrets Manager, then run `deploy.yml` with the last good image SHA.

## Observability

- **Metrics**: `GET /metrics` on the API. The Grafana dashboard `observability/grafana/dashboards/xdata-ops.json` covers API rate and p95 by route, connector runs and freshness, change and intel events, pipeline latency, LLM calls/tokens/latency, claim validation, alert deliveries, and retrieval latency.
- **Alerts**: `observability/prometheus/alerts.yml` fires on stale connectors (>6 h warning, >24 h critical), repeated connector failures, API 5xx >2%, p95 >2 s, alert pipeline p95 >15 min, LLM failure rate >10%, claim-rejection spikes, and dead-lettered alert deliveries.
- **Traces**: set `XDATA_OTEL_EXPORTER_OTLP_ENDPOINT`. The image includes the `otel` extra.
- **Logs**: JSON to stdout (`XDATA_LOG_JSON=true`), shipped by the cluster log agent.
