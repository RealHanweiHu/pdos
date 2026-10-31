"""One-hop fixed citations survive real HTTP/Temporal continuation without a new search."""
# ruff: noqa: F811, F401 -- actual fixture tree

import os

import pytest

from tests.enterprise_search.test_assistant_temporal_pg import run_http_case
from tests.enterprise_search.test_business_sources_pg import (
    accepted_work,
    apply_event,
    change_work,
    created,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from tests.enterprise_search.test_relations_pg import RelatedClient


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal and checkpoint runtime required",
)
def test_registered_relationship_reaches_fixed_source_and_continues_without_new_search(
    change_work, monkeypatch
):
    work = change_work
    receipt, _command, _id = created(work)
    assert apply_event(work.quality, work.issue_receipt["id"])["processed"] == 2
    assert apply_event(work.quality, receipt["id"])["processed"] == 1
    run_http_case(
        work.quality,
        monkeypatch,
        RelatedClient("Synthetic failure requires dual-lane impact"),
        expected_kind="issue",
        expected_calls=3,
        expected_matches=3,
        expected_relation="change_issue",
        continue_once=True,
        expected_continuation_calls=3,
        forbidden_history_tokens=(work.issue_view["issue"]["title"],),
    )
