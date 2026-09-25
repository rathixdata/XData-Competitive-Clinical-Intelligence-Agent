"""Application configuration.

All settings come from environment variables (12-factor). Secrets are expected to be
injected by a managed secrets facility (Kubernetes Secrets synced from AWS Secrets
Manager / Vault / GCP Secret Manager) - they are never committed to source (NFR-SEC-005).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XDATA_", env_file=".env", extra="ignore", env_ignore_empty=True)

    # ---- runtime -------------------------------------------------------------
    env: Literal["development", "test", "staging", "production"] = "development"
    service_name: str = "xdata-ci-agent"
    log_level: str = "INFO"
    log_json: bool = True
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    public_base_url: str = "http://localhost:5173"

    # ---- data stores ---------------------------------------------------------
    database_url: str = "postgresql+psycopg://xdata:xdata@localhost:5432/xdata"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_statement_timeout_ms: int = 15000
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_eager: bool = False

    # object store (raw immutable retention, FR-SRC-008)
    object_store_backend: Literal["local", "s3"] = "local"
    object_store_local_path: str = "./.data/objects"
    s3_bucket: str = "xdata-ci-raw"
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_kms_key_id: str | None = None

    # ---- security ------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("dev-only-change-me-dev-only-change-me")
    jwt_issuer: str = "xdata-ci-agent"
    jwt_audience: str = "xdata-ci-api"
    access_token_ttl_minutes: int = 60
    # Enterprise SSO (NFR-SEC-002): if set, bearer tokens are validated against the IdP JWKS.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_tenant_claim: str = "xdata_tenant"
    oidc_roles_claim: str = "xdata_roles"
    oidc_require_mfa: bool = False
    local_auth_enabled: bool = True
    # Fernet key used for application-level encryption of stored credentials/webhook URLs.
    field_encryption_key: SecretStr | None = None
    api_rate_limit_per_minute: int = 300
    ask_rate_limit_per_minute: int = 20
    login_rate_limit_per_minute: int = 10

    # ---- LLM / RAG -----------------------------------------------------------
    llm_provider: Literal["anthropic", "offline"] = "offline"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5"
    llm_validator_model: str = "claude-opus-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    llm_validator_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_max_tokens: int = 16000
    llm_timeout_seconds: float = 180.0
    llm_server_side_fallback: bool = True
    # Per-tenant monthly LLM budget in USD; 0 disables the guard.
    llm_monthly_budget_usd: float = 0.0

    embedding_provider: Literal["voyage", "hashing"] = "hashing"
    voyage_api_key: SecretStr | None = None
    embedding_model: str = "voyage-3.5"
    embedding_dim: int = 1024
    rerank_enabled: bool = False
    rerank_model: str = "rerank-2.5"
    rag_top_k: int = 12
    rag_candidate_k: int = 60
    rag_chunk_tokens: int = 350
    rag_chunk_overlap: int = 60
    rag_rrf_k: int = 60

    # ---- connectors ----------------------------------------------------------
    ncbi_api_key: SecretStr | None = None
    ncbi_tool: str = "xdata-ci-agent"
    ncbi_email: str = "ops@example.com"
    openfda_api_key: SecretStr | None = None
    sec_user_agent: str = "XData CI Agent ops@example.com"
    connector_http_timeout: float = 30.0
    connector_user_agent: str = "XData-CI-Agent/1.0 (+https://xdata.example.com)"

    # ---- alert delivery ------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "intelligence@xdata.example.com"
    webhook_signing_secret: SecretStr = SecretStr("dev-webhook-secret")

    # ---- observability -------------------------------------------------------
    otel_exporter_otlp_endpoint: str | None = None
    metrics_enabled: bool = True

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.env == "production":
            if self.jwt_secret.get_secret_value().startswith("dev-only"):
                raise ValueError("XDATA_JWT_SECRET must be set in production")
            if self.field_encryption_key is None:
                raise ValueError("XDATA_FIELD_ENCRYPTION_KEY must be set in production")
            if self.webhook_signing_secret.get_secret_value() == "dev-webhook-secret":
                raise ValueError("XDATA_WEBHOOK_SIGNING_SECRET must be set in production")
        return self

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
