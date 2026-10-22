"""Capability projection checks without opening any database connection."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event

from pdos_next import api, category_capabilities
from pdos_next.models import Category, Grant, Principal
from pdos_next.service import Context


@pytest.fixture
def projection(monkeypatch):
    tenant, actor, category = uuid4(), uuid4(), uuid4()
    at = datetime(2026, 10, 17, tzinfo=UTC)
    person = Principal(id=actor, tenant_id=tenant, kind="human", active=True)
    grant = Grant(
        tenant_id=tenant,
        category_id=category,
        principal_id=actor,
        product_manager=True,
        can_write=False,
        expires_at=None,
    )
    ctx = Context(tenant, actor, actor)
    queries = []

    def execute(query):
        queries.append(query)
        return [(person, grant)]

    session = SimpleNamespace(info={"scope": (tenant, actor, actor, None)}, execute=execute)
    monkeypatch.setattr(category_capabilities, "now", lambda: at)
    return SimpleNamespace(
        ctx=ctx, session=session, person=person, grant=grant, at=at, queries=queries
    )


@pytest.mark.parametrize(
    ("active", "kind", "product_manager", "expiry", "expected"),
    [
        (True, "human", True, None, True),
        (True, "human", True, 1, True),
        (True, "human", True, 0, False),
        (True, "human", True, -1, False),
        (False, "human", True, None, False),
        (True, "agent", True, None, False),
        (True, "human", False, None, False),
    ],
)
def test_existing_human_membership_role_and_deadline(
    projection, active, kind, product_manager, expiry, expected
):
    p = projection
    p.person.active, p.person.kind = active, kind
    p.grant.product_manager = product_manager
    p.grant.expires_at = None if expiry is None else p.at + timedelta(seconds=expiry)
    result = category_capabilities.product_management_categories(
        p.session, p.ctx, [p.grant.category_id]
    )
    assert result == ({p.grant.category_id} if expected else set())
    # Generic write access is not a substitute for the dedicated product-manager role.
    p.grant.can_write = True
    assert (
        category_capabilities.product_management_categories(p.session, p.ctx, [p.grant.category_id])
        == result
    )


@pytest.mark.parametrize("mode", ["empty", "different_requester", "run", "agent_run"])
def test_nonpersonal_or_empty_projection_has_no_capabilities_or_query(projection, mode):
    p = projection
    ctx = p.ctx
    ids = [p.grant.category_id]
    if mode == "empty":
        ids = []
    elif mode == "different_requester":
        ctx = replace(ctx, requester_id=uuid4())
        p.session.info = {}
    elif mode == "run":
        ctx = replace(ctx, run_id=uuid4())
    else:
        ctx = replace(ctx, agent_run_id=uuid4())
    assert category_capabilities.product_management_categories(p.session, ctx, ids) == set()
    assert p.queries == []


def test_query_is_bound_to_authenticated_tenant_actor_and_visible_categories(projection):
    p = projection
    ids = [p.grant.category_id, uuid4()]
    category_capabilities.product_management_categories(p.session, p.ctx, ids)
    query = p.queries[0]
    bound_values = list(query.compile().params.values())
    assert len(bound_values) == 3
    assert p.ctx.tenant_id in bound_values
    assert p.ctx.actor_id in bound_values
    assert ids in bound_values
    sql = str(query)
    assert "grants.tenant_id = principals.tenant_id" in sql
    assert "grants.principal_id = principals.id" in sql
    assert "principals.tenant_id = :tenant_id_" in sql
    assert "principals.id = :id_" in sql
    assert "grants.category_id IN" in sql


def test_categories_route_preserves_visible_rows_and_legacy_fields(projection, monkeypatch):
    p = projection
    visible = [
        Category(
            id=identity,
            tenant_id=p.ctx.tenant_id,
            key=f"category-{index}",
            name=f"Visible {index}",
            purpose="Synthetic projection check",
            owner_id=p.ctx.actor_id,
            revision=1,
            status="active",
        )
        for index, identity in enumerate([p.grant.category_id, uuid4()])
    ]
    p.session.scalars = lambda query: visible

    @contextmanager
    def session(engine, tenant_id, **scope):
        assert tenant_id == p.ctx.tenant_id
        assert scope == {"actor_id": p.ctx.actor_id, "requester_id": p.ctx.requester_id}
        yield p.session

    monkeypatch.setattr(api, "tenant_session", session)
    engine = create_engine("postgresql+psycopg://offline@127.0.0.1:1/pdos_schema_export")

    @event.listens_for(engine, "do_connect")
    def forbid_connection(*_args):
        raise AssertionError("Capability projection test must not connect to a database")

    try:
        app = api.create_app(engine, engine, workflow_enabled=False)
        route = next(
            route for route in app.routes if getattr(route, "path", None) == "/v1/categories"
        )
        result = route.endpoint(p.ctx)
        assert [row["id"] for row in result] == [str(category.id) for category in visible]
        for row, category in zip(result, visible, strict=True):
            assert row == {
                "id": str(category.id),
                "key": category.key,
                "name": category.name,
                "purpose": category.purpose,
                "revision": category.revision,
                "status": category.status,
                "capabilities": {"product_management": category.id == p.grant.category_id},
            }
    finally:
        engine.dispose()
