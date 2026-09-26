"""Prevent untraced legacy calls from racing durable budget admission."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065_mixed_call_admission"
down_revision: str | Sequence[str] | None = "0064_model_call_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIOR_OPEN = """CREATE OR REPLACE FUNCTION cehub_ai.open_model_call(
    wanted_tenant uuid, wanted_run uuid, wanted_project uuid,
    wanted_agent text, wanted_mode text
) RETURNS TABLE (session_id uuid, error_code text)
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog AS $body$
DECLARE current_mode text; new_session uuid := gen_random_uuid();
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || wanted_tenant::text, 0));
    IF wanted_mode NOT IN ('legacy', 'budgeted') OR wanted_mode IS NULL
       OR wanted_agent IS NULL OR btrim(wanted_agent) = '' THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_SCOPE_INVALID'::text; RETURN;
    END IF;
    IF wanted_run IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM cehub_ai.agent_runs WHERE id = wanted_run AND tenant_id = wanted_tenant
          AND (wanted_project IS NULL OR project_id = wanted_project) AND agent_key =
wanted_agent
          AND status = 'running'
    ) THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_SCOPE_INVALID'::text; RETURN;
    END IF;
    SELECT mode INTO current_mode FROM cehub_ai.model_call_mode_events
      WHERE tenant_id = wanted_tenant ORDER BY revision DESC LIMIT 1;
    current_mode := coalesce(current_mode, 'compatibility');
    IF current_mode = 'draining' THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_DRAINING'::text; RETURN;
    END IF;
    IF current_mode = 'budgeted' AND wanted_mode <> 'budgeted' THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_BUDGET_REQUIRED'::text; RETURN;
    END IF;
    INSERT INTO cehub_ai.model_call_sessions
        (id, tenant_id, run_id, project_id, agent_key, execution_mode, created_at)
        VALUES (new_session, wanted_tenant, wanted_run, wanted_project,
                wanted_agent, wanted_mode, clock_timestamp());
    INSERT INTO cehub_ai.model_call_events
        (id, tenant_id, session_id, revision, state, created_at)
        VALUES (gen_random_uuid(), wanted_tenant, new_session, 1, 'open', clock_timestamp());
    RETURN QUERY SELECT new_session, NULL::text;
END
$body$;
REVOKE ALL ON FUNCTION cehub_ai.open_model_call(uuid, uuid, uuid, text, text) FROM PUBLIC;
"""
IN_FLIGHT = """CREATE FUNCTION cehub_ai.model_calls_in_flight(wanted_tenant uuid, wanted_mode text)
RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $body$
    SELECT EXISTS (
        SELECT 1 FROM cehub_ai.model_call_sessions AS call
        JOIN LATERAL (
            SELECT state FROM cehub_ai.model_call_events
            WHERE tenant_id = wanted_tenant AND session_id = call.id
            ORDER BY revision DESC LIMIT 1
        ) AS latest ON true
        WHERE call.tenant_id = wanted_tenant AND call.execution_mode = wanted_mode
          AND latest.state IN ('open', 'unknown')
    )
$body$;
REVOKE ALL ON FUNCTION cehub_ai.model_calls_in_flight(uuid, text) FROM PUBLIC;
"""
GUARDED_OPEN = """CREATE OR REPLACE FUNCTION cehub_ai.open_model_call(
    wanted_tenant uuid, wanted_run uuid, wanted_project uuid,
    wanted_agent text, wanted_mode text
) RETURNS TABLE (session_id uuid, error_code text)
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog AS $body$
DECLARE current_mode text; new_session uuid := gen_random_uuid();
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || wanted_tenant::text, 0));
    IF wanted_mode NOT IN ('legacy', 'budgeted') OR wanted_mode IS NULL
       OR wanted_agent IS NULL OR btrim(wanted_agent) = '' THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_SCOPE_INVALID'::text; RETURN;
    END IF;
    IF wanted_run IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM cehub_ai.agent_runs WHERE id = wanted_run AND tenant_id = wanted_tenant
          AND (wanted_project IS NULL OR project_id = wanted_project) AND agent_key =
wanted_agent
          AND status = 'running'
    ) THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_SCOPE_INVALID'::text; RETURN;
    END IF;
    SELECT mode INTO current_mode FROM cehub_ai.model_call_mode_events
      WHERE tenant_id = wanted_tenant ORDER BY revision DESC LIMIT 1;
    current_mode := coalesce(current_mode, 'compatibility');
    IF current_mode = 'draining' THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_DRAINING'::text; RETURN;
    END IF;
    IF current_mode = 'budgeted' AND wanted_mode <> 'budgeted' THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_BUDGET_REQUIRED'::text; RETURN;
    END IF;
    -- Both sides use the same tenant lock as the budget journal. A legacy
    -- response is not accounted until its trace is committed and session closed.
    IF wanted_mode = 'budgeted' AND cehub_ai.model_calls_in_flight(wanted_tenant, 'legacy') THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_LEGACY_IN_FLIGHT'::text; RETURN;
    END IF;
    IF wanted_mode = 'legacy' AND (
        cehub_ai.model_calls_in_flight(wanted_tenant, 'budgeted') OR EXISTS (
            SELECT 1 FROM (
                SELECT DISTINCT ON (attempt_id) reservation_status
                FROM cehub_ai.budget_journal WHERE tenant_id = wanted_tenant
                ORDER BY attempt_id, revision DESC
            ) AS latest WHERE reservation_status IN ('reserved', 'unknown')
        )
    ) THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_BUDGET_IN_FLIGHT'::text; RETURN;
    END IF;
    INSERT INTO cehub_ai.model_call_sessions
        (id, tenant_id, run_id, project_id, agent_key, execution_mode, created_at)
        VALUES (new_session, wanted_tenant, wanted_run, wanted_project,
                wanted_agent, wanted_mode, clock_timestamp());
    INSERT INTO cehub_ai.model_call_events
        (id, tenant_id, session_id, revision, state, created_at)
        VALUES (gen_random_uuid(), wanted_tenant, new_session, 1, 'open', clock_timestamp());
    RETURN QUERY SELECT new_session, NULL::text;
END
$body$;
REVOKE ALL ON FUNCTION cehub_ai.open_model_call(uuid, uuid, uuid, text, text) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(IN_FLIGHT)
    op.execute(GUARDED_OPEN)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM cehub_ai.model_call_sessions)"))
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: model call fence history exists")
    op.execute(PRIOR_OPEN)
    op.execute("DROP FUNCTION cehub_ai.model_calls_in_flight(uuid, text)")
