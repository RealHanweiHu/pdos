"""Gateway -> durable budget -> actual provider adapter, using synthetic qualification."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Literal, Required, TypedDict, Unpack
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, Table, select, text, update
from sqlalchemy.exc import DBAPIError

from app.ai.budget_evidence import BudgetUsageEvidence
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError, BudgetReceipt
from app.ai.egress import ProviderEgressPolicy
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.ai.model_budget import (
    ModelBudgetController,
    ModelBudgetPort,
    QualifiedModelMeter,
    evidence_digest,
)
from app.ai.model_catalog import ProtocolKind, ProviderName, ResolvedModelRoute
from app.ai.provider_adapters import ChatMessage, OpenAICompatibleAdapter
from app.contracts.runtime_policy import RunBudgetProfile
from app.db.schema import tables
from app.domain.model_governance import ModelGovernanceService
from tests.test_budget_ledger import SERVER_ROOT, profile
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_model_gateway import RiskOutput, catalog, invocation, qualification

LedgerDatabase = tuple[Engine, UUID, list[UUID]]


class TransitionArguments(TypedDict, total=False):
    tenant_id: Required[UUID]
    attempt_id: Required[UUID]
    action: Required[Literal["dispatch", "unknown", "cancel", "settle"]]
    charged_tokens: int | None
    reconciliation_ref: str | None
    provider_request_id: str | None
    usage_evidence: BudgetUsageEvidence | None


def revision(row: Mapping[str, object]) -> int:
    value = row["revision"]
    assert isinstance(value, int)
    return value


def evidence(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return dict(value)


class SyntheticMeter:
    def __init__(self, value: int | Exception = 10) -> None:
        self.value = value

    def count(self, route: ResolvedModelRoute, messages: Sequence[ChatMessage]) -> int:
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def qualified(value: int | Exception = 10) -> QualifiedModelMeter:
    return QualifiedModelMeter(
        protocol=ProtocolKind.OPENAI_COMPATIBLE,
        window_tokens=8192,
        output_token_limit=2048,
        output_parameter="max_completion_tokens",
        qualification_ref="synthetic-test-only",
        meter_version="synthetic-v1",
        meter=SyntheticMeter(value),
    )


def controller(
    engine: Engine,
    *,
    ledger: ModelBudgetPort | None = None,
    meter: QualifiedModelMeter | None = None,
    budget_profile: RunBudgetProfile | None = None,
) -> ModelBudgetController:
    return ModelBudgetController(
        ledger or BudgetLedger(engine),
        profile=budget_profile or profile(),
        meters={(ProviderName.MINIMAX, "MiniMax-M2.7"): meter or qualified()},
    )


def gateway(
    engine: Engine, client: httpx2.Client, budget: ModelBudgetController | None
) -> StructuredModelGateway:
    return StructuredModelGateway(
        engine,
        catalog=catalog(),
        qualifications=[qualification()],
        governance=ModelGovernanceService(
            engine,
            catalog=catalog(),
            qualifications=[qualification()],
            default_daily_token_budget=10000,
        ),
        adapters={
            ProtocolKind.OPENAI_COMPATIBLE: OpenAICompatibleAdapter(
                client, ProviderEgressPolicy.from_catalog(catalog())
            )
        },
        rate_cards={},
        budget_controller=budget,
    )


def response(
    content: str = '{"risk":"low"}', *, inputs: int = 7, outputs: int = 3
) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "synthetic-request",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": inputs, "completion_tokens": outputs},
        },
    )


def rows(engine: Engine, table: Table = tables.budget_journal) -> list[dict[str, object]]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(select(table)).mappings()]


def invocation_trace(engine: Engine, result: GatewayResult[RiskOutput]) -> dict[str, object]:
    assert result.invocation_id is not None
    with engine.connect() as connection:
        return dict(
            connection.execute(
                select(tables.model_invocations).where(
                    tables.model_invocations.c.id == result.invocation_id
                )
            )
            .mappings()
            .one()
        )


def call(
    tenant: UUID, run: UUID, call_id: UUID | None = None, **kwargs: object
) -> GatewayInvocation:
    return invocation(tenant, run_id=run, model_call_id=call_id or uuid4(), **kwargs)


def test_gateway_retries_are_separately_reserved_and_settled(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    requests: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = evidence(json.loads(request.content))
        assert body["max_completion_tokens"] == 20
        requests.append(body)
        return response("bad-json" if len(requests) == 1 else '{"risk":"low"}')

    inv = call(tenant, runs[0])
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        result = gateway(engine, client, controller(engine)).invoke_structured(inv, RiskOutput)
    assert result.status == "succeeded"
    assert result.structured_attempts == 2
    journal = rows(engine)
    assert len(journal) == 6
    settled = [row for row in journal if row["reservation_status"] == "settled"]
    charged_tokens = [row["charged_tokens"] for row in settled]
    assert all(isinstance(value, int) for value in charged_tokens)
    assert sum(value for value in charged_tokens if isinstance(value, int)) == 20
    assert len({row["attempt_id"] for row in settled}) == 2
    assert len({evidence(row["request_binding"])["request_digest"] for row in settled}) == 2
    assert all(
        evidence(row["request_binding"])["model_call_id"] == str(inv.model_call_id)
        for row in settled
    )
    assert all(evidence(row["usage_evidence"])["input_tokens"] == 7 for row in settled)
    assert all(row["held_tokens"] == 0 and row["charged_cost_microusd"] is None for row in settled)
    trace = invocation_trace(engine, result)
    assert trace["budget_call_id"] == inv.model_call_id
    assert trace["total_tokens"] == 20


def test_second_structured_attempt_is_blocked_by_lineage_budget(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return response("bad-json", inputs=70, outputs=10)

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        service = gateway(
            engine,
            client,
            controller(
                engine, meter=qualified(70), budget_profile=profile(lineage_token_limit=100)
            ),
        )
        result = service.invoke_structured(call(tenant, runs[0]), RiskOutput)
    assert result.error_code == "BUDGET_LINEAGE_TOKENS_EXHAUSTED"
    assert result.structured_attempts == 1
    assert len(requests) == 1
    assert invocation_trace(engine, result)["total_tokens"] == 80


def test_timeout_holds_budget_and_neither_replay_nor_new_id_redispatches(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        raise httpx2.ReadTimeout("synthetic response lost")

    inv = call(tenant, runs[0])
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        service = gateway(engine, client, controller(engine))
        first = service.invoke_structured(inv, RiskOutput)
        replay = service.invoke_structured(inv, RiskOutput)
        fresh = service.invoke_structured(call(tenant, runs[0]), RiskOutput)
    assert first.error_code == "PROVIDER_TRANSPORT_ERROR"
    assert replay.error_code == "BUDGET_ATTEMPT_ALREADY_DISPATCHED"
    assert fresh.error_code == "BUDGET_LINEAGE_CALL_BUSY"
    assert len(requests) == 1
    latest = max(rows(engine), key=revision)
    assert latest["reservation_status"] == "unknown"
    assert latest["held_tokens"] == 30
    assert latest["usage_evidence"] is None


def test_malformed_content_with_known_usage_still_settles(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    with httpx2.Client(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(
                200,
                json={
                    "id": "bad-content",
                    "choices": [],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                },
            )
        )
    ) as client:
        result = gateway(engine, client, controller(engine)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    assert result.error_code == "PROVIDER_INVALID_RESPONSE"
    latest = max(rows(engine), key=revision)
    assert latest["charged_tokens"] == 10
    assert latest["held_tokens"] == 0
    assert evidence(latest["usage_evidence"])["error_code"] == "provider_invalid_response"


def test_replay_cannot_change_body_at_the_same_token_count(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return response()

    inv = call(tenant, runs[0])
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        service = gateway(engine, client, controller(engine))
        assert service.invoke_structured(inv, RiskOutput).status == "succeeded"
        result = service.invoke_structured(
            inv.model_copy(update={"instruction": "changed request"}), RiskOutput
        )
    assert result.error_code == "BUDGET_ATTEMPT_CONFLICT"
    assert len(requests) == 1


def test_concurrent_same_call_sends_exactly_one_provider_request(ledger_db: LedgerDatabase) -> None:
    engine, tenant, runs = ledger_db
    barrier = Barrier(2)
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return response()

    inv = call(tenant, runs[0])
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        service = gateway(engine, client, controller(engine))

        def invoke() -> GatewayResult[RiskOutput]:
            barrier.wait(timeout=5)
            return service.invoke_structured(inv, RiskOutput)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invoke) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
    assert len(requests) == 1
    assert sorted(result.status for result in results) == ["degraded", "succeeded"]
    assert (
        next(result for result in results if result.status == "degraded").error_code
        == "BUDGET_ATTEMPT_ALREADY_DISPATCHED"
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("over-context", "BUDGET_CONTEXT_WINDOW_EXCEEDED"),
        ("meter-failed", "BUDGET_INPUT_METER_UNAVAILABLE"),
        ("meter-bool", "BUDGET_INPUT_METER_INVALID"),
        ("unqualified", "BUDGET_MODEL_METER_UNQUALIFIED"),
        ("missing-run", "BUDGET_CALL_IDENTITY_REQUIRED"),
        ("missing-call", "BUDGET_CALL_IDENTITY_REQUIRED"),
    ],
)
def test_admission_failures_send_nothing(
    ledger_db: LedgerDatabase, mode: str, expected: str
) -> None:
    engine, tenant, runs = ledger_db
    meter = qualified(
        81
        if mode == "over-context"
        else RuntimeError("meter unavailable")
        if mode == "meter-failed"
        else True
        if mode == "meter-bool"
        else 10
    )
    budget = controller(engine, meter=meter)
    if mode == "unqualified":
        budget = ModelBudgetController(BudgetLedger(engine), profile=profile(), meters={})
    inv = call(tenant, runs[0])
    if mode == "missing-run":
        inv = inv.model_copy(update={"run_id": None})
    if mode == "missing-call":
        inv = inv.model_copy(update={"model_call_id": None})

    def handler(request: httpx2.Request) -> httpx2.Response:
        pytest.fail("admission failure reached HTTP")

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        result = gateway(engine, client, budget).invoke_structured(inv, RiskOutput)
    assert result.error_code == expected
    assert result.structured_attempts == 0
    assert not rows(engine)
    assert invocation_trace(engine, result)["cost_status"] == "not_invoked"


def test_settlement_failure_never_becomes_zero_call(
    ledger_db: LedgerDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    transition = ledger.transition

    def fail_settle(**kwargs: Unpack[TransitionArguments]) -> BudgetReceipt:
        if kwargs["action"] == "settle":
            raise BudgetLedgerError("SYNTHETIC_SETTLEMENT_FAILURE")
        return transition(**kwargs)

    monkeypatch.setattr(ledger, "transition", fail_settle)
    with httpx2.Client(transport=httpx2.MockTransport(lambda _: response())) as client:
        result = gateway(engine, client, controller(engine, ledger=ledger)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    assert result.error_code == "BUDGET_RECEIPT_FAILED"
    assert result.structured_attempts == 1
    trace = invocation_trace(engine, result)
    assert trace["total_tokens"] == 10
    assert trace["cost_status"] == "unknown"
    latest = max(rows(engine), key=revision)
    assert latest["dispatched_at"] is not None and latest["held_tokens"] == 30


def test_run_ending_before_dispatch_cancels_only_undispatched_hold(
    ledger_db: LedgerDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, runs = ledger_db
    ledger = BudgetLedger(engine)
    transition = ledger.transition

    def finish_run(**kwargs: Unpack[TransitionArguments]) -> BudgetReceipt:
        if kwargs["action"] == "dispatch":
            with engine.begin() as connection:
                connection.execute(
                    update(tables.agent_runs)
                    .where(tables.agent_runs.c.id == runs[0])
                    .values(
                        status="degraded",
                        error_code="SYNTHETIC_STOP",
                        completed_at=text("clock_timestamp()"),
                    )
                )
        return transition(**kwargs)

    monkeypatch.setattr(ledger, "transition", finish_run)

    def handler(request: httpx2.Request) -> httpx2.Response:
        pytest.fail("finished run reached HTTP")

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        result = gateway(engine, client, controller(engine, ledger=ledger)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    assert result.error_code == "BUDGET_RUN_NOT_RUNNING"
    latest = max(rows(engine), key=revision)
    assert latest["reservation_status"] == "cancelled_before_dispatch"
    assert latest["held_tokens"] == 0


def test_provider_overshoot_is_charged_in_full_and_output_rejected(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    with httpx2.Client(transport=httpx2.MockTransport(lambda _: response(outputs=21))) as client:
        result = gateway(engine, client, controller(engine)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    assert result.error_code == "PROVIDER_OUTPUT_LIMIT_EXCEEDED"
    assert result.output is None
    latest = max(rows(engine), key=revision)
    assert latest["charged_tokens"] == 28
    assert evidence(latest["usage_evidence"])["output_tokens"] == 21


def test_unknown_reconciliation_requires_matching_usage_and_preserves_migration(
    ledger_db: LedgerDatabase,
) -> None:
    engine, tenant, runs = ledger_db
    with engine.connect() as c:
        original_head = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0061_provider_admission")
    command.upgrade(config, "head")

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("synthetic lost response")

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        gateway(engine, client, controller(engine)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    latest = max(rows(engine), key=revision)
    ledger = BudgetLedger(engine)
    request_digest = evidence(latest["request_binding"])["request_digest"]
    assert isinstance(request_digest, str)
    usage = BudgetUsageEvidence(
        request_digest=request_digest,
        input_tokens=7,
        output_tokens=3,
        request_id="reconciled",
    )
    attempt_id = latest["attempt_id"]
    assert isinstance(attempt_id, UUID)
    for charged_tokens, provider_request_id, usage_evidence in (
        (9, "reconciled", usage),
        (10, "different", usage),
        (10, "reconciled", usage.model_copy(update={"request_digest": "0" * 64})),
    ):
        values: TransitionArguments = dict(
            tenant_id=tenant,
            attempt_id=attempt_id,
            action="settle",
            charged_tokens=charged_tokens,
            provider_request_id=provider_request_id,
            reconciliation_ref="synthetic-evidence",
            usage_evidence=usage_evidence,
        )
        with pytest.raises(BudgetLedgerError, match="BUDGET_SETTLEMENT_EVIDENCE_CONFLICT"):
            ledger.transition(**values)
    ledger.transition(
        tenant_id=tenant,
        attempt_id=attempt_id,
        action="settle",
        charged_tokens=10,
        provider_request_id="reconciled",
        reconciliation_ref="provider-usage.v1:sha256:"
        + evidence_digest(usage.model_dump(mode="json")),
        usage_evidence=usage,
    )
    # Current outer migration refuses the persistent binding before older guards run.
    with pytest.raises(DBAPIError, match="persistent budget history"):
        command.downgrade(config, "0061_provider_admission")
    with engine.connect() as connection:
        assert (
            connection.execute(text("select version_num from alembic_version")).scalar_one()
            == original_head
        )


@pytest.mark.parametrize("exception", [RuntimeError("SDK failed"), KeyboardInterrupt()])
def test_unexpected_provider_failure_keeps_unknown_hold(
    ledger_db: LedgerDatabase, exception: BaseException
) -> None:
    engine, tenant, runs = ledger_db

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise exception

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        service = gateway(engine, client, controller(engine))
        with pytest.raises(type(exception)):
            service.invoke_structured(call(tenant, runs[0]), RiskOutput)
    latest = max(rows(engine), key=revision)
    assert latest["reservation_status"] == "unknown"
    assert latest["held_tokens"] == 30


def test_qualified_window_intersects_profile_and_reserves_tool_and_safety_space(
    ledger_db: LedgerDatabase,
) -> None:
    from dataclasses import replace

    engine, tenant, runs = ledger_db
    # 3160 - 20 output - 2048 next tool - 1024 safety = 68, below profile's 80.
    meter = replace(qualified(69), window_tokens=3160)

    def handler(request: httpx2.Request) -> httpx2.Response:
        pytest.fail("context exceeded qualified model window")

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        result = gateway(engine, client, controller(engine, meter=meter)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    assert result.error_code == "BUDGET_CONTEXT_WINDOW_EXCEEDED"
    assert not rows(engine)


def test_replay_cannot_replace_meter_qualification(ledger_db: LedgerDatabase) -> None:
    from dataclasses import replace

    engine, tenant, runs = ledger_db
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return response()

    inv = call(tenant, runs[0])
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        assert (
            gateway(engine, client, controller(engine)).invoke_structured(inv, RiskOutput).status
            == "succeeded"
        )
        changed = replace(qualified(), qualification_ref="different-qualification")
        result = gateway(engine, client, controller(engine, meter=changed)).invoke_structured(
            inv, RiskOutput
        )
    assert result.error_code == "BUDGET_ATTEMPT_CONFLICT"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "changes", [{"request_binding": []}, {"usage_evidence": []}, {"usage_evidence": {}}]
)
def test_database_rejects_invalid_evidence_shapes_or_premature_receipts(
    ledger_db: LedgerDatabase, changes: dict[str, object]
) -> None:
    from sqlalchemy.exc import IntegrityError

    engine, tenant, runs = ledger_db

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("synthetic lost response")

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        gateway(engine, client, controller(engine)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    latest = max(rows(engine), key=revision)
    latest.update(id=uuid4(), revision=revision(latest) + 1, **changes)
    with pytest.raises(IntegrityError, match="model_evidence_shape"), engine.begin() as connection:
        connection.execute(tables.budget_journal.insert(), latest)


def test_output_limit_is_intersection_of_profile_and_model_qualification(
    ledger_db: LedgerDatabase,
) -> None:
    from dataclasses import replace

    engine, tenant, runs = ledger_db
    meter = replace(qualified(), output_token_limit=8)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert json.loads(request.content)["max_completion_tokens"] == 8
        return response()

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        result = gateway(engine, client, controller(engine, meter=meter)).invoke_structured(
            call(tenant, runs[0]), RiskOutput
        )
    assert result.status == "succeeded"
    first = min(rows(engine), key=revision)
    assert first["reserved_tokens"] == 18
    assert evidence(first["request_binding"])["qualified_output_limit"] == 8
    assert evidence(first["request_binding"])["output_limit"] == 8


def test_business_call_slot_replay_cannot_mint_a_second_request(ledger_db: LedgerDatabase) -> None:
    from app.ai.call_identity import ModelCallSlot, model_call_id

    engine, tenant, runs = ledger_db
    identity = model_call_id(runs[0], ModelCallSlot.EVENT_ASSESSMENT)
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return response()

    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        service = gateway(engine, client, controller(engine))
        first = call(tenant, runs[0], call_id=identity)
        assert service.invoke_structured(first, RiskOutput).status == "succeeded"
        replay = first.model_copy(
            update={
                "model_call_id": model_call_id(runs[0], ModelCallSlot.EVENT_ASSESSMENT),
                "instruction": "Changed input must not create another budget attempt.",
            }
        )
        assert service.invoke_structured(replay, RiskOutput).error_code == "BUDGET_ATTEMPT_CONFLICT"
    assert len(requests) == 1
    assert len(rows(engine)) == 3
