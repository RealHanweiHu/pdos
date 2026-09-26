"""Independent named commitment confirmation and scoped immutable deadline history."""

import sqlalchemy as sa
from alembic import op

revision = "0127_schedule_commitments"
down_revision = "0126_forecast_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.schedule_commitment_policies (\n\t"
        "id UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UU"
        "ID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tapprover_user_id "
        "UUID NOT NULL, \n\tauthority_basis TEXT NOT NULL, \n\tcreated_by"
        "_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\treques"
        "t_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH T"
        "IME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk"
        "_schedule_commitment_policies PRIMARY KEY (id), \n\tCONSTRAINT"
        " uq_schedule_commitment_policies_scope UNIQUE (tenant_id, id"
        "), \n\tCONSTRAINT uq_schedule_commitment_policies_version UNIQ"
        "UE (tenant_id, project_id, version), \n\tCONSTRAINT uq_schedul"
        "e_commitment_policies_request UNIQUE (tenant_id, created_by_"
        "user_id, request_id), \n\tCONSTRAINT fk_schedule_commitment_po"
        "licies_tenant_id_projects FOREIGN KEY(tenant_id, project_id)"
        " REFERENCES cehub_project.projects (tenant_id, id) ON DELETE"
        " RESTRICT, \n\tCONSTRAINT fk_schedule_commitment_policy_approv"
        "er FOREIGN KEY(tenant_id, approver_user_id) REFERENCES cehub"
        "_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT"
        " fk_schedule_commitment_policy_creator FOREIGN KEY(tenant_id"
        ", created_by_user_id) REFERENCES cehub_core.users (tenant_id"
        ", id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_schedule_commitmen"
        "t_policies_commitment_policy_valid CHECK (version>0 AND btri"
        "m(authority_basis)<>'')\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.schedule_commitment_confirmation"
        "s (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_"
        "id UUID NOT NULL, \n\trecord_id UUID NOT NULL, \n\tpolicy_id UUI"
        "D NOT NULL, \n\tforecast_record_id UUID NOT NULL, \n\tcapacity_c"
        "heck_id UUID NOT NULL, \n\tscope_label TEXT NOT NULL, \n\treason"
        " TEXT NOT NULL, \n\tsnapshot JSONB NOT NULL, \n\tpayload_digest "
        "VARCHAR(64) NOT NULL, \n\tapproved_by_user_id UUID NOT NULL, \n"
        "\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT "
        "NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_"
        "TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_schedule_commitment_conf"
        "irmations PRIMARY KEY (id), \n\tCONSTRAINT uq_schedule_commitm"
        "ent_confirmations_record UNIQUE (tenant_id, record_id), \n\tCO"
        "NSTRAINT uq_schedule_commitment_confirmations_request UNIQUE"
        " (tenant_id, approved_by_user_id, request_id), \n\tCONSTRAINT "
        "fk_schedule_commitment_confirmations_tenant_id_schedule_e3ce"
        " FOREIGN KEY(tenant_id, project_id, record_id) REFERENCES ce"
        "hub_project.schedule_time_records (tenant_id, project_id, id"
        ") ON DELETE RESTRICT, \n\tCONSTRAINT fk_schedule_commitment_co"
        "nfirmations_tenant_id_schedule_5b6c FOREIGN KEY(tenant_id, p"
        "olicy_id) REFERENCES cehub_project.schedule_commitment_polic"
        "ies (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_sche"
        "dule_commitment_confirmations_tenant_id_schedule_2bd5 FOREIG"
        "N KEY(tenant_id, forecast_record_id) REFERENCES cehub_projec"
        "t.schedule_forecast_runs (tenant_id, record_id) ON DELETE RE"
        "STRICT, \n\tCONSTRAINT fk_schedule_commitment_confirmations_te"
        "nant_id_forecast_0132 FOREIGN KEY(tenant_id, capacity_check_"
        "id) REFERENCES cehub_project.forecast_capacity_checks (tenan"
        "t_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_schedule_commi"
        "tment_confirmations_tenant_id_users FOREIGN KEY(tenant_id, a"
        "pproved_by_user_id) REFERENCES cehub_core.users (tenant_id, "
        "id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_schedule_commitment_poli"
        "cy() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_cat"
        "alog AS $$\nDECLARE latest integer;\nBEGIN\n PERFORM 1 FROM ceh"
        "ub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW"
        ".project_id FOR UPDATE;\n SELECT MAX(version) INTO latest FRO"
        "M cehub_project.schedule_commitment_policies WHERE tenant_id"
        "=NEW.tenant_id AND project_id=NEW.project_id;\n IF NEW.versio"
        "n<>COALESCE(latest,0)+1 OR NOT EXISTS(SELECT 1 FROM cehub_co"
        "re.users WHERE tenant_id=NEW.tenant_id AND id=NEW.created_by"
        "_user_id AND is_active AND role IN ('owner','admin')) THEN R"
        "AISE EXCEPTION 'Named commitment authority requires current "
        "administrator publication' USING ERRCODE='23514'; END IF;\n R"
        "ETURN NEW;\nEND $$;\nCREATE TRIGGER guard_schedule_commitment_"
        "policy BEFORE INSERT ON cehub_project.schedule_commitment_po"
        "licies FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_sch"
        "edule_commitment_policy();\nCREATE FUNCTION cehub_project.gua"
        "rd_schedule_commitment_confirmation() RETURNS trigger LANGUA"
        "GE plpgsql SET search_path=pg_catalog AS $$\nBEGIN\n IF NOT EX"
        "ISTS(SELECT 1 FROM cehub_project.schedule_commitment_policie"
        "s p JOIN cehub_project.schedule_time_records r ON r.tenant_i"
        "d=p.tenant_id AND r.project_id=p.project_id JOIN cehub_proje"
        "ct.forecast_capacity_checks c ON c.tenant_id=r.tenant_id AND"
        " c.project_id=r.project_id WHERE p.tenant_id=NEW.tenant_id A"
        "ND p.project_id=NEW.project_id AND p.id=NEW.policy_id AND p."
        "approver_user_id=NEW.approved_by_user_id AND r.id=NEW.record"
        "_id AND r.time_kind='commitment' AND r.contract->'approval'-"
        ">>'approval_id'=NEW.id::text AND r.contract->'approval'->>'p"
        "ayload_digest'=NEW.payload_digest AND r.contract->'approval'"
        "->>'approved_by_user_id'=NEW.approved_by_user_id::text AND c"
        ".id=NEW.capacity_check_id AND c.forecast_record_id=NEW.forec"
        "ast_record_id) OR EXISTS(SELECT 1 FROM cehub_project.schedul"
        "e_commitment_policies p JOIN cehub_project.schedule_commitme"
        "nt_policies used ON used.tenant_id=p.tenant_id AND used.proj"
        "ect_id=p.project_id WHERE used.id=NEW.policy_id AND p.versio"
        "n>used.version) THEN RAISE EXCEPTION 'Commitment must bind a"
        "ctual current authority, forecast and independent approval' "
        "USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE T"
        "RIGGER guard_schedule_commitment_confirmation BEFORE INSERT "
        "ON cehub_project.schedule_commitment_confirmations FOR EACH "
        "ROW EXECUTE FUNCTION cehub_project.guard_schedule_commitment"
        "_confirmation();\nCREATE FUNCTION cehub_project.require_commi"
        "tment_confirmation() RETURNS trigger LANGUAGE plpgsql SET se"
        "arch_path=pg_catalog AS $$\nBEGIN\n IF NEW.time_kind='commitme"
        "nt' AND NOT EXISTS(SELECT 1 FROM cehub_project.schedule_comm"
        "itment_confirmations WHERE tenant_id=NEW.tenant_id AND proje"
        "ct_id=NEW.project_id AND record_id=NEW.id) THEN RAISE EXCEPT"
        "ION 'Commitment time requires an independent confirmation re"
        "ceipt' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nC"
        "REATE CONSTRAINT TRIGGER require_commitment_confirmation AFT"
        "ER INSERT ON cehub_project.schedule_time_records DEFERRABLE "
        "INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_proje"
        "ct.require_commitment_confirmation();\nREVOKE ALL ON FUNCTION"
        " cehub_project.guard_schedule_commitment_policy(),cehub_proj"
        "ect.guard_schedule_commitment_confirmation(),cehub_project.r"
        "equire_commitment_confirmation() FROM PUBLIC;\nCREATE TRIGGER"
        " protect_capacity_history BEFORE UPDATE OR DELETE ON cehub_p"
        "roject.schedule_commitment_policies FOR EACH ROW EXECUTE FUN"
        "CTION cehub_project.protect_capacity_history();\nCREATE TRIGG"
        "ER protect_capacity_history BEFORE UPDATE OR DELETE ON cehub"
        "_project.schedule_commitment_confirmations FOR EACH ROW EXEC"
        "UTE FUNCTION cehub_project.protect_capacity_history();\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.schedule_commitmen"
                "t_policies) OR EXISTS(SELECT 1 FROM cehub_project.schedule_c"
                "ommitment_confirmations)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard commitment authority or confirmed deadlines")
    op.execute(
        "DROP TRIGGER require_commitment_confirmation ON cehub_project.schedule_time_records"
    )
    op.drop_table("schedule_commitment_confirmations", schema="cehub_project")
    op.drop_table("schedule_commitment_policies", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.require_commitment_confirmation()")
    op.execute("DROP FUNCTION cehub_project.guard_schedule_commitment_confirmation()")
    op.execute("DROP FUNCTION cehub_project.guard_schedule_commitment_policy()")
