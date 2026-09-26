"""Persist user authority with application run creation and gate model dispatch."""

from collections.abc import Sequence

from alembic import op

revision: str = "0081_application_authorization"
down_revision: str | Sequence[str] | None = "0080_context_manifests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTHORITY = r"""
CREATE FUNCTION cehub_ai.application_authorization_is_current(wanted_run uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM cehub_ai.application_authorizations
  WHERE run_id=wanted_run)
 THEN NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r JOIN cehub_ai.budget_run_links b
   ON b.tenant_id=r.tenant_id AND b.run_id=r.id WHERE r.id=wanted_run
   AND (r.request_id IS NOT NULL OR r.run_context ? 'api_actor_user_id'
    OR r.run_context ? 'test_plan_request'))
 ELSE EXISTS(SELECT 1 FROM cehub_ai.application_authorizations a
  JOIN cehub_ai.agent_runs r ON r.tenant_id=a.tenant_id AND r.id=a.run_id
  JOIN cehub_core.users u ON u.tenant_id=a.tenant_id AND u.id=a.principal_id
  JOIN cehub_core.tenants t ON t.id=a.tenant_id
  JOIN cehub_project.projects p ON p.tenant_id=a.tenant_id AND p.id=a.project_id
  WHERE a.run_id=wanted_run AND a.expires_at>clock_timestamp() AND r.status='running'
   AND r.project_id=a.project_id AND u.is_active AND t.status='active'
   AND u.auth_version=(a.pins->>'auth_version')::integer AND u.role=a.pins->>'role'
   AND (a.pins->>'membership_id' IS NULL AND u.role IN ('owner','admin')
    OR EXISTS(SELECT 1 FROM cehub_project.project_members m
     WHERE m.tenant_id=a.tenant_id AND m.project_id=a.project_id
      AND m.id::text=a.pins->>'membership_id' AND m.user_id::text=a.pins->>'membership_user_id'
      AND (a.pins->>'delegation_id' IS NULL AND m.user_id=a.principal_id
       OR EXISTS(SELECT 1 FROM cehub_core.user_delegations d
        WHERE d.tenant_id=a.tenant_id AND d.id::text=a.pins->>'delegation_id'
         AND d.principal_user_id=m.user_id AND d.delegate_user_id=a.principal_id
         AND d.revoked_at IS NULL AND d.starts_at<=clock_timestamp()
         AND d.ends_at>clock_timestamp()))))) END;
$body$;
REVOKE ALL ON FUNCTION cehub_ai.application_authorization_is_current(uuid) FROM PUBLIC;

CREATE FUNCTION cehub_ai.require_application_authorization() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
BEGIN
 IF NEW.call_kind='model' AND NEW.reservation_status='reserved' AND NEW.dispatched_at IS NOT NULL
  AND NOT cehub_ai.application_authorization_is_current(NEW.run_id) THEN
  RAISE EXCEPTION 'BUDGET_APPLICATION_AUTHORIZATION_CHANGED' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.require_application_authorization() FROM PUBLIC;
CREATE TRIGGER require_application_authorization BEFORE INSERT ON cehub_ai.budget_journal
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.require_application_authorization();
"""


def upgrade() -> None:
    op.execute("""CREATE TABLE cehub_ai.application_authorizations (
      id uuid PRIMARY KEY, tenant_id uuid NOT NULL, run_id uuid NOT NULL,
      lineage_id uuid NOT NULL, principal_id uuid NOT NULL, project_id uuid NOT NULL,
      body jsonb NOT NULL, pins jsonb NOT NULL,
      issued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
      CONSTRAINT uq_application_authorization_scope UNIQUE(tenant_id,run_id,id),
      CONSTRAINT uq_application_authorization_run UNIQUE(tenant_id,run_id),
      FOREIGN KEY(tenant_id,run_id) REFERENCES cehub_ai.agent_runs(tenant_id,id) ON DELETE RESTRICT,
      FOREIGN KEY(tenant_id,lineage_id,run_id)
       REFERENCES cehub_ai.budget_run_links(tenant_id,lineage_id,run_id) ON DELETE RESTRICT,
      FOREIGN KEY(tenant_id,principal_id)
       REFERENCES cehub_core.users(tenant_id,id) ON DELETE RESTRICT,
      FOREIGN KEY(tenant_id,project_id)
       REFERENCES cehub_project.projects(tenant_id,id) ON DELETE RESTRICT,
      CONSTRAINT ck_application_authorizations_lifetime CHECK(expires_at>issued_at
       AND jsonb_typeof(body)='object' AND jsonb_typeof(pins)='object')
    );
    CREATE TRIGGER protect_application_authorization BEFORE UPDATE OR DELETE
     ON cehub_ai.application_authorizations FOR EACH ROW
     EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
    REVOKE ALL ON cehub_ai.application_authorizations FROM PUBLIC;""")
    op.execute(AUTHORITY)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.application_authorizations) THEN
       RAISE EXCEPTION 'cannot remove persistent application authorization history';
      END IF;
    END $body$;""")
    op.execute("DROP TRIGGER require_application_authorization ON cehub_ai.budget_journal")
    op.execute("DROP FUNCTION cehub_ai.require_application_authorization()")
    op.execute("DROP FUNCTION cehub_ai.application_authorization_is_current(uuid)")
    op.execute("DROP TABLE cehub_ai.application_authorizations")
