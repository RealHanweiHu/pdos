"""Root-owned PostgreSQL admission of fixed inherited skills; no model/network calls."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentEvent, AgentRun, TenantSkillEnablement
from pdos_next.agent_kernel.requested_skills import preload
from pdos_next.errors import DomainError
from tests.agent_kernel.test_api import client
from tests.agent_kernel.test_requested_skills_pg import request_skill, scope_for
from tests.agent_kernel.test_run_continuation import finish


def parent_run(setup, *, changes=None, disabled=False):
    from pdos_next.agent_kernel.skills import SkillCatalog

    api, calls = client(setup)
    path = f"/v1/categories/{setup.category}/agent-runs"
    response = api.post(path, json={"goal": "合成延续技能父轮", "idempotency_key": str(uuid4())})
    assert response.status_code == 202, response.text
    parent = UUID(response.json()["run_id"])
    bindings = []
    with Session(setup.admin) as session, session.begin():
        sequence = session.scalar(select(func.max(AgentEvent.sequence)).where(
            AgentEvent.run_id == parent))
        for index, key in enumerate(("proposal_drafting", "gap_check", "public_research"), 1):
            skill = SkillCatalog().configuration(key)
            binding = {"key": key, "version": skill.version, "digest": skill.digest}
            if key == "public_research":
                binding.update(changes or {})
            bindings.append(binding)
            session.add(TenantSkillEnablement(
                tenant_id=setup.tenant, skill_key=key,
                enabled=not (disabled and key == "public_research"),
            ))
            session.add(AgentEvent(
                tenant_id=setup.tenant, run_id=parent, sequence=sequence + index,
                body={"type": "skill_loaded", "isolation": "main", **binding},
            ))
        session.add(AgentEvent(
            tenant_id=setup.tenant, run_id=parent, sequence=sequence + 4,
            body={"type": "skill_loaded", "isolation": "research", **request_skill()},
        ))
    finish(setup, parent)
    return api, calls, path, parent, list(reversed(bindings[1:]))


def test_scoped_read_exposes_only_actual_latest_two_versions_and_no_execution(setup):
    api, calls, path, parent, expected = parent_run(
        setup, changes={"version": "historical-original-version"}, disabled=True,
    )
    reading = api.get(f"{path}/{parent}/continuation")
    assert reading.status_code == 200, reading.text
    assert reading.json()["continued_skills"] == expected
    assert reading.json()["can_continue"] and len(calls) == 1
    foreign = setup.client.get(f"{path}/{parent}/continuation", headers={
        "Authorization": "Bearer " + setup.tokens[setup.other_human],
    })
    assert foreign.status_code == 403
    assert "historical-original-version" not in foreign.text
    api.close()


def test_removed_recent_skill_is_recorded_replayed_and_never_refilled_from_third(setup):
    api, calls, path, parent, _ = parent_run(setup)
    body = {"goal": "合成移除上轮公开研究", "idempotency_key": str(uuid4()),
            "continue_from_run_id": str(parent), "excluded_continued_skills": ["public_research"]}
    response = api.post(path, json=body)
    assert response.status_code == 202, response.text
    child = UUID(response.json()["run_id"])
    store, scope = scope_for(setup, str(child))
    assert preload(store, scope) == ("gap_check",)
    with Session(setup.admin) as session:
        accepted = session.scalar(select(AgentEvent).where(
            AgentEvent.run_id == child, AgentEvent.sequence == 1))
        assert accepted.body["excluded_continued_skills"] == ["public_research"]
        assert not accepted.body.get("requested_skills")
        assert session.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.continued_from_id == parent)) == 1
    assert api.post(path, json=body).json() == response.json()
    different = api.post(path, json={**body, "excluded_continued_skills": []})
    assert different.status_code == 409
    assert len(calls) == 3  # parent, first child, exact replay; no conflicting workflow
    api.close()


@pytest.mark.parametrize("changes, disabled, status", [
    ({"version": "historical-original-version"}, False, 409),
    ({"digest": "0" * 64}, False, 409),
    ({}, True, 403),
])
def test_changed_or_disabled_inherited_skill_is_rejected_before_run_but_can_be_removed(
    setup, changes, disabled, status,
):
    api, calls, path, parent, expected = parent_run(setup, changes=changes, disabled=disabled)
    body = {"goal": "合成核对原技能变化", "idempotency_key": str(uuid4()),
            "continue_from_run_id": str(parent)}
    response = api.post(path, json=body)
    assert response.status_code == status, response.text
    assert response.json()["detail"]["reason"] == (
        "requested_skill_unavailable" if disabled else "requested_skill_version_changed"
    )
    assert len(calls) == 1
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.continued_from_id == parent)) == 0
    reading = api.get(f"{path}/{parent}/continuation")
    assert reading.status_code == 200 and reading.json()["continued_skills"] == expected
    allowed = api.post(path, json={**body, "idempotency_key": str(uuid4()),
                                  "excluded_continued_skills": ["public_research"]})
    assert allowed.status_code == 202, allowed.text
    store, scope = scope_for(setup, allowed.json()["run_id"])
    assert preload(store, scope) == ("gap_check",)
    api.close()


def test_inherited_enablement_is_rechecked_after_admission_before_preload(setup):
    api, _calls, path, parent, _ = parent_run(setup)
    response = api.post(path, json={"goal": "合成受理后再核对启用", "idempotency_key": str(uuid4()),
                                   "continue_from_run_id": str(parent)})
    assert response.status_code == 202, response.text
    store, scope = scope_for(setup, response.json()["run_id"])
    assert preload(store, scope) == ("public_research", "gap_check")
    with Session(setup.admin) as session, session.begin():
        row = session.scalar(select(TenantSkillEnablement).where(
            TenantSkillEnablement.tenant_id == setup.tenant,
            TenantSkillEnablement.skill_key == "public_research",
        ))
        row.enabled = False
    with pytest.raises(DomainError) as rejected:
        preload(store, scope)
    assert rejected.value.code == "FORBIDDEN_SCOPE"
    api.close()


def test_human_explicit_current_selection_replaces_old_version_without_silent_upgrade(setup):
    from pdos_next.agent_kernel.skills import SkillCatalog

    api, _calls, path, parent, _ = parent_run(
        setup, changes={"version": "historical-original-version"},
    )
    current = SkillCatalog().configuration("public_research")
    chosen = {"key": current.key, "version": current.version, "digest": current.digest}
    response = api.post(path, json={
        "goal": "合成人工重新选择当前技能", "idempotency_key": str(uuid4()),
        "continue_from_run_id": str(parent), "requested_skills": [chosen],
    })
    assert response.status_code == 202, response.text
    store, scope = scope_for(setup, response.json()["run_id"])
    assert preload(store, scope) == ("public_research", "gap_check")
    api.close()


def test_restart_excluding_all_inherited_skills_keeps_complete_empty_selection(setup):
    from pdos_next.agent_kernel.context_restart import KEY
    from pdos_next.agent_kernel.skills import SkillCatalog

    api, _calls = client(setup)
    path = f"/v1/categories/{setup.category}/agent-runs"
    response = api.post(path, json={
        "goal": "合成上下文停止后移除全部沿用技能", "idempotency_key": str(uuid4()),
    })
    assert response.status_code == 202, response.text
    original = response.json()
    store, scope = scope_for(setup, original["run_id"])
    skill = SkillCatalog().configuration("proposal_drafting")
    binding = {"key": skill.key, "version": skill.version, "digest": skill.digest}
    with Session(setup.admin) as session, session.begin():
        session.add(TenantSkillEnablement(
            tenant_id=setup.tenant, skill_key=skill.key, enabled=True,
        ))
    store.emit(scope, {"type": "skill_loaded", "isolation": "main", **binding})
    store.emit(scope, {"type": "context_incomplete", "missing": ["synthetic_history"]})
    store.finish(scope, {"status": "partial", "summary": "合成预算停止，等待恢复。",
                         "questions": [], "unfinished": ["继续核对"], "result": {}})
    reading = api.get(f"{path}/{original['run_id']}/continuation")
    assert reading.status_code == 200, reading.text
    assert reading.json()["continued_skills"] == [binding]
    recovery = reading.json()["context_restart"]
    body = {"goal": "保留工作状态，移除全部上轮技能。", "idempotency_key": str(uuid4()),
            "restart_from_run_id": original["run_id"],
            "context_revision": recovery["expected_revision"],
            "excluded_continued_skills": [skill.key]}
    restarted = api.post(path, json=body)
    assert restarted.status_code == 202, restarted.text
    value = restarted.json()
    assert value["session_id"] != original["session_id"]
    assert value["continued_from_id"] is None
    assert value["restarted_from_id"] == original["run_id"]
    restarted_store, restarted_scope = scope_for(setup, value["run_id"])
    assert preload(restarted_store, restarted_scope, (skill.key,)) == ()
    with restarted_store.transaction(restarted_scope) as (session, run):
        assert run.versions[KEY]["source_run_id"] == original["run_id"]
        accepted = session.scalar(select(AgentEvent).where(
            AgentEvent.run_id == run.id, AgentEvent.sequence == 1,
        ))
        assert accepted.body.get("requested_skills", []) == []
        assert "excluded_continued_skills" not in accepted.body
    assert api.post(path, json=body).json() == value
    changed = api.post(path, json={**body, "excluded_continued_skills": []})
    assert changed.status_code == 409
    api.close()
