"""Keep named professional task routes inside immutable plan candidate history."""

import sqlalchemy as sa
from alembic import op

revision = "0226_plan_task_routing"
down_revision = "0225_template_generation_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE cehub_project.initial_plan_candidates
          ADD COLUMN routing_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE cehub_project.initial_plan_candidates ADD CONSTRAINT
          ck_initial_plan_candidates_initial_plan_routing_object
          CHECK(jsonb_typeof(routing_snapshot)='object');
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.initial_plan_candidates
          WHERE routing_snapshot<>'{}'::jsonb)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard named task routing history")
    op.drop_constraint(
        op.f("ck_initial_plan_candidates_initial_plan_routing_object"),
        "initial_plan_candidates",
        schema="cehub_project",
    )
    op.drop_column("initial_plan_candidates", "routing_snapshot", schema="cehub_project")
