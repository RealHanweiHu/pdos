"""Market-scoped matrix analysis with fixed inputs and current authorization."""

from importlib import import_module

from alembic import op

revision = "0348_product_matrix_runs"
down_revision = "0347_product_matrix_records"
branch_labels = None
depends_on = None
previous = import_module("migrations.versions.0345_executive_brief_runs")
OLD_EVENTS = previous.NEW
NEW_EVENTS = OLD_EVENTS.replace(
    "agent_key = 'ai_chat' OR",
    "agent_key = 'ai_chat' OR (agent_key='product_management_intelligence' AND "
    "context_version='product-matrix-request-v1') OR",
    1,
)
OLD_AGENTS = (
    "agent_key IN ('project_intelligence','knowledge_lite','engineering_intelligence',"
    "'quality_intelligence','supplier_intelligence','executive_intelligence','ai_chat')"
)
NEW_AGENTS = OLD_AGENTS.replace("'ai_chat')", "'ai_chat','product_management_intelligence')")
OLD_SCOPE = (
    "(scope_kind='project' AND project_id IS NOT NULL AND "
    "context_version<>'process-template-request-v1') OR (scope_kind='tenant' "
    "AND project_id IS NULL AND agent_key='knowledge_lite' "
    "AND context_version='process-template-request-v1')"
)
NEW_SCOPE = (
    "(scope_kind='project' AND project_id IS NOT NULL AND market_space_id IS NULL "
    "AND context_version NOT IN ('process-template-request-v1','product-matrix-request-v1')) OR "
    "(scope_kind='tenant' AND project_id IS NULL AND market_space_id IS NULL "
    "AND agent_key='knowledge_lite' AND context_version='process-template-request-v1') OR "
    "(scope_kind='market_space' AND project_id IS NULL AND market_space_id IS NOT NULL "
    "AND agent_key='product_management_intelligence' "
    "AND context_version='product-matrix-request-v1')"
)
DDL = """
ALTER TABLE cehub_ai.agent_runs ADD COLUMN market_space_id uuid;
ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT fk_agent_runs_market_space
 FOREIGN KEY(tenant_id,market_space_id) REFERENCES cehub_product.market_spaces(tenant_id,id)
 ON DELETE RESTRICT;
CREATE UNIQUE INDEX uq_market_agent_run_request ON cehub_ai.agent_runs
 (tenant_id,market_space_id,agent_key,request_id) WHERE scope_kind='market_space';
CREATE FUNCTION cehub_ai.guard_market_matrix_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE b cehub_product.product_matrix_records;
BEGIN
 IF TG_OP='UPDATE' AND NEW.market_space_id IS DISTINCT FROM OLD.market_space_id THEN
  RAISE EXCEPTION 'Market run scope is immutable';
 END IF;
 IF NEW.scope_kind<>'market_space' THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND (NEW.tenant_id,NEW.agent_key,NEW.request_id,NEW.requested_by_user_id,
  NEW.context_version,NEW.run_context->'matrix_selection',NEW.run_context->'matrix_expected_digest',
  NEW.run_context->'matrix_source',NEW.run_context->'matrix_user_instruction',
  NEW.run_context->'matrix_prompt_version',NEW.run_context->'matrix_schema_digest',
  NEW.run_context->'matrix_output_mode') IS DISTINCT FROM
  (OLD.tenant_id,OLD.agent_key,OLD.request_id,OLD.requested_by_user_id,
  OLD.context_version,OLD.run_context->'matrix_selection',OLD.run_context->'matrix_expected_digest',
  OLD.run_context->'matrix_source',OLD.run_context->'matrix_user_instruction',
  OLD.run_context->'matrix_prompt_version',OLD.run_context->'matrix_schema_digest',
  OLD.run_context->'matrix_output_mode') THEN
  RAISE EXCEPTION 'Matrix run input identity is immutable';
 END IF;
 SELECT * INTO b FROM cehub_product.product_matrix_records WHERE tenant_id=NEW.tenant_id
  AND market_space_id=NEW.market_space_id
  AND id::text=NEW.run_context->'matrix_selection'->>'record_id';
 IF b.id IS NULL OR NEW.run_context->'matrix_source'->>'market_space_id'
    IS DISTINCT FROM NEW.market_space_id::text
  OR NEW.run_context->'matrix_source'->>'actor_id' IS DISTINCT FROM NEW.requested_by_user_id::text
  OR NEW.run_context->'matrix_source'->'selection'
    IS DISTINCT FROM NEW.run_context->'matrix_selection'
  OR NEW.run_context->'matrix_source'->>'record_result_digest' IS DISTINCT FROM b.result_digest
  OR NEW.run_context->'matrix_source'->>'digest'
    IS DISTINCT FROM NEW.run_context->>'matrix_expected_digest'
  OR coalesce(NEW.run_context->>'matrix_expected_digest','') !~ '^[a-f0-9]{64}$'
  OR coalesce(NEW.run_context->>'matrix_schema_digest','') !~ '^[a-f0-9]{64}$'
  OR NEW.run_context->'matrix_source'->>'projection_version'
    IS DISTINCT FROM 'product-matrix-context.v1'
  OR NEW.run_context->>'matrix_prompt_version' IS DISTINCT FROM 'product-matrix-v1'
  OR NEW.run_context->>'matrix_output_mode' IS DISTINCT FROM 'read_only.v1' THEN
  RAISE EXCEPTION 'Matrix run requires a fixed record, scope and version';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_market_matrix_run() FROM PUBLIC;
CREATE TRIGGER guard_market_matrix_run BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_market_matrix_run();
ALTER FUNCTION cehub_ai.application_authorization_is_current(uuid)
 RENAME TO application_pre_market_authorization_is_current;
CREATE FUNCTION cehub_ai.application_authorization_is_current(wanted_run uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cehub_ai.agent_runs
   WHERE id=wanted_run AND scope_kind='market_space')
 THEN EXISTS(
  SELECT 1 FROM cehub_ai.agent_runs r
  JOIN cehub_ai.application_authorizations a ON a.tenant_id=r.tenant_id AND a.run_id=r.id
  JOIN cehub_core.users u ON u.tenant_id=r.tenant_id AND u.id=a.principal_id
  JOIN cehub_core.tenants t ON t.id=r.tenant_id
  JOIN cehub_product.market_spaces s ON s.tenant_id=r.tenant_id AND s.id=r.market_space_id
  JOIN cehub_product.product_matrix_records b ON b.tenant_id=r.tenant_id
   AND b.market_space_id=r.market_space_id
   AND b.id::text=r.run_context->'matrix_selection'->>'record_id'
  WHERE r.id=wanted_run AND r.project_id IS NULL AND a.project_id IS NULL
   AND r.scope_kind='market_space' AND r.agent_key='product_management_intelligence'
   AND r.context_version='product-matrix-request-v1'
   AND r.status='running' AND r.requested_by_user_id=a.principal_id
   AND u.is_active AND t.status='active' AND s.lifecycle<>'archived'
   AND u.role IN ('owner','admin','project_manager','engineer','quality')
   AND a.expires_at>clock_timestamp() AND u.role=a.pins->>'role'
   AND u.auth_version=(a.pins->>'auth_version')::integer
   AND a.pins->>'action'='product_work.contribute' AND a.pins->>'delegation_id' IS NULL
   AND a.pins->>'membership_id' IS NULL
   AND a.body->>'tenant_id'=r.tenant_id::text AND a.body->>'run_id'=r.id::text
   AND a.body->>'principal_id'=a.principal_id::text AND a.body->>'purpose'='product_matrix'
   AND a.body->'scope'=jsonb_build_object('kind','market_space','ref_id',r.market_space_id::text)
   AND jsonb_array_length(a.body->'sources')=1
   AND a.body->'sources' @> jsonb_build_array(jsonb_build_object('kind','product_matrix_record',
     'ref_id',b.id::text,'tenant_id',b.tenant_id::text,'digest',b.result_digest))
   AND r.run_context->'matrix_source'->>'record_result_digest'=b.result_digest
   AND (u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_product.market_space_members m
     WHERE m.tenant_id=r.tenant_id AND m.market_space_id=r.market_space_id AND m.user_id=u.id
       AND m.access IN ('contributor','manager')))
   AND (b.product_line_id IS NULL OR EXISTS(SELECT 1 FROM cehub_product.product_nodes n
     WHERE n.tenant_id=r.tenant_id AND n.market_space_id=r.market_space_id
       AND n.id=b.product_line_id AND n.level='line' AND n.lifecycle<>'retired'
       AND (u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_product.product_line_members m
         WHERE m.tenant_id=r.tenant_id AND m.market_space_id=r.market_space_id
           AND m.product_line_id=n.id AND m.user_id=u.id
           AND m.access IN ('contributor','manager')))))
   AND (u.role IN ('owner','admin') OR NOT EXISTS(
     SELECT 1 FROM cehub_product.product_matrix_record_products rp
     JOIN cehub_product.product_nodes n ON n.tenant_id=rp.tenant_id
       AND n.market_space_id=rp.market_space_id AND n.id=rp.product_id
     WHERE rp.tenant_id=r.tenant_id AND rp.market_space_id=r.market_space_id AND rp.record_id=b.id
       AND NOT EXISTS(SELECT 1 FROM cehub_product.product_line_members m
         WHERE m.tenant_id=r.tenant_id
         AND m.market_space_id=r.market_space_id AND m.product_line_id=n.product_line_id
         AND m.user_id=u.id)))
 ) ELSE cehub_ai.application_pre_market_authorization_is_current(wanted_run) END;
$$;
REVOKE ALL ON FUNCTION cehub_ai.application_authorization_is_current(uuid) FROM PUBLIC;
"""


def replace_constraint(name: str, expression: str) -> None:
    op.execute(f"ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_{name}")
    op.execute(
        f"ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT ck_agent_runs_{name} CHECK ({expression})"
    )


def upgrade() -> None:
    op.execute(DDL)
    for name, expression in (
        ("scope", NEW_SCOPE),
        ("agent_key_allowed", NEW_AGENTS),
        ("event_bounds_consistent", NEW_EVENTS),
    ):
        replace_constraint(name, expression)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
      WHERE scope_kind='market_space') THEN
      RAISE EXCEPTION 'Retain market matrix run history and budgets'; END IF; END $$;""")
    op.execute("DROP FUNCTION cehub_ai.application_authorization_is_current(uuid)")
    op.execute(
        "ALTER FUNCTION cehub_ai.application_pre_market_authorization_is_current(uuid) "
        "RENAME TO application_authorization_is_current"
    )
    op.execute("DROP TRIGGER guard_market_matrix_run ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.guard_market_matrix_run()")
    for name, expression in (
        ("scope", OLD_SCOPE),
        ("agent_key_allowed", OLD_AGENTS),
        ("event_bounds_consistent", OLD_EVENTS),
    ):
        replace_constraint(name, expression)
    op.execute("DROP INDEX cehub_ai.uq_market_agent_run_request")
    op.execute("ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT fk_agent_runs_market_space")
    op.execute("ALTER TABLE cehub_ai.agent_runs DROP COLUMN market_space_id")
