"""Named approval and immutable, linked cost freeze versions."""

from alembic import op

revision = "0324_cost_freezes"
down_revision = "0323_cost_rollups"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_cost.cost_freeze_requests (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        rollup_id UUID NOT NULL,
        approver_user_id UUID NOT NULL,
        evidence_id UUID NOT NULL,
        payload JSONB NOT NULL,
        snapshot JSONB NOT NULL,
        previous_freeze_id UUID,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_freeze_requests PRIMARY KEY (id),
        CONSTRAINT fk_cost_freeze_requests_tenant_id_cost_rollups FOREIGN KEY(tenant_id,
project_id, rollup_id) REFERENCES cehub_cost.cost_rollups (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_cfr_approver FOREIGN KEY(tenant_id, approver_user_id) REFERENCES
cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_freeze_requests_tenant_id_documents FOREIGN KEY(tenant_id,
project_id, evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_cfr_creator FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES
cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_cfr_replay UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_cost_freeze_requests_digest CHECK (request_digest ~ '^[0-9a-f]{64}$'),
        CONSTRAINT uq_cfr_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT ck_cost_freeze_requests_snapshot CHECK (jsonb_typeof(snapshot)='object')
)

;
CREATE INDEX ix_cfr_history ON cehub_cost.cost_freeze_requests (tenant_id, project_id,
created_at, id);

CREATE TABLE cehub_cost.cost_freeze_decisions (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        freeze_request_id UUID NOT NULL,
        action VARCHAR(16) NOT NULL,
        reason TEXT NOT NULL,
        snapshot JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_freeze_decisions PRIMARY KEY (id),
        CONSTRAINT fk_cost_freeze_decisions_tenant_id_cost_freeze_requests FOREIGN
KEY(tenant_id, project_id, freeze_request_id) REFERENCES cehub_cost.cost_freeze_requests
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_cfd_decision UNIQUE (tenant_id, freeze_request_id),
        CONSTRAINT ck_cost_freeze_decisions_decision CHECK (action IN
('approve','reject','withdraw') AND btrim(reason)<>''),
        CONSTRAINT fk_cfd_creator FOREIGN KEY(tenant_id, created_by_user_id) REFERENCES
cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_cfd_replay UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT ck_cost_freeze_decisions_digest CHECK (request_digest ~ '^[0-9a-f]{64}$'),
        CONSTRAINT uq_cfd_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT ck_cost_freeze_decisions_snapshot CHECK (jsonb_typeof(snapshot)='object')
)

;
CREATE INDEX ix_cfd_history ON cehub_cost.cost_freeze_decisions (tenant_id, project_id,
created_at, id);

CREATE TABLE cehub_cost.cost_freezes (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        freeze_request_id UUID NOT NULL,
        decision_id UUID NOT NULL,
        rollup_id UUID NOT NULL,
        version INTEGER NOT NULL,
        calculation_digest VARCHAR(64) NOT NULL,
        snapshot JSONB NOT NULL,
        approved_by_user_id UUID NOT NULL,
        previous_freeze_id UUID,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_freezes PRIMARY KEY (id),
        CONSTRAINT fk_cost_freezes_tenant_id_cost_freeze_requests FOREIGN KEY(tenant_id,
project_id, freeze_request_id) REFERENCES cehub_cost.cost_freeze_requests (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_freezes_tenant_id_cost_freeze_decisions FOREIGN KEY(tenant_id,
project_id, decision_id) REFERENCES cehub_cost.cost_freeze_decisions (tenant_id, project_id,
id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_freezes_tenant_id_cost_rollups FOREIGN KEY(tenant_id, project_id,
rollup_id) REFERENCES cehub_cost.cost_rollups (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_freezes_tenant_id_cost_freezes FOREIGN KEY(tenant_id, project_id,
previous_freeze_id) REFERENCES cehub_cost.cost_freezes (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_cost_freezes_tenant_id_users FOREIGN KEY(tenant_id, approved_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT uq_cf_version UNIQUE (tenant_id, project_id, version),
        CONSTRAINT uq_cf_request UNIQUE (tenant_id, freeze_request_id),
        CONSTRAINT uq_cf_decision UNIQUE (tenant_id, decision_id),
        CONSTRAINT ck_cost_freezes_version CHECK (version > 0 AND calculation_digest ~
'^[0-9a-f]{64}$'),
        CONSTRAINT uq_cf_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT ck_cost_freezes_snapshot CHECK (jsonb_typeof(snapshot)='object')
)

;
CREATE INDEX ix_cf_history ON cehub_cost.cost_freezes (tenant_id, project_id, created_at, id);
ALTER TABLE cehub_cost.cost_freeze_requests ADD CONSTRAINT fk_cfr_previous FOREIGN
KEY(tenant_id, project_id, previous_freeze_id) REFERENCES cehub_cost.cost_freezes (tenant_id,
project_id, id) ON DELETE RESTRICT;
"""

GUARD = """
CREATE FUNCTION cehub_cost.guard_cost_freeze_request() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE calculation cehub_cost.cost_rollups; previous uuid;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO calculation FROM cehub_cost.cost_rollups WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.rollup_id;
 SELECT id INTO previous FROM cehub_cost.cost_freezes WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id ORDER BY version DESC LIMIT 1;
 IF NEW.previous_freeze_id IS DISTINCT FROM previous OR
  (calculation.algorithm='cost-rollup.v1' AND calculation.result->>'complete'='true'
   AND calculation.command->>'stage' IN ('estimate','quote')
   AND NEW.payload->>'rollup_id'=NEW.rollup_id::text
   AND NEW.payload->>'expected_calculation_digest'=calculation.calculation_digest
   AND NEW.payload->>'approver_user_id'=NEW.approver_user_id::text
   AND NEW.payload->>'evidence_id'=NEW.evidence_id::text
   AND btrim(NEW.payload->>'evidence_location')<>''
   AND btrim(NEW.payload->>'authority_basis')<>''
   AND btrim(NEW.payload->>'accepted_limits')<>''
   AND btrim(NEW.payload->>'reason')<>''
   AND NEW.snapshot->'command'=NEW.payload
   AND NEW.snapshot#>>'{approver,id}'=NEW.approver_user_id::text
   AND NEW.snapshot#>>'{authority_document,id}'=NEW.evidence_id::text
   AND NEW.snapshot#>>'{calculation,id}'=calculation.id::text
   AND NEW.snapshot#>'{calculation,command}'=calculation.command
   AND NEW.snapshot#>'{calculation,result}'=calculation.result
   AND NEW.snapshot#>'{calculation,snapshot}'=calculation.snapshot
   AND NEW.snapshot#>>'{calculation,calculation_digest}'=calculation.calculation_digest
   AND NEW.payload->>'previous_freeze_id' IS NOT DISTINCT FROM previous::text
  ) IS NOT TRUE THEN RAISE EXCEPTION 'Cost freeze request must bind the original calculation';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM cehub_core.users u WHERE u.tenant_id=NEW.tenant_id
  AND u.id=NEW.approver_user_id AND u.is_active AND (u.role IN ('owner','admin')
  OR (u.role='project_manager' AND EXISTS(SELECT 1 FROM cehub_project.project_members m
    WHERE m.tenant_id=NEW.tenant_id AND m.project_id=NEW.project_id AND m.user_id=u.id))))
 THEN RAISE EXCEPTION 'Cost approval requires an active authorized project approver'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_cost.guard_cost_freeze_decision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE request cehub_cost.cost_freeze_requests; previous uuid;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO request FROM cehub_cost.cost_freeze_requests WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.freeze_request_id;
 IF (NEW.snapshot#>>'{request,id}'=request.id::text
  AND NEW.snapshot#>'{request,payload}'=request.payload
  AND NEW.snapshot#>'{request,snapshot}'=request.snapshot
  AND NEW.snapshot#>>'{decision,action}'=NEW.action
  AND NEW.snapshot#>>'{decision,reason}'=NEW.reason) IS NOT TRUE THEN
  RAISE EXCEPTION 'Cost decision must retain the actual original request'; END IF;
 IF (NEW.action='withdraw' AND NEW.created_by_user_id<>request.created_by_user_id)
 OR (NEW.action<>'withdraw' AND NEW.created_by_user_id<>request.approver_user_id) THEN
  RAISE EXCEPTION 'Only the named person may decide this request'; END IF;
 IF NEW.action<>'withdraw' AND NOT EXISTS(SELECT 1 FROM cehub_core.users u
  WHERE u.tenant_id=NEW.tenant_id AND u.id=NEW.created_by_user_id AND u.is_active
  AND (u.role IN ('owner','admin') OR (u.role='project_manager' AND EXISTS(
  SELECT 1 FROM cehub_project.project_members m WHERE m.tenant_id=NEW.tenant_id
  AND m.project_id=NEW.project_id AND m.user_id=u.id)))) THEN
  RAISE EXCEPTION 'Current cost approval permission required'; END IF;
 IF NEW.action='approve' THEN
  SELECT id INTO previous FROM cehub_cost.cost_freezes WHERE tenant_id=NEW.tenant_id
   AND project_id=NEW.project_id ORDER BY version DESC LIMIT 1;
  IF request.previous_freeze_id IS DISTINCT FROM previous OR
   (NEW.snapshot#>>'{decision,scope_checked}'='true'
    AND NEW.snapshot#>>'{decision,cost_gap_checked}'='true'
    AND NEW.snapshot#>>'{decision,nre_checked}'='true'
    AND NEW.snapshot#>'{current,calculation}'=request.snapshot->'calculation'
    AND NEW.snapshot#>'{current,authority_document}'=request.snapshot->'authority_document'
    AND NEW.snapshot#>'{current,command}'=request.payload) IS NOT TRUE THEN
   RAISE EXCEPTION 'Approval requires checked original cost and current predecessor'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_cost.guard_cost_freeze() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE decision cehub_cost.cost_freeze_decisions; request cehub_cost.cost_freeze_requests;
 previous cehub_cost.cost_freezes;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO decision FROM cehub_cost.cost_freeze_decisions WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.decision_id;
 SELECT * INTO request FROM cehub_cost.cost_freeze_requests WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.freeze_request_id;
 SELECT * INTO previous FROM cehub_cost.cost_freezes WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id ORDER BY version DESC LIMIT 1;
 IF NEW.previous_freeze_id IS DISTINCT FROM previous.id OR
  NEW.version<>coalesce(previous.version,0)+1 OR
  (decision.action='approve' AND decision.freeze_request_id=request.id
   AND NEW.approved_by_user_id=decision.created_by_user_id
   AND NEW.approved_by_user_id=request.approver_user_id AND NEW.rollup_id=request.rollup_id
   AND NEW.previous_freeze_id IS NOT DISTINCT FROM request.previous_freeze_id
   AND NEW.snapshot->'calculation'=request.snapshot->'calculation'
   AND NEW.snapshot->'request'=decision.snapshot->'request'
   AND NEW.snapshot#>>'{approval,id}'=decision.id::text
   AND NEW.snapshot#>'{approval,snapshot}'=decision.snapshot
   AND NEW.calculation_digest=request.payload->>'expected_calculation_digest') IS NOT TRUE
 THEN RAISE EXCEPTION 'Frozen cost must preserve its actual named approval and version chain';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION cehub_cost.require_approved_cost_freeze() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.action='approve' AND NOT EXISTS(SELECT 1 FROM cehub_cost.cost_freezes
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND decision_id=NEW.id) THEN
  RAISE EXCEPTION 'Cost approval and frozen version must commit together'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cost_freeze_request_guard BEFORE INSERT ON cehub_cost.cost_freeze_requests
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_freeze_request();
CREATE TRIGGER cost_freeze_decision_guard BEFORE INSERT ON cehub_cost.cost_freeze_decisions
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_freeze_decision();
CREATE TRIGGER cost_freeze_guard BEFORE INSERT ON cehub_cost.cost_freezes
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_freeze();
CREATE CONSTRAINT TRIGGER cost_freeze_atomic AFTER INSERT ON cehub_cost.cost_freeze_decisions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION cehub_cost.require_approved_cost_freeze();
CREATE TRIGGER cost_freeze_request_immutable BEFORE UPDATE OR DELETE
ON cehub_cost.cost_freeze_requests FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER cost_freeze_decision_immutable BEFORE UPDATE OR DELETE
ON cehub_cost.cost_freeze_decisions FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
CREATE TRIGGER cost_freeze_immutable BEFORE UPDATE OR DELETE ON cehub_cost.cost_freezes
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
REVOKE ALL ON cehub_cost.cost_freeze_requests, cehub_cost.cost_freeze_decisions,
cehub_cost.cost_freezes FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_cost.guard_cost_freeze_request(),
cehub_cost.guard_cost_freeze_decision(), cehub_cost.guard_cost_freeze(),
cehub_cost.require_approved_cost_freeze() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
     IF EXISTS(SELECT 1 FROM cehub_cost.cost_freeze_requests) THEN
      RAISE EXCEPTION 'Retain cost approval and frozen version history'; END IF;
    END $$;
    ALTER TABLE cehub_cost.cost_freeze_requests DROP CONSTRAINT fk_cfr_previous;
    DROP TABLE cehub_cost.cost_freezes;
    DROP TABLE cehub_cost.cost_freeze_decisions;
    DROP TABLE cehub_cost.cost_freeze_requests;
    DROP FUNCTION cehub_cost.require_approved_cost_freeze();
    DROP FUNCTION cehub_cost.guard_cost_freeze();
    DROP FUNCTION cehub_cost.guard_cost_freeze_decision();
    DROP FUNCTION cehub_cost.guard_cost_freeze_request();
    """)
