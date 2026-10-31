"""Fixed continuation identities and Human removals, with DB/policy ports isolated."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel import requested_skills
from pdos_next.agent_kernel.requested_skills import RequestedSkill
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.errors import DomainError


def identity(key):
    skill = SkillCatalog().configuration(key)
    return RequestedSkill(key=key, version=skill.version, digest=skill.digest)


def loaded(key, **change):
    return {"type": "skill_loaded", "isolation": "main",
            **identity(key).model_dump(mode="json"), **change}


def session_for(events):
    return SimpleNamespace(scalars=lambda _query: events)


def test_recent_preserves_newest_actual_two_bindings_without_loading_current_catalog(monkeypatch):
    old = loaded("public_research", version="stored-prior-version", digest="1" * 64)
    events = [loaded("gap_check", isolation="research"), old,
              loaded("public_research"), loaded("gap_check"), loaded("proposal_drafting")]
    monkeypatch.setattr(requested_skills, "SkillCatalog", lambda: pytest.fail("metadata only"))
    result = requested_skills.recent(session_for(events), uuid4())
    assert result == [RequestedSkill.model_validate({
        key: old[key] for key in ("key", "version", "digest")
    }), identity("gap_check")]


def test_removed_or_explicit_recent_skill_does_not_pull_in_an_older_third(monkeypatch):
    events = [loaded(key) for key in ("public_research", "gap_check", "proposal_drafting")]
    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: True)
    parent = SimpleNamespace(id=uuid4())
    session = session_for(events)
    assert requested_skills.validate_start(
        session, object(), [], parent=parent, excluded=["public_research"],
    ) == [identity("gap_check")]
    assert requested_skills.validate_start(
        session, object(), [identity("public_research")], parent=parent,
    ) == [identity("public_research"), identity("gap_check")]
    assert requested_skills.validate_start(
        session, object(), [], parent=parent, excluded=["public_research", "gap_check"],
    ) == []


@pytest.mark.parametrize("change, enabled, code", [
    ({"version": "stored-prior-version"}, True, "VERSION_CONFLICT"),
    ({"digest": "0" * 64}, True, "VERSION_CONFLICT"),
    ({}, False, "FORBIDDEN_SCOPE"),
])
def test_inherited_binding_changes_are_rejected_instead_of_skipped_or_upgraded(
    monkeypatch, change, enabled, code,
):
    session = session_for([loaded("gap_check", **change)])
    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: enabled)
    with pytest.raises(DomainError) as rejected:
        requested_skills.validate_start(session, object(), [], parent=SimpleNamespace(id=uuid4()))
    assert rejected.value.code == code
    assert rejected.value.detail["reason"] == (
        "requested_skill_unavailable" if code == "FORBIDDEN_SCOPE"
        else "requested_skill_version_changed"
    )
    assert requested_skills.validate_start(
        session, object(), [], parent=SimpleNamespace(id=uuid4()), excluded=["gap_check"],
    ) == []


def test_human_reselecting_current_version_replaces_the_old_inherited_identity(monkeypatch):
    session = session_for([loaded("gap_check", version="stored-prior-version")])
    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: True)
    assert requested_skills.validate_start(
        session, object(), [identity("gap_check")], parent=SimpleNamespace(id=uuid4()),
    ) == [identity("gap_check")]


@pytest.mark.parametrize("excluded", [
    ["gap_check", "gap_check"], ["proposal_drafting"], [""], [None],
    ["public_research", "gap_check", "proposal_drafting"],
])
def test_invalid_exclusions_are_not_silently_ignored(monkeypatch, excluded):
    session = session_for([loaded("public_research"), loaded("gap_check")])
    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: True)
    with pytest.raises(DomainError) as rejected:
        requested_skills.validate_start(
            session, object(), [], parent=SimpleNamespace(id=uuid4()), excluded=excluded,
        )
    assert rejected.value.status == 422
    assert rejected.value.detail["reason"] == "continued_skill_selection_invalid"


def test_new_conversation_cannot_claim_an_inherited_skill_to_remove():
    with pytest.raises(DomainError) as rejected:
        requested_skills.validate_start(object(), object(), [], excluded=["gap_check"])
    assert rejected.value.status == 422


def test_incomplete_historical_binding_is_not_rebound_to_current_version():
    event = loaded("gap_check")
    event.pop("digest")
    with pytest.raises(DomainError) as rejected:
        requested_skills.recent(session_for([event]), uuid4())
    assert rejected.value.code == "VERSION_CONFLICT"


def test_preload_uses_recorded_exclusions_and_rechecks_current_policy(monkeypatch):
    event = SimpleNamespace(body={"excluded_continued_skills": ["public_research"]})
    session = session_for([loaded("public_research"), loaded("gap_check"),
                           loaded("proposal_drafting")])
    session.scalar = lambda _query: event
    run = SimpleNamespace(id=uuid4(), continued_from_id=uuid4())

    @contextmanager
    def transaction(_scope):
        yield session, run

    store = SimpleNamespace(transaction=transaction)
    scope = SimpleNamespace(isolation="main", trigger="conversation")
    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: True)
    assert requested_skills.preload(store, scope) == ("gap_check",)
    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: False)
    with pytest.raises(DomainError, match="技能当前未启用"):
        requested_skills.preload(store, scope)


def test_default_preload_cannot_override_a_removed_or_changed_historical_binding(monkeypatch):
    event = SimpleNamespace(body={})
    session = session_for([loaded("proposal_drafting", version="stored-prior-version")])
    session.scalar = lambda _query: event
    run = SimpleNamespace(id=uuid4(), continued_from_id=uuid4())

    @contextmanager
    def transaction(_scope):
        yield session, run

    store = SimpleNamespace(transaction=transaction)
    scope = SimpleNamespace(isolation="main", trigger="conversation")
    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: True)
    with pytest.raises(DomainError) as rejected:
        requested_skills.preload(store, scope, ("proposal_drafting",))
    assert rejected.value.code == "VERSION_CONFLICT"
    event.body = {"excluded_continued_skills": ["proposal_drafting"]}
    assert requested_skills.preload(store, scope, ("proposal_drafting",)) == ()


@pytest.mark.parametrize("selected", [False, True])
def test_proven_restart_uses_complete_fixed_selection_including_empty(monkeypatch, selected):
    from tests.agent_kernel.test_context_restart import provenance

    run, source = provenance()
    requested = [identity("gap_check")] if selected else []
    event = SimpleNamespace(body={
        "requested_skills": [item.model_dump(mode="json") for item in requested],
    })
    session = SimpleNamespace(scalar=lambda _query: event, get=lambda *_: source,
                              scalars=lambda _: pytest.fail("restart must not inherit again"))

    @contextmanager
    def transaction(_scope):
        yield session, run

    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: True)
    store = SimpleNamespace(transaction=transaction)
    scope = SimpleNamespace(isolation="main", trigger="conversation")
    assert requested_skills.preload(store, scope, ("proposal_drafting",)) == (
        ("gap_check",) if selected else ()
    )


@pytest.mark.parametrize("fault", ["source_proof", "disabled"])
def test_restart_complete_selection_still_requires_exact_proof_and_current_policy(
    monkeypatch, fault,
):
    from tests.agent_kernel.test_context_restart import provenance

    run, source = provenance()
    event = SimpleNamespace(body={"requested_skills": [identity("gap_check").model_dump()]})
    session = SimpleNamespace(scalar=lambda _query: event, get=lambda *_: source)
    if fault == "source_proof":
        source.revision += 1

    @contextmanager
    def transaction(_scope):
        yield session, run

    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_: fault != "disabled")
    store = SimpleNamespace(transaction=transaction)
    scope = SimpleNamespace(isolation="main", trigger="conversation")
    with pytest.raises(DomainError) as rejected:
        requested_skills.preload(store, scope, ("proposal_drafting",))
    assert rejected.value.code == (
        "SOURCE_UNAVAILABLE" if fault == "source_proof" else "FORBIDDEN_SCOPE"
    )


@pytest.mark.parametrize("scope", [
    SimpleNamespace(isolation="research", trigger="conversation"),
    SimpleNamespace(isolation="main", trigger="automation_manual"),
])
def test_nonconversation_or_isolated_child_does_not_inherit(scope):
    assert requested_skills.preload(object(), scope, ("gap_check",)) == ("gap_check",)
