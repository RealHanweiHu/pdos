"""Actual Start compatibility on a separately marked repository-test database."""

# ruff: noqa: F811 - imported fixtures register their transitive dependencies
import os
from uuid import uuid4

import pytest
from test_retained_execution import (  # noqa: F401
    _current,
    _proof,
    _run_row,
    _scoped,
    known_configuration,
    operational_work,
    ready_work,
    retained_launch_work,
    retained_started_work,
)
from verification_launch import fixtures as launch_fixtures

from pdos_next.database import engine_for
from pdos_next.domain.test_resources import service as resources
from pdos_next.safety import verify_test_target


@pytest.fixture
def engines():
    # Fresh real Engine configuration for each case: the original single-key
    # case must not inherit another test's retired issuer epoch map.
    admin = engine_for(os.environ["TEST_DATABASE_URL"])
    app = engine_for(os.environ["DATABASE_URL"])
    auth = engine_for(os.environ["AUTH_DATABASE_URL"])
    verify_test_target(admin)
    verify_test_target(app)
    dispatch = engine_for(os.environ["DISPATCH_DATABASE_URL"])
    verify_test_target(dispatch)
    app._pdos_dispatch_engine = dispatch
    yield admin, app, auth
    for engine in (admin, app, auth, dispatch):
        engine.dispose()


def add_unrelated_scope(work):
    return resources.configure_local_synthetic(
        work.setup.engine,
        tenant_id=uuid4(),
        product_id=uuid4(),
        project_id=uuid4(),
        key=f"unrelated-resource-{uuid4()}",
        enabled=True,
        test_marker_verified=True,
    )


def test_exact_single_dependency_survives_unrelated_scope_addition(retained_started_work):
    work = retained_started_work
    with _scoped(work) as s:
        before = _proof(s, work)
        _current(before)
    assert len(work.setup.engine._pdos_test_resource_issuer_epochs) == 1
    add_unrelated_scope(work)
    with _scoped(work) as s:
        after = _proof(s, work)
        _current(after)
        assert after["facts_revision"] == before["facts_revision"]
        assert after["reservation"] == before["reservation"]
        assert after["occupancy"] == before["occupancy"]
        assert after["sample_usage"] == before["sample_usage"]
        assert after["saved_start_at"] == before["saved_start_at"]


def test_new_v2_start_preserves_its_exact_dependency_with_multiple_registered_keys(
    retained_launch_work, monkeypatch
):
    work = retained_launch_work
    add_unrelated_scope(work)
    launch_fixtures.started(work, monkeypatch)
    assert len(work.setup.engine._pdos_test_resource_issuer_epochs) == 2
    with _scoped(work) as s:
        original = _run_row(s, work)
        assert original.input_snapshot["resource_fingerprint_version"] == (
            "test-resource-dependency-v2"
        )
        before = _proof(s, work)
        _current(before)
    add_unrelated_scope(work)
    with _scoped(work) as s:
        after = _proof(s, work)
        _current(after)
        for field in (
            "facts_revision",
            "reservation",
            "occupancy",
            "sample_usage",
            "saved_start_at",
        ):
            assert after[field] == before[field]


def test_registry_boolean_epoch_cannot_reinterpret_fixed_proof_or_supply_a_valid_saved_epoch(
    retained_started_work,
):
    from copy import deepcopy

    from pdos_next.errors import DomainError

    work = retained_started_work
    with _scoped(work) as s:
        before = _proof(s, work)
        _current(before)
        original = _run_row(s, work)
        fixed = deepcopy(original.input_snapshot["resource_dependency_proof"])
    add_unrelated_scope(work)
    epochs = dict(work.setup.engine._pdos_test_resource_issuer_epochs)
    assert type(epochs[work.test_issuer.key]) is int
    assert epochs[work.test_issuer.key] == 1
    epochs[work.test_issuer.key] = True
    work.setup.engine._pdos_test_resource_issuer_epochs = epochs
    with _scoped(work) as s:
        after = _proof(s, work)
        _current(after)
        for key in (
            "facts_revision", "original_start_intent", "reservation", "occupancy", "sample_usage"
        ):
            assert after[key] == before[key]
    # A later registry is not consumed; the persisted typed dependency still
    # rejects a boolean masquerading as its real original integer epoch.
    assert type(fixed["material"]["issuer_epochs"][work.test_issuer.key]) is int
    malformed = deepcopy(fixed)
    malformed["material"]["issuer_epochs"][work.test_issuer.key] = True
    with pytest.raises(DomainError):
        resources._verify_stored_fingerprint_v2(malformed)
