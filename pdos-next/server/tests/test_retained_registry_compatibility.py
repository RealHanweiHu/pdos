"""Actual Start compatibility on a separately marked repository-test database."""

# ruff: noqa: F811 - imported fixtures register their transitive dependencies
import os
from uuid import uuid4

import pytest
from test_retained_execution import (  # noqa: F401
    _current,
    _proof,
    known_configuration,
    operational_work,
    ready_work,
    retained_launch_work,
    retained_started_work,
)
from verification_launch import fixtures as launch_fixtures

from pdos_next.database import engine_for, tenant_session
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
    yield admin, app, auth
    for engine in (admin, app, auth):
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
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        before = _proof(s, work)
        _current(before)
    assert len(work.setup.engine._pdos_test_resource_issuer_epochs) == 1
    add_unrelated_scope(work)
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        after = _proof(s, work)
        _current(after)
        assert after["facts_revision"] == before["facts_revision"]
        assert after["reservation"] == before["reservation"]
        assert after["occupancy"] == before["occupancy"]
        assert after["sample_usage"] == before["sample_usage"]
        assert after["saved_start_at"] == before["saved_start_at"]


def test_legacy_saved_multiple_keys_are_not_guessed(retained_launch_work, monkeypatch):
    work = retained_launch_work
    add_unrelated_scope(work)
    launch_fixtures.started(work, monkeypatch)
    assert len(work.setup.engine._pdos_test_resource_issuer_epochs) == 2
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        _current(_proof(s, work))
    add_unrelated_scope(work)
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        after = _proof(s, work)
        assert after["current"] is False
        assert after["reason_codes"] == ["RETAINED_EXECUTION_CHANGED"]


def test_boolean_epoch_does_not_reproduce_real_original_dependency(retained_started_work):
    work = retained_started_work
    add_unrelated_scope(work)
    epochs = dict(work.setup.engine._pdos_test_resource_issuer_epochs)
    assert type(epochs[work.test_issuer.key]) is int
    assert epochs[work.test_issuer.key] == 1
    epochs[work.test_issuer.key] = True
    work.setup.engine._pdos_test_resource_issuer_epochs = epochs
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        after = _proof(s, work)
        assert after["current"] is False
        assert after["reason_codes"]
