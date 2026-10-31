"""Native command/read-ledger regressions for I14/I22; offline provider and scanner.

Root alone runs these against its checked TEST_DATABASE_URL. Business evidence
is created through native registration/upload/parse/proposal/promotion commands;
no Artifact, Run result, model/read binding or knowledge proof is forged in SQL.
"""
# ruff: noqa: F811 -- explicitly imported native fixture dependency tree

import json
from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from pdos_next.agent_kernel.api import StartInput
from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.persistence import create_run
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.domain.knowledge import assistant_sources
from pdos_next.domain.knowledge.assistant_models import KnowledgeAnswerReview
from pdos_next.domain.knowledge.models import KnowledgeCandidateVersion
from pdos_next.domain.preproject.category_models import KnowledgeEntry, PromotionProof
from pdos_next.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.enterprise_search.assistant_ledger import carried
from pdos_next.models import Artifact, Receipt
from pdos_next.providers.types import ProviderUsage
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from tests.agent_kernel.test_gateway import configured_route
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_retrieval_pg import index
from tests.knowledge_pg.test_assistant_knowledge import from_seed, root, seed, submit
from tests.knowledge_pg.test_assistant_knowledge_lifecycle import saved_candidate
from tests.preproject.test_g0 import create, payload, post
from tests.preproject.test_g0 import work as work  # noqa: F401
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work  # noqa: F401
from tests.test_trusted_source_work import command as product_command


class UncitedClient:
    """Read both real sources, retain one citation, and attempt to reuse both in prose."""

    def __init__(self, cited_id, *, query="漏气", unread_mention=None, material_id=None):
        self.cited_id, self.query = str(cited_id), query
        self.unread_mention = unread_mention
        self.material_id = str(material_id) if material_id else None
        self.calls, self.child_calls = 0, 0
        self.sources = {}

    def close(self):
        pass

    def turn(self, _route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        self.calls += 1
        messages = kwargs["messages"]
        names = {tool["name"] for tool in kwargs["tools"]}
        values = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
        if names == {"assistant.passage.read", "result.read"}:
            self.child_calls += 1
            cid = json.loads(messages[0]["content"])["context"]["citation_id"]
            if not values:
                return self.call(
                    "assistant.passage.read",
                    {
                        "citation_id": cid,
                        "cursor": 0,
                        "page_chars": 2000,
                    },
                )
            quote = values[-1]["text"].splitlines()[0]
            body = {"rows": [{"citation_id": cid, "statement": quote, "quote": quote}]}
            return self.output(body, "已核对真实原文。")
        if not values:
            if self.material_id:
                return self.call("assistant.materials.read", {"artifact_ids": [self.material_id]})
            return self.call("assistant.search", {"query": self.query})
        if "items" in values[-1]:
            self.sources = {item["source_id"]: item["citation_id"] for item in values[-1]["items"]}
            assert self.cited_id in self.sources, values[-1]
            return self.call("assistant.extract", {"citation_ids": list(self.sources.values())})
        rows = values[-1]["rows"]
        assert rows
        return self.output(
            {
                "assistant": {"citation_ids": [self.sources[self.cited_id]]},
                "non_read_source_uuid": self.unread_mention,
            },
            "本次参考：" + "；".join(row["statement"] for row in rows),
        )

    @staticmethod
    def call(name, arguments):
        return ModelTurn(
            calls=(ToolCall(id=str(uuid4()), name=name, arguments=arguments),),
            usage=ProviderUsage(10, 2),
        )

    @staticmethod
    def output(body, summary):
        return ModelTurn(
            structured={
                "status": "completed",
                "summary": summary,
                "result": body,
                "questions": [],
                "unfinished": [],
            },
            usage=ProviderUsage(10, 2),
        )


def scoped(setup, *, admin=False, person=None):
    person = person or setup.human
    return tenant_session(
        setup.admin if admin else setup.engine,
        setup.tenant,
        actor_id=person,
        requester_id=person,
        category_id=setup.category,
        read_snapshot=not admin,
    )


def register(setup, title, content, visibility="category"):
    """Use the actual target product; a category-only source cannot pretend it belongs there."""
    response = post(
        setup,
        product_command(
            setup,
            "evidence.artifact.register",
            {
                "title": title,
                "content": content,
                "source_label": "I14/I22 synthetic native evidence",
                "visibility": visibility,
            },
        ),
    )
    assert response.status_code == 200, response.text
    return UUID(response.json()["subject_id"])


def native_counts(setup):
    with Session(setup.admin) as session:
        return tuple(
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.tenant_id == setup.tenant,
                )
            )
            for model in (Artifact, KnowledgeEntry, KnowledgeCandidateVersion, Receipt)
        )


def checked_answer(setup, client, public_id, *, parent=None):
    owner, scope, host, _adapter = fixture(
        setup,
        client,
        product_id=setup.product,
        read_sources=({"artifact_id": str(public_id), "expected_revision": 1},),
        session_id=parent.session_id if parent else None,
        continued_from_id=parent.run_id if parent else None,
    )
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    assert output["result"]["assistant"]["lookup"] == "cited", output
    assert len(output["result"]["assistant"]["citation_ids"]) == 1
    assert scope.private_context is False
    return owner, scope, output


def actual_proof(setup, scope):
    with scoped(setup) as session:
        issued, _history = carried(session, scope)
        capture = assistant_sources.capture(session, setup.ctx, scope.run_id)
        assert len(issued) >= 2
        return capture["source_proof"]


def assert_known_only_actual_reads(setup, scope, proof, unread_id):
    with scoped(setup, admin=True) as session:
        check = text("SELECT public.knowledge_answer_sources_known(:r,CAST(:p AS jsonb))")
        assert session.scalar(check, {"r": scope.run_id, "p": json.dumps(proof)}) is True
        unread = session.get(Artifact, unread_id)
        forged = [
            {
                "source_type": "artifact",
                "source_id": str(unread.id),
                "source_revision": unread.revision,
                "content_hash": unread.content_hash,
                "category_id": str(unread.category_id),
            }
        ]
        assert session.scalar(check, {"r": scope.run_id, "p": json.dumps(forged)}) is False


@pytest.mark.parametrize("kind", ["private", "customer_original"])
def test_uncited_real_read_cannot_launder_prose_into_shared_category_or_candidate(
    security_work,
    kind,
):
    work, setup = security_work, security_work.setup
    public = register(setup, "I14-A 公开漏气记录", "漏气处理：更换密封圈。")
    if kind == "private":
        restricted = register(
            setup, "I14-B 私有漏气记录", "漏气：更换密封圈。SYNTHETIC_PRIVATE", "private"
        )
    else:
        original = uploaded(work, content="漏气：更换密封圈。合成客户甲专用。".encode())
        restricted = parsed(work, original)
    for identity in (public, restricted):
        index(setup, identity)
    client = UncitedClient(public)
    _owner, scope, output = checked_answer(setup, client, public)
    assert str(restricted) in client.sources
    assert client.sources[str(restricted)] not in output["result"]["assistant"]["citation_ids"]
    proof = actual_proof(setup, scope)
    assert {ref["source_id"] for ref in proof} == {str(public), str(restricted)}
    before = native_counts(setup)
    denied = setup.client.post(
        root(setup) + "/answer-draft",
        headers=setup.headers,
        json={"run_id": str(scope.run_id), "kind": "category"},
    )
    assert denied.status_code == 403, denied.text
    value = from_seed(seed(setup, scope.run_id, "rule"))
    assert value["payload"]["visibility"] == "private"
    forged = deepcopy(value)
    forged["payload"]["visibility"] = "category"
    denied = setup.client.post(
        f"/v1/categories/{setup.category}/products/{setup.product}/experience/inputs",
        headers=setup.headers,
        json=forged,
    )
    assert denied.status_code == 403, denied.text
    assert native_counts(setup) == before
    candidate = saved_candidate(setup, scope.run_id)
    with scoped(setup) as session:
        entry = session.get(KnowledgeCandidateVersion, candidate)
        review = session.scalar(
            select(KnowledgeAnswerReview).where(
                KnowledgeAnswerReview.subject_id == candidate,
            )
        )
        assert entry.visibility == "private"
        assert review.source_proof == entry.source_basis["answer_sources"] == proof
    with scoped(setup, person=setup.peer) as session:
        assert session.get(KnowledgeCandidateVersion, candidate) is None
        assert session.get(AgentRun, scope.run_id) is None
    unread = register(setup, "Unrelated unread source", "No matching query")
    assert_known_only_actual_reads(setup, scope, proof, unread)


def test_uncited_shared_read_survives_native_save_and_does_not_acquire_an_unread_source(setup):
    public = register(setup, "I14-A 公开漏气记录", "漏气处理：更换密封圈。")
    uncited = register(setup, "I14-B 另一公开漏气记录", "漏气核查：更换密封圈。")
    unread = register(setup, "Unrelated unread source", "No matching query")
    for identity in (public, uncited, unread):
        index(setup, identity)
    client = UncitedClient(public, unread_mention=str(unread))
    _owner, scope, _output = checked_answer(setup, client, public)
    saved = submit(setup, from_seed(seed(setup, scope.run_id)))
    assert saved.status_code == 200, saved.text
    with scoped(setup) as session:
        review = session.scalar(
            select(KnowledgeAnswerReview).where(
                KnowledgeAnswerReview.subject_id == UUID(saved.json()["result"]["entry_id"]),
            )
        )
        proof = review.source_proof
        assert {ref["source_id"] for ref in proof} == {str(public), str(uncited)}
    assert_known_only_actual_reads(setup, scope, proof, unread)
    with scoped(setup, admin=True) as session:
        model_json = session.scalars(
            select(AgentToolCall.result).where(
                AgentToolCall.run_id == scope.run_id,
                AgentToolCall.tool == "model",
            )
        ).all()
        assert str(unread) in json.dumps(model_json)  # A real model JSON mention is not READ.
    _owner, separate, _output = checked_answer(
        setup,
        UncitedClient(unread, query=str(unread)),
        unread,
    )
    assert separate.session_id != scope.session_id
    with scoped(setup) as session:
        separate_proof = assistant_sources.capture(session, setup.ctx, separate.run_id)[
            "source_proof"
        ]
    assert {ref["source_id"] for ref in separate_proof} == {str(unread)}
    assert_known_only_actual_reads(setup, scope, proof, unread)
    with scoped(setup, admin=True) as session:
        check = text("SELECT public.knowledge_answer_sources_known(:r,CAST(:p AS jsonb))")
        assert (
            session.scalar(check, {"r": separate.run_id, "p": json.dumps(separate_proof)}) is True
        )


def test_uncited_private_parent_footprint_remains_when_only_public_source_is_requeried(setup):
    public = register(setup, "I14-A 公开漏气记录", "漏气处理：更换密封圈。")
    restricted = register(
        setup, "I14-B 私有漏气记录", "漏气：更换密封圈。SYNTHETIC_PRIVATE", "private"
    )
    for identity in (public, restricted):
        index(setup, identity)
    _owner, parent, _output = checked_answer(setup, UncitedClient(public), public)
    client = UncitedClient(public, query=str(public))
    _owner, scope, _output = checked_answer(setup, client, public, parent=parent)
    assert (
        str(restricted) not in client.sources
    )  # Only carried native history can supply this root.
    proof = actual_proof(setup, scope)
    assert {ref["source_id"] for ref in proof} == {str(public), str(restricted)}
    denied = setup.client.post(
        root(setup) + "/answer-draft",
        headers=setup.headers,
        json={"run_id": str(scope.run_id), "kind": "category"},
    )
    assert denied.status_code == 403, denied.text
    saved_candidate(setup, scope.run_id)  # Also exercises the inherited SQL known branch.


def proposal_answer(setup, client, proposal_id, source_id):
    owner = Bootstrap(
        setup.engine, ports=RuntimePorts(provider_client=client, preload=lambda _: ())
    )
    owner.route_for = lambda _scope: replace(configured_route(), context_window_tokens=200_000)
    owner.provider_for = lambda *_args: "synthetic-assistant-no-egress"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        data = StartInput(
            goal="复核本提案资料",
            idempotency_key=str(uuid4()),
            proposal_id=UUID(proposal_id),
            sources=[{"artifact_id": str(source_id), "expected_revision": 1}],
        )
        binding = owner.binding_for(session, setup.ctx, data)
        run = create_run(
            session,
            setup.ctx,
            goal=data.goal,
            writer_id=setup.agent,
            intent_key=data.idempotency_key,
            token_limit=2_000_000,
            proposal_id=data.proposal_id,
            data_categories=binding.data_categories,
            private_context=binding.private_context,
            customer_identities=binding.customer_identities,
            read_sources=binding.read_sources,
            outbound_context=binding.outbound_context,
        )
        identity = run.id
    scope = owner.store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=identity,
    )
    host = BoundHost(owner.store, replace(owner.adapters(), cost_required=False))
    owner._assistant_adapter.graph = AssistantExtractGraph(host, owner._assistant_adapter)
    output = AgentKernel(host, owner.registry).execute(
        scope,
        goal=data.goal,
        execution_key={"synthetic": str(identity)},
    )["output"]
    assert output["status"] == "completed", output
    return scope


def test_human_original_deidentification_publishes_clean_answer_with_private_native_proof(
    security_work,
    work,
):
    setup = security_work.setup
    original = uploaded(security_work, content="漏气：更换密封圈。合成客户甲专用。".encode())
    source = parsed(security_work, original)
    index(setup, source)
    body = payload(work)
    body.update(
        entry_kind="customer_request",
        customer_identities=["合成客户甲"],
        source_refs=[{
            "type": "original", "id": str(source), "version": 1,
            "line": 1, "quote": "漏气：更换密封圈。合成客户甲专用。",
        }],
    )
    proposal_id, _command = create(work, body)
    scope = proposal_answer(
        setup,
        UncitedClient(source, material_id=source),
        proposal_id,
        source,
    )
    draft = seed(setup, scope.run_id)
    assert draft["operation"] == "category.knowledge.promote"
    assert draft["payload"]["deidentified_confirmed"] is False
    value = from_seed(draft)
    value["payload"]["content"]["answer"] = "便携方案应按实际工况复核；适用边界待本人确认。"
    value["payload"]["content"]["question"] = "便携方案需要复核哪些条件？"
    value["payload"]["deidentified_confirmed"] = True  # Explicit actual Human choice.
    preview = post(work, value, preview=True)
    assert preview.status_code == 200, preview.text
    before = native_counts(setup)
    confirmed = preview.json()["command"]
    saved = post(work, confirmed)
    assert saved.status_code == 200, saved.text
    assert post(work, confirmed).json()["id"] == saved.json()["id"]
    assert native_counts(setup)[0] == before[0]  # No generated Artifact for the answer.
    entry_id = UUID(saved.json()["result"]["entry_id"])
    with scoped(setup) as session:
        entry = session.get(KnowledgeEntry, entry_id)
        review = session.scalar(
            select(KnowledgeAnswerReview).where(
                KnowledgeAnswerReview.subject_id == entry_id,
            )
        )
        proof = session.scalar(
            select(PromotionProof).where(PromotionProof.knowledge_entry_id == entry_id)
        )
        assert (
            proof.source_proposal_id == UUID(proposal_id) and proof.receipt_id == entry.receipt_id
        )
        assert review.source_proof == [] and entry.answer_sources == [] and entry.source_refs == []
        assert review.origin_run_id == scope.run_id and review.verified_by == setup.human
        proof_id = proof.id
    with scoped(setup, person=setup.peer) as session:
        assert session.get(PromotionProof, proof_id) is None
        assert session.get(AgentRun, scope.run_id) is None
        entry = session.get(KnowledgeEntry, entry_id)
        assert entry is not None
        assert all(
            secret not in json.dumps(entry.content, ensure_ascii=False)
            for secret in ("合成客户甲", str(source), str(original), proposal_id)
        )
