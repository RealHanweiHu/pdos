"""Bind human category name and scene revisions to the original confirmed candidate."""

from alembic import op

from migrations.schema_s0_0747 import SCHEMA_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0816"
down_revision = "s0_0815"
branch_labels = None
depends_on = None

PREVIOUS = next(
    sql for sql in SCHEMA_SQL if "FUNCTION public.kernel_category_creation_proven(" in sql
)
ANCHOR = " body=event.body; source=body->'source'; skill=source->'skill'; input=body->'input';"
EDIT_GUARD = """
 IF payload ? 'human_edits' THEN
  IF jsonb_typeof(payload->'human_edits') IS DISTINCT FROM 'object'
   OR NOT (payload->'human_edits' ?& ARRAY['name','purpose'])
   OR ((payload->'human_edits')-ARRAY['name','purpose'])<>'{}'::jsonb
   OR jsonb_typeof(payload->'human_edits'->'name') IS DISTINCT FROM 'string'
   OR jsonb_typeof(payload->'human_edits'->'purpose') IS DISTINCT FROM 'string'
   OR NOT (length(btrim(payload->'human_edits'->>'name')) BETWEEN 1 AND 160)
   OR NOT (length(btrim(payload->'human_edits'->>'purpose')) BETWEEN 1 AND 4000)
   OR receipt.result->'human_edits' IS DISTINCT FROM payload->'human_edits'
   OR receipt.result->>'edited_by' IS DISTINCT FROM actor.id::text THEN RETURN false; END IF;
 ELSIF receipt.result ? 'human_edits' THEN RETURN false;
 END IF;
"""
assert PREVIOUS.count(ANCHOR) == 1
CURRENT = PREVIOUS.replace(ANCHOR, EDIT_GUARD + ANCHOR)
for field in ("name", "purpose"):
    old = f"category.{field} IS DISTINCT FROM input->>'{field}'"
    assert CURRENT.count(old) == 1
    CURRENT = CURRENT.replace(
        old,
        f"category.{field} IS DISTINCT FROM "
        f"coalesce(payload->'human_edits'->>'{field}',input->>'{field}')",
    )


def upgrade():
    ordinary_owner()
    op.execute(CURRENT)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute(
        "LOCK TABLE categories,action_receipts,category_creation_confirmations "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if (
        op.get_bind()
        .exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM action_receipts "
            "WHERE operation='category.create' AND result ? 'human_edits')"
        )
        .scalar_one()
    ):
        raise RuntimeError(
            "Human-edited category history exists; preserve it instead of downgrading"
        )
    op.execute(PREVIOUS)
    op.execute("SET LOCAL ROLE NONE")
