# Security and trust model (SRS §11)

| Threat / failure mode | Controls in this codebase |
|---|---|
| **Cross-tenant data leakage** | See "Cross-tenant data leakage" below. |
| **Prompt injection in source documents** | Retrieved text appears only inside delimited `<evidence>` blocks in the user turn, and closing tags inside it are neutralized. The system prompts say data is never instructions. The model has no tools, so injected text can't trigger actions. Outputs go through a strict JSON schema, and every factual claim is independently validated against evidence. The validator does not trust the generator. |
| **Hallucinated factual claim** | Verified changes are rendered deterministically. Numbers, dates and ids are checked against the cited evidence. An independent LLM judge reviews each claim. Unsupported claims are withheld, and a high-severity one blocks publication. The golden suite's hallucination-injection test is a CI gate. |
| **Incorrect entity mapping** | Confidence thresholds; review queue; development codes are never fuzzy-linked; analyst corrections are stored as decisions and reused; merge/split is audited; mapping rationale and graph path are shown on every event. |
| **Compromised source / API** | TLS only; credentials in Secrets Manager (rotatable); raw payloads kept content-addressed with sha256 checksums and verified on reconstruction; per-connector anomaly signals (record counts, error rates) in metrics and alerts; rights metadata on every artifact. |
| **Malicious user query** | Authorization-aware retrieval (RLS + filters); per-user rate limits on API, Ask and login; every question is audited; input size limits. |
| **Sensitive internal strategy exposure** | Internal assets and notes are tenant-private rows; RBAC; field encryption for destinations/credentials; configurable retention; **no training on customer data**. The Anthropic API is used without fine-tuning, and `allow_training_on_customer_data=false`. |
| **Stale intelligence** | Freshness SLO per connector; `stale` state and a global banner on the dashboard; stale warnings in Ask limitations and matrix rows; Prometheus alert rules. |

## Cross-tenant data leakage

- **Row-level security.** Postgres policies use `FORCE ROW LEVEL SECURITY`, and the app connects as a
  non-superuser, non-BYPASSRLS role.
- **Tenant context.** Every session sets its tenant context before any query runs.
- **Defence in depth.** Application code also filters every query by tenant.
- **Tests.** Isolation is verified at both layers:
  - API: `test_cross_tenant_api_isolation`
  - raw SQL: `test_rls_blocks_cross_tenant_rows_at_database_level`
  - RAG retrieval with a forged tenant id: `test_hybrid_retrieval_relevance_and_tenant_isolation`

- **Shared public corpus.** Public records are fetched once and shared across tenants. The provenance that could
  reveal *what another customer monitors* (PubMed query strings, landscape ids, connector run parameters and error
  details) is visible only to platform administrators (`redact_provenance`). The corpus itself still shows which
  public records the platform has fetched. Customers who need that hidden too should use a dedicated deployment
  (`deployment_mode=dedicated`, a separate stack from the same manifests).

## Authentication and authorization

- **OIDC/SSO.** RS256/ES256 tokens are validated against the IdP JWKS, checking issuer and audience. Tenant and roles
  come from configurable claims. Users are provisioned just-in-time as `viewer` unless the IdP supplies roles.
  MFA can be enforced through the `amr` claim (`XDATA_OIDC_REQUIRE_MFA`).
- **Local login.** For bootstrap and non-SSO pilots only; production can disable it
  (`XDATA_LOCAL_AUTH_ENABLED=false`). Passwords are hashed with argon2id, and login attempts are rate-limited per
  account.
- **API keys.** Stored only as a sha256 hash, with a prefix index. Keys expire, can be revoked, and can only narrow
  their owner's roles.
- **RBAC.** Role → permission mapping in `app/core/rbac.py`, enforced on every route with `require(Perm.X)`.
  Platform-level operations (global connector configuration, global entity curation) require `platform_admin`.

## Data protection

- **In transit:** TLS everywhere (ingress, RDS `sslmode`, ElastiCache TLS).
- **At rest:** KMS for RDS, S3 (SSE-KMS + Object Lock) and ElastiCache.
- **Application-level:** Fernet encryption for alert destinations and connector credentials; the key lives in
  Secrets Manager.
- **Logs:** the structlog processor redacts authorization headers, keys, passwords, tokens and webhook URLs.
- **Secrets hygiene:** gitleaks in CI and pre-commit. Production refuses to start with default secrets.

## Audit

- **What is recorded:** security-sensitive, administrative and editorial actions, including login success and
  failure, key management, landscape/watchlist/policy changes, entity curation, narrative edits and approvals,
  report approval and distribution, exports, raw downloads and connector operations.
- **Tamper protection:** the log is hash-chained per tenant and cannot be updated or deleted by the application
  role. `GET /api/v1/audit/verify` and `python -m app.cli verify-audit` recompute the chain.

## Outbound webhooks

Payloads are signed with `X-XData-Signature: sha256=HMAC(secret, timestamp + "." + body)` and carry an
`X-XData-Timestamp` header. Receivers should reject timestamps older than 5 minutes. In production, only `https`
destinations are allowed.

## Supply chain

- Dependabot covers pip, npm, GitHub Actions and Docker.
- CI runs pip-audit, npm audit, Trivy on the filesystem and images, and CodeQL.
- Images are multi-stage and non-root, with a read-only root filesystem in Kubernetes.
