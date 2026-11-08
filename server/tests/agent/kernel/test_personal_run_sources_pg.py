"""P91 / D42: a personal Run pins only its Human requester's currently readable sources."""

import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.api import StartInput
from pdos_next.agent.kernel.models import AgentRun, AgentToolCall
from pdos_next.agent.kernel.persistence import create_run
from pdos_next.agent.kernel.personal_sources import resolve
from pdos_next.agent.kernel.types import ModelTurn, ToolCall
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Artifact, Category, Grant, now
from pdos_next.core.service import Context
from pdos_next.errors import DomainError
from pdos_next.providers.types import ProviderUsage
from tests.agent.enterprise_search.test_assistant_pg import SyntheticClient, execute
from tests.agent.enterprise_search.test_retrieval_pg import register

BODY = "合成维修记录（非真实客户资料）\n漏气时更换密封圈并复测\n"


def other_category(setup, *, members):
    identity = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Category(
                id=identity,
                tenant_id=setup.tenant,
                name=f"合成品类 {identity.hex[:6]}",
                purpose="P91 合成跨品类来源",
                owner_id=members[0],
            )
        )
        session.flush()
        session.add_all(
            Grant(
                tenant_id=setup.tenant,
                category_id=identity,
                principal_id=member,
                can_write=True,
                expires_at=now() + timedelta(days=1),
            )
            for member in members
        )
    return identity


def in_category(setup, category):
    return SimpleNamespace(
        **{**vars(setup), "category": category, "ctx": replace(setup.ctx, category_id=category)}
    )


def personal(setup):
    return replace(setup.ctx, category_id=None)


def start(setup, sources, **extra):
    return setup.client.post(
        "/v1/personal/agent-runs",
        headers=setup.headers,
        json={
            "goal": "按我选的资料回答漏气怎么处理",
            "idempotency_key": str(uuid4()),
            "sources": [
                {"artifact_id": str(identity), "expected_revision": 1} for identity in sources
            ],
            **extra,
        },
    )


def stored(setup, run_id):
    with Session(setup.admin) as session:
        return session.get(AgentRun, UUID(run_id))


def revoke(setup, category, principal):
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Grant)
            .where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == category,
                Grant.principal_id == principal,
            )
            .values(expires_at=now() - timedelta(seconds=1))
        )


def test_personal_start_binds_readable_sources_across_categories_with_receipt(setup):
    first = register(setup, "本品类合成资料", BODY)
    second_category = other_category(setup, members=[setup.human, setup.agent])
    second = register(in_category(setup, second_category), "他品类合成资料", BODY)
    response = start(setup, [first, second])
    assert response.status_code == 202, response.text
    run = stored(setup, response.json()["run_id"])
    assert run.category_id is None and run.product_id is None and run.proposal_id is None
    assert {ref["artifact_id"] for ref in run.read_sources} == {str(first), str(second)}
    receipt = {row["artifact_id"]: row for row in run.versions["personal_sources"]}
    assert receipt[str(first)]["category_id"] == str(setup.category)
    assert receipt[str(second)]["category_id"] == str(second_category)
    assert {row["data_category"] for row in receipt.values()} == {"internal"}
    # Only the requester reads the personal Run; another member of the category does not.
    own = setup.client.get(f"/v1/personal/agent-runs/{run.id}", headers=setup.headers)
    assert own.status_code == 200 and own.json()["status"] != "hidden"
    peer = setup.client.get(
        f"/v1/personal/agent-runs/{run.id}",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
    )
    assert peer.status_code == 403 or peer.json().get("status") == "hidden"


def test_uploaded_docx_original_is_a_personal_source_with_customer_original_class(setup, tmp_path):
    """D55 + P91: a scanned, parsed DOCX original binds in a personal Run like any source."""
    import base64

    from pdos_next.core.contracts import UploadInput
    from pdos_next.originals.access import upload
    from pdos_next.originals.object_storage import LocalPrivateObjectStore
    from pdos_next.originals.security import configure
    from tests.originals.office_fixture import docx_bytes
    from tests.security_fixture import secured_parse, synthetic_runtime

    configure(setup.engine, synthetic_runtime())
    try:
        store = LocalPrivateObjectStore(tmp_path / "originals")
        data = UploadInput(
            title="合成客户规格",
            filename="合成客户规格.docx",
            visibility="private",
            source_label="P91 合成原件",
            expected_revision=1,
            idempotency_key=str(uuid4()),
            content_base64=base64.b64encode(docx_bytes()).decode("ascii"),
        )
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            receipt = upload(session, setup.ctx, None, data, store)
        reference = {
            "category_id": str(setup.category),
            "actor_id": str(setup.human),
            "requester_id": str(setup.human),
            "tenant_id": str(setup.tenant),
            "product_id": None,
            "subject_id": receipt["subject_id"],
        }
        assert secured_parse(setup.engine, reference, store)["status"] == "parsed"
        with Session(setup.admin) as session:
            source = session.scalar(
                select(Artifact).where(Artifact.original_id == UUID(receipt["subject_id"]))
            ).id
        response = start(setup, [source])
        assert response.status_code == 202, response.text
        run = stored(setup, response.json()["run_id"])
        assert run.versions["personal_sources"][0]["data_category"] == "customer_original"
        assert "customer_original" in run.data_categories and run.private_context
    finally:
        configure(setup.engine, None)


def test_source_in_category_without_requester_membership_is_forbidden(setup):
    closed = other_category(setup, members=[setup.peer, setup.agent])
    response = setup.client.post(
        f"/v1/categories/{closed}/commands",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        json={
            "command_id": str(uuid4()),
            "idempotency_key": str(uuid4()),
            "category_id": str(closed),
            "product_id": None,
            "expected_revision": 1,
            "source_read_set": [],
            "operation": "evidence.artifact.register",
            "payload": {
                "title": "无权品类资料",
                "content": BODY,
                "source_label": "P91 合成",
                "visibility": "category",
            },
        },
    )
    assert response.status_code == 200, response.text
    foreign = UUID(response.json()["subject_id"])
    rejected = start(setup, [foreign])
    assert rejected.status_code == 403, rejected.text
    assert "FORBIDDEN_SCOPE" in rejected.text or "SOURCE_UNAVAILABLE" in rejected.text
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(AgentRun).where(
                    AgentRun.requester_id == setup.human,
                    AgentRun.category_id.is_(None),
                )
            )
            is None
        )


def test_source_category_without_ai_read_grant_is_forbidden(setup):
    readable = other_category(setup, members=[setup.human])
    source = register(in_category(setup, readable), "小Pai无授权品类资料", BODY)
    rejected = start(setup, [source])
    assert rejected.status_code == 403, rejected.text
    assert "小Pai当前没有该来源品类的读取授权" in rejected.text


def test_cross_tenant_and_unknown_sources_are_forbidden(setup):
    other_category_id, other_artifact = uuid4(), uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Category(
                id=other_category_id,
                tenant_id=setup.other_tenant,
                name="他租户品类",
                purpose="P91 合成",
                owner_id=setup.other_human,
            )
        )
        session.flush()
        session.add(
            Artifact(
                id=other_artifact,
                tenant_id=setup.other_tenant,
                category_id=other_category_id,
                owner_id=setup.other_human,
                title="他租户资料",
                source_label="P91 合成",
                content=BODY,
                content_hash="0" * 64,
                visibility="category",
            )
        )
    for identity in (other_artifact, uuid4()):
        response = start(setup, [identity])
        assert response.status_code == 403, response.text


def test_ai_identity_cannot_bind_personal_sources(setup):
    source = register(setup, "合成资料", BODY)
    agent = Context(setup.tenant, setup.agent, setup.human)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.agent, requester_id=setup.human, category_id=None
    ) as session:
        with pytest.raises(DomainError) as error:
            resolve(session, agent, source, 1)
        assert error.value.reason == "FORBIDDEN_SCOPE"
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.agent, requester_id=setup.human, category_id=None
    ) as session:
        with pytest.raises(DomainError):
            create_run(
                session,
                agent,
                goal="AI 代绑来源",
                writer_id=setup.agent,
                intent_key=str(uuid4()),
                read_sources=[
                    {"artifact_id": str(source), "expected_revision": 1, "product_id": None}
                ],
            )


def test_database_guard_admits_only_receipted_requester_sources(setup, monkeypatch):
    import pdos_next.agent.kernel.personal_sources as personal_sources

    source = register(setup, "合成资料", BODY)
    ref = {"artifact_id": str(source), "expected_revision": 1, "product_id": None}
    receipt = {**ref, "category_id": str(setup.category), "data_category": "internal"}
    forged = (
        None,  # no category receipt at all
        [{**receipt, "category_id": str(uuid4())}],  # receipt names another category
        [{**receipt, "data_category": "public"}],  # receipt understates the data class
        [receipt, receipt],  # one source, two receipts
    )
    for receipts in forged:
        # Bypass the domain resolver: the INSERT trigger is the last guard.
        monkeypatch.setattr(
            personal_sources, "canonical", lambda *_args, value=receipts: ([dict(ref)], value)
        )
        with pytest.raises(DBAPIError) as error:
            with tenant_session(
                setup.engine,
                setup.tenant,
                actor_id=setup.human,
                requester_id=setup.human,
                category_id=None,
            ) as session:
                create_run(
                    session,
                    personal(setup),
                    goal="伪造个人来源",
                    writer_id=setup.agent,
                    intent_key=str(uuid4()),
                    read_sources=[ref],
                )
        assert error.value.orig.sqlstate == "23514", error.value
    monkeypatch.undo()
    # Receipts are immutable once bound; a category Run cannot gain them later.
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            run = create_run(
                session,
                setup.ctx,
                goal="品类运行",
                writer_id=setup.agent,
                intent_key=str(uuid4()),
                read_sources=[ref],
                data_categories=("internal",),
            )
            run.versions = {**run.versions, "personal_sources": [receipt]}
            session.flush()


class PinnedClient(SyntheticClient):
    def __init__(self, ids):
        super().__init__()
        self.ids = [str(identity) for identity in ids]

    def turn(self, route, **kwargs):
        names = {row["name"] for row in kwargs["tools"]}
        values = [json.loads(row["content"]) for row in kwargs["messages"] if row["role"] == "tool"]
        if "assistant.passage.read" not in names and not values:
            self.calls += 1
            return ModelTurn(
                calls=(
                    ToolCall(
                        id="pinned-personal",
                        name="assistant.materials.read",
                        arguments={"artifact_ids": self.ids},
                    ),
                ),
                usage=ProviderUsage(10, 2),
            )
        return super().turn(route, **kwargs)


def personal_kernel(setup, client, sources):
    from pdos_next.agent.enterprise_search.assistant_graph import AssistantExtractGraph
    from pdos_next.agent.kernel.bootstrap import Bootstrap, RuntimePorts
    from pdos_next.agent.kernel.host import BoundHost
    from tests.agent.kernel.test_gateway import configured_route

    owner = Bootstrap(
        setup.engine, ports=RuntimePorts(provider_client=client, preload=lambda _: ())
    )
    owner.route_for = lambda _scope: replace(configured_route(), context_window_tokens=200_000)
    owner.provider_for = lambda *_args: "synthetic-assistant-no-egress"
    ctx = personal(setup)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human, category_id=None
    ) as session:
        binding = owner.binding_for(
            session,
            ctx,
            StartInput(
                goal="按我选的资料回答",
                idempotency_key=str(uuid4()),
                sources=[
                    {"artifact_id": str(identity), "expected_revision": 1} for identity in sources
                ],
            ),
        )
        run = create_run(
            session,
            ctx,
            goal="以前漏气怎么处理？",
            writer_id=setup.agent,
            intent_key=str(uuid4()),
            token_limit=2_000_000,
            data_categories=binding.data_categories,
            private_context=binding.private_context,
            read_sources=binding.read_sources,
        )
        identity = run.id
    scope = owner.store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=None,
        run_id=identity,
    )
    host = BoundHost(owner.store, replace(owner.adapters(), cost_required=False))
    owner._assistant_adapter.graph = AssistantExtractGraph(host, owner._assistant_adapter)
    return owner, scope, host


def test_personal_answer_cites_pinned_sources_and_revocation_hides_them(setup):
    from pdos_next.agent.kernel.conversation_acl import classify, manifests

    first = register(setup, "本品类合成资料", BODY)
    second_category = other_category(setup, members=[setup.human, setup.agent])
    second = register(in_category(setup, second_category), "他品类合成资料", BODY)
    owner, scope, host = personal_kernel(setup, PinnedClient([second, first]), [first, second])
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    cited = output["result"]["assistant"]["citation_ids"]
    assert cited, output
    with owner.store.transaction(scope) as (session, run):
        call = session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.run_id == run.id, AgentToolCall.tool == "assistant.materials.read"
            )
        )
        assert {item["source_id"] for item in call.result["items"]} == {str(first), str(second)}
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human, category_id=None
    ) as session:
        run = session.get(AgentRun, scope.run_id)
        access = manifests(session, [run], consumer=run)
        assert classify(session, access, consumer=run)[str(run.id)] == "current"
    # Losing the source category's membership hides the Run and its M1 recall origin.
    revoke(setup, second_category, setup.human)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human, category_id=None
    ) as session:
        assert session.get(AgentRun, scope.run_id) is None
    hidden = setup.client.get(f"/v1/personal/agent-runs/{scope.run_id}", headers=setup.headers)
    assert hidden.status_code == 200 and hidden.json()["status"] == "hidden"
    # A follow-up rebinds through the same path and refuses the revoked source.
    follow_up = setup.client.post(
        "/v1/personal/agent-runs",
        headers=setup.headers,
        json={
            "goal": "继续",
            "idempotency_key": str(uuid4()),
            "continue_from_run_id": str(scope.run_id),
        },
    )
    assert follow_up.status_code == 403, follow_up.text
    again = start(setup, [second])
    assert again.status_code == 403, again.text


def test_personal_follow_up_carries_and_rebinds_the_bound_sources(setup):
    first = register(setup, "本品类合成资料", BODY)
    second_category = other_category(setup, members=[setup.human, setup.agent])
    second = register(in_category(setup, second_category), "他品类合成资料", BODY)
    response = start(setup, [first, second])
    assert response.status_code == 202, response.text
    parent = UUID(response.json()["run_id"])
    with Session(setup.admin) as session, session.begin():
        session.get(AgentRun, parent).state = "completed"  # only the terminal state matters here
    third = register(setup, "追问新增资料", BODY)
    follow_up = setup.client.post(
        "/v1/personal/agent-runs",
        headers=setup.headers,
        json={
            "goal": "再按这些资料确认一次",
            "idempotency_key": str(uuid4()),
            "continue_from_run_id": str(parent),
            "sources": [{"artifact_id": str(third), "expected_revision": 1}],
        },
    )
    assert follow_up.status_code == 202, follow_up.text
    run = stored(setup, follow_up.json()["run_id"])
    assert run.continued_from_id == parent and run.category_id is None
    assert {ref["artifact_id"] for ref in run.read_sources} == {str(first), str(second), str(third)}
    assert {row["category_id"] for row in run.versions["personal_sources"]} == {
        str(setup.category),
        str(second_category),
    }


def test_personal_run_with_sources_still_cannot_write_business_objects(setup):
    source = register(setup, "合成资料", BODY)
    owner, scope, _host = personal_kernel(setup, PinnedClient([source]), [source])
    with pytest.raises(DomainError) as error:
        owner.commands.execute(scope, "category.knowledge.add", {}, "personal-write", source=None)
    assert error.value.reason in {"FORBIDDEN_SCOPE", "NAMED_DECISION_REQUIRED"}


def test_personal_source_list_spans_member_categories_only(setup):
    mine = register(setup, "本品类合成资料", BODY)
    member = other_category(setup, members=[setup.human, setup.agent])
    theirs = register(in_category(setup, member), "他品类合成资料", BODY)
    closed = other_category(setup, members=[setup.peer, setup.agent])
    hidden = setup.client.post(
        f"/v1/categories/{closed}/commands",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        json={
            "command_id": str(uuid4()),
            "idempotency_key": str(uuid4()),
            "category_id": str(closed),
            "product_id": None,
            "expected_revision": 1,
            "source_read_set": [],
            "operation": "evidence.artifact.register",
            "payload": {
                "title": "无权品类资料",
                "content": BODY,
                "source_label": "P91 合成",
                "visibility": "category",
            },
        },
    )
    assert hidden.status_code == 200, hidden.text
    reading = setup.client.get("/v1/personal/agent-input-sources", headers=setup.headers)
    assert reading.status_code == 200, reading.text
    items = {row["artifact_id"]: row for row in reading.json()["items"]}
    assert {str(mine), str(theirs)} <= set(items)
    assert hidden.json()["subject_id"] not in items
    assert items[str(theirs)]["category"]["id"] == str(member)
    assert items[str(mine)]["availability"] == {"available": True, "code": None}
