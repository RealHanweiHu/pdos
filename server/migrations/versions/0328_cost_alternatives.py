"""Immutable cost alternative revisions and fixed professional ECR sources."""

from alembic import op

revision = "0328_cost_alternatives"
down_revision = "0327_cost_gaps"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_cost.cost_alternatives (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        root_id UUID NOT NULL,
        previous_id UUID,
        case_id UUID NOT NULL,
        observation_id UUID NOT NULL,
        proposal_rollup_id UUID,
        evidence_id UUID NOT NULL,
        revision_number INTEGER NOT NULL,
        title VARCHAR(256) NOT NULL,
        status VARCHAR(16) NOT NULL,
        payload JSONB NOT NULL,
        snapshot JSONB NOT NULL,
        created_by_user_id UUID NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT pk_cost_alternatives PRIMARY KEY (id),
        CONSTRAINT uq_cost_alternative_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_cost_alternative_version UNIQUE (tenant_id, root_id, revision_number),
        CONSTRAINT uq_cost_alternative_request UNIQUE (tenant_id, created_by_user_id, request_id),
        CONSTRAINT fk_cost_alternative_root FOREIGN KEY(tenant_id, project_id, root_id) REFERENCES
cehub_cost.cost_alternatives (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_alternative_previous FOREIGN KEY(tenant_id, project_id, previous_id)
REFERENCES cehub_cost.cost_alternatives (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_alternatives_tenant_id_cost_gap_cases FOREIGN KEY(tenant_id, project_id,
case_id) REFERENCES cehub_cost.cost_gap_cases (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_alternatives_tenant_id_cost_gap_observations FOREIGN KEY(tenant_id,
project_id, observation_id) REFERENCES cehub_cost.cost_gap_observations (tenant_id, project_id, id)
ON DELETE RESTRICT,
        CONSTRAINT fk_cost_alternatives_tenant_id_cost_rollups FOREIGN KEY(tenant_id, project_id,
proposal_rollup_id) REFERENCES cehub_cost.cost_rollups (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_cost_alternatives_tenant_id_documents FOREIGN KEY(tenant_id, project_id,
evidence_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_cost_alternatives_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_cost_alternatives_shape CHECK (revision_number>0 AND status IN
('proposed','withdrawn') AND btrim(title)<>'' AND request_digest ~ '^[a-f0-9]{64}$' AND
jsonb_typeof(snapshot)='object' AND jsonb_typeof(payload)='object')
)

;
CREATE INDEX ix_cost_alternative_case ON cehub_cost.cost_alternatives (tenant_id, project_id,
case_id, created_at, id);
"""

ROUTE = """

CREATE OR REPLACE FUNCTION cehub_product.guard_professional_change_route() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Professional change routing is immutable' USING
ERRCODE='23514'; END IF;
IF NOT EXISTS(SELECT 1 FROM cehub_product.engineering_change_requests WHERE
tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.ecr_id AND status IN ('request','impact_analysis'))
THEN
RAISE EXCEPTION 'Professional source requires an ECR awaiting analysis' USING ERRCODE='23514';
END IF;
IF (NEW.source_kind='engineering_review' AND NOT EXISTS(SELECT 1 FROM
cehub_product.engineering_review_packages
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_id))
OR (NEW.source_kind='firmware_package' AND NOT EXISTS(SELECT 1 FROM
cehub_product.firmware_work_packages
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_id))
OR (NEW.source_kind='cost_alternative' AND NOT EXISTS(SELECT 1 FROM
cehub_cost.cost_alternatives a
WHERE a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id AND a.id=NEW.source_id
AND a.status='proposed' AND NEW.snapshot->'source' @> jsonb_build_object(
'id',a.id,'root_id',a.root_id,'revision_number',a.revision_number,'snapshot',a.snapshot)
AND NOT EXISTS(SELECT 1 FROM cehub_cost.cost_alternatives newer WHERE
newer.tenant_id=a.tenant_id AND newer.root_id=a.root_id
AND newer.revision_number>a.revision_number))) THEN
RAISE EXCEPTION 'Professional source must belong to actual project' USING ERRCODE='23514'; END
IF;
RETURN NEW;
END $$
"""

OLD_ROUTE = """

CREATE OR REPLACE FUNCTION cehub_product.guard_professional_change_route() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Professional change routing is immutable' USING
ERRCODE='23514'; END IF;
IF NOT EXISTS(SELECT 1 FROM cehub_product.engineering_change_requests WHERE
tenant_id=NEW.tenant_id
AND project_id=NEW.project_id AND id=NEW.ecr_id AND status IN ('request','impact_analysis'))
THEN
RAISE EXCEPTION 'Professional source requires an ECR awaiting analysis' USING ERRCODE='23514';
END IF;
IF (NEW.source_kind='engineering_review' AND NOT EXISTS(SELECT 1 FROM
cehub_product.engineering_review_packages
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_id))
OR (NEW.source_kind='firmware_package' AND NOT EXISTS(SELECT 1 FROM
cehub_product.firmware_work_packages
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.source_id)) THEN
RAISE EXCEPTION 'Professional source must belong to actual project' USING ERRCODE='23514'; END
IF;
RETURN NEW;
END $$
"""

EXTEND = """
ALTER TABLE cehub_product.professional_change_routes DROP CONSTRAINT
ck_professional_change_routes_professional_change_shape; ALTER TABLE
cehub_product.professional_change_routes ADD CONSTRAINT
ck_professional_change_routes_professional_change_shape CHECK (source_kind IN
('engineering_review','firmware_package','cost_alternative') AND request_digest ~ '^[a-f0-9]{64}$'
AND jsonb_typeof(snapshot)='object' AND btrim(reason)<>'');
"""

RESTORE = """
ALTER TABLE cehub_product.professional_change_routes DROP CONSTRAINT
ck_professional_change_routes_professional_change_shape; ALTER TABLE
cehub_product.professional_change_routes ADD CONSTRAINT
ck_professional_change_routes_professional_change_shape CHECK (source_kind IN
('engineering_review','firmware_package') AND request_digest ~ '^[a-f0-9]{64}$' AND
jsonb_typeof(snapshot)='object' AND btrim(reason)<>'');
"""

GUARD = """
CREATE FUNCTION cehub_cost.guard_cost_alternative() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE prior cehub_cost.cost_alternatives; observation cehub_cost.cost_gap_observations;
 parent cehub_cost.cost_gap_cases; proposal cehub_cost.cost_rollups;
 document cehub_project.documents;
 command jsonb;
BEGIN
 PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id
 FOR UPDATE;
 SELECT * INTO prior FROM cehub_cost.cost_alternatives WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND root_id=NEW.root_id ORDER BY revision_number DESC LIMIT 1;
 IF prior.id IS NULL THEN
  IF NEW.previous_id IS NOT NULL OR NEW.root_id<>NEW.id OR NEW.revision_number<>1
   OR NEW.status<>'proposed' THEN RAISE EXCEPTION 'Invalid cost alternative origin'; END IF;
 ELSE
  IF NEW.previous_id IS DISTINCT FROM prior.id OR NEW.case_id<>prior.case_id
   OR NEW.revision_number<>prior.revision_number+1 THEN
   RAISE EXCEPTION 'Revise the latest cost alternative in its original case'; END IF;
 END IF;
 SELECT * INTO observation FROM cehub_cost.cost_gap_observations WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.observation_id;
 SELECT * INTO parent FROM cehub_cost.cost_gap_cases WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.case_id;
 SELECT * INTO document FROM cehub_project.documents WHERE tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND id=NEW.evidence_id;
 command:=NEW.payload->'draft';
 IF (observation.case_id=NEW.case_id AND observation.state<>'needs_review'
  AND command=NEW.snapshot->'command'
  AND NEW.snapshot->>'algorithm'='cost-alternative.v1'
  AND command->>'title'=NEW.title AND command->>'status'=NEW.status
  AND command->>'case_id'=NEW.case_id::text
  AND command->>'observation_id'=NEW.observation_id::text
  AND command->>'evidence_id'=NEW.evidence_id::text
  AND command->>'previous_id' IS NOT DISTINCT FROM NEW.previous_id::text
  AND command->>'proposal_rollup_id' IS NOT DISTINCT FROM NEW.proposal_rollup_id::text
  AND (NEW.snapshot->>'revision_number')::int=NEW.revision_number
  AND NEW.snapshot#>>'{case,id}'=parent.id::text
  AND NEW.snapshot#>'{case,snapshot}'=parent.snapshot
  AND NEW.snapshot#>>'{observation,id}'=observation.id::text
  AND NEW.snapshot#>'{observation,snapshot}'=observation.snapshot
  AND NEW.snapshot->'baseline_calculation'=observation.snapshot->'calculation'
  AND NEW.snapshot#>>'{evidence,id}'=document.id::text
  AND NEW.snapshot#>>'{evidence,sha256}'=document.sha256
  AND NEW.payload->>'checked'='true') IS NOT TRUE THEN
  RAISE EXCEPTION 'Cost alternative must retain its scoped observation and evidence'; END IF;
 IF NEW.proposal_rollup_id IS NOT NULL THEN
  SELECT * INTO proposal FROM cehub_cost.cost_rollups WHERE tenant_id=NEW.tenant_id
  AND project_id=NEW.project_id AND id=NEW.proposal_rollup_id;
  IF (proposal.command->>'stage' IN ('estimate','quote')
   AND NEW.snapshot#>>'{proposal_calculation,id}'=proposal.id::text
   AND NEW.snapshot#>'{proposal_calculation,command}'=proposal.command
   AND NEW.snapshot#>'{proposal_calculation,result}'=proposal.result
   AND NEW.snapshot#>'{proposal_calculation,snapshot}'=proposal.snapshot) IS NOT TRUE THEN
   RAISE EXCEPTION 'Expected alternative costs require the selected estimate or quote'; END IF;
 ELSE
  IF NEW.snapshot->'proposal_calculation' IS DISTINCT FROM 'null'::jsonb THEN
   RAISE EXCEPTION 'Missing alternative calculation cannot have synthetic costs'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER cost_alternative_guard BEFORE INSERT ON cehub_cost.cost_alternatives
FOR EACH ROW EXECUTE FUNCTION cehub_cost.guard_cost_alternative();
CREATE TRIGGER cost_alternative_immutable BEFORE UPDATE OR DELETE ON cehub_cost.cost_alternatives
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.material_ledger_immutable();
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)
    op.execute(EXTEND)
    op.execute(ROUTE)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
     IF EXISTS(SELECT 1 FROM cehub_cost.cost_alternatives) OR EXISTS(SELECT 1 FROM
      cehub_product.professional_change_routes WHERE source_kind='cost_alternative') THEN
      RAISE EXCEPTION 'Retain cost alternatives and their engineering change history'; END IF;
    END $$;
    """)
    op.execute(OLD_ROUTE)
    op.execute(RESTORE)
    op.execute("DROP TABLE cehub_cost.cost_alternatives")
    op.execute("DROP FUNCTION cehub_cost.guard_cost_alternative()")
