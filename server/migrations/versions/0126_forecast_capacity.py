"""Forecast capacity snapshots and actual resource version bindings."""

import sqlalchemy as sa
from alembic import op

revision = "0126_forecast_capacity"
down_revision = "0125_schedule_forecasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.forecast_capacity_checks (\n\tid U"
        "UID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID N"
        "OT NULL, \n\tforecast_record_id UUID NOT NULL, \n\tinputs JSONB "
        "NOT NULL, \n\tresult JSONB NOT NULL, \n\tresult_digest VARCHAR(6"
        "4) NOT NULL, \n\tforecast_basis_digest VARCHAR(64) NOT NULL, \n"
        "\tcreated_by_user_id UUID NOT NULL, \n\trequest_id UUID NOT NUL"
        "L, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcreated_at TIMES"
        "TAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCO"
        "NSTRAINT pk_forecast_capacity_checks PRIMARY KEY (id), \n\tCON"
        "STRAINT uq_forecast_capacity_checks_scope UNIQUE (tenant_id,"
        " id), \n\tCONSTRAINT uq_forecast_capacity_checks_request UNIQU"
        "E (tenant_id, created_by_user_id, request_id), \n\tCONSTRAINT "
        "fk_forecast_capacity_checks_tenant_id_schedule_forecast_runs"
        " FOREIGN KEY(tenant_id, forecast_record_id) REFERENCES cehub"
        "_project.schedule_forecast_runs (tenant_id, record_id) ON DE"
        "LETE RESTRICT, \n\tCONSTRAINT fk_forecast_capacity_checks_tena"
        "nt_id_schedule_time_records FOREIGN KEY(tenant_id, project_i"
        "d, forecast_record_id) REFERENCES cehub_project.schedule_tim"
        "e_records (tenant_id, project_id, id) ON DELETE RESTRICT, \n\t"
        "CONSTRAINT fk_forecast_capacity_checks_tenant_id_users FOREI"
        "GN KEY(tenant_id, created_by_user_id) REFERENCES cehub_core."
        "users (tenant_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.forecast_capacity_check_versions"
        " (\n\ttenant_id UUID NOT NULL, \n\tcheck_id UUID NOT NULL, \n\tcap"
        "acity_version_id UUID NOT NULL, \n\tCONSTRAINT pk_forecast_cap"
        "acity_check_versions PRIMARY KEY (tenant_id, check_id, capac"
        "ity_version_id), \n\tCONSTRAINT fk_forecast_capacity_check_ver"
        "sions_tenant_id_forecast__a2f1 FOREIGN KEY(tenant_id, check_"
        "id) REFERENCES cehub_project.forecast_capacity_checks (tenan"
        "t_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_forecast_capac"
        "ity_check_versions_tenant_id_resource__2fc5 FOREIGN KEY(tena"
        "nt_id, capacity_version_id) REFERENCES cehub_project.resourc"
        "e_capacity_versions (tenant_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_forecast_capacity_check("
        ") RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalo"
        "g AS $$\nBEGIN\n IF NOT EXISTS(SELECT 1 FROM cehub_project.sch"
        "edule_forecast_runs WHERE tenant_id=NEW.tenant_id AND projec"
        "t_id=NEW.project_id AND record_id=NEW.forecast_record_id AND"
        " basis_digest=NEW.forecast_basis_digest) THEN RAISE EXCEPTIO"
        "N 'Capacity check must bind the actual forecast version and "
        "basis' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nC"
        "REATE TRIGGER guard_forecast_capacity_check BEFORE INSERT ON"
        " cehub_project.forecast_capacity_checks FOR EACH ROW EXECUTE"
        " FUNCTION cehub_project.guard_forecast_capacity_check();\nREV"
        "OKE ALL ON FUNCTION cehub_project.guard_forecast_capacity_ch"
        "eck() FROM PUBLIC;\nCREATE TRIGGER protect_capacity_history B"
        "EFORE UPDATE OR DELETE ON cehub_project.forecast_capacity_ch"
        "ecks FOR EACH ROW EXECUTE FUNCTION cehub_project.protect_cap"
        "acity_history();\nCREATE TRIGGER protect_capacity_history BEF"
        "ORE UPDATE OR DELETE ON cehub_project.forecast_capacity_chec"
        "k_versions FOR EACH ROW EXECUTE FUNCTION cehub_project.prote"
        "ct_capacity_history();\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.forecast_capacity_checks)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard forecast capacity evidence")
    op.drop_table("forecast_capacity_check_versions", schema="cehub_project")
    op.drop_table("forecast_capacity_checks", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_forecast_capacity_check()")
