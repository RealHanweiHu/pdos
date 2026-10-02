"""Separate admin evaluation runs; no promotion of employee capabilities."""

import json

from alembic import op
from sqlalchemy import String, literal, text

revision = "0407_product_shadow_evaluation"
down_revision = "0406_matrix_outcome_guard"
branch_labels = None
depends_on = None
VERSION = "product-evaluation-request-v1"

DDL = r"""
CREATE FUNCTION cehub_ai.guard_product_evaluation_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE s jsonb; b jsonb; v cehub_ai.model_invocations;
BEGIN
 IF TG_OP='UPDATE' AND OLD.context_version='product-evaluation-request-v1'
   AND NEW.context_version IS DISTINCT FROM OLD.context_version THEN
  RAISE EXCEPTION 'Product evaluation identity is immutable'; END IF;
 IF NEW.context_version<>'product-evaluation-request-v1' THEN RETURN NEW; END IF;
 s:=NEW.run_context->'evaluation_source'; b:=NEW.run_context->'evaluation_input';
 IF NEW.scope_kind<>'market_space' OR NEW.project_id IS NOT NULL OR NEW.market_space_id IS NULL
  OR NEW.agent_key<>'product_management_intelligence' OR NEW.requested_by_user_id IS NULL
  OR s IS NULL OR b IS NULL OR NEW.request_id IS DISTINCT FROM 'evaluation:'||(b->>'request_id')
  OR s->>'market_space_id' IS DISTINCT FROM NEW.market_space_id::text
  OR s->>'actor_id' IS DISTINCT FROM NEW.requested_by_user_id::text
  OR s->>'digest' IS DISTINCT FROM b->>'expected_digest'
  OR coalesce(s->>'digest','') !~ '^[a-f0-9]{64}$'
  OR coalesce(b->>'source_sha256','') !~ '^[a-f0-9]{64}$'
  OR coalesce(b->>'runtime_sha256','') !~ '^[a-f0-9]{64}$'
  OR coalesce(b->>'suite_sha256','') !~ '^[a-f0-9]{64}$'
  OR coalesce(b->>'case_id','')=''
  OR coalesce(NEW.run_context->>'evaluation_schema_digest','') !~ '^[a-f0-9]{64}$'
  OR NEW.run_context->>'evaluation_output_mode' IS DISTINCT FROM 'shadow_evaluation.v1'
  OR coalesce(b->'selection'->>'capability','') NOT IN ('research_planning','competitor_analysis',
   'market_analysis','opportunity_mapping','experiment_design','product_strategy',
   'product_definition','product_matrix','rfq_requirements')
  OR s->'selection' IS DISTINCT FROM (CASE WHEN b->'selection'->>'capability'='product_matrix'
     THEN b->'selection'->'matrix' ELSE b->'selection'->'work' END)
 THEN RAISE EXCEPTION 'Product evaluation requires fixed actor, scope, input and read-only mode';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.tenant_id,NEW.market_space_id,NEW.project_id,NEW.scope_kind,
  NEW.agent_key,NEW.request_id,NEW.requested_by_user_id,NEW.context_version,
  NEW.run_context->'evaluation_input',NEW.run_context->'evaluation_source',
  NEW.run_context->'evaluation_prompt_version',NEW.run_context->'evaluation_schema_digest',
  NEW.run_context->'evaluation_output_mode') IS DISTINCT FROM
  (OLD.tenant_id,OLD.market_space_id,OLD.project_id,OLD.scope_kind,
  OLD.agent_key,OLD.request_id,OLD.requested_by_user_id,OLD.context_version,
  OLD.run_context->'evaluation_input',OLD.run_context->'evaluation_source',
  OLD.run_context->'evaluation_prompt_version',OLD.run_context->'evaluation_schema_digest',
  OLD.run_context->'evaluation_output_mode') THEN
  RAISE EXCEPTION 'Product evaluation inputs are immutable'; END IF;
 IF TG_OP='UPDATE' AND (OLD.status IN ('succeeded','failed') OR
    OLD.status='degraded' AND OLD.error_code IS DISTINCT FROM 'APPLICATION_RUN_LEASE_EXPIRED')
   AND (NEW.status,NEW.error_code,NEW.run_context->'evaluation_result',
        NEW.run_context->'evaluation_invocation_id') IS DISTINCT FROM
       (OLD.status,OLD.error_code,OLD.run_context->'evaluation_result',
        OLD.run_context->'evaluation_invocation_id') THEN
  RAISE EXCEPTION 'Completed evaluation receipts are immutable'; END IF;
 IF NEW.status='succeeded' THEN
  SELECT * INTO v FROM cehub_ai.model_invocations WHERE tenant_id=NEW.tenant_id AND run_id=NEW.id
    AND id::text=NEW.run_context->>'evaluation_invocation_id' AND status='succeeded'
    AND agent_key='product_management_intelligence' AND budget_call_id IS NOT NULL;
  IF v.id IS NULL
    OR jsonb_typeof(NEW.run_context->'evaluation_result') IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'Successful evaluation requires the original invocation and structured result';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_product_evaluation_run() FROM PUBLIC;
CREATE TRIGGER guard_product_evaluation_run BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_product_evaluation_run();

ALTER FUNCTION cehub_ai.application_authorization_is_current(uuid)
 RENAME TO application_pre_product_evaluation_authorization_is_current;
CREATE FUNCTION cehub_ai.application_authorization_is_current(wanted_run uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE id=wanted_run
  AND context_version='product-evaluation-request-v1') THEN EXISTS(
 SELECT 1 FROM cehub_ai.agent_runs r
 JOIN cehub_ai.application_authorizations a ON a.tenant_id=r.tenant_id AND a.run_id=r.id
 JOIN cehub_core.users u ON u.tenant_id=r.tenant_id AND u.id=a.principal_id
 JOIN cehub_core.tenants t ON t.id=r.tenant_id
 JOIN cehub_product.market_spaces s ON s.tenant_id=r.tenant_id AND s.id=r.market_space_id
 WHERE r.id=wanted_run AND r.scope_kind='market_space' AND r.project_id IS NULL
  AND r.agent_key='product_management_intelligence' AND r.status='running'
  AND r.requested_by_user_id=a.principal_id AND a.project_id IS NULL
  AND u.is_active AND t.status='active' AND u.role IN ('owner','admin')
  AND a.expires_at>clock_timestamp() AND u.role=a.pins->>'role'
  AND u.auth_version=(a.pins->>'auth_version')::integer
  AND a.pins->>'action'='model_governance.manage'
  AND a.pins->>'delegation_id' IS NULL AND a.pins->>'membership_id' IS NULL
  AND a.body->>'purpose'='product_evaluation' AND a.body->>'tenant_id'=r.tenant_id::text
  AND a.body->>'run_id'=r.id::text AND a.body->>'principal_id'=a.principal_id::text
  AND a.body->'scope'=jsonb_build_object('kind','market_space','ref_id',r.market_space_id::text)
  AND jsonb_array_length(a.body->'sources')=1
  AND a.body->'sources' @> jsonb_build_array(jsonb_build_object('tenant_id',r.tenant_id::text,
    'kind','market_space','ref_id',r.market_space_id::text,
    'digest',r.run_context->'evaluation_source'->>'digest'))
 ) ELSE cehub_ai.application_pre_product_evaluation_authorization_is_current(wanted_run) END;
$$;
REVOKE ALL ON FUNCTION cehub_ai.application_authorization_is_current(uuid) FROM PUBLIC;
"""


def constraints(add: bool) -> None:
    c = op.get_bind()
    for suffix in ("scope", "event_bounds_consistent"):
        name = "ck_agent_runs_" + suffix
        previous, comment = c.execute(
            text(
                "SELECT pg_get_constraintdef(oid),obj_description(oid,'pg_constraint') "
                "FROM pg_constraint WHERE conrelid='cehub_ai.agent_runs'::regclass AND conname=:n"
            ),
            {"n": name},
        ).one()
        if add:
            original = previous.removeprefix("CHECK (").removesuffix(")")
            expression = (
                f"({original}) OR (context_version='{VERSION}' AND scope_kind='market_space' "
                "AND project_id IS NULL AND market_space_id IS NOT NULL AND "
                "agent_key='product_management_intelligence' AND subscription_id IS NULL AND "
                "first_event_row_id IS NULL AND last_event_row_id IS NULL AND event_count=0 AND "
                "event_row_ids='[]'::jsonb AND request_id IS NOT NULL AND "
                "btrim(request_id)<>'' AND "
                "requested_by_user_id IS NOT NULL AND status IN "
                "('running','succeeded','degraded','failed')) IS TRUE"
            )
            new_comment = json.dumps(dict(version=VERSION, expression=previous, comment=comment))
        else:
            saved = json.loads(comment)
            if saved["version"] != VERSION:
                raise RuntimeError("Original evaluation constraints are unavailable")
            expression = saved["expression"].removeprefix("CHECK (").removesuffix(")")
            new_comment = saved["comment"]
        op.execute(f"ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT {name} CHECK ({expression})")
        encoded = (
            str(
                literal(new_comment, type_=String()).compile(
                    dialect=c.dialect, compile_kwargs={"literal_binds": True}
                )
            )
            if new_comment is not None
            else "NULL"
        )
        op.execute(f"COMMENT ON CONSTRAINT {name} ON cehub_ai.agent_runs IS {encoded}")


def matrix_guard(add: bool) -> None:
    ddl = (
        op.get_bind()
        .execute(
            text("SELECT pg_get_functiondef('cehub_ai.guard_market_matrix_run()'::regprocedure)")
        )
        .scalar_one()
    )
    old = "NEW.context_version='product-work-request-v1' THEN RETURN NEW; END IF;"
    new = (
        "NEW.context_version IN ('product-work-request-v1','product-evaluation-request-v1') "
        "THEN RETURN NEW; END IF;"
    )
    if (old if add else new) not in ddl:
        raise RuntimeError("Preceding matrix guard is unavailable")
    op.execute(ddl.replace(old if add else new, new if add else old, 1))


def upgrade() -> None:
    constraints(True)
    matrix_guard(True)
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
      WHERE context_version='product-evaluation-request-v1') THEN
      RAISE EXCEPTION 'Retain product evaluation runs, budgets and receipts'; END IF; END $$;""")
    op.execute("DROP FUNCTION cehub_ai.application_authorization_is_current(uuid)")
    op.execute(
        "ALTER FUNCTION cehub_ai.application_pre_product_evaluation_authorization_is_current(uuid) "
        "RENAME TO application_authorization_is_current"
    )
    op.execute("DROP TRIGGER guard_product_evaluation_run ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.guard_product_evaluation_run()")
    matrix_guard(False)
    constraints(False)
