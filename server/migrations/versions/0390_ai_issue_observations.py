# ruff: noqa: E501
"""Immutable complete Issue run observations; no qualification grants."""

from alembic import op

revision = "0390_ai_issue_observations"
down_revision = "0389_ai_issue_trial_evidence"
branch_labels = None
depends_on = None

DDL = "\nCREATE TABLE cehub_ai.ai_issue_observations (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\twindow_start TIMESTAMP WITH TIME ZONE NOT NULL, \n\twindow_end TIMESTAMP WITH TIME ZONE NOT NULL, \n\tas_of TIMESTAMP WITH TIME ZONE NOT NULL, \n\tobservation JSONB NOT NULL, \n\tobservation_digest VARCHAR(64) NOT NULL, \n\toutput_event_row_id BIGINT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_ai_issue_observations PRIMARY KEY (id), \n\tCONSTRAINT fk_ai_issue_observations_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_observations_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_observations_tenant_id_events FOREIGN KEY(tenant_id, output_event_row_id) REFERENCES cehub_event.events (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_ai_issue_observation_scope UNIQUE (tenant_id, project_id, id), \n\tCONSTRAINT uq_ai_issue_observation_request UNIQUE (tenant_id, actor_user_id, request_id), \n\tCONSTRAINT ck_ai_issue_observations_shape CHECK (window_start < window_end AND window_end <= as_of AND as_of <= created_at AND window_end-window_start <= interval '366 days' AND request_digest ~ '^[a-f0-9]{64}$' AND observation_digest ~ '^[a-f0-9]{64}$' AND (jsonb_typeof(observation)='object' AND observation->>'version'='event-issue-observation-v1' AND observation->>'id'=id::text AND observation->>'tenant_id'=tenant_id::text AND observation->>'project_id'=project_id::text AND observation->'qualification_granted'='false'::jsonb AND jsonb_typeof(observation->'items')='array' AND jsonb_array_length(observation->'items')=(observation->>'total_runs')::integer) IS TRUE)\n)\n\n"
GUARDS = "CREATE FUNCTION cehub_ai.guard_issue_observation() RETURNS trigger LANGUAGE plpgsql AS $$\nBEGIN\n IF (NEW.observation->>'actor_user_id'=NEW.actor_user_id::text\n  AND (NEW.observation->>'window_start')::timestamptz=NEW.window_start\n  AND (NEW.observation->>'window_end')::timestamptz=NEW.window_end\n  AND (NEW.observation->>'as_of')::timestamptz=NEW.as_of\n  AND (NEW.observation->>'created_at')::timestamptz=NEW.created_at\n  AND NEW.observation->'ratios'->'descriptive_only'='true'::jsonb\n  AND NEW.observation->'counts'->>'total_runs'=NEW.observation->>'total_runs') IS NOT TRUE\n THEN RAISE EXCEPTION 'Observation scope and descriptive counts must match'; END IF;\n IF NOT EXISTS(SELECT 1 FROM cehub_event.events e JOIN cehub_audit.audit_log a\n  ON a.tenant_id=e.tenant_id AND a.project_id=e.project_id AND a.event_id=e.event_id\n   AND a.entity_id=e.entity_id AND a.timestamp=e.timestamp\n  WHERE e.tenant_id=NEW.tenant_id AND e.project_id=NEW.project_id AND e.id=NEW.output_event_row_id\n   AND e.entity_id=NEW.id AND e.event_type='AI_ISSUE_OBSERVATION_SAVED'\n   AND e.source='ai_issue_observation_service' AND e.payload->>'observation_id'=NEW.id::text\n   AND e.payload->>'observation_digest'=NEW.observation_digest\n   AND e.payload->>'total_runs'=NEW.observation->>'total_runs'\n   AND a.actor_user_id=NEW.actor_user_id AND a.action='ai_issue.observation_saved'\n   AND a.after_snapshot->>'observation_digest'=NEW.observation_digest)\n THEN RAISE EXCEPTION 'Observation requires its original named event and audit'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_issue_observation BEFORE INSERT ON cehub_ai.ai_issue_observations\n FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_issue_observation();\nCREATE TRIGGER immutable_issue_observation BEFORE UPDATE OR DELETE ON cehub_ai.ai_issue_observations\n FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();\nREVOKE ALL ON cehub_ai.ai_issue_observations FROM PUBLIC;\nDO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN\n REVOKE ALL ON cehub_ai.ai_issue_observations FROM pdos_agent; END IF; END $$;\n"


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.ai_issue_observations) THEN RAISE EXCEPTION 'Retain original Issue observations'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_ai.ai_issue_observations")
    op.execute("DROP FUNCTION cehub_ai.guard_issue_observation()")
