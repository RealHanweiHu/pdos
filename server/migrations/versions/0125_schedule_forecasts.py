"""Immutable forecast versions and pointwise prediction error history."""

import sqlalchemy as sa
from alembic import op

revision = "0125_schedule_forecasts"
down_revision = "0124_scheduled_task_actuals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.schedule_forecast_runs (\n\ttenant"
        "_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\trecord_id U"
        "UID NOT NULL, \n\tbaseline_id UUID NOT NULL, \n\tinputs JSONB NO"
        "T NULL, \n\tresult JSONB NOT NULL, \n\tbasis_digest VARCHAR(64) "
        "NOT NULL, \n\treason TEXT NOT NULL, \n\tcreated_by_user_id UUID "
        "NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCH"
        "AR(64) NOT NULL, \n\tCONSTRAINT pk_schedule_forecast_runs PRIM"
        "ARY KEY (tenant_id, record_id), \n\tCONSTRAINT uq_schedule_for"
        "ecast_runs_request UNIQUE (tenant_id, created_by_user_id, re"
        "quest_id), \n\tCONSTRAINT fk_schedule_forecast_runs_record FOR"
        "EIGN KEY(tenant_id, project_id, record_id) REFERENCES cehub_"
        "project.schedule_time_records (tenant_id, project_id, id) ON"
        " DELETE RESTRICT, \n\tCONSTRAINT fk_schedule_forecast_runs_bas"
        "eline FOREIGN KEY(tenant_id, project_id, baseline_id) REFERE"
        "NCES cehub_project.schedule_time_records (tenant_id, project"
        "_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_schedule_foreca"
        "st_runs_tenant_id_users FOREIGN KEY(tenant_id, created_by_us"
        "er_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE"
        " RESTRICT\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.schedule_forecast_errors (\n\ttena"
        "nt_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tforecast_"
        "record_id UUID NOT NULL, \n\tnode_id UUID NOT NULL, \n\tpoint VA"
        "RCHAR(8) NOT NULL, \n\tevent_row_id BIGINT NOT NULL, \n\tpredict"
        "ed_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tobserved_at TIMES"
        "TAMP WITH TIME ZONE NOT NULL, \n\terror_seconds NUMERIC(24, 6)"
        " NOT NULL, \n\tCONSTRAINT pk_schedule_forecast_errors PRIMARY "
        "KEY (tenant_id, forecast_record_id, node_id, point), \n\tCONST"
        "RAINT fk_schedule_forecast_errors_tenant_id_schedule_time_re"
        "cords FOREIGN KEY(tenant_id, project_id, forecast_record_id)"
        " REFERENCES cehub_project.schedule_time_records (tenant_id, "
        "project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_schedule"
        "_forecast_errors_tenant_id_scheduled_task_ob_0d78 FOREIGN KE"
        "Y(tenant_id, node_id, point) REFERENCES cehub_project.schedu"
        "led_task_observations (tenant_id, node_id, point) ON DELETE "
        "RESTRICT, \n\tCONSTRAINT fk_schedule_forecast_errors_tenant_id"
        "_events FOREIGN KEY(tenant_id, event_row_id) REFERENCES cehu"
        "b_event.events (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRA"
        "INT ck_schedule_forecast_errors_forecast_error_point CHECK ("
        "point IN ('start','finish'))\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_schedule_forecast_run() "
        "RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog "
        "AS $$\nBEGIN\n IF NOT EXISTS(SELECT 1 FROM cehub_project.sched"
        "ule_time_records f JOIN cehub_project.schedule_time_records "
        "b ON b.tenant_id=f.tenant_id AND b.project_id=f.project_id W"
        "HERE f.tenant_id=NEW.tenant_id AND f.project_id=NEW.project_"
        "id AND f.id=NEW.record_id AND f.time_kind='forecast' AND b.i"
        "d=NEW.baseline_id AND b.time_kind='baseline' AND f.contract-"
        ">>'algorithm_version'=NEW.result->>'algorithm_version') THEN"
        " RAISE EXCEPTION 'Forecast requires actual project baseline "
        "and derived time version' USING ERRCODE='23514'; END IF;\n RE"
        "TURN NEW;\nEND $$;\nCREATE TRIGGER guard_schedule_forecast_run"
        " BEFORE INSERT ON cehub_project.schedule_forecast_runs FOR E"
        "ACH ROW EXECUTE FUNCTION cehub_project.guard_schedule_foreca"
        "st_run();\nCREATE FUNCTION cehub_project.guard_schedule_forec"
        "ast_error() RETURNS trigger LANGUAGE plpgsql SET search_path"
        "=pg_catalog AS $$\nBEGIN\n IF NOT EXISTS(SELECT 1 FROM cehub_p"
        "roject.schedule_time_records r JOIN cehub_project.schedule_t"
        "ime_nodes n ON n.tenant_id=r.tenant_id AND n.project_id=r.pr"
        "oject_id AND n.record_id=r.id JOIN cehub_project.scheduled_t"
        "ask_observations o ON o.tenant_id=n.tenant_id AND o.project_"
        "id=n.project_id AND o.node_id=n.node_id WHERE r.tenant_id=NE"
        "W.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.for"
        "ecast_record_id AND r.time_kind='forecast' AND n.node_id=NEW"
        ".node_id AND o.point=NEW.point AND o.event_row_id=NEW.event_"
        "row_id AND o.observed_at=NEW.observed_at AND (r.contract->>'"
        "as_of')::timestamptz<o.observed_at AND CASE WHEN NEW.point='"
        "start' THEN n.start ELSE n.end END=NEW.predicted_at AND NEW."
        "error_seconds=extract(epoch FROM (NEW.observed_at-NEW.predic"
        "ted_at))) THEN RAISE EXCEPTION 'Forecast error requires an e"
        "arlier prediction and actual observed event' USING ERRCODE='"
        "23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_sc"
        "hedule_forecast_error BEFORE INSERT ON cehub_project.schedul"
        "e_forecast_errors FOR EACH ROW EXECUTE FUNCTION cehub_projec"
        "t.guard_schedule_forecast_error();\nCREATE TRIGGER protect_ca"
        "pacity_history BEFORE UPDATE OR DELETE ON cehub_project.sche"
        "dule_forecast_runs FOR EACH ROW EXECUTE FUNCTION cehub_proje"
        "ct.protect_capacity_history();\nCREATE TRIGGER protect_capaci"
        "ty_history BEFORE UPDATE OR DELETE ON cehub_project.schedule"
        "_forecast_errors FOR EACH ROW EXECUTE FUNCTION cehub_project"
        ".protect_capacity_history();\nREVOKE ALL ON FUNCTION cehub_pr"
        "oject.guard_schedule_forecast_run(),cehub_project.guard_sche"
        "dule_forecast_error() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.schedule_forecast_"
                "runs) OR EXISTS(SELECT 1 FROM cehub_project.schedule_forecas"
                "t_errors)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard forecast history or prediction errors")
    op.drop_table("schedule_forecast_errors", schema="cehub_project")
    op.drop_table("schedule_forecast_runs", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_schedule_forecast_error()")
    op.execute("DROP FUNCTION cehub_project.guard_schedule_forecast_run()")
