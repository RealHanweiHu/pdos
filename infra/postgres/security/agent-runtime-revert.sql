DROP FUNCTION IF EXISTS cehub_ai.verify_agent_context_sources(uuid);
DROP FUNCTION IF EXISTS cehub_ai.verify_agent_manifest_sources();
DROP FUNCTION IF EXISTS cehub_ai.freeze_agent_context_manifest(uuid,uuid,text);
DROP FUNCTION IF EXISTS cehub_ai.bind_agent_runtime_bundle(text);
DROP FUNCTION IF EXISTS cehub_ai.read_agent_authorization();
DROP FUNCTION IF EXISTS cehub_ai.read_agent_loop_binding();
DROP FUNCTION IF EXISTS cehub_ai.dispatch_agent_tool_call(uuid);
DROP FUNCTION IF EXISTS cehub_ai.prepare_agent_tool_call(uuid,varchar,varchar,text);

DROP FUNCTION IF EXISTS cehub_ai.verify_agent_context_receipt(uuid,uuid,text);
DROP FUNCTION IF EXISTS cehub_ai.freeze_agent_context_receipt(uuid,text,uuid[]);
DROP FUNCTION IF EXISTS cehub_ai.append_agent_tool_observation(varchar,varchar,text,text,text);
DO $body$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_worker') AND EXISTS(
   SELECT 1 FROM information_schema.columns WHERE table_schema='cehub_ai'
   AND table_name='agent_runs' AND column_name='dispatch_policy') THEN
  REVOKE INSERT(dispatch_key,dispatch_policy,dispatch_deadline)
   ON cehub_ai.agent_runs FROM pdos_worker;
 END IF;
END $body$;
-- Migration-owned dispatcher maintenance remains available to the schema owner.
-- The role/schema/function revocations below still disable the restricted runtime.
-- Recovery also needs agent_lease_is_current; its migration-owned dependencies stay intact.
DROP FUNCTION IF EXISTS cehub_ai.load_agent_result_checkpoint(uuid,uuid);
DROP FUNCTION IF EXISTS cehub_ai.save_agent_result_checkpoint(uuid,uuid,text);
DROP FUNCTION IF EXISTS cehub_ai.agent_check_active_budget();
-- Revert only the PDOS S2-2b Agent runtime grants and database objects.
-- This intentionally does not drop login roles or passwords owned by the DBA.

BEGIN;
DROP FUNCTION IF EXISTS cehub_ai.load_agent_loop_checkpoint();
DROP FUNCTION IF EXISTS cehub_ai.save_agent_loop_checkpoint(text);

DROP POLICY IF EXISTS pdos_agent_insert_model_invocations
    ON cehub_ai.model_invocations;
ALTER TABLE cehub_ai.model_invocations DISABLE ROW LEVEL SECURITY;

DROP VIEW IF EXISTS
    cehub_ai.agent_finding_quality_projection,
    cehub_ai.agent_run_usage_projection,
    cehub_ai.agent_model_usage_projection,
    cehub_ai.agent_model_settings_projection,
    cehub_ai.agent_document_fragment_projection,
    cehub_ai.agent_user_role_projection,
    cehub_ai.agent_quality_evidence_projection,
    cehub_ai.agent_engineering_evidence_projection,
    cehub_ai.agent_supplier_delay_projection,
    cehub_ai.agent_portfolio_projection,
    cehub_ai.agent_memory_projection,
    cehub_ai.agent_event_projection,
    cehub_ai.agent_gate_projection,
    cehub_ai.agent_task_projection,
    cehub_ai.agent_risk_projection,
    cehub_ai.agent_issue_projection,
    cehub_ai.agent_project_projection,
    cehub_ai.agent_run_projection;

DROP FUNCTION IF EXISTS cehub_ai.agent_open_budgeted_model_call();
DROP FUNCTION IF EXISTS cehub_ai.agent_reserve_model_budget(uuid, bigint, jsonb);
DROP FUNCTION IF EXISTS cehub_ai.agent_budget_profile();
DROP FUNCTION IF EXISTS cehub_ai.agent_transition_model_budget(uuid, text, text);
DROP FUNCTION IF EXISTS cehub_ai.agent_open_model_call();
DROP FUNCTION IF EXISTS cehub_ai.agent_finish_model_call(uuid, uuid);
DROP FUNCTION IF EXISTS cehub_ai.agent_mark_model_call_unknown(uuid);
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
DROP FUNCTION IF EXISTS cehub_ai.agent_tenant_agent_scope_allows(uuid, varchar);
DROP FUNCTION IF EXISTS cehub_ai.agent_scope_allows(uuid, uuid);
DROP FUNCTION IF EXISTS cehub_ai.renew_agent_run_lease(uuid, uuid);

-- A fresh cluster has neither runtime role yet. Keep this rollback safe before
-- bootstrap as well as after bootstrap by revoking only from roles that exist.
DO $revoke_runtime_roles$
DECLARE
    runtime_role text;
BEGIN
    FOREACH runtime_role IN ARRAY ARRAY['pdos_worker', 'pdos_agent']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime_role) THEN
            EXECUTE format(
                'REVOKE ALL ON ALL TABLES IN SCHEMA cehub_core, cehub_project, '
                'cehub_product, cehub_quality, cehub_supplier, cehub_cost, '
                'cehub_memory, cehub_event, cehub_audit, cehub_ai FROM %I',
                runtime_role
            );
            EXECUTE format(
                'REVOKE ALL ON ALL SEQUENCES IN SCHEMA cehub_core, cehub_project, '
                'cehub_product, cehub_quality, cehub_supplier, cehub_cost, '
                'cehub_memory, cehub_event, cehub_audit, cehub_ai FROM %I',
                runtime_role
            );
            EXECUTE format(
                'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cehub_ai FROM %I',
                runtime_role
            );
            EXECUTE format(
                'REVOKE USAGE ON SCHEMA cehub_core, cehub_project, cehub_product, '
                'cehub_quality, cehub_supplier, cehub_cost, cehub_memory, '
                'cehub_event, cehub_audit, cehub_ai FROM %I',
                runtime_role
            );
        END IF;
    END LOOP;
END
$revoke_runtime_roles$;

COMMIT;
