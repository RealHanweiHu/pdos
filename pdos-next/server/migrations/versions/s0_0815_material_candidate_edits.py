# ruff: noqa: E501 -- frozen SQL statements
"""Bind named human edits to the original candidate and consumed T1 material."""

from alembic import op

from migrations.schema_s0_0746 import SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0815"
down_revision = "s0_0814"
branch_labels = None
depends_on = None

PREVIOUS = next(
    sql
    for sql in SCHEMA_SQL
    if sql.startswith("CREATE OR REPLACE FUNCTION public.m3_material_atom()")
)
OLD_MATCH = "IS DISTINCT FROM pc.payload"
NEW_MATCH = (
    "IS DISTINCT FROM (pc.payload || coalesce(confirmed_proof.snapshot->'human_edits','{}'::jsonb))"
)
EDIT_GUARD = """
   IF confirmed_proof.snapshot ? 'human_edits' THEN
    IF jsonb_typeof(confirmed_proof.snapshot->'human_edits') IS DISTINCT FROM 'object'
     OR confirmed_proof.snapshot->'human_edits' = '{}'::jsonb
     OR r.result->'human_edits' IS DISTINCT FROM confirmed_proof.snapshot->'human_edits'
     OR r.result->>'edited_by' IS DISTINCT FROM r.actor_id::text
     OR r.result->>'prepared_candidate_id' IS DISTINCT FROM pc.id::text
     OR EXISTS(SELECT 1 FROM jsonb_object_keys(confirmed_proof.snapshot->'human_edits') k
       WHERE NOT (CASE
        WHEN r.operation='category.knowledge.add' AND pc.payload->>'kind' IN ('competitor','voice') THEN k='content'
        WHEN r.operation='category.knowledge.withdraw' THEN k='reason'
        WHEN r.operation='category.parameter.publish' THEN k=ANY(ARRAY['name','value_type','enum_values','unit','direction','standard_condition','method','acceptance_criterion','change_note'])
          OR (k='key' AND pc.payload->>'parameter_id' IS NULL)
        ELSE false END)) THEN
     RAISE EXCEPTION 'material human edits require their named confirmation' USING ERRCODE='23514';
    END IF;
   END IF;
"""
ANCHOR = "   IF NEW.confirmed_by<>r.actor_id OR r.actor_id<>r.requester_id"
assert PREVIOUS.count(OLD_MATCH) == 1 and PREVIOUS.count(ANCHOR) == 1
CURRENT = PREVIOUS.replace(OLD_MATCH, NEW_MATCH).replace(ANCHOR, EDIT_GUARD + ANCHOR)


def upgrade():
    ordinary_owner()
    op.execute(CURRENT)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute(
        "LOCK TABLE action_receipts, confirmations, category_knowledge_entries, parameter_versions IN ACCESS EXCLUSIVE MODE"
    )
    if (
        op.get_bind()
        .exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM action_receipts WHERE operation IN ('category.knowledge.add','category.knowledge.withdraw','category.parameter.publish') AND result ? 'human_edits')"
        )
        .scalar_one()
    ):
        raise RuntimeError(
            "Human-edited material history exists; preserve it instead of downgrading"
        )
    op.execute(PREVIOUS)
    op.execute("SET LOCAL ROLE NONE")
