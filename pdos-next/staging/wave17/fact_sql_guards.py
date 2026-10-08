"""Unapplied, exact-head25 guard preparation; this module never executes SQL.

Root supplies actual pg_get_functiondef observations and owns table DDL,
metadata, registry, trusted importers, seven live gates and PostgreSQL checks.
SQL snapshots do not grant issuer/professional/source-byte qualifications.
"""

# ruff: noqa: E501 -- preserve auditable literal SQL and exact observed anchors

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType


class GuardPreparationError(ValueError):
    pass


FACT_TABLES = (
    "capa_verification_rule_facts",
    "capa_observation_facts",
    "capa_named_verification_reviews",
)
CURRENT_TABLES = ("capa_current_verification_rules", "capa_current_observations")
CANDIDATE_TABLE = "capa_verification_evidence"
LIFECYCLE_TABLES = FACT_TABLES + CURRENT_TABLES
PRESERVED_FUNCTIONS = (
    "assert_quality_followup_receipt(uuid,uuid,uuid,integer,text,text,uuid,text,text)",
    "require_quality_followup_atom()",
)
REPLACED_FUNCTIONS = (
    "assert_quality_followup_proof(uuid,uuid,uuid,text,jsonb,timestamptz)",
    "protect_quality_followup_confirmation()",
    "require_quality_followup_consumption_atom()",
    "assert_quality_change_receipt(uuid,uuid,uuid,integer,text,text,uuid,text)",
)
# Root's real head25, READ ONLY observation; not hashes of migration text.
EXPECTED_DEFINITIONS_SHA256 = MappingProxyType(
    {
        REPLACED_FUNCTIONS[0]: "3804a6762816a5a4bbb92c4055637f682dddc6fb9c42cb7489d8ca44ae047fe0",
        REPLACED_FUNCTIONS[1]: "50041550ae20c84c36b09df868373ca4b100e7a02af6fbd892448b3a8aca89bb",
        REPLACED_FUNCTIONS[2]: "958a891cdf688705c27b501d81df876aa392d5f473a79c30d0821a6513f09ee6",
        REPLACED_FUNCTIONS[3]: "664ed1b5bc62c9558dfe2b1b6d60e92ae91a399a7c1922fef174e9521caa0685",
        PRESERVED_FUNCTIONS[0]: "7dcf70ba1b333572e7d4afc08c0eae123310ba6e4f639c81d116178f1218aa3b",
        PRESERVED_FUNCTIONS[1]: "af47a61163221c81b2c7f40745cc08163cdd70a4d26cced24d1c17f03bc9cb2c",
    }
)
OPERATIONS = MappingProxyType(
    {
        "quality.capa.verification.rule.import": (
            "capa_verification_rule",
            "CapaVerificationRulePublished",
            "host_import",
        ),
        "quality.capa.observation.record": ("capa_observation", "CapaObservationRecorded", "T1"),
        "quality.capa.verification.review": (
            "capa_named_verification_review",
            "CapaVerificationReviewed",
            "T2",
        ),
        "quality.capa.verification.candidate.record": (
            "capa_verification_candidate",
            "CapaVerificationCandidateRecorded",
            "T1",
        ),
    }
)
PUBLIC_PROOF_OPERATIONS = tuple(
    op for op, (_, _, tier) in OPERATIONS.items() if tier != "host_import"
)
NEW_FUNCTION_SIGNATURES = (
    "require_capa_publication_receipt_atom()",
    "require_capa_publication_atom()",
    "assert_capa_publication_atom(text,uuid,uuid)",
    "protect_capa_fact_current()",
    "assert_capa_fact_origin(uuid,uuid,uuid,uuid,uuid,uuid,integer,text,text,jsonb,jsonb,text,uuid)",
    "assert_capa_fact_source_closure(uuid,uuid,jsonb,jsonb,jsonb,text,uuid)",
)
OLD_PROOF_OPERATIONS_SQL = "('quality.issue.root_cause.decide','quality.capa.actions.complete','quality.capa.followup.link')"


@dataclass(frozen=True)
class SqlGuardPlan:
    """Statements only. Parent FK/table DDL and actual installation are Root-owned."""

    preflight: tuple[str, ...]
    replace_functions: tuple[str, ...]
    new_functions: tuple[str, ...]
    new_triggers: tuple[str, ...]
    permissions: tuple[str, ...]
    rollback_preflight: tuple[str, ...]
    rollback_guards: tuple[str, ...]
    restore_functions: tuple[str, ...]
    installed_definition_sha256: tuple[tuple[str, str], ...]
    preserved_functions: tuple[str, ...] = PRESERVED_FUNCTIONS
    lifecycle_tables: tuple[str, ...] = LIFECYCLE_TABLES
    authorized: bool = False


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise GuardPreparationError("Exact reviewed SQL anchor is absent or ambiguous")
    return text.replace(old, new, 1)


def _quoted(values) -> str:
    # Only internal closed constants reach this formatter.
    return "(" + ",".join("'" + value + "'" for value in values) + ")"


def _target_union(alias: str) -> str:
    if alias not in {"c", "NEW"}:
        raise GuardPreparationError("Unsupported internal proof alias")
    return f"""    UNION ALL SELECT product_id,writer_id,operation FROM capa_observation_facts
      WHERE tenant_id={alias}.tenant_id AND shared_proof_id={alias}.id
    UNION ALL SELECT product_id,writer_id,operation FROM capa_named_verification_reviews
      WHERE tenant_id={alias}.tenant_id AND shared_proof_id={alias}.id
    UNION ALL SELECT product_id,writer_id,'quality.capa.verification.candidate.record'::text
      FROM capa_verification_evidence WHERE tenant_id={alias}.tenant_id
      AND input_snapshot->'shared_proof'->>'id'={alias}.id::text"""


def _expanded_functions(definitions):
    proof = definitions[REPLACED_FUNCTIONS[0]]
    proof = _replace_once(
        proof,
        "WHEN 'quality.capa.followup.link' THEN 'T1' END;",
        "WHEN 'quality.capa.followup.link' THEN 'T1'\n"
        "    WHEN 'quality.capa.observation.record' THEN 'T1'\n"
        "    WHEN 'quality.capa.verification.review' THEN 'T2'\n"
        "    WHEN 'quality.capa.verification.candidate.record' THEN 'T1' END;",
    )
    proof = _replace_once(
        proof,
        "  ) u;",
        "    UNION ALL SELECT id FROM capa_observation_facts WHERE tenant_id=tid AND shared_proof_id=c.id\n"
        "    UNION ALL SELECT id FROM capa_named_verification_reviews WHERE tenant_id=tid AND shared_proof_id=c.id\n"
        "    UNION ALL SELECT id FROM capa_verification_evidence WHERE tenant_id=tid\n"
        "      AND input_snapshot->'shared_proof'->>'id'=c.id::text\n  ) u;",
    )
    scoped = _quoted(
        (
            "quality.issue.root_cause.decide",
            "quality.capa.actions.complete",
            "quality.capa.followup.link",
        )
        + PUBLIC_PROOF_OPERATIONS
    )
    transition = definitions[REPLACED_FUNCTIONS[1]]
    if transition.count(OLD_PROOF_OPERATIONS_SQL) != 2:
        raise GuardPreparationError("Exact two transition scope anchors required")
    transition = transition.replace(OLD_PROOF_OPERATIONS_SQL, scoped)
    reciprocal = _replace_once(definitions[REPLACED_FUNCTIONS[2]], OLD_PROOF_OPERATIONS_SQL, scoped)
    reciprocal = _replace_once(reciprocal, "  ) u;", _target_union("c") + "\n  ) u;")
    receipt = definitions[REPLACED_FUNCTIONS[3]]
    extra = "\n".join(f"    WHEN '{op}' THEN '{value[1]}'" for op, value in OPERATIONS.items())
    receipt = _replace_once(
        receipt,
        "WHEN 'quality.capa.followup.link' THEN 'capa.followup_linked' END;",
        "WHEN 'quality.capa.followup.link' THEN 'capa.followup_linked'\n" + extra + " END;",
    )
    return proof, transition, reciprocal, receipt


SOURCE_SQL = r"""
CREATE FUNCTION public.assert_capa_fact_source_closure(tid uuid, pid uuid, sources jsonb,
  reads jsonb, basis jsonb, audience text, owner uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE x jsonb; b jsonb;
BEGIN
  IF NOT COALESCE(jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0
    AND jsonb_typeof(reads)='array' AND jsonb_array_length(reads) BETWEEN 1 AND 20
    AND jsonb_typeof(basis)='array' AND jsonb_array_length(basis)=jsonb_array_length(reads),false) THEN
    RAISE EXCEPTION 'CAPA fact requires complete bounded source arrays'; END IF;
  IF (SELECT count(DISTINCT read_element.value->>'artifact_id')
      FROM jsonb_array_elements(reads) AS read_element(value))
       <>jsonb_array_length(reads)
    OR (SELECT count(DISTINCT basis_element.value->>'id')
        FROM jsonb_array_elements(basis) AS basis_element(value))
       <>jsonb_array_length(basis) THEN
    RAISE EXCEPTION 'CAPA source identities cannot be duplicate or truncated'; END IF;
  FOR x IN SELECT value FROM jsonb_array_elements(reads) LOOP
    IF NOT COALESCE(jsonb_typeof(x)='object'
      AND (x-ARRAY['artifact_id','expected_revision'])='{}'::jsonb
      AND x->>'artifact_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
      AND jsonb_typeof(x->'expected_revision')='number'
      AND (x->>'expected_revision')::integer>0,false) THEN
      RAISE EXCEPTION 'CAPA source read requires exact Artifact revision'; END IF;
    SELECT value INTO b FROM jsonb_array_elements(basis)
      WHERE value->>'id'=x->>'artifact_id';
    IF NOT COALESCE(b->'revision'=x->'expected_revision' AND b->>'status'='active'
      AND b->>'hash' ~ '^[0-9a-f]{64}$' AND b->>'visibility' IN ('private','product')
      AND b->>'owner_id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',false)
      OR NOT EXISTS (SELECT 1 FROM artifact_versions a WHERE a.tenant_id=tid AND a.product_id=pid
        AND a.id=(x->>'artifact_id')::uuid AND a.revision=(x->>'expected_revision')::integer
        AND a.content_hash=b->>'hash' AND a.status='active'
        AND a.visibility=b->>'visibility' AND a.owner_id=(b->>'owner_id')::uuid)
      OR (b->>'visibility'='private' AND (audience<>'private' OR b->>'owner_id'<>owner::text)) THEN
      RAISE EXCEPTION 'CAPA exact source identity or audience differs'; END IF;
  END LOOP;
  FOR x IN SELECT value FROM jsonb_array_elements(sources) LOOP
    IF x->>'kind'='artifact' AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(reads) r
      WHERE r->>'artifact_id'=x->>'id' AND r->'expected_revision'=x->'revision') THEN
      RAISE EXCEPTION 'Every Artifact source must remain in the complete read set'; END IF;
  END LOOP;
  -- Raw native/uploaded provenance remains unchanged. Bytes, security epoch,
  -- issuer and professional qualification still require real host gates.
END $$;
"""

ORIGIN_SQL = r"""
CREATE FUNCTION public.assert_capa_fact_origin(tid uuid, pid uuid, project uuid, issue uuid,
  capa uuid, origin_id uuid, origin_rev integer, purpose_value text, nature_value text,
  anchor jsonb, reads jsonb, audience text, actor uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE original quality_issue_versions%ROWTYPE; p projects%ROWTYPE; raw jsonb;
BEGIN
  SELECT * INTO original FROM quality_issue_versions WHERE tenant_id=tid AND product_id=pid
    AND project_id=project AND issue_id=issue AND id=origin_id AND revision=origin_rev;
  SELECT * INTO p FROM projects WHERE tenant_id=tid AND product_id=pid AND id=project;
  raw := anchor->'origin';
  IF original.id IS NULL OR p.id IS NULL OR p.status<>'active'
    OR (p.visibility='private' AND p.owner_id<>actor)
    OR original.operation<>'quality.capa.actions.complete' OR original.status<>'awaiting_verification'
    OR NOT COALESCE(original.issue_snapshot->'capa'->>'id'=capa::text
      AND jsonb_typeof(original.issue_snapshot->'root_cause')='object'
      AND jsonb_typeof(original.issue_snapshot->'capa'->'actions')='array'
      AND jsonb_array_length(original.issue_snapshot->'capa'->'actions')>0
      AND NOT (original.issue_snapshot->>'needs_recheck')::boolean
      AND original.issue_snapshot->'merged_into'='null'::jsonb
      AND original.issue_snapshot->'capa'->'effectiveness'='null'::jsonb
      AND original.issue_snapshot->'capa'->'effectiveness_history'='[]'::jsonb
      AND original.issue_snapshot->'recheck_reasons'='[]'::jsonb
      AND original.issue_snapshot->'closure'='null'::jsonb
      AND raw->'ref'->>'id'=origin_id::text AND (raw->'ref'->>'revision')::integer=origin_rev
      AND raw->'ref'->>'snapshot_sha256'=original.snapshot_sha256
      AND raw->'scope'->>'tenant_id'=tid::text AND raw->'scope'->>'product_id'=pid::text
      AND raw->'scope'->>'project_id'=project::text AND raw->>'issue_id'=issue::text
      AND raw->>'purpose'=purpose_value AND raw->>'purpose'=original.purpose
      AND raw->>'nature'=nature_value
      AND raw->>'owner_id'=original.owner_id::text AND raw->>'visibility'=original.visibility
      AND raw->>'writer_id'=original.writer_id::text
      AND raw->>'operation'=original.operation
      AND (raw->>'created_at')::timestamptz=original.created_at
      AND raw->'issue'=original.issue_snapshot AND raw->'input_snapshot'=original.input_snapshot
      AND raw->'authority_snapshot'=original.authority_snapshot
      AND raw->'policy_snapshot'=original.policy_snapshot
      AND raw->'persisted_source_basis'=original.source_basis
      AND reads @> original.required_source_read_set
      AND jsonb_typeof(anchor->'origin_required_source_read_set')='array'
      AND reads @> (anchor->'origin_required_source_read_set'),false)
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(original.issue_snapshot->'capa'->'actions') x
      WHERE jsonb_typeof(x->'completion') IS DISTINCT FROM 'object')
    OR (original.visibility='private' AND (audience<>'private' OR original.owner_id<>actor)) THEN
    RAISE EXCEPTION 'CAPA publication requires exact immutable completed origin and preserves private scope'; END IF;
  -- No comparison deletes Current descendant history. Legal later lineage and
  -- all original failure bytes must be attested by the missing actual owners.
END $$;
"""

CURRENT_SQL = r"""
CREATE FUNCTION public.protect_capa_fact_current() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target jsonb; allowed text[] := ARRAY['fact_id','fact_revision','epoch'];
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'CAPA fact Current cannot be deleted'; END IF;
  PERFORM 1 FROM products WHERE tenant_id=NEW.tenant_id AND id=NEW.product_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'CAPA Current product gate missing'; END IF;
  IF TG_TABLE_NAME='capa_current_verification_rules' THEN
    SELECT to_jsonb(f) INTO target FROM capa_verification_rule_facts f
      WHERE f.tenant_id=NEW.tenant_id AND f.id=NEW.fact_id;
    allowed := allowed || ARRAY['issuer_version'];
    IF target->>'issuer_key' IS DISTINCT FROM NEW.issuer_key
      OR target->>'issuer_version' IS DISTINCT FROM NEW.issuer_version
      OR target->>'external_id' IS DISTINCT FROM NEW.external_id THEN
      RAISE EXCEPTION 'Rule Current requires exact issuer series and version'; END IF;
  ELSIF TG_TABLE_NAME='capa_current_observations' THEN
    SELECT to_jsonb(f) INTO target FROM capa_observation_facts f
      WHERE f.tenant_id=NEW.tenant_id AND f.id=NEW.fact_id;
  ELSE RAISE EXCEPTION 'Unsupported CAPA Current target'; END IF;
  IF target IS NULL OR NOT COALESCE(
    target->>'product_id'=NEW.product_id::text AND target->>'project_id'=NEW.project_id::text
    AND target->>'issue_id'=NEW.issue_id::text AND target->>'capa_id'=NEW.capa_id::text
    AND target->>'series_id'=NEW.series_id::text AND (target->>'revision')::integer=NEW.fact_revision
    AND target->>'origin_issue_version_id'=NEW.origin_issue_version_id::text
    AND (target->>'origin_issue_revision')::integer=NEW.origin_issue_revision
    AND target->>'owner_id'=NEW.owner_id::text AND target->>'visibility'=NEW.visibility
    AND target->>'nature'=NEW.nature AND target->>'purpose'=NEW.purpose
    AND target->>'anchor_sha256'=NEW.anchor_sha256 AND target->>'requirement_sha256'=NEW.requirement_sha256
    AND target->'anchor_snapshot'=NEW.anchor_snapshot,false) THEN
    RAISE EXCEPTION 'CAPA Current requires exact full scoped immutable target'; END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.fact_revision<>1 OR NEW.epoch<>1 OR NEW.series_id<>NEW.fact_id
      OR target->'previous_fact_id' IS DISTINCT FROM 'null'::jsonb
      OR target->'previous_revision' IS DISTINCT FROM 'null'::jsonb THEN
      RAISE EXCEPTION 'CAPA Current begins at exact first version and epoch one'; END IF;
  ELSE
    IF (to_jsonb(NEW)-allowed) IS DISTINCT FROM (to_jsonb(OLD)-allowed)
      OR NEW.fact_id=OLD.fact_id OR NEW.fact_revision<>OLD.fact_revision+1 OR NEW.epoch<>OLD.epoch+1
      OR target->>'previous_fact_id' IS DISTINCT FROM OLD.fact_id::text
      OR (target->>'previous_revision')::integer IS DISTINCT FROM OLD.fact_revision THEN
      RAISE EXCEPTION 'CAPA Current requires exact continuous predecessor and monotonic epoch'; END IF;
  END IF;
  RETURN NEW;
END $$;
"""

ATOM_SQL = r"""
CREATE FUNCTION public.assert_capa_publication_atom(table_name text, tid uuid, sid uuid)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE n jsonb; body jsonb; anchor jsonb; original_id uuid; original_rev integer;
  op_name text; family text; tier_value text; kind_value text; c confirmations%ROWTYPE;
  r action_receipts%ROWTYPE; previous jsonb; dependency jsonb; child jsonb; actual_time timestamptz;
BEGIN
  CASE table_name
    WHEN 'capa_verification_rule_facts' THEN
      SELECT to_jsonb(f) INTO n FROM capa_verification_rule_facts f WHERE f.tenant_id=tid AND f.id=sid;
      op_name := 'quality.capa.verification.rule.import'; family := 'capa_verification_rule';
      tier_value := 'host_import'; kind_value := 'rule';
    WHEN 'capa_observation_facts' THEN
      SELECT to_jsonb(f) INTO n FROM capa_observation_facts f WHERE f.tenant_id=tid AND f.id=sid;
      op_name := 'quality.capa.observation.record'; family := 'capa_observation';
      tier_value := 'T1'; kind_value := 'observation';
    WHEN 'capa_named_verification_reviews' THEN
      SELECT to_jsonb(f) INTO n FROM capa_named_verification_reviews f WHERE f.tenant_id=tid AND f.id=sid;
      op_name := 'quality.capa.verification.review'; family := 'capa_named_verification_review';
      tier_value := 'T2'; kind_value := 'review';
    WHEN 'capa_verification_evidence' THEN
      SELECT to_jsonb(f) INTO n FROM capa_verification_evidence f WHERE f.tenant_id=tid AND f.id=sid;
      op_name := 'quality.capa.verification.candidate.record'; family := 'capa_verification_candidate';
      tier_value := 'T1'; kind_value := 'candidate';
    ELSE RAISE EXCEPTION 'Unsupported CAPA publication target';
  END CASE;
  IF n IS NULL OR NOT COALESCE(isfinite((n->>'created_at')::timestamptz),false)
    OR NOT EXISTS (SELECT 1 FROM principals WHERE tenant_id=tid
    AND id=(n->>'writer_id')::uuid AND kind='human' AND active)
    OR NOT EXISTS (SELECT 1 FROM grants WHERE tenant_id=tid
      AND product_id=(n->>'product_id')::uuid AND principal_id=(n->>'writer_id')::uuid
      AND can_write AND expires_at>(n->>'created_at')::timestamptz) THEN
    RAISE EXCEPTION 'CAPA publication requires exact target and named actual human'; END IF;
  IF kind_value='candidate' THEN
    anchor := n->'input_snapshot'->'stable_anchor';
    original_id := (n->>'issue_version_id')::uuid; original_rev := (n->>'issue_revision')::integer;
    IF NOT COALESCE(jsonb_typeof(n->'input_snapshot')='object'
      AND (n->'input_snapshot') ?& ARRAY['semantic','shared_proof','proof_consumed_at','stable_anchor']
      AND ((n->'input_snapshot')-ARRAY['semantic','shared_proof','proof_consumed_at','stable_anchor'])='{}'::jsonb
      AND jsonb_typeof(n->'input_snapshot'->'semantic')='object'
      AND n->>'owner_id'=anchor->'origin'->>'owner_id'
      AND n->>'visibility'=anchor->'origin'->>'visibility'
      AND ((n->'input_snapshot'->'shared_proof')-ARRAY['id','tier'])='{}'::jsonb
      AND NOT ((n->'input_snapshot'->'semantic') ? 'confirmation_token')
      AND NOT ((n->'input_snapshot'->'semantic') ? 'approval_token')
      AND n->'candidate_binding'->'basis'=n->'basis_snapshot'
      AND n->'candidate_snapshot'->'binding'=n->'candidate_binding'
      AND n->'candidate_snapshot'->>'inspection_sha256'=n->>'inspection_sha256'
      AND n->'basis_snapshot'->>'basis_sha256'=n->>'basis_sha256'
      AND n->'candidate_snapshot'->'required_source_read_set'=n->'required_source_read_set',false) THEN
      RAISE EXCEPTION 'Candidate requires exact frozen unknown binding/inspection and no-token semantic'; END IF;
    PERFORM assert_capa_fact_source_closure(tid,(n->>'product_id')::uuid,n->'sources',n->'required_source_read_set',
      n->'source_basis'->'artifact_sources',n->>'visibility',(n->>'owner_id')::uuid);
    c := assert_quality_followup_proof(tid,(n->>'product_id')::uuid,(n->>'writer_id')::uuid,
      op_name,n->'input_snapshot'->'shared_proof',(n->>'created_at')::timestamptz);
    IF NOT COALESCE(jsonb_typeof(n->'input_snapshot'->'proof_consumed_at')='string'
      AND n->'input_snapshot'->>'proof_consumed_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+-][0-9]{2}:[0-9]{2})$'
      AND c.created_at<=(n->'input_snapshot'->>'proof_consumed_at')::timestamptz
      AND (n->'input_snapshot'->>'proof_consumed_at')::timestamptz<=(n->>'created_at')::timestamptz,false) THEN
      RAISE EXCEPTION 'Candidate retains actual consumed and saved clocks'; END IF;
  ELSE
    body := n->'fact_body'->'body'; anchor := n->'anchor_snapshot';
    original_id := (n->>'origin_issue_version_id')::uuid;
    original_rev := (n->>'origin_issue_revision')::integer;
    IF n->>'operation' IS DISTINCT FROM op_name OR n->>'tier' IS DISTINCT FROM tier_value
      OR n->>'fact_kind' IS DISTINCT FROM kind_value
      OR ROW(n->>'actor_id',n->>'requester_id') IS DISTINCT FROM ROW(n->>'writer_id',n->>'writer_id') THEN
      RAISE EXCEPTION 'CAPA fact actual operation, tier and writer must match'; END IF;
    PERFORM assert_capa_fact_source_closure(tid,(n->>'product_id')::uuid,n->'sources',n->'required_source_read_set',
      n->'source_basis',n->>'visibility',(n->>'owner_id')::uuid);
    IF tier_value<>'host_import' THEN
      c := assert_quality_followup_proof(tid,(n->>'product_id')::uuid,(n->>'writer_id')::uuid,
        op_name,jsonb_build_object('id',n->'shared_proof_id','tier',tier_value),(n->>'created_at')::timestamptz);
      IF NOT COALESCE((n->>'shared_proof_revision')::integer=c.revision
        AND (n->>'proof_expires_at')::timestamptz=c.expires_at AND n->>'token_sha256'=c.token_hash
        AND n->>'material_sha256'=c.payload_digest AND c.created_at<=(n->>'proof_consumed_at')::timestamptz
        AND (n->>'proof_consumed_at')::timestamptz<=(n->>'created_at')::timestamptz,false) THEN
        RAISE EXCEPTION 'CAPA fact requires exact actual shared proof fields and consumption clock'; END IF;
    END IF;
  END IF;
  PERFORM assert_capa_fact_origin(tid,(n->>'product_id')::uuid,(n->>'project_id')::uuid,
    (n->>'issue_id')::uuid,(n->>'capa_id')::uuid,original_id,original_rev,n->>'purpose',n->>'nature',
    anchor,n->'required_source_read_set',n->>'visibility',(n->>'writer_id')::uuid);
  IF kind_value IN ('rule','observation') AND n->>'previous_fact_id' IS NOT NULL THEN
    IF kind_value='rule' THEN
      SELECT to_jsonb(f) INTO previous FROM capa_verification_rule_facts f
        WHERE f.tenant_id=tid AND f.id=(n->>'previous_fact_id')::uuid;
    ELSE
      SELECT to_jsonb(f) INTO previous FROM capa_observation_facts f
        WHERE f.tenant_id=tid AND f.id=(n->>'previous_fact_id')::uuid;
    END IF;
    IF previous IS NULL OR previous->>'purpose' IS DISTINCT FROM n->>'purpose' THEN
      RAISE EXCEPTION 'CAPA successor retains exact complete original purpose'; END IF;
  END IF;
  r := assert_quality_followup_receipt(tid,(n->>'product_id')::uuid,sid,(n->>'revision')::integer,
    op_name,family,(n->>'writer_id')::uuid,n->>'visibility',n->>'status');
  IF jsonb_typeof(r.result->'revision') IS DISTINCT FROM 'number'
    OR NOT COALESCE(r.result->>'revision' ~ '^[1-9][0-9]*$',false)
    OR r.result->'revision' IS DISTINCT FROM n->'revision'
    OR r.created_at<(n->>'created_at')::timestamptz THEN
    RAISE EXCEPTION 'CAPA receipt retains exact numeric revision and actual save ordering'; END IF;
  IF r.intent_digest IS DISTINCT FROM n->>'intent_digest' THEN
    RAISE EXCEPTION 'CAPA publication uses actual common intent, not domain intent'; END IF;
  IF tier_value<>'host_import' AND (c.snapshot->>'operation' IS DISTINCT FROM op_name
    OR c.snapshot->'required_source_read_set' IS DISTINCT FROM n->'required_source_read_set') THEN
    RAISE EXCEPTION 'CAPA proof review retains operation and exact complete read set'; END IF;
  IF kind_value='candidate' THEN
    IF (r.result-ARRAY['id','revision','status','candidate_binding_sha256','inspection_sha256'])<>'{}'::jsonb
      OR r.result->>'candidate_binding_sha256' IS DISTINCT FROM n->>'binding_sha256'
      OR r.result->>'inspection_sha256' IS DISTINCT FROM n->>'inspection_sha256' THEN
      RAISE EXCEPTION 'Candidate receipt binds actual non-cyclic binding and inspection hashes'; END IF;
  ELSE
    IF (r.result-ARRAY['id','revision','status','fact_kind','payload_sha256'])<>'{}'::jsonb
      OR r.command_id IS DISTINCT FROM (n->>'command_id')::uuid
      OR r.result->>'fact_kind' IS DISTINCT FROM kind_value
      OR r.result->>'payload_sha256' IS DISTINCT FROM n->>'payload_sha256' THEN
      RAISE EXCEPTION 'CAPA fact receipt binds actual command and body payload hash'; END IF;
  END IF;
  IF kind_value IN ('rule','observation') THEN
    IF kind_value='rule' THEN
      IF NOT COALESCE(isfinite((n->>'valid_from')::timestamptz)
        AND isfinite((n->>'valid_until')::timestamptz),false) THEN
        RAISE EXCEPTION 'Rule publication retains finite fixed validity clocks'; END IF;
      IF NOT EXISTS (SELECT 1 FROM capa_current_verification_rules p WHERE p.tenant_id=tid
        AND p.product_id=(n->>'product_id')::uuid AND p.project_id=(n->>'project_id')::uuid
        AND p.issue_id=(n->>'issue_id')::uuid AND p.capa_id=(n->>'capa_id')::uuid
        AND p.series_id=(n->>'series_id')::uuid AND p.fact_id=sid
        AND p.fact_revision=(n->>'revision')::integer) THEN
        RAISE EXCEPTION 'Rule publication and its exact Current must commit together'; END IF;
      IF n->>'previous_fact_id' IS NOT NULL THEN
        SELECT to_jsonb(f) INTO previous FROM capa_verification_rule_facts f
          WHERE f.tenant_id=tid AND f.id=(n->>'previous_fact_id')::uuid;
        IF previous->>'issuer_key' IS DISTINCT FROM n->>'issuer_key'
          OR previous->>'external_id' IS DISTINCT FROM n->>'external_id'
          OR (n->>'issuer_epoch')::integer<(previous->>'issuer_epoch')::integer THEN
          RAISE EXCEPTION 'Rule successor preserves external series and cannot rewind issuer epoch'; END IF;
      END IF;
    ELSE
      IF NOT EXISTS (SELECT 1 FROM capa_current_observations p WHERE p.tenant_id=tid
        AND p.product_id=(n->>'product_id')::uuid AND p.project_id=(n->>'project_id')::uuid
        AND p.issue_id=(n->>'issue_id')::uuid AND p.capa_id=(n->>'capa_id')::uuid
        AND p.series_id=(n->>'series_id')::uuid AND p.fact_id=sid
        AND p.fact_revision=(n->>'revision')::integer) THEN
        RAISE EXCEPTION 'Observation and its exact Current must commit together'; END IF;
      actual_time := (body->'at'->>'occurred_at')::timestamptz;
      IF NOT COALESCE((n->>'observed_from')::timestamptz<(n->>'observed_until')::timestamptz
        AND (n->>'observed_until')::timestamptz<=actual_time
        AND actual_time<=(n->>'created_at')::timestamptz
        AND jsonb_typeof(body->'records')='array' AND jsonb_array_length(body->'records')>0
        AND jsonb_typeof(body->'targets')='array' AND jsonb_array_length(body->'targets')>0,false)
        OR EXISTS (SELECT 1 FROM jsonb_array_elements(body->'records') x WHERE NOT COALESCE(
          (x->>'occurred_at')::timestamptz BETWEEN (n->>'observed_from')::timestamptz
            AND (n->>'observed_until')::timestamptz
          AND EXISTS (SELECT 1 FROM jsonb_array_elements(body->'targets') t WHERE t->>'key'=x->>'target_key'),false)) THEN
        RAISE EXCEPTION 'Observation retains actual target records and original received time'; END IF;
    END IF;
  END IF;
  IF kind_value IN ('observation','review') THEN
    SELECT to_jsonb(f) INTO dependency FROM capa_verification_rule_facts f WHERE f.tenant_id=tid
      AND f.product_id=(n->>'product_id')::uuid AND f.project_id=(n->>'project_id')::uuid
      AND f.issue_id=(n->>'issue_id')::uuid AND f.capa_id=(n->>'capa_id')::uuid
      AND f.id=(n->>'rule_fact_id')::uuid AND f.revision=(n->>'rule_revision')::integer;
    IF dependency IS NULL OR ROW(dependency->>'anchor_sha256',dependency->>'requirement_sha256',
      dependency->>'purpose',dependency->>'nature') IS DISTINCT FROM ROW(n->>'anchor_sha256',
      n->>'requirement_sha256',n->>'purpose',n->>'nature') THEN
      RAISE EXCEPTION 'CAPA observation/review requires exact scoped published Rule'; END IF;
  END IF;
  IF kind_value='review' THEN
    IF NOT COALESCE(isfinite((body->'at'->>'occurred_at')::timestamptz)
      AND (body->'at'->>'occurred_at')::timestamptz<=(n->>'created_at')::timestamptz
      AND isfinite((n->>'valid_until')::timestamptz),false)
      OR NOT EXISTS (SELECT 1 FROM capa_verification_evidence f WHERE f.tenant_id=tid
      AND f.product_id=(n->>'product_id')::uuid AND f.project_id=(n->>'project_id')::uuid
      AND f.issue_id=(n->>'issue_id')::uuid AND f.capa_id=(n->>'capa_id')::uuid
      AND f.id=(n->>'candidate_id')::uuid AND f.revision=(n->>'candidate_revision')::integer
      AND f.input_snapshot->'stable_anchor'=anchor AND f.purpose=n->>'purpose' AND f.nature=n->>'nature')
      OR NOT COALESCE(jsonb_typeof(body->'observations')='array'
        AND jsonb_array_length(body->'observations')>0
        AND jsonb_array_length(body->'observations')=(SELECT count(DISTINCT x->>'id')
          FROM jsonb_array_elements(body->'observations') x),false) THEN
      RAISE EXCEPTION 'Named review requires exact scoped candidate and unique ordered observation refs'; END IF;
    FOR child IN SELECT value FROM jsonb_array_elements(body->'observations') LOOP
      IF NOT EXISTS (SELECT 1 FROM capa_observation_facts f WHERE f.tenant_id=tid
        AND f.product_id=(n->>'product_id')::uuid AND f.project_id=(n->>'project_id')::uuid
        AND f.issue_id=(n->>'issue_id')::uuid AND f.capa_id=(n->>'capa_id')::uuid
        AND f.id=(child->>'id')::uuid AND f.revision=(child->>'revision')::integer
        AND f.rule_fact_id=(n->>'rule_fact_id')::uuid AND f.rule_revision=(n->>'rule_revision')::integer
        AND f.rule_sha256=n->>'rule_sha256' AND f.anchor_sha256=n->>'anchor_sha256'
        AND f.requirement_sha256=n->>'requirement_sha256' AND f.purpose=n->>'purpose' AND f.nature=n->>'nature'
        AND (f.fact_body->'body'->'at'->>'occurred_at')::timestamptz<=(body->'at'->>'occurred_at')::timestamptz) THEN
        RAISE EXCEPTION 'Named review requires every exact original observation in the saved scope'; END IF;
    END LOOP;
  END IF;
  -- Canonical body/full SHA, original bytes, full child FactRef SHA, actual
  -- semantic material and seven current owner gates remain host responsibilities.
END $$;
"""

TARGET_TRIGGER_SQL = r"""
CREATE FUNCTION public.require_capa_publication_atom() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM assert_capa_publication_atom(TG_TABLE_NAME,NEW.tenant_id,NEW.id);
  RETURN NULL;
END $$;
"""

RECEIPT_TRIGGER_SQL = r"""
CREATE FUNCTION public.require_capa_publication_receipt_atom() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target_table text; uses integer;
BEGIN
  target_table := CASE NEW.operation
    WHEN 'quality.capa.verification.rule.import' THEN 'capa_verification_rule_facts'
    WHEN 'quality.capa.observation.record' THEN 'capa_observation_facts'
    WHEN 'quality.capa.verification.review' THEN 'capa_named_verification_reviews'
    WHEN 'quality.capa.verification.candidate.record' THEN 'capa_verification_evidence' END;
  IF target_table IS NULL THEN RETURN NULL; END IF;
  SELECT count(*) INTO uses FROM (
    SELECT id FROM capa_verification_rule_facts WHERE tenant_id=NEW.tenant_id AND id=NEW.subject_id
      AND revision=NEW.subject_revision AND target_table='capa_verification_rule_facts'
    UNION ALL SELECT id FROM capa_observation_facts WHERE tenant_id=NEW.tenant_id AND id=NEW.subject_id
      AND revision=NEW.subject_revision AND target_table='capa_observation_facts'
    UNION ALL SELECT id FROM capa_named_verification_reviews WHERE tenant_id=NEW.tenant_id AND id=NEW.subject_id
      AND revision=NEW.subject_revision AND target_table='capa_named_verification_reviews'
    UNION ALL SELECT id FROM capa_verification_evidence WHERE tenant_id=NEW.tenant_id AND id=NEW.subject_id
      AND revision=NEW.subject_revision AND target_table='capa_verification_evidence'
  ) u;
  IF uses<>1 THEN RAISE EXCEPTION 'CAPA publication receipt requires exactly one actual target'; END IF;
  PERFORM assert_capa_publication_atom(target_table,NEW.tenant_id,NEW.subject_id);
  RETURN NULL;
END $$;
"""


def _preflight(*, rollback=False):
    new_ops = _quoted(OPERATIONS)
    public_ops = _quoted(PUBLIC_PROOF_OPERATIONS)
    if rollback:
        return (
            "LOCK TABLE confirmations,action_receipts,capa_verification_evidence,"
            + ",".join(FACT_TABLES + CURRENT_TABLES)
            + " IN SHARE ROW EXCLUSIVE MODE",
            "DO $$ BEGIN IF "
            + " OR ".join(f"EXISTS(SELECT 1 FROM {t})" for t in FACT_TABLES + CURRENT_TABLES)
            + " OR EXISTS(SELECT 1 FROM capa_verification_evidence)"
            + f" OR EXISTS(SELECT 1 FROM action_receipts WHERE operation IN {new_ops})"
            + f" OR EXISTS(SELECT 1 FROM confirmations WHERE consumed IS TRUE AND operation IN {public_ops})"
            + " THEN RAISE EXCEPTION 'Retained CAPA publication prevents guard downgrade'; END IF; END $$;",
        )
    return (
        "LOCK TABLE confirmations,action_receipts,capa_verification_evidence IN SHARE ROW EXCLUSIVE MODE",
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM capa_verification_evidence)"
        + f" OR EXISTS(SELECT 1 FROM confirmations WHERE consumed IS TRUE AND operation IN {public_ops})"
        + f" OR EXISTS(SELECT 1 FROM action_receipts WHERE operation IN {new_ops})"
        + " THEN RAISE EXCEPTION 'New CAPA targets/proofs must be empty before establishing reciprocal atoms'; END IF; END $$;",
        "DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_constraint c WHERE c.conrelid='confirmations'::regclass"
        " AND c.contype='u' AND c.conkey=ARRAY["
        "(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='tenant_id'),"
        "(SELECT attnum FROM pg_attribute WHERE attrelid=c.conrelid AND attname='id')]::smallint[])"
        " THEN RAISE EXCEPTION 'Root must first add exact confirmations UNIQUE(tenant_id,id)'; END IF; END $$;",
    )


def build_guard_plan(definitions: Mapping[str, str]) -> SqlGuardPlan:
    """Build statements from SIX exact actual-head25 definitions, never execute.

    Root must reobserve these within its guarded migration boundary. This
    accepts no table names, role names, issuer permissions or client SQL.
    """
    if set(definitions) != set(EXPECTED_DEFINITIONS_SHA256):
        raise GuardPreparationError("Six exact observed head25 definitions are required")
    for key, expected in EXPECTED_DEFINITIONS_SHA256.items():
        value = definitions[key]
        if not isinstance(value, str) or sha256(value.encode()).hexdigest() != expected:
            raise GuardPreparationError("Actual SQL guard differs from reviewed head25")
    replacements = _expanded_functions(definitions)
    triggers, permissions, drops = [], [], []
    for table in FACT_TABLES + CURRENT_TABLES:
        permissions.extend(
            (
                f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY tenant_scope ON "{table}" '
                "USING (tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid) "
                "WITH CHECK (tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid)",
                f'REVOKE ALL ON "{table}" FROM PUBLIC,pdos_next_app,pdos_agent',
                f'GRANT SELECT,INSERT ON "{table}" TO pdos_next_app',
            )
        )
        triggers.append(
            f'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()"
        )
        if table in CURRENT_TABLES:
            columns = "fact_id,fact_revision,epoch" + (
                ",issuer_version" if table == CURRENT_TABLES[0] else ""
            )
            permissions.append(f'GRANT UPDATE({columns}) ON "{table}" TO pdos_next_app')
            triggers.append(
                f'CREATE TRIGGER exact_current BEFORE INSERT OR UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION protect_capa_fact_current()"
            )
            drops.append(f'DROP TRIGGER exact_current ON "{table}"')
        else:
            triggers.extend(
                (
                    f'CREATE TRIGGER retained_record BEFORE UPDATE OR DELETE ON "{table}" '
                    "FOR EACH ROW EXECUTE FUNCTION protect_next_snapshot()",
                    f'CREATE CONSTRAINT TRIGGER capa_publication_required AFTER INSERT ON "{table}" '
                    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_capa_publication_atom()",
                )
            )
            drops.extend(
                (
                    f'DROP TRIGGER retained_record ON "{table}"',
                    f'DROP TRIGGER capa_publication_required ON "{table}"',
                )
            )
        drops.append(f'DROP TRIGGER lifecycle_reference ON "{table}"')
    permissions.extend(
        (
            'REVOKE ALL ON "capa_verification_evidence" FROM PUBLIC,pdos_next_app,pdos_agent',
            'GRANT SELECT,INSERT ON "capa_verification_evidence" TO pdos_next_app',
        )
    )
    for signature in NEW_FUNCTION_SIGNATURES:
        permissions.extend(
            (
                f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,pdos_agent",
                f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_app",
            )
        )
    # Candidate already has FORCE RLS, tenant_scope, retained_record and
    # lifecycle_reference installed by head24. Do not duplicate those triggers.
    triggers.extend(
        (
            "CREATE CONSTRAINT TRIGGER capa_publication_required AFTER INSERT ON capa_verification_evidence "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_capa_publication_atom()",
            "CREATE CONSTRAINT TRIGGER capa_publication_receipt_required AFTER INSERT ON action_receipts "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_capa_publication_receipt_atom()",
        )
    )
    drops.extend(
        (
            "DROP TRIGGER capa_publication_required ON capa_verification_evidence",
            "DROP TRIGGER capa_publication_receipt_required ON action_receipts",
        )
    )
    drops.extend("DROP FUNCTION " + signature for signature in NEW_FUNCTION_SIGNATURES)
    drops.extend(
        (
            'REVOKE INSERT ON "capa_verification_evidence" FROM pdos_next_app',
            'GRANT SELECT ON "capa_verification_evidence" TO pdos_next_app',
        )
    )
    # Root drops the five empty tables after these guards, then restores the
    # exact prior functions before relinquishing the migration table locks.
    return SqlGuardPlan(
        preflight=_preflight(),
        replace_functions=replacements,
        new_functions=tuple(
            sql.strip().replace(
                "LANGUAGE plpgsql AS $$",
                "LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$",
                1,
            )
            for sql in (
                SOURCE_SQL,
                ORIGIN_SQL,
                CURRENT_SQL,
                ATOM_SQL,
                TARGET_TRIGGER_SQL,
                RECEIPT_TRIGGER_SQL,
            )
        ),
        new_triggers=tuple(triggers),
        permissions=tuple(permissions),
        rollback_preflight=_preflight(rollback=True),
        rollback_guards=tuple(drops),
        restore_functions=tuple(definitions[name] for name in REPLACED_FUNCTIONS),
        installed_definition_sha256=tuple(EXPECTED_DEFINITIONS_SHA256.items()),
    )
