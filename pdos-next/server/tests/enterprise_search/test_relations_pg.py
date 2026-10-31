"""Registered one-hop references, fixed source proofs, and no recursive/private disclosure."""
# ruff: noqa: F811, F401 -- the actual domain fixture dependency tree

import hashlib
import json
from uuid import UUID

import pytest
from change_execution.test_transactions import command, create_payload, post
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.enterprise_search import assistant_ledger as ledger
from pdos_next.enterprise_search.indexing import project
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from pdos_next.providers.types import ProviderUsage
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_business_sources_pg import (
    accepted_work,
    apply_event,
    change_work,
    known_configuration,
    launch_work,
    native_search,
    native_session,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from tests.enterprise_search.test_retrieval_pg import register


class RelatedClient:
    def __init__(self, query):
        self.query, self.calls, self.related = query, 0, None
        self.continuation = None

    def close(self):
        pass

    def continue_with(self, cid):
        self.continuation = cid

    def turn(self, _route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        values = [json.loads(row["content"]) for row in kwargs["messages"] if row["role"] == "tool"]
        if not values and self.continuation:
            call = ToolCall(
                id="inherited",
                name="assistant.citations.read",
                arguments={"reference_id": self.continuation},
            )
        elif not values:
            call = ToolCall(
                id="search",
                name="assistant.search",
                arguments={
                    "query": self.query,
                    "source_types": ["issue", "capa", "change"],
                    "limit": 1,
                },
            )
        elif "items" in values[-1]:
            self.related = (
                values[-1]["items"][0]
                if self.continuation
                else next(
                    row
                    for row in values[-1]["items"]
                    if row.get("relation") and row["source_type"] == "issue"
                )
            )
            call = ToolCall(
                id="extract",
                name="assistant.extract",
                arguments={
                    "citation_ids": [self.related["citation_id"]],
                },
            )
        else:
            assert values[-1]["rows"][0]["citation_id"] == self.related["citation_id"]
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "按明确登记的原问题核对历史。",
                    "result": {"assistant": {"citation_ids": [self.related["citation_id"]]}},
                    "questions": [],
                    "unfinished": [],
                },
                usage=ProviderUsage(10, 2),
            )
        return ModelTurn(calls=(call,), usage=ProviderUsage(10, 2))


def test_registered_change_expands_only_one_hop_and_origin_revocation_hides_relation(change_work):
    work, person = change_work, change_work.quality
    extra = register(work.setup, "变更单独登记的依据", "关系验证的额外原生依据。")
    data = create_payload(work)
    data.update(title="RELALPHA-9801 明确关联", references=[])
    data["sources"].append(
        {
            "id": str(extra),
            "revision": 1,
            "kind": "artifact",
            "position": "line:1;quote_sha256:"
            + hashlib.sha256("关系验证的额外原生依据。".encode()).hexdigest(),
        }
    )
    body, _ = command(work, "change.request.create", data)
    response = post(person, body)
    assert response.status_code == 200, response.text
    assert apply_event(person, response.json()["id"])["processed"] == 1
    found = native_search(person, "RELALPHA-9801", ["issue", "capa", "change"], limit=1)
    assert found["direct_returned"] == found["related_returned"] == 1, found
    assert [row["source_type"] for row in found["items"]] == ["change", "issue"]
    # The Issue has CAPA, but is a related result, not a new expansion seed.
    assert found["items"][1]["object_id"] == str(work.issue_id)
    assert found["items"][1]["relation"]["type"] == "change_issue"
    assert found["items"][1]["relation"]["source_id"] == found["items"][0]["source_id"]
    assert all(
        "facts" not in row and "structured" not in row and "body" not in row
        for row in found["items"]
    )
    narrowed = native_search(person, "RELALPHA-9801", ["change"], limit=1)
    assert narrowed["returned"] == 1 and narrowed["related_returned"] == 0
    denied = person.client.post(
        "/v1/personal/enterprise-search",
        json={
            "query": "RELALPHA-9801",
            "source_types": ["issue", "capa", "change"],
        },
        headers={"Authorization": f"Bearer {work.setup.tokens[work.setup.peer]}"},
    )
    assert denied.status_code == 200 and denied.json()["returned"] == 0
    assert "RELALPHA" not in str(denied.json()["items"])

    client = RelatedClient("RELALPHA-9801")
    owner, scope, host, adapter = fixture(person, client)
    output = execute(owner, scope, host)
    assert output["status"] == "partial", output  # Related Issue is readable but unindexed.
    answer = output["result"]["assistant"]
    assert client.calls == 3 and answer["sources"][0]["relation"]["type"] == "change_issue"
    from urllib.parse import parse_qs, urlsplit

    destination = parse_qs(urlsplit(answer["sources"][0]["object_url"]).query)
    assert destination["issue"] == [str(work.issue_id)]
    assert destination["build"] == [str(work.build_id)]
    assert destination["panel"] == ["quality"]
    with owner.store.transaction(scope) as (session, _run):
        issued = ledger.issued(session, scope)
    related = {client.related["citation_id"]: issued[client.related["citation_id"]]}
    assert not adapter._current(scope, related)[1]
    # Already direct matches also retain their explicit relationship; dedup
    # does not erase that fact or count them as extra relation candidates.
    with native_session(person) as session:
        project(session, person.ctx, "issue", UUID(client.related["source_id"]))
        project(session, person.ctx, "capa", UUID(client.related["source_id"]))
    paired = native_search(person, work.issue_view["issue"]["title"], ["issue", "capa"])
    assert paired["direct_returned"] == 2 and paired["related_returned"] == 0
    assert {row["relation"]["type"] for row in paired["items"]} == {"issue_capa", "capa_issue"}
    with Session(person.admin) as session, session.begin():
        session.get(Artifact, extra).status = "withdrawn"
    # The Issue itself is still readable. Its private Change origin is not:
    # the relation cannot reveal that origin's ID or bypass its invalid evidence.
    actual, missing = adapter._current(scope, related)
    assert not actual and set(missing.values()) == {"relation_origin_unavailable"}
    with pytest.raises(DomainError):
        adapter.guard(scope)


def test_registered_build_parent_expands_unindexed_records_without_text_inference(change_work):
    work, person = change_work, change_work.quality
    with native_session(person) as session:
        assert project(session, person.ctx, "build", work.build_id)["status"] == "ready"
    found = native_search(person, str(work.build_id), ["build", "test_run"], limit=1)
    assert found["direct_returned"] == 1 and found["related_returned"] > 0, found
    assert found["items"][0]["source_id"] == str(work.build_id)
    assert any(row["source_type"] == "test_run" for row in found["items"][1:])
    assert all(row["relation"]["type"].startswith("build_") for row in found["items"][1:])
    assert (
        len({(row["source_type"], row["source_id"]) for row in found["items"]}) == found["returned"]
    )
    assert found["returned"] <= 21
    artifact = register(work.setup, "只有文字提到Build", str(work.build_id))
    with native_session(person) as session:
        project(session, person.ctx, "artifact", artifact)
    literal = native_search(person, str(work.build_id), ["artifact", "build", "test_run"], limit=1)
    # Exact registered Build still wins over a text mention. A raw document is
    # never a graph seed even when its body contains real object identities.
    only_text = native_search(person, "只有文字提到Build", ["artifact"])
    assert only_text["returned"] == 1 and only_text["related_returned"] == 0
    assert literal["items"][0]["source_id"] == str(work.build_id)
