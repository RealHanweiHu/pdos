"""Versioned supply recovery reports with original task and actual source evidence."""

from alembic import op

revision = "0312_supplier_recovery_results"
down_revision = "0311_supplier_recovery_application"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.supplier_recovery_results (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
item_id UUID NOT NULL,
version INTEGER NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
source_digest VARCHAR(64) NOT NULL,
source_snapshot JSONB NOT NULL,
report JSONB NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_supplier_recovery_results PRIMARY KEY (id),
CONSTRAINT uq_supply_result_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_supply_result_version UNIQUE (item_id, version),
CONSTRAINT uq_supply_result_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_supplier_recovery_results_tenant_id_supplier_recovery_items FOREIGN KEY(tenant_id,
project_id, item_id) REFERENCES cehub_supplier.supplier_recovery_items (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_recovery_results_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supplier_recovery_results_shape CHECK (version>0 AND request_digest ~
'^[a-f0-9]{64}$' AND source_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(source_snapshot)='object'
AND jsonb_typeof(report)='object')
)

;
"""
GUARDS = """

CREATE FUNCTION cehub_supplier.guard_recovery_result() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE task cehub_project.tasks%ROWTYPE;
DECLARE prior integer;
BEGIN
SELECT t.* INTO task FROM cehub_supplier.supplier_recovery_items i
JOIN cehub_project.tasks t ON t.tenant_id=i.tenant_id AND t.project_id=i.project_id
AND t.id=i.task_id WHERE i.tenant_id=NEW.tenant_id AND i.project_id=NEW.project_id
AND i.id=NEW.item_id;
SELECT coalesce(max(version),0) INTO prior FROM cehub_supplier.supplier_recovery_results
WHERE item_id=NEW.item_id;
IF task.id IS NULL OR task.assignee_user_id IS DISTINCT FROM NEW.created_by_user_id
OR NEW.version<>prior+1
OR NEW.report->>'expected_version' IS DISTINCT FROM prior::text
OR NEW.report->>'request_id' IS DISTINCT FROM NEW.request_id::text
OR NEW.source_snapshot->>'item_id' IS DISTINCT FROM NEW.item_id::text
OR NEW.source_snapshot->'task'->>'id' IS DISTINCT FROM task.id::text
OR NEW.source_snapshot->'task'->>'assignee_user_id' IS DISTINCT FROM task.assignee_user_id::text
OR NEW.report->>'disposition' IS NULL
OR NEW.report->>'disposition' NOT IN ('progress','ready_for_review','unable_to_recover')
OR jsonb_typeof(NEW.report->'evidence') IS DISTINCT FROM 'array'
OR jsonb_array_length(NEW.report->'evidence') NOT BETWEEN 1 AND 20
THEN RAISE EXCEPTION 'Recovery result needs current owner, source and consecutive version'
USING ERRCODE='23514'; END IF;
IF NEW.report->>'disposition'='ready_for_review' AND (
jsonb_typeof(NEW.source_snapshot->'targets') IS DISTINCT FROM 'array'
OR jsonb_array_length(NEW.source_snapshot->'targets')=0
OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.source_snapshot->'targets') x
WHERE x->'ready' IS DISTINCT FROM 'true'::jsonb)) THEN
RAISE EXCEPTION 'Ready report requires actual supply or tooling observations'
USING ERRCODE='23514'; END IF;
IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.report->'evidence') e
WHERE NOT EXISTS(SELECT 1 FROM cehub_project.documents d
WHERE d.tenant_id=NEW.tenant_id AND d.project_id=NEW.project_id
AND d.id::text=e->>'document_id')) THEN
RAISE EXCEPTION 'Result evidence must belong to this project' USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_recovery_result BEFORE INSERT ON cehub_supplier.supplier_recovery_results
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.guard_recovery_result();
CREATE TRIGGER protect_recovery_results BEFORE UPDATE OR DELETE ON
cehub_supplier.supplier_recovery_results FOR EACH ROW
EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();
REVOKE ALL ON cehub_supplier.supplier_recovery_results FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.guard_recovery_result() FROM PUBLIC;

"""


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_supplier_recovery_item_scope",
        "supplier_recovery_items",
        ["tenant_id", "project_id", "id"],
        schema="cehub_supplier",
    )
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
IF EXISTS(SELECT 1 FROM cehub_supplier.supplier_recovery_results) THEN
RAISE EXCEPTION 'Recovery result history requires retention'; END IF;
END $$;
DROP TABLE cehub_supplier.supplier_recovery_results;
DROP FUNCTION cehub_supplier.guard_recovery_result();
""")
    op.drop_constraint(
        "uq_supplier_recovery_item_scope", "supplier_recovery_items", schema="cehub_supplier"
    )
