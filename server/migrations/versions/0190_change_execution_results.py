"""Actual execution evidence with versioned independent confirmation.
Revision ID: 0190_change_execution_results
Revises: 0189_change_execution_tasks
"""

import sqlalchemy as sa
from alembic import op

revision = "0190_change_execution_results"
down_revision = "0189_change_execution_tasks"
branch_labels = None
depends_on = None
DDL = [
    """
CREATE TABLE cehub_product.change_execution_results (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
binding_id UUID NOT NULL,
revision_number INTEGER NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
reviewer_user_id UUID,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
outcome VARCHAR(32) NOT NULL,
snapshot JSONB NOT NULL,
CONSTRAINT pk_change_execution_results PRIMARY KEY (id),
CONSTRAINT uq_change_execution_result_revision UNIQUE (tenant_id, binding_id, revision_number),
CONSTRAINT uq_change_execution_result_request UNIQUE (tenant_id, created_by_user_id,
request_id),
CONSTRAINT fk_change_execution_results_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_change_execution_result_reviewer FOREIGN KEY(tenant_id, reviewer_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_change_execution_results_change_execution_result_shape CHECK (revision_number>0
AND request_digest ~ '^[a-f0-9]{64}$' AND outcome IN
('recorded','needs_follow_up','ready_for_confirmation') AND jsonb_typeof(snapshot)='object'),
CONSTRAINT ck_change_execution_results_change_execution_result_reviewer CHECK
(outcome<>'ready_for_confirmation' OR (reviewer_user_id IS NOT NULL AND
reviewer_user_id<>created_by_user_id)),
CONSTRAINT fk_change_execution_results_binding_id_change_execution_tasks FOREIGN KEY(binding_id)
REFERENCES cehub_product.change_execution_tasks (id) ON DELETE RESTRICT
)
""",
    """
CREATE TABLE cehub_product.change_execution_confirmations (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
result_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
outcome VARCHAR(16) NOT NULL,
note TEXT NOT NULL,
snapshot JSONB NOT NULL,
CONSTRAINT pk_change_execution_confirmations PRIMARY KEY (id),
CONSTRAINT uq_change_execution_result_confirmation UNIQUE (tenant_id, result_id),
CONSTRAINT uq_change_execution_confirmation_request UNIQUE (tenant_id, created_by_user_id,
request_id),
CONSTRAINT fk_change_execution_confirmations_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_change_execution_confirmations_change_execution_conf_f008 CHECK (request_digest ~
'^[a-f0-9]{64}$' AND outcome IN ('verified','returned') AND btrim(note)<>'' AND
jsonb_typeof(snapshot)='object'),
CONSTRAINT fk_change_execution_confirmations_result_id_change_exec_f2c4 FOREIGN KEY(result_id)
REFERENCES cehub_product.change_execution_results (id) ON DELETE RESTRICT
)
""",
    """
CREATE FUNCTION cehub_product.guard_change_execution_result() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE latest integer; submitted uuid; expected_reviewer uuid; actual_binding uuid;
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Execution result history is immutable' USING
ERRCODE='23514'; END IF;
IF TG_TABLE_NAME='change_execution_results' THEN
PERFORM 1 FROM cehub_product.change_execution_tasks WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id AND id=NEW.binding_id FOR UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Result must bind actual project execution item' USING
ERRCODE='23514'; END IF;
SELECT COALESCE(max(revision_number),0) INTO latest FROM cehub_product.change_execution_results
WHERE tenant_id=NEW.tenant_id AND binding_id=NEW.binding_id;
IF NEW.revision_number<>latest+1 THEN RAISE EXCEPTION 'Result revision must follow latest' USING
ERRCODE='23514'; END IF;
ELSE
SELECT created_by_user_id,reviewer_user_id,binding_id INTO
submitted,expected_reviewer,actual_binding FROM cehub_product.change_execution_results
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.result_id AND
outcome='ready_for_confirmation' FOR UPDATE;
IF NOT FOUND OR submitted=NEW.created_by_user_id OR expected_reviewer<>NEW.created_by_user_id
THEN
RAISE EXCEPTION 'Confirmation requires named independent reviewer' USING ERRCODE='23514'; END
IF;
IF EXISTS (SELECT 1 FROM cehub_product.change_execution_results r JOIN
cehub_product.change_execution_results target ON target.id=NEW.result_id
WHERE r.tenant_id=NEW.tenant_id AND r.binding_id=actual_binding AND
r.revision_number>target.revision_number) THEN
RAISE EXCEPTION 'Only the latest result may be confirmed' USING ERRCODE='23514'; END IF;
END IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_change_execution_results BEFORE INSERT OR UPDATE OR DELETE ON
cehub_product.change_execution_results FOR EACH ROW EXECUTE FUNCTION
cehub_product.guard_change_execution_result()
""",
    """
CREATE TRIGGER guard_change_execution_confirmations BEFORE INSERT OR UPDATE OR DELETE ON
cehub_product.change_execution_confirmations FOR EACH ROW EXECUTE FUNCTION
cehub_product.guard_change_execution_result()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.change_execution_results)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard execution evidence and confirmation history")
    op.execute("DROP TABLE cehub_product.change_execution_confirmations")
    op.execute("DROP TABLE cehub_product.change_execution_results")
    op.execute("DROP FUNCTION cehub_product.guard_change_execution_result()")
