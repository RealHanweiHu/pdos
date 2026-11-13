"""Status-update cadence (P34-6, P65, D75): the owner's T1 schedule bound to one project.

Real confirmation, grant and admission owners stay in the path. The Temporal wait is
outside this slice: the actual tick Activity is called once. No model is called; the
admitted Run is checked as queued, bound to the project, never as a published update.
"""

# ruff: noqa: F811 - imported fixtures intentionally register their dependency tree

from copy import deepcopy
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import AgentRun, AgentSession
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.kernel.skills import SkillCatalog
from pdos_next.core.models import now
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.schemas import ACTIVATE, DRAFT_SAVE
from pdos_next.domain.automations.service_models import AutomationServiceAttempt
from pdos_next.domain.automations.templates import STATUS_UPDATE, TEMPLATES
from pdos_next.domain.projects.work.constants import STATUS
from tests.agent.kernel import test_skill_management as skills
from tests.automations.pg.test_manual_workflow import path, reading, save
from tests.automations.pg.test_service_automation_pg import _activate, _control, _ready
from tests.projects.work_pg import test_workflow as flow
from tests.projects.work_pg.test_workflow import original_security_work  # noqa: F401
from tests.projects.work_pg.test_workflow import work as work_case  # noqa: F401

LABEL = "按周一至周五估算，未扣节假日与停线"
DEFAULTS = next(t for t in TEMPLATES if t["key"] == STATUS_UPDATE)["defaults"]


@pytest.fixture
def cadence_work(request):
    return request.getfixturevalue("work_case")


def _enable(setup, key):
    command = skills.command(setup)
    actual = SkillCatalog().configuration(key)
    command["payload"].update(
        skill_key=actual.key, skill_version=actual.version, skill_digest=actual.digest
    )
    response = skills.post(setup, skills.preview(setup, command)["command"])
    assert response.status_code == 200, response.text
    return {"key": actual.key, "version": actual.version, "digest": actual.digest}


def _spec(work, wallet, skill, **changes):
    value = {
        "name": DEFAULTS["name"],
        "goal": DEFAULTS["goal"],
        "purpose": DEFAULTS["purpose"],
        "stop_condition": DEFAULTS["stop_condition"],
        "trigger_kind": "schedule",
        "trigger_config": {
            "first_at": (now() - timedelta(minutes=5)).isoformat(),
            "original_timezone": "UTC",
            "interval_seconds": DEFAULTS["interval_seconds"],
            "expires_at": None,
            "project_id": str(work.project_id),
        },
        "conditions": {"task_id": None, "only_states": [], "stop_states": ["completed"]},
        "max_cascade_depth": 3,
        "external_sources_enabled": False,
        "product_id": str(work.setup.product),
        "skill_keys": [skill],
        "validation_budget_id": wallet["subject_id"],
        "token_limit": 1000,
        "budget": {
            "limit_micro_usd": 100_000,
            "input_token_limit": 1000,
            "output_token_limit": 1000,
            "call_limit": 3,
        },
        "cooldown_seconds": 0,
        "max_runs": 3,
        "allow_network": False,
        "mcp_tools": [],
        "cross_object_write": False,
        "template": STATUS_UPDATE,
    }
    value.update(changes)
    return value


def _cadence(work, actor=None):
    response = work.setup.client.get(
        flow.root(work) + "/project-work/status-cadence",
        params={"project_id": str(work.project_id)},
        headers=flow.headers(work, actor),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _draft(work, spec, actor):
    setup = work.setup
    return setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers=flow.headers(work, actor),
        json={
            "command_id": str(uuid4()),
            "idempotency_key": str(uuid4()),
            "category_id": str(setup.category),
            "product_id": None,
            "operation": DRAFT_SAVE,
            "expected_revision": reading(setup)["category_revision"],
            "source_read_set": [],
            "payload": {"expected_rule_revision": 0, "spec": deepcopy(spec)},
        },
    )


def test_owner_cadence_binds_one_project_drafts_by_t1_and_shows_missing_state(cadence_work):
    work = cadence_work
    setup = work.setup
    wallet = _ready(setup)
    skill = _enable(setup, "work_management")
    assert _cadence(work)["cadence"] is None

    # Only the project owner sets the cadence (P57-2, P65); a member is refused.
    spec = _spec(work, wallet, skill)
    refused = _draft(work, spec, setup.peer)
    assert refused.status_code == 403, refused.text
    # A project-bound schedule must be the cadence template.
    plain = _draft(work, _spec(work, wallet, skill, template=None), setup.human)
    assert plain.status_code == 422, plain.text

    rule_id, ref = _activate(setup, spec)
    owner_view = _cadence(work)
    cadence = owner_view["cadence"]
    assert cadence["rule_id"] == rule_id and cadence["owner_id"] == str(setup.human)
    assert cadence["status"] == "awaiting_publication" and not cadence["missing"]
    assert cadence["interval_seconds"] == 7 * 86400 and cadence["basis_label"] == LABEL
    assert cadence["grace_workdays"] == 1 and cadence["current_deadline_at"]
    # Members see the timing and “状态更新缺失”; the rule itself stays the owner's.
    member_view = _cadence(work, actor=setup.peer)
    assert {k: v for k, v in member_view["cadence"].items()} == {k: v for k, v in cadence.items()}
    hidden = setup.client.get(path(setup, rule_id), headers=flow.headers(work, setup.peer))
    assert hidden.status_code == 404, hidden.text

    # One active cadence per project.
    _, second_receipt = save(setup, DRAFT_SAVE, {"expected_rule_revision": 0, "spec": spec})
    second = reading(setup, second_receipt["result"]["rule_id"])["rule"]
    conflict = skills.post(setup, _control(setup, second, ACTIVATE))
    assert conflict.status_code == 409, conflict.text

    # The actual tick admits one queued Run bound to this project; nothing is published.
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    with Session(setup.admin) as session:
        attempt = session.scalar(
            select(AutomationServiceAttempt).where(
                AutomationServiceAttempt.service_grant_id == UUID(ref["grant_id"])
            )
        )
        assert attempt.state == "admitted" and attempt.trigger_kind == "schedule"
        run = session.get(AgentRun, attempt.run_id)
        assert run.project_id == work.project_id and run.state == "queued"
        assert run.goal == DEFAULTS["goal"] and run.trigger == service_runtime.TRIGGER
        assert run.writer_id == setup.agent and run.requester_id == setup.human
        assert session.get(AgentSession, run.session_id).project_id == work.project_id
    store = KernelStore(setup.engine)
    bound = store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=run.id,
    )
    with store.transaction(bound) as (session, current):
        actual, fixed = service_runtime.run_binding(session, current)
        assert actual.run_id == run.id and fixed.template == STATUS_UPDATE
    assert _cadence(work)["cadence"]["status"] == "awaiting_publication"

    # The owner publishes under their own name (P18); the cycle is then on track.
    flow.execute(
        work,
        STATUS,
        flow.payload(
            work,
            fact_summary="Synthetic facts as of this cycle",
            next_steps="Synthetic next steps",
            task_refs=[],
        ),
    )
    published = _cadence(work)["cadence"]
    assert published["status"] == "on_track" and published["latest_update_at"]
    assert datetime.fromisoformat(published["latest_update_at"]) <= now()
