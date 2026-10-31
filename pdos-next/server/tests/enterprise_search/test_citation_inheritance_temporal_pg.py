"""Authenticated continuation through durable workflows, with an offline provider."""

import os

import pytest

from tests.enterprise_search.test_assistant_pg import SyntheticClient
from tests.enterprise_search.test_assistant_temporal_pg import run_http_case
from tests.enterprise_search.test_citation_inheritance_pg import FollowupClient
from tests.enterprise_search.test_retrieval_pg import index, register


class ContinuingClient:
    def __init__(self):
        self.clients = [SyntheticClient()]

    @property
    def calls(self):
        return sum(client.calls for client in self.clients)

    @property
    def child_calls(self):
        return sum(client.child_calls for client in self.clients)

    def continue_with(self, cid):
        self.clients.append(FollowupClient(selector={"reference_id": cid}))

    def turn(self, route, **kwargs):
        return self.clients[-1].turn(route, **kwargs)

    def close(self):
        pass


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal and checkpoint runtime required",
)
def test_http_continuation_reissues_citation_and_replay_does_not_repeat_inference(
    setup, monkeypatch
):
    index(setup, register(setup, "漏气处理记录", "更换密封圈。RAW_ONLY_CHILD_MARKER"))
    run_http_case(setup, monkeypatch, ContinuingClient(), continue_once=True)
