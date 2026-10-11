"""Actual strict client contracts only; no source/qualification/DB attestation."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from pdos_next.domain.capa_effectiveness import fact_commands as commands


def uid(name):
    return uuid5(NAMESPACE_URL, "pdos-wave18-pure:" + name)


def source(name="actual-report"):
    return {
        "id": str(uid(name)),
        "revision": 1,
        "kind": "artifact",
        "position": "line:2;quote_sha256:" + "a" * 64,
    }


def ref(name):
    return {"id": str(uid(name)), "revision": 1, "sha256": "b" * 64}


def observation_raw():
    return {
        "issue_id": str(uid("issue")),
        "expected_issue_revision": 6,
        "capa_id": str(uid("capa")),
        "rule": ref("rule"),
        "target_keys": ["fixed-target"],
        "observed_from": "2026-10-03T08:00:00.000001Z",
        "observed_until": "2026-10-03T09:00:00.123456Z",
        "at": {
            "occurred_at": "2026-10-03T09:00:00.123457Z",
            "original_timezone": "America/Los_Angeles",
            "source": source(),
        },
        "records": [
            {
                "target_key": "fixed-target",
                "occurred_at": "2026-10-03T09:00:00.123456Z",
                "original_timezone": "America/Los_Angeles",
                "sources": [source()],
                "raw_material": {"value": None, "reported": "literal original unknown"},
            }
        ],
        "coverage_sources": [source()],
        "sources": [source()],
        "reason": "Actual source record including an explicit missing value",
        "visibility": "category",
    }


def test_duplicate_original_record_cannot_hide_behind_raw_json_key_order():
    raw = observation_raw()
    duplicate = deepcopy(raw["records"][0])
    duplicate["raw_material"] = dict(reversed(tuple(duplicate["raw_material"].items())))
    raw["records"].append(duplicate)
    with pytest.raises(ValidationError):
        commands.ObservationPayload.model_validate(raw)


def review_raw():
    raw = observation_raw()
    return {
        **{
            k: raw[k]
            for k in (
                "issue_id",
                "expected_issue_revision",
                "capa_id",
                "sources",
                "reason",
                "visibility",
                "at",
            )
        },
        "candidate": ref("candidate"),
        "rule": ref("rule"),
        "observations": [ref("observation")],
        "pair_applicability": [
            {
                "mapping": {
                    "failure_id": "failure",
                    "run": {
                        "id": str(uid("new-fixed-run-version")),
                        "revision": 4,
                        "kind": "verification_run",
                        "key": None,
                    },
                    "sample_id": str(uid("sample")),
                    "sample_revision": 1,
                    "actual_configuration_id": str(uid("actual")),
                    "actual_configuration_revision": 1,
                    "item_id": "dimension",
                    "measurement_id": None,
                    "projection_id": None,
                    "applicability_sources": [],
                },
                "method": None,
                "criterion": None,
                "conclusion": "unknown",
                "reason": "Unknown remains explicitly unknown",
                "sources": [source()],
            }
        ],
        "action_fulfillment": [
            {
                "action_id": str(uid("action")),
                "conclusion": "unknown",
                "reason": "Actual owner must independently establish fulfillment",
                "sources": [source()],
            }
        ],
        "conclusion": "unknown",
    }


@pytest.mark.parametrize("kind,factory", [("observation", observation_raw), ("review", review_raw)])
@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "issuer",
        "nature",
        "owner_id",
        "authority_snapshot",
        "participants",
        "provenance",
        "applicable",
        "complete",
        "shared_proof_id",
        "source_basis",
        "created_at",
    ],
)
def test_clients_cannot_fill_server_fact_or_authority_fields(kind, factory, field):
    raw = factory()
    raw[field] = True
    with pytest.raises(ValidationError):
        commands.payload_for(kind, raw)


@pytest.mark.parametrize(
    "kind,factory,token",
    [
        ("observation", observation_raw, "confirmation_token"),
        ("review", review_raw, "approval_token"),
    ],
)
def test_actual_semantic_only_removes_corresponding_token_keeps_order_and_nulls(
    kind, factory, token
):
    raw = factory()
    payload = commands.payload_for(kind, raw)
    with_token = payload.model_copy(update={token: "actual-named-public-token-1234"})
    assert commands.semantic(payload) == commands.semantic(with_token)
    assert commands.semantic(payload)["visibility"] == "category"
    assert token not in commands.semantic(with_token)
    if kind == "observation":
        assert commands.semantic(payload)["records"][0]["raw_material"]["value"] is None
        assert commands.semantic(payload)["records"][0]["occurred_at"].endswith("123456Z")
    else:
        assert (
            commands.semantic(payload)["pair_applicability"][0]["mapping"]["measurement_id"] is None
        )
        assert commands.semantic(payload)["pair_applicability"][0]["method"] is None
    assert commands.payload_for(kind, commands.semantic(payload)) == payload


@pytest.mark.parametrize(
    "kind,factory,wrong_token",
    [
        ("observation", observation_raw, "approval_token"),
        ("review", review_raw, "confirmation_token"),
    ],
)
def test_tier_tokens_are_not_interchangeable(kind, factory, wrong_token):
    raw = factory()
    raw[wrong_token] = "some-real-looking-token-1234"
    with pytest.raises(ValidationError):
        commands.payload_for(kind, raw)


@pytest.mark.parametrize(
    "path", [("expected_issue_revision",), ("rule", "revision"), ("sources", 0, "revision")]
)
def test_true_is_never_an_integer_revision_even_in_constructed_children(path):
    raw = observation_raw()
    part = raw
    for key in path[:-1]:
        part = part[key]
    part[path[-1]] = True
    with pytest.raises(ValidationError):
        commands.payload_for("observation", raw)


@pytest.mark.parametrize("field", ["sources", "target_keys", "records", "coverage_sources"])
def test_duplicate_original_material_cannot_count_twice(field):
    raw = observation_raw()
    raw[field].append(deepcopy(raw[field][0]))
    with pytest.raises(ValidationError):
        commands.payload_for("observation", raw)


def test_naive_time_outside_interval_and_unproved_effective_time_rejected():
    for mutation in (
        lambda raw: raw.update(observed_from="2026-10-03T08:00:00"),
        lambda raw: raw["records"][0].update(occurred_at="2026-10-03T10:00:00Z"),
        lambda raw: raw["at"].update(effective_at="2026-10-03T10:00:00Z"),
        lambda raw: raw["records"][0].update(original_timezone="Unknown/Zone"),
    ):
        raw = observation_raw()
        mutation(raw)
        with pytest.raises(ValidationError):
            commands.payload_for("observation", raw)


def test_equivalent_event_offsets_keep_microseconds_and_original_iana():
    raw = observation_raw()
    raw["at"]["occurred_at"] = "2026-10-03T02:00:00.123457-07:00"
    payload = commands.payload_for("observation", raw)
    assert payload.at.occurred_at == datetime(2026, 10, 3, 9, 0, 0, 123457, tzinfo=UTC)
    assert payload.at.original_timezone == "America/Los_Angeles"
    assert (
        payload.observed_until
        < payload.at.occurred_at
        < payload.at.occurred_at + timedelta(microseconds=1)
    )


def test_review_refs_and_named_decisions_are_explicit_not_inferred_pass():
    raw = review_raw()
    raw["observations"].append(deepcopy(raw["observations"][0]))
    with pytest.raises(ValidationError):
        commands.payload_for("review", raw)
    raw = review_raw()
    raw["conclusion"] = "pass"
    with pytest.raises(ValidationError):
        commands.payload_for("review", raw)
