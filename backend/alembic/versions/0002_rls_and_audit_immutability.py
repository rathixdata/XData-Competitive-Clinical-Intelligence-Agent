"""Row-level security (tenant isolation), immutable audit log, raw-artifact immutability.

NFR-SEC-001: tenant isolation is enforced by Postgres RLS in addition to application filters.
NFR-AUD-001: audit_log rows cannot be updated or deleted by the application role.
FR-SRC-008: source_documents / source_snapshots are append-only.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

STRICT_TABLES = [
    "users", "api_keys", "idempotency_keys", "usage_records", "profile_field_definitions",
    "intelligence_events", "generation_records", "generated_artifacts", "claims", "feedback",
    "feedback_datasets", "model_releases", "ask_sessions", "ask_turns", "landscapes",
    "landscape_members", "watchlists", "watchlist_items", "proximity_rules", "saved_views",
    "alert_policies", "notifications", "notified_event_state", "reports",
]
SHARED_TABLES = [
    "companies", "assets", "asset_profile_versions", "concepts", "catalysts", "entity_aliases",
    "entity_links", "relationships", "document_chunks", "feature_flags",
]
APPEND_ONLY_TABLES = ["source_documents", "source_snapshots"]


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION xdata_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('app.current_tenant', true), '')::uuid $$;
        CREATE OR REPLACE FUNCTION xdata_rls_bypass() RETURNS boolean
        LANGUAGE sql STABLE AS $$ SELECT coalesce(current_setting('app.bypass_rls', true), 'off') = 'on' $$;
        """
    )
    for t in STRICT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING (xdata_rls_bypass() OR tenant_id = xdata_current_tenant()) "
            f"WITH CHECK (xdata_rls_bypass() OR tenant_id = xdata_current_tenant())"
        )
    for t in SHARED_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_or_public ON {t} "
            f"USING (xdata_rls_bypass() OR tenant_id IS NULL OR tenant_id = xdata_current_tenant()) "
            f"WITH CHECK (xdata_rls_bypass() OR tenant_id = xdata_current_tenant())"
        )

    # Audit log: tenants read only their own rows; anyone may append; nobody may modify.
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY audit_read ON audit_log FOR SELECT USING (xdata_rls_bypass() OR tenant_id = xdata_current_tenant())"
    )
    op.execute("CREATE POLICY audit_append ON audit_log FOR INSERT WITH CHECK (true)")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION xdata_block_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION xdata_block_mutation()"
    )
    for t in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {t}_immutable BEFORE UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION xdata_block_mutation()"
        )

    # Trigram index for fuzzy alias lookups (FR-ENT-002)
    op.execute("CREATE INDEX IF NOT EXISTS ix_alias_norm_trgm ON entity_aliases USING gin (alias_norm gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_alias_norm_trgm")
    for t in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {t}_immutable ON {t}")
    op.execute("DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log")
    op.execute("DROP POLICY IF EXISTS audit_read ON audit_log")
    op.execute("DROP POLICY IF EXISTS audit_append ON audit_log")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")
    for t in STRICT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    for t in SHARED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_or_public ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS xdata_block_mutation()")
    op.execute("DROP FUNCTION IF EXISTS xdata_rls_bypass()")
    op.execute("DROP FUNCTION IF EXISTS xdata_current_tenant()")
