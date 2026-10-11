"""Real Session/UOW, no-connect dispatch checks with explicit owner substitutes.

The live adapter owns actual paired bytes/professional proof. These tests check
that its same-phase read/refresh is selected exactly, never replaced by a direct
Formal receipt, and never copied into the persisted OutputReading contract.
"""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from capa_effectiveness.test_participants_owner import work as work
from capa_verification.test_pure import basis as original_basis  # noqa: F401 - pytest fixture
from capa_verification.test_pure import output

from pdos_next import paired_followup_adapter as adapter
from pdos_next.domain.capa_verification import service
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.errors import DomainError


@pytest.fixture
def selected(work, original_basis, monkeypatch):  # noqa: F811 - imported pytest fixture
    basis = original_basis.model_copy(update={"scope": work.scope, "owner_id": work.actor})
    basis = basis.model_copy(update={"basis_sha256": service._basis_digest(basis)})
    reading = output(basis, kind="verification_request")
    row = work.s.seed(
        FormalVerificationRequest,
        id=reading.ref.id,
        revision=1,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        request_id=uuid4(),
        owner_id=work.actor,
        visibility="category",
        operation="test.run.start",
        status="executing",
        required_source_read_set=[
            r.model_dump(mode="json") for r in basis.required_source_read_set
        ],
    )
    value = SimpleNamespace(
        work=work,
        basis=basis,
        ref=reading.ref,
        row=row,
        output=reading,
        receipt_id=uuid4(),
        reads=[],
        refreshes=[],
        direct_calls=[],
        basis_calls=[],
        sources=[],
        drift=False,
        refresh_error=None,
    )

    class LiveOwnerSubstitute:
        def read(self, s, ctx, pid, supplied_basis, ref, *, write=False):
            assert (s, ctx, pid, supplied_basis, ref) == (
                work.s,
                work.ctx,
                work.pid,
                basis,
                reading.ref,
            )
            assert s.get_transaction().is_active
            result = SimpleNamespace(output=value.output, receipt_id=value.receipt_id)
            value.reads.append((result, write))
            return result

        def refresh(self, s, ctx, pid, supplied_basis, ref, previous, *, write=False):
            assert (s, ctx, pid, supplied_basis, ref) == (
                work.s,
                work.ctx,
                work.pid,
                basis,
                reading.ref,
            )
            assert previous is value.reads[-1][0] and write == value.reads[-1][1]
            assert s.get_transaction().is_active
            value.refreshes.append((previous, write))
            if value.refresh_error:
                raise DomainError(value.refresh_error, "explicit live-owner refusal")
            current = (
                value.output.model_copy(update={"owner_basis_sha256": "b" * 64})
                if value.drift
                else value.output
            )
            return SimpleNamespace(output=current, receipt_id=value.receipt_id)

    value.owner = LiveOwnerSubstitute()
    monkeypatch.setattr(adapter, "configured", lambda s: value.owner)

    def recheck(s, ctx, pid, supplied_basis, **kwargs):
        assert (s, ctx, pid, supplied_basis) == (work.s, work.ctx, work.pid, basis)
        value.basis_calls.append(kwargs)
        return basis

    def sources(s, ctx, pid, reads):
        assert (s, ctx, pid) == (work.s, work.ctx, work.pid)
        value.sources.append(service.merge_reads(reads))
        return [
            {"id": str(r.artifact_id), "revision": r.expected_revision}
            for r in service._reads(reads)
        ], False

    monkeypatch.setattr(service, "recheck_followup_basis", recheck)
    monkeypatch.setattr(service, "source_basis", sources)
    monkeypatch.setattr(service.quality, "_human", lambda *a, **kw: None)

    def direct(s, ctx, pid, ref):
        value.direct_calls.append(ref)
        raise AssertionError("advanced paired Formal cannot use direct receipt/owner")

    monkeypatch.setattr(service, "_owner", direct)
    return value


def resolve(v, *, write=False):
    return service.resolve_followup_outputs(
        v.work.s,
        v.work.ctx,
        v.work.pid,
        v.basis,
        v.basis.actions[0].action_id,
        (v.ref,),
        write=write,
    )


@pytest.mark.parametrize("operation", sorted(adapter.PAIRED_FORMAL_OPERATIONS))
@pytest.mark.parametrize("write", [False, True])
def test_each_actual_paired_formal_operation_gets_same_phase_read_then_refresh(
    selected, operation, write
):
    v = selected
    v.row["operation"] = operation
    before = deepcopy(v.row)
    result = resolve(v, write=write)
    assert result.outputs == (v.output,)
    assert len(v.reads) == len(v.refreshes) == 1
    assert v.refreshes[0][0] is v.reads[0][0]
    assert [c["write"] for c in v.basis_calls] == [write, write]
    assert len(v.sources) == 2 and v.sources[0] == v.sources[1]
    assert not v.direct_calls and v.row == before
    assert v.work.s.info == {}
    saved = result.model_dump(mode="json")
    assert saved["outputs"] == [v.output.model_dump(mode="json")]
    assert str(v.receipt_id) not in str(saved)
    assert result.action_fulfilled is None


def test_actual_pair_receipt_and_handle_are_only_stack_local_helper_results(selected):
    v = selected
    reading, handle = service._read_output(v.work.s, v.work.ctx, v.work.pid, v.basis, v.ref)
    assert reading is v.output and handle is v.reads[0][0]
    assert handle.receipt_id == v.receipt_id
    refreshed = service._refresh_output(v.work.s, v.work.ctx, v.work.pid, v.basis, v.ref, handle)
    assert refreshed is reading
    assert "receipt_id" not in reading.model_dump(mode="json") and v.work.s.info == {}


@pytest.mark.parametrize(
    "operation",
    ["verification.request.create", "verification.handoff.offer", "verification.handoff.accept"],
)
def test_early_formal_output_keeps_complete_direct_material_and_children(
    selected, monkeypatch, operation
):
    v = selected
    v.row["operation"], v.row["status"] = operation, "draft"
    direct_row = SimpleNamespace(**v.row)
    view = dict(
        id=str(v.ref.id),
        revision=1,
        request_id=str(v.row["request_id"]),
        status="draft",
        title="Fixed real early Formal",
        source_status="current",
        is_current=True,
        documents_ready=False,
        freshness="current",
        authority={"UI_only": "not saved"},
        capabilities={"request_create": True},
        method_assessments=[],
        window_proposals=[],
        required_source_read_set=deepcopy(v.row["required_source_read_set"]),
    )
    calls = []

    def get_request(s, ctx, pid, identity, *, assess_capabilities=True):
        assert (s, ctx, pid, identity) == (v.work.s, v.work.ctx, v.work.pid, v.ref.id)
        calls.append(assess_capabilities)
        return direct_row, deepcopy(view)

    monkeypatch.setattr(front, "get_request", get_request)
    monkeypatch.setattr(service, "_owner", _REAL_OWNER)
    expected = service._direct_reading(v.work.s, v.work.ctx, v.work.pid, v.basis, v.ref)
    result = resolve(v)
    assert result.outputs == (expected,)
    assert calls == [False, False, False]
    assert not v.reads and not v.refreshes
    assert result.outputs[0].snapshot["method_assessments"] == view["method_assessments"]
    assert result.outputs[0].snapshot["window_proposals"] == view["window_proposals"]
    assert result.outputs[0].snapshot["documents_ready"] is False
    assert "authority" not in result.outputs[0].snapshot


_REAL_OWNER = service._owner


def test_advanced_missing_owner_never_uses_direct_receipt_or_draft_fallback(selected, monkeypatch):
    v = selected
    monkeypatch.setattr(adapter, "configured", lambda s: None)
    with pytest.raises(DomainError) as error:
        resolve(v)
    assert (error.value.reason, error.value.status) == ("INTEGRATION_REQUIRED", 503)
    assert not v.direct_calls and not v.reads


def test_refresh_cannot_degrade_to_direct_formal_when_original_operation_changes(selected):
    v = selected
    _, handle = service._read_output(v.work.s, v.work.ctx, v.work.pid, v.basis, v.ref)
    v.row["operation"] = "verification.request.create"
    with pytest.raises(DomainError) as error:
        service._refresh_output(v.work.s, v.work.ctx, v.work.pid, v.basis, v.ref, handle)
    assert error.value.reason == "SOURCE_STALE" and not v.direct_calls


@pytest.mark.parametrize("problem", ["ref", "project", "private"])
def test_adapter_return_cannot_change_output_scope_or_private_audience(selected, problem):
    v = selected
    update = (
        {"ref": v.ref.model_copy(update={"id": uuid4()})}
        if problem == "ref"
        else {"project_id": uuid4()}
        if problem == "project"
        else {"visibility": "private", "owner_id": uuid4()}
    )
    v.output = v.output.model_copy(update=update)
    with pytest.raises(DomainError) as error:
        resolve(v)
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_second_actual_refresh_output_drift_is_not_serialized_as_current(selected):
    v = selected
    v.drift = True
    with pytest.raises(DomainError) as error:
        resolve(v)
    assert error.value.reason == "SOURCE_STALE" and len(v.refreshes) == 1


@pytest.mark.parametrize("code", ["SOURCE_STALE", "FORBIDDEN_SCOPE", "INTEGRATION_REQUIRED"])
def test_actual_owner_refresh_refusal_is_preserved_not_caught_or_replaced(selected, code):
    v = selected
    v.refresh_error = code
    with pytest.raises(DomainError) as error:
        resolve(v)
    assert error.value.reason == code and not v.direct_calls


def test_run_kind_uses_existing_actual_run_owner_not_formal_pair(selected, monkeypatch):
    v = selected
    selected_run = output(
        v.basis, kind="verification_run", snapshot={"retained": {"current": True}}
    )
    row = SimpleNamespace(
        id=selected_run.ref.id,
        revision=1,
        tenant_id=v.work.ctx.tenant_id,
        product_id=v.work.pid,
        project_id=v.work.scope.project_id,
        owner_id=v.work.actor,
        visibility="category",
        status="running",
        run_id=uuid4(),
    )
    calls = []

    def owner(s, ctx, pid, ref):
        assert ref == selected_run.ref
        calls.append(ref)
        return row, dict(
            status="running",
            source_status="current",
            is_current=True,
            retained={"current": True},
            required_source_read_set=v.row["required_source_read_set"],
        )

    monkeypatch.setattr(service, "_owner", owner)
    reading, handle = service._read_output(
        v.work.s, v.work.ctx, v.work.pid, v.basis, selected_run.ref
    )
    refreshed = service._refresh_output(
        v.work.s, v.work.ctx, v.work.pid, v.basis, selected_run.ref, handle
    )
    assert handle is None and refreshed == reading and reading.meaning == "performed"
    assert calls == [selected_run.ref, selected_run.ref] and not v.reads and not v.refreshes
