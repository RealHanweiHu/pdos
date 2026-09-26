"""Require admitted context on all four application paths and verify observed traces."""

from collections.abc import Sequence

from alembic import op

revision: str = "0083_domain_context_adapters"
down_revision: str | Sequence[str] | None = "0082_application_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_GUARD = """
CREATE OR REPLACE FUNCTION cehub_ai.require_application_manifest() RETURNS trigger
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
"""

NEW_GUARD = """
CREATE OR REPLACE FUNCTION cehub_ai.require_application_manifest() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.call_kind='model' AND NEW.reservation_status='reserved' AND NEW.dispatched_at IS NOT NULL
  AND EXISTS(SELECT 1 FROM cehub_ai.application_authorizations a
    WHERE a.run_id=NEW.run_id)
  AND NOT EXISTS(SELECT 1 FROM cehub_ai.application_context_manifests m
    WHERE m.tenant_id=NEW.tenant_id AND m.run_id=NEW.run_id AND m.attempt_id=NEW.attempt_id) THEN
  RAISE EXCEPTION 'BUDGET_APPLICATION_MANIFEST_REQUIRED' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_application_manifest() FROM PUBLIC;
"""

TRACE_GUARD = """
CREATE FUNCTION cehub_ai.require_application_trace_manifests() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.structured_attempts>0
  AND EXISTS(SELECT 1 FROM cehub_ai.application_context_observations
   WHERE tenant_id=NEW.tenant_id AND run_id=NEW.run_id)
  AND EXISTS(SELECT 1 FROM generate_series(1,NEW.structured_attempts) n WHERE NOT EXISTS(
   SELECT 1 FROM cehub_ai.application_context_manifests m
   JOIN cehub_ai.application_context_observations o
    ON o.tenant_id=m.tenant_id AND o.run_id=m.run_id AND o.id=m.observation_id
   JOIN cehub_ai.budget_journal j
    ON j.tenant_id=m.tenant_id AND j.run_id=m.run_id AND j.id=m.admission_id
   WHERE m.tenant_id=NEW.tenant_id AND m.run_id=NEW.run_id
    AND o.model_call_id=NEW.budget_call_id
    AND j.request_binding->>'model_call_id'=NEW.budget_call_id::text
    AND (j.request_binding->>'structured_attempt')::integer=n)) THEN
  RAISE EXCEPTION 'BUDGET_APPLICATION_TRACE_MANIFEST_REQUIRED' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_application_trace_manifests() FROM PUBLIC;
CREATE TRIGGER require_application_trace_manifests BEFORE INSERT ON cehub_ai.model_invocations
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_application_trace_manifests();
"""


def upgrade() -> None:
    op.execute(NEW_GUARD)
    op.execute(TRACE_GUARD)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
     IF EXISTS(SELECT 1 FROM cehub_ai.application_context_manifests m
      JOIN cehub_ai.application_authorizations a ON a.id=m.authorization_id
      WHERE a.body->>'purpose'<>'chat_answer') THEN
      RAISE EXCEPTION 'cannot remove persistent domain application context history';
     END IF;
    END $body$;""")
    op.execute("DROP TRIGGER require_application_trace_manifests ON cehub_ai.model_invocations")
    op.execute("DROP FUNCTION cehub_ai.require_application_trace_manifests()")
    op.execute(OLD_GUARD)
