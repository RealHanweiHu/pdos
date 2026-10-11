"""Pure scoped-reader tests; these fixtures never open a database or model."""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.preproject import spec_compare as service
from pdos_next.errors import DomainError
from pdos_next.models import Product


@pytest.fixture
def world(monkeypatch):
    ctx = NS(tenant_id=uuid4(), category_id=uuid4())
    state = NS(
        ctx=ctx,
        proposals={},
        competitors={},
        baselines={},
        products={},
        parameters={},
        source_calls=[],
        reads=[],
        requests=[],
        scope_calls=[],
        denied=set(),
    )

    class Session:
        def get(self, model, identity):
            assert model is Product
            return state.products.get(identity)

    state.session = Session()
    monkeypatch.setattr(service, "category_scope", lambda s, ctx: state.scope_calls.append(ctx))

    def proposal(s, ctx, identity):
        state.reads.append(("proposal", identity))
        if identity not in state.proposals:
            raise DomainError("NOT_FOUND", "Not readable", 404)
        return deepcopy(state.proposals[identity])

    def competitor(s, ctx, identity):
        state.reads.append(("competitor", identity))
        return deepcopy(state.competitors[identity])

    def baseline(s, ctx, identity, *, definition_revision=None):
        state.requests.append((identity, definition_revision))
        return deepcopy(state.baselines[identity])

    def parameter(s, ctx, identity, version):
        state.reads.append(("parameter", identity, version))
        if (identity, version) not in state.parameters:
            raise DomainError("SOURCE_UNAVAILABLE", "Missing actual version")
        return state.parameters[identity, version]

    def source(s, ctx, ref, *, product_id=None):
        state.source_calls.append((ref, product_id))
        if ref.id in state.denied:
            raise DomainError("SOURCE_UNAVAILABLE", "Unreadable original")

    monkeypatch.setattr(service, "_proposal", proposal)
    monkeypatch.setattr(service, "_competitor", competitor)
    monkeypatch.setattr(service.baseline, "read_baseline", baseline)
    monkeypatch.setattr(service.category_service, "parameter_version", parameter)
    monkeypatch.setattr(service, "_check_reference", source)
    monkeypatch.setattr(
        service.category_reads,
        "parameters",
        lambda *a, **kw: {
            "items": [
                {"parameter_id": str(identity), "version": 9}
                for identity in kw["parameter_ids"]
                if (identity, 9) in state.parameters
            ],
            "next_cursor": None,
        },
    )
    return state


def parameter(world, *, version=1, identity=None, value_type="number", condition="23 C"):
    identity = identity or uuid4()
    world.parameters[identity, version] = NS(
        key="pressure",
        name="Pressure",
        value_type=value_type,
        unit="kPa",
        direction="higher",
        standard_condition=condition,
        enum_values=["small", "large"],
    )
    return identity


def item(identity, *, version=1, value="0", **changes):
    content = {
        "key": "pressure",
        "parameter": "Pressure",
        "parameter_id": str(identity),
        "parameter_version": version,
        "value_type": "number",
        "value": value,
        "unit": "kPa",
        "condition_note": "23 C",
        "availability": "known",
        "nature": "decided",
        **changes,
    }
    return {"item_id": str(uuid4()), "kind": "spec", "content": content, "source_refs": []}


def proposal(world, items, **changes):
    identity = uuid4()
    world.proposals[identity] = {
        "id": str(identity),
        "title": "Target",
        "revision": 2,
        "items": items,
        **changes,
    }
    return {"type": "proposal", "id": str(identity)}


def run(world, subjects, **changes):
    return service.compare(world.session, world.ctx, {"subjects": subjects, **changes})


def test_actual_reader_zero_and_no_caller_values(world):
    key = parameter(world)
    subject = proposal(world, [item(key)])
    original = deepcopy(world.proposals)
    result = run(world, [subject])
    observation = result["groups"][0]["observations"][0]
    assert observation["value"] == "0" and observation["comparable"] is True
    assert observation["evidence_kind"] == "target"
    assert world.proposals == original
    assert world.scope_calls == [world.ctx]
    assert ("parameter", key, 1) in world.reads
    assert len(result["input_digest"]) == 64
    with pytest.raises(ValidationError):
        run(world, [{**subject, "value": 900}])
    with pytest.raises(ValidationError):
        run(world, [subject], values=[0])


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2},
        {"unit": "bar"},
        {"condition_note": "30 C"},
        {"test_conditions": ["load=10"]},
    ],
)
def test_exact_versions_units_and_conditions_form_separate_groups(world, change):
    key = parameter(world)
    parameter(world, identity=key, version=2)
    subject = proposal(world, [item(key), item(key, value="10", **change)])
    result = run(world, [subject])
    assert len(result["groups"]) == 2
    assert all(group["sample_count"] == 1 for group in result["groups"])
    assert all(group["separation_reasons"] for group in result["groups"])


def test_dictionary_standard_is_explicit_not_null_wildcard(world):
    key = parameter(world, condition="actual standard")
    subject = proposal(world, [item(key, condition_note=None)])
    result = run(world, [subject])
    group = result["groups"][0]
    assert group["condition_note"] == group["parameter"]["standard_condition"] == "actual standard"
    assert group["observations"][0]["condition_note"] is None
    assert group["observations"][0]["condition_source"] == "parameter_standard"
    world.parameters[key, 1].standard_condition = None
    changed = run(world, [subject])["groups"][0]["observations"][0]
    assert changed["comparable"] is False and "condition_missing" in changed["reasons"]


@pytest.mark.parametrize("availability", ["unknown", "conflicted", "not_applicable"])
def test_unavailable_never_inherits_a_stored_value(world, availability):
    key = parameter(world)
    subject = proposal(world, [item(key, value="99", availability=availability)])
    result = run(world, [subject])
    observation = result["groups"][0]["observations"][0]
    assert observation["value"] is None and observation["comparable"] is False
    assert availability in observation["reasons"]
    assert result["unknown_count"] == int(availability == "unknown")


def test_boolean_false_enum_and_unmapped_free_key_are_preserved(world):
    flag = parameter(world, value_type="boolean")
    size = parameter(world, value_type="enum")
    subject = proposal(
        world,
        [
            item(flag, value=None, value_type="boolean", text_value="false", unit=None),
            item(size, value=None, value_type="enum", text_value="small", unit=None),
            item(None, parameter_id=None, parameter_version=None, key="free", value="5"),
        ],
    )
    result = run(world, [subject])
    assert result["groups"][0]["observations"][0]["value"] is False
    assert result["groups"][1]["observations"][0]["text_value"] == "small"
    assert result["unmapped"][0]["key"] == "free"
    assert result["unmapped"][0]["reasons"] == ["unmapped_parameter"]


def test_missing_historical_version_is_not_replaced_with_current(world):
    key = parameter(world, version=2)
    subject = proposal(world, [item(key, version=1)])
    result = run(world, [subject])
    assert not result["groups"]
    assert "parameter_version_unavailable" in result["unmapped"][0]["reasons"]
    assert ("parameter", key, 2) not in world.reads


def test_withdrawn_source_redacts_quote_and_disables_value(world):
    key = parameter(world)
    spec = item(key)
    identity = uuid4()
    spec["source_refs"] = [
        {
            "type": "claim",
            "id": str(identity),
            "version": 1,
            "quote": "private original",
            "statement": "private statement",
        }
    ]
    subject = proposal(world, [spec])
    world.denied.add(identity)
    observation = run(world, [subject])["groups"][0]["observations"][0]
    assert observation["value"] is None and not observation["comparable"]
    assert observation["source_refs"] == [
        {"type": "claim", "id": str(identity), "version": 1, "status": "unavailable"}
    ]


def test_competitor_observations_and_prices_are_not_averaged_or_replaced(world):
    key = parameter(world)
    identity, source = uuid4(), uuid4()
    ref = {"type": "snapshot", "id": str(source), "version": 1, "line": 1, "quote": "rated"}
    metric = {
        "parameter_id": str(key),
        "parameter_version": 1,
        "value": "0",
        "unit": "kPa",
        "condition_note": "23 C",
        "nature": "claimed",
        "source_ref": ref,
    }
    world.competitors[identity] = {
        "id": str(identity),
        "lineage_id": str(uuid4()),
        "version": 2,
        "source_refs": [],
        "content": {
            "brand": "Fixture",
            "model": "Pump",
            "metrics": [metric, {**metric, "value": "7", "nature": "measured"}],
            "features": [],
            "prices": [
                {
                    "amount": "0",
                    "currency": "USD",
                    "observed_on": "2026-10-01",
                    "price_type": "retail",
                    "source_ref": ref,
                },
                {
                    "amount": "20",
                    "currency": "EUR",
                    "observed_on": "2026-10-02",
                    "price_type": "promo",
                    "source_ref": ref,
                },
            ],
        },
    }
    result = run(world, [{"type": "competitor", "id": str(identity)}])
    rows = result["groups"][0]["observations"]
    assert [row["value"] for row in rows] == ["0", "7"]
    assert [row["evidence_kind"] for row in rows] == ["claimed", "observed"]
    assert [price["amount"] for price in result["subjects"][0]["prices"]] == ["0", "20"]
    assert result["groups"][0]["sample_count"] == 2


@pytest.mark.parametrize("guarded", [False, True])
def test_product_uses_proposals_exact_fixed_baseline_and_honest_kind(world, monkeypatch, guarded):
    key, product_id, definition_id = parameter(world), uuid4(), uuid4()
    subject = proposal(
        world,
        [],
        baseline_product_id=str(product_id),
        baseline_definition_id=str(definition_id),
        baseline_definition_revision=1,
    )
    world.products[product_id] = NS(
        id=product_id,
        tenant_id=world.ctx.tenant_id,
        category_id=world.ctx.category_id,
        name="Current",
        revision=4,
        target_price=Decimal("0"),
        target_price_currency="USD",
        target_price_basis="retail",
        target_price_includes_tax=False,
        target_price_as_of=None,
    )
    world.baselines[product_id] = {
        "baseline_kind": "g0",
        "source_issues": [],
        "definition": {"id": str(definition_id), "revision": 1, "specs": [item(key)["content"]]},
    }
    options, guarded_heads = {}, []
    if guarded:
        selected_head = NS(id=definition_id, revision=1)

        def guard(head):
            guarded_heads.append(head)

        def guarded_baseline(
            s, ctx, identity, *, definition_revision, before_definition_read, include_blocks
        ):
            assert before_definition_read is guard
            assert include_blocks is False
            world.requests.append((identity, definition_revision))
            before_definition_read(selected_head)
            return deepcopy(world.baselines[identity])

        monkeypatch.setattr(service.baseline, "read_baseline", guarded_baseline)
        options["before_definition_read"] = guard
    payload = {"subjects": [subject, {"type": "product", "id": str(product_id)}]}
    result = service.compare(world.session, world.ctx, payload, **options)
    assert world.requests == [(product_id, 1)]
    if guarded:
        assert guarded_heads == [selected_head]
    product = result["subjects"][1]
    assert product["baseline_kind"] == "g0" and product["definition_revision"] == 1
    price = product["prices"][0]
    assert price["amount"] == "0" and price["includes_tax"] is False
    assert price["source_refs"] == [] and "price_source_unavailable" in price["reasons"]
    assert price["availability"] == "unknown" and price["comparable"] is False
    world.baselines[product_id]["definition"]["id"] = str(uuid4())
    with pytest.raises(DomainError, match="固定基线"):
        service.compare(world.session, world.ctx, payload, **options)


def test_selected_definition_guard_failure_stops_comparison_before_body(world, monkeypatch):
    product_id = uuid4()
    selected_head = NS(id=uuid4(), revision=3)
    checked = []

    def deny(head):
        checked.append(head)
        raise DomainError("SOURCE_UNAVAILABLE", "Selected definition is private", 403)

    def guarded_baseline(
        s, ctx, identity, *, definition_revision, before_definition_read, include_blocks
    ):
        assert identity == product_id and definition_revision is None
        assert include_blocks is False
        before_definition_read(selected_head)
        pytest.fail("Private definition contents must not be read")

    monkeypatch.setattr(service.baseline, "read_baseline", guarded_baseline)
    with pytest.raises(DomainError, match="Selected definition is private"):
        service.compare(
            world.session,
            world.ctx,
            {"subjects": [{"type": "product", "id": str(product_id)}]},
            before_definition_read=deny,
        )
    assert checked == [selected_head]
    assert world.reads == [] and world.source_calls == []


def test_proposal_prices_and_unmapped_feature_text_keep_actual_sources(world):
    ref = {"type": "human", "id": str(uuid4()), "version": 1, "statement": "Target decision"}
    subject = proposal(
        world,
        [
            {
                "item_id": str(uuid4()),
                "kind": "commercial_target",
                "source_refs": [ref],
                "content": {
                    "target_price": {
                        "amount": "12",
                        "currency": "USD",
                        "basis": "retail",
                        "as_of": "2026-10-10",
                        "source": ref,
                    }
                },
            },
            {
                "item_id": str(uuid4()),
                "kind": "section",
                "source_refs": [ref],
                "content": {"key": "features_in_out", "text": "No text matching into dictionary"},
            },
        ],
    )
    result = run(world, [subject])
    assert not result["groups"]
    assert result["subjects"][0]["prices"][0]["source_refs"] == [ref]
    assert result["subjects"][0]["unmapped_features"][0]["text"].startswith("No text matching")


def test_extra_parameter_choices_do_not_fabricate_observations(world):
    key = parameter(world)
    extra = parameter(world, version=9)
    subject = proposal(world, [item(key)])
    result = run(world, [subject], parameter_ids=[str(extra)])
    assert result["groups"] == []
    assert result["requested_parameters"] == [{"parameter_id": str(extra), "version": 9}]


def test_unauthorized_proposal_stops_before_reading_comparison_data(world):
    with pytest.raises(DomainError):
        run(world, [{"type": "proposal", "id": str(uuid4())}])
    assert all(read[0] == "proposal" for read in world.reads)


@pytest.mark.parametrize("value", [True, 1.5, "NaN", "Infinity", "marketing text"])
def test_invalid_numeric_values_are_not_converted_to_zero(world, value):
    key = parameter(world)
    result = run(world, [proposal(world, [item(key, value=value)])])
    row = result["groups"][0]["observations"][0]
    assert row["value"] is None and "value_missing_or_invalid" in row["reasons"]


def test_competitor_query_requires_current_entry_and_scope(monkeypatch):
    captured = []
    ctx = NS(tenant_id=uuid4(), category_id=uuid4())
    entry = uuid4()
    session = NS(scalar=lambda query: captured.append(str(query)) or None)
    with pytest.raises(DomainError):
        service._competitor(session, ctx, entry)
    query = captured[0]
    assert "current_entry_id = category_knowledge_entries.id" in query
    assert "category_knowledge_entries.category_id =" in query
    assert "category_knowledge_entries.tenant_id =" in query
    assert "category_knowledge_current.status =" in query


def test_claim_reference_uses_actual_resolver_and_compares_location(monkeypatch):
    from pdos_next.domain.preproject import claim_access
    from pdos_next.domain.preproject.schemas import Reference

    seen = []
    monkeypatch.setattr(
        claim_access,
        "resolve",
        lambda *args, **kwargs: seen.append(kwargs) or NS(quote="actual quotation", line=2),
    )
    ref = Reference(type="claim", id=uuid4(), version=1, line=1, quote="invented")
    with pytest.raises(DomainError):
        service._check_reference(NS(), NS(), ref)
    assert seen == [{"approved": True}]


@pytest.mark.parametrize("current_status", ["active", "withdrawn", None])
def test_fixed_knowledge_preserves_version_and_actual_product_source(monkeypatch, current_status):
    from pdos_next import service as sources
    from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry
    from pdos_next.domain.preproject.schemas import Reference

    ctx = NS(tenant_id=uuid4(), category_id=uuid4())
    identity, artifact, product, lineage = (uuid4() for _ in range(4))
    ref = {"type": "artifact", "id": str(artifact), "version": 2, "line": 2, "quote": "rated"}
    fixed = NS(
        id=identity,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        lineage_id=lineage,
        version=1,
        action="create",
        kind="competitor",
        source_refs=[],
        content={"metrics": [{"source_ref": ref}], "features": [], "prices": []},
    )
    current = NS(status=current_status, current_entry_id=uuid4(), current_version=3)
    calls, queries = [], []

    class Session:
        def get(self, model, key):
            calls.append((model, key))
            return fixed if model is KnowledgeEntry else current

        def execute(self, query):
            queries.append(str(query))
            return NS(mappings=lambda: NS(first=lambda: {"id": artifact, "product_id": product}))

    def source_for(s, actual_ctx, product_id, artifact_id, revision):
        assert actual_ctx is ctx
        assert (product_id, artifact_id, revision) == (product, artifact, 2)
        return NS(content="Header\nrated pressure")

    monkeypatch.setattr(sources, "source_for", source_for)
    session = Session()
    pinned = Reference(type="knowledge", id=identity, version=1)
    service._check_reference(session, ctx, pinned)
    assert all(model is not KnowledgeCurrent for model, _ in calls)
    assert len(queries) == 1
    assert "artifact_versions.content" not in queries[0]
    assert "artifact_versions.tenant_id =" in queries[0]
    assert "artifact_versions.category_id =" in queries[0]
    fixed.action = "withdraw"
    with pytest.raises(DomainError, match="固定知识来源不可读"):
        service._check_reference(session, ctx, pinned)
    fixed.action = "create"
    with pytest.raises(DomainError, match="固定知识来源不可读"):
        service._check_reference(session, ctx, pinned.model_copy(update={"version": 2}))


@pytest.mark.parametrize("unavailable", ["head", "original", "quote"])
def test_product_artifact_scope_does_not_bypass_source_guards(monkeypatch, unavailable):
    from pdos_next import service as sources
    from pdos_next.domain.preproject.schemas import Reference

    ctx = NS(tenant_id=uuid4(), category_id=uuid4())
    artifact, product = uuid4(), uuid4()
    calls = []
    head = None if unavailable == "head" else {"id": artifact, "product_id": product}
    session = NS(execute=lambda _: NS(mappings=lambda: NS(first=lambda: head)))

    def source_for(s, actual_ctx, product_id, artifact_id, revision):
        calls.append((product_id, artifact_id, revision))
        if unavailable == "original":
            raise DomainError("SOURCE_UNAVAILABLE", "Original inaccessible", 403)
        return NS(content="actual content")

    monkeypatch.setattr(sources, "source_for", source_for)
    with pytest.raises(DomainError):
        service._check_reference(
            session,
            ctx,
            Reference(type="artifact", id=artifact, version=2, line=1, quote="invented"),
            product_id=uuid4(),
        )
    assert calls == ([] if unavailable == "head" else [(product, artifact, 2)])


def test_proposal_uses_reviewers_selected_frozen_document(monkeypatch):
    import sys
    from types import ModuleType

    proposal_views = ModuleType("pdos_next.domain.preproject.proposal_views")
    monkeypatch.setitem(sys.modules, proposal_views.__name__, proposal_views)
    fixed = {
        "proposal_id": str(uuid4()),
        "revision": 3,
        "mode": "frozen",
        "submission_id": str(uuid4()),
        "document_digest": "actual fixed digest",
    }
    monkeypatch.setattr(
        proposal_views,
        "read_document",
        lambda *_: {
            "title": "Current",
            "revision": 8,
            "items": [{"kind": "current"}],
            "document_identity": fixed,
            "display_document": {"title": "Frozen", "items": [{"kind": "frozen"}]},
        },
        raising=False,
    )
    result = service._proposal(NS(), NS(), uuid4())
    assert result["title"] == "Frozen" and result["revision"] == 3
    assert result["items"] == [{"kind": "frozen"}]
    assert result["document_identity"] == fixed


def test_product_stale_redacted_sources_cannot_crash_or_supply_values(world):
    key, product_id, definition_id = parameter(world), uuid4(), uuid4()
    world.products[product_id] = NS(
        id=product_id,
        tenant_id=world.ctx.tenant_id,
        category_id=world.ctx.category_id,
        name="Current",
        revision=1,
        target_price=None,
        target_price_currency=None,
        target_price_basis=None,
        target_price_includes_tax=None,
        target_price_as_of=None,
    )
    world.baselines[product_id] = {
        "baseline_kind": "g0",
        "source_issues": [{"reason": "source_stale"}],
        "definition": {
            "id": str(definition_id),
            "revision": 1,
            "specs": [
                {
                    **item(key)["content"],
                    "sources": [{"artifact_id": str(uuid4()), "expected_revision": 1}],
                }
            ],
        },
    }
    result = run(world, [{"type": "product", "id": str(product_id)}])
    row = result["groups"][0]["observations"][0]
    assert row["value"] is None and not row["comparable"]
    assert result["unavailable"]


@pytest.mark.parametrize("source_state", ["absent", "unavailable"])
def test_unverifiable_feature_text_is_not_returned(world, source_state):
    identity = uuid4()
    refs = (
        []
        if source_state == "absent"
        else [{"type": "claim", "id": str(identity), "version": 1, "quote": "private original"}]
    )
    world.denied.add(identity)
    subject = proposal(
        world,
        [
            {
                "item_id": str(uuid4()),
                "kind": "section",
                "source_refs": refs,
                "content": {"key": "features_in_out", "text": "private inferred features"},
            }
        ],
    )
    row = run(world, [subject])["subjects"][0]["unmapped_features"][0]
    assert row["text"] is None and row["availability"] == "unknown"
    assert "private" not in str(row)


def test_complete_price_without_source_stays_unknown_and_is_not_plotted(world):
    from pdos_next.domain.preproject.proposal_views import positioning

    key = parameter(world)
    subject = proposal(
        world,
        [
            item(key),
            {
                "item_id": str(uuid4()),
                "kind": "commercial_target",
                "source_refs": [],
                "content": {
                    "target_price": {
                        "amount": "0",
                        "currency": "USD",
                        "basis": "retail",
                        "as_of": "2026-10-10",
                    }
                },
            },
        ],
    )
    compared = run(world, [subject])
    price = compared["subjects"][0]["prices"][0]
    assert price["amount"] == "0" and price["availability"] == "unknown"
    assert price["comparable"] is False
    plotted = positioning(compared)
    assert plotted["groups"] == []
    assert plotted["unknowns"][0]["reasons"] == ["price_source_unavailable"]
