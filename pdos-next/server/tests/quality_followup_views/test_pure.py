"""Synthetic read-port doubles verify mapping and fail-closed behavior only."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next import quality_followup_views as views
from pdos_next.domain.capa_verification.schemas import (
    ActionBinding,
    FollowupBasis,
    OutputReading,
    OutputRef,
    ResolvedOutputs,
    SourceRead,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import EffectivenessRequirement
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import digest

AT = datetime(2026, 10, 3, tzinfo=UTC)
REAL_LINKS = views._links


@pytest.fixture
def work(monkeypatch):
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    owner = uuid4()
    source = SourceRead(artifact_id=uuid4(), expected_revision=1)
    basis = FollowupBasis(
        scope=scope,
        issue_id=uuid4(),
        issue_version_id=uuid4(),
        issue_revision=4,
        capa_id=uuid4(),
        purpose="Exact investigation purpose",
        owner_id=owner,
        visibility="category",
        nature="synthetic",
        requirement=EffectivenessRequirement(
            method="Independent new Run",
            acceptance="Exact failures",
            observation_until=AT + timedelta(days=1),
            required_failure_ids=("failure-a",),
        ),
        requirement_sha256="a" * 64,
        failure_ids=("failure-a",),
        failure_basis_sha256="b" * 64,
        actions=(ActionBinding(action_id=uuid4(), executor_id=owner, action_sha256="c" * 64),),
        sources=(),
        required_source_read_set=(source,),
        source_basis_sha256="d" * 64,
        basis_sha256="0" * 64,
    )
    basis = basis.model_copy(update={"basis_sha256": views.owners._basis_digest(basis)})
    ctx = SimpleNamespace(
        tenant_id=scope.tenant_id,
        requester_id=owner,
        actor_id=owner,
        run_id=None,
        category_id=uuid4(),
    )
    authority = {
        "authorized": True,
        "qualified": True,
        "roles": ["quality"],
        "valid_until": None,
        "operation": views.followup.ROOT_CAUSE,
        "purpose": basis.purpose,
        "synthetic": True,
        "required_source_read_set": [],
        "fact_refs": [
            {
                "id": str(uuid4()),
                "revision": 1,
                "epoch": 1,
                "state": "active",
                "nature": "synthetic",
                "kind": kind,
                "role": "quality",
                "qualified": True,
                "operations": list(views.OPERATIONS),
                "purposes": [basis.purpose],
                "valid_from": (AT - timedelta(hours=1)).isoformat(),
                "valid_until": (AT + timedelta(hours=1)).isoformat(),
            }
            for kind in ("duty", "qualification")
        ],
        "reason_codes": [],
    }
    published = {
        "valid_until": authority["valid_until"],
        "facts_revision": "e" * 64,
        "id": "policy-id",
        "revision": 1,
        "source_basis": [
            {
                "id": "policy-id",
                "revision": 1,
                "state": "active",
                "valid_from": (AT - timedelta(hours=1)).isoformat(),
                "valid_until": (AT + timedelta(hours=1)).isoformat(),
            }
        ],
        "required_source_read_set": [],
    }
    selected = {
        "id": str(basis.issue_version_id),
        "issue_id": str(basis.issue_id),
        "revision": 4,
        "project_id": str(scope.project_id),
        "purpose": basis.purpose,
        "is_current": True,
        "source_status": "current",
        "owner_id": str(owner),
        "visibility": "category",
        "issue": {"title": "Original failure", "status": "actioning"},
        "followup_basis": basis.model_dump(mode="json"),
        "authority": {
            op: deepcopy(authority) for op in (views.followup.ROOT_CAUSE, views.followup.COMPLETE)
        },
        "policy": published,
        "capabilities": {op: True for op in views.OPERATIONS},
        "reason_codes": [],
        "required_source_read_set": [source.model_dump(mode="json")],
        "actions": [
            {
                "action_id": str(basis.actions[0].action_id),
                "executor_id": str(owner),
                "text": "Observe actual action",
                "completion": None,
                "can_prepare_completion": True,
                "blockers": [
                    {"code": "STRUCTURED_COMPLETION_REQUIRED", "detail": "Need actual source"}
                ],
            }
        ],
        "source_options": [
            {
                "title": "Registered source",
                "source": {
                    "kind": "artifact",
                    "id": str(source.artifact_id),
                    "revision": 1,
                    "position": "line:1;quote_sha256:" + "f" * 64,
                },
                "quote": "Exact original line",
            }
        ],
    }
    pointer = {"version_id": selected["id"], "revision": 4}
    row = SimpleNamespace(id=basis.issue_version_id, project_id=scope.project_id)
    state = {"calls": [], "epoch": 1, "write": True}
    engine = SimpleNamespace()

    class Session:
        def get_bind(self):
            return engine

        def execute(self, query):
            fields = {
                part.left.name: ctx.category_id
                if getattr(part.right, "name", None) == "category_for_product"
                else part.right.value
                for part in query._where_criteria
            }
            assert fields == {
                "tenant_id": ctx.tenant_id,
                "category_id": ctx.category_id,
                "principal_id": owner,
            }
            return SimpleNamespace(
                one_or_none=lambda: SimpleNamespace(
                    can_write=state["write"], expires_at=AT + timedelta(hours=1)
                )
            )

    def listing(s, context, pid, **kwargs):
        state["calls"].append((s, context, pid, kwargs))
        return {
            "issues": [deepcopy(selected)],
            "current_by_issue": {},
            "capabilities": {op: True for op in views.OPERATIONS},
        }

    monkeypatch.setattr(views.followup, "_human", lambda *args: None)
    monkeypatch.setattr(views, "_current", lambda *args: (row, deepcopy(pointer)))
    monkeypatch.setattr(views.followup, "list_quality_followup", listing)
    monkeypatch.setattr(views.followup, "_row", lambda *args: row)
    monkeypatch.setattr(views.followup, "_read_row", lambda *args, **kwargs: deepcopy(selected))
    monkeypatch.setattr(
        views, "_links", lambda *args: ([], [], {"has_more": False, "unavailable_count": 0})
    )
    monkeypatch.setattr(views.professional, "assess", lambda *args, **kwargs: deepcopy(authority))
    monkeypatch.setattr(views.policy, "assess", lambda *args: deepcopy(published))
    monkeypatch.setattr(views, "source_basis", lambda *args: ([{"epoch": state["epoch"]}], False))
    monkeypatch.setattr(views, "now", lambda: AT)
    return SimpleNamespace(
        scope=scope,
        owner=owner,
        ctx=ctx,
        basis=basis,
        selected=selected,
        pointer=pointer,
        row=row,
        state=state,
        engine=engine,
        session=Session(),
        authority=authority,
        policy=published,
    )


def read(work, **kwargs):
    return views.list_quality_followup(
        work.session, work.ctx, work.scope.product_id, issue_id=work.basis.issue_id, **kwargs
    )


def error(code, callback):
    with pytest.raises(DomainError) as rejected:
        callback()
    assert rejected.value.reason == code


def test_single_issue_once_with_explicit_missing_and_no_candidate_or_effectiveness(work):
    result = read(work)
    assert len(work.state["calls"]) == 1
    assert work.state["calls"][0][3] == {"issue_id": work.basis.issue_id, "revision": 4}
    assert result["current"] == work.pointer and result["issue"] == work.selected
    assert result["output_options"] == result["links"] == result["candidates"] == []
    assert result["integration"]["effectiveness"] is result["integration"]["close"] is False
    assert {r["code"] for r in result["integration"]["missing"]} == {
        "OUTPUT_OPTIONS_NOT_CONFIGURED",
        "CANDIDATE_PERSISTENCE_NOT_ENABLED",
    }
    assert result["operations"][views.LINK]["allowed"] is False
    action = result["actions"][0]
    assert action["can_prepare_completion"] is True
    assert action["can_complete"] is False and action["completion_verified"] is None
    assert action["reason_codes"] == ["STRUCTURED_COMPLETION_REQUIRED"]
    assert action["label"] == work.selected["actions"][0]["text"]
    assert result["source_options"][0]["quote"] == "Exact original line"


def test_history_uses_real_current_not_old_row_and_blocks_all_write(work):
    old = uuid4()
    work.selected.update(
        id=str(old), revision=2, is_current=False, source_status="not_evaluated_historical"
    )
    result = read(work, revision=2)
    assert result["issue"]["id"] == str(old) and result["current"] == work.pointer
    assert result["basis"] is None and all(
        v["allowed"] is False for v in result["operations"].values()
    )
    assert all("HISTORICAL_READ_ONLY" in v["reason_codes"] for v in result["operations"].values())
    assert result["actions"][0]["can_prepare_completion"] is False


@pytest.mark.parametrize("revision", [True, 0, -1, "4", 1.5])
def test_revision_strict_and_no_ambient_list(work, revision):
    error("INVALID_PAYLOAD", lambda: read(work, revision=revision))
    assert work.state["calls"] == []


def test_missing_issue_id_is_not_an_all_product_read(work):
    error(
        "INVALID_PAYLOAD",
        lambda: views.list_quality_followup(
            work.session, work.ctx, work.scope.product_id, issue_id=None
        ),
    )
    assert work.state["calls"] == []


def test_top_any_capability_does_not_override_selected_issue(work):
    work.selected["capabilities"] = dict.fromkeys(views.OPERATIONS, False)
    result = read(work)
    assert all(v["allowed"] is False for v in result["operations"].values())
    assert result["actions"][0]["can_prepare_completion"] is False


def test_current_pointer_drift_or_wrong_selected_issue_is_not_silently_latest(work):
    work.pointer["version_id"] = str(uuid4())
    error("SOURCE_STALE", lambda: read(work))
    work.pointer["version_id"] = work.selected["id"]
    work.selected["issue_id"] = str(uuid4())
    error("INTEGRITY_MISMATCH", lambda: read(work))


def test_write_grant_recheck_and_expiry_disable_prepare_not_only_submit(work):
    work.state["write"] = False
    result = read(work)
    assert all(v["allowed"] is False for v in result["operations"].values())
    assert "PRODUCT_WRITE_REQUIRED" in result["operations"][views.followup.COMPLETE]["reason_codes"]
    assert result["actions"][0]["can_prepare_completion"] is False
    work.state["write"] = True
    work.authority["fact_refs"][1]["valid_until"] = AT.isoformat()
    work.selected["authority"] = {
        op: deepcopy(work.authority) for op in (views.followup.ROOT_CAUSE, views.followup.COMPLETE)
    }
    result = read(work)
    assert not result["operations"][views.followup.COMPLETE]["allowed"]


def test_final_professional_epoch_change_rejects_after_owner_io(work, monkeypatch):
    actual = deepcopy(work.authority)
    actual["fact_refs"][0]["epoch"] = 3
    monkeypatch.setattr(views.professional, "assess", lambda *args, **kwargs: actual)
    error("SOURCE_STALE", lambda: read(work))


def test_policy_change_and_current_private_scope_remain_hard_errors(work, monkeypatch):
    monkeypatch.setattr(
        views.policy, "assess", lambda *args: {**work.policy, "facts_revision": "0" * 64}
    )
    error("SOURCE_STALE", lambda: read(work))
    monkeypatch.setattr(
        views,
        "_current",
        lambda *args: (_ for _ in ()).throw(DomainError("FORBIDDEN_SCOPE", "Current private", 403)),
    )
    error("FORBIDDEN_SCOPE", lambda: read(work, revision=2))


def option(work, *, snapshot=None):
    return OutputReading(
        ref=OutputRef(kind="build", id=uuid4(), revision=1),
        owner_id=work.owner,
        visibility="category",
        project_id=work.scope.project_id,
        title="Real fixed output",
        status="planned",
        meaning="planned",
        source_status="current",
        snapshot=snapshot or {},
        required_source_read_set=work.basis.required_source_read_set,
        owner_basis_sha256="a" * 64,
    )


def test_option_callback_cannot_supply_label_qualification_or_scope_facts(work):
    views.configure_output_options(
        work.engine,
        lambda *args: [{"kind": "build", "id": str(uuid4()), "revision": 1, "qualified": True}],
    )
    with pytest.raises(ValidationError):
        read(work)


def test_options_ref_bounds_and_duplicate_identity_do_not_silently_truncate(work):
    value = option(work).ref
    views.configure_output_options(work.engine, lambda *args: [value] * 21)
    error("INTEGRITY_MISMATCH", lambda: read(work))
    views.configure_output_options(work.engine, lambda *args: [value, value])
    error("INTEGRITY_MISMATCH", lambda: read(work))


def test_option_uses_exact_receipt_and_registered_sample_allocation_proof(work, monkeypatch):
    value = option(work)
    monkeypatch.setattr(views.owners, "_read_output", lambda *args: (value, None))
    receipt = SimpleNamespace(
        id=uuid4(),
        requester_id=work.owner,
        actor_id=work.owner,
        run_id=None,
        visibility="category",
        result={"id": str(value.ref.id), "revision": 1},
    )
    session = SimpleNamespace(scalar=lambda query: receipt)
    result, _ = views._option(session, work.ctx, work.scope.product_id, work.basis, value.ref)
    assert result["label"] == value.title and result["receipt_id"] == str(receipt.id)
    receipt.result["revision"] = 2
    error(
        "INTEGRATION_REQUIRED",
        lambda: views._option(session, work.ctx, work.scope.product_id, work.basis, value.ref),
    )
    allocation = uuid4()
    sample = value.model_copy(
        update={
            "ref": OutputRef(kind="sample", id=uuid4(), revision=1),
            "snapshot": {"allocation_id": str(allocation)},
        }
    )
    monkeypatch.setattr(views.owners, "_read_output", lambda *args: (sample, None))
    receipt.result = {"id": str(allocation), "revision": 1, "sample_ids": [str(sample.ref.id)]}
    result, _ = views._option(session, work.ctx, work.scope.product_id, work.basis, sample.ref)
    assert result["ref"]["id"] == str(sample.ref.id)
    receipt.result["sample_ids"] = []
    error(
        "INTEGRATION_REQUIRED",
        lambda: views._option(session, work.ctx, work.scope.product_id, work.basis, sample.ref),
    )


@pytest.mark.parametrize("kind", ["verification_request", "verification_run"])
def test_series_owner_is_not_mistaken_for_this_version_named_writer(work, monkeypatch, kind):
    other = uuid4()
    reading = option(work).model_copy(update={"ref": OutputRef(kind=kind, id=uuid4(), revision=2)})
    row = SimpleNamespace(authority_snapshot={"subject_id": str(other)}, writer_id=other)
    receipt = SimpleNamespace(
        id=uuid4(),
        requester_id=other,
        actor_id=other,
        run_id=None,
        visibility="category",
        result={"id": str(reading.ref.id), "revision": 2},
    )
    monkeypatch.setattr(views.owners, "_read_output", lambda *args: (reading, None))
    monkeypatch.setattr(views.owners, "_fixed_row", lambda *args: row)
    session = SimpleNamespace(scalar=lambda query: receipt)
    result, _ = views._option(session, work.ctx, work.scope.product_id, work.basis, reading.ref)
    assert result["ref"] == reading.ref.model_dump(mode="json")
    receipt.requester_id = work.owner
    error(
        "INTEGRATION_REQUIRED",
        lambda: views._option(session, work.ctx, work.scope.product_id, work.basis, reading.ref),
    )
    row.authority_snapshot = {}
    error(
        "INTEGRATION_REQUIRED",
        lambda: views._option(session, work.ctx, work.scope.product_id, work.basis, reading.ref),
    )


def test_paired_option_uses_its_actual_common_receipt_without_a_direct_formal_fallback(
    work, monkeypatch
):
    """Explicit pair-port double verifies the envelope, not a live professional gate."""
    reading = option(work).model_copy(
        update={
            "ref": OutputRef(kind="verification_request", id=uuid4(), revision=7),
            "logical_id": uuid4(),
        }
    )
    receipt_id = uuid4()
    paired = SimpleNamespace(
        output=reading,
        receipt_id=receipt_id,
        pair_read=SimpleNamespace(material=SimpleNamespace(receipt=SimpleNamespace(id=receipt_id))),
        host_gate=SimpleNamespace(
            time_constraints=(), needs_review=False, valid_until=AT + timedelta(minutes=1)
        ),
    )
    monkeypatch.setattr(views.owners, "_read_output", lambda *args: (reading, paired))
    monkeypatch.setattr(views, "_receipt", lambda *args, **kwargs: pytest.fail("No draft fallback"))
    local_proofs = []
    result, returned = views._option(
        work.session,
        work.ctx,
        work.scope.product_id,
        work.basis,
        reading.ref,
        paired_reads=local_proofs,
    )
    assert result["receipt_id"] == str(receipt_id) and returned == reading
    assert result["logical_id"] == str(reading.logical_id) and local_proofs == [paired]
    assert not {"host_gate", "valid_until", "pair_read", "structure", "runtime"} & result.keys()
    paired.receipt_id = uuid4()
    error(
        "INTEGRITY_MISMATCH",
        lambda: views._option(
            work.session, work.ctx, work.scope.product_id, work.basis, reading.ref
        ),
    )


def test_paired_gate_must_remain_unexpired_after_final_consumer_permission_io(work, monkeypatch):
    value = option(work)
    views.configure_output_options(work.engine, lambda *args: [value.ref])
    paired = SimpleNamespace(
        host_gate=SimpleNamespace(
            time_constraints=(), needs_review=False, valid_until=AT + timedelta(seconds=1)
        )
    )

    def load(*args, paired_reads=None):
        paired_reads.append(paired)
        return {"ref": value.ref.model_dump(mode="json"), "label": value.title}, value

    def late_permission(*args):
        monkeypatch.setattr(views, "now", lambda: AT + timedelta(seconds=2))
        return True

    monkeypatch.setattr(views, "_option", load)
    monkeypatch.setattr(views, "_writable", late_permission)
    error("SOURCE_STALE", lambda: read(work))


def test_paired_runtime_epoch_aba_after_last_permission_io_is_rejected(work, monkeypatch):
    runtime = SimpleNamespace(runtime={"epoch": 1})
    work.engine._pdos_paired_followup_owner = runtime

    def late_permission(*args):
        runtime.runtime["epoch"] = 3
        return True

    monkeypatch.setattr(views, "_writable", late_permission)
    error("SOURCE_STALE", lambda: read(work))


def test_output_owner_change_after_io_rejects_without_generating_any_record(work, monkeypatch):
    value = option(work)
    views.configure_output_options(work.engine, lambda *args: [value.ref])
    work.engine._pdos_capa_link_consumed_proof = lambda *args: pytest.fail("GET must not consume")
    calls = []

    def load(*args, **kwargs):
        calls.append(1)
        reading = (
            value if len(calls) == 1 else value.model_copy(update={"owner_basis_sha256": "b" * 64})
        )
        return {
            "label": value.title,
            "ref": value.ref.model_dump(mode="json"),
            "status": "planned",
        }, reading

    monkeypatch.setattr(views, "_option", load)
    error("SOURCE_STALE", lambda: read(work))
    assert len(calls) == 2


def test_true_owner_selection_still_only_enables_link_preparation_not_effectiveness(
    work, monkeypatch
):
    value = option(work)
    views.configure_output_options(work.engine, lambda *args: [value.ref])
    work.engine._pdos_capa_link_consumed_proof = lambda *args: pytest.fail("GET must not consume")
    monkeypatch.setattr(
        views,
        "_option",
        lambda *args, **kwargs: (
            {
                "label": value.title,
                "ref": value.ref.model_dump(mode="json"),
                "status": value.status,
            },
            value,
        ),
    )
    result = read(work)
    assert result["operations"][views.LINK]["allowed"] is True
    assert result["candidates"] == [] and result["integration"]["effectiveness"] is False


def test_source_epoch_aba_during_last_owner_read_is_rejected(work, monkeypatch):
    value = option(work)
    views.configure_output_options(work.engine, lambda *args: [value.ref])
    calls = []

    def load(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            work.state["epoch"] = 3
        return {
            "label": value.title,
            "ref": value.ref.model_dump(mode="json"),
            "status": value.status,
        }, value

    monkeypatch.setattr(views, "_option", load)
    error("SOURCE_STALE", lambda: read(work))


def test_full_output_source_union_cannot_be_truncated_to_twenty(work, monkeypatch):
    work.selected["required_source_read_set"] = [
        {"artifact_id": str(uuid4()), "expected_revision": 1} for _ in range(20)
    ]
    value = option(work)
    views.configure_output_options(work.engine, lambda *args: [value.ref])
    monkeypatch.setattr(
        views,
        "_option",
        lambda *args, **kwargs: (
            {
                "label": value.title,
                "ref": value.ref.model_dump(mode="json"),
                "status": value.status,
            },
            value,
        ),
    )
    assert len(read(work)["required_source_read_set"]) == 21


def link_row(work):
    output = option(work)
    resolved = ResolvedOutputs(
        basis=work.basis,
        action_id=work.basis.actions[0].action_id,
        outputs=(output,),
        visibility="category",
        owner_id=work.owner,
        required_source_read_set=work.basis.required_source_read_set,
        source_basis_sha256="a" * 64,
        resolution_sha256="0" * 64,
    )
    resolved = resolved.model_copy(
        update={
            "resolution_sha256": digest(
                resolved.model_dump(mode="json", exclude={"resolution_sha256"})
            )
        }
    )
    return SimpleNamespace(
        id=uuid4(),
        revision=1,
        tenant_id=work.ctx.tenant_id,
        product_id=work.scope.product_id,
        project_id=work.scope.project_id,
        issue_id=work.basis.issue_id,
        issue_version_id=work.basis.issue_version_id,
        issue_revision=4,
        capa_id=work.basis.capa_id,
        action_id=work.basis.actions[0].action_id,
        basis_snapshot=work.basis.model_dump(mode="json"),
        output_snapshot=resolved.model_dump(mode="json"),
        basis_sha256=work.basis.basis_sha256,
        resolution_sha256=resolved.resolution_sha256,
        owner_id=work.owner,
        writer_id=work.owner,
        visibility="category",
        created_at=AT - timedelta(minutes=3),
        sources=[],
        required_source_read_set=[
            r.model_dump(mode="json") for r in work.basis.required_source_read_set
        ],
        reason="Fixed actual follow-up",
    ), resolved


def test_real_saved_link_dto_keeps_identity_clock_and_old_basis_not_resolution(work, monkeypatch):
    row, resolved = link_row(work)
    receipt = SimpleNamespace(id=uuid4(), operation=views.LINK, actor_id=row.writer_id)
    monkeypatch.setattr(views, "_receipt", lambda *args, **kwargs: receipt)
    monkeypatch.setattr(views.owners, "_link", lambda *args: resolved)
    session = SimpleNamespace(scalars=lambda query: [row])
    values, proofs, meta = REAL_LINKS(session, work.ctx, work.scope.product_id, work.selected)
    assert values[0]["id"] == str(row.id)
    assert values[0]["received_at"] == row.created_at.isoformat().replace("+00:00", "Z")
    assert values[0]["basis"] == work.basis.model_dump(mode="json")
    assert values[0]["output_refs"] == [resolved.outputs[0].ref.model_dump(mode="json")]
    assert "outputs" not in values[0] and len(proofs) == 1 and meta["unavailable_count"] == 0


def test_private_link_is_hidden_and_stale_visible_link_is_explicit_not_current(work, monkeypatch):
    row, _ = link_row(work)
    row.visibility, row.owner_id = "private", uuid4()
    session = SimpleNamespace(scalars=lambda query: [row])
    values, proofs, meta = REAL_LINKS(session, work.ctx, work.scope.product_id, work.selected)
    assert values == proofs == [] and meta["unavailable_count"] == 1
    row.visibility, row.owner_id = "category", work.owner
    monkeypatch.setattr(
        views,
        "_receipt",
        lambda *args, **kwargs: SimpleNamespace(
            id=uuid4(), operation=views.LINK, actor_id=row.writer_id
        ),
    )
    monkeypatch.setattr(
        views.owners,
        "_link",
        lambda *args: (_ for _ in ()).throw(DomainError("RECHECK_REQUIRED", "Old output changed")),
    )
    values, proofs, _ = REAL_LINKS(session, work.ctx, work.scope.product_id, work.selected)
    assert proofs == [] and values[0]["source_status"] == "needs_recheck"
    assert values[0]["reason_codes"] == ["RECHECK_REQUIRED"]


def test_saved_link_digest_or_scope_corruption_is_not_a_missing_candidate(work):
    row, _ = link_row(work)
    row.resolution_sha256 = "b" * 64
    error(
        "INTEGRITY_MISMATCH",
        lambda: views._saved_link(row, work.ctx, work.scope.product_id, work.selected),
    )
    row.project_id = uuid4()
    error(
        "FORBIDDEN_SCOPE",
        lambda: views._saved_link(row, work.ctx, work.scope.product_id, work.selected),
    )


def test_real_current_lookup_has_scoped_sql_and_does_not_borrow_history_acl(work, monkeypatch):
    monkeypatch.undo()
    row = SimpleNamespace(
        id=work.basis.issue_version_id,
        revision=4,
        project_id=work.scope.project_id,
        required_source_read_set=work.selected["required_source_read_set"],
    )
    pointer = SimpleNamespace(
        issue_version_id=row.id, issue_revision=4, project_id=work.scope.project_id
    )

    def scalar(query):
        assert {part.left.name: part.right.value for part in query._where_criteria} == {
            "tenant_id": work.ctx.tenant_id,
            "product_id": work.scope.product_id,
            "issue_id": work.basis.issue_id,
        }
        return pointer

    session = SimpleNamespace(scalar=scalar)
    monkeypatch.setattr(views.followup, "_row", lambda *args: row)
    checked = []
    monkeypatch.setattr(
        views, "source_basis", lambda *args: (checked.append(args[-1]) or [], False)
    )
    _, public = views._current(session, work.ctx, work.scope.product_id, work.basis.issue_id)
    assert public == {"version_id": str(row.id), "revision": 4} and len(checked) == 1
    monkeypatch.setattr(
        views.followup,
        "_row",
        lambda *args: (_ for _ in ()).throw(DomainError("FORBIDDEN_SCOPE", "Current private", 403)),
    )
    error(
        "FORBIDDEN_SCOPE",
        lambda: views._current(session, work.ctx, work.scope.product_id, work.basis.issue_id),
    )
