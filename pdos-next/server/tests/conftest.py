import os
import secrets
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pdos_next.api import create_app
from pdos_next.database import engine_for
from pdos_next.models import Category, Grant, LoginSession, Principal, Product, now
from pdos_next.safety import verify_test_target
from pdos_next.service import Context, digest


class IsolatedFixture(SimpleNamespace):
    def __repr__(self):
        return "<isolated synthetic test scope>"


@pytest.fixture(scope="session")
def engines():
    admin = engine_for(os.environ["TEST_DATABASE_URL"])
    verify_test_target(admin)
    app = engine_for(os.environ["DATABASE_URL"])
    verify_test_target(app)
    auth = engine_for(os.environ["AUTH_DATABASE_URL"])
    dispatch = engine_for(os.environ["DISPATCH_DATABASE_URL"])
    verify_test_target(dispatch)
    app._pdos_dispatch_engine = dispatch
    yield admin, app, auth
    for engine in (admin, app, auth, dispatch):
        engine.dispose()


@pytest.fixture
def setup(engines, request):
    from pdos_next.agent_kernel.models import TenantPilotAdmission

    parameters = getattr(request, "param", None)
    if parameters is not None:
        assert parameters == {"test_authorization_hours": 4}
    test_window = timedelta(hours=4) if parameters is not None else None
    test_deadline = now() + test_window if test_window else None
    membership_window = test_window or timedelta(hours=1)
    admin, app, auth = engines
    tenant, human, peer, agent, other_tenant, other_human = (uuid4() for _ in range(6))
    category, product = uuid4(), uuid4()
    tokens = {p: secrets.token_urlsafe(32) for p in [human, peer, other_human]}
    with Session(admin) as s, s.begin():
        s.add_all(
            [
                Principal(id=human, tenant_id=tenant, name="Synthetic owner", kind="human"),
                Principal(id=peer, tenant_id=tenant, name="Synthetic peer", kind="human"),
                Principal(id=agent, tenant_id=tenant, name="Synthetic agent", kind="agent"),
                Principal(
                    id=other_human, tenant_id=other_tenant, name="Other tenant", kind="human"
                ),
            ]
        )
        s.flush()
        s.add(TenantPilotAdmission(tenant_id=tenant, active=True, approval_reference="isolated synthetic test only"))
        s.add(
            Category(
                id=category,
                tenant_id=tenant,
                name="汽车充气泵",
                purpose="隔离合成品类",
                owner_id=human,
            )
        )
        s.flush()
        s.add(
            Product(
                id=product,
                tenant_id=tenant,
                category_id=category,
                name="Synthetic product",
                purpose="Isolated command verification",
                owner_id=human,
            )
        )
        s.flush()
        s.add_all(
            [
                Grant(
                    tenant_id=tenant,
                    category_id=category,
                    principal_id=p,
                    can_write=True,
                    expires_at=now() + membership_window,
                )
                for p in [human, peer, agent]
            ]
        )
        s.add_all(
            [
                LoginSession(
                    tenant_id=other_tenant if p == other_human else tenant,
                    principal_id=p,
                    token_hash=digest(token),
                    expires_at=now() + membership_window,
                )
                for p, token in tokens.items()
            ]
        )
    client = TestClient(create_app(app, auth))
    yield IsolatedFixture(
        test_authorization_window=test_window,
        test_authorization_until=test_deadline,
        admin=admin,
        engine=app,
        auth=auth,
        dispatch=app._pdos_dispatch_engine,
        tenant=tenant,
        human=human,
        peer=peer,
        agent=agent,
        category=category,
        product=product,
        other_human=other_human,
        other_tenant=other_tenant,
        tokens=tokens,
        client=client,
        headers={"Authorization": f"Bearer {tokens[human]}"},
        ctx=Context(tenant, human, human, category_id=category),
    )
    client.close()
