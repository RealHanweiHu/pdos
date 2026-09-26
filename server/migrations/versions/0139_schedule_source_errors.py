"""Immutable forecast errors for typed business observations."""

import sqlalchemy as sa
from alembic import op

revision = "0139_schedule_source_errors"
down_revision = "0138_schedule_milestones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.schedule_source_forecast_errors "
        "(\n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tob"
        "servation_id UUID NOT NULL, \n\tforecast_record_id UUID NOT NU"
        "LL, \n\tpoint VARCHAR(8) NOT NULL, \n\tnode_id UUID NOT NULL, \n\t"
        "predicted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tobserved_a"
        "t TIMESTAMP WITH TIME ZONE NOT NULL, \n\terror_seconds NUMERIC"
        "(24, 6) NOT NULL, \n\tCONSTRAINT pk_schedule_source_forecast_e"
        "rrors PRIMARY KEY (tenant_id, observation_id, forecast_recor"
        "d_id, point), \n\tCONSTRAINT fk_source_error_observation FOREI"
        "GN KEY(tenant_id, project_id, observation_id) REFERENCES ceh"
        "ub_project.schedule_source_observations (tenant_id, project_"
        "id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_source_error_for"
        "ecast FOREIGN KEY(tenant_id, project_id, forecast_record_id)"
        " REFERENCES cehub_project.schedule_time_records (tenant_id, "
        "project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_source_e"
        "rror_node FOREIGN KEY(tenant_id, project_id, node_id) REFERE"
        "NCES cehub_project.schedule_nodes (tenant_id, project_id, id"
        ") ON DELETE RESTRICT, \n\tCONSTRAINT ck_schedule_source_foreca"
        "st_errors_source_forecast_error_point CHECK (point IN ('star"
        "t','finish'))\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_source_forecast_error() "
        "RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog "
        "AS $$\nDECLARE observation cehub_project.schedule_source_obse"
        "rvations%ROWTYPE; forecast cehub_project.schedule_time_recor"
        "ds%ROWTYPE; actual_time timestamptz; prediction timestamptz;"
        "\nBEGIN\n SELECT * INTO observation FROM cehub_project.schedul"
        "e_source_observations WHERE tenant_id=NEW.tenant_id AND proj"
        "ect_id=NEW.project_id AND id=NEW.observation_id;\n SELECT * I"
        "NTO forecast FROM cehub_project.schedule_time_records WHERE "
        "tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id"
        "=NEW.forecast_record_id;\n actual_time := CASE WHEN NEW.point"
        "='start' THEN observation.started_at ELSE observation.finish"
        "ed_at END;\n SELECT CASE WHEN NEW.point='start' THEN t.start "
        "ELSE t.end END INTO prediction FROM cehub_project.schedule_t"
        "ime_nodes t WHERE t.tenant_id=NEW.tenant_id AND t.project_id"
        "=NEW.project_id AND t.record_id=NEW.forecast_record_id AND t"
        ".node_id=NEW.node_id;\n IF observation.node_id IS DISTINCT FR"
        "OM NEW.node_id OR forecast.time_kind IS DISTINCT FROM 'forec"
        "ast' OR actual_time IS NULL OR prediction IS NULL OR NEW.obs"
        "erved_at IS DISTINCT FROM actual_time OR NEW.predicted_at IS"
        " DISTINCT FROM prediction OR NEW.error_seconds IS DISTINCT F"
        "ROM EXTRACT(EPOCH FROM (actual_time-prediction)) OR NOT ((fo"
        "recast.contract->>'as_of')::timestamptz<LEAST(actual_time,ob"
        "servation.observed_at)) THEN RAISE EXCEPTION 'Source forecas"
        "t error must use exact earlier prediction and actual observa"
        "tion' USING ERRCODE='23514'; END IF;\n IF NEW.point='finish' "
        "AND (observation.source_status IN ('cancelled','skipped','ab"
        "orted') OR (observation.node_kind='gate' AND observation.suc"
        "cessful IS DISTINCT FROM true)) THEN RAISE EXCEPTION 'This s"
        "ource outcome is not qualified completion' USING ERRCODE='23"
        "514'; END IF;\n IF NOT EXISTS(SELECT 1 FROM cehub_project.sch"
        "edule_forecast_runs r CROSS JOIN LATERAL jsonb_array_element"
        "s(r.result->'nodes') n WHERE r.tenant_id=NEW.tenant_id AND r"
        ".project_id=NEW.project_id AND r.record_id=NEW.forecast_reco"
        "rd_id AND n->>'node_id'=NEW.node_id::text AND (CASE WHEN NEW"
        ".point='start' THEN n->>'actual_start' ELSE n->>'actual_fini"
        "sh' END) IS NULL) THEN RAISE EXCEPTION 'A carried historical"
        " actual point cannot count as a prediction' USING ERRCODE='2"
        "3514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_sou"
        "rce_forecast_error BEFORE INSERT ON cehub_project.schedule_s"
        "ource_forecast_errors FOR EACH ROW EXECUTE FUNCTION cehub_pr"
        "oject.guard_source_forecast_error();\nCREATE TRIGGER protect_"
        "capacity_history BEFORE UPDATE OR DELETE ON cehub_project.sc"
        "hedule_source_forecast_errors FOR EACH ROW EXECUTE FUNCTION "
        "cehub_project.protect_capacity_history();\nREVOKE ALL ON FUNC"
        "TION cehub_project.guard_source_forecast_error() FROM PUBLIC"
        ";\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.schedule_source_forecast_errors)")
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard source forecast error evidence")
    op.drop_table("schedule_source_forecast_errors", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_source_forecast_error()")
