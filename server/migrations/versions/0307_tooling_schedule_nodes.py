"""Actual tooling rounds as typed schedule nodes and source audit observations."""

from alembic import op

revision = "0307_tooling_schedule_nodes"
down_revision = "0306_tooling_rounds"
branch_labels = None
depends_on = None

DDL = """
ALTER TABLE cehub_project.schedule_nodes ADD COLUMN tooling_id uuid;
ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT
ck_schedule_nodes_schedule_node_typed_source;
ALTER TABLE cehub_project.schedule_source_observations DROP CONSTRAINT
ck_schedule_source_observations_schedule_source_observa_d4e6;
ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT
ck_schedule_nodes_schedule_node_typed_source CHECK ((node_kind='task' AND task_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id,tooling_id)=1) OR
(node_kind='gate' AND gate_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id,tooling_id)=1) OR
(node_kind='build' AND build_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id,tooling_id)=1) OR
(node_kind='test_run' AND test_run_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id,tooling_id)=1) OR
(node_kind='certification' AND certification_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id,tooling_id)=1) OR
(node_kind='tooling' AND tooling_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id,tooling_id)=1) OR
(node_kind='milestone' AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id,tooling_id)=0 AND title IS NOT
NULL AND length(trim(title))>0 AND completion_criteria IS NOT NULL AND
length(trim(completion_criteria))>0));
ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT uq_schedule_node_tooling_id UNIQUE
(tenant_id, tooling_id);
ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT fk_schedule_node_tooling_id FOREIGN
KEY(tenant_id, project_id, tooling_id) REFERENCES cehub_supplier.tooling_rounds (tenant_id,
project_id, id) ON DELETE RESTRICT;
ALTER TABLE cehub_project.schedule_source_observations ADD CONSTRAINT
ck_schedule_source_observations_schedule_source_observa_d4e6 CHECK (version>0 AND node_kind IN
('build','test_run','gate','certification','tooling','milestone') AND (started_at IS NULL OR
finished_at IS NULL OR finished_at>=started_at));
"""

OLD_FUNCTIONS = """
CREATE OR REPLACE FUNCTION cehub_project.guard_typed_schedule_node() RETURNS trigger LANGUAGE
plpgsql SET search_path=pg_catalog AS $$
DECLARE source_id uuid; calendar_id uuid;
BEGIN
 SELECT c.calendar_id INTO calendar_id FROM cehub_project.work_calendar_versions c WHERE
c.tenant_id=NEW.tenant_id AND c.id=NEW.calendar_version_id;
 IF calendar_id IS NULL OR NEW.contract->>'id' IS DISTINCT FROM NEW.id::text OR
NEW.contract->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR NEW.contract->>'project_id' IS
DISTINCT FROM NEW.project_id::text OR NEW.contract->>'calendar_id' IS DISTINCT FROM
calendar_id::text OR NEW.contract->>'node_kind' IS DISTINCT FROM NEW.node_kind THEN RAISE
EXCEPTION 'ScheduleNode contract must match project, kind and pinned calendar' USING
ERRCODE='23514'; END IF;
 source_id := COALESCE(NEW.task_id,NEW.gate_id,NEW.build_id,NEW.test_run_id,NEW.certification_id);
 IF NEW.node_kind='milestone' THEN
  IF NEW.contract->'source' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Independent
milestone cannot pretend to have a source' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.contract->'source'->>'ref_id' IS DISTINCT FROM source_id::text OR
NEW.contract->'source'->>'kind' IS DISTINCT FROM NEW.node_kind OR
NEW.contract->'source'->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
NEW.contract->'source'->>'project_id' IS DISTINCT FROM NEW.project_id::text THEN RAISE EXCEPTION
'ScheduleNode source must match its typed foreign key' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION cehub_project.guard_schedule_source_observation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a cehub_audit.audit_log%ROWTYPE; n cehub_project.schedule_nodes%ROWTYPE;
 previous cehub_project.schedule_source_observations%ROWTYPE;
 start_time timestamptz; finish_time timestamptz; success boolean; source_id uuid;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
 SELECT * INTO n FROM cehub_project.schedule_nodes WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id AND id=NEW.node_id;
 SELECT * INTO a FROM cehub_audit.audit_log WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id AND id=NEW.audit_row_id;
 source_id := CASE WHEN n.node_kind='milestone' THEN n.id ELSE
COALESCE(n.build_id,n.test_run_id,n.gate_id,n.certification_id) END;
 IF n.node_kind IS DISTINCT FROM NEW.node_kind OR a.entity_id IS DISTINCT FROM source_id OR
a.timestamp IS DISTINCT FROM NEW.observed_at OR a.after_snapshot->>'status' IS DISTINCT FROM
NEW.source_status THEN RAISE EXCEPTION 'Schedule observation must match real scoped source audit'
USING ERRCODE='23514'; END IF;
 SELECT * INTO previous FROM cehub_project.schedule_source_observations WHERE
tenant_id=NEW.tenant_id AND node_id=NEW.node_id ORDER BY version DESC LIMIT 1;
 IF NEW.version<>COALESCE(previous.version,0)+1 OR (previous.id IS NOT NULL AND
(a.timestamp,a.id)<=(previous.observed_at,previous.audit_row_id)) THEN RAISE EXCEPTION 'Schedule
observations must append in source chronology' USING ERRCODE='23514'; END IF;
 IF NEW.node_kind='milestone' THEN
  IF a.action<>'milestone.complete' OR NOT EXISTS(SELECT 1 FROM
cehub_project.schedule_milestone_completions c WHERE c.tenant_id=NEW.tenant_id AND
c.project_id=NEW.project_id AND c.node_id=NEW.node_id AND c.audit_row_id=a.id AND
c.event_row_id=NEW.event_row_id) THEN RAISE EXCEPTION 'Milestone observation requires its actual
completion record' USING ERRCODE='23514'; END IF;
  start_time := (a.after_snapshot->>'completed_at')::timestamptz;
  finish_time := start_time;
  success := true;
 ELSIF NEW.node_kind='gate' THEN
  IF a.action NOT IN
('gate.round.open','gate.approve','gate.conditional','gate.hold','gate.rejected') THEN RAISE
EXCEPTION 'Unsupported gate observation' USING ERRCODE='23514'; END IF;
  start_time := CASE WHEN a.action='gate.round.open' THEN a.timestamp ELSE previous.started_at END;
  finish_time := CASE WHEN a.action='gate.round.open' THEN NULL ELSE
(a.after_snapshot->>'decided_at')::timestamptz END;
  IF NEW.source_status IN ('approved','conditional','hold','rejected') THEN success :=
NEW.source_status='approved'; END IF;
 ELSIF NEW.node_kind='build' THEN
  IF a.action NOT LIKE 'npi.build.%' THEN RAISE EXCEPTION 'Unsupported build observation' USING
ERRCODE='23514'; END IF;
  start_time := (a.after_snapshot->>'started_at')::timestamptz;
  finish_time := CASE WHEN NEW.source_status='completed' THEN
(a.after_snapshot->>'completed_at')::timestamptz ELSE NULL END;
  IF NEW.source_status IN ('completed','cancelled') THEN success := NEW.source_status='completed';
END IF;
 ELSIF NEW.node_kind='test_run' THEN
  IF a.action NOT IN ('test_run.record','test_run.complete') THEN RAISE EXCEPTION 'Unsupported
test observation' USING ERRCODE='23514'; END IF;
  start_time := COALESCE((a.after_snapshot->>'started_at')::timestamptz,previous.started_at,CASE
WHEN a.action='test_run.record' THEN a.timestamp ELSE NULL END);
  finish_time := CASE WHEN NEW.source_status IN ('passed','failed','aborted') THEN
(a.after_snapshot->>'executed_at')::timestamptz ELSE NULL END;
  IF NEW.source_status IN ('passed','failed','aborted') THEN success :=
NEW.source_status='passed'; END IF;
 ELSIF NEW.node_kind='certification' THEN
  start_time := (a.after_snapshot->>'started_at')::timestamptz;
  finish_time := (a.after_snapshot->>'completed_at')::timestamptz;
  IF a.action NOT LIKE 'npi.certification.%' THEN RAISE EXCEPTION 'Unsupported certification
observation' USING ERRCODE='23514'; END IF;
  IF NEW.source_status IN ('valid','expired','revoked') THEN success := NEW.source_status='valid';
END IF;
 END IF;
 IF NEW.started_at IS DISTINCT FROM start_time OR NEW.finished_at IS DISTINCT FROM finish_time OR
NEW.successful IS DISTINCT FROM success THEN RAISE EXCEPTION 'Actual times and outcome must derive
from source evidence' USING ERRCODE='23514'; END IF;
 IF NEW.event_row_id IS NULL THEN
  IF NEW.node_kind<>'gate' OR a.action='gate.approve' THEN RAISE EXCEPTION 'This observation
requires its real source event' USING ERRCODE='23514'; END IF;
 ELSIF NOT EXISTS(SELECT 1 FROM cehub_event.events e WHERE e.tenant_id=NEW.tenant_id AND
e.project_id=NEW.project_id AND e.id=NEW.event_row_id AND e.entity_id=a.entity_id AND
e.event_id=a.event_id AND e.timestamp=a.timestamp AND ((NEW.node_kind='milestone' AND
e.event_type='SCHEDULE_MILESTONE_COMPLETED' AND e.source='planning_service') OR
(NEW.node_kind='gate' AND e.event_type='GATE_APPROVED' AND e.source='gate_service') OR
(NEW.node_kind<>'gate' AND e.event_type='NPI_RECORD_CHANGED' AND e.source='npi_service' AND
e.payload->>'record_type'=NEW.node_kind))) THEN RAISE EXCEPTION 'Schedule observation event and
audit must agree' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION cehub_project.guard_source_forecast_error() RETURNS trigger LANGUAGE
plpgsql SET search_path=pg_catalog AS $$
DECLARE observation cehub_project.schedule_source_observations%ROWTYPE; forecast
cehub_project.schedule_time_records%ROWTYPE; actual_time timestamptz; prediction timestamptz;
BEGIN
 SELECT * INTO observation FROM cehub_project.schedule_source_observations WHERE
tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.observation_id;
 SELECT * INTO forecast FROM cehub_project.schedule_time_records WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id AND id=NEW.forecast_record_id;
 actual_time := CASE WHEN NEW.point='start' THEN observation.started_at ELSE
observation.finished_at END;
 SELECT CASE WHEN NEW.point='start' THEN t.start ELSE t.end END INTO prediction FROM
cehub_project.schedule_time_nodes t WHERE t.tenant_id=NEW.tenant_id AND
t.project_id=NEW.project_id AND t.record_id=NEW.forecast_record_id AND t.node_id=NEW.node_id;
 IF observation.node_id IS DISTINCT FROM NEW.node_id OR forecast.time_kind IS DISTINCT FROM
'forecast' OR actual_time IS NULL OR prediction IS NULL OR NEW.observed_at IS DISTINCT FROM
actual_time OR NEW.predicted_at IS DISTINCT FROM prediction OR NEW.error_seconds IS DISTINCT FROM
EXTRACT(EPOCH FROM (actual_time-prediction)) OR NOT
((forecast.contract->>'as_of')::timestamptz<LEAST(actual_time,observation.observed_at)) THEN RAISE
EXCEPTION 'Source forecast error must use exact earlier prediction and actual observation' USING
ERRCODE='23514'; END IF;
 IF NEW.point='finish' AND (observation.source_status IN ('cancelled','skipped','aborted') OR
(observation.node_kind='certification' AND observation.source_status IN ('expired','revoked')) OR
(observation.node_kind='gate' AND observation.successful IS DISTINCT FROM true)) THEN RAISE
EXCEPTION 'This source outcome is not qualified completion' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_project.schedule_forecast_runs r CROSS JOIN LATERAL
jsonb_array_elements(r.result->'nodes') n WHERE r.tenant_id=NEW.tenant_id AND
r.project_id=NEW.project_id AND r.record_id=NEW.forecast_record_id AND
n->>'node_id'=NEW.node_id::text AND (CASE WHEN NEW.point='start' THEN n->>'actual_start' ELSE
n->>'actual_finish' END) IS NULL) THEN RAISE EXCEPTION 'A carried historical actual point cannot
count as a prediction' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

FUNCTIONS = """
CREATE OR REPLACE FUNCTION cehub_project.guard_typed_schedule_node() RETURNS trigger LANGUAGE
plpgsql SET search_path=pg_catalog AS $$
DECLARE source_id uuid; calendar_id uuid;
BEGIN
 SELECT c.calendar_id INTO calendar_id FROM cehub_project.work_calendar_versions c WHERE
c.tenant_id=NEW.tenant_id AND c.id=NEW.calendar_version_id;
 IF calendar_id IS NULL OR NEW.contract->>'id' IS DISTINCT FROM NEW.id::text OR
NEW.contract->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR NEW.contract->>'project_id' IS
DISTINCT FROM NEW.project_id::text OR NEW.contract->>'calendar_id' IS DISTINCT FROM
calendar_id::text OR NEW.contract->>'node_kind' IS DISTINCT FROM NEW.node_kind THEN RAISE
EXCEPTION 'ScheduleNode contract must match project, kind and pinned calendar' USING
ERRCODE='23514'; END IF;
 source_id :=
COALESCE(NEW.task_id,NEW.gate_id,NEW.build_id,NEW.test_run_id,NEW.certification_id,NEW.tooling_id);
 IF NEW.node_kind='milestone' THEN
  IF NEW.contract->'source' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Independent
milestone cannot pretend to have a source' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.contract->'source'->>'ref_id' IS DISTINCT FROM source_id::text OR
NEW.contract->'source'->>'kind' IS DISTINCT FROM NEW.node_kind OR
NEW.contract->'source'->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
NEW.contract->'source'->>'project_id' IS DISTINCT FROM NEW.project_id::text THEN RAISE EXCEPTION
'ScheduleNode source must match its typed foreign key' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION cehub_project.guard_schedule_source_observation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a cehub_audit.audit_log%ROWTYPE; n cehub_project.schedule_nodes%ROWTYPE;
 previous cehub_project.schedule_source_observations%ROWTYPE;
 start_time timestamptz; finish_time timestamptz; success boolean; source_id uuid;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
 SELECT * INTO n FROM cehub_project.schedule_nodes WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id AND id=NEW.node_id;
 SELECT * INTO a FROM cehub_audit.audit_log WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id AND id=NEW.audit_row_id;
 IF NEW.node_kind='tooling' AND a.after_snapshot->>'status' IS NULL THEN
  a.after_snapshot := a.after_snapshot->'payload';
 END IF;
 source_id := CASE WHEN n.node_kind='milestone' THEN n.id ELSE
COALESCE(n.build_id,n.test_run_id,n.gate_id,n.certification_id,n.tooling_id) END;
 IF n.node_kind IS DISTINCT FROM NEW.node_kind OR a.entity_id IS DISTINCT FROM source_id OR
a.timestamp IS DISTINCT FROM NEW.observed_at OR a.after_snapshot->>'status' IS DISTINCT FROM
NEW.source_status THEN RAISE EXCEPTION 'Schedule observation must match real scoped source audit'
USING ERRCODE='23514'; END IF;
 SELECT * INTO previous FROM cehub_project.schedule_source_observations WHERE
tenant_id=NEW.tenant_id AND node_id=NEW.node_id ORDER BY version DESC LIMIT 1;
 IF NEW.version<>COALESCE(previous.version,0)+1 OR (previous.id IS NOT NULL AND
(a.timestamp,a.id)<=(previous.observed_at,previous.audit_row_id)) THEN RAISE EXCEPTION 'Schedule
observations must append in source chronology' USING ERRCODE='23514'; END IF;
 IF NEW.node_kind='milestone' THEN
  IF a.action<>'milestone.complete' OR NOT EXISTS(SELECT 1 FROM
cehub_project.schedule_milestone_completions c WHERE c.tenant_id=NEW.tenant_id AND
c.project_id=NEW.project_id AND c.node_id=NEW.node_id AND c.audit_row_id=a.id AND
c.event_row_id=NEW.event_row_id) THEN RAISE EXCEPTION 'Milestone observation requires its actual
completion record' USING ERRCODE='23514'; END IF;
  start_time := (a.after_snapshot->>'completed_at')::timestamptz;
  finish_time := start_time;
  success := true;
 ELSIF NEW.node_kind='gate' THEN
  IF a.action NOT IN
('gate.round.open','gate.approve','gate.conditional','gate.hold','gate.rejected') THEN RAISE
EXCEPTION 'Unsupported gate observation' USING ERRCODE='23514'; END IF;
  start_time := CASE WHEN a.action='gate.round.open' THEN a.timestamp ELSE previous.started_at END;
  finish_time := CASE WHEN a.action='gate.round.open' THEN NULL ELSE
(a.after_snapshot->>'decided_at')::timestamptz END;
  IF NEW.source_status IN ('approved','conditional','hold','rejected') THEN success :=
NEW.source_status='approved'; END IF;
 ELSIF NEW.node_kind='build' THEN
  IF a.action NOT LIKE 'npi.build.%' THEN RAISE EXCEPTION 'Unsupported build observation' USING
ERRCODE='23514'; END IF;
  start_time := (a.after_snapshot->>'started_at')::timestamptz;
  finish_time := CASE WHEN NEW.source_status='completed' THEN
(a.after_snapshot->>'completed_at')::timestamptz ELSE NULL END;
  IF NEW.source_status IN ('completed','cancelled') THEN success := NEW.source_status='completed';
END IF;
 ELSIF NEW.node_kind='test_run' THEN
  IF a.action NOT IN ('test_run.record','test_run.complete') THEN RAISE EXCEPTION 'Unsupported
test observation' USING ERRCODE='23514'; END IF;
  start_time := COALESCE((a.after_snapshot->>'started_at')::timestamptz,previous.started_at,CASE
WHEN a.action='test_run.record' THEN a.timestamp ELSE NULL END);
  finish_time := CASE WHEN NEW.source_status IN ('passed','failed','aborted') THEN
(a.after_snapshot->>'executed_at')::timestamptz ELSE NULL END;
  IF NEW.source_status IN ('passed','failed','aborted') THEN success :=
NEW.source_status='passed'; END IF;
 ELSIF NEW.node_kind='tooling' THEN
  IF a.action NOT LIKE 'npi.tooling_round.%' THEN
   RAISE EXCEPTION 'Unsupported tooling observation' USING ERRCODE='23514'; END IF;
  start_time := coalesce((a.after_snapshot->>'started_at')::timestamptz,
                        (a.after_snapshot#>>'{started,at}')::timestamptz);
  finish_time := CASE WHEN NEW.source_status='completed' THEN
   coalesce((a.after_snapshot->>'completed_at')::timestamptz,
            (a.after_snapshot#>>'{completed,at}')::timestamptz) ELSE NULL END;
  IF NEW.source_status IN ('completed','cancelled') THEN
   success := NEW.source_status='completed' AND a.after_snapshot->>'outcome'='accepted';
  END IF;
 ELSIF NEW.node_kind='certification' THEN
  start_time := (a.after_snapshot->>'started_at')::timestamptz;
  finish_time := (a.after_snapshot->>'completed_at')::timestamptz;
  IF a.action NOT LIKE 'npi.certification.%' THEN RAISE EXCEPTION 'Unsupported certification
observation' USING ERRCODE='23514'; END IF;
  IF NEW.source_status IN ('valid','expired','revoked') THEN success := NEW.source_status='valid';
END IF;
 END IF;
 IF NEW.started_at IS DISTINCT FROM start_time OR NEW.finished_at IS DISTINCT FROM finish_time OR
NEW.successful IS DISTINCT FROM success THEN RAISE EXCEPTION 'Actual times and outcome must derive
from source evidence' USING ERRCODE='23514'; END IF;
 IF NEW.event_row_id IS NULL THEN
  IF NEW.node_kind<>'gate' OR a.action='gate.approve' THEN RAISE EXCEPTION 'This observation
requires its real source event' USING ERRCODE='23514'; END IF;
 ELSIF NOT EXISTS(SELECT 1 FROM cehub_event.events e WHERE e.tenant_id=NEW.tenant_id AND
e.project_id=NEW.project_id AND e.id=NEW.event_row_id AND e.entity_id=a.entity_id AND
e.event_id=a.event_id AND e.timestamp=a.timestamp AND ((NEW.node_kind='milestone' AND
e.event_type='SCHEDULE_MILESTONE_COMPLETED' AND e.source='planning_service') OR
(NEW.node_kind='gate' AND e.event_type='GATE_APPROVED' AND e.source='gate_service') OR
(NEW.node_kind<>'gate' AND e.event_type='NPI_RECORD_CHANGED' AND e.source='npi_service' AND
e.payload->>'record_type'=CASE WHEN NEW.node_kind='tooling' THEN 'tooling_round' ELSE
NEW.node_kind END))) THEN RAISE EXCEPTION 'Schedule observation event and audit must agree' USING
ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION cehub_project.guard_source_forecast_error() RETURNS trigger LANGUAGE
plpgsql SET search_path=pg_catalog AS $$
DECLARE observation cehub_project.schedule_source_observations%ROWTYPE; forecast
cehub_project.schedule_time_records%ROWTYPE; actual_time timestamptz; prediction timestamptz;
BEGIN
 SELECT * INTO observation FROM cehub_project.schedule_source_observations WHERE
tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.observation_id;
 SELECT * INTO forecast FROM cehub_project.schedule_time_records WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id AND id=NEW.forecast_record_id;
 actual_time := CASE WHEN NEW.point='start' THEN observation.started_at ELSE
observation.finished_at END;
 SELECT CASE WHEN NEW.point='start' THEN t.start ELSE t.end END INTO prediction FROM
cehub_project.schedule_time_nodes t WHERE t.tenant_id=NEW.tenant_id AND
t.project_id=NEW.project_id AND t.record_id=NEW.forecast_record_id AND t.node_id=NEW.node_id;
 IF observation.node_id IS DISTINCT FROM NEW.node_id OR forecast.time_kind IS DISTINCT FROM
'forecast' OR actual_time IS NULL OR prediction IS NULL OR NEW.observed_at IS DISTINCT FROM
actual_time OR NEW.predicted_at IS DISTINCT FROM prediction OR NEW.error_seconds IS DISTINCT FROM
EXTRACT(EPOCH FROM (actual_time-prediction)) OR NOT
((forecast.contract->>'as_of')::timestamptz<LEAST(actual_time,observation.observed_at)) THEN RAISE
EXCEPTION 'Source forecast error must use exact earlier prediction and actual observation' USING
ERRCODE='23514'; END IF;
 IF NEW.point='finish' AND (observation.source_status IN ('cancelled','skipped','aborted') OR
(observation.node_kind='certification' AND observation.source_status IN ('expired','revoked')) OR
(observation.node_kind IN ('gate','tooling') AND observation.successful IS DISTINCT FROM true))
THEN RAISE EXCEPTION 'This source outcome is not qualified completion' USING ERRCODE='23514'; END
IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_project.schedule_forecast_runs r CROSS JOIN LATERAL
jsonb_array_elements(r.result->'nodes') n WHERE r.tenant_id=NEW.tenant_id AND
r.project_id=NEW.project_id AND r.record_id=NEW.forecast_record_id AND
n->>'node_id'=NEW.node_id::text AND (CASE WHEN NEW.point='start' THEN n->>'actual_start' ELSE
n->>'actual_finish' END) IS NULL) THEN RAISE EXCEPTION 'A carried historical actual point cannot
count as a prediction' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

RESTORE = """
ALTER TABLE cehub_project.schedule_nodes DROP CONSTRAINT
ck_schedule_nodes_schedule_node_typed_source;
ALTER TABLE cehub_project.schedule_source_observations DROP CONSTRAINT
ck_schedule_source_observations_schedule_source_observa_d4e6;
ALTER TABLE cehub_project.schedule_nodes DROP COLUMN tooling_id;
ALTER TABLE cehub_project.schedule_nodes ADD CONSTRAINT
ck_schedule_nodes_schedule_node_typed_source CHECK ((node_kind='task' AND task_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id)=1) OR (node_kind='gate' AND
gate_id IS NOT NULL AND num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id)=1) OR
(node_kind='build' AND build_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id)=1) OR (node_kind='test_run'
AND test_run_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id)=1) OR
(node_kind='certification' AND certification_id IS NOT NULL AND
num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id)=1) OR (node_kind='milestone'
AND num_nonnulls(task_id,gate_id,build_id,test_run_id,certification_id)=0 AND title IS NOT NULL
AND length(trim(title))>0 AND completion_criteria IS NOT NULL AND
length(trim(completion_criteria))>0));
ALTER TABLE cehub_project.schedule_source_observations ADD CONSTRAINT
ck_schedule_source_observations_schedule_source_observa_d4e6 CHECK (version>0 AND node_kind IN
('build','test_run','gate','certification','milestone') AND (started_at IS NULL OR finished_at IS
NULL OR finished_at>=started_at));
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(FUNCTIONS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_project.schedule_nodes WHERE node_kind='tooling') THEN
    RAISE EXCEPTION 'Tooling schedule sources and their history require retention'; END IF;
    END $$;
    """)
    op.execute(OLD_FUNCTIONS)
    op.execute(RESTORE)
