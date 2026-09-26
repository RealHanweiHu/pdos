"""Event-backed actual Task points and versioned actual schedule history."""

import sqlalchemy as sa
from alembic import op

revision = "0124_scheduled_task_actuals"
down_revision = "0123_initial_plan_application"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.scheduled_task_observations (\n\ti"
        "d UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUI"
        "D NOT NULL, \n\tnode_id UUID NOT NULL, \n\ttask_id UUID NOT NULL"
        ", \n\tpoint VARCHAR(8) NOT NULL, \n\tobserved_at TIMESTAMP WITH "
        "TIME ZONE NOT NULL, \n\tevent_row_id BIGINT NOT NULL, \n\taudit_"
        "row_id BIGINT NOT NULL, \n\tCONSTRAINT pk_scheduled_task_obser"
        "vations PRIMARY KEY (id), \n\tCONSTRAINT uq_scheduled_task_obs"
        "ervations_point UNIQUE (tenant_id, node_id, point), \n\tCONSTR"
        "AINT uq_scheduled_task_observations_event UNIQUE (tenant_id,"
        " event_row_id), \n\tCONSTRAINT fk_scheduled_task_observations_"
        "tenant_id_schedule_nodes FOREIGN KEY(tenant_id, project_id, "
        "node_id) REFERENCES cehub_project.schedule_nodes (tenant_id,"
        " project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_schedul"
        "ed_task_observations_tenant_id_tasks FOREIGN KEY(tenant_id, "
        "project_id, task_id) REFERENCES cehub_project.tasks (tenant_"
        "id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_sche"
        "duled_task_observations_tenant_id_events FOREIGN KEY(tenant_"
        "id, event_row_id) REFERENCES cehub_event.events (tenant_id, "
        "id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_scheduled_task_obser"
        "vations_tenant_id_audit_log FOREIGN KEY(tenant_id, audit_row"
        "_id) REFERENCES cehub_audit.audit_log (tenant_id, id) ON DEL"
        "ETE RESTRICT, \n\tCONSTRAINT ck_scheduled_task_observations_sc"
        "heduled_task_observation_point CHECK (point IN ('start','fin"
        "ish'))\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_scheduled_task_observati"
        "on() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_cat"
        "alog AS $$\nBEGIN\n PERFORM 1 FROM cehub_project.projects WHER"
        "E tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;\n"
        " IF NOT EXISTS(SELECT 1 FROM cehub_project.schedule_nodes n "
        "JOIN cehub_event.events e ON e.tenant_id=n.tenant_id AND e.p"
        "roject_id=n.project_id AND e.entity_id=n.task_id JOIN cehub_"
        "audit.audit_log a ON a.tenant_id=e.tenant_id AND a.project_i"
        "d=e.project_id AND a.event_id=e.event_id AND a.entity_id=e.e"
        "ntity_id WHERE n.tenant_id=NEW.tenant_id AND n.project_id=NE"
        "W.project_id AND n.id=NEW.node_id AND n.task_id=NEW.task_id "
        "AND e.id=NEW.event_row_id AND a.id=NEW.audit_row_id AND e.ti"
        "mestamp=NEW.observed_at AND e.event_type='TASK_STATUS_CHANGE"
        "D' AND e.source='task_service' AND a.action='task.transition"
        "' AND e.payload->>'to_status'=CASE WHEN NEW.point='start' TH"
        "EN 'in_progress' ELSE 'done' END AND a.after_snapshot->>'sta"
        "tus'=e.payload->>'to_status') THEN RAISE EXCEPTION 'Actual t"
        "ask time requires its own real transition event and audit' U"
        "SING ERRCODE='23514'; END IF;\n IF NEW.point='finish' AND NOT"
        " EXISTS(SELECT 1 FROM cehub_project.scheduled_task_observati"
        "ons WHERE tenant_id=NEW.tenant_id AND node_id=NEW.node_id AN"
        "D point='start' AND observed_at<=NEW.observed_at) THEN RAISE"
        " EXCEPTION 'Actual finish requires an earlier actual start' "
        "USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE T"
        "RIGGER guard_scheduled_task_observation BEFORE INSERT ON ceh"
        "ub_project.scheduled_task_observations FOR EACH ROW EXECUTE "
        "FUNCTION cehub_project.guard_scheduled_task_observation();\nC"
        "REATE TRIGGER protect_capacity_history BEFORE UPDATE OR DELE"
        "TE ON cehub_project.scheduled_task_observations FOR EACH ROW"
        " EXECUTE FUNCTION cehub_project.protect_capacity_history();\n"
        "REVOKE ALL ON FUNCTION cehub_project.guard_scheduled_task_ob"
        "servation() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.scheduled_task_observations)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard actual execution evidence")
    op.drop_table("scheduled_task_observations", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_scheduled_task_observation()")
