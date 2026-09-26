"""Actual Chat API observation, admitted Manifest and source/contract failures."""

from __future__ import annotations

import json
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from uuid import UUID

import httpx2
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import RowMapping, Table, select
from sqlalchemy.exc import DBAPIError

from app.ai import application_context
from app.ai.budget_ledger import BudgetLedger
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.ai.observations import digest
from app.contracts.runtime_records import ContextManifest, Observation
from app.db.engine import get_engine
from app.db.schema import metadata, tables
from tests import test_application_run_budget_api as api_factory
from tests.migration_fixtures import rollback_migration_operations
from tests.test_ai_api import api_context as api_context
from tests.test_ai_api import isolated_ai_api_database as isolated_ai_api_database
from tests.test_application_authorization import LedgerFixture
from tests.test_budget_ledger import SERVER_ROOT
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_chat_requests import ChatSetup
from tests.test_chat_requests import chat_setup as chat_setup

ApplicationContextSetup = tuple[
    TestClient, UUID, dict[str, str], dict[str, str], list[httpx2.Request]
]


def after[**P, R](function: Callable[P, R], action: Callable[[], None]) -> Callable[P, R]:
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        result = function(*args, **kwargs)
        action()
        return result

    return wrapped


def rows(table: Table) -> list[RowMapping]:
    with get_engine().connect() as c:
        return list(c.execute(select(table)).mappings())


@pytest.fixture
def setup(
    chat_setup: ChatSetup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ApplicationContextSetup:
    client, _, _, _, project, headers, body = chat_setup
    _, calls, _ = api_factory.factory(
        get_engine(),
        tmp_path,
        monkeypatch,
        output={
            "disposition": "answered",
            "claims": [{"text": "Project status", "citation_ids": [f"project:{project}"]}],
        },
    )
    return client, project, headers, body, calls


def answer(setup: ApplicationContextSetup) -> dict[str, object]:
    client, _, headers, body, _ = setup
    response = client.post("/api/ai/chat", headers=headers, json=body)
    assert response.status_code == 200, response.text
    result_body = response.json()
    assert isinstance(result_body, dict) and all(isinstance(key, str) for key in result_body)
    return result_body


def test_actual_observation_manifest_and_admission_are_linked(
    setup: ApplicationContextSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = api_factory.response

    def inspect(content: str) -> httpx2.Response:
        manifests = rows(tables.application_context_manifests)
        assert len(manifests) == 1
        assert any(r["dispatched_at"] is not None for r in rows(tables.budget_journal))
        return original(content)

    monkeypatch.setattr(api_factory, "response", inspect)
    assert answer(setup)["status"] == "answered"
    o = rows(tables.application_context_observations)[0]
    m = rows(tables.application_context_manifests)[0]
    observed = Observation.model_validate(o["metadata"])
    manifest = ContextManifest.model_validate(m["body"])
    assert observed.sources and observed.shown_count == len(o["output_body"])
    assert observed.status == "partial" and observed.total_count is None
    assert manifest.observation_ids == (o["id"],) and manifest.completeness == "partial"
    assert manifest.authorization_id == o["authorization_id"]
    assert manifest.selected_sources == observed.sources
    assert o["bundle"]["compiled"]["model_tools"] == []
    admitted = next(r for r in rows(tables.budget_journal) if r["id"] == m["admission_id"])
    assert manifest.estimated_input_tokens == admitted["input_tokens"] > 0
    assert manifest.reserved_output_tokens == admitted["output_tokens"] > 0
    assert manifest.digest == digest({k: v for k, v in m["body"].items() if k != "digest"})
    assert str(m["id"]) not in setup[-1][0].content.decode()
    checkpoint = rows(tables.application_result_checkpoints)[0]
    assert checkpoint["manifest_id"] == m["id"]
    assert checkpoint["body"]["output"]["claims"][0]["text"] == "Project status"


def test_structured_retry_uses_same_observation_and_distinct_admissions(
    setup: ApplicationContextSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = api_factory.response
    count = 0

    def invalid_first(content: str) -> httpx2.Response:
        nonlocal count
        count += 1
        return original("invalid" if count == 1 else content)

    monkeypatch.setattr(api_factory, "response", invalid_first)
    assert answer(setup)["status"] == "answered"
    manifests = sorted(rows(tables.application_context_manifests), key=lambda r: r["revision_no"])
    assert len(setup[-1]) == len(manifests) == 2
    assert manifests[1]["parent_revision_id"] == manifests[0]["id"]
    assert manifests[0]["observation_id"] == manifests[1]["observation_id"]
    assert manifests[0]["admission_id"] != manifests[1]["admission_id"]
    checkpoint = rows(tables.application_result_checkpoints)[0]
    assert checkpoint["manifest_id"] == manifests[1]["id"]
    assert checkpoint["body"]["structured_attempts"] == 2


@pytest.mark.parametrize("moment", ["before_meter", "after_reserve", "after_response"])
def test_source_change_stops_disclosure_and_keeps_real_usage(
    setup: ApplicationContextSetup, monkeypatch: pytest.MonkeyPatch, moment: str
) -> None:
    def change() -> None:
        with get_engine().begin() as c:
            c.execute(tables.projects.update().values(name="Changed after snapshot"))

    if moment == "before_meter":
        monkeypatch.setattr(
            application_context,
            "record_chat_context",
            after(application_context.record_chat_context, change),
        )
    elif moment == "after_reserve":
        monkeypatch.setattr(BudgetLedger, "reserve", after(BudgetLedger.reserve, change))
    else:
        original_response = api_factory.response

        def response(content: str) -> httpx2.Response:
            change()
            return original_response(content)

        monkeypatch.setattr(api_factory, "response", response)
    result = answer(setup)
    assert result["status"] == "unavailable" and result["answer"] is None
    assert result["error_code"] == "APPLICATION_CONTEXT_SOURCE_CHANGED"
    assert len(setup[-1]) == (1 if moment == "after_response" else 0)
    journal = rows(tables.budget_journal)
    if moment == "before_meter":
        assert not journal
    else:
        last = max(journal, key=lambda r: r["revision"])
        assert last["reservation_status"] == (
            "settled" if moment == "after_response" else "cancelled_before_dispatch"
        )


def test_bundle_is_json_stable_and_changed_bundle_cannot_continue(
    setup: ApplicationContextSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = application_context.chat_bundle
    initial = original()
    assert json.loads(json.dumps(initial)) == initial
    calls = 0

    def change(*, work_focus: bool = False) -> dict[str, object]:
        nonlocal calls
        calls += 1
        current = original(work_focus=work_focus)
        return current if calls == 1 else {**current, "version": "changed"}

    monkeypatch.setattr(application_context, "chat_bundle", change)
    assert answer(setup)["error_code"] == "APPLICATION_CONTEXT_BUNDLE_CHANGED"
    assert setup[-1] == []


def test_observation_and_manifest_are_immutable_and_history_blocks_downgrade(
    setup: ApplicationContextSetup,
) -> None:
    assert answer(setup)["status"] == "answered"
    for table in (tables.application_context_observations, tables.application_context_manifests):
        with pytest.raises(DBAPIError, match="append-only"), get_engine().begin() as c:
            c.execute(table.delete())
    with (
        rollback_migration_operations(get_engine()),
        pytest.raises(DBAPIError, match="persistent application context history"),
    ):
        import_module("migrations.versions.0082_application_context").downgrade()


@pytest.mark.parametrize("change", ["context", "prompt", "schema"])
def test_actual_outbound_contract_cannot_differ_from_recorded_input(
    setup: ApplicationContextSetup, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from tests.test_model_gateway import RiskOutput

    original = StructuredModelGateway.invoke_structured

    def changed[OutputT: BaseModel](
        self: StructuredModelGateway, invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT] | GatewayResult[RiskOutput]:
        if change == "context":
            invocation = invocation.model_copy(
                update={"context": {**invocation.context, "question": "Altered"}}
            )
        elif change == "prompt":
            invocation = invocation.model_copy(
                update={"system_prompt": invocation.system_prompt + "changed"}
            )
        else:
            return original(self, invocation, RiskOutput)
        return original(self, invocation, output_type)

    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", changed)
    result = answer(setup)
    assert result["error_code"] == (
        "APPLICATION_CONTEXT_CHANGED"
        if change == "context"
        else "APPLICATION_CONTEXT_CONTRACT_CHANGED"
    )
    assert setup[-1] == [] and rows(tables.application_context_manifests) == []


def test_database_dispatch_requires_manifest_even_if_application_hook_is_skipped(
    setup: ApplicationContextSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(application_context, "freeze_chat_manifest", lambda *a, **kw: None)
    assert answer(setup)["error_code"] == "BUDGET_APPLICATION_MANIFEST_REQUIRED"
    assert setup[-1] == [] and rows(tables.application_context_manifests) == []
    assert (
        max(rows(tables.budget_journal), key=lambda r: r["revision"])["reservation_status"]
        == "cancelled_before_dispatch"
    )


def test_physical_metadata_and_empty_context_migration_roundtrip(ledger_db: LedgerFixture) -> None:
    engine, _, _ = ledger_db
    with engine.connect() as c:
        context = MigrationContext.configure(
            c,
            opts=dict(
                include_schemas=True,
                include_object=lambda obj, name, kind, reflected, compared: (
                    kind != "table"
                    or name in {"application_context_observations", "application_context_manifests"}
                ),
            ),
        )
        assert compare_metadata(context, metadata) == []
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0081_application_authorization")
    command.upgrade(config, "head")
