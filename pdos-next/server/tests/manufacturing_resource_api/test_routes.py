"""Thin-route parsing/serialization/rollback checks, without real owner qualification IO."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from pdos_next.domain.manufacturing_resource_owner import api
from pdos_next.domain.manufacturing_resource_owner.schemas import (
    ResourceProjection,
    ResourceRelation,
    ResourceRequest,
    ResourceView,
    VersionRef,
)
from pdos_next.errors import DomainError
from pdos_next.service import Context

TENANT, PRODUCT, BUILD, PROJECT, PROCESS, ACTOR, FACT, RESOURCE = (
    UUID(int=index) for index in range(1, 9)
)
CATEGORY = UUID(int=1000000)
REAL_INSPECT = api.owner.inspect_resource


def input_body():
    return {
        "project_id": str(PROJECT),
        "expected_build_revision": 3,
        "process": {"id": str(PROCESS), "revision": 7},
        "execution": {
            "purpose": "synthetic route-contract inspection",
            "quantity": "2.125",
            "unit": "piece",
            "site": "synthetic-site",
            "window": {
                "start": "2030-01-01T00:00:00Z",
                "finish": "2030-01-01T00:30:00Z",
                "original_timezone": "UTC",
            },
        },
        "operation_key": "OP_1",
    }


class PrivateRead:
    """A projection carrier; trying to encode its internal proof must fail."""

    def __init__(self, view):
        self.view = view

    def __getattr__(self, key):
        raise AssertionError(f"API accessed a server-private proof field: {key}")

    def __iter__(self):
        raise AssertionError("API tried to serialize the opaque ResourceRead")


@dataclass
class RouteState:
    context: Context = field(
        default_factory=lambda: Context(TENANT, ACTOR, ACTOR, category_id=CATEGORY)
    )
    sessions: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    fail: DomainError | None = None
    view_factory: object = None
    auth_error: DomainError | None = None
    session: object = field(default_factory=object)


def unknown_view(selection):
    return ResourceView(
        request=selection,
        state="unknown",
        current=False,
        facts_revision="a" * 64,
        valid_until=datetime(2030, 1, 1, tzinfo=UTC),
        gaps=("GLOBAL_PROCESS_RESOURCE_CLOSURE_UNKNOWN",),
    )


@pytest.fixture
def route(monkeypatch):
    state = RouteState(view_factory=unknown_view)
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def domain_error(_request, error):
        return JSONResponse(error.payload(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _error):
        return JSONResponse(
            DomainError("INVALID_PAYLOAD", "输入无效。", 422).payload(), status_code=422
        )

    def authenticated():
        if state.auth_error:
            raise state.auth_error
        return state.context

    engine = object()

    @contextmanager
    def tenant_session(actual_engine, tenant, **binding):
        assert actual_engine is engine
        assert binding == {
            "actor_id": state.context.actor_id,
            "requester_id": state.context.requester_id,
            "category_id": CATEGORY,
        }
        state.sessions.append(("begin", tenant))
        try:
            yield state.session
        except BaseException:
            state.sessions.append(("rollback", tenant))
            raise
        else:
            state.sessions.append(("end", tenant))

    def inspect(session, context, product_id, *, request):
        assert session is state.session and context is state.context
        assert type(request) is ResourceRequest
        state.calls.append((product_id, request))
        if state.fail:
            raise state.fail
        return PrivateRead(state.view_factory(request))

    monkeypatch.setattr(api, "tenant_session", tenant_session)
    monkeypatch.setattr(api.owner, "inspect_resource", inspect)
    api.register_routes(app, engine, Depends(authenticated))
    with TestClient(app) as client:
        yield client, state


def url(product=PRODUCT, build=BUILD):
    return f"/v1/categories/{CATEGORY}/products/{product}/builds/{build}/resources/inspect"


def test_only_url_and_context_bind_roots_and_opaque_proof_stays_private(route):
    client, state = route
    response = client.post(url(), json=input_body())
    assert response.status_code == 200
    assert state.sessions == [("begin", TENANT), ("end", TENANT)]
    product, selection = state.calls[0]
    assert product == PRODUCT
    assert selection.scope.tenant_id == TENANT
    assert selection.scope.product_id == PRODUCT and selection.scope.project_id == PROJECT
    assert selection.build == VersionRef(id=BUILD, revision=3)
    assert selection.process == VersionRef(id=PROCESS, revision=7)
    assert selection.operation_key == "OP_1"
    assert selection.resource is None and selection.fact is None
    assert str(selection.execution.quantity) == "2.125"
    assert response.json() == unknown_view(selection).model_dump(mode="json")
    assert not response.json()["execution_authorized"]
    assert not response.json()["negative_enumeration_complete"]


@pytest.mark.parametrize(
    "key",
    [
        "tenant_id",
        "product_id",
        "build_id",
        "scope",
        "owner_id",
        "actor_id",
        "authority",
        "source_read_set",
        "opaque_token",
        "basis",
        "accepted",
        "command_id",
    ],
)
def test_body_cannot_supply_scope_authority_proof_or_write_command(route, key):
    client, state = route
    data = input_body()
    data[key] = str(UUID(int=900))
    response = client.post(url(), json=data)
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["detail"]["reason"] == "INVALID_PAYLOAD"
    assert state.sessions == [] and state.calls == []


@pytest.mark.parametrize("suffix", ["?resource_id=x", "?revision=1", "?fact_id=x&fact_id=x"])
def test_no_parallel_query_selector_or_duplicate_query(route, suffix):
    client, state = route
    response = client.post(url() + suffix, json=input_body())
    assert response.status_code == 422 and state.sessions == [] and state.calls == []


@pytest.mark.parametrize(
    "case",
    [
        "missing_process",
        "bool_revision",
        "string_revision",
        "float_quantity",
        "bad_window",
        "nested_authority",
        "partial_fact",
        "wrong_kind",
    ],
)
def test_closed_nested_exact_selection_rejects_ambiguity_before_uow(route, case):
    client, state = route
    data = input_body()
    if case == "missing_process":
        del data["process"]
    elif case == "bool_revision":
        data["expected_build_revision"] = True
    elif case == "string_revision":
        data["process"]["revision"] = "7"
    elif case == "float_quantity":
        data["execution"]["quantity"] = 2.125
    elif case == "bad_window":
        data["execution"]["window"]["finish"] = data["execution"]["window"]["start"]
    elif case == "nested_authority":
        data["execution"]["authorized"] = True
    elif case == "partial_fact":
        data["fact"] = {"id": str(FACT)}
    else:
        data["resource"] = {"id": str(RESOURCE), "revision": 1, "kind": "fixture.accept"}
    assert client.post(url(), json=data).status_code == 422
    assert state.sessions == [] and state.calls == []


def test_historical_fact_and_exact_resource_are_passed_without_selecting_current(route):
    client, state = route
    data = input_body()
    data["fact"] = {"id": str(FACT), "revision": 4}
    data["resource"] = {"id": str(RESOURCE), "revision": 6, "kind": "fixture"}

    def historical(selection):
        return unknown_view(selection).model_copy(
            update={
                "state": "historical",
                "fact": selection.fact,
                "nature": "synthetic",
                "fact_valid_until": datetime(2025, 1, 1, tzinfo=UTC),
            }
        )

    state.view_factory = historical
    response = client.post(url(), json=data)
    assert response.status_code == 200
    selection = state.calls[0][1]
    assert selection.fact == VersionRef(id=FACT, revision=4)
    assert selection.resource.id == RESOURCE and selection.resource.kind == "fixture"
    assert not response.json()["current"]
    assert response.json()["state"] == "historical"
    assert response.json()["fact_valid_until"] == "2025-01-01T00:00:00Z"


def test_complete_20_source_readset_and_relation_originals_are_preserved(route):
    client, state = route
    readset = tuple(
        {"artifact_id": UUID(int=100 + n), "expected_revision": n + 1} for n in range(20)
    )
    originals = tuple(
        {**read, "line": n + 1, "quote": f"Synthetic original position {n}"}
        for n, read in enumerate(readset)
    )
    resource = {"id": RESOURCE, "revision": 6, "kind": "tooling"}

    def full(selection):
        return ResourceView(
            request=selection,
            state="known",
            current=True,
            fact=VersionRef(id=FACT, revision=4),
            fact_sha256="b" * 64,
            nature="synthetic",
            resources=(
                ResourceProjection(
                    resource=resource,
                    lifecycle="active",
                    current=True,
                    originals=originals,
                ),
            ),
            relations=(
                ResourceRelation(
                    build=selection.build,
                    process=selection.process,
                    operation_key=selection.operation_key,
                    resource=resource,
                    units="2",
                    relation_source={
                        "kind": "domain",
                        "id": FACT,
                        "revision": 4,
                        "position": "requirements[0].uses[0]",
                    },
                    relation_originals=originals,
                ),
            ),
            required_source_read_set=readset,
            facts_revision="c" * 64,
            valid_until=datetime(2030, 1, 1, tzinfo=UTC),
            fact_valid_until=datetime(2030, 1, 1, tzinfo=UTC),
            gaps=("NATIVE_ACCEPTANCE_OWNER_UNCONNECTED",),
        )

    state.view_factory = full
    response = client.post(url(), json=input_body())
    assert response.status_code == 200
    assert response.json() == full(state.calls[0][1]).model_dump(mode="json")
    relation = response.json()["relations"][0]
    assert len(response.json()["required_source_read_set"]) == 20
    assert relation["relation_source"]["position"] == "requirements[0].uses[0]"
    assert len(relation["relation_originals"]) == 20
    assert response.json()["resources"][0]["acceptance"] == "unknown"


@pytest.mark.parametrize(
    "code,status",
    [
        ("FORBIDDEN_SCOPE", 403),
        ("RESOURCE_RECHECK_REQUIRED", 409),
        ("RESOURCE_PEOPLE_NOWAIT_REQUIRED", 503),
    ],
)
def test_owner_failure_propagates_without_unknown_fallback_and_exits_uow(route, code, status):
    client, state = route
    state.fail = DomainError(code, "Concrete owner guard failed", status)
    response = client.post(url(), json=input_body())
    assert response.status_code == status and response.json()["code"] == state.fail.code
    assert response.json()["detail"]["reason"] == code
    assert state.sessions == [("begin", TENANT), ("rollback", TENANT)]
    assert len(state.calls) == 1


def test_failed_authentication_never_opens_tenant_uow(route):
    client, state = route
    state.auth_error = DomainError("UNAUTHENTICATED", "请先登录。", 401)
    assert client.post(url(), json=input_body()).status_code == 401
    assert state.sessions == [] and state.calls == []


def test_real_owner_rejects_agent_context_before_any_owner_io(route, monkeypatch):
    client, state = route
    state.context = Context(TENANT, ACTOR, ACTOR, run_id=UUID(int=999), category_id=CATEGORY)
    monkeypatch.setattr(api.owner, "inspect_resource", REAL_INSPECT)
    response = client.post(url(), json=input_body())
    assert response.status_code == 409 and response.json()["code"] == "SOURCE_STALE"
    assert response.json()["detail"]["reason"] == "RESOURCE_RECHECK_REQUIRED"
    assert state.sessions == [("begin", TENANT), ("rollback", TENANT)]


def test_no_asset_global_route_or_implicit_build_guess_exists(route):
    client, state = route
    assert (
        client.post(
            f"/v1/products/{PRODUCT}/resources/{RESOURCE}/inspect", json=input_body()
        ).status_code
        == 404
    )
    assert state.sessions == [] and state.calls == []
