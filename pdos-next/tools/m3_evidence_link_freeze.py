# ruff: noqa: E501
"""Freeze 0735 Link atoms and historical identity checks without connecting to a DB."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Restore the exact live 0734 function definitions on downgrade.
CAT = json.loads((ROOT / ".local/m3-evidence-0734-catalog.json").read_text())
prior_module = ast.parse((ROOT / "server/migrations/schema_s0_0734.py").read_text())
prior_up = next(
    ast.literal_eval(n.value)
    for n in prior_module.body
    if isinstance(n, ast.Assign) and n.targets[0].id == "SCHEMA_SQL"
)
UP, DOWN = [], []


def replace_function(name, amended):
    old = next(row["sql"] for row in CAT["functions"] if row["proname"] == name)
    assert not any(
        f"FUNCTION {name}(" in sql or f"FUNCTION public.{name}(" in sql for sql in prior_up
    )
    assert amended != old
    UP.append(amended)
    DOWN.insert(0, old)


UP.append(r"""
CREATE FUNCTION m3_evidence_proposal_identity_tokens(t uuid,c uuid,pid uuid) RETURNS SETOF text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 WITH registered_data AS (
  SELECT p.source_refs||p.context_refs data FROM proposals p WHERE p.tenant_id=t AND p.category_id=c AND p.id=pid
  UNION ALL SELECT v.source_refs FROM proposal_item_versions v WHERE v.tenant_id=t AND v.category_id=c AND v.proposal_id=pid
  UNION ALL SELECT v.changed_items FROM proposal_revisions v WHERE v.tenant_id=t AND v.category_id=c AND v.proposal_id=pid
  UNION ALL SELECT jsonb_build_array(s.frozen_document,s.context_refs) FROM proposal_submissions s
   WHERE s.tenant_id=t AND s.category_id=c AND s.proposal_id=pid
  UNION ALL SELECT jsonb_build_object('type',l.evidence_type,'id',l.evidence_id) FROM evidence_links l
   JOIN proposal_items i ON i.tenant_id=l.tenant_id AND i.category_id=l.category_id AND i.id=l.target_id
   WHERE l.tenant_id=t AND l.category_id=c AND l.target_type='proposal_item' AND i.proposal_id=pid
 ), referenced_claims AS (
  SELECT unnest(m3_evidence_reference_ids(data,'claim')) id FROM registered_data
 ), artifact_ids AS (
  SELECT ps.source_id id FROM proposal_sources ps WHERE ps.tenant_id=t AND ps.category_id=c AND ps.proposal_id=pid AND ps.source_type='original'
  UNION SELECT unnest(m3_evidence_reference_ids(data,'artifact')||m3_evidence_reference_ids(data,'original')) FROM registered_data
  UNION SELECT k.artifact_id FROM claims k JOIN referenced_claims ref ON ref.id=k.id
   WHERE k.tenant_id=t AND k.category_id=c AND k.source_kind='artifact'
  UNION SELECT (source->>'artifact_id')::uuid FROM claims k
   JOIN agent_runs ar ON ar.tenant_id=k.tenant_id AND ar.category_id=k.category_id AND ar.id=k.run_id AND ar.proposal_id=k.proposal_id
    AND ar.requester_id=k.human_owner_id AND ar.writer_id=k.writer_id
   CROSS JOIN LATERAL jsonb_array_elements(ar.read_sources) source
   WHERE k.tenant_id=t AND k.category_id=c AND k.proposal_id=pid AND k.privacy='private' AND ar.private_context
 ), registered_originals AS (
  SELECT a.id artifact_id,o.id original_id,o.filename FROM artifact_ids ref
   JOIN artifact_versions a ON a.tenant_id=t AND a.category_id=c AND a.id=ref.id
   JOIN uploaded_originals o ON o.tenant_id=a.tenant_id AND o.category_id=a.category_id AND o.id=a.original_id
 )
 SELECT lower(filename) FROM registered_originals UNION SELECT artifact_id::text FROM registered_originals
 UNION SELECT original_id::text FROM registered_originals
$$;
""")
UP.append(
    "REVOKE ALL ON FUNCTION m3_evidence_proposal_identity_tokens(uuid,uuid,uuid) FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
)
DOWN.append("DROP FUNCTION m3_evidence_proposal_identity_tokens(uuid,uuid,uuid)")

old = next(row["sql"] for row in CAT["functions"] if row["proname"] == "m3_atom_guard")
marker = " IF r.category_id<>NEW.category_id OR r.subject_type<>'proposal'"
branch = r""" IF TG_TABLE_NAME='proposal_revisions' AND r.operation='evidence.link.create' THEN
  IF r.category_id IS DISTINCT FROM NEW.category_id OR r.product_id IS NOT NULL
   OR r.subject_type IS DISTINCT FROM 'evidence_link' OR r.subject_revision IS DISTINCT FROM 1
   OR r.actor_id IS DISTINCT FROM scope_actor() OR r.requester_id IS DISTINCT FROM scope_requester()
   OR r.run_id IS NOT NULL OR NEW.actor_id IS DISTINCT FROM r.actor_id OR NEW.run_id IS DISTINCT FROM r.agent_run_id
   OR p.category_id IS DISTINCT FROM NEW.category_id OR p.owner_id IS DISTINCT FROM r.requester_id
   OR p.status NOT IN ('draft','returned') OR p.revision IS DISTINCT FROM NEW.revision
   OR NEW.changed_items IS DISTINCT FROM '[]'::jsonb
   OR NOT EXISTS(SELECT 1 FROM proposal_revisions prior WHERE prior.tenant_id=NEW.tenant_id
    AND prior.category_id=NEW.category_id AND prior.proposal_id=NEW.proposal_id AND prior.revision=NEW.revision-1)
   OR NOT EXISTS(SELECT 1 FROM evidence_links link JOIN proposal_items item ON item.tenant_id=link.tenant_id
    AND item.category_id=link.category_id AND item.id=link.target_id
    JOIN action_receipts receipt ON receipt.tenant_id=link.tenant_id AND receipt.id=link.receipt_id
    JOIN proposal_revisions revision ON revision.tenant_id=link.tenant_id AND revision.receipt_id=receipt.id
    JOIN proposals current_proposal ON current_proposal.tenant_id=item.tenant_id AND current_proposal.id=item.proposal_id
    WHERE link.tenant_id=NEW.tenant_id AND link.category_id=NEW.category_id AND link.id=r.subject_id
     AND link.receipt_id=r.id AND link.target_type='proposal_item' AND link.reverted_by_receipt_id IS NULL
     AND link.run_id IS NOT DISTINCT FROM r.agent_run_id AND item.proposal_id=NEW.proposal_id
     AND NOT item.removed AND item.current_version=link.target_version AND revision.id=NEW.id
     AND revision.proposal_id=NEW.proposal_id AND revision.revision=NEW.revision
     AND link.xmin=receipt.xmin AND revision.xmin=receipt.xmin AND current_proposal.xmin=receipt.xmin
     AND r.result->>'link_id'=link.id::text
     AND r.result->'target'=jsonb_build_object('type',link.target_type,'id',link.target_id,'version',link.target_version))
   OR (SELECT count(*) FROM proposal_revisions revision WHERE revision.tenant_id=NEW.tenant_id AND revision.receipt_id=r.id)<>1
   OR p.private_source_count<>(SELECT count(*) FROM proposal_sources ps WHERE ps.tenant_id=NEW.tenant_id AND ps.proposal_id=p.id AND ps.privacy='private')
   OR p.effective_visibility IS DISTINCT FROM (CASE WHEN p.private_source_count>0 THEN 'private' ELSE p.visibility END)
   OR EXISTS((SELECT source_type,source_id,source_version,privacy,ref_count FROM m3_evidence_proposal_roots(NEW.tenant_id,NEW.category_id,p.id)
      EXCEPT SELECT source_type,source_id,source_version,privacy,ref_count::bigint FROM proposal_sources WHERE tenant_id=NEW.tenant_id AND proposal_id=p.id)
     UNION ALL (SELECT source_type,source_id,source_version,privacy,ref_count::bigint FROM proposal_sources WHERE tenant_id=NEW.tenant_id AND proposal_id=p.id
      EXCEPT SELECT source_type,source_id,source_version,privacy,ref_count FROM m3_evidence_proposal_roots(NEW.tenant_id,NEW.category_id,p.id))) THEN
   RAISE EXCEPTION 'evidence link proposal receipt or projection mismatch' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 END IF;
"""
assert marker in old
replace_function("m3_atom_guard", old.replace(marker, branch + marker, 1))

old = next(row["sql"] for row in CAT["functions"] if row["proname"] == "m3_evidence_share_atom")
marker = "BEGIN\n IF NEW.visibility IS NOT DISTINCT FROM OLD.visibility"
branch = r"""BEGIN
 -- An evidence association advances only the document revision and source
 -- projection. Its receipt is checked by m3_atom_guard and its own Link atom.
 IF NEW.revision<>OLD.revision AND EXISTS(SELECT 1 FROM proposal_revisions pv
  JOIN action_receipts receipt ON receipt.tenant_id=pv.tenant_id AND receipt.id=pv.receipt_id
  WHERE pv.tenant_id=NEW.tenant_id AND pv.category_id=NEW.category_id AND pv.proposal_id=NEW.id
   AND pv.revision=NEW.revision AND receipt.operation='evidence.link.create') THEN
  IF NEW.revision<>OLD.revision+1
   OR (to_jsonb(NEW)-ARRAY['revision','private_source_count','effective_visibility']) IS DISTINCT FROM
      (to_jsonb(OLD)-ARRAY['revision','private_source_count','effective_visibility']) THEN
   RAISE EXCEPTION 'evidence link cannot change proposal content' USING ERRCODE='23514'; END IF;
  RETURN NULL;
 END IF;
 IF NEW.visibility IS NOT DISTINCT FROM OLD.visibility"""
assert marker in old
amended = old.replace(marker, branch, 1)
marker = "   UNION SELECT NEW.id::text"
assert marker in amended
amended = amended.replace(
    marker,
    "   UNION SELECT identity_token FROM m3_evidence_proposal_identity_tokens(NEW.tenant_id,NEW.category_id,NEW.id) identity_token\n"
    + marker,
    1,
)
replace_function("m3_evidence_share_atom", amended)

output = ROOT / "server/migrations/schema_s0_0735.py"
output.write_text(
    '# ruff: noqa: E501 -- frozen PostgreSQL definitions\n"""Link document atoms and historical sharing identity checks after s0_0734."""\n\nSCHEMA_SQL = '
    + repr(tuple(UP))
    + "\n\nDOWNGRADE_SQL = "
    + repr(tuple(DOWN))
    + "\n"
)
print(f"Frozen {len(UP)} upgrade / {len(DOWN)} downgrade statements into {output.name}")
