"""Capture responses survive the actual ORM expiry at the transaction boundary."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next import change_implementation_owner as implementation
from pdos_next.change_order_store import ImplementationCapture
from pdos_next.domain.change_execution import api
from pdos_next.service import Context


def test_capture_response_materialized_before_commit_expiry(monkeypatch):
    tenant, actor, category, product, change, order, item, fact, original = (
        uuid4() for _ in range(9)
    )
    ctx = Context(tenant, actor, actor, category_id=category)
    at = datetime.now(UTC)
    row = ImplementationCapture(
        id=uuid4(), tenant_id=tenant, product_id=product, change_id=change,
        change_revision=7, revision=1, order_id=order, item_id=item, fact_id=fact,
        fact_snapshot={"id": str(fact), "outputs": [{"id": str(uuid4()), "revision": 2}]},
        required_source_read_set=[{"artifact_id": str(original), "expected_revision": 1}],
        source_basis={"internal": "not part of public response"},
        created_at=at, expires_at=at + timedelta(minutes=10),
    )
    captured_id = str(row.id)
    # Attach a detached actual mapped instance without SQL, then use SQLAlchemy's
    # real expiration/detachment behavior when the route exits its transaction.
    make_transient_to_detached(row)

    @contextmanager
    def transaction(*args, **kwargs):
        with Session() as session:
            session.add(row)
            yield session
            session.expire(row)
            session.expunge(row)

    def prepare(session, actual_ctx, actual_product, data):
        assert actual_ctx == ctx and actual_product == product
        assert data.change_id == change and data.item_id == item
        return row

    monkeypatch.setattr(api, "tenant_session", transaction)
    monkeypatch.setattr(implementation, "prepare_capture", prepare)
    app = FastAPI()
    api.register_routes(app, object(), Depends(lambda: ctx))
    with TestClient(app) as client:
        response = client.post(
            f"/v1/categories/{category}/products/{product}/change-execution/implementation-captures",
            json={
                "change_id": str(change), "expected_change_revision": 7,
                "visibility": "category", "capture_key": str(uuid4()),
                "order_id": str(order), "item_id": str(item),
                "source": {"id": str(original), "revision": 1, "kind": "artifact",
                           "position": "line:1;quote_sha256:" + "a" * 64},
            },
        )
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["id"] == captured_id and value["fact_id"] == str(fact)
    assert value["fact"]["id"] == str(fact) and value["fact"]["outputs"][0]["revision"] == 2
    assert value["required_source_read_set"] == [
        {"artifact_id": str(original), "expected_revision": 1}
    ]
    assert value["created_at"] == at.isoformat()
    assert set(value) == {
        "id", "revision", "change_id", "change_revision", "order_id", "item_id",
        "fact_id", "fact", "required_source_read_set", "created_at", "expires_at",
    }
