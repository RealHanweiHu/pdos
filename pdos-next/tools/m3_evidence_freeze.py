# ruff: noqa: E501, E402 -- frozen SQL literals and explicit local import path
"""Freeze 0733 from reviewed 0732 catalog and local metadata; never opens a database."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from pdos_next.domain.preproject.evidence_models import TABLES
from pdos_next.models import Base
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateColumn, CreateIndex, CreateTable

CAT = json.loads((ROOT / ".local/m3-evidence-catalog.json").read_text())
UP, DOWN = [], []
FUNCTIONS = []
DIALECT = postgresql.dialect()


def change(up, down):
    UP.append(up)
    DOWN.insert(0, down)


def function(sql, signature):
    UP.append(sql)
    name = signature.split("(")[0]
    prior = next((x["sql"] for x in CAT["functions"] if x["proname"] == name), None)
    DOWN.insert(0, prior if prior else f"DROP FUNCTION {signature}")
    FUNCTIONS.append(signature)


def policy_restore(row):
    sql = (
        f'CREATE POLICY "{row["policyname"]}" ON "{row["tablename"]}" '
        f"AS {row['permissive']} FOR {row['cmd']} TO " + ",".join(row["roles"])
    )
    if row["qual"] is not None:
        sql += " USING (" + row["qual"] + ")"
    if row["with_check"] is not None:
        sql += " WITH CHECK (" + row["with_check"] + ")"
    return sql


# Match ORM additions without evaluating any live database configuration.
for table_name in ("claims", "claim_consumptions"):
    table = Base.metadata.tables[table_name]
    old_columns = {x["column_name"]: x for x in CAT["columns"] if x["table_name"] == table_name}
    for column in table.columns:
        if column.name not in old_columns:
            change(
                f"ALTER TABLE {table_name} ADD COLUMN "
                + str(CreateColumn(column).compile(dialect=DIALECT)),
                f'ALTER TABLE {table_name} DROP COLUMN "{column.name}"',
            )
        elif column.nullable and old_columns[column.name]["is_nullable"] == "NO":
            change(
                f'ALTER TABLE {table_name} ALTER COLUMN "{column.name}" DROP NOT NULL',
                f'ALTER TABLE {table_name} ALTER COLUMN "{column.name}" SET NOT NULL',
            )

change(
    "ALTER TABLE definition_revisions ADD CONSTRAINT definition_category_identity UNIQUE(tenant_id,category_id,id)",
    "ALTER TABLE definition_revisions DROP CONSTRAINT definition_category_identity",
)
# Existing checks are replaced with the same physical names for exact rollback.
legacy_checks = {
    "claims_nature_check": "CHECK (nature IN ('observed','extracted','inferred'))",
    "claims_availability_check": "CHECK (availability IN ('known','unknown','conflicted'))",
    "claims_status_check": "CHECK (status IN ('active','reverted'))",
}
checks = {
    "claims_nature_check": "nature IN ('observed','extracted','computed','inferred','decided')",
    "claims_availability_check": "availability IN ('known','unknown','conflicted','not_applicable')",
    "claims_status_check": "status IN ('active','reverted','withdrawn')",
}
for name, condition in checks.items():
    old = next(
        x["sql"] for x in CAT["constraints"] if x["table_name"] == "claims" and x["conname"] == name
    )
    change(
        f"ALTER TABLE claims DROP CONSTRAINT {name}; ALTER TABLE claims ADD CONSTRAINT {name} CHECK ({condition})",
        f"ALTER TABLE claims DROP CONSTRAINT {name}; ALTER TABLE claims ADD CONSTRAINT {name} {legacy_checks[name]}",
    )

for table_name in ("claims", "claim_consumptions"):
    table = Base.metadata.tables[table_name]
    new_columns = {x.name for x in table.columns} - {
        x["column_name"] for x in CAT["columns"] if x["table_name"] == table_name
    }
    for constraint in sorted(table.constraints, key=lambda c: (str(type(c)), str(c))):
        cols = {x.name for x in constraint.columns}
        if not (
            cols & new_columns
            or constraint.name
            in {
                "claim_category_identity",
                "claim_one_source",
                "claim_privacy",
                "claim_origin",
                "claim_vendor_nature",
                "claim_consumption_version",
            }
        ):
            continue
        if constraint.name is None:
            constraint.name = (
                "m3_" + table_name + "_" + ("_".join(x.name for x in constraint.columns)) + "_fk"
            )
        change(
            str(AddConstraint(constraint).compile(dialect=DIALECT)),
            f'ALTER TABLE {table_name} DROP CONSTRAINT "{constraint.name}"',
        )
for table in TABLES:
    change(str(CreateTable(table).compile(dialect=DIALECT)), f"DROP TABLE {table.name}")
    for index in sorted(table.indexes, key=lambda x: x.name):
        UP.append(str(CreateIndex(index).compile(dialect=DIALECT)))

# Snapshot sources have their own exact checks below; the old artifact-only trigger
# remains unchanged for all other source-consuming S0 tables.
old_trigger = next(
    x["sql"]
    for x in CAT["triggers"]
    if x["table_name"] == "claims" and x["tgname"] == "category_source_consumer"
)
change("DROP TRIGGER category_source_consumer ON claims", old_trigger)

function(
    r"""
CREATE FUNCTION m3_evidence_root(t uuid,c uuid,kind text,sid uuid,ver integer)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a artifact_versions; w public_web_snapshots; k claims; private boolean; body text;
BEGIN
 IF kind='claim' THEN
  SELECT * INTO STRICT k FROM claims WHERE tenant_id=t AND category_id=c AND id=sid;
  IF k.status<>'active' OR k.revision<>ver THEN RAISE EXCEPTION 'claim source stale' USING ERRCODE='23514'; END IF;
  RETURN m3_evidence_root(t,c,k.source_kind,coalesce(k.artifact_id,k.snapshot_id),k.source_revision)
   ||jsonb_build_object('claim_private',k.privacy='private','proposal_id',k.proposal_id);
 ELSIF kind IN ('artifact','original') THEN
  SELECT * INTO STRICT a FROM artifact_versions WHERE tenant_id=t AND category_id=c AND id=sid;
  IF a.status<>'active' OR a.revision<>ver THEN RAISE EXCEPTION 'artifact source stale' USING ERRCODE='23514'; END IF;
  private=a.visibility<>'category' OR EXISTS(SELECT 1 FROM products p WHERE p.tenant_id=t AND p.id=a.product_id AND p.visibility<>'category')
   OR EXISTS(SELECT 1 FROM uploaded_originals o WHERE o.tenant_id=t AND o.id=a.original_id AND o.visibility<>'category');
  RETURN jsonb_build_object('type','original','id',a.id,'version',a.revision,'private',private,'body',a.content,'product_id',a.product_id);
 ELSIF kind='snapshot' THEN
  SELECT * INTO STRICT w FROM public_web_snapshots WHERE tenant_id=t AND category_id=c AND id=sid;
  IF ver<>1 OR w.status NOT IN ('ok','partial') THEN RAISE EXCEPTION 'snapshot source stale' USING ERRCODE='23514'; END IF;
  RETURN jsonb_build_object('type','snapshot','id',w.id,'version',1,'private',w.visibility<>'category','body',w.markdown,'product_id',NULL);
 END IF;
 RAISE EXCEPTION 'unknown evidence source' USING ERRCODE='23514';
END $$;
""",
    "m3_evidence_root(uuid,uuid,text,uuid,integer)",
)

function(
    r"""
CREATE FUNCTION m3_evidence_source_reader(t uuid,c uuid,kind text,sid uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND CASE WHEN kind='snapshot' THEN EXISTS(
  SELECT 1 FROM public_web_snapshots w WHERE w.tenant_id=t AND w.category_id=c AND w.id=sid
   AND source_object_audience(t,c,'public_web_snapshots',w.id,w.owner_id,w.visibility))
 ELSE EXISTS(SELECT 1 FROM artifact_versions a WHERE a.tenant_id=t AND a.category_id=c AND a.id=sid
   AND source_object_audience(t,c,'artifact_versions',a.id,a.owner_id,a.visibility)
   AND (a.product_id IS NULL OR EXISTS(SELECT 1 FROM products p WHERE p.tenant_id=t AND p.id=a.product_id
    AND source_object_audience(t,c,'products',p.id,p.owner_id,p.visibility)))
   AND (a.original_id IS NULL OR EXISTS(SELECT 1 FROM uploaded_originals o WHERE o.tenant_id=t AND o.id=a.original_id
    AND source_object_audience(t,c,'uploaded_originals',o.id,o.owner_id,o.visibility)))) END
$$;
""",
    "m3_evidence_source_reader(uuid,uuid,text,uuid)",
)

function(
    r"""
CREATE FUNCTION m3_claim_reader(t uuid,c uuid,sid uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND EXISTS(SELECT 1 FROM claims k WHERE k.tenant_id=t AND k.category_id=c AND k.id=sid
 AND CASE WHEN k.status<>'active' THEN k.human_owner_id=scope_requester() OR EXISTS(
  SELECT 1 FROM object_audiences a WHERE a.tenant_id=t AND a.category_id=c AND a.object_type='claims'
   AND a.subject_id=k.id AND a.owner_id=k.human_owner_id AND a.principal_id=scope_requester())
 WHEN k.privacy='private' AND k.proposal_id IS NOT NULL THEN m3_proposal_reader(t,c,k.proposal_id)
 ELSE source_object_audience(t,c,'claims',k.id,k.human_owner_id,k.visibility)
  AND m3_evidence_source_reader(t,c,k.source_kind,coalesce(k.artifact_id,k.snapshot_id)) END)
$$;
""",
    "m3_claim_reader(uuid,uuid,uuid)",
)

function(
    r"""
CREATE FUNCTION m3_claim_withdrawer(t uuid,c uuid,sid uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT scope_actor()=scope_requester() AND category_access(t,c) AND EXISTS(
 SELECT 1 FROM principals person JOIN claims k ON k.tenant_id=person.tenant_id
 WHERE person.tenant_id=t AND person.id=scope_actor() AND person.kind='human' AND person.active
  AND k.id=sid AND k.category_id=c AND CASE WHEN k.privacy='shared' THEN category_access(t,c,true)
  WHEN k.proposal_id IS NULL THEN k.human_owner_id=scope_requester()
  ELSE EXISTS(SELECT 1 FROM proposals p WHERE p.tenant_id=t AND p.category_id=c AND p.id=k.proposal_id AND p.owner_id=scope_requester()) END)
$$;
""",
    "m3_claim_withdrawer(uuid,uuid,uuid)",
)

function(
    r"""
CREATE FUNCTION m3_evidence_target_reader(t uuid,c uuid,kind text,sid uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND CASE kind
 WHEN 'proposal_item' THEN EXISTS(SELECT 1 FROM proposal_items i WHERE i.tenant_id=t AND i.category_id=c AND i.id=sid AND m3_proposal_reader(t,c,i.proposal_id))
 WHEN 'knowledge_entry' THEN EXISTS(SELECT 1 FROM category_knowledge_entries k WHERE k.tenant_id=t AND k.category_id=c AND k.id=sid)
 WHEN 'definition_spec' THEN EXISTS(SELECT 1 FROM definition_specs s JOIN definition_revisions d ON d.tenant_id=s.tenant_id AND d.id=s.definition_id
  JOIN products p ON p.tenant_id=d.tenant_id AND p.id=d.product_id WHERE s.tenant_id=t AND s.category_id=c AND s.id=sid
  AND source_object_audience(t,c,'definition_revisions',d.id,d.owner_id,d.visibility)
  AND source_object_audience(t,c,'products',p.id,p.owner_id,p.visibility)) ELSE false END
$$;
""",
    "m3_evidence_target_reader(uuid,uuid,text,uuid)",
)

function(
    r"""
CREATE FUNCTION m3_evidence_signed_consumed(t uuid,c uuid,sid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM claim_consumptions cc WHERE cc.tenant_id=t AND cc.category_id=c AND cc.claim_id=sid
  AND (EXISTS(SELECT 1 FROM proposal_decisions d WHERE d.tenant_id=t AND d.category_id=c AND d.id=cc.decision_id AND d.outcome='approved')
   OR EXISTS(SELECT 1 FROM definition_revisions d WHERE d.tenant_id=t AND d.category_id=c AND d.id=cc.definition_id AND d.sealed)
   OR (cc.decision_id IS NULL AND cc.definition_id IS NULL AND cc.consumer_type IN
    ('definition','proposal_decision','g0_decision'))
   OR (cc.decision_id IS NULL AND cc.definition_id IS NULL AND cc.consumer_type='definition_revision'
    AND EXISTS(SELECT 1 FROM definition_revisions d WHERE d.tenant_id=t AND d.category_id=c AND d.id=cc.consumer_id AND d.sealed))))
$$;
""",
    "m3_evidence_signed_consumed(uuid,uuid,uuid)",
)

function(
    r"""
CREATE FUNCTION m3_evidence_revert_confirmation(t uuid,c uuid,rid uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r action_receipts; cp confirmations; rx xid; cx xid; expected jsonb; supplied jsonb; source_receipt uuid; expected_payload jsonb;
BEGIN
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=t AND category_id=c AND id=rid;
 SELECT * INTO STRICT cp FROM confirmations WHERE tenant_id=t AND id=r.confirmation_id;
 SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=t AND id=r.id;
 SELECT xmin INTO cx FROM confirmations WHERE tenant_id=t AND id=cp.id;
 IF r.operation IS DISTINCT FROM 'ai.run.revert' OR r.subject_type NOT IN ('agent_run','claim')
  OR r.actor_id IS DISTINCT FROM scope_actor() OR r.requester_id IS DISTINCT FROM scope_requester()
  OR r.actor_id IS DISTINCT FROM r.requester_id OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL
  OR cp.operation IS DISTINCT FROM r.operation OR cp.actor_id IS DISTINCT FROM r.actor_id
  OR cp.category_id IS DISTINCT FROM c OR cp.product_id IS DISTINCT FROM r.product_id
  OR cp.subject_type IS DISTINCT FROM r.subject_type OR cp.subject_id IS DISTINCT FROM r.subject_id
  OR cp.consumed IS DISTINCT FROM true OR cx IS DISTINCT FROM rx OR rx::text::bigint IS DISTINCT FROM txid_current()%4294967296
  OR (r.subject_type='agent_run' AND cp.revision IS DISTINCT FROM r.subject_revision)
  OR (r.subject_type='claim' AND cp.revision+1 IS DISTINCT FROM r.subject_revision)
  OR jsonb_typeof(cp.snapshot->'receipts') IS DISTINCT FROM 'array'
  OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=t AND p.id=r.actor_id AND p.active AND p.kind='human') THEN
  RAISE EXCEPTION 'evidence revert requires same transaction named confirmation' USING ERRCODE='23514'; END IF;
 IF r.subject_type='agent_run' THEN
  expected_payload=jsonb_build_object('run_id',r.subject_id,'receipt_id',NULL);
  IF cp.snapshot->>'run_id' IS DISTINCT FROM r.subject_id::text OR NOT EXISTS(
   SELECT 1 FROM agent_runs ar WHERE ar.tenant_id=t AND ar.category_id=c AND ar.id=r.subject_id
    AND ar.product_id IS NOT DISTINCT FROM r.product_id AND ar.requester_id=r.requester_id
    AND ar.cancel_epoch=r.subject_revision AND ar.revert_receipt_id=r.id) THEN
   RAISE EXCEPTION 'evidence revert confirmation run mismatch' USING ERRCODE='23514'; END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',original.id,'operation',original.operation,
   'subject_id',original.subject_id,'revision',original.subject_revision) ORDER BY original.id),'[]'::jsonb)
   INTO expected FROM action_receipts original WHERE original.tenant_id=t AND original.category_id=c AND original.agent_run_id=r.subject_id;
 ELSE
  source_receipt=(cp.snapshot->'payload'->>'receipt_id')::uuid;
  expected_payload=jsonb_build_object('run_id',NULL,'receipt_id',source_receipt);
  IF source_receipt IS NULL OR cp.snapshot->>'run_id' IS NOT NULL THEN
   RAISE EXCEPTION 'evidence revert confirmation claim mismatch' USING ERRCODE='23514'; END IF;
  SELECT jsonb_build_array(jsonb_build_object('id',original.id,'operation',original.operation,
   'subject_id',original.subject_id,'revision',original.subject_revision)) INTO STRICT expected FROM action_receipts original
   WHERE original.tenant_id=t AND original.category_id=c AND original.id=source_receipt
    AND original.product_id IS NOT DISTINCT FROM r.product_id AND original.operation='evidence.claim.record'
    AND original.subject_type='claim' AND original.subject_id=r.subject_id AND original.subject_revision=cp.revision
    AND original.requester_id=r.requester_id;
 END IF;
 SELECT coalesce(jsonb_agg(value ORDER BY value->>'id'),'[]'::jsonb) INTO supplied
  FROM jsonb_array_elements(cp.snapshot->'receipts');
 IF cp.snapshot->'payload' IS DISTINCT FROM expected_payload OR supplied IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'evidence revert differs from complete confirmed receipt set' USING ERRCODE='23514'; END IF;
END $$;
""",
    "m3_evidence_revert_confirmation(uuid,uuid,uuid)",
)

function(
    r"""
CREATE FUNCTION m3_evidence_claim_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE root jsonb; ar agent_runs; private boolean;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'claim history retained' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['status','revision']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','revision'])
   OR OLD.status<>'active' OR NEW.status NOT IN ('withdrawn','reverted') OR NEW.revision<>OLD.revision+1 THEN
   RAISE EXCEPTION 'claim only permits named withdrawal' USING ERRCODE='23514';
  END IF;
  IF (NEW.status='reverted' AND EXISTS(SELECT 1 FROM claim_consumptions cc WHERE cc.tenant_id=OLD.tenant_id AND cc.category_id=OLD.category_id AND cc.claim_id=OLD.id))
   OR (NEW.status='withdrawn' AND m3_evidence_signed_consumed(OLD.tenant_id,OLD.category_id,OLD.id)) THEN
   RAISE EXCEPTION 'claim already consumed' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
 IF NEW.status<>'active' OR NEW.revision<>1 THEN RAISE EXCEPTION 'claim starts active' USING ERRCODE='23514'; END IF;
 root=m3_evidence_root(NEW.tenant_id,NEW.category_id,NEW.source_kind,coalesce(NEW.artifact_id,NEW.snapshot_id),NEW.source_revision);
 IF NOT m3_evidence_source_reader(NEW.tenant_id,NEW.category_id,NEW.source_kind,coalesce(NEW.artifact_id,NEW.snapshot_id))
  OR (root->>'product_id' IS NOT NULL AND (root->>'product_id')::uuid IS DISTINCT FROM NEW.product_id)
  OR NEW.quote='' OR position(NEW.quote IN coalesce((string_to_array(replace(root->>'body',E'\r\n',E'\n'),E'\n'))[NEW.line],''))=0 THEN
  RAISE EXCEPTION 'claim source scope or quote mismatch' USING ERRCODE='23514';
 END IF;
 private=(root->>'private')::boolean OR EXISTS(SELECT 1 FROM products p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.product_id AND p.visibility<>'category');
 IF NEW.run_id IS NOT NULL THEN
  SELECT * INTO STRICT ar FROM agent_runs WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.run_id;
  IF ar.product_id IS DISTINCT FROM NEW.product_id OR ar.proposal_id IS DISTINCT FROM NEW.proposal_id
   OR ar.requester_id<>NEW.human_owner_id OR ar.writer_id<>NEW.writer_id
   OR ar.state='cancelled' OR ar.reverted_at IS NOT NULL OR NEW.origin<>'ai_draft'
   OR NEW.nature='observed' OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.writer_id AND p.kind='agent' AND p.active) THEN
   RAISE EXCEPTION 'claim AI provenance mismatch' USING ERRCODE='23514';
  END IF;
  private=private OR ar.private_context;
  IF private AND NEW.proposal_id IS NULL THEN RAISE EXCEPTION 'private AI claim needs proposal' USING ERRCODE='23514'; END IF;
 ELSIF NEW.origin<>'human' OR NEW.writer_id<>scope_actor() OR NEW.human_owner_id<>scope_requester()
  OR scope_actor()<>scope_requester() OR NEW.confirmed_by IS NOT NULL OR NEW.prepared_event_id IS NOT NULL
  OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.writer_id AND p.kind='human' AND p.active) THEN
  RAISE EXCEPTION 'claim human provenance mismatch' USING ERRCODE='23514';
 END IF;
 IF private AND NEW.product_id IS NULL AND NEW.proposal_id IS NULL THEN
  RAISE EXCEPTION 'private category claim needs proposal' USING ERRCODE='23514'; END IF;
 IF NEW.proposal_id IS NOT NULL AND NOT m3_proposal_reader(NEW.tenant_id,NEW.category_id,NEW.proposal_id) THEN
  RAISE EXCEPTION 'claim proposal unreadable' USING ERRCODE='23514';
 END IF;
 IF NEW.privacy IS DISTINCT FROM (CASE WHEN private OR NEW.visibility<>'category' THEN 'private' ELSE 'shared' END)
  OR (private AND NEW.visibility='category') THEN RAISE EXCEPTION 'claim privacy mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.availability='not_applicable' AND nullif(btrim(NEW.content->>'text'),'') IS NULL THEN
  RAISE EXCEPTION 'not applicable claim needs basis' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
""",
    "m3_evidence_claim_guard()",
)

function(
    r"""
CREATE FUNCTION m3_evidence_claim_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r action_receipts; cp confirmations; ev agent_run_events; ar agent_runs; expected jsonb; payload jsonb;
 rx xid; cx xid; k claims;
BEGIN
 SELECT * INTO STRICT k FROM claims WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 IF TG_OP='UPDATE' THEN
  IF NEW.status='withdrawn' AND NOT EXISTS(SELECT 1 FROM claim_withdrawals w
   WHERE w.tenant_id=NEW.tenant_id AND w.category_id=NEW.category_id AND w.claim_id=NEW.id AND w.expected_version=OLD.revision) THEN
   RAISE EXCEPTION 'claim withdrawal record required' USING ERRCODE='23514';
  END IF;
  IF NEW.status='reverted' AND NOT EXISTS(SELECT 1 FROM action_receipts rr
   WHERE rr.tenant_id=NEW.tenant_id AND rr.category_id=NEW.category_id AND rr.operation='ai.run.revert'
    AND rr.actor_id=scope_actor() AND rr.requester_id=scope_requester()
    AND rr.xmin=(SELECT xmin FROM claims WHERE tenant_id=NEW.tenant_id AND id=NEW.id)
    AND ((rr.subject_type='claim' AND rr.subject_id=NEW.id) OR (rr.subject_type='agent_run' AND rr.subject_id=NEW.run_id
     AND EXISTS(SELECT 1 FROM agent_runs actual WHERE actual.tenant_id=NEW.tenant_id AND actual.id=NEW.run_id
      AND actual.revert_receipt_id=rr.id AND actual.reverted_by=rr.requester_id)))) THEN
   RAISE EXCEPTION 'claim revert receipt required' USING ERRCODE='23514';
  END IF;
  IF NEW.status='reverted' THEN
   SELECT rr.* INTO STRICT r FROM action_receipts rr WHERE rr.tenant_id=NEW.tenant_id AND rr.category_id=NEW.category_id
    AND rr.operation='ai.run.revert' AND rr.xmin=(SELECT xmin FROM claims WHERE tenant_id=NEW.tenant_id AND id=NEW.id)
    AND ((rr.subject_type='claim' AND rr.subject_id=NEW.id) OR (rr.subject_type='agent_run' AND rr.subject_id=NEW.run_id));
   PERFORM m3_evidence_revert_confirmation(NEW.tenant_id,NEW.category_id,r.id);
  END IF;
  RETURN NULL;
 END IF;
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id;
 SELECT xmin INTO cx FROM claims WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 IF rx IS DISTINCT FROM cx OR r.operation<>'evidence.claim.record' OR r.subject_type<>'claim'
  OR r.subject_id<>NEW.id OR r.subject_revision<>1 OR r.category_id<>NEW.category_id
  OR r.product_id IS DISTINCT FROM NEW.product_id OR r.actor_id<>scope_actor() OR r.requester_id<>NEW.human_owner_id
  OR r.agent_run_id IS DISTINCT FROM NEW.run_id THEN RAISE EXCEPTION 'claim receipt mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.origin='ai_draft' THEN
  SELECT * INTO STRICT ar FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
  IF NEW.confirmed_by IS NULL THEN
   IF r.actor_id<>NEW.writer_id OR NEW.prepared_event_id IS NOT NULL OR r.confirmation_id IS NOT NULL
    OR NOT EXISTS(SELECT 1 FROM agent_tool_calls tc WHERE tc.tenant_id=NEW.tenant_id AND tc.run_id=NEW.run_id
     AND tc.receipt_id=r.id AND tc.state='completed' AND tc.execution_binding->>'operation'=r.operation) THEN
    RAISE EXCEPTION 'claim T0 requires trusted call' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO STRICT cp FROM confirmations WHERE tenant_id=NEW.tenant_id AND id=r.confirmation_id;
   SELECT * INTO STRICT ev FROM agent_run_events WHERE tenant_id=NEW.tenant_id AND id=NEW.prepared_event_id;
   payload=cp.snapshot->'payload'; expected=ev.body->'command'->'payload';
   -- xmin is a system attribute, read it separately from the composite row.
   SELECT xmin INTO cx FROM confirmations WHERE tenant_id=NEW.tenant_id AND id=cp.id;
   IF cx IS DISTINCT FROM rx OR NEW.confirmed_by<>r.actor_id OR r.actor_id<>r.requester_id
    OR cp.actor_id<>r.actor_id OR cp.consumed IS DISTINCT FROM true OR cp.category_id<>NEW.category_id
    OR cp.product_id IS DISTINCT FROM NEW.product_id OR cp.operation<>r.operation
    OR ev.run_id<>NEW.run_id OR ev.body->>'type' IS DISTINCT FROM 'claim_candidate'
    OR (ev.body->>'cancel_epoch')::integer IS DISTINCT FROM ar.cancel_epoch
    OR (payload-'confirmation_token') IS DISTINCT FROM (expected-'confirmation_token') THEN
    RAISE EXCEPTION 'claim candidate confirmation mismatch' USING ERRCODE='23514'; END IF;
   IF payload->'source' IS NOT NULL AND payload->'source'<>'null'::jsonb THEN
    IF payload->'source'->>'kind' IS DISTINCT FROM NEW.source_kind
     OR payload->'source'->>'id' IS DISTINCT FROM coalesce(NEW.artifact_id,NEW.snapshot_id)::text
     OR (payload->'source'->>'version')::integer IS DISTINCT FROM NEW.source_revision
     OR payload->'source'->>'quote' IS DISTINCT FROM NEW.quote
     OR (payload->'source'->>'line')::integer IS DISTINCT FROM NEW.line
     OR payload->'content' IS DISTINCT FROM NEW.content THEN RAISE EXCEPTION 'claim differs from candidate source' USING ERRCODE='23514'; END IF;
   ELSIF payload->>'artifact_id' IS DISTINCT FROM NEW.artifact_id::text
    OR payload->>'quote' IS DISTINCT FROM NEW.quote OR payload->>'statement' IS DISTINCT FROM NEW.statement
    OR (payload->>'line')::integer IS DISTINCT FROM NEW.line THEN
    RAISE EXCEPTION 'claim differs from legacy candidate' USING ERRCODE='23514';
   END IF;
   IF payload->>'nature' IS DISTINCT FROM NEW.nature OR payload->>'availability' IS DISTINCT FROM NEW.availability
    OR coalesce((payload->>'vendor_claimed')::boolean,false) IS DISTINCT FROM NEW.vendor_claimed THEN
    RAISE EXCEPTION 'claim differs from candidate nature' USING ERRCODE='23514'; END IF;
  END IF;
 ELSIF r.agent_run_id IS NOT NULL OR r.actor_id<>NEW.writer_id OR r.confirmation_id IS NOT NULL THEN
  RAISE EXCEPTION 'human claim cannot borrow AI proof' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
""",
    "m3_evidence_claim_atom()",
)

function(
    r"""
CREATE FUNCTION m3_evidence_proposal_roots(t uuid,c uuid,pid uuid)
RETURNS TABLE(source_type text,source_id uuid,source_version integer,privacy text,ref_count bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 WITH refs AS (
  SELECT ref FROM proposals p CROSS JOIN LATERAL jsonb_array_elements(p.source_refs||p.context_refs) ref
   WHERE p.tenant_id=t AND p.category_id=c AND p.id=pid
  UNION ALL
  SELECT ref FROM proposal_items i JOIN proposal_item_versions v ON v.tenant_id=i.tenant_id AND v.item_id=i.id AND v.version=i.current_version
   CROSS JOIN LATERAL jsonb_array_elements(v.source_refs) ref
   WHERE i.tenant_id=t AND i.category_id=c AND i.proposal_id=pid AND NOT i.removed
  UNION ALL
  SELECT jsonb_build_object('type',l.evidence_type,'id',l.evidence_id,'version',l.evidence_version)
   FROM evidence_links l JOIN proposal_items i ON i.tenant_id=l.tenant_id AND i.id=l.target_id AND i.current_version=l.target_version
   WHERE l.tenant_id=t AND l.category_id=c AND l.target_type='proposal_item' AND i.proposal_id=pid
    AND NOT i.removed AND l.reverted_by_receipt_id IS NULL
 ), normalized AS (
  SELECT CASE WHEN ref->>'type'='claim' THEN CASE WHEN k.source_kind='artifact' THEN 'original' ELSE 'snapshot' END
    WHEN ref->>'type'='artifact' THEN 'original' ELSE ref->>'type' END typ,
   CASE WHEN ref->>'type'='claim' THEN coalesce(k.artifact_id,k.snapshot_id) ELSE (ref->>'id')::uuid END sid,
   CASE WHEN ref->>'type'='claim' THEN k.source_revision ELSE (ref->>'version')::integer END ver
  FROM refs LEFT JOIN claims k ON ref->>'type'='claim' AND k.tenant_id=t AND k.category_id=c AND k.id=(ref->>'id')::uuid
  WHERE ref->>'type' NOT IN ('human','parameter') AND (ref->>'type'<>'claim' OR k.status='active')
 ), roots AS (
  SELECT typ,sid,ver,CASE
   WHEN typ='original' THEN CASE WHEN a.visibility='category' AND (a.product_id IS NULL OR pr.visibility='category')
    AND (a.original_id IS NULL OR o.visibility='category') THEN 'shared' ELSE 'private' END
   WHEN typ='snapshot' THEN CASE WHEN w.visibility='category' THEN 'shared' ELSE 'private' END
   WHEN typ='definition' THEN CASE WHEN d.visibility='category' THEN 'shared' ELSE 'private' END
   ELSE 'shared' END priv
  FROM normalized n LEFT JOIN artifact_versions a ON n.typ='original' AND a.tenant_id=t AND a.category_id=c AND a.id=n.sid
   LEFT JOIN products pr ON pr.tenant_id=t AND pr.id=a.product_id
   LEFT JOIN uploaded_originals o ON o.tenant_id=t AND o.id=a.original_id
   LEFT JOIN public_web_snapshots w ON n.typ='snapshot' AND w.tenant_id=t AND w.category_id=c AND w.id=n.sid
   LEFT JOIN definition_revisions d ON n.typ='definition' AND d.tenant_id=t AND d.category_id=c AND d.id=n.sid
 ) SELECT typ,sid,ver,priv,count(*) FROM roots GROUP BY typ,sid,ver,priv
$$;
""",
    "m3_evidence_proposal_roots(uuid,uuid,uuid)",
)

function(
    r"""
CREATE FUNCTION m3_evidence_withdraw_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k claims; r action_receipts; cp confirmations; rx xid; wx xid; cx xid; rowp proposals; payload jsonb; roots record;
BEGIN
 SELECT * INTO STRICT k FROM claims WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.claim_id FOR UPDATE;
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 SELECT * INTO STRICT cp FROM confirmations WHERE tenant_id=NEW.tenant_id AND id=NEW.confirmation_id;
 SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id;
 SELECT xmin INTO wx FROM claim_withdrawals WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO cx FROM confirmations WHERE tenant_id=NEW.tenant_id AND id=cp.id;
 payload=cp.snapshot->'payload';
 IF rx IS DISTINCT FROM wx OR cx IS DISTINCT FROM rx
  OR rx IS DISTINCT FROM (SELECT xmin FROM claims WHERE tenant_id=NEW.tenant_id AND id=k.id)
  OR cp.consumed IS DISTINCT FROM true OR cp.actor_id<>NEW.actor_id OR cp.category_id<>NEW.category_id
  OR cp.operation<>'evidence.claim.withdraw' OR cp.subject_type<>'claim' OR cp.subject_id<>k.id OR cp.revision<>NEW.expected_version
  OR r.confirmation_id IS DISTINCT FROM cp.id OR r.operation<>cp.operation OR r.subject_type<>'claim' OR r.subject_id<>k.id
  OR r.subject_revision<>NEW.expected_version+1 OR r.actor_id<>NEW.actor_id OR r.requester_id<>NEW.actor_id
  OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL OR r.product_id IS DISTINCT FROM k.product_id
  OR cp.product_id IS DISTINCT FROM k.product_id OR r.category_id<>NEW.category_id
  OR NEW.actor_id IS DISTINCT FROM scope_actor() OR NOT m3_claim_withdrawer(NEW.tenant_id,NEW.category_id,k.id)
  OR (payload->>'claim_id')::uuid IS DISTINCT FROM k.id OR (payload->>'expected_version')::integer IS DISTINCT FROM NEW.expected_version
  OR payload->>'reason' IS DISTINCT FROM NEW.reason OR k.status<>'withdrawn' OR k.revision<>NEW.expected_version+1
  OR m3_evidence_signed_consumed(NEW.tenant_id,NEW.category_id,k.id) THEN
  RAISE EXCEPTION 'claim withdrawal proof or consumption mismatch' USING ERRCODE='23514';
 END IF;
 -- Preserve existing named readers, never future proposal audience members.
 INSERT INTO object_audiences(id,tenant_id,category_id,object_type,subject_id,owner_id,principal_id,created_at)
 SELECT gen_random_uuid(),NEW.tenant_id,NEW.category_id,'claims',k.id,k.human_owner_id,a.principal_id,statement_timestamp()
 FROM object_audiences a WHERE a.tenant_id=NEW.tenant_id AND a.category_id=NEW.category_id
  AND a.object_type='proposals' AND a.subject_id=k.proposal_id ON CONFLICT DO NOTHING;
 INSERT INTO object_audiences(id,tenant_id,category_id,object_type,subject_id,owner_id,principal_id,created_at)
 SELECT gen_random_uuid(),NEW.tenant_id,NEW.category_id,'claims',k.id,k.human_owner_id,s.reviewer_id,statement_timestamp()
 FROM proposal_submissions s WHERE s.tenant_id=NEW.tenant_id AND s.category_id=NEW.category_id AND s.proposal_id=k.proposal_id
 ON CONFLICT DO NOTHING;
 -- Only derived projections are repaired with definer authority. No private body
 -- or target identity is returned to the withdrawing actor.
 FOR rowp IN SELECT p.* FROM proposals p WHERE p.tenant_id=NEW.tenant_id AND p.category_id=NEW.category_id AND (
  p.source_refs @> jsonb_build_array(jsonb_build_object('type','claim','id',k.id))
  OR p.context_refs @> jsonb_build_array(jsonb_build_object('type','claim','id',k.id))
  OR EXISTS(SELECT 1 FROM proposal_items i JOIN proposal_item_versions v ON v.tenant_id=i.tenant_id AND v.item_id=i.id AND v.version=i.current_version
   WHERE i.tenant_id=p.tenant_id AND i.proposal_id=p.id AND NOT i.removed
    AND (v.source_refs @> jsonb_build_array(jsonb_build_object('type','claim','id',k.id)) OR EXISTS(
     SELECT 1 FROM evidence_links l WHERE l.tenant_id=i.tenant_id AND l.target_type='proposal_item' AND l.target_id=i.id
      AND l.target_version=i.current_version AND l.evidence_type='claim' AND l.evidence_id=k.id AND l.reverted_by_receipt_id IS NULL))))
  ORDER BY p.id FOR UPDATE LOOP
  DELETE FROM proposal_sources WHERE tenant_id=NEW.tenant_id AND proposal_id=rowp.id;
  INSERT INTO proposal_sources(id,tenant_id,category_id,proposal_id,source_type,source_id,source_version,privacy,ref_count,created_at)
  SELECT gen_random_uuid(),NEW.tenant_id,NEW.category_id,rowp.id,source_type,source_id,source_version,privacy,ref_count,statement_timestamp()
   FROM m3_evidence_proposal_roots(NEW.tenant_id,NEW.category_id,rowp.id);
  UPDATE proposals SET private_source_count=(SELECT count(*) FROM proposal_sources ps WHERE ps.tenant_id=NEW.tenant_id AND ps.proposal_id=rowp.id AND ps.privacy='private'),
   effective_visibility=CASE WHEN EXISTS(SELECT 1 FROM proposal_sources ps WHERE ps.tenant_id=NEW.tenant_id AND ps.proposal_id=rowp.id AND ps.privacy='private') THEN 'private' ELSE visibility END,
   context_hint=true WHERE tenant_id=NEW.tenant_id AND id=rowp.id;
 END LOOP;
 UPDATE evidence_links SET reverted_by_receipt_id=r.id WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id
  AND evidence_type='claim' AND evidence_id=k.id AND reverted_by_receipt_id IS NULL;
 RETURN NULL;
END $$;
""",
    "m3_evidence_withdraw_atom()",
)

function(
    r"""
CREATE FUNCTION m3_evidence_consumption_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k claims;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'claim consumption immutable' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT k FROM claims WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.claim_id FOR UPDATE;
 IF k.status<>'active' OR (NEW.claim_version IS NOT NULL AND NEW.claim_version<>k.revision) THEN
  RAISE EXCEPTION 'withdrawn or changed claim cannot be consumed' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
""",
    "m3_evidence_consumption_guard()",
)

function(
    r"""
CREATE FUNCTION m3_evidence_consumption_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE k claims; d proposal_decisions; def definition_revisions; r action_receipts; sub proposal_submissions; refs jsonb;
BEGIN
 -- Old S0 consumption records keep their product-scoped semantics; new M3 rows
 -- carry a real decision/definition and exact Claim version.
 IF NEW.decision_id IS NULL AND NEW.definition_id IS NULL THEN
  IF NEW.product_id IS NULL OR NEW.consumer_type IN ('proposal_decision','g0_decision','definition','definition_revision') THEN
   RAISE EXCEPTION 'named consumption needs actual decision' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 END IF;
 SELECT * INTO STRICT k FROM claims WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.claim_id FOR UPDATE;
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF NEW.claim_version IS DISTINCT FROM k.revision OR k.status<>'active' OR r.category_id<>NEW.category_id
  OR r.operation<>'proposal.g0.decide' OR r.actor_id<>r.requester_id OR r.agent_run_id IS NOT NULL
  OR (SELECT xmin FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id) IS DISTINCT FROM
     (SELECT xmin FROM claim_consumptions WHERE tenant_id=NEW.tenant_id AND id=NEW.id) THEN
  RAISE EXCEPTION 'signed claim consumption receipt mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.decision_id IS NOT NULL THEN
  SELECT * INTO STRICT d FROM proposal_decisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.decision_id;
 ELSE
  SELECT * INTO STRICT def FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.definition_id;
  SELECT * INTO STRICT d FROM proposal_decisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=def.g0_decision_id;
 END IF;
 SELECT * INTO STRICT sub FROM proposal_submissions WHERE tenant_id=NEW.tenant_id AND id=d.submission_id;
 IF d.outcome IS DISTINCT FROM 'approved' OR d.receipt_id IS DISTINCT FROM r.id OR d.decided_by<>r.actor_id OR d.review_digest IS DISTINCT FROM sub.document_digest
  OR r.subject_type<>'proposal' OR r.subject_id<>d.proposal_id THEN
  RAISE EXCEPTION 'consumption signer mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.definition_id IS NOT NULL THEN
  SELECT * INTO STRICT def FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.definition_id;
  IF NOT def.sealed OR def.g0_decision_id IS DISTINCT FROM d.id OR d.outcome<>'approved'
   OR def.product_id IS DISTINCT FROM NEW.product_id THEN
   RAISE EXCEPTION 'consumption definition mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.consumer_id NOT IN (d.id,coalesce(NEW.definition_id,d.id)) THEN
  RAISE EXCEPTION 'consumption target mismatch' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM (
  SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'source_refs','[]'::jsonb)) ref
  UNION ALL SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'context_refs','[]'::jsonb)) ref
  UNION ALL SELECT ref FROM jsonb_array_elements(coalesce(sub.frozen_document->'items','[]'::jsonb)) item
   CROSS JOIN LATERAL jsonb_array_elements(coalesce(item->'source_refs','[]'::jsonb)) ref
 ) x WHERE ref->>'type'='claim' AND (ref->>'id')::uuid=k.id AND (ref->>'version')::integer=NEW.claim_version) THEN
  RAISE EXCEPTION 'claim absent from signed document' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
""",
    "m3_evidence_consumption_atom()",
)

function(
    r"""
CREATE FUNCTION m3_evidence_link_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'evidence link history retained' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' AND (OLD.reverted_by_receipt_id IS NOT NULL OR NEW.reverted_by_receipt_id IS NULL
  OR (to_jsonb(NEW)-'reverted_by_receipt_id') IS DISTINCT FROM (to_jsonb(OLD)-'reverted_by_receipt_id')) THEN
  RAISE EXCEPTION 'evidence link only reverts once' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' AND NEW.reverted_by_receipt_id IS NOT NULL THEN
  RAISE EXCEPTION 'evidence link starts active' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
""",
    "m3_evidence_link_guard()",
)

function(
    r"""
CREATE FUNCTION m3_evidence_link_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r action_receipts; ar agent_runs; p proposals; i proposal_items; k category_knowledge_entries;
 spec definition_specs; def definition_revisions; root jsonb; shared boolean; target_product uuid; target_proposal uuid;
BEGIN
 IF TG_OP='UPDATE' THEN
  SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.reverted_by_receipt_id;
  IF r.category_id<>NEW.category_id OR r.actor_id<>r.requester_id OR r.actor_id IS DISTINCT FROM scope_actor()
   OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL
   OR (SELECT xmin FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id) IS DISTINCT FROM
      (SELECT xmin FROM evidence_links WHERE tenant_id=NEW.tenant_id AND id=NEW.id)
   OR NOT ( (r.operation='evidence.claim.withdraw' AND NEW.evidence_type='claim' AND r.subject_id=NEW.evidence_id
     AND EXISTS(SELECT 1 FROM claim_withdrawals w WHERE w.tenant_id=NEW.tenant_id AND w.receipt_id=r.id AND w.claim_id=NEW.evidence_id))
    OR (r.operation='ai.run.revert' AND r.subject_type='agent_run' AND r.subject_id=NEW.run_id AND NEW.origin='ai_draft'
     AND EXISTS(SELECT 1 FROM agent_runs ar WHERE ar.tenant_id=NEW.tenant_id AND ar.id=NEW.run_id AND ar.requester_id=r.requester_id AND ar.revert_receipt_id=r.id AND ar.reverted_by=r.requester_id)))
   OR EXISTS(SELECT 1 FROM proposal_decisions d JOIN proposal_submissions sub ON sub.tenant_id=d.tenant_id AND sub.id=d.submission_id
    WHERE d.tenant_id=NEW.tenant_id AND d.category_id=NEW.category_id AND position(NEW.id::text IN sub.frozen_document::text)>0)
   OR EXISTS(SELECT 1 FROM definition_specs s JOIN definition_revisions d ON d.tenant_id=s.tenant_id AND d.id=s.definition_id
    WHERE s.tenant_id=NEW.tenant_id AND s.category_id=NEW.category_id AND d.sealed AND position(NEW.id::text IN s.source_refs::text)>0) THEN
   RAISE EXCEPTION 'evidence link revert proof or consumption mismatch' USING ERRCODE='23514'; END IF;
  IF r.operation='ai.run.revert' THEN
   PERFORM m3_evidence_revert_confirmation(NEW.tenant_id,NEW.category_id,r.id);
   IF NOT EXISTS(SELECT 1 FROM action_receipts original JOIN agent_runs actual ON actual.tenant_id=original.tenant_id AND actual.id=original.agent_run_id
     WHERE original.tenant_id=NEW.tenant_id AND original.id=NEW.receipt_id AND original.agent_run_id=NEW.run_id
      AND original.operation='evidence.link.create' AND original.subject_type='evidence_link' AND original.subject_id=NEW.id
      AND original.category_id=NEW.category_id AND original.actor_id=actual.writer_id AND original.requester_id=r.requester_id
      AND actual.category_id=NEW.category_id AND actual.writer_id=NEW.writer_id AND actual.requester_id=r.requester_id)
    OR (NEW.target_type='proposal_item' AND NOT EXISTS(SELECT 1 FROM proposal_items item JOIN proposals proposal
     ON proposal.tenant_id=item.tenant_id AND proposal.id=item.proposal_id WHERE item.tenant_id=NEW.tenant_id AND item.id=NEW.target_id
      AND NOT item.removed AND item.current_version=NEW.target_version AND proposal.owner_id=r.requester_id AND proposal.status IN ('draft','returned')))
    OR (NEW.target_type='knowledge_entry' AND NOT EXISTS(SELECT 1 FROM category_knowledge_entries entry WHERE entry.tenant_id=NEW.tenant_id
     AND entry.id=NEW.target_id AND entry.version=NEW.target_version AND EXISTS(SELECT 1 FROM category_knowledge_current current
      WHERE current.tenant_id=entry.tenant_id AND current.category_id=entry.category_id AND current.current_entry_id=entry.id AND current.status='active')))
    OR (NEW.target_type='definition_spec' AND NOT EXISTS(SELECT 1 FROM definition_specs spec JOIN definition_revisions definition
     ON definition.tenant_id=spec.tenant_id AND definition.id=spec.definition_id WHERE spec.tenant_id=NEW.tenant_id AND spec.id=NEW.target_id
      AND definition.revision=NEW.target_version AND NOT definition.sealed AND definition.status='draft')) THEN
    RAISE EXCEPTION 'evidence link run revert target changed' USING ERRCODE='23514'; END IF;
  END IF;
  IF r.operation='ai.run.revert' AND NEW.target_type='proposal_item' THEN
   SELECT pp.* INTO STRICT p FROM proposals pp JOIN proposal_items ii ON ii.tenant_id=pp.tenant_id AND ii.proposal_id=pp.id
    WHERE ii.tenant_id=NEW.tenant_id AND ii.id=NEW.target_id FOR UPDATE OF pp;
   DELETE FROM proposal_sources WHERE tenant_id=NEW.tenant_id AND proposal_id=p.id;
   INSERT INTO proposal_sources(id,tenant_id,category_id,proposal_id,source_type,source_id,source_version,privacy,ref_count,created_at)
   SELECT gen_random_uuid(),NEW.tenant_id,NEW.category_id,p.id,source_type,source_id,source_version,privacy,ref_count,statement_timestamp()
    FROM m3_evidence_proposal_roots(NEW.tenant_id,NEW.category_id,p.id);
   UPDATE proposals SET private_source_count=(SELECT count(*) FROM proposal_sources ps WHERE ps.tenant_id=NEW.tenant_id AND ps.proposal_id=p.id AND ps.privacy='private'),
    effective_visibility=CASE WHEN EXISTS(SELECT 1 FROM proposal_sources ps WHERE ps.tenant_id=NEW.tenant_id AND ps.proposal_id=p.id AND ps.privacy='private') THEN 'private' ELSE visibility END,
    context_hint=true WHERE tenant_id=NEW.tenant_id AND id=p.id;
  END IF;
  RETURN NULL;
 END IF;
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 root=m3_evidence_root(NEW.tenant_id,NEW.category_id,NEW.evidence_type,NEW.evidence_id,NEW.evidence_version);
 IF NEW.evidence_type='claim' THEN
  IF NOT m3_claim_reader(NEW.tenant_id,NEW.category_id,NEW.evidence_id) THEN RAISE EXCEPTION 'claim unreadable' USING ERRCODE='23514'; END IF;
 ELSIF NOT m3_evidence_source_reader(NEW.tenant_id,NEW.category_id,NEW.evidence_type,NEW.evidence_id) THEN
  RAISE EXCEPTION 'link source unreadable' USING ERRCODE='23514';
 END IF;
 IF NOT m3_evidence_target_reader(NEW.tenant_id,NEW.category_id,NEW.target_type,NEW.target_id)
  OR NOT category_access(NEW.tenant_id,NEW.category_id,true) THEN RAISE EXCEPTION 'link target unavailable' USING ERRCODE='23514'; END IF;
 IF NEW.target_type='proposal_item' THEN
  SELECT * INTO STRICT i FROM proposal_items WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.target_id;
  SELECT * INTO STRICT p FROM proposals WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=i.proposal_id;
  IF i.current_version<>NEW.target_version OR i.removed OR p.status NOT IN ('draft','returned') OR p.owner_id<>r.requester_id THEN
   RAISE EXCEPTION 'link proposal target mismatch' USING ERRCODE='23514'; END IF;
  target_proposal=p.id; shared=p.effective_visibility<>'private';
 ELSIF NEW.target_type='knowledge_entry' THEN
  SELECT * INTO STRICT k FROM category_knowledge_entries WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.target_id;
  IF k.version<>NEW.target_version OR NOT EXISTS(SELECT 1 FROM category_knowledge_current cur WHERE cur.tenant_id=k.tenant_id
   AND cur.category_id=k.category_id AND cur.current_entry_id=k.id AND cur.status='active') THEN
   RAISE EXCEPTION 'link knowledge target mismatch' USING ERRCODE='23514'; END IF;
  shared=true;
 ELSE
  SELECT * INTO STRICT spec FROM definition_specs WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.target_id;
  SELECT * INTO STRICT def FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=spec.definition_id FOR UPDATE;
  IF def.sealed OR def.status<>'draft' OR def.revision<>NEW.target_version THEN
   RAISE EXCEPTION 'link sealed definition target mismatch' USING ERRCODE='23514'; END IF;
  target_product=def.product_id;
  shared=def.visibility<>'private' AND EXISTS(SELECT 1 FROM products pr WHERE pr.tenant_id=def.tenant_id AND pr.id=def.product_id AND pr.visibility<>'private');
 END IF;
 IF (shared AND ((root->>'private')::boolean OR coalesce((root->>'claim_private')::boolean,false)))
  OR (coalesce((root->>'claim_private')::boolean,false) AND (root->>'proposal_id')::uuid IS DISTINCT FROM target_proposal) THEN
  RAISE EXCEPTION 'private evidence cannot enter shared target' USING ERRCODE='23514'; END IF;
 IF r.operation<>'evidence.link.create' OR r.subject_type<>'evidence_link' OR r.subject_id<>NEW.id OR r.subject_revision<>1
  OR r.category_id<>NEW.category_id OR r.product_id IS DISTINCT FROM target_product OR r.actor_id IS DISTINCT FROM scope_actor()
  OR r.requester_id IS DISTINCT FROM scope_requester() OR r.agent_run_id IS DISTINCT FROM NEW.run_id
  OR NEW.confirmed_by IS NOT NULL OR r.run_id IS NOT NULL OR r.confirmation_id IS NOT NULL
  OR (SELECT xmin FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id) IS DISTINCT FROM
     (SELECT xmin FROM evidence_links WHERE tenant_id=NEW.tenant_id AND id=NEW.id) THEN
  RAISE EXCEPTION 'evidence link receipt mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.origin='human' THEN
  IF NEW.writer_id<>r.actor_id OR r.actor_id<>r.requester_id OR NEW.run_id IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM principals pr WHERE pr.tenant_id=NEW.tenant_id AND pr.id=NEW.writer_id AND pr.kind='human' AND pr.active) THEN
   RAISE EXCEPTION 'evidence link human provenance mismatch' USING ERRCODE='23514'; END IF;
 ELSIF NEW.origin='ai_draft' THEN
  SELECT * INTO STRICT ar FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
  IF ar.category_id<>NEW.category_id OR ar.product_id IS DISTINCT FROM target_product OR ar.writer_id<>NEW.writer_id
   OR ar.requester_id<>r.requester_id OR ar.writer_id<>r.actor_id OR ar.reverted_at IS NOT NULL OR ar.state='cancelled'
   OR (target_proposal IS NOT NULL AND ar.proposal_id IS DISTINCT FROM target_proposal)
   OR (target_proposal IS NULL AND ar.private_context)
   OR NOT EXISTS(SELECT 1 FROM agent_tool_calls tc WHERE tc.tenant_id=NEW.tenant_id AND tc.run_id=NEW.run_id
    AND tc.receipt_id=r.id AND tc.state='completed' AND tc.execution_binding->>'operation'=r.operation) THEN
   RAISE EXCEPTION 'evidence link T0 provenance mismatch' USING ERRCODE='23514'; END IF;
 ELSE RAISE EXCEPTION 'evidence link imported path unavailable' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
""",
    "m3_evidence_link_atom()",
)

function(
    r"""
CREATE FUNCTION m3_evidence_share_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r action_receipts; cp confirmations; payload jsonb; k claims; root jsonb; material text; token text; rx xid; cx xid;
BEGIN
 IF NEW.visibility IS NOT DISTINCT FROM OLD.visibility AND NEW.revision=OLD.revision THEN RETURN NULL; END IF;
 IF NEW.visibility IS NOT DISTINCT FROM OLD.visibility AND NOT EXISTS(
  SELECT 1 FROM proposal_revisions pv JOIN action_receipts rr ON rr.tenant_id=pv.tenant_id AND rr.id=pv.receipt_id
  WHERE pv.tenant_id=NEW.tenant_id AND pv.proposal_id=NEW.id AND pv.revision=NEW.revision AND rr.operation='proposal.share') THEN RETURN NULL; END IF;
 IF NEW.visibility NOT IN ('category','audience') OR NEW.effective_visibility<>NEW.visibility
  OR NEW.private_source_count<>0 OR NEW.owner_id IS DISTINCT FROM scope_actor() OR scope_actor()<>scope_requester() THEN
  RAISE EXCEPTION 'proposal share requires owner' USING ERRCODE='23514'; END IF;
 SELECT rr.* INTO STRICT r FROM action_receipts rr JOIN proposal_revisions rev ON rev.tenant_id=rr.tenant_id AND rev.receipt_id=rr.id
  WHERE rev.tenant_id=NEW.tenant_id AND rev.proposal_id=NEW.id AND rev.revision=NEW.revision;
 SELECT * INTO STRICT cp FROM confirmations WHERE tenant_id=NEW.tenant_id AND id=r.confirmation_id;
 payload=cp.snapshot->'payload';
 SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id;
 SELECT xmin INTO cx FROM confirmations WHERE tenant_id=NEW.tenant_id AND id=cp.id;
 IF rx IS DISTINCT FROM cx OR rx IS DISTINCT FROM (SELECT xmin FROM proposals WHERE tenant_id=NEW.tenant_id AND id=NEW.id)
  OR cp.consumed IS DISTINCT FROM true OR cp.operation<>'proposal.share' OR cp.subject_type<>'proposal'
  OR cp.subject_id<>NEW.id OR cp.revision<>OLD.revision OR cp.actor_id<>NEW.owner_id OR cp.product_id IS NOT NULL
  OR cp.category_id<>NEW.category_id OR r.operation<>cp.operation OR r.subject_id<>NEW.id OR r.subject_type<>'proposal'
  OR r.subject_revision<>NEW.revision OR r.actor_id<>NEW.owner_id OR r.requester_id<>NEW.owner_id
  OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL OR r.product_id IS NOT NULL OR r.category_id<>NEW.category_id
  OR (payload->>'proposal_id')::uuid IS DISTINCT FROM NEW.id OR (payload->>'expected_revision')::integer IS DISTINCT FROM OLD.revision
  OR payload->>'visibility' IS DISTINCT FROM NEW.visibility OR jsonb_typeof(payload->'audience_ids') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'proposal share confirmation mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM m3_evidence_proposal_roots(NEW.tenant_id,NEW.category_id,NEW.id) roots WHERE roots.privacy='private')
  OR EXISTS((SELECT source_type,source_id,source_version,privacy,ref_count FROM m3_evidence_proposal_roots(NEW.tenant_id,NEW.category_id,NEW.id)
    EXCEPT SELECT source_type,source_id,source_version,privacy,ref_count::bigint FROM proposal_sources WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.id)
   UNION ALL (SELECT source_type,source_id,source_version,privacy,ref_count::bigint FROM proposal_sources WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.id
    EXCEPT SELECT source_type,source_id,source_version,privacy,ref_count FROM m3_evidence_proposal_roots(NEW.tenant_id,NEW.category_id,NEW.id))) THEN
  RAISE EXCEPTION 'proposal share source projection mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(payload->'audience_ids') person WHERE NOT EXISTS(
  SELECT 1 FROM object_audiences a JOIN principals pr ON pr.tenant_id=a.tenant_id AND pr.id=a.principal_id
   JOIN grants g ON g.tenant_id=a.tenant_id AND g.category_id=a.category_id AND g.principal_id=a.principal_id
   WHERE a.tenant_id=NEW.tenant_id AND a.category_id=NEW.category_id AND a.object_type='proposals' AND a.subject_id=NEW.id
    AND a.principal_id=person::uuid AND a.owner_id=NEW.owner_id AND pr.active AND pr.kind='human'
    AND (g.expires_at IS NULL OR g.expires_at>statement_timestamp()))) THEN
  RAISE EXCEPTION 'proposal share audience mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM object_audiences a WHERE a.tenant_id=NEW.tenant_id AND a.category_id=NEW.category_id
   AND a.object_type='proposals' AND a.subject_id=NEW.id AND NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements_text(payload->'audience_ids') v WHERE v::uuid=a.principal_id)
   AND NOT EXISTS(SELECT 1 FROM proposal_submissions sub WHERE sub.tenant_id=NEW.tenant_id
    AND sub.id=NEW.current_submission_id AND sub.reviewer_id=a.principal_id))
  OR EXISTS(SELECT 1 FROM proposal_submissions sub WHERE sub.tenant_id=NEW.tenant_id AND sub.id=NEW.current_submission_id
   AND NOT EXISTS(SELECT 1 FROM object_audiences a WHERE a.tenant_id=NEW.tenant_id AND a.object_type='proposals'
    AND a.subject_id=NEW.id AND a.principal_id=sub.reviewer_id)) THEN
  RAISE EXCEPTION 'proposal share final audience set mismatch' USING ERRCODE='23514'; END IF;
 FOR k IN SELECT * FROM claims WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND proposal_id=NEW.id
  AND status='active' AND privacy='private' ORDER BY id FOR UPDATE LOOP
  root=m3_evidence_root(NEW.tenant_id,NEW.category_id,k.source_kind,coalesce(k.artifact_id,k.snapshot_id),k.source_revision);
  IF (root->>'private')::boolean OR (payload->>'deidentified_confirmed')::boolean IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'private claim sharing needs deidentification' USING ERRCODE='23514'; END IF;
  material=lower(jsonb_build_object('content',k.content,'quote',k.quote,'statement',k.statement)::text);
  IF material ~ '(https?://|www\.)' THEN RAISE EXCEPTION 'claim identity link not removed' USING ERRCODE='23514'; END IF;
  FOR token IN SELECT lower(value) FROM jsonb_array_elements_text(NEW.customer_identities) value
   UNION SELECT lower(o.filename) FROM proposal_sources ps JOIN artifact_versions a ON a.tenant_id=ps.tenant_id AND a.id=ps.source_id
    JOIN uploaded_originals o ON o.tenant_id=a.tenant_id AND o.id=a.original_id
    WHERE ps.tenant_id=NEW.tenant_id AND ps.proposal_id=NEW.id AND ps.source_type='original'
   UNION SELECT NEW.id::text
   UNION SELECT ps.source_id::text FROM proposal_sources ps WHERE ps.tenant_id=NEW.tenant_id AND ps.proposal_id=NEW.id LOOP
   IF token<>'' AND position(token IN material)>0 THEN RAISE EXCEPTION 'claim identity not removed' USING ERRCODE='23514'; END IF;
  END LOOP;
 END LOOP;
 RETURN NULL;
END $$;
""",
    "m3_evidence_share_atom()",
)

function(
    r"""
CREATE FUNCTION m3_evidence_audience_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a object_audiences; p proposals; r action_receipts; cp confirmations; payload jsonb; xid_now bigint;
BEGIN
 IF TG_OP='DELETE' THEN a=OLD; ELSE a=NEW; END IF;
 IF a.object_type<>'proposals' THEN RETURN NULL; END IF;
 xid_now=txid_current()%4294967296;
 SELECT * INTO STRICT p FROM proposals WHERE tenant_id=a.tenant_id AND category_id=a.category_id AND id=a.subject_id;
 -- Submission only grants its named reviewer; unrelated audience changes need sharing proof.
 IF TG_OP='INSERT' AND a.owner_id=p.owner_id AND scope_actor()=p.owner_id AND scope_actor()=scope_requester()
  AND EXISTS(SELECT 1 FROM proposal_submissions sub JOIN action_receipts rr ON rr.tenant_id=sub.tenant_id AND rr.id=sub.receipt_id
   WHERE sub.tenant_id=a.tenant_id AND sub.category_id=a.category_id AND sub.id=p.current_submission_id
    AND sub.proposal_id=p.id AND sub.reviewer_id=a.principal_id AND rr.operation='proposal.g0.submit'
    AND rr.actor_id=p.owner_id AND rr.requester_id=p.owner_id AND rr.agent_run_id IS NULL AND rr.run_id IS NULL
    AND sub.xmin::text::bigint=xid_now AND rr.xmin=sub.xmin) THEN RETURN NULL; END IF;
 SELECT rr.* INTO r FROM proposal_revisions pv JOIN action_receipts rr ON rr.tenant_id=pv.tenant_id AND rr.id=pv.receipt_id
  WHERE pv.tenant_id=a.tenant_id AND pv.proposal_id=p.id AND pv.revision=p.revision AND rr.operation='proposal.share';
 IF NOT FOUND THEN RAISE EXCEPTION 'proposal audience requires named share' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT cp FROM confirmations WHERE tenant_id=a.tenant_id AND id=r.confirmation_id;
 payload=cp.snapshot->'payload';
 IF p.owner_id IS DISTINCT FROM scope_actor() OR scope_actor() IS DISTINCT FROM scope_requester()
  OR a.owner_id IS DISTINCT FROM p.owner_id OR cp.actor_id IS DISTINCT FROM p.owner_id
  OR cp.category_id IS DISTINCT FROM p.category_id OR cp.product_id IS NOT NULL OR cp.consumed IS DISTINCT FROM true
  OR cp.operation IS DISTINCT FROM 'proposal.share' OR cp.subject_type IS DISTINCT FROM 'proposal'
  OR cp.subject_id IS DISTINCT FROM p.id OR cp.revision+1 IS DISTINCT FROM p.revision
  OR r.actor_id IS DISTINCT FROM p.owner_id OR r.requester_id IS DISTINCT FROM p.owner_id
  OR r.subject_type IS DISTINCT FROM 'proposal' OR r.subject_id IS DISTINCT FROM p.id
  OR r.subject_revision IS DISTINCT FROM p.revision OR r.category_id IS DISTINCT FROM p.category_id
  OR r.product_id IS NOT NULL OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL
  OR NOT EXISTS(SELECT 1 FROM confirmations proof JOIN action_receipts receipt ON receipt.tenant_id=proof.tenant_id AND receipt.confirmation_id=proof.id
    JOIN proposals current_proposal ON current_proposal.tenant_id=receipt.tenant_id AND current_proposal.id=receipt.subject_id
    WHERE proof.tenant_id=a.tenant_id AND proof.id=cp.id AND receipt.id=r.id
     AND proof.xmin::text::bigint=xid_now AND receipt.xmin=proof.xmin AND current_proposal.xmin=proof.xmin)
  OR (payload->>'proposal_id')::uuid IS DISTINCT FROM p.id
  OR (payload->>'expected_revision')::integer IS DISTINCT FROM cp.revision
  OR payload->>'visibility' IS DISTINCT FROM p.visibility
  OR jsonb_typeof(payload->'audience_ids') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'proposal audience share proof mismatch' USING ERRCODE='23514'; END IF;
 IF EXISTS((SELECT principal_id FROM object_audiences aa WHERE aa.tenant_id=a.tenant_id AND aa.category_id=a.category_id
    AND aa.object_type='proposals' AND aa.subject_id=p.id
   EXCEPT (SELECT value::uuid FROM jsonb_array_elements_text(payload->'audience_ids')
    UNION SELECT sub.reviewer_id FROM proposal_submissions sub WHERE sub.tenant_id=a.tenant_id AND sub.id=p.current_submission_id))
  UNION ALL ((SELECT value::uuid FROM jsonb_array_elements_text(payload->'audience_ids')
    UNION SELECT sub.reviewer_id FROM proposal_submissions sub WHERE sub.tenant_id=a.tenant_id AND sub.id=p.current_submission_id)
   EXCEPT SELECT principal_id FROM object_audiences aa WHERE aa.tenant_id=a.tenant_id AND aa.category_id=a.category_id
    AND aa.object_type='proposals' AND aa.subject_id=p.id)) THEN
  RAISE EXCEPTION 'proposal audience differs from confirmed set' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
""",
    "m3_evidence_audience_atom()",
)

# Recursive typed-reference extraction preserves IDs deliberately ignored by the
# S0 generic lifecycle scanner, without changing that scanner's existing callers.
function(
    r"""
CREATE FUNCTION m3_evidence_reference_ids(value jsonb,wanted_type text DEFAULT NULL) RETURNS uuid[]
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE ids uuid[]='{}'; child jsonb;
BEGIN
 IF jsonb_typeof(value)='object' THEN
  IF value->>'type' IN ('claim','artifact','original','evidence_link') AND value->>'id' IS NOT NULL
   AND (wanted_type IS NULL OR value->>'type'=wanted_type) THEN
   BEGIN ids=array_append(ids,(value->>'id')::uuid); EXCEPTION WHEN invalid_text_representation THEN NULL; END;
  END IF;
  FOR child IN SELECT v FROM jsonb_each(value) x(k,v) LOOP ids=ids||m3_evidence_reference_ids(child,wanted_type); END LOOP;
 ELSIF jsonb_typeof(value)='array' THEN
  FOR child IN SELECT v FROM jsonb_array_elements(value) x(v) LOOP ids=ids||m3_evidence_reference_ids(child,wanted_type); END LOOP;
 END IF;
 RETURN ids;
END $$;
""",
    "m3_evidence_reference_ids(jsonb,text)",
)

function(
    r"""
CREATE FUNCTION m3_claim_reference_states(t uuid,c uuid,requested uuid[])
RETURNS TABLE(id uuid,revision integer,status text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 WITH readable_refs AS (
  SELECT m3_evidence_reference_ids(p.source_refs,'claim')||m3_evidence_reference_ids(p.context_refs,'claim') refs
   FROM proposals p WHERE p.tenant_id=t AND p.category_id=c AND m3_proposal_reader(t,c,p.id)
  UNION ALL SELECT m3_evidence_reference_ids(v.source_refs,'claim') FROM proposal_item_versions v
   JOIN proposal_items i ON i.tenant_id=v.tenant_id AND i.id=v.item_id
   WHERE v.tenant_id=t AND v.category_id=c AND m3_proposal_reader(t,c,i.proposal_id)
  UNION ALL SELECT m3_evidence_reference_ids(sub.frozen_document,'claim') FROM proposal_submissions sub
   WHERE sub.tenant_id=t AND sub.category_id=c AND m3_proposal_reader(t,c,sub.proposal_id)
  UNION ALL SELECT m3_evidence_reference_ids(k.source_refs,'claim') FROM category_knowledge_entries k
   WHERE k.tenant_id=t AND k.category_id=c AND m3_evidence_target_reader(t,c,'knowledge_entry',k.id)
  UNION ALL SELECT m3_evidence_reference_ids(s.source_refs,'claim') FROM definition_specs s
   WHERE s.tenant_id=t AND s.category_id=c AND m3_evidence_target_reader(t,c,'definition_spec',s.id)
  UNION ALL SELECT ARRAY[l.evidence_id] FROM evidence_links l WHERE l.tenant_id=t AND l.category_id=c
   AND l.evidence_type='claim' AND m3_evidence_target_reader(t,c,l.target_type,l.target_id)
 )
 SELECT k.id,k.revision,k.status FROM claims k WHERE k.tenant_id=t AND k.category_id=c AND category_access(t,c)
  AND k.id=ANY(requested) AND EXISTS(SELECT 1 FROM readable_refs r WHERE k.id=ANY(r.refs))
$$;
""",
    "m3_claim_reference_states(uuid,uuid,uuid[])",
)

function(
    r"""
CREATE FUNCTION m3_evidence_decision_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE sub proposal_submissions; ref jsonb; k claims;
BEGIN
 IF NEW.outcome<>'approved' THEN RETURN NULL; END IF;
 SELECT * INTO STRICT sub FROM proposal_submissions WHERE tenant_id=NEW.tenant_id AND id=NEW.submission_id;
 FOR ref IN SELECT DISTINCT value FROM (
  SELECT value FROM jsonb_array_elements(coalesce(sub.frozen_document->'source_refs','[]'::jsonb))
  UNION ALL SELECT value FROM jsonb_array_elements(coalesce(sub.frozen_document->'context_refs','[]'::jsonb))
  UNION ALL SELECT item_ref.value FROM jsonb_array_elements(coalesce(sub.frozen_document->'items','[]'::jsonb)) item
   CROSS JOIN LATERAL jsonb_array_elements(coalesce(item->'source_refs','[]'::jsonb)) item_ref(value)
 ) x WHERE value->>'type'='claim' LOOP
  SELECT * INTO STRICT k FROM claims WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=(ref->>'id')::uuid FOR UPDATE;
  IF k.status<>'active' OR k.revision IS DISTINCT FROM (ref->>'version')::integer OR NOT EXISTS(
   SELECT 1 FROM claim_consumptions cc WHERE cc.tenant_id=NEW.tenant_id AND cc.category_id=NEW.category_id AND cc.claim_id=k.id
    AND cc.claim_version=k.revision AND cc.decision_id=NEW.id AND cc.definition_id=NEW.created_definition_id AND cc.receipt_id=NEW.receipt_id) THEN
   RAISE EXCEPTION 'G0 claim consumption must commit with decision' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NULL;
END $$;
""",
    "m3_evidence_decision_atom()",
)

function(
    r"""
CREATE FUNCTION m3_claim_is_consumed(t uuid,c uuid,sid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT (m3_claim_reader(t,c,sid) OR m3_claim_withdrawer(t,c,sid)) AND m3_evidence_signed_consumed(t,c,sid)
$$;
""",
    "m3_claim_is_consumed(uuid,uuid,uuid)",
)

# Keep the exact S0 scan, extending only actual M3 dependencies and validating
# the caller-provided exclusion set against the complete run receipt set.
original = next(x["sql"] for x in CAT["functions"] if x["proname"] == "revert_subjects_consumed")
amended = (
    original.replace(
        "'work_requests']; table_name",
        "'work_requests','proposals','proposal_item_versions','proposal_submissions','proposal_decisions','category_knowledge_entries','evidence_links']; table_name",
    )
    .replace(
        "payload jsonb;",
        "payload jsonb; bound_run_id uuid; rr action_receipts; ar agent_runs;",
    )
    .replace(
        " IF NOT category_access(t,c,true) OR jsonb_typeof(targets)<>'array' THEN RETURN true; END IF;",
        """ IF category_access(t,c,true) IS DISTINCT FROM true OR scope_actor() IS DISTINCT FROM scope_requester()
  OR jsonb_typeof(targets) IS DISTINCT FROM 'array' OR own_receipts IS NULL THEN RETURN true; END IF;
 IF cardinality(own_receipts)=0 THEN RETURN jsonb_array_length(targets)<>0; END IF;
 IF cardinality(own_receipts)<>(SELECT count(DISTINCT v) FROM unnest(own_receipts) x(v))
  OR cardinality(own_receipts)<>jsonb_array_length(targets)
  OR jsonb_array_length(targets)<>(SELECT count(DISTINCT v->>'id') FROM jsonb_array_elements(targets) x(v)) THEN RETURN true; END IF;
 SELECT r.agent_run_id INTO bound_run_id FROM action_receipts r WHERE r.tenant_id=t AND r.id=own_receipts[1];
 SELECT * INTO ar FROM agent_runs a WHERE a.tenant_id=t AND a.category_id=c AND a.id=bound_run_id
  AND a.requester_id=scope_requester();
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=t AND p.id=scope_actor() AND p.active AND p.kind='human') THEN RETURN true; END IF;
 IF EXISTS(SELECT 1 FROM action_receipts r WHERE r.tenant_id=t AND r.agent_run_id=bound_run_id AND NOT r.id=ANY(own_receipts)) THEN RETURN true; END IF;
 FOR rr IN SELECT r.* FROM action_receipts r WHERE r.id=ANY(own_receipts) LOOP
  IF rr.tenant_id IS DISTINCT FROM t OR rr.category_id IS DISTINCT FROM c OR rr.agent_run_id IS DISTINCT FROM bound_run_id
   OR rr.requester_id IS DISTINCT FROM ar.requester_id OR rr.run_id IS NOT NULL
   OR (ar.product_id IS NOT NULL AND rr.product_id IS DISTINCT FROM ar.product_id)
   OR NOT (rr.actor_id=ar.writer_id OR (rr.actor_id=ar.requester_id AND rr.operation='evidence.claim.record'
    AND EXISTS(SELECT 1 FROM claims k WHERE k.tenant_id=t AND k.id=rr.subject_id AND k.run_id=bound_run_id
     AND k.origin='ai_draft' AND k.writer_id=ar.writer_id AND k.confirmed_by=ar.requester_id AND k.receipt_id=rr.id)))
   OR rr.operation NOT IN ('evidence.claim.record','evidence.artifact.register','evidence.link.create')
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(targets) x(v) WHERE v->>'type'=rr.subject_type AND (v->>'id')::uuid=rr.subject_id)
   THEN RETURN true; END IF;
 END LOOP;
 IF (SELECT count(*) FROM action_receipts r WHERE r.id=ANY(own_receipts))<>cardinality(own_receipts) THEN RETURN true; END IF;""",
    )
    .replace(
        "AND a.human_owner_id=scope_requester() AND source_object_audience(t,c,'claims',a.id,a.human_owner_id,a.visibility)",
        "AND a.human_owner_id=scope_requester() AND (a.run_id=bound_run_id OR a.receipt_id IS NULL) AND m3_claim_reader(t,c,a.id)",
    )
    .replace(
        "  ELSE RETURN true; END IF;\n  ids=array_append",
        """  ELSIF target->>'type'='evidence_link' THEN
   IF NOT EXISTS(SELECT 1 FROM evidence_links l JOIN agent_runs a ON a.tenant_id=l.tenant_id AND a.id=l.run_id
    WHERE l.tenant_id=t AND l.category_id=c AND l.id=(target->>'id')::uuid AND l.run_id=bound_run_id
     AND l.origin='ai_draft' AND l.writer_id=a.writer_id AND a.requester_id=scope_requester()
     AND m3_evidence_target_reader(t,c,l.target_type,l.target_id)) THEN RETURN true; END IF;
  ELSE RETURN true; END IF;
  ids=array_append""",
    )
    .replace(
        "   IF lifecycle_payload_links(payload) && ids THEN RETURN true; END IF;",
        """   IF table_name='evidence_links' AND payload->>'reverted_by_receipt_id' IS NOT NULL THEN CONTINUE; END IF;
   IF table_name='proposal_item_versions' AND NOT EXISTS(SELECT 1 FROM proposal_items i WHERE i.tenant_id=t AND i.category_id=c
    AND i.id=(payload->>'item_id')::uuid AND NOT i.removed AND i.current_version=(payload->>'version')::integer) THEN CONTINUE; END IF;
   IF lifecycle_payload_links(payload) && ids OR m3_evidence_reference_ids(payload) && ids THEN RETURN true; END IF;""",
    )
)
assert amended != original and "'evidence_links']; table_name" in amended
function(amended, "revert_subjects_consumed(uuid,uuid,jsonb,uuid[])")

function(
    r"""
CREATE FUNCTION m3_evidence_run_revert_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r action_receipts; original action_receipts; ids uuid[]; targets jsonb; expected_ids jsonb; rx xid;
BEGIN
 IF NEW.revert_receipt_id IS NOT DISTINCT FROM OLD.revert_receipt_id THEN RETURN NULL; END IF;
 -- Existing S0-only run semantics remain with their original owner.
 IF NOT EXISTS(SELECT 1 FROM evidence_links l WHERE l.tenant_id=NEW.tenant_id AND l.run_id=NEW.id)
  AND NOT EXISTS(SELECT 1 FROM claims k WHERE k.tenant_id=NEW.tenant_id AND k.run_id=NEW.id AND k.receipt_id IS NOT NULL) THEN RETURN NULL; END IF;
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.revert_receipt_id;
 PERFORM m3_evidence_revert_confirmation(NEW.tenant_id,NEW.category_id,r.id);
 SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id;
 IF r.operation IS DISTINCT FROM 'ai.run.revert' OR r.subject_type IS DISTINCT FROM 'agent_run' OR r.subject_id IS DISTINCT FROM NEW.id
  OR r.actor_id IS DISTINCT FROM scope_actor() OR r.requester_id IS DISTINCT FROM NEW.requester_id
  OR r.actor_id IS DISTINCT FROM r.requester_id OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL
  OR r.category_id IS DISTINCT FROM NEW.category_id OR r.product_id IS DISTINCT FROM NEW.product_id
  OR rx IS DISTINCT FROM (SELECT xmin FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.id) THEN
  RAISE EXCEPTION 'evidence run revert identity mismatch' USING ERRCODE='23514'; END IF;
 SELECT coalesce(array_agg(receipt.id ORDER BY receipt.id),'{}'::uuid[]),
  coalesce(jsonb_agg(jsonb_build_object('type',receipt.subject_type,'id',receipt.subject_id) ORDER BY receipt.id),'[]'::jsonb),
  coalesce(jsonb_agg(to_jsonb(receipt.id) ORDER BY receipt.id),'[]'::jsonb)
 INTO ids,targets,expected_ids FROM action_receipts receipt WHERE receipt.tenant_id=NEW.tenant_id AND receipt.agent_run_id=NEW.id;
 IF jsonb_typeof(r.result->'receipt_ids') IS DISTINCT FROM 'array'
  OR (SELECT coalesce(jsonb_agg(value ORDER BY value),'[]'::jsonb) FROM jsonb_array_elements(r.result->'receipt_ids')) IS DISTINCT FROM expected_ids
  OR revert_subjects_consumed(NEW.tenant_id,NEW.category_id,targets,ids) THEN
  RAISE EXCEPTION 'evidence run revert incomplete or consumed' USING ERRCODE='23514'; END IF;
 FOR original IN SELECT receipt.* FROM action_receipts receipt WHERE receipt.tenant_id=NEW.tenant_id AND receipt.agent_run_id=NEW.id LOOP
  IF original.subject_type='claim' THEN
   IF NOT EXISTS(SELECT 1 FROM claims k WHERE k.tenant_id=NEW.tenant_id AND k.id=original.subject_id
    AND k.status='reverted' AND k.revision=original.subject_revision+1 AND k.xmin=rx) THEN
    RAISE EXCEPTION 'evidence run revert missing claim' USING ERRCODE='23514'; END IF;
  ELSIF original.subject_type='artifact' THEN
   IF NOT EXISTS(SELECT 1 FROM artifact_versions a WHERE a.tenant_id=NEW.tenant_id AND a.id=original.subject_id
    AND a.status='withdrawn' AND a.revision=original.subject_revision+1 AND a.xmin=rx) THEN
    RAISE EXCEPTION 'evidence run revert missing artifact' USING ERRCODE='23514'; END IF;
  ELSIF original.subject_type='evidence_link' THEN
   IF NOT EXISTS(SELECT 1 FROM evidence_links l WHERE l.tenant_id=NEW.tenant_id AND l.id=original.subject_id
    AND l.reverted_by_receipt_id=r.id AND l.xmin=rx) THEN
    RAISE EXCEPTION 'evidence run revert missing link' USING ERRCODE='23514'; END IF;
  ELSE RAISE EXCEPTION 'evidence run revert unsupported result' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NULL;
END $$;
""",
    "m3_evidence_run_revert_atom()",
)

# Only the trusted withdrawal projection may update hidden proposal counters.
original = next(x["sql"] for x in CAT["functions"] if x["proname"] == "m3_proposal_guard")
marker = " ELSE\n  IF NEW.context_hint"
assert marker in original
amended = original.replace(
    marker,
    """ ELSE
  IF current_user='pdos_next_owner'
   AND (to_jsonb(NEW)-ARRAY['private_source_count','effective_visibility','context_hint'])
      IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['private_source_count','effective_visibility','context_hint'])
   AND NEW.context_hint AND NEW.private_source_count=(SELECT count(*) FROM proposal_sources ps
    WHERE ps.tenant_id=NEW.tenant_id AND ps.proposal_id=NEW.id AND ps.privacy='private')
   AND NEW.effective_visibility=(CASE WHEN NEW.private_source_count>0 THEN 'private' ELSE NEW.visibility END)
   AND (EXISTS(SELECT 1 FROM claim_withdrawals w JOIN action_receipts r ON r.tenant_id=w.tenant_id AND r.id=w.receipt_id
    WHERE w.tenant_id=NEW.tenant_id AND w.category_id=NEW.category_id AND r.operation='evidence.claim.withdraw'
     AND r.actor_id=scope_actor() AND w.xmin=r.xmin)
    OR EXISTS(SELECT 1 FROM evidence_links l JOIN action_receipts r ON r.tenant_id=l.tenant_id AND r.id=l.reverted_by_receipt_id
     WHERE l.tenant_id=NEW.tenant_id AND l.category_id=NEW.category_id AND r.operation='ai.run.revert'
      AND r.actor_id=scope_actor() AND l.xmin=r.xmin)) THEN RETURN NEW; END IF;
  IF NEW.context_hint""",
)
# A read-only owner may only update the fields of the exact consumed share.
share_gate = """  IF OLD.owner_id=scope_actor() AND scope_actor()=scope_requester()
   AND NEW.revision=OLD.revision+1
   AND (to_jsonb(NEW)-ARRAY['visibility','effective_visibility','revision']) IS NOT DISTINCT FROM
       (to_jsonb(OLD)-ARRAY['visibility','effective_visibility','revision'])
   AND EXISTS(SELECT 1 FROM confirmations cp WHERE cp.tenant_id=NEW.tenant_id AND cp.category_id=NEW.category_id
    AND cp.operation='proposal.share' AND cp.subject_type='proposal' AND cp.subject_id=NEW.id
    AND cp.actor_id=scope_actor() AND cp.consumed AND cp.revision=OLD.revision
    AND cp.snapshot->'payload'->>'visibility'=NEW.visibility) THEN RETURN NEW; END IF;
  IF current_user<>'pdos_next_owner' AND NOT category_access(NEW.tenant_id,NEW.category_id,true)
   AND NOT m3_reviewer(NEW.tenant_id,NEW.category_id,NEW.id) THEN
   RAISE EXCEPTION 'read owner may only apply named share' USING ERRCODE='23514'; END IF;
"""
amended = amended.replace("  IF NEW.context_hint", share_gate + "  IF NEW.context_hint", 1)
function(amended, "m3_proposal_guard()")

original = next(
    x["sql"] for x in CAT["functions"] if x["proname"] == "protect_object_audience_target"
)
assert '"proposals": "owner_id"' in original
function(
    original.replace(
        '"proposals": "owner_id"', '"proposals": "owner_id", "claims": "human_owner_id"'
    ),
    "protect_object_audience_target()",
)
original = next(
    x["sql"] for x in CAT["functions"] if x["proname"] == "m3_material_confirmation_guard"
)
assert original.count("'category.parameter.publish')") == 2
function(
    original.replace(
        "'category.parameter.publish')",
        "'category.parameter.publish','evidence.claim.record','evidence.claim.withdraw','proposal.share','ai.run.revert')",
    ),
    "m3_material_confirmation_guard()",
)

policy_share = """category_access(tenant_id,category_id) AND owner_id=scope_actor() AND scope_actor()=scope_requester()
 AND EXISTS(SELECT 1 FROM principals pr WHERE pr.tenant_id=proposals.tenant_id AND pr.id=scope_actor() AND pr.kind='human' AND pr.active)
 AND EXISTS(SELECT 1 FROM confirmations cp WHERE cp.tenant_id=proposals.tenant_id AND cp.category_id=proposals.category_id
 AND cp.actor_id=scope_actor() AND cp.operation='proposal.share' AND cp.subject_type='proposal' AND cp.subject_id=proposals.id
 AND cp.consumed AND cp.revision IN (proposals.revision,proposals.revision-1))"""
change(
    "CREATE POLICY m3_owner_share_update ON proposals FOR UPDATE TO pdos_next_app USING ("
    + policy_share
    + ") WITH CHECK ("
    + policy_share
    + ")",
    "DROP POLICY m3_owner_share_update ON proposals",
)
# Owner-sharing explicit audiences also needs category read rather than write.
change(
    "CREATE POLICY m3_owner_share_audience ON object_audiences FOR ALL TO pdos_next_app USING (object_type='proposals' AND owner_id=scope_actor() AND scope_actor()=scope_requester() AND category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM confirmations cp WHERE cp.tenant_id=object_audiences.tenant_id AND cp.category_id=object_audiences.category_id AND cp.operation='proposal.share' AND cp.subject_id=object_audiences.subject_id AND cp.actor_id=scope_actor() AND cp.consumed)) WITH CHECK (object_type='proposals' AND owner_id=scope_actor() AND scope_actor()=scope_requester() AND category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM confirmations cp WHERE cp.tenant_id=object_audiences.tenant_id AND cp.category_id=object_audiences.category_id AND cp.operation='proposal.share' AND cp.subject_id=object_audiences.subject_id AND cp.actor_id=scope_actor() AND cp.consumed))",
    "DROP POLICY m3_owner_share_audience ON object_audiences",
)

# Named owner actions can consume confirmations and persist their receipt atom
# without granting general category-write rights.
function(
    r"""
CREATE FUNCTION m3_evidence_named_actor(t uuid,c uuid,op text,sid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND scope_actor()=scope_requester() AND EXISTS(
 SELECT 1 FROM principals pr WHERE pr.tenant_id=t AND pr.id=scope_actor() AND pr.kind='human' AND pr.active)
 AND CASE op WHEN 'proposal.share' THEN EXISTS(SELECT 1 FROM proposals p WHERE p.tenant_id=t AND p.category_id=c AND p.id=sid AND p.owner_id=scope_actor())
 WHEN 'evidence.claim.withdraw' THEN m3_claim_withdrawer(t,c,sid) ELSE false END
$$;
""",
    "m3_evidence_named_actor(uuid,uuid,text,uuid)",
)
change(
    "CREATE POLICY m3_evidence_named_confirmation ON confirmations FOR ALL TO pdos_next_app USING (actor_id=scope_actor() AND m3_evidence_named_actor(tenant_id,category_id,operation,subject_id)) WITH CHECK (actor_id=scope_actor() AND m3_evidence_named_actor(tenant_id,category_id,operation,subject_id))",
    "DROP POLICY m3_evidence_named_confirmation ON confirmations",
)
change(
    "CREATE POLICY m3_evidence_named_receipt ON action_receipts FOR INSERT TO pdos_next_app WITH CHECK (actor_id=scope_actor() AND requester_id=scope_requester() AND m3_evidence_named_actor(tenant_id,category_id,operation,subject_id))",
    "DROP POLICY m3_evidence_named_receipt ON action_receipts",
)
for satellite in ("audit_entries", "outbox_events", "request_keys"):
    change(
        f"CREATE POLICY m3_evidence_named_receipt ON {satellite} FOR INSERT TO pdos_next_app WITH CHECK (actor_id=scope_actor() AND EXISTS(SELECT 1 FROM action_receipts r WHERE r.tenant_id={satellite}.tenant_id AND r.id={satellite}.receipt_id AND r.actor_id=scope_actor() AND m3_evidence_named_actor(r.tenant_id,r.category_id,r.operation,r.subject_id)))",
        f"DROP POLICY m3_evidence_named_receipt ON {satellite}",
    )

change(
    "CREATE POLICY m3_owner_share_revision ON proposal_revisions FOR INSERT TO pdos_next_app WITH CHECK (actor_id=scope_actor() AND run_id IS NULL AND m3_evidence_named_actor(tenant_id,category_id,'proposal.share',proposal_id) AND EXISTS(SELECT 1 FROM confirmations cp WHERE cp.tenant_id=proposal_revisions.tenant_id AND cp.category_id=proposal_revisions.category_id AND cp.operation='proposal.share' AND cp.subject_id=proposal_revisions.proposal_id AND cp.actor_id=scope_actor() AND cp.consumed AND cp.revision+1=proposal_revisions.revision))",
    "DROP POLICY m3_owner_share_revision ON proposal_revisions",
)

# Exactly restore the old product/Claim FK on downgrade.
old = next(
    x
    for x in CAT["constraints"]
    if x["table_name"] == "claim_consumptions"
    and "REFERENCES claims(tenant_id, product_id, id)" in x["sql"]
)
change(
    f'ALTER TABLE claim_consumptions DROP CONSTRAINT "{old["conname"]}"',
    f'ALTER TABLE claim_consumptions ADD CONSTRAINT "{old["conname"]}" {old["sql"]}',
)
change(
    "ALTER TABLE claim_consumptions ADD CONSTRAINT m3_claim_consumption_category_fk FOREIGN KEY(tenant_id,category_id,claim_id) REFERENCES claims(tenant_id,category_id,id)",
    "ALTER TABLE claim_consumptions DROP CONSTRAINT m3_claim_consumption_category_fk",
)

for table in ("claims", "claim_consumptions"):
    for row in CAT["policies"]:
        if row["tablename"] == table and row["policyname"] != "owner_internal":
            change(f'DROP POLICY "{row["policyname"]}" ON {table}', policy_restore(row))


def policy(name, table, verb, using=None, check=None):
    sql = f"CREATE POLICY {name} ON {table} FOR {verb} TO pdos_next_app"
    if using:
        sql += " USING (" + using + ")"
    if check:
        sql += " WITH CHECK (" + check + ")"
    change(sql, f"DROP POLICY {name} ON {table}")


policy("m3_claim_read", "claims", "SELECT", "m3_claim_reader(tenant_id,category_id,id)")
policy(
    "m3_claim_insert",
    "claims",
    "INSERT",
    check="category_access(tenant_id,category_id,true) AND human_owner_id=scope_requester()",
)
policy(
    "m3_claim_update",
    "claims",
    "UPDATE",
    "m3_claim_withdrawer(tenant_id,category_id,id) OR (human_owner_id=scope_requester() AND m3_claim_reader(tenant_id,category_id,id))",
    "m3_claim_withdrawer(tenant_id,category_id,id) OR human_owner_id=scope_requester()",
)
policy(
    "m3_consumption_read",
    "claim_consumptions",
    "SELECT",
    "m3_claim_reader(tenant_id,category_id,claim_id)",
)
policy(
    "m3_consumption_insert",
    "claim_consumptions",
    "INSERT",
    check="category_access(tenant_id,category_id) AND m3_claim_reader(tenant_id,category_id,claim_id) AND (category_access(tenant_id,category_id,true) OR EXISTS(SELECT 1 FROM proposal_decisions d WHERE d.tenant_id=claim_consumptions.tenant_id AND d.id=claim_consumptions.decision_id AND d.decided_by=scope_actor()))",
)
for table in TABLES:
    UP.append(
        f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY; ALTER TABLE {table.name} FORCE ROW LEVEL SECURITY; CREATE POLICY owner_internal ON {table.name} TO pdos_next_owner USING(true) WITH CHECK(true); REVOKE ALL ON {table.name} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch; GRANT SELECT,INSERT ON {table.name} TO pdos_next_app"
    )
policy(
    "m3_link_read",
    "evidence_links",
    "SELECT",
    "m3_evidence_target_reader(tenant_id,category_id,target_type,target_id)",
)
policy(
    "m3_link_insert",
    "evidence_links",
    "INSERT",
    check="category_access(tenant_id,category_id,true) AND m3_evidence_target_reader(tenant_id,category_id,target_type,target_id)",
)
policy(
    "m3_link_update",
    "evidence_links",
    "UPDATE",
    "m3_evidence_target_reader(tenant_id,category_id,target_type,target_id)",
    "m3_evidence_target_reader(tenant_id,category_id,target_type,target_id)",
)
UP.append("GRANT UPDATE ON evidence_links TO pdos_next_app")
policy(
    "m3_withdraw_read",
    "claim_withdrawals",
    "SELECT",
    "m3_claim_reader(tenant_id,category_id,claim_id)",
)
policy(
    "m3_withdraw_insert",
    "claim_withdrawals",
    "INSERT",
    check="actor_id=scope_actor() AND m3_claim_withdrawer(tenant_id,category_id,claim_id)",
)


def trigger(name, table, timing, ops, fn, deferred=False):
    prefix = "CREATE CONSTRAINT TRIGGER" if deferred else "CREATE TRIGGER"
    sql = f"{prefix} {name} {timing} {ops} ON {table}"
    if deferred:
        sql += " DEFERRABLE INITIALLY DEFERRED"
    sql += f" FOR EACH ROW EXECUTE FUNCTION {fn}()"
    change(sql, f"DROP TRIGGER {name} ON {table}")


trigger(
    "m3_evidence_claim_guard",
    "claims",
    "BEFORE",
    "INSERT OR UPDATE OR DELETE",
    "m3_evidence_claim_guard",
)
trigger(
    "m3_evidence_claim_atom", "claims", "AFTER", "INSERT OR UPDATE", "m3_evidence_claim_atom", True
)
trigger(
    "m3_withdraw_immutable", "claim_withdrawals", "BEFORE", "UPDATE OR DELETE", "m3_append_only"
)
trigger(
    "m3_evidence_withdraw_atom",
    "claim_withdrawals",
    "AFTER",
    "INSERT",
    "m3_evidence_withdraw_atom",
    True,
)
trigger(
    "m3_evidence_link_guard",
    "evidence_links",
    "BEFORE",
    "INSERT OR UPDATE OR DELETE",
    "m3_evidence_link_guard",
)
trigger(
    "m3_evidence_link_atom",
    "evidence_links",
    "AFTER",
    "INSERT OR UPDATE",
    "m3_evidence_link_atom",
    True,
)
trigger(
    "m3_evidence_consumption_guard",
    "claim_consumptions",
    "BEFORE",
    "INSERT OR UPDATE OR DELETE",
    "m3_evidence_consumption_guard",
)
trigger(
    "m3_evidence_consumption_atom",
    "claim_consumptions",
    "AFTER",
    "INSERT",
    "m3_evidence_consumption_atom",
    True,
)
trigger(
    "m3_evidence_audience_atom",
    "object_audiences",
    "AFTER",
    "INSERT OR UPDATE OR DELETE",
    "m3_evidence_audience_atom",
    True,
)
trigger(
    "m3_evidence_run_revert_atom",
    "agent_runs",
    "AFTER",
    "UPDATE",
    "m3_evidence_run_revert_atom",
    True,
)
trigger("m3_evidence_share_atom", "proposals", "AFTER", "UPDATE", "m3_evidence_share_atom", True)
trigger(
    "m3_evidence_decision_atom",
    "proposal_decisions",
    "AFTER",
    "INSERT",
    "m3_evidence_decision_atom",
    True,
)

# Internal functions have no callable app surface; only boolean RLS predicates
# expose narrowly filtered authorization answers.
for signature in FUNCTIONS:
    UP.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,pdos_agent")
for signature in (
    "m3_evidence_source_reader(uuid,uuid,text,uuid)",
    "m3_claim_reader(uuid,uuid,uuid)",
    "m3_claim_withdrawer(uuid,uuid,uuid)",
    "m3_evidence_target_reader(uuid,uuid,text,uuid)",
    "m3_claim_is_consumed(uuid,uuid,uuid)",
    "m3_claim_reference_states(uuid,uuid,uuid[])",
    "revert_subjects_consumed(uuid,uuid,jsonb,uuid[])",
    "m3_evidence_named_actor(uuid,uuid,text,uuid)",
):
    UP.append(f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_app")

# Tables with new facts, new source kinds or nonlegacy semantics cannot be erased.
REFUSE = """LOCK TABLE claims,claim_consumptions,evidence_links,claim_withdrawals,proposals,action_receipts IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM evidence_links) OR EXISTS(SELECT 1 FROM claim_withdrawals)
  OR EXISTS(SELECT 1 FROM claims WHERE product_id IS NULL OR artifact_id IS NULL OR receipt_id IS NOT NULL
   OR proposal_id IS NOT NULL OR run_id IS NOT NULL OR source_kind<>'artifact' OR origin<>'human'
   OR status='withdrawn' OR nature NOT IN ('observed','extracted','inferred') OR availability='not_applicable' OR vendor_claimed)
  OR EXISTS(SELECT 1 FROM claim_consumptions WHERE product_id IS NULL OR claim_version IS NOT NULL OR decision_id IS NOT NULL OR definition_id IS NOT NULL OR receipt_id IS NOT NULL)
  OR EXISTS(SELECT 1 FROM action_receipts WHERE operation IN ('proposal.share','evidence.link.create','evidence.claim.withdraw')) THEN
  RAISE EXCEPTION 'M3 evidence downgrade refuses persisted facts' USING ERRCODE='23514';
 END IF;
END $$;"""
# Downgrade order follows actual dependency removal, then old metadata restoration.
output = ROOT / "server/migrations/schema_s0_0733.py"
output.write_text(
    '# ruff: noqa: E501 -- frozen PostgreSQL definitions\n"""Scoped evidence facts, named withdrawal and sharing; frozen against s0_0732."""\n\nSCHEMA_SQL = '
    + repr(tuple(UP))
    + "\n\nDOWNGRADE_SQL = "
    + repr((REFUSE, *DOWN))
    + "\n"
)
print(f"Frozen {len(UP)} upgrade / {len(DOWN) + 1} downgrade statements into {output.name}")
