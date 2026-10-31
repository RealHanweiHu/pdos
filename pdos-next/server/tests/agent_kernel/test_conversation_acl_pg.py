"""Root-only actual private/cross-category READ and batched historical ACL checks."""

import hashlib
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Category, Grant
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_personal_context_pins_pg import pin_personal
from tests.agent_kernel.test_run_continuation import scope, start, synthetic_artifact


class MaterialsProvider:
    """Only scripted control flow, no provider or model-quality claim."""

    def __init__(self, identities):
        self.identities, self.calls, self.read = identities, 0, None

    def turn(self, _route, **request):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        if self.calls == 1:
            return ModelTurn(calls=(ToolCall(
                id="selected-materials", name="assistant.materials.read",
                arguments={"artifact_ids": [str(item) for item in self.identities]}),),
                usage=ProviderUsage(10, 2))
        import json

        self.read = json.loads(next(message["content"] for message in reversed(request["messages"])
                                    if message["role"] == "tool"))
        assert self.read["returned"] == 2
        return ModelTurn(structured={"status": "completed",
            "summary": "已读取选定资料，未形成事实结论。",
            "result": {}, "questions": [], "unfinished": []}, usage=ProviderUsage(10, 2))


def test_actual_private_cross_category_read_uses_owner_and_one_batch_then_revoke(setup):
    first = synthetic_artifact(setup, "本人私有资料第一品类")
    other_category, second = uuid4(), uuid4()
    content = "本人另一品类私有资料。"
    with Session(setup.admin) as session, session.begin():
        session.add(Category(id=other_category, tenant_id=setup.tenant, owner_id=setup.peer,
                             name="ACL合成只读品类", purpose="实际跨品类权限验证"))
        session.flush()
        session.add(Grant(tenant_id=setup.tenant, category_id=other_category,
                          principal_id=setup.human, can_write=False))
        session.add(Artifact(id=second, tenant_id=setup.tenant, category_id=other_category,
            product_id=None, owner_id=setup.human, title="本人第二品类私有来源",
            source_label="合成", content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            visibility="private", revision=1, status="active"))
    actual = pin_personal(setup, [first, second])
    with Session(setup.admin) as session, session.begin():
        from pdos_next.agent_kernel.models import AgentRun

        run = session.get(AgentRun, actual.run_id)
        assert run.state == "queued"
        # The unmetered synthetic gateway reserves the complete wire byte bound,
        # including the production registry. Keep that surface and its guard;
        # give this isolated fixture the same 2m budget as the assistant PG suite.
        run.token_limit = 2_000_000
    provider = MaterialsProvider([first, second])
    owner = Bootstrap(setup.engine, ports=RuntimePorts(
        provider_client=provider, preload=lambda _: ()))
    owner.route_for = lambda _: replace(configured_route(), context_window_tokens=200_000)
    owner.provider_for = lambda *_: "synthetic-assistant-no-egress"
    host = BoundHost(owner.store, replace(owner.adapters(), cost_required=False))
    output = AgentKernel(host, owner.registry).execute(actual, goal="只依据这些资料继续核对。")
    assert output["output"]["status"] == "completed", output
    assert provider.calls == 2 and provider.read is not None
    child, _ = start(setup, personal=True, continue_from_run_id=str(actual.run_id))
    bound = scope(setup, child, personal=True)
    frozen = owner.project_context(bound, "继续")
    assert frozen["conversation"]["turns"][0]["outcome_state"] == "current"
    # Both private sources were read; neither is a final citation. The history
    # dependency must retain them and ordinary owner RLS must continue to read.
    with Session(setup.admin) as session:
        from pdos_next.agent_kernel.models import AgentRun
        access = session.get(AgentRun, child).versions["conversation_access"]
        assert {str(first), str(second)} <= {item["source_id"]
            for value in access.values() for item in value["citations"]}
    batches = []
    def observe(_connection, _cursor, statement, _params, _context, _many):
        if "conversation_history_metadata" in statement:
            batches.append(statement)
    event.listen(setup.engine, "before_cursor_execute", observe)
    try:
        owner.check_conversation(bound)
    finally:
        event.remove(setup.engine, "before_cursor_execute", observe)
    assert len(batches) == 1
    assert owner.project_context(bound, "继续")["conversation"] == frozen["conversation"]
    peer = setup.client.get(f"/v1/personal/agent-runs/{actual.run_id}",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"})
    assert peer.status_code == 403
    with Session(setup.admin) as session, session.begin():
        session.delete(session.scalar(select(Grant).where(
            Grant.category_id == other_category, Grant.principal_id == setup.human)))
    # This child also explicitly carries the same fixed materials as its current
    # input. That prerequisite runs before historical ACL, and must retain its
    # own error rather than be mislabeled as an old-answer failure.
    batches.clear()
    event.listen(setup.engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(DomainError) as failure:
            owner.check_conversation(bound)
    finally:
        event.remove(setup.engine, "before_cursor_execute", observe)
    assert failure.value.reason == "SOURCE_UNAVAILABLE"
    assert failure.value.message == "选定版本当前不可读，请重新选择。"
    assert batches == []  # The current selection stopped before history assembly.

    # Independently exercise the persisted historical manifest, without clearing
    # or editing the frozen selection merely to reach this layer. The unquoted
    # second source must still hide that historical answer in one metadata batch.
    from pdos_next.agent_kernel.conversation_acl import classify

    event.listen(setup.engine, "before_cursor_execute", observe)
    try:
        with owner.store.transaction(bound) as (session, run):
            states = classify(session, run.versions["conversation_access"], consumer=run)
    finally:
        event.remove(setup.engine, "before_cursor_execute", observe)
    assert states[str(actual.run_id)] == "hidden"
    assert len(batches) == 1
    assert provider.calls == 2


def test_actual_read_without_explicit_run_sources_keeps_goal_and_hides_revoked_answer(setup):
    from pdos_next.agent_kernel.models import AgentRun
    from pdos_next.models import ObjectAudience
    from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
    from tests.enterprise_search.test_retrieval_pg import index
    from tests.preproject.test_g0 import post, request

    registered = post(setup, request(setup, "evidence.artifact.register", {
        "title": "漏气受众共享历史记录", "content": "更换密封圈。RAW_ONLY_CHILD_MARKER",
        "source_label": "合成当前受众", "visibility": "audience",
    }), actor=setup.peer)
    assert registered.status_code == 200, registered.text
    from uuid import UUID

    identity = UUID(registered.json()["subject_id"])
    with Session(setup.admin) as session, session.begin():
        audience = ObjectAudience(tenant_id=setup.tenant, category_id=setup.category,
            object_type="artifact_versions", subject_id=identity, owner_id=setup.peer,
            principal_id=setup.human)
        session.add(audience)
        session.flush()
        audience_id = audience.id
    index(setup, identity)
    provider = SyntheticClient()
    _reader, actual, main_host, _adapter = fixture(setup, provider)
    output = execute(_reader, actual, main_host)
    assert output["status"] == "completed", output
    assert provider.calls == 5
    with Session(setup.admin) as session:
        assert session.get(AgentRun, actual.run_id).read_sources == []
    child, _ = start(setup, personal=True, continue_from_run_id=str(actual.run_id))
    bound = scope(setup, child, personal=True)
    owner = Bootstrap(setup.engine)
    frozen = owner.project_context(bound, "继续")
    assert frozen["conversation"]["turns"][0]["outcome_state"] == "current"
    with Session(setup.admin) as session, session.begin():
        session.delete(session.get(ObjectAudience, audience_id))
    with pytest.raises(DomainError) as failure:
        owner.check_conversation(bound)
    assert failure.value.reason == "CONVERSATION_HISTORY_REVOKED"
    history = owner.conversation_history(bound, {"page_size": 10})
    prior = history["turns"][0]
    assert prior["run_id"] == str(actual.run_id) and prior["goal"] == "以前漏气怎么处理？"
    assert prior["outcome_state"] == "hidden" and prior["historical_outcome"] is None
    assert prior["sources"] == [] and "更换密封圈" not in str(history)
    assert provider.calls == 5
