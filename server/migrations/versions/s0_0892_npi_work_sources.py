"""Permit only checked plan facts as a native task and commitment source."""

from alembic import op

from migrations.versions.s0_0778_native_pilot import ordinary_owner
from pdos_next.domain.projects.work.g0_storage import NATIVE_GUARD
from pdos_next.domain.projects.work.models import source_constraint

revision = "s0_0892"
down_revision = "s0_0891"
branch_labels = depends_on = None

# ruff: noqa: E501
G0_GUARD = NATIVE_GUARD.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
G0_ORIGINALS = "OR jsonb_array_length(v.sources)=0 OR jsonb_array_length(v.reads)=0"
G0_AND_NPI = G0_GUARD.replace(
    G0_ORIGINALS,
    "OR (NOT (v.source_basis ? 'npi_plan_task') AND "
    "(jsonb_array_length(v.sources)=0 OR jsonb_array_length(v.reads)=0))",
)


def _replace_g0(expected, new):
    conn = op.get_bind()
    actual = conn.exec_driver_sql(
        "SELECT prosrc FROM pg_proc WHERE oid='assert_work_task_g0_source(uuid,uuid)'::regprocedure"
    ).scalar_one()
    if actual.strip() != expected.split("$g0_work$")[1].strip():
        raise RuntimeError("Unexpected native G0 work source guard")
    conn.exec_driver_sql(new)


def _checks(npi):
    for table, name in (
        ("work_task_versions", "work_task_g0_sources"),
        ("work_commitment_versions", "work_commitment_versions_check1"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(
            name,
            table,
            source_constraint(g0_task=table == "work_task_versions", npi=npi),
        )


def upgrade():
    ordinary_owner()
    _replace_g0(G0_GUARD, G0_AND_NPI)
    _checks(True)
    op.execute("""
        CREATE UNIQUE INDEX npi_work_task_key_once ON work_task_versions
            (tenant_id, project_id, (source_basis #>> '{npi_plan_task,key}'))
            WHERE revision=1 AND source_basis ? 'npi_plan_task';
        CREATE FUNCTION require_npi_work_source() RETURNS trigger LANGUAGE plpgsql
            SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE native jsonb; expected jsonb; ref jsonb; prior jsonb;
        BEGIN
            native=NEW.source_basis->'npi_plan_task';
            IF TG_TABLE_NAME='work_commitment_versions' THEN
                SELECT source_basis->'npi_plan_task' INTO prior
                    FROM work_task_versions w
                    WHERE w.tenant_id=NEW.tenant_id AND w.project_id=NEW.project_id
                        AND w.task_id=NEW.task_id AND w.revision=NEW.task_revision;
                IF native IS DISTINCT FROM prior AND native IS NOT NULL THEN
                    RAISE EXCEPTION 'Commitment requires its own checked plan task basis'
                        USING ERRCODE='23514';
                END IF;
                RETURN NULL;
            END IF;
            ref=NEW.body->'plan_task';
            SELECT jsonb_build_object(
                    'project_id',p.id,'task',jsonb_build_object('id',t.id,'revision',v.revision),
                    'plan_id',v.id,'key',t.key,'framework',d.input_snapshot #> '{npi,checked,framework}',
                    'sources',t.forecast->'sources'
                ) INTO expected
                FROM project_tasks t JOIN plan_revisions v ON v.tenant_id=t.tenant_id
                    AND v.id=t.plan_id AND v.project_id=t.project_id
                JOIN plan_proposals d ON d.tenant_id=v.tenant_id AND d.id=v.proposal_id
                JOIN projects p ON p.tenant_id=v.tenant_id AND p.id=v.project_id
                WHERE t.tenant_id=NEW.tenant_id AND p.category_id=NEW.category_id
                    AND p.product_id=NEW.product_id AND p.id=NEW.project_id
                    AND t.id::text=ref->>'id' AND v.revision::text=ref->>'revision'
                    AND t.forecast ? 'role' AND jsonb_array_length(t.forecast->'sources')>0
                    AND d.input_snapshot #>> '{npi,checked,framework,id}' IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM action_receipts r WHERE r.tenant_id=t.tenant_id
                            AND r.subject_id=v.id AND r.subject_revision=v.revision
                            AND r.operation='work.plan.apply'
                            AND r.subject_type='plan_revision' AND r.category_id=p.category_id
                            AND r.product_id=p.product_id
                    )
                    AND (NEW.revision>1 OR (p.current_plan_id=v.id AND p.owner_id=NEW.requester_id));
            IF native IS DISTINCT FROM expected OR (native IS NOT NULL AND NEW.g0_open_item_id IS NOT NULL) THEN
                RAISE EXCEPTION 'Work task requires exact checked plan task basis'
                    USING ERRCODE='23514';
            END IF;
            IF NEW.revision>1 THEN
                SELECT source_basis->'npi_plan_task' INTO prior
                    FROM work_task_versions w WHERE w.tenant_id=NEW.tenant_id AND w.id=NEW.previous_id;
                IF native IS DISTINCT FROM prior THEN
                    RAISE EXCEPTION 'Task continuation must retain its checked plan task basis'
                        USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NULL;
        END $$;
        REVOKE ALL ON FUNCTION require_npi_work_source() FROM PUBLIC;
        CREATE CONSTRAINT TRIGGER npi_task_source AFTER INSERT ON work_task_versions
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_npi_work_source();
        CREATE CONSTRAINT TRIGGER npi_commitment_source AFTER INSERT ON work_commitment_versions
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_npi_work_source();
    """)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    conn = op.get_bind()
    if conn.exec_driver_sql(
        "SELECT EXISTS(SELECT 1 FROM work_task_versions WHERE source_basis ? 'npi_plan_task')"
    ).scalar():
        raise RuntimeError(
            "Restore a version without checked plan execution facts before downgrade"
        )
    ordinary_owner()
    op.execute("""
        DROP TRIGGER npi_commitment_source ON work_commitment_versions;
        DROP TRIGGER npi_task_source ON work_task_versions;
        DROP FUNCTION require_npi_work_source();
        DROP INDEX npi_work_task_key_once;
    """)
    _checks(False)
    _replace_g0(G0_AND_NPI, G0_GUARD)
    op.execute("SET LOCAL ROLE NONE")
