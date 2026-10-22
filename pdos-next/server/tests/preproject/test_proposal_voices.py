"""Read-only voice projection tests, without PostgreSQL/model/network access."""

from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest

from pdos_next.domain.preproject import proposal_voices as service
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.errors import DomainError
from pdos_next.service import digest


def ref(identity=None, version=1, **fields):
    return {"type": "knowledge", "id": str(identity or uuid4()), "version": version, **fields}


def item(reference, *, identity=None, version=1, label="Actual linked requirement"):
    return {
        "item_id": str(identity or uuid4()),
        "version": version,
        "kind": "section",
        "content": {"key": "worth_it", "text": label},
        "source_refs": [reference],
    }


@pytest.fixture
def world(monkeypatch):
    ctx = NS(tenant_id=uuid4(), category_id=uuid4(), requester_id=uuid4())
    proposal_id, voice_id = uuid4(), uuid4()
    citation = {
        "type": "snapshot",
        "id": str(uuid4()),
        "version": 1,
        "line": 2,
        "quote": "literal source quotation",
    }
    row = NS(
        id=voice_id,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        lineage_id=uuid4(),
        version=1,
        action="add",
        kind="voice",
        origin="ai_draft",
        content={
            "label": "Fixed voice label",
            "source_platform": "Actual platform",
            "sample_size": 7,
            "representative_refs": [citation],
        },
        source_refs=[citation],
    )
    pointer = NS(current_version=1, status="active")
    document = {
        "title": "Readable proposal",
        "brief": "Actual brief",
        "entry_kind": "new_product",
        "target_kind": "new_product",
        "baseline_product_id": None,
        "baseline_definition_id": None,
        "baseline_definition_revision": None,
        "items": [],
        "source_refs": [],
        "context_refs": [ref(voice_id)],
    }
    record = {
        "id": str(proposal_id),
        "category_id": str(ctx.category_id),
        "revision": 5,
        "status": "draft",
        "submission": None,
        **document,
    }
    state = NS(
        ctx=ctx,
        proposal_id=proposal_id,
        row=row,
        pointer=pointer,
        citation=citation,
        record=record,
        rows=[(row, pointer)],
        queries=[],
        document_reads=[],
        guard_reads=[],
        projections=[],
        deny=set(),
        projected_changes=[],
        projected_links=[],
        extra_sources=[],
        fail_raw_quote=False,
    )

    def read_document(s, actual_ctx, identity):
        state.document_reads.append((actual_ctx, identity))
        return deepcopy(state.record)

    def project(s, actual_ctx, entries):
        assert actual_ctx is ctx
        state.projections.extend(deepcopy(entries))
        return [
            {
                **deepcopy(entry),
                "source_refs": [*entry["source_refs"], *state.extra_sources],
                "source_changes": deepcopy(state.projected_changes),
                "evidence_links": deepcopy(state.projected_links),
            }
            for entry in entries
        ]

    def check(s, actual_ctx, reference, **kwargs):
        assert actual_ctx is ctx
        state.guard_reads.append(reference)
        if reference.id in state.deny or (
            state.fail_raw_quote
            and reference.quote is not None
            and reference.quote != reference.quote.strip()
        ):
            raise DomainError("SOURCE_UNAVAILABLE", "Source not readable")

    class Session:
        def execute(self, query):
            assert query.is_select
            assert query.column_descriptions[0]["entity"] is KnowledgeEntry
            state.queries.append(query)
            identities = next(
                value
                for value in query.compile().params.values()
                if isinstance(value, (list, tuple, set))
            )
            return NS(
                all=lambda: [
                    (entry, current)
                    for entry, current in state.rows
                    if entry.id in identities
                    and entry.tenant_id == ctx.tenant_id
                    and entry.category_id == ctx.category_id
                ]
            )

    monkeypatch.setattr(service.proposal_views.views, "read", read_document)
    monkeypatch.setattr(service.spec_compare, "_check_reference", check)
    monkeypatch.setattr(service.root_sources, "project_knowledge", project)
    monkeypatch.setattr(
        service.category_reads,
        "_row",
        lambda entry: {
            **deepcopy(vars(entry)),
            "id": str(entry.id),
            "lineage_id": str(entry.lineage_id),
        },
    )
    state.session = Session()
    return state


def read(world):
    return service.read(world.session, world.ctx, world.proposal_id)


def assert_unavailable(result, reason, *, secret="Fixed voice label"):
    assert result["entries"] == []
    assert result["counts"]["unavailable_entries"] == 1
    row = result["unavailable"][0]
    assert set(row) == {"reference", "reasons"}
    assert set(row["reference"]) <= {"type", "id", "version"}
    assert reason in row["reasons"]
    assert secret not in str(result)
    assert "literal source quotation" not in str(result)
    assert "Actual platform" not in str(result)


def test_only_explicit_fixed_references_are_read_deduplicated_and_keep_ai_origin(world):
    linked = item(ref(world.row.id))
    unrelated = item(ref(), label="Unrelated row text mentioning Fixed voice label")
    unrelated["source_refs"] = []
    world.record["items"] = [linked, unrelated]
    world.record["source_refs"] = [ref(world.row.id)]
    result = read(world)
    assert result["counts"] == {"entries": 1, "unavailable_entries": 0}
    [voice] = result["entries"]
    assert voice["origin"] == "ai_draft" and voice["label"] == "Fixed voice label"
    assert voice["sample_size"] == 7 and voice["used_in_context"] is True
    assert voice["related_items"] == [
        {
            "item_id": linked["item_id"],
            "version": 1,
            "kind": "section",
            "label": "Actual linked requirement",
        }
    ]
    assert voice["representative_refs"] == [world.citation]
    assert world.document_reads == [(world.ctx, world.proposal_id)]
    assert len(world.projections) == 1
    sql = str(world.queries[0])
    assert "category_knowledge_entries.id IN" in sql
    assert "category_knowledge_entries.tenant_id =" in sql
    assert "category_knowledge_entries.category_id =" in sql
    assert "current_entry_id =" not in sql


def test_visible_document_without_voice_edges_never_scans_category_or_infers_text(world):
    world.record["context_refs"] = []
    world.record["items"] = [item(ref(), label="Fixed voice label")]
    world.record["items"][0]["source_refs"] = []
    result = read(world)
    assert result["entries"] == [] and result["unavailable"] == []
    assert world.queries == [] and world.guard_reads == []


def test_named_review_uses_only_frozen_document_and_echoes_the_exact_five_field_identity(world):
    frozen = {key: deepcopy(world.record[key]) for key in service.proposal_views.DOCUMENT_KEYS}
    frozen["items"] = [item(ref(world.row.id), version=3, label="Frozen linked requirement")]
    world.record.update(status="in_review", context_refs=[], items=[])
    world.record["submission"] = {
        "id": str(uuid4()),
        "revision": 3,
        "reviewer_id": str(world.ctx.requester_id),
        "frozen_document": frozen,
        "document_digest": digest(frozen),
    }
    result = read(world)
    assert result["document"] == {
        "proposal_id": str(world.proposal_id),
        "revision": 3,
        "document_digest": digest(frozen),
        "submission_id": world.record["submission"]["id"],
        "document_mode": "frozen",
    }
    assert result["entries"][0]["related_items"][0]["version"] == 3
    assert result["entries"][0]["related_items"][0]["label"] == "Frozen linked requirement"


def test_nonreviewer_keeps_current_document_even_if_retained_submission_has_voice(world):
    frozen = {key: deepcopy(world.record[key]) for key in service.proposal_views.DOCUMENT_KEYS}
    world.record.update(status="in_review", context_refs=[])
    world.record["submission"] = {
        "id": str(uuid4()),
        "revision": 3,
        "reviewer_id": str(uuid4()),
        "frozen_document": frozen,
        "document_digest": digest(frozen),
    }
    result = read(world)
    assert result["document"]["document_mode"] == "current"
    assert result["document"]["submission_id"] is None and result["entries"] == []
    assert world.queries == []


def test_old_fixed_voice_keeps_name_platform_and_saved_sample_count_while_current_advances(world):
    world.pointer.current_version = 4
    result = read(world)
    [voice] = result["entries"]
    assert voice["version"] == 1 and voice["current_version"] == 4
    assert voice["label"] == "Fixed voice label" and voice["sample_size"] == 7
    assert voice["source_changes"] == [
        {
            "type": "knowledge",
            "id": str(world.row.id),
            "version": 1,
            "current_version": 4,
            "status": "active",
        }
    ]


@pytest.mark.parametrize("mode", ["missing", "withdrawn", "fixed_withdrawn", "mismatch"])
def test_unreadable_withdrawn_or_wrong_fixed_version_returns_metadata_only(world, mode):
    reason = {
        "missing": "knowledge_unavailable",
        "withdrawn": "knowledge_withdrawn",
        "fixed_withdrawn": "knowledge_withdrawn",
        "mismatch": "knowledge_version_mismatch",
    }[mode]
    if mode == "missing":
        world.rows = []
    elif mode == "withdrawn":
        world.pointer.status = "withdrawn"
    elif mode == "fixed_withdrawn":
        world.row.action = "withdraw"
    else:
        world.record["context_refs"] = [ref(world.row.id, 2)]
    assert_unavailable(read(world), reason)
    assert world.projections == []


def test_current_pointer_not_readable_cannot_reveal_fixed_body(world):
    world.rows = [(world.row, None)]
    assert_unavailable(read(world), "knowledge_current_unavailable")


@pytest.mark.parametrize("location", ["source", "representative", "linked_source", "fixed"])
def test_any_bottom_source_denial_closes_the_whole_voice(world, location):
    if location == "source":
        denied = UUID(world.citation["id"])
        world.row.content["representative_refs"] = []
    elif location == "representative":
        denied = UUID(world.citation["id"])
        world.row.source_refs = []
    elif location == "linked_source":
        denied = uuid4()
        world.extra_sources = [{**world.citation, "id": str(denied)}]
    else:
        denied = world.row.id
    world.deny.add(denied)
    assert_unavailable(read(world), "source_unavailable")


@pytest.mark.parametrize("kind", ["claim_change", "reverted_link"])
def test_projection_withdrawal_or_reverted_support_never_returns_label_or_snippet(world, kind):
    if kind == "claim_change":
        world.projected_changes = [
            {
                "type": "claim",
                "id": str(uuid4()),
                "version": 1,
                "current_version": 2,
                "status": "withdrawn",
                "quote": "LEAK",
            }
        ]
    else:
        world.projected_links = [{"status": "reverted"}]
    result = read(world)
    assert_unavailable(result, "source_unavailable")
    assert "LEAK" not in str(result)


def test_exact_original_quote_is_rechecked_when_reference_model_trims_whitespace(world):
    world.citation["quote"] = " literal source quotation "
    world.fail_raw_quote = True
    result = read(world)
    assert_unavailable(result, "source_unavailable")
    assert any(reference.quote == " literal source quotation " for reference in world.guard_reads)


def test_legal_identity_only_sources_and_zero_samples_do_not_gain_synthetic_quotes(world):
    human = {"type": "human", "id": str(uuid4()), "version": 1, "statement": "Named statement"}
    world.row.source_refs = [human]
    world.row.content.update(representative_refs=[], sample_size=0)
    [voice] = read(world)["entries"]
    assert voice["source_refs"] == [human] and voice["representative_refs"] == []
    assert voice["sample_size"] == 0 and "quote" not in str(voice)


@pytest.mark.parametrize("value", [None, True, -1, "9", 3.5])
def test_sample_size_is_only_the_fixed_server_integer_never_recomputed(world, value):
    world.row.content["sample_size"] = value
    assert read(world)["entries"][0]["sample_size"] is None


@pytest.mark.parametrize("mode", ["inactive", "wrong_target", "wrong_version"])
def test_illegal_link_cannot_reveal_voice_even_if_it_was_also_flattened_into_sources(world, mode):
    linked = item(ref(world.row.id))
    linked["evidence_links"] = [
        {
            "status": "reverted" if mode == "inactive" else "active",
            "evidence": ref(world.row.id),
            "target": {
                "type": "proposal_item",
                "id": str(uuid4()) if mode == "wrong_target" else linked["item_id"],
                "version": 9 if mode == "wrong_version" else 1,
            },
        }
    ]
    world.record["context_refs"] = []
    world.record["items"] = [linked]
    result = read(world)
    assert_unavailable(
        result, "evidence_link_inactive" if mode == "inactive" else "evidence_link_target_mismatch"
    )
    assert world.queries == []


def test_active_exact_link_and_known_commercial_source_bind_only_their_actual_items(world):
    linked = item(ref(world.row.id))
    linked["source_refs"] = []
    linked["evidence_links"] = [
        {
            "status": "active",
            "evidence": ref(world.row.id),
            "target": {
                "type": "proposal_item",
                "id": linked["item_id"],
                "version": linked["version"],
            },
        }
    ]
    target = {
        "item_id": str(uuid4()),
        "version": 2,
        "kind": "commercial_target",
        "source_refs": [],
        "content": {"target_price": {"amount": "10", "source": ref(world.row.id)}},
    }
    world.record["context_refs"] = []
    world.record["items"] = [linked, target]
    [voice] = read(world)["entries"]
    assert {item["item_id"] for item in voice["related_items"]} == {
        linked["item_id"],
        target["item_id"],
    }
    assert voice["used_in_context"] is False


def test_nonvoice_and_removed_item_references_are_not_reinterpreted_as_voice(world):
    world.row.kind = "segment"
    assert read(world)["entries"] == [] and read(world)["unavailable"] == []
    world.record["context_refs"] = []
    removed = item(ref(world.row.id))
    removed["removed"] = True
    world.record["items"] = [removed]
    result = read(world)
    assert result["counts"] == {"entries": 0, "unavailable_entries": 0}


def test_malformed_reference_is_metadata_only_never_raw_body_or_quote(world):
    world.record["context_refs"] = [
        {
            "type": "knowledge",
            "id": str(world.row.id),
            "version": "broken",
            "quote": "FORGED_PRIVATE_QUOTE",
            "body": "FORGED_PRIVATE_BODY",
            "label": "FORGED_LABEL",
        }
    ]
    result = read(world)
    assert_unavailable(result, "knowledge_reference_invalid")
    assert all(
        value not in str(result)
        for value in ("FORGED_PRIVATE_QUOTE", "FORGED_PRIVATE_BODY", "FORGED_LABEL")
    )


def test_cross_scope_knowledge_query_cannot_publish_foreign_names_or_samples(world):
    world.row.tenant_id = uuid4()
    assert_unavailable(read(world), "knowledge_unavailable")
    world.row.tenant_id = world.ctx.tenant_id
    world.row.category_id = uuid4()
    assert_unavailable(read(world), "knowledge_unavailable")


def test_no_claim_consumption_or_business_mutation_is_reachable_from_projection(world, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("GET cannot consume a Claim or acquire a write-side source lock")

    monkeypatch.setattr(service.root_sources, "consume_claims", forbidden)
    monkeypatch.setattr(service.root_sources, "lock_claim_refs", forbidden)
    result = read(world)
    assert result["counts"]["entries"] == 1
    assert all(query.is_select for query in world.queries)
    assert all("FOR UPDATE" not in str(query) for query in world.queries)
