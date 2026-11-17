"""Versioned NPI framework catalog, project binding, and role reference guards."""

# ruff: noqa: E501 - Keep the SQL constraints readable.

from alembic import op

from migrations.schema_s0_0881 import SCHEMA_SQL as FIXTURE_SQL
from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0889"
down_revision = "s0_0888"
branch_labels = depends_on = None

# Preserve the reviewed T2 list from the last migration that changed it.
PREVIOUS_DEADLINE = next(
    sql
    for sql in FIXTURE_SQL
    if sql.startswith(
        "ALTER TABLE confirmations ADD CONSTRAINT ck_confirmations_decision_deadline "
    )
)


def upgrade():
    ordinary_owner()
    op.execute("""
        CREATE TABLE npi_framework_revisions (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL,
            category_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            project_type text NOT NULL CHECK (project_type IN ('new_product','derivative')),
            revision integer NOT NULL CHECK (revision > 0),
            state text NOT NULL CHECK (state IN ('draft','published','retired')),
            document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
            reason text NOT NULL,
            author_id uuid NOT NULL,
            previous_id uuid,
            receipt_id uuid NOT NULL,
            UNIQUE (tenant_id, category_id, id),
            UNIQUE (tenant_id, category_id, project_type, revision),
            FOREIGN KEY (tenant_id, category_id) REFERENCES categories (tenant_id, id),
            FOREIGN KEY (tenant_id, author_id) REFERENCES principals (tenant_id, id),
            FOREIGN KEY (tenant_id, category_id, previous_id)
                REFERENCES npi_framework_revisions (tenant_id, category_id, id),
            FOREIGN KEY (tenant_id, receipt_id)
                REFERENCES action_receipts (tenant_id, id) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE INDEX ix_npi_framework_revisions_tenant_id ON npi_framework_revisions (tenant_id);
        CREATE INDEX ix_npi_framework_revisions_category_id ON npi_framework_revisions (category_id);
        ALTER TABLE npi_framework_revisions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE npi_framework_revisions FORCE ROW LEVEL SECURITY;
        CREATE POLICY owner_internal ON npi_framework_revisions TO pdos_next_owner USING (true) WITH CHECK (true);
        CREATE POLICY framework_read ON npi_framework_revisions FOR SELECT
            TO pdos_next_app,pdos_agent USING (category_access(tenant_id, category_id));
        CREATE POLICY framework_insert ON npi_framework_revisions FOR INSERT
            TO pdos_next_app WITH CHECK (
                category_access(tenant_id, category_id, true)
                AND author_id = scope_actor() AND author_id = scope_requester()
                AND EXISTS (
                    SELECT 1 FROM tenant_administrators a JOIN principals p
                        ON p.tenant_id = a.tenant_id AND p.id = a.principal_id
                    WHERE a.tenant_id = npi_framework_revisions.tenant_id
                        AND a.principal_id = author_id AND a.active AND p.active AND p.kind = 'human'
                )
            );
        GRANT SELECT ON npi_framework_revisions TO pdos_next_app,pdos_agent;
        GRANT INSERT ON npi_framework_revisions TO pdos_next_app;
        CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON npi_framework_revisions
            FOR EACH ROW EXECUTE FUNCTION protect_next_snapshot();
        ALTER TABLE projects ADD COLUMN framework_id uuid;
        ALTER TABLE projects ADD CONSTRAINT project_npi_framework_fk
            FOREIGN KEY (tenant_id, category_id, framework_id)
            REFERENCES npi_framework_revisions (tenant_id, category_id, id);
        CREATE FUNCTION require_npi_framework_receipt() RETURNS trigger LANGUAGE plpgsql
            SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM action_receipts r JOIN confirmations c
                    ON c.tenant_id=r.tenant_id AND c.id=r.confirmation_id
                WHERE r.tenant_id=NEW.tenant_id AND r.category_id=NEW.category_id
                    AND r.id=NEW.receipt_id AND r.product_id IS NULL
                    AND r.operation=CASE WHEN NEW.state='draft'
                        THEN 'work.framework.draft' ELSE 'work.framework.publish' END
                    AND r.actor_id=NEW.author_id AND r.requester_id=NEW.author_id
                    AND r.subject_type='npi_framework_revision' AND r.subject_id=NEW.id
                    AND r.subject_revision=NEW.revision AND c.operation=r.operation
                    AND c.consumed AND c.actor_id=NEW.author_id
            ) THEN
                RAISE EXCEPTION 'Framework requires named confirmation and receipt' USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END $$;
        REVOKE ALL ON FUNCTION require_npi_framework_receipt() FROM PUBLIC;
        CREATE CONSTRAINT TRIGGER framework_receipt AFTER INSERT ON npi_framework_revisions
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_npi_framework_receipt();
        CREATE FUNCTION npi_framework_role_references(t uuid, keys text[]) RETURNS text[]
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
            SELECT coalesce(array_agg(DISTINCT outcome->>'role' ORDER BY outcome->>'role'), ARRAY[]::text[])
            FROM (
                SELECT DISTINCT ON (category_id, project_type) state, document
                FROM npi_framework_revisions WHERE tenant_id=t AND state<>'draft'
                ORDER BY category_id, project_type, revision DESC
            ) v CROSS JOIN LATERAL jsonb_array_elements(v.document->'outcomes') outcome
            WHERE v.state='published' AND outcome->>'role'=ANY(keys)
                AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
                AND scope_actor()=scope_requester()
                AND EXISTS (
                    SELECT 1 FROM tenant_administrators a JOIN principals p
                        ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
                    WHERE a.tenant_id=t AND a.principal_id=scope_actor()
                        AND a.active AND p.active AND p.kind='human'
                )
        $$;
        REVOKE ALL ON FUNCTION npi_framework_role_references(uuid,text[]) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION npi_framework_role_references(uuid,text[]) TO pdos_next_app;
        CREATE FUNCTION protect_npi_framework_roles() RETURNS trigger LANGUAGE plpgsql
            SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE held text[];
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended('project-role-catalog:'||NEW.tenant_id::text,0));
            SELECT npi_framework_role_references(NEW.tenant_id, array_agg(DISTINCT outcome->>'role'))
                INTO held FROM npi_framework_revisions v
                CROSS JOIN LATERAL jsonb_array_elements(v.document->'outcomes') outcome
                WHERE v.tenant_id=NEW.tenant_id
                    AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.roles) e
                                    WHERE e->>'key'=outcome->>'role');
            IF cardinality(held)>0 THEN
                RAISE EXCEPTION 'Active framework role cannot be deleted' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION protect_npi_framework_roles() FROM PUBLIC;
        CREATE TRIGGER npi_role_guard BEFORE INSERT ON project_role_catalog_versions
            FOR EACH ROW EXECUTE FUNCTION protect_npi_framework_roles();
    """)
    op.execute("ALTER TABLE confirmations DROP CONSTRAINT ck_confirmations_decision_deadline")
    op.execute(
        PREVIOUS_DEADLINE.removesuffix("))")
        + ",'work.framework.publish'))"
    )
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute("""
        DROP TRIGGER npi_role_guard ON project_role_catalog_versions;
        DROP FUNCTION protect_npi_framework_roles();
        DROP FUNCTION npi_framework_role_references(uuid,text[]);
        ALTER TABLE projects DROP COLUMN framework_id;
        DROP TABLE npi_framework_revisions;
        DROP FUNCTION require_npi_framework_receipt();
    """)
    op.execute("ALTER TABLE confirmations DROP CONSTRAINT ck_confirmations_decision_deadline")
    op.execute(PREVIOUS_DEADLINE)
    op.execute("SET LOCAL ROLE NONE")
