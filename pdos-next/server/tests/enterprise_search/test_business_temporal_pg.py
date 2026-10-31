"""Authenticated native issue question through actual Temporal and the registered graph."""
# ruff: noqa: F811, F401 -- actual fixture tree, no native-fact fabrication

import os

import pytest
from change_execution.test_transactions import (
    accepted_work,
    change_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)

from tests.enterprise_search.test_assistant_temporal_pg import run_http_case
from tests.enterprise_search.test_business_sources_pg import NativeClient, apply_event


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal and checkpoint runtime required",
)
def test_native_issue_question_is_durable_and_uses_no_extraction_model(change_work, monkeypatch):
    work = change_work
    assert apply_event(work.quality, work.issue_receipt["id"])["processed"] == 2
    run_http_case(
        work.quality,
        monkeypatch,
        NativeClient(str(work.issue_id), ["issue"]),
        expected_kind="issue",
        expected_calls=3,
    )
