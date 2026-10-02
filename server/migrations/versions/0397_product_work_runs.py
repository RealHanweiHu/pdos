"""Source-bound product work analysis; existing matrix identities remain unchanged."""

from alembic import op
from sqlalchemy import text

revision = "0397_product_work_runs"
down_revision = "0396_fmea_knowledge_basis"
branch_labels = None
depends_on = None

VERSION = "product-work-request-v1"

DDL = r"""
CREATE FUNCTION cehub_ai.guard_product_work_run() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE s jsonb; selection jsonb;
BEGIN
 IF TG_OP='UPDATE' AND OLD.context_version='product-work-request-v1'
  AND NEW.context_version IS DISTINCT FROM OLD.context_version THEN
  RAISE EXCEPTION 'Product work run version is immutable'; END IF;
 IF NEW.context_version<>'product-work-request-v1' THEN RETURN NEW; END IF;
 s:=NEW.run_context->'product_work_source';
 selection:=NEW.run_context->'product_work_selection';
 IF NEW.scope_kind<>'market_space' OR NEW.project_id IS NOT NULL
  OR NEW.market_space_id IS NULL OR NEW.agent_key<>'product_management_intelligence'
  OR NEW.requested_by_user_id IS NULL OR s IS NULL OR selection IS NULL
  OR s->>'market_space_id' IS DISTINCT FROM NEW.market_space_id::text
  OR s->>'actor_id' IS DISTINCT FROM NEW.requested_by_user_id::text
  OR s->'selection' IS DISTINCT FROM selection
  OR s->>'projection_version' IS DISTINCT FROM 'product-work-context.v1'
  OR s->>'digest' IS DISTINCT FROM NEW.run_context->>'product_work_expected_digest'
  OR coalesce(s->>'digest','') !~ '^[a-f0-9]{64}$'
  OR coalesce(NEW.run_context->>'product_work_schema_digest','') !~ '^[a-f0-9]{64}$'
  OR NEW.run_context->>'product_work_prompt_version' IS DISTINCT FROM 'product-work-v1'
  OR NEW.run_context->>'product_work_output_mode' IS DISTINCT FROM 'read_only.v1'
  OR coalesce(selection->>'capability','') NOT IN ('research_planning','competitor_analysis',
    'market_analysis','opportunity_mapping','experiment_design','product_strategy','product_definition')
  OR (selection->>'capability' IN ('opportunity_mapping','experiment_design','product_strategy',
      'product_definition') AND selection->>'product_line_id' IS NULL)
 THEN RAISE EXCEPTION 'Product work run requires fixed scope, capability and sources'; END IF;
 IF TG_OP='UPDATE' AND (NEW.tenant_id,NEW.market_space_id,NEW.project_id,NEW.scope_kind,
   NEW.agent_key,NEW.request_id,NEW.requested_by_user_id,NEW.context_version,
   NEW.run_context->'product_work_selection',NEW.run_context->'product_work_expected_digest',
   NEW.run_context->'product_work_source',NEW.run_context->'product_work_user_instruction',
   NEW.run_context->'product_work_prompt_version',NEW.run_context->'product_work_schema_digest',
   NEW.run_context->'product_work_output_mode') IS DISTINCT FROM
  (OLD.tenant_id,OLD.market_space_id,OLD.project_id,OLD.scope_kind,OLD.agent_key,OLD.request_id,
   OLD.requested_by_user_id,OLD.context_version,OLD.run_context->'product_work_selection',
   OLD.run_context->'product_work_expected_digest',OLD.run_context->'product_work_source',
   OLD.run_context->'product_work_user_instruction',OLD.run_context->'product_work_prompt_version',
   OLD.run_context->'product_work_schema_digest',OLD.run_context->'product_work_output_mode')
 THEN RAISE EXCEPTION 'Product work run input identity is immutable'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_product_work_run() FROM PUBLIC;
CREATE TRIGGER guard_product_work_run BEFORE INSERT OR UPDATE ON cehub_ai.agent_runs
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_product_work_run();

ALTER FUNCTION cehub_ai.application_authorization_is_current(uuid)
 RENAME TO application_pre_product_work_authorization_is_current;
CREATE FUNCTION cehub_ai.application_authorization_is_current(wanted_run uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM cehub_ai.agent_runs
   WHERE id=wanted_run AND context_version='product-work-request-v1') THEN EXISTS(
  SELECT 1 FROM cehub_ai.agent_runs r
  JOIN cehub_ai.application_authorizations a ON a.tenant_id=r.tenant_id AND a.run_id=r.id
  JOIN cehub_core.users u ON u.tenant_id=r.tenant_id AND u.id=a.principal_id
  JOIN cehub_core.tenants t ON t.id=r.tenant_id
  JOIN cehub_product.market_spaces s ON s.tenant_id=r.tenant_id AND s.id=r.market_space_id
  WHERE r.id=wanted_run AND r.scope_kind='market_space' AND r.project_id IS NULL
   AND a.project_id IS NULL AND r.agent_key='product_management_intelligence'
   AND r.requested_by_user_id=a.principal_id AND r.status='running'
   AND u.is_active AND t.status='active' AND s.lifecycle<>'archived'
   AND u.role IN ('owner','admin','project_manager','engineer','quality')
   AND a.expires_at>clock_timestamp() AND u.role=a.pins->>'role'
   AND u.auth_version=(a.pins->>'auth_version')::integer
   AND a.pins->>'action'='product_work.contribute' AND a.pins->>'delegation_id' IS NULL
   AND a.pins->>'membership_id' IS NULL
   AND a.body->>'tenant_id'=r.tenant_id::text AND a.body->>'run_id'=r.id::text
   AND a.body->>'principal_id'=a.principal_id::text AND a.body->>'purpose'='product_work'
   AND a.body->'scope'=jsonb_build_object('kind','market_space','ref_id',r.market_space_id::text)
   AND jsonb_array_length(a.body->'sources')=1
   AND a.body->'sources' @> jsonb_build_array(jsonb_build_object('kind','market_space',
     'ref_id',r.market_space_id::text,'tenant_id',r.tenant_id::text,
     'digest',r.run_context->'product_work_source'->>'digest'))
   AND (u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_product.market_space_members m
     WHERE m.tenant_id=r.tenant_id AND m.market_space_id=r.market_space_id AND m.user_id=u.id
       AND m.access IN ('contributor','manager')))
   AND (r.run_context->'product_work_selection'->>'product_line_id' IS NULL OR EXISTS(
     SELECT 1 FROM cehub_product.product_nodes n WHERE n.tenant_id=r.tenant_id
      AND n.market_space_id=r.market_space_id AND n.level='line' AND n.lifecycle<>'retired'
      AND n.id::text=r.run_context->'product_work_selection'->>'product_line_id'
      AND (u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_product.product_line_members m
        WHERE m.tenant_id=r.tenant_id AND m.market_space_id=r.market_space_id
          AND m.product_line_id=n.id AND m.user_id=u.id
          AND m.access IN ('contributor','manager')))))
 ) ELSE cehub_ai.application_pre_product_work_authorization_is_current(wanted_run) END;
$$;
REVOKE ALL ON FUNCTION cehub_ai.application_authorization_is_current(uuid) FROM PUBLIC;
"""


def constraints(add: bool) -> None:
    c = op.get_bind()
    for name in ("scope", "event_bounds_consistent"):
        full = "ck_agent_runs_" + name
        expression = c.execute(
            text("""SELECT pg_get_constraintdef(oid)
          FROM pg_constraint WHERE conrelid='cehub_ai.agent_runs'::regclass AND conname=:name"""),
            {"name": full},
        ).scalar_one()
        # Preserve the actual preceding-head expression, including issue-event amendments.
        if add:
            expression = expression.removeprefix("CHECK (").removesuffix(")")
            expression = (
                f"({expression}) OR (context_version='{VERSION}' AND scope_kind='market_space' "
                f"AND project_id IS NULL AND market_space_id IS NOT NULL AND "
                f"agent_key='product_management_intelligence' AND subscription_id IS NULL AND "
                f"first_event_row_id IS NULL AND last_event_row_id IS NULL AND event_count=0 "
                f"AND event_row_ids='[]'::jsonb AND request_id IS NOT NULL AND "
                f"btrim(request_id)<>'' AND requested_by_user_id IS NOT NULL AND status IN "
                f"('running','succeeded','degraded','failed')) IS TRUE"
            )
        else:
            # Downgrade restores exact expressions saved in constraint comments on upgrade.
            expression = c.execute(
                text(
                    "SELECT obj_description(oid,'pg_constraint') FROM pg_constraint WHERE "
                    "conrelid='cehub_ai.agent_runs'::regclass AND conname=:name"
                ),
                {"name": full},
            ).scalar_one()
            if not expression or not expression.startswith("CHECK ("):
                raise RuntimeError("Original product-run constraint is unavailable")
            expression = expression.removeprefix("CHECK (").removesuffix(")")
        previous = c.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE "
                "conrelid='cehub_ai.agent_runs'::regclass AND conname=:name"
            ),
            {"name": full},
        ).scalar_one()
        op.execute(f"ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT {full}")
        op.execute(f"ALTER TABLE cehub_ai.agent_runs ADD CONSTRAINT {full} CHECK ({expression})")
        if add:
            from sqlalchemy import String, literal

            encoded = str(
                literal(previous, type_=String()).compile(
                    dialect=c.dialect, compile_kwargs={"literal_binds": True}
                )
            )
            op.execute(f"COMMENT ON CONSTRAINT {full} ON cehub_ai.agent_runs IS {encoded}")


def matrix_guard(add: bool) -> None:
    c = op.get_bind()
    ddl = c.execute(
        text("SELECT pg_get_functiondef('cehub_ai.guard_market_matrix_run()'::regprocedure)")
    ).scalar_one()
    old = "IF NEW.scope_kind<>'market_space' THEN RETURN NEW; END IF;"
    new = (
        "IF NEW.scope_kind<>'market_space' OR "
        "NEW.context_version='product-work-request-v1' THEN RETURN NEW; END IF;"
    )
    assert (old if add else new) in ddl
    op.execute(ddl.replace(old if add else new, new if add else old, 1))


def upgrade() -> None:
    constraints(True)
    matrix_guard(True)
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs
      WHERE context_version='product-work-request-v1') THEN
      RAISE EXCEPTION 'Retain product work history and budgets'; END IF; END $$;""")
    op.execute("DROP FUNCTION cehub_ai.application_authorization_is_current(uuid)")
    op.execute(
        "ALTER FUNCTION "
        "cehub_ai.application_pre_product_work_authorization_is_current(uuid) RENAME "
        "TO application_authorization_is_current"
    )
    op.execute("DROP TRIGGER guard_product_work_run ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.guard_product_work_run()")
    matrix_guard(False)
    constraints(False)
