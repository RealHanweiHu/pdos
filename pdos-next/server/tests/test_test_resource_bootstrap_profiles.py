"""Real TestPlanBinding/issuer registry; no database or source/qualification assertions."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_operational_bootstrap_profiles import (
    AT,
    marker,
    old_shape,
    registration_failure_restores_absence,
    registration_failure_restores_existing,
    reused_epoch_drift_refused,
)
from test_operational_bootstrap_profiles import profile as operational_profile

from pdos_next import test_resource_bootstrap as bootstrap
from pdos_next.domain.build_operational_facts.schemas import DecisionInput
from pdos_next.domain.test_resources import service as domain
from pdos_next.domain.test_resources.schemas import TestPlanBinding as PlanBinding
from pdos_next.error_catalog import REASONS
from pdos_next.errors import DomainError
from pdos_next.schemas.resource_readiness.contracts import ResourceRef


def profile(*, key="new-test", tenant=None, product=None):
    value = operational_profile(key=key, tenant=tenant, product=product)
    entry = value["decisions"][0]
    build = str(uuid4())
    source = entry["decision"]["sources"][0]
    binding = {
        "run_id": str(uuid4()),
        "request_id": str(uuid4()),
        "accepted_request_id": str(uuid4()),
        "accepted_request_revision": 4,
        "build_id": build,
        "project_id": str(uuid4()),
        "purpose": "shared synthetic investigation",
        "executor_id": str(uuid4()),
        "window": {
            "start": AT.isoformat(),
            "finish": (AT + timedelta(hours=1)).isoformat(),
            "original_timezone": "UTC",
        },
        "environment": "lab",
        "conditions": "23 C, dry",
        "equipment": source,
        "calibration": source,
        "pairs": [
            {
                "sample": {
                    "id": str(uuid4()),
                    "revision": 1,
                    "build_id": build,
                    "actual_configuration": {"id": str(uuid4()), "revision": 1},
                    "cavity": "A",
                },
                "item_id": "dimension",
                "method_id": str(uuid4()),
                "method_revision": 1,
                "method_sha256": "a" * 64,
                "destructive": False,
            }
        ],
    }
    entry["binding"] = PlanBinding.model_validate(binding).model_dump(mode="json")
    return value


def state(engine):
    return {
        k: dict(getattr(engine, k, {}))
        for k in (
            "_pdos_test_resource_issuers",
            "_pdos_test_resource_issuer_epochs",
            "_pdos_test_resource_bootstrap_profiles",
        )
    }


def test_legacy_profile_with_typed_pairs_is_reused_in_exact_explicit_list(monkeypatch):
    marker(monkeypatch, bootstrap)
    engine = SimpleNamespace()
    old = profile(key=bootstrap.DEFAULT_ISSUER_KEY)
    original = bootstrap.configure_local_profile(engine, old_shape(old))
    new = profile()
    values = bootstrap.configure_local_profiles(engine, [old, new])
    assert values[0] is original and values[0].epoch == 1
    assert values[1].key == "new-test" and values[1].nature == "synthetic"
    assert bootstrap.configure_local_profiles(engine, [new, old]) == (values[1], original)
    assert len(engine._pdos_test_resource_issuers) == 2


def test_wrong_product_is_rejected_by_actual_domain_issuer_and_wrong_run_by_callback(monkeypatch):
    marker(monkeypatch, bootstrap)
    engine = SimpleNamespace()
    a, b = profile(key="a"), profile(key="b")
    left, right = bootstrap.configure_local_profiles(engine, [a, b])
    session = SimpleNamespace(get_bind=lambda: engine)
    ctx = SimpleNamespace(tenant_id=left.tenant_id)
    assert domain._issuer(session, ctx, left.product_id, uuid4(), left) is left
    with pytest.raises(DomainError) as error:
        domain._issuer(session, ctx, right.product_id, uuid4(), left)
    assert error.value.reason == "TRUSTED_ISSUER_REQUIRED"
    assert error.value.code == REASONS["TRUSTED_ISSUER_REQUIRED"]
    entry = a["decisions"][0]
    args = (
        session,
        ctx,
        entry["binding"],
        ResourceRef.model_validate(entry["resource"]),
        DecisionInput.model_validate(entry["decision"]),
        AT,
    )
    assert left.verify_named_decision(*args) is not None
    changed = deepcopy(entry["binding"])
    changed["run_id"] = str(uuid4())
    assert left.verify_named_decision(*(*args[:2], changed, *args[3:])) is None
    changed = deepcopy(entry["binding"])
    changed["pairs"][0]["method_revision"] = 2
    assert left.verify_named_decision(*(*args[:2], changed, *args[3:])) is None
    assert left.verify_named_decision(*(*args[:5], AT + timedelta(hours=1))) is None


@pytest.mark.parametrize(
    "kind",
    [
        "scope",
        "key",
        "unknown-field",
        "invalid-pair",
        "bool-revision",
        "changed-material",
        "duplicate-decision",
        "over-limit",
        "tuple",
        "empty",
        "unrecorded",
        "revoked",
    ],
)
def test_list_invalid_or_conflicting_late_entry_preserves_every_old_registry(monkeypatch, kind):
    checks = marker(monkeypatch, bootstrap)
    engine = SimpleNamespace()
    saved = profile(key="saved")
    (issuer,) = bootstrap.configure_local_profiles(engine, [saved])
    left, right = profile(key="left"), profile(key="right")
    values = [left, right]
    if kind == "scope":
        right["tenant_id"], right["product_id"] = left["tenant_id"], left["product_id"]
    elif kind == "key":
        right["issuer_key"] = left["issuer_key"]
    elif kind == "unknown-field":
        right["qualified"] = True
    elif kind == "invalid-pair":
        right["decisions"][0]["binding"]["pairs"][0]["sample"]["build_id"] = str(uuid4())
    elif kind == "bool-revision":
        right["decisions"][0]["binding"]["accepted_request_revision"] = True
    elif kind == "changed-material":
        right = deepcopy(saved)
        right["decisions"][0]["binding"]["conditions"] = "different"
        values = [left, right]
    elif kind == "duplicate-decision":
        right["decisions"] *= 2
    elif kind == "over-limit":
        values *= 11
    elif kind == "tuple":
        values = tuple(values)
    elif kind == "empty":
        values = []
    elif kind == "unrecorded":
        del engine._pdos_test_resource_bootstrap_profiles[issuer.key]
        values = [left, saved]
    elif kind == "revoked":
        domain.disable_issuer(engine, issuer.key)
        values = [left, saved]
    before, marker_count = state(engine), len(checks)
    with pytest.raises((ValueError, TypeError)):
        bootstrap.configure_local_profiles(engine, values)
    assert state(engine) == before and len(checks) == marker_count


def test_decision_wrong_tenant_or_resource_and_unlisted_name_cannot_verify(monkeypatch):
    marker(monkeypatch, bootstrap)
    engine = SimpleNamespace()
    value = profile()
    (issuer,) = bootstrap.configure_local_profiles(engine, [value])
    entry = value["decisions"][0]
    fact = DecisionInput.model_validate(entry["decision"])
    resource = ResourceRef.model_validate(entry["resource"])
    verify = issuer.verify_named_decision
    wrong = SimpleNamespace(tenant_id=uuid4())
    assert verify(None, wrong, entry["binding"], resource, fact, AT) is None
    ctx = SimpleNamespace(tenant_id=issuer.tenant_id)
    assert (
        verify(None, ctx, entry["binding"], resource.model_copy(update={"id": uuid4()}), fact, AT)
        is None
    )
    assert (
        verify(
            None,
            ctx,
            entry["binding"],
            resource,
            fact.model_copy(update={"named_decision_id": uuid4()}),
            AT,
        )
        is None
    )
    assert set(engine._pdos_test_resource_issuers) == {"new-test"}


def test_second_real_factory_failure_restores_every_original_configuration_object(monkeypatch):
    engine, original, _ = registration_failure_restores_existing(
        monkeypatch, bootstrap, domain, profile
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
