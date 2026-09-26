"""Atomic portfolio baseline and resource application with actual scoped receipts."""

from alembic import op

revision = "0340_portfolio_applications"
down_revision = "0339_portfolio_execution_preps"
branch_labels = None
depends_on = None

TABLES = (
    "portfolio_execution_applications",
    "portfolio_execution_applied_projects",
    "portfolio_execution_applied_reservations",
)

DDL = """
CREATE TABLE cehub_project.portfolio_execution_applications (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	preparation_id UUID NOT NULL, 
	selection_id UUID NOT NULL, 
	plan JSONB NOT NULL, 
	plan_digest VARCHAR(64) NOT NULL, 
	reason TEXT NOT NULL, 
	actor_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	transaction_id BIGINT DEFAULT txid_current() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_portfolio_execution_applications PRIMARY KEY (id), 
	CONSTRAINT uq_portfolio_application_scope UNIQUE (tenant_id, id), 
	CONSTRAINT uq_portfolio_application_preparation UNIQUE (tenant_id, preparation_id), 
	CONSTRAINT uq_portfolio_application_selection UNIQUE (tenant_id, selection_id), 
	CONSTRAINT uq_portfolio_application_request UNIQUE (tenant_id, actor_user_id, request_id), 
        CONSTRAINT fk_portfolio_execution_applications_tenant_id_portfolio_c9d9 FOREIGN
KEY(tenant_id, preparation_id) REFERENCES cehub_project.portfolio_execution_preparations
(tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_portfolio_execution_applications_tenant_id_portfolio_9dd1 FOREIGN
KEY(tenant_id, selection_id) REFERENCES cehub_project.portfolio_selections (tenant_id, id) ON
DELETE RESTRICT,
        CONSTRAINT fk_portfolio_execution_applications_tenant_id_users FOREIGN KEY(tenant_id,
actor_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_portfolio_execution_applications_shape CHECK (jsonb_typeof(plan)='object'
AND plan_digest ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$')
);
CREATE TABLE cehub_project.portfolio_execution_applied_projects (
	tenant_id UUID NOT NULL, 
	application_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	preparation_id UUID NOT NULL, 
	baseline_application_id UUID NOT NULL, 
	receipt JSONB NOT NULL, 
        CONSTRAINT pk_portfolio_execution_applied_projects PRIMARY KEY (tenant_id,
application_id, project_id),
        CONSTRAINT fk_portfolio_execution_applied_projects_tenant_id_portf_4beb FOREIGN
KEY(tenant_id, application_id) REFERENCES cehub_project.portfolio_execution_applications
(tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_portfolio_execution_applied_projects_tenant_id_portf_f109 FOREIGN
KEY(tenant_id, preparation_id, project_id) REFERENCES cehub_project.portfolio_execution_projects
(tenant_id, preparation_id, project_id) ON DELETE RESTRICT,
        CONSTRAINT fk_portfolio_execution_applied_projects_tenant_id_basel_8c54 FOREIGN
KEY(tenant_id, project_id, baseline_application_id) REFERENCES
cehub_project.baseline_change_applications (tenant_id, project_id, id) ON DELETE RESTRICT
);
CREATE TABLE cehub_project.portfolio_execution_applied_reservations (
	tenant_id UUID NOT NULL, 
	application_id UUID NOT NULL, 
	key VARCHAR(128) NOT NULL, 
	project_id UUID NOT NULL, 
	reservation_id UUID NOT NULL, 
	reservation_receipt_id UUID NOT NULL, 
	disposition VARCHAR(24) NOT NULL, 
	snapshot JSONB NOT NULL, 
        CONSTRAINT pk_portfolio_execution_applied_reservations PRIMARY KEY (tenant_id,
application_id, key),
	CONSTRAINT uq_portfolio_applied_reservation UNIQUE (tenant_id, application_id, reservation_id), 
        CONSTRAINT fk_portfolio_execution_applied_reservations_tenant_id_p_02b9 FOREIGN
KEY(tenant_id, application_id, project_id) REFERENCES
cehub_project.portfolio_execution_applied_projects (tenant_id, application_id, project_id) ON
DELETE RESTRICT,
        CONSTRAINT fk_portfolio_execution_applied_reservations_tenant_id_r_f9d9 FOREIGN
KEY(tenant_id, project_id, reservation_id) REFERENCES cehub_project.resource_reservations
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_portfolio_execution_applied_reservations_shape CHECK (disposition IN
('created','confirmed_existing','preserved') AND jsonb_typeof(snapshot)='object'),
        CONSTRAINT fk_portfolio_execution_applied_reservations_reservation_2fb1 FOREIGN
KEY(reservation_receipt_id) REFERENCES cehub_project.resource_reservation_receipts (id) ON
DELETE RESTRICT
);
"""

GUARDS = """
CREATE FUNCTION cehub_project.guard_portfolio_application() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE package cehub_project.portfolio_execution_preparations%ROWTYPE;
 saved cehub_project.portfolio_selections%ROWTYPE;
BEGIN
 SELECT * INTO package FROM cehub_project.portfolio_execution_preparations
 WHERE tenant_id=NEW.tenant_id AND id=NEW.preparation_id;
 SELECT * INTO saved FROM cehub_project.portfolio_selections
 WHERE tenant_id=NEW.tenant_id AND id=NEW.selection_id FOR UPDATE;
 IF package.id IS NULL OR saved.id IS NULL OR package.selection_id IS DISTINCT FROM
NEW.selection_id
 OR NEW.transaction_id IS DISTINCT FROM txid_current()
 OR NEW.plan->>'ready' IS DISTINCT FROM 'true'
 OR NEW.plan->>'preparation_id' IS DISTINCT FROM NEW.preparation_id::text
 OR NEW.plan->>'selection_id' IS DISTINCT FROM NEW.selection_id::text
 OR NEW.plan->>'selection_digest' IS DISTINCT FROM saved.payload_digest
 OR EXISTS(SELECT 1 FROM cehub_project.portfolio_selection_decisions d
 WHERE d.tenant_id=NEW.tenant_id AND d.selection_id=NEW.selection_id AND d.action<>'approve')
 OR EXISTS(SELECT 1 FROM cehub_project.portfolio_execution_projects p
 WHERE p.tenant_id=NEW.tenant_id AND p.preparation_id=NEW.preparation_id AND (
 NOT EXISTS(SELECT 1 FROM cehub_project.portfolio_selection_decisions d
 WHERE d.tenant_id=p.tenant_id AND d.selection_id=p.selection_id AND d.project_id=p.project_id
 AND d.action='approve' AND d.payload_digest=saved.payload_digest)
 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.plan->'items') i
 WHERE i->>'project_id'=p.project_id::text AND i->>'change_id'=p.change_id::text
 AND i->>'change_digest'=p.change_digest)))
 OR jsonb_array_length(NEW.plan->'items') IS DISTINCT FROM (SELECT count(*)::integer
 FROM cehub_project.portfolio_execution_projects WHERE tenant_id=NEW.tenant_id AND
preparation_id=NEW.preparation_id)
 THEN RAISE EXCEPTION 'complete approved portfolio dispatch required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.guard_portfolio_applied_project() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE batch cehub_project.portfolio_execution_applications%ROWTYPE;
 original cehub_project.portfolio_execution_projects%ROWTYPE;
 actual cehub_project.baseline_change_applications%ROWTYPE;
 item jsonb;
BEGIN
 SELECT * INTO batch FROM cehub_project.portfolio_execution_applications
 WHERE tenant_id=NEW.tenant_id AND id=NEW.application_id;
 SELECT * INTO original FROM cehub_project.portfolio_execution_projects
 WHERE tenant_id=NEW.tenant_id AND preparation_id=NEW.preparation_id AND
project_id=NEW.project_id;
 SELECT * INTO actual FROM cehub_project.baseline_change_applications
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.baseline_application_id;
 SELECT i INTO item FROM jsonb_array_elements(batch.plan->'items') i WHERE
i->>'project_id'=NEW.project_id::text;
 IF batch.id IS NULL OR original.project_id IS NULL OR actual.id IS NULL OR item IS NULL
 OR batch.transaction_id IS DISTINCT FROM txid_current()
 OR NEW.preparation_id IS DISTINCT FROM batch.preparation_id
 OR actual.change_id IS DISTINCT FROM original.change_id
 OR actual.decision_id::text IS DISTINCT FROM item->'decision'->>'id'
 OR actual.actor_user_id IS DISTINCT FROM batch.actor_user_id
 OR NEW.receipt IS DISTINCT FROM (actual.receipt ||
jsonb_build_object('project_name',item->>'project_name'))
 THEN RAISE EXCEPTION 'exact real portfolio baseline receipt required'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.guard_portfolio_applied_reservation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE batch cehub_project.portfolio_execution_applications%ROWTYPE;
 actual cehub_project.resource_reservations%ROWTYPE;
 original cehub_project.resource_reservation_receipts%ROWTYPE;
 item jsonb; addition jsonb; draft jsonb;
BEGIN
 SELECT * INTO batch FROM cehub_project.portfolio_execution_applications
 WHERE tenant_id=NEW.tenant_id AND id=NEW.application_id;
 SELECT * INTO actual FROM cehub_project.resource_reservations
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.reservation_id;
 SELECT * INTO original FROM cehub_project.resource_reservation_receipts
 WHERE id=NEW.reservation_receipt_id AND tenant_id=NEW.tenant_id
 AND project_id=NEW.project_id AND reservation_id=NEW.reservation_id;
 SELECT i INTO item FROM jsonb_array_elements(batch.plan->'items') i WHERE
i->>'project_id'=NEW.project_id::text;
 IF batch.id IS NULL OR actual.id IS NULL OR original.id IS NULL OR item IS NULL
 OR batch.transaction_id IS DISTINCT FROM txid_current() OR actual.state<>'reserved'
 OR actual.contract->>'reservation_receipt_id' IS DISTINCT FROM NEW.reservation_receipt_id::text
 OR NEW.snapshot IS DISTINCT FROM original.snapshot
 THEN RAISE EXCEPTION 'real reserved resource receipt required'; END IF;
 IF NEW.disposition='preserved' THEN
   IF NEW.key IS DISTINCT FROM 'covered:'||NEW.reservation_id::text
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(item->'bookings'->'coverage') cv,
   jsonb_array_elements(cv->'reservations') r WHERE r->>'id'=NEW.reservation_id::text)
   THEN RAISE EXCEPTION 'original portfolio coverage required'; END IF;
 ELSE
   SELECT a INTO addition FROM jsonb_array_elements(item->'bookings'->'additions') a WHERE
a->>'key'=NEW.key;
   draft:=addition->'draft';
   IF addition IS NULL OR original.actor_user_id IS DISTINCT FROM batch.actor_user_id
   OR actual.node_id::text IS DISTINCT FROM draft->>'node_id'
   OR actual.capacity_version_id::text IS DISTINCT FROM draft->>'capacity_version_id'
   OR actual.window_start IS DISTINCT FROM (draft->>'window_start')::timestamptz
   OR actual.window_end IS DISTINCT FROM (draft->>'window_end')::timestamptz
   OR actual.parallel_units IS DISTINCT FROM (draft->>'parallel_units')::numeric
   OR actual.occupancy_policy IS DISTINCT FROM draft->>'occupancy_policy'
   OR actual.owner_user_id::text IS DISTINCT FROM addition->>'owner_user_id'
   OR (NEW.disposition='confirmed_existing' AND actual.id::text IS DISTINCT FROM
addition->>'existing_proposal_id')
   OR (NEW.disposition='created' AND addition->>'existing_proposal_id' IS NOT NULL)
   THEN RAISE EXCEPTION 'exact planned reservation required'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.require_portfolio_application_complete() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM cehub_project.portfolio_execution_projects p
 WHERE p.tenant_id=NEW.tenant_id AND p.preparation_id=NEW.preparation_id AND NOT EXISTS(
 SELECT 1 FROM cehub_project.portfolio_execution_applied_projects a
 WHERE a.tenant_id=p.tenant_id AND a.application_id=NEW.id AND a.project_id=p.project_id))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.plan->'items') i,
 jsonb_array_elements(i->'bookings'->'additions') a WHERE NOT EXISTS(
 SELECT 1 FROM cehub_project.portfolio_execution_applied_reservations r
 WHERE r.tenant_id=NEW.tenant_id AND r.application_id=NEW.id AND r.key=a->>'key'
 AND r.project_id::text=i->>'project_id' AND r.disposition<>'preserved'))
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.plan->'items') i,
 jsonb_array_elements(i->'bookings'->'coverage') cv, jsonb_array_elements(cv->'reservations') old
 WHERE NOT EXISTS(SELECT 1 FROM cehub_project.portfolio_execution_applied_reservations r
 WHERE r.tenant_id=NEW.tenant_id AND r.application_id=NEW.id AND r.key='covered:'||(old->>'id')
 AND r.project_id::text=i->>'project_id' AND r.disposition='preserved'))
 THEN RAISE EXCEPTION 'all portfolio effects must commit atomically'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION cehub_project.guard_applied_portfolio_selection() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM cehub_project.portfolio_selections
 WHERE tenant_id=NEW.tenant_id AND id=NEW.selection_id FOR UPDATE;
 IF EXISTS(SELECT 1 FROM cehub_project.portfolio_execution_applications
 WHERE tenant_id=NEW.tenant_id AND selection_id=NEW.selection_id)
 THEN RAISE EXCEPTION 'applied portfolio selection cannot be withdrawn or revised'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_portfolio_application BEFORE INSERT ON
cehub_project.portfolio_execution_applications
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_portfolio_application();
CREATE TRIGGER guard_portfolio_applied_project BEFORE INSERT ON
cehub_project.portfolio_execution_applied_projects
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_portfolio_applied_project();
CREATE TRIGGER guard_portfolio_applied_reservation BEFORE INSERT ON
cehub_project.portfolio_execution_applied_reservations
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_portfolio_applied_reservation();
CREATE CONSTRAINT TRIGGER require_portfolio_application_complete AFTER INSERT ON
cehub_project.portfolio_execution_applications
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
cehub_project.require_portfolio_application_complete();
CREATE TRIGGER guard_applied_portfolio_selection BEFORE INSERT ON
cehub_project.portfolio_selection_decisions
FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_applied_portfolio_selection();

CREATE OR REPLACE FUNCTION cehub_project.guard_portfolio_baseline_path() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE bound cehub_project.portfolio_execution_projects%ROWTYPE; actual_scenario uuid;
BEGIN
 IF TG_TABLE_NAME='baseline_change_decisions' THEN
   SELECT scenario_id INTO actual_scenario FROM cehub_project.baseline_change_requests
   WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.change_id;
 ELSE actual_scenario:=NEW.scenario_id;
 END IF;
 SELECT * INTO bound FROM cehub_project.portfolio_execution_projects
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND scenario_id=actual_scenario;
 IF bound.project_id IS NULL THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='baseline_change_applications' THEN
   IF NOT EXISTS(SELECT 1 FROM cehub_project.portfolio_execution_applications a,
   jsonb_array_elements(a.plan->'items') i
   WHERE a.tenant_id=NEW.tenant_id AND a.preparation_id=bound.preparation_id
   AND a.transaction_id=txid_current() AND a.actor_user_id=NEW.actor_user_id
   AND NEW.change_id=bound.change_id AND NEW.scenario_id=bound.scenario_id
   AND i->>'project_id'=NEW.project_id::text AND i->>'change_id'=NEW.change_id::text
   AND i->>'change_digest'=bound.change_digest
   AND i->'decision'->>'id'=NEW.decision_id::text)
   THEN RAISE EXCEPTION 'portfolio baseline requires current atomic dispatch'; END IF;
 ELSIF TG_TABLE_NAME='baseline_change_requests' THEN
   RAISE EXCEPTION 'portfolio execution scenario already has its fixed request';
 ELSIF NEW.action='approve' THEN
   PERFORM 1 FROM cehub_project.portfolio_selections
   WHERE tenant_id=NEW.tenant_id AND id=bound.selection_id FOR UPDATE;
   IF NEW.change_id IS DISTINCT FROM bound.change_id
   OR NEW.approved_payload_digest IS DISTINCT FROM bound.change_digest
   OR EXISTS(SELECT 1 FROM cehub_project.portfolio_selection_decisions
   WHERE tenant_id=NEW.tenant_id AND selection_id=bound.selection_id AND action<>'approve')
   THEN RAISE EXCEPTION 'portfolio selection no longer supports baseline approval'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""

PREVIOUS_PATH = """
CREATE OR REPLACE FUNCTION cehub_project.guard_portfolio_baseline_path() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE bound cehub_project.portfolio_execution_projects%ROWTYPE; actual_scenario uuid;
BEGIN
 IF TG_TABLE_NAME='baseline_change_decisions' THEN
   SELECT scenario_id INTO actual_scenario FROM cehub_project.baseline_change_requests
   WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.change_id;
 ELSE actual_scenario:=NEW.scenario_id;
 END IF;
 SELECT * INTO bound FROM cehub_project.portfolio_execution_projects
 WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND scenario_id=actual_scenario;
 IF bound.project_id IS NULL THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='baseline_change_applications' THEN
   RAISE EXCEPTION 'portfolio baseline requires independent batch application';
 ELSIF TG_TABLE_NAME='baseline_change_requests' THEN
   RAISE EXCEPTION 'portfolio execution scenario already has its fixed request';
 ELSIF NEW.action='approve' THEN
   PERFORM 1 FROM cehub_project.portfolio_selections
   WHERE tenant_id=NEW.tenant_id AND id=bound.selection_id FOR UPDATE;
   IF NEW.change_id IS DISTINCT FROM bound.change_id
   OR NEW.approved_payload_digest IS DISTINCT FROM bound.change_digest
   OR EXISTS(SELECT 1 FROM cehub_project.portfolio_selection_decisions
   WHERE tenant_id=NEW.tenant_id AND selection_id=bound.selection_id AND action<>'approve')
   THEN RAISE EXCEPTION 'portfolio selection no longer supports baseline approval'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARDS)
    for name in TABLES:
        op.execute(f"REVOKE ALL ON cehub_project.{name} FROM PUBLIC")
        op.execute(
            f"CREATE TRIGGER immutable_{name} BEFORE UPDATE OR DELETE "
            f"ON cehub_project.{name} FOR EACH ROW "
            "EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )


def downgrade() -> None:
    for name in TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_project.{name}) "
            "THEN RAISE EXCEPTION 'portfolio application history cannot be discarded'; "
            "END IF; END $$"
        )
    op.execute(PREVIOUS_PATH)
    op.execute(
        "DROP TRIGGER guard_applied_portfolio_selection "
        "ON cehub_project.portfolio_selection_decisions"
    )
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE cehub_project.{name}")
    for name in (
        "guard_portfolio_application",
        "guard_portfolio_applied_project",
        "guard_portfolio_applied_reservation",
        "require_portfolio_application_complete",
        "guard_applied_portfolio_selection",
    ):
        op.execute(f"DROP FUNCTION cehub_project.{name}()")
