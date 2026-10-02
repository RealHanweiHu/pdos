# ruff: noqa: E501
"""Immutable original Issue trial collections, never qualification grants."""

from alembic import op

revision = "0392_ai_issue_trial_collections"
down_revision = "0391_ai_issue_trial_protocols"
branch_labels = None
depends_on = None

DDL = "\nCREATE TABLE cehub_ai.ai_issue_trial_collections (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\tprotocol_id UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcollection_digest VARCHAR(64) NOT NULL, \n\tas_of TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcollection JSONB NOT NULL, \n\toutput_event_row_id BIGINT NOT NULL, \n\tCONSTRAINT pk_ai_issue_trial_collections PRIMARY KEY (id), \n\tCONSTRAINT fk_ai_issue_trial_collections_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_trial_collections_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_trial_collections_tenant_id_events FOREIGN KEY(tenant_id, output_event_row_id) REFERENCES cehub_event.events (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_trial_collections_tenant_id_ai_issue_trial__b84d FOREIGN KEY(tenant_id, project_id, protocol_id) REFERENCES cehub_ai.ai_issue_trial_protocols (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_ai_issue_trial_collection_request UNIQUE (tenant_id, actor_user_id, request_id), \n\tCONSTRAINT uq_ai_issue_trial_collection_scope UNIQUE (tenant_id, project_id, protocol_id, id), \n\tCONSTRAINT ck_ai_issue_trial_collections_shape CHECK (as_of<=created_at AND request_digest ~ '^[a-f0-9]{64}$' AND collection_digest ~ '^[a-f0-9]{64}$' AND (jsonb_typeof(collection)='object' AND collection->>'version'='event-issue-trial-collection-v1' AND collection->>'id'=id::text AND collection->>'tenant_id'=tenant_id::text AND collection->>'project_id'=project_id::text AND collection->>'protocol_id'=protocol_id::text AND collection->>'actor_user_id'=actor_user_id::text AND (collection->>'as_of')::timestamptz=as_of AND (collection->>'created_at')::timestamptz=created_at AND collection->'selection_complete'='true'::jsonb AND collection->'qualification_granted'='false'::jsonb AND jsonb_typeof(collection->'items')='array' AND jsonb_typeof(collection->'total_runs')='number' AND collection->>'total_runs' ~ '^(0|[1-9][0-9]*)$' AND jsonb_typeof(collection->'matching_runs')='number' AND collection->>'matching_runs' ~ '^(0|[1-9][0-9]*)$' AND jsonb_array_length(collection->'items')=(collection->>'total_runs')::numeric AND (collection->>'matching_runs')::numeric <=(collection->>'total_runs')::numeric) IS TRUE)\n)\n\n"

GUARDS = """
CREATE FUNCTION cehub_ai.guard_issue_trial_collection() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM cehub_ai.ai_issue_trial_protocols p
  WHERE p.tenant_id=NEW.tenant_id AND p.project_id=NEW.project_id AND p.id=NEW.protocol_id
   AND NEW.collection->>'protocol_digest'=p.protocol_digest
   AND (NEW.collection->>'window_start')::timestamptz=p.window_start
   AND (NEW.collection->>'window_end')::timestamptz=p.window_end
   AND p.window_end<=NEW.as_of AND p.created_at<=NEW.as_of)
 THEN RAISE EXCEPTION 'Issue collection requires its original protocol and closed window'; END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_event.events e JOIN cehub_audit.audit_log a
  ON a.tenant_id=e.tenant_id AND a.project_id=e.project_id AND a.event_id=e.event_id
   AND a.entity=e.entity AND a.entity_id=e.entity_id AND a.timestamp=e.timestamp
  WHERE e.tenant_id=NEW.tenant_id AND e.project_id=NEW.project_id AND e.id=NEW.output_event_row_id
   AND e.entity='ai_issue_trial_collection' AND e.entity_id=NEW.id
   AND e.event_type='AI_ISSUE_TRIAL_COLLECTED' AND e.schema_version=1
   AND e.source='ai_issue_trial_service'
   AND e.payload=jsonb_build_object(
    'collection_id',NEW.id::text,'collection_digest',NEW.collection_digest,
    'protocol_id',NEW.protocol_id::text,'total_runs',NEW.collection->'total_runs')
   AND a.actor_user_id=NEW.actor_user_id AND a.action='ai_issue.trial_collected'
   AND a.after_snapshot=e.payload)
 THEN RAISE EXCEPTION 'Issue collection requires its original named event and audit'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_issue_trial_collection BEFORE INSERT ON cehub_ai.ai_issue_trial_collections
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_issue_trial_collection();
CREATE TRIGGER immutable_issue_trial_collection BEFORE UPDATE OR DELETE
 ON cehub_ai.ai_issue_trial_collections
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.ai_issue_trial_collections FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
 REVOKE ALL ON cehub_ai.ai_issue_trial_collections FROM pdos_agent; END IF; END $$;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.ai_issue_trial_collections) "
        "THEN RAISE EXCEPTION 'Retain original Issue trial collections'; END IF; END $$;"
    )
    op.execute("DROP TABLE cehub_ai.ai_issue_trial_collections")
    op.execute("DROP FUNCTION cehub_ai.guard_issue_trial_collection()")
