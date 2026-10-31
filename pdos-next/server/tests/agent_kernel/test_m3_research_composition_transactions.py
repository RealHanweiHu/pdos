"""Actual child-read references and instruction captures in the marked M3 database."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.category_research_refs import CategoryResearchRefs
from pdos_next.agent_kernel.models import AgentEvent, AgentToolCall, TenantSkillEnablement
from pdos_next.agent_kernel.research_instruction import ResearchInstruction
from pdos_next.errors import DomainError
from tests.agent_kernel.test_category_candidate_transactions import personal_fixture
from tests.agent_kernel.test_snapshot_proof_transactions import registered_page, registration


def coverage(snapshot, page):
    return {
        "snapshots": [{"id": str(snapshot.id), "content_hash": snapshot.content_hash}],
        "coverage": [{"reads": [{
            "snapshot_id": str(snapshot.id), "locator": page["locator"], "error": None,
        }]}],
    }


def test_actual_personal_child_reference_can_restore_and_feed_category_candidate(setup, tmp_path):
    f = personal_fixture(setup, tmp_path)
    callback = CategoryResearchRefs(f.store, f.artifacts)
    with f.store.transaction(f.scope) as (session, _):
        page = session.get(AgentToolCall, f.read_id).result
    result = coverage(f.snapshot, page)
    refs = callback(f.scope, result)
    assert refs == [{
        "call_id": str(f.read_id), "snapshot_id": str(f.snapshot.id),
        "content_hash": f.snapshot.content_hash, "locator": page["locator"],
    }]
    assert f.arguments["groups"]["snapshot_refs"] == [
        {"call_id": refs[0]["call_id"], "content_hash": refs[0]["content_hash"]}
    ]
    result["snapshot_read_refs"] = refs
    assert callback(f.scope, result) == refs
    assert "markdown" not in str(refs)
    forged = deepcopy(result)
    forged["snapshot_read_refs"][0]["call_id"] = str(uuid4())
    with pytest.raises(DomainError):
        callback(f.scope, forged)
    changed = deepcopy(result)
    changed["coverage"][0]["reads"][0]["locator"] = "chars:0:1"
    with pytest.raises(DomainError):
        callback(f.scope, changed)


def test_actual_registered_page_returns_original_read_reference_on_restore(setup, tmp_path):
    f, snapshot, _ = registration(setup, tmp_path)
    page = registered_page(f, snapshot, cursor=0, page_chars=8)
    callback = CategoryResearchRefs(f.store, f.adapter.artifacts)
    result = coverage(snapshot, page)
    refs = callback(f.scope, result)
    assert refs[0]["call_id"] == page["execution_ref"]["call_id"]
    result["snapshot_read_refs"] = refs
    later = registered_page(f, snapshot, cursor=0, page_chars=8)
    assert later["execution_ref"]["call_id"] != refs[0]["call_id"]
    assert callback(f.scope, result) == refs


def instruction_fixture(setup, tmp_path):
    f = personal_fixture(setup, tmp_path, sources=False)
    skill = f.bootstrap.catalog._skills["public_research"]
    with Session(setup.admin) as session, session.begin():
        session.add(TenantSkillEnablement(
            tenant_id=setup.tenant, skill_key=skill.key, enabled=True,
            pilot=False, qualification_revoked=True,
        ))
    f.instruction = ResearchInstruction(f.store, f.bootstrap.catalog)
    f.research_scope = f.scope.child("research")
    return f


def test_actual_instruction_capture_is_locked_once_and_has_real_research_skill_event(
    setup, tmp_path,
):
    f = instruction_fixture(setup, tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(f.instruction, [f.research_scope, f.research_scope]))
    assert first == second and "LedgerDraft" in first.instruction
    assert "category.knowledge.add" not in first.instruction
    with f.store.transaction(f.research_scope) as (session, run):
        event = session.get(AgentEvent, first.skill.load_event_id)
        assert event.body == {
            "type": "skill_loaded", "key": "public_research",
            "version": first.skill.version, "digest": first.skill.digest,
            "isolation": "research",
        }
        assert run.versions["research_instruction"]["load_event_id"] == str(event.id)
        assert session.scalar(select(func.count()).select_from(AgentEvent).where(
            AgentEvent.run_id == run.id, AgentEvent.body["key"].astext == "public_research",
        )) == 1
    assert f.bootstrap.default_preload(f.scope) == ()


@pytest.mark.parametrize("change", ["version", "content", "disabled", "cancelled"])
def test_actual_captured_instruction_refuses_changed_skill_or_current_authority(
    setup, tmp_path, change,
):
    f = instruction_fixture(setup, tmp_path)
    f.instruction(f.research_scope)
    if change in {"version", "content"}:
        skill = f.bootstrap.catalog._skills["public_research"]
        f.bootstrap.catalog._skills[skill.key] = replace(
            skill, **{change: getattr(skill, change) + " changed"},
        )
    elif change == "disabled":
        with Session(setup.admin) as session, session.begin():
            row = session.scalar(select(TenantSkillEnablement).where(
                TenantSkillEnablement.tenant_id == setup.tenant,
                TenantSkillEnablement.skill_key == "public_research",
            ))
            row.enabled = False
    else:
        with f.store.transaction(f.scope, lock=True) as (_, run):
            run.state = "cancelled"
            run.cancel_epoch += 1
    with pytest.raises(DomainError):
        f.instruction(f.research_scope)
