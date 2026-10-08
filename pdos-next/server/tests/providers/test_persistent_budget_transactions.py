"""Real PostgreSQL budget checks; root runs them on its verified isolated candidate.

No model HTTP requests are permitted. The shared engines/setup fixture verifies
the explicit database endpoint and marker before any synthetic rows are seeded.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.model_gateway import CallPermit, Reservation
from pdos_next.model_gateway.persistent_budget import DatabaseBudgetPort
from pdos_next.models import (
    Artifact,
    BudgetReservation,
    Confirmation,
    Grant,
    Invocation,
    Outbox,
    Product,
    Qualification,
    Run,
    WorkRequest,
    now,
)
from pdos_next.providers import ProviderUsage
from pdos_next.runtime import OnceInvocation
from pdos_next.service import Context, check_run, digest


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

    def port():
        return DatabaseBudgetPort(setup.engine, ctx, lambda _: None, synthetic_mode=True)

    def state():
        with tenant_session(setup.engine, setup.tenant) as s:
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

    return SimpleNamespace(
        setup=setup, ctx=ctx, permit=permit, port=port, state=state, run_id=run_id
    )


@pytest.mark.parametrize("status", ["reserved", "completed", "rejected", "unknown"])
def test_cross_instance_reservation_never_reissues_an_existing_call(budget_work, status):
    first, second = budget_work.port(), budget_work.port()
    reservation = first.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    if status == "unknown":
        first.unknown(reservation, error_code="PROVIDER_RESULT_UNKNOWN")
    elif status in {"completed", "rejected"}:
        first.settle(reservation, usage=ProviderUsage(50, 30), outcome=status)
    with pytest.raises(DomainError) as denied:
        second.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    assert denied.value.code == "MODEL_CALL_ALREADY_ATTEMPTED"
    state = budget_work.state()
    assert len(state.rows) == 1 and state.rows[0].status == status
    assert state.rows[0].token_hash == digest(reservation.token)
    assert state.rows[0].token_hash != reservation.token
    assert state.reserved == (130 if status in {"reserved", "unknown"} else 0)
    assert state.used == (80 if status in {"completed", "rejected"} else 0)


def test_concurrent_same_call_creates_one_reservation(budget_work):
    ports = [budget_work.port(), budget_work.port()]
    ready = Barrier(2)

    def attempt(port):
        ready.wait(timeout=10)
        try:
            port.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
            return "reserved"
        except DomainError as denied:
            return denied.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ports))
    assert sorted(results) == ["MODEL_CALL_ALREADY_ATTEMPTED", "reserved"]
    state = budget_work.state()
    assert len(state.rows) == 1 and state.reserved == 130 and state.used == 0


@pytest.mark.parametrize("change", ["token", "call"])
def test_bad_reservation_token_or_call_cannot_charge(budget_work, change):
    port = budget_work.port()
    reservation = port.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    forged = (
        replace(reservation, token="synthetic-forged-budget-token")
        if change == "token"
        else Reservation(uuid4(), reservation.token)
    )
    with pytest.raises(DomainError) as denied:
        port.settle(forged, usage=ProviderUsage(50, 30), outcome="completed")
    assert denied.value.code == "MODEL_BUDGET_INVALID"
    state = budget_work.state()
    assert state.used == 0 and state.reserved == 130
    assert state.rows[0].status == "reserved" and state.rows[0].charged is None


def test_duplicate_settlement_charges_once_and_different_usage_conflicts(budget_work):
    first, second = budget_work.port(), budget_work.port()
    reservation = first.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    first.settle(reservation, usage=ProviderUsage(50, 30), outcome="completed")
    second.settle(reservation, usage=ProviderUsage(50, 30), outcome="completed")
    with pytest.raises(DomainError) as denied:
        second.settle(reservation, usage=ProviderUsage(51, 30), outcome="completed")
    assert denied.value.code == "MODEL_BUDGET_CONFLICT"
    state = budget_work.state()
    assert state.used == 80 and state.reserved == 0 and state.rows[0].charged == 80


def test_unknown_keeps_reservation_until_usage_reconciled_once(budget_work):
    first, second = budget_work.port(), budget_work.port()
    reservation = first.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    first.unknown(reservation, error_code="PROVIDER_RESULT_UNKNOWN")
    second.unknown(reservation, error_code="PROVIDER_RESULT_UNKNOWN")
    unknown = budget_work.state()
    assert unknown.reserved == 130 and unknown.used == 0
    assert unknown.rows[0].status == "unknown" and unknown.rows[0].charged is None
    second.settle(reservation, usage=ProviderUsage(50, 30), outcome="completed")
    known = budget_work.state()
    assert known.reserved == 0 and known.used == 80 and known.rows[0].status == "completed"
    with pytest.raises(DomainError) as denied:
        first.unknown(reservation, error_code="PROVIDER_RESULT_UNKNOWN")
    assert denied.value.code == "MODEL_BUDGET_CONFLICT"
    assert budget_work.state().used == 80


@pytest.mark.parametrize("revoked", ["cancel", "grant", "qualification"])
def test_inflight_cost_is_recorded_after_authority_revocation(budget_work, revoked):
    port = budget_work.port()
    reservation = port.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    fixture = budget_work.setup
    with Session(fixture.admin) as s, s.begin():
        if revoked == "cancel":
            run = s.get(Run, budget_work.run_id)
            run.status, run.cancel_epoch = "cancelled", 1
        elif revoked == "grant":
            grant = s.scalar(
                select(Grant).where(
                    Grant.tenant_id == fixture.tenant,
                    Grant.product_id == fixture.product,
                    Grant.principal_id == fixture.agent,
                )
            )
            grant.expires_at = now() - timedelta(seconds=1)
        else:
            qualification = s.scalar(
                select(Qualification).where(
                    Qualification.tenant_id == fixture.tenant,
                    Qualification.writer_id == fixture.agent,
                )
            )
            qualification.active = False
    budget_work.port().settle(reservation, usage=ProviderUsage(50, 30), outcome="completed")
    state = budget_work.state()
    assert state.used == 80 and state.reserved == 0 and state.rows[0].charged == 80
    with pytest.raises(DomainError):
        budget_work.port().reserve(
            replace(budget_work.permit, call_id=uuid4()), input_bytes=100, max_output_tokens=30
        )
    assert len(budget_work.state().rows) == 1


def test_overrun_commits_real_usage_before_stopping_further_execution(budget_work):
    with Session(budget_work.setup.admin) as s, s.begin():
        s.get(Run, budget_work.run_id).token_limit = 150
    port = budget_work.port()
    reservation = port.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    with pytest.raises(DomainError) as stopped:
        port.settle(reservation, usage=ProviderUsage(150, 30), outcome="completed")
    assert stopped.value.code == "MODEL_BUDGET_EXCEEDED"
    state = budget_work.state()
    assert state.used == 180 and state.reserved == 0
    assert state.rows[0].charged == 180 and state.rows[0].status == "completed"
    with pytest.raises(DomainError) as denied:
        budget_work.port().reserve(
            replace(budget_work.permit, call_id=uuid4()), input_bytes=1, max_output_tokens=1
        )
    assert denied.value.code == "MODEL_BUDGET_EXCEEDED"
    assert len(budget_work.state().rows) == 1
    with pytest.raises(DomainError) as blocked:
        with tenant_session(budget_work.setup.engine, budget_work.setup.tenant) as s:
            check_run(s, budget_work.ctx, budget_work.setup.product)
    assert blocked.value.code == "MODEL_BUDGET_EXCEEDED"


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
        connection.execute(text("UPDATE model_budget_reservations SET status=status WHERE false"))
    assert getattr(denied.value.orig, "sqlstate", None) == "42501"


def test_accounting_rows_are_tenant_isolated_and_pool_scope_resets(budget_work):
    budget_work.port().reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    with tenant_session(budget_work.setup.engine, uuid4()) as s:
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


def test_trace_and_normalized_usage_stay_bound_to_original_call(budget_work):
    port = budget_work.port()
    reservation = port.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    reserved = budget_work.state().rows[0]
    assert reserved.provider_version == "synthetic-budget@1"
    assert reserved.protocol == "openai-compatible"
    assert reserved.route_digest == budget_work.permit.route_digest
    assert reserved.revision == 1
    port.unknown(
        reservation, error_code="PROVIDER_RESULT_UNKNOWN", request_id="synthetic-request-1"
    )
    with pytest.raises(DomainError) as denied:
        port.settle(
            reservation,
            usage=ProviderUsage(50, 30, 20, 10),
            outcome="completed",
            request_id="synthetic-other-request",
        )
    assert denied.value.code == "MODEL_BUDGET_CONFLICT"
    port.settle(
        reservation,
        usage=ProviderUsage(50, 30, 20, 10),
        outcome="completed",
        request_id="synthetic-request-1",
    )
    settled = budget_work.state().rows[0]
    assert settled.request_id == "synthetic-request-1"
    assert settled.normalized_usage == {
        "input_tokens": 50,
        "output_tokens": 30,
        "cache_read_tokens": 20,
        "cache_creation_tokens": 10,
    }
    assert settled.revision == 3 and settled.settled_at is not None
    with pytest.raises(DomainError) as breakdown:
        port.settle(
            reservation,
            usage=ProviderUsage(50, 30, 21, 9),
            outcome="completed",
            request_id="synthetic-request-1",
        )
    assert breakdown.value.code == "MODEL_BUDGET_CONFLICT"
    assert budget_work.state().used == 80


def _unknown_call(budget_work):
    port = budget_work.port()
    reservation = port.reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    port.unknown(
        reservation,
        error_code="PROVIDER_RESULT_UNKNOWN",
        request_id="synthetic-provider-request-1",
    )
    fixture = budget_work.setup
    with Session(fixture.admin) as s, s.begin():
        s.add(
            Invocation(
                tenant_id=fixture.tenant,
                run_id=budget_work.run_id,
                call_id=budget_work.permit.call_id,
                step_key="synthetic-budget-step",
                input_digest=digest("synthetic-budget-invocation"),
                provider_version="synthetic-budget@1",
                status="unknown",
                error_code="MODEL_RESULT_UNKNOWN",
            )
        )
    return reservation


def _reconciliation_command(budget_work, *, resolution="known", usage=None):
    with tenant_session(budget_work.setup.engine, budget_work.setup.tenant) as s:
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
        "product_id": str(budget_work.setup.product),
        "expected_revision": product_revision,
        "source_read_set": [],
        "payload": payload,
    }


def _confirm(budget_work, command):
    fixture = budget_work.setup
    response = fixture.client.post("/v1/commands/preview", json=command, headers=fixture.headers)
    assert response.status_code == 200, response.text
    command["payload"]["confirmation_token"] = response.json()["confirmation_token"]
    return response.json()


def _submit(budget_work, command):
    fixture = budget_work.setup
    return fixture.client.post("/v1/commands", json=command, headers=fixture.headers)


def _assert_model_outcome_unchanged(budget_work):
    with tenant_session(budget_work.setup.engine, budget_work.setup.tenant) as s:
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
    with pytest.raises(DomainError) as denied:
        budget_work.port().reserve(budget_work.permit, input_bytes=100, max_output_tokens=30)
    assert denied.value.code == "MODEL_CALL_ALREADY_ATTEMPTED"


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
    assert changed.json()["code"] == "CONFIRMATION_SCOPE_CHANGED"
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
        "/v1/commands/preview",
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
    with tenant_session(budget_work.setup.engine, budget_work.setup.tenant) as s:
        confirmation = s.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
            )
        )
        assert confirmation.consumed is False
    accepted = _submit(budget_work, command)
    assert accepted.status_code == 200, accepted.text
    assert budget_work.state().used == 80


def _once_invocation_fixture(budget_work, *, unknown=False):
    fixture = budget_work.setup
    with tenant_session(fixture.engine, fixture.tenant) as s:
        run = s.get(Run, budget_work.run_id)
        work = s.get(WorkRequest, run.work_id)
        artifact = s.get(Artifact, work.artifact_id)
        request = {"goal": work.goal, "source": artifact.content, "artifact_id": artifact.id}
    candidate = {
        "artifact_id": str(request["artifact_id"]),
        "line": 1,
        "quote": request["source"],
        "statement": "Synthetic source reports an unknown quantity",
        "nature": "extracted",
        "availability": "unknown",
        "visibility": "private",
    }

    class Factory:
        version = "synthetic-budget@1"
        writer_id = fixture.agent

        def __init__(self):
            self.bindings = []
            self.extractions = 0

        def extract(self, **material):
            pytest.fail("OnceInvocation must bind the server call before extraction")

        def for_call(self, *, ctx, call_id, product_id, source_revision):
            assert ctx == budget_work.ctx and product_id == fixture.product
            assert source_revision == 1
            with tenant_session(fixture.engine, fixture.tenant) as s:
                persisted = s.scalar(
                    select(Invocation).where(
                        Invocation.run_id == budget_work.run_id,
                        Invocation.step_key == "source-claim-extract-v1",
                    )
                )
                assert persisted.call_id == call_id and persisted.status == "started"
            self.bindings.append(call_id)

            def extract(**material):
                assert material == request
                self.extractions += 1
                port = budget_work.port()
                permit = replace(
                    budget_work.permit,
                    call_id=call_id,
                    request_digest=digest(material),
                )
                reservation = port.reserve(permit, input_bytes=100, max_output_tokens=30)
                if unknown:
                    port.unknown(
                        reservation,
                        error_code="PROVIDER_RESULT_UNKNOWN",
                        request_id="synthetic-once-request-1",
                    )
                    raise RuntimeError("synthetic-provider-result-unknown")
                port.settle(
                    reservation,
                    usage=ProviderUsage(50, 30),
                    outcome="completed",
                    request_id="synthetic-once-request-1",
                )
                return candidate

            return SimpleNamespace(version=self.version, writer_id=self.writer_id, extract=extract)

    provider = Factory()

    def once():
        return OnceInvocation(fixture.engine, budget_work.ctx, fixture.product, 1, provider, True)

    return SimpleNamespace(provider=provider, request=request, candidate=candidate, once=once)


def test_once_invocation_call_and_fee_match_and_saved_candidate_replays_without_charge(budget_work):
    bound = _once_invocation_fixture(budget_work)
    first = bound.once().extract(**bound.request)
    assert first == bound.candidate
    with tenant_session(budget_work.setup.engine, budget_work.setup.tenant) as s:
        invocation = s.scalar(select(Invocation).where(Invocation.run_id == budget_work.run_id))
        row = s.scalar(
            select(BudgetReservation).where(BudgetReservation.run_id == budget_work.run_id)
        )
        assert invocation.call_id == row.call_id == bound.provider.bindings[0]
        assert invocation.status == "completed" and invocation.candidate == first
        assert row.status == "completed" and row.charged == 80
    # A new wrapper represents recovery after the provider adapter's process-local state is gone.
    assert bound.once().extract(**bound.request) == first
    assert len(bound.provider.bindings) == 1 and bound.provider.extractions == 1
    state = budget_work.state()
    assert state.used == 80 and state.reserved == 0 and len(state.rows) == 1


def test_once_invocation_unknown_keeps_original_hold_and_never_rebinds_or_resends(budget_work):
    bound = _once_invocation_fixture(budget_work, unknown=True)
    with pytest.raises(RuntimeError, match="synthetic-provider-result-unknown"):
        bound.once().extract(**bound.request)
    with tenant_session(budget_work.setup.engine, budget_work.setup.tenant) as s:
        invocation = s.scalar(select(Invocation).where(Invocation.run_id == budget_work.run_id))
        row = s.scalar(
            select(BudgetReservation).where(BudgetReservation.run_id == budget_work.run_id)
        )
        assert invocation.call_id == row.call_id == bound.provider.bindings[0]
        assert invocation.status == "unknown" and invocation.candidate is None
        assert row.status == "unknown" and row.charged is None
    with pytest.raises(DomainError) as blocked:
        bound.once().extract(**bound.request)
    assert blocked.value.code == "MODEL_RESULT_UNKNOWN"
    assert len(bound.provider.bindings) == 1 and bound.provider.extractions == 1
    state = budget_work.state()
    assert state.used == 0 and state.reserved == 130 and len(state.rows) == 1
