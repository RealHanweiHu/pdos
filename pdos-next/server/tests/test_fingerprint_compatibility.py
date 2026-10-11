"""No-connect structural diagnostics; the issuer owner below is an explicit fake.

These cases do not validate live qualification, bytes, a configured Engine or UOW.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from pdos_next.domain.build_operational_facts.schemas import DecisionInput, DecisionProof
from pdos_next.domain.build_operational_facts.service import digest
from pdos_next.domain.test_resources.fingerprint_compatibility import (
    FixedIssuerDependency,
    diagnose_legacy_single_dependency,
    validate_material,
)
from pdos_next.domain.test_resources.schemas import TestPlanBinding as Binding
from pdos_next.errors import DomainError
from pdos_next.schemas.resource_readiness.contracts import Check


def uid(n):
    return UUID(int=n)


@pytest.fixture
def materials():
    reference = {
        "artifact_id": str(uid(30)),
        "expected_revision": 1,
        "line": 1,
        "quote": "原完整材料",
    }
    binding = Binding.model_validate(
        {
            "run_id": uid(1),
            "request_id": uid(2),
            "accepted_request_id": uid(3),
            "accepted_request_revision": 5,
            "build_id": uid(4),
            "project_id": uid(5),
            "purpose": "fixed-purpose",
            "executor_id": uid(6),
            "window": {
                "start": "2026-10-03T12:00:00.123456Z",
                "finish": "2026-10-03T13:00:00.123456Z",
                "original_timezone": "UTC",
            },
            "environment": "23 C, dry",
            "conditions": "controlled",
            "equipment": reference,
            "calibration": reference,
            "pairs": [
                {
                    "sample": {
                        "id": uid(7),
                        "revision": 1,
                        "build_id": uid(4),
                        "actual_configuration": {"id": uid(8), "revision": 2},
                    },
                    "item_id": "strength",
                    "method_id": uid(9),
                    "method_revision": 1,
                    "method_sha256": "1" * 64,
                    "destructive": False,
                }
            ],
        }
    )
    decision = DecisionInput.model_validate(
        {
            "kind": "calibration",
            "purpose": "fixed-purpose",
            "operation_id": "test.run.start",
            "status": "accepted",
            "valid_from": "2026-10-03T11:00:00Z",
            "valid_until": "2026-10-03T15:00:00Z",
            "named_decision_id": uid(12),
            "actor_id": uid(6),
            "sources": [reference],
        }
    )
    fixed = FixedIssuerDependency(
        tenant_id=uid(10),
        product_id=uid(11),
        project_id=uid(5),
        fact_id=uid(13),
        fact_revision=1,
        fact_sha256="2" * 64,
        current_epoch=1,
        issuer_key="old-key",
        issuer_version="v1",
        issuer_epoch=1,
        issuer_project_id=uid(5),
        nature="synthetic",
    )
    old = {
        "binding": binding,
        "fact": fixed.fact_sha256,
        "epoch": 1,
        "issuer": ["old-key", "v1", 1, True],
        "issuer_epochs": {"old-key": 1},
        "assets": [
            {"id": uid(14), "revision": 1, "sha256": "3" * 64, "epoch": 1},
            {"id": uid(6), "revision": 1, "sha256": "4" * 64, "epoch": 1},
        ],
        "sample_epochs": {str(uid(7)): 1},
        "samples": {str(uid(7)): "5" * 64},
        "authority": {
            "scope": {
                "tenant_id": str(uid(10)),
                "product_id": str(uid(11)),
                "project_id": str(uid(5)),
            },
            "subject_id": str(uid(6)),
            "operation": "test.run.start",
            "purpose": "fixed-purpose",
            "authorized": True,
            "roles": ["quality"],
            "qualified": True,
            "reason_codes": [],
            "fact_refs": [
                {
                    "id": str(uid(15)),
                    "revision": 1,
                    "epoch": 1,
                    "kind": "duty",
                    "role": "quality",
                    "nature": "synthetic",
                    "issuer_key": "professional",
                    "issuer_version": "v1",
                    "series_id": str(uid(15)),
                    "fact_sha256": "9" * 64,
                    "issuer_epoch": 1,
                    "state": "active",
                    "operations": ["test.run.start"],
                    "purposes": ["fixed-purpose"],
                    "valid_from": "2026-10-03T10:00:00Z",
                    "valid_until": "2026-10-03T15:00:00Z",
                },
                {
                    "id": str(uid(16)),
                    "revision": 1,
                    "epoch": 1,
                    "kind": "qualification",
                    "role": "quality",
                    "nature": "synthetic",
                    "issuer_key": "professional",
                    "issuer_version": "v1",
                    "series_id": str(uid(16)),
                    "fact_sha256": "9" * 64,
                    "issuer_epoch": 1,
                    "state": "active",
                    "operations": ["test.run.start"],
                    "purposes": ["fixed-purpose"],
                    "valid_from": "2026-10-03T10:00:00Z",
                    "valid_until": "2026-10-03T15:00:00Z",
                },
            ],
            "facts_revision": "6" * 64,
            "valid_until": "2026-10-03T15:00:00Z",
            "synthetic": True,
            "required_source_read_set": [{"artifact_id": str(uid(30)), "expected_revision": 1}],
        },
        "source_basis": {
            "refs": [
                {
                    "source_id": f"artifact:{uid(30)}",
                    "version": "1",
                    "sha256": "7" * 64,
                    "captured_at": "2026-10-03T10:00:00.123456Z",
                    "valid_until": "2026-10-03T16:00:00Z",
                    "state": "current",
                }
            ],
            "security": [
                {
                    "original_id": str(uid(31)),
                    "security_epoch": 1,
                    "source_state": "active",
                    "disposition": "retained",
                }
            ],
            "fixed_readset_security": [
                {
                    "artifact_id": str(uid(30)),
                    "original_id": str(uid(31)),
                    "epoch": 1,
                    "source_state": "active",
                    "disposition": "retained",
                }
            ],
            "access": {
                "principal_id": str(uid(6)),
                "principal_epoch": 1,
                "grant_id": str(uid(32)),
                "grant_epoch": 1,
            },
        },
        "proofs": [
            {
                "resource": {"id": str(uid(14)), "revision": 1, "kind": "equipment"},
                "decision": decision.model_dump(mode="json"),
                "proof": DecisionProof(
                    current=True,
                    facts_revision="8" * 64,
                    valid_until=datetime(2026, 10, 3, 15, tzinfo=UTC),
                ).model_dump(mode="json"),
            }
        ],
        "checks": [],
    }
    current = deepcopy(old)
    current["issuer_epochs"]["new-unrelated-key"] = 1
    return old, current, fixed


def compare(materials, *, current=None, fixed=None, owner=lambda _: None, old=None):
    previous, fresh, dependency = materials
    fresh = fresh if current is None else current
    previous = previous if old is None else old
    return diagnose_legacy_single_dependency(
        {"material": fresh, "facts_revision": digest(fresh)},
        fixed=dependency if fixed is None else fixed,
        original_saved_facts_revision=digest(previous),
        reservation_saved_facts_revision=digest(previous),
        original_reservation_facts_revision=digest(previous),
        verify_fixed_issuer=owner,
    )


def error_code(expected, call):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == expected
    return error.value


def test_actual_typed_digest_and_single_local_candidate_preserve_every_input(materials):
    old, current, fixed = materials
    before = deepcopy(current)
    calls = []
    result = compare(materials, owner=lambda dependency: calls.append(dependency))
    assert result.current_facts_revision == digest(current) != digest(old)
    assert result.candidate_facts_revision == digest(old) and result.candidate_matches_saved
    assert not result.current_matches_saved
    assert calls == [fixed, fixed]
    assert current == before and current["issuer_epochs"] == {"old-key": 1, "new-unrelated-key": 1}
    assert result.authorization_attested is False and result.retained_current_attested is False
    assert result.source_or_qualification_attested is False


@pytest.mark.parametrize(
    "field",
    [
        "binding",
        "fact",
        "epoch",
        "issuer",
        "issuer_epochs",
        "assets",
        "sample_epochs",
        "samples",
        "authority",
        "source_basis",
        "proofs",
        "checks",
    ],
)
def test_every_top_level_field_is_required_and_current_sha_cannot_attest_omissions(
    materials, field
):
    _, current, fixed = materials
    del current[field]
    error_code(
        "INVALID_RESOURCE_FINGERPRINT_MATERIAL",
        lambda: compare(materials, current=current, fixed=fixed),
    )


@pytest.mark.parametrize(
    "dimension",
    [
        "asset_epoch",
        "sample_epoch",
        "sample_proof",
        "authority_negative",
        "source_security",
        "source_access",
        "decision",
        "checks",
        "method",
        "window",
    ],
)
def test_every_other_real_dependency_remains_bound_by_full_saved_sha(materials, dimension):
    _, current, _ = materials
    if dimension == "asset_epoch":
        current["assets"][0]["epoch"] += 1
    elif dimension == "sample_epoch":
        current["sample_epochs"][str(uid(7))] += 1
    elif dimension == "sample_proof":
        current["samples"][str(uid(7))] = "a" * 64
    elif dimension == "authority_negative":
        current["authority"]["reason_codes"] = ["NEW_RELEVANT_NEGATIVE_FACT"]
        current["authority"]["facts_revision"] = "a" * 64
    elif dimension == "source_security":
        current["source_basis"]["security"][0]["security_epoch"] += 1
    elif dimension == "source_access":
        current["source_basis"]["access"]["grant_epoch"] += 1
    elif dimension == "decision":
        current["proofs"][0]["proof"]["current"] = False
    elif dimension == "checks":
        current["checks"].append(
            Check(
                code="sample_not_ready", status="BLOCKED", detail="Actual readiness changed"
            ).model_dump(mode="json")
        )
    else:
        data = current["binding"].model_dump(mode="python")
        if dimension == "method":
            data["pairs"][0]["method_sha256"] = "a" * 64
        else:
            data["window"]["finish"] = datetime(2026, 10, 3, 14, tzinfo=UTC)
        current["binding"] = Binding.model_validate(data)
    result = compare(materials)
    assert not result.candidate_matches_saved and not result.retained_current_attested


def test_multi_key_old_commitment_is_not_searched_or_recovered(materials):
    old, current, _ = materials
    old["issuer_epochs"]["another-old-dependency"] = 3
    current["issuer_epochs"]["another-old-dependency"] = 3
    calls = []
    result = compare(materials, owner=lambda value: calls.append(value))
    assert not result.candidate_matches_saved and result.registry_entries == 3
    assert len(calls) == 2  # One candidate; no subset or epoch trials.


def test_fixed_issuer_aba_matching_live_epoch_still_cannot_match_old_commitment(materials):
    _, current, fixed = materials
    current["issuer"][2] = current["issuer_epochs"]["old-key"] = 3
    result = compare(materials, fixed=replace(fixed, issuer_epoch=3))
    assert not result.candidate_matches_saved


def test_missing_true_owner_is_explicit_integration_required(materials):
    failure = error_code("INTEGRATION_REQUIRED", lambda: compare(materials, owner=None))
    assert failure.status == 503


def test_boolean_hash_or_client_stamp_is_not_owner_verification(materials):
    error_code(
        "INVALID_FIXED_ISSUER_OWNER_RESULT", lambda: compare(materials, owner=lambda _: True)
    )


def test_true_owner_original_rejection_is_not_swallowed(materials):
    def denied(_):
        raise DomainError("FORBIDDEN_SCOPE", "Actual owner refused", 403)

    error_code("FORBIDDEN_SCOPE", lambda: compare(materials, owner=denied))


def test_collector_sha_and_original_reservation_must_both_match(materials):
    old, current, fixed = materials
    error_code(
        "CURRENT_RESOURCE_FINGERPRINT_MISMATCH",
        lambda: diagnose_legacy_single_dependency(
            {"material": current, "facts_revision": "e" * 64},
            fixed=fixed,
            original_saved_facts_revision=digest(old),
            reservation_saved_facts_revision=digest(old),
            original_reservation_facts_revision=digest(old),
            verify_fixed_issuer=lambda _: None,
        ),
    )
    error_code(
        "ORIGINAL_RESOURCE_PROOF_MISMATCH",
        lambda: diagnose_legacy_single_dependency(
            {"material": current, "facts_revision": digest(current)},
            fixed=fixed,
            original_saved_facts_revision=digest(old),
            reservation_saved_facts_revision="e" * 64,
            original_reservation_facts_revision=digest(old),
            verify_fixed_issuer=lambda _: None,
        ),
    )


@pytest.mark.parametrize("value", [True, 1.0, 0, "1"])
def test_strict_revision_and_no_default_string_coercion(materials, value):
    _, current, _ = materials
    current["assets"][0]["epoch"] = value
    error_code("INVALID_RESOURCE_FINGERPRINT_MATERIAL", lambda: compare(materials))


@pytest.mark.parametrize(
    "dimension",
    ["extra", "nested_missing", "arbitrary_object", "naive_time", "wrong_scope", "foreign_sample"],
)
def test_closed_schema_does_not_accept_unchecked_material_or_scope(materials, dimension):
    _, current, fixed = materials
    if dimension == "extra":
        current["authorized"] = True
    elif dimension == "nested_missing":
        del current["proofs"][0]["decision"]["conditions"]
    elif dimension == "arbitrary_object":
        current["fact"] = object()
    elif dimension == "naive_time":
        current["source_basis"]["refs"][0]["captured_at"] = "2026-10-03T10:00:00"
    elif dimension == "foreign_sample":
        current["sample_epochs"][str(uid(99))] = 1
    else:
        fixed = replace(fixed, product_id=uid(99))
    expected = (
        "FIXED_ISSUER_DEPENDENCY_MISMATCH"
        if dimension == "wrong_scope"
        else "INVALID_RESOURCE_FINGERPRINT_MATERIAL"
    )
    error_code(expected, lambda: compare(materials, fixed=fixed))


def test_owner_io_drift_cannot_use_the_earlier_material(materials):
    old, current, fixed = materials
    collected = {"material": current, "facts_revision": digest(current)}

    def owner(_):
        current["source_basis"]["access"]["grant_epoch"] += 1

    error_code(
        "COLLECTED_RESOURCE_MATERIAL_CHANGED",
        lambda: diagnose_legacy_single_dependency(
            collected,
            fixed=fixed,
            original_saved_facts_revision=digest(old),
            reservation_saved_facts_revision=digest(old),
            original_reservation_facts_revision=digest(old),
            verify_fixed_issuer=owner,
        ),
    )


def test_saved_wire_times_and_nulls_are_not_resealed(materials):
    _, current, _ = materials
    before = deepcopy(current["source_basis"])
    validate_material(current)
    result = compare(materials)
    assert result.candidate_matches_saved
    assert current["source_basis"] == before
    assert current["source_basis"]["refs"][0]["captured_at"].endswith(".123456Z")
    assert current["proofs"][0]["decision"]["conditions"] == []


def test_original_result_fp_is_a_third_independent_exact_binding(materials):
    old, current, fixed = materials
    error_code(
        "ORIGINAL_RESOURCE_PROOF_MISMATCH",
        lambda: diagnose_legacy_single_dependency(
            {"material": current, "facts_revision": digest(current)},
            fixed=fixed,
            original_saved_facts_revision=digest(old),
            reservation_saved_facts_revision=digest(old),
            original_reservation_facts_revision="e" * 64,
            verify_fixed_issuer=lambda _: None,
        ),
    )


def test_fixed_epoch_map_must_match_the_actual_issuer_and_fact_epoch(materials):
    _, current, _ = materials
    current["issuer_epochs"]["old-key"] = 3
    error_code("INVALID_RESOURCE_FINGERPRINT_MATERIAL", lambda: compare(materials))


def test_final_owner_withdrawal_rejects_even_an_exact_candidate_hash(materials):
    calls = []

    def owner(_):
        calls.append(None)
        if len(calls) == 2:
            raise DomainError("SOURCE_STALE", "Actual final owner epoch changed")

    error_code("SOURCE_STALE", lambda: compare(materials, owner=owner))
