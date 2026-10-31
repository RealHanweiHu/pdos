"""Actual category fallback and citation continuation through Temporal, no real models."""

import os

import pytest

from tests.enterprise_search.test_assistant_temporal_pg import run_http_case
from tests.enterprise_search.test_citation_inheritance_temporal_pg import ContinuingClient
from tests.enterprise_search.test_retrieval_pg import index, register
from tests.g0_fixture import create_g0_project


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal and checkpoint runtime required",
)
def test_server_category_fallback_and_group_survive_durable_continuation(setup, monkeypatch):
    project = create_g0_project(setup, visibility="category")
    index(setup, register(setup, "漏气历史经验", "更换密封圈。RAW_ONLY_CHILD_MARKER"))
    run_http_case(setup, monkeypatch, ContinuingClient(), category_scoped=True,
                  expected_group="same_category", continue_once=True,
                  start_payload={"project_id": project.project_id,
                                 "product_id": str(setup.product),
                                 "search_preferences": {"scope": "same_category",
                                                        "include_customer_private": False}})
