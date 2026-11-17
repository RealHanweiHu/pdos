"""Require a named plan receipt for framework rebinding and retain roles in open work."""

from alembic import op

from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0891"
down_revision = "s0_0890"
branch_labels = depends_on = None

# ruff: noqa: E501


def upgrade():
    ordinary_owner()
    op.execute("""
        CREATE FUNCTION require_npi_framework_upgrade() RETURNS trigger LANGUAGE plpgsql
            SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM npi_framework_revisions f
                JOIN plan_revisions p ON p.tenant_id=f.tenant_id AND p.id=NEW.current_plan_id
                JOIN plan_proposals d ON d.tenant_id=p.tenant_id AND d.id=p.proposal_id
                JOIN action_receipts r ON r.tenant_id=p.tenant_id AND r.subject_id=p.id
                JOIN confirmations c ON c.tenant_id=r.tenant_id AND c.id=r.confirmation_id
                WHERE f.tenant_id=NEW.tenant_id AND f.category_id=NEW.category_id
                    AND f.id=NEW.framework_id AND f.state='published'
                    AND p.project_id=NEW.id AND p.product_id=NEW.product_id
                    AND d.project_id=NEW.id AND d.base_plan_id IS NOT DISTINCT FROM OLD.current_plan_id
                    AND d.project_revision=OLD.revision AND NEW.revision=OLD.revision+1
                    AND (d.input_snapshot #>> '{npi,checked,framework,id}')=f.id::text
                    AND r.operation='work.plan.apply' AND r.subject_type='plan_revision'
                    AND r.subject_revision=p.revision AND r.product_id=NEW.product_id
                    AND r.category_id=NEW.category_id AND r.actor_id=NEW.owner_id
                    AND r.requester_id=NEW.owner_id AND r.agent_run_id IS NULL AND r.run_id IS NULL
                    AND r.result #>> '{framework_upgrade,from,id}' IS NOT DISTINCT FROM OLD.framework_id::text
                    AND r.result #>> '{framework_upgrade,to,id}'=f.id::text
                    AND r.xmin=p.xmin AND c.consumed AND c.operation=r.operation
                    AND c.actor_id=NEW.owner_id AND c.product_id=NEW.product_id
            ) THEN
                RAISE EXCEPTION 'Framework upgrade requires the named plan application'
                    USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END $$;
        REVOKE ALL ON FUNCTION require_npi_framework_upgrade() FROM PUBLIC;
        CREATE CONSTRAINT TRIGGER require_npi_framework_upgrade
            AFTER UPDATE ON projects DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            WHEN (NEW.framework_id IS DISTINCT FROM OLD.framework_id)
            EXECUTE FUNCTION require_npi_framework_upgrade();

        CREATE FUNCTION npi_open_work_roles(t uuid) RETURNS SETOF text
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
            SELECT DISTINCT task.forecast->>'role'
            FROM project_tasks task JOIN projects p
                ON p.tenant_id=task.tenant_id AND p.id=task.project_id
                AND p.current_plan_id=task.plan_id
            WHERE task.tenant_id=t AND task.forecast ? 'role'
              AND NOT EXISTS (
                SELECT 1 FROM work_task_currents c JOIN work_task_versions v
                    ON v.tenant_id=c.tenant_id AND v.id=c.version_id
                WHERE c.tenant_id=t AND c.project_id=p.id AND c.state='completed'
                    AND v.body #>> '{plan_task,id}'=task.id::text
              )
            UNION
            SELECT DISTINCT task.forecast->>'role'
            FROM work_task_currents c JOIN work_task_versions v
                ON v.tenant_id=c.tenant_id AND v.id=c.version_id
            JOIN project_tasks task ON task.tenant_id=v.tenant_id AND task.project_id=v.project_id
                AND task.id::text=v.body #>> '{plan_task,id}'
            WHERE c.tenant_id=t AND c.state NOT IN ('completed','cancelled')
                AND task.forecast ? 'role'
        $$;
        REVOKE ALL ON FUNCTION npi_open_work_roles(uuid) FROM PUBLIC;
        CREATE FUNCTION npi_unfinished_plan_role_references(t uuid, keys text[]) RETURNS text[]
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
            SELECT coalesce(array_agg(role ORDER BY role),ARRAY[]::text[]) FROM npi_open_work_roles(t) role
            WHERE t=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND role=ANY(keys)
                AND scope_actor()=scope_requester()
                AND EXISTS (
                    SELECT 1 FROM tenant_administrators a JOIN principals p
                        ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
                    WHERE a.tenant_id=t AND a.principal_id=scope_actor()
                        AND a.active AND p.active AND p.kind='human'
                )
        $$;
        REVOKE ALL ON FUNCTION npi_unfinished_plan_role_references(uuid,text[]) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION npi_unfinished_plan_role_references(uuid,text[]) TO pdos_next_app;
        CREATE FUNCTION protect_npi_open_work_roles() RETURNS trigger LANGUAGE plpgsql
            SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended('project-role-catalog:'||NEW.tenant_id::text,0));
            IF EXISTS (
                SELECT 1 FROM npi_open_work_roles(NEW.tenant_id) role
                WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.roles) r WHERE r->>'key'=role)
            ) THEN
                RAISE EXCEPTION 'Open NPI work role cannot be deleted' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION protect_npi_open_work_roles() FROM PUBLIC;
        CREATE TRIGGER npi_open_plan_role_guard BEFORE INSERT ON project_role_catalog_versions
            FOR EACH ROW EXECUTE FUNCTION protect_npi_open_work_roles();
    """)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute("""
        DROP TRIGGER npi_open_plan_role_guard ON project_role_catalog_versions;
        DROP FUNCTION protect_npi_open_work_roles();
        DROP FUNCTION npi_unfinished_plan_role_references(uuid,text[]);
        DROP FUNCTION npi_open_work_roles(uuid);
        DROP TRIGGER require_npi_framework_upgrade ON projects;
        DROP FUNCTION require_npi_framework_upgrade();
    """)
    op.execute("SET LOCAL ROLE NONE")
