"""Owned, connection-prohibited protocol checks; SQL/qualification owners are substituted."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from pdos_next.domain.test_resources import fingerprint_compatibility as dependency
from pdos_next.domain.test_resources import service as resources

from .harness import load, v2


def owner(h, record, *, new_columns=True):
    value = SimpleNamespace(
        id=h.binding.run_id,
        intent_digest="a" * 64,
        binding=h.binding.model_dump(mode="json"),
        facts_revision=record["facts_revision"],
    )
    if new_columns:
        value.fingerprint_version = record["schema_version"]
        value.dependency_proof = deepcopy(record)
    return value


def own_current(h, record):
    h.existing = owner(h, record)
    for asset in h.assets.values():
        asset.occupancy_epoch += 1
    for sentinel in h.sentinels.values():
        sentinel.epoch += 1


@pytest.mark.parametrize("columns", [False, True])
def test_v1_owner_is_only_null_null_or_absent_for_existing_test_substitutes(h, columns):
    new = resources
    _, record = v2(h)
    saved = owner(h, record, new_columns=columns)
    if columns:
        saved.fingerprint_version = None
        saved.dependency_proof = None
    assert new._reservation_fingerprint(saved) == (new._FINGERPRINT_V1, None)


@pytest.mark.parametrize(
    "change",
    [
        "null-version",
        "v1-explicit",
        "garbage-version",
        "bool-version",
        "missing-proof",
        "extra-key",
        "bad-fp",
        "row-fp",
        "row-binding",
    ],
)
def test_actual_saved_version_and_full_record_are_required_without_inference(h, change):
    new = resources
    _, record = v2(h)
    saved = owner(h, record)
    if change == "null-version":
        saved.fingerprint_version = None
    elif change == "v1-explicit":
        saved.fingerprint_version = new._FINGERPRINT_V1
    elif change == "garbage-version":
        saved.fingerprint_version = "future"
    elif change == "bool-version":
        saved.fingerprint_version = True
    elif change == "missing-proof":
        saved.dependency_proof = None
    elif change == "extra-key":
        saved.dependency_proof["attested"] = True
    elif change == "bad-fp":
        saved.dependency_proof["facts_revision"] = "f" * 64
    elif change == "row-fp":
        saved.facts_revision = "f" * 64
    else:
        saved.binding["purpose"] = "different exact purpose"
    with pytest.raises(new.DomainError):
        new._reservation_fingerprint(saved)


def test_saved_v2_decoder_returns_complete_deep_copy_without_qualification(h):
    new = resources
    _, record = v2(h)
    saved = owner(h, record)
    before = deepcopy(record)
    version, decoded = new._reservation_fingerprint(saved)
    assert version == new._FINGERPRINT_V2 and decoded == record
    second_version, second = new._reservation_fingerprint(saved)
    assert second_version == version and second == before
    decoded["material"]["authority"]["qualified"] = True
    decoded["material"]["checks"][0]["detail"] = "Changed only in the first returned copy"
    decoded["material"]["source_basis"]["refs"][0]["state"] = "withdrawn"
    assert saved.dependency_proof == record == second == before
    assert saved.dependency_proof["material"]["authority"]["qualified"] is None
    second["material"]["source_basis"]["refs"][0]["sha256"] = "e" * 64
    assert (
        decoded["material"]["source_basis"]["refs"][0]["sha256"]
        == before["material"]["source_basis"]["refs"][0]["sha256"]
    )
    assert saved.dependency_proof == record == before
    assert new._reservation_fingerprint(saved) == (version, before)


def test_builtin_material_validation_keeps_all_nested_input_without_an_extra_clone(h, monkeypatch):
    _, record = v2(h)
    material = record["material"]
    before = deepcopy(material)
    before_sha = resources.digest(material)
    copies = []

    def observe_copy(value):
        copies.append(value)
        return deepcopy(value)

    assert dependency.validate_material is dependency._READ_ONLY_MATERIAL_VALIDATOR[0]
    assert dependency.validate_material.__code__ is dependency._READ_ONLY_MATERIAL_VALIDATOR[1]
    monkeypatch.setattr(resources, "deepcopy", observe_copy)
    resources._validate_fingerprint_v2_json(material)
    assert copies == []
    assert material == before and resources.digest(material) == before_sha
    assert material["authority"]["qualified"] is None
    assert material["source_basis"]["refs"][0]["state"] == "unknown"
    assert material["issuer"] == before["issuer"]


def test_same_validator_identity_with_changed_code_still_gets_deep_isolation(h, monkeypatch):
    _, record = v2(h)
    material = record["material"]
    before = deepcopy(material)
    actual = dependency.validate_material
    copies = []

    def changed_code(value):
        from types import FunctionType

        from pdos_next.domain.test_resources import fingerprint_compatibility as pure

        original, original_code = pure._READ_ONLY_MATERIAL_VALIDATOR
        result = FunctionType(original_code, original.__globals__)(value)
        value["authority"]["reason_codes"].append("changed-code isolation probe")
        value["source_basis"]["access"]["grant_epoch"] += 1
        return result

    def observe_copy(value):
        copy = deepcopy(value)
        copies.append(copy)
        return copy

    monkeypatch.setattr(actual, "__code__", changed_code.__code__)
    monkeypatch.setattr(resources, "deepcopy", observe_copy)
    assert actual is dependency._READ_ONLY_MATERIAL_VALIDATOR[0]
    assert actual.__code__ is not dependency._READ_ONLY_MATERIAL_VALIDATOR[1]
    resources._validate_fingerprint_v2_json(material)
    assert material == before and len(copies) == 1
    assert copies[0]["authority"]["reason_codes"][-1] == "changed-code isolation probe"
    assert copies[0]["source_basis"]["access"]["grant_epoch"] == (
        before["source_basis"]["access"]["grant_epoch"] + 1
    )


@pytest.mark.parametrize("case", ["partial-read", "tuple-assets", "non-json-check"])
def test_builtin_validation_preserves_deep_copy_path_errors_and_input(h, monkeypatch, case):
    _, record = v2(h)
    material = record["material"]
    if case == "partial-read":
        material["authority"]["required_source_read_set"] = [
            {"artifact_id": material["assets"][0]["id"]}
        ]
    elif case == "tuple-assets":
        material["assets"] = tuple(material["assets"])
    else:
        material["checks"][0]["detail"] = {"not a JSON value"}
    before = deepcopy(material)
    actual = dependency.validate_material

    def copied_port(value):
        return actual(value)

    with monkeypatch.context() as changed:
        changed.setattr(dependency, "validate_material", copied_port)
        with pytest.raises(TypeError) as copied_error:
            resources._validate_fingerprint_v2_json(material)
    with pytest.raises(TypeError) as builtin_error:
        resources._validate_fingerprint_v2_json(material)
    assert builtin_error.value.args == copied_error.value.args
    assert builtin_error.value.__cause__.reason == copied_error.value.__cause__.reason
    assert material == before


@pytest.mark.parametrize("retained", [False, True])
def test_actual_owned_v2_full_current_record_preserves_original_own_epoch_normalization(
    h, retained
):
    new = resources
    _, record = v2(h)
    own_current(h, record)
    sink = []
    loaded = load(
        h,
        _fingerprint_version=new._FINGERPRINT_V2,
        _fingerprint_collector=sink,
        own_intent=h.existing.intent_digest,
        retained=retained,
        retained_authority=h.authority if retained else None,
    )
    assert loaded[0].facts_revision == record["facts_revision"] and sink == [record]
    assert "complete-own-effects" in h.calls
    assert all(asset.occupancy_epoch == 6 for asset in h.assets.values())
    assert all(sentinel.epoch == 5 for sentinel in h.sentinels.values())
    assert loaded[0].report.status not in {"READY", "READY_WITH_CONDITIONS"}


@pytest.mark.parametrize(
    "change",
    [
        "no-owner",
        "no-intent",
        "wrong-intent",
        "v1-row",
        "corrupt-proof",
        "material-drift",
        "source-withdrawal",
        "runtime-drift",
    ],
)
def test_v2_retained_cannot_be_a_saved_record_or_qualification_bypass(h, change):
    new = resources
    _, record = v2(h)
    own_current(h, record)
    intent = h.existing.intent_digest
    if change == "no-owner":
        h.existing = None
    elif change == "no-intent":
        intent = None
    elif change == "wrong-intent":
        intent = "b" * 64
    elif change == "v1-row":
        h.existing.fingerprint_version = h.existing.dependency_proof = None
    elif change == "corrupt-proof":
        h.existing.dependency_proof["facts_revision"] = "d" * 64
    elif change == "material-drift":
        next(iter(h.assets.values())).data_sha256 = "e" * 64
    elif change == "source-withdrawal":
        h.source_failure = True
    else:
        h.after_hash = lambda: h.engine._pdos_test_resource_issuer_epochs.update(
            {"unrelated-other-scope": 100}
        )
    sink = []
    with pytest.raises(new.DomainError):
        load(
            h,
            _fingerprint_version=new._FINGERPRINT_V2,
            _fingerprint_collector=sink,
            own_intent=intent,
            retained=True,
            retained_authority=h.authority,
        )
    assert sink == []


def test_load_bundle_dispatches_default_own_version_from_actual_row_and_uses_private_sink(
    h, monkeypatch
):
    new = resources
    _, record = v2(h)
    own_current(h, record)
    actual = new._load
    seen = []

    def spy(*args, **kwargs):
        seen.append((kwargs["_fingerprint_version"], kwargs["_fingerprint_collector"]))
        return actual(*args, **kwargs)

    monkeypatch.setattr(new, "_load", spy)
    value = new.load_bundle(
        h.session,
        h.ctx,
        h.pid,
        h.binding,
        h.fact.id,
        h.fact.revision,
        at=h.at,
        own_intent=h.existing.intent_digest,
    )
    assert value.facts_revision == record["facts_revision"]
    assert seen == [(new._FINGERPRINT_V2, [record])]


def test_load_bundle_explicit_v2_cannot_reseal_a_real_legacy_row(h):
    new = resources
    _, record = v2(h)
    h.existing = owner(h, record, new_columns=False)
    sink = []
    with pytest.raises(new.DomainError) as error:
        new.load_bundle(
            h.session,
            h.ctx,
            h.pid,
            h.binding,
            h.fact.id,
            h.fact.revision,
            at=h.at,
            own_intent=h.existing.intent_digest,
            _fingerprint_version=new._FINGERPRINT_V2,
            _fingerprint_collector=sink,
        )
    assert error.value.reason == "RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED" and sink == []


@pytest.mark.parametrize("change", ["version", "proof", "intent"])
def test_saved_owner_is_rechecked_after_complete_current_material_io(h, change):
    new = resources
    _, record = v2(h)
    own_current(h, record)
    intent = h.existing.intent_digest
    if change == "version":
        h.after_hash = lambda: setattr(h.existing, "fingerprint_version", "future")
    elif change == "proof":
        h.after_hash = lambda: h.existing.dependency_proof.update({"facts_revision": "f" * 64})
    else:
        h.after_hash = lambda: setattr(h.existing, "intent_digest", "f" * 64)
    sink = []
    with pytest.raises(new.DomainError):
        load(
            h,
            _fingerprint_version=new._FINGERPRINT_V2,
            _fingerprint_collector=sink,
            own_intent=intent,
            retained=True,
            retained_authority=h.authority,
        )
    assert sink == []


@pytest.mark.parametrize("version", [resources._FINGERPRINT_V1, resources._FINGERPRINT_V2])
@pytest.mark.parametrize("write", [False, True])
def test_saved_reservation_rechecks_never_bootstrap_consuming_sentinels(
    h, monkeypatch, version, write
):
    _, record = v2(h)
    own_current(h, record)
    if version == resources._FINGERPRINT_V1:
        h.existing.fingerprint_version = h.existing.dependency_proof = None
    calls = []

    def existing_sentinels(*args, create, lock=False):
        calls.append(create)
        return h.sentinels

    monkeypatch.setattr(resources, "_sample_sentinels", existing_sentinels)
    before = {key: value.epoch for key, value in h.sentinels.items()}
    sink = [] if version == resources._FINGERPRINT_V2 else None
    result = load(
        h,
        write=write,
        own_intent=h.existing.intent_digest,
        _fingerprint_version=version,
        _fingerprint_collector=sink,
    )
    assert calls == [False]
    assert {key: value.epoch for key, value in h.sentinels.items()} == before
    assert "complete-own-effects" in h.calls
    assert result[0].report.status not in {"READY", "READY_WITH_CONDITIONS"}


@pytest.mark.parametrize("write", [False, True])
def test_only_a_new_reservation_write_may_bootstrap_sentinels(h, monkeypatch, write):
    calls = []

    def new_sentinels(*args, create, lock=False):
        calls.append(create)
        return h.sentinels

    monkeypatch.setattr(resources, "_sample_sentinels", new_sentinels)
    load(h, write=write)
    assert calls == [write]


@pytest.mark.parametrize("version", [resources._FINGERPRINT_V1, resources._FINGERPRINT_V2])
def test_missing_saved_sentinel_fails_without_recreating_original_effects(h, monkeypatch, version):
    _, record = v2(h)
    own_current(h, record)
    if version == resources._FINGERPRINT_V1:
        h.existing.fingerprint_version = h.existing.dependency_proof = None
    calls = []

    def missing_sentinels(*args, create, lock=False):
        calls.append(create)
        return {}

    monkeypatch.setattr(resources, "_sample_sentinels", missing_sentinels)
    sink = [] if version == resources._FINGERPRINT_V2 else None
    with pytest.raises(resources.DomainError) as error:
        load(
            h,
            write=True,
            own_intent=h.existing.intent_digest,
            _fingerprint_version=version,
            _fingerprint_collector=sink,
        )
    assert error.value.reason == "RUN_SAMPLE_USAGE_MISSING"
    assert calls == [False] and sink in (None, [])
    assert "complete-own-effects" not in h.calls
