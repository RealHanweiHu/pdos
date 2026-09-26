"""Persist authenticated read-only Chat runs without fabricating business events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068_chat_request_runs"
down_revision: str | Sequence[str] | None = "0067_model_budget_reservation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KEYS = (
    "agent_key IN ('project_intelligence', 'knowledge_lite', 'engineering_intelligence', "
    "'quality_intelligence', 'supplier_intelligence', 'executive_intelligence')"
)
OLD_EVENTS = """CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN
event_count > 0 AND first_event_row_id > 0 AND last_event_row_id >= first_event_row_id
AND jsonb_array_length(event_row_ids) = event_count
AND (event_row_ids->>0)::bigint = first_event_row_id
AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id ELSE false END"""
EVENTS = f"""((agent_key = 'ai_chat' AND subscription_id IS NULL
AND first_event_row_id IS NULL AND last_event_row_id IS NULL
AND event_count = 0 AND event_row_ids = '[]'::jsonb
AND request_id IS NOT NULL AND btrim(request_id) <> ''
AND requested_by_user_id IS NOT NULL
AND status IN ('running', 'succeeded', 'degraded', 'failed')) OR
(agent_key <> 'ai_chat' AND subscription_id IS NOT NULL
AND request_id IS NULL AND requested_by_user_id IS NULL
AND first_event_row_id IS NOT NULL AND last_event_row_id IS NOT NULL
AND {OLD_EVENTS})) IS TRUE"""
WORKER_COLUMNS = """id, tenant_id, project_id, subscription_id, agent_key, status,
window_started_at, window_ended_at, first_event_row_id, last_event_row_id,
event_count, event_row_ids, context_version, run_context, started_at, completed_at,
error_code, created_at, updated_at"""


def replace_check(name: str, expression: str) -> None:
    op.drop_constraint(op.f(name), "agent_runs", schema="cehub_ai", type_="check")
    op.create_check_constraint(op.f(name), "agent_runs", expression, schema="cehub_ai")


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("request_id", sa.String(128)), schema="cehub_ai")
    op.add_column("agent_runs", sa.Column("requested_by_user_id", sa.Uuid()), schema="cehub_ai")
    for name, type_ in (
        ("subscription_id", sa.Uuid()),
        ("first_event_row_id", sa.BigInteger()),
        ("last_event_row_id", sa.BigInteger()),
    ):
        op.alter_column("agent_runs", name, nullable=True, existing_type=type_, schema="cehub_ai")
    replace_check("ck_agent_runs_agent_key_allowed", f"({OLD_KEYS}) OR agent_key = 'ai_chat'")
    replace_check("ck_agent_runs_event_bounds_consistent", EVENTS)
    op.create_foreign_key(
        "fk_agent_runs_tenant_request_user",
        "agent_runs",
        "users",
        ["tenant_id", "requested_by_user_id"],
        ["tenant_id", "id"],
        source_schema="cehub_ai",
        referent_schema="cehub_core",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_agent_runs_request",
        "agent_runs",
        ["tenant_id", "project_id", "agent_key", "request_id"],
        schema="cehub_ai",
    )
    # Existing worker installs must not inherit INSERT authority over new user identity columns.
    op.execute(f"""DO $body$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pdos_worker') THEN
            REVOKE INSERT ON cehub_ai.agent_runs FROM pdos_worker;
            GRANT INSERT ({WORKER_COLUMNS}) ON cehub_ai.agent_runs TO pdos_worker;
        END IF;
    END $body$;""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
        IF EXISTS (SELECT 1 FROM cehub_ai.agent_runs WHERE agent_key = 'ai_chat'
                   OR request_id IS NOT NULL OR requested_by_user_id IS NOT NULL) THEN
            RAISE EXCEPTION 'cannot discard persistent Chat request history';
        END IF;
    END $body$;""")
    op.drop_constraint("uq_agent_runs_request", "agent_runs", schema="cehub_ai", type_="unique")
    op.drop_constraint(
        "fk_agent_runs_tenant_request_user", "agent_runs", schema="cehub_ai", type_="foreignkey"
    )
    replace_check("ck_agent_runs_event_bounds_consistent", OLD_EVENTS)
    replace_check("ck_agent_runs_agent_key_allowed", OLD_KEYS)
    for name, type_ in (
        ("subscription_id", sa.Uuid()),
        ("first_event_row_id", sa.BigInteger()),
        ("last_event_row_id", sa.BigInteger()),
    ):
        op.alter_column("agent_runs", name, nullable=False, existing_type=type_, schema="cehub_ai")
    op.drop_column("agent_runs", "requested_by_user_id", schema="cehub_ai")
    op.drop_column("agent_runs", "request_id", schema="cehub_ai")
    op.execute("""DO $body$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pdos_worker') THEN
            GRANT INSERT ON cehub_ai.agent_runs TO pdos_worker;
        END IF;
    END $body$;""")
