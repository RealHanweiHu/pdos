"""Actual admission/preload/replay; no model, skill enablement or qualification granted."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, TenantSkillEnablement
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.requested_skills import preload
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.errors import DomainError
from tests.agent_kernel.test_api import client


def request_skill():
    skill = SkillCatalog().configuration("gap_check")
    return {"key": skill.key, "version": skill.version, "digest": skill.digest}


def enable(setup):
    with Session(setup.admin) as session, session.begin():
        session.add(TenantSkillEnablement(
            tenant_id=setup.tenant, skill_key="gap_check", enabled=True,
        ))


def scope_for(setup, identity):
    store = KernelStore(setup.engine)
    return store, store.scope(tenant_id=setup.tenant, requester_id=setup.human,
        writer_id=setup.agent, category_id=setup.category, run_id=UUID(identity))


def test_personal_catalog_reads_only_current_tenant_without_granting_or_creating_work(setup):
    enable(setup)
    with Session(setup.admin) as session:
        before = session.scalar(select(func.count()).select_from(AgentRun))
    path = "/v1/personal/agent-skills"
    response = setup.client.get(path, headers=setup.headers)
    assert response.status_code == 200, response.text
    reading = response.json()
    choice = next(item for item in reading["items"] if item["skill_key"] == "gap_check")
    assert choice["enabled"] and not reading["can_edit"]
    assert {key: choice[key] for key in ("skill_version", "skill_digest")} == {
        "skill_version": request_skill()["version"], "skill_digest": request_skill()["digest"],
    }
    assert "operations" not in choice and "receipt_id" not in choice
    other = setup.client.get(path, headers={
        "Authorization": "Bearer " + setup.tokens[setup.other_human],
    })
    assert other.status_code == 200 and not any(item["enabled"] for item in other.json()["items"])
    assert setup.client.get(path).status_code == 401
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(AgentRun)) == before
        row = session.scalar(select(TenantSkillEnablement).where(
            TenantSkillEnablement.tenant_id == setup.tenant))
        assert row.enabled and row.reviewed_at is None


def test_selected_version_is_persisted_preloaded_and_replayed_without_rebinding(setup):
    enable(setup)
    api, calls = client(setup)
    path = f"/v1/categories/{setup.category}/agent-runs"
    body = {"goal": "合成技能选择验证", "idempotency_key": str(uuid4()),
            "requested_skills": [request_skill()]}
    first = api.post(path, json=body)
    assert first.status_code == 202, first.text
    identity = first.json()["run_id"]
    store, scope = scope_for(setup, identity)
    assert preload(store, scope, ("proposal_drafting",)) == ("gap_check",)
    assert KernelActivities(setup.engine).preload(
        scope, SimpleNamespace(preload=lambda _: ("gap_check",))
    ) == ("gap_check",)
    with Session(setup.admin) as session, session.begin():
        accepted = session.scalar(select(AgentEvent).where(
            AgentEvent.run_id == UUID(identity), AgentEvent.sequence == 1))
        assert accepted.body["requested_skills"] == body["requested_skills"]
        row = session.scalar(select(TenantSkillEnablement).where(
            TenantSkillEnablement.tenant_id == setup.tenant))
        row.enabled = False
    # Re-reading/replaying does not borrow current composer selections or grant enablement.
    assert api.post(path, json=body).json() == first.json()
    with pytest.raises(DomainError, match="技能当前未启用"):
        preload(store, scope)
    assert api.post(path, json={**body, "requested_skills": []}).status_code == 409
    assert len(calls) == 2
    api.close()


@pytest.mark.parametrize("case", ["disabled", "changed", "duplicate", "unknown", "too_many"])
def test_invalid_choice_creates_no_run_or_workflow(setup, case):
    if case != "disabled":
        enable(setup)
    item = request_skill()
    if case == "changed":
        item["digest"] = "0" * 64
    if case == "unknown":
        item["key"] = "unregistered"
    selected = [item] * (2 if case == "duplicate" else 9 if case == "too_many" else 1)
    api, calls = client(setup)
    with Session(setup.admin) as session:
        before = session.scalar(select(func.count()).select_from(AgentRun))
    response = api.post(f"/v1/categories/{setup.category}/agent-runs", json={
        "goal": "合成拒绝技能选择", "idempotency_key": str(uuid4()), "requested_skills": selected,
    })
    expected = 422 if case in {"duplicate", "too_many"} else 409 if case == "changed" else 403
    assert response.status_code == expected, response.text
    assert calls == []
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(AgentRun)) == before
    api.close()


def test_legacy_empty_request_and_child_or_automation_do_not_acquire_selected_methods(setup):
    api, _ = client(setup)
    body = {"goal": "合成原空技能请求", "idempotency_key": str(uuid4())}
    path = f"/v1/categories/{setup.category}/agent-runs"
    response = api.post(path, json=body)
    assert response.status_code == 202
    assert api.post(path, json={**body, "requested_skills": []}).json() == response.json()
    store, scope = scope_for(setup, response.json()["run_id"])
    assert preload(store, scope, ("proposal_drafting",)) == ("proposal_drafting",)
    assert preload(store, scope.child("research"), ()) == ()
    assert preload(store, replace(scope, trigger="automation_manual"), ("gap_check",)) == (
        "gap_check",
    )
    api.close()


@pytest.mark.parametrize("case, expected", [
    ("one", ("proposal_drafting",)),
    ("three", ("public_research", "gap_check")),
    ("explicit", ("gap_check", "proposal_drafting")),
])
def test_continuation_inherits_only_recent_enabled_main_skills(setup, case, expected):
    from tests.agent_kernel.test_run_continuation import finish, start

    loaded = ["proposal_drafting"]
    if case == "three":
        loaded += ["gap_check", "public_research"]
    if case == "explicit":
        loaded += ["gap_check"]
    parent, _ = start(setup)
    with Session(setup.admin) as session, session.begin():
        sequence = session.scalar(select(func.max(AgentEvent.sequence)).where(
            AgentEvent.run_id == parent)) or 0
        for index, key in enumerate(loaded, start=1):
            skill = SkillCatalog().configuration(key)
            session.add(TenantSkillEnablement(
                tenant_id=setup.tenant, skill_key=key, enabled=True,
            ))
            session.add(AgentEvent(tenant_id=setup.tenant, run_id=parent,
                sequence=sequence + index, body={"type": "skill_loaded", "key": key,
                    "version": skill.version, "digest": skill.digest, "isolation": "main"}))
        session.add(AgentEvent(tenant_id=setup.tenant, run_id=parent,
            sequence=sequence + len(loaded) + 1, body={"type": "skill_loaded",
                "key": "option_comparison", "isolation": "research"}))
    finish(setup, parent)
    selected = [request_skill()] if case == "explicit" else []
    child, _ = start(setup, continue_from_run_id=str(parent), requested_skills=selected)
    store, scope = scope_for(setup, str(child))
    assert preload(store, scope) == expected
