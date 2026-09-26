"""ID frozen feedback dispositions linked atomically to ECR governance."""

import sqlalchemy as sa
from alembic import op

revision = "0152_id_design_change_routing"
down_revision = "0151_id_handoff_reacceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_product.id_design_change_decisions (\n\tid"
        " UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID"
        " NOT NULL, \n\tcreated_by_user_id UUID NOT NULL, \n\trequest_id "
        "UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcrea"
        "ted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NO"
        "T NULL, \n\tcandidate_id UUID NOT NULL, \n\taction VARCHAR(16) N"
        "OT NULL, \n\tecr_id UUID, \n\tsnapshot JSONB NOT NULL, \n\tcandida"
        "te_digest VARCHAR(64) NOT NULL, \n\treason TEXT NOT NULL, \n\tCO"
        "NSTRAINT pk_id_design_change_decisions PRIMARY KEY (id), \n\tC"
        "ONSTRAINT uq_id_change_candidate_decision UNIQUE (tenant_id,"
        " candidate_id), \n\tCONSTRAINT ck_id_design_change_decisions_i"
        "d_change_decision_shape CHECK (action IN ('reject','route_ec"
        "r') AND ((action='route_ecr')=(ecr_id IS NOT NULL))), \n\tCONS"
        "TRAINT uq_id_design_change_decisions_scope UNIQUE (tenant_id"
        ", project_id, id), \n\tCONSTRAINT uq_id_design_change_decision"
        "s_request UNIQUE (tenant_id, created_by_user_id, request_id)"
        ", \n\tCONSTRAINT fk_id_design_change_decisions_tenant_id_proje"
        "cts FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_proj"
        "ect.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAIN"
        "T fk_id_design_change_decisions_tenant_id_users FOREIGN KEY("
        "tenant_id, created_by_user_id) REFERENCES cehub_core.users ("
        "tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_id_change"
        "_decision_candidate FOREIGN KEY(tenant_id, project_id, candi"
        "date_id) REFERENCES cehub_product.id_design_change_candidate"
        "s (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAI"
        "NT fk_id_change_decision_ecr FOREIGN KEY(tenant_id, project_"
        "id, ecr_id) REFERENCES cehub_product.engineering_change_requ"
        "ests (tenant_id, project_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_product.guard_id_change_decision() RET"
        "URNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS "
        "$$\nDECLARE candidate cehub_product.id_design_change_candidat"
        "es%ROWTYPE;\nBEGIN\n PERFORM 1 FROM cehub_project.projects WHE"
        "RE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;"
        "\n SELECT * INTO candidate FROM cehub_product.id_design_chang"
        "e_candidates WHERE tenant_id=NEW.tenant_id AND project_id=NE"
        "W.project_id AND id=NEW.candidate_id;\n IF candidate.id IS NU"
        "LL OR NEW.snapshot->'candidate'->>'id' IS DISTINCT FROM cand"
        "idate.id::text OR NEW.snapshot->'freeze'->>'id' IS DISTINCT "
        "FROM candidate.freeze_id::text OR NEW.snapshot->'feedback'->"
        ">'id' IS DISTINCT FROM candidate.feedback_id::text THEN RAIS"
        "E EXCEPTION 'Design change decision must bind the original f"
        "rozen feedback' USING ERRCODE='23514'; END IF;\n IF NEW.actio"
        "n='route_ecr' AND NOT EXISTS(SELECT 1 FROM cehub_product.eng"
        "ineering_change_requests WHERE tenant_id=NEW.tenant_id AND p"
        "roject_id=NEW.project_id AND id=NEW.ecr_id AND status IN ('r"
        "equest','impact_analysis')) THEN RAISE EXCEPTION 'New design"
        " requirements cannot inherit already submitted ECR approval'"
        " USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE "
        "TRIGGER guard_id_change_decision BEFORE INSERT ON cehub_prod"
        "uct.id_design_change_decisions FOR EACH ROW EXECUTE FUNCTION"
        " cehub_product.guard_id_change_decision();\nCREATE TRIGGER pr"
        "otect_capacity_history BEFORE UPDATE OR DELETE ON cehub_prod"
        "uct.id_design_change_decisions FOR EACH ROW EXECUTE FUNCTION"
        " cehub_project.protect_capacity_history();\nREVOKE ALL ON FUN"
        "CTION cehub_product.guard_id_change_decision() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.id_design_change_decisions)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard frozen design change decisions")
    op.drop_table("id_design_change_decisions", schema="cehub_product")
    op.execute("DROP FUNCTION cehub_product.guard_id_change_decision()")
