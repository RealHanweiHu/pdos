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
from pdos_next.models import Grant, LoginSession, Principal, Product, now
from pdos_next.safety import verify_test_target
from pdos_next.service import Context, digest


@pytest.fixture(scope="session")
def engines():
    admin = engine_for(os.environ["TEST_DATABASE_URL"])
    verify_test_target(admin)
    app = engine_for(os.environ["DATABASE_URL"])
    verify_test_target(app)
    auth = engine_for(os.environ["AUTH_DATABASE_URL"])
    yield admin, app, auth
    for engine in (admin, app, auth):
        engine.dispose()


@pytest.fixture
def setup(engines):
    admin, app, auth = engines
    tenant, human, peer, agent, other_tenant, other_human = (uuid4() for _ in range(6))
    product = uuid4()
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
        s.add(
            Product(
                id=product,
                tenant_id=tenant,
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
                    product_id=product,
                    principal_id=p,
                    can_write=True,
                    expires_at=now() + timedelta(hours=1),
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
                    expires_at=now() + timedelta(hours=1),
                )
                for p, token in tokens.items()
            ]
        )
    client = TestClient(create_app(app, auth))
    yield SimpleNamespace(
        admin=admin,
        engine=app,
        auth=auth,
        tenant=tenant,
        human=human,
        peer=peer,
        agent=agent,
        product=product,
        other_human=other_human,
        tokens=tokens,
        client=client,
        headers={"Authorization": f"Bearer {tokens[human]}"},
        ctx=Context(tenant, human, human),
    )
    client.close()
