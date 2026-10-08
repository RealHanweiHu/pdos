"""Allow source-bound item Findings without weakening original review/apply guards."""

from alembic import op
from sqlalchemy import text

revision = "0416_product_evidence_item_decisions"
down_revision = "0415_product_planning_v6_runs"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "cehub_ai.guard_product_evidence_finding()",
    "cehub_ai.guard_product_discovery_finding()",
    "cehub_ai.guard_product_planning_finding()",
)
HELPER = r"""
CREATE FUNCTION cehub_ai.product_evidence_item_valid(f cehub_ai.findings, field text)
RETURNS boolean LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p cehub_ai.findings; pos integer; expected jsonb;
BEGIN
 IF f.proposed_payload->>'parent_finding_id' IS NULL THEN
  RETURN f.origin_key='product-evidence:'||f.run_id::text AND NOT EXISTS(
   SELECT 1 FROM cehub_ai.findings child WHERE child.tenant_id=f.tenant_id
    AND child.run_id=f.run_id
    AND child.proposed_payload->>'parent_finding_id'=f.id::text);
 END IF;
 IF f.proposed_payload->>'version' IS DISTINCT FROM 'product-evidence-item-v1'
  OR coalesce(f.proposed_payload->>'position','') !~ '^[1-6]$'
 THEN RETURN false; END IF;
 pos:=(f.proposed_payload->>'position')::integer;
 SELECT * INTO p FROM cehub_ai.findings WHERE tenant_id=f.tenant_id AND run_id=f.run_id
  AND id::text=f.proposed_payload->>'parent_finding_id' AND finding_type=f.finding_type
  FOR UPDATE;
 IF p.id IS NULL OR p.status<>'pending_review'
  OR p.proposed_payload->>'parent_finding_id' IS NOT NULL
  OR p.model_invocation_id IS DISTINCT FROM f.model_invocation_id
  OR p.agent_key IS DISTINCT FROM f.agent_key
  OR p.preflight_version IS DISTINCT FROM f.preflight_version
  OR p.evidence_event_ids IS DISTINCT FROM f.evidence_event_ids
  OR p.confidence_basis_points IS DISTINCT FROM f.confidence_basis_points
  OR f.origin_key IS DISTINCT FROM 'product-evidence:'||f.run_id::text||':item:'||pos::text
  OR f.proposed_payload->>'source_digest' IS DISTINCT FROM p.proposed_payload->>'source_digest'
  OR jsonb_array_length(p.proposed_payload->'assessment'->field)<pos
 THEN RETURN false; END IF;
 expected:=jsonb_set(p.proposed_payload->'assessment', ARRAY[field],
  jsonb_build_array(p.proposed_payload->'assessment'->field->(pos-1)));
 RETURN f.proposed_payload->'assessment' IS NOT DISTINCT FROM expected;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.product_evidence_item_valid(cehub_ai.findings,text) FROM PUBLIC;
"""
ORIGIN = "OR NEW.origin_key IS DISTINCT FROM 'product-evidence:'||r.id::text"
ITEM_ORIGIN = "OR NOT cehub_ai.product_evidence_item_valid(NEW,field)"
OUTPUT = "cp.body->'output' IS DISTINCT FROM\n   NEW.proposed_payload->'assessment'"
ITEM_OUTPUT = (
    "(cp.body->'output' IS DISTINCT FROM\n   NEW.proposed_payload->'assessment'\n"
    "   AND NOT (NEW.proposed_payload->>'version'='product-evidence-item-v1'\n"
    "    AND cehub_ai.product_evidence_item_valid(NEW,field)))"
)
ACCEPTED = "OR jsonb_array_length(NEW.accepted_payload->'proposal'->'items') NOT BETWEEN 1 AND 6"
ITEM_ACCEPTED = (
    ACCEPTED + "\n    OR (NEW.proposed_payload->>'version'='product-evidence-item-v1'\n"
    "     AND jsonb_array_length(NEW.accepted_payload->'proposal'->'items')<>1)"
)


def rewrite(*, forward: bool) -> None:
    for name in FUNCTIONS:
        definition = str(
            op.get_bind()
            .execute(text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": name})
            .scalar_one()
        )
        for old, new in ((ORIGIN, ITEM_ORIGIN), (OUTPUT, ITEM_OUTPUT), (ACCEPTED, ITEM_ACCEPTED)):
            source, target = (old, new) if forward else (new, old)
            if definition.count(source) != 1:
                raise RuntimeError(f"Expected immutable evidence guard unavailable: {name}")
            definition = definition.replace(source, target)
        op.execute(definition)


PUBLICATION = "IF TG_TABLE_NAME='findings' THEN rid:=NEW.run_id;"
ITEM_PUBLICATION = """IF TG_TABLE_NAME='findings' THEN
  IF NEW.proposed_payload->>'version'='product-evidence-item-v1'
   AND NEW.finding_type IN ('product_competitor_observations','product_market_segments',
    'product_opportunities','product_experiments','product_strategy_drafts','product_definition_drafts')
   AND cehub_ai.product_evidence_item_valid(NEW, CASE NEW.finding_type
    WHEN 'product_competitor_observations' THEN 'competitor_observations'
    WHEN 'product_market_segments' THEN 'market_segments'
    WHEN 'product_opportunities' THEN 'opportunities'
    WHEN 'product_experiments' THEN 'experiments'
    WHEN 'product_strategy_drafts' THEN 'product_strategies'
    ELSE 'product_definitions' END) THEN RETURN NEW; END IF;
  rid:=NEW.run_id;"""


def rewrite_publication(*, forward: bool) -> None:
    # A derived decision copies an already published immutable result. It is not
    # a fresh model publication. Every original Finding and run success keeps
    # the existing worker lease requirement; only the verified projection differs.
    name = "cehub_ai.require_application_publication_lease()"
    definition = str(
        op.get_bind()
        .execute(text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": name})
        .scalar_one()
    )
    source, target = (PUBLICATION, ITEM_PUBLICATION) if forward else (ITEM_PUBLICATION, PUBLICATION)
    if definition.count(source) != 1:
        raise RuntimeError("Expected application publication guard unavailable")
    op.execute(definition.replace(source, target))


def upgrade() -> None:
    op.execute(HELPER)
    rewrite(forward=True)
    rewrite_publication(forward=True)


def downgrade() -> None:
    op.execute("""
LOCK TABLE cehub_ai.findings IN SHARE ROW EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM cehub_ai.findings
  WHERE proposed_payload->>'version'='product-evidence-item-v1') THEN
  RAISE EXCEPTION 'Retain original item decisions before downgrading';
 END IF;
END $$;
""")
    rewrite_publication(forward=False)
    rewrite(forward=False)
    op.execute("DROP FUNCTION cehub_ai.product_evidence_item_valid(cehub_ai.findings,text)")
