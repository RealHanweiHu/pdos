"""Append-only invocation drain fence for coordinated budget adoption."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064_model_call_fence"
down_revision: str | Sequence[str] | None = "0063_legacy_usage_accounting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = """
CREATE TABLE cehub_ai.model_call_sessions (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    run_id UUID,
    project_id UUID,
    agent_key VARCHAR(64) NOT NULL,
    execution_mode VARCHAR(16) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_model_call_sessions PRIMARY KEY (id),
    CONSTRAINT uq_model_call_sessions_tenant_id UNIQUE (tenant_id, id),
    CONSTRAINT fk_model_call_sessions_tenant_id_agent_runs FOREIGN KEY(tenant_id, run_id)
REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_model_call_sessions_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_model_call_sessions_mode_and_agent CHECK (execution_mode IN ('legacy',
'budgeted') AND btrim(agent_key) <> ''),
    CONSTRAINT fk_model_call_sessions_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES
cehub_core.tenants (id) ON DELETE RESTRICT
)

;

CREATE TABLE cehub_ai.model_call_events (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    session_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    state VARCHAR(16) NOT NULL,
    invocation_id UUID,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_model_call_events PRIMARY KEY (id),
    CONSTRAINT fk_model_call_events_tenant_id_model_call_sessions FOREIGN KEY(tenant_id,
session_id) REFERENCES cehub_ai.model_call_sessions (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_model_call_events_tenant_id_model_invocations FOREIGN KEY(tenant_id,
invocation_id) REFERENCES cehub_ai.model_invocations (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT uq_model_call_events_revision UNIQUE (tenant_id, session_id, revision),
    CONSTRAINT ck_model_call_events_lifecycle CHECK (revision > 0 AND ((state = 'closed' AND
invocation_id IS NOT NULL) OR (state IN ('open', 'unknown') AND invocation_id IS NULL)))
)

;

CREATE TABLE cehub_ai.model_call_mode_events (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    mode VARCHAR(16) NOT NULL,
    previous_mode VARCHAR(16) NOT NULL,
    target_mode VARCHAR(16),
    actor_user_id UUID NOT NULL,
    evidence_ref TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_model_call_mode_events PRIMARY KEY (id),
    CONSTRAINT fk_model_call_mode_events_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT uq_model_call_mode_revision UNIQUE (tenant_id, revision),
    CONSTRAINT ck_model_call_mode_events_mode_transition CHECK (revision > 0 AND previous_mode
IN ('compatibility', 'budgeted') AND btrim(evidence_ref) <> '' AND ((mode = 'draining' AND
target_mode IS NOT NULL AND target_mode IN ('compatibility', 'budgeted') AND target_mode <>
previous_mode) OR (mode IN ('compatibility', 'budgeted') AND target_mode IS NULL))),
    CONSTRAINT fk_model_call_mode_events_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES
cehub_core.tenants (id) ON DELETE RESTRICT
)

"""
FUNCTIONS = """CREATE FUNCTION cehub_ai.open_model_call(
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

CREATE FUNCTION cehub_ai.finish_model_call(wanted_tenant uuid, wanted_session uuid, trace_id
uuid)
RETURNS void LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog AS $body$
DECLARE last_event cehub_ai.model_call_events%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || wanted_tenant::text, 0));
    IF NOT EXISTS (
        SELECT 1 FROM cehub_ai.model_invocations AS trace
        JOIN cehub_ai.model_call_sessions AS call ON call.tenant_id = trace.tenant_id
            AND call.id = trace.model_call_session_id
        WHERE trace.tenant_id = wanted_tenant AND trace.id = trace_id
            AND call.id = wanted_session AND trace.run_id IS NOT DISTINCT FROM call.run_id
            AND trace.project_id IS NOT DISTINCT FROM call.project_id AND trace.agent_key =
call.agent_key
    ) THEN RAISE EXCEPTION 'Model call trace binding is invalid' USING ERRCODE = '42501'; END
IF;
    SELECT * INTO last_event FROM cehub_ai.model_call_events
      WHERE tenant_id = wanted_tenant AND session_id = wanted_session ORDER BY revision DESC
LIMIT 1;
    IF last_event.state = 'closed' THEN
        IF last_event.invocation_id <> trace_id THEN
            RAISE EXCEPTION 'Model call completion conflicts' USING ERRCODE = '42501';
        END IF;
        RETURN;
    END IF;
    INSERT INTO cehub_ai.model_call_events
        (id, tenant_id, session_id, revision, state, invocation_id, created_at)
        VALUES (gen_random_uuid(), wanted_tenant, wanted_session, last_event.revision + 1,
                'closed', trace_id, clock_timestamp());
END
$body$;
REVOKE ALL ON FUNCTION cehub_ai.finish_model_call(uuid, uuid, uuid) FROM PUBLIC;

CREATE FUNCTION cehub_ai.mark_model_call_unknown(wanted_tenant uuid, wanted_session uuid)
RETURNS void LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog AS $body$
DECLARE last_event cehub_ai.model_call_events%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || wanted_tenant::text, 0));
    SELECT * INTO last_event FROM cehub_ai.model_call_events
      WHERE tenant_id = wanted_tenant AND session_id = wanted_session ORDER BY revision DESC
LIMIT 1;
    IF NOT FOUND THEN RAISE EXCEPTION 'Model call scope invalid' USING ERRCODE = '42501'; END
IF;
    IF last_event.state <> 'open' THEN RETURN; END IF;
    INSERT INTO cehub_ai.model_call_events
        (id, tenant_id, session_id, revision, state, created_at)
        VALUES (gen_random_uuid(), wanted_tenant, wanted_session, last_event.revision + 1,
                'unknown', clock_timestamp());
END
$body$;
REVOKE ALL ON FUNCTION cehub_ai.mark_model_call_unknown(uuid, uuid) FROM PUBLIC;
"""


def upgrade() -> None:
    op.add_column(
        "model_invocations", sa.Column("model_call_session_id", sa.Uuid()), schema="cehub_ai"
    )
    op.execute(DDL)
    op.create_foreign_key(
        "fk_model_invocations_call_session",
        "model_invocations",
        "model_call_sessions",
        ["tenant_id", "model_call_session_id"],
        ["tenant_id", "id"],
        source_schema="cehub_ai",
        referent_schema="cehub_ai",
        ondelete="RESTRICT",
    )
    for name in ("model_call_sessions", "model_call_events", "model_call_mode_events"):
        op.execute(
            f"CREATE TRIGGER {name}_append_only BEFORE UPDATE OR DELETE ON cehub_ai.{name} "
            "FOR EACH ROW EXECUTE FUNCTION cehub_ai.reject_budget_history_mutation()"
        )
    op.execute(FUNCTIONS)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM cehub_ai.model_call_sessions) OR "
                "EXISTS (SELECT 1 FROM cehub_ai.model_call_mode_events)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: model call fence history exists")
    for signature in (
        "open_model_call(uuid, uuid, uuid, text, text)",
        "finish_model_call(uuid, uuid, uuid)",
        "mark_model_call_unknown(uuid, uuid)",
    ):
        op.execute(f"DROP FUNCTION cehub_ai.{signature}")
    op.drop_constraint(
        "fk_model_invocations_call_session",
        "model_invocations",
        schema="cehub_ai",
        type_="foreignkey",
    )
    op.drop_column("model_invocations", "model_call_session_id", schema="cehub_ai")
    for name in ("model_call_mode_events", "model_call_events", "model_call_sessions"):
        op.drop_table(name, schema="cehub_ai")
