"""Historical pre-S0 schema proposal, retained only for structural comparison.

It never executes SQL. Active schema and repaired guards are owned by the
s0 Alembic chain, including s0_0424; old caps and aggregate TTLs below are
superseded and must not be installed as a new runtime contract.
"""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import BaselineDocumentLink, PreparationCurrent, PreparationVersion

TABLES = (
    PreparationVersion.__table__,
    PreparationCurrent.__table__,
    BaselineDocumentLink.__table__,
)


def create_tables():
    dialect = postgresql.dialect()
    statements = [str(CreateTable(t).compile(dialect=dialect)) for t in TABLES]
    statements.extend(
        str(CreateIndex(i).compile(dialect=dialect)) for t in TABLES for i in t.indexes
    )
    return tuple(statements)


def permissions():
    statements = []
    for table in TABLES:
        name = table.name
        statements.extend(
            (
                f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY tenant_scope ON "{name}" USING '
                "(tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid) WITH CHECK "
                "(tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid)",
                f'REVOKE ALL ON "{name}" FROM PUBLIC,pdos_next_app,pdos_agent',
                f'GRANT SELECT,INSERT ON "{name}" TO pdos_next_app',
            )
        )
    statements.append(
        'GRANT UPDATE(version_id,revision) ON "manufacturing_preparation_currents" TO pdos_next_app'
    )
    for signature in (
        "assert_manufacturing_preparation_members(uuid,uuid)",
        "require_manufacturing_preparation_member()",
        "protect_manufacturing_preparation_member()",
        "protect_manufacturing_preparation_proof()",
        "require_manufacturing_preparation_transition()",
        "assert_manufacturing_preparation_atom(uuid,uuid)",
        "require_manufacturing_preparation_atom()",
        "require_manufacturing_preparation_receipt()",
        "require_manufacturing_preparation_child()",
        "protect_manufacturing_preparation_current()",
        "reject_manufacturing_preparation_mutation()",
    ):
        statements.extend(
            (
                f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,pdos_agent",
                f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_app",
            )
        )
    return tuple(statements)


# Python sorted JSON digest is NOT reconstructed using jsonb::text. These
# comparisons bind full real review/semantic/body/source/authority material;
# material/token/read_set hashes remain actual host-consumer markers.
GUARDS = r"""
CREATE FUNCTION protect_manufacturing_preparation_proof() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_scoped boolean; new_scoped boolean;
BEGIN
 IF TG_OP='DELETE' THEN
   IF OLD.operation IN ('npi.work_instruction.record','npi.control_plan.record',
'npi.manufacturing_baseline.record') THEN
     RAISE EXCEPTION 'Preparation proof history is retained'; END IF;
   RETURN OLD;
 END IF;
 new_scoped := NEW.operation IN ('npi.work_instruction.record', 'npi.control_plan.record',
'npi.manufacturing_baseline.record');
 IF TG_OP='INSERT' THEN
   IF new_scoped AND NEW.consumed IS DISTINCT FROM false THEN
     RAISE EXCEPTION 'Manufacturing preparation proof must begin unconsumed'; END IF;
   RETURN NEW;
 END IF;
 old_scoped := OLD.operation IN ('npi.work_instruction.record', 'npi.control_plan.record',
'npi.manufacturing_baseline.record');
 IF NOT (old_scoped OR new_scoped) THEN RETURN NEW; END IF;
 IF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false
    OR NEW.consumed IS DISTINCT FROM true
    OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Preparation proof permits only original false to true'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION require_manufacturing_preparation_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE used integer;
BEGIN
 IF NEW.operation NOT IN ('npi.work_instruction.record', 'npi.control_plan.record',
'npi.manufacturing_baseline.record')
   THEN RETURN NULL; END IF;
 IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'Preparation target requires actual transition'; END IF;
 SELECT count(*) INTO used FROM manufacturing_preparation_versions v
 WHERE v.tenant_id=NEW.tenant_id AND v.shared_proof_id=NEW.id;
 IF used<>1 THEN RAISE EXCEPTION 'One transitioned preparation proof requires one new target';
END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION assert_manufacturing_preparation_atom(t uuid, target uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v manufacturing_preparation_versions%ROWTYPE;
 c confirmations%ROWTYPE; r action_receipts%ROWTYPE; n integer; expected_event text;
BEGIN
 SELECT * INTO STRICT v FROM manufacturing_preparation_versions WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT c FROM confirmations WHERE tenant_id=t AND id=v.shared_proof_id;
 SELECT count(*) INTO n FROM manufacturing_preparation_versions WHERE tenant_id=t AND
shared_proof_id=c.id;
 IF n<>1 OR c.consumed IS DISTINCT FROM true
    OR ROW(c.product_id,c.actor_id,c.subject_id,c.operation,c.revision)
       IS DISTINCT FROM
ROW(v.product_id,v.owner_id,v.product_id,v.operation,v.shared_proof_revision)
    OR c.token_hash IS DISTINCT FROM v.token_sha256 OR c.payload_digest IS DISTINCT FROM
v.material_sha256
    OR c.snapshot IS DISTINCT FROM v.review OR c.expires_at IS DISTINCT FROM v.proof_expires_at
    OR NOT(c.created_at<=v.proof_consumed_at AND v.proof_consumed_at<=v.created_at AND
v.created_at<c.expires_at)
    OR (SELECT revision FROM products WHERE tenant_id=t AND id=v.product_id) IS DISTINCT FROM
c.revision
    OR v.shared_proof_revision IS DISTINCT FROM c.revision
    OR v.review->>'operation' IS DISTINCT FROM v.operation
    OR v.review->'after'->>'revision' IS DISTINCT FROM v.revision::text
    OR jsonb_typeof(v.review->'after'->'revision') IS DISTINCT FROM 'number'
    OR v.review->'after'->>'status' IS DISTINCT FROM 'draft'
    OR v.input_snapshot->'command'->>'operation' IS DISTINCT FROM v.operation
    OR v.input_snapshot->'command'->>'product_id' IS DISTINCT FROM v.product_id::text
    OR v.input_snapshot->'command'->>'expected_revision' IS DISTINCT FROM c.revision::text
    OR v.input_snapshot->'command'->'payload' IS DISTINCT FROM v.input_snapshot->'semantic'
    OR v.body->'input'->'sources' IS NULL
    OR jsonb_typeof(v.sources) IS DISTINCT FROM 'array'
    OR jsonb_typeof(v.required_source_read_set) IS DISTINCT FROM 'array'
    OR jsonb_array_length(v.required_source_read_set)>20
    OR v.body->>'kind' IS DISTINCT FROM v.kind
    OR v.review->'after'->'body' IS DISTINCT FROM v.body
    OR v.review->'authority' IS DISTINCT FROM v.authority_snapshot
    OR v.review->'read_basis' IS DISTINCT FROM v.source_basis
    OR v.review->'required_source_read_set' IS DISTINCT FROM v.required_source_read_set
    OR v.body->'input' IS DISTINCT FROM v.input_snapshot->'semantic'
    OR v.body->'scope'->>'purpose' IS DISTINCT FROM v.purpose
    OR (SELECT purpose FROM projects WHERE tenant_id=t AND product_id=v.product_id AND
id=v.project_id) IS DISTINCT FROM v.purpose
    OR v.body->'input'->>'project_id' IS DISTINCT FROM v.project_id::text
    OR v.body->'input'->'process' IS DISTINCT FROM
jsonb_build_object('id',v.process_id,'revision',v.process_revision)
    OR v.body->>'status' IS DISTINCT FROM 'draft'
    OR v.body->'input'->>'visibility' IS DISTINCT FROM v.visibility
    OR v.body->'input'->>'title' IS DISTINCT FROM v.title
    OR v.authority_snapshot->>'valid_until' IS NULL
    OR (v.authority_snapshot->>'valid_until')::timestamptz<=v.created_at
    OR v.authority_snapshot->>'subject_id' IS DISTINCT FROM v.owner_id::text
    OR v.authority_snapshot->>'operation' IS DISTINCT FROM v.operation
    OR v.authority_snapshot->>'purpose' IS DISTINCT FROM v.purpose
    OR v.authority_snapshot->'scope' IS DISTINCT FROM
jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)
    OR v.authority_snapshot->'authorized' IS DISTINCT FROM 'true'::jsonb
    OR v.authority_snapshot->'qualified' IS DISTINCT FROM 'true'::jsonb
    OR NOT(v.authority_snapshot->'roles' @> '["manufacturing"]'::jsonb)
    OR NOT EXISTS(SELECT 1 FROM principals actor WHERE actor.tenant_id=t AND actor.id=v.owner_id
       AND actor.kind='human' AND actor.active IS TRUE) THEN
   RAISE EXCEPTION 'Preparation original proof, scope and actual material mismatch'; END IF;
 IF NOT EXISTS(SELECT 1 FROM process_revisions p
   JOIN engineering_configurations e ON e.tenant_id=p.tenant_id AND e.product_id=p.product_id
      AND e.id=p.engineering_configuration_id AND e.revision=p.engineering_revision
   JOIN project_product_links l ON l.tenant_id=p.tenant_id AND l.product_id=p.product_id AND
l.project_id=v.project_id
   WHERE p.tenant_id=t AND p.product_id=v.product_id AND p.id=v.process_id AND
p.revision=v.process_revision
     AND e.definition_id=l.definition_id AND e.definition_revision=l.definition_revision
     AND (v.visibility='private' OR (p.visibility='category' AND e.visibility='category'))
     AND p.operations IS NOT DISTINCT FROM v.body->'process_snapshot'->'operations') THEN
   RAISE EXCEPTION 'Preparation actual process/engineering/project binding mismatch'; END IF;
 IF v.kind<>'manufacturing_baseline' THEN
   IF v.body->'input'->>'operation_key' IS DISTINCT FROM v.operation_key OR NOT EXISTS(
     SELECT 1 FROM process_revisions p, LATERAL jsonb_array_elements(p.operations) op
     WHERE p.tenant_id=t AND p.id=v.process_id AND op->>'key'=v.operation_key) THEN
     RAISE EXCEPTION 'Preparation operation is not in fixed process'; END IF;
 ELSE
   IF (SELECT count(*) FROM jsonb_array_elements(v.body->'input'->'operations'))
       <> (SELECT jsonb_array_length(operations) FROM process_revisions WHERE tenant_id=t AND
id=v.process_id)
      OR EXISTS(SELECT 1 FROM process_revisions p, LATERAL jsonb_array_elements(p.operations) op
         WHERE p.tenant_id=t AND p.id=v.process_id AND
           (SELECT count(*) FROM jsonb_array_elements(v.body->'input'->'operations') x
             WHERE x->>'operation_key'=op->>'key')<>1)
      OR EXISTS(SELECT 1 FROM manufacturing_baseline_document_links d
         JOIN manufacturing_preparation_versions child ON child.tenant_id=d.tenant_id AND
child.id=d.document_id
         WHERE d.tenant_id=t AND d.baseline_id=v.id AND
           (d.project_id<>v.project_id OR d.process_id<>v.process_id OR
d.process_revision<>v.process_revision
            OR d.baseline_revision<>v.revision OR child.kind<>d.document_kind OR
child.revision<>d.document_revision
            OR child.operation_key<>d.operation_key OR child.purpose<>v.purpose
            OR (v.visibility='category' AND child.visibility<>'product')
            OR NOT EXISTS(SELECT 1 FROM manufacturing_preparation_currents cur
                 WHERE cur.tenant_id=t AND cur.version_id=child.id AND
cur.revision=child.revision)))
      OR (SELECT count(*) FROM manufacturing_baseline_document_links d WHERE d.tenant_id=t AND
d.baseline_id=v.id)
         <> (SELECT count(*) FROM jsonb_array_elements(v.body->'input'->'operations') op
              CROSS JOIN (VALUES ('work_instruction'),('control_plan')) AS kinds(name)
              WHERE op->kinds.name IS NOT NULL AND op->kinds.name<>'null'::jsonb)
      OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.body->'input'->'operations') op
           CROSS JOIN (VALUES ('work_instruction'),('control_plan')) AS kinds(name)
           WHERE op->kinds.name IS NOT NULL AND op->kinds.name<>'null'::jsonb AND NOT EXISTS(
              SELECT 1 FROM manufacturing_baseline_document_links d WHERE d.tenant_id=t AND
d.baseline_id=v.id
                AND d.operation_key=op->>'operation_key' AND d.document_kind=kinds.name
                AND d.document_id::text=op->kinds.name->>'id'
                AND d.document_revision::text=op->kinds.name->>'revision')) THEN
     RAISE EXCEPTION 'Baseline exact whole process and fixed child set mismatch'; END IF;
 END IF;
 IF v.body->'input'->>'previous_id' IS DISTINCT FROM v.previous_id::text
 OR v.body->'input'->>'expected_previous_revision' IS DISTINCT FROM v.previous_revision::text
 OR (v.previous_id IS NULL AND v.review->'before' IS DISTINCT FROM 'null'::jsonb)
 OR (v.previous_id IS NOT NULL AND (v.review->'before'->>'id' IS DISTINCT FROM v.previous_id::text
 OR v.review->'before'->>'revision' IS DISTINCT FROM v.previous_revision::text)) THEN
   RAISE EXCEPTION 'Preparation previous semantic and actual before material mismatch'; END IF;
 IF v.previous_id IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM manufacturing_preparation_versions p WHERE p.tenant_id=t AND p.id=v.previous_id
    AND p.series_id=v.series_id AND p.project_id=v.project_id AND p.product_id=v.product_id
    AND p.kind=v.kind AND p.owner_id=v.owner_id AND p.visibility=v.visibility AND
p.purpose=v.purpose
    AND p.revision=v.previous_revision AND v.revision=p.revision+1
    AND p.operation_key IS NOT DISTINCT FROM v.operation_key
    AND EXISTS(SELECT 1 FROM process_revisions old_process, process_revisions new_process
      WHERE old_process.tenant_id=t AND new_process.tenant_id=t
        AND old_process.product_id=v.product_id AND new_process.product_id=v.product_id
        AND old_process.id=p.process_id AND old_process.revision=p.process_revision
        AND new_process.id=v.process_id AND new_process.revision=v.process_revision
        AND old_process.series_id=new_process.series_id)) THEN
   RAISE EXCEPTION 'Preparation predecessor full series scope mismatch'; END IF;
 IF NOT EXISTS(SELECT 1 FROM manufacturing_preparation_currents p WHERE p.tenant_id=t
    AND p.product_id=v.product_id AND p.project_id=v.project_id AND p.kind=v.kind AND
p.series_id=v.series_id
    AND p.owner_id=v.owner_id AND p.visibility=v.visibility AND p.version_id=v.id AND
p.revision=v.revision) THEN
   RAISE EXCEPTION 'New preparation requires exact Current'; END IF;
 SELECT count(*) INTO n FROM action_receipts WHERE tenant_id=t AND product_id=v.product_id
   AND subject_type=v.kind AND subject_id=v.id AND subject_revision=v.revision;
 IF n<>1 THEN RAISE EXCEPTION 'Preparation requires one common receipt'; END IF;
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=t AND product_id=v.product_id
   AND subject_type=v.kind AND subject_id=v.id AND subject_revision=v.revision;
 expected_event := CASE v.operation WHEN 'npi.work_instruction.record' THEN
'work_instruction.recorded'
   WHEN 'npi.control_plan.record' THEN 'control_plan.recorded' ELSE
'manufacturing_baseline.recorded' END;
 IF ROW(r.actor_id,r.requester_id,r.visibility,r.operation,r.intent_digest,r.request_digest)
     IS DISTINCT FROM
ROW(v.owner_id,v.owner_id,v.visibility,v.operation,v.intent_digest,v.input_snapshot->>'request_digest')
    OR r.run_id IS NOT NULL OR r.result->>'id' IS DISTINCT FROM v.id::text
    OR r.result->>'revision' IS DISTINCT FROM v.revision::text OR r.result->>'status' IS
DISTINCT FROM 'draft'
    OR jsonb_typeof(r.result->'revision') IS DISTINCT FROM 'number'
    OR r.command_id::text IS DISTINCT FROM v.input_snapshot->'command'->>'command_id'
    OR (SELECT count(*) FROM audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id)<>1
    OR (SELECT count(*) FROM outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id)<>1
    OR (SELECT count(*) FROM audit_entries a WHERE a.tenant_id=t AND a.receipt_id=r.id
         AND a.actor_id=v.owner_id AND a.operation=v.operation)<>1
    OR (SELECT count(*) FROM outbox_events e WHERE e.tenant_id=t AND e.receipt_id=r.id
         AND e.type=expected_event AND e.actor_id=v.owner_id AND e.subject_id=v.id
         AND e.subject_revision=v.revision AND e.correlation_id=r.command_id)<>1
    OR (SELECT count(*) FROM request_keys k WHERE k.tenant_id=t AND k.receipt_id=r.id
         AND k.actor_id=v.owner_id AND k.key=v.input_snapshot->'command'->>'idempotency_key'
         AND k.digest=r.request_digest)<>1 THEN
   RAISE EXCEPTION 'Preparation receipt/audit/outbox/original request mismatch'; END IF;
END $$;
CREATE FUNCTION require_manufacturing_preparation_atom() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 PERFORM assert_manufacturing_preparation_atom(NEW.tenant_id,NEW.id); RETURN NULL;
END $$;
CREATE FUNCTION require_manufacturing_preparation_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF NEW.operation IN ('npi.work_instruction.record', 'npi.control_plan.record',
'npi.manufacturing_baseline.record') OR NEW.subject_type IN
('work_instruction','control_plan','manufacturing_baseline') THEN
   PERFORM assert_manufacturing_preparation_atom(NEW.tenant_id,NEW.subject_id); END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION require_manufacturing_preparation_child() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 PERFORM assert_manufacturing_preparation_atom(NEW.tenant_id,NEW.baseline_id); RETURN NULL;
END $$;
CREATE FUNCTION protect_manufacturing_preparation_current() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF (to_jsonb(NEW)-ARRAY['version_id', 'revision']) IS DISTINCT FROM
(to_jsonb(OLD)-ARRAY['version_id', 'revision'])
    OR NEW.revision<>OLD.revision+1 OR NOT EXISTS(SELECT 1 FROM
manufacturing_preparation_versions v
      WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.version_id AND v.revision=NEW.revision
        AND v.previous_id=OLD.version_id AND v.previous_revision=OLD.revision) THEN
   RAISE EXCEPTION 'Preparation Current only advances one exact successor'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION reject_manufacturing_preparation_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Manufacturing preparation is immutable'; END $$;
CREATE TRIGGER manufacturing_preparation_proof_guard BEFORE INSERT OR UPDATE OR DELETE
 ON confirmations
 FOR EACH ROW EXECUTE FUNCTION protect_manufacturing_preparation_proof();
CREATE CONSTRAINT TRIGGER manufacturing_preparation_proof_target AFTER UPDATE ON confirmations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
require_manufacturing_preparation_transition();
CREATE CONSTRAINT TRIGGER manufacturing_preparation_atom AFTER INSERT ON
manufacturing_preparation_versions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
require_manufacturing_preparation_atom();
CREATE CONSTRAINT TRIGGER manufacturing_preparation_receipt AFTER INSERT ON action_receipts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
require_manufacturing_preparation_receipt();
CREATE CONSTRAINT TRIGGER manufacturing_preparation_child_atom AFTER INSERT ON
manufacturing_baseline_document_links
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
require_manufacturing_preparation_child();
CREATE TRIGGER manufacturing_preparation_current_guard BEFORE UPDATE ON
manufacturing_preparation_currents
 FOR EACH ROW EXECUTE FUNCTION protect_manufacturing_preparation_current();
CREATE TRIGGER manufacturing_preparation_immutable BEFORE UPDATE OR DELETE ON
manufacturing_preparation_versions
 FOR EACH ROW EXECUTE FUNCTION reject_manufacturing_preparation_mutation();
CREATE TRIGGER manufacturing_preparation_child_immutable BEFORE UPDATE OR DELETE ON
manufacturing_baseline_document_links
 FOR EACH ROW EXECUTE FUNCTION reject_manufacturing_preparation_mutation();
CREATE TRIGGER manufacturing_preparation_current_delete BEFORE DELETE ON
manufacturing_preparation_currents
 FOR EACH ROW EXECUTE FUNCTION reject_manufacturing_preparation_mutation();
"""


MEMBER_GUARDS = r"""
CREATE FUNCTION assert_manufacturing_preparation_members(t uuid, target uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v manufacturing_preparation_versions%ROWTYPE; r action_receipts%ROWTYPE;
 n integer; expected_event text;
BEGIN
 SELECT * INTO STRICT v FROM manufacturing_preparation_versions WHERE tenant_id=t AND id=target;
 SELECT count(*) INTO n FROM action_receipts WHERE tenant_id=t AND product_id=v.product_id
 AND subject_type=v.kind AND subject_id=v.id AND subject_revision=v.revision;
 IF n<>1 THEN RAISE EXCEPTION 'Preparation retained group requires one receipt'; END IF;
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=t AND product_id=v.product_id
 AND subject_type=v.kind AND subject_id=v.id AND subject_revision=v.revision;
 expected_event := CASE v.operation WHEN 'npi.work_instruction.record' THEN
 'work_instruction.recorded' WHEN 'npi.control_plan.record' THEN 'control_plan.recorded'
 ELSE 'manufacturing_baseline.recorded' END;
 IF ROW(r.operation,r.actor_id,r.requester_id,r.visibility,r.intent_digest,r.request_digest)
 IS DISTINCT FROM ROW(v.operation,v.owner_id,v.owner_id,v.visibility,v.intent_digest,
 v.input_snapshot->>'request_digest') OR r.run_id IS NOT NULL
 OR (SELECT count(*) FROM audit_entries WHERE tenant_id=t AND receipt_id=r.id)<>1
 OR (SELECT count(*) FROM audit_entries WHERE tenant_id=t AND receipt_id=r.id
 AND actor_id=v.owner_id AND operation=v.operation)<>1
 OR (SELECT count(*) FROM outbox_events WHERE tenant_id=t AND receipt_id=r.id)<>1
 OR (SELECT count(*) FROM outbox_events WHERE tenant_id=t AND receipt_id=r.id
 AND actor_id=v.owner_id AND type=expected_event AND subject_id=v.id
 AND subject_revision=v.revision AND correlation_id=r.command_id)<>1
 OR (SELECT count(*) FROM request_keys WHERE tenant_id=t AND receipt_id=r.id
 AND actor_id=v.owner_id AND key=v.input_snapshot->'command'->>'idempotency_key'
 AND digest=r.request_digest)<>1 THEN
 RAISE EXCEPTION 'Preparation retained audit/outbox/original key group mismatch'; END IF;
END $$;
CREATE FUNCTION require_manufacturing_preparation_member() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r action_receipts%ROWTYPE;
BEGIN
 SELECT * INTO r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF FOUND AND (r.operation IN ('npi.work_instruction.record','npi.control_plan.record',
 'npi.manufacturing_baseline.record') OR r.subject_type IN
 ('work_instruction','control_plan','manufacturing_baseline')) THEN
 PERFORM assert_manufacturing_preparation_members(NEW.tenant_id,r.subject_id); END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION protect_manufacturing_preparation_member() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE n jsonb; o jsonb; scoped boolean; old_scoped boolean;
BEGIN
 IF TG_OP<>'DELETE' THEN n=to_jsonb(NEW); END IF;
 IF TG_OP<>'INSERT' THEN o=to_jsonb(OLD); END IF;
 SELECT EXISTS(SELECT 1 FROM action_receipts WHERE tenant_id=(n->>'tenant_id')::uuid
 AND id=(n->>'receipt_id')::uuid AND (operation IN
 ('npi.work_instruction.record','npi.control_plan.record','npi.manufacturing_baseline.record')
 OR subject_type IN ('work_instruction','control_plan','manufacturing_baseline'))) INTO scoped;
 SELECT EXISTS(SELECT 1 FROM action_receipts WHERE tenant_id=(o->>'tenant_id')::uuid
 AND id=(o->>'receipt_id')::uuid AND (operation IN
 ('npi.work_instruction.record','npi.control_plan.record','npi.manufacturing_baseline.record')
 OR subject_type IN ('work_instruction','control_plan','manufacturing_baseline')))
 INTO old_scoped;
 IF TG_OP='INSERT' OR NOT(scoped OR old_scoped) THEN
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF; END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Preparation common history is retained'; END IF;
 IF TG_TABLE_NAME='outbox_events' THEN
 IF (n-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error'])
 IS DISTINCT FROM (o-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN
 RAISE EXCEPTION 'Only delivery state may update preparation Outbox'; END IF;
 ELSE
 RAISE EXCEPTION 'Preparation Audit/RequestKey is immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER manufacturing_preparation_audit_guard BEFORE INSERT OR UPDATE OR DELETE
 ON audit_entries FOR EACH ROW EXECUTE FUNCTION protect_manufacturing_preparation_member();
CREATE TRIGGER manufacturing_preparation_outbox_guard BEFORE INSERT OR UPDATE OR DELETE
 ON outbox_events FOR EACH ROW EXECUTE FUNCTION protect_manufacturing_preparation_member();
CREATE TRIGGER manufacturing_preparation_request_guard BEFORE INSERT OR UPDATE OR DELETE
 ON request_keys FOR EACH ROW EXECUTE FUNCTION protect_manufacturing_preparation_member();
CREATE CONSTRAINT TRIGGER manufacturing_preparation_audit_atom AFTER INSERT ON audit_entries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
 require_manufacturing_preparation_member();
CREATE CONSTRAINT TRIGGER manufacturing_preparation_outbox_atom AFTER INSERT ON outbox_events
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
 require_manufacturing_preparation_member();
CREATE CONSTRAINT TRIGGER manufacturing_preparation_request_atom AFTER INSERT ON request_keys
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
 require_manufacturing_preparation_member();
"""


def lifecycle_triggers():
    return tuple(
        f'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON "{t.name}" '
        "FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()"
        for t in TABLES
    )


def proposed_sql():
    # Guard SQL still needs Root's exact operation/catalog/atom-tail composition.
    return (*create_tables(), GUARDS, MEMBER_GUARDS, *lifecycle_triggers(), *permissions())
