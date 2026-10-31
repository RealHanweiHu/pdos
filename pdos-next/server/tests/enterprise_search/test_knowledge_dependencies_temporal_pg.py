"""Actual HTTP→Temporal→registered graph and lineage reuse of signed dependency roots."""

import os

import pytest

from tests.enterprise_search.test_assistant_temporal_pg import run_http_case
from tests.enterprise_search.test_citation_inheritance_temporal_pg import ContinuingClient
from tests.enterprise_search.test_knowledge_dependencies_pg import (
    KnowledgeClient,
    indexed_knowledge,
)
from tests.enterprise_search.test_retrieval_pg import register


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal and checkpoint runtime required",
)
def test_http_knowledge_dependency_proof_survives_durable_continuation_and_replay(
    setup, monkeypatch,
):
    source = register(setup, "内部知识依据", "更换密封圈。")
    indexed_knowledge(setup, {
        "type": "artifact", "id": str(source), "version": 1,
        "line": 1, "quote": "更换密封圈",
    })
    provider = ContinuingClient()
    provider.clients = [KnowledgeClient()]
    run_http_case(setup, monkeypatch, provider, expected_kind="knowledge", expected_calls=3,
                  continue_once=True, expected_continuation_calls=3,
                  forbidden_history_tokens=("原知识说明",))
