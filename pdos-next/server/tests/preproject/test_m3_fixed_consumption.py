"""New consumers recheck real baseline traversal; historical reads remain usable."""

from types import SimpleNamespace as NS
from uuid import UUID

import pytest

from pdos_next import request_proof
from pdos_next.domain.builds import service as builds
from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.preproject import baseline, root_sources
from pdos_next.domain.projects import service as projects
from pdos_next.errors import DomainError

TENANT, CATEGORY, PRODUCT, ACTOR, DEFINITION, PROJECT, ENGINEERING, PROCESS, CLAIM, KNOWLEDGE = (
    UUID(int=i) for i in range(1, 11)
)


class Session:
    """No DB: only the immutable knowledge read and actual actor lookup are supplied."""

    def __init__(self, knowledge):
        self.info = {}
        self.knowledge = knowledge
        self.knowledge_reads = 0

    def get(self, model, identity):
        assert identity == ACTOR
        return NS(kind="human")

    def scalar(self, query):
        assert "category_knowledge_entries" in str(query)
        self.knowledge_reads += 1
        return self.knowledge


@pytest.fixture
def environment(monkeypatch):
    claim_ref = {"type": "claim", "id": str(CLAIM), "version": 1}
    knowledge_ref = {"type": "knowledge", "id": str(KNOWLEDGE), "version": 1}
    knowledge = NS(
        id=KNOWLEDGE,
        tenant_id=TENANT,
        category_id=CATEGORY,
        version=1,
        action="add",
        kind="voice",
        content={"representative_refs": [claim_ref]},
        source_refs=[],
    )
    session = Session(knowledge)
    definition = {
        "id": str(DEFINITION),
        "revision": 1,
        "product_id": str(PRODUCT),
        "category_id": str(CATEGORY),
        "sealed": True,
        "g0_decision_id": str(UUID(int=11)),
        "sources": [],
        "specs": [{"source_refs": [claim_ref]}],
    }
    context = NS(
        tenant_id=TENANT, category_id=CATEGORY, actor_id=ACTOR, requester_id=ACTOR, run_id=None
    )
    product = NS(id=PRODUCT, tenant_id=TENANT, revision=1)
    command = NS(product_id=PRODUCT, expected_revision=1, source_read_set=[])
    payload = NS(
        project_id=PROJECT,
        engineering_configuration_id=ENGINEERING,
        manufacturing_configuration_id=PROCESS,
        visibility="private",
        build_id=UUID(int=12),
    )
    project, link = NS(id=PROJECT), NS(definition_id=DEFINITION)
    proof = NS(read_rows={})
    engineering = {
        "id": str(ENGINEERING),
        "definition_id": str(DEFINITION),
        "required_source_read_set": [],
    }
    manufacturing = {
        "engineering_configuration_id": str(ENGINEERING),
        "required_source_read_set": [],
    }
    state = NS(withdrawn=True, locked=[], definition_reads=[])

    def lock_claims(s, ctx, refs, *, approved):
        assert s is session and ctx is context and approved
        identities = [ref.id for ref in refs if ref.type == "claim"]
        state.locked.append(identities)
        if identities and state.withdrawn:
            baseline.fail("SOURCE_STALE", "claim_withdrawn", "Synthetic withdrawn claim")
        return {identity: NS(revision=1, quote="Fixed quote", line=1) for identity in identities}

    def load_definition(s, ctx, product_id, identity):
        assert product_id == PRODUCT and identity == DEFINITION
        state.definition_reads.append(identity)
        return NS(revision=1), definition

    def load_project(*args, **kwargs):
        return project, link, definition

    monkeypatch.setattr(root_sources, "lock_claim_refs", lock_claims)
    monkeypatch.setattr(projects, "_project", load_project)
    monkeypatch.setattr(projects, "calculate", lambda payload: {})
    monkeypatch.setattr(configurations, "_human", lambda *args, **kwargs: None)
    monkeypatch.setattr(configurations, "_definition", load_definition)
    monkeypatch.setattr(builds, "_project", load_project)
    monkeypatch.setattr(builds, "_build", lambda *args, **kwargs: payload)
    monkeypatch.setattr(builds, "get_engineering", lambda *args: (None, engineering))
    monkeypatch.setattr(builds, "get_process", lambda *args: (None, manufacturing))
    monkeypatch.setattr(request_proof, "request_proof", lambda s: proof)
    return NS(
        session=session,
        ctx=context,
        product=product,
        command=command,
        payload=payload,
        definition=definition,
        knowledge=knowledge,
        knowledge_ref=knowledge_ref,
        state=state,
        proof=proof,
    )


def consume(e, entry, monkeypatch):
    args = (e.session, e.ctx, e.command, e.product, e.payload)
    if entry == "project":
        return projects.validate(*args)
    if entry == "build":
        return builds.validate(*args)
    inputs = {
        "definition": e.definition if entry == "engineering" else None,
        "engineering": (
            {
                "definition_id": str(DEFINITION),
                "definition_revision": 1,
                # This read DTO is deliberately a summary, not a source proof.
                "definition": {"id": str(DEFINITION), "revision": 1},
            }
            if entry == "manufacturing"
            else None
        ),
        "reads": [],
        "references": [],
    }
    monkeypatch.setattr(configurations, "_inputs", lambda *args: inputs)
    return configurations._checked_inputs(*args)


@pytest.mark.parametrize("source_product", [None, PRODUCT, UUID(int=30)])
def test_historical_original_uses_actual_source_scope_and_checks_both_products(
    monkeypatch, source_product,
):
    from pdos_next import originals, service
    from pdos_next.domain.preproject.schemas import Reference

    original, source = UUID(int=31), UUID(int=32)
    row = NS(
        id=source, tenant_id=TENANT, category_id=CATEGORY,
        product_id=source_product, original_id=original,
    )
    context = NS(tenant_id=TENANT, category_id=CATEGORY)
    queries, access, originals_read = [], [], []

    def scalar(query):
        queries.append(str(query))
        return row

    def require_access(session, ctx, scope):
        assert ctx is context
        access.append(scope)

    def require_original(session, ctx, scope, identity):
        assert ctx is context and identity == original
        originals_read.append(scope)

    monkeypatch.setattr(service, "require_access", require_access)
    monkeypatch.setattr(originals, "require_original", require_original)
    baseline._historical_source_access(
        NS(scalar=scalar), context, PRODUCT,
        Reference(type="artifact", id=source, version=1, line=1, quote="Fixed"),
    )
    assert access == ([source_product] if source_product is not None else []) + [PRODUCT]
    assert originals_read == [source_product]
    assert len(queries) == 1 and "artifact_versions.content" not in queries[0]


@pytest.mark.parametrize("entry", ["project", "engineering", "manufacturing", "build"])
@pytest.mark.parametrize("source", ["claim", "nested_knowledge_claim", "withdrawn_knowledge"])
def test_new_consumption_checks_spec_sources_even_with_empty_legacy_sources(
    environment, monkeypatch, entry, source
):
    e = environment
    if source != "claim":
        e.definition["specs"][0]["source_refs"] = [e.knowledge_ref]
    if source == "withdrawn_knowledge":
        e.knowledge.action = "withdraw"
    with pytest.raises(DomainError) as caught:
        consume(e, entry, monkeypatch)
    assert caught.value.code == (
        "SOURCE_UNAVAILABLE" if source == "withdrawn_knowledge" else "SOURCE_STALE"
    )
    if source == "nested_knowledge_claim":
        assert e.session.knowledge_reads == 1
        assert e.state.locked == [[CLAIM]]
    if entry == "manufacturing":
        assert e.state.definition_reads == [DEFINITION]


@pytest.mark.parametrize("entry", ["project", "engineering", "manufacturing", "build"])
def test_g0_empty_sources_remain_valid_for_new_consumption(environment, monkeypatch, entry):
    e = environment
    e.definition["specs"][0]["source_refs"] = []
    consume(e, entry, monkeypatch)
    assert e.state.locked == [[]]


def test_build_read_cache_cannot_authorize_new_consumption(environment):
    e = environment
    historical = builds._linked(e.session, e.ctx, PRODUCT, e.payload)
    assert e.state.locked == [] and e.proof.read_rows
    with pytest.raises(DomainError) as caught:
        builds._linked(e.session, e.ctx, PRODUCT, e.payload, write=True, new_consumption=True)
    assert caught.value.code == "SOURCE_STALE"
    assert builds._linked(e.session, e.ctx, PRODUCT, e.payload) is historical


def test_build_previously_valid_cache_is_rechecked_after_withdrawal(environment):
    e = environment
    e.state.withdrawn = False
    builds._linked(e.session, e.ctx, PRODUCT, e.payload, write=True, new_consumption=True)
    e.state.withdrawn = True
    with pytest.raises(DomainError) as caught:
        builds._linked(e.session, e.ctx, PRODUCT, e.payload, write=True, new_consumption=True)
    assert caught.value.code == "SOURCE_STALE"
    assert e.state.locked == [[CLAIM], [CLAIM]]


def test_manufacturing_checks_actual_definition_version(environment, monkeypatch):
    e = environment
    e.definition["specs"] = []
    monkeypatch.setattr(configurations, "_definition", lambda *args: (NS(revision=2), e.definition))
    with pytest.raises(DomainError) as caught:
        consume(e, "manufacturing", monkeypatch)
    assert caught.value.code == "VERSION_CONFLICT"
    assert e.state.locked == []


def test_three_consumers_request_category_before_product_fence():
    assert projects.category_lifecycle_fence is True
    assert configurations.category_lifecycle_fence is True
    assert builds.category_lifecycle_fence is True
