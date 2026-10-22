"""No-connect adapter checks using the frozen actual ORM/live-owner shape.

SQL SELECT, bytes, professional and front child readers are explicit doubles.
The actual LivePairedOwner/structural rules/UOW are exercised; no test is a
claim of real source material, independent people, production authority or PG.
"""

import importlib.util
import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from pdos_next import paired_followup_adapter as adapter
from pdos_next.domain.capa_effectiveness import paired_storage
from pdos_next.domain.capa_verification.schemas import ActionBinding, FollowupBasis, OutputRef
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunIdentity,
)
from pdos_next.domain.verification_results.models import TestResultActionFact as ResultActionORM
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Receipt
from pdos_next.schemas.quality_issues.contracts import EffectivenessRequirement
from pdos_next.service import Context, digest

_spec = importlib.util.spec_from_file_location(
    "followup_live_saved_shapes", Path(__file__).with_name("test_live_paired_owner.py")
)
live_samples = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_samples)
samples = live_samples.structural


def frame(monkeypatch, operation="test.run.start"):
    work = live_samples.frame(monkeypatch, operation)
    monkeypatch.setattr(adapter, "_now", lambda: work.clock[0])
    monkeypatch.setattr(paired_storage, "now", lambda: work.clock[0])
    if operation == "verification.schedule.promise":
        # The frozen storage-only sample predates its real resource input body.
        # This explicit planned-resource port substitute tests dispatch/live
        # sequencing; it cannot certify real readiness or professional facts.
        plan = SimpleNamespace(
            facts_revision="f" * 64,
            required_source_read_set=work.material.fact.reads,
            valid_until=work.sources.valid_until,
            expiry_boundaries=work.sources.time_constraints,
        )
        monkeypatch.setattr(live_samples.bridge, "_execution", lambda *a: (None, plan))
        monkeypatch.setattr(
            live_samples.bridge.resources, "expired", lambda value, at: at >= value.valid_until
        )
    if operation in {"test.results.import", "test.run.review", "test.disposition.decide"}:
        actual = live_samples.NumericalRead(work.read())
        monkeypatch.setattr(
            adapter.quality_result_bridge, "fixed_failure_result", lambda *a, **k: actual
        )
        monkeypatch.setattr(
            adapter.quality_result_bridge, "recheck_fixed_failure_result", lambda *a: actual
        )
    work.basis = FollowupBasis(
        scope=work.binding.scope,
        issue_id=samples.uid("followup-issue"),
        issue_version_id=samples.uid("followup-issue-version"),
        issue_revision=6,
        capa_id=samples.uid("followup-capa"),
        purpose=work.binding.purpose,
        owner_id=work.ctx.requester_id,
        visibility="category",
        nature="synthetic",
        requirement=EffectivenessRequirement(
            method="actual new Run, controlled owner test substitute",
            acceptance="complete fixed failure scope",
            observation_until=samples.AT + timedelta(days=1),
            required_failure_ids=("failure-a",),
        ),
        requirement_sha256="a" * 64,
        failure_ids=("failure-a",),
        failure_basis_sha256="b" * 64,
        actions=(
            ActionBinding(
                action_id=samples.uid("completed-action"),
                executor_id=work.ctx.requester_id,
                action_sha256="c" * 64,
            ),
        ),
        sources=(),
        required_source_read_set=tuple(v.model_dump(mode="json") for v in work.material.fact.reads),
        source_basis_sha256="d" * 64,
        basis_sha256="e" * 64,
    )
    work.selected = OutputRef(
        kind="verification_request",
        id=work.binding.output_ref.id,
        revision=work.binding.output_ref.revision,
    )
    work.front_calls = []
    work.extra_children = []

    def fixed_view(s, ctx, pid, identity, *, assess_capabilities=True):
        work.front_calls.append((ctx.requester_id, assess_capabilities))
        assert assess_capabilities is False and ctx is work.active_ctx
        row = next(v for v in work.memory.rows[FormalVerificationRequest] if v.id == identity)
        request = adapter.front._snapshot(row)
        return row, {
            "id": str(row.id),
            "request_id": str(row.request_id),
            "revision": row.revision,
            "project_id": str(row.project_id),
            "build": request.build.model_dump(mode="json"),
            "owner_id": str(row.owner_id),
            "visibility": row.visibility,
            "status": row.status,
            "operation": row.operation,
            "title": request.title,
            "purpose": row.purpose,
            "request_snapshot": row.request_snapshot,
            "method_assessments": deepcopy(work.extra_children),
            "window_proposals": [],
            "documents_ready": True,
            "document_milestone_current": True,
            "authority": {"caller_display_only": str(ctx.requester_id)},
            "capabilities": {"caller_display_only": True},
            "checked_at": work.clock[0].isoformat(),
            "created_at": row.created_at.isoformat(),
            "blockers": [{"code": "LEGACY_EXECUTION_UNCONNECTED"}],
            "required_source_read_set": row.required_source_read_set,
            "source_status": "current",
            "is_current": True,
            "freshness": "current",
        }

    monkeypatch.setattr(adapter.front, "get_request", fixed_view)
    work.active_ctx = work.ctx
    work.adapter = adapter.configure(work.s.get_bind(), work.owner)
    work.read_output = lambda: work.adapter.read(
        work.s, work.active_ctx, work.binding.scope.product_id, work.basis, work.selected
    )
    work.refresh_output = lambda previous: work.adapter.refresh(
        work.s, work.active_ctx, work.binding.scope.product_id, work.basis, work.selected, previous
    )
    return work


def code(call, expected):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == expected


@pytest.mark.parametrize(
    "operation,meaning",
    [
        ("verification.schedule.promise", "planned"),
        ("test.run.start", "performed"),
        ("test.results.import", "performed"),
        ("test.run.review", "performed"),
        ("test.disposition.decide", "performed"),
    ],
)
def test_actual_pair_group_projects_exact_receipt_stable_full_rows_and_live_handle(
    monkeypatch, operation, meaning
):
    work = frame(monkeypatch, operation)
    handle = work.read_output()
    assert handle.receipt_id == work.material.receipt.id == handle.pair_read.material.receipt.id
    assert handle.output.ref == work.selected and handle.output.meaning == meaning
    assert handle.host_gate.issued_by is work.owner
    assert handle.host_gate.session is work.s
    assert handle.pair_read.binding.caller_id == work.ctx.requester_id
    assert handle.output.snapshot["paired_material"] == handle.pair_read.material.model_dump(
        mode="json"
    )
    assert (
        not {
            "caller_id",
            "authority",
            "capabilities",
            "checked_at",
            "created_at",
            "host_gate",
            "valid_until",
        }
        & handle.output.snapshot.keys()
    )
    assert "caller_id" not in handle.output.snapshot["paired_material"]
    assert (
        json.loads(json.dumps(handle.output.model_dump(mode="json"), allow_nan=False))["meaning"]
        == meaning
    )
    assert work.front_calls == [(work.ctx.requester_id, False)] * 2
    assert all(query.is_select for query in work.memory.queries)
    assert not work.s.new and not work.s.dirty and not work.s.deleted


def test_refresh_rechecks_actual_owner_but_preserves_saved_material_and_same_receipt(monkeypatch):
    work = frame(monkeypatch)
    first = work.read_output()
    calls = len(work.calls)
    work.clock[0] += timedelta(seconds=2)
    second = work.refresh_output(first)
    assert second is not first and second.output == first.output
    assert second.receipt_id == first.receipt_id
    assert second.host_gate.checked_at > first.host_gate.checked_at
    assert len(work.calls) > calls and len(work.front_calls) == 4
    assert work.adapter.runtime["epoch"] == 1


def test_two_authorized_shared_callers_have_identical_fixed_output_and_separate_live_gates(
    monkeypatch,
):
    work = frame(monkeypatch)
    first = work.read_output()
    other = samples.uid("independent-readable-consumer")
    work.memory.add(
        Principal(id=other, tenant_id=work.ctx.tenant_id, kind="human", active=True, access_epoch=1)
    )
    work.memory.add(
        Grant(
            id=samples.uid("independent-grant"),
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            principal_id=other,
            can_write=True,
            access_epoch=3,
            expires_at=samples.AT + timedelta(hours=2),
        )
    )
    work.active_ctx = Context(work.ctx.tenant_id, other, other, category_id=work.ctx.category_id)
    second = work.read_output()
    assert second.output == first.output
    assert second.output.owner_id != other
    assert second.host_gate.caller_id == other
    assert second.host_gate.stamps != first.host_gate.stamps
    code(lambda: work.refresh_output(first), "CALLER_UOW_CHANGED")


def test_duplicate_current_pointer_for_exact_fact_is_rejected_not_chosen(monkeypatch):
    work = frame(monkeypatch)
    model = VerificationRunCurrent
    original = work.memory.first(model)
    duplicate = model(
        **{
            column.key: deepcopy(getattr(original, column.key))
            for column in model.__table__.columns
            if hasattr(original, column.key)
        }
    )
    duplicate.id = samples.uid("ambiguous-run-row")
    work.memory.add(duplicate)
    code(work.read_output, "PAIR_CURRENT_MISSING_OR_AMBIGUOUS")
    assert not work.calls


def test_other_run_identity_under_same_request_cannot_replace_exact_fact_run(monkeypatch):
    work = frame(monkeypatch)
    original = work.memory.first(VerificationRunIdentity)
    sibling = VerificationRunIdentity(
        **{
            column.key: deepcopy(getattr(original, column.key))
            for column in VerificationRunIdentity.__table__.columns
            if hasattr(original, column.key)
        }
    )
    sibling.id = samples.uid("other-run-under-request")
    work.memory.add(sibling)
    handle = work.read_output()
    assert handle.pair_read.binding.run_id == original.id


def test_unchanged_formal_import_selects_review_fact_by_exact_current_run(monkeypatch):
    work = frame(monkeypatch, "test.run.review")
    formal = next(
        row for row in work.memory.rows[FormalVerificationRequest] if row.id == work.selected.id
    )
    current = work.memory.first(VerificationRunCurrent)
    review = work.memory.first(ResultActionORM)
    assert formal.operation == "test.results.import" and review.operation == "test.run.review"
    prior_import = ResultActionORM(
        **{
            column.key: deepcopy(getattr(review, column.key))
            for column in ResultActionORM.__table__.columns
            if hasattr(review, column.key)
        }
    )
    prior_import.id = samples.uid("prior-import-fact-same-formal")
    prior_import.operation = formal.operation
    prior_import.next_run_version_id = review.run_version_id
    prior_import.next_run_revision = review.run_revision
    work.memory.add(prior_import)
    handle = work.read_output()
    assert handle.pair_read.material.fact.operation == "test.run.review"
    assert handle.pair_read.material.run_after.ref.id == current.run_version_id


def test_advanced_formal_cannot_borrow_old_direct_receipt_when_actual_pair_receipt_missing(
    monkeypatch,
):
    work = frame(monkeypatch)
    work.memory.drop(Receipt)
    code(work.read_output, "PAIR_RECEIPT_MISSING")


def test_direct_front_operation_is_not_redirected_to_pair_by_status_or_hidden_fallback(monkeypatch):
    work = frame(monkeypatch)
    row = next(v for v in work.memory.rows[FormalVerificationRequest] if v.id == work.selected.id)
    row.operation = "verification.handoff.accept"
    code(work.read_output, "PAIR_NOT_REQUIRED")
    assert not work.calls and not work.front_calls
    assert "test.run.plan" not in adapter.PAIRED_FORMAL_OPERATIONS


@pytest.mark.parametrize("field", ["project", "purpose", "product"])
def test_actual_fixed_basis_and_formal_scope_must_match(monkeypatch, field):
    work = frame(monkeypatch)
    if field == "purpose":
        work.basis = work.basis.model_copy(update={"purpose": "another real purpose"})
    else:
        key = "project_id" if field == "project" else "product_id"
        work.basis = work.basis.model_copy(
            update={
                "scope": work.basis.scope.model_copy(update={key: samples.uid("another-scope")})
            }
        )
    code(
        work.read_output,
        "PAIR_SCOPE_MISMATCH" if field in {"purpose", "product"} else "FORBIDDEN_SCOPE",
    )
    assert not work.calls


def test_private_formal_cannot_be_read_using_saved_writer_context(monkeypatch):
    work = frame(monkeypatch)
    row = next(v for v in work.memory.rows[FormalVerificationRequest] if v.id == work.selected.id)
    row.visibility, row.owner_id = "private", samples.uid("private-original-owner")
    code(work.read_output, "FORBIDDEN_SCOPE")


def test_final_pair_source_io_revoke_or_current_change_blocks_live_output(monkeypatch):
    work = frame(monkeypatch)
    original = live_samples.bridge._source_read

    def changed(*args):
        work.memory.first(VerificationRunCurrent).run_revision += 1
        return original(*args)

    monkeypatch.setattr(live_samples.bridge, "_source_read", changed)
    code(work.read_output, "PAIR_FACT_MISMATCH")


def test_runtime_configuration_changed_by_final_owner_io_invalidates_phase(monkeypatch):
    work = frame(monkeypatch)
    original = live_samples.bridge._source_read

    def changed(*args):
        adapter.configure(work.s.get_bind(), work.owner)
        return original(*args)

    monkeypatch.setattr(live_samples.bridge, "_source_read", changed)
    code(work.read_output, "PAIR_OWNER_CONFIGURATION_CHANGED")


def test_complete_child_source_union_over_twenty_is_returned_without_truncation(monkeypatch):
    work = frame(monkeypatch)
    work.extra_children = [
        {
            "id": "fixed-child",
            "current": True,
            "required_source_read_set": [
                {"artifact_id": str(samples.uid(f"child-source:{i}")), "expected_revision": 1}
                for i in range(21)
            ],
        }
    ]
    result = work.read_output()
    wanted = {value["artifact_id"] for value in work.extra_children[0]["required_source_read_set"]}
    assert wanted <= {str(value.artifact_id) for value in result.output.required_source_read_set}


@pytest.mark.parametrize("mutation", ["clone", "snapshot", "receipt"])
def test_forged_or_modified_handle_cannot_refresh(monkeypatch, mutation):
    work = frame(monkeypatch)
    handle = work.read_output()
    if mutation == "clone":
        handle = replace(handle)
    elif mutation == "snapshot":
        handle.output.snapshot["status"] = "invented"
    else:
        object.__setattr__(handle, "receipt_id", samples.uid("unrelated-receipt"))
    code(lambda: work.refresh_output(handle), "PAIR_HANDLE_UNBOUND")


def test_current_child_business_change_during_owner_io_cannot_keep_old_stable_output(monkeypatch):
    work = frame(monkeypatch)
    original, reads = adapter.front.get_request, [0]

    def changed(*args, **kwargs):
        row, view = original(*args, **kwargs)
        reads[0] += 1
        if reads[0] == 2:
            view["document_milestone_current"] = False
            view["documents_ready"] = False
            view["freshness"] = "requires_recalculation"
        return row, view

    monkeypatch.setattr(adapter.front, "get_request", changed)
    code(work.read_output, "SOURCE_STALE")


def test_last_caller_sql_crossing_expiry_is_checked_after_all_io(monkeypatch):
    work = frame(monkeypatch)
    original = paired_storage._acl
    finishing = [False]
    finish = work.adapter._finish

    def changed(*args, **kwargs):
        value = original(*args, **kwargs)
        if finishing[0]:
            work.clock[0] = work.sources.valid_until
        return value

    def marked(*args, **kwargs):
        finishing[0] = True
        return finish(*args, **kwargs)

    monkeypatch.setattr(paired_storage, "_acl", changed)
    monkeypatch.setattr(work.adapter, "_finish", marked)
    code(work.read_output, "PAIR_LIVE_PROOF_EXPIRED")


def test_nested_uow_change_is_rejected_and_readers_never_flush(monkeypatch):
    work = frame(monkeypatch)
    original_flush = work.s.flush
    monkeypatch.setattr(work.s, "flush", lambda *a, **k: pytest.fail("owner must not flush"))
    handle = work.read_output()
    # The real caller's begin_nested takes its empty snapshot via flush; the
    # reader is prohibited from performing that action, not this test caller.
    monkeypatch.setattr(work.s, "flush", original_flush)
    work.s.begin_nested()
    monkeypatch.setattr(work.s, "flush", lambda *a, **k: pytest.fail("owner must not flush"))
    code(lambda: work.refresh_output(handle), "CALLER_UOW_CHANGED")


def test_no_structural_only_owner_is_configured_and_no_sqlalchemy_duck_uow_is_accepted(monkeypatch):
    work = frame(monkeypatch)
    code(
        lambda: adapter.configure(work.s.get_bind(), paired_storage.StoragePairReader()),
        "INTEGRATION_REQUIRED",
    )
    assert adapter.configured(work.s) is work.adapter
    assert digest(work.adapter.runtime) != digest({**work.adapter.runtime, "epoch": 2})
    fake = SimpleNamespace(
        is_active=True,
        get_bind=lambda: work.s.get_bind(),
        get_transaction=lambda: object(),
        get_nested_transaction=lambda: None,
    )
    code(
        lambda: work.adapter.read(
            fake, work.ctx, work.binding.scope.product_id, work.basis, work.selected
        ),
        "CALLER_UOW_REQUIRED",
    )


def test_runtime_property_includes_actual_registry_epoch_but_does_not_enter_output(monkeypatch):
    work = frame(monkeypatch)
    before = work.adapter.runtime
    handle = work.read_output()
    work.s.get_bind()._pdos_professional_issuer_epochs = {"changed-original-issuer": 2}
    assert before != work.adapter.runtime
    assert "owners_runtime_sha256" not in handle.output.snapshot
    code(lambda: work.refresh_output(handle), "PAIR_HANDLE_UNBOUND")


def test_strict_ref_reparse_does_not_allow_copied_boolean_revision(monkeypatch):
    work = frame(monkeypatch)
    work.selected = work.selected.model_copy(update={"revision": True})
    with pytest.raises(ValidationError):
        work.read_output()
    assert not work.calls


def test_expired_original_handle_cannot_be_refreshed_as_another_permission_phase(monkeypatch):
    work = frame(monkeypatch)
    handle = work.read_output()
    calls = len(work.calls)
    work.clock[0] = min(handle.host_gate.time_constraints)
    code(lambda: work.refresh_output(handle), "PAIR_LIVE_PROOF_EXPIRED")
    assert len(work.calls) == calls
