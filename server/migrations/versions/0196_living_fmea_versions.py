"""Human FMEA revisions, source snapshots and explicit publication history."""

import sqlalchemy as sa
from alembic import op

revision = "0196_living_fmea_versions"
down_revision = "0195_application_engineering_tools"
branch_labels = None
depends_on = None

DDL = [
    """
CREATE TABLE cehub_quality.fmea_entries (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_fmea_entries PRIMARY KEY (id),
        CONSTRAINT uq_fmea_entry_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT fk_fmea_entries_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_fmea_entries_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT
)
""",
    """
CREATE TABLE cehub_quality.fmea_versions (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        entry_id UUID NOT NULL,
        version INTEGER NOT NULL,
        previous_version_id UUID,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        body JSONB NOT NULL,
        sources JSONB NOT NULL,
        CONSTRAINT pk_fmea_versions PRIMARY KEY (id),
        CONSTRAINT uq_fmea_version_scope UNIQUE (tenant_id, project_id, entry_id, id),
        CONSTRAINT uq_fmea_version_number UNIQUE (tenant_id, project_id, entry_id, version),
        CONSTRAINT uq_fmea_version_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT fk_fmea_versions_tenant_id_fmea_entries FOREIGN KEY(tenant_id, project_id,
entry_id) REFERENCES cehub_quality.fmea_entries (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_fmea_versions_tenant_id_fmea_versions FOREIGN KEY(tenant_id, project_id,
entry_id, previous_version_id) REFERENCES cehub_quality.fmea_versions (tenant_id, project_id,
entry_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_fmea_versions_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_fmea_versions_shape CHECK (version>0 AND request_digest ~ '^[a-f0-9]{64}$'
AND jsonb_typeof(body)='object' AND jsonb_typeof(sources)='array')
)
""",
    """
CREATE TABLE cehub_quality.fmea_publications (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        entry_id UUID NOT NULL,
        version_id UUID NOT NULL,
        previous_publication_id UUID,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        published_by_user_id UUID NOT NULL,
        published_at TIMESTAMP WITH TIME ZONE NOT NULL,
        reason TEXT NOT NULL,
        CONSTRAINT pk_fmea_publications PRIMARY KEY (id),
        CONSTRAINT uq_fmea_publication_scope UNIQUE (tenant_id, project_id, entry_id, id),
        CONSTRAINT uq_fmea_published_version UNIQUE (version_id),
        CONSTRAINT uq_fmea_publication_request UNIQUE (tenant_id, published_by_user_id,
request_id),
        CONSTRAINT fk_fmea_publications_tenant_id_fmea_versions FOREIGN KEY(tenant_id,
project_id, entry_id, version_id) REFERENCES cehub_quality.fmea_versions (tenant_id, project_id,
entry_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_fmea_publications_tenant_id_fmea_publications FOREIGN KEY(tenant_id,
project_id, entry_id, previous_publication_id) REFERENCES cehub_quality.fmea_publications
(tenant_id, project_id, entry_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_fmea_publications_tenant_id_users FOREIGN KEY(tenant_id,
published_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_fmea_publications_shape CHECK (request_digest ~ '^[a-f0-9]{64}$' AND
btrim(reason)<>'')
)
""",
]
GUARD = """

CREATE FUNCTION cehub_quality.guard_fmea_history() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE prior uuid; number integer;
BEGIN
IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'FMEA history is immutable' USING ERRCODE='23514'; END
IF;
IF TG_TABLE_NAME='fmea_entries' THEN RETURN NEW; END IF;
PERFORM 1 FROM cehub_quality.fmea_entries WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.entry_id FOR UPDATE;
SELECT id,version INTO prior,number FROM cehub_quality.fmea_versions
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND entry_id=NEW.entry_id
 ORDER BY version DESC LIMIT 1;
IF TG_TABLE_NAME='fmea_versions' THEN
 IF NEW.previous_version_id IS DISTINCT FROM prior OR NEW.version<>coalesce(number,0)+1 THEN
  RAISE EXCEPTION 'FMEA revision must follow the latest version' USING ERRCODE='23514'; END IF;
ELSE
 IF NEW.version_id IS DISTINCT FROM prior THEN
  RAISE EXCEPTION 'Only the latest FMEA revision can be published' USING ERRCODE='23514'; END
IF;
 SELECT p.id INTO prior FROM cehub_quality.fmea_publications p
 JOIN cehub_quality.fmea_versions v ON v.id=p.version_id
 WHERE p.tenant_id=NEW.tenant_id AND p.project_id=NEW.project_id AND p.entry_id=NEW.entry_id
 ORDER BY v.version DESC LIMIT 1;
 IF NEW.previous_publication_id IS DISTINCT FROM prior THEN
  RAISE EXCEPTION 'FMEA publication must replace the current publication' USING ERRCODE='23514';
END IF;
END IF;
RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_quality.guard_fmea_history() FROM PUBLIC;
CREATE TRIGGER guard_fmea_history BEFORE INSERT OR UPDATE OR DELETE ON
cehub_quality.fmea_entries FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_fmea_history();
REVOKE ALL ON cehub_quality.fmea_entries FROM PUBLIC;
CREATE TRIGGER guard_fmea_history BEFORE INSERT OR UPDATE OR DELETE ON
cehub_quality.fmea_versions FOR EACH ROW EXECUTE FUNCTION cehub_quality.guard_fmea_history();
REVOKE ALL ON cehub_quality.fmea_versions FROM PUBLIC;
CREATE TRIGGER guard_fmea_history BEFORE INSERT OR UPDATE OR DELETE ON
cehub_quality.fmea_publications FOR EACH ROW EXECUTE FUNCTION
cehub_quality.guard_fmea_history();
REVOKE ALL ON cehub_quality.fmea_publications FROM PUBLIC;
"""


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)
    op.execute(GUARD)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_quality.fmea_entries)"))
        .scalar()
    ):
        raise RuntimeError("Refusing to discard FMEA history")
    for table in ("fmea_publications", "fmea_versions", "fmea_entries"):
        op.drop_table(table, schema="cehub_quality")
    op.execute("DROP FUNCTION cehub_quality.guard_fmea_history()")
