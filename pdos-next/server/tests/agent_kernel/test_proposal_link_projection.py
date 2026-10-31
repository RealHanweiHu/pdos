"""Server Link metadata is separate from the owner-projected body references."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_next import service
from pdos_next.agent_kernel import proposal_context
from pdos_next.agent_kernel.m3_object_reads import _references
from pdos_next.agent_kernel.proposal_context import _projected_references, collect
from pdos_next.domain.preproject.evidence_schemas import EvidenceLinkCreate
from pdos_next.domain.preproject.root_sources import _canonical_citation
from pdos_next.errors import DomainError


def projection(locator):
    identity, item_id = uuid4(), uuid4()
    request = EvidenceLinkCreate.model_validate(
        {
            "evidence": {"type": "artifact", "id": identity, "version": 1, "locator": locator},
            "target": {"type": "proposal_item", "id": item_id, "version": 1},
            "relation": "supports",
        }
    )
    body = "First real line\nSecond actual line"
    canonical = _canonical_citation(body, request.evidence.locator)
    reference = {"type": "artifact", "id": str(identity), "version": 1}
    return (
        identity,
        body,
        {
            "items": [
                {
                    "item_id": str(item_id),
                    "version": 1,
                    "direct_source_refs": [],
                    "source_refs": [{**reference, **canonical}],
                    "evidence_links": [
                        {
                            "id": str(uuid4()),
                            "status": "active",
                            "evidence": request.evidence.model_dump(mode="json"),
                            "target": request.target.model_dump(mode="json"),
                            "relation": request.relation,
                        }
                    ],
                }
            ]
        },
    )


@pytest.mark.parametrize("locator", [None, "line:2", "lines:1:2", "chars:6:15"])
def test_native_link_schema_and_canonical_projection_produce_one_consumable_body_ref(locator):
    identity, body, value = projection(locator)
    before = deepcopy(value)
    generic = list(_references(value))
    assert len(generic) == 2 and generic[1].line is generic[1].quote is None
    actual = list(_projected_references(value))
    assert len(actual) == 1 and actual[0].id == identity
    assert actual[0].quote in body.splitlines()[actual[0].line - 1]
    assert value == before  # Read projection; no item/history/attribution rewrite.


def source_session(monkeypatch, identity, body):
    tenant, category, human = uuid4(), uuid4(), uuid4()
    ctx = SimpleNamespace(tenant_id=tenant, category_id=category, requester_id=human)
    head = SimpleNamespace(
        id=identity,
        tenant_id=tenant,
        category_id=category,
        product_id=None,
        revision=1,
        visibility="category",
        original_id=None,
        status="active",
        content=body,
    )
    root = SimpleNamespace(
        source_type="original", source_id=identity, source_version=1, privacy="shared"
    )
    row = SimpleNamespace(
        id=uuid4(),
        effective_visibility="private",
        private_source_count=0,
        customer_identities=[],
        baseline_definition_id=None,
    )
    # DB access alone is a double. The source closure and exact quote validator
    # are the real production functions; no source validator is stubbed away.
    session = SimpleNamespace(
        info={"read_snapshot": True},
        scalars=lambda _: [root],
        scalar=lambda _: head,
        get=lambda _model, _identity: head,
    )
    monkeypatch.setattr(service, "source_for", lambda *_args, **_kwargs: head)
    monkeypatch.setattr(proposal_context, "source_for", lambda *_args, **_kwargs: head)
    return session, ctx, row


def test_collect_validates_canonical_link_and_keeps_the_actual_fixed_source(monkeypatch):
    identity, body, value = projection("line:2")
    facts = collect(*source_session(monkeypatch, identity, body), value)
    assert facts.private_context
    assert facts.read_sources == [
        {"artifact_id": str(identity), "expected_revision": 1, "product_id": None}
    ]
    assert len(facts.references) == 1
    assert facts.references[0]["line"] == 2
    assert facts.references[0]["quote"] == "Second actual line"


@pytest.mark.parametrize("problem", ["no_quote", "wrong_quote", "no_canonical_ref"])
def test_link_description_does_not_replace_missing_or_invalid_source_proof(monkeypatch, problem):
    identity, body, value = projection("line:2")
    refs = value["items"][0]["source_refs"]
    if problem == "no_canonical_ref":
        refs.clear()
    else:
        refs[0]["quote"] = None if problem == "no_quote" else "Invented quotation"
    with pytest.raises(DomainError) as failed:
        collect(*source_session(monkeypatch, identity, body), value)
    assert failed.value.detail["reason"] == (
        "private_material_context_binding_required"
        if problem == "no_canonical_ref"
        else "quote_not_in_source"
    )


def test_projected_walk_keeps_other_actual_typed_refs_and_does_not_scan_uuid_values():
    claim, human, artifact, unknown = (uuid4() for _ in range(4))
    value = {
        "source_refs": [{"type": "claim", "id": str(claim), "version": 2}],
        "items": [
            {
                "content": {
                    "decided_by": {
                        "type": "human",
                        "id": str(human),
                        "version": 1,
                        "statement": "Human decision",
                    }
                },
                "required_source_read_set": [
                    {"artifact_id": str(artifact), "expected_revision": 3}
                ],
            }
        ],
        "untyped": {"id": str(unknown), "version": 1},
        "another_uuid": str(unknown),
    }
    assert [(ref.type, ref.id, ref.version) for ref in _projected_references(value)] == [
        ("claim", claim, 2),
        ("human", human, 1),
        ("artifact", artifact, 3),
    ]
