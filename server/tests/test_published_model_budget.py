"""Published counting reaches the real journal, and revocation cancels before dispatch."""

from pathlib import Path
from typing import Unpack
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy import Engine, select

from app.ai.budget_ledger import BudgetLedger, BudgetReceipt
from app.ai.egress import ProviderEgressPolicy
from app.ai.model_budget import ModelBudgetController
from app.db.schema import tables
from tests.test_application_authorization import ReserveArguments
from tests.test_budget_ledger import LedgerFixture, profile
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_input_metering import publication
from tests.test_model_budget_controller import gateway, response
from tests.test_model_gateway import RiskOutput, catalog, invocation, qualification


def published(
    engine: Engine,
    client: httpx2.Client,
    path: Path,
    digest: str,
    ledger: BudgetLedger | None = None,
) -> ModelBudgetController:
    return ModelBudgetController.from_publication(
        ledger or BudgetLedger(engine),
        profile=profile(input_token_limit=512, lineage_token_limit=2000),
        path=path,
        expected_sha256=digest,
        qualifications=[qualification()],
        client=client,
        egress_policy=ProviderEgressPolicy.from_catalog(catalog()),
    )


def test_published_meter_is_recorded_and_document_change_prevents_next_call(
    ledger_db: LedgerFixture, tmp_path: Path
) -> None:
    engine, tenant, runs = ledger_db
    path, _, digest = publication(tmp_path)
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return response()

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        runtime = gateway(engine, client, published(engine, client, path, digest))
        result = runtime.invoke_structured(
            invocation(tenant, run_id=runs[0], model_call_id=uuid4()), RiskOutput
        )
        assert result.status == "succeeded"
        path.write_text("{}")
        denied = runtime.invoke_structured(
            invocation(tenant, run_id=runs[0], model_call_id=uuid4()), RiskOutput
        )
    assert denied.error_code == "BUDGET_INPUT_METER_UNAVAILABLE" and len(calls) == 1
    with engine.connect() as c:
        journal = list(c.execute(select(tables.budget_journal)).mappings())
        trace = (
            c.execute(
                select(tables.model_invocations).where(
                    tables.model_invocations.c.id == denied.invocation_id
                )
            )
            .mappings()
            .one()
        )
    assert len(journal) == 3
    assert journal[0]["input_tokens"] > 10
    assert journal[0]["request_binding"]["qualification_ref"].startswith(
        f"meter-publication:sha256:{digest}:"
    )
    assert trace["usage_status"] == "not_invoked"


def test_qualification_revoked_after_reservation_is_cancelled_before_dispatch(
    ledger_db: LedgerFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, runs = ledger_db
    path, _, digest = publication(tmp_path)
    ledger = BudgetLedger(engine)
    original = ledger.reserve

    def revoke(**kwargs: Unpack[ReserveArguments]) -> BudgetReceipt:
        receipt = original(**kwargs)
        path.write_text("{}")
        return receipt

    monkeypatch.setattr(ledger, "reserve", revoke)
    with httpx2.Client(
        transport=httpx2.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("wire called"))
        )
    ) as client:
        runtime = gateway(engine, client, published(engine, client, path, digest, ledger))
        result = runtime.invoke_structured(
            invocation(tenant, run_id=runs[0], model_call_id=uuid4()), RiskOutput
        )
    assert result.error_code == "BUDGET_MODEL_METER_UNQUALIFIED" and result.structured_attempts == 0
    with engine.connect() as c:
        journal = list(
            c.execute(
                select(tables.budget_journal).order_by(tables.budget_journal.c.revision)
            ).mappings()
        )
    assert [r["reservation_status"] for r in journal] == ["reserved", "cancelled_before_dispatch"]
    assert all(r["dispatched_at"] is None for r in journal)
    assert journal[-1]["held_tokens"] == 0
