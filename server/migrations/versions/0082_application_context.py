"""Persist actual Chat collector observations and admitted context revisions."""

from collections.abc import Sequence

from alembic import op

revision: str = "0082_application_context"
down_revision: str | Sequence[str] | None = "0081_application_authorization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = """
CREATE TABLE cehub_ai.application_context_observations (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, run_id uuid NOT NULL, authorization_id uuid NOT NULL,
 model_call_id uuid NOT NULL, metadata jsonb NOT NULL, output_body jsonb NOT NULL,
 context_body jsonb NOT NULL, bundle jsonb NOT NULL, created_at timestamptz NOT NULL,
 CONSTRAINT uq_application_observation_scope UNIQUE(tenant_id,run_id,id),
 CONSTRAINT uq_application_observation_call UNIQUE(tenant_id,run_id,model_call_id),
 FOREIGN KEY(tenant_id,run_id,authorization_id)
 REFERENCES cehub_ai.application_authorizations(tenant_id,run_id,id) ON DELETE RESTRICT
);
CREATE TABLE cehub_ai.application_context_manifests (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, run_id uuid NOT NULL, authorization_id uuid NOT NULL,
 observation_id uuid NOT NULL, admission_id uuid NOT NULL, attempt_id uuid NOT NULL,
 revision_no integer NOT NULL, parent_revision_id uuid, body jsonb NOT NULL,
 created_at timestamptz NOT NULL,
 CONSTRAINT uq_application_manifest_scope UNIQUE(tenant_id,run_id,id),
 CONSTRAINT uq_application_manifest_revision UNIQUE(tenant_id,run_id,revision_no),
 CONSTRAINT uq_application_manifest_attempt UNIQUE(tenant_id,run_id,attempt_id),
 CONSTRAINT ck_application_context_manifests_revision
 CHECK(revision_no>0 AND (revision_no=1)=(parent_revision_id IS NULL)),
 FOREIGN KEY(tenant_id,run_id,authorization_id)
 REFERENCES cehub_ai.application_authorizations(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,observation_id)
 REFERENCES cehub_ai.application_context_observations(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,admission_id)
 REFERENCES cehub_ai.budget_journal(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,parent_revision_id)
 REFERENCES cehub_ai.application_context_manifests(tenant_id,run_id,id) ON DELETE RESTRICT
);
CREATE TRIGGER protect_application_observation BEFORE UPDATE OR DELETE
 ON cehub_ai.application_context_observations FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
CREATE TRIGGER protect_application_manifest BEFORE UPDATE OR DELETE
 ON cehub_ai.application_context_manifests FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.application_context_observations,cehub_ai.application_context_manifests
 FROM PUBLIC;
"""

GUARDS = """
CREATE FUNCTION cehub_ai.require_application_manifest() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.call_kind='model' AND NEW.reservation_status='reserved' AND NEW.dispatched_at IS NOT NULL
  AND EXISTS(SELECT 1 FROM cehub_ai.application_authorizations a
    WHERE a.run_id=NEW.run_id AND a.body->>'purpose'='chat_answer')
  AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_context_manifests m
    WHERE m.tenant_id=NEW.tenant_id AND m.run_id=NEW.run_id AND m.attempt_id=NEW.attempt_id) THEN
  RAISE EXCEPTION 'BUDGET_APPLICATION_MANIFEST_REQUIRED' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_application_manifest() FROM PUBLIC;
CREATE TRIGGER require_application_manifest BEFORE INSERT ON cehub_ai.budget_journal
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_application_manifest();
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
     IF EXISTS(SELECT 1 FROM cehub_ai.application_context_observations) THEN
      RAISE EXCEPTION 'cannot remove persistent application context history';
     END IF;
    END $body$;""")
    op.execute("DROP TRIGGER require_application_manifest ON cehub_ai.budget_journal")
    op.execute("DROP FUNCTION cehub_ai.require_application_manifest()")
    op.execute("DROP TABLE cehub_ai.application_context_manifests")
    op.execute("DROP TABLE cehub_ai.application_context_observations")
