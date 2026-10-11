"""Pure view projections: no database, service process or model is used."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.domain.preproject import proposal_views as service
from pdos_next.errors import DomainError
from pdos_next.service import digest


def comparison():
    subject = {"type": "proposal", "id": str(uuid4())}
    reference = {"type": "snapshot", "id": str(uuid4()), "version": 2, "line": 7}
    price = {
        "amount": "100",
        "currency": "CNY",
        "basis": "retail",
        "as_of": "2026-10-11",
        "includes_tax": True,
        "includes_shipping": False,
        "channel": "shop",
        "region": "CN",
        "availability": "known",
        "reasons": [],
        "source_refs": [reference],
    }
    observation = {
        "subject": subject,
        "observation_id": str(uuid4()),
        "value": "20",
        "lower": None,
        "upper": None,
        "value_type": "number",
        "availability": "known",
        "comparable": True,
        "reasons": [],
        "evidence_kind": "observed",
        "source_refs": [reference],
    }
    group = {
        "parameter_id": str(uuid4()),
        "parameter_version": 2,
        "parameter": {"key": "pressure", "name": "Pressure", "value_type": "number"},
        "unit": "kPa",
        "condition_note": "23 C",
        "test_conditions": [{"load": "nominal"}],
        "observations": [observation],
    }
    return {
        "subjects": [{**subject, "label": "Synthetic target", "prices": [price]}],
        "groups": [group],
        "unmapped": [],
        "unavailable": [],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parameter_id", "other-parameter"),
        ("parameter_version", 3),
        ("unit", "bar"),
        ("condition_note", "40 C"),
        ("test_conditions", [{"load": "peak"}]),
    ],
)
def test_parameter_version_unit_and_test_conditions_keep_separate_facets(field, value):
    data = comparison()
    other = deepcopy(data["groups"][0])
    other[field] = value
    data["groups"].append(other)
    result = service.positioning(data)
    assert len(result["groups"]) == 2
    assert len({group["key"] for group in result["groups"]}) == 2
    assert [group["sample_count"] for group in result["groups"]] == [1, 1]
    assert result["groups"][1][field] == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("currency", "USD"),
        ("basis", "promo"),
        ("as_of", "2026-10-10"),
        ("includes_tax", False),
        ("includes_tax", None),
        ("includes_shipping", True),
        ("includes_shipping", None),
        ("channel", "online"),
        ("region", "US"),
    ],
)
def test_every_price_context_dimension_separates_facets(field, value):
    data = comparison()
    other = deepcopy(data["subjects"][0]["prices"][0])
    other[field] = value
    data["subjects"][0]["prices"].append(other)
    result = service.positioning(data)
    assert len(result["groups"]) == 2
    assert result["groups"][1]["price_context"][field] == value


def test_prices_are_individual_observations_and_never_averaged():
    data = comparison()
    price = data["subjects"][0]["prices"][0]
    data["subjects"][0]["prices"].append({**price, "amount": "150.123456789012"})
    original = deepcopy(data)
    result = service.positioning(data)
    assert len(result["groups"]) == 1
    assert result["groups"][0]["sample_count"] == 2
    points = result["groups"][0]["points"]
    assert [point["x"] for point in points] == ["100", "150.123456789012"]
    assert [point["price_index"] for point in points] == [0, 1]
    assert data == original


def test_zero_is_a_valid_price_and_parameter_coordinate():
    data = comparison()
    data["subjects"][0]["prices"][0]["amount"] = "0"
    data["groups"][0]["observations"][0]["value"] = "0"
    result = service.positioning(data)
    assert result["unknown_count"] == 0
    assert result["groups"][0]["points"][0]["x"] == "0"
    assert result["groups"][0]["points"][0]["y"] == "0"


@pytest.mark.parametrize("value", [None, True, False, "NaN", "Infinity", "", "not-number"])
def test_unknown_or_non_numeric_parameters_do_not_become_points(value):
    data = comparison()
    data["groups"][0]["observations"][0]["value"] = value
    result = service.positioning(data)
    assert result["groups"] == []
    assert result["unknown_count"] == 1
    assert "numeric_point_unavailable" in result["unknowns"][0]["reasons"]


def test_range_and_noncomparable_observations_have_no_invented_midpoint():
    data = comparison()
    observation = data["groups"][0]["observations"][0]
    observation.update(value=None, value_type="range", lower="10", upper="30")
    data["groups"][0]["observations"].append(
        {
            **observation,
            "observation_id": "conflicted",
            "value": "20",
            "comparable": False,
            "availability": "conflicted",
            "reasons": ["conflicted", "source_unavailable"],
        }
    )
    result = service.positioning(data)
    assert result["groups"] == []
    assert result["unknown_count"] == 2
    assert result["unknowns"][1]["reasons"] == ["conflicted", "source_unavailable"]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"amount": None}, "price_amount_unknown"),
        ({"amount": True}, "price_amount_unknown"),
        ({"currency": None}, "price_currency_unknown"),
        ({"basis": "unknown"}, "price_basis_unknown"),
        ({"as_of": None}, "price_date_unknown"),
        ({"availability": "unknown"}, "price_unavailable"),
    ],
)
def test_incomplete_or_unknown_prices_only_report_reasons(changes, reason):
    data = comparison()
    data["subjects"][0]["prices"][0].update(changes)
    result = service.positioning(data)
    assert result["groups"] == []
    assert reason in result["unknowns"][0]["reasons"]


def test_competitor_price_names_and_observation_nature_sources_are_preserved():
    data = comparison()
    price = data["subjects"][0]["prices"][0]
    price["price_type"] = price.pop("basis")
    price["observed_on"] = price.pop("as_of")
    observation = data["groups"][0]["observations"][0]
    observation["evidence_kind"] = "claimed"
    price["source_refs"] = [{"type": "claim", "id": str(uuid4()), "version": 4}]
    result = service.positioning(data)
    facet = result["groups"][0]
    assert facet["price_context"]["basis"] == "retail"
    assert facet["price_context"]["as_of"] == "2026-10-11"
    point = facet["points"][0]
    assert point["evidence_kind"] == "claimed"
    assert point["observation_id"] == observation["observation_id"]
    assert point["source_refs"] == [*observation["source_refs"], *price["source_refs"]]


@pytest.mark.parametrize(
    "nature", ["observed", "claimed", "inferred", "target", "computed", "other"]
)
def test_nature_is_not_reclassified_by_the_positioning_projection(nature):
    data = comparison()
    data["groups"][0]["observations"][0]["evidence_kind"] = nature
    assert service.positioning(data)["groups"][0]["points"][0]["evidence_kind"] == nature


def test_missing_price_unmapped_and_unavailable_subjects_stay_visible():
    data = comparison()
    data["subjects"][0]["prices"] = []
    data["unmapped"] = [{"observation_id": "free-key", "reasons": ["unmapped_parameter"]}]
    data["unavailable"] = [{"subject": {"id": "denied"}, "reasons": ["source_unavailable"]}]
    result = service.positioning(data)
    assert result["unknowns"][0]["reasons"] == ["price_missing"]
    assert result["unmapped"] == data["unmapped"]
    assert result["unavailable"] == data["unavailable"]


def test_price_with_missing_source_is_not_drawn_even_when_amount_is_known():
    data = comparison()
    # This is the actual _price shape when an amount has no source reference.
    data["subjects"][0]["prices"][0].update(
        availability="known", source_refs=[], reasons=["price_source_unavailable"]
    )
    result = service.positioning(data)
    assert result["groups"] == []
    assert result["unknowns"][0]["reasons"] == ["price_source_unavailable"]


@pytest.mark.parametrize("branch", ["numeric_unknown", "price_missing", "price_unavailable"])
def test_unknown_positioning_preserves_filtered_sources_without_reopening_them(monkeypatch, branch):
    from pdos_next.domain.preproject import spec_compare

    def forbidden(*args, **kwargs):
        pytest.fail("A projection must not reopen sources or the raw document")

    monkeypatch.setattr(spec_compare, "_sources", forbidden)
    monkeypatch.setattr(service.views, "document", forbidden)
    data = comparison()
    observation = data["groups"][0]["observations"][0]
    readable = {
        "type": "artifact",
        "id": str(uuid4()),
        "version": 3,
        "line": 9,
        "quote": "Already permitted synthetic quote",
    }
    redacted = {
        "type": "claim",
        "id": str(uuid4()),
        "version": 2,
        "status": "unavailable",
    }
    observation["source_refs"] = [readable, redacted]
    expected_refs = [readable, redacted]
    if branch == "numeric_unknown":
        observation.update(
            value=None, availability="unknown", comparable=False, reasons=["source_unavailable"]
        )
        expected_reason = "numeric_point_unavailable"
    elif branch == "price_missing":
        data["subjects"][0]["prices"] = []
        expected_reason = "price_missing"
    else:
        price_source = {**redacted, "id": str(uuid4()), "version": 5}
        data["subjects"][0]["prices"][0].update(
            amount=None,
            availability="unknown",
            reasons=["source_unavailable"],
            source_refs=[price_source],
        )
        expected_refs = [*expected_refs, price_source]
        expected_reason = "price_amount_unknown"
    original = deepcopy(data)

    result = service.positioning(data)

    assert data == original
    assert result["groups"] == [] and result["unknown_count"] == 1
    unknown = result["unknowns"][0]
    assert unknown["subject"] == observation["subject"]
    assert unknown["label"] == data["subjects"][0]["label"]
    assert unknown["observation_id"] == observation["observation_id"]
    assert expected_reason in unknown["reasons"]
    assert unknown["source_refs"] == expected_refs
    assert not {"x", "y", "value", "amount"} & unknown.keys()
    if branch == "price_unavailable":
        assert unknown["price_index"] == 0
    else:
        assert "price_index" not in unknown
    assert all(
        "quote" not in ref and "statement" not in ref
        for ref in unknown["source_refs"]
        if ref.get("status") == "unavailable"
    )


def spec(**changes):
    return {
        "item_id": str(uuid4()),
        "version": 1,
        "kind": "spec",
        "source_refs": [],
        "content": {
            "parameter": "Pressure",
            "value_type": "number",
            "value": "20",
            "unit": "kPa",
            "condition_note": "23 C",
            "item_status": "confirmed",
            "availability": "known",
            **changes,
        },
    }


def test_maturity_returns_exact_blockers_questions_counts_and_no_score():
    blocked = spec(
        item_status="expert_pending", availability="conflicted", unit=None, condition_note=None
    )
    unknown = spec(item_status="unknown", availability="unknown")
    boolean = spec(value_type="boolean", value=False, unit=None, condition_note=None)
    question = {
        "item_id": str(uuid4()),
        "version": 2,
        "kind": "question",
        "content": {
            "question": "Which condition?",
            "owner_id": str(uuid4()),
            "due_date": "2026-11-01",
            "status": "open",
        },
    }
    document = {
        "items": [
            blocked,
            unknown,
            boolean,
            question,
            {
                "kind": "section",
                "content": {"key": "worth_it", "text": "Actual rationale"},
            },
        ]
    }
    result = service.maturity(document)
    assert result["spec_count"] == 3
    assert result["option_count"] == 0
    assert result["questions"] == [question]
    assert [item["item_id"] for item in result["freeze_blockers"]] == [
        blocked["item_id"],
        unknown["item_id"],
    ]
    assert result["freeze_blockers"][0]["blocker_reasons"] == [
        "item_status_expert_pending",
        "availability_conflicted",
        "unit_missing",
        "condition_missing",
    ]
    assert result["freeze_blockers"][1]["blocker_reasons"] == [
        "item_status_unknown",
        "availability_unknown",
    ]
    assert result["item_status_counts"] == {"expert_pending": 1, "unknown": 1, "confirmed": 1}
    assert result["submission_checks"] == {
        "worth_it_present": True,
        "alternative_or_reason_required": True,
    }
    assert "score" not in result


def test_feature_projection_keeps_only_explicit_boolean_enum_mappings():
    data = comparison()
    original = data["groups"][0]
    data["groups"] = [
        {**original, "parameter": {"value_type": kind}}
        for kind in ["boolean", "enum", "text", "number", "range"]
    ]
    data["subjects"][0]["unmapped_features"] = [{"text": "Automatic pressure?"}]
    data["unmapped"] = [{"key": "free-key", "value": False}]
    result = service.feature_config(data)
    assert [group["parameter"]["value_type"] for group in result["groups"]] == ["boolean", "enum"]
    assert result["unmapped"] == data["unmapped"]
    assert result["subjects"][0]["unmapped_features"] == [{"text": "Automatic pressure?"}]


@pytest.mark.parametrize("count", [0, 9, 21])
def test_maturity_specification_count_is_guidance_not_a_new_gate(count):
    result = service.maturity({"items": [spec() for _ in range(count)]})
    assert result["spec_count"] == count
    assert result["freeze_blockers"] == []
    assert set(result["submission_checks"]) == {
        "worth_it_present",
        "alternative_or_reason_required",
    }


@pytest.fixture
def documents(monkeypatch):
    reviewer, owner = uuid4(), uuid4()
    doc = {
        "title": "Current",
        "brief": "Current brief",
        "entry_kind": "new",
        "target_kind": "product",
        "baseline_product_id": None,
        "baseline_definition_id": None,
        "baseline_definition_revision": None,
        "items": [spec()],
        "source_refs": [],
        "context_refs": [],
    }
    frozen = {**deepcopy(doc), "title": "Frozen", "items": [spec(availability="unknown")]}
    submission = {
        "id": str(uuid4()),
        "revision": 2,
        "reviewer_id": str(reviewer),
        "document_digest": digest(frozen),
        "frozen_document": frozen,
    }
    row = {
        **doc,
        "id": str(uuid4()),
        "owner_id": str(owner),
        "revision": 3,
        "status": "in_review",
        "submission": submission,
        "context_changes": [],
    }
    calls = []

    def read(session, ctx, identity):
        calls.append((session, ctx, identity))
        return row

    def raw(*args, **kwargs):
        raise AssertionError("Views must never re-read a raw document after redaction")

    monkeypatch.setattr(service.views, "read", read)
    monkeypatch.setattr(service.views, "document", raw)
    return SimpleNamespace(row=row, reviewer=reviewer, owner=owner, calls=calls)


@pytest.mark.parametrize("actor", ["reviewer", "owner"])
def test_document_identity_matches_the_actual_displayed_copy(documents, actor):
    ctx = SimpleNamespace(requester_id=getattr(documents, actor))
    result = service.read_document(object(), ctx, documents.row["id"])
    frozen = actor == "reviewer"
    expected_doc = (
        documents.row["submission"]["frozen_document"]
        if frozen
        else {key: documents.row[key] for key in service.DOCUMENT_KEYS}
    )
    assert result["display_document"] == expected_doc
    assert result["document_identity"] == {
        "proposal_id": documents.row["id"],
        "revision": 2 if frozen else 3,
        "document_digest": documents.row["submission"]["document_digest"]
        if frozen
        else digest(expected_doc),
        "submission_id": documents.row["submission"]["id"] if frozen else None,
        "document_mode": "frozen" if frozen else "current",
    }
    assert result["revision"] == 3  # Common commands still use the current proposal revision.
    assert len(documents.calls) == 1
    result["display_document"]["items"].clear()
    assert expected_doc["items"]  # Projection is detached from the authenticated reader's value.


def test_returned_submission_does_not_replace_current_document(documents):
    documents.row["status"] = "returned"
    result = service.read_document(
        object(), SimpleNamespace(requester_id=documents.reviewer), documents.row["id"]
    )
    assert result["document_identity"]["document_mode"] == "current"
    assert result["display_document"]["title"] == "Current"


def test_withdrawn_references_remain_redacted_without_reopening_raw_document(documents):
    redacted = {"type": "claim", "id": str(uuid4()), "version": 1, "status": "withdrawn"}
    frozen = documents.row["submission"]["frozen_document"]
    frozen["items"][0]["source_refs"] = [redacted]
    sealed_digest = documents.row["submission"]["document_digest"]
    result = service.read_document(
        object(), SimpleNamespace(requester_id=documents.reviewer), documents.row["id"]
    )
    assert result["display_document"]["items"][0]["source_refs"] == [redacted]
    assert result["document_identity"]["document_digest"] == sealed_digest
    assert "quote" not in result["display_document"]["items"][0]["source_refs"][0]
    assert len(documents.calls) == 1


def test_maturity_endpoint_preserves_frozen_identity_and_context_changes(documents):
    documents.row["context_changes"] = [{"type": "claim", "id": "withdrawn", "status": "withdrawn"}]
    result = service.read(
        object(),
        SimpleNamespace(requester_id=documents.reviewer),
        "definition-maturity",
        documents.row["id"],
    )
    assert result["document_mode"] == "frozen"
    assert result["revision"] == 2
    assert result["context_changes"] == documents.row["context_changes"]
    assert result["data"]["availability_counts"] == {"unknown": 1}
    identity = {
        key: result[key]
        for key in (
            "proposal_id",
            "revision",
            "document_digest",
            "submission_id",
            "document_mode",
        )
    }
    assert result["input_digest"] == digest([identity, result["data"]])


def test_unknown_view_does_not_read_any_document(monkeypatch):
    monkeypatch.setattr(service, "read_document", lambda *args: pytest.fail("Unexpected read"))
    with pytest.raises(DomainError) as caught:
        service.read(object(), object(), "unknown", uuid4())
    assert caught.value.code == "NOT_FOUND"


@pytest.mark.parametrize("name", ["spec-benchmark", "feature-config", "positioning"])
def test_comparison_view_keeps_actual_proposal_baseline_parameter_scope(
    documents, monkeypatch, name
):
    from pdos_next.domain.preproject import spec_compare

    product_id, competitor_id, parameter_id = uuid4(), uuid4(), uuid4()
    documents.row["submission"]["frozen_document"]["baseline_product_id"] = str(product_id)
    observed = []
    result_comparison = comparison()
    result_comparison["input_digest"] = "actual-comparison-input"

    class Session:
        def scalars(self, statement):
            observed.append(statement)
            return SimpleNamespace(all=lambda: [competitor_id])

    def compare(session, ctx, payload):
        assert isinstance(session, Session)
        observed.append(payload)
        return result_comparison

    monkeypatch.setattr(spec_compare, "compare", compare)
    ctx = SimpleNamespace(requester_id=documents.reviewer, tenant_id=uuid4(), category_id=uuid4())
    result = service.read(Session(), ctx, name, documents.row["id"], [parameter_id])
    payload = observed[-1]
    assert [(subject.type, str(subject.id)) for subject in payload.subjects] == [
        ("proposal", documents.row["id"]),
        ("product", str(product_id)),
        ("competitor", str(competitor_id)),
    ]
    assert payload.parameter_ids == [parameter_id]
    assert result["view"] == name
    assert result["document_mode"] == "frozen"
    assert result["revision"] == 2
    assert result["submission_id"] == documents.row["submission"]["id"]
    assert len(documents.calls) == 1
