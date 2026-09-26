"""Actual factory, bounded protocol and PostgreSQL journal; synthetic transport only."""

import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy import select

from app.ai import application_gateway
from app.ai.budget_adoption import (
    METER_DIGEST_KEY,
    METER_PATH_KEY,
    MODE_KEY,
    PROFILE_KEY,
    approved_budget_profile,
)
from app.ai.input_metering import MeteringError
from app.ai.run_budget_creation import freeze_created_application_run
from app.db.schema import tables
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_input_metering import publication
from tests.test_model_budget_controller import response as response
from tests.test_model_gateway import RiskOutput, invocation, qualification
from tests.test_run_budget_creation import LedgerFixture, new_run

FactoryFixture = tuple[dict[str, str], list[httpx2.Request], Path]


@pytest.fixture
def factory_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FactoryFixture:
    path, _, digest = publication(tmp_path)
    calls: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return response()

    client_class = httpx2.Client
    monkeypatch.setattr(
        httpx2,
        "Client",
        lambda **kwargs: client_class(transport=httpx2.MockTransport(respond), **kwargs),
    )
    # Synthetic golden results exist only in this test process, never in golden files.
    monkeypatch.setattr(
        application_gateway, "load_golden_qualifications", lambda *a, **kw: [qualification()]
    )
    environment = {
        "PDOS_LLM_PROVIDER": "minimax",
        "PDOS_LLM_BASE_URL": "https://fake-openai.local/v1",
        "PDOS_LLM_API_KEY": "test-secret",
        "PDOS_LLM_MODEL": "MiniMax-M2.7",
        MODE_KEY: "budgeted",
        PROFILE_KEY: "short",
        METER_PATH_KEY: str(path),
        METER_DIGEST_KEY: digest,
    }
    return environment, calls, path


def test_factory_reads_creation_profile_bounds_wire_and_rejects_replay_or_hot_switch(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, runs = ledger_db
    environment, calls, _ = factory_setup
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        with engine.begin() as c:
            created = new_run(c)
            run_id = created["id"]
            assert isinstance(run_id, UUID)
            freeze_created_application_run(c, gateway, tenant_id=tenant, run_id=run_id)
        request = invocation(tenant, run_id=created["id"], model_call_id=uuid4())
        result = gateway.invoke_structured(request, RiskOutput)
        assert result.status == "succeeded"
        replay = gateway.invoke_structured(request, RiskOutput)
        assert replay.error_code == "BUDGET_ATTEMPT_ALREADY_DISPATCHED"
    with application_gateway.configured_application_gateway(
        engine, {**environment, PROFILE_KEY: "research_discussion"}
    ) as changed:
        denied = changed.invoke_structured(
            invocation(tenant, run_id=created["id"], model_call_id=uuid4()), RiskOutput
        )
        assert denied.error_code == "BUDGET_PROFILE_CONFLICT"
    assert len(calls) == 1
    assert json.loads(calls[0].content)["max_completion_tokens"] == 64
    with engine.connect() as c:
        lineage = c.execute(select(tables.budget_lineages)).mappings().one()
        assert lineage["profile"] == approved_budget_profile("short").model_dump(mode="json")
        journal = list(
            c.execute(
                select(tables.budget_journal).order_by(tables.budget_journal.c.revision)
            ).mappings()
        )
        assert len(journal) == 3
        assert [r["dispatched_at"] is not None for r in journal] == [False, True, True]
        assert journal[-1]["reservation_status"] == "settled"
        assert journal[-1]["charged_tokens"] == 10 and journal[-1]["held_tokens"] == 0
        assert journal[0]["request_binding"]["qualification_ref"].startswith("meter-publication:")


def test_factory_runless_invocation_fails_without_provider_call(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        denied = gateway.invoke_structured(invocation(tenant), RiskOutput)
    assert denied.error_code == "BUDGET_CALL_IDENTITY_REQUIRED"
    assert calls == []
    with engine.connect() as c:
        assert c.execute(select(tables.budget_journal)).first() is None


def test_factory_invalid_meter_publication_has_no_legacy_fallback(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, _, _ = ledger_db
    environment, calls, path = factory_setup
    path.write_text("{}")
    with (
        pytest.raises(MeteringError),
        application_gateway.configured_application_gateway(engine, environment),
    ):
        pytest.fail("invalid adoption yielded a gateway")
    assert calls == []


def test_factory_legacy_default_keeps_existing_unbounded_protocol(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    legacy = {
        key: value for key, value in environment.items() if not key.startswith("PDOS_APPLICATION_")
    }
    with application_gateway.configured_application_gateway(engine, legacy) as gateway:
        assert gateway.invoke_structured(invocation(tenant), RiskOutput).status == "succeeded"
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert "max_completion_tokens" not in body and "max_tokens" not in body
    with engine.connect() as c:
        assert c.execute(select(tables.budget_lineages)).first() is None


def test_factory_does_not_assign_new_budget_to_committed_unbound_run(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, runs = ledger_db
    environment, calls, _ = factory_setup
    with application_gateway.configured_application_gateway(engine, environment) as gateway:
        result = gateway.invoke_structured(
            invocation(tenant, run_id=runs[0], model_call_id=uuid4()),
            RiskOutput,
        )
    assert result.error_code == "BUDGET_RUN_UNBOUND" and calls == []
    with engine.connect() as c:
        assert c.execute(select(tables.budget_lineages)).first() is None
