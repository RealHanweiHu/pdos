"""Incomplete but self-hashed JSON is not the full actual producer contract."""

import builtins
import json
from copy import deepcopy
from uuid import UUID

import pytest

from pdos_next.domain.test_resources import fingerprint_compatibility as actual_dependency
from pdos_next.domain.test_resources import service as resources

from .harness import load, v2


def seal(module, record):
    record["facts_revision"] = module.digest(
        {"schema_version": record["schema_version"], "material": record["material"]}
    )
    return record


@pytest.mark.parametrize("case", ["empty_authority", "null_basis", "list_basis"])
def test_prior_self_consistent_but_incomplete_envelope_is_now_rejected(h, case):
    new = resources
    _, record = v2(h)
    if case == "empty_authority":
        record["material"]["authority"] = {}
    elif case == "null_basis":
        record["material"]["source_basis"] = None
    else:
        record["material"]["source_basis"] = []
    seal(new, record)
    with pytest.raises(new.DomainError) as error:
        new._verify_stored_fingerprint_v2(record)
    assert error.value.reason == "RESOURCE_FINGERPRINT_MATERIAL_INVALID"


@pytest.mark.parametrize(
    "case",
    [
        "authority_missing_scope",
        "authority_extra",
        "authority_wrong_subject",
        "authority_wrong_operation",
        "authority_wrong_purpose",
        "authority_bool_revision",
        "authority_partial_fact_ref",
        "authority_partial_read",
        "authority_duplicate_read",
        "authority_qualified_string",
        "authority_naive_deadline",
        "basis_extra",
        "basis_partial_access",
        "basis_bool_epoch",
        "basis_snapshot_default_omitted",
        "basis_security_default_omitted",
        "basis_fixed_security_partial",
        "basis_duplicate_snapshot",
        "basis_naive_capture",
        "sample_unknown_as_null",
        "sample_extra_identity",
        "sample_zero_epoch",
        "asset_zero_epoch",
        "proof_default_omitted",
        "proof_resource_wrong_asset",
        "proof_bool_current_as_string",
        "proof_partial_current",
        "check_default_omitted",
        "check_extra",
        "issuer_wrong_tenant",
        "issuer_wrong_product",
        "issuer_noncanonical_uuid",
        "binding_default_omitted",
        "binary_float",
    ],
)
def test_full_nested_shape_cannot_be_replaced_by_a_new_self_hash(h, case):
    new = resources
    _, record = v2(h)
    material = record["material"]
    authority = material["authority"]
    basis = material["source_basis"]
    if case == "authority_missing_scope":
        authority.pop("scope")
    elif case == "authority_extra":
        authority["claimed_current"] = True
    elif case == "authority_wrong_subject":
        authority["subject_id"] = str(UUID(int=601))
    elif case == "authority_wrong_operation":
        authority["operation"] = "test.run.review"
    elif case == "authority_wrong_purpose":
        authority["purpose"] += " altered"
    elif case == "authority_bool_revision":
        authority["fact_refs"][0]["revision"] = True
    elif case == "authority_partial_fact_ref":
        authority["fact_refs"][0].pop("issuer_version")
    elif case == "authority_partial_read":
        authority["required_source_read_set"] = [{"artifact_id": str(UUID(int=36))}]
    elif case == "authority_duplicate_read":
        authority["required_source_read_set"] = [
            {"artifact_id": str(UUID(int=36)), "expected_revision": 1}
        ] * 2
    elif case == "authority_qualified_string":
        authority["qualified"] = "unknown"
    elif case == "authority_naive_deadline":
        authority["valid_until"] = "2026-10-03T14:00:00"
    elif case == "basis_missing_access":
        basis.pop("access")
    elif case == "basis_extra":
        basis["claimed_safe"] = True
    elif case == "basis_partial_access":
        basis["access"].pop("grant_epoch")
    elif case == "basis_bool_epoch":
        basis["access"]["grant_epoch"] = True
    elif case == "basis_snapshot_default_omitted":
        basis["refs"][0].pop("valid_until")
    elif case == "basis_security_default_omitted":
        basis["security"][0].pop("disposition")
    elif case == "basis_fixed_security_partial":
        basis["fixed_readset_security"][0].pop("source_state")
    elif case == "basis_duplicate_snapshot":
        basis["refs"] *= 2
    elif case == "basis_naive_capture":
        basis["refs"][0]["captured_at"] = "2026-10-03T11:30:00"
    elif case == "sample_unknown_as_null":
        material["samples"][str(h.binding.pairs[0].sample.id)] = None
    elif case == "sample_extra_identity":
        material["samples"][str(UUID(int=602))] = "a" * 64
    elif case == "sample_zero_epoch":
        material["sample_epochs"][str(h.binding.pairs[0].sample.id)] = 0
    elif case == "asset_zero_epoch":
        material["assets"][0]["epoch"] = 0
    elif case == "proof_default_omitted":
        material["proofs"][0]["decision"].pop("valid_from")
    elif case == "proof_resource_wrong_asset":
        material["proofs"][0]["resource"]["id"] = str(UUID(int=603))
    elif case == "proof_bool_current_as_string":
        material["proofs"][0]["proof"] = {
            "current": "true",
            "facts_revision": "5" * 64,
            "valid_until": None,
        }
    elif case == "proof_partial_current":
        material["proofs"][0]["proof"] = {"current": False, "facts_revision": "5" * 64}
    elif case == "check_default_omitted":
        material["checks"][0].pop("source")
    elif case == "check_extra":
        material["checks"][0]["claimed_allowed"] = True
    elif case in {"issuer_wrong_tenant", "issuer_wrong_product"}:
        name = "tenant_id" if case.endswith("tenant") else "product_id"
        material["issuer"]["scope"][name] = str(UUID(int=604))
    elif case == "issuer_noncanonical_uuid":
        material["issuer"]["scope"]["product_id"] = UUID(int=42).hex
    elif case == "binding_default_omitted":
        material["binding"]["pairs"][0]["sample"].pop("cavity")
    else:
        material["checks"][0]["detail"] = 1.5
    seal(new, record)
    with pytest.raises(new.DomainError) as error:
        new._verify_stored_fingerprint_v2(record)
    assert error.value.reason == "RESOURCE_FINGERPRINT_MATERIAL_INVALID"


def test_exact_nullable_unknown_and_original_arrays_remain_unmodified(h):
    new = resources
    _, record = v2(h)
    material = record["material"]
    before = deepcopy(material)
    original_sha = new.digest(material)
    new._validate_fingerprint_v2_json(material)
    assert material == before and new.digest(material) == original_sha
    assert material["authority"]["qualified"] is None
    assert material["authority"]["reason_codes"] == ["QUALIFICATION_UNKNOWN"]
    assert material["source_basis"]["refs"][0]["state"] == "unknown"
    assert material["source_basis"]["security"][0]["security_epoch"] is None
    assert material["proofs"][0]["proof"] is None
    assert len(material["samples"][str(h.binding.pairs[0].sample.id)]) == 64
    assert new._verify_stored_fingerprint_v2(json.loads(json.dumps(record))) == record


def test_validator_only_receives_a_deep_validation_copy(monkeypatch, h):
    new = resources
    _, record = v2(h)
    before = deepcopy(record)
    dependency = actual_dependency
    actual = dependency.validate_material
    seen = []

    def inspect_copy(copy):
        seen.append(deepcopy(copy))
        result = actual(copy)
        copy["authority"]["reason_codes"].append("pure mutation isolation probe")
        copy["source_basis"]["access"]["grant_epoch"] += 1
        return result

    monkeypatch.setattr(dependency, "validate_material", inspect_copy)
    new._validate_fingerprint_v2_json(record["material"])
    assert record == before and len(seen) == 1
    issuer = record["material"]["issuer"]
    assert seen[0]["issuer"] == [issuer["key"], issuer["version"], issuer["epoch"], True]
    for key in set(new._FINGERPRINT_KEYS) - {"issuer"}:
        assert seen[0][key] == record["material"][key]


def test_missing_pure_validator_is_explicit_missing_and_default_v1_does_not_load_it(monkeypatch, h):
    new = resources
    actual_import = builtins.__import__

    def absent(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "fingerprint_compatibility" and level == 1:
            raise ImportError("Owned pure missing dependency probe")
        return actual_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", absent)
    original = []
    assert len(load(h, _fingerprint_collector=original)) == 7
    assert set(original[0]) == {"material", "facts_revision"}
    with pytest.raises(new.DomainError) as error:
        v2(h)
    assert error.value.reason == "INTEGRATION_REQUIRED" and error.value.status == 503


def test_current_provenance_is_complete_without_a_reader_acl_stamp(h):
    _, record = v2(h)
    record["material"]["source_basis"].pop("access")
    seal(resources, record)
    assert resources._verify_stored_fingerprint_v2(record) == record
