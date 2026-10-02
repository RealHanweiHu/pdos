"""Strategy and definition draft batches with fixed provenance and separate application."""

import json

from alembic import op
from sqlalchemy import String, literal, text

revision = "0401_product_planning_findings"
down_revision = "0400_product_discovery_findings"
branch_labels = None
depends_on = None

TYPES = "('product_strategy_drafts','product_definition_drafts')"
BRANCHES = {
    "scope": (
        "scope_kind='market_space' AND project_id IS NULL AND "
        f"agent_key='product_management_intelligence' AND finding_type IN {TYPES}"
    ),
    "type_allowed": f"agent_key='product_management_intelligence' AND finding_type IN {TYPES}",
    "evidence_event_ids_array": f"finding_type IN {TYPES} AND evidence_event_ids='[]'::jsonb",
    "apply_lifecycle_consistent": (
        f"finding_type IN {TYPES} AND status='applied' AND reviewed_by_user_id IS NOT "
        "NULL AND reviewed_at IS NOT NULL AND accepted_payload IS NOT NULL AND "
        "applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL AND "
        "applied_entity_type IN ('product_strategy','product_definition') AND "
        "applied_entity_id IS NOT NULL AND reviewed_at<applied_at"
    ),
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
CREATE FUNCTION cehub_ai.guard_product_planning_finding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints;
 actor uuid; cap text; field text; target text; total integer; first_id uuid;
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type IN
  ('product_strategy_drafts','product_definition_drafts')
  AND NEW.finding_type IS DISTINCT FROM OLD.finding_type THEN
  RAISE EXCEPTION 'Evidence finding type is immutable'; END IF;
 IF NEW.finding_type NOT IN ('product_strategy_drafts','product_definition_drafts')
 THEN RETURN NEW; END IF;
 cap:=CASE NEW.finding_type WHEN 'product_strategy_drafts' THEN 'product_strategy'
  ELSE 'product_definition' END;
 field:=CASE cap WHEN 'product_strategy' THEN 'product_strategies'
  ELSE 'product_definitions' END;
 target:=CASE cap WHEN 'product_strategy' THEN 'product_strategy'
  ELSE 'product_definition' END;
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id
  AND scope_kind='market_space' AND context_version='product-work-request-v1'
  AND agent_key='product_management_intelligence'
  AND run_context->'product_work_selection'->>'capability'=cap;
 IF r.id IS NULL OR NEW.scope_kind<>'market_space' OR NEW.project_id IS NOT NULL
  OR NEW.origin_key IS DISTINCT FROM 'product-evidence:'||r.id::text
  OR NEW.proposed_payload->>'source_digest' IS DISTINCT FROM
   r.run_context->'product_work_source'->>'digest'
 THEN RAISE EXCEPTION 'Evidence Finding requires original market request'; END IF;
 IF TG_OP='INSERT' THEN
  SELECT * INTO cp FROM cehub_ai.application_result_checkpoints WHERE tenant_id=NEW.tenant_id
   AND run_id=NEW.run_id AND invocation_id=NEW.model_invocation_id;
  IF NEW.status<>'pending_review' OR cp.id IS NULL OR cp.body->'output' IS DISTINCT FROM
   NEW.proposed_payload->'assessment' OR
   jsonb_typeof(cp.body->'output'->field) IS DISTINCT FROM 'array' OR
   jsonb_array_length(cp.body->'output'->field) NOT BETWEEN 1 AND 6 OR
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
    OR NEW.accepted_payload->'proposal'->>'capability' IS DISTINCT FROM cap
    OR jsonb_typeof(NEW.accepted_payload->'proposal'->'items') IS DISTINCT FROM 'array'
    OR jsonb_array_length(NEW.accepted_payload->'proposal'->'items') NOT BETWEEN 1 AND 6)
   THEN RAISE EXCEPTION 'Accepted evidence candidate must retain original capability'; END IF;
  ELSIF OLD.status='accepted' AND NEW.status='applied' THEN
   actor:=NEW.applied_by_user_id;
   IF (NEW.accepted_payload,NEW.reviewed_by_user_id,NEW.reviewed_at,NEW.review_comment)
    IS DISTINCT FROM (OLD.accepted_payload,OLD.reviewed_by_user_id,OLD.reviewed_at,
    OLD.review_comment) OR NEW.applied_entity_type IS DISTINCT FROM target
   THEN RAISE EXCEPTION 'Evidence apply retains accepted immutable payload'; END IF;
   EXECUTE format('SELECT count(*), (array_agg(id ORDER BY source_finding_position))[1]
    FROM cehub_product.%I WHERE tenant_id=$1 AND source_finding_id=$2',field)
    INTO total,first_id USING NEW.tenant_id,NEW.id;
   IF total IS DISTINCT FROM jsonb_array_length(NEW.accepted_payload->'proposal'->'items')
    OR NEW.applied_entity_id IS DISTINCT FROM first_id
   THEN RAISE EXCEPTION 'Evidence apply requires the complete domain batch'; END IF;
  ELSE RAISE EXCEPTION 'Evidence Finding requires separate acceptance and apply'; END IF;
  IF actor IS DISTINCT FROM r.requested_by_user_id OR NOT EXISTS(
   SELECT 1 FROM cehub_core.users u JOIN cehub_core.tenants ten ON ten.id=u.tenant_id
   JOIN cehub_product.market_spaces s ON s.tenant_id=u.tenant_id AND s.id=r.market_space_id
   WHERE u.tenant_id=NEW.tenant_id AND u.id=actor AND u.is_active AND ten.status='active'
    AND u.role IN ('owner','admin','project_manager','engineer','quality')
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
REVOKE ALL ON FUNCTION cehub_ai.guard_product_planning_finding() FROM PUBLIC;
CREATE TRIGGER guard_product_planning_finding BEFORE INSERT OR UPDATE ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_product_planning_finding();
CREATE FUNCTION cehub_product.guard_planning_finding_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE f cehub_ai.findings; r cehub_ai.agent_runs; item jsonb; expected jsonb; actual jsonb;
 parent jsonb; product jsonb; previous jsonb; normalized jsonb; child jsonb; work jsonb;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF (NEW.source_finding_id,NEW.source_finding_position) IS DISTINCT FROM
   (OLD.source_finding_id,OLD.source_finding_position) THEN
   RAISE EXCEPTION 'Planning AI origin is immutable'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.source_finding_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO f FROM cehub_ai.findings WHERE tenant_id=NEW.tenant_id AND id=NEW.source_finding_id
  AND finding_type=CASE TG_TABLE_NAME WHEN 'product_strategies'
    THEN 'product_strategy_drafts' ELSE 'product_definition_drafts' END AND status='accepted';
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=f.run_id;
 item:=f.accepted_payload->'proposal'->'items'->(NEW.source_finding_position-1);
 IF f.id IS NULL OR item IS NULL OR NEW.market_space_id IS DISTINCT FROM r.market_space_id
  OR NEW.product_line_id::text IS DISTINCT FROM
      r.run_context->'product_work_selection'->>'product_line_id'
  OR NEW.owner_user_id IS DISTINCT FROM r.requested_by_user_id
  OR NEW.created_by_user_id IS DISTINCT FROM r.requested_by_user_id
  OR NEW.version<>1 OR NEW.state<>'draft' OR NEW.approval IS NOT NULL
  OR NEW.supersedes_id IS DISTINCT FROM (item->>'supersedes_id')::uuid
 THEN RAISE EXCEPTION 'Planning record needs accepted original-scoped draft'; END IF;
 IF TG_TABLE_NAME='product_strategies' THEN
  SELECT ref->'fields' INTO parent FROM jsonb_array_elements(
   r.run_context->'product_work_source'->'references') ref
   WHERE ref->>'reference_id'='opportunity:'||NEW.opportunity_id::text;
  IF parent IS NULL OR parent->>'state'='closed' OR NEW.selected_solution_id IS NOT NULL
   OR jsonb_array_length(NEW.route_comparisons)<3
  THEN RAISE EXCEPTION 'Strategy requires original alternatives without selection'; END IF;
  FOR child IN SELECT * FROM jsonb_array_elements(NEW.route_comparisons) LOOP
   IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(parent->'solutions') solution
     WHERE solution->>'id'=child->>'solution_id')
   THEN RAISE EXCEPTION 'Strategy route is not an original solution'; END IF;
  END LOOP;
  IF NEW.supersedes_id IS NOT NULL THEN
   SELECT ref->'fields' INTO previous FROM jsonb_array_elements(
    r.run_context->'product_work_source'->'references') ref
    WHERE ref->>'reference_id'='strategy:'||NEW.supersedes_id::text;
   IF previous IS NULL OR previous->>'state'<>'published'
   THEN RAISE EXCEPTION 'Strategy revision needs original published source'; END IF;
  END IF;
  FOR child IN SELECT * FROM jsonb_array_elements(NEW.professional_constraints) LOOP
   IF child->'disposition' IS DISTINCT FROM 'null'::jsonb
   THEN RAISE EXCEPTION 'AI constraint cannot assert a disposition'; END IF;
   IF child->>'work_item_id' IS NOT NULL THEN
    SELECT ref->'fields' INTO work FROM jsonb_array_elements(
     r.run_context->'product_work_source'->'references') ref
     WHERE ref->>'reference_id'='work:'||(child->>'work_item_id');
    IF work IS NULL OR work->>'action_type' NOT IN ('discipline_review','constraint_review')
      OR work->>'state'='cancelled'
    THEN RAISE EXCEPTION 'Constraint work must be an original review source'; END IF;
   END IF;
  END LOOP;
  SELECT jsonb_agg(value-'id'-'disposition' ORDER BY ordinality) INTO normalized
   FROM jsonb_array_elements(NEW.professional_constraints) WITH ORDINALITY;
  IF normalized IS DISTINCT FROM item->'professional_constraints'
  THEN RAISE EXCEPTION 'Strategy constraints differ from accepted content'; END IF;
  expected:=item-'professional_constraints';
  SELECT jsonb_object_agg(k,to_jsonb(NEW)->k) INTO actual FROM jsonb_object_keys(expected) k;
 ELSE
  SELECT ref->'fields' INTO parent FROM jsonb_array_elements(
   r.run_context->'product_work_source'->'references') ref
   WHERE ref->>'reference_id'='strategy:'||NEW.strategy_id::text;
  SELECT ref->'fields' INTO product FROM jsonb_array_elements(
   r.run_context->'product_work_source'->'references') ref
   WHERE ref->>'reference_id'='product:'||NEW.product_id::text;
  IF parent IS NULL OR parent->>'state'<>'published' OR product IS NULL
   OR product->>'lifecycle'='retired' OR NEW.content->'reviewers'<>'{}'::jsonb
   OR NEW.content->>'owner_user_id' IS DISTINCT FROM r.requested_by_user_id::text
   OR NEW.published_at IS NOT NULL OR NEW.review_digest IS NOT NULL
   OR NEW.product_id IS DISTINCT FROM (item->>'product_id')::uuid
   OR NEW.strategy_id IS DISTINCT FROM (item->>'strategy_id')::uuid
  THEN RAISE EXCEPTION 'Definition requires original sources and draft state'; END IF;
  IF NEW.supersedes_id IS NOT NULL THEN
   SELECT ref->'fields' INTO previous FROM jsonb_array_elements(
    r.run_context->'product_work_source'->'references') ref
    WHERE ref->>'reference_id'='definition:'||NEW.supersedes_id::text;
   IF previous IS NULL OR previous->>'state'<>'published'
    OR previous->>'product_id' IS DISTINCT FROM NEW.product_id::text
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(previous->'content'->'items') old_item
      WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.content->'items') new_item
        WHERE new_item->>'item_key'=old_item->>'item_key'))
   THEN RAISE EXCEPTION 'Definition revision retains original published specification keys'; END IF;
  END IF;
  FOR child IN SELECT * FROM jsonb_array_elements(NEW.content->'items') LOOP
   IF child->>'state' IS DISTINCT FROM 'needs_confirmation' OR child->>'owner_user_id' IS NOT NULL
    OR child->>'disposition_reason' IS NOT NULL
   THEN RAISE EXCEPTION 'AI specification requires later confirmation and ownership'; END IF;
  END LOOP;
  SELECT jsonb_agg(value-'owner_user_id'-'state'-'disposition_reason' ORDER BY ordinality)
   INTO normalized FROM jsonb_array_elements(NEW.content->'items') WITH ORDINALITY;
  IF normalized IS DISTINCT FROM item->'items'
  THEN RAISE EXCEPTION 'Definition specifications differ from accepted content'; END IF;
  expected:=item-'product_id'-'strategy_id'-'supersedes_id'-'items';
  SELECT jsonb_object_agg(k,NEW.content->k) INTO actual FROM jsonb_object_keys(expected) k;
 END IF;
 IF actual IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'Planning record must equal the accepted content'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_product.guard_planning_finding_origin() FROM PUBLIC;
"""


def prompt_guard(add: bool) -> None:
    c = op.get_bind()
    ddl = c.execute(
        text("SELECT pg_get_functiondef('cehub_ai.guard_product_work_run()'::regprocedure)")
    ).scalar_one()
    old = "('product-work-v1','product-research-v2','product-evidence-v3','product-discovery-v4')"
    new = (
        "('product-work-v1','product-research-v2','product-evidence-v3',"
        "'product-discovery-v4','product-planning-v5')"
    )
    assert (old if add else new) in ddl
    op.execute(ddl.replace(old if add else new, new if add else old, 1))


def upgrade() -> None:
    constraints(True, "findings")
    constraints(True, "finding_quality_controls")
    prompt_guard(True)
    for table in ("product_strategies", "product_definitions"):
        op.execute(f"""ALTER TABLE cehub_product.{table}
         ADD COLUMN source_finding_id uuid, ADD COLUMN source_finding_position integer,
         ADD CONSTRAINT fk_{table}_source_finding FOREIGN KEY(tenant_id,source_finding_id)
          REFERENCES cehub_ai.findings(tenant_id,id) ON DELETE RESTRICT,
         ADD CONSTRAINT uq_{table}_source_finding_position
          UNIQUE(tenant_id,source_finding_id,source_finding_position),
         ADD CONSTRAINT ck_{table}_finding_position CHECK (
          (source_finding_id IS NULL AND source_finding_position IS NULL) OR
          (source_finding_id IS NOT NULL AND source_finding_position IS NOT NULL
           AND source_finding_position BETWEEN 1 AND 6))""")
    op.execute(DDL)
    for table in ("product_strategies", "product_definitions"):
        op.execute(f"""CREATE TRIGGER guard_planning_finding_origin BEFORE INSERT OR UPDATE
        ON cehub_product.{table} FOR EACH ROW
        EXECUTE FUNCTION cehub_product.guard_planning_finding_origin()""")


def downgrade() -> None:
    op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.findings
     WHERE finding_type IN {TYPES}) OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs
     WHERE run_context->>'product_work_prompt_version'='product-planning-v5') THEN
     RAISE EXCEPTION 'Retain product evidence candidates and original runs'; END IF; END $$;""")
    for table in ("product_strategies", "product_definitions"):
        op.execute(f"DROP TRIGGER guard_planning_finding_origin ON cehub_product.{table}")
        op.execute(
            f"ALTER TABLE cehub_product.{table} DROP COLUMN source_finding_id, "
            "DROP COLUMN source_finding_position"
        )
    op.execute("DROP FUNCTION cehub_product.guard_planning_finding_origin()")
    op.execute("DROP TRIGGER guard_product_planning_finding ON cehub_ai.findings")
    op.execute("DROP FUNCTION cehub_ai.guard_product_planning_finding()")
    prompt_guard(False)
    constraints(False, "finding_quality_controls")
    constraints(False, "findings")
