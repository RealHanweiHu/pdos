"""Allow fixed test resources after another scoped Run has been scheduled or started."""

import sqlalchemy as sa
from alembic import op

from migrations.schema_s0_0001 import SCHEMA_SQL

revision = "s0_0774"
down_revision = "s0_0773"
branch_labels = None
depends_on = None

SIGNATURE = "public.protect_test_resource_fact()"
_definitions = [
    sql for sql in SCHEMA_SQL if sql.startswith(f"CREATE OR REPLACE FUNCTION {SIGNATURE}\n")
]
if len(_definitions) != 1:
    raise RuntimeError("Expected the one frozen test-resource parent guard")
OLD_FUNCTION = _definitions[0]
OLD_PREDICATE = "parent.status<>'accepted'"
NEW_PREDICATE = "parent.status NOT IN ('accepted','scheduled','executing')"
if OLD_FUNCTION.count(OLD_PREDICATE) != 1 or OLD_FUNCTION.count("$function$") != 2:
    raise RuntimeError("Frozen test-resource parent guard does not match the reviewed predicate")
NEW_FUNCTION = OLD_FUNCTION.replace(OLD_PREDICATE, NEW_PREDICATE, 1)
OLD_BODY = OLD_FUNCTION.split("$function$")[1]
NEW_BODY = NEW_FUNCTION.split("$function$")[1]


def _replace_guard(expected_body, before, after):
    # Replace only the reviewed predicate in the actual function definition.
    # CREATE OR REPLACE retains its owner/ACL; every existing function attribute
    # (including search_path or security mode) is kept from pg_get_functiondef.
    definition, body = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT pg_get_functiondef(p.oid),p.prosrc FROM pg_proc p "
                "WHERE p.oid=to_regprocedure(:signature)"
            ),
            {"signature": SIGNATURE},
        )
        .one()
    )
    if body != expected_body or definition.count(before) != 1:
        raise RuntimeError("Unreviewed test-resource parent guard; no replacement was applied")
    op.execute(definition.replace(before, after, 1))


def upgrade():
    _replace_guard(OLD_BODY, OLD_PREDICATE, NEW_PREDICATE)


def downgrade():
    op.execute(
        "LOCK TABLE test_resource_facts,verification_formal_requests IN ACCESS EXCLUSIVE MODE"
    )
    op.execute("""DO $$ BEGIN
      IF EXISTS (
        SELECT 1 FROM test_resource_facts f
        JOIN verification_formal_requests p ON p.tenant_id=f.tenant_id
          AND p.product_id=f.product_id AND p.project_id=f.project_id
          AND p.build_id=f.build_id AND p.request_id=f.request_id
          AND p.id=f.accepted_request_id AND p.revision=f.accepted_request_revision
        WHERE p.status IN ('scheduled','executing')
      ) THEN
        RAISE EXCEPTION 'Advanced verification resource history requires s0_0774'
          USING ERRCODE='23514';
      END IF;
    END $$""")
    _replace_guard(NEW_BODY, NEW_PREDICATE, OLD_PREDICATE)
