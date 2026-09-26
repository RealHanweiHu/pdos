"""Real application factory, persisted user grants and revoked dispatch boundaries."""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Literal, NoReturn, NotRequired, TypedDict, Unpack
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, RowMapping, Table, func, select
from sqlalchemy.exc import DBAPIError

from app.ai import application_authorization, application_gateway
from app.ai.application_context import record_chat_context
from app.ai.budget_evidence import BudgetRequestBinding, BudgetUsageEvidence
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError, BudgetReceipt
from app.ai.chat import CHAT_PROMPT, ChatAssessment, ChatEvidenceRepository
from app.ai.chat_runs import ChatRunStore
from app.ai.gateway import BoundedModelProviderAdapter, GatewayInvocation, StructuredModelGateway
from app.ai.model_catalog import ResolvedModelRoute
from app.ai.provider_adapters import ChatMessage, ProviderCallLimits, ProviderResponse
from app.contracts.runtime_records import AuthorizationEnvelope
from app.db.schema import metadata, tables
from tests import test_application_budget_factory as base_factory
from tests.test_application_budget_factory import factory_setup as factory_setup
from tests.test_budget_ledger import SERVER_ROOT
from tests.test_budget_ledger import ledger_db as ledger_db
from tests.test_input_metering import publication
from tests.test_model_budget_controller import response as provider_response
from tests.test_model_gateway import invocation

type LedgerFixture = tuple[Engine, UUID, list[UUID]]
type FactoryFixture = tuple[dict[str, str], list[httpx2.Request], Path]


class ReserveArguments(TypedDict):
    tenant_id: UUID
    run_id: UUID
    attempt_id: UUID
    call_kind: Literal["model", "tool"]
    input_tokens: int
    output_tokens: int
    tenant_daily_token_limit: int
    request_binding: NotRequired[BudgetRequestBinding | None]


class TransitionArguments(TypedDict):
    tenant_id: UUID
    attempt_id: UUID
    action: Literal["dispatch", "unknown", "cancel", "settle"]
    charged_tokens: NotRequired[int | None]
    reconciliation_ref: NotRequired[str | None]
    provider_request_id: NotRequired[str | None]
    usage_evidence: NotRequired[BudgetUsageEvidence | None]


@pytest.fixture(autouse=True)
def chat_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    original_publication = publication
    monkeypatch.setattr(
        base_factory,
        "publication",
        lambda path: original_publication(path, qualified_input_limit=4000),
    )
    monkeypatch.setattr(
        base_factory,
        "response",
        lambda: provider_response('{"disposition":"insufficient_evidence","claims":[]}'),
    )


def identity(engine: Engine, *, grant: str = "member") -> tuple[UUID, UUID]:
    with engine.begin() as c:
        actor = c.execute(
            select(tables.users.c.id).where(tables.users.c.username == "reviewer")
        ).scalar_one()
        project = c.execute(select(tables.projects.c.id)).scalar_one()
        if grant == "owner":
            c.execute(tables.users.update().where(tables.users.c.id == actor).values(role="owner"))
            c.execute(tables.project_members.delete())
        if grant == "delegate":
            principal = actor
            actor = c.execute(
                select(tables.users.c.id).where(tables.users.c.username == "outsider")
            ).scalar_one()
            tenant = c.execute(select(tables.tenants.c.id)).scalar_one()
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            c.execute(
                tables.user_delegations.insert().values(
                    id=uuid4(),
                    tenant_id=tenant,
                    principal_user_id=principal,
                    delegate_user_id=actor,
                    starts_at=now - timedelta(seconds=5),
                    ends_at=now + timedelta(seconds=90),
                    reason="synthetic delegation",
                    created_by_user_id=principal,
                )
            )
    assert isinstance(actor, UUID) and isinstance(project, UUID)
    return actor, project


def start(
    engine: Engine,
    gateway: StructuredModelGateway,
    tenant: UUID,
    actor: UUID,
    project: UUID,
) -> tuple[RowMapping, GatewayInvocation]:
    row, created = ChatRunStore(engine, gateway=gateway).start(
        tenant_id=tenant,
        project_id=project,
        actor_user_id=actor,
        request_id=str(uuid4()),
        question="Synthetic question",
    )
    assert created
    evidence = ChatEvidenceRepository(engine).collect(
        tenant_id=tenant, project_id=project, question="Synthetic question"
    )
    call_id = uuid4()
    record_chat_context(
        engine,
        tenant_id=tenant,
        project_id=project,
        run_id=row["id"],
        model_call_id=call_id,
        question="Synthetic question",
        evidence=evidence,
    )
    request = invocation(tenant, run_id=row["id"], model_call_id=call_id).model_copy(
        update={
            "agent_key": "ai_chat",
            "project_id": project,
            "prompt_version": CHAT_PROMPT.version,
            "system_prompt": CHAT_PROMPT.system_prompt,
            "instruction": CHAT_PROMPT.instruction,
            "context": {
                "question": "Synthetic question",
                "references": [item.model_dump(mode="json", exclude={"href"}) for item in evidence],
            },
        }
    )
    return row, request


def records(engine: Engine, table: Table) -> list[RowMapping]:
    with engine.connect() as c:
        return list(c.execute(select(table)).mappings())


@pytest.mark.parametrize("grant", ["member", "owner", "delegate"])
def test_original_user_scope_and_grant_are_frozen_before_inference(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, grant: str
) -> None:
    engine, tenant, _ = ledger_db
    env, calls, _ = factory_setup
    actor, project = identity(engine, grant=grant)
    with application_gateway.configured_application_gateway(engine, env) as gateway:
        row, request = start(engine, gateway, tenant, actor, project)
        auth = records(engine, tables.application_authorizations)[0]
        envelope = AuthorizationEnvelope.model_validate(auth["body"])
        assert envelope.principal_kind == "user" and envelope.principal_id == actor
        assert envelope.trigger_actor_user_id == actor and envelope.scope.ref_id == project
        assert envelope.run_id == row["id"] and envelope.purpose == "chat_answer"
        assert bool(envelope.delegation_id) == (grant == "delegate")
        assert (
            envelope.expires_at <= records(engine, tables.budget_lineages)[0]["absolute_deadline"]
        )
        assert gateway.invoke_structured(request, ChatAssessment).status == "succeeded"
    assert len(calls) == 1 and str(auth["id"]) not in calls[0].content.decode()


@pytest.mark.parametrize(
    "revocation", ["membership", "role", "auth_version", "inactive", "delegation"]
)
def test_revocation_stops_before_input_metering(
    ledger_db: LedgerFixture,
    factory_setup: FactoryFixture,
    monkeypatch: pytest.MonkeyPatch,
    revocation: str,
) -> None:
    from app.ai.input_metering import LocalTemplateMeter

    engine, tenant, _ = ledger_db
    env, calls, _ = factory_setup
    actor, project = identity(engine, grant="delegate" if revocation == "delegation" else "member")
    with application_gateway.configured_application_gateway(engine, env) as gateway:
        _, request = start(engine, gateway, tenant, actor, project)
        with engine.begin() as c:
            if revocation == "membership":
                c.execute(tables.project_members.delete())
            elif revocation == "delegation":
                c.execute(
                    tables.user_delegations.update().values(
                        revoked_at=func.clock_timestamp(), revoked_by_user_id=actor
                    )
                )
            else:
                values = (
                    {"role": "customer"}
                    if revocation == "role"
                    else {"auth_version": 2}
                    if revocation == "auth_version"
                    else {"is_active": False}
                )
                c.execute(tables.users.update().where(tables.users.c.id == actor).values(**values))

        def forbidden(*args: object, **kwargs: object) -> NoReturn:
            pytest.fail("revoked content reached the input meter")

        monkeypatch.setattr(LocalTemplateMeter, "count", forbidden)
        result = gateway.invoke_structured(request, ChatAssessment)
        assert result.error_code == "APPLICATION_AUTHORIZATION_CHANGED", result
    assert calls == [] and records(engine, tables.budget_journal) == []


def test_revoked_after_metering_cancels_undispatched_reservation(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    env, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, env) as gateway:
        _, request = start(engine, gateway, tenant, actor, project)
        assert gateway._budget_controller is not None
        original = gateway._budget_controller._ledger.reserve

        def revoke(**kwargs: Unpack[ReserveArguments]) -> BudgetReceipt:
            result = original(**kwargs)
            with engine.begin() as c:
                c.execute(tables.project_members.delete())
            return result

        monkeypatch.setattr(gateway._budget_controller._ledger, "reserve", revoke)
        result = gateway.invoke_structured(request, ChatAssessment)
        assert result.error_code == "APPLICATION_AUTHORIZATION_CHANGED"
    assert calls == []
    assert (
        max(records(engine, tables.budget_journal), key=lambda r: r["revision"])[
            "reservation_status"
        ]
        == "cancelled_before_dispatch"
    )


def test_provider_response_after_revocation_is_charged_but_not_returned(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.model_catalog import ProtocolKind

    engine, tenant, _ = ledger_db
    env, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, env) as gateway:
        _, request = start(engine, gateway, tenant, actor, project)
        adapter = gateway._adapters[ProtocolKind.OPENAI_COMPATIBLE]
        assert isinstance(adapter, BoundedModelProviderAdapter)
        original = adapter.complete_bounded

        def revoke(
            route: ResolvedModelRoute,
            messages: Sequence[ChatMessage],
            *,
            limits: ProviderCallLimits,
        ) -> ProviderResponse:
            result = original(route, messages, limits=limits)
            with engine.begin() as c:
                c.execute(tables.project_members.delete())
            return result

        monkeypatch.setattr(adapter, "complete_bounded", revoke)
        result = gateway.invoke_structured(request, ChatAssessment)
        assert result.error_code == "APPLICATION_AUTHORIZATION_CHANGED" and result.output is None
    assert len(calls) == 1 and len(records(engine, tables.model_invocations)) == 1
    assert (
        max(records(engine, tables.budget_journal), key=lambda r: r["revision"])[
            "reservation_status"
        ]
        == "settled"
    )


def test_scope_and_policy_changes_are_not_new_authority(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    env, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, env) as gateway:
        _, request = start(engine, gateway, tenant, actor, project)
        wrong = request.model_copy(update={"project_id": uuid4()})
        assert (
            gateway.invoke_structured(wrong, ChatAssessment).error_code
            == "APPLICATION_AUTHORIZATION_BINDING_CHANGED"
        )
        monkeypatch.setattr(
            application_authorization, "policy_version", lambda: "sha256:" + "f" * 64
        )
        assert (
            gateway.invoke_structured(request, ChatAssessment).error_code
            == "APPLICATION_AUTHORIZATION_BINDING_CHANGED"
        )
    assert calls == []


def test_creation_denial_rolls_back_run_budget_and_authority(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, _ = ledger_db
    env, calls, _ = factory_setup
    actor, project = identity(engine)
    with engine.begin() as c:
        c.execute(tables.project_members.delete())
    before = len(records(engine, tables.agent_runs))
    with (
        application_gateway.configured_application_gateway(engine, env) as gateway,
        pytest.raises(BudgetLedgerError, match="APPLICATION_AUTHORIZATION_DENIED"),
    ):
        start(engine, gateway, tenant, actor, project)
    assert len(records(engine, tables.agent_runs)) == before and calls == []
    assert (
        records(engine, tables.application_authorizations)
        == records(engine, tables.budget_lineages)
        == []
    )


def test_history_immutable_and_database_dispatch_checks_current_grant(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, _ = ledger_db
    env, _, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, env) as gateway:
        row, _ = start(engine, gateway, tenant, actor, project)
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as c:
        c.execute(tables.application_authorizations.delete())
    with pytest.raises(DBAPIError, match="application (authorization|context|lease) history"):
        command.downgrade(Config(str(SERVER_ROOT / "alembic.ini")), "0080_context_manifests")
    ledger = BudgetLedger(engine)
    attempt = uuid4()
    ledger.reserve(
        tenant_id=tenant,
        run_id=row["id"],
        attempt_id=attempt,
        call_kind="model",
        input_tokens=10,
        output_tokens=10,
        tenant_daily_token_limit=100000,
    )
    with engine.begin() as c:
        member = dict(c.execute(select(tables.project_members)).mappings().one())
        c.execute(tables.project_members.delete())
        c.execute(tables.project_members.insert().values({**member, "id": uuid4()}))
    with pytest.raises(DBAPIError, match="BUDGET_APPLICATION_AUTHORIZATION_CHANGED"):
        ledger.transition(tenant_id=tenant, attempt_id=attempt, action="dispatch")
    assert len(records(engine, tables.budget_journal)) == 1


def test_metadata_and_empty_migration_roundtrip(ledger_db: LedgerFixture) -> None:
    engine, _, _ = ledger_db
    with engine.connect() as c:
        context = MigrationContext.configure(
            c,
            opts=dict(
                include_schemas=True,
                include_object=lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name == "application_authorizations"
                ),
            ),
        )
        assert compare_metadata(context, metadata) == []
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0080_context_manifests")
    command.upgrade(config, "head")


def test_original_session_version_cannot_be_reissued_after_wait(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, _ = ledger_db
    env, calls, _ = factory_setup
    actor, project = identity(engine)
    with engine.begin() as c:
        old_version = c.execute(
            select(tables.users.c.auth_version).where(tables.users.c.id == actor)
        ).scalar_one()
        c.execute(
            tables.users.update()
            .where(tables.users.c.id == actor)
            .values(auth_version=old_version + 1)
        )
    with (
        application_gateway.configured_application_gateway(engine, env) as gateway,
        pytest.raises(BudgetLedgerError, match="APPLICATION_AUTHORIZATION_DENIED"),
    ):
        ChatRunStore(engine, gateway=gateway).start(
            tenant_id=tenant,
            project_id=project,
            actor_user_id=actor,
            auth_version=old_version,
            request_id=str(uuid4()),
            question="Expired session",
        )
    assert calls == [] and records(engine, tables.application_authorizations) == []
    assert records(engine, tables.budget_lineages) == []


def test_old_budgeted_application_cannot_mint_missing_authority_at_dispatch(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture
) -> None:
    engine, tenant, _ = ledger_db
    env, calls, _ = factory_setup
    actor, project = identity(engine)
    row, _ = ChatRunStore(engine).start(
        tenant_id=tenant,
        project_id=project,
        actor_user_id=actor,
        request_id=str(uuid4()),
        question="Old application run",
    )
    from app.ai.budget_adoption import approved_budget_profile

    BudgetLedger(engine).open_lineage(
        tenant_id=tenant, run_id=row["id"], profile=approved_budget_profile("short")
    )
    evidence = ChatEvidenceRepository(engine).collect(
        tenant_id=tenant, project_id=project, question="Synthetic question"
    )
    call_id = uuid4()
    record_chat_context(
        engine,
        tenant_id=tenant,
        project_id=project,
        run_id=row["id"],
        model_call_id=call_id,
        question="Synthetic question",
        evidence=evidence,
    )
    request = invocation(tenant, run_id=row["id"], model_call_id=call_id).model_copy(
        update={
            "agent_key": "ai_chat",
            "project_id": project,
            "prompt_version": CHAT_PROMPT.version,
            "system_prompt": CHAT_PROMPT.system_prompt,
            "instruction": CHAT_PROMPT.instruction,
            "context": {
                "question": "Synthetic question",
                "references": [item.model_dump(mode="json", exclude={"href"}) for item in evidence],
            },
        }
    )
    with application_gateway.configured_application_gateway(engine, env) as gateway:
        assert (
            gateway.invoke_structured(request, ChatAssessment).error_code
            == "APPLICATION_AUTHORIZATION_CHANGED"
        )
    assert calls == [] and records(engine, tables.application_authorizations) == []


def test_database_closes_revocation_between_preflight_and_dispatch(
    ledger_db: LedgerFixture, factory_setup: FactoryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, tenant, _ = ledger_db
    env, calls, _ = factory_setup
    actor, project = identity(engine)
    with application_gateway.configured_application_gateway(engine, env) as gateway:
        _, request = start(engine, gateway, tenant, actor, project)
        assert gateway._budget_controller is not None
        ledger = gateway._budget_controller._ledger
        original = ledger.transition

        def revoke(**kwargs: Unpack[TransitionArguments]) -> BudgetReceipt:
            if kwargs["action"] == "dispatch":
                with engine.begin() as c:
                    c.execute(tables.project_members.delete())
            return original(**kwargs)

        monkeypatch.setattr(ledger, "transition", revoke)
        result = gateway.invoke_structured(request, ChatAssessment)
        assert result.error_code == "BUDGET_APPLICATION_AUTHORIZATION_CHANGED"
    assert calls == []
    assert (
        max(records(engine, tables.budget_journal), key=lambda r: r["revision"])[
            "reservation_status"
        ]
        == "cancelled_before_dispatch"
    )
