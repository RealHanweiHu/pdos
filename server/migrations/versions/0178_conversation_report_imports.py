"""Conversation report handoffs and named import confirmation receipts.
Revision ID: 0178_conversation_report_imports
Revises: 0177_conversation_attachments
"""

import sqlalchemy as sa
from alembic import op

revision = "0178_conversation_report_imports"
down_revision = "0177_conversation_attachments"
branch_labels = None
depends_on = None
DDL = [
    """
ALTER TABLE cehub_quality.test_report_import_batches ADD COLUMN confirmed_by_user_id uuid, ADD
COLUMN confirmed_at timestamptz
""",
    """
ALTER TABLE cehub_quality.test_report_import_batches ADD CONSTRAINT fk_import_batch_confirmer
FOREIGN KEY (tenant_id,confirmed_by_user_id) REFERENCES cehub_core.users(tenant_id,id) ON
DELETE RESTRICT
""",
    """
ALTER TABLE cehub_quality.test_report_import_batches ADD CONSTRAINT
ck_test_report_import_batches_confirmation_receipt CHECK ((confirmed_by_user_id IS NULL AND
confirmed_at IS NULL) OR (status='confirmed' AND confirmed_by_user_id IS NOT NULL AND
confirmed_at IS NOT NULL))
""",
    """

CREATE TABLE cehub_ai.conversation_report_imports (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    conversation_id UUID NOT NULL,
    message_id UUID NOT NULL,
    attachment_id UUID NOT NULL,
    plan_id UUID NOT NULL,
    created_by_user_id UUID NOT NULL,
    request_id UUID NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL,
    mapping_request_id VARCHAR(128) NOT NULL,
    run_id UUID,
    batch_id UUID,
    reused_existing BOOLEAN,
    error_code VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_conversation_report_imports PRIMARY KEY (id),
    CONSTRAINT uq_conversation_import_request UNIQUE (tenant_id, conversation_id, request_id),
    CONSTRAINT fk_conversation_report_imports_tenant_id_conversation_m_b249 FOREIGN
KEY(tenant_id, message_id, attachment_id) REFERENCES cehub_ai.conversation_message_attachments
(tenant_id, message_id, attachment_id) ON DELETE RESTRICT,
    CONSTRAINT fk_conversation_report_imports_tenant_id_conversations FOREIGN KEY(tenant_id,
project_id, conversation_id) REFERENCES cehub_ai.conversations (tenant_id, project_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_conversation_report_imports_tenant_id_test_plans FOREIGN KEY(tenant_id,
plan_id) REFERENCES cehub_quality.test_plans (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_conversation_report_imports_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_conversation_report_imports_tenant_id_test_report_im_e0a0 FOREIGN
KEY(tenant_id, batch_id) REFERENCES cehub_quality.test_report_import_batches (tenant_id, id) ON
DELETE RESTRICT,
    CONSTRAINT fk_conversation_report_imports_tenant_id_agent_runs FOREIGN KEY(tenant_id,
run_id) REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_conversation_report_imports_digests CHECK (request_digest ~ '^[0-9a-f]{64}$'
AND source_sha256 ~ '^[0-9a-f]{64}$')
)

""",
    """
CREATE INDEX ix_conversation_import_message ON cehub_ai.conversation_report_imports (tenant_id,
conversation_id, message_id, created_at)
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)
    op.execute(GUARDS)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.conversation_report_imports) "
                "OR EXISTS(SELECT 1 FROM cehub_quality.test_report_import_batches "
                "WHERE confirmed_by_user_id IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to remove report handoff and confirmation evidence")
    op.execute("""
      DROP TABLE cehub_ai.conversation_report_imports;
      DROP FUNCTION cehub_ai.guard_conversation_report_import();
      DROP TRIGGER guard_import_confirmation_receipt ON cehub_quality.test_report_import_batches;
      DROP FUNCTION cehub_quality.guard_import_confirmation_receipt();
      ALTER TABLE cehub_quality.test_report_import_batches
       DROP CONSTRAINT ck_test_report_import_batches_confirmation_receipt,
       DROP CONSTRAINT fk_import_batch_confirmer,
       DROP COLUMN confirmed_by_user_id, DROP COLUMN confirmed_at;
    """)


GUARDS = r"""
CREATE FUNCTION cehub_ai.guard_conversation_report_import() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE
 c cehub_ai.conversations%ROWTYPE;
 a cehub_ai.conversation_attachments%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Report handoff receipts are retained' USING ERRCODE='23514';
 END IF;
 SELECT * INTO c FROM cehub_ai.conversations WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id=NEW.conversation_id;
 SELECT * INTO a FROM cehub_ai.conversation_attachments WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND conversation_id=NEW.conversation_id AND id=NEW.attachment_id;
 IF c.id IS NULL OR a.id IS NULL OR c.created_by_user_id<>NEW.created_by_user_id
  OR a.sha256<>NEW.source_sha256 OR NOT EXISTS(SELECT 1 FROM cehub_quality.test_plans p
   WHERE p.tenant_id=NEW.tenant_id AND p.project_id=NEW.project_id AND p.id=NEW.plan_id)
  OR NOT EXISTS(SELECT 1 FROM cehub_ai.conversation_messages m WHERE m.tenant_id=NEW.tenant_id
   AND m.conversation_id=NEW.conversation_id AND m.id=NEW.message_id) THEN
  RAISE EXCEPTION 'Report source and plan must match this private handoff' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND (c.archived_at IS NOT NULL OR a.revoked_at IS NOT NULL
  OR a.status<>'extracted' OR a.classification<>'internal' OR NEW.run_id IS NOT NULL
  OR NEW.batch_id IS NOT NULL) THEN
  RAISE EXCEPTION 'New handoff requires a usable source and no invented receipt'
   USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (
  (to_jsonb(NEW)-ARRAY['run_id','batch_id','reused_existing','error_code','updated_at'])
  IS DISTINCT FROM
  (to_jsonb(OLD)-ARRAY['run_id','batch_id','reused_existing','error_code','updated_at'])
  OR (OLD.run_id IS NOT NULL AND NEW.run_id IS DISTINCT FROM OLD.run_id)
  OR (OLD.batch_id IS NOT NULL AND NEW.batch_id IS DISTINCT FROM OLD.batch_id)) THEN
  RAISE EXCEPTION 'Report request identity and bound receipts are immutable' USING ERRCODE='23514';
 END IF;
 IF NEW.run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_ai.agent_runs r
  WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.run_id
   AND r.requested_by_user_id=NEW.created_by_user_id AND r.request_id=NEW.mapping_request_id
   AND r.context_version='report-mapping-request-v1'
   AND r.run_context->'mapping_request'->>'file_sha256'=NEW.source_sha256
   AND r.run_context->'mapping_request'->>'plan_id'=NEW.plan_id::text) THEN
  RAISE EXCEPTION 'Mapping run must be the actual source request' USING ERRCODE='23514';
 END IF;
 IF NEW.batch_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_quality.test_report_import_batches b
  JOIN cehub_project.documents d ON d.tenant_id=b.tenant_id AND d.id=b.document_id
  WHERE b.tenant_id=NEW.tenant_id AND b.project_id=NEW.project_id AND b.plan_id=NEW.plan_id
   AND b.id=NEW.batch_id AND d.project_id=NEW.project_id
   AND d.sha256=NEW.source_sha256) THEN
  RAISE EXCEPTION 'Import batch must contain the same original report' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_ai.guard_conversation_report_import() FROM PUBLIC;
CREATE TRIGGER guard_conversation_report_import BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_ai.conversation_report_imports FOR EACH ROW
 EXECUTE FUNCTION cehub_ai.guard_conversation_report_import();

CREATE FUNCTION cehub_quality.guard_import_confirmation_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF OLD.status='confirmed' AND (NEW.status<>OLD.status
  OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
  OR NEW.confirmed_by_user_id IS DISTINCT FROM OLD.confirmed_by_user_id) THEN
  RAISE EXCEPTION 'Confirmed report receipt cannot be rewritten' USING ERRCODE='23514';
 END IF;
 IF NEW.status='confirmed' AND OLD.status<>'confirmed'
  AND (NEW.confirmed_by_user_id IS NULL OR NEW.confirmed_at IS NULL) THEN
  RAISE EXCEPTION 'New report confirmation requires its actual actor and time'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_quality.guard_import_confirmation_receipt() FROM PUBLIC;
CREATE TRIGGER guard_import_confirmation_receipt BEFORE UPDATE
 ON cehub_quality.test_report_import_batches
 FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_import_confirmation_receipt();
"""
