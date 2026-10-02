"""RFQ T1 draft requirement batches bound to original files and durable model receipts."""

# ruff: noqa: E501
import json

from alembic import op
from sqlalchemy import String, literal, text

revision = "0404_product_rfq_requirements"
down_revision = "0403_product_source_files"
branch_labels = None
depends_on = None
BRANCHES = {
    "scope": "scope_kind='market_space' AND project_id IS NULL AND agent_key='product_management_intelligence' AND finding_type='product_rfq_requirements'",
    "type_allowed": "agent_key='product_management_intelligence' AND finding_type='product_rfq_requirements'",
    "evidence_event_ids_array": "finding_type='product_rfq_requirements' AND evidence_event_ids='[]'::jsonb",
    "apply_lifecycle_consistent": "finding_type='product_rfq_requirements' AND status='applied' AND reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL AND accepted_payload IS NOT NULL AND applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND applied_entity_type='requirement' AND applied_entity_id IS NOT NULL AND reviewed_at<applied_at",
}


def constraints(add: bool, table: str) -> None:
    c = op.get_bind()
    branches = BRANCHES if table == "findings" else {"type_allowed": BRANCHES["type_allowed"]}
    for name, branch in branches.items():
        full = f"ck_{table}_{name}"
        definition, comment = c.execute(
            text(
                "SELECT pg_get_constraintdef(oid),obj_description(oid,'pg_constraint') "
                f"FROM pg_constraint WHERE conrelid='cehub_ai.{table}'::regclass AND conname=:name"
            ),
            {"name": full},
        ).one()
        if add:
            prior = {"definition": definition, "comment": comment}
            expression = (
                f"({definition.removeprefix('CHECK (').removesuffix(')')}) OR ({branch}) IS TRUE"
            )
            restored_comment = json.dumps(prior)
        else:
            prior = json.loads(comment)
            expression = prior["definition"].removeprefix("CHECK (").removesuffix(")")
            restored_comment = prior["comment"]
        op.execute(f"ALTER TABLE cehub_ai.{table} DROP CONSTRAINT {full}")
        op.execute(f"ALTER TABLE cehub_ai.{table} ADD CONSTRAINT {full} CHECK ({expression})")
        encoded = str(
            literal(restored_comment, type_=String()).compile(
                dialect=c.dialect, compile_kwargs={"literal_binds": True}
            )
        )
        op.execute(f"COMMENT ON CONSTRAINT {full} ON cehub_ai.{table} IS {encoded}")


DDL = r"""
CREATE FUNCTION cehub_ai.guard_product_rfq_finding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints;
 actor uuid; cap text; field text; target text; total integer; first_id uuid;
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type IN
  ('product_rfq_requirements')
  AND NEW.finding_type IS DISTINCT FROM OLD.finding_type THEN
  RAISE EXCEPTION 'Evidence finding type is immutable'; END IF;
 IF NEW.finding_type NOT IN ('product_rfq_requirements')
 THEN RETURN NEW; END IF;
 cap:='rfq_requirements'; field:='requirements'; target:='requirement';
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id
  AND scope_kind='market_space' AND context_version='product-work-request-v1'
  AND agent_key='product_management_intelligence'
  AND run_context->>'product_work_prompt_version'='product-rfq-v6'
  AND run_context->'product_work_selection'->>'capability'=cap;
 IF r.id IS NULL OR NEW.scope_kind<>'market_space' OR NEW.project_id IS NOT NULL
  OR NEW.origin_key IS DISTINCT FROM 'product-rfq:'||r.id::text
  OR NEW.proposed_payload->>'source_digest' IS DISTINCT FROM
   r.run_context->'product_work_source'->>'digest'
 THEN RAISE EXCEPTION 'Evidence Finding requires original market request'; END IF;
 IF TG_OP='INSERT' THEN
  SELECT * INTO cp FROM cehub_ai.application_result_checkpoints WHERE tenant_id=NEW.tenant_id
   AND run_id=NEW.run_id AND invocation_id=NEW.model_invocation_id;
  IF NEW.status<>'pending_review' OR cp.id IS NULL OR cp.body->'output' IS DISTINCT FROM
   NEW.proposed_payload->'assessment' OR
   jsonb_typeof(cp.body->'output'->field) IS DISTINCT FROM 'array' OR
   jsonb_array_length(cp.body->'output'->field) NOT BETWEEN 1 AND 20 OR
   NOT cehub_ai.application_result_receipt_valid(cp.tenant_id,cp.run_id,cp.model_call_id,
     cp.observation_id,cp.manifest_id,cp.invocation_id,cp.owner_lease_id)
  THEN RAISE EXCEPTION 'Evidence Finding needs actual durable model result'; END IF;
 ELSE
  IF (NEW.id,NEW.tenant_id,NEW.run_id,NEW.model_invocation_id,NEW.agent_key,NEW.finding_type,
      NEW.origin_key,NEW.title,NEW.summary,NEW.proposed_payload,NEW.evidence_event_ids,
      NEW.confidence_basis_points,NEW.preflight_version,NEW.created_at) IS DISTINCT FROM
     (OLD.id,OLD.tenant_id,OLD.run_id,OLD.model_invocation_id,OLD.agent_key,OLD.finding_type,
      OLD.origin_key,OLD.title,OLD.summary,OLD.proposed_payload,OLD.evidence_event_ids,
      OLD.confidence_basis_points,OLD.preflight_version,OLD.created_at)
  THEN RAISE EXCEPTION 'Original evidence Finding is immutable'; END IF;
  IF OLD.status='pending_review' AND NEW.status IN ('accepted','rejected') THEN
   actor:=NEW.reviewed_by_user_id;
   IF NEW.status='accepted' AND (
    NEW.accepted_payload->>'source_digest' IS DISTINCT FROM NEW.proposed_payload->>'source_digest'
    OR jsonb_typeof(NEW.accepted_payload->'items') IS DISTINCT FROM 'array'
    OR jsonb_array_length(NEW.accepted_payload->'items') NOT BETWEEN 1 AND 20)
   THEN RAISE EXCEPTION 'Accepted evidence candidate must retain original capability'; END IF;
  ELSIF OLD.status='accepted' AND NEW.status='applied' THEN
   actor:=NEW.applied_by_user_id;
   IF (NEW.accepted_payload,NEW.reviewed_by_user_id,NEW.reviewed_at,NEW.review_comment)
    IS DISTINCT FROM (OLD.accepted_payload,OLD.reviewed_by_user_id,OLD.reviewed_at,
    OLD.review_comment) OR NEW.applied_entity_type IS DISTINCT FROM target
   THEN RAISE EXCEPTION 'Evidence apply retains accepted immutable payload'; END IF;
   SELECT count(*), (array_agg(requirement_id ORDER BY source_finding_position))[1]
    INTO total,first_id FROM cehub_product.product_rfq_requirement_links
    WHERE tenant_id=NEW.tenant_id AND source_finding_id=NEW.id;
   IF total IS DISTINCT FROM jsonb_array_length(NEW.accepted_payload->'items')
    OR NEW.applied_entity_id IS DISTINCT FROM first_id
   THEN RAISE EXCEPTION 'Evidence apply requires the complete domain batch'; END IF;
  ELSE RAISE EXCEPTION 'Evidence Finding requires separate acceptance and apply'; END IF;
  IF actor IS DISTINCT FROM r.requested_by_user_id OR NOT EXISTS(
   SELECT 1 FROM cehub_core.users u JOIN cehub_core.tenants ten ON ten.id=u.tenant_id
   JOIN cehub_product.market_spaces s ON s.tenant_id=u.tenant_id AND s.id=r.market_space_id
   WHERE u.tenant_id=NEW.tenant_id AND u.id=actor AND u.is_active AND ten.status='active'
    AND u.role IN ('owner','admin','project_manager')
    AND s.lifecycle<>'archived'
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
  ) THEN RAISE EXCEPTION 'Evidence review/apply needs current scoped original actor'; END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_product_rfq_finding() FROM PUBLIC;
CREATE TRIGGER guard_product_rfq_finding BEFORE INSERT OR UPDATE ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_product_rfq_finding();
"""

ORIGIN_DDL = r"""
CREATE FUNCTION cehub_product.guard_rfq_requirement_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE f cehub_ai.findings; r cehub_ai.agent_runs; req cehub_project.requirements; item jsonb;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'RFQ requirement origin is immutable'; END IF;
 SELECT * INTO f FROM cehub_ai.findings WHERE tenant_id=NEW.tenant_id
  AND id=NEW.source_finding_id AND finding_type='product_rfq_requirements' AND status='accepted';
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=f.run_id;
 SELECT * INTO req FROM cehub_project.requirements WHERE tenant_id=NEW.tenant_id AND id=NEW.requirement_id;
 item:=f.accepted_payload->'items'->(NEW.source_finding_position-1);
 IF f.id IS NULL OR item IS NULL OR NEW.accepted_item IS DISTINCT FROM item
  OR NEW.market_space_id IS DISTINCT FROM r.market_space_id OR req.id IS NULL
  OR req.created_by_user_id IS DISTINCT FROM r.requested_by_user_id OR req.status<>'draft'
  OR req.customer_id IS NOT NULL OR req.title IS DISTINCT FROM item->>'title'
  OR req.description IS DISTINCT FROM item->>'description' OR req.priority IS DISTINCT FROM item->>'priority'
  OR req.acceptance_criteria IS DISTINCT FROM item->'acceptance_criteria'
 THEN RAISE EXCEPTION 'RFQ requirement requires the accepted original-scoped draft'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_product.guard_rfq_requirement_origin() FROM PUBLIC,pdos_agent;
CREATE TRIGGER guard_rfq_requirement_origin BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_product.product_rfq_requirement_links FOR EACH ROW
 EXECUTE FUNCTION cehub_product.guard_rfq_requirement_origin();
REVOKE ALL ON cehub_product.product_rfq_requirement_links FROM PUBLIC,pdos_agent;
"""


def run_guard(add: bool) -> None:
    c = op.get_bind()
    ddl = c.execute(
        text("SELECT pg_get_functiondef('cehub_ai.guard_product_work_run()'::regprocedure)")
    ).scalar_one()
    pairs = [
        (
            "'product-discovery-v4','product-planning-v5')",
            "'product-discovery-v4','product-planning-v5','product-rfq-v6')",
        ),
        (
            "NOT IN ('research_planning','competitor_analysis',",
            "NOT IN ('rfq_requirements','research_planning','competitor_analysis',",
        ),
    ]
    for old, new in pairs:
        assert (old if add else new) in ddl
        ddl = ddl.replace(old if add else new, new if add else old, 1)
    op.execute(ddl)


def upgrade() -> None:
    constraints(True, "findings")
    constraints(True, "finding_quality_controls")
    run_guard(True)
    op.execute(TABLE_DDL)
    op.execute(DDL)
    op.execute(ORIGIN_DDL)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.findings WHERE finding_type='product_rfq_requirements')
     OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE run_context->>'product_work_prompt_version'='product-rfq-v6')
     THEN RAISE EXCEPTION 'Retain RFQ requirement history and original runs'; END IF; END $$;""")
    op.execute("DROP TABLE cehub_product.product_rfq_requirement_links")
    op.execute("DROP FUNCTION cehub_product.guard_rfq_requirement_origin()")
    op.execute("DROP TRIGGER guard_product_rfq_finding ON cehub_ai.findings")
    op.execute("DROP FUNCTION cehub_ai.guard_product_rfq_finding()")
    run_guard(False)
    constraints(False, "finding_quality_controls")
    constraints(False, "findings")


TABLE_DDL = "\nCREATE TABLE cehub_product.product_rfq_requirement_links (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT NULL, \n\tsource_finding_id UUID NOT NULL, \n\tsource_finding_position INTEGER NOT NULL, \n\trequirement_id UUID NOT NULL, \n\taccepted_item JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_product_rfq_requirement_links PRIMARY KEY (id), \n\tCONSTRAINT uq_product_rfq_requirement_links_position UNIQUE (tenant_id, source_finding_id, source_finding_position), \n\tCONSTRAINT uq_product_rfq_requirement_links_requirement UNIQUE (tenant_id, requirement_id), \n\tCONSTRAINT ck_product_rfq_requirement_links_item CHECK (source_finding_position BETWEEN 1 AND 20 AND jsonb_typeof(accepted_item)='object'), \n\tCONSTRAINT fk_product_rfq_requirement_links_tenant_id_market_spaces FOREIGN KEY(tenant_id, market_space_id) REFERENCES cehub_product.market_spaces (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_rfq_requirement_links_tenant_id_findings FOREIGN KEY(tenant_id, source_finding_id) REFERENCES cehub_ai.findings (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_rfq_requirement_links_tenant_id_requirements FOREIGN KEY(tenant_id, requirement_id) REFERENCES cehub_project.requirements (tenant_id, id) ON DELETE RESTRICT\n)\n\n"
