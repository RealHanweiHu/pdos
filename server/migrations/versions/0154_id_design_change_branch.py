"""Approved ECR lineage for new draft ID design revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0154_id_design_change_branch"
down_revision = "0153_id_change_impact_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_product.id_design_change_branches (\n\tid "
        "UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID "
        "NOT NULL, \n\tcreated_by_user_id UUID NOT NULL, \n\trequest_id U"
        "UID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreat"
        "ed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT"
        " NULL, \n\tsource_freeze_id UUID NOT NULL, \n\tecr_id UUID NOT N"
        "ULL, \n\tvariant_id UUID NOT NULL, \n\tinitial_revision_id UUID "
        "NOT NULL, \n\tapproval_digest VARCHAR(64) NOT NULL, \n\tsnapshot"
        " JSONB NOT NULL, \n\treason TEXT NOT NULL, \n\tCONSTRAINT pk_id_"
        "design_change_branches PRIMARY KEY (id), \n\tCONSTRAINT uq_id_"
        "branch_source_ecr UNIQUE (tenant_id, source_freeze_id, ecr_i"
        "d), \n\tCONSTRAINT uq_id_branch_variant UNIQUE (tenant_id, var"
        "iant_id), \n\tCONSTRAINT uq_id_design_change_branches_scope UN"
        "IQUE (tenant_id, project_id, id), \n\tCONSTRAINT uq_id_design_"
        "change_branches_request UNIQUE (tenant_id, created_by_user_i"
        "d, request_id), \n\tCONSTRAINT fk_id_design_change_branches_te"
        "nant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENC"
        "ES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT"
        ", \n\tCONSTRAINT fk_id_design_change_branches_tenant_id_users "
        "FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_"
        "core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT "
        "fk_id_branch_source_freeze FOREIGN KEY(tenant_id, project_id"
        ", source_freeze_id) REFERENCES cehub_product.id_design_freez"
        "es (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRA"
        "INT fk_id_branch_ecr FOREIGN KEY(tenant_id, project_id, ecr_"
        "id) REFERENCES cehub_product.engineering_change_requests (te"
        "nant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk"
        "_id_branch_variant FOREIGN KEY(tenant_id, project_id, varian"
        "t_id) REFERENCES cehub_product.id_design_variants (tenant_id"
        ", project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_id_bra"
        "nch_initial_revision FOREIGN KEY(tenant_id, project_id, init"
        "ial_revision_id) REFERENCES cehub_product.id_design_revision"
        "s (tenant_id, project_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_product.guard_id_change_branch() RETUR"
        "NS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$"
        "\nDECLARE e cehub_product.engineering_change_requests%ROWTYPE"
        "; f cehub_product.id_design_freezes%ROWTYPE; r cehub_product"
        ".id_design_revisions%ROWTYPE;\nBEGIN\n PERFORM 1 FROM cehub_pr"
        "oject.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.proj"
        "ect_id FOR UPDATE;\n SELECT * INTO e FROM cehub_product.engin"
        "eering_change_requests WHERE tenant_id=NEW.tenant_id AND pro"
        "ject_id=NEW.project_id AND id=NEW.ecr_id;\n SELECT * INTO f F"
        "ROM cehub_product.id_design_freezes WHERE tenant_id=NEW.tena"
        "nt_id AND project_id=NEW.project_id AND id=NEW.source_freeze"
        "_id;\n SELECT * INTO r FROM cehub_product.id_design_revisions"
        " WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id"
        " AND id=NEW.initial_revision_id;\n IF e.id IS NULL OR e.statu"
        "s<>'approved' OR f.id IS NULL OR r.id IS NULL OR r.variant_i"
        "d<>NEW.variant_id OR r.version<>1 OR f.variant_id=NEW.varian"
        "t_id OR r.created_by_user_id<>NEW.created_by_user_id THEN RA"
        "ISE EXCEPTION 'Design revision branch requires approved ECR "
        "and a new scoped draft variant' USING ERRCODE='23514'; END I"
        "F;\n IF NEW.snapshot->'approval'->>'approval_decision_id' IS "
        "DISTINCT FROM e.approval_decision_id::text OR NEW.snapshot->"
        "'approval'->'impact_analysis' IS DISTINCT FROM e.impact_anal"
        "ysis OR NEW.snapshot->'source_freeze'->>'id' IS DISTINCT FRO"
        "M f.id::text OR NOT EXISTS(SELECT 1 FROM jsonb_array_element"
        "s(e.impact_analysis->'id_design'->'basis'->'links') l WHERE "
        "l->'snapshot'->'freeze'->>'id'=f.id::text) THEN RAISE EXCEPT"
        "ION 'Design branch must preserve the approved frozen feedbac"
        "k scope' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;"
        "\nCREATE TRIGGER guard_id_change_branch BEFORE INSERT ON cehu"
        "b_product.id_design_change_branches FOR EACH ROW EXECUTE FUN"
        "CTION cehub_product.guard_id_change_branch();\nCREATE TRIGGER"
        " protect_capacity_history BEFORE UPDATE OR DELETE ON cehub_p"
        "roduct.id_design_change_branches FOR EACH ROW EXECUTE FUNCTI"
        "ON cehub_project.protect_capacity_history();\nREVOKE ALL ON F"
        "UNCTION cehub_product.guard_id_change_branch() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.id_design_change_branches)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard approved ID revision lineage")
    op.drop_table("id_design_change_branches", schema="cehub_product")
    op.execute("DROP FUNCTION cehub_product.guard_id_change_branch()")
