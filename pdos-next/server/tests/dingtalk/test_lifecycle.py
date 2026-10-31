"""Retention identities are complete fixed metadata; body/quotes never enter the edge array."""

from uuid import uuid4

import pytest
from pdos_next.dingtalk.lifecycle import capture, grouped
from pdos_next.dingtalk.projection import Answer, whole_answer
from pdos_next.errors import DomainError


def dependency(**changes):
    return {
        "source_type": "artifact",
        "source_id": str(uuid4()),
        "source_revision": 3,
        "content_hash": "a" * 64,
        "category_id": str(uuid4()),
        **changes,
    }


def test_complete_copied_answer_retains_uncited_dependencies_and_real_category_groups():
    cited, uncited = dependency(), dependency(source_type="build")
    answer = Answer(
        "actual answer",
        ({"citation_id": "cited"},),
        {
            "cited": {**cited, "body": "NOT_IN_EDGES"},
            "uncited": {**uncited, "quote": "NOT_IN_EDGES"},
            "duplicate": cited,
        },
        ("internal",),
    )
    values = capture(answer)
    assert len(values) == 2 and cited in values and uncited in values
    assert all(
        set(value) == {"source_type", "source_id", "source_revision", "content_hash", "category_id"}
        for value in values
    )
    groups = grouped(values)
    assert set(groups) == {cited["category_id"], uncited["category_id"]}
    assert "NOT_IN_EDGES" not in str(groups)


@pytest.mark.parametrize("reason", ["customer_derived", "dependency_unverified", "source_changed"])
def test_fact_free_link_retains_no_business_material_copy(reason):
    assert capture(Answer("local login link only", (), {}, ("internal",), reason)) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_revision", 0),
        ("source_revision", True),
        ("source_id", "not-a-uuid"),
        ("category_id", None),
        ("source_type", "arbitrary"),
        ("content_hash", "short"),
    ],
)
def test_incomplete_fixed_identity_cannot_be_saved_as_a_fact_copy(field, value):
    with pytest.raises(DomainError):
        capture(Answer("facts", (), {"actual": dependency(**{field: value})}, ("internal",)))


def test_empty_provenance_cannot_claim_to_be_a_copied_answer():
    with pytest.raises(DomainError):
        capture(Answer("facts", (), {}, ("internal",)))


def test_current_revision_never_replaces_old_answer_dependency_for_external_copy():
    value = whole_answer(
        output={"summary": "OLD FACTS", "result": {}},
        footprint={
            "fixed": {**dependency(), "customer_original": False, "_dingtalk_current": False}
        },
        run_categories=["internal"],
        customer_identities=(),
        tools=["model", "assistant.search"],
    )
    assert value.withheld_reason == "source_changed" and "OLD FACTS" not in value.body
    assert capture(value) == []


def test_delivery_receipt_keeps_metadata_only_even_if_adapter_returns_an_echo():
    from types import SimpleNamespace

    from pdos_next.dingtalk.runtime import ChannelService

    row = SimpleNamespace(payload_sha256="a" * 64, state="sending", error_code=None)
    ChannelService.accept_receipt(
        row,
        {
            "provider": "dingtalk",
            "message_id": "synthetic:receipt",
            "payload_sha256": "a" * 64,
            "raw_body": "DO_NOT_COPY",
            "headers": {"token": "NO"},
        },
    )
    assert row.state == "delivered"
    assert set(row.provider_receipt) == {"provider", "message_id", "payload_sha256"}
    assert "DO_NOT_COPY" not in str(row.provider_receipt)
