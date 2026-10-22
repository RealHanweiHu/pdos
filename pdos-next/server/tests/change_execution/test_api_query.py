"""Direct route query guards reject ambiguity before any tenant UOW opens."""

from contextlib import contextmanager
from uuid import UUID as CategoryUUID
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from pdos_next.contracts import Command
from pdos_next.domain.change_execution import api, service
from pdos_next.errors import DomainError
from pdos_next.service import Context


@pytest.fixture
def route(monkeypatch):
    app = FastAPI()
    opened = []
    actor, tenant, product = uuid4(), uuid4(), uuid4()
    ctx = Context(tenant, actor, actor, category_id=CategoryUUID(int=1000000))

    @app.exception_handler(DomainError)
    async def error_handler(request, error):
        return JSONResponse({"code": error.code}, status_code=error.status)

    @contextmanager
    def session(engine, tenant_id, **scope):
        opened.append(tenant_id)
        yield object()

    monkeypatch.setattr(api, "tenant_session", session)
    monkeypatch.setattr(service, "list_changes", lambda *a, **k: {"selection": k})
    api.register_routes(app, object(), Depends(lambda: ctx))
    with TestClient(app) as client:
        yield client, product, opened


@pytest.mark.parametrize("key", ["unknown", "scope"])
def test_unknown_get_query_is_rejected_before_uow(route, key):
    client, product, opened = route
    response = client.get(
        f"/v1/categories/{CategoryUUID(int=1000000)}/products/{product}/change-execution",
        params={key: str(uuid4())},
    )
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"
    assert opened == []


@pytest.mark.parametrize(
    "key", ["project_id", "issue_id", "change_id", "history_cursor", "capture_cursor"]
)
def test_duplicate_get_selection_is_rejected_before_uow(route, key):
    client, product, opened = route
    value = str(uuid4())
    response = client.get(
        f"/v1/categories/{CategoryUUID(int=1000000)}/products/{product}/change-execution",
        params=[(key, value), (key, value)],
    )
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"
    assert opened == []


def test_inputs_query_is_rejected_before_handler_or_uow(route):
    client, product, opened = route
    command = Command(
        command_id=uuid4(),
        idempotency_key=f"no-io-query:{uuid4()}",
        operation="evidence.artifact.register",
        product_id=product,
        expected_revision=1,
        payload={
            "title": "Synthetic no-IO unit",
            "source_label": "Synthetic",
            "content": "Synthetic",
            "visibility": "private",
        },
        category_id=CategoryUUID(int=1000000),
    )
    response = client.post(
        f"/v1/categories/{CategoryUUID(int=1000000)}/products/{product}/change-execution/inputs?unexpected=1",
        json=command.model_dump(mode="json"),
    )
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"
    assert opened == []


@pytest.mark.parametrize("key", ["project_id", "issue_id", "change_id"])
def test_single_explicit_selection_reaches_original_reader(route, key):
    client, product, opened = route
    selection = str(uuid4())
    response = client.get(
        f"/v1/categories/{CategoryUUID(int=1000000)}/products/{product}/change-execution",
        params={key: selection},
    )
    assert response.status_code == 200 and response.json()["selection"][key] == selection
    assert len(opened) == 1
