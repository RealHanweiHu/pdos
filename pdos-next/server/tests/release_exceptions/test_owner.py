"""Actual exception reader with explicit lowest-level row/authority IO fixtures.

No connection or business authority is established here. The real retained-row,
reference, policy, scope, expiry and direct-current reader branches run unchanged.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from pdos_next.domain.release import rules as release
from pdos_next.domain.release_exceptions import owner
from pdos_next.domain.release_exceptions.constants import DECIDE
from pdos_next.domain.release_exceptions.models import (
    ReleaseExceptionCurrent,
    ReleaseExceptionDecision,
)
from pdos_next.errors import DomainError
from pdos_next.models import Receipt

from .test_rules import case as rule_case  # noqa: F401
from .test_rules import release_case  # noqa: F401


@pytest.fixture
def work(request, monkeypatch):
    case = request.getfixturevalue("rule_case")
    engine = create_engine("postgresql+psycopg://unused/never_connect")

    @event.listens_for(engine, "do_connect")
    def no_connection(*args):
        raise AssertionError("Pure exception owner must never connect")

    s = Session(engine)
    s.begin()
    ctx, plan, identity = case.base.ctx, case.plan, uuid4()
    s.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    row = ReleaseExceptionDecision(
        id=identity,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=plan.scope.product_id,
        project_id=plan.scope.project_id,
        revision=1,
        series_id=identity,
        owner_id=plan.owner_id,
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        visibility=plan.visibility,
        action="approved",
        basis_package_id=plan.basis_package.id,
        basis_package_revision=plan.basis_package.revision,
        policy_fact_id=plan.policy_fact.id,
        policy_fact_revision=plan.policy_fact.revision,
        discipline=plan.discipline,
        purpose=plan.purpose,
        body=plan.model_dump(mode="json"),
        body_sha256=release.digest(plan),
        expiry=plan.expiry,
        source_basis={"artifact_sources": {str(case.base.source.id): {"revision": 1}}},
        authority_snapshot={"explicit": "IO substitute, not a professional fact"},
        operation=DECIDE,
        write_tier="T2",
        shared_proof_id=uuid4(),
        shared_proof_revision=1,
        proof_consumed_at=plan.prepared_at,
        proof_expires_at=None,
        created_at=plan.prepared_at,
        command_id=uuid4(),
        receipt_id=uuid4(),
        request_digest="a" * 64,
        intent_digest="b" * 64,
    )
    pointer = ReleaseExceptionCurrent(
        id=uuid4(),
        series_id=identity,
        decision_id=identity,
        decision_revision=1,
        epoch=1,
        action="approved",
    )
    receipt = Receipt(id=row.receipt_id, confirmation_id=row.shared_proof_id)
    group = {
        "receipt": {
            "id": row.receipt_id,
            "subject_type": "release_exception",
            "command_id": row.command_id,
            "request_digest": row.request_digest,
            "intent_digest": row.intent_digest,
        }
    }
    value = SimpleNamespace(
        case=case,
        engine=engine,
        s=s,
        ctx=ctx,
        pid=plan.scope.product_id,
        row=row,
        pointer=pointer,
        receipt=receipt,
        group=group,
        signed=True,
        source_current=True,
        source_calls=[],
        at=plan.prepared_at,
    )

    def actual_row(_s, model, selected, **kwargs):
        if model is ReleaseExceptionDecision and selected == row.id:
            return row
        if model is Receipt and selected == receipt.id:
            return receipt
        raise AssertionError("Reader requested an unexpected direct identity")

    def watermarks(_s, _ctx, _pid, marks):
        value.source_calls.append(deepcopy(marks))
        if not value.source_current:
            raise DomainError("SOURCE_STALE", "Explicit changed original watermark", 409)

    monkeypatch.setattr(owner, "require_access", lambda *_args: None)
    monkeypatch.setattr(owner, "snapshot_get", actual_row)
    monkeypatch.setattr(owner, "snapshot_scalar", lambda *_args, **_kwargs: pointer)
    monkeypatch.setattr(owner, "common_group", lambda *_args, **_kwargs: group)
    monkeypatch.setattr(owner, "signature_current", lambda *_args: value.signed)
    monkeypatch.setattr(
        owner.direct, "_source_watermarks", lambda *_args: [{"explicit": "source watermark"}]
    )
    monkeypatch.setattr(owner.direct, "_watermarks_current", watermarks)
    monkeypatch.setattr(owner, "now", lambda: value.at)
    value.reader = owner.ActualReleaseExceptionOwner(engine)
    value.read = lambda **updates: value.reader.read(
        s,
        ctx,
        value.pid,
        (case.ref.model_copy(update={"id": identity}),),
        **(
            {
                "scope": plan.scope,
                "config": plan.subject_config,
                "purpose": plan.purpose,
                "policy_version": plan.policy_version,
                "policy_fact": plan.policy_fact,
                "visibility": plan.visibility,
            }
            | updates
        ),
    )
    yield value
    s.close()
    engine.dispose()


def replace_plan(work, **updates):
    plan = work.case.plan.model_copy(update=updates)
    work.row.body, work.row.body_sha256 = plan.model_dump(mode="json"), release.digest(plan)
    work.row.expiry = plan.expiry
    return plan


def test_actual_reader_preserves_original_checks_and_explicit_controls(work):
    values, objects, bases, sources, reads = work.read()
    assert values[0].state == "current" and bases[0]["state"] == "current"
    assert values[0].limits == (*work.case.plan.limits, *work.case.plan.risk_controls)
    assert objects[0].sha256 == work.row.body_sha256
    assert sources == work.case.plan.sources and reads == work.case.plan.required_source_read_set
    assert work.reader.current(work.s, work.ctx, work.pid, bases)
    assert work.row.body["selected_checks"][0]["state"] == "blocked"
    assert not (work.s.new or work.s.dirty or work.s.deleted)


@pytest.mark.parametrize("fault", ["identity", "revision"])
def test_equal_policy_version_cannot_replace_exact_policy_fact(work, fault):
    selected = work.case.plan.policy_fact.model_copy(
        update={"id": uuid4()} if fault == "identity" else {"revision": 2}
    )
    values, _, bases, _, _ = work.read(policy_fact=selected)
    assert values[0].policy_version == work.case.plan.policy_version
    assert values[0].state == bases[0]["state"] == "unknown"
    assert work.row.policy_fact_id == work.case.plan.policy_fact.id


def test_expiry_blocks_new_use_but_does_not_erase_retained_approved_fact(work):
    replace_plan(work, expiry=work.at + timedelta(seconds=1))
    _, _, bases, _, _ = work.read()
    work.at += timedelta(seconds=1)
    with pytest.raises(DomainError) as error:
        work.reader.current(work.s, work.ctx, work.pid, bases)
    assert error.value.reason == "RECHECK_REQUIRED"
    values, _, fresh_bases, _, _ = work.read()
    assert values[0].state == fresh_bases[0]["state"] == "unknown"
    row, retained = owner.retained(work.s, work.ctx, work.pid, work.row.id, 1)
    assert row is work.row and retained.action == "approved"


def test_withdrawn_current_keeps_the_original_approved_row_and_reports_withdrawn(work):
    _, _, bases, _, _ = work.read()
    original = deepcopy(work.row.body)
    work.pointer.action, work.pointer.decision_id, work.pointer.epoch = "withdrawn", uuid4(), 2
    with pytest.raises(DomainError) as error:
        work.reader.current(work.s, work.ctx, work.pid, bases)
    assert error.value.reason == "RECHECK_REQUIRED"
    values, _, _, _, _ = work.read()
    assert values[0].state == "withdrawn"
    assert work.row.body == original and work.row.action == "approved"


@pytest.mark.parametrize("fault", ["signature", "original"])
def test_later_actual_dependency_drift_is_unknown_and_rejects_old_current_basis(work, fault):
    _, _, bases, _, _ = work.read()
    if fault == "signature":
        work.signed = False
    else:
        work.source_current = False
    values, _, _, _, _ = work.read()
    assert values[0].state == "unknown"
    with pytest.raises(DomainError):
        work.reader.current(work.s, work.ctx, work.pid, bases)


def test_private_exception_cannot_be_repackaged_as_shared(work):
    replace_plan(work, visibility="private")
    work.row.visibility = "private"
    with pytest.raises(DomainError) as error:
        work.read(visibility="category")
    assert error.value.reason == "FORBIDDEN_SCOPE" and error.value.status == 403
