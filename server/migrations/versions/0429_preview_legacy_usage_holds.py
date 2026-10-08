# ruff: noqa: E501
"""Approved, append-only conservative bounds for three local-preview traces."""

from importlib import import_module

from alembic import op
from sqlalchemy import text
from sqlalchemy.schema import CreateTable

revision = "0429_preview_legacy_usage_holds"
down_revision = "0428_preproject_dialogue"
branch_labels = None
depends_on = None

PREVIOUS = import_module("migrations.versions.0067_model_budget_reservation").ACCOUNTING
ACCOUNTING = (
    PREVIOUS.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    .replace(
        "SELECT t.*, r.id AS resolution_id, r.input_tokens + r.output_tokens AS resolved_tokens",
        "SELECT t.*, r.id AS resolution_id, r.input_tokens + r.output_tokens AS resolved_tokens, "
        "h.id AS hold_id, h.input_token_bound + h.output_token_bound AS held_bound, "
        "h.budget_period_start AS hold_period",
    )
    .replace(
        "CROSS JOIN boundary b WHERE t.tenant_id",
        "LEFT JOIN cehub_ai.legacy_usage_holds h ON h.tenant_id=t.tenant_id AND h.invocation_id=t.id "
        "CROSS JOIN boundary b WHERE t.tenant_id",
    )
    .replace(
        "r.created_at >= b.day OR (r.id IS NULL AND (",
        "(CASE WHEN h.id IS NOT NULL THEN h.budget_period_start ELSE r.created_at END) >= b.day "
        "OR (r.id IS NULL AND (",
    )
    .replace(
        "WHEN resolution_id IS NOT NULL THEN resolved_tokens",
        "WHEN resolution_id IS NOT NULL THEN CASE WHEN hold_id IS NULL OR hold_period >= day "
        "THEN resolved_tokens ELSE 0 END "
        "WHEN hold_id IS NOT NULL THEN CASE WHEN hold_period >= day THEN held_bound ELSE 0 END",
    )
    .replace(
        "AND resolution_id IS NULL AND usage_status",
        "AND resolution_id IS NULL AND hold_id IS NULL AND usage_status",
    )
)

GUARD = """
CREATE FUNCTION cehub_ai.guard_preview_legacy_hold() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE t cehub_ai.model_invocations%ROWTYPE; current_state text;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Legacy usage holds are append-only'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:'||NEW.tenant_id::text,0));
 IF NEW.tenant_id <> 'cc87e1fc-cc18-486e-89c1-56a8be1fb11d'::uuid
 OR NEW.invocation_id NOT IN ('c5ac39e4-af83-4911-b40c-236ee4066c24'::uuid,
 '95fe9204-c8f3-4aa6-a870-c51123a08833'::uuid,'a3b1253d-1c28-4272-92e9-4175ab9fdbfc'::uuid)
 OR NOT EXISTS (SELECT 1 FROM cehub_core.users WHERE tenant_id=NEW.tenant_id
   AND id=NEW.reviewer_user_id AND is_active AND role IN ('owner','admin'))
 THEN RAISE EXCEPTION 'LEGACY_HOLD_SCOPE_OR_ROLE_INVALID'; END IF;
 SELECT * INTO t FROM cehub_ai.model_invocations WHERE tenant_id=NEW.tenant_id AND id=NEW.invocation_id;
 SELECT state INTO current_state FROM cehub_ai.model_call_events
 WHERE tenant_id=NEW.tenant_id AND session_id=t.model_call_session_id ORDER BY revision DESC LIMIT 1;
 IF t.id IS NULL OR t.provider<>'minimax' OR t.model<>'MiniMax-M3'
 OR t.protocol<>'openai-compatible' OR t.budget_call_id IS NOT NULL
 OR t.usage_status <> 'unknown' OR t.input_meter_version<>'normalized_input.v1'
 OR t.status<>'provider_error' OR t.error_code IS DISTINCT FROM 'PROVIDER_TRANSPORT_ERROR'
 OR t.structured_attempts<>1 OR current_state IS DISTINCT FROM 'closed'
 OR date_trunc('day',t.created_at AT TIME ZONE 'UTC') <> timestamp '2026-10-06'
 OR NEW.budget_period_start <> date_trunc('day',t.created_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
 OR EXISTS (SELECT 1 FROM cehub_ai.legacy_usage_resolutions WHERE tenant_id=NEW.tenant_id AND invocation_id=t.id)
 THEN RAISE EXCEPTION 'LEGACY_HOLD_TARGET_INVALID'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER preview_legacy_hold_guard BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_ai.legacy_usage_holds FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_preview_legacy_hold();
REVOKE ALL ON cehub_ai.legacy_usage_holds FROM PUBLIC,pdos_agent;
REVOKE ALL ON FUNCTION cehub_ai.guard_preview_legacy_hold() FROM PUBLIC,pdos_agent;
"""


def upgrade() -> None:
    from app.db.schema import tables

    op.execute(str(CreateTable(tables.legacy_usage_holds).compile(dialect=op.get_bind().dialect)))
    op.execute(GUARD)
    op.execute(ACCOUNTING)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(text("SELECT EXISTS(SELECT 1 FROM cehub_ai.legacy_usage_holds)"))
        .scalar_one()
    ):
        raise RuntimeError("Legacy usage hold history must be preserved")
    op.execute(PREVIOUS.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    op.execute("DROP TABLE cehub_ai.legacy_usage_holds")
    op.execute("DROP FUNCTION cehub_ai.guard_preview_legacy_hold()")
