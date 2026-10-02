"""Private market-scoped research Finding, separate acceptance and domain application."""

from alembic import op
from sqlalchemy import String, literal, text

revision = "0398_product_research_findings"
down_revision = "0397_product_work_runs"
branch_labels = None
depends_on = None

BRANCHES = {
    "scope": (
        "scope_kind='market_space' AND project_id IS NULL AND "
        "agent_key='product_management_intelligence' AND "
        "finding_type='product_research_plan'"
    ),
    "type_allowed": (
        "agent_key='product_management_intelligence' AND finding_type='product_research_plan'"
    ),
    "evidence_event_ids_array": (
        "finding_type='product_research_plan' AND evidence_event_ids='[]'::jsonb"
    ),
    "apply_lifecycle_consistent": (
        "finding_type='product_research_plan' AND status='applied' AND "
        "reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL AND "
        "accepted_payload IS NOT NULL AND applied_by_user_id IS NOT NULL AND "
        "applied_at IS NOT NULL AND applied_entity_type='research_task' AND "
        "applied_entity_id IS NOT NULL AND reviewed_at<applied_at"
    ),
}
DDL = r"""
ALTER TABLE cehub_product.research_tasks ADD COLUMN source_finding_id uuid;
ALTER TABLE cehub_product.research_tasks ADD CONSTRAINT fk_research_tasks_source_finding
 FOREIGN KEY(tenant_id,source_finding_id)
 REFERENCES cehub_ai.findings(tenant_id,id) ON DELETE RESTRICT;
ALTER TABLE cehub_product.research_tasks ADD CONSTRAINT uq_research_tasks_source_finding
 UNIQUE(tenant_id,source_finding_id);
CREATE FUNCTION cehub_ai.guard_product_research_finding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints; actor uuid;
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type='product_research_plan' AND
  NEW.finding_type IS DISTINCT FROM OLD.finding_type THEN
  RAISE EXCEPTION 'Research finding type is immutable'; END IF;
 IF NEW.finding_type<>'product_research_plan' THEN RETURN NEW; END IF;
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id
  AND scope_kind='market_space' AND context_version='product-work-request-v1'
  AND agent_key='product_management_intelligence'
  AND run_context->'product_work_selection'->>'capability'='research_planning';
 IF r.id IS NULL OR NEW.scope_kind<>'market_space' OR NEW.project_id IS NOT NULL
  OR NEW.origin_key IS DISTINCT FROM 'product-research:'||r.id::text
  OR NEW.proposed_payload->>'source_digest' IS DISTINCT FROM
   r.run_context->'product_work_source'->>'digest'
 THEN RAISE EXCEPTION 'Research Finding requires original market request'; END IF;
 IF TG_OP='INSERT' THEN
  SELECT * INTO cp FROM cehub_ai.application_result_checkpoints WHERE tenant_id=NEW.tenant_id
   AND run_id=NEW.run_id AND invocation_id=NEW.model_invocation_id;
  IF NEW.status<>'pending_review' OR cp.id IS NULL OR cp.body->'output' IS DISTINCT FROM
   NEW.proposed_payload->'assessment' OR
   jsonb_typeof(cp.body->'output'->'research_plan') IS DISTINCT FROM 'object' OR
   NOT cehub_ai.application_result_receipt_valid(cp.tenant_id,cp.run_id,cp.model_call_id,
     cp.observation_id,cp.manifest_id,cp.invocation_id,cp.owner_lease_id)
  THEN RAISE EXCEPTION 'Research Finding needs actual durable model result'; END IF;
 ELSE
  IF (NEW.id,NEW.tenant_id,NEW.run_id,NEW.model_invocation_id,NEW.agent_key,NEW.finding_type,
      NEW.origin_key,NEW.title,NEW.summary,NEW.proposed_payload,NEW.evidence_event_ids,
      NEW.confidence_basis_points,NEW.preflight_version,NEW.created_at) IS DISTINCT FROM
     (OLD.id,OLD.tenant_id,OLD.run_id,OLD.model_invocation_id,OLD.agent_key,OLD.finding_type,
      OLD.origin_key,OLD.title,OLD.summary,OLD.proposed_payload,OLD.evidence_event_ids,
      OLD.confidence_basis_points,OLD.preflight_version,OLD.created_at)
  THEN RAISE EXCEPTION 'Original research Finding is immutable'; END IF;
  IF OLD.status='pending_review' AND NEW.status IN ('accepted','rejected') THEN
   actor:=NEW.reviewed_by_user_id;
  ELSIF OLD.status='accepted' AND NEW.status='applied' THEN
   actor:=NEW.applied_by_user_id;
   IF (NEW.accepted_payload,NEW.reviewed_by_user_id,NEW.reviewed_at,NEW.review_comment)
    IS DISTINCT FROM (OLD.accepted_payload,OLD.reviewed_by_user_id,OLD.reviewed_at,
 OLD.review_comment)
    OR NOT EXISTS(SELECT 1 FROM cehub_product.research_tasks t WHERE t.tenant_id=NEW.tenant_id
      AND t.id=NEW.applied_entity_id AND t.source_finding_id=NEW.id
      AND t.market_space_id=r.market_space_id AND t.state='draft')
  
 THEN RAISE EXCEPTION 'Research apply needs accepted immutable payload and domain receipt'; END IF;
  ELSE RAISE EXCEPTION 'Research Finding requires separate acceptance and apply'; END IF;
  IF actor IS DISTINCT FROM r.requested_by_user_id OR NOT EXISTS(
   SELECT 1 FROM cehub_core.users u JOIN cehub_core.tenants ten ON ten.id=u.tenant_id
   JOIN cehub_product.market_spaces s ON s.tenant_id=u.tenant_id AND s.id=r.market_space_id
   WHERE u.tenant_id=NEW.tenant_id AND u.id=actor AND u.is_active AND ten.status='active'
   
 AND u.role IN ('owner','admin','project_manager','engineer','quality') AND s.lifecycle<>'archived'
    AND (u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_product.market_space_members m
      WHERE m.tenant_id=u.tenant_id AND m.market_space_id=s.id AND m.user_id=u.id
        AND m.access IN ('contributor','manager')))
    AND (r.run_context->'product_work_selection'->>'product_line_id' IS NULL OR EXISTS(
      SELECT 1 FROM cehub_product.product_nodes n WHERE n.tenant_id=u.tenant_id
       AND n.market_space_id=s.id AND n.level='line' AND n.lifecycle<>'retired'
       AND n.id::text=r.run_context->'product_work_selection'->>'product_line_id'
       AND (u.role IN ('owner','admin') OR EXISTS(SELECT 1 FROM cehub_product.product_line_members m
        WHERE m.tenant_id=u.tenant_id AND m.product_line_id=n.id AND m.user_id=u.id
         AND m.access IN ('contributor','manager')))))
  ) THEN RAISE EXCEPTION 'Research review/apply needs current scoped original actor'; END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_product_research_finding() FROM PUBLIC;
CREATE TRIGGER guard_product_research_finding BEFORE INSERT OR UPDATE ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_product_research_finding();
CREATE FUNCTION cehub_product.guard_research_finding_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE f cehub_ai.findings; r cehub_ai.agent_runs;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF NEW.source_finding_id IS DISTINCT FROM OLD.source_finding_id THEN
   RAISE EXCEPTION 'Research AI origin is immutable'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.source_finding_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO f FROM cehub_ai.findings WHERE tenant_id=NEW.tenant_id AND id=NEW.source_finding_id
  AND finding_type='product_research_plan' AND status='accepted';
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=f.run_id;
 IF f.id IS NULL OR NEW.market_space_id IS DISTINCT FROM r.market_space_id
  OR NEW.product_line_id::text IS DISTINCT FROM
      r.run_context->'product_work_selection'->>'product_line_id'
  OR NEW.created_by_user_id IS DISTINCT FROM r.requested_by_user_id
 OR NEW.owner_user_id IS DISTINCT FROM r.requested_by_user_id
 OR NEW.request_id IS DISTINCT FROM f.id
  OR NEW.state<>'draft' OR NEW.version<>1
  OR jsonb_build_object('question',NEW.question,'user_groups',NEW.user_groups,'regions',NEW.regions,
    'time_scope',NEW.time_scope,'method',NEW.method,'expected_decision',NEW.expected_decision,
    'stop_conditions',NEW.stop_conditions) IS DISTINCT FROM f.accepted_payload->'proposal'
 THEN RAISE EXCEPTION 'Research task must match the accepted original-scoped proposal'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_product.guard_research_finding_origin() FROM PUBLIC;
CREATE TRIGGER guard_research_finding_origin BEFORE INSERT OR UPDATE ON cehub_product.research_tasks
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_research_finding_origin();
"""


def change_constraints(add: bool, table: str = "findings") -> None:
    c = op.get_bind()
    branches = BRANCHES if table == "findings" else {"type_allowed": BRANCHES["type_allowed"]}
    for name, branch in branches.items():
        full = "ck_" + table + "_" + name
        previous = c.execute(
            text(
                f"SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE "
                f"conrelid='cehub_ai.{table}'::regclass AND conname=:n"
            ),
            {"n": full},
        ).scalar_one()
        if add:
            expression = (
                f"({previous.removeprefix('CHECK (').removesuffix(')')}) OR ({branch}) IS TRUE"
            )
        else:
            old = c.execute(
                text(
                    f"SELECT obj_description(oid,'pg_constraint') FROM pg_constraint WHERE "
                    f"conrelid='cehub_ai.{table}'::regclass AND conname=:n"
                ),
                {"n": full},
            ).scalar_one()
            if not old or not old.startswith("CHECK ("):
                raise RuntimeError("Prior Finding constraint unavailable")
            expression = old.removeprefix("CHECK (").removesuffix(")")
        op.execute(f"ALTER TABLE cehub_ai.{table} DROP CONSTRAINT {full}")
        op.execute(f"ALTER TABLE cehub_ai.{table} ADD CONSTRAINT {full} CHECK ({expression})")
        if add:
            encoded = str(
                literal(previous, type_=String()).compile(
                    dialect=c.dialect, compile_kwargs={"literal_binds": True}
                )
            )
            op.execute(f"COMMENT ON CONSTRAINT {full} ON cehub_ai.{table} IS {encoded}")


def prompt_guard(add: bool) -> None:
    c = op.get_bind()
    ddl = c.execute(
        text("SELECT pg_get_functiondef('cehub_ai.guard_product_work_run()'::regprocedure)")
    ).scalar_one()
    old = "NEW.run_context->>'product_work_prompt_version' IS DISTINCT FROM 'product-work-v1'"
    new = (
        "coalesce(NEW.run_context->>'product_work_prompt_version','') NOT IN "
        "('product-work-v1','product-research-v2')"
    )
    assert (old if add else new) in ddl
    op.execute(ddl.replace(old if add else new, new if add else old, 1))


def upgrade() -> None:
    change_constraints(True)
    change_constraints(True, "finding_quality_controls")
    prompt_guard(True)
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.findings
     WHERE finding_type='product_research_plan') OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs
     WHERE run_context->>'product_work_prompt_version'='product-research-v2') THEN
     RAISE EXCEPTION 'Retain product research proposals and original runs'; END IF; END $$;""")
    op.execute("DROP TRIGGER guard_research_finding_origin ON cehub_product.research_tasks")
    op.execute("DROP FUNCTION cehub_product.guard_research_finding_origin()")
    op.execute("DROP TRIGGER guard_product_research_finding ON cehub_ai.findings")
    op.execute("DROP FUNCTION cehub_ai.guard_product_research_finding()")
    op.execute("ALTER TABLE cehub_product.research_tasks DROP COLUMN source_finding_id")
    prompt_guard(False)
    change_constraints(False)
    change_constraints(False, "finding_quality_controls")
