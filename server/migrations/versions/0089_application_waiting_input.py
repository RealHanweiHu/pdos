"""Persist human-input waits and release application execution resources."""

import re
from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0089_application_waiting_input"
down_revision: str | Sequence[str] | None = "0088_application_queue_stops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEASES = import_module("migrations.versions.0084_application_run_leases")
PREVIOUS = import_module("migrations.versions.0088_application_queue_stops")


def previous_function(name: str) -> str:
    found = re.search(
        r"CREATE FUNCTION cehub_ai\." + name + r"\b.*?\$body\$;", LEASES.FUNCTIONS, re.S
    )
    assert found is not None
    return found.group().replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


OLD_PUBLICATION = previous_function("require_application_publication_lease")
OLD_FINISH = previous_function("finish_application_lease")
OLD_EXPIRE = previous_function("expire_application_runs")
NEW_PUBLICATION = OLD_PUBLICATION.replace(
    "IF NEW.status<>'succeeded' OR OLD.status=NEW.status THEN RETURN NEW; END IF;",
    """IF NEW.status NOT IN ('succeeded','waiting_input') OR OLD.status=NEW.status
   THEN RETURN NEW; END IF;
  IF OLD.status='waiting_input' AND NEW.status='succeeded' AND EXISTS(
    SELECT 1 FROM cehub_ai.application_input_waits w WHERE w.tenant_id=NEW.tenant_id
      AND w.run_id=NEW.id AND w.resolved_at IS NOT NULL AND w.resolution<>'expired'
  ) THEN RETURN NEW; END IF;""",
)
NEW_FINISH = OLD_FINISH.replace(
    "NEW.status IN ('succeeded','degraded','failed')",
    "NEW.status IN ('succeeded','degraded','failed','waiting_input')",
).replace(
    "coalesce(NEW.error_code,'completed')",
    "CASE WHEN NEW.status='waiting_input' THEN 'waiting_input' "
    "ELSE coalesce(NEW.error_code,'completed') END",
)
NEW_EXPIRE = OLD_EXPIRE.replace(
    " RETURN amount;",
    """
 FOR r IN SELECT a.id,a.tenant_id FROM cehub_ai.agent_runs a
  JOIN cehub_ai.application_input_waits w ON w.tenant_id=a.tenant_id AND w.run_id=a.id
  WHERE a.status='waiting_input' AND w.resolved_at IS NULL AND w.expires_at<=clock_timestamp()
  ORDER BY w.expires_at,a.id LIMIT wanted_limit FOR UPDATE OF w SKIP LOCKED LOOP
  UPDATE cehub_ai.application_input_waits SET resolved_at=clock_timestamp(),resolution='expired'
   WHERE tenant_id=r.tenant_id AND run_id=r.id AND resolved_at IS NULL;
  IF NOT FOUND THEN CONTINUE; END IF;
  UPDATE cehub_ai.agent_runs SET status='degraded',error_code='APPLICATION_INPUT_WAIT_EXPIRED',
   completed_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=r.id;
  amount:=amount+1;
 END LOOP;
 RETURN amount;""",
)

TABLE = """CREATE TABLE cehub_ai.application_input_waits (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,run_id uuid NOT NULL,finding_id uuid NOT NULL,
 checkpoint_id uuid NOT NULL,owner_user_id uuid NOT NULL,body jsonb NOT NULL,
 created_at timestamptz NOT NULL,expires_at timestamptz NOT NULL,
 resolved_at timestamptz,resolution varchar(32),continuation_run_id uuid,
 CONSTRAINT uq_application_input_wait_run UNIQUE(tenant_id,run_id),
 FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,finding_id) REFERENCES cehub_ai.findings(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,run_id,checkpoint_id)
  REFERENCES cehub_ai.application_result_checkpoints(tenant_id,run_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,owner_user_id) REFERENCES cehub_core.users(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,continuation_run_id)
  REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
 CONSTRAINT ck_application_input_waits_body CHECK((jsonb_typeof(body)='object'
  AND jsonb_typeof(body->'questions')='array' AND jsonb_array_length(body->'questions')
   BETWEEN 1 AND 20) IS TRUE),
 CONSTRAINT ck_application_input_waits_resolution CHECK((
  (resolved_at IS NULL AND resolution IS NULL AND continuation_run_id IS NULL) OR
  (resolved_at IS NOT NULL AND resolved_at>=created_at AND
   ((resolution='input_received' AND continuation_run_id IS NOT NULL) OR
    (resolution IN ('finding_accepted','finding_rejected','finding_applied','expired')
     AND continuation_run_id IS NULL)))) IS TRUE),
 CONSTRAINT ck_application_input_waits_lifetime CHECK(expires_at>created_at)
);
REVOKE ALL ON cehub_ai.application_input_waits FROM PUBLIC;
CREATE INDEX ix_application_input_wait_deadline ON cehub_ai.application_input_waits(expires_at)
 WHERE resolved_at IS NULL;
CREATE FUNCTION cehub_ai.protect_application_input_wait() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'application wait history is retained'; END IF;
 IF OLD.resolved_at IS NOT NULL OR
  (to_jsonb(NEW)-'resolved_at'-'resolution'-'continuation_run_id') IS DISTINCT FROM
  (to_jsonb(OLD)-'resolved_at'-'resolution'-'continuation_run_id') THEN
  RAISE EXCEPTION 'application wait identity and resolved receipt are immutable';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.protect_application_input_wait() FROM PUBLIC;
CREATE TRIGGER protect_application_input_wait BEFORE UPDATE OR DELETE
 ON cehub_ai.application_input_waits FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.protect_application_input_wait();
CREATE FUNCTION cehub_ai.finish_application_wait_review() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE rid uuid;
BEGIN
 IF NEW.status=OLD.status OR NEW.status NOT IN ('accepted','rejected','applied')
  THEN RETURN NEW; END IF;
 UPDATE cehub_ai.application_input_waits SET resolved_at=clock_timestamp(),
   resolution='finding_'||NEW.status
  WHERE tenant_id=NEW.tenant_id AND finding_id=NEW.id AND resolved_at IS NULL
  RETURNING run_id INTO rid;
 IF rid IS NOT NULL THEN
  UPDATE cehub_ai.agent_runs SET status='succeeded',completed_at=clock_timestamp(),
    updated_at=clock_timestamp()
   WHERE tenant_id=NEW.tenant_id AND id=rid AND status='waiting_input';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.finish_application_wait_review() FROM PUBLIC;
CREATE TRIGGER finish_application_wait_review AFTER UPDATE OF status ON cehub_ai.findings
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.finish_application_wait_review();
"""


def upgrade() -> None:
    op.execute(TABLE)
    op.execute("""ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_status_allowed,
     ADD CONSTRAINT ck_agent_runs_status_allowed CHECK(status IN
       ('debouncing','queued','running','waiting_input','succeeded','degraded','failed'));""")
    op.execute(
        PREVIOUS.LIFECYCLE.replace(
            "(status='running' AND started_at IS NOT NULL",
            "(status IN ('running','waiting_input') AND started_at IS NOT NULL",
        )
    )
    for sql in (NEW_PUBLICATION, NEW_FINISH, NEW_EXPIRE):
        op.execute(sql)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.application_input_waits) THEN
      RAISE EXCEPTION 'cannot remove persistent application input waits'; END IF; END $body$;""")
    for sql in (OLD_PUBLICATION, OLD_FINISH, OLD_EXPIRE):
        op.execute(sql)
    op.execute(PREVIOUS.LIFECYCLE)
    op.execute("""ALTER TABLE cehub_ai.agent_runs DROP CONSTRAINT ck_agent_runs_status_allowed,
     ADD CONSTRAINT ck_agent_runs_status_allowed CHECK(status IN
       ('debouncing','queued','running','succeeded','degraded','failed'));
     DROP TRIGGER finish_application_wait_review ON cehub_ai.findings;
     DROP FUNCTION cehub_ai.finish_application_wait_review();
     DROP TABLE cehub_ai.application_input_waits;
     DROP FUNCTION cehub_ai.protect_application_input_wait();""")
