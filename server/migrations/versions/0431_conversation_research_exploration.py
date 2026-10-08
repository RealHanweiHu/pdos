"""Append-only multi-round public research, with matching authorization and checkpoints."""

from importlib import import_module

from alembic import op
from sqlalchemy import text

revision = "0431_conversation_research_exploration"
down_revision = "0430_application_token_budget"
branch_labels = None
depends_on = None

PREVIOUS = import_module("migrations.versions.0423_xiaopai_conversation_search").CURRENT
OLD_OBSERVATION = PREVIOUS.split("\nCREATE FUNCTION cehub_ai.guard_xiaopai_research_receipt()", 1)[
    0
]
OLD_GUARD = (
    "CREATE OR REPLACE FUNCTION cehub_ai.guard_xiaopai_research_receipt()"
    + PREVIOUS.split("CREATE FUNCTION cehub_ai.guard_xiaopai_research_receipt()", 1)[1].split(
        "\nREVOKE ALL", 1
    )[0]
)
OBSERVATION = OLD_OBSERVATION.replace(
    "a.body->>'toolset_version'='xiaopai-public-research-v1'",
    "a.body->>'toolset_version' IN ('xiaopai-public-research-v1','xiaopai-public-research-v2')",
).replace(
    "i.input_body->>'version'='xiaopai-public-research-v1'",
    "i.input_body->>'version'=a.body->>'toolset_version' "
    "AND NEW.metadata->>'tool_version'=a.body->>'toolset_version'",
)

GUARD = """
CREATE OR REPLACE FUNCTION cehub_ai.guard_xiaopai_research_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous jsonb:=OLD.run_context->'reply_research';
 current_receipt jsonb:=NEW.run_context->'reply_research'; key text; prefix jsonb; last_round jsonb;
 token uuid:=nullif(current_setting('pdos.application_lease_id',true),'')::uuid;
BEGIN
 IF OLD.context_version<>'xiaopai-conversation-v1'
 OR current_receipt IS NOT DISTINCT FROM previous THEN RETURN NEW; END IF;
 IF previous IS NOT NULL AND previous->>'version'<>'xiaopai-public-research-v2' THEN
  RAISE EXCEPTION 'Conversation research receipt is immutable'; END IF;
 IF (current_receipt->>'version'='xiaopai-public-research-v2'
 AND NEW.status='running' AND cehub_ai.application_lease_is_current(NEW.id,token)
 AND EXISTS(SELECT 1 FROM cehub_ai.application_authorizations a WHERE a.tenant_id=NEW.tenant_id
  AND a.run_id=NEW.id AND a.body->>'purpose'='xiaopai_reply'
  AND a.body->>'toolset_version'='xiaopai-public-research-v2')) IS NOT TRUE THEN
  -- Legacy initial receipts remain compatible; their later replacement is forbidden above.
  IF previous IS NULL AND current_receipt->>'version'='xiaopai-public-research-v1'
  THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'CONVERSATION_RESEARCH_APPEND_INVALID'; END IF;
 FOREACH key IN ARRAY ARRAY['observations','references','pins','rounds'] LOOP
  IF jsonb_typeof(current_receipt->key) IS DISTINCT FROM 'array' THEN
   RAISE EXCEPTION 'CONVERSATION_RESEARCH_APPEND_INVALID'; END IF;
  SELECT coalesce(jsonb_agg(value ORDER BY ordinal),'[]'::jsonb) INTO prefix
   FROM jsonb_array_elements(current_receipt->key) WITH ORDINALITY e(value,ordinal)
   WHERE ordinal<=jsonb_array_length(coalesce(previous->key,'[]'::jsonb));
  IF prefix IS DISTINCT FROM coalesce(previous->key,'[]'::jsonb) THEN
   RAISE EXCEPTION 'Conversation research history is immutable'; END IF;
 END LOOP;
 IF jsonb_array_length(current_receipt->'rounds')<>
  jsonb_array_length(coalesce(previous->'rounds','[]'::jsonb))+1
 OR jsonb_array_length(current_receipt->'rounds')>7
 OR (SELECT count(*) FROM jsonb_array_elements(current_receipt->'observations') e
  WHERE e->'output'->>'tool'='search')>6
 OR (SELECT count(*) FROM jsonb_array_elements(current_receipt->'observations') e
  WHERE e->'output'->>'tool'='read')>24
 THEN RAISE EXCEPTION 'CONVERSATION_RESEARCH_APPEND_INVALID'; END IF;
 last_round:=current_receipt->'rounds'->-1;
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.application_result_checkpoints cp
  WHERE cp.tenant_id=NEW.tenant_id AND cp.run_id=NEW.id
  AND cp.model_call_id::text=last_round->>'model_call_id'
  AND cp.body->'output'->'research'=jsonb_build_object(
   'action',last_round->>'action','target',last_round->>'target'))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(current_receipt->'observations') e
  WHERE NOT EXISTS(SELECT 1 FROM cehub_ai.application_tool_observations o
   WHERE o.tenant_id=NEW.tenant_id AND o.run_id=NEW.id AND o.id::text=e->>'id'
   AND o.output_body=e->'output'))
 OR current_receipt->'references' IS DISTINCT FROM
  (SELECT coalesce(jsonb_agg(e->'output'->'reference' ORDER BY ordinal),'[]'::jsonb)
   FROM jsonb_array_elements(current_receipt->'observations') WITH ORDINALITY t(e,ordinal)
   WHERE e->'output' ? 'reference')
 OR current_receipt->'pins' IS DISTINCT FROM
  (SELECT coalesce(jsonb_agg(e->'output'->'pin' ORDER BY ordinal),'[]'::jsonb)
   FROM jsonb_array_elements(current_receipt->'observations') WITH ORDINALITY t(e,ordinal)
   WHERE e->'output' ? 'reference')
 THEN RAISE EXCEPTION 'CONVERSATION_RESEARCH_APPEND_INVALID'; END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(OBSERVATION)
    op.execute(GUARD)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            text("""SELECT EXISTS(SELECT 1 FROM cehub_ai.application_authorizations
      WHERE body->>'toolset_version'='xiaopai-public-research-v2')""")
        )
        .scalar_one()
    ):
        raise RuntimeError("Multi-round research history must be preserved")
    op.execute(OLD_OBSERVATION)
    op.execute(OLD_GUARD)
