from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.api import StartInput
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import TenantAdministrator, ValidationBudget
from pdos_next.agent_kernel.persistence import cancel_run
from pdos_next.models import Audit, Category, Confirmation, Grant, Outbox, Receipt, now
from tests.agent_kernel.test_cost_budget import rate
from tests.agent_kernel.test_skill_management import promote
from tests.agent_kernel.test_transactions import human_session, run

LIMITS = {
    "limit_micro_usd": 2_000_000,
    "input_token_limit": 100000,
    "output_token_limit": 10000,
    "call_limit": 20,
}


def path(setup, suffix="agent-budgets"):
    return f"/v1/categories/{setup.category}/{suffix}"


def reading(setup, query=""):
    result = setup.client.get(path(setup) + query, headers=setup.headers)
    assert result.status_code == 200, result.text
    return result.json()


def command(setup, action="allocate", current=None):
    current = current or reading(setup)
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "category_id": str(setup.category),
        "product_id": None,
        "operation": "ai.budget.configure",
        "expected_revision": current["category_revision"],
        "source_read_set": [],
        "payload": {
            "action": action,
            "expected_active_digest": current["active_digest"],
            "limits": LIMITS if action == "allocate" else None,
        },
    }


def post(setup, data, suffix="commands"):
    return setup.client.post(path(setup, suffix), headers=setup.headers, json=data)


def preview(setup, data):
    result = post(setup, data, "commands/preview")
    assert result.status_code == 200, result.text
    return result.json()["command"]


def allocate(setup):
    original = preview(setup, command(setup))
    result = post(setup, original)
    assert result.status_code == 200, result.text
    return original, result.json()


def test_current_member_reads_only_own_budget_and_admin_confirms_one_t1_atom(setup):
    current = reading(setup)
    assert not current["can_edit"] and not current["items"]
    assert post(setup, command(setup), "commands/preview").status_code == 403
    promote(setup)
    assert post(setup, command(setup)).json()["code"] == "CONFIRMATION_REQUIRED"
    original = preview(setup, command(setup))
    assert not reading(setup)["items"]
    saved = post(setup, original).json()
    with Session(setup.admin) as session:
        receipt = session.get(Receipt, UUID(saved["id"]))
        proof = session.get(Confirmation, receipt.confirmation_id)
        row = session.get(ValidationBudget, UUID(saved["subject_id"]))
        assert proof.consumed and row.revision == 1 and row.receipt_id == receipt.id
        assert row.active and row.calls == 0 and row.spent_micro_usd == row.held_micro_usd == 0
        for model in (Audit, Outbox):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.receipt_id == receipt.id)
                )
                == 1
            )
    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert setup.client.get(path(setup), headers=peer).json()["items"] == []
    assert reading(setup)["selected_budget_id"] == saved["subject_id"]


def test_default_run_binding_selects_new_wallet_without_any_model_or_kms_call(setup):
    promote(setup)
    _, saved = allocate(setup)
    with human_session(setup) as session:
        value = Bootstrap(setup.engine).binding_for(
            session,
            setup.ctx,
            StartInput(goal="Synthetic budget binding only", idempotency_key=str(uuid4())),
        )
        assert str(value.validation_budget_id) == saved["subject_id"]
        assert value.token_limit == LIMITS["input_token_limit"] + LIMITS["output_token_limit"]


def test_replace_during_reserved_call_preserves_old_usage_and_settles_original_wallet(setup):
    promote(setup)
    _, first = allocate(setup)
    replacement = preview(setup, command(setup))
    budget_id = UUID(first["subject_id"])
    store, scope = run(setup, token_limit=110000, validation_budget_id=budget_id)
    card = rate()
    call, _ = store.claim(
        scope,
        "inflight-budget-change",
        "model",
        {},
        reservation=200,
        cost_lease=(card.reserve(100, 100), 100, 100, card.snapshot()),
    )
    result = post(setup, replacement)
    assert result.status_code == 200, result.text
    second = result.json()
    assert second["subject_id"] != first["subject_id"]
    from pdos_next.errors import DomainError

    with pytest.raises(DomainError) as inactive:
        store.claim(
            scope,
            "after-budget-stop",
            "model",
            {},
            reservation=200,
            cost_lease=(card.reserve(100, 100), 100, 100, card.snapshot()),
        )
    assert inactive.value.detail["reason_key"] == "budget_inactive"
    with Session(setup.admin) as session:
        old = session.get(ValidationBudget, budget_id)
        assert not old.active and old.held_micro_usd == card.reserve(100, 100)
        assert old.limit_micro_usd == LIMITS["limit_micro_usd"] and old.calls == 1
    with human_session(setup) as session:
        cancel_run(session, setup.ctx, scope.run_id)
    assert not store.release_call(scope, call, error="CANCELLED_RUN", unknown=True, usage=12)
    with Session(setup.admin) as session:
        old = session.get(ValidationBudget, budget_id)
        new = session.get(ValidationBudget, UUID(second["subject_id"]))
        assert old.held_micro_usd == 0 and old.spent_micro_usd == card.reserve(100, 100)
        assert old.used_input_tokens == old.used_output_tokens == 100
        assert new.spent_micro_usd == new.held_micro_usd == new.calls == 0


def test_stop_deactivates_every_own_active_wallet_and_no_new_run_silently_falls_back(setup):
    promote(setup)
    _, first = allocate(setup)
    with Session(setup.admin) as session, session.begin():
        session.add(
            ValidationBudget(
                tenant_id=setup.tenant, requester_id=setup.human, active=True, **LIMITS
            )
        )
    current = reading(setup)
    assert len(current["active_budgets"]) == 2
    original = preview(setup, command(setup, "stop", current))
    saved = post(setup, original)
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["result"]["retired_budgets"]) == 2
    current = reading(setup)
    assert current["selected_budget_id"] is None and not current["active_budgets"]
    assert len(current["items"]) == 2
    with human_session(setup) as session:
        bound = Bootstrap(setup.engine).binding_for(
            session,
            setup.ctx,
            StartInput(goal="Synthetic stopped budget", idempotency_key=str(uuid4())),
        )
        assert bound.validation_budget_id is None


def test_stale_confirmation_and_changed_payload_cannot_replace_a_new_wallet(setup):
    promote(setup)
    first = preview(setup, command(setup))
    stale = preview(setup, command(setup))
    changed = command(setup)
    changed["payload"]["limits"] = {**LIMITS, "call_limit": 19}
    different = preview(setup, changed)
    saved = post(setup, first).json()
    assert post(setup, stale).json() == saved
    assert post(setup, different).json()["code"] == "VERSION_CONFLICT"
    forged = {**first, "payload": {**first["payload"], "requester_id": str(setup.peer)}}
    assert post(setup, forged).status_code == 422
    assert len(reading(setup)["items"]) == 1


def test_allocate_same_limits_after_full_stop_creates_fresh_budget_not_old_receipt(setup):
    promote(setup)
    _, first = allocate(setup)
    stopped = preview(setup, command(setup, "stop"))
    assert post(setup, stopped).status_code == 200
    assert reading(setup)["selected_budget_id"] is None
    _, second = allocate(setup)
    assert second["id"] != first["id"]
    assert second["subject_id"] != first["subject_id"]
    assert reading(setup)["selected_budget_id"] == second["subject_id"]


def test_old_receipt_recovers_after_confirmation_expiry_and_admin_revocation(setup):
    promote(setup)
    original = preview(setup, command(setup))
    assert post(setup, original, "agent-budgets/recover").json() == {"receipt": None}
    saved = post(setup, original).json()
    with Session(setup.admin) as session, session.begin():
        row = session.get(Receipt, UUID(saved["id"]))
        session.get(Confirmation, row.confirmation_id).expires_at = now() - timedelta(days=1)
        session.scalar(
            select(TenantAdministrator).where(TenantAdministrator.tenant_id == setup.tenant)
        ).active = False
    assert post(setup, original).json() == saved
    assert post(setup, original, "agent-budgets/recover").json() == {"receipt": saved}
    changed = {
        **original,
        "payload": {**original["payload"], "limits": {**LIMITS, "call_limit": 1}},
    }
    assert (
        post(setup, changed, "agent-budgets/recover").json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    )
    assert post(setup, command(setup), "commands/preview").status_code == 403


def test_budget_history_pages_and_zero_cost_limit_remain_explicit(setup):
    promote(setup)
    for _ in range(3):
        allocate(setup)
    first = reading(setup, "?page_size=2")
    second = reading(setup, "?page_size=2&cursor=" + first["next_cursor"])
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert not set(row["id"] for row in first["items"]) & set(row["id"] for row in second["items"])
    assert second["next_cursor"] is None
    data = command(setup)
    data["payload"]["limits"] = {**LIMITS, "limit_micro_usd": 0}
    assert post(setup, preview(setup, data)).status_code == 200
    assert reading(setup)["active_budgets"][0]["limit_micro_usd"] == 0


def test_two_categories_cannot_concurrently_create_different_current_wallets(setup):
    from pdos_next.contracts import Command
    from pdos_next.database import category_transaction
    from pdos_next.errors import DomainError
    from pdos_next.service import execute, preview_command

    promote(setup)
    other = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Category(
                id=other,
                tenant_id=setup.tenant,
                name="预算第二品类",
                purpose="合成共享钱包检查",
                owner_id=setup.human,
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=other,
                principal_id=setup.human,
                can_write=True,
                expires_at=now() + timedelta(hours=1),
            )
        )
    first = preview(setup, command(setup))
    ctx = replace(setup.ctx, category_id=other)
    data = command(setup)
    data["category_id"] = str(other)
    second = category_transaction(
        setup.engine,
        ctx,
        lambda session: preview_command(session, ctx, Command.model_validate(data)),
    )["command"]
    barrier = Barrier(2)

    def write(value):
        current, body = value
        barrier.wait(timeout=10)
        try:
            return category_transaction(
                setup.engine,
                current,
                lambda session: execute(session, current, Command.model_validate(body)),
            )
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [(setup.ctx, first), (ctx, second)]))
    assert sum(isinstance(value, dict) for value in results) == 1
    assert "VERSION_CONFLICT" in results
    assert len(reading(setup)["active_budgets"]) == 1


def test_budget_controls_http_latency_and_sql_count(setup):
    import json
    from math import ceil
    from statistics import median
    from time import perf_counter

    from sqlalchemy import event

    promote(setup)
    telemetry = {"active": False, "sql": 0}
    durations, counts = [], []

    def count(*_args):
        if telemetry["active"]:
            telemetry["sql"] += 1

    engines = {setup.engine, setup.auth}
    for engine in engines:
        event.listen(engine, "before_cursor_execute", count)
    try:
        for step in range(20):
            original = preview(setup, command(setup, "allocate" if step % 2 == 0 else "stop"))
            telemetry.update(active=True, sql=0)
            start = perf_counter()
            result = post(setup, original)
            durations.append((perf_counter() - start) * 1000)
            telemetry["active"] = False
            counts.append(telemetry["sql"])
            assert result.status_code == 200, result.text
            assert result.json()["subject_revision"] == step + 1
    finally:
        for engine in engines:
            event.remove(engine, "before_cursor_execute", count)
    print(
        "BUDGET_TIMING="
        + json.dumps(
            {
                "operation": "ai.budget.configure",
                "samples": 20,
                "actual_http": True,
                "median_ms": round(median(durations), 2),
                "p95_ms": round(sorted(durations)[ceil(len(durations) * 0.95) - 1], 2),
                "max_ms": round(max(durations), 2),
                "sql_count_min": min(counts),
                "sql_count_max": max(counts),
                "counts_include_auth_and_domain": True,
                "scope": "one owner; alternating allocate/stop; not full S1 acceptance",
            }
        )
    )
