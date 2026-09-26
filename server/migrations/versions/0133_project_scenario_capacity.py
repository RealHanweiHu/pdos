"""Fixed project scenario capacity evidence and resource version references."""

import sqlalchemy as sa
from alembic import op

revision = "0133_project_scenario_capacity"
down_revision = "0132_project_schedule_scenarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.project_scenario_capacity_checks"
        " (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_i"
        "d UUID NOT NULL, \n\tscenario_id UUID NOT NULL, \n\tinputs JSONB"
        " NOT NULL, \n\tresult JSONB NOT NULL, \n\tresult_digest VARCHAR("
        "64) NOT NULL, \n\tscenario_basis_digest VARCHAR(64) NOT NULL, "
        "\n\tcreated_by_user_id UUID NOT NULL, \n\trequest_id UUID NOT NU"
        "LL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIME"
        "STAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tC"
        "ONSTRAINT pk_project_scenario_capacity_checks PRIMARY KEY (i"
        "d), \n\tCONSTRAINT uq_project_scenario_capacity_check_id UNIQU"
        "E (tenant_id, id), \n\tCONSTRAINT uq_project_scenario_capacity"
        "_check_scope UNIQUE (tenant_id, project_id, id), \n\tCONSTRAIN"
        "T uq_project_scenario_capacity_request UNIQUE (tenant_id, cr"
        "eated_by_user_id, request_id), \n\tCONSTRAINT fk_project_scena"
        "rio_capacity_checks_tenant_id_project_s_4ebb FOREIGN KEY(ten"
        "ant_id, project_id, scenario_id) REFERENCES cehub_project.pr"
        "oject_schedule_scenarios (tenant_id, project_id, id) ON DELE"
        "TE RESTRICT, \n\tCONSTRAINT fk_project_scenario_capacity_check"
        "s_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)"
        " REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTR"
        "ICT, \n\tCONSTRAINT ck_project_scenario_capacity_checks_projec"
        "t_scenario_ca_f311 CHECK (jsonb_typeof(inputs)='object' AND "
        "jsonb_typeof(result)='object')\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.project_scenario_capacity_versio"
        "ns (\n\ttenant_id UUID NOT NULL, \n\tcheck_id UUID NOT NULL, \n\tc"
        "apacity_version_id UUID NOT NULL, \n\tCONSTRAINT pk_project_sc"
        "enario_capacity_versions PRIMARY KEY (tenant_id, check_id, c"
        "apacity_version_id), \n\tCONSTRAINT fk_project_scenario_capaci"
        "ty_versions_tenant_id_project_9048 FOREIGN KEY(tenant_id, ch"
        "eck_id) REFERENCES cehub_project.project_scenario_capacity_c"
        "hecks (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_pr"
        "oject_scenario_capacity_versions_tenant_id_resourc_9675 FORE"
        "IGN KEY(tenant_id, capacity_version_id) REFERENCES cehub_pro"
        "ject.resource_capacity_versions (tenant_id, id) ON DELETE RE"
        "STRICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_project_scenario_capacit"
        "y() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_cata"
        "log AS $$\nBEGIN\n IF NOT EXISTS(SELECT 1 FROM cehub_project.p"
        "roject_schedule_scenarios s WHERE s.tenant_id=NEW.tenant_id "
        "AND s.project_id=NEW.project_id AND s.id=NEW.scenario_id AND"
        " s.basis_digest=NEW.scenario_basis_digest) OR NEW.result->>'"
        "project_scenario_id' IS DISTINCT FROM NEW.scenario_id::text "
        "OR NEW.result->>'baseline_changed' IS DISTINCT FROM 'false' "
        "THEN RAISE EXCEPTION 'Capacity evidence must bind its unchan"
        "ged project scenario' USING ERRCODE='23514'; END IF;\n RETURN"
        " NEW;\nEND $$;\nCREATE TRIGGER guard_project_scenario_capacity"
        " BEFORE INSERT ON cehub_project.project_scenario_capacity_ch"
        "ecks FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_proje"
        "ct_scenario_capacity();\nCREATE FUNCTION cehub_project.guard_"
        "project_capacity_versions() RETURNS trigger LANGUAGE plpgsql"
        " SET search_path=pg_catalog AS $$\nDECLARE item cehub_project"
        ".project_scenario_capacity_checks%ROWTYPE; check_ref uuid;\nB"
        "EGIN\n IF TG_TABLE_NAME='project_scenario_capacity_checks' TH"
        "EN check_ref := NEW.id; ELSE check_ref := NEW.check_id; END "
        "IF;\n SELECT * INTO item FROM cehub_project.project_scenario_"
        "capacity_checks WHERE tenant_id=NEW.tenant_id AND id=check_r"
        "ef;\n IF EXISTS(SELECT 1 FROM jsonb_array_elements(item.resul"
        "t->'profiles') p WHERE NOT EXISTS(SELECT 1 FROM cehub_projec"
        "t.project_scenario_capacity_versions v WHERE v.tenant_id=ite"
        "m.tenant_id AND v.check_id=item.id AND v.capacity_version_id"
        "=(p->>'id')::uuid)) OR EXISTS(SELECT 1 FROM cehub_project.pr"
        "oject_scenario_capacity_versions v WHERE v.tenant_id=item.te"
        "nant_id AND v.check_id=item.id AND NOT EXISTS(SELECT 1 FROM "
        "jsonb_array_elements(item.result->'profiles') p WHERE (p->>'"
        "id')::uuid=v.capacity_version_id)) THEN RAISE EXCEPTION 'Cap"
        "acity profiles require their actual immutable versions' USIN"
        "G ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE CONST"
        "RAINT TRIGGER guard_project_capacity_versions AFTER INSERT O"
        "N cehub_project.project_scenario_capacity_checks DEFERRABLE "
        "INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_proje"
        "ct.guard_project_capacity_versions();\nCREATE CONSTRAINT TRIG"
        "GER guard_project_capacity_versions AFTER INSERT ON cehub_pr"
        "oject.project_scenario_capacity_versions DEFERRABLE INITIALL"
        "Y DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_project.guard"
        "_project_capacity_versions();\nCREATE TRIGGER protect_capacit"
        "y_history BEFORE UPDATE OR DELETE ON cehub_project.project_s"
        "cenario_capacity_checks FOR EACH ROW EXECUTE FUNCTION cehub_"
        "project.protect_capacity_history();\nCREATE TRIGGER protect_c"
        "apacity_history BEFORE UPDATE OR DELETE ON cehub_project.pro"
        "ject_scenario_capacity_versions FOR EACH ROW EXECUTE FUNCTIO"
        "N cehub_project.protect_capacity_history();\nREVOKE ALL ON FU"
        "NCTION cehub_project.guard_project_scenario_capacity() FROM "
        "PUBLIC;\nREVOKE ALL ON FUNCTION cehub_project.guard_project_c"
        "apacity_versions() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.project_scenario_capacity_checks)")
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard project scenario capacity evidence")
    op.drop_table("project_scenario_capacity_versions", schema="cehub_project")
    op.drop_table("project_scenario_capacity_checks", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_project_capacity_versions()")
    op.execute("DROP FUNCTION cehub_project.guard_project_scenario_capacity()")
