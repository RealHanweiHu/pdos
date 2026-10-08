"""Actual isolated PostgreSQL recovery and denials for the approved three traces."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import DBAPIError

from app.ai.budget_accounting import (
    BudgetAccountingError,
    LegacyUsageEvidence,
    LegacyUsageReconciler,
)
from app.ai.legacy_preview_holds import INVOCATIONS, TENANT, PreviewLegacyHolds
from app.ai.model_call_fence import ModelCallFence, ModelCallFenceError, ModelCallModeService
from app.auth.repository import AuthRepository
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants
from tests.test_budget_ledger import SERVER_ROOT
from tests.test_model_gateway_schema import valid_invocation


@pytest.fixture
def held_db(monkeypatch, request):
    url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(url))
    with engine.begin() as c:
        clear_test_tenants(c)
        c.execute(tables.tenants.insert(), dict(id=TENANT, slug="hold-test", name="Synthetic"))
        for role in ("owner", "project_manager"):
            c.execute(
                tables.users.insert(),
                dict(id=uuid4(), tenant_id=TENANT, username=role, display_name=role, role=role),
            )
    fence = ModelCallFence(engine)
    for index, identifier in enumerate(INVOCATIONS):
        session = fence.begin(
            tenant_id=TENANT,
            run_id=None,
            project_id=None,
            agent_key="project_intelligence",
            budgeted=False,
        )
        row = valid_invocation(TENANT)
        row.update(
            id=identifier,
            model="MiniMax-M3",
            status="provider_error",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            normalized_cost_microusd=None,
            error_code="PROVIDER_TRANSPORT_ERROR",
            usage_status="unknown",
            input_meter_version="normalized_input.v1",
            model_call_session_id=session,
            created_at=datetime(2026, 10, 6, 7, tzinfo=UTC),
        )
        with engine.begin() as c:
            c.execute(tables.model_invocations.insert(), row)
        if index != 2 or not getattr(request, "param", {}).get("leave_open"):
            fence.finish(tenant_id=TENANT, session_id=session, invocation_id=identifier)
    context = AuthRepository(engine).find_login_context(tenant_slug="hold-test", username="owner")
    assert context
    try:
        yield engine, context
    finally:
        with engine.begin() as c:
            clear_test_tenants(c)
        engine.dispose()


def accounting(engine, day):
    with engine.connect() as c:
        return (
            c.execute(
                text("SELECT * FROM cehub_ai.unbound_model_usage(:t,:now)"),
                dict(t=TENANT, now=datetime(2026, 10, day, 12, tzinfo=UTC)),
            )
            .mappings()
            .one()
        )


def adopt_all(engine, context):
    for identifier in INVOCATIONS:
        PreviewLegacyHolds(engine).adopt(
            context, identifier, approval_ref="synthetic-human-approval"
        )


def test_bounds_keep_unknown_trace_and_original_period_then_allow_mode(held_db):
    engine, context = held_db
    with engine.connect() as c:
        before = list(c.execute(select(tables.model_invocations)).mappings())
    adopt_all(engine, context)
    assert accounting(engine, 6)["additional_tokens"] == 3 * 1524288
    assert accounting(engine, 7)["additional_tokens"] == 0
    assert accounting(engine, 7)["unresolved_invocation_ids"] == []
    with engine.connect() as c:
        assert list(c.execute(select(tables.model_invocations)).mappings()) == before
        assert len(c.execute(select(tables.legacy_usage_holds)).all()) == 3
    service = ModelCallModeService(engine)
    assert (
        service.change(
            tenant_id=TENANT,
            actor_user_id=context.user.id,
            expected_revision=0,
            action="request",
            target="budgeted",
            evidence_ref="synthetic-approval",
        )
        == 1
    )
    assert (
        service.change(
            tenant_id=TENANT,
            actor_user_id=context.user.id,
            expected_revision=1,
            action="complete",
            evidence_ref="synthetic-approval",
        )
        == 2
    )


def test_replay_conflict_permissions_scope_and_append_only(held_db):
    engine, context = held_db
    service = PreviewLegacyHolds(engine)
    identifier = next(iter(INVOCATIONS))
    first = service.adopt(context, identifier, approval_ref="human")
    assert service.adopt(context, identifier, approval_ref="human") == first
    with pytest.raises(BudgetAccountingError, match="CONFLICT"):
        service.adopt(context, identifier, approval_ref="different")
    manager = AuthRepository(engine).find_login_context(
        tenant_slug="hold-test", username="project_manager"
    )
    with pytest.raises(BudgetAccountingError, match="FORBIDDEN"):
        service.adopt(manager, identifier, approval_ref="human")
    with pytest.raises(BudgetAccountingError, match="SCOPE_INVALID"):
        service.adopt(context, uuid4(), approval_ref="human")
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as c:
        c.execute(update(tables.legacy_usage_holds).values(input_token_bound=0))
    with pytest.raises(DBAPIError, match="permission denied"), engine.begin() as c:
        c.execute(text("SET LOCAL ROLE pdos_agent"))
        c.execute(select(tables.legacy_usage_holds))
    with pytest.raises(RuntimeError, match="history must be preserved"):
        command.downgrade(Config(str(SERVER_ROOT / "alembic.ini")), "0428_preproject_dialogue")


@pytest.mark.parametrize("held_db", [{"leave_open": True}], indirect=True)
def test_lower_bound_or_unclosed_call_is_rejected_by_database(held_db):
    engine, context = held_db
    identifiers = list(INVOCATIONS)
    PreviewLegacyHolds(engine).adopt(context, identifiers[0], approval_ref="human")
    with engine.connect() as c:
        row = dict(c.execute(select(tables.legacy_usage_holds)).mappings().one())
    row.update(id=uuid4(), invocation_id=identifiers[1], input_token_bound=999999)
    with pytest.raises(DBAPIError, match="preview_bounds"), engine.begin() as c:
        c.execute(tables.legacy_usage_holds.insert(), row)
    # An unknown session is not released by a conservative usage bound.
    with engine.connect() as c:
        session = c.execute(
            select(tables.model_invocations.c.model_call_session_id).where(
                tables.model_invocations.c.id == identifiers[2]
            )
        ).scalar_one()
    ModelCallFence(engine).unknown(tenant_id=TENANT, session_id=session)
    with pytest.raises(DBAPIError, match="TARGET_INVALID"):
        PreviewLegacyHolds(engine).adopt(context, identifiers[2], approval_ref="human")


def test_actual_receipt_appends_correction_and_new_unknown_still_blocks(held_db):
    engine, context = held_db
    adopt_all(engine, context)
    LegacyUsageReconciler(engine).reconcile(
        tenant_id=TENANT,
        invocation_id=next(iter(INVOCATIONS)),
        reviewer_user_id=context.user.id,
        evidence=LegacyUsageEvidence(
            evidence_ref="synthetic-actual", input_tokens=30, output_tokens=10
        ),
    )
    assert accounting(engine, 6)["additional_tokens"] == 2 * 1524288 + 40
    assert accounting(engine, 7)["additional_tokens"] == 0
    row = valid_invocation(TENANT)
    row.update(
        status="provider_error",
        usage_status="unknown",
        input_meter_version="normalized_input.v1",
        error_code="PROVIDER_TRANSPORT_ERROR",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        normalized_cost_microusd=None,
    )
    with engine.begin() as c:
        c.execute(tables.model_invocations.insert(), row)
    assert accounting(engine, 7)["unresolved_invocation_ids"] == [row["id"]]
    service = ModelCallModeService(engine)
    service.change(
        tenant_id=TENANT,
        actor_user_id=context.user.id,
        expected_revision=0,
        action="request",
        target="budgeted",
        evidence_ref="synthetic",
    )
    with pytest.raises(ModelCallFenceError, match="USAGE_UNRESOLVED"):
        service.change(
            tenant_id=TENANT,
            actor_user_id=context.user.id,
            expected_revision=1,
            action="complete",
            evidence_ref="synthetic",
        )
