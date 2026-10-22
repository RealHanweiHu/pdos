"""No-connect adapter boundaries; real RLS and ordinary bindings are root PG work."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel import m3_spec_compare as module
from pdos_next.agent_kernel.models import AgentRun, AgentSession
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry
from pdos_next.domain.preproject.models import Proposal
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Claim, Product, UploadedOriginal


@pytest.fixture
def port(monkeypatch):
    scope = RunScope(*(uuid4() for _ in range(6)), proposal_id=uuid4())
    values = asdict(scope)
    values["id"] = values.pop("run_id")
    run = NS(**values, state="running", reverted_at=None, read_sources=[])
    owner = NS(
        id=scope.session_id,
        tenant_id=scope.tenant_id,
        owner_id=scope.requester_id,
        category_id=scope.category_id,
        product_id=None,
        proposal_id=scope.proposal_id,
    )
    heads, objects, events = {}, {(AgentRun, run.id): run, (AgentSession, owner.id): owner}, []
    result = {
        "engine_version": "actual-test-reader",
        "input_digest": "current",
        "groups": [],
        "subjects": [],
        "unmapped": [],
        "unavailable": [],
        "unknown_count": 0,
    }

    class Session:
        info = {"read_snapshot": True}

        def get(self, model, identity):
            events.append(("body", model, identity))
            return objects.get((model, identity))

        def scalars(self, query):
            assert "proposal_sources" in str(query)
            return []

        def execute(self, query):
            assert "definition_revisions" in str(query)
            return []

    session = Session()

    @contextmanager
    def transaction(engine, tenant, **kwargs):
        events.append(("transaction", tenant, kwargs))
        yield session

    def head(s, ctx, model, identity, *fields):
        events.append(("head", model, identity))
        row = heads.get((model, identity))
        if row is None:
            module._unavailable()
        return row

    def compare(s, ctx, payload, *, before_definition_read):
        events.append(("compare", payload.model_dump(mode="json")))
        if state.selected_definition is not None:
            before_definition_read(state.selected_definition)
        return deepcopy(result)

    def document(s, ctx, identity):
        events.append(("document", identity))
        return deepcopy(state.document)

    monkeypatch.setattr(module, "tenant_session", transaction)
    monkeypatch.setattr(module, "_head", head)
    monkeypatch.setattr(module, "require_access", lambda *a: events.append(("access", a[-1])))
    monkeypatch.setattr(
        module, "_public_sources", lambda s, ctx, refs: events.append(("source_check", list(refs)))
    )
    monkeypatch.setattr(
        module, "_public_definition", lambda s, ctx, row: events.append(("definition_check", row))
    )
    monkeypatch.setattr(module, "_public_proposal", lambda *a: events.append(("proposal_check",)))
    monkeypatch.setattr(
        module,
        "parameter_version",
        lambda s, ctx, identity, version: events.append(("parameter", identity, version)),
    )
    monkeypatch.setattr(module.views, "read", document)
    monkeypatch.setattr(module.spec_compare, "compare", compare)
    ctx = NS(
        tenant_id=scope.tenant_id, category_id=scope.category_id, requester_id=scope.requester_id
    )
    store = NS(engine="no-connect", authority=lambda *a: events.append(("authority",)))
    adapter = module.SpecCompareReads(store, NS(context=lambda _: ctx))
    state = NS(
        scope=scope,
        run=run,
        owner=owner,
        session=session,
        ctx=ctx,
        adapter=adapter,
        heads=heads,
        objects=objects,
        events=events,
        result=result,
        document={"items": [], "source_refs": [], "context_refs": []},
        selected_definition=None,
    )
    heads[Proposal, scope.proposal_id] = {
        "effective_visibility": "category",
        "private_source_count": 0,
        "customer_identities": [],
        "baseline_product_id": None,
        "baseline_definition_id": None,
        "baseline_definition_revision": None,
    }
    objects[Proposal, scope.proposal_id] = NS(id=scope.proposal_id)
    return state


def arguments(port, subjects=None):
    return {"subjects": subjects or [{"type": "proposal", "id": str(port.scope.proposal_id)}]}


def call(port, **kwargs):
    return port.adapter.handlers()["calc.spec_compare"](port.scope, arguments(port, **kwargs))


def test_actual_run_session_authority_and_readonly_scope_before_compare(port):
    assert call(port) == port.result
    transaction = port.events[0]
    assert transaction[1] == port.scope.tenant_id
    assert transaction[2] == {
        "actor_id": port.scope.writer_id,
        "requester_id": port.scope.requester_id,
        "category_id": port.scope.category_id,
        "read_snapshot": True,
    }
    kinds = [event[0] for event in port.events]
    assert kinds.index("authority") < kinds.index("head") < kinds.index("document")
    assert kinds.index("proposal_check") < kinds.index("compare")
    assert kinds.count("authority") == 2


@pytest.mark.parametrize("field", ["session_id", "requester_id", "writer_id", "category_id"])
def test_actual_run_identity_cannot_be_replaced_by_scope(port, field):
    port.scope = replace(port.scope, **{field: uuid4()})
    with pytest.raises(DomainError) as caught:
        call(port)
    assert caught.value.code == "FORBIDDEN_SCOPE"
    assert not any(event[0] in {"head", "document", "compare"} for event in port.events)


def test_actual_session_owner_cannot_be_replaced(port):
    port.owner.owner_id = uuid4()
    with pytest.raises(DomainError):
        call(port)
    assert not any(event[0] == "head" for event in port.events)


@pytest.mark.parametrize(
    "field,value",
    [
        ("effective_visibility", "private"),
        ("private_source_count", 1),
        ("customer_identities", ["Private customer"]),
    ],
)
def test_private_proposal_head_denied_before_document_or_compute(port, field, value):
    port.heads[Proposal, port.scope.proposal_id][field] = value
    with pytest.raises(DomainError) as caught:
        call(port)
    assert caught.value.code == "SOURCE_UNAVAILABLE"
    assert not any(event[0] in {"document", "compare"} for event in port.events)
    assert ("body", Proposal, port.scope.proposal_id) not in port.events


def test_private_run_context_denied_even_if_compared_objects_are_public(port):
    port.run.private_context = True
    port.scope = replace(port.scope, private_context=True)
    with pytest.raises(DomainError) as caught:
        call(port)
    assert caught.value.code == "SOURCE_UNAVAILABLE"
    assert not any(event[0] == "head" for event in port.events)


def test_cancel_epoch_and_model_supplied_values_never_reach_reader(port):
    port.run.cancel_epoch = 1
    with pytest.raises(DomainError) as caught:
        call(port)
    assert caught.value.code == "CANCELLED_RUN"
    with pytest.raises(ValidationError):
        port.adapter.call(port.scope, {**arguments(port), "values": [999]})
    assert not any(event[0] == "compare" for event in port.events)


def test_private_product_head_denied_before_product_body(port):
    identity = uuid4()
    port.heads[Product, identity] = {"visibility": "private"}
    with pytest.raises(DomainError) as caught:
        call(port, subjects=[{"type": "product", "id": str(identity)}])
    assert caught.value.code == "SOURCE_UNAVAILABLE"
    assert ("body", Product, identity) not in port.events
    assert not any(event[0] == "compare" for event in port.events)


def test_product_bound_run_does_not_accept_other_product_selector(port):
    identity = uuid4()
    port.run.product_id = port.owner.product_id = uuid4()
    port.scope = replace(port.scope, product_id=port.run.product_id)
    with pytest.raises(DomainError) as caught:
        call(port, subjects=[{"type": "product", "id": str(identity)}])
    assert caught.value.code == "FORBIDDEN_SCOPE"
    assert not any(event[0] == "head" for event in port.events)


def test_private_actual_run_artifact_is_denied_before_source_reader(port):
    identity = uuid4()
    port.run.read_sources = [{"artifact_id": str(identity), "expected_revision": 1}]
    port.heads[Artifact, identity] = {
        "visibility": "private",
        "revision": 1,
        "status": "active",
        "product_id": None,
        "original_id": None,
    }
    with pytest.raises(DomainError):
        call(port)
    assert not any(event[0] in {"source_check", "document", "compare"} for event in port.events)
    assert ("body", Artifact, identity) not in port.events


def test_shared_artifact_cannot_escape_private_original_parent(port):
    identity, original = uuid4(), uuid4()
    port.run.read_sources = [{"artifact_id": str(identity), "expected_revision": 1}]
    port.heads[Artifact, identity] = {
        "visibility": "category",
        "revision": 1,
        "status": "active",
        "product_id": None,
        "original_id": original,
    }
    port.heads[UploadedOriginal, original] = {"visibility": "private", "product_id": None}
    with pytest.raises(DomainError):
        call(port)
    assert not any(event[0] in {"source_check", "compare"} for event in port.events)


def test_nested_competitor_metric_source_is_checked_before_comparison(port):
    identity, lineage, source = uuid4(), uuid4(), uuid4()
    port.heads[KnowledgeEntry, identity] = {
        "kind": "competitor",
        "version": 2,
        "lineage_id": lineage,
        "action": "supersede",
    }
    port.objects[KnowledgeCurrent, (port.scope.tenant_id, lineage)] = NS(
        category_id=port.scope.category_id,
        status="active",
        current_entry_id=identity,
        current_version=2,
    )
    port.objects[KnowledgeEntry, identity] = NS(
        source_refs=[],
        content={
            "metrics": [
                {
                    "source_ref": {"type": "claim", "id": str(source), "version": 1},
                }
            ]
        },
    )
    port.heads[Claim, source] = {
        "privacy": "private",
        "visibility": "category",
        "status": "active",
        "revision": 1,
    }
    with pytest.raises(DomainError) as caught:
        call(port, subjects=[{"type": "competitor", "id": str(identity)}])
    assert caught.value.code == "SOURCE_UNAVAILABLE"
    assert ("body", Claim, source) not in port.events
    assert not any(event[0] == "compare" for event in port.events)


def test_historical_parameter_is_checked_as_actual_version(port):
    identity = uuid4()
    port.document["items"] = [{"content": {"parameter_id": str(identity), "parameter_version": 1}}]
    call(port)
    assert ("parameter", identity, 1) in port.events


@pytest.mark.parametrize("current_status", ["active", "withdrawn", None])
def test_fixed_knowledge_survives_current_change_but_competitor_requires_current(
    port, current_status
):
    from pdos_next.domain.preproject.schemas import Reference

    identity, lineage = uuid4(), uuid4()
    port.heads[KnowledgeEntry, identity] = {
        "kind": "competitor",
        "version": 1,
        "lineage_id": lineage,
        "action": "create",
    }
    port.objects[KnowledgeEntry, identity] = NS(source_refs=[], content={})
    if current_status is not None:
        port.objects[KnowledgeCurrent, (port.scope.tenant_id, lineage)] = NS(
            category_id=port.scope.category_id,
            status=current_status,
            current_entry_id=uuid4(),
            current_version=2,
        )
    public = module._PublicObjects(port.session, port.ctx)
    public.refs([Reference(type="knowledge", id=identity, version=1)])
    assert ("body", KnowledgeEntry, identity) in port.events
    assert not any(event[:2] == ("body", KnowledgeCurrent) for event in port.events)
    port.events.clear()
    with pytest.raises(DomainError) as caught:
        public.knowledge(identity, competitor=True)
    assert caught.value.code == "SOURCE_UNAVAILABLE"
    assert ("body", KnowledgeEntry, identity) not in port.events
    for version, action in [(2, "create"), (1, "withdraw")]:
        port.heads[KnowledgeEntry, identity]["action"] = action
        with pytest.raises(DomainError):
            public.knowledge(identity, version)
    assert ("body", KnowledgeEntry, identity) not in port.events


@pytest.mark.parametrize("private_parent", [None, "product", "original"])
def test_fixed_knowledge_product_artifact_metadata_precedes_source_body(port, private_parent):
    from pdos_next.domain.preproject.schemas import Reference

    identity, lineage, artifact, product, original = (uuid4() for _ in range(5))
    port.heads[KnowledgeEntry, identity] = {
        "kind": "competitor",
        "version": 1,
        "lineage_id": lineage,
        "action": "create",
    }
    port.objects[KnowledgeEntry, identity] = NS(
        source_refs=[],
        content={
            "prices": [
                {
                    "source_ref": {
                        "type": "artifact",
                        "id": str(artifact),
                        "version": 2,
                    }
                }
            ]
        },
    )
    port.heads[Artifact, artifact] = {
        "visibility": "category",
        "status": "active",
        "revision": 2,
        "product_id": product,
        "original_id": original,
    }
    port.heads[Product, product] = {
        "visibility": "private" if private_parent == "product" else "category",
    }
    port.heads[UploadedOriginal, original] = {
        "visibility": "private" if private_parent == "original" else "category",
        "product_id": product,
    }
    public = module._PublicObjects(port.session, port.ctx)
    refs = [Reference(type="knowledge", id=identity, version=1)]
    if private_parent:
        with pytest.raises(DomainError) as caught:
            public.refs(refs)
        assert caught.value.code == "SOURCE_UNAVAILABLE"
        assert not any(event[0] == "source_check" for event in port.events)
    else:
        public.refs(refs)
        kinds = [event[0] for event in port.events]
        original_head = port.events.index(("head", UploadedOriginal, original))
        assert original_head < kinds.index("source_check")
        assert ("access", product) in port.events
    for model, value in ((Artifact, artifact), (UploadedOriginal, original), (Product, product)):
        assert ("body", model, value) not in port.events


def test_returned_source_is_rechecked_before_result_crosses_port(port):
    identity = uuid4()
    port.result["source_refs"] = [{"type": "artifact", "id": str(identity), "version": 1}]
    port.heads[Artifact, identity] = {"visibility": "private", "status": "active", "revision": 1}
    with pytest.raises(DomainError):
        call(port)
    assert any(event[0] == "compare" for event in port.events)
    assert ("body", Artifact, identity) not in port.events


def test_restore_rereads_actual_sources_and_rejects_changed_result(port):
    before = call(port)
    assert port.adapter.restore(port.scope, arguments(port), before) == before
    port.result["input_digest"] = "changed"
    with pytest.raises(DomainError) as caught:
        port.adapter.restore(port.scope, arguments(port), before)
    assert caught.value.code == "SOURCE_STALE"
    port.heads[Proposal, port.scope.proposal_id]["effective_visibility"] = "private"
    with pytest.raises(DomainError) as caught:
        port.adapter.restore(port.scope, arguments(port), before)
    assert caught.value.code == "SOURCE_UNAVAILABLE"


def test_metadata_sql_does_not_read_private_proposal_body():
    ctx = NS(tenant_id=uuid4(), category_id=uuid4())
    identity, queries = uuid4(), []
    row = {
        "id": identity,
        "tenant_id": ctx.tenant_id,
        "category_id": ctx.category_id,
        "effective_visibility": "private",
    }
    session = NS(
        execute=lambda query: (
            queries.append(str(query)) or NS(mappings=lambda: NS(first=lambda: row))
        )
    )
    assert module._head(session, ctx, Proposal, identity, "effective_visibility") == row
    sql = queries[0]
    assert "proposals.tenant_id =" in sql and "proposals.category_id =" in sql
    assert "brief" not in sql and "title" not in sql and "source_refs" not in sql


def test_actual_selected_definition_guard_does_not_scan_unrelated_history(port):
    from pdos_next.domain.products.models import DefinitionRevision

    product_id, selected, private_history = uuid4(), uuid4(), uuid4()
    port.heads[Product, product_id] = {"visibility": "category"}
    port.heads[DefinitionRevision, selected] = {
        "visibility": "category",
        "product_id": product_id,
        "revision": 3,
    }
    port.heads[DefinitionRevision, private_history] = {
        "visibility": "private",
        "product_id": product_id,
        "revision": 1,
    }
    port.selected_definition = NS(id=selected, revision=3)
    assert call(port, subjects=[{"type": "product", "id": str(product_id)}]) == port.result
    assert ("head", DefinitionRevision, selected) in port.events
    assert ("head", DefinitionRevision, private_history) not in port.events
    port.heads[DefinitionRevision, selected]["visibility"] = "private"
    with pytest.raises(DomainError) as caught:
        call(port, subjects=[{"type": "product", "id": str(product_id)}])
    assert caught.value.code == "SOURCE_UNAVAILABLE"
