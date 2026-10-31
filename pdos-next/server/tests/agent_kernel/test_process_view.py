"""Actual public process projection and terminal timestamps; zero model calls."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentEvent, AgentRun
from pdos_next.agent_kernel.persistence import cancel_run
from pdos_next.agent_kernel.process_view import read_process, record_state
from pdos_next.clock import now, using_clock
from pdos_next.database import tenant_session
from pdos_next.models import Artifact, Grant
from pdos_next.service import digest
from tests.agent_kernel.test_revert import receipt
from tests.agent_kernel.test_transactions import human_session, run


def path(setup, scope):
    return f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}"


def test_process_reads_actual_call_receipt_and_selected_events_without_raw_content(setup):
    store, scope = run(setup)
    call, _ = store.claim(scope, "private-params", "category.read", {"private": "raw arguments"})
    saved = receipt(setup, scope)
    store.settle(scope, call, result={"secret_result": "raw provider reply"}, receipt_id=saved)
    store.emit(scope, {"type": "model_started", "turn": 1, "text": "private reasoning"})
    store.emit(scope, {"type": "text_delta", "text": "private streamed reasoning"})
    store.emit(scope, {"type": "tool_finished", "tool": "category.read", "arguments": "hidden"})
    statements = []

    def observe(_, __, statement, *___):
        statements.append(statement)

    event.listen(setup.engine, "before_cursor_execute", observe)
    try:
        response = setup.client.get(path(setup, scope) + "/process", headers=setup.headers)
    finally:
        event.remove(setup.engine, "before_cursor_execute", observe)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["call_counts"] == {"total": 1, "completed": 1, "pending": 0, "failed": 0}
    assert data["business_receipt_count"] == 1 and data["receipts"][0]["id"] == str(saved)
    assert [row["kind"] for row in data["steps"]] == ["model_started", "tool_finished"]
    assert not any(
        text in response.text
        for text in [
            "raw arguments",
            "raw provider",
            "private reasoning",
            "private streamed",
            '"arguments"',
            '"text"',
        ]
    )
    sql = "\n".join(statements)
    assert "agent_tool_calls.result" not in sql and "agent_tool_calls.execution_binding" not in sql
    assert "agent_runs.result" not in sql and "agent_runs.versions" not in sql
    assert "agent_run_events.body," not in sql and " LIMIT " in sql


def test_service_run_process_checks_binding_without_exposing_fixed_goal(setup):
    from pdos_next.domain.automations import service_runtime
    from pdos_next.domain.automations.service_models import AutomationServiceAttempt
    from tests.automations_pg.test_service_automation_pg import _activate, _ready, _spec

    spec = _spec(setup, _ready(setup))
    _, reference = _activate(setup, spec)
    service_runtime.tick(setup.engine, reference)
    with Session(setup.admin) as session:
        identity = session.scalar(select(AutomationServiceAttempt.run_id).where(
            AutomationServiceAttempt.service_grant_id == UUID(reference["grant_id"]),
        ))
    resource = f"/v1/categories/{setup.category}/agent-runs/{identity}/process"
    response = setup.client.get(resource, headers=setup.headers)
    assert response.status_code == 200, response.text
    assert response.json()["run_id"] == str(identity)
    assert response.json()["business_receipt_count"] == 0
    assert spec["goal"] not in response.text
    assert setup.client.get(resource, headers={
        "Authorization": "Bearer " + setup.tokens[setup.peer],
    }).status_code == 403


def test_terminal_time_is_atomic_and_stable_after_refresh_and_original_cancel_replay(setup):
    start = now()
    with using_clock(lambda: start):
        store, scope = run(setup)
    with using_clock(lambda: start + timedelta(seconds=65)):
        with human_session(setup) as session:
            cancel_run(session, setup.ctx, scope.run_id)
    with using_clock(lambda: start + timedelta(hours=1)):
        with human_session(setup) as session:
            cancel_run(session, setup.ctx, scope.run_id)
            row = session.get(AgentRun, scope.run_id)
            data = read_process(session, row)
            assert data["elapsed_seconds"] == 65
            assert data["status"] == "cancelled"
            assert len(data["steps"]) == 1
    value = setup.client.get(path(setup, scope), headers=setup.headers).json()["process"]
    assert value["elapsed_seconds"] == 65 and value["ended_at"] == data["ended_at"]


def test_completed_run_is_not_claimed_as_business_approval_and_old_missing_end_stays_unknown(setup):
    store, scope = run(setup)
    store.finish(scope, {"status": "completed", "summary": "Synthetic complete", "result": {}})
    data = setup.client.get(path(setup, scope) + "/process", headers=setup.headers).json()
    assert data["ended_at"] and data["business_receipt_count"] == 0
    now_for_replay = now() + timedelta(minutes=5)
    with using_clock(lambda: now_for_replay):
        store.finish(scope, {"status": "completed", "summary": "Synthetic complete", "result": {}})
    replay = setup.client.get(path(setup, scope) + "/process", headers=setup.headers).json()
    assert replay["ended_at"] == data["ended_at"] and replay["steps"] == data["steps"]
    old_store, old = run(setup)
    with old_store.transaction(old, lock=True) as (_, row):
        row.state = "failed"
    legacy = setup.client.get(path(setup, old) + "/process", headers=setup.headers).json()
    assert legacy["ended_at"] is None and legacy["elapsed_seconds"] is None


def test_timeline_uses_bounded_complete_pages_and_ignores_provider_delta_volume(setup):
    store, scope = run(setup)
    with store.transaction(scope, lock=True) as (session, row):
        for sequence in range(1, 76):
            session.add(
                AgentEvent(
                    tenant_id=setup.tenant,
                    run_id=row.id,
                    sequence=sequence,
                    body={"type": "text_delta", "text": "not public"}
                    if sequence % 3
                    else {"type": "model_started", "turn": sequence},
                )
            )
    base = path(setup, scope) + "/process?page_size=7"
    data = setup.client.get(base, headers=setup.headers).json()
    observed, cursor = [row["sequence"] for row in data["steps"]], data["next_before"]
    assert len(observed) == 7
    while cursor:
        page = setup.client.get(base + f"&before={cursor}", headers=setup.headers)
        assert page.status_code == 200
        data = page.json()
        observed += [row["sequence"] for row in data["steps"]]
        cursor = data["next_before"]
    assert sorted(observed) == list(range(3, 76, 3)) and len(set(observed)) == 25
    assert setup.client.get(base + "&before=2", headers=setup.headers).status_code == 403
    assert (
        setup.client.get(
            path(setup, scope) + "/process?page_size=101", headers=setup.headers
        ).status_code
        == 422
    )


def test_current_owner_source_and_category_access_are_rechecked_on_every_process_page(setup):
    artifact = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Artifact(
                id=artifact,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=setup.product,
                owner_id=setup.human,
                title="Actual bound source",
                source_label="synthetic",
                content="PRIVATE ORIGINAL BODY",
                content_hash=digest("PRIVATE ORIGINAL BODY"),
                visibility="private",
            )
        )
    store, scope = run(
        setup,
        product_id=setup.product,
        private_context=True,
        data_categories=("customer_original",),
        read_sources=(
            {
                "artifact_id": str(artifact),
                "expected_revision": 1,
                "product_id": str(setup.product),
            },
        ),
    )
    store.emit(scope, {"type": "model_started", "turn": 1})
    base = path(setup, scope) + "/process"
    response = setup.client.get(base, headers=setup.headers)
    assert (
        response.status_code == 200
        and response.json()["sources"][0]["title"] == "Actual bound source"
    )
    assert "PRIVATE ORIGINAL BODY" not in response.text
    assert (
        setup.client.get(
            base, headers={"Authorization": "Bearer " + setup.tokens[setup.peer]}
        ).status_code
        == 403
    )
    with Session(setup.admin) as session, session.begin():
        session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        ).expires_at = now() - timedelta(seconds=1)
    assert setup.client.get(base, headers=setup.headers).status_code == 403


def test_state_and_record_rollback_as_one_transaction(setup):
    store, scope = run(setup)
    with pytest.raises(RuntimeError):
        with store.transaction(scope, lock=True) as (session, row):
            row.state = "failed"
            record_state(session, row)
            session.flush()
            raise RuntimeError("Synthetic after record failure")
    with Session(setup.admin) as session:
        assert session.get(AgentRun, scope.run_id).state == "queued"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentEvent)
                .where(AgentEvent.run_id == scope.run_id)
            )
            == 0
        )


def test_personal_run_process_is_readable_only_in_its_personal_entry(setup):
    from dataclasses import replace

    from pdos_next.agent_kernel.persistence import create_run

    ctx = replace(setup.ctx, category_id=None)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human
    ) as session:
        identity = create_run(
            session,
            ctx,
            goal="Synthetic personal work",
            writer_id=setup.agent,
            intent_key=str(uuid4()),
        ).id
    path = f"/v1/personal/agent-runs/{identity}/process"
    response = setup.client.get(path, headers=setup.headers)
    assert response.status_code == 200 and response.json()["source_count"] == 0
    assert (
        setup.client.get(
            path.replace("/personal/", f"/categories/{setup.category}/"), headers=setup.headers
        ).status_code
        == 403
    )


def test_all_sources_and_receipts_have_independent_complete_metadata_pages(setup):
    identities = [uuid4() for _ in range(28)]
    with Session(setup.admin) as session, session.begin():
        session.add_all(
            [
                Artifact(
                    id=identity,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=setup.product,
                    owner_id=setup.human,
                    title="Synthetic source " + str(index),
                    source_label="synthetic",
                    content="not projected",
                    content_hash=digest("not projected"),
                    visibility="category",
                )
                for index, identity in enumerate(identities)
            ]
        )
    _, scope = run(
        setup,
        product_id=setup.product,
        read_sources=tuple(
            {"artifact_id": str(identity), "expected_revision": 1, "product_id": str(setup.product)}
            for identity in identities
        ),
    )
    receipt_ids = {receipt(setup, scope) for _ in range(28)}
    base = path(setup, scope) + "/process?page_size=7"
    for key, expected in [("sources", set(identities)), ("receipts", receipt_ids)]:
        found, cursor = [], None
        while True:
            query = base + (
                f"&{'source_cursor' if key == 'sources' else 'receipt_cursor'}={cursor}"
                if cursor
                else ""
            )
            response = setup.client.get(query, headers=setup.headers)
            assert response.status_code == 200, response.text
            value = response.json()
            found += [row["id"] for row in value[key]]
            cursor = value["next_source_cursor" if key == "sources" else "next_receipt_cursor"]
            if cursor is None:
                break
        assert set(found) == {str(identity) for identity in expected} and len(found) == 28
    assert (
        setup.client.get(base + f"&source_cursor={uuid4()}", headers=setup.headers).status_code
        == 403
    )
    assert (
        setup.client.get(base + f"&receipt_cursor={uuid4()}", headers=setup.headers).status_code
        == 403
    )
