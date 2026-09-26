"""Bind actual ID freeze evidence to formal task and milestone checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0157_id_design_checkpoints"
down_revision = "0156_id_feedback_continuity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_product.id_design_checkpoint_bindings (\n"
        "\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id U"
        "UID NOT NULL, \n\tcreated_by_user_id UUID NOT NULL, \n\trequest_"
        "id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tc"
        "reated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP"
        " NOT NULL, \n\tnode_id UUID NOT NULL, \n\tvariant_id UUID NOT NU"
        "LL, \n\tversion INTEGER NOT NULL, \n\tprevious_binding_id UUID, "
        "\n\tsnapshot JSONB NOT NULL, \n\ttarget_digest VARCHAR(64) NOT N"
        "ULL, \n\treason TEXT NOT NULL, \n\tCONSTRAINT pk_id_design_check"
        "point_bindings PRIMARY KEY (id), \n\tCONSTRAINT uq_id_checkpoi"
        "nt_version UNIQUE (tenant_id, node_id, version), \n\tCONSTRAIN"
        "T ck_id_design_checkpoint_bindings_id_checkpoint_binding_sha"
        "pe CHECK (version>0 AND ((version=1)=(previous_binding_id IS"
        " NULL))), \n\tCONSTRAINT uq_id_design_checkpoint_bindings_scop"
        "e UNIQUE (tenant_id, project_id, id), \n\tCONSTRAINT uq_id_des"
        "ign_checkpoint_bindings_request UNIQUE (tenant_id, created_b"
        "y_user_id, request_id), \n\tCONSTRAINT fk_id_design_checkpoint"
        "_bindings_tenant_id_projects FOREIGN KEY(tenant_id, project_"
        "id) REFERENCES cehub_project.projects (tenant_id, id) ON DEL"
        "ETE RESTRICT, \n\tCONSTRAINT fk_id_design_checkpoint_bindings_"
        "tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id) R"
        "EFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRIC"
        "T, \n\tCONSTRAINT fk_id_checkpoint_variant FOREIGN KEY(tenant_"
        "id, project_id, variant_id) REFERENCES cehub_product.id_desi"
        "gn_variants (tenant_id, project_id, id) ON DELETE RESTRICT, "
        "\n\tCONSTRAINT fk_id_checkpoint_previous FOREIGN KEY(tenant_id"
        ", project_id, previous_binding_id) REFERENCES cehub_product."
        "id_design_checkpoint_bindings (tenant_id, project_id, id) ON"
        " DELETE RESTRICT, \n\tCONSTRAINT fk_id_checkpoint_node FOREIGN"
        " KEY(tenant_id, project_id, node_id) REFERENCES cehub_projec"
        "t.schedule_nodes (tenant_id, project_id, id) ON DELETE RESTR"
        "ICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_product.guard_id_checkpoint_binding() "
        "RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog "
        "AS $$\nDECLARE previous cehub_product.id_design_checkpoint_bi"
        "ndings%ROWTYPE; node cehub_project.schedule_nodes%ROWTYPE;\nB"
        "EGIN\n PERFORM 1 FROM cehub_project.projects WHERE tenant_id="
        "NEW.tenant_id AND id=NEW.project_id FOR UPDATE;\n SELECT * IN"
        "TO previous FROM cehub_product.id_design_checkpoint_bindings"
        " WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id"
        " AND node_id=NEW.node_id ORDER BY version DESC LIMIT 1;\n SEL"
        "ECT * INTO node FROM cehub_project.schedule_nodes WHERE tena"
        "nt_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW"
        ".node_id;\n IF NEW.version<>COALESCE(previous.version,0)+1 OR"
        " NEW.previous_binding_id IS DISTINCT FROM previous.id OR nod"
        "e.id IS NULL OR node.node_kind NOT IN ('task','milestone') T"
        "HEN RAISE EXCEPTION 'ID checkpoint binding must append to th"
        "e exact scoped task or milestone' USING ERRCODE='23514'; END"
        " IF;\n IF EXISTS(SELECT 1 FROM cehub_project.tasks WHERE tena"
        "nt_id=NEW.tenant_id AND project_id=NEW.project_id AND id=nod"
        "e.task_id AND status IN ('done','skipped')) OR EXISTS(SELECT"
        " 1 FROM cehub_project.schedule_milestone_completions WHERE t"
        "enant_id=NEW.tenant_id AND project_id=NEW.project_id AND nod"
        "e_id=NEW.node_id) THEN RAISE EXCEPTION 'Completed checkpoint"
        " evidence bindings cannot be rewritten' USING ERRCODE='23514"
        "'; END IF;\n IF NEW.snapshot->'target'->>'node_id' IS DISTINC"
        "T FROM NEW.node_id::text OR NEW.snapshot->'variant'->>'id' I"
        "S DISTINCT FROM NEW.variant_id::text THEN RAISE EXCEPTION 'C"
        "heckpoint source and target snapshot mismatch' USING ERRCODE"
        "='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_"
        "id_checkpoint_binding BEFORE INSERT ON cehub_product.id_desi"
        "gn_checkpoint_bindings FOR EACH ROW EXECUTE FUNCTION cehub_p"
        "roduct.guard_id_checkpoint_binding();\nCREATE TRIGGER protect"
        "_capacity_history BEFORE UPDATE OR DELETE ON cehub_product.i"
        "d_design_checkpoint_bindings FOR EACH ROW EXECUTE FUNCTION c"
        "ehub_project.protect_capacity_history();\nREVOKE ALL ON FUNCT"
        "ION cehub_product.guard_id_checkpoint_binding() FROM PUBLIC;"
        "\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.id_design_checkpoint_bindings)")
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard ID checkpoint evidence bindings")
    op.drop_table("id_design_checkpoint_bindings", schema="cehub_product")
    op.execute("DROP FUNCTION cehub_product.guard_id_checkpoint_binding()")
