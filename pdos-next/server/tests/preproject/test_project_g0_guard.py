"""Reverse G0 integrity under the actual application role, no model or bypass."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from pdos_next.database import tenant_session
from pdos_next.domain.projects.models import Project
from tests.g0_fixture import create_g0_project


def session(setup):
    return tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human,
        category_id=setup.category,
    )


@pytest.mark.parametrize("borrow_decision", [False, True])
def test_new_project_cannot_bypass_or_borrow_completed_g0(setup, borrow_decision):
    scope = create_g0_project(setup)
    with session(setup) as s:
        actual = s.get(Project, UUID(scope.project_id))
        decision_id = actual.g0_decision_id
    with pytest.raises(DBAPIError) as caught:
        with session(setup) as s:
            s.add(Project(
                id=uuid4(), tenant_id=setup.tenant, category_id=setup.category,
                product_id=setup.product, owner_id=setup.human, name="Unapproved extra project",
                purpose="Synthetic scope", scope="Synthetic scope", visibility="private",
                g0_decision_id=decision_id if borrow_decision else None,
                trigger_type="proposal" if borrow_decision else None,
                trigger_id=UUID(scope.proposal_id) if borrow_decision else None,
            ))
            s.flush()
            s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert caught.value.orig.sqlstate == "23514"
    with session(setup) as s:
        assert s.scalar(select(func.count()).select_from(Project)) == 1


@pytest.mark.parametrize("field,value", [
    ("g0_decision_id", None), ("trigger_type", "customer_request"),
    ("trigger_id", uuid4()), ("product_id", uuid4()), ("category_id", uuid4()),
])
def test_project_source_identity_is_immutable_after_g0(setup, field, value):
    scope = create_g0_project(setup)
    with pytest.raises(DBAPIError) as caught:
        with session(setup) as s:
            row = s.get(Project, UUID(scope.project_id))
            setattr(row, field, value)
            s.flush()
    # The existing category-binding trigger runs first and preserves its code.
    expected = "P0001" if field in {"category_id", "product_id"} else "23514"
    assert caught.value.orig.sqlstate == expected


def test_ordinary_project_updates_do_not_reapprove_a_completed_g0(setup):
    scope = create_g0_project(setup)
    with session(setup) as s:
        row = s.get(Project, UUID(scope.project_id))
        row.revision += 1
        s.flush()
        s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    with session(setup) as s:
        row = s.get(Project, UUID(scope.project_id))
        assert row.revision == 2
        assert row.g0_decision_id is not None
