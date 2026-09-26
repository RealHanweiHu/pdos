"""Actual tooling rounds and immutable evidence-backed revisions."""

from alembic import op

revision = "0306_tooling_rounds"
down_revision = "0305_change_compliance_reviews"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.tooling_rounds (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	code VARCHAR(128) NOT NULL,
	asset_reference VARCHAR(128) NOT NULL,
	tooling_kind VARCHAR(16) NOT NULL,
	round_label VARCHAR(64) NOT NULL,
	title VARCHAR(256) NOT NULL,
	phase VARCHAR(16) NOT NULL,
	version INTEGER NOT NULL,
	status VARCHAR(16) NOT NULL,
	outcome VARCHAR(16) NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	payload JSONB NOT NULL,
	snapshot JSONB NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_tooling_rounds PRIMARY KEY (id),
	CONSTRAINT uq_tooling_round_scope UNIQUE (tenant_id, project_id, id),
	CONSTRAINT uq_tooling_round_code UNIQUE (tenant_id, project_id, code),
	CONSTRAINT uq_tooling_actual_round UNIQUE (tenant_id, project_id, asset_reference, round_label),
        CONSTRAINT fk_tooling_rounds_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_tooling_rounds_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_tooling_rounds_tooling_round_valid CHECK (version>0 AND tooling_kind IN
('mold','fixture','tooling') AND phase IN ('EVT','DVT','PVT','other') AND status IN
('planned','in_progress','completed','cancelled') AND outcome IN
('pending','accepted','conditional','rejected')),
        CONSTRAINT ck_tooling_rounds_tooling_actual_order CHECK (completed_at IS NULL OR
(started_at IS NOT NULL AND completed_at>=started_at))
)

;

CREATE TABLE cehub_supplier.tooling_round_revisions (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	project_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	request_id UUID NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	reason TEXT NOT NULL,
	snapshot JSONB NOT NULL,
	evidence_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	round_id UUID NOT NULL,
	version INTEGER NOT NULL,
	payload JSONB NOT NULL,
	CONSTRAINT pk_tooling_round_revisions PRIMARY KEY (id),
        CONSTRAINT fk_tooling_round_revisions_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_tooling_round_revisions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_tooling_round_revisions_record_valid CHECK (btrim(reason)<>'' AND
request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
        CONSTRAINT fk_tooling_round_revisions_tenant_id_tooling_rounds FOREIGN KEY(tenant_id,
project_id, round_id) REFERENCES cehub_supplier.tooling_rounds (tenant_id, project_id, id) ON
DELETE RESTRICT,
	CONSTRAINT uq_tooling_round_revision UNIQUE (tenant_id, project_id, round_id, version),
	CONSTRAINT uq_tooling_round_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_tooling_round_revisions_tooling_revision_valid CHECK (version>0 AND
jsonb_typeof(payload)='object')
)

;
"""

GUARDS = """
CREATE FUNCTION cehub_supplier.tooling_round_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Tooling round history requires retention'; END IF;
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
IF TG_OP='INSERT' AND NEW.version<>1 THEN RAISE EXCEPTION 'Tooling starts at revision one'; END IF;
IF TG_OP='UPDATE' AND (NEW.version<>OLD.version+1 OR NEW.id<>OLD.id OR
NEW.tenant_id<>OLD.tenant_id OR NEW.project_id<>OLD.project_id OR NEW.code<>OLD.code OR
NEW.asset_reference<>OLD.asset_reference OR NEW.round_label<>OLD.round_label OR
NEW.tooling_kind<>OLD.tooling_kind OR NEW.created_by_user_id<>OLD.created_by_user_id OR
NEW.created_at<>OLD.created_at) THEN
RAISE EXCEPTION 'Tooling revision retains original identity'; END IF;
IF NEW.payload IS DISTINCT FROM NEW.snapshot->'command'
OR NEW.status IS DISTINCT FROM NEW.payload->>'status'
OR NEW.outcome IS DISTINCT FROM NEW.payload->>'outcome'
OR NEW.started_at IS DISTINCT FROM (NEW.payload#>>'{started,at}')::timestamptz
OR NEW.completed_at IS DISTINCT FROM (NEW.payload#>>'{completed,at}')::timestamptz
OR NEW.started_at>clock_timestamp() OR NEW.completed_at>clock_timestamp() THEN
RAISE EXCEPTION 'Tooling current state must match its actual evidence'; END IF;
RETURN NEW;
END $$;
CREATE FUNCTION cehub_supplier.tooling_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current cehub_supplier.tooling_rounds%ROWTYPE;
previous cehub_supplier.tooling_round_revisions%ROWTYPE;
key text; fact jsonb; identity uuid;
BEGIN
SELECT * INTO STRICT current FROM cehub_supplier.tooling_rounds WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.round_id FOR UPDATE;
SELECT * INTO previous FROM cehub_supplier.tooling_round_revisions
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND round_id=NEW.round_id
ORDER BY version DESC LIMIT 1;
IF NEW.version<>coalesce(previous.version,0)+1 OR NEW.version<>current.version
OR NEW.payload IS DISTINCT FROM current.payload OR NEW.snapshot IS DISTINCT FROM current.snapshot
OR NEW.snapshot#>>'{sources,evidence_id,id}' IS DISTINCT FROM NEW.evidence_id::text THEN
RAISE EXCEPTION 'Tooling revision must preserve the current complete evidence'; END IF;
IF NEW.snapshot->'first_promise' IS DISTINCT FROM coalesce(
nullif(previous.snapshot->'first_promise','null'::jsonb),
NEW.snapshot#>'{sources,promised}', 'null'::jsonb) THEN
RAISE EXCEPTION 'Original tooling commitment must be preserved'; END IF;
FOREACH key IN ARRAY ARRAY['promised','estimated_ready','started','completed'] LOOP
fact := NEW.payload->key;
IF fact IS NOT NULL AND fact<>'null'::jsonb AND NOT EXISTS (
SELECT 1 FROM cehub_project.documents WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
AND id=(fact->>'evidence_id')::uuid) THEN
RAISE EXCEPTION 'Tooling milestone requires project evidence'; END IF;
END LOOP;
IF NEW.payload->>'report_id' IS NOT NULL AND NOT EXISTS (
SELECT 1 FROM cehub_project.documents WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
AND id=(NEW.payload->>'report_id')::uuid) THEN
RAISE EXCEPTION 'Tooling report must belong to this project'; END IF;
FOR identity IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.payload->'build_ids') LOOP
IF NOT EXISTS (SELECT 1 FROM cehub_product.build_batches WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=identity) THEN
RAISE EXCEPTION 'Tooling relationship is outside the project'; END IF;
END LOOP;
FOR identity IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.payload->'sample_ids') LOOP
IF NOT EXISTS (SELECT 1 FROM cehub_product.samples WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=identity) THEN
RAISE EXCEPTION 'Tooling relationship is outside the project'; END IF;
END LOOP;
FOR identity IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.payload->'issue_ids') LOOP
IF NOT EXISTS (SELECT 1 FROM cehub_project.issues WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=identity) THEN
RAISE EXCEPTION 'Tooling relationship is outside the project'; END IF;
END LOOP;
FOR identity IN SELECT value::uuid FROM jsonb_array_elements_text(NEW.payload->'need_node_ids') LOOP
IF NOT EXISTS (SELECT 1 FROM cehub_project.schedule_nodes WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=identity) THEN
RAISE EXCEPTION 'Tooling relationship is outside the project'; END IF;
END LOOP;
RETURN NEW;
END $$;
CREATE FUNCTION cehub_supplier.tooling_revision_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NOT EXISTS (SELECT 1 FROM cehub_supplier.tooling_round_revisions WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND round_id=NEW.id AND version=NEW.version
AND payload=NEW.payload AND snapshot=NEW.snapshot) THEN
RAISE EXCEPTION 'Tooling change must commit its immutable revision in the same transaction'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER tooling_round_write BEFORE INSERT OR UPDATE OR DELETE
ON cehub_supplier.tooling_rounds FOR EACH ROW EXECUTE FUNCTION cehub_supplier.tooling_round_guard();
CREATE TRIGGER tooling_revision_insert BEFORE INSERT ON cehub_supplier.tooling_round_revisions
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.tooling_revision_guard();
CREATE TRIGGER tooling_revision_immutable BEFORE UPDATE OR DELETE
ON cehub_supplier.tooling_round_revisions
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE CONSTRAINT TRIGGER tooling_revision_committed AFTER INSERT OR UPDATE
ON cehub_supplier.tooling_rounds DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.tooling_revision_complete();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.tooling_rounds) THEN
    RAISE EXCEPTION 'Tooling actual history requires retention'; END IF;
    END $$;
    DROP TABLE cehub_supplier.tooling_round_revisions;
    DROP TABLE cehub_supplier.tooling_rounds;
    DROP FUNCTION cehub_supplier.tooling_round_guard();
    DROP FUNCTION cehub_supplier.tooling_revision_guard();
    DROP FUNCTION cehub_supplier.tooling_revision_complete();
    """)
