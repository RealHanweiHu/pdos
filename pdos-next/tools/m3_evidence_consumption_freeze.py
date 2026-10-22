# ruff: noqa: E501
"""Freeze 0737 reverse Link atoms and signed lifecycle accounting from actual 0736."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = json.loads((ROOT / ".local/m3-evidence-0736-catalog.json").read_text())
UP, DOWN = [], []


def replace_function(name, amended):
    prior = next(row["sql"] for row in CAT["functions"] if row["proname"] == name)
    assert amended != prior
    UP.append(amended)
    DOWN.insert(0, prior)


old = next(row["sql"] for row in CAT["functions"] if row["proname"] == "lifecycle_reference_gate")
marker = "        p=(payload->>'product_id')::uuid; t=(payload->>'tenant_id')::uuid;"
assert marker in old
routing = """        -- Named G0 Claim consumption is checked and counted by its own deferred
        -- atom after the actual common receipt exists. All other paths retain
        -- the original caller-privileged lifecycle behavior.
        IF TG_TABLE_NAME='claim_consumptions' AND TG_OP='INSERT'
          AND (payload->>'decision_id' IS NOT NULL OR payload->>'definition_id' IS NOT NULL) THEN
          RETURN NEW;
        END IF;
"""
replace_function("lifecycle_reference_gate", old.replace(marker, routing + marker, 1))

UP.append(r"""
CREATE FUNCTION m3_evidence_consumption_lifecycle_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE decision proposal_decisions; definition definition_revisions; receipt action_receipts;
 subject_product products; rx xid; payload jsonb;
BEGIN
 IF NEW.decision_id IS NULL AND NEW.definition_id IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO STRICT receipt FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF NEW.decision_id IS NOT NULL THEN
  SELECT * INTO STRICT decision FROM proposal_decisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.decision_id;
 ELSE
  SELECT actual_decision.* INTO STRICT decision FROM proposal_decisions actual_decision
   JOIN definition_revisions actual_definition ON actual_definition.tenant_id=actual_decision.tenant_id AND actual_definition.g0_decision_id=actual_decision.id
   WHERE actual_decision.tenant_id=NEW.tenant_id AND actual_decision.category_id=NEW.category_id AND actual_definition.id=NEW.definition_id;
 END IF;
 SELECT * INTO STRICT definition FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id
  AND id=coalesce(NEW.definition_id,decision.created_definition_id);
 SELECT * INTO STRICT subject_product FROM products WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.product_id FOR UPDATE;
 SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=receipt.id;
 IF scope_actor() IS DISTINCT FROM scope_requester() OR receipt.actor_id IS DISTINCT FROM scope_actor()
  OR receipt.requester_id IS DISTINCT FROM scope_requester() OR receipt.agent_run_id IS NOT NULL OR receipt.run_id IS NOT NULL
  OR receipt.operation IS DISTINCT FROM 'proposal.g0.decide' OR receipt.category_id IS DISTINCT FROM NEW.category_id
  OR receipt.subject_type IS DISTINCT FROM 'proposal' OR receipt.subject_id IS DISTINCT FROM decision.proposal_id
  OR decision.outcome IS DISTINCT FROM 'approved' OR decision.decided_by IS DISTINCT FROM receipt.actor_id
  OR decision.receipt_id IS DISTINCT FROM receipt.id OR decision.created_product_id IS DISTINCT FROM NEW.product_id
  OR decision.created_definition_id IS DISTINCT FROM definition.id OR definition.product_id IS DISTINCT FROM NEW.product_id
  OR definition.g0_decision_id IS DISTINCT FROM decision.id OR definition.sealed IS DISTINCT FROM true
  OR NEW.consumer_type NOT IN ('proposal_decision','g0_decision','definition','definition_revision')
  OR NEW.consumer_id NOT IN (decision.id,definition.id)
  OR category_access(NEW.tenant_id,NEW.category_id) IS DISTINCT FROM true
  OR NOT EXISTS(SELECT 1 FROM principals person WHERE person.tenant_id=NEW.tenant_id AND person.id=scope_actor() AND person.active AND person.kind='human')
  OR rx IS DISTINCT FROM (SELECT xmin FROM claim_consumptions WHERE tenant_id=NEW.tenant_id AND id=NEW.id)
  OR rx IS DISTINCT FROM (SELECT xmin FROM proposal_decisions WHERE tenant_id=NEW.tenant_id AND id=decision.id)
  OR rx IS DISTINCT FROM (SELECT xmin FROM definition_revisions WHERE tenant_id=NEW.tenant_id AND id=definition.id)
  OR rx IS DISTINCT FROM (SELECT xmin FROM products WHERE tenant_id=NEW.tenant_id AND id=subject_product.id) THEN
  RAISE EXCEPTION 'signed consumption lifecycle requires actual G0 atom' USING ERRCODE='23514'; END IF;
 payload=to_jsonb(NEW);
 IF EXISTS(SELECT 1 FROM lifecycle_objects lifecycle WHERE lifecycle.product_id=NEW.product_id
  AND lifecycle.tenant_id=NEW.tenant_id
  AND ((lifecycle.state->'value'->>'pending_intent_id') IS NOT NULL
   OR lifecycle.state->'value'->>'disposition' IN ('quarantined','unknown','purged'))
  AND position(lifecycle.id::text IN payload::text)>0) THEN
  RAISE EXCEPTION 'Pending or isolated original prohibits new references'; END IF;
 UPDATE products SET lifecycle_epoch=lifecycle_epoch+1 WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.product_id;
 RETURN NULL;
END $$;
""")
UP.extend(
    [
        "REVOKE ALL ON FUNCTION m3_evidence_consumption_lifecycle_atom() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
        "CREATE CONSTRAINT TRIGGER m3_evidence_consumption_lifecycle_atom AFTER INSERT ON claim_consumptions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION m3_evidence_consumption_lifecycle_atom()",
    ]
)
DOWN[:0] = [
    "DROP TRIGGER m3_evidence_consumption_lifecycle_atom ON claim_consumptions",
    "DROP FUNCTION m3_evidence_consumption_lifecycle_atom()",
]

old = next(row["sql"] for row in CAT["functions"] if row["proname"] == "m3_evidence_link_atom")
marker = " ELSE RAISE EXCEPTION 'evidence link imported path unavailable' USING ERRCODE='23514'; END IF;\n RETURN NULL;"
assert marker in old
reverse = r""" ELSE RAISE EXCEPTION 'evidence link imported path unavailable' USING ERRCODE='23514'; END IF;
 IF NEW.target_type='proposal_item' THEN
  IF NOT EXISTS(SELECT 1 FROM proposal_revisions document_revision
    JOIN action_receipts actual_receipt ON actual_receipt.tenant_id=document_revision.tenant_id AND actual_receipt.id=document_revision.receipt_id
    JOIN proposals current_proposal ON current_proposal.tenant_id=document_revision.tenant_id AND current_proposal.id=document_revision.proposal_id
    JOIN evidence_links actual_link ON actual_link.tenant_id=actual_receipt.tenant_id AND actual_link.id=actual_receipt.subject_id
    WHERE document_revision.tenant_id=NEW.tenant_id AND document_revision.category_id=NEW.category_id
     AND document_revision.proposal_id=p.id AND document_revision.receipt_id=r.id
     AND document_revision.revision=current_proposal.revision AND document_revision.changed_items='[]'::jsonb
     AND document_revision.actor_id=r.actor_id AND document_revision.run_id IS NOT DISTINCT FROM r.agent_run_id
     AND actual_link.id=NEW.id AND actual_link.receipt_id=r.id
     AND document_revision.xmin=actual_receipt.xmin AND current_proposal.xmin=actual_receipt.xmin AND actual_link.xmin=actual_receipt.xmin
     AND EXISTS(SELECT 1 FROM proposal_revisions prior WHERE prior.tenant_id=document_revision.tenant_id
      AND prior.proposal_id=document_revision.proposal_id AND prior.revision=document_revision.revision-1))
   OR (SELECT count(*) FROM proposal_revisions document_revision WHERE document_revision.tenant_id=NEW.tenant_id AND document_revision.receipt_id=r.id)<>1
   OR p.private_source_count<>(SELECT count(*) FROM proposal_sources ps WHERE ps.tenant_id=NEW.tenant_id AND ps.proposal_id=p.id AND ps.privacy='private')
   OR p.effective_visibility IS DISTINCT FROM (CASE WHEN p.private_source_count>0 THEN 'private' ELSE p.visibility END)
   OR EXISTS((SELECT source_type,source_id,source_version,privacy,ref_count FROM m3_evidence_proposal_roots(NEW.tenant_id,NEW.category_id,p.id)
      EXCEPT SELECT source_type,source_id,source_version,privacy,ref_count::bigint FROM proposal_sources WHERE tenant_id=NEW.tenant_id AND proposal_id=p.id)
     UNION ALL (SELECT source_type,source_id,source_version,privacy,ref_count::bigint FROM proposal_sources WHERE tenant_id=NEW.tenant_id AND proposal_id=p.id
      EXCEPT SELECT source_type,source_id,source_version,privacy,ref_count FROM m3_evidence_proposal_roots(NEW.tenant_id,NEW.category_id,p.id))) THEN
   RAISE EXCEPTION 'evidence link missing proposal revision or projection' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;"""
replace_function("m3_evidence_link_atom", old.replace(marker, reverse, 1))

output = ROOT / "server/migrations/schema_s0_0737.py"
output.write_text(
    '# ruff: noqa: E501 -- frozen PostgreSQL definitions\n"""Signed G0 lifecycle accounting and reverse evidence Link projection atoms."""\n\nSCHEMA_SQL = '
    + repr(tuple(UP))
    + "\n\nDOWNGRADE_SQL = "
    + repr(tuple(DOWN))
    + "\n"
)
print(f"Frozen {len(UP)} upgrade / {len(DOWN)} downgrade statements into {output.name}")
