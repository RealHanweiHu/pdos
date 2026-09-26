"""Independent recovery review, immutable decisions and explicit return response."""

from alembic import op

revision = "0313_supplier_recovery_reviews"
down_revision = "0312_supplier_recovery_results"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.supplier_recovery_reviews (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
item_id UUID NOT NULL,
result_id UUID NOT NULL,
decision VARCHAR(24) NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
review JSONB NOT NULL,
snapshot JSONB NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_supplier_recovery_reviews PRIMARY KEY (id),
CONSTRAINT uq_supply_result_review_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_supply_result_review_once UNIQUE (result_id),
CONSTRAINT uq_supply_review_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_supplier_recovery_reviews_tenant_id_supplier_recovery_items FOREIGN KEY(tenant_id,
project_id, item_id) REFERENCES cehub_supplier.supplier_recovery_items (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_recovery_reviews_tenant_id_supplier_recover_954e FOREIGN KEY(tenant_id,
project_id, result_id) REFERENCES cehub_supplier.supplier_recovery_results (tenant_id,
project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_recovery_reviews_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supplier_recovery_reviews_shape CHECK (decision IN ('confirmed','returned') AND
request_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(review)='object' AND
jsonb_typeof(snapshot)='object')
)

;
ALTER TABLE cehub_supplier.supplier_recovery_results ADD COLUMN response_to_review_id uuid;
ALTER TABLE cehub_supplier.supplier_recovery_results ADD CONSTRAINT
fk_supplier_recovery_results_tenant_id_supplier_recover_ecde FOREIGN KEY(tenant_id, project_id,
response_to_review_id) REFERENCES cehub_supplier.supplier_recovery_reviews (tenant_id,
project_id, id) ON DELETE RESTRICT;
"""
GUARDS = """
CREATE FUNCTION cehub_supplier.guard_recovery_review() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE r cehub_supplier.supplier_recovery_results%ROWTYPE;
DECLARE owner_id uuid;
BEGIN
SELECT * INTO r FROM cehub_supplier.supplier_recovery_results
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.result_id;
SELECT t.assignee_user_id INTO owner_id FROM cehub_supplier.supplier_recovery_items i
JOIN cehub_project.tasks t ON t.tenant_id=i.tenant_id AND t.project_id=i.project_id
AND t.id=i.task_id WHERE i.tenant_id=NEW.tenant_id AND i.project_id=NEW.project_id
AND i.id=NEW.item_id;
IF r.id IS NULL OR r.item_id<>NEW.item_id OR r.created_by_user_id=NEW.created_by_user_id
OR owner_id=NEW.created_by_user_id
OR r.report->>'disposition' IS DISTINCT FROM 'ready_for_review'
OR EXISTS(SELECT 1 FROM cehub_supplier.supplier_recovery_results
WHERE item_id=NEW.item_id AND version>r.version)
OR NEW.review->>'decision' IS DISTINCT FROM NEW.decision
OR NEW.review->>'result_id' IS DISTINCT FROM r.id::text
OR NEW.review->>'request_id' IS DISTINCT FROM NEW.request_id::text
OR NEW.snapshot->'result'->'report' IS DISTINCT FROM r.report
OR NEW.snapshot->'result'->'source_snapshot' IS DISTINCT FROM r.source_snapshot
OR coalesce(btrim(NEW.review->>'reason'),'')=''
THEN RAISE EXCEPTION 'Independent review requires latest exact submitted result'
USING ERRCODE='23514'; END IF;
IF NEW.decision='returned' AND coalesce(btrim(NEW.review->>'follow_up'),'')='' THEN
RAISE EXCEPTION 'Return requires concrete follow-up' USING ERRCODE='23514'; END IF;
IF NEW.decision='confirmed' AND (
NEW.snapshot->'sources_current' IS DISTINCT FROM 'true'::jsonb
OR NEW.snapshot->'current_source'->'task'->>'assignee_user_id'
IS DISTINCT FROM owner_id::text
OR NEW.snapshot->'current_source'->'task'->>'status'='skipped'
OR (NEW.snapshot->'current_source'-'task') IS DISTINCT FROM (r.source_snapshot-'task')
OR (NEW.snapshot->'current_source'->'task'-'status'-'updated_at') IS DISTINCT FROM
(r.source_snapshot->'task'-'status'-'updated_at')
OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'current_source'->'targets') x
WHERE x->'ready' IS DISTINCT FROM 'true'::jsonb)
OR EXISTS(SELECT 1 FROM unnest(ARRAY['evidence_checked','verification_verified',
'criteria_verified','remaining_resolved']) k WHERE NEW.review->k IS DISTINCT FROM 'true'::jsonb)
) THEN RAISE EXCEPTION 'Confirmation requires unchanged evidence and explicit verification'
USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_recovery_review BEFORE INSERT ON cehub_supplier.supplier_recovery_reviews
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.guard_recovery_review();
CREATE TRIGGER protect_recovery_reviews BEFORE UPDATE OR DELETE ON
cehub_supplier.supplier_recovery_reviews FOR EACH ROW
EXECUTE FUNCTION cehub_ai.protect_checkpoint_history();

CREATE FUNCTION cehub_supplier.guard_recovery_return_response() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous uuid;
DECLARE returned uuid;
BEGIN
SELECT id INTO previous FROM cehub_supplier.supplier_recovery_results
WHERE item_id=NEW.item_id ORDER BY version DESC LIMIT 1;
SELECT id INTO returned FROM cehub_supplier.supplier_recovery_reviews
WHERE result_id=previous AND decision='returned';
IF NEW.response_to_review_id IS DISTINCT FROM returned OR
NEW.report->>'response_to_review_id' IS DISTINCT FROM NEW.response_to_review_id::text OR
(returned IS NOT NULL AND coalesce(btrim(NEW.report->>'review_response'),'')='') THEN
RAISE EXCEPTION 'New result must address exact prior return' USING ERRCODE='23514'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_recovery_return_response BEFORE INSERT ON
cehub_supplier.supplier_recovery_results FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.guard_recovery_return_response();
REVOKE ALL ON cehub_supplier.supplier_recovery_reviews FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.guard_recovery_review() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.guard_recovery_return_response() FROM PUBLIC;

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
IF EXISTS(SELECT 1 FROM cehub_supplier.supplier_recovery_reviews) THEN
RAISE EXCEPTION 'Independent recovery decisions require retention'; END IF;
END $$;
DROP TRIGGER guard_recovery_return_response ON cehub_supplier.supplier_recovery_results;
DROP FUNCTION cehub_supplier.guard_recovery_return_response();
ALTER TABLE cehub_supplier.supplier_recovery_results DROP COLUMN response_to_review_id;
DROP TABLE cehub_supplier.supplier_recovery_reviews;
DROP FUNCTION cehub_supplier.guard_recovery_review();
""")
