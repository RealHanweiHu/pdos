"""Explicit synthetic ports only. No DB, bytes, HTTP or professional grant proof."""

import json
from copy import deepcopy
from datetime import timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from quality_issues.helpers import NOW, fixed_run, source, uid

from pdos_next.domain.quality_execution.ports import FixedQualityResult
from pdos_next.domain.quality_followup import service
from pdos_next.domain.quality_followup.adapters import TransactionCommands, kernel
from pdos_next.domain.quality_followup.evidence import verify_completion_line
from pdos_next.domain.quality_followup.ports import Runtime
from pdos_next.domain.quality_followup.schemas import (
    ActionsCompletePayload,
    Completion,
    CompletionAssessment,
    RootCausePayload,
)
from pdos_next.domain.quality_issues.ports import Authority, Invocation, VerifiedRun
from pdos_next.domain.quality_issues.rules import failure_ref, replace, semantic_digest
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import (
    Capa,
    CapaAction,
    EffectivenessRequirement,
    Hypothesis,
    Issue,
)
from pdos_next.service import Context, digest


def issue():
    verified = VerifiedRun(run=fixed_run(), nature="synthetic")
    failure = failure_ref(verified, verified.run.measurements[0].id)
    return Issue(
        id=uid("issue"),
        revision=4,
        scope=verified.run.scope,
        audience=(f"private:{uid('executor')}",),
        title="Synthetic original failure",
        status="actioning",
        risk="high",
        failures=(failure,),
        capa=Capa(
            id=uid("capa"),
            hypotheses=(Hypothesis(text="Original hypothesis", sources=(source("hypothesis"),)),),
            actions=tuple(
                CapaAction(
                    id=uid(name),
                    kind="corrective",
                    text="Investigate dimension",
                    executor_id=uid("executor"),
                )
                for name in ("first", "second")
            ),
            requirement=EffectivenessRequirement(
                method="New owner Run",
                acceptance="All original failures covered",
                observation_until=NOW + timedelta(days=1),
                required_failure_ids=(failure.identity,),
            ),
        ),
    )


def completion(name="first"):
    return Completion(
        id=uid(name),
        text="Personally investigated dimension",
        executor_id=uid("executor"),
        evidence=(source("event").model_dump(),),
        at={
            "occurred_at": NOW - timedelta(minutes=1, microseconds=123456),
            "original_timezone": "America/Los_Angeles",
            "source": source("event").model_dump(),
        },
    )


def line(value=None):
    c = value or completion()
    return {
        "issue_id": str(uid("issue")),
        "capa_id": str(uid("capa")),
        "action_id": str(c.id),
        "executor_id": str(c.executor_id),
        "operation": service.COMPLETE,
        "occurred_at": c.at.occurred_at.isoformat(),
        "original_timezone": c.at.original_timezone,
        "purpose": "investigation",
        "text": c.text,
    }


def code(expected, callback):
    with pytest.raises(DomainError) as error:
        callback()
    assert error.value.reason == expected


@pytest.mark.parametrize("time", ["Z", "offset"])
def test_completion_observed_time_matches_instant_and_preserves_microseconds(time):
    c = completion()
    raw = line(c)
    raw["occurred_at"] = (
        c.at.occurred_at.isoformat().replace("+00:00", "Z")
        if time == "Z"
        else c.at.occurred_at.astimezone(timezone(timedelta(hours=-7))).isoformat()
    )
    fact = verify_completion_line(
        json.dumps(raw), issue(), "investigation", c, uid("executor"), NOW
    )
    assert fact.occurred_at == c.at.occurred_at
    assert fact.occurred_at.microsecond == 876544


@pytest.mark.parametrize(
    "field,value",
    [
        ("issue_id", str(uid("other-issue"))),
        ("capa_id", str(uid("other-capa"))),
        ("action_id", str(uid("other-action"))),
        ("executor_id", str(uid("other-person"))),
        ("operation", service.ROOT_CAUSE),
        ("purpose", "other-purpose"),
        ("text", "Different completion statement"),
        ("original_timezone", "UTC"),
        ("occurred_at", (NOW - timedelta(hours=1)).isoformat()),
        ("occurred_at", "2026-10-02T17:59:00"),
        ("occurred_at", 1790963940),
        ("original_timezone", "invalid-zone"),
    ],
)
def test_completion_wrong_exact_field_or_naive_clock_is_not_observed_fact(field, value):
    raw = line()
    raw[field] = value
    code(
        "MISSING_REQUIRED_EVIDENCE",
        lambda: verify_completion_line(
            json.dumps(raw), issue(), "investigation", completion(), uid("executor"), NOW
        ),
    )


@pytest.mark.parametrize(
    "raw",
    [
        lambda: json.dumps(line())[:-1] + ',"purpose":"investigation"}',
        lambda: json.dumps({**line(), "received_at": NOW.isoformat()}),
        lambda: json.dumps({k: v for k, v in line().items() if k != "text"}),
        lambda: "[]",
        lambda: json.dumps(line())[:-1] + ',"unknown":NaN}',
    ],
)
def test_duplicate_keys_extra_server_fields_missing_values_and_nonfinite_json_rejected(raw):
    code(
        "MISSING_REQUIRED_EVIDENCE",
        lambda: verify_completion_line(
            raw(), issue(), "investigation", completion(), uid("executor"), NOW
        ),
    )


def test_unknown_action_other_executor_and_future_completion_are_blocked():
    c = completion("unknown")
    code(
        "NAMED_EXECUTOR_REQUIRED",
        lambda: verify_completion_line(
            json.dumps(line(c)), issue(), "investigation", c, uid("executor"), NOW
        ),
    )
    code(
        "NAMED_EXECUTOR_REQUIRED",
        lambda: verify_completion_line(
            json.dumps(line()), issue(), "investigation", completion(), uid("delegate"), NOW
        ),
    )
    future = replace(
        completion(), at=replace(completion().at, occurred_at=NOW + timedelta(seconds=1))
    )
    code(
        "INVALID_EVENT_TIME",
        lambda: verify_completion_line(
            json.dumps(line(future)), issue(), "investigation", future, uid("executor"), NOW
        ),
    )


@pytest.mark.parametrize(
    "cls,field",
    [(RootCausePayload, "confirmation_token"), (ActionsCompletePayload, "approval_token")],
)
def test_wrappers_forbid_other_tier_and_server_identity(cls, field):
    data = {
        "issue_id": uid("issue"),
        "expected_issue_revision": 4,
        **(
            {"text": "Named root", "sources": [source("root").model_dump()]}
            if cls is RootCausePayload
            else {"completions": [completion().model_dump()]}
        ),
    }
    for extra in (
        {field: "x" * 32},
        {"decision_id": uuid4()},
        {"actor_id": uid("delegate")},
        {"expected_issue_revision": True},
    ):
        with pytest.raises(ValidationError):
            cls.model_validate({**data, **extra})


def test_completions_cannot_repeat_or_add_future_effective_clock():
    with pytest.raises(ValidationError):
        ActionsCompletePayload(
            issue_id=uid("issue"),
            expected_issue_revision=4,
            completions=(completion(), completion()),
        )
    raw = completion().model_dump()
    raw["at"]["effective_at"] = NOW + timedelta(hours=1)
    with pytest.raises(ValidationError):
        Completion.model_validate(raw)


def adapters(before, payload, *, operation, proof_id=None, actor_kind="human", roles=("quality",)):
    authority = Authority(
        scope=before.scope,
        actor_id=uid("executor"),
        actor_kind=actor_kind,
        roles=roles,
        audience=before.audience,
        authorized=True,
        qualified=True,
        cancelled=False,
        now=NOW,
    )
    domain = service._domain(payload)
    inv = Invocation(
        command_id=uuid4(),
        operation=operation,
        subject_id=before.id,
        expected_revision=before.revision,
        semantic_digest=semantic_digest(domain),
        decision_id=proof_id
        if operation == service.ROOT_CAUSE and isinstance(proof_id, UUID)
        else None,
    )
    written = []

    def record(mutation):
        written.append(mutation)
        i = mutation.changes[0]
        return SimpleNamespace(issue_id=i.id, revision=i.revision, status=i.status)

    commands = TransactionCommands(authority, inv, before, record, proof_id)
    v = SimpleNamespace(
        scope=before.scope,
        verified=VerifiedRun(run=fixed_run(), nature="synthetic"),
        run_revision=1,
        measurement_id=before.failures[0].measurement_id,
        current=True,
        reasons=(),
    )
    handler = kernel(
        commands,
        (v,),
        lambda *args: None,
        {"id": uid("policy"), "revision": 1, "risk": "high", "independent_verification": True},
    )
    return handler, inv, domain, written


def root_payload():
    return RootCausePayload(
        issue_id=uid("issue"),
        expected_issue_revision=4,
        text="Named professional root conclusion",
        sources=(source("root").model_dump(),),
    )


@pytest.mark.parametrize("proof", [None, True, "accepted"])
def test_t2_never_substitutes_accepted_boolean_for_actual_shared_proof(proof):
    h, inv, data, written = adapters(
        issue(), root_payload(), operation=service.ROOT_CAUSE, proof_id=proof
    )
    code("CONFIRMATION_REQUIRED", lambda: h.execute(inv, data))
    assert written == []


def test_actual_t2_proof_is_invocation_decision_id_and_original_hypotheses_survive():
    proof = uuid4()
    before = issue()
    h, inv, data, written = adapters(
        before, root_payload(), operation=service.ROOT_CAUSE, proof_id=proof
    )
    h.execute(inv, data)
    assert inv.decision_id == proof
    after = written[0].changes[0]
    assert after.root_cause.actor_id == uid("executor")
    assert after.root_cause.at == NOW
    assert after.capa.hypotheses == before.capa.hypotheses


@pytest.mark.parametrize(
    "kind,roles,expected",
    [
        ("ai", ("quality",), "NAMED_DECISION_REQUIRED"),
        ("human", ("engineering",), "FORBIDDEN_OPERATION"),
    ],
)
def test_t2_rejects_ai_and_nonquality(kind, roles, expected):
    h, inv, data, written = adapters(
        issue(),
        root_payload(),
        operation=service.ROOT_CAUSE,
        proof_id=uuid4(),
        actor_kind=kind,
        roles=roles,
    )
    code(expected, lambda: h.execute(inv, data))
    assert not written


def test_partial_and_all_completion_follow_old_kernel_states_without_effectiveness():
    before = issue()
    payload = ActionsCompletePayload(
        issue_id=before.id, expected_issue_revision=before.revision, completions=(completion(),)
    )
    h, inv, data, written = adapters(before, payload, operation=service.COMPLETE, proof_id=uuid4())
    h.execute(inv, data)
    partial = written[0].changes[0]
    assert partial.status == "actioning" and partial.capa.actions[1].completion is None
    nextpayload = ActionsCompletePayload(
        issue_id=before.id,
        expected_issue_revision=partial.revision,
        completions=(completion("second"),),
    )
    h, inv, data, written = adapters(
        partial, nextpayload, operation=service.COMPLETE, proof_id=uuid4()
    )
    h.execute(inv, data)
    complete = written[0].changes[0]
    assert complete.status == "awaiting_verification"
    assert complete.capa.effectiveness is None and complete.closure is None
    # Kernel intentionally disallows a later first root cause after all completion.
    late = root_payload().model_copy(update={"expected_issue_revision": complete.revision})
    h, inv, data, written = adapters(complete, late, operation=service.ROOT_CAUSE, proof_id=uuid4())
    code("INVALID_STATE", lambda: h.execute(inv, data))


def test_preview_clock_only_normalizes_new_server_times_and_preserves_observed_microseconds():
    before = issue()
    h, inv, data, _ = adapters(before, root_payload(), operation=service.ROOT_CAUSE)
    _, mutation = h._prepare(h.ports.commands.authority, inv, data)
    preview = service._preview_issue(mutation.changes[0], before)
    assert preview["root_cause"]["at"] is None
    assert preview["history"][-1]["at"] is None
    p = ActionsCompletePayload(
        issue_id=before.id, expected_issue_revision=before.revision, completions=(completion(),)
    )
    h, inv, data, _ = adapters(before, p, operation=service.COMPLETE)
    _, mutation = h._prepare(h.ports.commands.authority, inv, data)
    preview = service._preview_issue(mutation.changes[0], before)
    assert (
        preview["capa"]["actions"][0]["completion"]["at"]["occurred_at"]
        == completion().model_dump(mode="json")["at"]["occurred_at"]
    )


def assessment_context():
    before = issue()
    c = completion()
    basis = SimpleNamespace(
        scope=before.scope,
        purpose="investigation",
        nature="synthetic",
        basis_sha256=digest("basis"),
        actions=(SimpleNamespace(action_id=c.id, action_sha256=digest("action")),),
    )
    published = {"facts_revision": digest("policy")}
    raw = dict(
        scope=before.scope.model_dump(mode="json"),
        issue_id=before.id,
        capa_id=before.capa.id,
        action_id=c.id,
        executor_id=c.executor_id,
        purpose="investigation",
        basis_sha256=basis.basis_sha256,
        action_sha256=basis.actions[0].action_sha256,
        completion_sha256=digest(c.model_dump(mode="json")),
        event_source=c.at.source.model_dump(),
        policy_basis_sha256=digest(published),
        allowed=True,
        current=True,
        classification="investigation",
        nature="synthetic",
        sources=[source("policy").model_dump()],
        owner_proofs=[],
        required_source_read_set=[{"artifact_id": uid("policy"), "expected_revision": 1}],
        valid_until=NOW + timedelta(hours=1),
        reason_codes=[],
    )
    value = CompletionAssessment.model_validate({**raw, "proof_sha256": "0" * 64})
    value = value.model_copy(
        update={"proof_sha256": digest(value.model_dump(mode="json", exclude={"proof_sha256"}))}
    )
    return before, c, basis, published, value


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"allowed": False}, "ACTION_COMPLETION_UNVERIFIED"),
        ({"current": False}, "ACTION_COMPLETION_UNVERIFIED"),
        ({"classification": "unknown"}, "ACTION_COMPLETION_UNVERIFIED"),
        ({"classification": "formal_change"}, "ACTION_COMPLETION_UNVERIFIED"),
        ({"valid_until": NOW}, "ACTION_COMPLETION_UNVERIFIED"),
        ({"action_sha256": digest("other-action")}, "INTEGRITY_MISMATCH"),
        ({"nature": "real"}, "INTEGRITY_MISMATCH"),
        ({"completion_sha256": digest("other-fact")}, "INTEGRITY_MISMATCH"),
    ],
)
def test_host_assessment_cannot_promote_unknown_or_formal_draft_or_unbound_positive(
    monkeypatch, change, expected
):
    before, c, basis, published, value = assessment_context()
    value = value.model_copy(update=change)
    value = value.model_copy(
        update={"proof_sha256": digest(value.model_dump(mode="json", exclude={"proof_sha256"}))}
    )
    monkeypatch.setattr(service, "now", lambda: NOW)
    runtime = Runtime(lambda: None, lambda: uuid4(), lambda *a, **kw: value)
    code(
        expected,
        lambda: service._assessment(
            None,
            SimpleNamespace(requester_id=c.executor_id),
            before.scope.product_id,
            runtime,
            basis,
            published,
            before,
            c,
            None,
            write=True,
        ),
    )


def test_missing_callback_fails_closed_and_no_default_runtime(monkeypatch):
    before, c, basis, published, _ = assessment_context()
    runtime = Runtime(lambda: None, lambda: uuid4())
    code(
        "INTEGRATION_REQUIRED",
        lambda: service._assessment(
            None,
            SimpleNamespace(requester_id=c.executor_id),
            before.scope.product_id,
            runtime,
            basis,
            published,
            before,
            c,
            None,
            write=True,
        ),
    )
    code(
        "INTEGRATION_REQUIRED",
        lambda: service._runtime(SimpleNamespace(get_bind=lambda: SimpleNamespace())),
    )


def test_semantic_removes_only_proof_fields_and_canonicalizes_completion_order():
    p = ActionsCompletePayload(
        issue_id=uid("issue"),
        expected_issue_revision=4,
        completions=(completion("second"), completion()),
        confirmation_token="x" * 32,
    )
    other = ActionsCompletePayload(
        issue_id=p.issue_id,
        expected_issue_revision=4,
        completions=tuple(reversed(p.completions)),
        confirmation_token="y" * 32,
    )
    assert service.semantic(p) == service.semantic(other)
    assert "confirmation_token" not in service.semantic(p)
    changed = other.model_copy(update={"expected_issue_revision": 5})
    assert service.semantic(changed) != service.semantic(p)


def test_preview_facade_never_calls_real_proof_or_append(monkeypatch):
    before = issue()
    calls = []
    runtime = Runtime(lambda *a, **k: calls.append("append"), lambda *a, **k: calls.append("proof"))
    payload = root_payload()
    domain = service._domain(payload)
    bound = SimpleNamespace(
        issue=before,
        runtime=runtime,
        authority={"roles": ["quality"]},
        purpose="investigation",
        policy={
            "id": uid("policy"),
            "revision": 1,
            "risk": "high",
            "independent_verification": True,
        },
        source_basis={},
        reads=[],
        observations=(),
        assessments=(),
        domain_payload=domain,
        invocation=Invocation(
            command_id=uuid4(),
            operation=service.ROOT_CAUSE,
            subject_id=before.id,
            expected_revision=before.revision,
            semantic_digest=semantic_digest(domain),
        ),
        results=(
            SimpleNamespace(
                scope=before.scope,
                verified=VerifiedRun(run=fixed_run(), nature="synthetic"),
                run_revision=1,
                measurement_id=before.failures[0].measurement_id,
                sources=(),
                current=True,
                reasons=(),
            ),
        ),
    )
    monkeypatch.setattr(service, "now", lambda: NOW)
    monkeypatch.setattr(service, "check_source", lambda *a: None)
    monkeypatch.setattr(service, "_load", lambda *a, **k: bound)
    monkeypatch.setattr(service, "_new_write", lambda *a: None)
    ctx = Context(before.scope.tenant_id, uid("executor"), uid("executor"))
    command = SimpleNamespace(operation=service.ROOT_CAUSE)
    result = service.preview_view(
        None, ctx, command, SimpleNamespace(id=before.scope.product_id), payload
    )
    assert calls == [] and result["after"][str(before.id)]["root_cause"]["at"] is None
    assert "proof_id" not in result
    first = deepcopy(result)
    monkeypatch.setattr(service, "now", lambda: NOW + timedelta(minutes=3))
    later = service.preview_view(
        None, ctx, command, SimpleNamespace(id=before.scope.product_id), payload
    )
    assert first == later


def fixed_result():
    run = fixed_run()
    return FixedQualityResult(
        scope=run.scope,
        purpose="investigation",
        event_id=None,
        run_version_id=uid("original-run-version"),
        run_revision=run.revision,
        measurement_id=run.measurements[0].id,
        projection_id=uid("projection"),
        projection_revision=1,
        basis_sha256=digest("projection-basis"),
        rules_version="synthetic-test-only-v1",
        rules_sha256=digest("rules"),
        verified=VerifiedRun(run=run, nature="synthetic"),
        visibility="private",
        owner_id=uid("executor"),
        sources=(),
        required_source_read_set=[{"artifact_id": uid("report"), "expected_revision": 1}],
        source_basis={"runtime_epoch": 1},
        retained={"current": True, "epoch": 1},
        current=True,
    )


@pytest.fixture
def host(monkeypatch):
    before = issue()
    state = {"revoked": False, "proofs": 0, "appends": 0}
    product = SimpleNamespace(id=before.scope.product_id, revision=1)
    ctx = Context(before.scope.tenant_id, uid("executor"), uid("executor"))
    engine = SimpleNamespace()
    session = SimpleNamespace(get_bind=lambda: engine)
    proof = uuid4()

    def proof_reader(*a, **kw):
        state["proofs"] += 1
        return proof

    def append(s, context, p, old, mutation, **kwargs):
        state["appends"] += 1
        assert kwargs["source_basis"]["shared_proof"]["id"] == str(proof)
        nextissue = mutation.changes[0]
        row = SimpleNamespace(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=p.id,
            issue_id=nextissue.id,
            revision=nextissue.revision,
            status=nextissue.status,
            issue_snapshot=nextissue.model_dump(mode="json"),
        )
        state["saved"] = (row, kwargs)
        return row

    service.configure_followup(engine, append_issue=append, consumed_proof=proof_reader)
    original = fixed_result()
    engine._pdos_quality_result_refresh = lambda *a, **k: original.model_copy(
        update={"current": not state["revoked"]}
    )
    authority = {
        "roles": ["quality"],
        "authorized": True,
        "qualified": True,
        "valid_until": None,
        "operation": service.ROOT_CAUSE,
        "purpose": "investigation",
        "synthetic": True,
        "fact_refs": [
            {
                "kind": kind,
                "role": "quality",
                "nature": "synthetic",
                "state": "active",
                "operations": [service.ROOT_CAUSE],
                "purposes": ["investigation"],
                "valid_from": (NOW - timedelta(hours=1)).isoformat(),
                "valid_until": (NOW + timedelta(hours=1)).isoformat(),
            }
            for kind in ("duty", "qualification")
        ],
        "facts_revision": digest("authority"),
    }
    published = {
        "id": uid("policy"),
        "revision": 1,
        "risk": "high",
        "independent_verification": True,
        "valid_until": None,
        "source_basis": [
            {
                "id": uid("policy"),
                "revision": 1,
                "state": "active",
                "valid_from": (NOW - timedelta(hours=1)).isoformat(),
                "valid_until": (NOW + timedelta(hours=1)).isoformat(),
            }
        ],
    }
    payload = root_payload()
    domain = service._domain(payload)
    row = SimpleNamespace(
        id=uid("issue-version-4"),
        issue_id=before.id,
        revision=4,
        visibility="private",
        issue_snapshot=before.model_dump(mode="json"),
    )
    bound = service.Bound(
        row=row,
        issue=before,
        purpose="investigation",
        runtime=engine._pdos_quality_followup,
        authority=authority,
        policy=published,
        results=(original,),
        basis=None,
        observations=(),
        assessments=(),
        sources=(),
        reads=[],
        source_basis={"artifact_sources": []},
        domain_payload=domain,
        payload=payload,
        write=True,
        invocation=Invocation(
            command_id=uuid4(),
            operation=service.ROOT_CAUSE,
            subject_id=before.id,
            expected_revision=4,
            semantic_digest=semantic_digest(domain),
        ),
    )
    monkeypatch.setattr(service, "now", lambda: NOW)
    monkeypatch.setattr(service, "_human", lambda *a, **k: product)
    monkeypatch.setattr(service, "source_basis", lambda *a: ([], False))
    monkeypatch.setattr(service.policy, "assess", lambda *a, **k: published)
    monkeypatch.setattr(service.professional, "assess", lambda *a, **k: authority)
    monkeypatch.setattr(service, "check_source", lambda *a: None)
    monkeypatch.setattr(service, "_load", lambda *a, **k: bound)
    monkeypatch.setattr(service, "_new_write", lambda *a: None)
    command = SimpleNamespace(
        operation=service.ROOT_CAUSE, product_id=product.id, command_id=uuid4()
    )
    return SimpleNamespace(
        s=session,
        ctx=ctx,
        product=product,
        command=command,
        payload=payload,
        bound=bound,
        state=state,
        proof=proof,
    )


def test_apply_actual_proof_binds_new_version_and_host_alone_owns_append(host):
    row, subject, visibility = service.apply(
        host.s, host.ctx, host.command, host.product, host.payload
    )
    assert subject == "quality_issue" and visibility == "private" and row.revision == 5
    assert host.state["appends"] == 1 and host.state["proofs"] == 2
    assert host.bound.row.issue_snapshot["root_cause"] is None
    assert host.state["saved"][1]["input_snapshot"] == service.semantic(host.payload)


def test_source_io_revoke_prior_result_cannot_reach_append(host, monkeypatch):
    def after_source(*args):
        host.state["revoked"] = True
        return [], False

    monkeypatch.setattr(service, "source_basis", after_source)
    code(
        "SOURCE_STALE",
        lambda: service.apply(host.s, host.ctx, host.command, host.product, host.payload),
    )
    assert host.state["appends"] == 0


def test_completion_owner_callback_revokes_prior_result_then_terminal_refresh_rejects(
    host, monkeypatch
):
    before, c, basis, published, value = assessment_context()
    host.bound.payload = ActionsCompletePayload(
        issue_id=before.id, expected_issue_revision=4, completions=(c,)
    )
    host.bound.observations = (None,)
    host.bound.assessments = (value,)
    host.bound.basis = basis

    def assessment(*a, **k):
        host.state["revoked"] = True
        return value

    monkeypatch.setattr(service, "_assessment", assessment)
    code(
        "SOURCE_STALE",
        lambda: service._refresh(host.s, host.ctx, host.product.id, service.COMPLETE, host.bound),
    )
    assert host.state["appends"] == 0


@pytest.mark.parametrize("change", ["authority", "policy", "runtime", "deadline"])
def test_terminal_current_authority_policy_configuration_and_expiry_are_hard_guards(
    host, monkeypatch, change
):
    if change == "authority":
        monkeypatch.setattr(
            service.professional,
            "assess",
            lambda *a, **k: {**host.bound.authority, "facts_revision": digest("ABA")},
        )
    elif change == "policy":
        monkeypatch.setattr(
            service.policy, "assess", lambda *a, **k: {**host.bound.policy, "revision": 2}
        )
    elif change == "runtime":
        host.s.get_bind()._pdos_quality_followup = Runtime(lambda: None, lambda: uuid4())
    else:
        monkeypatch.setattr(service, "now", lambda: NOW + timedelta(hours=2))
    code(
        "SOURCE_STALE",
        lambda: service._refresh(host.s, host.ctx, host.product.id, service.ROOT_CAUSE, host.bound),
    )
    assert host.state["appends"] == 0


def test_actual_proof_is_rechecked_after_final_source_io_without_second_consumption(host):
    runtime = Runtime(
        host.bound.runtime.append_issue,
        lambda *a, **k: host.proof if host.state["proofs"] == 0 else uuid4(),
    )

    # The fixture callback below changes only proof identity, not any actual
    # Confirmation. This proves append is impossible on a mismatched late proof.
    def proof(*a, **k):
        host.state["proofs"] += 1
        return host.proof if host.state["proofs"] == 1 else uuid4()

    runtime = Runtime(runtime.append_issue, proof)
    host.s.get_bind()._pdos_quality_followup = runtime
    host.bound.runtime = runtime
    code(
        "SOURCE_STALE",
        lambda: service.apply(host.s, host.ctx, host.command, host.product, host.payload),
    )
    assert host.state["appends"] == 0


def test_completion_gate_samples_final_clock_after_reading_actual_source(monkeypatch):
    from pdos_next.domain.quality_followup import evidence

    raw = completion().model_dump()
    raw["at"]["occurred_at"] = NOW + timedelta(seconds=1)
    raw["at"]["source"] = source("event", position="line:1;quote_sha256:" + "0" * 64).model_dump()
    c = Completion.model_validate(raw)
    clock = [NOW]

    def checked(*a):
        clock[0] = NOW + timedelta(seconds=2)
        return [], [], False

    monkeypatch.setattr(evidence, "check_source", checked)
    monkeypatch.setattr(
        evidence, "source_for", lambda *a: SimpleNamespace(content=json.dumps(line(c)))
    )
    fact, *_ = evidence.completion_observation(
        None,
        SimpleNamespace(requester_id=uid("executor")),
        uid("product"),
        issue(),
        "investigation",
        c,
        lambda: clock[0],
    )
    assert fact.occurred_at == NOW + timedelta(seconds=1)


def test_historical_row_never_deep_assesses_or_grants_new_capabilities(monkeypatch):
    before = issue()
    row = SimpleNamespace(
        id=uid("historical-version"),
        tenant_id=before.scope.tenant_id,
        product_id=before.scope.product_id,
        project_id=before.scope.project_id,
        issue_id=before.id,
        revision=before.revision,
        status=before.status,
        owner_id=uid("executor"),
        visibility="private",
        purpose="investigation",
        issue_snapshot=before.model_dump(mode="json"),
        snapshot_sha256=digest(before.model_dump(mode="json")),
        sources=[],
        required_source_read_set=[
            {"artifact_id": str(uid("historical-source")), "expected_revision": 1}
        ],
        source_basis={"artifact_sources": [{"id": "fixed"}]},
        created_at=NOW,
        reason="Saved history",
    )
    monkeypatch.setattr(service, "source_basis", lambda *a: ([{"id": "fixed"}], False))
    monkeypatch.setattr(
        service, "_result", lambda *a, **k: pytest.fail("Historical proof not requested")
    )
    monkeypatch.setattr(
        service.professional, "assess", lambda *a, **k: pytest.fail("Historical cap not requested")
    )
    s = SimpleNamespace(get_bind=lambda: SimpleNamespace())
    view = service._read_row(
        s, SimpleNamespace(requester_id=uid("executor")), uid("product"), row, current=False
    )
    assert view["source_status"] == "not_evaluated_historical"
    assert all(value is False for value in view["capabilities"].values())
    assert all(
        a["can_complete"] is False and a["can_prepare_completion"] is False for a in view["actions"]
    )
