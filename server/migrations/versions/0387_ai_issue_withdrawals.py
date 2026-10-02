"""Reversible AI Issue creation, immutable single/run withdrawal receipts."""
# ruff: noqa: E501
from alembic import op

revision = "0387_ai_issue_withdrawals"
down_revision = "0386_ai_issue_applications"
branch_labels = None
depends_on = None

DDL = "CREATE TABLE cehub_ai.ai_issue_withdrawal_receipts (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tapplication_id UUID, \n\tactor_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\treason VARCHAR(1000) NOT NULL, \n\titems JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_ai_issue_withdrawal_receipts PRIMARY KEY (id), \n\tCONSTRAINT fk_ai_issue_withdrawal_receipts_tenant_id_projects FOREIGN KEY(tenant_id, project_id) REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_withdrawal_receipts_tenant_id_agent_runs FOREIGN KEY(tenant_id, run_id) REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_withdrawal_receipts_tenant_id_ai_issue_applications FOREIGN KEY(tenant_id, project_id, application_id) REFERENCES cehub_ai.ai_issue_applications (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_ai_issue_withdrawal_receipts_tenant_id_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_ai_issue_withdrawal_receipts_shape CHECK (kind IN ('single','run') AND ((kind='single')=(application_id IS NOT NULL)) AND btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(items)='array'), \n\tCONSTRAINT uq_ai_issue_withdrawal_scope UNIQUE (tenant_id, project_id, id), \n\tCONSTRAINT uq_ai_issue_withdrawal_request UNIQUE (tenant_id, actor_user_id, request_id)\n);"

GUARDS = """
ALTER TABLE cehub_project.issues ADD COLUMN withdrawn_at timestamptz;
ALTER TABLE cehub_project.issues ADD COLUMN ai_withdrawal_id uuid;
ALTER TABLE cehub_project.issues ADD CONSTRAINT ck_issues_ai_withdrawal
 CHECK ((withdrawn_at IS NULL)=(ai_withdrawal_id IS NULL) AND (withdrawn_at IS NULL OR created_by_ai_principal_id IS NOT NULL));
ALTER TABLE cehub_project.issues ADD CONSTRAINT fk_issue_ai_withdrawal
 FOREIGN KEY(tenant_id,project_id,ai_withdrawal_id)
 REFERENCES cehub_ai.ai_issue_withdrawal_receipts(tenant_id,project_id,id)
 ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION cehub_ai.guard_issue_withdrawal_overlay() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.withdrawn_at IS NOT NULL THEN RAISE EXCEPTION 'Issue creation cannot start withdrawn'; END IF;
 ELSE
  IF OLD.withdrawn_at IS NOT NULL AND NEW IS DISTINCT FROM OLD
  THEN RAISE EXCEPTION 'Withdrawn Issue history cannot be rewritten'; END IF;
  IF OLD.withdrawn_at IS NULL AND NEW.withdrawn_at IS NOT NULL AND
    (OLD.created_by_ai_principal_id IS NULL OR OLD.status<>'open'
     OR (to_jsonb(NEW)-ARRAY['withdrawn_at','ai_withdrawal_id','updated_at'])
       IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['withdrawn_at','ai_withdrawal_id','updated_at']))
  THEN RAISE EXCEPTION 'Withdrawal must preserve the original AI Issue business state'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_issue_withdrawal_overlay BEFORE INSERT OR UPDATE ON cehub_project.issues
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_issue_withdrawal_overlay();
CREATE FUNCTION cehub_ai.verify_issue_withdrawal_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF NEW.withdrawn_at IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM cehub_ai.ai_issue_withdrawal_receipts r
  JOIN cehub_ai.ai_issue_applications a ON a.tenant_id=r.tenant_id AND a.project_id=r.project_id
  WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.ai_withdrawal_id
   AND a.issue_id=NEW.id AND a.disposition='created' AND a.principal_id=NEW.created_by_ai_principal_id
   AND a.run_id=r.run_id AND r.created_at=NEW.withdrawn_at
   AND r.items @> jsonb_build_array(jsonb_build_object('application_id',a.id::text,'issue_id',NEW.id::text,'status','withdrawn'))
 ) THEN RAISE EXCEPTION 'Issue withdrawal requires its immutable reverse receipt'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER verify_issue_withdrawal_receipt AFTER UPDATE ON cehub_project.issues
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION cehub_ai.verify_issue_withdrawal_receipt();
CREATE FUNCTION cehub_ai.guard_issue_withdrawal_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item jsonb;
BEGIN
 IF jsonb_array_length(NEW.items)=0 THEN RAISE EXCEPTION 'Withdrawal requires actual application items'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(NEW.items) LOOP
  IF NOT EXISTS(SELECT 1 FROM cehub_ai.ai_issue_applications a
   JOIN cehub_project.issues i ON i.tenant_id=a.tenant_id AND i.project_id=a.project_id AND i.id=a.issue_id
   WHERE a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id AND a.run_id=NEW.run_id
    AND a.id::text=item->>'application_id' AND a.issue_id::text=item->>'issue_id'
    AND (NEW.kind='run' OR a.id=NEW.application_id)
    AND (item->>'status'='skipped' OR (item->>'status'='withdrawn' AND a.disposition='created'
      AND i.ai_withdrawal_id=NEW.id AND i.withdrawn_at=NEW.created_at))
  ) THEN RAISE EXCEPTION 'Withdrawal item does not match its actual application'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_issue_withdrawal_receipt BEFORE INSERT ON cehub_ai.ai_issue_withdrawal_receipts
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.guard_issue_withdrawal_receipt();
CREATE TRIGGER immutable_issue_withdrawal_receipt BEFORE UPDATE OR DELETE ON cehub_ai.ai_issue_withdrawal_receipts
 FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_ai.ai_issue_withdrawal_receipts FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
 REVOKE ALL ON cehub_ai.ai_issue_withdrawal_receipts FROM pdos_agent; END IF; END $$;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_ai.ai_issue_withdrawal_receipts)
     OR EXISTS(SELECT 1 FROM cehub_project.issues WHERE withdrawn_at IS NOT NULL)
     THEN RAISE EXCEPTION 'Retain AI Issue withdrawal history'; END IF; END $$;""")
    op.execute("DROP TRIGGER verify_issue_withdrawal_receipt ON cehub_project.issues")
    op.execute("DROP TRIGGER guard_issue_withdrawal_overlay ON cehub_project.issues")
    op.execute("DROP FUNCTION cehub_ai.verify_issue_withdrawal_receipt()")
    op.execute("DROP FUNCTION cehub_ai.guard_issue_withdrawal_overlay()")
    op.execute("ALTER TABLE cehub_project.issues DROP CONSTRAINT fk_issue_ai_withdrawal")
    op.execute("ALTER TABLE cehub_project.issues DROP CONSTRAINT ck_issues_ai_withdrawal")
    op.execute("ALTER TABLE cehub_project.issues DROP COLUMN ai_withdrawal_id, DROP COLUMN withdrawn_at")
    op.execute("DROP TABLE cehub_ai.ai_issue_withdrawal_receipts")
    op.execute("DROP FUNCTION cehub_ai.guard_issue_withdrawal_receipt()")
