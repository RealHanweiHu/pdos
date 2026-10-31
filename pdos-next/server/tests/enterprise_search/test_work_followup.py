"""Task action uses real native contracts and small storage doubles, without IO."""
# ruff: noqa: F811 -- existing independent source proof fixture

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pdos_next.agent_kernel import host, work_state_candidates
from pdos_next.domain.work_management import owner
from pdos_next.enterprise_search import action_sources as carry
from pdos_next.enterprise_search import work_followup_actions as actions
from pdos_next.enterprise_search import work_followup_candidates as candidates
from pdos_next.errors import DomainError
from pdos_next.source_current import direct_source_basis
from pydantic import ValidationError
from tests.enterprise_search.test_action_sources import case  # noqa: F401


@pytest.fixture
def task_case(case, monkeypatch):
    project = NS(
        id=case.run.project_id, revision=2, owner_id=case.ctx.requester_id, visibility="category"
    )
    monkeypatch.setattr(owner, "project", lambda *_args, **_kwargs: project)
    return case, project


def test_originals_are_explicit_actual_reads_and_never_inferred_from_discussion(task_case):
    case, project = task_case
    selected = case.source("artifact")
    proof = carry.capture_work(case.session, case.ctx, case.run, [selected])
    assert proof["target"]["project_id"] == str(project.id)
    assert proof["execution_sources"] == proof["read_set"] == []
    assert proof["discussion_sources"][0]["citation_id"] == selected
    ref = {
        "kind": "artifact",
        "id": case.state.carried[selected]["source_id"],
        "revision": 3,
        "position": "line:1;quote_sha256:" + "a" * 64,
    }
    with pytest.raises(DomainError) as failed:
        carry.capture_work(case.session, case.ctx, case.run, [selected], execution_references=[ref])
    assert failed.value.detail["reason_key"] == "assistant_action_execution_read_missing"
    assert case.run.read_sources == []


@pytest.mark.parametrize("customer", [False, True])
def test_uncited_private_or_customer_context_cannot_enter_a_shared_task(
    task_case,
    customer,
    monkeypatch,
):
    case, _project = task_case
    selected = case.source("artifact")
    other = case.source("artifact", private=not customer, customer=customer)
    monkeypatch.setattr(carry, "_audience_roots", lambda *_args: set())
    monkeypatch.setattr(carry, "_source_roots", lambda *_args: {("artifact", "private", "owner")})
    with pytest.raises(DomainError) as failed:
        carry.capture_work(case.session, case.ctx, case.run, [selected])
    expected = "customer_original_shared" if customer else "audience_widened"
    # The actual audience port may not resolve restricted roots in this small fixture.
    assert failed.value.detail["reason_key"] == "assistant_action_" + expected
    assert set(case.state.current_calls[0][0]) == {selected, other}


def test_private_project_must_cover_all_current_readers_not_just_have_private_label(
    task_case,
    monkeypatch,
):
    case, project = task_case
    project.visibility = "private"
    selected = case.source("artifact")
    private = case.source("artifact", private=True)
    monkeypatch.setattr(carry, "_audience_roots", lambda *_args: {("projects", "project", "owner")})
    monkeypatch.setattr(carry, "_source_roots", lambda *_args: {("artifact", "private", "owner")})
    monkeypatch.setattr(carry, "_covers", lambda *_args: False)
    with pytest.raises(DomainError) as failed:
        carry.capture_work(case.session, case.ctx, case.run, [selected])
    assert failed.value.detail["reason_key"] == "assistant_action_audience_widened"
    monkeypatch.setattr(carry, "_covers", lambda *_args: True)
    proof = carry.capture_work(case.session, case.ctx, case.run, [selected])
    assert private not in str(proof) and case.run.read_sources == []
    case.state.actual.pop(private)
    with pytest.raises(DomainError, match="撤回"):
        carry.recheck_work(case.session, case.ctx, case.run, proof)


def test_original_line_check_stays_with_native_work_source_owner(task_case, monkeypatch):
    case, _project = task_case
    cid = case.source("artifact")
    identity = case.state.carried[cid]["source_id"]
    case.run.read_sources = [{"artifact_id": identity, "expected_revision": 3}]
    references = [
        {
            "kind": "artifact",
            "id": identity,
            "revision": 3,
            "position": "line:1;quote_sha256:" + "a" * 64,
        }
    ]
    calls = []

    def line_guard(session, ctx, product, refs, reads):
        assert session is case.session and ctx is case.ctx
        calls.append((refs, reads))
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "原件逐字行校验失败")

    monkeypatch.setattr("pdos_next.source_current.direct_source_basis", line_guard)
    with pytest.raises(DomainError, match="逐字行"):
        carry.capture_work(case.session, case.ctx, case.run, [cid], execution_references=references)
    assert calls and direct_source_basis is not line_guard


@pytest.mark.parametrize("tainted", [False, True])
def test_start_freezes_enabled_skill_without_changing_human_read_selection(
    task_case, monkeypatch, tainted,
):
    case, project = task_case
    cid = case.source("artifact")
    if tainted:
        project.visibility = "private"
        case.source("artifact", private=True, customer=True)
        monkeypatch.setattr(carry, "_audience_roots", lambda *_args: {("project", "p", "owner")})
        monkeypatch.setattr(carry, "_source_roots", lambda *_args: {("artifact", "s", "owner")})
        monkeypatch.setattr(carry, "_covers", lambda *_args: True)
    effective = NS(
        product_id=case.run.product_id,
        project_id=case.run.project_id,
        requested_skills=[],
        sources=[{"artifact_id": str(uuid4()), "expected_revision": 4}],
    )
    before = deepcopy(effective.sources)
    configured = NS(key=actions.SKILL, version="actual-configured-version", digest="a" * 64)
    monkeypatch.setattr(actions, "SkillCatalog", lambda: NS(configuration=lambda _key: configured))
    checked = []
    monkeypatch.setattr(actions, "validate", lambda _s, _c, skills, **_kw: checked.append(skills))
    request = actions.WorkFollowupAction(project_id=case.run.project_id, citation_ids=[cid])
    actual, frozen, skills = actions.prepare_start(
        case.session,
        case.ctx,
        effective,
        case.run,
        request,
    )
    assert actual is effective and actual.sources == before
    assert case.run._explicit_context_binding["private_context"] == tainted
    assert case.run._explicit_context_binding["data_categories"] == (
        ["customer_original"] if tainted else []
    )
    assert frozen["source_run_id"] == str(case.run.id)
    assert frozen["assignment"] is None and frozen["source_proof"]["read_set"] == []
    assert skills[0].key == actions.SKILL and checked == [skills]
    assert "qualification" not in str(frozen) and "promised_at" not in str(frozen)
    with pytest.raises(DomainError):
        actions.prepare_start(
            case.session,
            case.ctx,
            effective,
            case.run,
            request.model_copy(update={"project_id": uuid4()}),
        )


@pytest.mark.parametrize(
    "extra",
    [{"automatic": True}, {"due_date": "2026-11-01"}, {"qualification": "T0"}, {"sources": []}],
)
def test_action_does_not_accept_client_authority_dates_or_model_sources(extra):
    with pytest.raises(ValidationError):
        actions.WorkFollowupAction(project_id=uuid4(), citation_ids=[uuid4()], **extra)


def test_direct_parent_bridge_rechecks_parent_full_footprint_without_expanding_child(
    task_case,
    monkeypatch,
):
    case, _project = task_case
    chosen, hidden, execution = (case.source("artifact") for _ in range(3))
    parent = NS(**{**vars(case.run), "id": uuid4(), "versions": {}})
    case.run.versions = {actions.KEY: {"kind": "prepare_work_followup"}}
    parent_items = {cid: deepcopy(case.state.carried[cid]) for cid in (chosen, hidden)}
    child_items = {execution: deepcopy(case.state.carried[execution])}
    monkeypatch.setattr(
        carry.ledger,
        "carried",
        lambda _s, identity: (
            deepcopy(parent_items if identity == parent.id else child_items),
            set(),
        ),
    )
    original_get = case.session.get
    case.session.get = lambda model, identity: (
        parent
        if identity == parent.id
        else original_get(
            model,
            identity,
        )
    )
    checks = []

    def checked(_s, _ctx, _run, _action):
        checks.append(_run.id)
        return {"run_id": str(parent.id), "discussion_sources": [{"citation_id": chosen}]}

    monkeypatch.setattr(actions, "check_action", checked)
    proof = carry.capture_work(case.session, case.ctx, case.run, [chosen])
    assert checks == [case.run.id]
    assert set(case.state.current_calls[0][0]) == {chosen, hidden, execution}
    assert [item["citation_id"] for item in proof["discussion_sources"]] == [chosen]
    assert proof["read_set"] == case.run.read_sources == []
    assert set(carry.ledger.carried(case.session, case.run.id)[0]) == {execution}


def test_task_action_has_no_t0_write_even_if_policy_would_qualify(monkeypatch):
    @contextmanager
    def transaction(_scope):
        yield None, NS(versions={actions.KEY: {"version": 1}})

    bound = object.__new__(host.BoundHost)
    bound.store = NS(transaction=transaction)
    bound.adapters = NS(route_for=lambda _scope: NS(), source_action_guard=None)
    bound.current = lambda _scope: None
    assert bound.qualified(NS(), NS(), actions.OPERATION) is False
    monkeypatch.setattr("pdos_next.domain.automations.runtime.guard_tool", lambda *_a, **_kw: None)
    monkeypatch.setattr("pdos_next.dingtalk.guards.guard_writing", lambda *_a, **_kw: None)
    with pytest.raises(DomainError) as failed:
        from pdos_next.agent_kernel.bindings import SkillBinding, WriteSource, execution_key

        scope = NS(isolation="main", run_id=uuid4())
        source = WriteSource(
            skill=SkillBinding(key="work_management", version="actual", digest="a" * 64,
                               load_event_id=uuid4()),
            model_call_id=uuid4(), response_index=0,
        )
        bound.write(scope, NS(tier="T0"), {},
                    execution_key(scope.run_id, source.model_call_id, 0), source=source)
    assert failed.value.code == "NAMED_DECISION_REQUIRED"


def test_work_state_uses_fresh_native_receipt_metadata_and_never_copies_candidate_body():
    event = NS(
        id=uuid4(),
        body={"type": "domain_candidate", "kind": candidates.KIND, "payload": "DO_NOT_COPY"},
    )
    run = NS(id=uuid4())
    receipt = str(uuid4())
    value = work_state_candidates._summary(
        event,
        run,
        {
            "kind": candidates.KIND,
            "state": "adopted",
            "operation": actions.OPERATION,
            "receipt": {"id": receipt, "body": "DO_NOT_COPY"},
            "command": "DO_NOT_COPY",
        },
    )
    assert value["kind"] == "domain" and value["state"] == "adopted"
    assert value["receipt_id"] == receipt and "DO_NOT_COPY" not in str(value)
    assert work_state_candidates._summary(event, run, {"state": "adopted"})["state"] == (
        "unavailable"
    )


def test_ordinary_human_task_command_has_no_action_candidate_requirement():
    session = NS(scalar=lambda _query: None)
    candidates.check_command(session, NS(tenant_id=uuid4()), NS(command_id=uuid4()))


def test_readonly_action_check_does_not_lock_future_assignment_members(task_case, monkeypatch):
    case, _project = task_case
    cid = case.source("artifact")
    parent = case.run
    child = NS(**{**vars(parent), "id": uuid4(), "continued_from_id": parent.id})
    proof = {"discussion_sources": [{"citation_id": cid}]}
    action = {"version": 1, "kind": "prepare_work_followup", "source_run_id": str(parent.id),
              "citation_ids": [cid], "assignment": {"assignee_id": str(uuid4()),
                                                       "recipient_id": str(uuid4())},
              "source_proof": proof}
    monkeypatch.setattr(actions, "recheck_work", lambda *_a: proof)

    def no_member_lock(*_a):
        raise AssertionError("Future assignment is not a readonly task creation prerequisite")

    monkeypatch.setattr(actions, "_assignment", no_member_lock)
    assert actions.check_action(case.session, case.ctx, child, action) is proof


def test_server_candidate_command_cannot_change_payload_before_native_create(monkeypatch):
    from pdos_next.contracts import Command

    command = Command(command_id=uuid4(), idempotency_key=str(uuid4()),
                      operation=actions.OPERATION, category_id=uuid4(), product_id=uuid4(),
                      expected_revision=1, source_read_set=[], payload={"title": "fixed"})
    event = NS(run_id=uuid4())
    run = NS(id=event.run_id)
    statements = []
    session = NS(scalar=lambda query: statements.append(query) or event,
                 get=lambda _model, _identity, **_kw: run)
    monkeypatch.setattr(
        candidates, "read", lambda *_a: {"command": command.model_dump(mode="json")},
    )
    ctx = NS(tenant_id=uuid4())
    candidates.check_command(session, ctx, command)
    changed = command.model_copy(update={"payload": {"title": "changed"}})
    with pytest.raises(DomainError):
        candidates.check_command(session, ctx, changed)
    assert "work_followup" in str(statements[0].compile().params.values())
    assert str(command.command_id) in statements[0].compile().params.values()
