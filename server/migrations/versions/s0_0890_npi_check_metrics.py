"""Rolling framework-check counts from persisted planning run results."""

from alembic import op

from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0890"
down_revision = "s0_0889"
branch_labels = depends_on = None

SIGNATURE = "npi_framework_check_counts(uuid,text,text,text,timestamptz,integer)"


def upgrade():
    ordinary_owner()
    op.execute("""
        CREATE INDEX ix_agent_run_events_npi_check ON agent_run_events (tenant_id, run_id, sequence)
            WHERE body->>'type' IN ('npi_plan_candidate','npi_plan_check_failed');
        CREATE FUNCTION npi_framework_check_counts(
            tenant uuid, skill text, skill_version text, model_version text,
            since timestamptz, window_size integer
        ) RETURNS TABLE (sample integer, failures integer)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
            WITH observations AS (
                SELECT DISTINCT ON (e.run_id) e.run_id, e.created_at,
                    e.body->>'type'='npi_plan_check_failed' AS failed
                FROM agent_run_events e
                JOIN agent_runs r ON r.tenant_id=e.tenant_id AND r.id=e.run_id
                WHERE e.tenant_id=tenant
                    AND tenant=nullif(current_setting('pdos.tenant_id',true),'')::uuid
                    AND e.body->>'skill_key'=skill AND e.body->>'skill_version'=skill_version
                    AND r.versions->>'model_version'=model_version
                    AND (since IS NULL OR e.created_at>=since)
                    AND (e.body->>'type'='npi_plan_candidate'
                        OR (e.body->>'type'='npi_plan_check_failed' AND e.body->'exception'='true'))
                ORDER BY e.run_id,e.sequence DESC
            ), recent AS (
                SELECT failed FROM observations ORDER BY created_at DESC,run_id DESC
                LIMIT LEAST(GREATEST(window_size,1),500)
            )
            SELECT count(*)::integer, count(*) FILTER (WHERE failed)::integer FROM recent
            HAVING tenant=nullif(current_setting('pdos.tenant_id',true),'')::uuid
        $$;
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO pdos_next_app,pdos_next_dispatch")
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.execute("DROP INDEX ix_agent_run_events_npi_check")
    op.execute("SET LOCAL ROLE NONE")
