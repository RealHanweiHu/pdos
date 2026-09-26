"""Distinguish deterministic forecast propagation from human authorship."""

import sqlalchemy as sa
from alembic import op

revision = "0145_schedule_propagation"
down_revision = "0144_cross_schedule_application"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "schedule_forecast_runs",
        "created_by_user_id",
        nullable=True,
        existing_type=sa.Uuid(),
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_schedule_forecast_runs_forecast_run_actor"),
        "schedule_forecast_runs",
        (
            "(created_by_user_id IS NULL AND COALESCE(inputs->>'trigger',"
            "'')='propagation') OR (created_by_user_id IS NOT NULL AND CO"
            "ALESCE(inputs->>'trigger','human') IN ('human','automatic'))"
        ),
        schema="cehub_project",
    )
    op.create_index(
        "uq_schedule_forecast_service_request",
        "schedule_forecast_runs",
        ["tenant_id", "request_id"],
        unique=True,
        schema="cehub_project",
        postgresql_where=sa.text("created_by_user_id IS NULL"),
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.schedule_forecast_"
                "runs WHERE created_by_user_id IS NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard system propagation authorship")
    op.drop_index(
        "uq_schedule_forecast_service_request",
        table_name="schedule_forecast_runs",
        schema="cehub_project",
    )
    op.drop_constraint(
        op.f("ck_schedule_forecast_runs_forecast_run_actor"),
        "schedule_forecast_runs",
        schema="cehub_project",
        type_="check",
    )
    op.alter_column(
        "schedule_forecast_runs",
        "created_by_user_id",
        nullable=False,
        existing_type=sa.Uuid(),
        schema="cehub_project",
    )
