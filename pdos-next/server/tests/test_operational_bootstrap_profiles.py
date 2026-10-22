"""No connections: real issuer registries/DTOs, fake verified-marker boundary only."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next import operational_bootstrap as bootstrap
from pdos_next.domain.build_operational_facts import service as domain
from pdos_next.domain.build_operational_facts.schemas import DecisionInput
from pdos_next.error_catalog import REASONS
from pdos_next.errors import DomainError
from pdos_next.schemas.resource_readiness.contracts import ResourceRef

AT = datetime(2026, 10, 3, 12, 0, 0, 123456, UTC)


def decision():
    return DecisionInput.model_validate(
        {
            "kind": "calibration",
            "purpose": "shared synthetic investigation",
            "operation_id": "measure",
            "status": "accepted",
            "valid_from": (AT - timedelta(minutes=1)).isoformat(),
            "valid_until": (AT + timedelta(hours=1)).isoformat(),
            "named_decision_id": str(uuid4()),
            "actor_id": str(uuid4()),
            "conditions": [],
            "sources": [
                {
                    "artifact_id": str(uuid4()),
                    "expected_revision": 1,
                    "line": 1,
                    "quote": "Explicit synthetic source; no production qualification",
                }
            ],
        }
    ).model_dump(mode="json")


def profile(*, tenant=None, product=None, key="new-operational", version="v1", entries=True):
    resource = ResourceRef(id=uuid4(), revision=1, kind="equipment").model_dump(mode="json")
    binding = {
        "build_id": str(uuid4()),
        "build_revision": 1,
        "project_id": str(uuid4()),
        "engineering_configuration_id": str(uuid4()),
        "engineering_configuration_revision": 1,
        "manufacturing_configuration_id": str(uuid4()),
        "manufacturing_configuration_revision": 1,
        "scope": {
            "purpose": "shared synthetic investigation",
            "quantity": "1",
            "unit": "ea",
            "site": "synthetic",
            "window": {
                "start": AT.isoformat(),
                "finish": (AT + timedelta(hours=1)).isoformat(),
                "original_timezone": "UTC",
            },
        },
    }
    return {
        "tenant_id": str(tenant or uuid4()),
        "product_id": str(product or uuid4()),
        "issuer_key": key,
        "issuer_version": version,
        "decisions": [{"binding": binding, "resource": resource, "decision": decision()}]
        if entries
        else [],
    }


def marker(monkeypatch, module=bootstrap):
    calls = []
    monkeypatch.setattr(module, "verify_test_target", lambda engine: calls.append(engine))
    return calls


def old_shape(value):
    return {k: deepcopy(v) for k, v in value.items() if k not in {"issuer_key", "issuer_version"}}


def state(engine):
    return {
        "issuers": dict(getattr(engine, "_pdos_operational_issuers", {})),
        "epochs": dict(getattr(engine, "_pdos_operational_issuer_epochs", {})),
        "configurations": dict(getattr(engine, "_pdos_operational_bootstrap_profiles", {})),
    }


def test_legacy_single_then_explicit_batch_reuses_object_epoch_and_callback(monkeypatch):
    checks = marker(monkeypatch)
    engine = SimpleNamespace()
    old = profile(key=bootstrap.DEFAULT_ISSUER_KEY)
    first = bootstrap.configure_local_profile(engine, old_shape(old))
    new = profile()
    values = bootstrap.configure_local_profiles(engine, [old, new])
    assert values[0] is first and first.epoch == 1
    assert engine._pdos_operational_issuers[first.key] is first
    again = bootstrap.configure_local_profiles(engine, [new, old])
    assert again == (values[1], first)
    assert state(engine)["epochs"] == {first.key: 1, values[1].key: 1}
    assert len(checks) == 3
    assert all(v.nature == "synthetic" for v in values)


def test_exact_scope_selects_real_issuer_before_finite_decision_callback(monkeypatch):
    marker(monkeypatch)
    engine = SimpleNamespace()
    tenant = uuid4()
    left, right = profile(tenant=tenant, key="left"), profile(tenant=tenant, key="right")
    a, b = bootstrap.configure_local_profiles(engine, [left, right])
    session = SimpleNamespace(get_bind=lambda: engine)
    ctx = SimpleNamespace(tenant_id=tenant)
    assert domain._issuer(session, ctx, a.product_id, uuid4(), a) is a
    with pytest.raises(DomainError) as error:
        domain._issuer(session, ctx, b.product_id, uuid4(), a)
    assert error.value.reason == "TRUSTED_ISSUER_REQUIRED"
    assert error.value.code == REASONS["TRUSTED_ISSUER_REQUIRED"]
    item = left["decisions"][0]
    resource = ResourceRef.model_validate(item["resource"])
    fact = DecisionInput.model_validate(item["decision"])
    callback = a.verify_named_decision
    assert callback(session, ctx, item["binding"], resource, fact, AT)["current"] is True
    assert b.verify_named_decision(session, ctx, item["binding"], resource, fact, AT) is None
    assert (
        callback(session, SimpleNamespace(tenant_id=uuid4()), item["binding"], resource, fact, AT)
        is None
    )
    changed = deepcopy(item["binding"])
    changed["build_revision"] = 2
    assert callback(session, ctx, changed, resource, fact, AT) is None
    assert callback(session, ctx, item["binding"], resource, fact, AT + timedelta(hours=1)) is None


def test_input_mutation_cannot_change_pinned_ledger(monkeypatch):
    marker(monkeypatch)
    engine = SimpleNamespace()
    configured = profile()
    original = deepcopy(configured)
    (issuer,) = bootstrap.configure_local_profiles(engine, [configured])
    configured["decisions"][0]["binding"]["build_revision"] = 99
    item = original["decisions"][0]
    result = issuer.verify_named_decision(
        None,
        SimpleNamespace(tenant_id=issuer.tenant_id),
        item["binding"],
        ResourceRef.model_validate(item["resource"]),
        DecisionInput.model_validate(item["decision"]),
        AT,
    )
    assert result is not None
    before = state(engine)
    with pytest.raises(ValueError):
        bootstrap.configure_local_profiles(engine, [configured])
    assert state(engine) == before


@pytest.mark.parametrize("bad", [None, (), [], {}, [None], [profile(entries=False)] * 21])
def test_only_nonempty_explicit_json_list_at_most_twenty(monkeypatch, bad):
    checks = marker(monkeypatch)
    engine = SimpleNamespace()
    with pytest.raises(ValueError):
        bootstrap.configure_local_profiles(engine, bad)
    assert state(engine) == {"issuers": {}, "epochs": {}, "configurations": {}}
    assert checks == []


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate-key",
        "duplicate-scope",
        "bad-uuid",
        "extra-field",
        "missing-key",
        "blank-name",
        "long-version",
        "malformed-binding",
        "bool-revision",
        "bad-resource",
        "duplicate-decision",
        "missing-expiry",
        "nan-binding",
    ],
)
def test_entire_list_prevalidation_does_not_partially_register(monkeypatch, kind):
    checks = marker(monkeypatch)
    engine = SimpleNamespace()
    first, second = profile(key="first"), profile(key="second")
    if kind == "duplicate-key":
        second["issuer_key"] = first["issuer_key"]
    elif kind == "duplicate-scope":
        second["tenant_id"], second["product_id"] = first["tenant_id"], first["product_id"]
    elif kind == "bad-uuid":
        second["product_id"] = "bad"
    elif kind == "extra-field":
        second["current"] = True
    elif kind == "missing-key":
        second.pop("issuer_version")
    elif kind == "blank-name":
        second["issuer_key"] = " spaced "
    elif kind == "long-version":
        second["issuer_version"] = "x" * 101
    elif kind == "malformed-binding":
        second["decisions"][0]["binding"].pop("project_id")
    elif kind == "bool-revision":
        second["decisions"][0]["binding"]["build_revision"] = True
    elif kind == "bad-resource":
        second["decisions"][0]["resource"]["kind"] = "grant"
    elif kind == "duplicate-decision":
        second["decisions"] *= 2
    elif kind == "missing-expiry":
        second["decisions"][0]["decision"].pop("valid_until")
    elif kind == "nan-binding":
        second["decisions"][0]["binding"]["scope"]["quantity"] = float("nan")
    before = state(engine)
    with pytest.raises((ValueError, TypeError)):
        bootstrap.configure_local_profiles(engine, [first, second])
    assert state(engine) == before and checks == []


@pytest.mark.parametrize(
    "kind", ["scope", "version", "material", "revoked", "replacement", "unrecorded"]
)
def test_old_key_cannot_be_replaced_or_revived_by_batch(monkeypatch, kind):
    marker(monkeypatch)
    engine = SimpleNamespace()
    saved = profile()
    (issuer,) = bootstrap.configure_local_profiles(engine, [saved])
    attempted = deepcopy(saved)
    if kind == "scope":
        attempted["product_id"] = str(uuid4())
    elif kind == "version":
        attempted["issuer_version"] = "v2"
    elif kind == "material":
        attempted["decisions"][0]["decision"]["conditions"] = ["new"]
    elif kind == "revoked":
        domain.disable_issuer(engine, issuer.key)
    elif kind == "replacement":
        domain.configure_local_synthetic(
            engine,
            tenant_id=issuer.tenant_id,
            product_id=issuer.product_id,
            key=issuer.key,
            enabled=True,
            test_marker_verified=True,
        )
    elif kind == "unrecorded":
        del engine._pdos_operational_bootstrap_profiles[issuer.key]
    before = state(engine)
    with pytest.raises(ValueError):
        bootstrap.configure_local_profiles(engine, [profile(key="never-register"), attempted])
    assert state(engine) == before


def test_marker_failure_has_no_registration_even_for_valid_list(monkeypatch):
    engine = SimpleNamespace()

    def reject(_):
        raise ValueError("unverified marker")

    monkeypatch.setattr(bootstrap, "verify_test_target", reject)
    with pytest.raises(ValueError):
        bootstrap.configure_local_profiles(engine, [profile(), profile(key="second")])
    assert state(engine) == {"issuers": {}, "epochs": {}, "configurations": {}}


def test_maximum_distinct_profiles_is_supported_without_extra_default_scope(monkeypatch):
    marker(monkeypatch)
    engine = SimpleNamespace()
    configured = [profile(key=f"scope-{i}", entries=False) for i in range(20)]
    values = bootstrap.configure_local_profiles(engine, configured)
    assert len(values) == len(engine._pdos_operational_issuers) == 20
    assert bootstrap.DEFAULT_ISSUER_KEY not in engine._pdos_operational_issuers
    assert {str(v.product_id) for v in values} == {v["product_id"] for v in configured}


def registration_failure_restores_existing(monkeypatch, module, registrar, make_profile):
    """Inject after REAL second factory publication; retain every original object."""
    marker(monkeypatch, module)
    engine = SimpleNamespace()
    old = make_profile(key=getattr(module, "DEFAULT_ISSUER_KEY", "old"))
    original = module.configure_local_profile(engine, old_shape(old) if "decisions" in old else old)
    names = module._CONFIGURATION_ATTRIBUTES
    original_attributes = {name: getattr(engine, name) for name in names}
    contents = {name: dict(value) for name, value in original_attributes.items()}
    old_record = original_attributes[module._CONFIGURATIONS][original.key]
    old_record_contents = dict(old_record)
    callback = getattr(original, "verify_named_decision", None)
    actual_factory = registrar.configure_local_synthetic
    calls = []

    def publish_then_fail(target, **kwargs):
        issuer = actual_factory(target, **kwargs)
        calls.append(issuer)
        if kwargs["key"] == "late-new":
            # Simulate a registrar mutating old objects as well as replacing maps.
            original_attributes[module._REGISTRY][original.key] = object()
            original_attributes[module._EPOCHS][original.key] = 500
            old_record["canonical"] = "damaged"
            old_record["issuer"] = object()
            raise RuntimeError("second real factory failed after publication")
        return issuer

    monkeypatch.setattr(registrar, "configure_local_synthetic", publish_then_fail)
    if hasattr(module, "configure_local_synthetic"):
        monkeypatch.setattr(module, "configure_local_synthetic", publish_then_fail)
    profiles = [old, make_profile(key="first-new"), make_profile(key="late-new")]
    unchanged = deepcopy(profiles)
    with pytest.raises(RuntimeError, match="after publication"):
        module.configure_local_profiles(engine, profiles)
    assert [value.key for value in calls] == ["first-new", "late-new"]
    assert profiles == unchanged
    for name, value in original_attributes.items():
        assert getattr(engine, name) is value
        assert value == contents[name]
    assert old_record is engine.__dict__[module._CONFIGURATIONS][original.key]
    assert old_record == old_record_contents
    assert engine.__dict__[module._REGISTRY][original.key] is original
    assert original.epoch == engine.__dict__[module._EPOCHS][original.key] == 1
    assert getattr(original, "verify_named_decision", None) is callback
    return engine, original, old


def registration_failure_restores_absence(monkeypatch, module, registrar, make_profile):
    marker(monkeypatch, module)
    engine = SimpleNamespace()
    actual_factory = registrar.configure_local_synthetic
    calls = []

    def publish_then_fail(target, **kwargs):
        issuer = actual_factory(target, **kwargs)
        calls.append(issuer)
        if kwargs["key"] == "late-new":
            raise RuntimeError("late real factory failure")
        return issuer

    monkeypatch.setattr(registrar, "configure_local_synthetic", publish_then_fail)
    if hasattr(module, "configure_local_synthetic"):
        monkeypatch.setattr(module, "configure_local_synthetic", publish_then_fail)
    with pytest.raises(RuntimeError, match="late real factory"):
        module.configure_local_profiles(
            engine, [make_profile(key="first-new"), make_profile(key="late-new")]
        )
    assert len(calls) == 2
    assert all(not hasattr(engine, name) for name in module._CONFIGURATION_ATTRIBUTES)
    assert vars(engine) == {}


def reused_epoch_drift_refused(monkeypatch, module, make_profile, bad_epoch):
    checks = marker(monkeypatch, module)
    engine = SimpleNamespace()
    old = make_profile(key=getattr(module, "DEFAULT_ISSUER_KEY", "old"))
    original = module.configure_local_profile(engine, old_shape(old) if "decisions" in old else old)
    attrs = {name: getattr(engine, name) for name in module._CONFIGURATION_ATTRIBUTES}
    attrs[module._EPOCHS][original.key] = bad_epoch
    contents = {name: dict(value) for name, value in attrs.items()}
    with pytest.raises(ValueError):
        module.configure_local_profiles(engine, [make_profile(key="never-register"), old])
    assert len(checks) == 1
    for name, value in attrs.items():
        assert getattr(engine, name) is value
        assert value == contents[name]
    assert attrs[module._REGISTRY][original.key] is original


def test_second_real_factory_failure_restores_old_issuer_callback_epoch_and_metadata(monkeypatch):
    engine, original, saved = registration_failure_restores_existing(
        monkeypatch, bootstrap, domain, profile
    )
    entry = saved["decisions"][0]
    assert (
        original.verify_named_decision(
            None,
            SimpleNamespace(tenant_id=original.tenant_id),
            entry["binding"],
            ResourceRef.model_validate(entry["resource"]),
            DecisionInput.model_validate(entry["decision"]),
            AT,
        )
        is not None
    )
    assert (
        domain._issuer(
            SimpleNamespace(get_bind=lambda: engine),
            SimpleNamespace(tenant_id=original.tenant_id),
            original.product_id,
            uuid4(),
            original,
        )
        is original
    )


def test_second_real_factory_failure_removes_originally_absent_configuration(monkeypatch):
    registration_failure_restores_absence(monkeypatch, bootstrap, domain, profile)


@pytest.mark.parametrize("bad_epoch", [2, True])
def test_same_issuer_object_with_drifted_or_boolean_epoch_cannot_be_reused(monkeypatch, bad_epoch):
    reused_epoch_drift_refused(monkeypatch, bootstrap, profile, bad_epoch)


@pytest.mark.parametrize("attribute", bootstrap._CONFIGURATION_ATTRIBUTES)
def test_malformed_registry_epoch_or_metadata_shape_is_refused_without_registration(
    monkeypatch, attribute
):
    checks = marker(monkeypatch)
    engine = SimpleNamespace()
    setattr(engine, attribute, [])
    with pytest.raises(ValueError):
        bootstrap.configure_local_profiles(engine, [profile()])
    assert getattr(engine, attribute) == []
    assert set(vars(engine)) == {attribute}
    assert checks == []


def test_reused_metadata_extra_fields_are_not_trusted(monkeypatch):
    checks = marker(monkeypatch)
    engine = SimpleNamespace()
    saved = profile()
    (issuer,) = bootstrap.configure_local_profiles(engine, [saved])
    engine._pdos_operational_bootstrap_profiles[issuer.key]["current"] = True
    before = state(engine)
    with pytest.raises(ValueError):
        bootstrap.configure_local_profiles(engine, [profile(key="never-register"), saved])
    assert state(engine) == before and len(checks) == 1


def test_epoch_only_tombstone_cannot_be_silently_registered_again(monkeypatch):
    marker(monkeypatch, bootstrap)
    engine = SimpleNamespace()
    saved = profile()
    (issuer,) = bootstrap.configure_local_profiles(engine, [saved])
    del engine.__dict__[bootstrap._REGISTRY][issuer.key]
    del engine.__dict__[bootstrap._CONFIGURATIONS][issuer.key]
    originals = {name: getattr(engine, name) for name in bootstrap._CONFIGURATION_ATTRIBUTES}
    before = {name: dict(value) for name, value in originals.items()}
    with pytest.raises(ValueError):
        bootstrap.configure_local_profiles(engine, [profile(key="never-register"), saved])
    for name, value in originals.items():
        assert getattr(engine, name) is value
        assert value == before[name]
