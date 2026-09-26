"""Versioned industrial-design variants with exact-source feedback and dispositions."""

import sqlalchemy as sa
from alembic import op

revision = "0148_id_design_versions"
down_revision = "0147_cross_schedule_transfer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_external_file_references_scope",
        "external_file_references",
        ["tenant_id", "project_id", "id"],
        schema="cehub_project",
    )
    op.execute(
        "\nCREATE TABLE cehub_product.id_design_variants (\n\tid UUID NO"
        "T NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NUL"
        "L, \n\tcreated_by_user_id UUID NOT NULL, \n\trequest_id UUID NOT"
        " NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at T"
        "IMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "\n\ttitle VARCHAR(512) NOT NULL, \n\tCONSTRAINT pk_id_design_var"
        "iants PRIMARY KEY (id), \n\tCONSTRAINT uq_id_design_variants_s"
        "cope UNIQUE (tenant_id, project_id, id), \n\tCONSTRAINT uq_id_"
        "design_variants_request UNIQUE (tenant_id, created_by_user_i"
        "d, request_id), \n\tCONSTRAINT fk_id_design_variants_tenant_id"
        "_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehu"
        "b_project.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCON"
        "STRAINT fk_id_design_variants_tenant_id_users FOREIGN KEY(te"
        "nant_id, created_by_user_id) REFERENCES cehub_core.users (te"
        "nant_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_product.id_design_revisions (\n\tid UUID N"
        "OT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NU"
        "LL, \n\tcreated_by_user_id UUID NOT NULL, \n\trequest_id UUID NO"
        "T NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at "
        "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,"
        " \n\tvariant_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tp"
        "revious_revision_id UUID, \n\towner_user_id UUID NOT NULL, \n\tb"
        "rief TEXT NOT NULL, \n\tenvelope TEXT, \n\tcmf TEXT, \n\tlayout TE"
        "XT, \n\tinterfaces TEXT, \n\tdocument_id UUID, \n\texternal_file_r"
        "eference_id UUID, \n\tartifact_snapshot JSONB NOT NULL, \n\treas"
        "on TEXT NOT NULL, \n\tpayload_digest VARCHAR(64) NOT NULL, \n\tC"
        "ONSTRAINT pk_id_design_revisions PRIMARY KEY (id), \n\tCONSTRA"
        "INT uq_id_design_revision_version UNIQUE (tenant_id, variant"
        "_id, version), \n\tCONSTRAINT ck_id_design_revisions_id_design"
        "_revision_shape CHECK (version>0 AND (document_id IS NULL OR"
        " external_file_reference_id IS NULL)), \n\tCONSTRAINT uq_id_de"
        "sign_revisions_scope UNIQUE (tenant_id, project_id, id), \n\tC"
        "ONSTRAINT uq_id_design_revisions_request UNIQUE (tenant_id, "
        "created_by_user_id, request_id), \n\tCONSTRAINT fk_id_design_r"
        "evisions_tenant_id_projects FOREIGN KEY(tenant_id, project_i"
        "d) REFERENCES cehub_project.projects (tenant_id, id) ON DELE"
        "TE RESTRICT, \n\tCONSTRAINT fk_id_design_revisions_tenant_id_u"
        "sers FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES c"
        "ehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTR"
        "AINT fk_id_design_revision_variant FOREIGN KEY(tenant_id, pr"
        "oject_id, variant_id) REFERENCES cehub_product.id_design_var"
        "iants (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONS"
        "TRAINT fk_id_design_revision_previous FOREIGN KEY(tenant_id,"
        " project_id, previous_revision_id) REFERENCES cehub_product."
        "id_design_revisions (tenant_id, project_id, id) ON DELETE RE"
        "STRICT, \n\tCONSTRAINT fk_id_design_revisions_owner_user_id_us"
        "ers FOREIGN KEY(tenant_id, owner_user_id) REFERENCES cehub_c"
        "ore.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT f"
        "k_id_design_document FOREIGN KEY(tenant_id, project_id, docu"
        "ment_id) REFERENCES cehub_project.documents (tenant_id, proj"
        "ect_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_id_design_ex"
        "ternal_file FOREIGN KEY(tenant_id, project_id, external_file"
        "_reference_id) REFERENCES cehub_project.external_file_refere"
        "nces (tenant_id, project_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_product.id_design_feedback (\n\tid UUID NO"
        "T NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NUL"
        "L, \n\tcreated_by_user_id UUID NOT NULL, \n\trequest_id UUID NOT"
        " NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at T"
        "IMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "\n\trevision_id UUID NOT NULL, \n\tsource_kind VARCHAR(16) NOT N"
        "ULL, \n\tsource_reference TEXT NOT NULL, \n\treported_at TIMESTA"
        "MP WITH TIME ZONE, \n\ttopic VARCHAR(24) NOT NULL, \n\tcontent T"
        "EXT NOT NULL, \n\tCONSTRAINT pk_id_design_feedback PRIMARY KEY"
        " (id), \n\tCONSTRAINT ck_id_design_feedback_id_design_feedback"
        "_kind CHECK (source_kind IN ('customer','internal') AND topi"
        "c IN ('appearance','ergonomics','cmf','interface','cost','ot"
        "her')), \n\tCONSTRAINT uq_id_design_feedback_scope UNIQUE (ten"
        "ant_id, project_id, id), \n\tCONSTRAINT uq_id_design_feedback_"
        "request UNIQUE (tenant_id, created_by_user_id, request_id), "
        "\n\tCONSTRAINT fk_id_design_feedback_tenant_id_projects FOREIG"
        "N KEY(tenant_id, project_id) REFERENCES cehub_project.projec"
        "ts (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_id_de"
        "sign_feedback_tenant_id_users FOREIGN KEY(tenant_id, created"
        "_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON "
        "DELETE RESTRICT, \n\tCONSTRAINT fk_id_design_feedback_revision"
        " FOREIGN KEY(tenant_id, project_id, revision_id) REFERENCES "
        "cehub_product.id_design_revisions (tenant_id, project_id, id"
        ") ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_product.id_design_feedback_decisions (\n\t"
        "id UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UU"
        "ID NOT NULL, \n\tcreated_by_user_id UUID NOT NULL, \n\trequest_i"
        "d UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcr"
        "eated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP "
        "NOT NULL, \n\tfeedback_id UUID NOT NULL, \n\tversion INTEGER NOT"
        " NULL, \n\taction VARCHAR(24) NOT NULL, \n\tresolution_revision_"
        "id UUID, \n\treason TEXT NOT NULL, \n\tCONSTRAINT pk_id_design_f"
        "eedback_decisions PRIMARY KEY (id), \n\tCONSTRAINT uq_id_desig"
        "n_feedback_decision_version UNIQUE (tenant_id, feedback_id, "
        "version), \n\tCONSTRAINT ck_id_design_feedback_decisions_id_de"
        "sign_feedback_deci_c181 CHECK (version>0 AND action IN ('pla"
        "nned','needs_decision','rejected','addressed') AND ((action="
        "'addressed' AND resolution_revision_id IS NOT NULL) OR (acti"
        "on<>'addressed' AND resolution_revision_id IS NULL))), \n\tCON"
        "STRAINT uq_id_design_feedback_decisions_scope UNIQUE (tenant"
        "_id, project_id, id), \n\tCONSTRAINT uq_id_design_feedback_dec"
        "isions_request UNIQUE (tenant_id, created_by_user_id, reques"
        "t_id), \n\tCONSTRAINT fk_id_design_feedback_decisions_tenant_i"
        "d_projects FOREIGN KEY(tenant_id, project_id) REFERENCES ceh"
        "ub_project.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCO"
        "NSTRAINT fk_id_design_feedback_decisions_tenant_id_users FOR"
        "EIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_cor"
        "e.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_"
        "id_design_decision_feedback FOREIGN KEY(tenant_id, project_i"
        "d, feedback_id) REFERENCES cehub_product.id_design_feedback "
        "(tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT"
        " fk_id_design_decision_revision FOREIGN KEY(tenant_id, proje"
        "ct_id, resolution_revision_id) REFERENCES cehub_product.id_d"
        "esign_revisions (tenant_id, project_id, id) ON DELETE RESTRI"
        "CT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_product.guard_id_design_revision() RET"
        "URNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS "
        "$$\nDECLARE previous cehub_product.id_design_revisions%ROWTYP"
        "E;\nBEGIN\n PERFORM 1 FROM cehub_project.projects WHERE tenant"
        "_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;\n SELECT "
        "* INTO previous FROM cehub_product.id_design_revisions WHERE"
        " tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND v"
        "ariant_id=NEW.variant_id ORDER BY version DESC LIMIT 1;\n IF "
        "NEW.version<>COALESCE(previous.version,0)+1 OR NEW.previous_"
        "revision_id IS DISTINCT FROM previous.id THEN RAISE EXCEPTIO"
        "N 'Design revision must append to the exact current variant'"
        " USING ERRCODE='23514'; END IF;\n IF NEW.document_id IS NOT N"
        "ULL AND NOT EXISTS(SELECT 1 FROM cehub_project.documents WHE"
        "RE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND"
        " id=NEW.document_id AND NEW.artifact_snapshot->>'id'=id::tex"
        "t AND NEW.artifact_snapshot->>'kind'='document' AND NEW.arti"
        "fact_snapshot->>'digest'=sha256 AND NEW.artifact_snapshot->>"
        "'filename'=filename) THEN RAISE EXCEPTION 'Design artifact m"
        "ust match the scoped document' USING ERRCODE='23514'; END IF"
        ";\n IF NEW.external_file_reference_id IS NOT NULL AND NOT EXI"
        "STS(SELECT 1 FROM cehub_project.external_file_references WHE"
        "RE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND"
        " id=NEW.external_file_reference_id AND NEW.artifact_snapshot"
        "->>'id'=id::text AND NEW.artifact_snapshot->>'kind'='externa"
        "l' AND NEW.artifact_snapshot->>'digest'=source_hash AND NEW."
        "artifact_snapshot->>'filename'=filename) THEN RAISE EXCEPTIO"
        "N 'Design artifact must match the scoped external reference'"
        " USING ERRCODE='23514'; END IF;\n IF NEW.document_id IS NULL "
        "AND NEW.external_file_reference_id IS NULL AND NEW.artifact_"
        "snapshot<>'{}'::jsonb THEN RAISE EXCEPTION 'Unknown design a"
        "rtifact cannot contain fabricated references' USING ERRCODE="
        "'23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE FUNCTION cehub_"
        "product.guard_id_design_feedback_decision() RETURNS trigger "
        "LANGUAGE plpgsql SET search_path=pg_catalog AS $$\nDECLARE la"
        "test integer; original cehub_product.id_design_revisions%ROW"
        "TYPE;\nBEGIN\n PERFORM 1 FROM cehub_project.projects WHERE ten"
        "ant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;\n SELE"
        "CT max(version) INTO latest FROM cehub_product.id_design_fee"
        "dback_decisions WHERE tenant_id=NEW.tenant_id AND project_id"
        "=NEW.project_id AND feedback_id=NEW.feedback_id;\n IF NEW.ver"
        "sion<>COALESCE(latest,0)+1 THEN RAISE EXCEPTION 'Feedback op"
        "inions must append sequentially' USING ERRCODE='23514'; END "
        "IF;\n IF NEW.action='addressed' THEN\n  SELECT r.* INTO origin"
        "al FROM cehub_product.id_design_revisions r JOIN cehub_produ"
        "ct.id_design_feedback f ON f.tenant_id=r.tenant_id AND f.pro"
        "ject_id=r.project_id AND f.revision_id=r.id WHERE f.tenant_i"
        "d=NEW.tenant_id AND f.project_id=NEW.project_id AND f.id=NEW"
        ".feedback_id;\n  IF NOT EXISTS(SELECT 1 FROM cehub_product.id"
        "_design_revisions WHERE tenant_id=NEW.tenant_id AND project_"
        "id=NEW.project_id AND id=NEW.resolution_revision_id AND vari"
        "ant_id=original.variant_id AND version>original.version) THE"
        "N RAISE EXCEPTION 'Addressed feedback needs an actual later "
        "revision of the same variant' USING ERRCODE='23514'; END IF;"
        "\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_id_desig"
        "n_revision BEFORE INSERT ON cehub_product.id_design_revision"
        "s FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_id_desig"
        "n_revision();\nCREATE TRIGGER guard_id_design_feedback_decisi"
        "on BEFORE INSERT ON cehub_product.id_design_feedback_decisio"
        "ns FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_id_desi"
        "gn_feedback_decision();\nREVOKE ALL ON FUNCTION cehub_product"
        ".guard_id_design_revision(),cehub_product.guard_id_design_fe"
        "edback_decision() FROM PUBLIC;\nCREATE TRIGGER protect_capaci"
        "ty_history BEFORE UPDATE OR DELETE ON cehub_product.id_desig"
        "n_variants FOR EACH ROW EXECUTE FUNCTION cehub_project.prote"
        "ct_capacity_history();\nCREATE TRIGGER protect_capacity_histo"
        "ry BEFORE UPDATE OR DELETE ON cehub_product.id_design_revisi"
        "ons FOR EACH ROW EXECUTE FUNCTION cehub_project.protect_capa"
        "city_history();\nCREATE TRIGGER protect_capacity_history BEFO"
        "RE UPDATE OR DELETE ON cehub_product.id_design_feedback FOR "
        "EACH ROW EXECUTE FUNCTION cehub_project.protect_capacity_his"
        "tory();\nCREATE TRIGGER protect_capacity_history BEFORE UPDAT"
        "E OR DELETE ON cehub_product.id_design_feedback_decisions FO"
        "R EACH ROW EXECUTE FUNCTION cehub_project.protect_capacity_h"
        "istory();\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.id_design_variants)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard design and customer feedback history")
    op.drop_table("id_design_feedback_decisions", schema="cehub_product")
    op.drop_table("id_design_feedback", schema="cehub_product")
    op.drop_table("id_design_revisions", schema="cehub_product")
    op.drop_table("id_design_variants", schema="cehub_product")
    op.drop_constraint(
        "uq_external_file_references_scope",
        "external_file_references",
        schema="cehub_project",
        type_="unique",
    )
    op.execute("DROP FUNCTION cehub_product.guard_id_design_revision()")
    op.execute("DROP FUNCTION cehub_product.guard_id_design_feedback_decision()")
