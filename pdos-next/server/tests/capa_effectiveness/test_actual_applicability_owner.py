"""Writer-shaped saved method/action reads with real no-connect Session/UOW.

Source/byte, professional and paired callbacks are explicit substitutes. These
tests are not actual independent qualification, PG atom enforcement or a live
paired-owner acceptance. No engine connection, flush, commit or DML is allowed.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from capa_effectiveness.test_candidate_write_prepare import origin_fixture
from capa_effectiveness.test_fact_sources_owner import native, project
from capa_effectiveness.test_named_review_owner import payload_for
from capa_effectiveness.test_participants_owner import work as work
from quality_issues.helpers import fixed_run

from pdos_next import capa_applicability_owner as owner
from pdos_next import service as common
from pdos_next.domain.capa_effectiveness import anchor as a
from pdos_next.domain.capa_effectiveness.facts import _action_bindings
from pdos_next.domain.capa_effectiveness.participants_owner import _Read
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_handoff.models import (
    ActualMethodApplicability,
    ActualMethodBatch,
    ActualMethodCurrent,
)
from pdos_next.domain.verification_handoff.schemas import ActualMethodPreparePayload
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Grant, Outbox, Principal, Product, Receipt, RequestKey
from pdos_next.schemas.verification.contracts import (
    NumericCriterion,
    VerificationRequest,
)


def group(work, subject, *, operation, family, actor, revision=1, command_id=None):
    command_id = command_id or uuid4()
    receipt = work.s.seed(
        Receipt,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        operation=operation,
        subject_type=family,
        subject_id=subject,
        subject_revision=revision,
        actor_id=actor,
        requester_id=actor,
        visibility="category",
        command_id=command_id,
        run_id=None,
        request_digest=common.digest("original key material"),
        intent_digest=common.digest("separate common semantic"),
        result={"id": str(subject), "revision": revision, "status": "prepared"},
    )
    key = work.s.seed(
        RequestKey,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        actor_id=actor,
        receipt_id=receipt["id"],
        digest=receipt["request_digest"],
        key="original",
    )
    audit = work.s.seed(
        Audit,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        actor_id=actor,
        operation=operation,
        receipt_id=receipt["id"],
    )
    outbox = work.s.seed(
        Outbox,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        actor_id=actor,
        receipt_id=receipt["id"],
        type=common.EVENTS[operation],
        subject_id=subject,
        subject_revision=revision,
        schema_version=1,
        correlation_id=command_id,
    )
    return receipt, key, audit, outbox


@pytest.fixture
def method_work(work, monkeypatch):
    method_row, _, method, method_read = native(work, content="Actual method")
    criterion_row, _, criterion, criterion_read = native(work, content="Actual criterion")
    project(work)
    run = fixed_run()
    build = run.build.model_copy(
        update={"product_id": work.pid, "project_id": work.scope.project_id}
    )
    item = run.items[0].model_copy(
        update={
            "method": method,
            "criterion": NumericCriterion(lower="9", upper="10", source=criterion),
        }
    )
    sample = run.samples[0].model_copy(update={"build_id": build.id})
    at = datetime.now(UTC) - timedelta(minutes=1)
    request = VerificationRequest(
        id=uuid4(),
        revision=1,
        scope=work.scope,
        build=build,
        title="Fixed exact request",
        purpose="Independent fixed retest",
        items=(item,),
        return_form="Original report",
        samples=(sample,),
        timeline={
            "request_created": {
                "occurred_at": at,
                "received_at": at,
                "original_timezone": "UTC",
                "source": method,
                "actor_id": work.actor,
            }
        },
    )
    refs = [
        dict(artifact_id=str(v.id), expected_revision=1, line=1, quote=text)
        for v, text in ((method, "Actual method"), (criterion, "Actual criterion"))
    ]
    reads = [v.model_dump(mode="json") for v in (method_read, criterion_read)]
    source_basis = {"refs": deepcopy(reads), "security": []}
    authority = {
        "subject_id": str(work.actor),
        "operation": "verification.actual_method.prepare",
        "purpose": request.purpose,
        "scope": work.scope.model_dump(mode="json"),
        "valid_until": None,
        "roles": ["quality"],
        "synthetic": True,
        "fact_refs": [
            dict(
                id=str(uuid4()),
                revision=1,
                kind=kind,
                role="quality",
                state="active",
                nature="synthetic",
                operations=["verification.actual_method.prepare"],
                purposes=[request.purpose],
                valid_from=at.isoformat(),
                valid_until=(at + timedelta(hours=2)).isoformat(),
            )
            for kind in ("duty", "qualification")
        ],
    }
    fact = work.s.seed(
        ProfessionalFact,
        id=UUID_value(authority["fact_refs"][0]["id"]),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        subject_id=work.actor,
        revision=1,
        state="active",
        valid_from=at,
        valid_until=at + timedelta(hours=2),
    )
    work.s.seed(
        ProfessionalFact,
        id=UUID_value(authority["fact_refs"][1]["id"]),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        subject_id=work.actor,
        revision=1,
    )
    payload = ActualMethodPreparePayload(
        request_id=request.id,
        expected_request_revision=1,
        sources=tuple(refs),
        reason="Exact actual configuration applicability",
        assessments=(
            {
                "sample": sample,
                "item_id": item.id,
                "expected_assessment_revision": 0,
                "status": "applicable",
                "conditions": ["Same actual configuration"],
                "reason": "Named actual method decision",
                "sources": tuple(reversed(refs)),
            },
        ),
    )
    semantic = owner.methods.semantic(payload)
    command_id = uuid4()
    batch_id = uuid5(NAMESPACE_URL, f"pdos-verification-handoff:{command_id}:batch")
    child_id = uuid5(
        NAMESPACE_URL, f"pdos-verification-handoff:{command_id}:pair:{sample.id}:{item.id}"
    )
    parent = work.s.seed(
        FormalVerificationRequest,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        request_id=request.id,
        revision=1,
        owner_id=work.actor,
        visibility="category",
        request_snapshot=request.model_dump(mode="json"),
        snapshot_sha256=common.digest(request.model_dump(mode="json")),
        sources=refs,
        required_source_read_set=reads,
    )
    actual_config = {
        "id": str(sample.actual_configuration.id),
        "revision": sample.actual_configuration.revision,
        "observed_at": at.isoformat(),
    }
    snapshot = {
        "scope": work.scope.model_dump(mode="json"),
        "purpose": request.purpose,
        "build": build.model_dump(mode="json"),
        "sample": sample.model_dump(mode="json"),
        "fixed_item": item.model_dump(mode="json"),
        "actual_configuration": actual_config,
        "reviewer_id": str(work.actor),
        "status": "applicable",
        "conditions": ["Same actual configuration"],
        "reason": payload.assessments[0].reason,
        "sources": [v.model_dump(mode="json") for v in payload.assessments[0].sources],
    }
    common_fields = dict(
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        request_id=request.id,
        request_version_id=parent["id"],
        request_revision=1,
        owner_id=work.actor,
        visibility="category",
        sources=refs,
        required_source_read_set=reads,
        source_basis=source_basis,
        authority_snapshot=authority,
        created_at=at,
    )
    batch = work.s.seed(
        ActualMethodBatch,
        **common_fields,
        id=batch_id,
        revision=1,
        status="prepared",
        input_snapshot=semantic,
        snapshot_sha256=common.digest(semantic),
        assessment_ids=[str(child_id)],
        intent_digest=common.digest(
            {
                "operation": "verification.actual_method.prepare",
                "actor": work.actor,
                "payload": semantic,
            }
        ),
    )
    child = work.s.seed(
        ActualMethodApplicability,
        **common_fields,
        id=child_id,
        revision=1,
        batch_id=batch_id,
        sample_id=sample.id,
        sample_revision=sample.revision,
        actual_configuration_id=sample.actual_configuration.id,
        actual_configuration_revision=sample.actual_configuration.revision,
        build_id=build.id,
        item_id=item.id,
        status="applicable",
        method_digest=common.digest(item.model_dump(mode="json")),
        assessment_snapshot=snapshot,
        snapshot_sha256=common.digest(snapshot),
    )
    pointer = work.s.seed(
        ActualMethodCurrent,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        request_id=request.id,
        sample_id=sample.id,
        item_id=item.id,
        assessment_id=child_id,
        assessment_revision=1,
    )
    receipt, key, audit, outbox = group(
        work,
        batch_id,
        operation="verification.actual_method.prepare",
        family="verification_actual_method",
        actor=work.actor,
        command_id=command_id,
    )
    mapping = dict(
        failure_id="fixed failure",
        run={"id": uuid4(), "revision": 4, "kind": "verification_run"},
        sample_id=sample.id,
        sample_revision=sample.revision,
        actual_configuration_id=sample.actual_configuration.id,
        actual_configuration_revision=sample.actual_configuration.revision,
        item_id=item.id,
    )
    selected = owner.commands.PairReviewInput(
        mapping=mapping,
        method=method.model_dump(mode="json"),
        criterion=criterion.model_dump(mode="json"),
        conclusion="applicable",
        reason="Independent actual method conclusion",
        sources=(method.model_dump(mode="json"),),
    )
    raw_pair = SimpleNamespace(
        material=SimpleNamespace(
            request_after=SimpleNamespace(snapshot=request),
            run_after=SimpleNamespace(ref=SimpleNamespace(id=selected.mapping.run.id, revision=4)),
        )
    )
    checked = []
    monkeypatch.setattr(owner.methods, "_basis", lambda *_: (deepcopy(source_basis), False))
    monkeypatch.setattr(
        owner.front,
        "_recheck",
        lambda *_args, **_kwargs: checked.append("current reviewer") or {"current": True},
    )
    monkeypatch.setattr(
        owner.physical,
        "_chain",
        lambda *_args, **_kwargs: {
            "sample": SimpleNamespace(revision=sample.revision, cavity=sample.cavity),
            "build": SimpleNamespace(id=build.id),
            "reads": reads,
            "actual_view": actual_config,
        },
    )
    monkeypatch.setattr(
        owner.physical, "_physical", lambda chain: {"actual_configuration": chain["actual_view"]}
    )
    monkeypatch.setattr(
        owner._Read.__init__.__globals__["evidence"],
        "refs_from_exact",
        lambda _s, _ctx, _pid, values: tuple(
            method if v.artifact_id == method.id else criterion for v in values
        ),
    )
    return SimpleNamespace(
        work=work,
        request=request,
        sample=sample,
        selected=selected,
        pair=raw_pair,
        rule=SimpleNamespace(method=method, criterion=criterion),
        pointer=pointer,
        child=child,
        batch=batch,
        parent=parent,
        receipt=receipt,
        key=key,
        audit=audit,
        outbox=outbox,
        fact=fact,
        sources=(method_row, criterion_row),
        checked=checked,
        source_basis=source_basis,
    )


def UUID_value(value):
    from uuid import UUID

    return UUID(value)


def method_read(value):
    reader = _Read(
        value.work.s,
        value.work.ctx,
        value.work.pid,
        SimpleNamespace(scope=value.work.scope, visibility="category"),
    )
    actual = owner.ActualApplicabilityOwner(None)._method(
        reader, value.selected, value.pair, value.rule
    )
    reader.finish()
    return actual, reader


def test_actual_method_reads_writer_batch_atom_and_preserves_raw_material(method_work):
    actual, reader = method_read(method_work)
    value, raw, bounds, _ = actual
    assert value.conclusion == "applicable" and owner._same_source(
        value.method, method_work.selected.method
    )
    assert raw["actual"] == method_work.child and raw["batch"] == method_work.batch
    assert raw["batch"]["intent_digest"] != method_work.receipt["intent_digest"]
    assert method_work.checked == ["current reviewer"]
    assert bounds == ()
    assert raw["actual"]["authority_snapshot"]["fact_refs"]
    assert {v["table"] for v in reader.rows} >= {
        "verification_actual_method_batches",
        "verification_actual_method_applicabilities",
        "verification_current_actual_methods",
        Receipt.__tablename__,
        Audit.__tablename__,
        Outbox.__tablename__,
        RequestKey.__tablename__,
    }
    assert (
        reader.rows[1]["value"]["assessment_snapshot"]["sources"]
        == method_work.child["assessment_snapshot"]["sources"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing_current",
        "wrong_revision",
        "wrong_sample",
        "wrong_actual",
        "wrong_item",
        "wrong_sha",
        "wrong_batch_sha",
        "wrong_batch_scope",
        "missing_child",
        "wrong_actor",
        "no_receipt",
        "wrong_audit",
        "wrong_outbox",
        "no_original_key",
        "wrong_domain_intent",
        "wrong_id",
        "wrong_criterion",
        "wrong_rule",
        "unknown_status",
        "private_other",
        "changed_parent",
    ],
)
def test_actual_method_rejects_missing_or_mismatched_saved_owner_material(method_work, change):
    v = method_work
    if change == "missing_current":
        v.work.s.rows[ActualMethodCurrent.__tablename__] = []
    elif change == "wrong_revision":
        v.pointer["assessment_revision"] = 2
    elif change == "wrong_sample":
        v.child["sample_revision"] += 1
    elif change == "wrong_actual":
        v.child["actual_configuration_id"] = uuid4()
    elif change == "wrong_item":
        v.child["method_digest"] = "0" * 64
    elif change == "wrong_sha":
        v.child["snapshot_sha256"] = "0" * 64
    elif change == "wrong_batch_sha":
        v.batch["snapshot_sha256"] = "0" * 64
    elif change == "wrong_batch_scope":
        v.batch["request_id"] = uuid4()
    elif change == "missing_child":
        v.batch["assessment_ids"] = []
    elif change == "wrong_actor":
        v.receipt["actor_id"] = uuid4()
    elif change == "no_receipt":
        v.work.s.rows[Receipt.__tablename__] = [
            r for r in v.work.s.rows[Receipt.__tablename__] if r is not v.receipt
        ]
    elif change == "wrong_audit":
        v.audit["operation"] = "verification.method.prepare"
    elif change == "wrong_outbox":
        v.outbox["subject_id"] = uuid4()
    elif change == "no_original_key":
        v.key["digest"] = "0" * 64
    elif change == "wrong_domain_intent":
        v.batch["intent_digest"] = v.receipt["intent_digest"]
    elif change == "wrong_id":
        v.receipt["command_id"] = uuid4()
        v.outbox["correlation_id"] = v.receipt["command_id"]
    elif change == "wrong_criterion":
        v.selected = v.selected.model_copy(update={"criterion": v.selected.method})
    elif change == "wrong_rule":
        v.rule.criterion = v.selected.method
    elif change == "unknown_status":
        v.selected = v.selected.model_copy(update={"conclusion": "unknown"})
    elif change == "private_other":
        v.child.update(visibility="private", owner_id=uuid4())
    elif change == "changed_parent":
        v.parent["snapshot_sha256"] = "0" * 64
    with pytest.raises(DomainError):
        method_read(v)


def test_unknown_actual_method_is_not_promoted_to_applicable(method_work):
    v = method_work
    v.child["status"] = "unknown"
    v.child["assessment_snapshot"]["status"] = "unknown"
    v.child["snapshot_sha256"] = common.digest(v.child["assessment_snapshot"])
    v.batch["input_snapshot"]["assessments"][0]["status"] = "unknown"
    v.batch["snapshot_sha256"] = common.digest(v.batch["input_snapshot"])
    v.batch["intent_digest"] = common.digest(
        {
            "operation": "verification.actual_method.prepare",
            "actor": v.work.actor,
            "payload": v.batch["input_snapshot"],
        }
    )
    v.selected = v.selected.model_copy(update={"conclusion": "unknown"})
    assert method_read(v)[0][0].conclusion == "unknown"


def test_planned_method_record_cannot_replace_missing_actual_current(method_work):
    v = method_work
    v.work.s.rows[ActualMethodCurrent.__tablename__] = []
    v.work.s.rows["verification_method_applicabilities"] = [deepcopy(v.child)]
    with pytest.raises(DomainError):
        method_read(v)


def test_source_and_reviewer_revocation_propagate(method_work, monkeypatch):
    monkeypatch.setattr(owner.front, "_recheck", lambda *_args, **_kwargs: {"current": False})
    with pytest.raises(DomainError) as failure:
        method_read(method_work)
    assert failure.value.code == "SOURCE_STALE"


def test_source_aba_basis_propagates(method_work, monkeypatch):
    monkeypatch.setattr(
        owner.methods,
        "_basis",
        lambda *_: ({**method_work.source_basis, "security": [{"epoch": 3}]}, False),
    )
    with pytest.raises(DomainError) as failure:
        method_read(method_work)
    assert failure.value.code == "SOURCE_STALE"


def test_selected_professional_duty_must_be_effective_for_new_action(method_work):
    v = method_work
    future = datetime.now(UTC) + timedelta(seconds=10)
    v.fact["valid_from"] = future
    v.child["authority_snapshot"]["fact_refs"][0]["valid_from"] = future.isoformat()
    with pytest.raises(DomainError) as error:
        method_read(v)
    assert error.value.reason == "SOURCE_STALE"


def test_missing_live_pair_does_not_authorize_dto(method_work):
    v = method_work
    reader = owner.ActualApplicabilityOwner(None)
    with pytest.raises(DomainError) as failure:
        reader._pair(
            v.work.s,
            v.work.ctx,
            v.work.pid,
            (v.pair, True),
            SimpleNamespace(origin=SimpleNamespace(scope=v.work.scope, purpose=v.request.purpose)),
        )
    assert failure.value.reason == "LIVE_PAIRED_OWNER_REQUIRED"


def test_raw_session_rollback_before_return_is_rejected(method_work):
    v = method_work
    reader = _Read(
        v.work.s, v.work.ctx, v.work.pid, SimpleNamespace(scope=v.work.scope, visibility="category")
    )
    owner.ActualApplicabilityOwner(None)._method(reader, v.selected, v.pair, v.rule)
    v.work.s.rollback()
    with pytest.raises(DomainError):
        reader.finish()


def test_current_changes_after_owner_io_are_not_cached(method_work):
    v = method_work
    reader = _Read(
        v.work.s, v.work.ctx, v.work.pid, SimpleNamespace(scope=v.work.scope, visibility="category")
    )
    owner.ActualApplicabilityOwner(None)._method(reader, v.selected, v.pair, v.rule)
    v.pointer["assessment_revision"] += 1
    with pytest.raises(DomainError) as failure:
        reader.finish()
    assert failure.value.reason == "PARTICIPANT_OWNER_CHANGED"


@pytest.fixture
def action_work(work, monkeypatch):
    saved = origin_fixture()
    origin = saved.origin
    work.pid, work.scope = origin.scope.product_id, origin.scope
    work.ctx = common.Context(origin.scope.tenant_id, work.actor, work.actor)
    work.s.rows.clear()
    work.s.seed(Product, id=work.pid, tenant_id=work.ctx.tenant_id, owner_id=work.actor)
    work.s.seed(Principal, id=work.actor, tenant_id=work.ctx.tenant_id, kind="human", active=True)
    work.s.seed(
        Grant,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        principal_id=work.actor,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    project(work)
    action = origin.issue.capa.actions[0]
    event = action.completion.at
    observed = dict(
        issue_id=str(origin.issue_id),
        capa_id=str(origin.issue.capa.id),
        action_id=str(action.id),
        executor_id=str(action.executor_id),
        purpose=origin.purpose,
        operation="quality.capa.actions.complete",
        occurred_at=event.occurred_at.isoformat(),
        original_timezone=event.original_timezone,
        text=action.completion.text,
    )
    row = work.s.seed(
        QualityIssueVersion,
        id=origin.ref.id,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        issue_id=origin.issue_id,
        revision=origin.ref.revision,
        owner_id=origin.owner_id,
        writer_id=origin.writer_id,
        visibility=origin.visibility,
        operation="quality.capa.actions.complete",
        created_at=origin.created_at,
        issue_snapshot=origin.issue.model_dump(mode="json"),
        snapshot_sha256=origin.ref.snapshot_sha256,
        sources=_dump(origin.sources),
        required_source_read_set=_dump(origin.required_source_read_set),
        source_basis={
            "completion_observations": [
                {"fact": observed, "received_at": origin.created_at.isoformat()}
            ]
        },
    )
    group(
        work,
        row["id"],
        operation=row["operation"],
        family="quality_issue",
        actor=origin.writer_id,
        revision=origin.ref.revision,
    )
    current = work.s.seed(
        QualityIssueCurrent,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        issue_id=origin.issue_id,
        issue_version_id=origin.ref.id,
        issue_revision=origin.ref.revision,
        epoch=1,
    )
    monkeypatch.setattr(
        owner.ActualActionFulfillmentOwner,
        "_completion",
        staticmethod(lambda *_: (owner.CompletionFact.model_validate(observed), [], [])),
    )
    monkeypatch.setattr(
        owner,
        "read_source_closure",
        lambda _s, _ctx, _pid, **kwargs: SimpleNamespace(
            valid_until=None,
            time_constraints=tuple(value for value in kwargs["boundaries"] if value is not None),
            source_basis=_dump(saved.origin_source_basis),
            material_sha256="c" * 64,
        ),
    )
    payload = payload_for(saved)
    return SimpleNamespace(
        work=work,
        anchor=saved,
        selection=payload.action_fulfillment[0],
        row=row,
        action=action,
        binding=_action_bindings(saved)[0],
        rule=SimpleNamespace(valid_until=datetime.now(UTC) + timedelta(hours=1)),
        current=current,
    )


def _dump(values):
    return [v.model_dump(mode="json") for v in values]


def action_read(v, reader=None):
    return (reader or owner.ActualActionFulfillmentOwner()).read(
        v.work.s,
        v.work.ctx,
        v.work.pid,
        v.selection,
        anchor=v.anchor,
        candidate=None,
        rule=v.rule,
        observations=(),
    )


def test_real_completed_action_remains_unknown_without_fulfillment_owner(action_work):
    v = action_work
    # Source selections must be real action evidence, not arbitrary Rule text.
    v.selection = v.selection.model_copy(update={"sources": v.action.completion.evidence})
    result = action_read(v)
    assert result.value.conclusion == "unknown" and result.value.classification == "unknown"
    assert "ACTION_FULFILLMENT_UNDETERMINED" in result.missing
    assert result.owner_material["raw_origin"] == owner._wire(v.row)
    assert result.owner_material["action_runtime"]
    assert v.work.actor != v.action.executor_id  # current reader does not borrow executor context


def test_action_port_replaced_during_final_source_io_is_rejected(action_work, monkeypatch):
    v = action_work
    v.selection = v.selection.model_copy(update={"sources": v.action.completion.evidence})
    reader = owner.ActualActionFulfillmentOwner()
    original, calls = owner.read_source_closure, []

    def source_io(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            reader.implementation_owner = SimpleNamespace(epoch=1, read=lambda: None)
        return result

    monkeypatch.setattr(owner, "read_source_closure", source_io)
    with pytest.raises(DomainError) as error:
        action_read(v, reader)
    assert error.value.reason == "SOURCE_STALE"


def test_expiry_during_final_action_material_construction_is_rejected(action_work, monkeypatch):
    v = action_work
    v.selection = v.selection.model_copy(update={"sources": v.action.completion.evidence})
    at = datetime.now(UTC)

    def expire_at_construction(*args, **kwargs):
        return at - timedelta(seconds=2), (at - timedelta(seconds=1),)

    monkeypatch.setattr(owner, "_deadline", expire_at_construction)
    with pytest.raises(DomainError) as error:
        action_read(v)
    assert error.value.reason == "SOURCE_STALE"


@pytest.mark.parametrize(
    "change",
    [
        "missing_observed",
        "wrong_executor",
        "wrong_clock",
        "duplicate",
        "changed_snapshot",
        "wrong_source",
    ],
)
def test_action_completion_exact_saved_event_is_required(action_work, change):
    v = action_work
    v.selection = v.selection.model_copy(update={"sources": v.action.completion.evidence})
    record = v.row["source_basis"]["completion_observations"][0]
    if change == "missing_observed":
        v.row["source_basis"]["completion_observations"] = []
    elif change == "wrong_executor":
        record["fact"]["executor_id"] = str(uuid4())
    elif change == "wrong_clock":
        record["fact"]["occurred_at"] = (
            v.action.completion.at.occurred_at + timedelta(minutes=1)
        ).isoformat()
    elif change == "duplicate":
        v.row["source_basis"]["completion_observations"].append(deepcopy(record))
    elif change == "changed_snapshot":
        v.row["snapshot_sha256"] = "0" * 64
    elif change == "wrong_source":
        v.selection = v.selection.model_copy(update={"sources": (v.anchor.origin_sources[0],)})
    with pytest.raises(DomainError):
        action_read(v)


def test_completion_true_does_not_prove_fulfillment(action_work):
    v = action_work
    v.selection = v.selection.model_copy(
        update={"conclusion": "applicable", "sources": v.action.completion.evidence}
    )
    with pytest.raises(DomainError) as failure:
        action_read(v)
    assert failure.value.reason == "ACTION_FULFILLMENT_OWNER_REQUIRED"


def test_fulfillment_attestation_does_not_accept_boolean_or_other_caller(action_work):
    v = action_work
    v.selection = v.selection.model_copy(
        update={"conclusion": "applicable", "sources": v.action.completion.evidence}
    )
    kwargs = dict(
        session=v.work.s,
        caller=v.work.ctx,
        product_id=v.work.pid,
        anchor_sha256=v.anchor.anchor_sha256,
        action=v.binding,
        classification="investigation",
        conclusion="applicable",
        owner_refs=v.action.completion.evidence,
        owner_material={"actual owner provenance": "test substitute"},
        reads=v.anchor.origin_required_source_read_set,
        checked_at=datetime.now(UTC),
        valid_until=v.rule.valid_until,
    )
    actual = owner.ActualActionAttestation(**kwargs)
    for proof in (
        True,
        replace(actual, caller=common.Context(v.work.ctx.tenant_id, uuid4(), uuid4())),
    ):
        with pytest.raises(DomainError):
            owner.ActualActionFulfillmentOwner._check(
                v.work.s, v.work.ctx, v.work.pid, v.anchor, v.binding, v.selection, proof
            )


def test_action_refresh_reads_original_group_again(action_work):
    v = action_work
    v.selection = v.selection.model_copy(update={"sources": v.action.completion.evidence})
    reader = owner.ActualActionFulfillmentOwner()
    previous = action_read(v, reader)
    v.row["source_basis"]["completion_observations"][0]["fact"]["text"] = "changed"
    with pytest.raises(DomainError):
        reader.refresh(
            v.work.s,
            v.work.ctx,
            v.work.pid,
            v.selection,
            previous,
            anchor=v.anchor,
            candidate=None,
            rule=v.rule,
            observations=(),
        )


def test_source_union_over_20_is_complete():
    selected = tuple(a.SourceRead(artifact_id=uuid4(), expected_revision=1) for _ in range(21))
    assert set(a.canonical_reads(selected)) == set(selected)
