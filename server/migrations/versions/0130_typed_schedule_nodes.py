"""Typed business ScheduleNodes and standalone milestones with scoped source integrity."""

import sqlalchemy as sa
from alembic import op

revision = "0130_typed_schedule_nodes"
down_revision = "0129_schedule_actual_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("schedule_nodes", "task_id", nullable=True, schema="cehub_project")
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD COLUMN node_kin"
        "d VARCHAR(24) DEFAULT 'task' NOT NULL"
    )
    op.execute("ALTER TABLE cehub_project.schedule_nodes ADD COLUMN gate_id UUID")
    op.execute("ALTER TABLE cehub_project.schedule_nodes ADD COLUMN build_id UUID")
    op.execute("ALTER TABLE cehub_project.schedule_nodes ADD COLUMN test_run_id UUID")
    op.execute("ALTER TABLE cehub_project.schedule_nodes ADD COLUMN certification_id UUID")
    op.execute("ALTER TABLE cehub_project.schedule_nodes ADD COLUMN title TEXT")
    op.execute("ALTER TABLE cehub_project.schedule_nodes ADD COLUMN completion_criteria TEXT")
    op.execute("ALTER TABLE cehub_project.schedule_nodes ADD COLUMN created_by_user_id UUID")
    op.execute("ALTER TABLE cehub_project.schedule_nodes ADD COLUMN request_id UUID")
    op.execute("ALTER TABLE cehub_project.schedule_nodes ADD COLUMN request_digest VARCHAR(64)")
    op.execute(
        "ALTER TABLE cehub_quality.test_runs ADD CONSTRAINT uq_test_r"
        "uns_project_id UNIQUE (tenant_id, project_id, id)"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT ck_s"
        "chedule_nodes_schedule_node_registration CHECK ((created_by_"
        "user_id IS NULL AND request_id IS NULL AND request_digest IS"
        " NULL) OR (created_by_user_id IS NOT NULL AND request_id IS "
        "NOT NULL AND request_digest IS NOT NULL))"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT ck_s"
        "chedule_nodes_schedule_node_typed_source CHECK ((node_kind='"
        "task' AND task_id IS NOT NULL AND num_nonnulls(task_id,gate_"
        "id,build_id,test_run_id,certification_id)=1) OR (node_kind='"
        "gate' AND gate_id IS NOT NULL AND num_nonnulls(task_id,gate_"
        "id,build_id,test_run_id,certification_id)=1) OR (node_kind='"
        "build' AND build_id IS NOT NULL AND num_nonnulls(task_id,gat"
        "e_id,build_id,test_run_id,certification_id)=1) OR (node_kind"
        "='test_run' AND test_run_id IS NOT NULL AND num_nonnulls(tas"
        "k_id,gate_id,build_id,test_run_id,certification_id)=1) OR (n"
        "ode_kind='certification' AND certification_id IS NOT NULL AN"
        "D num_nonnulls(task_id,gate_id,build_id,test_run_id,certific"
        "ation_id)=1) OR (node_kind='milestone' AND num_nonnulls(task"
        "_id,gate_id,build_id,test_run_id,certification_id)=0 AND tit"
        "le IS NOT NULL AND length(trim(title))>0 AND completion_crit"
        "eria IS NOT NULL AND length(trim(completion_criteria))>0))"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT fk_s"
        "chedule_node_build_id FOREIGN KEY(tenant_id, project_id, bui"
        "ld_id) REFERENCES cehub_product.build_batches (tenant_id, pr"
        "oject_id, id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT fk_s"
        "chedule_node_certification_id FOREIGN KEY(tenant_id, project"
        "_id, certification_id) REFERENCES cehub_quality.certificatio"
        "ns (tenant_id, project_id, id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT fk_s"
        "chedule_node_creator FOREIGN KEY(tenant_id, created_by_user_"
        "id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RE"
        "STRICT"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT fk_s"
        "chedule_node_gate_id FOREIGN KEY(tenant_id, project_id, gate"
        "_id) REFERENCES cehub_project.gates (tenant_id, project_id, "
        "id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT fk_s"
        "chedule_node_project FOREIGN KEY(tenant_id, project_id) REFE"
        "RENCES cehub_project.projects (tenant_id, id) ON DELETE REST"
        "RICT"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT fk_s"
        "chedule_node_test_run_id FOREIGN KEY(tenant_id, project_id, "
        "test_run_id) REFERENCES cehub_quality.test_runs (tenant_id, "
        "project_id, id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT uq_s"
        "chedule_node_build_id UNIQUE (tenant_id, build_id)"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT uq_s"
        "chedule_node_certification_id UNIQUE (tenant_id, certificati"
        "on_id)"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT uq_s"
        "chedule_node_gate_id UNIQUE (tenant_id, gate_id)"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT uq_s"
        "chedule_node_request UNIQUE (tenant_id, created_by_user_id, "
        "request_id)"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT uq_s"
        "chedule_node_test_run_id UNIQUE (tenant_id, test_run_id)"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_typed_schedule_node() RE"
        "TURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS"
        " $$\nDECLARE source_id uuid; calendar_id uuid;\nBEGIN\n SELECT "
        "c.calendar_id INTO calendar_id FROM cehub_project.work_calen"
        "dar_versions c WHERE c.tenant_id=NEW.tenant_id AND c.id=NEW."
        "calendar_version_id;\n IF calendar_id IS NULL OR NEW.contract"
        "->>'id' IS DISTINCT FROM NEW.id::text OR NEW.contract->>'ten"
        "ant_id' IS DISTINCT FROM NEW.tenant_id::text OR NEW.contract"
        "->>'project_id' IS DISTINCT FROM NEW.project_id::text OR NEW"
        ".contract->>'calendar_id' IS DISTINCT FROM calendar_id::text"
        " OR NEW.contract->>'node_kind' IS DISTINCT FROM NEW.node_kin"
        "d THEN RAISE EXCEPTION 'ScheduleNode contract must match pro"
        "ject, kind and pinned calendar' USING ERRCODE='23514'; END I"
        "F;\n source_id := COALESCE(NEW.task_id,NEW.gate_id,NEW.build_"
        "id,NEW.test_run_id,NEW.certification_id);\n IF NEW.node_kind="
        "'milestone' THEN\n  IF NEW.contract->'source' IS DISTINCT FRO"
        "M 'null'::jsonb THEN RAISE EXCEPTION 'Independent milestone "
        "cannot pretend to have a source' USING ERRCODE='23514'; END "
        "IF;\n ELSE\n  IF NEW.contract->'source'->>'ref_id' IS DISTINCT"
        " FROM source_id::text OR NEW.contract->'source'->>'kind' IS "
        "DISTINCT FROM NEW.node_kind OR NEW.contract->'source'->>'ten"
        "ant_id' IS DISTINCT FROM NEW.tenant_id::text OR NEW.contract"
        "->'source'->>'project_id' IS DISTINCT FROM NEW.project_id::t"
        "ext THEN RAISE EXCEPTION 'ScheduleNode source must match its"
        " typed foreign key' USING ERRCODE='23514'; END IF;\n END IF;\n"
        " RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_typed_schedule_nod"
        "e BEFORE INSERT ON cehub_project.schedule_nodes FOR EACH ROW"
        " EXECUTE FUNCTION cehub_project.guard_typed_schedule_node();"
        "\nREVOKE ALL ON FUNCTION cehub_project.guard_typed_schedule_n"
        "ode() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.schedule_nodes WHE"
                "RE node_kind<>'task' OR created_by_user_id IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard typed schedule nodes or registration evidence")
    op.execute("DROP TRIGGER guard_typed_schedule_node ON cehub_project.schedule_nodes")
    op.execute("DROP FUNCTION cehub_project.guard_typed_schedule_node()")
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT uq_schedule_node_test_run_id"
    )
    op.execute("ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT uq_schedule_node_request")
    op.execute("ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT uq_schedule_node_gate_id")
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT uq_schedule_node_certification_id"
    )
    op.execute("ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT uq_schedule_node_build_id")
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT fk_schedule_node_test_run_id"
    )
    op.execute("ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT fk_schedule_node_project")
    op.execute("ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT fk_schedule_node_gate_id")
    op.execute("ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT fk_schedule_node_creator")
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT fk_schedule_node_certification_id"
    )
    op.execute("ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT fk_schedule_node_build_id")
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT ck_"
        "schedule_nodes_schedule_node_typed_source"
    )
    op.execute(
        "ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT ck_"
        "schedule_nodes_schedule_node_registration"
    )
    op.drop_column("schedule_nodes", "request_digest", schema="cehub_project")
    op.drop_column("schedule_nodes", "request_id", schema="cehub_project")
    op.drop_column("schedule_nodes", "created_by_user_id", schema="cehub_project")
    op.drop_column("schedule_nodes", "completion_criteria", schema="cehub_project")
    op.drop_column("schedule_nodes", "title", schema="cehub_project")
    op.drop_column("schedule_nodes", "certification_id", schema="cehub_project")
    op.drop_column("schedule_nodes", "test_run_id", schema="cehub_project")
    op.drop_column("schedule_nodes", "build_id", schema="cehub_project")
    op.drop_column("schedule_nodes", "gate_id", schema="cehub_project")
    op.drop_column("schedule_nodes", "node_kind", schema="cehub_project")
    op.drop_constraint(
        "uq_test_runs_project_id", "test_runs", schema="cehub_quality", type_="unique"
    )
    op.alter_column("schedule_nodes", "task_id", nullable=False, schema="cehub_project")
