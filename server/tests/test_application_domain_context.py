"""Actual domain API source races, mandatory admission and trace lineage."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import TypedDict, Unpack
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, RowMapping, Table, select
from sqlalchemy.exc import DBAPIError

from app.ai import application_context, application_domain_context
from app.ai.budget_ledger import BudgetLedger
from app.db.engine import get_engine
from app.db.schema import tables
from tests import test_application_run_budget_api as api_factory
from tests.migration_fixtures import rollback_migration_operations
from tests.test_ai_api import api_context as api_context
from tests.test_ai_api import isolated_ai_api_database as isolated_ai_api_database
from tests.test_ai_api import seed_project_and_users, setup_owner
from tests.test_ai_test_plan_changes import READY, Gateway, suggest
from tests.test_ai_test_plan_changes import scenario as scenario
from tests.test_application_context import after
from tests.test_test_report_import_api import Scope
from tests.test_test_report_import_api import isolated_import_database as isolated_import_database

DomainSetup = tuple[Callable[[], httpx2.Response], Callable[[], None], list[httpx2.Request]]
Scenario = tuple[TestClient, Scope, Gateway, dict[str, str], str, dict[str, object]]


class DomainRecordArguments(TypedDict):
    tenant_id: UUID
    project_id: UUID | None
    run_id: UUID
    model_call_id: UUID
    purpose: str
    context: dict[str, object]
    snapshot: dict[str, object]


def rows(table: Table) -> list[RowMapping]:
    with get_engine().connect() as c:
        return list(c.execute(select(table)).mappings())


@pytest.fixture(params=["risk", "test_plan"])
def domain(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> DomainSetup:
    if request.param == "risk":
        api_context_value: tuple[TestClient, object, object] = request.getfixturevalue(
            "api_context"
        )
        client, _, _ = api_context_value
        tenant, _, headers = setup_owner(client)
        project, event = seed_project_and_users(
            request.getfixturevalue("isolated_ai_api_database"), tenant_id=tenant
        )
        output: dict[str, object] = dict(
            disposition="no_action",
            candidate_type=None,
            summary="No action.",
            proposed_payload=None,
            evidence_event_ids=[],
            confidence=0.8,
        )

        def invoke() -> httpx2.Response:
            return client.post(
                "/api/ai/create-risk-suggestion",
                headers=headers,
                json=dict(
                    project_id=str(project),
                    request_id=str(uuid4()),
                    concern="Synthetic risk",
                    evidence_event_ids=[event],
                ),
            )

        def change() -> None:
            with get_engine().begin() as c:
                c.execute(
                    tables.projects.update()
                    .where(tables.projects.c.id == project)
                    .values(name="Changed business source")
                )
    else:
        scenario_value: Scenario = request.getfixturevalue("scenario")
        plan_id = scenario_value[-1]["id"]
        assert isinstance(plan_id, str)
        plan = UUID(plan_id)
        output = {
            **READY,
            "changes": [
                {
                    **{k: v for k, v in item.items() if k != "references"},
                    "reference_ids": [r["reference_id"] for r in item["references"]],
                }
                for item in READY["changes"]
            ],
        }

        def invoke() -> httpx2.Response:
            response = suggest(scenario_value)
            assert isinstance(response, httpx2.Response)
            return response

        def change() -> None:
            with get_engine().begin() as c:
                c.execute(
                    tables.test_cases.update()
                    .where(tables.test_cases.c.plan_id == plan)
                    .values(method="Changed source test procedure")
                )

    _, calls, _ = api_factory.factory(
        get_engine(), tmp_path, monkeypatch, request=request, output=output
    )
    return invoke, change, calls


@pytest.mark.parametrize("moment", ["before_meter", "after_reserve", "after_response"])
def test_domain_source_race_blocks_output_and_preserves_actual_charge(
    domain: DomainSetup, monkeypatch: pytest.MonkeyPatch, moment: str
) -> None:
    invoke, change, calls = domain
    if moment == "before_meter":
        monkeypatch.setattr(
            application_domain_context, "record", after(application_domain_context.record, change)
        )
    elif moment == "after_reserve":
        monkeypatch.setattr(BudgetLedger, "reserve", after(BudgetLedger.reserve, change))
    else:
        original_response = api_factory.response

        def respond(content: str) -> httpx2.Response:
            change()
            return original_response(content)

        monkeypatch.setattr(api_factory, "response", respond)
    result = invoke()
    assert result.status_code == 200, result.text
    assert result.json()["error_code"] == "APPLICATION_CONTEXT_SOURCE_CHANGED", result.text
    assert len(calls) == (1 if moment == "after_response" else 0)
    assert rows(tables.findings) == []
    journal = rows(tables.budget_journal)
    if moment == "before_meter":
        assert journal == []
    else:
        last = max(journal, key=lambda r: r["revision"])
        assert last["reservation_status"] == (
            "settled" if moment == "after_response" else "cancelled_before_dispatch"
        )
        if moment == "after_response":
            assert last["charged_tokens"] == 10


def test_domain_database_requires_manifest_when_hook_is_skipped(
    domain: DomainSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(application_context, "freeze_chat_manifest", lambda *a, **kw: None)
    result = domain[0]()
    assert result.status_code == 200, result.text
    assert result.json()["error_code"] == "BUDGET_APPLICATION_MANIFEST_REQUIRED", result.text
    assert domain[2] == [] and rows(tables.application_context_manifests) == []


def test_observed_trace_requires_matching_call_and_domain_history_cannot_downgrade(
    domain: DomainSetup,
) -> None:
    result = domain[0]()
    assert result.status_code == 200, result.text
    assert result.json().get("error_code") is None, result.text
    trace = dict(rows(tables.model_invocations)[0])
    trace.update(id=uuid4(), budget_call_id=uuid4())
    with (
        pytest.raises(DBAPIError, match="BUDGET_APPLICATION_TRACE_MANIFEST_REQUIRED"),
        get_engine().begin() as c,
    ):
        c.execute(tables.model_invocations.insert().values(**trace))
    with (
        rollback_migration_operations(get_engine()),
        pytest.raises(DBAPIError, match="persistent domain application context history"),
    ):
        import_module("migrations.versions.0083_domain_context_adapters").downgrade()


def test_existing_trace_cannot_be_backfilled_with_new_observation(
    domain: DomainSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = application_domain_context.record

    def legacy(engine: Engine, **kwargs: Unpack[DomainRecordArguments]) -> None:
        prompt, _ = application_domain_context.contract(kwargs["purpose"])
        with get_engine().begin() as c:
            c.execute(
                tables.model_invocations.insert().values(
                    id=uuid4(),
                    tenant_id=kwargs["tenant_id"],
                    project_id=kwargs["project_id"],
                    run_id=kwargs["run_id"],
                    agent_key=prompt["agent_key"],
                    agent_tier="default",
                    prompt_version=prompt["version"],
                    provider="minimax",
                    model="fake-model",
                    protocol="openai-compatible",
                    status="succeeded",
                    structured_attempts=1,
                )
            )
        original(engine, **kwargs)

    monkeypatch.setattr(application_domain_context, "record", legacy)
    result = domain[0]()
    assert result.status_code == 200, result.text
    assert result.json()["error_code"] == "APPLICATION_CONTEXT_HISTORY_UNAVAILABLE", result.text
    assert domain[2] == [] and rows(tables.application_context_observations) == []


def test_actual_domain_request_expiry_is_visible_and_never_calls_model(
    domain: DomainSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import func

    original = application_domain_context.record

    def record(engine: Engine, **kwargs: Unpack[DomainRecordArguments]) -> None:
        original(engine, **kwargs)
        with get_engine().begin() as c:
            c.execute(
                tables.application_run_leases.update()
                .where(
                    tables.application_run_leases.c.run_id == kwargs["run_id"],
                )
                .values(expires_at=func.clock_timestamp())
            )

    monkeypatch.setattr(application_domain_context, "record", record)
    result = domain[0]()
    assert result.status_code == 200, result.text
    assert result.json()["error_code"] == "APPLICATION_RUN_LEASE_LOST", result.text
    assert domain[2] == [] and rows(tables.findings) == []
    assert rows(tables.application_run_leases)[0]["ended_at"] is not None


def test_database_rejects_finding_if_service_skips_owner_binding(
    scenario: Scenario,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    from app.ai import test_plan_suggestions

    output = {
        **READY,
        "changes": [
            {
                **{k: v for k, v in item.items() if k != "references"},
                "reference_ids": [r["reference_id"] for r in item["references"]],
            }
            for item in READY["changes"]
        ],
    }
    _, calls, _ = api_factory.factory(
        get_engine(), tmp_path, monkeypatch, request=request, output=output
    )
    monkeypatch.setattr(test_plan_suggestions, "bind_write", lambda *a, **kw: None)
    result = suggest(scenario)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "unavailable"
    assert result.json()["error_code"] == "TEST_PLAN_MODEL_FAILED"
    assert len(calls) == 1 and rows(tables.findings) == []
