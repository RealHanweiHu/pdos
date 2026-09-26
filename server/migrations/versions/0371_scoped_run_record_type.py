"""Resolve market-only source types after the run scope is selected."""

from alembic import op

revision = "0371_scoped_run_record_type"
down_revision = "0370_conversation_run_guard"
branch_labels = None
depends_on = None

OLD_GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_ai.guard_market_matrix_run()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
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
END $function$
"""

GUARD = r"""
CREATE OR REPLACE FUNCTION cehub_ai.guard_market_matrix_run()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog'
AS $function$
DECLARE b record;
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
END $function$
"""


def upgrade() -> None:
    op.execute(GUARD)


def downgrade() -> None:
    op.execute(OLD_GUARD)
