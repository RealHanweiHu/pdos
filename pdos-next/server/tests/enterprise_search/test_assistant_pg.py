"""Actual model/read bindings and registered graphs with an offline synthetic provider."""

import json
from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.persistence import create_run
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant
from pdos_next.providers.types import ProviderUsage
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.agent_kernel.test_gateway import configured_route
from tests.enterprise_search.test_retrieval_pg import index, register
from tests.preproject.test_g0 import post, request


class SyntheticClient:
    def __init__(self, *, after_extract=None, forged=False):
        self.calls, self.child_calls, self.messages = 0, 0, []
        self.after_extract, self.forged = after_extract, forged

    def close(self):
        pass

    def turn(self, _route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        messages = kwargs["messages"]
        names = {row["name"] for row in kwargs["tools"]}
        values = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
        self.messages.append((names, deepcopy(messages)))
        if names == {"assistant.passage.read", "result.read"}:
            self.child_calls += 1
            context = json.loads(messages[0]["content"])["context"]
            cid = context["citation_id"]
            if not values or values[-1].get("next_cursor") is not None:
                cursor = values[-1]["next_cursor"] if values else 0
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="synthetic-child-read",
                            name="assistant.passage.read",
                            arguments={"citation_id": cid, "cursor": cursor, "page_chars": 2000},
                        ),
                    ),
                    usage=ProviderUsage(10, 2),
                )
            payload = {
                "rows": [
                    {"citation_id": cid, "statement": "措施为更换密封圈。", "quote": "更换密封圈"}
                ]
            }
        else:
            assert "assistant.passage.read" not in names and "evidence.artifact.read" not in names
            assert "RAW_ONLY_CHILD_MARKER" not in str(messages)
            if not values:
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="synthetic-search",
                            name="assistant.search",
                            arguments={"query": "漏气"},
                        ),
                    ),
                    usage=ProviderUsage(10, 2),
                )
            if "items" in values[-1]:
                if not values[-1]["items"]:
                    payload = {"assistant": {"citation_ids": [], "sources": ["forged"]}}
                else:
                    return ModelTurn(
                        calls=(
                            ToolCall(
                                id="synthetic-extract",
                                name="assistant.extract",
                                arguments={"citation_ids": [values[-1]["items"][0]["citation_id"]]},
                            ),
                        ),
                        usage=ProviderUsage(10, 2),
                    )
            else:
                if self.after_extract:
                    self.after_extract()
                ids = [row["citation_id"] for row in values[-1].get("rows", [])]
                payload = {
                    "assistant": {
                        "citation_ids": [str(uuid4())] if self.forged else list(dict.fromkeys(ids)),
                        "sources": [{"title": "MODEL_FORGED_SOURCE"}],
                        "matched_count": 999,
                    }
                }
        return ModelTurn(
            structured={
                "status": "completed",
                "summary": "参考固定记录：更换密封圈。",
                "result": payload,
                "questions": [],
                "unfinished": [],
            },
            usage=ProviderUsage(10, 2),
        )


def fixture(
    setup, client, *, session_id=None, continued_from_id=None, project_id=None,
    product_id=None, read_sources=()
):
    owner = Bootstrap(
        setup.engine, ports=RuntimePorts(provider_client=client, preload=lambda _: ())
    )
    # This synthetic route exercises the complete disclosed tool/schema surface.
    # Unknown production routes retain the conservative 32k admission guard.
    owner.route_for = lambda _scope: replace(configured_route(), context_window_tokens=200_000)
    owner.provider_for = lambda *_args: "synthetic-assistant-no-egress"
    ctx = setup.ctx if project_id or read_sources else replace(setup.ctx, category_id=None)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=ctx.category_id,
    ) as session:
        binding = None
        if read_sources:
            from pdos_next.agent_kernel.api import StartInput

            binding = owner.binding_for(session, ctx, StartInput(
                goal="比较明确选择的固定资料", idempotency_key=str(uuid4()),
                product_id=product_id,
                sources=[{key: value for key, value in ref.items() if key != "product_id"}
                         for ref in read_sources],
            ))
        run = create_run(
            session,
            ctx,
            goal="以前漏气怎么处理？",
            writer_id=setup.agent,
            intent_key=str(uuid4()),
            token_limit=2_000_000,
            data_categories=binding.data_categories if binding else ("internal",),
            private_context=binding.private_context if binding else False,
            customer_identities=binding.customer_identities if binding else (),
            session_id=session_id,
            continued_from_id=continued_from_id,
            product_id=setup.product if project_id else product_id,
            project_id=project_id,
            read_sources=binding.read_sources if binding else read_sources,
        )
        identity = run.id
    scope = owner.store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=ctx.category_id,
        run_id=identity,
    )
    adapters = replace(owner.adapters(), cost_required=False)
    host = BoundHost(owner.store, adapters)
    adapter = owner._assistant_adapter
    # Only accounting is synthetic; the child retains the actual registry, read
    # bindings, gateway, source checks, server rows and production graph.
    adapter.graph = AssistantExtractGraph(host, adapter)
    from pdos_next.enterprise_search.comparison_graph import AssistantComparisonGraph

    adapter.comparison_graph = AssistantComparisonGraph(host, adapter)
    return owner, scope, host, adapter


def execute(owner, scope, host):
    return AgentKernel(host, owner.registry).execute(
        scope,
        goal="以前漏气怎么处理？",
        execution_key={"synthetic": str(scope.run_id)},
    )["output"]


def test_actual_search_citation_isolated_extract_and_server_answer_are_replayable(setup):
    identity = register(
        setup, "D16 气密记录", "接口漏气。措施：更换密封圈。\nRAW_ONLY_CHILD_MARKER\n"
    )
    index(setup, identity)
    client = SyntheticClient()
    owner, scope, host, adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    assert "assistant" in output["result"], [
        row["content"]
        for _names, messages in client.messages
        for row in messages
        if row["role"] == "tool"
    ]
    answer = output["result"]["assistant"]
    assert answer["kind"] == "enterprise" and answer["lookup"] == "cited"
    assert answer["matched_count"] == 1 and answer["sources"][0]["quote"] == "更换密封圈"
    assert answer["sources"][0]["source_id"] == str(identity)
    assert "MODEL_FORGED_SOURCE" not in str(output)
    assert client.calls == 5 and client.child_calls == 2
    with owner.store.transaction(scope) as (session, _run):
        calls = session.scalars(
            select(AgentToolCall).where(
                AgentToolCall.run_id == scope.run_id,
                AgentToolCall.state == "completed",
            )
        ).all()
        search = next(row for row in calls if row.tool == "assistant.search")
        extraction = next(row for row in calls if row.tool == "assistant.extract")
        saved_search, saved_extract = deepcopy(search.result), deepcopy(extraction.result)
        assert all(row.execution_binding["kind"] in {"read", "model"} for row in calls)
        raw = next(row for row in calls if row.tool == "assistant.passage.read")
        assert raw.execution_binding["isolation"] == "assistant_extract"
        assert "RAW_ONLY_CHILD_MARKER" in raw.result["text"]
    assert adapter.restore_search(scope, {}, saved_search) == saved_search
    assert (
        adapter.restore_extract(scope, {"citation_ids": answer["citation_ids"]}, saved_extract)
        == saved_extract
    )
    assert client.calls == 5
    url = answer["sources"][0]["url"].removeprefix("/api")
    viewed = setup.client.get(url, headers=setup.headers, params={"page_chars": 20})
    assert viewed.status_code == 200 and len(viewed.json()["text"]) <= 20, viewed.text
    assert (
        setup.client.get(
            url, headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
        ).status_code
        == 403
    )
    assert (
        setup.client.get(
            url, headers=setup.headers, params={"tenant_id": str(setup.tenant)}
        ).status_code
        == 422
    )
    assert client.calls == 5  # Opening a source has no model side effect.
    saved = setup.client.get(f"/v1/personal/agent-runs/{scope.run_id}", headers=setup.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["result"]["assistant"] == answer
    with pytest.raises(DomainError):
        adapter.passage(scope, {"citation_id": answer["citation_ids"][0]})
    other_owner, other, _other_host, other_adapter = fixture(setup, SyntheticClient())
    with pytest.raises(DomainError):
        other_adapter._selected(other, [UUID(answer["citation_ids"][0])])
    other_owner.store.current(other)
    with pytest.raises(DomainError) as failure:
        adapter.guard_action(scope, "category.knowledge.add")
    assert failure.value.detail["reason_key"] == "assistant_source_carry_required"


def test_structured_knowledge_extract_uses_no_child_model_and_no_match_has_real_state(setup):
    response = post(
        setup,
        request(
            setup,
            "category.knowledge.add",
            {
                "kind": "boundary",
                "content": {"definition": "漏气时核对密封圈，已登记内部边界。"},
            },
        ),
    )
    assert response.status_code == 200, response.text
    from pdos_next.domain.preproject.category_models import KnowledgeEntry
    from pdos_next.enterprise_search.indexing import project
    from tests.enterprise_search.test_retrieval_pg import session_for

    with session_for(setup) as session:
        row = session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.lineage_id == UUID(response.json()["subject_id"]),
            )
        )
        project(session, setup.ctx, "knowledge", row.id)
    client = SyntheticClient()
    owner, scope, host, _adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    assert output["result"]["assistant"]["lookup"] == "cited"
    assert output["result"]["assistant"]["sources"][0]["source_type"] == "knowledge"
    assert client.calls == 3 and client.child_calls == 0
    changed = post(
        setup,
        request(
            setup,
            "category.knowledge.add",
            {
                "kind": "boundary",
                "content": {"definition": "漏气时采用新的复验流程。"},
                "supersedes": {"lineage_id": response.json()["subject_id"], "expected_version": 1},
            },
        ),
    )
    assert changed.status_code == 200, changed.text
    record = setup.client.get(f"/v1/personal/agent-runs/{scope.run_id}", headers=setup.headers)
    assert record.status_code == 200, record.text
    answer = record.json()["result"]["result"]["assistant"]
    assert answer["sources"][0]["currentness"] == "updated"
    assert "已登记内部边界" in answer["sources"][0]["quote"]
    assert "新的复验流程" not in str(answer)
    assert client.calls == 3


def test_final_source_withdrawal_removes_quotes_and_dependent_prose(setup):
    identity = register(setup, "漏气记录", "措施：更换密封圈。RAW_ONLY_CHILD_MARKER")
    index(setup, identity)

    def withdraw():
        with Session(setup.admin) as session, session.begin():
            session.get(Artifact, identity).status = "withdrawn"

    client = SyntheticClient(after_extract=withdraw)
    owner, scope, host, _adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "partial", output
    assert output["result"]["assistant"]["sources"] == []
    assert "更换密封圈" not in str(output)


def test_forged_citation_cannot_become_a_verified_company_source(setup):
    index(setup, register(setup, "漏气记录", "措施：更换密封圈。RAW_ONLY_CHILD_MARKER"))
    client = SyntheticClient(forged=True)
    owner, scope, host, _adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "partial", output
    assert output["result"]["assistant"]["sources"] == []
    assert output["result"]["assistant"]["lookup"] == "uncited"


def test_actual_no_match_is_not_mislabeled_as_no_lookup(setup):
    client = SyntheticClient()
    owner, scope, host, _adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    answer = output["result"]["assistant"]
    assert answer["lookup"] == "no_match" and answer["matched_count"] == 0
    assert "本人当前可读" in answer["notice"]


@pytest.mark.parametrize("change", ["updated", "withdrawn", "revoked"])
def test_saved_answer_and_carried_history_recheck_sources_without_inference(setup, change):
    identity = register(setup, "漏气历史记录", "更换密封圈。RAW_ONLY_CHILD_MARKER")
    index(setup, identity)
    client = SyntheticClient()
    owner, scope, host, adapter = fixture(setup, client)
    client.after_extract = lambda: host.emit(scope, {"type": "text_delta", "text": "更换密封圈"})
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    source = output["result"]["assistant"]["sources"][0]
    with owner.store.transaction(scope) as (_session, run):
        session_id = run.session_id
    child_owner, child, _host, child_adapter = fixture(
        setup, SyntheticClient(), session_id=session_id, continued_from_id=scope.run_id
    )
    frozen = child_owner.project_context(child, "继续核对")
    assert frozen["conversation"]["turns"][0]["outcome_state"] == "current"
    assert source["citation_id"] in child_adapter._carried(child)[0]
    assert child_adapter.guard(child) == frozenset({"internal"})
    product = setup.client.post(
        "/v1/personal/work-products/from-run",
        headers=setup.headers,
        json={
            "run_id": str(scope.run_id),
            "kind": "document",
            "request_key": str(uuid4()),
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]
    initial_events = setup.client.get(
        f"/v1/personal/agent-runs/{scope.run_id}/events", headers=setup.headers
    )
    assert initial_events.status_code == 200 and "更换密封圈" in initial_events.text
    with Session(setup.admin) as session, session.begin():
        if change == "revoked":
            session.delete(
                session.scalar(
                    select(Grant).where(
                        Grant.category_id == setup.category, Grant.principal_id == setup.human
                    )
                )
            )
        else:
            artifact = session.get(Artifact, identity)
            if change == "updated":
                # Synthetic version drift; neither current body nor old ledger is rewritten.
                artifact.revision += 1
            else:
                artifact.status = "withdrawn"
    saved = setup.client.get(f"/v1/personal/agent-runs/{scope.run_id}", headers=setup.headers)
    page = setup.client.get(source["url"].removeprefix("/api"), headers=setup.headers)
    events = setup.client.get(
        f"/v1/personal/agent-runs/{scope.run_id}/events", headers=setup.headers
    )
    document = setup.client.get(f"/v1/personal/work-products/{product_id}", headers=setup.headers)
    products = setup.client.get(
        "/v1/personal/work-products", headers=setup.headers, params={"session_id": str(session_id)}
    )
    assert page.status_code >= 400 and "RAW_ONLY_CHILD_MARKER" not in page.text
    if change == "updated":
        assert saved.status_code == 200, saved.text
        answer = saved.json()["result"]["result"]["assistant"]
        assert answer["sources"][0]["quote"] == "更换密封圈"
        assert answer["sources"][0]["currentness"] == "updated"
        assert "资料已更新" in answer["notice"]
        assert events.status_code == 200, events.text
        assert document.status_code == 200, document.text
        assert document.json()["source_currentness"] == "updated"
        assert "更换密封圈" in document.json()["body"]
        assert products.json()["items"][0]["source_currentness"] == "updated"
        assert child_adapter.guard(child) == frozenset({"internal"})
        child_owner.check_conversation(child)
        with pytest.raises(DomainError) as stale:
            adapter.restore_extract(scope, {"citation_ids": [source["citation_id"]]}, {"rows": []})
        assert stale.value.code == "SOURCE_STALE"
    else:
        assert saved.status_code == 403 and "更换密封圈" not in saved.text
        assert events.status_code == document.status_code == 403
        assert "更换密封圈" not in events.text + document.text
        assert products.status_code == 200 and products.json()["items"] == []
        edit = setup.client.post(
            f"/v1/personal/work-products/{product_id}/revisions",
            headers=setup.headers,
            json={
                "expected_revision": 1,
                "title": "不可复用旧依据",
                "body": "更换密封圈",
                "request_key": str(uuid4()),
            },
        )
        assert edit.status_code == 403
        with pytest.raises(DomainError):
            child_adapter.guard(child)
        with pytest.raises(DomainError):
            child_owner.check_conversation(child)
    assert client.calls == 5


def test_history_page_outside_frozen_recent_turns_retains_source_revocation_guard(setup):
    identity = register(setup, "漏气早期记录", "更换密封圈。RAW_ONLY_CHILD_MARKER")
    index(setup, identity)
    owner, first, host, _adapter = fixture(setup, SyntheticClient())
    answer = execute(owner, first, host)["result"]["assistant"]
    with owner.store.transaction(first) as (_session, run):
        session_id = run.session_id
    previous = first.run_id
    for _index in range(10):
        prior_owner, prior, _host, _adapter = fixture(
            setup, SyntheticClient(), session_id=session_id, continued_from_id=previous
        )
        prior_owner.store.finish(
            prior,
            {
                "status": "completed",
                "summary": "中间轮没有资料正文。",
                "result": {},
                "questions": [],
                "unfinished": [],
            },
        )
        previous = prior.run_id

    class HistoryClient:
        def turn(self, _route, **kwargs):
            values = [row for row in kwargs["messages"] if row["role"] == "tool"]
            if not values:
                return ModelTurn(
                    calls=(
                        ToolCall(
                            id="synthetic-history",
                            name="conversation.history",
                            arguments={"before": self.before, "page_size": 10},
                        ),
                    ),
                    usage=ProviderUsage(10, 2),
                )
            assert str(first.run_id) in values[-1]["content"]
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "已读早期处理记录。",
                    "result": {},
                    "questions": [],
                    "unfinished": [],
                },
                usage=ProviderUsage(10, 2),
            )

    client = HistoryClient()
    current_owner, scope, current_host, adapter = fixture(
        setup, client, session_id=session_id, continued_from_id=previous
    )
    frozen = current_owner.project_context(scope, "继续核对")
    turns = frozen["conversation"]["turns"]
    assert str(first.run_id) not in {row["run_id"] for row in turns}
    client.before = turns[-1]["run_id"]
    # The new turn already receives a reissued fixed-source preview, while the
    # original CID only enters context when the older history page is read.
    assert adapter._carried(scope)[0]
    assert answer["citation_ids"][0] not in adapter._carried(scope)[0]
    output = execute(current_owner, scope, current_host)
    assert output["status"] == "completed", output
    assert answer["citation_ids"][0] in adapter._carried(scope)[0]
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, identity).status = "withdrawn"
    with pytest.raises(DomainError):
        adapter.guard(scope)
    saved = setup.client.get(f"/v1/personal/agent-runs/{scope.run_id}", headers=setup.headers)
    assert saved.status_code == 403 and "更换密封圈" not in saved.text
