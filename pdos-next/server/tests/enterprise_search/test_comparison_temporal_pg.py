"""Pinned-document comparison through HTTP, durable workflow, child checkpoint and saving."""

import os

import pytest

from tests.enterprise_search.test_assistant_temporal_pg import run_http_case
from tests.enterprise_search.test_comparison_pg import CompareClient
from tests.enterprise_search.test_retrieval_pg import register


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal and checkpoint runtime required",
)
def test_http_document_pair_reaches_verified_differences_and_idempotent_private_table(
    setup, monkeypatch
):
    prefix = "这是两份相同的长背景段落。" * 180 + "\n\n"
    ids = [
        register(setup, "评审旧版", prefix + "压力 10 bar\n\nUNCHANGED_RAW_ONLY"),
        register(setup, "评审新版", prefix + "压力 12 bar\n\nUNCHANGED_RAW_ONLY"),
    ]
    run_http_case(
        setup,
        monkeypatch,
        CompareClient(ids),
        category_scoped=True,
        start_payload={
            "goal": "比较明确选择的两份资料并保留待确认事项",
            "sources": [{"artifact_id": str(identity), "expected_revision": 1} for identity in ids],
        },
        expected_matches=2,
        expect_comparison=True,
        forbidden_history_tokens=("UNCHANGED_RAW_ONLY", "压力 10 bar", "压力 12 bar"),
    )
