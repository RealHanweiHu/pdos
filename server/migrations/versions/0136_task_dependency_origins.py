"""Preserve baseline Task dependency projections separately from manual edges."""

import sqlalchemy as sa
from alembic import op

revision = "0136_task_dependency_origins"
down_revision = "0135_formal_schedule_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_dependencies",
        sa.Column("baseline_id", sa.Uuid(), nullable=True),
        schema="cehub_project",
    )
    op.create_foreign_key(
        "fk_task_dependency_baseline",
        "task_dependencies",
        "schedule_time_records",
        ["tenant_id", "project_id", "baseline_id"],
        ["tenant_id", "project_id", "id"],
        source_schema="cehub_project",
        referent_schema="cehub_project",
        ondelete="RESTRICT",
    )
    # Only recover edges written in the original atomic application transaction,
    # for the two Tasks created and bound by that exact application. Other edges
    # remain manual; matching a current plan edge alone does not establish origin.
    op.execute(
        "\n        UPDATE cehub_project.task_dependencies d SET baseli"
        "ne_id=a.baseline_id\n        FROM cehub_project.initial_plan_"
        "applications a\n        JOIN cehub_project.task_plan_bindings"
        " child\n          ON child.tenant_id=a.tenant_id AND child.pr"
        "oject_id=a.project_id AND child.application_id=a.id\n        "
        "JOIN cehub_project.task_plan_bindings parent\n          ON pa"
        "rent.tenant_id=a.tenant_id AND parent.project_id=a.project_i"
        "d AND parent.application_id=a.id\n        JOIN cehub_project."
        "schedule_plan_dependencies e\n          ON e.tenant_id=a.tena"
        "nt_id AND e.project_id=a.project_id AND e.baseline_id=a.base"
        "line_id\n          AND e.successor_node_id=child.schedule_nod"
        "e_id AND e.predecessor_node_id=parent.schedule_node_id\n     "
        "     AND e.relation='fs' AND e.lag>=0\n        JOIN cehub_pro"
        "ject.tasks ct ON ct.tenant_id=a.tenant_id AND ct.project_id="
        "a.project_id\n          AND ct.id=child.task_id AND ct.create"
        "d_at=a.created_at\n        JOIN cehub_project.tasks pt ON pt."
        "tenant_id=a.tenant_id AND pt.project_id=a.project_id\n       "
        "   AND pt.id=parent.task_id AND pt.created_at=a.created_at\n "
        "       WHERE d.tenant_id=a.tenant_id AND d.project_id=a.proj"
        "ect_id AND d.task_id=child.task_id\n          AND d.depends_o"
        "n_task_id=parent.task_id AND d.created_at=a.created_at\n    "
    )
    op.drop_constraint(
        "uq_task_dependencies_tenant_project_edge",
        "task_dependencies",
        type_="unique",
        schema="cehub_project",
    )
    op.create_unique_constraint(
        "uq_task_dependency_baseline_edge",
        "task_dependencies",
        ["tenant_id", "baseline_id", "task_id", "depends_on_task_id"],
        schema="cehub_project",
    )
    op.create_index(
        "uq_task_dependency_manual_edge",
        "task_dependencies",
        ["tenant_id", "project_id", "task_id", "depends_on_task_id"],
        unique=True,
        schema="cehub_project",
        postgresql_where=sa.text("baseline_id IS NULL"),
    )
    op.execute(
        "\n        CREATE FUNCTION cehub_project.guard_task_dependency"
        "_origin() RETURNS trigger\n        LANGUAGE plpgsql SET searc"
        "h_path=pg_catalog AS $$\n        BEGIN\n          IF TG_OP='DE"
        "LETE' THEN\n            IF OLD.baseline_id IS NOT NULL THEN\n "
        "             RAISE EXCEPTION 'Baseline Task projections are "
        "immutable' USING ERRCODE='23514';\n            END IF;\n      "
        "      RETURN OLD;\n          END IF;\n          IF TG_OP='UPDA"
        "TE' AND (OLD.baseline_id IS NOT NULL OR NEW.baseline_id IS N"
        "OT NULL) THEN\n            RAISE EXCEPTION 'Task dependency o"
        "rigin cannot be rewritten' USING ERRCODE='23514';\n          "
        "END IF;\n          IF NEW.baseline_id IS NOT NULL AND NOT EXI"
        "STS (\n            SELECT 1 FROM cehub_project.schedule_plan_"
        "dependencies e\n            JOIN cehub_project.schedule_time_"
        "records b ON b.tenant_id=e.tenant_id\n              AND b.pro"
        "ject_id=e.project_id AND b.id=e.baseline_id AND b.time_kind="
        "'baseline'\n            JOIN cehub_project.schedule_nodes chi"
        "ld ON child.tenant_id=e.tenant_id\n              AND child.pr"
        "oject_id=e.project_id AND child.id=e.successor_node_id\n     "
        "       JOIN cehub_project.schedule_nodes parent ON parent.te"
        "nant_id=e.tenant_id\n              AND parent.project_id=e.pr"
        "oject_id AND parent.id=e.predecessor_node_id\n            WHE"
        "RE e.tenant_id=NEW.tenant_id AND e.project_id=NEW.project_id"
        " AND e.baseline_id=NEW.baseline_id\n              AND child.t"
        "ask_id=NEW.task_id AND parent.task_id=NEW.depends_on_task_id"
        "\n              AND e.relation='fs' AND e.lag>=0\n          ) "
        "THEN\n            RAISE EXCEPTION 'Task projection must match"
        " a baseline finish-start dependency' USING ERRCODE='23514';\n"
        "          END IF;\n          RETURN NEW;\n        END $$;\n    "
        "    CREATE TRIGGER guard_task_dependency_origin BEFORE INSER"
        "T OR UPDATE OR DELETE\n          ON cehub_project.task_depend"
        "encies FOR EACH ROW\n          EXECUTE FUNCTION cehub_project"
        ".guard_task_dependency_origin();\n        REVOKE ALL ON FUNCT"
        "ION cehub_project.guard_task_dependency_origin() FROM PUBLIC"
        ";\n    "
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.task_dependencies "
                "WHERE baseline_id IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard baseline dependency provenance")
    op.execute("DROP TRIGGER guard_task_dependency_origin ON cehub_project.task_dependencies")
    op.execute("DROP FUNCTION cehub_project.guard_task_dependency_origin()")
    op.drop_index(
        "uq_task_dependency_manual_edge", table_name="task_dependencies", schema="cehub_project"
    )
    op.drop_constraint(
        "uq_task_dependency_baseline_edge",
        "task_dependencies",
        type_="unique",
        schema="cehub_project",
    )
    op.create_unique_constraint(
        "uq_task_dependencies_tenant_project_edge",
        "task_dependencies",
        ["tenant_id", "project_id", "task_id", "depends_on_task_id"],
        schema="cehub_project",
    )
    op.drop_constraint(
        "fk_task_dependency_baseline",
        "task_dependencies",
        type_="foreignkey",
        schema="cehub_project",
    )
    op.drop_column("task_dependencies", "baseline_id", schema="cehub_project")
