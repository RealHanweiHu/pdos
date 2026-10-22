# ruff: noqa: E501 -- exact reviewed SQL repair anchors and source hashes
"""B5 captures retain actual fact intervals without an ordinary material TTL."""

import hashlib

from alembic import op
from sqlalchemy import text

revision = "s0_0422"
down_revision = "s0_0421"
branch_labels = None
depends_on = None

TIME_CHECK = """CREATE FUNCTION public.quality_capture_time_current(
  authority jsonb, policy jsonb, saved_at timestamptz) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$
  SELECT COALESCE(
    (authority->>'valid_until' IS NULL OR
      (authority->>'valid_until')::timestamptz>saved_at)
    AND (policy->>'valid_until' IS NULL OR
      (policy->>'valid_until')::timestamptz>saved_at)
    AND EXISTS (
      SELECT 1 FROM jsonb_array_elements(authority->'fact_refs') duty
      JOIN jsonb_array_elements(authority->'fact_refs') qualification
        ON qualification->>'role'=duty->>'role'
      WHERE duty->>'kind'='duty' AND qualification->>'kind'='qualification'
        AND authority->'roles' @> jsonb_build_array(duty->>'role')
        AND duty->>'state'='active' AND qualification->>'state'='active'
        AND (duty->>'nature'<>'synthetic' OR authority->'synthetic'='true'::jsonb)
        AND (qualification->>'nature'<>'synthetic' OR authority->'synthetic'='true'::jsonb)
        AND duty->'operations' @> jsonb_build_array(authority->>'operation')
        AND qualification->'operations' @> jsonb_build_array(authority->>'operation')
        AND duty->'purposes' @> jsonb_build_array(authority->>'purpose')
        AND qualification->'purposes' @> jsonb_build_array(authority->>'purpose')
        AND (duty->>'valid_from')::timestamptz<=saved_at
        AND saved_at<(duty->>'valid_until')::timestamptz
        AND (qualification->>'valid_from')::timestamptz<=saved_at
        AND saved_at<(qualification->>'valid_until')::timestamptz)
    AND (SELECT count(*) FROM jsonb_array_elements(policy->'source_basis') fact
      WHERE fact->>'state'='active' AND (fact->>'valid_from')::timestamptz<=saved_at
        AND saved_at<(fact->>'valid_until')::timestamptz)=1
    AND EXISTS (SELECT 1 FROM jsonb_array_elements(policy->'source_basis') fact
      WHERE fact->>'id'=policy->>'id' AND fact->'revision'=policy->'revision'
        AND fact->>'state'='active' AND (fact->>'valid_from')::timestamptz<=saved_at
        AND saved_at<(fact->>'valid_until')::timestamptz),false)
$$;
"""

CAPTURE_REPAIR = (
    "AND (NEW.authority_snapshot->>'valid_until')::timestamptz>NEW.created_at\n"
    "    AND (NEW.policy_snapshot->>'valid_until')::timestamptz>NEW.created_at",
    "AND quality_capture_time_current(NEW.authority_snapshot,NEW.policy_snapshot,NEW.created_at)",
)

REPAIRS = {
    "require_quality_followup_atom()": (
        CAPTURE_REPAIR,
        (
            "jsonb_array_length(NEW.required_source_read_set) BETWEEN 1 AND 20",
            "jsonb_array_length(NEW.required_source_read_set)>0",
        ),
        (
            "COALESCE(jsonb_array_length(NEW.input_snapshot->'completions'),0) NOT BETWEEN 1 AND 1000",
            "COALESCE(jsonb_array_length(NEW.input_snapshot->'completions'),0)<1",
        ),
        (
            "jsonb_array_length(supplied->'evidence') BETWEEN 1 AND 20",
            "jsonb_array_length(supplied->'evidence')>0",
        ),
        (
            "AND (assessment->>'valid_until')::timestamptz>NEW.created_at",
            "AND (assessment->>'valid_until' IS NULL OR\n"
            "            (assessment->>'valid_until')::timestamptz>NEW.created_at)\n"
            "          AND jsonb_typeof(assessment->'time_constraints')='array'\n"
            "          AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(\n"
            "            assessment->'time_constraints') deadline WHERE deadline::timestamptz<=NEW.created_at)",
        ),
    ),
    "require_capa_link_atom()": (
        CAPTURE_REPAIR,
        (
            "jsonb_array_length(NEW.output_snapshot->'outputs') BETWEEN 1 AND 20",
            "jsonb_array_length(NEW.output_snapshot->'outputs')>0",
        ),
    ),
    "assert_capa_fact_source_closure(uuid,uuid,jsonb,jsonb,jsonb,text,uuid)": (
        ("jsonb_array_length(reads) BETWEEN 1 AND 20", "jsonb_array_length(reads)>0"),
        ("complete bounded source arrays", "complete source arrays"),
        (
            "b->>'visibility' IN ('private','product')",
            "b->>'visibility' IN ('private','category','audience')",
        ),
        (
            "a.tenant_id=tid AND a.product_id=pid",
            "a.tenant_id=tid AND a.category_id=(SELECT category_id FROM products\n"
            "        WHERE tenant_id=tid AND id=pid) AND (a.product_id=pid OR a.product_id IS NULL)",
        ),
    ),
    "assert_capa_publication_atom(text,uuid,uuid)": (
        (
            "AND isfinite((n->>'valid_until')::timestamptz),false)\n      OR NOT EXISTS",
            "AND (n->>'valid_until' IS NULL OR\n"
            "        isfinite((n->>'valid_until')::timestamptz)),false)\n      OR NOT EXISTS",
        ),
    ),
}

# SHA256 of pg_proc.prosrc captured from the verified s0_0421 predecessor.
HASHES = {'require_quality_followup_atom()': ('1440edf39592be9cebe21a6a36b29dfb35c5599980fd4996fe53461fe00aacbc', '24d6005bedff5d3fa909594d32c581f71bc87821422a2b34e6e9651767883f5a'), 'require_capa_link_atom()': ('d59ae7810a0300523d0c6e8e949c612749c36365379bc92f80e97b1d775944d8', 'c18f68dc70f7a841f52e0b287024569fb7d56d69c9aba77beccb50e4c8833011'), 'assert_capa_fact_source_closure(uuid,uuid,jsonb,jsonb,jsonb,text,uuid)': ('928e5404f20593fb09007726718fe05ab252c559c44e3576dfc86d68f160c695', 'bf49af20bdf74b63bb6d36d5f667ad4b02c36e7875f6306aa02274fb84ffadc9'), 'assert_capa_publication_atom(text,uuid,uuid)': ('d697e99290135a2782a534705ee5e80428477df951a3fddecfd6c13091c7918a', 'c08c09965ad22cf7bea5169a7d0d60fb266e60896b09c2dbbc40aebedf752b5f')}


def _replace(reverse=False):
    for signature, replacements in REPAIRS.items():
        body, definition = op.get_bind().execute(
            text("SELECT prosrc,pg_get_functiondef(oid) FROM pg_proc WHERE oid=to_regprocedure(:signature)"),
            {"signature": signature},
        ).one()
        before, after = HASHES[signature]
        expected, desired = (after, before) if reverse else (before, after)
        if hashlib.sha256(body.encode()).hexdigest() != expected:
            raise RuntimeError(f"Unreviewed predecessor for {signature}")
        for old, new in replacements:
            old, new = (new, old) if reverse else (old, new)
            if body.count(old) != 1 or definition.count(old) != 1:
                raise RuntimeError(f"Non-unique capture repair for {signature}")
            body = body.replace(old, new, 1)
            definition = definition.replace(old, new, 1)
        if hashlib.sha256(body.encode()).hexdigest() != desired:
            raise RuntimeError(f"Unexpected capture repair for {signature}")
        op.execute(definition)


def upgrade():
    op.execute(TIME_CHECK)
    op.execute("REVOKE ALL ON FUNCTION quality_capture_time_current(jsonb,jsonb,timestamptz) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION quality_capture_time_current(jsonb,jsonb,timestamptz) TO pdos_next_app")
    _replace()


def downgrade():
    _replace(reverse=True)
    op.execute("DROP FUNCTION quality_capture_time_current(jsonb,jsonb,timestamptz)")
