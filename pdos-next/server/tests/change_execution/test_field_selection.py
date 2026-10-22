"""No-connect Field selection composition with explicit native-reader substitutes."""

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from pdos_next import change_controlled_owner as owner
from pdos_next import change_preparation_view as view
from pdos_next import change_selection_service as service
from pdos_next import field_change_selection as field
from pdos_next.change_controlled_schemas import (
    FieldIntentTarget,
    FieldSelectionMaterial,
    SelectionPayload,
)
from pdos_next.domain.change_control.rules import digest
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.schemas.change_control.contracts import Ref

from . import kernel_helpers as helper
from .test_controlled_change import no_connection, read_work  # noqa: F401 -- no-connect fixture


@pytest.fixture
def work(monkeypatch):
    value = read_work(monkeypatch)
    target = FieldIntentTarget(
        kind="field_intent",
        feedback={"id": uuid4(), "revision": 2},
        executor_id=helper.uid("executor"),
    )
    value.payload = SelectionPayload.model_validate(
        {**value.payload.model_dump(), "action": target, "valid_until": None}
    )
    value.cmd = value.cmd.model_copy(update={"payload": value.payload.model_dump(mode="json")})
    value.request.roots = (Ref(kind="field_feedback", **target.feedback.model_dump()),)
    value.request.title = "A fixed Field change"
    host = helper.FakeHost()
    host.analyze()
    value.request.assessments = host.request_value.assessments
    policy = owner.policy_callback()
    policy.required_disciplines = (value.payload.item.discipline, "manufacturing")
    record = SimpleNamespace(
        id=uuid4(),
        category_id=value.ctx.category_id,
        feedback_id=target.feedback.id,
        revision=2,
        owner_id=uuid4(),
        visibility="category",
        body_sha256="f" * 64,
        source_basis={"fixed-original": "actual-owner substitute"},
    )
    value.field_record = record
    value.reads = [{"artifact_id": str(helper.SOURCE.id), "expected_revision": 1}]
    value.port_calls = []

    def port(*args):
        value.port_calls.append(args)
        return (
            record,
            {
                "sources": [helper.SOURCE.model_dump(mode="json")],
                "required_source_read_set": value.reads,
            },
            helper.SCOPE,
            "actual purpose",
        )

    monkeypatch.setattr(field.field_bridge, "get", port)
    monkeypatch.setattr(
        field,
        "executor_options",
        lambda *a: [{"id": str(target.executor_id), "name": "Actual scoped executor substitute"}],
    )
    monkeypatch.setattr(owner, "action_basis", lambda *a: pytest.fail("No CAPA may be invented"))
    basis, _ = field.load_basis(
        value.s,
        value.ctx,
        value.cmd.product_id,
        target,
        value.payload.item,
        value.request,
        helper.SCOPE,
        "actual purpose",
        policy.nature,
    )
    value.material = field.material_for(
        value.ctx,
        value.request,
        value.payload.item,
        target,
        basis,
        status="applicable",
        valid_until=None,
        reason=value.payload.reason,
    )
    monkeypatch.setattr(owner, "original", lambda *a: (value.material, None))
    yield value
    value.s.close()


def test_field_read_and_noio_stage_preserve_real_feedback_and_future_intent(work, monkeypatch):
    work.port_calls.clear()
    phase, _ = service._read(work.s, work.ctx, work.cmd, work.payload, new_write=True)
    assert len(work.port_calls) == 2  # Initial AND post-all-IO complete native owner read.
    assert (
        phase.basis.owner_id != work.row.owner_id
    )  # Shared report need not be authored by planner.
    review = service.review(phase)
    assert len(review) == 13 and review["after"]["feedback_version_id"] == str(work.field_record.id)
    assert "issue_version_id" not in review["after"]
    assert review["selection"]["intent_sha256"] == digest(work.payload.item.intent)
    assert "action_sha256" not in review["selection"]
    at, proof_id = now(), uuid4()
    marker = SimpleNamespace(
        proof_id=proof_id,
        tier="T2",
        expires_at=None,
        storage_columns=lambda: {
            "shared_proof_id": proof_id,
            "shared_proof_revision": 1,
            "proof_consumed_at": at,
            "proof_expires_at": None,
            "token_sha256": "a" * 64,
            "material_sha256": "b" * 64,
            "read_set_sha256": "c" * 64,
        },
    )
    monkeypatch.setattr(work.s, "flush", lambda *a, **kw: pytest.fail("No stage IO"))
    atom = service._stage_without_io(work.s, work.ctx, work.cmd, phase, marker, at)
    assert atom.basis_kind == "field_intent" and atom.category_id == work.ctx.category_id
    assert atom.feedback_id == work.payload.action.feedback.id
    assert atom.feedback_version_id == work.field_record.id and atom.feedback_sha256 == "f" * 64
    assert atom.executor_id == work.payload.action.executor_id
    assert all(
        getattr(atom, key) is None
        for key in (
            "issue_id",
            "issue_version_id",
            "issue_revision",
            "capa_id",
            "action_id",
            "action_sha256",
        )
    )
    assert atom.intent_id == work.payload.item.intent.id and atom.valid_until is None
    assert "action_id" not in atom.action_result and atom.action_result["intent_id"] == str(
        atom.intent_id
    )
    assert atom.input_snapshot["review"] == review


@pytest.mark.parametrize("change", ["field_current", "executor", "root", "purpose"])
def test_field_plan_cannot_outlive_current_scoped_owner(work, monkeypatch, change):
    if change == "field_current":
        calls = []
        original = field.field_bridge.get

        def changed(*args):
            calls.append(1)
            if len(calls) > 1:
                raise DomainError("SOURCE_STALE", "Actual owner now reports a withdrawn source")
            return original(*args)

        monkeypatch.setattr(field.field_bridge, "get", changed)
    elif change == "executor":
        monkeypatch.setattr(field, "executor_options", lambda *a: [])
    elif change == "root":
        work.request.roots = ()
    else:
        original = field.field_bridge.get
        monkeypatch.setattr(
            field.field_bridge, "get", lambda *a: (*original(*a)[:3], "different purpose")
        )
    with pytest.raises(DomainError) as failure:
        service._read(work.s, work.ctx, work.cmd, work.payload, new_write=True)
    assert failure.value.reason in {
        "SOURCE_STALE",
        "FORBIDDEN_SCOPE",
        "ACTION_INTENT_SCOPE_MISMATCH",
    }
    assert not work.s.new


def test_private_field_plan_cannot_expand_report_audience(work):
    work.field_record.visibility = "private"
    with pytest.raises(DomainError) as failure:
        service._read(work.s, work.ctx, work.cmd, work.payload, new_write=True)
    assert failure.value.reason == "AUDIENCE_USE_FORBIDDEN"


def test_read_only_draft_builds_typed_registered_original_without_writing(work):
    data = view.SelectionMaterialInput(
        change_id=work.request.id,
        expected_change_revision=2,
        field_intent=work.payload.action,
        item=work.payload.item,
        status="applicable",
        valid_until=None,
        reason=work.payload.reason,
    )
    before = tuple(work.s.new)
    result = view._field_material_draft(
        work.s, work.ctx, work.cmd.product_id, work.row, work.request, "actual purpose", data
    )
    assert result["stage"] == "material_draft" and tuple(work.s.new) == before
    assert result["material"]["feedback_version_id"] == str(work.field_record.id)
    assert result["material"]["valid_until"] is None
    assert field.parse_material(json.loads(result["material_content"])) == work.material
    assert result["artifact_payload"]["content"] == result["material_content"]
    assert result["artifact_payload"]["visibility"] == work.row.visibility
    assert "command" not in result  # A draft itself is neither a decision nor an approved command.


@pytest.mark.parametrize("extra", ["qualified", "owner_id", "feedback_version_id", "issue_id"])
def test_field_intent_cannot_supply_owner_proof_or_mix_capa_fields(work, extra):
    raw = work.payload.action.model_dump(mode="json")
    raw[extra] = str(uuid4())
    with pytest.raises(ValidationError):
        FieldIntentTarget.model_validate(raw)


@pytest.mark.parametrize("revision", [True, "2", 2.0, 0, -1])
def test_field_ref_revision_is_strict(work, revision):
    raw = work.payload.model_dump(mode="json")
    raw["action"]["feedback"]["revision"] = revision
    with pytest.raises(ValidationError):
        SelectionPayload.model_validate(raw)


def test_source_and_future_plan_inputs_are_exactly_exclusive(work):
    raw = {
        "change_id": str(work.request.id),
        "expected_change_revision": 2,
        "field_intent": work.payload.action.model_dump(mode="json"),
        "item": work.payload.item.model_dump(mode="json"),
        "status": "unknown",
        "valid_until": None,
        "reason": "Explicit future intent",
    }
    assert view.SelectionMaterialInput.model_validate(raw).source is None
    for bad in (
        {**raw, "source": None},
        {**raw, "source": helper.SOURCE.model_dump(mode="json")},
        {"change_id": str(work.request.id), "expected_change_revision": 2},
    ):
        with pytest.raises(ValidationError):
            view.SelectionMaterialInput.model_validate(bad)


def test_legacy_material_roundtrip_keeps_v1_exact_json_and_no_field_keys(monkeypatch):
    legacy = read_work(monkeypatch)
    try:
        raw = legacy.material.model_dump(mode="json")
        assert field.parse_material(deepcopy(raw)).model_dump(mode="json") == raw
        assert "feedback" not in raw and "basis_kind" not in raw
        assert not isinstance(field.parse_material(raw), FieldSelectionMaterial)
    finally:
        legacy.s.close()


def test_executor_lookup_sql_uses_actual_tenant_category_human_and_active_membership():
    statements = []
    session = SimpleNamespace(execute=lambda statement: statements.append(statement) or [])
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    assert field.executor_options(session, ctx) == []
    sql = str(
        statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert str(ctx.tenant_id) in sql and str(ctx.category_id) in sql
    assert "grants.tenant_id = principals.tenant_id" in sql
    assert "principals.kind = 'human'" in sql and "principals.active IS true" in sql
    assert "grants.expires_at" in sql
