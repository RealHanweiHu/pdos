"""Explicit Build/Gate material admission and independent scoped waivers."""

from alembic import op

revision = "0297_material_admission"
down_revision = "0296_material_schedule_bindings"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.material_admission_policies (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
target_kind VARCHAR(8) NOT NULL,
target_id UUID NOT NULL,
version INTEGER NOT NULL,
configuration JSONB NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
reason TEXT NOT NULL,
CONSTRAINT pk_material_admission_policies PRIMARY KEY (id),
CONSTRAINT fk_material_admission_policies_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_admission_policies_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT uq_material_admission_policy_version UNIQUE (tenant_id, target_kind, target_id,
version),
CONSTRAINT ck_material_admission_policies_policy_valid CHECK (target_kind IN ('build','gate')
AND version>0 AND jsonb_typeof(configuration)='object'),
CONSTRAINT ck_material_admission_policies_request_valid CHECK (request_digest ~ '^[0-9a-f]{64}$'
AND btrim(reason)<>''),
CONSTRAINT uq_material_admission_policies_request UNIQUE (tenant_id, created_by_user_id,
request_id)
)

;

CREATE TABLE cehub_supplier.material_admission_waivers (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
policy_id UUID NOT NULL,
source_digest VARCHAR(64) NOT NULL,
snapshot JSONB NOT NULL,
approver_user_id UUID NOT NULL,
expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
mitigations TEXT NOT NULL,
evidence JSONB NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
reason TEXT NOT NULL,
CONSTRAINT pk_material_admission_waivers PRIMARY KEY (id),
CONSTRAINT fk_material_admission_waivers_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_admission_waivers_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_admission_approver FOREIGN KEY(tenant_id,
approver_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_material_admission_waivers_independent_request CHECK
(created_by_user_id<>approver_user_id AND expires_at>created_at AND btrim(mitigations)<>''),
CONSTRAINT ck_material_admission_waivers_basis_valid CHECK (source_digest ~ '^[0-9a-f]{64}$' AND
jsonb_typeof(snapshot)='object' AND jsonb_typeof(evidence)='array' AND
jsonb_array_length(evidence) BETWEEN 1 AND 20),
CONSTRAINT ck_material_admission_waivers_request_valid CHECK (request_digest ~ '^[0-9a-f]{64}$'
AND btrim(reason)<>''),
CONSTRAINT uq_material_admission_waivers_request UNIQUE (tenant_id, created_by_user_id,
request_id),
CONSTRAINT fk_material_admission_waivers_policy_id_material_admiss_2498 FOREIGN KEY(policy_id)
REFERENCES cehub_supplier.material_admission_policies (id) ON DELETE RESTRICT
)

;

CREATE TABLE cehub_supplier.material_admission_decisions (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
waiver_id UUID NOT NULL,
outcome VARCHAR(16) NOT NULL,
snapshot JSONB NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
reason TEXT NOT NULL,
CONSTRAINT pk_material_admission_decisions PRIMARY KEY (id),
CONSTRAINT fk_material_admission_decisions_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_admission_decisions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT uq_material_admission_decision UNIQUE (tenant_id, waiver_id),
CONSTRAINT ck_material_admission_decisions_decision_valid CHECK (outcome IN
('approved','rejected') AND jsonb_typeof(snapshot)='object'),
CONSTRAINT ck_material_admission_decisions_request_valid CHECK (request_digest ~
'^[0-9a-f]{64}$' AND btrim(reason)<>''),
CONSTRAINT uq_material_admission_decisions_request UNIQUE (tenant_id, created_by_user_id,
request_id),
CONSTRAINT fk_material_admission_decisions_waiver_id_material_admi_d2d2 FOREIGN KEY(waiver_id)
REFERENCES cehub_supplier.material_admission_waivers (id) ON DELETE RESTRICT
)

;

CREATE TABLE cehub_supplier.material_admission_receipts (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
policy_id UUID NOT NULL,
target_kind VARCHAR(8) NOT NULL,
target_id UUID NOT NULL,
operation_key UUID NOT NULL,
transaction_id BIGINT DEFAULT txid_current() NOT NULL,
source_digest VARCHAR(64) NOT NULL,
decision_id UUID,
snapshot JSONB NOT NULL,
CONSTRAINT pk_material_admission_receipts PRIMARY KEY (id),
CONSTRAINT fk_material_admission_receipts_tenant_id_projects FOREIGN KEY(tenant_id, project_id)
REFERENCES cehub_project.projects (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_material_admission_receipts_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT uq_material_admission_operation UNIQUE (tenant_id, target_kind, operation_key),
CONSTRAINT ck_material_admission_receipts_receipt_valid CHECK (target_kind IN ('build','gate')
AND source_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(snapshot)='object'),
CONSTRAINT fk_material_admission_receipts_policy_id_material_admis_c8f9 FOREIGN KEY(policy_id)
REFERENCES cehub_supplier.material_admission_policies (id) ON DELETE RESTRICT,
CONSTRAINT fk_material_admission_receipts_decision_id_material_adm_4865 FOREIGN KEY(decision_id)
REFERENCES cehub_supplier.material_admission_decisions (id) ON DELETE RESTRICT
)

;
"""

GUARDS = """
CREATE FUNCTION cehub_supplier.material_admission_policy_guard() RETURNS trigger LANGUAGE
plpgsql AS $$
DECLARE cfg jsonb := NEW.configuration; latest integer; current_status text;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
SELECT coalesce(max(version),0) INTO latest FROM cehub_supplier.material_admission_policies
WHERE tenant_id=NEW.tenant_id AND target_kind=NEW.target_kind AND target_id=NEW.target_id;
IF NEW.version<>latest+1 OR cfg->>'mode' NOT IN ('enforce','disabled')
OR cfg->>'criterion' NOT IN ('all','critical') OR NOT cfg ?&
ARRAY['mode','criterion','build_ids','allow_waivers','require_closed_exceptions','waiver_max_hours']
OR jsonb_typeof(cfg->'allow_waivers')<>'boolean' OR
jsonb_typeof(cfg->'require_closed_exceptions')<>'boolean'
OR jsonb_typeof(cfg->'build_ids')<>'array' OR jsonb_array_length(cfg->'build_ids') NOT BETWEEN 1
AND 50
OR (cfg->>'waiver_max_hours')::integer NOT BETWEEN 1 AND 720 THEN
RAISE EXCEPTION 'Material policy requires a complete consecutive configuration'; END IF;
IF (SELECT count(DISTINCT value) FROM
jsonb_array_elements_text(cfg->'build_ids'))<>jsonb_array_length(cfg->'build_ids')
OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(cfg->'build_ids') ids(value)
WHERE NOT EXISTS (SELECT 1 FROM cehub_product.build_batches b WHERE b.tenant_id=NEW.tenant_id
AND b.project_id=NEW.project_id AND b.id=ids.value::uuid)) THEN
RAISE EXCEPTION 'Material policy requires unique actual project builds'; END IF;
IF NEW.target_kind='build' THEN
SELECT status INTO STRICT current_status FROM cehub_product.build_batches
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.target_id;
IF current_status<>'planned' OR cfg->'build_ids'<>jsonb_build_array(NEW.target_id::text) THEN
RAISE EXCEPTION 'Build material policy must be configured before starting its own build'; END
IF;
ELSE
SELECT status INTO STRICT current_status FROM cehub_project.gates
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.target_id;
IF current_status IN ('approved','conditional') OR EXISTS (SELECT 1 FROM
cehub_project.gate_signoff_rounds
WHERE tenant_id=NEW.tenant_id AND gate_id=NEW.target_id AND status='open') THEN
RAISE EXCEPTION 'Gate material policy is fixed for an open or approved round'; END IF;
END IF;
RETURN NEW;
END $$;

CREATE FUNCTION cehub_supplier.material_admission_waiver_guard() RETURNS trigger LANGUAGE
plpgsql AS $$
DECLARE p cehub_supplier.material_admission_policies%ROWTYPE;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
SELECT * INTO STRICT p FROM cehub_supplier.material_admission_policies WHERE id=NEW.policy_id;
IF p.tenant_id<>NEW.tenant_id OR p.project_id<>NEW.project_id OR
p.configuration->>'mode'<>'enforce'
OR p.configuration->>'allow_waivers'<>'true' OR NEW.expires_at<=clock_timestamp()
OR
NEW.expires_at>clock_timestamp()+make_interval(hours=>(p.configuration->>'waiver_max_hours')::integer)
OR NEW.snapshot#>>'{policy,id}' IS DISTINCT FROM NEW.policy_id::text
OR NEW.snapshot->>'source_digest' IS DISTINCT FROM NEW.source_digest
OR jsonb_array_length(NEW.snapshot->'blockers')=0
OR EXISTS (SELECT 1 FROM cehub_supplier.material_admission_policies newer
WHERE newer.tenant_id=p.tenant_id AND newer.target_kind=p.target_kind AND
newer.target_id=p.target_id AND newer.version>p.version) THEN
RAISE EXCEPTION 'Material waiver requires its current scoped policy, blockers and bounded
expiry'; END IF;
IF p.target_kind='build' AND NOT EXISTS (SELECT 1 FROM cehub_product.build_batches
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=p.target_id AND
status='planned') THEN
RAISE EXCEPTION 'Started build admission cannot receive a retrospective waiver'; END IF;
IF p.target_kind='gate' AND NOT EXISTS (SELECT 1 FROM cehub_project.gate_signoff_rounds
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND gate_id=p.target_id AND
status='open'
AND id::text=NEW.snapshot#>>'{scope,round_id}') THEN
RAISE EXCEPTION 'Gate material waiver must bind its actual open round'; END IF;
IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.evidence) e
WHERE NOT EXISTS (SELECT 1 FROM cehub_project.documents d WHERE d.tenant_id=NEW.tenant_id
AND d.project_id=NEW.project_id AND d.id::text=e->>'id' AND d.sha256=e->>'sha256'
AND d.size_bytes=(e->>'size_bytes')::bigint)) THEN
RAISE EXCEPTION 'Material waiver evidence must match actual scoped originals'; END IF;
RETURN NEW;
END $$;

CREATE FUNCTION cehub_supplier.material_admission_decision_guard() RETURNS trigger LANGUAGE
plpgsql AS $$
DECLARE w cehub_supplier.material_admission_waivers%ROWTYPE;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
SELECT * INTO STRICT w FROM cehub_supplier.material_admission_waivers WHERE id=NEW.waiver_id;
IF w.tenant_id<>NEW.tenant_id OR w.project_id<>NEW.project_id
OR NEW.created_by_user_id<>w.approver_user_id OR NEW.created_by_user_id=w.created_by_user_id
OR NEW.snapshot#>>'{waiver,id}' IS DISTINCT FROM w.id::text THEN
RAISE EXCEPTION 'Only the named independent approver may decide a material waiver'; END IF;
IF NEW.outcome='approved' AND (w.expires_at<=clock_timestamp()
OR NEW.snapshot#>>'{check,source_digest}' IS DISTINCT FROM w.source_digest
OR NEW.snapshot#>>'{check,policy,id}' IS DISTINCT FROM w.policy_id::text) THEN
RAISE EXCEPTION 'Material waiver approval requires its original current basis'; END IF;
RETURN NEW;
END $$;

CREATE FUNCTION cehub_supplier.material_admission_receipt_guard() RETURNS trigger LANGUAGE
plpgsql AS $$
DECLARE p cehub_supplier.material_admission_policies%ROWTYPE;
BEGIN
PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR
UPDATE;
SELECT * INTO STRICT p FROM cehub_supplier.material_admission_policies WHERE id=NEW.policy_id;
IF p.tenant_id<>NEW.tenant_id OR p.project_id<>NEW.project_id OR p.target_kind<>NEW.target_kind
OR p.target_id<>NEW.target_id
OR NEW.transaction_id<>txid_current() OR NEW.snapshot->>'allowed' IS DISTINCT FROM 'true'
OR NEW.snapshot->>'source_digest' IS DISTINCT FROM NEW.source_digest
OR NEW.snapshot#>>'{policy,id}' IS DISTINCT FROM NEW.policy_id::text
OR EXISTS (SELECT 1 FROM cehub_supplier.material_admission_policies newer WHERE
newer.tenant_id=p.tenant_id
AND newer.target_kind=p.target_kind AND newer.target_id=p.target_id AND newer.version>p.version)
THEN
RAISE EXCEPTION 'Admission receipt requires its current scoped policy and transaction'; END IF;
IF NEW.target_kind='build' AND (NEW.operation_key<>NEW.target_id OR NOT EXISTS
(SELECT 1 FROM cehub_product.build_batches WHERE tenant_id=NEW.tenant_id AND
project_id=NEW.project_id
AND id=NEW.target_id AND status='planned')) THEN RAISE EXCEPTION 'Build admission requires the
original start'; END IF;
IF NEW.target_kind='gate' AND NOT EXISTS (SELECT 1 FROM cehub_project.gate_signoff_rounds
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND gate_id=NEW.target_id AND
id=NEW.operation_key
AND status='open') THEN RAISE EXCEPTION 'Gate admission requires the current open round'; END
IF;
IF NEW.decision_id IS NULL AND jsonb_array_length(NEW.snapshot->'blockers')<>0 THEN
RAISE EXCEPTION 'Material blockers require an independent approved waiver'; END IF;
IF NEW.decision_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM
cehub_supplier.material_admission_decisions d
JOIN cehub_supplier.material_admission_waivers w ON w.id=d.waiver_id AND w.tenant_id=d.tenant_id
WHERE d.id=NEW.decision_id AND d.tenant_id=NEW.tenant_id AND d.project_id=NEW.project_id AND
d.outcome='approved'
AND w.policy_id=NEW.policy_id AND w.source_digest=NEW.source_digest AND
w.expires_at>clock_timestamp()
AND d.id::text=NEW.snapshot#>>'{waiver,decision_id}') THEN
RAISE EXCEPTION 'Material waiver is expired or does not cover this admission'; END IF;
RETURN NEW;
END $$;

CREATE FUNCTION cehub_supplier.material_admission_operation_guard() RETURNS trigger LANGUAGE
plpgsql AS $$
DECLARE kind text; p uuid;
BEGIN
IF TG_TABLE_NAME='build_batches' THEN
IF OLD.status<>'planned' OR NEW.status NOT IN ('in_progress','completed') THEN RETURN NEW; END
IF;
kind:='build';
ELSE
IF OLD.status=NEW.status OR NEW.status NOT IN ('approved','conditional') THEN RETURN NEW; END
IF;
kind:='gate';
END IF;
SELECT id INTO p FROM cehub_supplier.material_admission_policies WHERE tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND target_kind=kind AND target_id=NEW.id ORDER BY version DESC
LIMIT 1;
IF p IS NOT NULL AND NOT EXISTS (SELECT 1 FROM cehub_supplier.material_admission_receipts
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND target_kind=kind AND
target_id=NEW.id
AND policy_id=p AND transaction_id=txid_current()) THEN
RAISE EXCEPTION 'Actual operation requires its material admission receipt in the same
transaction'; END IF;
RETURN NEW;
END $$;

CREATE FUNCTION cehub_supplier.material_admission_used_guard() RETURNS trigger LANGUAGE plpgsql
AS $$
BEGIN
IF NEW.target_kind='build' AND NOT EXISTS (SELECT 1 FROM cehub_product.build_batches WHERE
tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.target_id AND status IN
('in_progress','completed')) THEN
RAISE EXCEPTION 'Build admission receipt must accompany actual starting'; END IF;
IF NEW.target_kind='gate' AND NOT EXISTS (SELECT 1 FROM cehub_project.gate_signoff_rounds r
JOIN cehub_project.gates g ON g.tenant_id=r.tenant_id AND g.id=r.gate_id
WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.id=NEW.operation_key
AND r.status='completed' AND g.status IN ('approved','conditional')
AND r.readiness_snapshot#>>'{material_admission,receipt_id}'=NEW.id::text) THEN
RAISE EXCEPTION 'Gate admission receipt must accompany its actual completed decision'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER material_admission_operation BEFORE UPDATE ON cehub_product.build_batches
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_admission_operation_guard();
CREATE TRIGGER material_admission_operation BEFORE UPDATE ON cehub_project.gates
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_admission_operation_guard();
CREATE CONSTRAINT TRIGGER material_admission_used AFTER INSERT ON
cehub_supplier.material_admission_receipts
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
cehub_supplier.material_admission_used_guard();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    for name, guard in (
        ("policies", "policy"),
        ("waivers", "waiver"),
        ("decisions", "decision"),
        ("receipts", "receipt"),
    ):
        op.execute(
            "CREATE TRIGGER material_admission_insert BEFORE INSERT ON "
            f"cehub_supplier.material_admission_{name} FOR EACH ROW EXECUTE FUNCTION "
            f"cehub_supplier.material_admission_{guard}_guard()"
        )
        op.execute(
            "CREATE TRIGGER material_admission_immutable BEFORE UPDATE OR DELETE ON "
            f"cehub_supplier.material_admission_{name} FOR EACH ROW EXECUTE FUNCTION "
            "cehub_supplier.material_ledger_immutable()"
        )


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_supplier.material_admission_policies) THEN
    RAISE EXCEPTION 'Material admission history requires retention; downgrade refused'; END IF;
    END $$;
    DROP TRIGGER material_admission_operation ON cehub_product.build_batches;
    DROP TRIGGER material_admission_operation ON cehub_project.gates;
    DROP TABLE cehub_supplier.material_admission_receipts;
    DROP TABLE cehub_supplier.material_admission_decisions;
    DROP TABLE cehub_supplier.material_admission_waivers;
    DROP TABLE cehub_supplier.material_admission_policies;
    DROP FUNCTION cehub_supplier.material_admission_policy_guard();
    DROP FUNCTION cehub_supplier.material_admission_waiver_guard();
    DROP FUNCTION cehub_supplier.material_admission_decision_guard();
    DROP FUNCTION cehub_supplier.material_admission_receipt_guard();
    DROP FUNCTION cehub_supplier.material_admission_operation_guard();
    DROP FUNCTION cehub_supplier.material_admission_used_guard();
    """)
