"""Unregistered immutable body codec; actual saved atoms come from the host.

The body digest excludes only provenance and its own ref.sha256. Child refs,
original clocks and all material remain intact. This codec validates structure,
never the truth of a Receipt/UOW or any of facts.py's seven live owner gates.
"""

from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field, create_model

from .facts import (
    FactAtom,
    FactOperations,
    FactRef,
    NamedReview,
    ObservationVersion,
    RuleVersion,
    fact_payload_sha256,
    fact_sha256,
)
from .paired import Closed, FixedRef

SCHEMA_VERSION = "pdos-capa-fact-body-v1"
OPERATIONS = FactOperations(
    rule_import="quality.capa.verification.rule.import",
    rule_tier="host_import",
    rule_event="CapaVerificationRulePublished",
    rule_subject_type="capa_verification_rule",
    observation="quality.capa.observation.record",
    observation_tier="T1",
    observation_event="CapaObservationRecorded",
    observation_subject_type="capa_observation",
    review="quality.capa.verification.review",
    review_tier="T2",
    review_event="CapaVerificationReviewed",
    review_subject_type="capa_named_verification_review",
)

COMMON_FIELDS = (
    "ref",
    "previous",
    "scope",
    "issue_id",
    "capa_id",
    "purpose",
    "anchor_sha256",
    "requirement_sha256",
    "nature",
    "owner_id",
    "visibility",
    "created_at",
    "sources",
    "required_source_read_set",
    "source_basis",
    "kind",
)
BODY_FIELDS = {
    "rule": COMMON_FIELDS
    + (
        "issuer",
        "policy_ref",
        "policy_sha256",
        "failures",
        "actions",
        "method",
        "criterion",
        "sampling",
        "rule_material",
        "independence_material",
        "valid_from",
        "valid_until",
    ),
    "observation": COMMON_FIELDS
    + (
        "rule",
        "issuer",
        "targets",
        "executor_id",
        "observed_from",
        "observed_until",
        "at",
        "records",
        "coverage_sources",
        "sampling_material",
    ),
    "review": COMMON_FIELDS
    + (
        "candidate",
        "candidate_sha256",
        "rule",
        "observations",
        "reviewer_id",
        "at",
        "pair_applicability",
        "action_fulfillment",
        "participants",
        "participant_owner_material",
        "conclusion",
        "reason",
        "authority_snapshot",
        "policy_snapshot",
        "valid_until",
    ),
}
FACT_TYPES = {"rule": RuleVersion, "observation": ObservationVersion, "review": NamedReview}


class FactCodecError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _body_model(kind, name):
    """Reuse frozen field types; an added/removed fact field requires a new contract.

    Frozen cross-field/provenance validators run at assemble_fact, after the host
    supplies the actual atom. The body deliberately has no dummy provenance.
    """
    klass = FACT_TYPES[kind]
    names = BODY_FIELDS[kind]
    if set(klass.model_fields) != {*names, "provenance"}:
        raise FactCodecError("FACT_BODY_SCHEMA_REQUIRES_REVISION")
    fields = {}
    for field_name in names:
        info = deepcopy(klass.model_fields[field_name])
        annotation = FixedRef if field_name == "ref" else info.annotation
        info.annotation = annotation
        fields[field_name] = (annotation, info)
    return create_model(name, __base__=Closed, **fields)


RuleBody = _body_model("rule", "RuleBody")
ObservationBody = _body_model("observation", "ObservationBody")
NamedReviewBody = _body_model("review", "NamedReviewBody")


class FactBodyDocument(Closed):
    schema_version: Literal["pdos-capa-fact-body-v1"]
    body: Annotated[RuleBody | ObservationBody | NamedReviewBody, Field(discriminator="kind")]


def decode_fact_body(document) -> FactBodyDocument:
    """Accept this explicit envelope only; no full-fact or legacy fallback."""
    if isinstance(document, FactBodyDocument):
        document = document.model_dump(mode="json")
    if not isinstance(document, dict):
        raise FactCodecError("FACT_BODY_DOCUMENT_REQUIRED")
    return FactBodyDocument.model_validate(document)


def body_payload_sha256(document) -> str:
    return fact_payload_sha256(decode_fact_body(document).body.model_dump(mode="json"))


def _check_operation(atom, kind):
    stem = "rule" if kind == "rule" else kind
    operation = OPERATIONS.rule_import if kind == "rule" else getattr(OPERATIONS, stem)
    tier = "host_import" if kind == "rule" else "T1" if kind == "observation" else "T2"
    if (
        atom.operation != operation
        or atom.tier != tier
        or atom.receipt_subject_type != getattr(OPERATIONS, stem + "_subject_type")
        or atom.outbox.effect != getattr(OPERATIONS, stem + "_event")
    ):
        raise FactCodecError("FACT_ATOM_OPERATION_MISMATCH")


def assemble_fact(
    document,
    actual_atom: FactAtom,
    *,
    expected_payload_sha256: str,
    expected_ref: FactRef | None = None,
) -> RuleVersion | ObservationVersion | NamedReview:
    """Host-read atom + immutable body -> fully validated frozen fact.

    actual_atom must be supplied explicitly by an actual saved-group reader.
    Its Python type/digests are NOT a live owner attestation. Without those
    callbacks, no caller may turn this result into qualified/current evidence.
    """
    value = decode_fact_body(document)
    if not isinstance(actual_atom, FactAtom):
        raise FactCodecError("ACTUAL_TYPED_FACT_ATOM_REQUIRED")
    # Revalidate even a model_construct/model_copy input rather than trusting it.
    atom = FactAtom.model_validate(actual_atom.model_dump(mode="json"))
    _check_operation(atom, value.body.kind)
    actual_payload = body_payload_sha256(value)
    if actual_payload != expected_payload_sha256 or atom.payload_sha256 != actual_payload:
        raise FactCodecError("FACT_BODY_PAYLOAD_MISMATCH")
    raw = value.body.model_dump(mode="json")
    raw["provenance"] = atom.model_dump(mode="json")
    raw["ref"]["sha256"] = fact_sha256(raw)
    fact = FACT_TYPES[value.body.kind].model_validate(raw)
    if expected_ref is not None:
        if not isinstance(expected_ref, FactRef):
            raise FactCodecError("TYPED_FULL_FACT_REF_REQUIRED")
        expected = FactRef.model_validate(expected_ref.model_dump(mode="json"))
        if expected != fact.ref:
            raise FactCodecError("FACT_FULL_REF_MISMATCH")
    return fact


def encode_fact_body(fact) -> FactBodyDocument:
    """Encode a complete valid fact, without issuing any fact/proof/Receipt."""
    if type(fact) not in FACT_TYPES.values():
        raise FactCodecError("EXPLICIT_SAVED_FACT_REQUIRED")
    checked = type(fact).model_validate(fact.model_dump(mode="json"))
    _check_operation(checked.provenance, checked.kind)
    raw = checked.model_dump(mode="json")
    del raw["provenance"]
    del raw["ref"]["sha256"]
    document = decode_fact_body({"schema_version": SCHEMA_VERSION, "body": raw})
    if body_payload_sha256(document) != fact_payload_sha256(checked):
        raise FactCodecError("FACT_BODY_ENCODING_MISMATCH")
    return document
