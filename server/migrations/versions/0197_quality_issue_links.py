"""Explicit Issue/NCR links, atomic escalation origins and immutable retractions."""

import sqlalchemy as sa
from alembic import op

revision = "0197_quality_issue_links"
down_revision = "0196_living_fmea_versions"
branch_labels = None
depends_on = None

DDL = [
    """
CREATE TABLE cehub_quality.quality_issue_links (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        issue_id UUID NOT NULL,
        ncr_id UUID NOT NULL,
        origin VARCHAR(16) NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        reason TEXT NOT NULL,
        snapshot JSONB NOT NULL,
        CONSTRAINT pk_quality_issue_links PRIMARY KEY (id),
        CONSTRAINT uq_quality_issue_link_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_quality_issue_link_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT fk_quality_issue_links_tenant_id_issues FOREIGN KEY(tenant_id, project_id,
issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_quality_issue_links_tenant_id_nonconformance_reports FOREIGN
KEY(tenant_id, project_id, ncr_id) REFERENCES cehub_quality.nonconformance_reports (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_quality_issue_links_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_quality_issue_links_shape CHECK (origin IN ('linked','escalated') AND
btrim(reason)<>'' AND request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(snapshot)='object')
)
""",
    """
CREATE TABLE cehub_quality.quality_issue_link_retractions (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        link_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        reason TEXT NOT NULL,
        CONSTRAINT pk_quality_issue_link_retractions PRIMARY KEY (id),
        CONSTRAINT uq_quality_issue_link_retracted UNIQUE (link_id),
        CONSTRAINT uq_quality_link_retraction_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT fk_quality_issue_link_retractions_tenant_id_quality_issue_links FOREIGN
KEY(tenant_id, project_id, link_id) REFERENCES cehub_quality.quality_issue_links (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_quality_issue_link_retractions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_quality_issue_link_retractions_shape CHECK (btrim(reason)<>'' AND
request_digest ~ '^[a-f0-9]{64}$')
)
""",
]
GUARD = """

CREATE FUNCTION cehub_quality.guard_quality_issue_link() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Quality issue relation history is immutable' USING
ERRCODE='23514'; END IF;
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
IF TG_TABLE_NAME='quality_issue_links' THEN
IF EXISTS(
 SELECT 1 FROM cehub_quality.quality_issue_links l WHERE l.tenant_id=NEW.tenant_id
 AND l.project_id=NEW.project_id AND l.issue_id=NEW.issue_id AND l.ncr_id=NEW.ncr_id
 AND NOT EXISTS(SELECT 1 FROM cehub_quality.quality_issue_link_retractions r WHERE
r.link_id=l.id)
) THEN RAISE EXCEPTION 'An active Issue NCR relation already exists' USING ERRCODE='23514'; END
IF;
END IF;
RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_quality.guard_quality_issue_link() FROM PUBLIC;
CREATE TRIGGER guard_quality_issue_link BEFORE INSERT OR UPDATE OR DELETE ON
cehub_quality.quality_issue_links FOR EACH ROW EXECUTE FUNCTION
cehub_quality.guard_quality_issue_link();
REVOKE ALL ON cehub_quality.quality_issue_links FROM PUBLIC;
CREATE TRIGGER guard_quality_issue_link BEFORE INSERT OR UPDATE OR DELETE ON
cehub_quality.quality_issue_link_retractions FOR EACH ROW EXECUTE FUNCTION
cehub_quality.guard_quality_issue_link();
REVOKE ALL ON cehub_quality.quality_issue_link_retractions FROM PUBLIC;
"""


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)
    op.execute(GUARD)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_quality.quality_issue_links)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard quality issue relation history")
    for table in ("quality_issue_link_retractions", "quality_issue_links"):
        op.drop_table(table, schema="cehub_quality")
    op.execute("DROP FUNCTION cehub_quality.guard_quality_issue_link()")
