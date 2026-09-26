"""Immutable product template revisions and explicit project adoption.

Revision ID: 0098_project_templates
Revises: 0097_business_completion
"""

import sqlalchemy as sa
from alembic import op

revision = "0098_project_templates"
down_revision = "0097_business_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\n    CREATE TABLE cehub_project.project_template_versions (\n"
        "      id uuid PRIMARY KEY, tenant_id uuid NOT NULL, project_"
        "id uuid NOT NULL,\n      revision integer NOT NULL, template_"
        "id varchar(128) NOT NULL, template_version integer NOT NULL,"
        "\n      snapshot jsonb NOT NULL, digest varchar(64) NOT NULL,"
        " source_version_id uuid,\n      status varchar(16) NOT NULL, "
        "reason text NOT NULL, difference jsonb NOT NULL,\n      propo"
        "sed_by_user_id uuid NOT NULL, decided_by_user_id uuid,\n     "
        " created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "decided_at timestamptz,\n      CONSTRAINT ck_project_template"
        "_versions_versions_positive CHECK (revision>0 AND template_v"
        "ersion>0),\n      CONSTRAINT ck_project_template_versions_sta"
        "tus_allowed CHECK (status IN ('proposed','active','supersede"
        "d','rejected')),\n      CONSTRAINT ck_project_template_versio"
        "ns_text_nonblank CHECK (btrim(reason)<>'' AND btrim(template"
        "_id)<>''),\n      CONSTRAINT ck_project_template_versions_obj"
        "ects CHECK (jsonb_typeof(snapshot)='object' AND jsonb_typeof"
        "(difference)='object'),\n      CONSTRAINT ck_project_template"
        "_versions_digest_hex CHECK (digest ~ '^[0-9a-f]{64}$'),\n    "
        "  CONSTRAINT ck_project_template_versions_decision_consisten"
        "t CHECK ((status='proposed' AND decided_at IS NULL AND decid"
        "ed_by_user_id IS NULL) OR (status<>'proposed' AND decided_at"
        " IS NOT NULL AND decided_by_user_id IS NOT NULL)),\n      CON"
        "STRAINT uq_project_template_versions_project_id UNIQUE (tena"
        "nt_id,project_id,id),\n      CONSTRAINT uq_project_template_v"
        "ersions_revision UNIQUE (tenant_id,project_id,revision),\n   "
        "   CONSTRAINT fk_project_template_versions_project FOREIGN K"
        "EY (tenant_id,project_id) REFERENCES cehub_project.projects("
        "tenant_id,id) ON DELETE RESTRICT,\n      CONSTRAINT fk_projec"
        "t_template_versions_source FOREIGN KEY (tenant_id,project_id"
        ",source_version_id) REFERENCES cehub_project.project_templat"
        "e_versions(tenant_id,project_id,id) ON DELETE RESTRICT,\n    "
        "  CONSTRAINT fk_project_template_versions_proposer FOREIGN K"
        "EY (tenant_id,proposed_by_user_id) REFERENCES cehub_core.use"
        "rs(tenant_id,id) ON DELETE RESTRICT,\n      CONSTRAINT fk_pro"
        "ject_template_versions_decider FOREIGN KEY (tenant_id,decide"
        "d_by_user_id) REFERENCES cehub_core.users(tenant_id,id) ON D"
        "ELETE RESTRICT\n    );\n    CREATE UNIQUE INDEX uq_project_tem"
        "plate_versions_active ON cehub_project.project_template_vers"
        "ions(tenant_id,project_id) WHERE status='active';\n    CREATE"
        " FUNCTION cehub_project.protect_project_template_version() R"
        "ETURNS trigger\n    LANGUAGE plpgsql SET search_path=pg_catal"
        "og AS $$\n    BEGIN\n      IF TG_OP='DELETE' THEN RAISE EXCEPT"
        "ION 'Project template revisions cannot be deleted' USING ERR"
        "CODE='42501'; END IF;\n      IF (to_jsonb(NEW)-ARRAY['status'"
        ",'decided_at','decided_by_user_id']) IS DISTINCT FROM\n      "
        "   (to_jsonb(OLD)-ARRAY['status','decided_at','decided_by_us"
        "er_id']) THEN\n        RAISE EXCEPTION 'Project template cont"
        "ent is immutable' USING ERRCODE='42501';\n      END IF;\n     "
        " IF OLD.status='proposed' AND NEW.status IN ('active','rejec"
        "ted') THEN RETURN NEW; END IF;\n      IF OLD.status='active' "
        "AND NEW.status='superseded' AND\n         NEW.decided_at=OLD."
        "decided_at AND NEW.decided_by_user_id=OLD.decided_by_user_id"
        " THEN RETURN NEW; END IF;\n      IF NEW IS NOT DISTINCT FROM "
        "OLD THEN RETURN NEW; END IF;\n      RAISE EXCEPTION 'Invalid "
        "project template transition' USING ERRCODE='22023';\n    END "
        "$$;\n    CREATE TRIGGER protect_project_template_version BEFO"
        "RE UPDATE OR DELETE ON cehub_project.project_template_versio"
        "ns\n    FOR EACH ROW EXECUTE FUNCTION cehub_project.protect_p"
        "roject_template_version();\n    REVOKE ALL ON FUNCTION cehub_"
        "project.protect_project_template_version() FROM PUBLIC;\n    "
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.project_template_versions)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard project template revision history")
    op.drop_table("project_template_versions", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.protect_project_template_version()")
