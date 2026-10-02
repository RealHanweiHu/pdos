"""Real HTTP retry takes over a supervised result without new inference or publication."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from importlib import import_module
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import RowMapping, Table, select, text

from app.ai.application_leases import ApplicationLeaseKeeper, bind_write
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.chat import ChatEvidence, ChatEvidenceRepository
from app.ai.finding_writer import FindingCandidate
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.db.engine import get_engine
from app.db.schema import tables
from tests import test_application_run_budget_api as api_factory
from tests.migration_fixtures import rollback_migration_operations
from tests.test_ai_api import api_context as api_context
from tests.test_ai_api import isolated_ai_api_database as isolated_ai_api_database
from tests.test_ai_api import seed_project_and_users, setup_owner
from tests.test_ai_test_plan_changes import READY, suggest
from tests.test_ai_test_plan_changes import scenario as scenario
from tests.test_application_authorization import chat_provider as chat_provider
from tests.test_application_budget_factory import factory_setup as factory_setup
from tests.test_application_leases import expire
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_chat_requests import chat_setup as chat_setup
from tests.test_model_budget_controller import LedgerDatabase
from tests.test_test_report_import_api import MAPPING, Scope, bearer_headers, build_report, upload
from tests.test_test_report_import_api import isolated_import_database as isolated_import_database

RecoveryEntry = tuple[str, Callable[[], httpx2.Response], list[httpx2.Request], dict[str, str]]
ApplicationFactory = tuple[dict[str, str], list[httpx2.Request], Path]


def rows(table: Table) -> list[RowMapping]:
    with get_engine().connect() as c:
        return list(c.execute(select(table)).mappings())


def unchanged_records() -> list[list[RowMapping]]:
    return [
        rows(t)
        for t in (
            tables.budget_lineages,
            tables.budget_run_links,
            tables.budget_journal,
            tables.model_invocations,
            tables.model_call_sessions,
            tables.model_call_events,
            tables.application_context_observations,
            tables.application_context_manifests,
            tables.application_result_checkpoints,
        )
    ]


@pytest.fixture(params=["chat", "risk", "test_plan", "report"])
def entry(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[RecoveryEntry]:
    client: TestClient
    project: UUID
    headers: dict[str, str]
    body: dict[str, object]
    output: dict[str, object]
    environment: dict[str, str]
    calls: list[httpx2.Request]
    kind = request.param
    scope = None
    if kind == "chat":
        client, _, _, _, project, headers, body = request.getfixturevalue("chat_setup")
        output = dict(
            disposition="answered",
            claims=[dict(text="Project status", citation_ids=[f"project:{project}"])],
        )

        def invoke() -> httpx2.Response:
            return client.post("/api/ai/chat", headers=headers, json=body)
    elif kind == "risk":
        client, _, _ = request.getfixturevalue("api_context")
        tenant, _, headers = setup_owner(client)
        project, event = seed_project_and_users(
            request.getfixturevalue("isolated_ai_api_database"), tenant_id=tenant
        )
        output = dict(
            disposition="human_review_candidate",
            candidate_type="risk_suggestion",
            summary="Review this risk",
            proposed_payload=dict(title="Evidence risk", likelihood=3, impact=4),
            evidence_event_ids=[event],
            confidence=0.8,
        )
        body = dict(
            project_id=str(project),
            request_id=str(uuid4()),
            concern="Synthetic risk",
            evidence_event_ids=[event],
        )

        def invoke() -> httpx2.Response:
            return client.post("/api/ai/create-risk-suggestion", headers=headers, json=body)
    elif kind == "test_plan":
        scenario = request.getfixturevalue("scenario")
        request_id = str(uuid4())
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
            result = suggest(scenario, request_id=request_id)
            assert isinstance(result, httpx2.Response)
            return result
    else:
        client, _, _ = request.getfixturevalue("api_context")
        scope = Scope(client, request.getfixturevalue("isolated_import_database"))
        ids = scope.seed()
        headers = bearer_headers(client)
        content = build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")])
        output = MAPPING.model_dump(mode="json")

        def invoke() -> httpx2.Response:
            return upload(client, headers, ids["project_id"], ids["plan_id"], content)

    original_invoke = StructuredModelGateway.invoke_structured
    environment, calls, _ = api_factory.factory(
        get_engine(), tmp_path, monkeypatch, request=request, output=output
    )
    # Creation-only fixture assumptions do not apply to the retained recovery history.
    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", original_invoke)
    try:
        yield kind, invoke, calls, environment
    finally:
        if scope is not None:
            scope.dispose()


def interrupt_after_result(
    entry: RecoveryEntry, monkeypatch: pytest.MonkeyPatch
) -> list[StructuredModelGateway]:
    original = StructuredModelGateway.invoke_structured
    interrupted = False
    holders: list[StructuredModelGateway] = []

    def invoke[OutputT: BaseModel](
        gateway: StructuredModelGateway, invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        assert invocation.run_id is not None
        nonlocal interrupted
        holders.append(gateway)
        if interrupted:
            with (
                pytest.raises(BudgetLedgerError, match="APPLICATION_RUN_LEASE_LOST"),
                get_engine().begin() as c,
            ):
                bind_write(c, holders[0], invocation.tenant_id, invocation.run_id)
        result = original(gateway, invocation, output_type)
        if not interrupted:
            assert result.status == "succeeded", result
            interrupted = True
            expire(get_engine(), invocation.run_id)
            with get_engine().begin() as c:
                assert (
                    c.execute(text("SELECT cehub_ai.expire_application_runs(100)")).scalar_one()
                    == 1
                )
            raise RuntimeError("synthetic stopped owner after durable result")
        return result

    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", invoke)
    try:
        first = entry[1]()
    except RuntimeError as error:
        assert "synthetic stopped owner" in str(error)
    else:
        assert first.status_code >= 400 or first.json().get("status") == "unavailable", first.text
    run = rows(tables.agent_runs)[0]
    assert run["status"] == "degraded" and run["error_code"] == "APPLICATION_RUN_LEASE_EXPIRED"
    assert len(rows(tables.application_result_checkpoints)) == len(entry[2]) == 1
    return holders


def test_four_http_entries_resume_original_result_and_reject_old_owner(
    entry: RecoveryEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    kind, invoke, calls, _ = entry
    holders = interrupt_after_result(entry, monkeypatch)
    before = unchanged_records()
    if kind == "chat":
        original_collect = ChatEvidenceRepository.collect

        def validate_only(
            repository: ChatEvidenceRepository,
            *,
            tenant_id: UUID,
            project_id: UUID,
            question: str,
            actor_user_id: UUID | None = None,
            attachment_ids: tuple[UUID, ...] = (),
            object_focus: dict[str, object] | None = None,
        ) -> tuple[ChatEvidence, ...]:
            assert repository._embedding_gateway is None
            return original_collect(
                repository,
                tenant_id=tenant_id,
                project_id=project_id,
                question=question,
                actor_user_id=actor_user_id,
                attachment_ids=attachment_ids,
                object_focus=object_focus,
            )

        monkeypatch.setattr(ChatEvidenceRepository, "collect", validate_only)
    resumed = invoke()
    assert resumed.status_code == (201 if kind == "report" else 200), resumed.text
    if kind != "report":
        assert resumed.json()["status"] == ("answered" if kind == "chat" else "created"), (
            resumed.text
        )
    assert len(calls) == 1 and unchanged_records() == before
    leases = sorted(rows(tables.application_run_leases), key=lambda row: row["generation"])
    assert [row["generation"] for row in leases] == [1, 2]
    assert leases[1]["previous_lease_id"] == leases[0]["id"]
    assert (
        leases[1]["recovery_checkpoint_id"] == rows(tables.application_result_checkpoints)[0]["id"]
    )
    assert leases[0]["owner_id"] != leases[1]["owner_id"]
    assert leases[1]["stop_reason"] == "completed" and leases[0]["ended_at"] is not None
    assert holders[0] is not holders[1]
    assert rows(tables.agent_runs)[0]["status"] == "succeeded"
    assert len(rows(tables.findings)) == (1 if kind in {"risk", "test_plan"} else 0)
    spans = rows(tables.budget_activity_spans)
    assert len(spans) == 2 and all(row["stopped_at"] is not None for row in spans)
    assert {row["lease_token"] for row in spans} == {row["id"] for row in leases}
    replayed = invoke()
    expected = {**resumed.json(), "reused_existing": True} if kind == "report" else resumed.json()
    assert replayed.status_code == 200 and replayed.json() == expected, replayed.text
    assert len(calls) == 1 and len(rows(tables.application_run_leases)) == 2


def claim_again(
    entry: RecoveryEntry,
    gateway: StructuredModelGateway,
    *,
    actor: UUID | None = None,
    version: int | None = None,
) -> bool:
    from app.ai.application_recovery import try_resume

    with get_engine().begin() as c:
        run = c.execute(select(tables.agent_runs)).mappings().one()
        auth = c.execute(select(tables.application_authorizations)).mappings().one()
        return try_resume(
            c,
            gateway,
            run,
            actor=actor or auth["principal_id"],
            auth_version=version if version is not None else auth["pins"]["auth_version"],
            purpose=auth["body"]["purpose"],
        )


@pytest.mark.parametrize("entry", ["chat"], indirect=True)
@pytest.mark.parametrize("fault", ["actor", "session", "inactive", "profile"])
def test_new_holder_cannot_replace_original_authority_or_budget(
    entry: RecoveryEntry, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from app.ai.application_gateway import configured_application_gateway

    interrupt_after_result(entry, monkeypatch)
    before = unchanged_records()
    leases = rows(tables.application_run_leases)
    run = rows(tables.agent_runs)[0]
    auth = rows(tables.application_authorizations)[0]
    if fault == "inactive":
        with get_engine().begin() as c:
            c.execute(
                tables.users.update()
                .where(tables.users.c.id == auth["principal_id"])
                .values(is_active=False)
            )
    with configured_application_gateway(get_engine(), entry[3]) as gateway:
        if fault == "profile":
            budget = gateway._budget_controller
            profile = gateway.creation_budget_profile
            assert budget is not None and profile is not None
            budget._profile = profile.model_copy(update={"active_seconds": 999})
        with pytest.raises(BudgetLedgerError, match="APPLICATION_RECOVERY_AUTHORIZATION_CHANGED"):
            claim_again(
                entry,
                gateway,
                actor=uuid4() if fault == "actor" else None,
                version=auth["pins"]["auth_version"] + 1 if fault == "session" else None,
            )
    assert unchanged_records() == before
    assert rows(tables.application_run_leases) == leases and rows(tables.agent_runs)[0] == run
    assert len(entry[2]) == 1


@pytest.mark.parametrize("entry", ["chat"], indirect=True)
def test_concurrent_new_holders_produce_one_generation_and_limit_is_durable(
    entry: RecoveryEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.ai.application_gateway import configured_application_gateway

    interrupt_after_result(entry, monkeypatch)
    before = unchanged_records()
    with (
        configured_application_gateway(get_engine(), entry[3]) as one,
        configured_application_gateway(get_engine(), entry[3]) as two,
    ):
        barrier = Barrier(2)

        def claim(gateway: StructuredModelGateway) -> bool:
            barrier.wait(timeout=10)
            return claim_again(entry, gateway)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, [one, two]))
        assert sorted(results) == [False, True]
        assert len(rows(tables.application_run_leases)) == 2
        assert claim_again(entry, two) is False
        run_id = rows(tables.agent_runs)[0]["id"]
        for expected in [True, False]:
            # End only the live lease: past generations are immutable history.
            with get_engine().begin() as c:
                c.execute(
                    text(
                        "UPDATE cehub_ai.application_run_leases SET expires_at=clock_timestamp() "
                        "WHERE ended_at IS NULL"
                    )
                )
                c.execute(text("SELECT cehub_ai.expire_application_runs(100)"))
            if expected:
                assert claim_again(entry, two)
            else:
                with pytest.raises(BudgetLedgerError, match="APPLICATION_RECOVERY_LIMIT_REACHED"):
                    claim_again(entry, one)
        assert [
            row["generation"]
            for row in sorted(
                rows(tables.application_run_leases), key=lambda row: row["generation"]
            )
        ] == [1, 2, 3]
        assert rows(tables.agent_runs)[0]["id"] == run_id
    assert unchanged_records() == before and len(entry[2]) == 1


def test_changed_bundle_stops_recovery_before_new_model_or_candidate(
    entry: RecoveryEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai import application_context

    interrupt_after_result(entry, monkeypatch)
    before = unchanged_records()
    original = application_context.chat_bundle
    monkeypatch.setattr(
        application_context,
        "chat_bundle",
        lambda *, work_focus=False: {
            **original(work_focus=work_focus),
            "source_sha256": {"changed": "0" * 64},
        },
    )
    response = entry[1]()
    assert response.status_code >= 400 or response.json().get("status") == "unavailable", (
        response.text
    )
    assert len(entry[2]) == 1 and rows(tables.findings) == []
    assert unchanged_records() == before
    leases = rows(tables.application_run_leases)
    assert len(leases) == 2 and all(row["ended_at"] is not None for row in leases)


@pytest.mark.parametrize("entry", ["risk"], indirect=True)
def test_risk_published_receipt_is_reused_after_owner_dies_before_completion(
    entry: RecoveryEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.risk_suggestions import RiskSuggestionService

    original = RiskSuggestionService._persist_finding
    stopped = False

    def persist(
        service: RiskSuggestionService,
        *,
        tenant_id: UUID,
        project_id: UUID,
        run_id: UUID,
        model_invocation_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        candidate: FindingCandidate,
        created_at: datetime,
    ) -> UUID:
        nonlocal stopped
        finding = original(
            service,
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            model_invocation_id=model_invocation_id,
            actor_user_id=actor_user_id,
            request_id=request_id,
            candidate=candidate,
            created_at=created_at,
        )
        if not stopped:
            stopped = True
            expire(get_engine(), run_id)
            with get_engine().begin() as c:
                c.execute(text("SELECT cehub_ai.expire_application_runs(100)"))
            raise RuntimeError("synthetic owner stopped after publishing")
        return finding

    monkeypatch.setattr(RiskSuggestionService, "_persist_finding", persist)
    with pytest.raises(RuntimeError, match="synthetic owner stopped"):
        entry[1]()
    findings = rows(tables.findings)
    actions = rows(tables.finding_actions)
    events = rows(tables.events)
    assert len(findings) == 1 and findings[0]["status"] == "pending_review"
    result = entry[1]()
    assert result.status_code == 200 and result.json()["status"] == "created", result.text
    assert result.json()["finding_id"] == str(findings[0]["id"])
    assert rows(tables.findings) == findings and rows(tables.finding_actions) == actions
    assert rows(tables.events) == events and len(entry[2]) == 1


@pytest.mark.parametrize("entry", ["chat"], indirect=True)
def test_unresolved_session_prevents_claim_without_releasing_or_redispatching(
    entry: RecoveryEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.model_call_fence import ModelCallFence

    original = StructuredModelGateway.invoke_structured

    def extra_session[OutputT: BaseModel](
        gateway: StructuredModelGateway, invocation: GatewayInvocation, output_type: type[OutputT]
    ) -> GatewayResult[OutputT]:
        result = original(gateway, invocation, output_type)
        ModelCallFence(get_engine()).begin(
            tenant_id=invocation.tenant_id,
            run_id=invocation.run_id,
            project_id=invocation.project_id,
            agent_key=invocation.agent_key,
            budgeted=True,
        )
        return result

    monkeypatch.setattr(StructuredModelGateway, "invoke_structured", extra_session)
    interrupt_after_result(entry, monkeypatch)
    before = unchanged_records()
    with (
        configured_application_gateway(get_engine(), entry[3]) as gateway,
        pytest.raises(BudgetLedgerError, match="APPLICATION_RECOVERY_RECEIPT_INVALID"),
    ):
        claim_again(entry, gateway)
    assert unchanged_records() == before and len(rows(tables.application_run_leases)) == 1
    assert len(entry[2]) == 1


@pytest.mark.parametrize("entry", ["chat"], indirect=True)
def test_recovery_chain_scope_immutability_and_destructive_downgrade(
    entry: RecoveryEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import DBAPIError

    from app.ai.application_gateway import configured_application_gateway

    interrupt_after_result(entry, monkeypatch)
    with configured_application_gateway(get_engine(), entry[3]) as gateway:
        assert claim_again(entry, gateway)
    leases = sorted(rows(tables.application_run_leases), key=lambda r: r["generation"])
    for field in ("generation", "previous_lease_id", "recovery_checkpoint_id"):
        with pytest.raises(DBAPIError, match="immutable"), get_engine().begin() as c:
            c.execute(
                tables.application_run_leases.update()
                .where(tables.application_run_leases.c.id == leases[-1]["id"])
                .values(**{field: 3 if field == "generation" else uuid4()})
            )
    with (
        rollback_migration_operations(get_engine()),
        pytest.raises(DBAPIError, match="persistent application recovery history"),
    ):
        import_module("migrations.versions.0086_application_recovery").downgrade()
    assert rows(tables.application_run_leases) == leases


def test_empty_recovery_migration_matches_physical_schema(ledger_db: LedgerDatabase) -> None:
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext

    from app.db.schema import metadata
    from tests.test_budget_ledger import SERVER_ROOT

    engine, _, _ = ledger_db
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0085_application_results")
    command.upgrade(config, "head")
    with engine.connect() as c:
        context = MigrationContext.configure(
            c,
            opts=dict(
                include_schemas=True,
                include_object=lambda obj, name, kind, reflected, compared: (
                    kind != "table"
                    or name in {"application_run_leases", "application_result_checkpoints"}
                ),
            ),
        )
        assert compare_metadata(context, metadata) == []


def test_expired_unfinished_owner_can_be_replaced_before_supervisor_runs(
    ledger_db: LedgerDatabase,
    factory_setup: ApplicationFactory,
) -> None:
    from app.ai.application_authorization import policy_version
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.chat import ChatAssessment
    from tests.test_application_authorization import identity, start

    engine, tenant, _ = ledger_db
    environment, calls, _ = factory_setup
    actor, project = identity(engine)
    with (
        configured_application_gateway(engine, environment) as first,
        configured_application_gateway(engine, environment) as second,
    ):
        run, invocation = start(engine, first, tenant, actor, project)
        result = first.invoke_structured(invocation, ChatAssessment)
        assert result.status == "succeeded"
        expire(engine, run["id"])
        keeper = second.application_lease_keeper
        profile = second.creation_budget_profile
        assert isinstance(keeper, ApplicationLeaseKeeper) and profile is not None
        with engine.begin() as c:
            cp = c.execute(select(tables.application_result_checkpoints)).mappings().one()
            token = c.execute(
                text("""SELECT cehub_ai.claim_application_result_run(
              :t,:r,:actor,1,:owner,:cp,:policy,CAST(:profile AS jsonb))"""),
                dict(
                    t=tenant,
                    r=run["id"],
                    actor=actor,
                    owner=keeper.owner_id,
                    cp=cp["id"],
                    policy=policy_version(),
                    profile=profile.model_dump_json(),
                ),
            ).scalar_one()
        keeper.register_recovery(tenant, run["id"], token)
        assert second.invoke_structured(invocation, ChatAssessment) == result
        with (
            pytest.raises(BudgetLedgerError, match="APPLICATION_RUN_LEASE_LOST"),
            engine.begin() as c,
        ):
            bind_write(c, first, tenant, run["id"], success=False)
        with engine.connect() as c:
            spans = list(c.execute(select(tables.budget_activity_spans)).mappings())
            assert len(spans) == 2 and sum(row["stopped_at"] is None for row in spans) == 1
    assert len(calls) == 1


@pytest.mark.parametrize("entry", ["chat"], indirect=True)
def test_database_forbids_new_model_dispatch_in_a_recovery_generation(
    entry: RecoveryEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.application_gateway import configured_application_gateway
    from app.ai.budget_evidence import BudgetRequestBinding
    from app.ai.budget_ledger import BudgetLedger

    interrupt_after_result(entry, monkeypatch)
    with configured_application_gateway(get_engine(), entry[3]) as gateway:
        assert claim_again(entry, gateway)
        run = rows(tables.agent_runs)[0]
        ledger = BudgetLedger(get_engine())
        prior = next(
            row for row in rows(tables.budget_journal) if row["request_binding"] is not None
        )
        binding = BudgetRequestBinding.model_validate(prior["request_binding"]).model_copy(
            update={"model_call_id": uuid4(), "structured_attempt": 1}
        )
        held = ledger.reserve(
            tenant_id=run["tenant_id"],
            run_id=run["id"],
            attempt_id=uuid4(),
            call_kind="model",
            input_tokens=prior["input_tokens"],
            output_tokens=prior["output_tokens"],
            tenant_daily_token_limit=100_000,
            request_binding=binding,
        )
        with pytest.raises(BudgetLedgerError, match="BUDGET_APPLICATION_RECOVERY_MODEL_FORBIDDEN"):
            ledger.transition(
                tenant_id=run["tenant_id"], attempt_id=held.entry.attempt_id, action="dispatch"
            )
        pending = [
            row for row in rows(tables.budget_journal) if row["attempt_id"] == held.entry.attempt_id
        ]
        assert pending and all(row["dispatched_at"] is None for row in pending)
        ledger.transition(
            tenant_id=run["tenant_id"], attempt_id=held.entry.attempt_id, action="cancel"
        )
    assert len(entry[2]) == 1
