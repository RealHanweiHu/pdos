"""Competitor and market candidate batches with fixed provenance and separate application."""

import json

from alembic import op
from sqlalchemy import String, literal, text

revision = "0399_product_evidence_findings"
down_revision = "0398_product_research_findings"
branch_labels = None
depends_on = None

TYPES = "('product_competitor_observations','product_market_segments')"
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
        "applied_entity_type IN ('competitor_observation','market_segment') AND "
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
CREATE FUNCTION cehub_ai.guard_product_evidence_finding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_ai.agent_runs; cp cehub_ai.application_result_checkpoints;
 actor uuid; cap text; field text; target text; total integer; first_id uuid;
BEGIN
 IF TG_OP='UPDATE' AND OLD.finding_type IN
  ('product_competitor_observations','product_market_segments')
  AND NEW.finding_type IS DISTINCT FROM OLD.finding_type THEN
  RAISE EXCEPTION 'Evidence finding type is immutable'; END IF;
 IF NEW.finding_type NOT IN ('product_competitor_observations','product_market_segments')
 THEN RETURN NEW; END IF;
 cap:=CASE NEW.finding_type WHEN 'product_competitor_observations' THEN 'competitor_analysis'
  ELSE 'market_analysis' END;
 field:=CASE cap WHEN 'competitor_analysis' THEN 'competitor_observations'
  ELSE 'market_segments' END;
 target:=CASE cap WHEN 'competitor_analysis' THEN 'competitor_observation'
  ELSE 'market_segment' END;
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
REVOKE ALL ON FUNCTION cehub_ai.guard_product_evidence_finding() FROM PUBLIC;
CREATE TRIGGER guard_product_evidence_finding BEFORE INSERT OR UPDATE ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_product_evidence_finding();
CREATE FUNCTION cehub_product.guard_evidence_finding_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE f cehub_ai.findings; r cehub_ai.agent_runs; item jsonb; expected jsonb; actual jsonb;
 o cehub_product.desired_outcomes;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF (NEW.source_finding_id,NEW.source_finding_position) IS DISTINCT FROM
   (OLD.source_finding_id,OLD.source_finding_position) THEN
   RAISE EXCEPTION 'Evidence AI origin is immutable'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.source_finding_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO f FROM cehub_ai.findings WHERE tenant_id=NEW.tenant_id AND id=NEW.source_finding_id
  AND finding_type=CASE TG_TABLE_NAME WHEN 'competitor_observations'
    THEN 'product_competitor_observations' ELSE 'product_market_segments' END AND status='accepted';
 SELECT * INTO r FROM cehub_ai.agent_runs WHERE tenant_id=NEW.tenant_id AND id=f.run_id;
 item:=f.accepted_payload->'proposal'->'items'->(NEW.source_finding_position-1);
 IF f.id IS NULL OR item IS NULL OR NEW.market_space_id IS DISTINCT FROM r.market_space_id
  OR NEW.product_line_id::text IS DISTINCT FROM
      r.run_context->'product_work_selection'->>'product_line_id'
  OR NEW.owner_user_id IS DISTINCT FROM r.requested_by_user_id
  OR NEW.supersedes_id IS NOT NULL OR NEW.version<>1
 THEN RAISE EXCEPTION 'Evidence record needs accepted original-scoped candidate'; END IF;
 expected:=item-'outcome';
 SELECT jsonb_object_agg(k,to_jsonb(NEW)->k) INTO actual FROM jsonb_object_keys(expected) k;
 IF actual IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'Evidence record must equal the accepted content'; END IF;
 IF TG_TABLE_NAME='market_segments' THEN
  SELECT * INTO o FROM cehub_product.desired_outcomes WHERE tenant_id=NEW.tenant_id
    AND id=NEW.desired_outcome_id;
  expected:=(item->'outcome')-'baseline_value'-'target_value';
  SELECT jsonb_object_agg(k,to_jsonb(o)->k) INTO actual FROM jsonb_object_keys(expected) k;
  IF o.id IS NULL OR actual IS DISTINCT FROM expected OR o.market_space_id<>NEW.market_space_id
   OR o.product_line_id IS DISTINCT FROM NEW.product_line_id OR o.owner_user_id<>NEW.owner_user_id
   OR o.baseline_value IS DISTINCT FROM (item->'outcome'->>'baseline_value')::numeric
   OR o.target_value IS DISTINCT FROM (item->'outcome'->>'target_value')::numeric
  THEN RAISE EXCEPTION 'Market outcome must match the accepted candidate'; END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_product.guard_evidence_finding_origin() FROM PUBLIC;
"""


def prompt_guard(add: bool) -> None:
    c = op.get_bind()
    ddl = c.execute(
        text("SELECT pg_get_functiondef('cehub_ai.guard_product_work_run()'::regprocedure)")
    ).scalar_one()
    old = "('product-work-v1','product-research-v2')"
    new = "('product-work-v1','product-research-v2','product-evidence-v3')"
    assert (old if add else new) in ddl
    op.execute(ddl.replace(old if add else new, new if add else old, 1))


def upgrade() -> None:
    constraints(True, "findings")
    constraints(True, "finding_quality_controls")
    prompt_guard(True)
    for table in ("competitor_observations", "market_segments"):
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
    for table in ("competitor_observations", "market_segments"):
        op.execute(f"""CREATE TRIGGER guard_evidence_finding_origin BEFORE INSERT OR UPDATE
        ON cehub_product.{table} FOR EACH ROW
        EXECUTE FUNCTION cehub_product.guard_evidence_finding_origin()""")


def downgrade() -> None:
    op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.findings
     WHERE finding_type IN {TYPES}) OR EXISTS(SELECT 1 FROM cehub_ai.agent_runs
     WHERE run_context->>'product_work_prompt_version'='product-evidence-v3') THEN
     RAISE EXCEPTION 'Retain product evidence candidates and original runs'; END IF; END $$;""")
    for table in ("competitor_observations", "market_segments"):
        op.execute(f"DROP TRIGGER guard_evidence_finding_origin ON cehub_product.{table}")
        op.execute(
            f"ALTER TABLE cehub_product.{table} DROP COLUMN source_finding_id, "
            "DROP COLUMN source_finding_position"
        )
    op.execute("DROP FUNCTION cehub_product.guard_evidence_finding_origin()")
    op.execute("DROP TRIGGER guard_product_evidence_finding ON cehub_ai.findings")
    op.execute("DROP FUNCTION cehub_ai.guard_product_evidence_finding()")
    prompt_guard(False)
    constraints(False, "finding_quality_controls")
    constraints(False, "findings")
