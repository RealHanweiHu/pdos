"""Pure matrix/source-reader checks; no database or credentials are opened."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.domain.preproject import category_matrix as matrix
from pdos_next.domain.preproject.category_models import KnowledgeEntry, ProductTargetSegment
from pdos_next.domain.preproject.models import ProposalDecision
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.service import digest


def source():
    return {"type": "snapshot", "id": str(uuid4()), "version": 1}


def segment(label="Fixed segment", version=1, **changes):
    return {
        "lineage_id": str(uuid4()),
        "version": version,
        "entry_id": str(uuid4()),
        "label": label,
        "status": "active",
        "source_refs": [source()],
        "reasons": [],
        **changes,
    }


def price(amount="150", **changes):
    return {
        "amount": amount,
        "currency": "CNY",
        "as_of": "2026-10-17",
        "basis": "retail",
        "includes_tax": True,
        "source_refs": [source()],
        "reasons": [],
        **changes,
    }


def subject(amount="150", *, fixed=None, typ="product", **changes):
    return {
        "subject": {"type": typ, "id": str(uuid4()), "label": "Visible object", "revision": 1},
        "segments": [fixed or segment()],
        "prices": [price(amount, **changes)],
    }


def placements(result):
    return [cell for group in result["groups"] for row in group["rows"] for cell in row["cells"]]


@pytest.mark.parametrize(
    ("amount", "band"),
    [
        ("0", 0),
        ("149.999999999999", 0),
        ("150", 1),
        ("299.999999999999", 1),
        ("300.000000000000", 2),
    ],
)
def test_exact_decimal_boundaries_and_zero_are_real_values(amount, band):
    result = matrix.compute(uuid4(), [subject(amount)])
    assert [cell["counts"]["products"] for cell in placements(result)] == [
        int(index == band) for index in range(3)
    ]
    assert result["display"]["bands"][2]["lower"] == "300"
    assert result["display"]["bands"][2]["lower_inclusive"] is True
    assert all(
        cell["status"] == "no_readable_observations"
        for index, cell in enumerate(placements(result))
        if index != band
    )


@pytest.mark.parametrize(
    "breaks", [[], [150, 150], [300, 150], [0], [-1], [150.0], ["NaN"], ["Infinity"], "12", [True]]
)
def test_bad_display_breaks_are_validation_errors_not_policy_changes(breaks):
    with pytest.raises(DomainError) as caught:
        matrix.compute(uuid4(), [], breaks=breaks)
    assert caught.value.code == "VALIDATION_FAILED"
    assert caught.value.detail["reason"] == "price_breaks_invalid"


def test_readonly_breaks_recompute_bands_without_mutating_subjects():
    subjects = [subject("150")]
    before = deepcopy(subjects)
    result = matrix.compute(uuid4(), subjects, breaks=["100", "150.0001", "1000"])
    assert result["display"]["breaks"] == ["100", "150.0001", "1000"]
    assert placements(result)[1]["counts"]["products"] == 1
    assert subjects == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("currency", "USD"),
        ("as_of", "2026-10-16"),
        ("basis", "promo"),
        ("includes_tax", False),
        ("includes_shipping", False),
        ("region", "EU"),
        ("channel", "retail-web"),
    ],
)
def test_every_price_basis_dimension_stays_in_its_own_group(field, value):
    fixed = segment()
    result = matrix.compute(uuid4(), [subject(fixed=fixed), subject(fixed=fixed, **{field: value})])
    assert len(result["groups"]) == 2
    assert result["coverage"]["placed_subjects"] == 2
    assert result["groups"][0]["basis"] != result["groups"][1]["basis"]


def test_unknown_values_missing_sources_and_no_competitor_segment_never_get_zero_points():
    unknown = subject(None)
    absent_source = subject("88", source_refs=[])
    competitor = subject("120", typ="competitor")
    competitor["segments"] = []
    result = matrix.compute(uuid4(), [unknown, absent_source, competitor])
    assert result["groups"] == []
    assert result["coverage"]["unplaced_subjects"] == 3
    assert {reason for row in result["unplaced"] for reason in row["reasons"]} >= {
        "price_unknown",
        "price_source_unavailable",
        "segment_missing",
    }
    assert result["unplaced"][0]["price"]["amount"] is None
    assert result["unplaced"][2]["fixed_segment"] is None


def test_multi_segment_coverage_counts_subjects_once_and_keeps_partial_failures():
    item = subject("150")
    item["segments"].append(segment("withdrawn", reasons=["segment_withdrawn"]))
    result = matrix.compute(uuid4(), [item])
    assert result["coverage"]["placed_subjects"] == 1
    assert result["coverage"]["partially_placed_subjects"] == 1
    assert result["coverage"]["unplaced_subjects"] == 0
    assert result["coverage"]["placements"] == 1
    assert result["coverage"]["reason_counts"] == {"segment_withdrawn": 1}


@pytest.fixture
def world(monkeypatch):
    ctx = NS(tenant_id=uuid4(), category_id=uuid4())
    product = NS(
        id=uuid4(),
        name="Visible product",
        revision=2,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        target_price=Decimal("150.00"),
        target_price_currency="CNY",
        target_price_basis="retail",
        target_price_includes_tax=True,
        target_price_as_of=date(2026, 10, 17),
    )
    entry = NS(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        lineage_id=uuid4(),
        version=1,
        action="add",
        kind="segment",
        content={"segment": "Original pinned name"},
        source_refs=[],
    )
    link = NS(product_id=product.id, segment_lineage_id=entry.lineage_id, segment_version=1)
    ref = source()
    value = {
        "amount": "150.00",
        "currency": "CNY",
        "basis": "retail",
        "includes_tax": True,
        "as_of": "2026-10-17",
        "source": ref,
    }
    document = {
        "items": [
            {
                "item_id": str(uuid4()),
                "kind": "commercial_target",
                "content": {"target_price": value},
                "source_refs": [],
            }
        ]
    }
    submission = NS(
        id=uuid4(), revision=3, frozen_document=document, document_digest=digest(document)
    )
    decision = NS(id=uuid4(), proposal_id=uuid4(), created_product_id=product.id)
    state = NS(
        ctx=ctx,
        product=product,
        entry=entry,
        link=link,
        ref=ref,
        value=value,
        submission=submission,
        decision=decision,
        products=[product],
        denied=set(),
        links=[link],
        fixed=[(entry, "active")],
        g0=[(decision, submission)],
        queries=[],
        sources=[],
        deny_sources=set(),
        competitors=[],
        scope=[],
        access=[],
    )

    class Session:
        def scalars(self, query):
            state.queries.append(query)
            model = query.column_descriptions[0]["entity"]
            assert model in {Product, ProductTargetSegment}
            return iter(state.products if model is Product else state.links)

        def execute(self, query):
            state.queries.append(query)
            model = query.column_descriptions[0]["entity"]
            assert model in {KnowledgeEntry, ProposalDecision}
            return NS(all=lambda: state.fixed if model is KnowledgeEntry else state.g0)

    def access(s, context, identity):
        state.access.append((context, identity))
        if identity in state.denied:
            raise DomainError("FORBIDDEN_SCOPE", "Unreadable", 403)

    def check_source(s, context, reference, *, product_id=None):
        state.sources.append((context, reference, product_id))
        if str(reference.id) in state.deny_sources:
            raise DomainError("SOURCE_UNAVAILABLE", "Unavailable source")

    monkeypatch.setattr(matrix, "category_scope", lambda s, c: state.scope.append(c))
    monkeypatch.setattr(matrix, "require_access", access)
    monkeypatch.setattr(matrix.spec_compare, "_check_reference", check_source)
    monkeypatch.setattr(
        matrix.category_reads,
        "knowledge",
        lambda s, c, **kw: {
            "items": deepcopy(state.competitors),
            "next_cursor": None,
        },
    )
    state.session = Session()
    return state


def test_read_can_place_actual_product_only_with_readable_equal_frozen_g0_source(world):
    result = matrix.read(world.session, world.ctx)
    assert result["coverage"]["placed_subjects"] == 1
    item = placements(result)[1]["products"][0]
    assert item["price"]["g0_source"]["submission_id"] == str(world.submission.id)
    assert item["price"]["source_refs"] == [world.ref]
    assert world.scope == [world.ctx]
    assert world.access == [(world.ctx, world.product.id)]
    assert any(ref.id == world.entry.id for _, ref, _ in world.sources)
    assert any(str(ref.id) == world.ref["id"] for _, ref, _ in world.sources)
    assert result["groups"][0]["rows"][0]["segment"]["label"] == "Original pinned name"
    assert result["groups"][0]["basis"]["includes_shipping"] is None
    assert result["groups"][0]["basis"]["channel"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", "149"),
        ("currency", "USD"),
        ("basis", "promo"),
        ("includes_tax", False),
        ("as_of", "2026-10-16"),
    ],
)
def test_g0_price_must_match_all_current_saved_target_fields(world, field, value):
    world.value[field] = value
    world.submission.document_digest = digest(world.submission.frozen_document)
    result = matrix.read(world.session, world.ctx)
    assert result["groups"] == []
    assert "target_price_g0_mismatch" in result["unplaced"][0]["reasons"]


def test_missing_private_or_bad_digest_g0_never_uses_product_identity_as_source(world):
    world.g0 = []
    result = matrix.read(world.session, world.ctx)
    assert result["groups"] == []
    assert "g0_price_source_unavailable" in result["unplaced"][0]["reasons"]
    assert not any(ref.type == "product" for _, ref, _ in world.sources)
    world.g0 = [(world.decision, world.submission)]
    world.submission.document_digest = "0" * 64
    result = matrix.read(world.session, world.ctx)
    assert result["groups"] == []
    assert "g0_price_source_unavailable" in result["unplaced"][0]["reasons"]


def test_g0_source_currently_denied_keeps_price_unknown_and_redacts_source_body(world):
    world.deny_sources.add(world.ref["id"])
    result = matrix.read(world.session, world.ctx)
    price = result["unplaced"][0]["price"]
    assert price["amount"] is None
    assert "source_unavailable" in price["reasons"]
    assert price["source_refs"] == [{**world.ref, "status": "unavailable"}]
    assert result["groups"] == []


@pytest.mark.parametrize("status", [None, "withdrawn"])
def test_fixed_segment_missing_or_withdrawn_is_unplaced_not_current_renamed(world, status):
    world.fixed = [(world.entry, status)]
    result = matrix.read(world.session, world.ctx)
    assert result["groups"] == []
    fixed = result["unplaced"][0]["fixed_segment"]
    assert fixed["version"] == 1
    assert ("segment_unavailable" if status is None else "segment_withdrawn") in fixed["reasons"]
    assert fixed["label"] is None if status is None else fixed["label"] == "Original pinned name"
    if status is None:
        assert fixed["source_refs"] == [] and fixed["entry_id"] is None


def test_missing_fixed_entry_exposes_only_known_target_link_not_unreadable_label(world):
    world.fixed = []
    result = matrix.read(world.session, world.ctx)
    fixed = result["unplaced"][0]["fixed_segment"]
    assert fixed["label"] is None and fixed["entry_id"] is None
    assert fixed["reasons"] == ["segment_unavailable"]


def test_hidden_or_denied_products_never_enter_labels_coverage_or_source_queries(world):
    hidden = NS(**{**vars(world.product), "id": uuid4(), "name": "Hidden product name"})
    world.products.append(hidden)
    world.denied.add(hidden.id)
    result = matrix.read(world.session, world.ctx)
    assert result["coverage"]["visible_products"] == 1
    assert "Hidden product name" not in str(result)
    for query in world.queries[1:]:
        values = query.compile().params.values()
        assert all(hidden.id not in value for value in values if isinstance(value, (list, set)))


def test_read_queries_are_only_scoped_selects_with_private_proposal_guard(world):
    matrix.read(world.session, world.ctx)
    sql = [str(query) for query in world.queries]
    assert all(query.is_select for query in world.queries)
    assert all("tenant_id" in query and "category_id" in query for query in sql)
    assert any("JOIN proposals" in query and "created_variant_id IS NULL" in query for query in sql)
    fixed = next(query for query in sql if "category_knowledge_entries" in query)
    assert "category_knowledge_entries.version" in fixed
    assert "category_knowledge_current.current_entry_id =" not in fixed
    assert all("count(" not in query.lower() and "FOR UPDATE" not in query for query in sql)


def test_competitor_read_preserves_prices_but_never_infers_segment_from_name(world):
    world.competitors = [
        {
            "id": str(uuid4()),
            "version": 2,
            "lineage_id": str(uuid4()),
            "origin": "ai_draft",
            "source_refs": [world.ref],
            "content": {
                "brand": "Original pinned name",
                "model": "Looks like our segment",
                "prices": [
                    {
                        "amount": "120",
                        "currency": "CNY",
                        "observed_on": "2026-10-17",
                        "price_type": "retail",
                        "source_ref": world.ref,
                    }
                ],
            },
        }
    ]
    result = matrix.read(world.session, world.ctx)
    assert result["coverage"]["visible_competitors"] == 1
    row = next(item for item in result["unplaced"] if item["subject"]["type"] == "competitor")
    assert row["reasons"] == ["segment_missing"]
    assert row["price"]["amount"] == "120"
    assert row["subject"]["origin"] == "ai_draft"
    assert all(cell["competitors"] == [] for cell in placements(result))
