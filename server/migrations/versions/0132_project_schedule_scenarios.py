"""Immutable multi-object project schedule scenarios and typed node maps."""

import sqlalchemy as sa
from alembic import op

revision = "0132_project_schedule_scenarios"
down_revision = "0131_schedule_source_actuals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.project_schedule_scenarios (\n\tid"
        " UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID"
        " NOT NULL, \n\tbaseline_id UUID NOT NULL, \n\ttitle TEXT NOT NUL"
        "L, \n\treason TEXT NOT NULL, \n\tinputs JSONB NOT NULL, \n\tsnapsh"
        "ot JSONB NOT NULL, \n\tbasis_digest VARCHAR(64) NOT NULL, \n\tpl"
        "an JSONB NOT NULL, \n\tresult JSONB NOT NULL, \n\tresult_digest "
        "VARCHAR(64) NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\treque"
        "st_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, "
        "\n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMEST"
        "AMP NOT NULL, \n\tCONSTRAINT pk_project_schedule_scenarios PRI"
        "MARY KEY (id), \n\tCONSTRAINT uq_project_schedule_scenario_sco"
        "pe UNIQUE (tenant_id, project_id, id), \n\tCONSTRAINT uq_proje"
        "ct_schedule_scenario_request UNIQUE (tenant_id, actor_user_i"
        "d, request_id), \n\tCONSTRAINT fk_project_schedule_scenarios_t"
        "enant_id_schedule_time_records FOREIGN KEY(tenant_id, projec"
        "t_id, baseline_id) REFERENCES cehub_project.schedule_time_re"
        "cords (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONS"
        "TRAINT fk_project_schedule_scenarios_tenant_id_users FOREIGN"
        " KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users ("
        "tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_project_s"
        "chedule_scenarios_project_schedule_scenario_values CHECK (le"
        "ngth(trim(title))>0 AND length(trim(reason))>0 AND jsonb_typ"
        "eof(inputs)='object' AND jsonb_typeof(snapshot)='object' AND"
        " jsonb_typeof(plan)='object' AND jsonb_typeof(result)='objec"
        "t')\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.project_schedule_scenario_nodes "
        "(\n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tsc"
        "enario_id UUID NOT NULL, \n\tnode_id UUID NOT NULL, \n\tnode_key"
        " VARCHAR(128) NOT NULL, \n\tCONSTRAINT pk_project_schedule_sce"
        "nario_nodes PRIMARY KEY (tenant_id, scenario_id, node_id), \n"
        "\tCONSTRAINT uq_project_schedule_scenario_node_key UNIQUE (te"
        "nant_id, scenario_id, node_key), \n\tCONSTRAINT fk_project_sch"
        "edule_scenario_nodes_tenant_id_project_sc_4b65 FOREIGN KEY(t"
        "enant_id, project_id, scenario_id) REFERENCES cehub_project."
        "project_schedule_scenarios (tenant_id, project_id, id) ON DE"
        "LETE RESTRICT, \n\tCONSTRAINT fk_project_schedule_scenario_nod"
        "es_tenant_id_schedule_nodes FOREIGN KEY(tenant_id, project_i"
        "d, node_id) REFERENCES cehub_project.schedule_nodes (tenant_"
        "id, project_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_project_schedule_scenari"
        "o() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_cata"
        "log AS $$\nBEGIN\n IF NOT EXISTS(SELECT 1 FROM cehub_project.s"
        "chedule_time_records WHERE tenant_id=NEW.tenant_id AND proje"
        "ct_id=NEW.project_id AND id=NEW.baseline_id AND time_kind='b"
        "aseline') OR NEW.plan->>'id' IS DISTINCT FROM NEW.id::text O"
        "R NEW.plan->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::tex"
        "t OR NEW.plan->'scope'->>'kind' IS DISTINCT FROM 'project' O"
        "R NEW.plan->'scope'->>'ref_id' IS DISTINCT FROM NEW.project_"
        "id::text OR NEW.result->>'capacity_status' IS DISTINCT FROM "
        "'not_checked' OR NEW.result->>'applied' IS DISTINCT FROM 'fa"
        "lse' THEN RAISE EXCEPTION 'Project scenario must retain its "
        "baseline and remain an unapplied hypothesis' USING ERRCODE='"
        "23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_pr"
        "oject_schedule_scenario BEFORE INSERT ON cehub_project.proje"
        "ct_schedule_scenarios FOR EACH ROW EXECUTE FUNCTION cehub_pr"
        "oject.guard_project_schedule_scenario();\nCREATE FUNCTION ceh"
        "ub_project.guard_project_scenario_mapping() RETURNS trigger "
        "LANGUAGE plpgsql SET search_path=pg_catalog AS $$\nDECLARE sc"
        "enario cehub_project.project_schedule_scenarios%ROWTYPE; sce"
        "nario_id uuid;\nBEGIN\n IF TG_TABLE_NAME='project_schedule_sce"
        "narios' THEN scenario_id := NEW.id; ELSE scenario_id := NEW."
        "scenario_id; END IF;\n SELECT * INTO scenario FROM cehub_proj"
        "ect.project_schedule_scenarios WHERE tenant_id=NEW.tenant_id"
        " AND project_id=NEW.project_id AND id=scenario_id;\n IF (SELE"
        "CT count(*) FROM cehub_project.project_schedule_scenario_nod"
        "es n WHERE n.tenant_id=scenario.tenant_id AND n.scenario_id="
        "scenario.id) <> jsonb_array_length(scenario.plan->'nodes') O"
        "R EXISTS(SELECT 1 FROM jsonb_array_elements(scenario.plan->'"
        "nodes') p WHERE NOT EXISTS(SELECT 1 FROM cehub_project.proje"
        "ct_schedule_scenario_nodes n WHERE n.tenant_id=scenario.tena"
        "nt_id AND n.scenario_id=scenario.id AND n.node_key=p->>'node"
        "_key')) OR EXISTS(SELECT 1 FROM jsonb_array_elements(scenari"
        "o.plan->'dependencies') e WHERE NOT EXISTS(SELECT 1 FROM ceh"
        "ub_project.project_schedule_scenario_nodes n WHERE n.tenant_"
        "id=scenario.tenant_id AND n.scenario_id=scenario.id AND n.no"
        "de_key=e->>'predecessor') OR NOT EXISTS(SELECT 1 FROM cehub_"
        "project.project_schedule_scenario_nodes n WHERE n.tenant_id="
        "scenario.tenant_id AND n.scenario_id=scenario.id AND n.node_"
        "key=e->>'successor')) THEN RAISE EXCEPTION 'Scenario graph r"
        "equires complete scoped node mapping' USING ERRCODE='23514';"
        " END IF;\n RETURN NEW;\nEND $$;\nCREATE CONSTRAINT TRIGGER guar"
        "d_project_scenario_mapping AFTER INSERT ON cehub_project.pro"
        "ject_schedule_scenarios DEFERRABLE INITIALLY DEFERRED FOR EA"
        "CH ROW EXECUTE FUNCTION cehub_project.guard_project_scenario"
        "_mapping();\nCREATE CONSTRAINT TRIGGER guard_project_scenario"
        "_mapping AFTER INSERT ON cehub_project.project_schedule_scen"
        "ario_nodes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUT"
        "E FUNCTION cehub_project.guard_project_scenario_mapping();\nC"
        "REATE TRIGGER protect_capacity_history BEFORE UPDATE OR DELE"
        "TE ON cehub_project.project_schedule_scenarios FOR EACH ROW "
        "EXECUTE FUNCTION cehub_project.protect_capacity_history();\nC"
        "REATE TRIGGER protect_capacity_history BEFORE UPDATE OR DELE"
        "TE ON cehub_project.project_schedule_scenario_nodes FOR EACH"
        " ROW EXECUTE FUNCTION cehub_project.protect_capacity_history"
        "();\nREVOKE ALL ON FUNCTION cehub_project.guard_project_sched"
        "ule_scenario() FROM PUBLIC;\nREVOKE ALL ON FUNCTION cehub_pro"
        "ject.guard_project_scenario_mapping() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.project_schedule_scenarios)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard project schedule scenario evidence")
    op.drop_table("project_schedule_scenario_nodes", schema="cehub_project")
    op.drop_table("project_schedule_scenarios", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_project_scenario_mapping()")
    op.execute("DROP FUNCTION cehub_project.guard_project_schedule_scenario()")
