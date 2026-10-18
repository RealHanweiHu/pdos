"""Project scope is an immutable server binding; no database or provider ports."""

from dataclasses import FrozenInstanceError, replace
from inspect import Parameter, signature
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.execution import check_run_binding, scope_for_run
from pdos_next.agent_kernel.project_scope import require_project
from pdos_next.agent_kernel.types import RunScope
from pdos_next.errors import DomainError


def _binding(*, project=True):
    scope = RunScope(
        *(uuid4() for _ in range(6)), product_id=uuid4(), project_id=uuid4() if project else None
    )
    row = SimpleNamespace(
        id=scope.run_id,
        tenant_id=scope.tenant_id,
        requester_id=scope.requester_id,
        writer_id=scope.writer_id,
        session_id=scope.session_id,
        category_id=scope.category_id,
        product_id=scope.product_id,
        proposal_id=scope.proposal_id,
        project_id=scope.project_id,
        cancel_epoch=scope.cancel_epoch,
        private_context=scope.private_context,
        data_categories=list(scope.data_categories),
        customer_identities=list(scope.customer_identities),
        trigger=scope.trigger,
        reverted_at=None,
        state="queued",
    )
    return scope, row


def test_project_is_keyword_only_and_child_preserves_immutable_server_scope():
    scope, _ = _binding()
    assert signature(RunScope).parameters["project_id"].kind is Parameter.KEYWORD_ONLY
    assert scope.cancel_epoch == 0 and scope.isolation == "main"
    child = scope.child("extract", artifact_ids={uuid4()})
    assert child.project_id == scope.project_id and child.run_id == scope.run_id
    assert child.isolation == "extract" and scope.isolation == "main"
    with pytest.raises(FrozenInstanceError):
        scope.project_id = uuid4()


def test_stored_project_round_trips_and_cannot_be_replaced_by_caller_scope():
    scope, row = _binding()
    assert scope_for_run(row) == scope
    check_run_binding(row, scope)
    for project_id in (None, uuid4()):
        with pytest.raises(DomainError) as error:
            check_run_binding(row, replace(scope, project_id=project_id))
        assert error.value.code == "FORBIDDEN_SCOPE"


def test_missing_historical_project_stays_unbound_without_guessing_from_product():
    scope, row = _binding(project=False)
    del row.project_id
    restored = scope_for_run(row)
    assert restored.project_id is None and restored.product_id == scope.product_id
    check_run_binding(row, restored, for_write=False)
    with pytest.raises(DomainError):
        check_run_binding(row, replace(restored, project_id=uuid4()), for_write=False)


@pytest.mark.parametrize("category,product", [(None, uuid4()), (uuid4(), None)])
def test_project_requires_real_category_and_product_before_query(category, product):
    ctx = SimpleNamespace(category_id=category)
    with pytest.raises(DomainError) as error:
        require_project(object(), ctx, uuid4(), product)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_unbound_project_does_not_read_or_infer_a_project():
    assert require_project(object(), object(), None, uuid4()) is None


def test_registered_context_profiles_carry_only_checked_project_metadata():
    from pdos_next.agent_kernel.context_projection import combine_contracts, project
    from pdos_next.agent_kernel.skills import SkillCatalog

    catalog = SkillCatalog()
    actual = {
        "goal": "Inspect current project",
        "sources": [],
        "project": {
            "id": str(uuid4()),
            "name": "Synthetic project",
            "revision": 2,
            "visibility": "private",
            "unregistered": "PRIVATE VALUE",
        },
    }
    for methods in [[], *[[catalog.configuration(entry["key"])] for entry in catalog.index]]:
        value, omitted, issues = project(actual, combine_contracts(catalog, methods))
        assert not issues and value["project"]["revision"] == 2
        assert "unregistered" not in value["project"]
        assert omitted == [
            {"field": "/project/unregistered", "reason": "outside_skill_context_schema"}
        ]
