"""Recall contracts for Chinese prose and exact engineering identifiers, without a model."""

import asyncio

import pytest
from pdos_next.enterprise_search.indexing import CHUNK_CHARS, chunks
from pdos_next.enterprise_search.tokenizer import analyze, codes, or_query
from pdos_next.enterprise_search.workflow import EnterpriseProjection
from temporalio import workflow
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner


def test_chinese_question_removes_function_words_but_keeps_domain_words_and_or():
    terms = analyze("以前类似的漏气问题怎么处理一下？")
    assert {"漏气", "问题", "处理"} <= set(terms["terms"])
    assert {"以前", "类似", "的", "怎么", "一下"} <= set(terms["removed"])
    query = or_query(terms["terms"])
    assert " | " in query and " & " not in query
    with pytest.raises(ValueError):
        or_query(["bad') | 'scope"])


def test_identifiers_are_independent_of_tokenization_and_dates_are_not_codes():
    exact, families = codes("Ｄ１６—０１、IP67、IPX7；GB／T 4706.1，日期2026-10-28")
    assert exact == ["D16-01", "GB/T4706.1", "IP67", "IPX7"]
    assert families == ["D16"]
    assert codes("2026-10-28 2026/10/28")[0] == []
    assert analyze("d16-01")["codes"] == ["D16-01"]


@pytest.mark.parametrize("code", [
    "FA-2026-029", "TR-A7-2026-006", "CAPA-2026-018", "RFQ-2026-118",
    "ENG-PRV-2026-009", "IPX7", "D16-01",
])
def test_separated_document_prefixes_keep_the_complete_identifier(code):
    assert codes(f"查{code}这份记录")[0] == [code]


def test_separated_code_normalization_preserves_standard_numbers_and_rejects_words():
    assert codes("ＦＡ—２０２６—０２９")[0] == ["FA-2026-029"]
    assert codes("load-bearing cross-scope 普通记录 2026-10-29")[0] == []
    assert codes("GB/T 4706.1 IEC 60529")[0] == ["GB/T4706.1", "IEC60529"]


def test_long_lines_and_paragraphs_remain_exact_located_source_substrings():
    body = "首段\n\n" + "充气泵压力条件" * 700 + "\n\n末段"
    result = list(chunks(body))
    assert len(result) > 3 and all(len(text) <= CHUNK_CHARS for text, _ in result)
    for text, locator in result:
        assert body[locator["char_start"] : locator["char_end"]] == text
        assert locator["line_start"] <= locator["line_end"]
    assert result[0][0].startswith("首段") and result[-1][0].endswith("末段")


def test_projection_workflow_is_sandboxable_without_business_or_provider_imports():
    async def validate():
        SandboxedWorkflowRunner().prepare_workflow(
            workflow._Definition.must_from_class(EnterpriseProjection)
        )

    asyncio.run(validate())
