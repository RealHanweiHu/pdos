"""M3 object ports against actual model-shaped rows, with no database connection."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import m3_object_reads as module
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.models import AgentRun, PublicWebSnapshot
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.preproject import root_sources
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.domain.preproject.models import ProposalSubmission
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Product, UploadedOriginal

PROPOSAL, PRODUCT, ITEM, RECEIPT, SOURCE = (UUID(int=i) for i in range(20, 25))
AT = datetime(2026, 10, 11, tzinfo=UTC)


class Rows(list):
    def all(self):
        return list(self)

    def first(self):
        return self[0] if self else None


def question(**changes):
    return {
        "question": "Which market needs review?",
        "owner_id": str(UUID(int=2)),
        "due_date": "2026-10-20",
        "status": "open",
        "answer": None,
        "related_item_ids": [str(UUID(int=30))],
        **changes,
    }


def item_view(**changes):
    return {
        "item_id": str(ITEM),
        "version": 2,
        "kind": "question",
        "content": question(),
        "source_refs": [],
        "origin": "human",
        "writer_id": str(UUID(int=2)),
        "run_id": None,
        "confirmed_by": None,
        "human_value": True,
        "removed": False,
        **changes,
    }


def category_record(identity=6):
    return (
        NS(
            id=UUID(int=identity),
            key=f"category-{identity}",
            name="Pump research",
            purpose="Public scope",
            status="active",
            revision=7,
            owner_id=UUID(int=2),
        ),
        NS(can_write=True, product_manager=True),
        NS(name="Actual category owner"),
        3,
    )


@pytest.fixture
def port(monkeypatch):
    scope = RunScope(*(UUID(int=i) for i in range(1, 7)), proposal_id=PROPOSAL)
    fields = asdict(scope)
    fields["id"] = fields.pop("run_id")
    run = NS(**fields, state="running", reverted_at=None)
    row = NS(
        id=PROPOSAL,
        tenant_id=scope.tenant_id,
        category_id=scope.category_id,
        owner_id=scope.requester_id,
        title="Public proposal",
        brief="Public draft",
        entry_kind="new_product",
        target_kind="new_product",
        status="draft",
        revision=4,
        visibility="category",
        effective_visibility="category",
        private_source_count=0,
        customer_identities=[],
        baseline_product_id=None,
        baseline_definition_id=None,
        baseline_definition_revision=None,
        source_refs=[],
        context_refs=[],
        current_submission_id=None,
    )
    doc = {"source_refs": [], "context_refs": [], "items": [item_view()]}
    version = NS(
        version=2,
        kind="question",
        content=question(),
        source_refs=[],
        origin="ai_draft",
        writer_id=scope.writer_id,
        run_id=scope.run_id,
        confirmed_by=scope.requester_id,
        receipt_id=RECEIPT,
        prepared_candidate_id=UUID(int=40),
        removed=False,
        created_at=AT,
    )
    calls, authority = [], []

    class Session:
        info = {"read_snapshot": True}

        def __init__(self):
            self.objects = {(AgentRun, run.id): run}
            self.categories = [category_record()]
            self.roots, self.sql, self.decision = [], [], None
            self.item_rows = [(NS(id=ITEM, current_version=2), version)]
            self.knowledge_counts = [("boundary", 2), ("competitor", 5)]

        def get(self, model, identity):
            return self.objects.get((model, identity))

        def execute(self, query, params=None):
            sql = str(query.compile(dialect=postgresql.dialect()))
            assert "FOR UPDATE" not in sql and "FOR SHARE" not in sql
            assert not any(verb in sql for verb in ("INSERT ", "UPDATE ", "DELETE "))
            self.sql.append((sql, query))
            if "FROM categories" in sql:
                return Rows(self.categories)
            if "FROM category_knowledge_current" in sql:
                return Rows(self.knowledge_counts)
            if "FROM proposal_items" in sql:
                return Rows(self.item_rows)
            raise AssertionError(sql)

        def scalar(self, query, params=None):
            sql = str(query)
            self.sql.append((sql, query))
            if "parameter_current" in sql:
                return 9
            if "proposal_decisions" in sql:
                return self.decision
            if "m3_definition_root_private" in sql:
                return False
            raise AssertionError(sql)

        def scalars(self, query):
            sql = str(query)
            self.sql.append((sql, query))
            assert "FROM proposal_sources" in sql
            return Rows(self.roots)

    session = Session()

    @contextmanager
    def readonly(engine, tenant, **kwargs):
        calls.append((engine, tenant, kwargs))
        assert kwargs["read_snapshot"] is True
        yield session

    monkeypatch.setattr(module, "tenant_session", readonly)
    monkeypatch.setattr(module, "require_access", lambda *a, **kw: None)
    monkeypatch.setattr(module, "proposal", lambda *a, **kw: row)
    monkeypatch.setattr(module.views, "document", lambda *a: deepcopy(doc))
    monkeypatch.setattr(
        module.views,
        "context_changes",
        lambda *a: [
            {"type": "parameter", "id": str(UUID(int=80)), "version": 1, "current_version": 2}
        ],
    )
    monkeypatch.setattr(root_sources, "project_items", lambda s, row, values: values)
    store = NS(engine="actual-store-engine", authority=lambda *a: authority.append(a))
    reads = module.M3ObjectReads(
        store, DomainCommands(None, catalog=None, registry=None, route=None)
    )
    return NS(
        scope=scope,
        run=run,
        row=row,
        doc=doc,
        version=version,
        session=session,
        calls=calls,
        authority=authority,
        reads=reads,
    )


def call(port, name="proposal.read", **args):
    return port.reads.call(port.scope, {"proposal_id": str(PROPOSAL), **args}, name=name)


def test_four_ports_export_selectors_without_authority_fields(port):
    assert (
        set(port.reads.handlers())
        == set(module.SCHEMAS)
        == {
            "category.list",
            "category.read",
            "proposal.read",
            "proposal.items.read",
        }
    )
    for name, schema in module.SCHEMAS.items():
        args = {"proposal_id": str(PROPOSAL)} if name.startswith("proposal") else {}
        for authority in ("tenant_id", "category_id", "requester_id", "private_context"):
            with pytest.raises(ValidationError):
                schema.model_validate({**args, authority: str(UUID(int=99))})


@pytest.mark.parametrize(
    "name,args",
    [
        ("category.list", {"status": "PRIVATE_INVALID_STATUS"}),
        ("category.read", {"category_id": "PRIVATE_SCOPE_INJECTION"}),
        ("proposal.read", {"proposal_id": "PRIVATE_NOT_UUID"}),
        (
            "proposal.items.read",
            {"proposal_id": str(PROPOSAL), "include_history": "PRIVATE_BOOLEAN"},
        ),
    ],
)
def test_invalid_model_read_arguments_are_safe_tool_errors_before_database(port, name, args):
    with pytest.raises(DomainError) as caught:
        port.reads.call(port.scope, args, name=name)
    assert caught.value.code == "VALIDATION_FAILED"
    assert caught.value.detail["fields"]
    assert "PRIVATE_" not in str(caught.value.payload())
    assert not port.calls


def test_personal_category_list_keeps_real_actor_requester_and_sql_intersection(port):
    port.scope = replace(port.scope, category_id=None, proposal_id=None)
    port.run.category_id = port.run.proposal_id = None
    result = port.reads.call(port.scope, {}, name="category.list")
    assert result["items"][0]["permissions"] == {
        "read": True,
        "write": True,
        "product_manager": True,
    }
    assert result["items"][0]["owner"] == {"id": str(UUID(int=2)), "name": "Actual category owner"}
    assert result["items"][0]["model_count"] == 3 and result["next_cursor"] is None
    _, tenant, options = port.calls[0]
    assert tenant == port.scope.tenant_id and options == {
        "actor_id": port.scope.writer_id,
        "requester_id": port.scope.requester_id,
        "category_id": None,
        "read_snapshot": True,
    }
    sql, query = port.session.sql[0]
    assert "category_access(categories.tenant_id, categories.id," in sql
    assert "grants.principal_id" in sql and "grants.expires_at" in sql
    assert query.compile().params["principal_id_1"] == port.scope.requester_id
    assert len(port.authority) == 1


def test_category_list_keyset_page_filters_and_literal_wildcards(port):
    port.session.categories = [category_record(i) for i in range(100, 201)]
    result = port.reads.call(
        port.scope,
        {
            "name_query": "pump_%",
            "status": "archived",
            "cursor": str(UUID(int=99)),
        },
        name="category.list",
    )
    assert len(result["items"]) == 100 and result["next_cursor"] == str(UUID(int=199))
    sql, query = port.session.sql[0]
    params = query.compile().params
    assert "categories.id >" in sql and "ORDER BY categories.id" in sql
    assert 101 in params.values() and "archived" in params.values()
    assert "pump/_/%" in params.values()
    assert port.scope.category_id in params.values()


def test_category_read_counts_current_authorized_objects_without_knowledge_bodies(port):
    result = port.reads.call(port.scope, {}, name="category.read")
    assert result["parameter_count"] == 9 and result["model_count"] == 3
    assert result["knowledge_counts"] == {
        "boundary": 2,
        "segment": 0,
        "competitor": 5,
        "voice": 0,
        "regulation": 0,
        "research_question": 0,
    }
    assert "items" not in result
    sql = "\n".join(value[0] for value in port.session.sql)
    assert "category_knowledge_current.status" in sql
    assert "parameter_current.category_id" in sql


def test_missing_category_or_revoked_authority_fails_before_object_read(port):
    port.scope = replace(port.scope, category_id=None)
    with pytest.raises(DomainError) as error:
        call(port)
    assert error.value.detail["reason"] == "category_run_required" and not port.calls


def test_run_binding_and_cancellation_are_rechecked(port):
    port.run.private_context = True
    with pytest.raises(DomainError) as error:
        call(port)
    assert error.value.code == "FORBIDDEN_SCOPE" and not port.session.sql
    port.run.private_context = False
    port.run.cancel_epoch = 1
    with pytest.raises(DomainError) as error:
        call(port)
    assert error.value.code == "CANCELLED_RUN"


def test_revoked_server_authority_prevents_any_read(port):
    def denied(*args):
        raise DomainError("FORBIDDEN_SCOPE", "Principal revoked", 403)

    port.reads.store.authority = denied
    with pytest.raises(DomainError):
        call(port)
    assert not port.session.sql


@pytest.mark.parametrize("bound", [None, UUID(int=99)])
def test_proposal_selector_cannot_replace_actual_run_binding(port, bound):
    port.scope = replace(port.scope, proposal_id=bound)
    port.run.proposal_id = bound
    with pytest.raises(DomainError) as error:
        call(port)
    assert error.value.detail["reason"] == "proposal_run_mismatch"


def test_proposal_summary_counts_questions_and_actual_submission_decision(port):
    submission_id, decision_id = UUID(int=60), UUID(int=61)
    port.row.current_submission_id = submission_id
    port.session.objects[(ProposalSubmission, submission_id)] = NS(
        id=submission_id,
        revision=3,
        reviewer_id=UUID(int=62),
        option_count=2,
        created_at=AT,
        frozen_document={"private_old_text": "Do not emit"},
    )
    port.session.decision = NS(
        id=decision_id,
        submission_id=submission_id,
        outcome="returned",
        decided_by=UUID(int=62),
        created_at=AT,
        rationale="Private prior rationale must not be leaked by a summary",
    )
    result = call(port)
    assert result["item_counts"] == {"question": 1} and result["question_counts"] == {"open": 1}
    assert result["questions"][0]["content"] == question()
    assert result["submission"]["revision"] == 3 and result["decision"]["outcome"] == "returned"
    assert result["context_hint"] is True and result["context_changes"][0]["current_version"] == 2
    assert "frozen_document" not in str(result) and "prior rationale" not in str(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("effective_visibility", "private"),
        ("effective_visibility", "audience"),
        ("private_source_count", 1),
        ("customer_identities", ["Actual customer"]),
    ],
)
def test_private_proposal_head_is_rejected_before_body_read(port, monkeypatch, field, value):
    setattr(port.row, field, value)
    monkeypatch.setattr(module.views, "document", lambda *a: pytest.fail("private body loaded"))
    with pytest.raises(DomainError) as error:
        call(port)
    assert error.value.detail["reason"] == "private_material_context_binding_required"


def test_items_preserve_provenance_and_real_existing_question_fields(port):
    result = call(port, "proposal.items.read")
    value = result["items"][0]
    assert value["origin"] == "ai_draft" and value["writer_id"] == str(port.scope.writer_id)
    assert value["run_id"] == str(port.scope.run_id) and value["receipt_id"] == str(RECEIPT)
    assert value["confirmed_by"] == str(port.scope.requester_id) and value["human_value"] is True
    assert value["content"] == question() and result["questions"] == result["items"]
    assert value["current_version"] == 2 and value["created_at"] == AT.isoformat()
    sql = next(sql for sql, _ in port.session.sql if "FROM proposal_items" in sql)
    assert "proposal_items.removed IS false" in sql and "proposal_items.current_version" in sql


def test_item_filters_and_history_have_no_business_row_limit(port):
    result = call(
        port,
        "proposal.items.read",
        kinds=["question"],
        item_ids=[str(ITEM)],
        question_status="open",
        include_history=True,
    )
    assert result["items"]
    sql, query = next(pair for pair in port.session.sql if "FROM proposal_items" in pair[0])
    assert "proposal_items.removed IS false" not in sql
    assert "proposal_item_versions.kind IN" in sql and "proposal_items.id IN" in sql
    assert "status" in query.compile().params.values() and "open" in query.compile().params.values()
    assert query._limit_clause is None


def install_artifact(port, monkeypatch, *, private=False):
    from pdos_next import service

    artifact = NS(
        id=SOURCE,
        tenant_id=port.scope.tenant_id,
        category_id=port.scope.category_id,
        product_id=PRODUCT,
        original_id=None,
        revision=1,
        visibility="private" if private else "category",
    )
    product = NS(
        id=PRODUCT,
        tenant_id=port.scope.tenant_id,
        category_id=port.scope.category_id,
        visibility="category",
    )
    port.session.objects[(Artifact, SOURCE)] = artifact
    port.session.objects[(Product, PRODUCT)] = product
    source_calls = []

    def checked(session, ctx, product_id, identity, revision):
        source_calls.append((product_id, identity, revision))
        assert (
            product_id == artifact.product_id
            and identity == SOURCE
            and revision == artifact.revision
        )
        return artifact

    monkeypatch.setattr(service, "source_for", checked)
    return artifact, source_calls


def source_ref():
    return {
        "type": "artifact",
        "id": str(SOURCE),
        "version": 1,
        "line": 1,
        "quote": "Exact reference",
    }


@pytest.mark.parametrize("placement", ["document", "difference", "root", "history", "knowledge"])
def test_real_private_source_is_denied_despite_public_current_head(port, monkeypatch, placement):
    install_artifact(port, monkeypatch, private=True)
    if placement == "document":
        port.doc["source_refs"] = [source_ref()]
    elif placement == "difference":
        port.doc["items"].append(item_view(kind="difference", content={"sources": [source_ref()]}))
    elif placement == "root":
        port.session.roots = [
            NS(privacy="shared", source_type="original", source_id=SOURCE, source_version=1)
        ]
    elif placement == "history":
        port.version.source_refs = [source_ref()]
        port.version.version = 1
    else:
        identity = UUID(int=70)
        port.session.objects[(KnowledgeEntry, identity)] = NS(
            tenant_id=port.scope.tenant_id,
            category_id=port.scope.category_id,
            version=1,
            source_refs=[source_ref()],
        )
        port.doc["context_refs"] = [{"type": "knowledge", "id": str(identity), "version": 1}]
    with pytest.raises(DomainError) as error:
        call(port, "proposal.items.read", include_history=True)
    assert error.value.detail["reason"] == "private_material_context_binding_required"


def test_public_product_bound_source_uses_actual_product_not_model_payload(port, monkeypatch):
    _, calls = install_artifact(port, monkeypatch)
    port.doc["source_refs"] = [source_ref()]
    assert call(port)["title"] == "Public proposal"
    assert calls == [(PRODUCT, SOURCE, 1)]


def test_public_artifact_with_private_original_root_is_denied(port, monkeypatch):
    artifact, _ = install_artifact(port, monkeypatch)
    artifact.original_id = UUID(int=71)
    port.session.objects[(UploadedOriginal, artifact.original_id)] = NS(
        tenant_id=port.scope.tenant_id,
        category_id=port.scope.category_id,
        visibility="private",
        product_id=PRODUCT,
    )
    port.doc["source_refs"] = [source_ref()]
    with pytest.raises(DomainError) as error:
        call(port)
    assert error.value.detail["reason"] == "private_material_context_binding_required"


def test_public_snapshot_requires_actual_scope_and_visibility(port):
    port.doc["source_refs"] = [{"type": "snapshot", "id": str(SOURCE), "version": 1}]
    snapshot = NS(category_id=port.scope.category_id, visibility="category", status="ok")
    port.session.objects[(PublicWebSnapshot, SOURCE)] = snapshot
    assert call(port)["title"] == "Public proposal"
    snapshot.visibility = "private"
    with pytest.raises(DomainError) as error:
        call(port)
    assert error.value.detail["reason"] == "private_material_context_binding_required"


def test_more_than_a_page_of_items_is_not_silently_truncated(port):
    port.session.item_rows *= 205
    assert len(call(port, "proposal.items.read")["items"]) == 205
