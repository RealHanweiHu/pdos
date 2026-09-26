"""Shared resource identity and immutable capacity scenario evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0118_resource_capacity"
down_revision = "0117_plan_responsibilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.planning_resources (\n\tid UUID NO"
        "T NULL, \n\ttenant_id UUID NOT NULL, \n\tname VARCHAR(256) NOT N"
        "ULL, \n\tkind VARCHAR(32) NOT NULL, \n\tuser_id UUID, \n\tcreated_"
        "by_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequ"
        "est_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH"
        " TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT "
        "pk_planning_resources PRIMARY KEY (id), \n\tCONSTRAINT uq_plan"
        "ning_resources_scope UNIQUE (tenant_id, id), \n\tCONSTRAINT uq"
        "_planning_resources_person UNIQUE (tenant_id, user_id), \n\tCO"
        "NSTRAINT uq_planning_resources_request UNIQUE (tenant_id, cr"
        "eated_by_user_id, request_id), \n\tCONSTRAINT fk_planning_reso"
        "urces_tenant_id_users FOREIGN KEY(tenant_id, user_id) REFERE"
        "NCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\t"
        "CONSTRAINT fk_planning_resources_created_by_user_id_users FO"
        "REIGN KEY(tenant_id, created_by_user_id) REFERENCES cehub_co"
        "re.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck"
        "_planning_resources_planning_resource_identity CHECK (btrim("
        "name)<>'' AND kind IN ('person','skill_group','laboratory','"
        "bench','equipment','mold','fixture','pilot_line') AND ((kind"
        "='person')=(user_id IS NOT NULL)))\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.resource_capacity_versions (\n\tid"
        " UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tresource_id UUI"
        "D NOT NULL, \n\tversion INTEGER NOT NULL, \n\tcalendar_version_i"
        "d UUID NOT NULL, \n\twindow_start TIMESTAMP WITH TIME ZONE NOT"
        " NULL, \n\twindow_end TIMESTAMP WITH TIME ZONE NOT NULL, \n\tpar"
        "allel_units NUMERIC(24, 8) NOT NULL, \n\tcapacity_contract JSO"
        "NB NOT NULL, \n\tcalendar_evidence JSONB NOT NULL, \n\tbasis TEX"
        "T NOT NULL, \n\tcreated_by_user_id UUID NOT NULL, \n\trequest_id"
        " UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcre"
        "ated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP N"
        "OT NULL, \n\tCONSTRAINT pk_resource_capacity_versions PRIMARY "
        "KEY (id), \n\tCONSTRAINT uq_resource_capacity_versions_scope U"
        "NIQUE (tenant_id, id), \n\tCONSTRAINT uq_resource_capacity_ver"
        "sions_number UNIQUE (tenant_id, resource_id, version), \n\tCON"
        "STRAINT uq_resource_capacity_versions_request UNIQUE (tenant"
        "_id, created_by_user_id, request_id), \n\tCONSTRAINT fk_resour"
        "ce_capacity_versions_tenant_id_planning_resources FOREIGN KE"
        "Y(tenant_id, resource_id) REFERENCES cehub_project.planning_"
        "resources (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT f"
        "k_resource_capacity_versions_tenant_id_work_calendar_version"
        "s FOREIGN KEY(tenant_id, calendar_version_id) REFERENCES ceh"
        "ub_project.work_calendar_versions (tenant_id, id) ON DELETE "
        "RESTRICT, \n\tCONSTRAINT fk_resource_capacity_versions_tenant_"
        "id_users FOREIGN KEY(tenant_id, created_by_user_id) REFERENC"
        "ES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCO"
        "NSTRAINT ck_resource_capacity_versions_resource_capacity_val"
        "id CHECK (version>0 AND window_end>window_start AND parallel"
        "_units>=0 AND parallel_units<=1000 AND btrim(basis)<>'')\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.plan_capacity_checks (\n\tid UUID "
        "NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tscenario_id UUID NOT "
        "NULL, \n\tinputs JSONB NOT NULL, \n\tresult JSONB NOT NULL, \n\tre"
        "sult_digest VARCHAR(64) NOT NULL, \n\tcreated_by_user_id UUID "
        "NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCH"
        "AR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAU"
        "LT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_plan_capacity"
        "_checks PRIMARY KEY (id), \n\tCONSTRAINT uq_plan_capacity_chec"
        "ks_scope UNIQUE (tenant_id, id), \n\tCONSTRAINT uq_plan_capaci"
        "ty_checks_request UNIQUE (tenant_id, scenario_id, created_by"
        "_user_id, request_id), \n\tCONSTRAINT fk_plan_capacity_checks_"
        "tenant_id_initial_plan_scenarios FOREIGN KEY(tenant_id, scen"
        "ario_id) REFERENCES cehub_project.initial_plan_scenarios (te"
        "nant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_plan_capaci"
        "ty_checks_tenant_id_users FOREIGN KEY(tenant_id, created_by_"
        "user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELE"
        "TE RESTRICT\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.plan_capacity_check_versions (\n\t"
        "tenant_id UUID NOT NULL, \n\tcheck_id UUID NOT NULL, \n\tcapacit"
        "y_version_id UUID NOT NULL, \n\tCONSTRAINT pk_plan_capacity_ch"
        "eck_versions PRIMARY KEY (tenant_id, check_id, capacity_vers"
        "ion_id), \n\tCONSTRAINT fk_plan_capacity_check_versions_tenant"
        "_id_plan_capacity_checks FOREIGN KEY(tenant_id, check_id) RE"
        "FERENCES cehub_project.plan_capacity_checks (tenant_id, id) "
        "ON DELETE RESTRICT, \n\tCONSTRAINT fk_plan_capacity_check_vers"
        "ions_tenant_id_resource_capa_83e4 FOREIGN KEY(tenant_id, cap"
        "acity_version_id) REFERENCES cehub_project.resource_capacity"
        "_versions (tenant_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.protect_capacity_history() RET"
        "URNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS "
        "$$\nBEGIN RAISE EXCEPTION 'Resource identity and capacity evi"
        "dence are immutable' USING ERRCODE='42501'; END $$;\nCREATE F"
        "UNCTION cehub_project.guard_capacity_version() RETURNS trigg"
        "er LANGUAGE plpgsql SET search_path=pg_catalog AS $$\nDECLARE"
        " latest integer; resource_kind text; calendar cehub_project."
        "work_calendar_versions%ROWTYPE;\nBEGIN\n SELECT kind INTO reso"
        "urce_kind FROM cehub_project.planning_resources WHERE tenant"
        "_id=NEW.tenant_id AND id=NEW.resource_id FOR UPDATE;\n SELECT"
        " MAX(version) INTO latest FROM cehub_project.resource_capaci"
        "ty_versions WHERE tenant_id=NEW.tenant_id AND resource_id=NE"
        "W.resource_id;\n SELECT * INTO calendar FROM cehub_project.wo"
        "rk_calendar_versions WHERE tenant_id=NEW.tenant_id AND id=NE"
        "W.calendar_version_id;\n IF resource_kind IS NULL OR calendar"
        ".id IS NULL OR NEW.version<>COALESCE(latest,0)+1 OR (resourc"
        "e_kind='person' AND NEW.parallel_units>1) THEN\n  RAISE EXCEP"
        "TION 'Invalid resource capacity version' USING ERRCODE='2351"
        "4';\n END IF;\n IF NEW.capacity_contract->>'id' IS DISTINCT FR"
        "OM NEW.id::text OR NEW.capacity_contract->>'tenant_id' IS DI"
        "STINCT FROM NEW.tenant_id::text OR NEW.capacity_contract->>'"
        "resource_id' IS DISTINCT FROM NEW.resource_id::text OR NEW.c"
        "apacity_contract->>'calendar_id' IS DISTINCT FROM calendar.c"
        "alendar_id::text OR (NEW.capacity_contract->>'calendar_versi"
        "on')::integer IS DISTINCT FROM calendar.version OR (NEW.capa"
        "city_contract->'window'->>'start')::timestamptz IS DISTINCT "
        "FROM NEW.window_start OR (NEW.capacity_contract->'window'->>"
        "'end')::timestamptz IS DISTINCT FROM NEW.window_end THEN\n  R"
        "AISE EXCEPTION 'Capacity contract identity mismatch' USING E"
        "RRCODE='23514';\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER"
        " guard_capacity_version BEFORE INSERT ON cehub_project.resou"
        "rce_capacity_versions FOR EACH ROW EXECUTE FUNCTION cehub_pr"
        "oject.guard_capacity_version();\nREVOKE ALL ON FUNCTION cehub"
        "_project.protect_capacity_history(), cehub_project.guard_cap"
        "acity_version() FROM PUBLIC;\n"
    )
    op.execute(
        "CREATE TRIGGER protect_capacity_history BEFORE UPDATE OR DEL"
        "ETE ON cehub_project.planning_resources FOR EACH ROW EXECUTE"
        " FUNCTION cehub_project.protect_capacity_history()"
    )
    op.execute(
        "CREATE TRIGGER protect_capacity_history BEFORE UPDATE OR DEL"
        "ETE ON cehub_project.resource_capacity_versions FOR EACH ROW"
        " EXECUTE FUNCTION cehub_project.protect_capacity_history()"
    )
    op.execute(
        "CREATE TRIGGER protect_capacity_history BEFORE UPDATE OR DEL"
        "ETE ON cehub_project.plan_capacity_checks FOR EACH ROW EXECU"
        "TE FUNCTION cehub_project.protect_capacity_history()"
    )
    op.execute(
        "CREATE TRIGGER protect_capacity_history BEFORE UPDATE OR DEL"
        "ETE ON cehub_project.plan_capacity_check_versions FOR EACH R"
        "OW EXECUTE FUNCTION cehub_project.protect_capacity_history()"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.planning_resources)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard resource or capacity history")
    op.drop_table("plan_capacity_check_versions", schema="cehub_project")
    op.drop_table("plan_capacity_checks", schema="cehub_project")
    op.drop_table("resource_capacity_versions", schema="cehub_project")
    op.drop_table("planning_resources", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_capacity_version()")
    op.execute("DROP FUNCTION cehub_project.protect_capacity_history()")
