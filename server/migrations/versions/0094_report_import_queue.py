"""Private staged uploads and atomic completion receipts for report mapping jobs."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0094_report_import_queue"
down_revision: str | Sequence[str] | None = "0093_test_plan_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
PREVIOUS = import_module("migrations.versions.0093_test_plan_queue")
EVENTS = PREVIOUS.EVENTS.replace(
    "(agent_key = 'ai_chat' AND status = 'queued')",
    "(agent_key IN ('ai_chat','quality_intelligence') AND status = 'queued')",
)
TABLE = """CREATE TABLE cehub_ai.application_import_inputs (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,project_id uuid NOT NULL,
 plan_id uuid NOT NULL,filename varchar(512) NOT NULL,object_key text NOT NULL,
 content_sha256 varchar(64) NOT NULL,byte_size integer NOT NULL,created_at timestamptz NOT NULL,
 batch_id uuid,resolved_at timestamptz,error_code varchar(128),released_at timestamptz,
 CONSTRAINT uq_application_import_input_run UNIQUE(tenant_id,run_id),
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,project_id) REFERENCES cehub_project.projects(tenant_id,id)
  ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,plan_id) REFERENCES cehub_quality.test_plans(tenant_id,id)
  ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,batch_id) REFERENCES cehub_quality.test_report_import_batches(tenant_id,id)
  ON DELETE RESTRICT,
 CONSTRAINT ck_application_import_inputs_size CHECK(byte_size BETWEEN 1 AND 20971520
  AND length(content_sha256)=64),
 CONSTRAINT ck_application_import_inputs_resolution CHECK(
  (resolved_at IS NULL AND batch_id IS NULL AND error_code IS NULL) OR
  (resolved_at IS NOT NULL AND resolved_at>=created_at AND
    ((batch_id IS NOT NULL AND error_code IS NULL) OR
     (batch_id IS NULL AND error_code IS NOT NULL))))
);
REVOKE ALL ON cehub_ai.application_import_inputs FROM PUBLIC;
CREATE INDEX ix_application_import_input_pending
 ON cehub_ai.application_import_inputs(created_at,id)
 WHERE resolved_at IS NULL OR released_at IS NULL;
CREATE FUNCTION cehub_ai.protect_application_import_input() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF TG_OP='DELETE' OR
  (to_jsonb(NEW)-'batch_id'-'resolved_at'-'error_code'-'released_at') IS DISTINCT FROM
  (to_jsonb(OLD)-'batch_id'-'resolved_at'-'error_code'-'released_at') OR
  (OLD.resolved_at IS NOT NULL AND
   (NEW.batch_id,NEW.resolved_at,NEW.error_code) IS DISTINCT FROM
   (OLD.batch_id,OLD.resolved_at,OLD.error_code)) OR
  (OLD.released_at IS NOT NULL AND NEW.released_at IS DISTINCT FROM OLD.released_at) THEN
  RAISE EXCEPTION 'staged import identity and completed receipts are immutable'; END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_application_import_input() FROM PUBLIC;
CREATE TRIGGER protect_application_import_input BEFORE UPDATE OR DELETE
 ON cehub_ai.application_import_inputs FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.protect_application_import_input();
"""


def upgrade() -> None:
    PREVIOUS.PREVIOUS.QUEUE.PREVIOUS.PREVIOUS.replace_check(
        "ck_agent_runs_event_bounds_consistent", EVENTS
    )
    op.execute(TABLE)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.application_import_inputs) THEN
     RAISE EXCEPTION 'cannot remove staged report history'; END IF; END $body$;""")
    op.execute("""DROP TABLE cehub_ai.application_import_inputs;
     DROP FUNCTION cehub_ai.protect_application_import_input();""")
    PREVIOUS.PREVIOUS.QUEUE.PREVIOUS.PREVIOUS.replace_check(
        "ck_agent_runs_event_bounds_consistent", PREVIOUS.EVENTS
    )
