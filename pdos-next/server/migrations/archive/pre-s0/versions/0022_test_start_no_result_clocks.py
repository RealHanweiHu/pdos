"""Keep actual test start separate from all result-return and disposition clocks."""

from alembic import op

revision = "next_0022"
down_revision = "next_0021"
branch_labels = None
depends_on = None

CHECK = (
    "operation <> 'test.run.start' OR COALESCE("
    "request_snapshot->'timeline'->'preliminary_result'='null'::jsonb AND "
    "request_snapshot->'timeline'->'final_result'='null'::jsonb AND "
    "request_snapshot->'timeline'->'disposed'='null'::jsonb, false)"
)


def upgrade():
    op.create_check_constraint(
        "ck_test_start_no_result_clocks", "verification_formal_requests", CHECK
    )


def downgrade():
    op.drop_constraint(
        "ck_test_start_no_result_clocks", "verification_formal_requests", type_="check"
    )
