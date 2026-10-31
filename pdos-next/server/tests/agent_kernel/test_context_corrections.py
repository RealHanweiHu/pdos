"""Human selectors use actual fixed source reads, not prompt or scope claims."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import context_corrections as corrections
from pdos_next.agent_kernel import work_state
from pdos_next.agent_kernel.conversation import merge_binding
from pdos_next.contracts import SourceRead
from pdos_next.errors import DomainError
from pdos_next.service import digest


def case():
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        requester_id=uuid4(),
        category_id=uuid4(),
        product_id=None,
        project_id=None,
        proposal_id=None,
        read_sources=[],
        versions={},
        private_context=False,
        data_categories=["internal"],
        customer_identities=[],
    )
    ctx = SimpleNamespace(tenant_id=run.tenant_id, requester_id=run.requester_id)
    ref = {
        "source_type": "issue",
        "source_id": str(uuid4()),
        "object_id": str(uuid4()),
        "source_revision": 2,
        "content_hash": "a" * 64,
        "category_id": str(run.category_id),
        "product_id": None,
        "project_id": None,
        "proposal_id": None,
        "title": "实际登记问题",
        "private": True,
        "customer_original": False,
    }
    return run, ctx, ref


def selection(ref, **updates):
    return {
        "version": 1,
        "status": "available",
        "focus": ref,
        "version_mode": "any",
        "versions": [],
        "sources": None,
        **updates,
    }


def change(ref, kind="replace_focus"):
    return corrections.ContextChange(
        kind=kind,
        sources=[
            {
                "source_type": ref["source_type"],
                "source_id": ref["source_id"],
                "expected_revision": ref["source_revision"],
            }
        ],
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"owner_id": str(uuid4())},
        {"tenant_id": str(uuid4())},
        {"audience": []},
        {
            "sources": [
                {
                    "source_type": "issue",
                    "source_id": str(uuid4()),
                    "expected_revision": 1,
                    "content_hash": "a" * 64,
                }
            ]
        },
    ],
)
def test_human_change_is_closed_and_cannot_supply_policy_or_actual_hash(patch):
    _run, _ctx, ref = case()
    with pytest.raises(ValidationError):
        corrections.ContextChange.model_validate({**change(ref).model_dump(), **patch})


def test_existing_work_state_actions_cannot_smuggle_a_context_change():
    _run, _ctx, ref = case()
    base = {"request_key": uuid4(), "expected_revision": 4}
    assert work_state.ChangeInput(**base, action="correct_context", context_change=change(ref))
    with pytest.raises(ValidationError):
        work_state.ChangeInput(
            **base, action="remove_constraint", item_id=uuid4(), context_change=change(ref)
        )
    with pytest.raises(ValidationError):
        work_state.ChangeInput(
            **base, action="correct_context", item_id=uuid4(), context_change=change(ref)
        )


def test_catalog_lookup_keeps_scope_and_exact_version_under_ordinary_rls(monkeypatch):
    run, _ctx, ref = case()
    run.product_id, run.project_id = uuid4(), uuid4()
    statements = []
    monkeypatch.setattr("pdos_next.enterprise_search.sources.prepare_read", lambda *_: None)
    session = SimpleNamespace(
        execute=lambda query: (
            statements.append(query)
            or SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))
        )
    )
    corrections._rows(session, run, change(ref).sources)
    sql = str(
        statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert str(run.tenant_id) in sql and str(run.category_id) in sql
    assert "source_id" in sql and "category_id" in sql
    assert str(run.product_id) not in sql and str(run.project_id) not in sql
    assert "source_revision) IN" in sql and str(ref["source_id"]) in sql
    assert "SECURITY DEFINER" not in sql and "owner_id =" not in sql


def test_resolution_reloads_real_rows_and_dependencies_not_browser_titles(monkeypatch):
    run, ctx, ref = case()
    actual = {
        **ref,
        "source_id": UUID(ref["source_id"]),
        "object_id": UUID(ref["object_id"]),
        "category_id": run.category_id,
        "private": False,
    }
    monkeypatch.setattr(corrections, "_rows", lambda *_: [actual])
    seen = []

    def current(_session, rows):
        seen.append(rows)
        return {"0": {"private": True, "customer_original": True}}, {}

    monkeypatch.setattr("pdos_next.enterprise_search.assistant_sources.current", current)
    result = corrections.resolve(None, ctx, run, change(ref).sources)
    assert result[0]["title"] == ref["title"] and result[0]["content_hash"] == ref["content_hash"]
    assert result[0]["private"] and result[0]["customer_original"]
    assert len(seen) == 1
    monkeypatch.setattr(
        "pdos_next.enterprise_search.assistant_sources.current",
        lambda *_: ({}, {"0": "source_dependency_unavailable"}),
    )
    with pytest.raises(DomainError):
        corrections.resolve(None, ctx, run, change(ref).sources)


def test_wrong_object_replaces_focus_but_retains_literal_constraints_and_tombstones(monkeypatch):
    run, ctx, ref = case()
    body = work_state.empty()
    body.update(
        constraints=[{"id": "literal", "text": "压力单位未知", "run_id": str(run.id)}],
        removed_constraints=["deleted"],
        focus_objects=[
            {
                "kind": "artifact",
                "id": str(uuid4()),
                "version": 1,
                "run_id": str(run.id),
            }
        ],
        context_selection=selection(ref, version_mode="fixed", versions=[ref]),
    )
    before = deepcopy(body)
    monkeypatch.setattr(corrections, "resolve", lambda *_: [ref])
    corrections.apply(None, ctx, run, body, change(ref))
    assert body["constraints"] == before["constraints"]
    assert body["removed_constraints"] == ["deleted"]
    assert body["context_selection"]["focus"] == ref
    assert body["context_selection"]["versions"] == [ref]
    assert body["context_selection"]["version_mode"] == "fixed"
    newer = {**ref, "source_id": str(uuid4()), "source_revision": 3, "content_hash": "b" * 64}
    assert not corrections.accepts(newer, body["context_selection"])
    assert all(item["kind"] != "artifact" for item in body["focus_objects"])
    corrections.apply(None, ctx, run, body, corrections.ContextChange(kind="clear"))
    assert "context_selection" not in body and body["focus_objects"] == []
    assert body["removed_constraints"] == ["deleted"]


def test_human_current_choice_resolves_actual_head_once_without_rewriting_old_run(monkeypatch):
    run, ctx, ref = case()
    body = work_state.empty() | {"context_selection": selection(ref)}
    old = deepcopy(ref)
    head = {**ref, "source_id": str(uuid4()), "source_revision": 3, "content_hash": "b" * 64}
    monkeypatch.setattr(corrections, "_current_focus", lambda *_: head)
    corrections.apply(None, ctx, run, body, corrections.ContextChange(kind="current_only"))
    assert body["context_selection"]["focus"] == head
    assert body["context_selection"]["version_mode"] == "current" and ref == old
    assert body["context_selection"]["sources"] == [head]
    newer = {**head, "source_id": str(uuid4()), "source_revision": 4, "content_hash": "c" * 64}
    assert not corrections.accepts(newer, body["context_selection"], actual={"is_current": True})


def test_only_explicit_current_artifact_choice_replaces_parent_fixed_read(monkeypatch):
    run, ctx, ref = case()
    ref.update(source_type="artifact", object_id=ref["source_id"])
    run.read_sources = [{"artifact_id": ref["source_id"], "expected_revision": 1}]
    state = SimpleNamespace(body={"context_selection": selection(ref)})
    monkeypatch.setattr(corrections, "recheck", lambda *_: selection(ref))
    reads, _condition = corrections.selected_reads(None, ctx, run, state, [])
    assert reads == [SourceRead(artifact_id=ref["source_id"], expected_revision=2)]
    assert run.read_sources[0]["expected_revision"] == 1
    with pytest.raises(DomainError):
        corrections.selected_reads(
            None,
            ctx,
            run,
            state,
            [
                SourceRead(artifact_id=ref["source_id"], expected_revision=1),
            ],
        )
    monkeypatch.setattr(corrections, "recheck", lambda *_: None)
    with pytest.raises(DomainError):
        corrections.selected_reads(None, ctx, run, state, reads)


def test_original_human_sources_limit_but_automatic_verification_sources_do_not(monkeypatch):
    run, ctx, ref = case()
    original = SimpleNamespace(sources=[])
    effective = SimpleNamespace(sources=[SourceRead(artifact_id=uuid4(), expected_revision=1)])
    monkeypatch.setattr(corrections, "resolve", lambda *_: [ref])
    corrections.configure_start(None, ctx, run, original, effective, None)
    assert corrections.requested(run) == (None, True)
    original.sources = effective.sources
    corrections.configure_start(None, ctx, run, original, effective, None)
    assert corrections.requested(run)[0]["sources"] == [ref]
    assert run.versions["context_selection_start_revision"] == 0


def test_actual_selected_privacy_merges_with_original_binding_without_scope_change():
    run, _ctx, _ref = case()
    run._explicit_context_binding = {
        "private_context": True,
        "data_categories": ["customer_original"],
    }
    binding = SimpleNamespace(
        private_context=False, data_categories=["internal"], customer_identities=[], read_sources=[]
    )
    merged = merge_binding(binding, run)
    assert merged.private_context and "customer_original" in merged.data_categories
    assert not hasattr(merged, "category_id") and run.category_id is not None


def test_frozen_condition_digest_and_fixed_hash_remain_authoritative(monkeypatch):
    run, ctx, ref = case()
    value = selection(ref)
    run.versions = {"work_state": {"context_selection": value}, "work_state_digest": "bad"}
    with pytest.raises(DomainError):
        corrections.frozen_condition(run)
    run.versions["work_state_digest"] = digest(run.versions["work_state"])
    assert corrections.frozen_condition(run) == value
    monkeypatch.setattr(corrections, "resolve", lambda *_: [{**ref, "content_hash": "b" * 64}])
    with pytest.raises(DomainError):
        corrections.recheck(None, ctx, run, value)
    hidden = corrections.public(None, ctx, run, value)
    assert hidden["status"] == "unavailable" and ref["title"] not in str(hidden)


def test_exact_allowlist_and_currentness_never_become_applicability():
    _run, _ctx, ref = case()
    fixed = selection(ref, focus=None, sources=[ref])
    assert corrections.accepts(ref, fixed)
    assert not corrections.accepts({**ref, "content_hash": "b" * 64}, fixed)
    assert not corrections.accepts({**ref, "source_revision": 3}, fixed)
    current = selection(ref, focus=None, version_mode="current")
    assert not corrections.accepts(ref, current, actual={"is_current": False})
    assert corrections.accepts(ref, current, actual={"is_current": True})
    assert "applicable" not in current and "verified" not in current


def test_removed_literal_condition_is_not_revived_by_context_choices(monkeypatch):
    run, ctx, ref = case()
    proposal = {"run_id": str(run.id), "text": "压力单位未知"}
    accepted, _ = work_state.validate_constraints([proposal], {str(run.id): "压力单位未知"}, set())
    body = work_state.empty() | {"removed_constraints": [accepted[0]["id"]]}
    monkeypatch.setattr(corrections, "resolve", lambda *_: [ref])
    corrections.apply(None, ctx, run, body, change(ref, "limit_sources"))
    values, rejected = work_state.validate_constraints(
        [proposal], {str(run.id): "压力单位未知"}, set(body["removed_constraints"])
    )
    assert values == [] and rejected[0]["reason"] == "removed_by_user"


def test_real_finish_does_not_resurrect_a_later_human_clear_or_deleted_literal(monkeypatch):
    run, _ctx, ref = case()
    run.category_id = None
    run.trigger, run.state, run.goal, run.session_id = (
        "conversation",
        "failed",
        "压力单位未知",
        uuid4(),
    )
    literal, _ = work_state.validate_constraints(
        [{"run_id": str(run.id), "text": run.goal}],
        {str(run.id): run.goal},
        set(),
    )
    body = work_state.empty() | {"removed_constraints": [literal[0]["id"]]}
    latest = SimpleNamespace(revision=2, body=body)
    condition = selection(ref)
    run.versions = {
        "requested_context_selection": condition,
        "requested_context_selection_digest": digest(condition),
        "context_selection_start_revision": 1,
    }
    sequences = iter([[SimpleNamespace(id=run.id, goal=run.goal)], [], []])
    session = SimpleNamespace(
        scalar=lambda *_: None, execute=lambda *_: SimpleNamespace(all=lambda: next(sequences))
    )
    appended = []
    monkeypatch.setattr(work_state, "_lock", lambda *_: None)
    monkeypatch.setattr(work_state, "latest", lambda *_: latest)
    monkeypatch.setattr(
        work_state,
        "_append",
        lambda _session, _run, value, **_kwargs: appended.append(deepcopy(value)),
    )
    work_state._record_finish(
        session,
        run,
        {
            "result": {
                "context_proposals": {
                    "constraints": [{"run_id": str(run.id), "text": run.goal}],
                }
            }
        },
    )
    assert "context_selection" not in appended[0]
    assert appended[0]["constraints"] == []
    assert appended[0]["removed_constraints"] == [literal[0]["id"]]
    assert run.versions["work_state_proposals"]["rejected"][0]["reason"] == "removed_by_user"


def test_registered_context_schema_retains_exact_human_selection_without_new_authority():
    from pdos_next.agent_kernel.context_projection import project
    from pdos_next.agent_kernel.skills import SkillCatalog

    _run, _ctx, ref = case()
    registered = SkillCatalog().contexts
    schema = {
        **registered["$defs"]["work_state"]["properties"]["context_selection"],
        "$defs": registered["$defs"],
    }
    value = selection(ref, version_mode="fixed", versions=[ref])
    projected, omitted, issues = project(value, schema)
    assert projected == value and not omitted and not issues
    assert projected["versions"][0]["content_hash"] == ref["content_hash"]
    assert schema["additionalProperties"] is False
    narrowed, omitted, issues = project({**value, "audience": ["model-supplied"]}, schema)
    assert narrowed == value and not issues
    assert omitted == [{"field": "/audience", "reason": "outside_skill_context_schema"}]
