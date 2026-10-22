"""Actual coverage seed adapter with explicit native-owner IO substitutes."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.domain.change_coverage_owner import owner
from pdos_next.domain.change_execution import field_bridge
from pdos_next.domain.quality_execution import service as quality
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import Ref
from pdos_next.schemas.verification.contracts import Scope


@pytest.fixture
def seed(monkeypatch):
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    ctx = SimpleNamespace(tenant_id=scope.tenant_id, category_id=uuid4())
    ref = Ref(kind="field_feedback", id=uuid4(), revision=3)
    calls = []

    def native(session, caller, pid, fixed):
        calls.append((session, caller, pid, fixed))
        return object(), {"source_status": "current"}, scope, "Actual fixed Field purpose"

    monkeypatch.setattr(field_bridge, "get", native)
    monkeypatch.setattr(owner.trust, "current", lambda *a: pytest.fail("A seed grants no issuer"))
    return SimpleNamespace(scope=scope, ctx=ctx, ref=ref, calls=calls)


@pytest.mark.parametrize("verify_sources", [True, False])
def test_field_scope_uses_complete_native_current_owner_in_both_binding_modes(seed, verify_sources):
    session = object()
    actual = owner.fixed_seed(
        session,
        seed.ctx,
        seed.scope.product_id,
        (seed.ref, seed.ref),
        verify_sources=verify_sources,
    )
    assert actual == (seed.scope, "Actual fixed Field purpose")
    assert seed.calls == [(session, seed.ctx, seed.scope.product_id, seed.ref)]


@pytest.mark.parametrize("reason,status", [("SOURCE_STALE", 409), ("FORBIDDEN_SCOPE", 403)])
def test_field_source_or_acl_failure_cannot_become_a_positive_coverage_seed(
    seed, monkeypatch, reason, status
):
    def stale(*args):
        raise DomainError(reason, "Actual native Field owner refusal", status)

    monkeypatch.setattr(field_bridge, "get", stale)
    with pytest.raises(DomainError) as failure:
        owner.fixed_seed(
            object(), seed.ctx, seed.scope.product_id, (seed.ref,), verify_sources=False
        )
    assert failure.value.reason == reason and failure.value.status == status


@pytest.mark.parametrize("different", [False, True])
def test_field_and_issue_namespaces_cannot_hide_an_incompatible_seed(seed, monkeypatch, different):
    # A UUID collision across native namespaces must not deduplicate one owner.
    issue = Ref(kind="issue", id=seed.ref.id, revision=seed.ref.revision)
    project = uuid4() if different else seed.scope.project_id
    row = SimpleNamespace(
        tenant_id=seed.scope.tenant_id, product_id=seed.scope.product_id, project_id=project
    )
    view = SimpleNamespace(
        issue_id=issue.id,
        revision=issue.revision,
        source_status="current",
        purpose="Actual fixed Field purpose",
    )
    monkeypatch.setattr(quality, "get_issue_for_change", lambda *a: (row, view))
    if different:
        with pytest.raises(DomainError) as failure:
            owner.fixed_seed(object(), seed.ctx, seed.scope.product_id, (seed.ref, issue))
        assert failure.value.reason == "COVERAGE_DEPENDENCY_UNRESOLVED"
    else:
        assert owner.fixed_seed(object(), seed.ctx, seed.scope.product_id, (seed.ref, issue)) == (
            seed.scope,
            view.purpose,
        )


def test_legacy_issue_metadata_binding_keeps_existing_scope_owner(seed, monkeypatch):
    issue = Ref(kind="issue", id=uuid4(), revision=2)
    calls = []

    def scoped(*args):
        calls.append(args[-1])
        return seed.scope, "Actual Issue purpose"

    monkeypatch.setattr(quality, "_change_scope_for_change", scoped)
    monkeypatch.setattr(
        quality, "get_issue_for_change", lambda *a: pytest.fail("No extra Issue IO")
    )
    assert owner.fixed_seed(
        object(), seed.ctx, seed.scope.product_id, (issue,), verify_sources=False
    ) == (seed.scope, "Actual Issue purpose")
    assert calls == [issue] and seed.calls == []
