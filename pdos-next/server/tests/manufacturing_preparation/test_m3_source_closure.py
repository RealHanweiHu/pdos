"""No-I/O manufacturing seam exercising the real recursive source validator."""

from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import Connection, Engine

from pdos_next.agent_kernel.models import PublicWebSnapshot
from pdos_next.contracts import Command
from pdos_next.domain.manufacturing_baseline import service as manufacturing
from pdos_next.domain.preproject import baseline
from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry
from pdos_next.errors import DomainError
from pdos_next.models import Claim
from pdos_next.service import Context


class ReachedProcess(Exception):
    """The source gate passed; no downstream authority is manufactured."""


@pytest.fixture
def closure(monkeypatch):
    def no_io(*_args, **_kwargs):
        pytest.fail("This regression must not connect to a database or provider")

    monkeypatch.setattr(Engine, "connect", no_io)
    monkeypatch.setattr(Engine, "raw_connection", no_io)
    monkeypatch.setattr(Connection, "execute", no_io)
    monkeypatch.setattr(httpx.Client, "request", no_io)
    tenant, category, actor, product, project_id = (uuid4() for _ in range(5))
    ctx = Context(tenant, actor, actor, category_id=category)
    claim = NS(
        id=uuid4(), tenant_id=tenant, category_id=category, status="active", revision=1,
        privacy="shared", proposal_id=None, product_id=None, source_kind="snapshot",
        snapshot_id=uuid4(), source_revision=1, line=1, quote="Exact source observation",
    )
    snapshot = NS(
        id=claim.snapshot_id, tenant_id=tenant, category_id=category,
        status="ok", markdown=claim.quote,
    )
    knowledge = NS(
        id=uuid4(), tenant_id=tenant, category_id=category, lineage_id=uuid4(),
        version=1, action="add", source_refs=[], kind="boundary", content={},
    )
    current = NS(category_id=category, status="active", current_version=1)

    class Session:
        info = {}

        def __init__(self):
            self.locked = []
            self.claim_reads = 0
            self.knowledge = knowledge

        def scalar(self, statement):
            model = statement.column_descriptions[0]["entity"]
            if model is Claim:
                self.claim_reads += 1
                return claim
            if model is KnowledgeEntry:
                return self.knowledge
            if model is PublicWebSnapshot:
                return snapshot
            raise AssertionError(f"Unexpected source query: {model}")

        def get(self, model, _identity):
            if model is KnowledgeEntry:
                return self.knowledge
            if model is KnowledgeCurrent:
                return current
            raise AssertionError(f"Unexpected source lookup: {model}")

        def execute(self, statement, parameters):
            assert "m3_lock_claim_references" in str(statement)
            self.locked.append(parameters["ids"])
            return []

    session = Session()
    definition = {
        "id": str(uuid4()), "revision": 1, "product_id": str(product),
        "sources": [], "specs": [], "source_status": "current", "visibility": "category",
        "sealed": True, "g0_decision_id": str(uuid4()),
    }
    ref = {"artifact_id": str(uuid4()), "expected_revision": 1, "line": 1, "quote": "Work source"}
    payload = manufacturing.PAYLOADS["npi.work_instruction.record"].model_validate({
        "project_id": project_id, "process": {"id": uuid4(), "revision": 1},
        "title": "Synthetic new work instruction", "visibility": "category",
        "reason": "New consumption checks typed fixed sources", "sources": [ref],
        "operation_key": "assemble",
        "steps": [{"key": "one", "text": "Synthetic step", "sources": [ref]}],
    })
    command = Command(
        command_id=uuid4(), idempotency_key=str(uuid4()), category_id=category,
        product_id=product, operation="npi.work_instruction.record", expected_revision=1,
        payload=payload.model_dump(mode="json"),
    )
    project = NS(id=project_id, visibility="category", purpose="Synthetic preparation")
    link = NS(definition_id=definition["id"], definition_revision=1)
    monkeypatch.setattr(manufacturing, "_uow", lambda *_: None)
    monkeypatch.setattr(manufacturing, "_persistent_product", lambda *_: None)
    monkeypatch.setattr(manufacturing, "_runtime", lambda *_: "no-io-owner")
    monkeypatch.setattr(manufacturing.configurations, "_human", lambda *_: None)
    monkeypatch.setattr(manufacturing.projects, "_project", lambda *_: (project, link, definition))

    def stop_after_sources(*_):
        raise ReachedProcess

    monkeypatch.setattr(manufacturing.configurations, "get_process", stop_after_sources)
    return NS(
        session=session, ctx=ctx, command=command, payload=payload, definition=definition,
        claim=claim, knowledge=knowledge, current=current, snapshot=snapshot,
    )


def point_at(f, kind, row):
    f.definition["specs"] = [{
        "source_refs": [{"type": kind, "id": str(row.id), "version": 1}], "sources": [],
    }]


def consume(f):
    return manufacturing._load_fixed(
        f.session, f.ctx, f.command, object(), f.payload, require_reads=False,
    )


def test_explicit_empty_source_definition_reaches_existing_process_gate(closure):
    before = deepcopy(closure.definition)
    assert baseline.validate_sources(closure.session, closure.ctx, closure.definition) == ()
    assert manufacturing._definition_reads(closure.definition) == []
    with pytest.raises(ReachedProcess):
        consume(closure)
    assert closure.definition == before and closure.session.locked == []


def test_active_claim_with_no_artifact_edges_is_locked_and_revalidated(closure):
    point_at(closure, "claim", closure.claim)
    with pytest.raises(ReachedProcess):
        consume(closure)
    assert closure.session.locked == [[closure.claim.id]]
    assert closure.session.claim_reads == 1


@pytest.mark.parametrize("status", ["withdrawn", "reverted"])
def test_withdrawn_claim_cannot_be_new_manufacturing_basis_even_with_empty_artifacts(
    closure, status
):
    point_at(closure, "claim", closure.claim)
    closure.claim.status, closure.claim.revision = status, 2
    with pytest.raises(DomainError) as denied:
        consume(closure)
    assert denied.value.code == "SOURCE_STALE"
    assert denied.value.detail["reason"] == "claim_withdrawn"
    assert closure.session.locked == [[closure.claim.id]]


@pytest.mark.parametrize("invalid", ["unreadable", "version", "withdraw_entry"])
def test_unusable_fixed_knowledge_cannot_be_new_manufacturing_basis(closure, invalid):
    point_at(closure, "knowledge", closure.knowledge)
    if invalid == "unreadable":
        closure.session.knowledge = None
    elif invalid == "version":
        closure.knowledge.version = 2
    else:
        closure.knowledge.action = "withdraw"
    with pytest.raises(DomainError) as denied:
        consume(closure)
    assert denied.value.code == "SOURCE_UNAVAILABLE"
    assert denied.value.detail["reason"] == "knowledge_unreadable"


def test_fixed_knowledge_recurses_into_its_withdrawn_claim(closure):
    point_at(closure, "knowledge", closure.knowledge)
    closure.knowledge.source_refs = [{"type": "claim", "id": str(closure.claim.id), "version": 1}]
    closure.claim.status, closure.claim.revision = "withdrawn", 2
    with pytest.raises(DomainError) as denied:
        consume(closure)
    assert denied.value.detail["reason"] == "claim_withdrawn"
    assert closure.session.locked == [[closure.claim.id]]


def test_at53_fixed_knowledge_survives_later_lineage_withdrawal(closure):
    point_at(closure, "knowledge", closure.knowledge)
    closure.current.status, closure.current.current_version = "withdrawn", 2
    with pytest.raises(ReachedProcess):
        consume(closure)
    assert closure.knowledge.action == "add" and closure.knowledge.version == 1


@pytest.mark.parametrize("container", ["metrics", "features", "prices", "representative_refs"])
def test_schema_declared_nested_knowledge_claim_cannot_escape_new_consumption(closure, container):
    point_at(closure, "knowledge", closure.knowledge)
    ref = {"type": "claim", "id": str(closure.claim.id), "version": 1}
    if container == "representative_refs":
        closure.knowledge.kind = "voice"
        closure.knowledge.content = {container: [ref]}
    else:
        closure.knowledge.kind = "competitor"
        closure.knowledge.content = {"metrics": [], "features": [], "prices": []}
        closure.knowledge.content[container] = [{"source_ref": ref}]
    closure.claim.status, closure.claim.revision = "withdrawn", 2
    assert closure.knowledge.source_refs == []
    with pytest.raises(DomainError) as denied:
        consume(closure)
    assert denied.value.detail["reason"] == "claim_withdrawn"
    assert closure.session.locked == [[closure.claim.id]]
