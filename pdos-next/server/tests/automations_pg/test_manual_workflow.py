"""Actual manual rule commands and Run admission; root alone runs this guarded PG chain."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentRun,
    AgentSession,
    AgentToolCall,
    TenantSkillEnablement,
    ValidationBudget,
)
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.database import tenant_session
from pdos_next.domain.automations import runtime
from pdos_next.domain.automations.models import (
    AutomationRuleCurrent,
    AutomationRuleVersion,
    AutomationTriggerOccurrence,
)
from pdos_next.domain.automations.schemas import ACTIVATE, DRAFT_SAVE, PAUSE
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey
from pdos_next.safety import verify_test_target
from pdos_next.service import digest
from tests.agent_kernel import test_budget_management as budgets
from tests.agent_kernel import test_skill_management as skills

MODELS = (
    AutomationRuleVersion,
    AutomationRuleCurrent,
    AutomationTriggerOccurrence,
    AgentRun,
    AgentSession,
    AgentEvent,
    AgentToolCall,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
    Confirmation,
    ValidationBudget,
    TenantSkillEnablement,
)
EVENTS = {
    DRAFT_SAVE: "ai.automation_draft_saved",
    ACTIVATE: "ai.automation_activated",
    PAUSE: "ai.automation_paused",
}


def snapshot(setup):
    with Session(setup.admin) as session:
        result = {}
        for model in MODELS:
            rows = session.scalars(select(model).where(model.tenant_id == setup.tenant)).all()
            result[model.__tablename__] = sorted(
                digest({column.name: getattr(row, column.name) for column in model.__table__.c})
                for row in rows
            )
        return result


def path(setup, rule_id=None):
    root = f"/v1/categories/{setup.category}/automation-rules"
    return root + (f"/{rule_id}" if rule_id else "")


def reading(setup, rule_id=None):
    response = setup.client.get(path(setup, rule_id), headers=setup.headers)
    assert response.status_code == 200, response.text
    return response.json()


def save(setup, operation, payload):
    command = {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "category_id": str(setup.category),
        "product_id": None,
        "operation": operation,
        "expected_revision": reading(setup)["category_revision"],
        "source_read_set": [],
        "payload": deepcopy(payload),
    }
    if operation != DRAFT_SAVE:
        command = skills.preview(setup, command)["command"]
        assert command["payload"]["confirmation_token"]
    response = skills.post(setup, command)
    assert response.status_code == 200, response.text
    return command, response.json()


def trigger(setup, rule_id, value, *, status=202, code=None, unchanged=False):
    before = snapshot(setup) if unchanged else None
    response = setup.client.post(
        path(setup, rule_id) + "/trigger", headers=setup.headers, json=value
    )
    assert response.status_code == status, response.text
    if code:
        assert response.json()["code"] == code
    if unchanged:
        assert snapshot(setup) == before
    return response.json()


def new_trigger(rule):
    return {
        "expected_rule_revision": rule["revision"],
        "version_id": rule["published"]["id"],
        "idempotency_key": str(uuid4()),
    }


def assert_common_group(session, setup, command, receipt):
    row = session.get(AutomationRuleVersion, UUID(receipt["subject_id"]))
    saved = session.get(Receipt, UUID(receipt["id"]))
    assert row.receipt_id == saved.id and saved.subject_id == row.id
    assert saved.subject_type == "automation_rule" and saved.subject_revision == row.revision
    assert row.actor_id == row.requester_id == row.owner_id == setup.human
    assert saved.actor_id == saved.requester_id == setup.human
    assert saved.run_id is None and saved.agent_run_id is None
    assert saved.category_id == setup.category and saved.product_id is None
    assert row.spec_sha256 == digest(row.spec)
    for model in (Audit, Outbox, RequestKey):
        assert (
            session.scalar(
                select(func.count()).select_from(model).where(model.receipt_id == saved.id)
            )
            == 1
        )
    event = session.scalar(select(Outbox).where(Outbox.receipt_id == saved.id))
    key = session.scalar(select(RequestKey).where(RequestKey.receipt_id == saved.id))
    assert event.type == EVENTS[row.operation] and event.correlation_id == row.command_id
    assert key.key == command["idempotency_key"] and key.digest == saved.request_digest
    if row.operation == DRAFT_SAVE:
        assert row.confirmation_id is None and saved.confirmation_id is None
    else:
        proof = session.get(Confirmation, saved.confirmation_id)
        assert proof.id == row.confirmation_id and proof.consumed
        assert proof.actor_id == setup.human and proof.operation == row.operation
        assert proof.subject_type == "category" and proof.subject_id == setup.category
        assert proof.snapshot == row.command["review"]
        assert proof.expires_at is not None and row.created_at < proof.expires_at
    return row


def test_actual_manual_rule_publish_pause_resume_and_exact_run_replay(setup):
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    verify_test_target(setup.dispatch)
    skills.promote(setup)
    enabled = skills.post(setup, skills.preview(setup, skills.command(setup))["command"])
    assert enabled.status_code == 200, enabled.text
    _, wallet = budgets.allocate(setup)
    skill = SkillCatalog().configuration("public_research")
    spec = {
        "name": "Synthetic bounded local inspection",
        "goal": "Read current category facts; preserve unknowns without network or business writes",
        "purpose": "Actual manual automation admission verification",
        "stop_condition": "Return the current read-only inspection result",
        "trigger_kind": "manual",
        "product_id": str(setup.product),
        "skill_keys": [{"key": skill.key, "version": skill.version, "digest": skill.digest}],
        "validation_budget_id": wallet["subject_id"],
        "token_limit": 1000,
        "budget": {
            "limit_micro_usd": 100_000,
            "input_token_limit": 1000,
            "output_token_limit": 1000,
            "call_limit": 2,
        },
        "cooldown_seconds": 0,
        "max_runs": 2,
        "allow_network": False,
        "mcp_tools": [],
        "cross_object_write": False,
    }
    original_spec = deepcopy(spec)
    commands = [save(setup, DRAFT_SAVE, {"expected_rule_revision": 0, "spec": spec})]
    rule_id = commands[0][1]["result"]["rule_id"]
    detail = reading(setup, rule_id)
    first_draft = detail["rule"]
    assert first_draft["state"] == "draft" and first_draft["revision"] == 1
    assert first_draft["published"] is None and first_draft["admitted_count"] == 0
    commands.append(
        save(
            setup,
            ACTIVATE,
            {
                "rule_id": rule_id,
                "expected_rule_revision": first_draft["revision"],
                "version_id": first_draft["draft"]["id"],
            },
        )
    )
    active = reading(setup, rule_id)["rule"]
    assert active["state"] == "active" and active["revision"] == 2
    assert active["draft"] is None and active["published"]["spec"] == spec
    first_request = new_trigger(active)
    first = trigger(setup, rule_id, first_request)
    assert trigger(setup, rule_id, first_request, unchanged=True) == first
    assert first["version_id"] == active["published"]["id"]
    active = reading(setup, rule_id)["rule"]
    assert active["admitted_count"] == 1 and active["last_admitted_at"] is not None

    spec["goal"] = (
        "Read a separately confirmed local view, preserving unknowns and original history"
    )
    commands.append(
        save(
            setup,
            DRAFT_SAVE,
            {
                "rule_id": rule_id,
                "expected_rule_revision": active["revision"],
                "spec": spec,
            },
        )
    )
    editing = reading(setup, rule_id)["rule"]
    assert editing["revision"] == 3 and editing["state"] == "active"
    assert editing["published"] == active["published"] and editing["draft"]["spec"] == spec
    assert editing["admitted_count"] == 1
    commands.append(
        save(
            setup,
            PAUSE,
            {
                "rule_id": rule_id,
                "expected_rule_revision": editing["revision"],
                "version_id": editing["published"]["id"],
            },
        )
    )
    paused = reading(setup, rule_id)["rule"]
    assert paused["state"] == "paused" and paused["revision"] == 4
    assert paused["published"] == active["published"] and paused["draft"] == editing["draft"]
    assert trigger(setup, rule_id, first_request, unchanged=True) == first
    trigger(
        setup, rule_id, new_trigger(paused), status=409, code="VALIDATION_FAILED", unchanged=True
    )
    commands.append(
        save(
            setup,
            ACTIVATE,
            {
                "rule_id": rule_id,
                "expected_rule_revision": paused["revision"],
                "version_id": paused["draft"]["id"],
            },
        )
    )
    resumed = reading(setup, rule_id)["rule"]
    assert resumed["state"] == "active" and resumed["revision"] == 5
    assert resumed["admitted_count"] == 1 and resumed["draft"] is None
    assert resumed["published"]["spec"] == spec
    second_request = new_trigger(resumed)
    second = trigger(setup, rule_id, second_request)
    assert second["run_id"] != first["run_id"]
    assert trigger(setup, rule_id, second_request, unchanged=True) == second
    trigger(setup, rule_id, new_trigger(resumed), status=429, code="RATE_LIMITED", unchanged=True)
    final = reading(setup, rule_id)
    assert final["rule"]["admitted_count"] == 2
    assert [row["revision"] for row in final["history"]] == [5, 4, 3, 2, 1]
    assert [row["action"] for row in final["history"]] == [
        "activate",
        "pause",
        "draft",
        "activate",
        "draft",
    ]
    assert {row["run_id"] for row in final["runs"]} == {first["run_id"], second["run_id"]}
    assert all(row["state"] == "queued" for row in final["runs"])
    before = snapshot(setup)
    store = KernelStore(setup.engine)
    for accepted, expected in ((first, original_spec), (second, spec)):
        scope = store.scope(
            tenant_id=setup.tenant,
            requester_id=setup.human,
            writer_id=setup.agent,
            category_id=setup.category,
            run_id=UUID(accepted["run_id"]),
        )
        assert scope.trigger == runtime.TRIGGER
        with store.transaction(scope) as (session, run):
            occurrence, actual = runtime.binding(session, run)
            assert (
                occurrence.run_id == run.id
                and str(occurrence.published_version_id) == accepted["version_id"]
            )
            assert actual.model_dump(mode="json") == expected and run.goal == expected["goal"]
            assert run.read_sources == [] and run.writer_id == setup.agent
        assert runtime.preload(store, scope) == (skill.key,)
        assert runtime.permitted_skill(store, scope, skill)
        runtime.guard_tool(store, scope, "category.read")
        for tool in ("research.search", "research.read", "research.fanout", "mcp.read"):
            with pytest.raises(DomainError) as denied:
                runtime.guard_tool(store, scope, tool)
            assert denied.value.code == "FORBIDDEN_SCOPE"
        with pytest.raises(DomainError):
            runtime.guard_tool(store, scope, writing=True)
    assert snapshot(setup) == before

    with Session(setup.admin) as session:
        versions = [assert_common_group(session, setup, *command) for command in commands]
        assert [row.revision for row in versions] == [1, 2, 3, 4, 5]
        assert all(
            row["receipt_id"] in {str(v.receipt_id) for v in versions} for row in final["history"]
        )
        assert (
            session.scalar(
                select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == setup.tenant)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentToolCall)
                .where(AgentToolCall.tenant_id == setup.tenant)
            )
            == 0
        )
        actual_wallet = session.get(ValidationBudget, UUID(wallet["subject_id"]))
        assert (
            actual_wallet.calls
            == actual_wallet.spent_micro_usd
            == actual_wallet.held_micro_usd
            == 0
        )
        enabled_skill = session.scalar(
            select(TenantSkillEnablement).where(TenantSkillEnablement.tenant_id == setup.tenant)
        )
        assert enabled_skill.enabled and not enabled_skill.pilot
    # Common command replay also returns its exact original receipt without new atoms.
    before = snapshot(setup)
    for command, receipt in commands:
        response = skills.post(setup, command)
        assert response.status_code == 200 and response.json() == receipt, response.text
    assert snapshot(setup) == before
    peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    peer = setup.client.get(path(setup), headers=peer_headers)
    assert peer.status_code == 200 and peer.json()["rules"] == []
    assert setup.client.get(path(setup, rule_id), headers=peer_headers).status_code == 404
    foreign_headers = {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    assert setup.client.get(path(setup), headers=foreign_headers).status_code == 403
    for principal, tenant in ((setup.peer, setup.tenant), (setup.other_human, setup.other_tenant)):
        with tenant_session(
            setup.engine,
            tenant,
            actor_id=principal,
            requester_id=principal,
            category_id=setup.category,
        ) as session:
            assert (
                session.scalar(
                    select(AutomationRuleCurrent).where(
                        AutomationRuleCurrent.rule_id == UUID(rule_id)
                    )
                )
                is None
            )
            assert session.get(AgentRun, UUID(first["run_id"])) is None
    with setup.engine.connect() as connection:
        for model in (
            AutomationRuleVersion,
            AutomationRuleCurrent,
            AutomationTriggerOccurrence,
            AgentRun,
        ):
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert not connection.scalar(
                    text("SELECT has_table_privilege('pdos_agent',:table,:privilege)"),
                    {"table": model.__tablename__, "privilege": privilege},
                )
            assert not connection.scalar(
                text("SELECT has_any_column_privilege('pdos_agent',:table,'UPDATE')"),
                {"table": model.__tablename__},
            )
    assert snapshot(setup) == before
