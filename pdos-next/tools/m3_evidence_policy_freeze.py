# ruff: noqa: E501
"""Freeze 0734 policy-only repair from the actual 0733 catalog; no database calls."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = json.loads((ROOT / ".local/m3-evidence-0733-catalog.json").read_text())
UP, DOWN = [], []


def function(body, signature):
    assert not any(row["proname"] == signature.split("(")[0] for row in CAT["functions"])
    UP.extend(
        [
            body,
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch",
            f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_app",
        ]
    )
    DOWN.insert(0, f"DROP FUNCTION {signature}")


def replace_policy(table, name, using=None, check=None):
    prior = next(
        row for row in CAT["policies"] if row["tablename"] == table and row["policyname"] == name
    )
    start = (
        f'CREATE POLICY "{name}" ON "{table}" AS {prior["permissive"]} FOR {prior["cmd"]} TO '
        + ",".join(prior["roles"])
    )
    old, new = start, start
    for key, keyword, expr in (("qual", "USING", using), ("with_check", "WITH CHECK", check)):
        if prior[key] is not None:
            old += f" {keyword} ({prior[key]})"
            assert expr is not None
            new += f" {keyword} ({expr})"
        else:
            assert expr is None
    drop = f'DROP POLICY "{name}" ON "{table}"'
    UP.extend([drop, new])
    DOWN[:0] = [drop, old]


function(
    r"""
CREATE FUNCTION m3_evidence_share_pending(t uuid,c uuid,pid uuid,prior_revision integer) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT m3_evidence_named_actor(t,c,'proposal.share',pid) AND EXISTS(
  SELECT 1 FROM proposals p JOIN confirmations cp ON cp.tenant_id=p.tenant_id AND cp.category_id=p.category_id
   AND cp.subject_id=p.id WHERE p.tenant_id=t AND p.category_id=c AND p.id=pid AND p.owner_id=scope_actor()
   AND cp.operation='proposal.share' AND cp.subject_type='proposal' AND cp.actor_id=scope_actor()
   AND cp.product_id IS NULL AND cp.consumed AND cp.xmin::text::bigint=txid_current()%4294967296
   AND (prior_revision IS NULL OR cp.revision=prior_revision) AND p.revision IN (cp.revision,cp.revision+1)
   AND cp.snapshot->'payload'->>'proposal_id'=p.id::text
   AND (cp.snapshot->'payload'->>'expected_revision')::integer=cp.revision)
$$;
""",
    "m3_evidence_share_pending(uuid,uuid,uuid,integer)",
)

function(
    r"""
CREATE FUNCTION m3_evidence_named_receipt_policy(t uuid,c uuid,op text,sid uuid,actor uuid,requester uuid,proof_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT actor=scope_actor() AND requester=scope_requester() AND actor=requester
  AND m3_evidence_named_actor(t,c,op,sid) AND EXISTS(
  SELECT 1 FROM confirmations cp WHERE cp.tenant_id=t AND cp.category_id=c AND cp.id=proof_id
   AND cp.actor_id=actor AND cp.operation=op AND cp.subject_id=sid AND cp.consumed
   AND cp.subject_type=(CASE WHEN op='proposal.share' THEN 'proposal' WHEN op='evidence.claim.withdraw' THEN 'claim' END)
   AND cp.xmin::text::bigint=txid_current()%4294967296)
$$;
""",
    "m3_evidence_named_receipt_policy(uuid,uuid,text,uuid,uuid,uuid,uuid)",
)

function(
    r"""
CREATE FUNCTION m3_evidence_satellite_policy(t uuid,c uuid,rid uuid,mode text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND EXISTS(SELECT 1 FROM action_receipts r WHERE r.tenant_id=t AND r.category_id=c AND r.id=rid
  AND r.actor_id=scope_actor() AND r.requester_id=scope_requester()
  AND CASE mode WHEN 'named' THEN
   r.xmin::text::bigint=txid_current()%4294967296
   AND m3_evidence_named_receipt_policy(t,c,r.operation,r.subject_id,r.actor_id,r.requester_id,r.confirmation_id)
  WHEN 'decision' THEN r.operation='proposal.g0.decide' AND r.subject_type='proposal'
   AND m3_proposal_reader(t,c,r.subject_id)
  ELSE false END)
$$;
""",
    "m3_evidence_satellite_policy(uuid,uuid,uuid,text)",
)

function(
    r"""
CREATE FUNCTION m3_evidence_consumption_policy(t uuid,c uuid,kid uuid,did uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT category_access(t,c) AND m3_claim_reader(t,c,kid) AND (category_access(t,c,true)
  OR EXISTS(SELECT 1 FROM proposal_decisions d WHERE d.tenant_id=t AND d.category_id=c AND d.id=did
   AND d.decided_by=scope_actor() AND scope_actor()=scope_requester()))
$$;
""",
    "m3_evidence_consumption_policy(uuid,uuid,uuid,uuid)",
)

share = "owner_id=scope_actor() AND (m3_evidence_share_pending(tenant_id,category_id,id,revision) OR m3_evidence_share_pending(tenant_id,category_id,id,revision-1))"
replace_policy("proposals", "m3_owner_share_update", share, share)
audience = "object_type='proposals' AND owner_id=scope_actor() AND m3_evidence_share_pending(tenant_id,category_id,subject_id,NULL)"
replace_policy("object_audiences", "m3_owner_share_audience", audience, audience)
replace_policy(
    "proposal_revisions",
    "m3_owner_share_revision",
    check="actor_id=scope_actor() AND run_id IS NULL AND m3_evidence_share_pending(tenant_id,category_id,proposal_id,revision-1)",
)
replace_policy(
    "action_receipts",
    "m3_evidence_named_receipt",
    check="m3_evidence_named_receipt_policy(tenant_id,category_id,operation,subject_id,actor_id,requester_id,confirmation_id)",
)
for table, previous_policy in (
    ("audit_entries", "m3_audit"),
    ("outbox_events", "m3_outbox"),
    ("request_keys", "m3_request_key"),
):
    replace_policy(
        table,
        "m3_evidence_named_receipt",
        check="actor_id=scope_actor() AND m3_evidence_satellite_policy(tenant_id,category_id,receipt_id,'named')",
    )
    replace_policy(
        table,
        previous_policy,
        check="actor_id=scope_actor() AND m3_evidence_satellite_policy(tenant_id,category_id,receipt_id,'decision')",
    )
replace_policy(
    "claim_consumptions",
    "m3_consumption_insert",
    check="m3_evidence_consumption_policy(tenant_id,category_id,claim_id,decision_id)",
)

# Existing Confirmation and domain read policies already call bounded SECURITY
# DEFINER predicates. No new policy contains a cross-table subquery, and all
# 0733 deferred C/R guards remain installed and unchanged.
for sql in UP:
    if sql.startswith("CREATE POLICY"):
        assert "SELECT " not in sql
output = ROOT / "server/migrations/schema_s0_0734.py"
output.write_text(
    '# ruff: noqa: E501 -- frozen PostgreSQL definitions\n"""Bounded evidence policy predicates; frozen against actual s0_0733."""\n\nSCHEMA_SQL = '
    + repr(tuple(UP))
    + "\n\nDOWNGRADE_SQL = "
    + repr(tuple(DOWN))
    + "\n"
)
print(f"Frozen {len(UP)} upgrade / {len(DOWN)} downgrade statements into {output.name}")
