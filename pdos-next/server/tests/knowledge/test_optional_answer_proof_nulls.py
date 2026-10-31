"""Real driver NULL binding and the exact generated optional-proof caller boundary."""

import re

from migrations.candidates import knowledge_optional_proof as proposal
from migrations.candidates.dingtalk_lifecycle import NATIVE_FUNCTIONS as installed_g
from migrations.schema_s0_0844 import SCHEMA_SQL as strict_resolver_sql
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from sqlalchemy.dialects.postgresql import JSONB, dialect

OPTIONAL = {
    "category_knowledge_entries",
    "knowledge_candidate_versions",
    "knowledge_rule_versions",
}


def test_nullable_native_proof_uses_sql_null_and_preserves_explicit_json_values():
    column = KnowledgeEntry.__table__.c.answer_sources
    driver = dialect()
    bind = column.type.dialect_impl(driver).bind_processor(driver)
    assert column.nullable and column.type.compile(dialect=driver) == "JSONB"
    assert bind(None) is None
    assert bind([]).obj == []
    actual = [{"source_type": "field_feedback", "source_revision": 1}]
    assert bind(actual).obj == actual
    # Explicit JSON null is still JSON null, so the existing shape CHECK can
    # reject it. This changes the optional Python None binding only.
    assert bind(JSONB.NULL).obj is None
    assert JSONB().dialect_impl(driver).bind_processor(driver)(None) is not None


def test_caller_normalizes_only_three_optional_arrays_and_passes_required_proof_raw():
    signature = proposal.SIGNATURE
    before, after = proposal.PREVIOUS_FUNCTIONS[signature], proposal.NATIVE_FUNCTIONS[signature]
    assert before == installed_g[signature]
    start = " -- F: only server-verified fixed answer proofs"
    end = " -- G private outbound body copies"
    assert before[:before.index(start)] == after[:after.index(start)]
    assert before[before.index(end):] == after[after.index(end):]
    section = after[after.index(start):after.index(end)]
    guard = re.search(
        r"IF table_name IN \(([^\n]+)\) THEN\n"
        r"   container=coalesce\(nullif\(container,'null'::jsonb\),'\[\]'::jsonb\);\n"
        r"  END IF;",
        section,
    )
    assert guard is not None
    assert set(re.findall(r"'([^']+)'", guard.group(1))) == OPTIONAL
    assert "'knowledge_answer_reviews','knowledge_gap_submissions'" in section
    assert section.count("assistant_source_lifecycle_links(t,c,container)") == 1
    assert "assistant_source_lifecycle_links(t,c,coalesce" not in section
    # Non-null scalars/objects are not changed by NULLIF. They still reach the
    # original resolver, whose array guard remains strict and unmodified.
    resolver = "\n".join(strict_resolver_sql)
    assert "IF jsonb_typeof(proof) IS DISTINCT FROM 'array' THEN" in resolver
    assert "Fixed assistant source dependencies must be an array" in resolver


def test_function_replacement_preserves_security_and_has_no_schema_acl_or_policy_side_effects():
    assert set(proposal.PREVIOUS_FUNCTIONS) == set(proposal.NATIVE_FUNCTIONS) == {
        proposal.SIGNATURE,
    }
    assert proposal.SCHEMA_SQL == tuple(proposal.NATIVE_FUNCTIONS.values())
    assert proposal.DOWNGRADE_SQL == tuple(proposal.PREVIOUS_FUNCTIONS.values())
    for sql in (*proposal.SCHEMA_SQL, *proposal.DOWNGRADE_SQL):
        assert sql.count("CREATE OR REPLACE FUNCTION") == 1
        assert "STABLE SECURITY DEFINER" in sql
        assert "SET search_path TO 'pg_catalog', 'public', 'pg_temp'" in sql
        assert not re.search(r"\b(?:ALTER|GRANT|REVOKE|POLICY|CREATE TABLE)\b", sql)
