"""Immutable human change scope, object versions and relationship evidence.
Revision ID: 0188_change_impact_scope
Revises: 0187_professional_change_routes
"""

import sqlalchemy as sa
from alembic import op

revision = "0188_change_impact_scope"
down_revision = "0187_professional_change_routes"
branch_labels = None
depends_on = None

DDL = [
    """
CREATE TABLE cehub_product.change_impact_scope_versions (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
ecr_id UUID NOT NULL,
revision_number INTEGER NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
reason TEXT NOT NULL,
snapshot JSONB NOT NULL,
CONSTRAINT pk_change_impact_scope_versions PRIMARY KEY (id),
CONSTRAINT uq_change_impact_scope_revision UNIQUE (tenant_id, project_id, ecr_id,
revision_number),
CONSTRAINT uq_change_impact_scope_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_change_impact_scope_versions_tenant_id_engineering_c_a02b FOREIGN KEY(tenant_id,
project_id, ecr_id) REFERENCES cehub_product.engineering_change_requests (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_change_impact_scope_versions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_change_impact_scope_versions_change_impact_scope_shape CHECK (revision_number > 0
AND request_digest ~ '^[a-f0-9]{64}$' AND btrim(reason)<>'' AND jsonb_typeof(snapshot)='object')
)
""",
    """
CREATE FUNCTION cehub_product.guard_change_impact_scope() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE latest integer;
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Change scope history is immutable' USING
ERRCODE='23514'; END IF;
PERFORM 1 FROM cehub_product.engineering_change_requests WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.ecr_id AND status IN ('request','impact_analysis') FOR
UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Change scope requires an ECR awaiting analysis' USING
ERRCODE='23514'; END IF;
SELECT COALESCE(max(revision_number),0) INTO latest FROM
cehub_product.change_impact_scope_versions
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND ecr_id=NEW.ecr_id;
IF NEW.revision_number<>latest+1 THEN RAISE EXCEPTION 'Change scope revision must follow latest'
USING ERRCODE='23514'; END IF;
IF jsonb_typeof(NEW.snapshot->'items') IS DISTINCT FROM 'array'
OR jsonb_array_length(NEW.snapshot->'items') NOT BETWEEN 1 AND 100
OR jsonb_typeof(NEW.snapshot->'edges') IS DISTINCT FROM 'array'
THEN RAISE EXCEPTION 'Change scope requires reviewed objects and relationship list' USING
ERRCODE='23514'; END IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_change_impact_scope BEFORE INSERT OR UPDATE OR DELETE
ON cehub_product.change_impact_scope_versions FOR EACH ROW
EXECUTE FUNCTION cehub_product.guard_change_impact_scope()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.change_impact_scope_versions)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard change scope history")
    op.execute("DROP TABLE cehub_product.change_impact_scope_versions")
    op.execute("DROP FUNCTION cehub_product.guard_change_impact_scope()")
