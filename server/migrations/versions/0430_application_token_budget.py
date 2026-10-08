"""Optional application token ceilings, preserving original usage and execution guards."""

from importlib import import_module

from alembic import op
from sqlalchemy import Boolean, Column, text

revision = "0430_application_token_budget"
down_revision = "0429_preview_legacy_usage_holds"
branch_labels = None
depends_on = None

PREVIOUS = import_module("migrations.versions.0077_tool_dispatch_intents").RESERVE


def replace_once(body: str, before: str, after: str) -> str:
    assert body.count(before) == 1
    return body.replace(before, after, 1)


RESERVE = replace_once(
    PREVIOUS,
    "    current_daily_limit bigint;",
    """    current_daily_limit bigint;
    enforce_tokens boolean;""",
)
RESERVE = replace_once(
    RESERVE,
    "SELECT daily_token_budget INTO current_daily_limit FROM cehub_ai.tenant_model_settings",
    "SELECT daily_token_budget,token_budget_enforced INTO current_daily_limit,enforce_tokens "
    "FROM cehub_ai.tenant_model_settings",
)
RESERVE = replace_once(
    RESERVE,
    "    event_time := clock_timestamp();",
    """    -- Only server-authorized application runs may use this tenant option.
    -- Independent Agent budgets and unbound owner calls retain their ceilings.
    enforce_tokens := coalesce(enforce_tokens,true) OR NOT EXISTS (
      SELECT 1 FROM cehub_ai.application_authorizations
      WHERE tenant_id=wanted_tenant AND run_id=wanted_run
    );
    event_time := clock_timestamp();""",
)
RESERVE = replace_once(
    RESERVE,
    "    IF wanted_input > (profile->>'input_token_limit')::bigint\n"
    "       OR wanted_output > (profile->>'output_token_reserve')::bigint THEN",
    "    IF enforce_tokens AND (wanted_input > (profile->>'input_token_limit')::bigint\n"
    "       OR wanted_output > (profile->>'output_token_reserve')::bigint) THEN",
)
RESERVE = replace_once(
    RESERVE,
    "SELECT DISTINCT lineage_id FROM latest WHERE reservation_status IN ('reserved','unknown')",
    """SELECT DISTINCT j.lineage_id FROM latest j
        WHERE j.reservation_status IN ('reserved','unknown') AND NOT (
          NOT enforce_tokens AND j.reservation_status='unknown' AND j.call_kind='model'
          AND j.request_binding IS NOT NULL AND EXISTS (
            SELECT 1 FROM cehub_ai.agent_runs r
            JOIN cehub_ai.model_invocations i ON i.tenant_id=r.tenant_id AND i.run_id=r.id
            JOIN cehub_ai.model_call_sessions s ON s.tenant_id=i.tenant_id
              AND s.id=i.model_call_session_id AND s.run_id=r.id AND s.execution_mode='budgeted'
            WHERE r.tenant_id=j.tenant_id AND r.id=j.run_id
              AND r.status IN ('succeeded','degraded','failed') AND r.completed_at IS NOT NULL
              AND i.budget_call_id::text=j.request_binding->>'model_call_id'
              AND (SELECT e.state FROM cehub_ai.model_call_events e
                   WHERE e.tenant_id=s.tenant_id AND e.session_id=s.id
                   ORDER BY e.revision DESC LIMIT 1)='closed'
          )
        )""",
)
RESERVE = replace_once(
    RESERVE,
    "IF own_used + tokens > (profile->>'lineage_token_limit')::bigint THEN",
    "IF enforce_tokens AND own_used + tokens > (profile->>'lineage_token_limit')::bigint THEN",
)
RESERVE = replace_once(
    RESERVE,
    "IF cardinality(unresolved) > 0 THEN",
    "IF enforce_tokens AND cardinality(unresolved) > 0 THEN",
)
RESERVE = replace_once(
    RESERVE,
    "IF tenant_used + trace_tokens + tokens > least(caller_daily_limit,",
    "IF enforce_tokens AND tenant_used + trace_tokens + tokens > least(caller_daily_limit,",
)


def upgrade() -> None:
    op.add_column(
        "tenant_model_settings",
        Column("token_budget_enforced", Boolean, nullable=False, server_default=text("true")),
        schema="cehub_ai",
    )
    op.execute(RESERVE)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            text("""
        SELECT EXISTS (SELECT 1 FROM cehub_ai.tenant_model_settings
          WHERE NOT token_budget_enforced)
        OR EXISTS (SELECT 1 FROM cehub_audit.audit_log
          WHERE action='tenant_model_settings.update'
            AND after_snapshot->>'token_budget_enforced'='false')
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Application token budget policy history must be preserved")
    op.execute(PREVIOUS)
    op.drop_column("tenant_model_settings", "token_budget_enforced", schema="cehub_ai")
