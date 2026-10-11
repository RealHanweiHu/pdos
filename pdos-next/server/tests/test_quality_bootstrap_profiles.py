"""Actual scoped policy issuers; marked-host boundary is substituted, never connected."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_next import quality_bootstrap as bootstrap
from pdos_next.domain.quality_execution import policy
from pdos_next.errors import DomainError
from test_operational_bootstrap_profiles import (
    registration_failure_restores_absence,
    registration_failure_restores_existing,
    reused_epoch_drift_refused,
)


def profile(key="quality-a", *, tenant=None, product=None, project=None):
    return {
        "tenant_id": str(tenant or uuid4()),
        "product_id": str(product or uuid4()),
        "project_id": str(project or uuid4()),
        "issuer_key": key,
        "issuer_version": "v1",
    }


def marker(monkeypatch):
    checks = []
    monkeypatch.setattr(bootstrap, "verify_test_target", lambda engine: checks.append(engine))
    return checks


def state(engine):
    return {
        k: dict(getattr(engine, k, {}))
        for k in (
            "_pdos_quality_policy_issuers",
            "_pdos_quality_policy_epochs",
            "_pdos_quality_bootstrap_profiles",
        )
    }


def test_explicit_old_and_new_policy_scopes_preserve_issuer_object_epoch(monkeypatch):
    marker(monkeypatch)
    engine = SimpleNamespace()
    old, new = profile("old"), profile("new")
    original = bootstrap.configure_local_profile(engine, old)
    values = bootstrap.configure_local_profiles(engine, [old, new])
    assert values[0] is original and original.epoch == 1
    assert bootstrap.configure_local_profiles(engine, [new, old]) == (values[1], original)
    assert engine._pdos_quality_policy_epochs == {"old": 1, "new": 1}
    assert set(engine._pdos_quality_policy_issuers) == {"old", "new"}


@pytest.mark.parametrize("changed", ["tenant_id", "product_id", "project_id"])
def test_actual_policy_domain_issuer_requires_every_scope_component(monkeypatch, changed):
    marker(monkeypatch)
    engine = SimpleNamespace()
    (issuer,) = bootstrap.configure_local_profiles(engine, [profile()])
    values = {k: getattr(issuer, k) for k in ("tenant_id", "product_id", "project_id")}
    policy._issuer(engine, issuer, values["tenant_id"], values["product_id"], values["project_id"])
    values[changed] = uuid4()
    with pytest.raises(DomainError) as error:
        policy._issuer(
            engine, issuer, values["tenant_id"], values["product_id"], values["project_id"]
        )
    assert error.value.reason == "TRUSTED_ISSUER_REQUIRED"


@pytest.mark.parametrize(
    "kind",
    [
        "scope",
        "key",
        "wrong-uuid",
        "extra",
        "missing",
        "blank",
        "long-version",
        "empty",
        "tuple",
        "too-many",
        "same-key-new-scope",
        "new-version",
        "revoked",
        "unrecorded",
        "replacement",
    ],
)
def test_invalid_or_conflicting_batch_leaves_original_policy_configuration_untouched(
    monkeypatch, kind
):
    checks = marker(monkeypatch)
    engine = SimpleNamespace()
    saved = profile("saved")
    (issuer,) = bootstrap.configure_local_profiles(engine, [saved])
    left, right = profile("left"), profile("right")
    values = [left, right]
    if kind == "scope":
        for k in ("tenant_id", "product_id", "project_id"):
            right[k] = left[k]
    elif kind == "key":
        right["issuer_key"] = left["issuer_key"]
    elif kind == "wrong-uuid":
        right["project_id"] = "bad"
    elif kind == "extra":
        right["risk"] = "low"
    elif kind == "missing":
        right.pop("project_id")
    elif kind == "blank":
        right["issuer_key"] = " changed "
    elif kind == "long-version":
        right["issuer_version"] = "x" * 101
    elif kind == "empty":
        values = []
    elif kind == "tuple":
        values = tuple(values)
    elif kind == "too-many":
        values *= 11
    elif kind == "same-key-new-scope":
        right["issuer_key"] = issuer.key
    elif kind == "new-version":
        right = deepcopy(saved)
        right["issuer_version"] = "v2"
        values = [left, right]
    elif kind == "revoked":
        policy.disable_issuer(engine, issuer.key)
        values = [left, saved]
    elif kind == "unrecorded":
        del engine._pdos_quality_bootstrap_profiles[issuer.key]
        values = [left, saved]
    elif kind == "replacement":
        policy.configure_local_synthetic(
            engine,
            tenant_id=issuer.tenant_id,
            product_id=issuer.product_id,
            project_id=issuer.project_id,
            key=issuer.key,
            enabled=True,
            test_marker_verified=True,
        )
        values = [left, saved]
    before, marker_count = state(engine), len(checks)
    with pytest.raises((ValueError, TypeError)):
        bootstrap.configure_local_profiles(engine, values)
    assert state(engine) == before and len(checks) == marker_count


def test_multiple_projects_of_same_product_are_explicit_separate_scopes(monkeypatch):
    marker(monkeypatch)
    engine = SimpleNamespace()
    tenant, product = uuid4(), uuid4()
    values = bootstrap.configure_local_profiles(
        engine,
        [
            profile("a", tenant=tenant, product=product),
            profile("b", tenant=tenant, product=product),
        ],
    )
    assert values[0].project_id != values[1].project_id
    assert all((v.tenant_id, v.product_id) == (tenant, product) for v in values)


def test_marker_failure_prevents_every_valid_policy_registration(monkeypatch):
    engine = SimpleNamespace()

    def reject(_):
        raise ValueError("target not verified")

    monkeypatch.setattr(bootstrap, "verify_test_target", reject)
    with pytest.raises(ValueError):
        bootstrap.configure_local_profiles(engine, [profile("a"), profile("b")])
    assert state(engine) == {k: {} for k in state(engine)}


def test_more_than_twenty_has_only_named_explicit_scopes(monkeypatch):
    marker(monkeypatch)
    engine = SimpleNamespace()
    profiles = [profile(f"policy-{i}") for i in range(21)]
    values = bootstrap.configure_local_profiles(engine, profiles)
    assert len(values) == 21
    assert set(engine._pdos_quality_policy_issuers) == {v["issuer_key"] for v in profiles}


def test_second_real_factory_failure_restores_every_original_configuration_object(monkeypatch):
    engine, original, _ = registration_failure_restores_existing(
        monkeypatch, bootstrap, policy, profile
    )
    policy._issuer(engine, original, original.tenant_id, original.product_id, original.project_id)


def test_second_real_factory_failure_removes_originally_absent_configuration(monkeypatch):
    registration_failure_restores_absence(monkeypatch, bootstrap, policy, profile)


@pytest.mark.parametrize("bad_epoch", [2, True])
def test_same_issuer_object_with_drifted_or_boolean_epoch_cannot_be_reused(monkeypatch, bad_epoch):
    reused_epoch_drift_refused(monkeypatch, bootstrap, profile, bad_epoch)


def test_epoch_only_tombstone_cannot_be_silently_registered_again(monkeypatch):
    marker(monkeypatch)
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
