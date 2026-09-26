"""Fixed professional work package sources for ECR analysis and approval.
Revision ID: 0187_professional_change_routes
Revises: 0186_engineering_review_packages
"""

import sqlalchemy as sa
from alembic import op

revision = "0187_professional_change_routes"
down_revision = "0186_engineering_review_packages"
branch_labels = None
depends_on = None

DDL = [
    """
CREATE TABLE cehub_product.professional_change_routes (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
source_kind VARCHAR(32) NOT NULL,
source_id UUID NOT NULL,
ecr_id UUID NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
reason TEXT NOT NULL,
snapshot JSONB NOT NULL,
CONSTRAINT pk_professional_change_routes PRIMARY KEY (id),
CONSTRAINT uq_professional_change_source UNIQUE (tenant_id, source_kind, source_id),
CONSTRAINT uq_professional_change_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_professional_change_routes_tenant_id_engineering_cha_f4d1 FOREIGN KEY(tenant_id,
project_id, ecr_id) REFERENCES cehub_product.engineering_change_requests (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_professional_change_routes_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_professional_change_routes_professional_change_shape CHECK (source_kind IN
('engineering_review','firmware_package') AND request_digest ~ '^[a-f0-9]{64}$' AND
jsonb_typeof(snapshot)='object' AND btrim(reason)<>'')
)
""",
    """
CREATE INDEX ix_professional_change_ecr ON cehub_product.professional_change_routes (tenant_id,
project_id, ecr_id)
""",
    """
CREATE FUNCTION cehub_product.guard_professional_change_route() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Professional change routing is immutable' USING
ERRCODE='23514'; END IF;
IF NOT EXISTS(SELECT 1 FROM cehub_product.engineering_change_requests WHERE
tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.ecr_id AND status IN ('request','impact_analysis'))
THEN
RAISE EXCEPTION 'Professional source requires an ECR awaiting analysis' USING ERRCODE='23514';
END IF;
IF (NEW.source_kind='engineering_review' AND NOT EXISTS(SELECT 1 FROM
cehub_product.engineering_review_packages
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_id))
OR (NEW.source_kind='firmware_package' AND NOT EXISTS(SELECT 1 FROM
cehub_product.firmware_work_packages
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_id)) THEN
RAISE EXCEPTION 'Professional source must belong to actual project' USING ERRCODE='23514'; END
IF;
RETURN NEW;
END $$
""",
    """
CREATE TRIGGER guard_professional_change_route BEFORE INSERT OR UPDATE OR DELETE
ON cehub_product.professional_change_routes FOR EACH ROW
EXECUTE FUNCTION cehub_product.guard_professional_change_route()
""",
]


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.professional_change_routes)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard professional change routing history")
    op.execute("DROP TABLE cehub_product.professional_change_routes")
    op.execute("DROP FUNCTION cehub_product.guard_professional_change_route()")
