-- Revert only the PDOS S2-2b Agent runtime grants and database objects.
-- This intentionally does not drop login roles or passwords owned by the DBA.

BEGIN;

DROP POLICY IF EXISTS pdos_agent_insert_model_invocations
    ON cehub_ai.model_invocations;
ALTER TABLE cehub_ai.model_invocations DISABLE ROW LEVEL SECURITY;

DROP VIEW IF EXISTS
    cehub_ai.agent_run_usage_projection,
    cehub_ai.agent_model_usage_projection,
    cehub_ai.agent_model_settings_projection,
    cehub_ai.agent_event_projection,
    cehub_ai.agent_gate_projection,
    cehub_ai.agent_task_projection,
    cehub_ai.agent_risk_projection,
    cehub_ai.agent_issue_projection,
    cehub_ai.agent_project_projection,
    cehub_ai.agent_run_projection;

DROP FUNCTION IF EXISTS cehub_ai.fail_agent_run(uuid, uuid, varchar, timestamptz);
DROP FUNCTION IF EXISTS cehub_ai.create_agent_finding(
    uuid, uuid, uuid, uuid, varchar, varchar, varchar, text, jsonb, jsonb,
    smallint, varchar, timestamptz
);
DROP FUNCTION IF EXISTS cehub_ai.complete_agent_run(
    uuid, uuid, varchar, varchar, timestamptz
);
DROP FUNCTION IF EXISTS cehub_ai.persist_agent_run_context(
    uuid, uuid, jsonb, timestamptz
);
DROP FUNCTION IF EXISTS cehub_ai.bind_agent_scope(uuid, uuid);
DROP FUNCTION IF EXISTS cehub_ai.claim_agent_run(timestamptz);
DROP FUNCTION IF EXISTS cehub_ai.agent_invocation_scope_allows(
    uuid, uuid, uuid, varchar
);
DROP FUNCTION IF EXISTS cehub_ai.agent_tenant_scope_allows(uuid);
DROP FUNCTION IF EXISTS cehub_ai.agent_scope_allows(uuid, uuid);

REVOKE ALL ON ALL TABLES IN SCHEMA cehub_core, cehub_project, cehub_product,
    cehub_quality, cehub_supplier, cehub_cost, cehub_memory, cehub_event,
    cehub_audit, cehub_ai FROM pdos_worker, pdos_agent;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA cehub_core, cehub_project, cehub_product,
    cehub_quality, cehub_supplier, cehub_cost, cehub_memory, cehub_event,
    cehub_audit, cehub_ai FROM pdos_worker, pdos_agent;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cehub_ai FROM pdos_worker, pdos_agent;
REVOKE USAGE ON SCHEMA cehub_core, cehub_project, cehub_product, cehub_quality,
    cehub_supplier, cehub_cost, cehub_memory, cehub_event, cehub_audit, cehub_ai
    FROM pdos_worker, pdos_agent;

COMMIT;
