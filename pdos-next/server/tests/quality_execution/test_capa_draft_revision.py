"""Staged real kernel/host pure checks; storage and trust ports are explicit fakes.

No PostgreSQL, HTTP, installed SQL guard, actual original bytes, qualification or
common Receipt is proved here. Root owns the affected real transaction checks.
"""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from quality_issues.helpers import NOW, Harness, Rejection, source, uid
from sqlalchemy import Engine
from sqlalchemy.dialects import postgresql

from pdos_next.domain.quality_execution import service
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.quality_execution.schemas import CapaDraftPayload, IssueTriagePayload
from pdos_next.domain.quality_issues.handlers import OPERATIONS
from pdos_next.domain.quality_issues.rules import capa_draft_text_revisable, replace
from pdos_next.errors import DomainError
from pdos_next.models import RemediationLinkRecord
from pdos_next.schemas.quality_issues.contracts import (
    CapaDraft,
    EffectivenessDecision,
    IssueTriage,
    NamedConclusion,
    RootCauseDecide,
)
from quality_execution.test_pure import call, create, result
from quality_execution.test_pure import host as old_host  # noqa: F401


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("owned pure tests must not connect to PostgreSQL or HTTP")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    import httpx

    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)


@pytest.fixture
def host(old_host, monkeypatch):  # noqa: F811 - pytest resolves the registered alias fixture
    # The older host fake used tuple sources; actual policy read DTO uses JSON lists.
    previous = service.policy.assess

    def publication(*args, **kwargs):
        value = previous(*args, **kwargs)
        value["sources"] = list(value["sources"])
        return value

    monkeypatch.setattr(service.policy, "assess", publication)
    return old_host


def reject(code, operation):
    with pytest.raises(DomainError) as error:
        operation()
    assert error.value.reason == code


def draft_for(issue):
    return CapaDraft(
        capa_id=uid("capa"),
        hypotheses=[{"text": "Tentative only", "sources": [source("hypothesis")]}],
        actions=[
            {
                "id": uid("corrective"),
                "kind": "corrective",
                "text": "Prepare and retest",
                "executor_id": uid("actor"),
            },
            {
                "id": uid("preventive"),
                "kind": "preventive",
                "text": "Retain original evidence",
                "executor_id": uid("actor"),
            },
        ],
        requirement={
            "method": "Independent new run",
            "acceptance": "All fixed affected pairs pass",
            "observation_until": NOW + timedelta(hours=1),
            "required_failure_ids": [failure.identity for failure in issue.failures],
        },
    )


def pending():
    h = Harness()
    identity = h.create().subject_id
    h.call("quality.issue.triage", identity, 1, IssueTriage(reason="Synthetic triage"))
    payload = draft_for(h.issue(identity))
    h.call("quality.capa.draft", identity, 2, payload)
    return h, identity, payload


def changed(payload):
    actions = (
        replace(payload.actions[0], text="Prepare and retain actual documents"),
        *payload.actions[1:],
    )
    return replace(payload, actions=actions)


def actual_command(h, payload):
    return SimpleNamespace(
        operation="quality.capa.draft",
        command_id=uuid4(),
        product_id=h.product.id,
        expected_revision=h.product.revision,
        source_read_set=result().required_source_read_set,
    )


def pending_host(h):
    first = create(h)
    second = call(
        h,
        "quality.issue.triage",
        IssueTriagePayload(
            issue_id=first.issue_id, expected_issue_revision=1, reason="Synthetic triage"
        ),
    )[0]
    domain = draft_for(service._snapshot(second))
    payload = CapaDraftPayload(
        issue_id=first.issue_id, expected_issue_revision=2, **domain.model_dump()
    )
    command = actual_command(h, payload)
    row = service.apply(h.s, h.ctx, command, h.product, payload)[0]
    revision = changed(payload)
    revision = replace(revision, expected_issue_revision=row.revision)
    return row, revision, payload, command


def link(h, issue, **changes):
    fields = dict(
        id=uuid4(),
        tenant_id=h.ctx.tenant_id,
        product_id=h.product.id,
        project_id=issue.scope.project_id,
        issue_id=issue.id,
        capa_id=issue.capa.id,
    )
    fields.update(changes)
    return RemediationLinkRecord(**fields)


def test_imports_resolve_to_the_explicit_staged_or_actual_layout():
    directory = Path(__file__).resolve().parent
    if directory.name == "wave22-capa-draft-revision-staged":
        server = directory / "server"
    elif directory.name == "quality_execution" and directory.parent.name == "tests":
        server = directory.parents[1]
    else:
        raise AssertionError("unsupported owned test layout")
    expected = server / "pdos_next/domain/quality_execution/service.py"
    assert Path(service.__file__).resolve() == expected


def test_real_kernel_preserves_complete_issue_and_old_capa_except_text_revision_history():
    h, identity, payload = pending()
    original = h.issue(identity)
    before = original.model_dump(mode="json")
    receipt = h.call("quality.capa.draft", identity, original.revision, changed(payload))
    current = h.issue(identity)
    expected = deepcopy(before)
    expected["revision"] += 1
    expected["history"] = current.model_dump(mode="json")["history"]
    expected["capa"]["actions"][0]["text"] = "Prepare and retain actual documents"
    assert current.model_dump(mode="json") == expected
    assert current.history[:-1] == original.history
    assert original.model_dump(mode="json") == before
    assert receipt.revision == original.revision + 1
    assert current.root_cause is None and current.closure is None
    assert current.capa.effectiveness is None
    assert all(action.completion is None for action in current.capa.actions)


def test_kernel_preview_is_text_only_without_writing_or_consuming_any_t1_proof():
    h, identity, payload = pending()
    original = h.issue(identity)
    before = deepcopy(h.commands.__dict__)
    preview = h.handler.preview("quality.capa.draft", identity, original.revision, changed(payload))
    assert preview.operation == "quality.capa.draft"
    assert OPERATIONS[preview.operation][1] == "T0"
    assert h.issue(identity) == original
    assert h.commands.proofs == before["proofs"]
    assert h.commands.consumed == before["consumed"]
    assert h.commands.receipts == before["receipts"]


@pytest.mark.parametrize(
    "field",
    [
        "capa_id",
        "hypothesis_text",
        "hypothesis_source",
        "method",
        "acceptance",
        "observation_until",
        "failure",
        "action_id",
        "kind",
        "executor",
        "add",
        "remove",
        "reorder",
        "duplicate",
    ],
)
def test_revision_refuses_every_non_text_scope_identity_or_requirement_change(field):
    h, identity, payload = pending()
    revision = changed(payload)
    if field == "capa_id":
        revision = replace(revision, capa_id=uid("another-capa"))
    elif field.startswith("hypothesis"):
        hypothesis = replace(
            revision.hypotheses[0],
            **(
                {"text": "Different hypothesis"}
                if field.endswith("text")
                else {"sources": (source("another-source"),)}
            ),
        )
        revision = replace(revision, hypotheses=(hypothesis,))
    elif field in {"method", "acceptance", "observation_until", "failure"}:
        key = "required_failure_ids" if field == "failure" else field
        value = (
            ("another-failure",)
            if field == "failure"
            else NOW + timedelta(days=1)
            if field == "observation_until"
            else "Changed"
        )
        revision = replace(revision, requirement=replace(revision.requirement, **{key: value}))
    else:
        actions = revision.actions
        if field == "add":
            actions += (replace(actions[0], id=uid("additional")),)
        elif field == "remove":
            actions = actions[:1]
        elif field == "reorder":
            actions = tuple(reversed(actions))
        elif field == "duplicate":
            actions = (actions[0], actions[0])
        else:
            key = {"action_id": "id", "executor": "executor_id"}.get(field, field)
            value = "preventive" if field == "kind" else uid("another-identity")
            actions = (replace(actions[0], **{key: value}), *actions[1:])
        revision = replace(revision, actions=actions)
    original = h.issue(identity)
    reject(
        "INVALID_CAPA_REVISION",
        lambda: h.call("quality.capa.draft", identity, original.revision, revision),
    )
    assert h.issue(identity) == original


def test_unchanged_new_draft_intent_does_not_append_a_revision():
    h, identity, payload = pending()
    original = h.issue(identity)
    reject("NO_CHANGES", lambda: h.call("quality.capa.draft", identity, original.revision, payload))
    assert h.issue(identity) == original


def locked_issue(issue, condition, h):
    conclusion = NamedConclusion(
        text="Actual named decision", actor_id=uid("actor"), sources=(source("root"),), at=NOW
    )
    if condition == "root":
        return replace(issue, root_cause=conclusion)
    if condition == "completion":
        action = issue.capa.actions[0]
        action = replace(action, completion=h.action("corrective"))
        return replace(issue, capa=replace(issue.capa, actions=(action, *issue.capa.actions[1:])))
    if condition in {"effectiveness", "effectiveness_history"}:
        decision = EffectivenessDecision(
            **conclusion.model_dump(),
            result="ineffective",
            evidence_ids=(uid("evidence"),),
            policy={"id": uid("policy"), "revision": 1},
            read_digest="fixed-read-digest",
        )
        capa = replace(
            issue.capa,
            **(
                {"effectiveness": decision}
                if condition == "effectiveness"
                else {"effectiveness_history": (decision,)}
            ),
        )
        return replace(issue, capa=capa)
    if condition == "closure":
        return replace(issue, closure=conclusion)
    if condition == "needs_recheck":
        return replace(issue, needs_recheck=True)
    if condition == "merged":
        return replace(issue, merged_into=uid("target"))
    return replace(issue, status=condition)


@pytest.mark.parametrize(
    "condition",
    [
        "root",
        "completion",
        "effectiveness",
        "effectiveness_history",
        "closure",
        "needs_recheck",
        "merged",
        "open",
        "awaiting_verification",
        "closed",
    ],
)
def test_any_formal_decision_completion_or_terminal_state_freezes_text_draft(condition):
    h, identity, payload = pending()
    issue = locked_issue(h.issue(identity), condition, h)
    assert not capa_draft_text_revisable(issue)
    h.commands.issues[identity] = issue
    with pytest.raises(DomainError):
        h.handler.preview("quality.capa.draft", identity, issue.revision, changed(payload))
    assert h.issue(identity) == issue


def test_initial_capa_creation_keeps_existing_root_cause_contract():
    h = Harness()
    identity = h.create().subject_id
    h.call("quality.issue.triage", identity, 1, IssueTriage(reason="Synthetic"))
    issue = h.issue(identity)
    named = NamedConclusion(
        text="Existing named decision", actor_id=uid("actor"), sources=(source("root"),), at=NOW
    )
    h.commands.issues[identity] = replace(issue, root_cause=named)
    h.call("quality.capa.draft", identity, issue.revision, draft_for(issue))
    assert h.issue(identity).root_cause == named


@pytest.mark.parametrize(
    "drift", ["revision", "authorization", "qualification", "source", "failure"]
)
def test_kernel_revision_cas_and_original_authority_evidence_gates_remain(drift):
    h, identity, payload = pending()
    issue = h.issue(identity)
    expected = issue.revision
    if drift == "revision":
        expected -= 1
    elif drift in {"authorization", "qualification"}:
        key = "authorized" if drift == "authorization" else "qualified"
        h.commands.authority = replace(h.commands.authority, **{key: False})
    elif drift == "source":
        h.evidence.denied.add(payload.hypotheses[0].sources[0])
    else:
        h.runs.denied = True
    with pytest.raises((DomainError, Rejection)):
        h.call("quality.capa.draft", identity, expected, changed(payload))
    assert h.issue(identity) == issue


def test_old_kernel_successful_draft_replay_after_named_root_does_not_rewrite_current():
    h, identity, original_payload = pending()
    original = h.issue(identity)
    h.call(
        "quality.issue.root_cause.decide",
        identity,
        original.revision,
        RootCauseDecide(text="Actual named root", sources=(source("root"),)),
    )
    current = h.issue(identity)
    receipt = h.call("quality.capa.draft", identity, 2, original_payload)
    assert receipt.replayed is True and receipt.revision == original.revision
    assert h.issue(identity) == current and current.root_cause is not None


def test_kernel_transaction_failure_leaves_original_issue_and_delivery_groups():
    h, identity, payload = pending()
    issue = h.issue(identity)
    before = deepcopy(h.commands.__dict__)
    h.commands.fail_at = "after-outbox"
    with pytest.raises(Rejection):
        h.call("quality.capa.draft", identity, issue.revision, changed(payload))
    assert h.issue(identity) == issue
    assert h.commands.receipts == before["receipts"]
    assert h.commands.audit == before["audit"]
    assert h.commands.outbox == before["outbox"]


def test_host_stages_new_immutable_issue_current_history_and_preserves_original_row(host):
    original, payload, _, _ = pending_host(host)
    before = deepcopy(original.issue_snapshot)
    old_basis = deepcopy(original.source_basis)
    preview = call(host, "quality.capa.draft", payload, preview=True)
    assert preview["before"][str(original.issue_id)] == before
    assert preview["after"][str(original.issue_id)]["history"][-1]["at"] is None
    current = call(host, "quality.capa.draft", payload)[0]
    assert current.id != original.id and current.previous_issue_version_id == original.id
    assert current.revision == original.revision + 1
    assert current.source_basis == old_basis
    assert original.issue_snapshot == before
    assert current.owner_id == original.owner_id and current.visibility == original.visibility
    assert current.writer_id == host.ctx.requester_id
    assert current.issue_snapshot["failures"] == before["failures"]
    assert current.issue_snapshot["history"][:-1] == before["history"]
    assert current.issue_snapshot["capa"]["actions"][1] == before["capa"]["actions"][1]
    pointers = [r for r in host.s.rows if isinstance(r, QualityIssueCurrent)]
    assert len(pointers) == 1 and pointers[0].issue_version_id == current.id
    assert pointers[0].issue_revision == current.revision
    assert service._view(host.s, host.ctx, host.product.id, current, current=True).capabilities[
        "quality.capa.draft"
    ]


@pytest.mark.parametrize("timing", ["already_saved", "final_refresh"])
def test_host_blocks_saved_links_before_new_write_and_after_last_owner_io(
    host, monkeypatch, timing
):
    row, payload, _, _ = pending_host(host)
    issue = service._snapshot(row)
    item = link(host, issue)
    if timing == "already_saved":
        host.s.add(item)
    else:
        actual = service._refresh
        calls = 0

        def refresh(*args, **kwargs):
            nonlocal calls
            actual(*args, **kwargs)
            calls += 1
            if calls == 2:
                host.s.add(item)

        monkeypatch.setattr(service, "_refresh", refresh)
    before = len([r for r in host.s.rows if isinstance(r, QualityIssueVersion)])
    reject("INVALID_STATE", lambda: call(host, "quality.capa.draft", payload))
    assert len([r for r in host.s.rows if isinstance(r, QualityIssueVersion)]) == before
    assert (
        service._view(host.s, host.ctx, host.product.id, row, current=True).capabilities[
            "quality.capa.draft"
        ]
        is False
    )


def test_host_link_presence_is_exact_scoped_bounded_and_does_not_skip_private_or_stale_rows(host):
    row, _, _, _ = pending_host(host)
    issue = service._snapshot(row)
    for field in ("tenant_id", "product_id", "project_id", "issue_id", "capa_id"):
        host.s.add(link(host, issue, **{field: uuid4()}))
    assert service._has_capa_link(host.s, host.ctx, host.product.id, issue) is False
    saved = link(host, issue)
    saved.visibility = "private"
    host.s.add(saved)
    assert service._has_capa_link(host.s, host.ctx, host.product.id, issue) is True
    statements = []
    actual = host.s.scalar

    def capture(statement):
        statements.append(statement)
        return actual(statement)

    host.s.scalar = capture
    service._has_capa_link(host.s, host.ctx, host.product.id, issue)
    query = statements[-1]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "LIMIT" in sql and query._limit_clause.value == 1
    assert {where.left.key for where in query._where_criteria} == {
        "tenant_id",
        "product_id",
        "project_id",
        "issue_id",
        "capa_id",
    }
    assert query._for_update_arg is None


def test_host_old_successful_draft_replay_still_checks_current_sources_and_qualification(host):
    row, _, old_payload, old_command = pending_host(host)
    host.s.add(link(host, service._snapshot(row)))
    service.validate(host.s, host.ctx, old_command, host.product, old_payload)
    assert service.replay_subject(host.s, host.ctx, old_command, host.product, old_payload) is row
    host.state["authorized"] = False
    reject(
        "QUALIFICATION_REQUIRED",
        lambda: service.validate(host.s, host.ctx, old_command, host.product, old_payload),
    )
    host.state["authorized"] = True
    host.state["retained_revoked"] = True
    reject(
        "SOURCE_STALE",
        lambda: service.validate(host.s, host.ctx, old_command, host.product, old_payload),
    )


@pytest.mark.parametrize(
    "drift", ["product", "issue", "private", "reads", "qualification", "retained"]
)
def test_host_revision_cas_private_scope_full_readset_and_trust_gates_remain(host, drift):
    row, payload, _, _ = pending_host(host)
    command = actual_command(host, payload)
    expected = "VERSION_CONFLICT"
    if drift == "product":
        command.expected_revision -= 1
    elif drift == "issue":
        pointer = next(r for r in host.s.rows if isinstance(r, QualityIssueCurrent))
        pointer.issue_revision += 1
    elif drift == "private":
        host.ctx = replace_context(host.ctx, uid("peer"))
        expected = "FORBIDDEN_SCOPE"
    elif drift == "reads":
        command.source_read_set = []
        expected = "MISSING_REQUIRED_EVIDENCE"
    elif drift == "qualification":
        host.state["authorized"] = False
        expected = "QUALIFICATION_REQUIRED"
    else:
        host.state["retained_revoked"] = True
        expected = "SOURCE_STALE"
    before = len([r for r in host.s.rows if isinstance(r, QualityIssueVersion)])
    reject(expected, lambda: service.apply(host.s, host.ctx, command, host.product, payload))
    assert len([r for r in host.s.rows if isinstance(r, QualityIssueVersion)]) == before
    assert row.revision == 3


def replace_context(ctx, actor):
    return type(ctx)(ctx.tenant_id, actor, actor)


def test_host_qualification_epoch_changes_during_final_original_refresh_block_append(host):
    row, payload, _, _ = pending_host(host)
    reads = 0
    actual = host.s.engine._pdos_quality_result_refresh

    def refresh(*args, **kwargs):
        nonlocal reads
        value = actual(*args, **kwargs)
        reads += 1
        if reads == 2:
            host.state["epoch"] += 1
        return value

    host.s.engine._pdos_quality_result_refresh = refresh
    reject("SOURCE_STALE", lambda: call(host, "quality.capa.draft", payload))
    assert row.revision == 3
    assert len([r for r in host.s.rows if isinstance(r, QualityIssueVersion)]) == 3
