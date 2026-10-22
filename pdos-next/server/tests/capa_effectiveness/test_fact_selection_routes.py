"""Actual HTTP selector parsing: no candidate guesses, duplicate or foreign query paths."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from pdos_next import capa_fact_api as api
from pdos_next.errors import DomainError

PID = UUID("11111111-1111-4111-8111-111111111111")
ISSUE = UUID("22222222-2222-4222-8222-222222222222")
CANDIDATE = UUID("33333333-3333-4333-8333-333333333333")


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    context = SimpleNamespace(
        tenant_id=PID, actor_id=ISSUE, requester_id=ISSUE, category_id=CANDIDATE
    )

    @app.exception_handler(DomainError)
    def domain_error(_request, error):
        return JSONResponse({"code": error.code}, status_code=error.status)

    @contextmanager
    def session(_engine, tenant, **kwargs):
        assert kwargs["category_id"] == CANDIDATE
        assert tenant == context.tenant_id
        yield object()

    def selector(_s, actual, product, issue, candidate=None, history_cursor=None):
        assert history_cursor is None
        assert actual is context
        return {
            "product_id": str(product),
            "issue_id": str(issue),
            "candidate_id": str(candidate) if candidate else None,
        }

    monkeypatch.setattr(api, "tenant_session", session)
    monkeypatch.setattr(api, "fact_context", selector)
    from fastapi import Depends

    api.register_routes(app, object(), Depends(lambda: context))
    with TestClient(app) as result:
        yield result


def test_unselected_get_passes_none_and_never_guesses_oldest_candidate(client):
    response = client.get(f"/v1/categories/{CANDIDATE}/products/{PID}/capa-facts?issue_id={ISSUE}")
    assert response.status_code == 200
    assert response.json()["candidate_id"] is None


def test_selected_get_binds_only_the_explicit_uuid(client):
    response = client.get(
        f"/v1/categories/{CANDIDATE}/products/{PID}/capa-facts?issue_id={ISSUE}&candidate_id={CANDIDATE}"
    )
    assert response.status_code == 200
    assert response.json() == {
        "product_id": str(PID),
        "issue_id": str(ISSUE),
        "candidate_id": str(CANDIDATE),
    }


@pytest.mark.parametrize(
    "suffix",
    [
        f"&candidate_id={CANDIDATE}&candidate_id={CANDIDATE}",
        f"&issue_id={ISSUE}",
        "&candidate_id=latest",
        "&candidate_id=",
        "&revision=1",
        "&owner_id=anyone",
        "&authorized=true",
        "&applicable=true",
    ],
)
def test_candidate_query_cannot_override_or_ambiguously_choose_scope(client, suffix):
    assert (
        client.get(
            f"/v1/categories/{CANDIDATE}/products/{PID}/capa-facts?issue_id={ISSUE}{suffix}"
        ).status_code
        == 422
    )
