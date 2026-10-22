"""Owned synthetic codec/metadata checks: no DB, actual atoms or qualification."""

import json
from copy import deepcopy
from datetime import timedelta, timezone

import fact_storage_codec as codec
import fact_storage_models as storage
import facts
import pytest
from pdos_next.errors import DomainError
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from test_facts import material_fixture
from test_paired import uid


def sealed(value, **changes):
    """Synthetic structural atom only, never an actual saved host group."""
    raw = value.model_dump(mode="json")
    raw.update(changes)
    kind = raw["kind"]
    op = codec.OPERATIONS.rule_import if kind == "rule" else getattr(codec.OPERATIONS, kind)
    atom = raw["provenance"]
    atom["operation"] = atom["receipt_operation"] = atom["audit"]["operation"] = op
    atom["receipt_subject_type"] = getattr(codec.OPERATIONS, kind + "_subject_type")
    atom["outbox"]["effect"] = getattr(codec.OPERATIONS, kind + "_event")
    atom["payload_sha256"] = facts.fact_payload_sha256(raw)
    raw["ref"]["sha256"] = facts.fact_sha256(raw)
    return type(value).model_validate(raw)


@pytest.fixture
def saved_facts():
    material = material_fixture()
    rule = sealed(material.rule)
    observation = sealed(material.observations[0], rule=rule.ref.model_dump(mode="json"))
    review = sealed(
        material.review,
        rule=rule.ref.model_dump(mode="json"),
        observations=[observation.ref.model_dump(mode="json")],
    )
    return {"rule": rule, "observation": observation, "review": review}


@pytest.mark.parametrize("kind", ["rule", "observation", "review"])
def test_json_roundtrip_retains_complete_body_and_exact_full_ref(saved_facts, kind):
    fact = saved_facts[kind]
    document = codec.encode_fact_body(fact)
    stored = json.loads(document.model_dump_json())
    expected = fact.model_dump(mode="json")
    del expected["provenance"]
    del expected["ref"]["sha256"]
    assert stored == {"schema_version": codec.SCHEMA_VERSION, "body": expected}
    assert codec.body_payload_sha256(stored) == facts.fact_payload_sha256(fact)
    restored = codec.assemble_fact(
        stored,
        fact.provenance,
        expected_payload_sha256=facts.fact_payload_sha256(fact),
        expected_ref=fact.ref,
    )
    assert restored == fact
    assert restored.ref.sha256 != codec.body_payload_sha256(stored)


def test_child_refs_and_nested_provenance_keys_are_preserved(saved_facts):
    value = saved_facts["review"]
    participant = dict(value.participant_owner_material)
    participant["provenance"] = {"sha256": "f" * 64, "fixed_original_owner": "kept"}
    value = sealed(value, participant_owner_material=participant)
    document = codec.encode_fact_body(value)
    body = document.body.model_dump(mode="json")
    assert body["rule"] == value.rule.model_dump(mode="json")
    assert body["observations"] == [o.model_dump(mode="json") for o in value.observations]
    assert body["candidate"] == value.candidate.model_dump(mode="json")
    assert body["participant_owner_material"]["provenance"] == participant["provenance"]
    assert body["pair_applicability"] == [
        v.model_dump(mode="json") for v in value.pair_applicability
    ]


def test_actual_event_microseconds_instant_and_original_iana_survive_storage(saved_facts):
    original = saved_facts["observation"]
    raw = original.model_dump(mode="json")
    event = raw["at"]
    instant = original.at.occurred_at.replace(microsecond=123456)
    event["occurred_at"] = instant.astimezone(timezone(timedelta(hours=-7))).isoformat()
    event["original_timezone"] = "America/Los_Angeles"
    raw["records"][0]["occurred_at"] = (
        original.records[0].occurred_at.replace(microsecond=654321).isoformat()
    )
    # Normalize via the real EventTime schema before sealing synthetic hashes.
    # Hashing the pre-normalization offset spelling is not a saved DTO digest.
    event = facts.EventTime.model_validate(event).model_dump(mode="json")
    records = [
        facts.ObservationRecord.model_validate(r).model_dump(mode="json") for r in raw["records"]
    ]
    value = sealed(original, at=event, records=records)
    document = codec.encode_fact_body(value)
    restored = codec.assemble_fact(
        json.loads(document.model_dump_json()),
        value.provenance,
        expected_payload_sha256=codec.body_payload_sha256(document),
        expected_ref=value.ref,
    )
    assert restored.at.occurred_at == instant
    assert restored.at.occurred_at.microsecond == 123456
    assert restored.at.original_timezone == "America/Los_Angeles"
    assert restored.records[0].occurred_at.microsecond == 654321
    assert restored.records[0].original_timezone == original.records[0].original_timezone


def test_wrong_full_sha_cannot_be_replaced_by_body_payload_sha(saved_facts):
    value = saved_facts["review"]
    document = codec.encode_fact_body(value)
    payload = codec.body_payload_sha256(document)
    for sha in ("f" * 64, payload):
        expected = facts.FactRef(id=value.ref.id, revision=value.ref.revision, sha256=sha)
        with pytest.raises(codec.FactCodecError, match="FACT_FULL_REF_MISMATCH"):
            codec.assemble_fact(
                document, value.provenance, expected_payload_sha256=payload, expected_ref=expected
            )


def test_actual_group_change_changes_full_ref_but_not_body_digest(saved_facts):
    value = saved_facts["rule"]
    document = codec.encode_fact_body(value)
    raw = value.provenance.model_dump(mode="json")
    raw["audit"]["id"] = str(uid("different actual audit row"))
    atom = facts.FactAtom.model_validate(raw)
    actual = codec.assemble_fact(
        document, atom, expected_payload_sha256=codec.body_payload_sha256(document)
    )
    assert codec.body_payload_sha256(document) == facts.fact_payload_sha256(actual)
    assert actual.ref.sha256 != value.ref.sha256
    with pytest.raises(codec.FactCodecError, match="FACT_FULL_REF_MISMATCH"):
        codec.assemble_fact(
            document,
            atom,
            expected_payload_sha256=codec.body_payload_sha256(document),
            expected_ref=value.ref,
        )


@pytest.mark.parametrize(
    "field", ["scope", "fact", "received_at", "payload_sha256", "read_set_sha256"]
)
def test_wrong_actual_atom_is_rejected(saved_facts, field):
    value = saved_facts["observation"]
    changes = {
        "scope": value.scope.model_copy(update={"product_id": uid("another product")}),
        "fact": facts.FixedRef(id=uid("another fact"), revision=1),
        "received_at": value.created_at + timedelta(seconds=1),
        "payload_sha256": "f" * 64,
        "read_set_sha256": "f" * 64,
    }
    # Bypass the DTO constructor deliberately: the codec must revalidate it.
    atom = value.provenance.model_copy(update={field: changes[field]})
    with pytest.raises((ValidationError, codec.FactCodecError)):
        codec.assemble_fact(
            codec.encode_fact_body(value),
            atom,
            expected_payload_sha256=facts.fact_payload_sha256(value),
        )


@pytest.mark.parametrize("field", ["operation", "receipt_subject_type", "outbox"])
def test_saved_group_must_bind_frozen_operation_subject_and_event(saved_facts, field):
    value = saved_facts["review"]
    atom = value.provenance.model_dump(mode="json")
    if field == "operation":
        atom["operation"] = atom["receipt_operation"] = atom["audit"]["operation"] = "other.op"
    elif field == "outbox":
        atom["outbox"]["effect"] = "OtherEvent"
    else:
        atom["receipt_subject_type"] = "capa_observation"
    with pytest.raises(codec.FactCodecError, match="FACT_ATOM_OPERATION_MISMATCH"):
        codec.assemble_fact(
            codec.encode_fact_body(value),
            facts.FactAtom.model_validate(atom),
            expected_payload_sha256=facts.fact_payload_sha256(value),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_version",
        "unknown_version",
        "legacy_fact",
        "extra_envelope",
        "extra_body",
        "self_sha",
        "missing_material",
        "wrong_kind",
        "naive_event",
    ],
)
def test_only_explicit_closed_body_schema_is_accepted(saved_facts, mutation):
    value = saved_facts["observation"]
    document = codec.encode_fact_body(value).model_dump(mode="json")
    if mutation == "missing_version":
        del document["schema_version"]
    elif mutation == "unknown_version":
        document["schema_version"] = "pdos-capa-fact-body-v2"
    elif mutation == "legacy_fact":
        document = value.model_dump(mode="json")
    elif mutation == "extra_envelope":
        document["full_sha256"] = value.ref.sha256
    elif mutation == "extra_body":
        document["body"]["current"] = True
    elif mutation == "self_sha":
        document["body"]["ref"]["sha256"] = value.ref.sha256
    elif mutation == "missing_material":
        del document["body"]["sampling_material"]
    elif mutation == "wrong_kind":
        document["body"]["kind"] = "rule"
    else:
        document["body"]["at"]["occurred_at"] = "2026-10-03T00:00:00.123456"
    with pytest.raises(ValidationError):
        codec.decode_fact_body(document)


def test_no_dict_or_boolean_can_supply_an_actual_typed_atom(saved_facts):
    value = saved_facts["rule"]
    for atom in (value.provenance.model_dump(mode="json"), True, None):
        with pytest.raises(codec.FactCodecError, match="ACTUAL_TYPED_FACT_ATOM_REQUIRED"):
            codec.assemble_fact(
                codec.encode_fact_body(value),
                atom,
                expected_payload_sha256=facts.fact_payload_sha256(value),
            )


def test_body_tamper_cannot_reuse_actual_group_payload(saved_facts):
    value = saved_facts["review"]
    document = codec.encode_fact_body(value).model_dump(mode="json")
    document["body"]["action_fulfillment"][0]["owner_material"]["changed"] = True
    with pytest.raises(codec.FactCodecError, match="FACT_BODY_PAYLOAD_MISMATCH"):
        codec.assemble_fact(
            document, value.provenance, expected_payload_sha256=facts.fact_payload_sha256(value)
        )


def test_missing_source_closure_still_fails_frozen_final_validator(saved_facts):
    value = saved_facts["review"]
    document = codec.encode_fact_body(value).model_dump(mode="json")
    document["body"]["source_basis"] = document["body"]["source_basis"][:-1]
    digest = codec.body_payload_sha256(document)
    atom = value.provenance.model_copy(update={"payload_sha256": digest})
    with pytest.raises(DomainError, match="full exact read set") as error:
        codec.assemble_fact(document, atom, expected_payload_sha256=digest)
    assert error.value.code == "RECHECK_REQUIRED"


def fk_pairs(model):
    return [
        (tuple(e.parent.name for e in fk.elements), tuple(e.target_fullname for e in fk.elements))
        for fk in model.__table__.constraints
        if isinstance(fk, ForeignKeyConstraint)
    ]


@pytest.mark.parametrize("model", storage.STAGED_MODELS)
def test_declarations_compile_offline_and_require_full_original_issue_scope(model):
    table = model.__table__
    sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "CREATE TABLE" in sql
    assert (
        (
            "tenant_id",
            "product_id",
            "project_id",
            "issue_id",
            "origin_issue_version_id",
            "origin_issue_revision",
        ),
        tuple(
            f"quality_issue_versions.{c}"
            for c in ("tenant_id", "product_id", "project_id", "issue_id", "id", "revision")
        ),
    ) in fk_pairs(model)
    assert all(not table.c[name].nullable for name in storage.BINDING)
    # This is DDL compilation only; no CREATE/connection or live enforcement claim.


@pytest.mark.parametrize(
    "model,parent",
    [
        (storage.RuleCurrent, storage.RuleFact),
        (storage.ObservationCurrent, storage.ObservationFact),
    ],
)
def test_pointer_fk_cannot_drop_scope_series_or_owner_binding(model, parent):
    columns = storage.BINDING + ("series_id", "fact_id", "fact_revision")
    targets = storage.BINDING + ("series_id", "id", "revision")
    assert (columns, tuple(f"{parent.__tablename__}.{c}" for c in targets)) in fk_pairs(model)
    assert all(not model.__table__.c[c].nullable for c in columns)


def test_previous_and_candidate_fks_bind_actual_parent_scope_not_uuid_alone():
    previous = storage.BINDING + ("series_id", "previous_fact_id", "previous_revision")
    for model in (storage.RuleFact, storage.ObservationFact):
        targets = storage.BINDING + ("series_id", "id", "revision")
        assert (previous, tuple(f"{model.__tablename__}.{c}" for c in targets)) in fk_pairs(model)
    assert (
        storage.SCOPE + ("candidate_id",),
        tuple(f"capa_verification_evidence.{c}" for c in storage.SCOPE + ("id",)),
    ) in fk_pairs(storage.NamedReviewRecord)


def test_null_rejection_and_receipt_result_do_not_store_future_full_proof(saved_facts):
    for model in (storage.RuleFact, storage.ObservationFact, storage.NamedReviewRecord):
        checks = " ".join(
            str(c.sqltext) for c in model.__table__.constraints if isinstance(c, CheckConstraint)
        )
        assert "COALESCE" in checks and "false)" in checks
        assert "shared_proof_revision" in checks and "proof_consumed_at" in checks
        assert "receipt_id" not in model.__table__.c
        assert "transaction_proof_sha256" not in model.__table__.c
        row = model(
            fact_kind=saved_facts[
                {
                    storage.RuleFact: "rule",
                    storage.ObservationFact: "observation",
                    storage.NamedReviewRecord: "review",
                }[model]
            ].kind,
            payload_sha256="a" * 64,
        )
        assert row.action_result == {"fact_kind": row.fact_kind, "payload_sha256": "a" * 64}
        assert "sha256" not in row.action_result


def test_codec_does_not_make_saved_structure_a_live_owner_attestation(saved_facts):
    value = saved_facts["review"]
    assembled = codec.assemble_fact(
        codec.encode_fact_body(value),
        value.provenance,
        expected_payload_sha256=facts.fact_payload_sha256(value),
    )
    outcome = facts.load_verification_facts(None, None, value.scope.product_id, assembled.ref)
    assert outcome.structure is None
    assert [m.code for m in outcome.missing] == ["INTEGRATION_REQUIRED"]
    assert not hasattr(assembled, "current") and not hasattr(assembled, "qualified")


def test_encoding_does_not_mutate_a_saved_fact_or_accept_unvalidated_construct(saved_facts):
    value = saved_facts["rule"]
    before = deepcopy(value.model_dump(mode="json"))
    codec.encode_fact_body(value)
    assert value.model_dump(mode="json") == before
    corrupt = value.model_copy(update={"ref": value.ref.model_copy(update={"sha256": "f" * 64})})
    with pytest.raises(ValidationError):
        codec.encode_fact_body(corrupt)
