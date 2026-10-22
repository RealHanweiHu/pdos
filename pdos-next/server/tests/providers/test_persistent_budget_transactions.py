"""Real PostgreSQL budget checks; root runs them on its verified isolated candidate.

No model HTTP requests are permitted. The shared engines/setup fixture verifies
the explicit database endpoint and marker before any synthetic rows are seeded.
"""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.model_gateway import CallPermit
from pdos_next.models import (
    Artifact,
    BudgetReservation,
    Confirmation,
    Invocation,
    Outbox,
    Product,
    Qualification,
    Run,
    WorkRequest,
    now,
)
from pdos_next.service import Context, digest


def human_session(setup, tenant=None):
    return tenant_session(
        setup.engine,
        setup.tenant if tenant is None else tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    )


@pytest.fixture(autouse=True)
def forbid_network_and_database(monkeypatch):
    """Override the package's pure-check guard only for this authorized DB module."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Budget database checks forbid model/network HTTP requests")

    original_send = httpx.Client.send

    def only_local_asgi(client, request, *args, **kwargs):
        if isinstance(client, TestClient) and request.url.host == "testserver":
            return original_send(client, request, *args, **kwargs)
        return forbidden()

    monkeypatch.setattr(httpx.Client, "send", only_local_asgi)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


@pytest.fixture
def budget_work(setup):
    artifact_id, work_id, run_id = uuid4(), uuid4(), uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(
            Artifact(
                id=artifact_id,
                tenant_id=setup.tenant,
                product_id=setup.product,
                owner_id=setup.human,
                title="Synthetic budget source",
                source_label="Synthetic accounting verification",
                content="Synthetic source: sample quantity unknown",
                content_hash=digest("Synthetic source: sample quantity unknown"),
                visibility="private",
            )
        )
        s.flush()
        s.add(
            WorkRequest(
                id=work_id,
                tenant_id=setup.tenant,
                product_id=setup.product,
                artifact_id=artifact_id,
                source_revision=1,
                goal="Record one sourced synthetic claim",
                outcome_spec={
                    "object_type": "claim",
                    "minimum_records": 1,
                    "source_required": True,
                },
                accountable_owner_id=setup.human,
                authorization={"operation": "evidence.claim.record", "purpose": "source_claim"},
                max_actions=1,
                stop_condition="one_sourced_claim_or_input_required",
                status="running",
            )
        )
        s.flush()
        s.add(
            Run(
                id=run_id,
                tenant_id=setup.tenant,
                product_id=setup.product,
                work_id=work_id,
                requester_id=setup.human,
                writer_id=setup.agent,
                status="running",
                skill_version="source-claim@1",
                provider_version="synthetic-budget@1",
                token_limit=10000,
            )
        )
        s.add(
            Qualification(
                tenant_id=setup.tenant,
                writer_id=setup.agent,
                skill_version="source-claim@1",
                provider_version="synthetic-budget@1",
                operation="evidence.claim.record",
                purpose="source_claim",
                evaluation_kind="synthetic",
                evaluation_ref="budget-test-only-not-real-qualification",
                expires_at=now() + timedelta(hours=1),
                active=True,
            )
        )
    ctx = Context(setup.tenant, setup.agent, setup.human, run_id, 0)
    permit = CallPermit(
        call_id=uuid4(),
        request_digest=digest("synthetic-budget-request"),
        route_digest=digest("synthetic-budget-route"),
        writer_id=setup.agent,
        provider_version="synthetic-budget@1",
        expires_at=now() + timedelta(hours=1),
        egress_allowed=True,
        protocol="openai-compatible",
    )

    def state():
        with human_session(setup) as s:
            run = s.get(Run, run_id)
            rows = s.scalars(
                select(BudgetReservation).where(BudgetReservation.run_id == run_id)
            ).all()
            return SimpleNamespace(
                used=run.used_tokens,
                reserved=run.reserved_tokens,
                limit=run.token_limit,
                rows=[
                    SimpleNamespace(
                        call_id=row.call_id,
                        status=row.status,
                        charged=row.charged,
                        reserved=row.reserved,
                        token_hash=row.token_hash,
                        error_code=row.error_code,
                        revision=row.revision,
                        normalized_usage=row.normalized_usage,
                        request_id=row.request_id,
                        provider_version=row.provider_version,
                        protocol=row.protocol,
                        route_digest=row.route_digest,
                        settled_at=row.settled_at,
                        history=row.reconciliation_history,
                    )
                    for row in rows
                ],
            )

    return SimpleNamespace(setup=setup, ctx=ctx, permit=permit, state=state, run_id=run_id)


def test_agent_cannot_directly_write_budget_rows(budget_work):
    fixture = budget_work.setup
    for action in ["INSERT", "UPDATE", "DELETE"]:
        with fixture.engine.connect() as connection:
            allowed = connection.execute(
                text(
                    "SELECT has_table_privilege('pdos_agent', 'model_budget_reservations', :action)"
                ),
                {"action": action},
            ).scalar_one()
            assert allowed is False
    with pytest.raises(DBAPIError) as denied, fixture.admin.begin() as connection:
        connection.execute(text("SET LOCAL ROLE pdos_agent"))
        connection.execute(
            text("UPDATE public.model_budget_reservations SET status=status WHERE false")
        )
    assert getattr(denied.value.orig, "sqlstate", None) == "42501"


def test_accounting_rows_are_tenant_isolated_and_pool_scope_resets(budget_work):
    _unknown_call(budget_work)
    with human_session(budget_work.setup, uuid4()) as s:
        assert (
            s.scalar(
                select(BudgetReservation).where(
                    BudgetReservation.call_id == budget_work.permit.call_id
                )
            )
            is None
        )
    with budget_work.setup.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM model_budget_reservations")).scalar_one()
            == 0
        )


def _unknown_call(budget_work):
    """Seed one persisted technical accounting fact; never run the retired pipeline."""
    fixture = budget_work.setup
    with Session(fixture.admin) as s, s.begin():
        run = s.get(Run, budget_work.run_id)
        run.reserved_tokens = 130
        s.add(
            BudgetReservation(
                tenant_id=fixture.tenant,
                run_id=run.id,
                call_id=budget_work.permit.call_id,
                token_hash=digest("synthetic-budget-token"),
                request_digest=budget_work.permit.request_digest,
                reserved=130,
                status="unknown",
                revision=2,
                error_code="MODEL_RESULT_UNKNOWN",
                provider_version="synthetic-budget@1",
                protocol="openai-compatible",
                route_digest=budget_work.permit.route_digest,
                request_id="synthetic-provider-request-1",
            )
        )
        s.add(
            Invocation(
                tenant_id=fixture.tenant,
                run_id=run.id,
                call_id=budget_work.permit.call_id,
                step_key="synthetic-budget-step",
                input_digest=digest("synthetic-budget-invocation"),
                provider_version="synthetic-budget@1",
                status="unknown",
                error_code="MODEL_RESULT_UNKNOWN",
            )
        )


def _reconciliation_command(budget_work, *, resolution="known", usage=None):
    with human_session(budget_work.setup) as s:
        product_revision = s.get(Product, budget_work.setup.product).revision
    payload = {
        "call_id": str(budget_work.permit.call_id),
        "expected_revision": budget_work.state().rows[0].revision,
        "resolution": resolution,
        "usage": (usage or {"input_tokens": 50, "output_tokens": 30})
        if resolution == "known"
        else None,
        "request_id": "synthetic-provider-request-1",
        "reason_code": "provider_usage_verified"
        if resolution == "known"
        else "provider_usage_unavailable",
        "evidence_ref": "synthetic-statement:20261002",
    }
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": "ai.model_call.reconcile",
        "category_id": str(budget_work.setup.category),
        "product_id": str(budget_work.setup.product),
        "expected_revision": product_revision,
        "source_read_set": [],
        "payload": payload,
    }


def _confirm(budget_work, command):
    fixture = budget_work.setup
    response = fixture.client.post(
        f"/v1/categories/{fixture.category}/commands/preview", json=command, headers=fixture.headers
    )
    assert response.status_code == 200, response.text
    command["payload"]["confirmation_token"] = response.json()["confirmation_token"]
    return response.json()


def _submit(budget_work, command):
    fixture = budget_work.setup
    return fixture.client.post(
        f"/v1/categories/{fixture.category}/commands", json=command, headers=fixture.headers
    )


def _assert_model_outcome_unchanged(budget_work):
    with human_session(budget_work.setup) as s:
        run = s.get(Run, budget_work.run_id)
        invocation = s.scalar(
            select(Invocation).where(Invocation.call_id == budget_work.permit.call_id)
        )
        assert run.status == "running"
        assert invocation.status == "unknown" and invocation.candidate is None


def test_human_known_reconciliation_charges_once_without_resuming_model(budget_work):
    _unknown_call(budget_work)
    command = _reconciliation_command(budget_work)
    reviewed = _confirm(budget_work, command)
    assert reviewed["review"]["before"]["held_tokens"] == 130
    assert reviewed["review"]["before"]["can_retry"] is False
    assert reviewed["review"]["after"]["held_tokens"] == 0
    assert reviewed["review"]["after"]["charged_tokens"] == 80
    first = _submit(budget_work, command)
    assert first.status_code == 200, first.text
    repeated = _submit(budget_work, command)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == first.json()
    state = budget_work.state()
    assert state.used == 80 and state.reserved == 0
    assert state.rows[0].charged == 80 and len(state.rows[0].history) == 1
    assert state.rows[0].history[0]["actor_id"] == str(budget_work.setup.human)
    assert state.rows[0].history[0]["prior_revision"] == 2
    _assert_model_outcome_unchanged(budget_work)


def test_human_unknown_review_keeps_cost_held_and_records_reason(budget_work):
    _unknown_call(budget_work)
    command = _reconciliation_command(budget_work, resolution="unknown")
    _confirm(budget_work, command)
    response = _submit(budget_work, command)
    assert response.status_code == 200, response.text
    state = budget_work.state()
    assert state.used == 0 and state.reserved == 130
    assert state.rows[0].charged is None and state.rows[0].status == "unknown"
    assert state.rows[0].revision == 3 and len(state.rows[0].history) == 1
    history = state.rows[0].history[0]
    assert history["reason_code"] == "provider_usage_unavailable"
    assert history["usage"] is None and history["occurred_at"]
    _assert_model_outcome_unchanged(budget_work)


def test_confirmation_payload_change_does_not_consume_original_token(budget_work):
    _unknown_call(budget_work)
    command = _reconciliation_command(budget_work)
    _confirm(budget_work, command)
    command["payload"]["usage"]["input_tokens"] = 60
    changed = _submit(budget_work, command)
    assert changed.status_code == 409, changed.text
    assert changed.json()["code"] == "CONFIRMATION_REQUIRED"
    assert changed.json()["detail"]["reason"] == "CONFIRMATION_SCOPE_CHANGED"
    assert budget_work.state().used == 0 and budget_work.state().reserved == 130
    command["payload"]["usage"]["input_tokens"] = 50
    accepted = _submit(budget_work, command)
    assert accepted.status_code == 200, accepted.text
    assert budget_work.state().used == 80


def test_human_confirmed_overrun_records_fee_and_does_not_resume_run(budget_work):
    with Session(budget_work.setup.admin) as s, s.begin():
        s.get(Run, budget_work.run_id).token_limit = 150
    _unknown_call(budget_work)
    command = _reconciliation_command(budget_work, usage={"input_tokens": 150, "output_tokens": 30})
    _confirm(budget_work, command)
    response = _submit(budget_work, command)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["budget_exceeded"] is True
    state = budget_work.state()
    assert state.used == 180 and state.reserved == 0 and state.rows[0].charged == 180
    _assert_model_outcome_unchanged(budget_work)


def test_peer_product_write_grant_does_not_expose_private_call_for_reconciliation(budget_work):
    _unknown_call(budget_work)
    fixture = budget_work.setup
    response = fixture.client.post(
        f"/v1/categories/{fixture.category}/commands/preview",
        json=_reconciliation_command(budget_work),
        headers={"Authorization": f"Bearer {fixture.tokens[fixture.peer]}"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_SCOPE"
    assert budget_work.state().used == 0 and budget_work.state().reserved == 130


def test_reconciliation_outbox_failure_rolls_back_fee_history_and_confirmation(budget_work):
    _unknown_call(budget_work)
    command = _reconciliation_command(budget_work)
    _confirm(budget_work, command)

    def fail_outbox(mapper, connection, target):
        raise RuntimeError("synthetic-outbox-failure")

    event.listen(Outbox, "before_insert", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="synthetic-outbox-failure"):
            _submit(budget_work, command)
    finally:
        event.remove(Outbox, "before_insert", fail_outbox)
    state = budget_work.state()
    assert state.used == 0 and state.reserved == 130
    assert state.rows[0].revision == 2 and state.rows[0].history == []
    with human_session(budget_work.setup) as s:
        confirmation = s.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
            )
        )
        assert confirmation.consumed is False
    accepted = _submit(budget_work, command)
    assert accepted.status_code == 200, accepted.text
    assert budget_work.state().used == 80
