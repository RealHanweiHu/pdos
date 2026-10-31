"""Query grammar must not alter indexed facts, exact IDs or durable policy provenance."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from pdos_next.enterprise_search import query
from pdos_next.enterprise_search.schemas import SearchInput
from pdos_next.enterprise_search.tokenizer import (
    QUERY_POLICY_VERSION,
    QUERY_RULE,
    analyze,
    analyze_query,
    version,
)
from pdos_next.errors import DomainError


def test_query_filter_keeps_source_analysis_and_index_version_unchanged():
    source = "我们 我们 先 按 这 批 料 不是 裂纹 裂纹"
    before, index_version = analyze(source), version()
    assert {"我们", "先", "按", "这", "不是", "料"} <= set(before["terms"])
    parsed = analyze_query(source)
    assert {"我们", "先", "按", "这", "不是"} <= set(parsed["removed"])
    assert not {"我们", "先", "按", "这", "不是"} & set(parsed["terms"])
    assert parsed["counts"]["裂纹"] == before["counts"]["裂纹"] == 2
    assert parsed["length"] == sum(parsed["counts"].values())
    assert analyze(source) == before
    assert parsed["tokenizer_version"] == version() == index_version


def test_technical_single_characters_factual_negatives_and_compounds_survive():
    text = "料 孔 测 不 未 无 没有 不能 裂纹 含水率 对照 按键 把手"
    parsed = analyze_query(text)
    assert set(text.split()) <= set(parsed["terms"])
    assert parsed["terms"] == analyze(text)["terms"]


@pytest.mark.parametrize("identifier", ["TR-A7-2026-006", "GB/T 4706.1"])
def test_grammar_filter_preserves_exact_engineering_code_and_raw_query(identifier):
    original = f"请先把这份{identifier}对上"
    data = SearchInput(query=original)
    parsed = analyze_query(data.query)
    before = analyze(original)
    assert parsed["codes"] == before["codes"]
    assert parsed["families"] == before["families"]
    assert parsed["codes"]
    assert data.query == original


def test_all_grammar_query_uses_existing_rejection_before_projection_or_sql(monkeypatch):
    original = "先把这个对"
    data = SearchInput(query=original)
    assert analyze_query(original)["terms"] == []
    monkeypatch.setattr(query, "require_context", lambda *_: None)
    monkeypatch.setattr(query, "_narrow", lambda *_: {})

    def unexpected_database_work(*_args, **_kwargs):
        pytest.fail("Empty lexical query must be rejected before projection or SQL")

    monkeypatch.setattr(query, "prepare_read", unexpected_database_work)
    session = SimpleNamespace(execute=unexpected_database_work)
    with pytest.raises(DomainError) as error:
        query.search(session, None, data)
    assert error.value.reason == "INVALID_PAYLOAD"
    assert error.value.code == "VALIDATION_FAILED"
    assert error.value.status == 422
    assert data.query == original


def test_response_retains_removed_terms_and_distinct_query_policy_provenance():
    data = SearchInput(query="先把这份裂纹记录对上")
    parsed = analyze_query(data.query)
    scope = dict.fromkeys(("category_id", "product_id", "project_id", "proposal_id"))
    response = query._response(
        None, data, scope, parsed, [], as_of=datetime(2026, 1, 1, tzinfo=UTC)
    )
    trace = response["query_trace"]
    assert {"先", "把"} <= set(trace["removed"])
    assert "裂纹" in trace["terms"]
    assert trace["tokenizer_version"] == version()
    assert trace["query_policy_version"] == QUERY_POLICY_VERSION
    assert QUERY_POLICY_VERSION.startswith(QUERY_RULE + "/")
    assert len(QUERY_POLICY_VERSION.rsplit("/", 1)[1]) == 64
    assert QUERY_POLICY_VERSION != version()
    assert QUERY_RULE in response["ranking_version"]
    assert len(response["ranking_version"]) <= 160
    assert analyze_query("不同技术查询")["query_policy_version"] == QUERY_POLICY_VERSION
