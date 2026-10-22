"""Fixed competitor associations and matrix admission without database access."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pdos_next import category_scope as scope_module
from pdos_next.domain.preproject import (
    category_matrix as matrix,
)
from pdos_next.domain.preproject import (
    category_service,
    provenance,
    spec_compare,
)
from pdos_next.domain.preproject import (
    competitor_segments as service,
)
from pdos_next.domain.preproject.category_creation import InitialKnowledge
from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry
from pdos_next.domain.preproject.category_schemas import (
    CompetitorContent,
    KnowledgeAdd,
    KnowledgePromote,
)
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Product
from pdos_next.service import Context, digest


def fixed(entry):
    return {"entry_id": str(entry.id), "version": entry.version}


def material(ctx, kind, content, *, lineage=None, version=1, source=None, origin="human"):
    refs = [deepcopy(source)] if source else []
    if kind == "competitor":
        payload = KnowledgeAdd(kind=kind, content=content, source_refs=refs)
        content = payload.content
        refs = [ref.model_dump(mode="json") for ref in category_service._references(payload)]
    return KnowledgeEntry(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        lineage_id=lineage or uuid4(),
        version=version,
        action="add" if version == 1 else "supersede",
        kind=kind,
        content=deepcopy(content),
        regions=["CN"],
        source_refs=refs,
        origin=origin,
        writer_id=ctx.requester_id,
        run_id=uuid4() if origin == "ai_draft" else None,
        confirmed_by=None,
        receipt_id=None,
        prepared_candidate_id=None,
        created_at=datetime(2026, 10, 17, tzinfo=UTC),
    )


def current(entry):
    return KnowledgeCurrent(
        tenant_id=entry.tenant_id,
        category_id=entry.category_id,
        lineage_id=entry.lineage_id,
        kind=entry.kind,
        current_entry_id=entry.id,
        current_version=entry.version,
        status="active",
        origin=entry.origin,
    )


@pytest.fixture
def world(monkeypatch):
    tenant, person, category = uuid4(), uuid4(), uuid4()
    ctx = Context(tenant, person, person, category_id=category)
    source = {
        "type": "human",
        "id": str(person),
        "version": 1,
        "statement": "Real named market observation",
    }
    source = Reference.model_validate(source).model_dump(mode="json")
    old = material(ctx, "segment", {"segment": "Original fixed segment"}, source=source)
    new = material(
        ctx,
        "segment",
        {"segment": "Current renamed segment"},
        lineage=old.lineage_id,
        version=2,
        source=source,
    )
    other = material(ctx, "segment", {"segment": "Second current segment"}, source=source)
    price = {
        "amount": "150.000000000001",
        "currency": "CNY",
        "observed_on": "2026-10-17",
        "price_type": "retail",
        "includes_tax": True,
        "includes_shipping": False,
        "channel": "retail",
        "region": "CN",
        "source_ref": source,
    }
    competitor = material(
        ctx,
        "competitor",
        {
            "brand": "Visible brand",
            "model": "Visible model",
            "metrics": [],
            "features": [],
            "prices": [price],
            "segment_refs": [fixed(old)],
        },
        source=source,
        origin="ai_draft",
    )
    entries = {entry.id: entry for entry in (old, new, other, competitor)}
    pointers = {entry.lineage_id: current(entry) for entry in (new, other, competitor)}
    state = NS(
        ctx=ctx,
        old=old,
        new=new,
        other=other,
        competitor=competitor,
        entries=entries,
        pointers=pointers,
        option_ids=[new.id, other.id],
        source=source,
        write=True,
        denied=set(),
        source_calls=[],
        projections=[],
        queries=[],
        scope_calls=[],
        extra_sources=[],
        changes=set(),
        shared_calls=[],
        private_checks=[],
    )

    def scope(s, context, *, write=False, lock=False):
        state.scope_calls.append((context, write, lock))
        if write and not state.write:
            raise DomainError("FORBIDDEN_SCOPE", "Read only", 403)

    def check(s, context, reference, **kwargs):
        assert context is state.ctx
        state.source_calls.append(reference)
        if reference.id in state.denied:
            raise DomainError("SOURCE_UNAVAILABLE", "Hidden source")
        if reference.type == "knowledge":
            entry = entries.get(reference.id)
            if (
                not entry
                or entry.tenant_id != context.tenant_id
                or entry.category_id != context.category_id
                or entry.version != reference.version
            ):
                raise DomainError("SOURCE_UNAVAILABLE", "Hidden knowledge")
            if any(UUID(raw["id"]) in state.denied for raw in entry.source_refs):
                raise DomainError("SOURCE_UNAVAILABLE", "Hidden bottom source")

    def projection(s, context, rows):
        assert context is state.ctx
        state.projections.extend(deepcopy(rows))
        result = []
        for row in rows:
            value = deepcopy(row)
            if state.extra_sources:
                value["direct_source_refs"] = deepcopy(row["source_refs"])
                value["source_refs"] += deepcopy(state.extra_sources)
            if UUID(row["id"]) in state.changes:
                value["source_changes"] = [{"type": "claim", "status": "withdrawn"}]
            result.append(value)
        return result

    def selected(query):
        values = [
            value
            for value in query.compile().params.values()
            if isinstance(value, (list, set, tuple))
        ]
        return set(values[0]) if values else set()

    class Session:
        info = {"scope": (tenant, person, person, category), "read_snapshot": True}

        def get(self, model, identity):
            if model is Principal:
                return NS(kind="human", active=True)
            assert model is KnowledgeEntry
            return entries.get(identity)

        def execute(self, query):
            state.queries.append(query)
            assert query.is_select
            columns = query.column_descriptions
            if columns[0]["expr"] is KnowledgeEntry and columns[1]["expr"] is KnowledgeCurrent:
                pair = (state.competitor, pointers.get(state.competitor.lineage_id))
                return NS(first=lambda: pair)
            if columns[0]["expr"] is KnowledgeEntry:
                ids = selected(query)
                rows = [
                    (
                        entry,
                        pointers[entry.lineage_id].status if entry.lineage_id in pointers else None,
                    )
                    for identity, entry in entries.items()
                    if identity in ids
                ]
                return NS(all=lambda: rows)
            assert columns[0]["entity"] is KnowledgeEntry
            return NS(
                all=lambda: [
                    (entries[identity].id, entries[identity].version)
                    for identity in state.option_ids
                ]
            )

        def scalars(self, query):
            state.queries.append(query)
            first = query.column_descriptions[0]
            if first["entity"] is Product:
                return iter(())
            if first["entity"] is KnowledgeCurrent:
                assert query._for_update_arg.read is True
                return iter(pointers[lineage] for lineage in selected(query) if lineage in pointers)
            assert first["entity"] is KnowledgeEntry
            return iter(
                entries[identity].lineage_id for identity in selected(query) if identity in entries
            )

    state.session = Session()
    monkeypatch.setattr(service, "category_scope", scope)
    monkeypatch.setattr(scope_module, "category_scope", scope)
    monkeypatch.setattr(matrix, "category_scope", scope)
    monkeypatch.setattr(spec_compare, "_check_reference", check)
    monkeypatch.setattr(service.root_sources, "project_knowledge", projection)
    monkeypatch.setattr(service, "now", lambda: datetime(2026, 10, 17, tzinfo=UTC))
    monkeypatch.setattr(
        provenance,
        "writing_path",
        lambda *args: {
            "origin": "human",
            "writer_id": person,
            "run_id": None,
            "confirmed_by": None,
            "prepared_candidate_id": None,
        },
    )
    monkeypatch.setattr(
        category_service, "check_shared_sources", lambda s, c, refs: state.shared_calls.extend(refs)
    )
    monkeypatch.setattr(
        category_service,
        "proposal",
        lambda *args, **kwargs: NS(id=uuid4(), revision=1, customer_identities=[]),
    )
    monkeypatch.setattr(
        category_service,
        "_private_checks",
        lambda *args: state.private_checks.append(args) or {"hits": [], "refs_clean": True},
    )
    return state


def assignment(world):
    return service.read(world.session, world.ctx, world.competitor.id)


def command(world, payload):
    operation = (
        "category.knowledge.promote"
        if isinstance(payload, KnowledgePromote)
        else "category.knowledge.add"
    )
    return category_service.validate(
        world.session, world.ctx, NS(operation=operation, product_id=None), None, payload
    )


@pytest.mark.parametrize("operation", ["add", "promote"])
def test_legacy_content_canonical_defaults_and_digests_do_not_gain_empty_segment_key(operation):
    content = {"brand": "Legacy", "model": "One"}
    expected = {"brand": "Legacy", "model": "One", "metrics": [], "features": [], "prices": []}
    if operation == "add":
        value = KnowledgeAdd(kind="competitor", content=content)
    else:
        value = KnowledgePromote(
            kind="competitor",
            content=content,
            source_proposal_id=uuid4(),
            source_proposal_revision=1,
            deidentified_confirmed=True,
        )
    assert value.content == expected
    assert digest(value.content) == digest(expected)
    assert "segment_refs" not in value.model_dump(mode="json")["content"]
    assert type(value).model_validate(value.model_dump(mode="json")).content == expected
    cleared = CompetitorContent.model_validate({**content, "segment_refs": []}).model_dump(
        mode="json"
    )
    assert cleared == {**expected, "segment_refs": []}


@pytest.mark.parametrize(
    "refs",
    [
        [{"entry_id": str(UUID(int=1)), "version": 1}] * 2,
        [{"entry_id": str(UUID(int=1)), "version": 0}],
        [{"entry_id": str(UUID(int=1)), "version": True}],
        [{"entry_id": str(UUID(int=1)), "version": 1, "label": "Forged"}],
        [{"lineage_id": str(UUID(int=1)), "version": 1}],
    ],
)
def test_segment_reference_shape_is_closed_positive_and_distinct(refs):
    with pytest.raises(ValidationError):
        KnowledgeAdd(kind="competitor", content={"brand": "A", "model": "B", "segment_refs": refs})


@pytest.mark.parametrize("provided", [False, True])
def test_new_category_empty_association_preserves_legacy_canonical_defaults(provided):
    content = {"brand": "Initial", "model": "One"}
    if provided:
        content["segment_refs"] = []
    expected = {**content, "metrics": [], "features": [], "prices": []}
    value = InitialKnowledge(kind="competitor", content=content)
    assert value.content == expected and digest(value.content) == digest(expected)


def test_new_category_cannot_reference_an_existing_fixed_segment_in_another_scope():
    with pytest.raises(ValidationError):
        InitialKnowledge(
            kind="competitor",
            content={
                "brand": "Initial",
                "model": "One",
                "segment_refs": [{"entry_id": str(uuid4()), "version": 1}],
            },
        )


@pytest.mark.parametrize("operation", ["add", "promote"])
def test_both_commands_validate_explicit_historical_refs_with_same_guard_without_provenance_edges(
    world, operation
):
    if operation == "add":
        payload = KnowledgeAdd(
            kind="competitor", content=world.competitor.content, source_refs=[world.source]
        )
    else:
        payload = KnowledgePromote(
            kind="competitor",
            content=world.competitor.content,
            source_proposal_id=uuid4(),
            source_proposal_revision=1,
            deidentified_confirmed=True,
        )
    result = command(world, payload)
    assert result.provenance["origin"] == "human"
    assert any(
        ref.type == "knowledge" and ref.id == world.old.id and ref.version == 1
        for ref in world.source_calls
    )
    assert all(ref.type != "knowledge" for ref in world.shared_calls)
    assert world.old.content["segment"] == "Original fixed segment"
    assert world.pointers[world.old.lineage_id].current_version == 2
    locks = [query for query in world.queries if query._for_update_arg is not None]
    assert len(locks) == 1 and locks[0]._for_update_arg.read is True
    assert "ORDER BY category_knowledge_current.lineage_id" in str(locks[0])


@pytest.mark.parametrize("operation", ["add", "promote"])
@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "wrong_kind",
        "wrong_version",
        "cross_tenant",
        "cross_category",
        "withdrawn",
        "fixed_withdrawn",
        "hidden_current",
        "source_denied",
        "root_changed",
    ],
)
def test_invalid_target_or_bottom_source_fails_closed_for_both_commands(world, operation, mode):
    ref = fixed(world.old)
    if mode == "missing":
        ref["entry_id"] = str(uuid4())
    elif mode == "wrong_kind":
        world.old.kind = "voice"
    elif mode == "wrong_version":
        ref["version"] = 2
    elif mode == "cross_tenant":
        world.old.tenant_id = uuid4()
    elif mode == "cross_category":
        world.old.category_id = uuid4()
    elif mode == "withdrawn":
        world.pointers[world.old.lineage_id].status = "withdrawn"
    elif mode == "fixed_withdrawn":
        world.old.action = "withdraw"
    elif mode == "hidden_current":
        del world.pointers[world.old.lineage_id]
    elif mode == "source_denied":
        world.denied.add(UUID(world.source["id"]))
    else:
        world.changes.add(world.old.id)
    content = {**world.competitor.content, "segment_refs": [ref]}
    payload = (
        KnowledgeAdd(kind="competitor", content=content)
        if operation == "add"
        else KnowledgePromote(
            kind="competitor",
            content=content,
            source_proposal_id=uuid4(),
            source_proposal_revision=1,
            deidentified_confirmed=True,
        )
    )
    with pytest.raises(DomainError) as error:
        command(world, payload)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert error.value.detail["reason"] == "competitor_segment_unavailable"


def test_assignment_lists_current_options_but_keeps_selected_old_version_and_ai_history(world):
    value = assignment(world)
    assert value["version"] == "competitor-segment-assignment/v1"
    assert value["category_id"] == str(world.ctx.category_id)
    assert value["principal_id"] == str(world.ctx.requester_id)
    assert value["can_edit"] is True and value["blockers"] == []
    assert value["competitor"]["origin"] == "ai_draft" and value["competitor"]["run_id"] == str(
        world.competitor.run_id
    )
    assert value["competitor"]["content"] == world.competitor.content
    [selected] = value["selected_segments"]
    assert selected == {
        **fixed(world.old),
        "lineage_id": str(world.old.lineage_id),
        "label": "Original fixed segment",
        "status": "available",
        "source_refs": [world.source],
    }
    assert {row["entry_id"] for row in value["segments"]} == {
        str(world.new.id),
        str(world.other.id),
    }
    assert value["unavailable_segment_count"] == 0
    assert all(query._for_update_arg is None for query in world.queries)


def test_assignment_returns_only_safe_direct_refs_not_derived_evidence_links(world):
    derived = {
        "type": "human",
        "id": str(uuid4()),
        "version": 1,
        "statement": "Derived linked statement",
    }
    world.extra_sources = [derived]
    value = assignment(world)
    assert value["competitor"]["source_refs"] == [world.source]
    assert derived not in value["competitor"]["source_refs"]
    assert any(str(ref.id) == derived["id"] for ref in world.source_calls)


@pytest.mark.parametrize(
    "mode", ["nested_only", "explicit_and_nested", "explicit_same_source_twice", "promotion_empty"]
)
def test_edit_dto_roundtrip_preserves_explicit_sources_without_appending_nested_twice(world, mode):
    nested = [
        ref.model_dump(mode="json")
        for ref in category_service._references(
            KnowledgeAdd(kind="competitor", content=world.competitor.content)
        )
    ]
    if mode == "explicit_and_nested":
        prefix = [
            Reference(
                type="human", id=uuid4(), version=1, statement="Explicit top source"
            ).model_dump(mode="json")
        ]
    elif mode == "explicit_same_source_twice":
        prefix = [deepcopy(world.source), deepcopy(world.source)]
    else:
        prefix = []
    stored = [] if mode == "promotion_empty" else [*deepcopy(prefix), *deepcopy(nested)]
    world.competitor.source_refs = stored
    value = assignment(world)
    assert value["can_edit"] is True
    assert value["competitor"]["source_refs"] == prefix
    rebuilt = KnowledgeAdd(
        kind="competitor",
        content=value["competitor"]["content"],
        source_refs=value["competitor"]["source_refs"],
    )
    actual = [ref.model_dump(mode="json") for ref in category_service._references(rebuilt)]
    assert actual == [*prefix, *nested]
    if mode != "promotion_empty":
        assert actual == stored
    assert world.competitor.source_refs == stored


def test_dto_strips_only_exact_metric_feature_price_suffix_in_saved_order(world):
    refs = [
        Reference(type="human", id=uuid4(), version=1, statement=f"Observation {n}").model_dump(
            mode="json"
        )
        for n in range(4)
    ]
    metric = {"parameter_id": str(uuid4()), "parameter_version": 1, "nature": "claimed"}
    content = {
        **world.competitor.content,
        "metrics": [{**metric, "source_ref": refs[1]}],
        "features": [{**metric, "source_ref": refs[2]}],
        "prices": [{**world.competitor.content["prices"][0], "source_ref": refs[3]}],
    }
    payload = KnowledgeAdd(kind="competitor", content=content, source_refs=[refs[0]])
    world.competitor.content = payload.content
    world.competitor.source_refs = [
        ref.model_dump(mode="json") for ref in category_service._references(payload)
    ]
    value = assignment(world)
    assert value["can_edit"] is True
    assert value["competitor"]["source_refs"] == [refs[0]]


@pytest.mark.parametrize(
    "mode", ["different_tail", "incomplete_suffix", "wrong_order", "missing_canonical_field"]
)
def test_nonempty_saved_sources_that_do_not_match_nested_suffix_fail_closed(world, mode):
    other = Reference(
        type="human", id=uuid4(), version=1, statement="Other valid source"
    ).model_dump(mode="json")
    payload = KnowledgeAdd(
        kind="competitor",
        content={
            **world.competitor.content,
            "prices": [
                world.competitor.content["prices"][0],
                {**world.competitor.content["prices"][0], "source_ref": other},
            ],
        },
    )
    world.competitor.content = payload.content
    if mode == "different_tail":
        world.competitor.source_refs = [world.source, world.source]
    elif mode == "incomplete_suffix":
        world.competitor.source_refs = [world.source]
    elif mode == "wrong_order":
        world.competitor.source_refs = [other, world.source]
    else:
        missing = deepcopy(other)
        del missing["quote"]
        world.competitor.source_refs = [world.source, missing]
    value = assignment(world)
    assert value["can_edit"] is False
    assert value["competitor"]["content"] is None
    assert value["competitor"]["source_refs"] == []
    assert value["blockers"][-1]["code"] == "competitor_source_unavailable"
    assert "Visible brand" not in str(value) and "Other valid source" not in str(value)


def test_no_nested_references_keeps_explicit_sources_verbatim(world):
    world.competitor.content["prices"] = []
    world.competitor.source_refs = [world.source, deepcopy(world.source)]
    value = assignment(world)
    assert value["can_edit"] is True
    assert value["competitor"]["source_refs"] == world.competitor.source_refs


@pytest.mark.parametrize("mode", ["missing", "withdrawn", "source_denied"])
def test_unavailable_selected_identity_has_no_label_but_does_not_prevent_clear(world, mode):
    if mode == "missing":
        del world.entries[world.old.id]
    elif mode == "withdrawn":
        world.pointers[world.old.lineage_id].status = "withdrawn"
        world.option_ids = [world.other.id]
    else:
        world.denied.add(world.old.id)
    value = assignment(world)
    selected = value["selected_segments"][0]
    assert value["can_edit"] is True
    assert selected == {
        **fixed(world.old),
        "lineage_id": None,
        "label": None,
        "status": "unavailable",
        "source_refs": [],
    }
    assert value["unavailable_segment_count"] == 1
    command(
        world,
        KnowledgeAdd(kind="competitor", content={**world.competitor.content, "segment_refs": []}),
    )


def test_base_source_failure_redacts_content_and_direct_refs_without_exposing_nested_quotes(world):
    world.denied.add(world.competitor.id)
    value = assignment(world)
    competitor = value["competitor"]
    assert (
        competitor["content"] is None
        and competitor["source_refs"] == []
        and competitor["regions"] == []
    )
    assert value["can_edit"] is False
    assert value["blockers"][0]["code"] == "competitor_source_unavailable"
    assert "Visible brand" not in str(value) and "Visible model" not in str(value)
    assert value["selected_segments"][0]["label"] is None


def test_read_only_category_keeps_readable_content_without_inventing_role_permission(world):
    world.write = False
    value = assignment(world)
    assert value["can_edit"] is False
    assert value["blockers"] == [
        {"code": "category_write_required", "message": "当前没有品类写入权限。"}
    ]
    assert value["competitor"]["content"]["brand"] == "Visible brand"
    with pytest.raises(DomainError):
        command(world, KnowledgeAdd(kind="competitor", content=world.competitor.content))


@pytest.mark.parametrize("mode", ["moved", "withdrawn", "cross_category", "cross_tenant", "agent"])
def test_stale_competitor_or_nonordinary_identity_is_rejected(world, mode):
    if mode == "moved":
        world.pointers[world.competitor.lineage_id].current_entry_id = uuid4()
    elif mode == "withdrawn":
        world.pointers[world.competitor.lineage_id].status = "withdrawn"
    elif mode == "cross_category":
        world.competitor.category_id = uuid4()
    elif mode == "cross_tenant":
        world.competitor.tenant_id = uuid4()
    else:
        world.ctx = replace(world.ctx, agent_run_id=uuid4())
    with pytest.raises(DomainError) as error:
        assignment(world)
    assert error.value.status in {403, 404, 409}


def test_option_source_unavailable_is_counted_without_label_or_quote_leak(world):
    world.denied.add(world.new.id)
    value = assignment(world)
    assert str(world.new.id) not in {row["entry_id"] for row in value["segments"]}
    assert "Current renamed segment" not in str(value)
    assert value["unavailable_segment_count"] == 1


def matrix_read(world, monkeypatch):
    monkeypatch.setattr(
        matrix.category_reads,
        "knowledge",
        lambda *args, **kwargs: {
            "items": [
                {
                    "id": str(world.competitor.id),
                    "version": world.competitor.version,
                    "content": deepcopy(world.competitor.content),
                    "origin": world.competitor.origin,
                    "source_refs": [world.source],
                }
            ],
            "next_cursor": None,
        },
    )
    return matrix.read(world.session, world.ctx)


def test_matrix_places_actual_competitor_with_exact_price_and_original_fixed_segment(
    world, monkeypatch
):
    value = matrix_read(world, monkeypatch)
    assert value["coverage"]["placed_subjects"] == 1
    assert value["coverage"]["placements"] == 1
    row = value["groups"][0]["rows"][0]
    assert row["segment"]["label"] == "Original fixed segment" and row["segment"]["version"] == 1
    [placed] = row["cells"][1]["competitors"]
    assert placed["subject"]["id"] == str(world.competitor.id)
    assert placed["price"]["amount"] == "150.000000000001"
    assert "competitor_segment_link_unavailable" not in value["limitations"]
    assert "competitor_segments_missing" not in value["limitations"]


def test_matrix_unlinked_competitor_remains_missing_with_conditional_limitation(world, monkeypatch):
    del world.competitor.content["segment_refs"]
    value = matrix_read(world, monkeypatch)
    assert value["groups"] == [] and value["coverage"]["placed_subjects"] == 0
    assert "segment_missing" in value["unplaced"][0]["reasons"]
    assert "competitor_segments_missing" in value["limitations"]


@pytest.mark.parametrize("mode", ["missing", "withdrawn", "source_denied"])
def test_matrix_unavailable_fixed_ref_is_neutral_unplaced_with_traceable_identity(
    world, monkeypatch, mode
):
    if mode == "missing":
        del world.entries[world.old.id]
    elif mode == "withdrawn":
        world.pointers[world.old.lineage_id].status = "withdrawn"
    else:
        world.denied.add(world.old.id)
    value = matrix_read(world, monkeypatch)
    assert value["groups"] == [] and value["coverage"]["placed_subjects"] == 0
    [unplaced] = value["unplaced"]
    assert unplaced["fixed_segment"] is None
    assert unplaced["segment_reference"] == fixed(world.old)
    assert "Original fixed segment" not in str(value)
    assert "segment_missing" not in unplaced["reasons"]


def test_query_scopes_are_exact_and_current_version_is_not_used_for_historical_resolution(world):
    assignment(world)
    fixed_query = next(
        query for query in world.queries if "category_knowledge_entries.id IN" in str(query)
    )
    text = str(fixed_query)
    assert "category_knowledge_entries.tenant_id =" in text
    assert "category_knowledge_entries.category_id =" in text
    assert "current_entry_id = category_knowledge_entries.id" not in text
    assert "current_version = category_knowledge_entries.version" not in text
