"""No-connect versioned retained boundaries, using the real complete-shape codec.

SQL/source/qualification/load/effect owners are explicit substitutes. A real
SQLAlchemy Session/UOW is used; no actual PG or professional qualification is
claimed by these cases.
"""

# ruff: noqa: F811 -- imported fixtures intentionally share their registration names

from copy import deepcopy
from datetime import timedelta

import pytest
from test_fingerprint_compatibility import materials  # noqa: F401 -- fixture dependency
from test_retained_fingerprint_compatibility import (
    denied,
    different_signer_and_maker,
    inspect,
    uid,
    work,  # noqa: F401 -- fixture registration
)

from pdos_next.domain.build_operational_facts.service import digest
from pdos_next.domain.test_resources import retained
from pdos_next.domain.test_resources import service as resources

VERSION = "test-resource-dependency-v2"


def prepare_v2(work, monkeypatch):
    binding = work.old["binding"]
    material = resources._scoped_fingerprint_material(
        work.s, work.ctx, work.pid, binding, work.fact, work.issuer, work.old
    )
    proof = resources._stored_fingerprint_v2(material)
    work.original.input_snapshot.update(
        resource_fingerprint_version=VERSION,
        resource_dependency_proof=deepcopy(proof),
        resource_facts_revision=proof["facts_revision"],
    )
    work.original.input_snapshot["reservation"]["facts_revision"] = proof["facts_revision"]
    work.existing.fingerprint_version = VERSION
    work.existing.dependency_proof = deepcopy(proof)
    work.existing.facts_revision = proof["facts_revision"]
    work.current_proof = deepcopy(proof)
    work.bundle.facts_revision = proof["facts_revision"]
    work.collector = None

    def load(*args, **kwargs):
        work.io.load += 1
        assert kwargs["_fingerprint_version"] == VERSION
        assert kwargs["write"] is False and kwargs["retained"] is True
        assert kwargs["at"] == work.original.created_at
        assert kwargs["own_intent"] == work.original.intent_digest
        assert kwargs["retained_authority"] == work.original.authority_snapshot
        assert kwargs["verified_actual_start"].occurred_at == binding.window.start
        work.collector = kwargs["_fingerprint_collector"]
        assert type(work.collector) is list and work.collector == []
        work.collector.append(deepcopy(work.current_proof))
        work.bundle.facts_revision = work.current_proof["facts_revision"]
        return work.bundle, None, work.request, None, None, None, work.existing

    monkeypatch.setattr(resources, "_load", load)
    monkeypatch.setattr(
        retained,
        "_legacy_revision",
        lambda *a, **k: pytest.fail("Explicit v2 must never use legacy recovery"),
    )
    return work


@pytest.fixture
def versioned(work, monkeypatch):
    return prepare_v2(work, monkeypatch)


def reseal(proof):
    proof["facts_revision"] = digest(
        {"schema_version": proof["schema_version"], "material": proof["material"]}
    )


def test_v2_matches_all_saved_owners_current_material_and_original_effects(versioned):
    saved = deepcopy(versioned.original.input_snapshot)
    stored = deepcopy(vars(versioned.existing))
    epochs = versioned.s.get_bind()._pdos_test_resource_issuer_epochs.copy()
    result = inspect(versioned)
    assert result["current"] is True and result["reason_codes"] == [], result
    assert result["facts_revision"] == saved["resource_facts_revision"]
    assert result["reservation"] == saved["reservation"]
    assert result["nature"] == "retained_execution_evidence_not_current_execution_permission"
    assert result["execution_window_elapsed"] is True
    assert versioned.io.load == versioned.io.effect == 1
    assert versioned.io.basis == versioned.io.authority == 2
    assert versioned.original.input_snapshot == saved
    assert vars(versioned.existing) == stored
    assert versioned.s.get_bind()._pdos_test_resource_issuer_epochs == epochs


def test_v2_unrelated_new_configuration_is_not_a_saved_dependency(versioned):
    saved = deepcopy(versioned.original.input_snapshot)
    resources.configure_local_synthetic(
        versioned.s.get_bind(),
        key="third-independent-scope",
        tenant_id=uid(200),
        product_id=uid(201),
        enabled=True,
        test_marker_verified=True,
    )
    result = inspect(versioned)
    assert result["current"] is True, result
    assert versioned.original.input_snapshot == saved
    assert set(saved["resource_dependency_proof"]["material"]["issuer_epochs"]) == {"old-key"}


@pytest.mark.parametrize("field", ["resource_fingerprint_version", "resource_dependency_proof"])
def test_v2_missing_either_saved_key_cannot_fall_back(versioned, field):
    del versioned.original.input_snapshot[field]
    denied(versioned, "INTEGRATION_REQUIRED")
    assert versioned.io.load == versioned.io.effect == 0


@pytest.mark.parametrize("version", [None, 2, "test-resource-dependency-v1", "unknown-v3"])
def test_explicit_unsupported_version_never_infers_a_schema_from_same_sha(versioned, version):
    versioned.original.input_snapshot["resource_fingerprint_version"] = version
    denied(versioned, "INTEGRATION_REQUIRED")
    assert versioned.io.load == versioned.io.effect == 0


@pytest.mark.parametrize("proof", [None, {}, [], True])
def test_v2_without_full_proof_never_uses_same_sha_as_permission(versioned, proof):
    versioned.original.input_snapshot["resource_dependency_proof"] = proof
    denied(versioned, "RESOURCE_FINGERPRINT_MATERIAL_INVALID")
    assert versioned.io.load == versioned.io.effect == 0


def test_missing_actual_codec_is_integration_gap_not_legacy_fallback(versioned, monkeypatch):
    monkeypatch.delattr(resources, "_verify_stored_fingerprint_v2")
    denied(versioned, "INTEGRATION_REQUIRED")
    assert versioned.io.load == versioned.io.effect == 0


@pytest.mark.parametrize("field", ["fingerprint_version", "dependency_proof"])
def test_actual_row_missing_version_or_proof_is_not_an_unversioned_record(versioned, field):
    setattr(versioned.existing, field, None)
    denied(versioned, "RETAINED_EXECUTION_CHANGED")


@pytest.mark.parametrize("version", [True, "unknown-v3", "test-resource-dependency-v1"])
def test_actual_row_version_must_equal_explicit_start_version(versioned, version):
    versioned.existing.fingerprint_version = version
    denied(versioned, "RETAINED_EXECUTION_CHANGED")


@pytest.mark.parametrize("owner", ["start", "result", "row"])
def test_v2_all_three_fingerprints_remain_identical(versioned, owner):
    if owner == "start":
        versioned.original.input_snapshot["resource_facts_revision"] = "d" * 64
    elif owner == "result":
        versioned.original.input_snapshot["reservation"]["facts_revision"] = "d" * 64
    else:
        versioned.existing.facts_revision = "d" * 64
    denied(versioned, "RETAINED_EXECUTION_CHANGED")


@pytest.mark.parametrize("owner", ["start", "row", "current"])
def test_individually_valid_resealed_other_material_is_still_not_the_original(versioned, owner):
    proof = {
        "start": versioned.original.input_snapshot["resource_dependency_proof"],
        "row": versioned.existing.dependency_proof,
        "current": versioned.current_proof,
    }[owner]
    proof["material"]["sample_epochs"][str(uid(7))] = 2
    reseal(proof)
    assert resources._verify_stored_fingerprint_v2(proof) == proof
    denied(versioned, "RETAINED_EXECUTION_CHANGED")


@pytest.mark.parametrize("owner", ["start", "row", "current"])
@pytest.mark.parametrize("change", ["authority", "source_basis", "schema", "missing_key"])
def test_self_hashed_incomplete_nested_material_is_not_a_saved_owner(versioned, owner, change):
    proof = {
        "start": versioned.original.input_snapshot["resource_dependency_proof"],
        "row": versioned.existing.dependency_proof,
        "current": versioned.current_proof,
    }[owner]
    if change == "authority":
        proof["material"]["authority"] = {}
    elif change == "source_basis":
        proof["material"]["source_basis"] = None
    elif change == "schema":
        proof["schema_version"] = "unknown-v3"
    else:
        del proof["material"]["proofs"]
    reseal(proof)
    denied(versioned, "RESOURCE_FINGERPRINT_MATERIAL_INVALID")


def test_unversioned_start_cannot_ignore_versioned_row_even_when_old_sha_matches(work):
    sha = digest(work.fresh)
    work.original.input_snapshot["resource_facts_revision"] = sha
    work.original.input_snapshot["reservation"]["facts_revision"] = sha
    work.existing.facts_revision = sha
    work.existing.fingerprint_version = VERSION
    work.existing.dependency_proof = {}
    denied(work, "RETAINED_EXECUTION_CHANGED")


@pytest.mark.parametrize("change", ["key", "version", "nature", "project"])
def test_all_resealed_copies_still_require_the_real_current_fixed_issuer(versioned, change):
    proof = deepcopy(versioned.current_proof)
    issuer = proof["material"]["issuer"]
    if change == "key":
        issuer["key"] = "forged-selected-key"
        proof["material"]["issuer_epochs"] = {issuer["key"]: issuer["epoch"]}
    elif change == "version":
        issuer["version"] = "different-v2"
    elif change == "nature":
        issuer["nature"] = "real"
    else:
        issuer["scope"]["project_id"] = None
    reseal(proof)
    assert resources._verify_stored_fingerprint_v2(proof) == proof
    versioned.current_proof = deepcopy(proof)
    versioned.existing.dependency_proof = deepcopy(proof)
    versioned.original.input_snapshot["resource_dependency_proof"] = deepcopy(proof)
    versioned.original.input_snapshot["resource_facts_revision"] = proof["facts_revision"]
    versioned.original.input_snapshot["reservation"]["facts_revision"] = proof["facts_revision"]
    versioned.existing.facts_revision = proof["facts_revision"]
    denied(versioned, "RETAINED_EXECUTION_CHANGED")


def test_v2_active_nested_savepoint_is_the_same_real_uow(versioned):
    nested = versioned.s.begin_nested()
    result = inspect(versioned)
    assert result["current"] is True, result
    assert versioned.s.get_nested_transaction() is nested and nested.is_active
    nested.rollback()


@pytest.mark.parametrize("owner", ["start", "row", "result", "collector"])
def test_saved_or_current_owner_mutation_during_final_caller_io_is_rejected(versioned, owner):
    def change(person_id, read_count):
        if person_id != versioned.ctx.actor_id or read_count != 2:
            return
        if owner == "start":
            versioned.original.input_snapshot["resource_dependency_proof"] = None
        elif owner == "row":
            versioned.existing.dependency_proof = None
        elif owner == "result":
            versioned.original.input_snapshot["reservation"]["occupancy_ids"][0] = str(uid(999))
        else:
            versioned.collector.append(deepcopy(versioned.current_proof))

    versioned.query_hooks.append(change)
    result = inspect(versioned)
    assert result["current"] is False and result["reason_codes"], result


@pytest.mark.parametrize("change", ["caller_epoch", "issuer_epoch", "authority", "source", "uow"])
def test_v2_retains_current_owner_source_and_uow_guards(versioned, change, monkeypatch):
    def hook(round):
        if round != 2:
            return
        if change == "caller_epoch":
            versioned.person.access_epoch += 1
        elif change == "issuer_epoch":
            versioned.s.get_bind()._pdos_test_resource_issuer_epochs[versioned.issuer.key] += 1
        elif change == "authority":
            versioned.historical["current"] = False
        elif change == "source":
            monkeypatch.setattr(retained.physical, "_basis", lambda *a: ({"changed": True}, False))
            versioned.s.get_bind()._pdos_security_runtime = object()
        else:
            versioned.s.rollback()
            versioned.s.begin()

    versioned.io.hook = hook
    result = inspect(versioned)
    assert result["current"] is False and result["reason_codes"], result


def test_v2_original_signer_member_deadline_is_independent_of_current_reader(work, monkeypatch):
    different_signer_and_maker(work)
    prepare_v2(work, monkeypatch)
    validate = retained._versioned_revision
    rounds = []

    def expire_old_member(*args):
        value = validate(*args)
        rounds.append(value)
        if len(rounds) == 2:
            work.clock.at = work.grants[uid(80)].expires_at
        return value

    monkeypatch.setattr(retained, "_versioned_revision", expire_old_member)
    assert inspect(work)["current"] is True
    assert work.clock.at < work.grants[uid(6)].expires_at


def test_v2_current_reader_deadline_checked_after_final_pure_integrity_validation(
    work, monkeypatch
):
    different_signer_and_maker(work)
    work.grants[uid(80)].expires_at = work.clock.at + timedelta(hours=3)
    work.grants[uid(6)].expires_at = work.clock.at + timedelta(seconds=1)
    prepare_v2(work, monkeypatch)
    validate = retained._versioned_revision
    rounds = []

    def delay(*args):
        value = validate(*args)
        rounds.append(value)
        if len(rounds) == 2:
            work.clock.at = work.grants[uid(6)].expires_at
        return value

    monkeypatch.setattr(retained, "_versioned_revision", delay)
    denied(work, "FORBIDDEN_SCOPE")
    assert len(rounds) == 2
