"""Actual APIs: budget bindings predate inference and follow the conversation."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import Connection, Engine, select

from app.ai import application_gateway
from app.ai.budget_adoption import METER_DIGEST_KEY, METER_PATH_KEY, MODE_KEY, PROFILE_KEY
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.api.ai import get_application_gateway
from app.db.engine import get_engine
from app.db.schema import tables
from app.main import app
from tests.test_ai_api import api_context as api_context
from tests.test_ai_api import isolated_ai_api_database as isolated_ai_api_database
from tests.test_ai_api import seed_project_and_users, setup_owner
from tests.test_ai_test_plan_changes import READY, Gateway, suggest
from tests.test_ai_test_plan_changes import scenario as scenario
from tests.test_chat_requests import ApiContext
from tests.test_input_metering import publication, save
from tests.test_model_budget_controller import response as response
from tests.test_model_gateway import qualification
from tests.test_test_report_import_api import Scope
from tests.test_test_report_import_api import isolated_import_database as isolated_import_database

FactoryResult = tuple[dict[str, str], list[httpx2.Request], list[dict[str, object]]]
PlanScenario = tuple[TestClient, Scope, Gateway, dict[str, str], str, dict[str, object]]


def install_gateway(request: pytest.FixtureRequest, dependency: Callable[..., Any]) -> None:
    """Restore the owned dictionary before a later owner can reveal it again."""
    missing = object()
    owned_overrides = app.dependency_overrides
    previous = owned_overrides.get(get_application_gateway, missing)

    def restore_gateway() -> None:
        if owned_overrides.get(get_application_gateway, missing) is not dependency:
            return
        if previous is missing:
            owned_overrides.pop(get_application_gateway, None)
        else:
            owned_overrides[get_application_gateway] = cast(Callable[..., Any], previous)

    request.addfinalizer(restore_gateway)
    owned_overrides[get_application_gateway] = dependency


def factory(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    request: pytest.FixtureRequest,
    output: dict[str, object],
) -> FactoryResult:
    path, doc, _ = publication(tmp_path, qualified_input_limit=32000)
    doc["models"][0]["window_tokens"] = 64000
    digest = save(path, doc)
    calls: list[httpx2.Request] = []
    snapshots: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        with engine.connect() as c:
            assert len(c.execute(select(tables.application_context_manifests)).all()) == len(calls)
        return response(json.dumps(output))

    original_client = httpx2.Client
    monkeypatch.setattr(
        httpx2,
        "Client",
        lambda **kw: original_client(transport=httpx2.MockTransport(respond), **kw),
    )
    monkeypatch.setattr(
        application_gateway, "load_golden_qualifications", lambda *a, **kw: [qualification()]
    )
    original_invoke = StructuredModelGateway.invoke_structured

    def observe[OutputT: BaseModel](
        gateway: StructuredModelGateway, invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        # A separate connection sees the committed binding before Gateway starts.
        with engine.connect() as c:
            span = (
                c.execute(
                    select(tables.budget_activity_spans).where(
                        tables.budget_activity_spans.c.run_id == invocation.run_id
                    )
                )
                .mappings()
                .one()
            )
            assert span["stopped_at"] is None
            link = (
                c.execute(
                    select(tables.budget_run_links).where(
                        tables.budget_run_links.c.run_id == invocation.run_id
                    )
                )
                .mappings()
                .one()
            )
            frozen = (
                c.execute(
                    select(tables.budget_lineages).where(
                        tables.budget_lineages.c.id == link["lineage_id"]
                    )
                )
                .mappings()
                .one()
            )
            assert (
                c.execute(
                    select(tables.budget_journal).where(
                        tables.budget_journal.c.run_id == invocation.run_id
                    )
                ).first()
                is None
            )
            snapshots.append(dict(frozen))
            authorization = (
                c.execute(
                    select(tables.application_authorizations).where(
                        tables.application_authorizations.c.run_id == invocation.run_id
                    )
                )
                .mappings()
                .one()
            )
            assert authorization["lineage_id"] == link["lineage_id"]
            assert authorization["body"]["principal_kind"] == "user"
            assert authorization["expires_at"] <= frozen["absolute_deadline"]
        return original_invoke(gateway, invocation, output_type)

    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", observe)
    environment = {
        "PDOS_LLM_PROVIDER": "minimax",
        "PDOS_LLM_MODEL": "MiniMax-M2.7",
        "PDOS_LLM_BASE_URL": "https://fake-openai.local/v1",
        "PDOS_LLM_API_KEY": "test-only",
        MODE_KEY: "budgeted",
        PROFILE_KEY: "short",
        METER_PATH_KEY: str(path),
        METER_DIGEST_KEY: digest,
    }

    def configured() -> Iterator[StructuredModelGateway]:
        with application_gateway.configured_application_gateway(engine, environment) as gateway:
            yield gateway

    install_gateway(request, configured)
    return environment, calls, snapshots


def test_risk_api_budget_predates_inference_and_replay_does_not_reset(
    request: pytest.FixtureRequest,
    api_context: ApiContext,
    isolated_ai_api_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = api_context
    tenant, _, headers = setup_owner(client)
    project, event_id = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant)
    _, calls, frozen = factory(
        get_engine(),
        tmp_path,
        monkeypatch,
        request=request,
        output=dict(
            disposition="no_action",
            candidate_type=None,
            summary="No supported action.",
            proposed_payload=None,
            evidence_event_ids=[],
            confidence=0.8,
        ),
    )
    body = dict(
        project_id=str(project),
        request_id=str(uuid4()),
        concern="Review project risk",
        evidence_event_ids=[event_id],
    )
    first = client.post("/api/ai/create-risk-suggestion", headers=headers, json=body)
    assert first.status_code == 200 and first.json()["status"] == "no_action", first.text
    assert (
        client.post("/api/ai/create-risk-suggestion", headers=headers, json=body).json()
        == first.json()
    )
    assert len(calls) == len(frozen) == 1
    with get_engine().connect() as c:
        assert dict(c.execute(select(tables.budget_lineages)).mappings().one()) == frozen[0]
        checkpoint = c.execute(select(tables.application_result_checkpoints)).mappings().one()
        assert checkpoint["body"]["output"]["disposition"] == "no_action"

        span = c.execute(select(tables.budget_activity_spans)).mappings().one()
        assert span["stopped_at"] >= span["started_at"]


@pytest.mark.parametrize("continuation", ["budgeted", "legacy", "unbound_parent"])
def test_test_plan_conversation_inherits_budget_and_cannot_reset_by_mode(
    request: pytest.FixtureRequest,
    scenario: PlanScenario,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: str,
) -> None:
    _, scope, _, _, _, _ = scenario
    output = {
        **READY,
        "changes": [
            {
                **{k: v for k, v in item.items() if k != "references"},
                "reference_ids": [ref["reference_id"] for ref in item["references"]],
            }
            for item in READY["changes"]
        ],
    }
    if continuation == "unbound_parent":
        initial = suggest(scenario)
        assert initial.status_code == 200 and initial.json()["status"] == "created", initial.text
    environment, calls, snapshots = factory(
        scope.engine, tmp_path, monkeypatch, request=request, output=output
    )
    if continuation != "unbound_parent":
        initial = suggest(scenario)
        assert initial.status_code == 200 and initial.json()["status"] == "created", initial.text
    previous = initial.json()["finding_id"]
    if continuation == "legacy":
        for key in (MODE_KEY, PROFILE_KEY, METER_PATH_KEY, METER_DIGEST_KEY):
            environment.pop(key)
        denied = suggest(scenario, previous_finding_id=previous)
        assert (
            denied.status_code == 200
            and denied.json()["error_code"] == "MODEL_CALL_BUDGET_REQUIRED"
        ), denied.text
        assert len(calls) == 1 and len(snapshots) == 2
    elif continuation == "unbound_parent":
        with scope.engine.connect() as c:
            runs_before = list(c.execute(select(tables.agent_runs.c.id)).scalars())
        denied = suggest(scenario, previous_finding_id=previous)
        assert denied.status_code == 409 and "BUDGET_PARENT_RUN_UNBOUND" in denied.text, denied.text
        assert calls == [] and snapshots == []
        with scope.engine.connect() as c:
            assert list(c.execute(select(tables.agent_runs.c.id)).scalars()) == runs_before
            assert c.execute(select(tables.budget_lineages)).first() is None
        return
    else:
        for _ in range(2):
            following = suggest(scenario, previous_finding_id=previous)
            assert following.status_code == 200 and following.json()["status"] == "created", (
                following.text
            )
            previous = following.json()["finding_id"]
        fourth = suggest(scenario, previous_finding_id=previous)
        assert fourth.status_code == 200 and fourth.json()["status"] == "unavailable", fourth.text
        assert fourth.json()["error_code"] == "BUDGET_CALL_COUNT_EXHAUSTED"
        assert len(calls) == 3 and len(snapshots) == 4
    assert all(snapshot == snapshots[0] for snapshot in snapshots)
    with scope.engine.connect() as c:
        assert c.execute(select(tables.budget_lineages.c.id)).scalars().all() == [
            snapshots[0]["id"]
        ]
        assert len(c.execute(select(tables.budget_run_links)).all()) == len(snapshots)
        spans = list(c.execute(select(tables.budget_activity_spans)).mappings())
        assert len(spans) == len(snapshots)
        assert all(span["stopped_at"] is not None for span in spans)
        checkpoints = list(c.execute(select(tables.application_result_checkpoints)).mappings())
        assert len(checkpoints) == len(calls)
        assert all(row["body"]["output"] == output for row in checkpoints)


@pytest.mark.parametrize("entry", ["chat", "risk"])
def test_creation_rechecks_original_login_and_returns_forbidden(
    request: pytest.FixtureRequest,
    api_context: ApiContext,
    isolated_ai_api_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    from app.ai import application_authorization

    client, _, _ = api_context
    tenant, actor, headers = setup_owner(client)
    project, event_id = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant)
    _, calls, _ = factory(get_engine(), tmp_path, monkeypatch, request=request, output={})
    original = application_authorization.issue_application_authorization

    def changed(
        connection: Connection,
        *,
        tenant_id: UUID,
        run_id: UUID,
        actor_user_id: UUID,
        purpose: str,
        auth_version: int | None = None,
    ) -> None:
        assert auth_version is not None
        connection.execute(
            tables.users.update()
            .where(tables.users.c.id == actor)
            .values(auth_version=tables.users.c.auth_version + 1)
        )
        return original(
            connection,
            tenant_id=tenant_id,
            run_id=run_id,
            actor_user_id=actor_user_id,
            purpose=purpose,
            auth_version=auth_version,
        )

    monkeypatch.setattr(application_authorization, "issue_application_authorization", changed)
    body: dict[str, object] = dict(project_id=str(project), request_id=str(uuid4()))
    if entry == "chat":
        body["question"] = "Synthetic status question"
        route = "/api/ai/chat"
    else:
        body.update(concern="Synthetic risk question", evidence_event_ids=[event_id])
        route = "/api/ai/create-risk-suggestion"
    response = client.post(route, headers=headers, json=body)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "APPLICATION_AUTHORIZATION_DENIED"
    assert calls == []
    with get_engine().connect() as c:
        assert c.execute(select(tables.application_authorizations)).first() is None
        assert c.execute(select(tables.budget_run_links)).first() is None


def test_test_plan_creation_rejects_changed_session_as_forbidden(
    request: pytest.FixtureRequest,
    scenario: PlanScenario,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai import application_authorization

    _, scope, _, _, _, _ = scenario
    _, calls, _ = factory(scope.engine, tmp_path, monkeypatch, request=request, output={})
    original = application_authorization.issue_application_authorization

    def changed(
        connection: Connection,
        *,
        tenant_id: UUID,
        run_id: UUID,
        actor_user_id: UUID,
        purpose: str,
        auth_version: int | None = None,
    ) -> None:
        assert auth_version is not None
        connection.execute(
            tables.users.update()
            .where(tables.users.c.id == actor_user_id)
            .values(auth_version=tables.users.c.auth_version + 1)
        )
        return original(
            connection,
            tenant_id=tenant_id,
            run_id=run_id,
            actor_user_id=actor_user_id,
            purpose=purpose,
            auth_version=auth_version,
        )

    monkeypatch.setattr(application_authorization, "issue_application_authorization", changed)
    response = suggest(scenario)
    assert response.status_code == 403, response.text
    assert calls == []
    with scope.engine.connect() as c:
        assert c.execute(select(tables.application_authorizations)).first() is None
        assert c.execute(select(tables.budget_run_links)).first() is None
