"""Immutable working calendars and reproducible initial-plan scenarios."""

import sqlalchemy as sa
from alembic import op

revision = "0116_plan_scenarios"
down_revision = "0115_initial_plan_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.work_calendar_versions (\n\tid UUI"
        "D NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcalendar_id UUID NO"
        "T NULL, \n\tversion INTEGER NOT NULL, \n\tname TEXT NOT NULL, \n\t"
        "definition JSONB NOT NULL, \n\tdefinition_digest VARCHAR(64) N"
        "OT NULL, \n\treason TEXT NOT NULL, \n\tcreated_by_user_id UUID N"
        "OT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHA"
        "R(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAUL"
        "T CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_work_calendar_"
        "versions PRIMARY KEY (id), \n\tCONSTRAINT uq_work_calendar_ver"
        "sions_scope UNIQUE (tenant_id, id), \n\tCONSTRAINT uq_work_cal"
        "endar_versions_number UNIQUE (tenant_id, calendar_id, versio"
        "n), \n\tCONSTRAINT uq_work_calendar_versions_request UNIQUE (t"
        "enant_id, created_by_user_id, request_id), \n\tCONSTRAINT fk_w"
        "ork_calendar_versions_tenant_id_users FOREIGN KEY(tenant_id,"
        " created_by_user_id) REFERENCES cehub_core.users (tenant_id,"
        " id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_work_calendar_versi"
        "ons_work_calendar_version_valid CHECK (version>0 AND btrim(n"
        "ame)<>'' AND definition_digest ~ '^[0-9a-f]{64}$')\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.initial_plan_scenarios (\n\tid UUI"
        "D NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcandidate_id UUID N"
        "OT NULL, \n\tinputs JSONB NOT NULL, \n\tresult JSONB NOT NULL, \n"
        "\tcandidate_digest VARCHAR(64) NOT NULL, \n\tresult_digest VARC"
        "HAR(64) NOT NULL, \n\tcreated_by_user_id UUID NOT NULL, \n\trequ"
        "est_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL,"
        " \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMES"
        "TAMP NOT NULL, \n\tCONSTRAINT pk_initial_plan_scenarios PRIMAR"
        "Y KEY (id), \n\tCONSTRAINT uq_initial_plan_scenarios_scope UNI"
        "QUE (tenant_id, id), \n\tCONSTRAINT uq_initial_plan_scenarios_"
        "request UNIQUE (tenant_id, candidate_id, created_by_user_id,"
        " request_id), \n\tCONSTRAINT fk_initial_plan_scenarios_tenant_"
        "id_initial_plan_candidates FOREIGN KEY(tenant_id, candidate_"
        "id) REFERENCES cehub_project.initial_plan_candidates (tenant"
        "_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_initial_plan_sc"
        "enarios_tenant_id_users FOREIGN KEY(tenant_id, created_by_us"
        "er_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE"
        " RESTRICT\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.initial_plan_scenario_calendars "
        "(\n\ttenant_id UUID NOT NULL, \n\tscenario_id UUID NOT NULL, \n\tc"
        "alendar_version_id UUID NOT NULL, \n\tCONSTRAINT pk_initial_pl"
        "an_scenario_calendars PRIMARY KEY (tenant_id, scenario_id, c"
        "alendar_version_id), \n\tCONSTRAINT fk_initial_plan_scenario_c"
        "alendars_tenant_id_initial_pl_a1a9 FOREIGN KEY(tenant_id, sc"
        "enario_id) REFERENCES cehub_project.initial_plan_scenarios ("
        "tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_initial_p"
        "lan_scenario_calendars_tenant_id_work_calen_e6f5 FOREIGN KEY"
        "(tenant_id, calendar_version_id) REFERENCES cehub_project.wo"
        "rk_calendar_versions (tenant_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.protect_work_calendar_version("
        ") RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalo"
        "g AS $$\nDECLARE latest integer;\nBEGIN\n IF TG_OP<>'INSERT' TH"
        "EN RAISE EXCEPTION 'Calendar versions are immutable' USING E"
        "RRCODE='42501'; END IF;\n PERFORM 1 FROM cehub_core.tenants W"
        "HERE id=NEW.tenant_id FOR UPDATE;\n SELECT MAX(version) INTO "
        "latest FROM cehub_project.work_calendar_versions WHERE tenan"
        "t_id=NEW.tenant_id AND calendar_id=NEW.calendar_id;\n IF NEW."
        "version<>COALESCE(latest,0)+1 OR NEW.definition->'calendar'-"
        ">>'id' IS DISTINCT FROM NEW.calendar_id::text OR NEW.definit"
        "ion->'calendar'->>'tenant_id' IS DISTINCT FROM NEW.tenant_id"
        "::text OR (NEW.definition->'calendar'->>'version')::integer "
        "IS DISTINCT FROM NEW.version THEN RAISE EXCEPTION 'Calendar "
        "contract or version mismatch' USING ERRCODE='23514'; END IF;"
        "\n RETURN NEW;\nEND $$;\nCREATE TRIGGER protect_work_calendar_v"
        "ersion BEFORE INSERT OR UPDATE OR DELETE ON cehub_project.wo"
        "rk_calendar_versions FOR EACH ROW EXECUTE FUNCTION cehub_pro"
        "ject.protect_work_calendar_version();\nCREATE FUNCTION cehub_"
        "project.protect_plan_scenario_history() RETURNS trigger LANG"
        "UAGE plpgsql SET search_path=pg_catalog AS $$\nBEGIN\n IF TG_O"
        "P<>'INSERT' THEN RAISE EXCEPTION 'Scenario input and result "
        "history are immutable' USING ERRCODE='42501'; END IF;\n RETUR"
        "N NEW;\nEND $$;\nCREATE TRIGGER protect_plan_scenario_history "
        "BEFORE UPDATE OR DELETE ON cehub_project.initial_plan_scenar"
        "ios FOR EACH ROW EXECUTE FUNCTION cehub_project.protect_plan"
        "_scenario_history();\nCREATE TRIGGER protect_plan_scenario_ca"
        "lendar_history BEFORE UPDATE OR DELETE ON cehub_project.init"
        "ial_plan_scenario_calendars FOR EACH ROW EXECUTE FUNCTION ce"
        "hub_project.protect_plan_scenario_history();\nREVOKE ALL ON F"
        "UNCTION cehub_project.protect_work_calendar_version(), cehub"
        "_project.protect_plan_scenario_history() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.work_calendar_vers"
                "ions) OR EXISTS(SELECT 1 FROM cehub_project.initial_plan_sce"
                "narios)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard calendar or scenario evidence")
    op.drop_table("initial_plan_scenario_calendars", schema="cehub_project")
    op.drop_table("initial_plan_scenarios", schema="cehub_project")
    op.drop_table("work_calendar_versions", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.protect_work_calendar_version()")
    op.execute("DROP FUNCTION cehub_project.protect_plan_scenario_history()")
