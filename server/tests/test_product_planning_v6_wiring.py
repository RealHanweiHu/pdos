"""Exercise planning replay and real Finding registration with SQL boundary doubles.

No database, provider, qualification or human publication is exercised here.
The source adapter, assessment validation, rollout checks and Finding creation
remain real; only persistence, model dispatch and authorization projections are doubles.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Literal, cast
from uuid import UUID

import pytest
from sqlalchemy import Connection as SQLConnection
from sqlalchemy import Engine as SQLEngine
from sqlalchemy import RowMapping
from sqlalchemy.sql import Executable, Insert, Select, Update

from app.ai import application_domain_context, capability_contract, product_work_runs
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.capability_contract import CapabilityKey, CapabilityRollout, CapabilityZone
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.ai.product_work_context import (
    LEGACY_PLANNING_PROMPT,
    PLANNING_PROMPT,
    PROMPT,
    contract,
    key,
)
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.auth.repository import AuthContext
from app.contracts.product_planning_ai import ProductPlanningAssessment
from app.contracts.product_records import StrategyCanvas
from app.contracts.product_work_ai import (
    REQUIRED_SECTIONS,
    ProductWorkAssessment,
    ProductWorkSelection,
)
from app.db.schema import tables
from app.domain import product_evidence_findings
from app.domain.product_workspace import digest

Capability = Literal["product_strategy", "product_definition"]
TENANT, SPACE, LINE, OWNER, RUN, REQUEST, INVOCATION, EVIDENCE, OPPORTUNITY, PRODUCT, STRATEGY = [
    UUID(int=i) for i in range(1, 12)
]
SOLUTIONS = tuple(UUID(int=i) for i in range(20, 23))
WORK = UUID(int=30)
STAMP = datetime(2026, 9, 30, tzinfo=UTC)
CONTENT = "Captured production constraints remain unconfirmed."


class Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def mappings(self) -> "Result":
        return self

    def one(self) -> Any:
        return self.value

    def scalar_one(self) -> Any:
        return self.value

    def first(self) -> tuple[Any] | None:
        return None if self.value is None else (self.value,)


class Connection:
    def __init__(self, row: dict[str, Any], *, receipt_present: bool = True) -> None:
        self.row = deepcopy(row)
        self.row["run_context"]["control_history"] = [{"event": "lease_renewed"}]
        self.receipt_present = receipt_present
        self.statements: list[Executable] = []
        self.findings: list[dict[str, Any]] = []
        self.writes: list[Executable] = []

    def execute(self, statement: Executable) -> Result:
        self.statements.append(statement)
        if isinstance(statement, Insert):
            assert statement.table is tables.findings, "Unexpected business mutation"
            self.writes.append(statement)
            value = statement.compile().params
            self.findings.append(value)
            return Result(value)
        if isinstance(statement, Update):
            assert statement.table is tables.agent_runs, "Unexpected business mutation"
            self.writes.append(statement)
            values = statement.compile().params
            for name in ("status", "error_code", "completed_at", "updated_at", "run_context"):
                self.row[name] = values[name]
            return Result(self.row)
        assert isinstance(statement, Select), "Unexpected SQL operation"
        source = statement.get_final_froms()
        if not source:
            return Result(STAMP)
        if source == [tables.market_spaces]:
            return Result(SPACE)
        if source == [tables.agent_runs]:
            if list(statement.selected_columns) == [tables.agent_runs.c.run_context]:
                return Result(deepcopy(self.row["run_context"]))
            return Result(self.row)
        if source == [tables.model_invocations]:
            return Result(INVOCATION if self.receipt_present else None)
        if source == [tables.findings]:
            return Result(self.findings[0]["id"] if self.findings else None)
        raise AssertionError("Unexpected SQL read")


class Engine:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    @contextmanager
    def begin(self) -> Iterator[SQLConnection]:
        yield cast(SQLConnection, self.connection)


class Gateway:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.calls: list[GatewayInvocation] = []
        self.after_dispatch: Callable[[], None] = lambda: None
        self.error: BudgetLedgerError | None = None

    def invoke_structured(
        self, invocation: GatewayInvocation, output_type: type[ProductWorkAssessment]
    ) -> GatewayResult[ProductWorkAssessment]:
        self.calls.append(invocation)
        if self.error:
            raise self.error
        output = output_type.model_validate(self.data)
        self.after_dispatch()
        return GatewayResult(
            status="succeeded",
            output=output,
            error_code=None,
            invocation_id=INVOCATION,
            structured_attempts=1,
            removed_context_paths=(),
        )


def inputs(
    capability: Capability, version: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fields: list[tuple[str, UUID, dict[str, Any]]] = [
        (
            "evidence",
            EVIDENCE,
            {"captured_at": STAMP.isoformat(), "content_digest": "a" * 64, "content": CONTENT},
        ),
        (
            "opportunity",
            OPPORTUNITY,
            {"state": "active", "solutions": [{"id": str(value)} for value in SOLUTIONS]},
        ),
        ("work", WORK, {"action_type": "constraint_review", "state": "in_progress"}),
        ("product", PRODUCT, {"lifecycle": "active", "derived_from": None}),
        ("strategy", STRATEGY, {"state": "published"}),
    ]
    selection = ProductWorkSelection.model_validate(
        {
            "capability": capability,
            "product_line_id": LINE,
            "question": "Prepare a bounded candidate from these exact sources.",
            "sources": [{"kind": kind, "id": entity_id} for kind, entity_id, _ in fields],
        }
    ).model_dump(mode="json")
    snapshot: dict[str, Any] = {
        "actor_id": str(OWNER),
        "market_space_id": str(SPACE),
        "selection": selection,
        "warnings": ["Manufacturing qualification has not been established."],
        "coverage_limits": "Synthetic fixed sources; no release decision.",
        "references": [
            {
                "reference_id": f"{kind}:{entity_id}",
                "label": f"Original {kind}",
                "digest": digest(value),
                "fields": value,
            }
            for kind, entity_id, value in fields
        ],
    }
    snapshot["digest"] = digest(snapshot)
    _, output_type = contract(version)
    row = {
        "id": RUN,
        "tenant_id": TENANT,
        "project_id": None,
        "market_space_id": SPACE,
        "requested_by_user_id": OWNER,
        "request_id": REQUEST,
        "created_at": STAMP,
        "status": "running",
        "error_code": None,
        "run_context": {
            "product_work_source": deepcopy(snapshot),
            "product_work_selection": selection,
            "product_work_expected_digest": snapshot["digest"],
            "product_work_prompt_version": version,
            "product_work_schema_digest": digest(output_type.model_json_schema()),
            "product_work_user_instruction": "Retain unknowns and original PIE work.",
        },
    }
    evidence = snapshot["references"][0]
    basis = {
        "text": "Captured constraints require human review.",
        "nature": "hypothesis",
        "citations": [
            {
                "reference_id": evidence["reference_id"],
                "digest": evidence["digest"],
                "field_path": ["content"],
                "quoted_value": CONTENT,
            }
        ],
    }
    assessment: dict[str, Any] = {
        "capability": capability,
        "disposition": "analysis",
        "summary": [basis],
        "sections": [
            {"key": section, "statements": [basis], "missing": ["Named human review pending."]}
            for section in REQUIRED_SECTIONS[capability]
        ],
        "next_steps": [],
        "missing": ["Named human review pending."],
        "coverage_limits": snapshot["coverage_limits"],
    }
    if output_type is ProductPlanningAssessment:
        fact = {
            "text": "Manufacturing readiness remains unconfirmed.",
            "fact_kind": "hypothesis",
            "sources": [
                {
                    "tenant_id": str(TENANT),
                    "kind": "evidence_snapshot",
                    "ref_id": str(EVIDENCE),
                    "as_of": STAMP.isoformat(),
                    "digest": "a" * 64,
                }
            ],
        }
        unknown_budget = {"amount": None, "basis": fact}
        if capability == "product_strategy":
            assessment["product_strategies"] = [
                {
                    "opportunity_id": str(OPPORTUNITY),
                    "title": "Unconfirmed strategy candidate",
                    "canvas": {name: fact for name in StrategyCanvas.model_fields},
                    "route_comparisons": [
                        {
                            "solution_id": str(solution),
                            "currency": "CNY",
                            "price_target": unknown_budget,
                            "nre_budget": unknown_budget,
                            "id_cycle_days": unknown_budget,
                            **{
                                name: fact
                                for name in (
                                    "scope",
                                    "quality",
                                    "supply",
                                    "manufacturing",
                                    "resources",
                                    "trade_off",
                                )
                            },
                        }
                        for solution in SOLUTIONS
                    ],
                    "professional_constraints": [
                        {"discipline": discipline, "statement": fact, "work_item_id": str(WORK)}
                        for discipline in ("dqe", "sqe", "pie")
                    ],
                    "unknowns": ["PIE review is pending; no capacity commitment."],
                    "decision_reason": "Await named review.",
                }
            ]
        else:
            assessment["product_definitions"] = [
                {
                    "product_id": str(PRODUCT),
                    "strategy_id": str(STRATEGY),
                    "title": "Unconfirmed definition candidate",
                    "target_users": ["Rider"],
                    "scenarios": ["Roadside"],
                    "target_cost": fact,
                    "price_position": fact,
                    "launch_window": fact,
                    "success_criteria": [fact],
                    "items": [
                        {
                            "item_key": "pressure",
                            "title": "Pressure target pending",
                            "target_text": None,
                            "target_value": None,
                            "unit": None,
                            "tolerance": None,
                            "conditions": [],
                            "priority": "must",
                            "required_for_release": True,
                            "rationale": fact,
                            "verification_method": None,
                            "acceptance_criterion": None,
                            "verification_stage": None,
                        }
                    ],
                    "change_reason": "Await named review.",
                }
            ]
    return row, snapshot, assessment


def prepare(
    monkeypatch: pytest.MonkeyPatch,
    capability: Capability,
    version: str,
    *,
    receipt_present: bool = True,
) -> tuple[
    product_work_runs.ProductWorkRuns,
    Connection,
    Gateway,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    row, snapshot, data = inputs(capability, version)
    connection, gateway = Connection(row, receipt_present=receipt_present), Gateway(data)
    records: dict[str, Any] = {"contexts": [], "writes": [], "authorizations": [], "events": []}
    context = cast(
        AuthContext,
        SimpleNamespace(tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=OWNER)),
    )
    registered = capability_contract.resolve_capability(key(capability))
    active = dict(capability_contract.CAPABILITY_CONTRACTS)
    active[registered.key] = registered.model_copy(update={"rollout": CapabilityRollout.LIVE})
    # Local synthetic rollout only; the production registry remains SHADOW.
    monkeypatch.setattr(capability_contract, "CAPABILITY_CONTRACTS", active)

    def record(_engine: Any, **values: Any) -> None:
        records["contexts"].append(values)

    def actor(_connection: Any, tenant: UUID, user: UUID) -> AuthContext:
        assert (tenant, user) == (TENANT, OWNER)
        return context

    def authorize(
        _connection: Any, current: AuthContext, space: UUID, line: UUID, **values: Any
    ) -> None:
        records["authorizations"].append((current, space, line, values))

    monkeypatch.setattr(application_domain_context, "record", record)
    monkeypatch.setattr(application_domain_context, "sources_current", lambda *args: True)
    monkeypatch.setattr(product_work_runs, "actor", actor)
    monkeypatch.setattr(product_work_runs, "authorize", authorize)
    monkeypatch.setattr(product_work_runs, "rebuild", lambda *args: deepcopy(snapshot))
    monkeypatch.setattr(
        product_work_runs,
        "bind_write",
        lambda _c, _g, tenant, run, **values: records["writes"].append((tenant, run, values)),
    )
    monkeypatch.setattr(product_evidence_findings, "actor", actor)
    monkeypatch.setattr(product_evidence_findings, "allowed", lambda *args: True)
    monkeypatch.setattr(
        product_evidence_findings,
        "_emit",
        lambda _c, current, space, finding_type, action, value: records["events"].append(
            (current, space, finding_type, action, value)
        ),
    )
    service = product_work_runs.ProductWorkRuns(
        cast(SQLEngine, Engine(connection)), gateway=cast(ApplicationModelGateway, gateway)
    )
    return service, connection, gateway, row, snapshot, records


@pytest.mark.parametrize("capability", ["product_strategy", "product_definition"])
def test_catalog_matches_default_planning_contract_without_promoting_rollout(
    capability: Capability,
) -> None:
    prompt, output_type = contract(capability=capability)
    registered = capability_contract.resolve_capability(key(capability))
    assert registered.prompt_version == prompt.version == PLANNING_PROMPT.version
    assert output_type is ProductPlanningAssessment
    assert registered.rollout is CapabilityRollout.SHADOW
    assert registered.zone is CapabilityZone.HARD_GATE
    assert registered.tools == () and registered.write_operations == ()
    assert contract(LEGACY_PLANNING_PROMPT.version)[0] is LEGACY_PLANNING_PROMPT
    assert contract(PROMPT.version)[1] is ProductWorkAssessment
    with pytest.raises(CapabilityUnavailableError, match="CAPABILITY_SHADOW"):
        require_live_key(registered.key.value)


@pytest.mark.parametrize("capability", ["product_strategy", "product_definition"])
@pytest.mark.parametrize("version", [LEGACY_PLANNING_PROMPT.version, PLANNING_PROMPT.version])
def test_planning_replay_registers_one_source_bound_finding(
    monkeypatch: pytest.MonkeyPatch, capability: Capability, version: str
) -> None:
    service, connection, gateway, row, snapshot, records = prepare(monkeypatch, capability, version)
    original = deepcopy(row)
    result = service._execute(cast(RowMapping, row), snapshot)
    assert result["status"] == "succeeded" and result["error_code"] is None
    assert row == original
    assert len(gateway.calls) == 1 and len(connection.findings) == 1
    invocation = gateway.calls[0]
    assert (invocation.tenant_id, invocation.project_id, invocation.run_id) == (TENANT, None, RUN)
    assert invocation.model_call_id == model_call_id(RUN, ModelCallSlot.PRODUCT_WORK)
    prompt, model = contract(version)
    assert (invocation.prompt_version, invocation.system_prompt, invocation.instruction) == (
        version,
        prompt.system_prompt,
        prompt.instruction,
    )
    question = cast(str, invocation.context["question"])
    details = json.loads(question.split("本次分析范围与要求：", 1)[1])
    assert details["user_instruction"] == original["run_context"]["product_work_user_instruction"]
    assert details["evidence_references"][0]["reference"]["tenant_id"] == str(TENANT)
    assert details["evidence_references"][0]["reference"]["ref_id"] == str(EVIDENCE)
    references = cast(list[dict[str, Any]], invocation.context["references"])
    for actual, expected in zip(references, snapshot["references"], strict=True):
        assert actual["reference_id"] == expected["reference_id"]
        assert json.loads(actual["excerpt"]) == {
            "digest": expected["digest"],
            "fields": expected["fields"],
        }
    recorded = records["contexts"][0]
    assert (recorded["tenant_id"], recorded["project_id"], recorded["run_id"]) == (
        TENANT,
        None,
        RUN,
    )
    assert recorded["context"] == invocation.context and recorded["snapshot"] == snapshot
    finding = connection.findings[0]
    assert (finding["tenant_id"], finding["run_id"], finding["model_invocation_id"]) == (
        TENANT,
        RUN,
        INVOCATION,
    )
    assert finding["project_id"] is None and finding["scope_kind"] == "market_space"
    finding_contract = capability_contract.resolve_capability(key(capability))
    assert finding["finding_type"] in finding_contract.finding_types
    assert finding["origin_key"] == f"product-evidence:{RUN}"
    assert finding["proposed_payload"]["source_digest"] == snapshot["digest"]
    assert finding["proposed_payload"]["assessment"] == result["assessment"]
    assert (
        not {
            "accepted_payload",
            "reviewed_by_user_id",
            "applied_at",
            "applied_by_user_id",
        }
        & finding.keys()
    )
    assert connection.row["run_context"]["control_history"] == [{"event": "lease_renewed"}]
    assert connection.row["run_context"]["product_work_source"] == snapshot
    assert connection.row["run_context"]["product_work_invocation_id"] == str(INVOCATION)
    assert records["authorizations"][0][1:] == (SPACE, LINE, {"write": True})
    assert records["events"][0][1:4] == (SPACE, finding["finding_type"], "proposed")
    assert records["writes"] == [(TENANT, RUN, {"success": True})]
    receipt_query = next(
        statement
        for statement in connection.statements
        if isinstance(statement, Select)
        and statement.get_final_froms() == [tables.model_invocations]
    )
    params = receipt_query.compile().params
    assert (params["tenant_id_1"], params["run_id_1"], params["id_1"]) == (TENANT, RUN, INVOCATION)
    assert params["budget_call_id_1"] == invocation.model_call_id
    assert params["status_1"] == "succeeded"
    assert params["agent_key_1"] == invocation.agent_key
    # Re-registering the same run/type follows the real domain duplicate guard.
    product_evidence_findings.create_finding(
        cast(SQLConnection, connection), connection.row, model.model_validate(result["assessment"])
    )
    assert len(connection.findings) == 1 and len(records["events"]) == 1
    assert len(connection.writes) == 2  # Finding proposal + saved run, no business application.


@pytest.mark.parametrize("capability", ["product_strategy", "product_definition"])
def test_v1_planning_analysis_replays_without_creating_domain_candidate(
    monkeypatch: pytest.MonkeyPatch, capability: Capability
) -> None:
    service, connection, gateway, row, snapshot, records = prepare(
        monkeypatch, capability, PROMPT.version
    )
    result = service._execute(cast(RowMapping, row), snapshot)
    assert result["status"] == "succeeded" and result["assessment"]["capability"] == capability
    assert gateway.calls[0].prompt_version == PROMPT.version
    assert connection.findings == [] and records["events"] == []
    assert len(connection.writes) == 1
    assert connection.row["run_context"]["product_work_prompt_version"] == PROMPT.version
    assert connection.row["run_context"]["product_work_source"] == snapshot


@pytest.mark.parametrize(
    "failure,error_code",
    [
        ("rollout_revoked", "CAPABILITY_SHADOW"),
        ("source_changed", "PRODUCT_WORK_SOURCE_CHANGED"),
        ("foreign_evidence", "PRODUCT_WORK_SOURCE_OR_OUTPUT_INVALID"),
        ("receipt_missing", "PRODUCT_WORK_RECEIPT_MISSING"),
        ("budget_denied", "TEST_BUDGET_DENIED"),
    ],
)
def test_v6_finalization_keeps_existing_source_receipt_budget_and_revocation_guards(
    monkeypatch: pytest.MonkeyPatch, failure: str, error_code: str
) -> None:
    service, connection, gateway, row, snapshot, records = prepare(
        monkeypatch,
        "product_strategy",
        PLANNING_PROMPT.version,
        receipt_present=failure != "receipt_missing",
    )
    if failure == "rollout_revoked":

        def revoke() -> None:
            active = dict(capability_contract.CAPABILITY_CONTRACTS)
            entry = active[CapabilityKey.PRODUCT_STRATEGY]
            active[entry.key] = entry.model_copy(update={"rollout": CapabilityRollout.SHADOW})
            monkeypatch.setattr(capability_contract, "CAPABILITY_CONTRACTS", active)

        gateway.after_dispatch = revoke
    elif failure == "source_changed":
        monkeypatch.setattr(product_work_runs, "rebuild", lambda *args: {"digest": "b" * 64})
    elif failure == "foreign_evidence":
        constraint = gateway.data["product_strategies"][0]["professional_constraints"][0]
        statement = constraint["statement"]
        statement["sources"][0]["tenant_id"] = str(UUID(int=99))
    elif failure == "budget_denied":
        gateway.error = BudgetLedgerError(error_code)
    result = service._execute(cast(RowMapping, row), snapshot)
    assert result["status"] == "degraded" and result["error_code"] == error_code
    assert result["assessment"] is None
    assert connection.findings == [] and records["events"] == []
    assert records["writes"] == [(TENANT, RUN, {"success": False})]
    assert connection.row["run_context"]["product_work_source"] == snapshot
    assert connection.row["run_context"]["control_history"] == [{"event": "lease_renewed"}]
