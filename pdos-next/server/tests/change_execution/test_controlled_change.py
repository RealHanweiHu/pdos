"""No-connect controls using actual DTO/ORM/consumer; SQL/source owners are explicit substitutes."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID as CategoryUUID
from uuid import uuid4

import httpx
import psycopg
import pytest
from pydantic import ValidationError
from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next import change_controlled_owner as owner
from pdos_next import change_controlled_store as store
from pdos_next import change_selection_service as service
from pdos_next.change_selection_consumption import ConsumptionHost
from pdos_next.contracts import Command
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution.graph import OwnedObject
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Product
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context, material_digest
from pdos_next.service import digest as common_digest

from . import kernel_helpers as helper


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def no(*args, **kwargs):
        raise AssertionError("Owned controls must never connect database or HTTP")

    for cls, name in ((Engine, "connect"), (Engine, "raw_connection"), (httpx.Client, "request")):
        monkeypatch.setattr(cls, name, no)
    monkeypatch.setattr(psycopg, "connect", no)


def rejected(code, callback):
    with pytest.raises(DomainError) as caught:
        callback()
    assert caught.value.reason == code


def proposal():
    item = (
        helper.plan()
        .items[0]
        .model_copy(
            update={
                "selection": helper.plan()
                .items[0]
                .selection.model_copy(
                    update={
                        "units": tuple(
                            f"object:{r.identity}" for r in helper.plan().items[0].selection.objects
                        )
                    }
                )
            }
        )
    )
    return store.SelectionPayload(
        change_id=helper.uid("request"),
        expected_change_revision=2,
        visibility="category",
        item=item,
        action=store.ActionTarget(
            issue_id=helper.uid("issue"),
            expected_issue_revision=4,
            capa_id=helper.uid("capa"),
            action_id=helper.uid("action"),
        ),
        status="applicable",
        source=helper.SOURCE,
        valid_until=datetime.now(UTC) + timedelta(hours=1),
        reason="Exact expert applicability proposal",
    )


@pytest.mark.parametrize(
    "field",
    [
        "qualified",
        "current",
        "scope",
        "issuer",
        "decision_id",
        "owner_proof",
        "policy",
        "action_sha256",
    ],
)
def test_public_selection_cannot_self_fill_server_authority(field):
    raw = proposal().model_dump(mode="json")
    raw[field] = True
    with pytest.raises(ValidationError):
        store.SelectionPayload.model_validate(raw)


@pytest.mark.parametrize("bad", [True, "2", 2.0, 0, -1])
def test_all_nested_revisions_are_strict(bad):
    raw = proposal().model_dump(mode="json")
    raw["action"]["expected_issue_revision"] = bad
    with pytest.raises(ValidationError):
        store.SelectionPayload.model_validate(raw)


def test_native_complete_policy_does_not_register_or_grant_publish_authority(monkeypatch):
    raw = dict(
        schema_version="pdos-controlled-change-policy-v1",
        scope=helper.SCOPE.model_dump(mode="json"),
        purpose="actual synthetic change",
        owner_id=str(helper.uid("maker")),
        visibility="category",
        publisher_id=str(helper.uid("publisher")),
        required_disciplines=["engineering", "manufacturing"],
        valid_from=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        valid_until=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        nature="synthetic",
    )
    line = json.dumps(raw)
    artifact = SimpleNamespace(
        id=helper.SOURCE.id,
        revision=1,
        original_id=None,
        content=line,
        content_hash=common_digest(line),
    )
    source = SourceRef(
        id=artifact.id,
        revision=1,
        kind="artifact",
        position=f"line:1;quote_sha256:{hashlib.sha256(line.encode()).hexdigest()}",
    )
    monkeypatch.setattr(owner, "source_for", lambda *a: artifact)
    calls = []
    monkeypatch.setattr(
        owner.old,
        "_native_registration",
        lambda *a: calls.append("actual-registration-owner-substitute"),
    )
    value, _ = owner.original(None, None, helper.SCOPE.product_id, source, store.PolicyMaterial)
    assert value.publisher_id == helper.uid("publisher") and calls
    assert not hasattr(value, "qualified") and not hasattr(value, "owner_proof")

    def missing(*a, **kw):
        raise DomainError("INTEGRATION_REQUIRED", "Publisher matrix absent", 503)

    monkeypatch.setattr(owner.old, "_authority", missing)
    rejected(
        "INTEGRATION_REQUIRED",
        lambda: owner.authority(
            None, None, helper.SCOPE.product_id, helper.SCOPE, store.POLICY_OPERATION, value.purpose
        ),
    )


@pytest.mark.parametrize(
    "line",
    [
        '{"schema_version":"a","schema_version":"b"}',
        '{"schema_version":NaN}',
        '{"qualified":true}',
        "{}",
    ],
)
def test_source_body_duplicates_constants_and_missing_binding_do_not_publish(line, monkeypatch):
    artifact = SimpleNamespace(
        id=helper.SOURCE.id,
        revision=1,
        original_id=None,
        content=line,
        content_hash=common_digest(line),
    )
    source = SourceRef(
        id=artifact.id,
        revision=1,
        kind="artifact",
        position=f"line:1;quote_sha256:{hashlib.sha256(line.encode()).hexdigest()}",
    )
    monkeypatch.setattr(owner, "source_for", lambda *a: artifact)
    monkeypatch.setattr(owner.old, "_native_registration", lambda *a: {})
    rejected(
        "MISSING_REQUIRED_EVIDENCE",
        lambda: owner.original(None, None, None, source, store.PolicyMaterial),
    )


def test_uploaded_material_requires_original_owner_not_artifact_text(monkeypatch):
    monkeypatch.setattr(owner, "source_for", lambda *a: SimpleNamespace(original_id=uuid4()))
    rejected(
        "CONTROLLED_ORIGINAL_OWNER_REQUIRED",
        lambda: owner.original(None, None, None, helper.SOURCE, store.PolicyMaterial),
    )


def test_scope_unit_strings_do_not_imply_actual_batch_serial_coverage():
    item = proposal().item
    units = owner.exact_units(item)
    assert {v.object_identity for v in units} == {v.identity for v in item.selection.objects}
    for token in ("batch:original-batch", "serial:actual-serial"):
        altered = item.model_copy(
            update={"selection": item.selection.model_copy(update={"units": (token,)})}
        )
        rejected("CHANGE_UNIT_OWNER_REQUIRED", lambda altered=altered: owner.exact_units(altered))
    altered = item.model_copy(
        update={"selection": item.selection.model_copy(update={"units": (f"object:{uuid4()}",)})}
    )
    rejected("SELECTION_SCOPE_MISMATCH", lambda: owner.exact_units(altered))


def test_new_series_cannot_skip_existing_current_and_nullable_previous_cannot_bypass():
    prior = SimpleNamespace(id=uuid4(), revision=2, epoch=2)
    rejected("VERSION_CONFLICT", lambda: owner.previous(object(), prior, None, None))
    assert owner.previous(object(), prior, prior.id, 2) == (3, 3)
    assert owner.previous(None, None, None, None) == (1, 1)
    constraints = [
        v
        for v in store.ChangeSelectionFact.__table__.constraints
        if isinstance(v, ForeignKeyConstraint)
    ]
    parent = next(v for v in constraints if v.referred_table.name == "quality_issue_versions")
    assert [v.parent.name for v in parent.elements] == [
        "tenant_id",
        "product_id",
        "project_id",
        "issue_id",
        "issue_version_id",
        "issue_revision",
    ]
    assert any(
        "previous_id IS NOT NULL" in str(v.sqltext)
        for v in store.ChangeSelectionFact.__table__.constraints
        if hasattr(v, "sqltext")
    )


def test_unconfigured_selection_runtime_is_explicit_missing():
    s = Session(bind=SimpleNamespace())
    rejected("CONTROLLED_SELECTION_INTEGRATION_REQUIRED", lambda: service.runtime(s))
    s.close()


def test_host_publication_without_common_tail_cannot_stage_any_record(monkeypatch):
    from pdos_next import service as common

    monkeypatch.delitem(common.EVENTS, store.POLICY_OPERATION)

    class NoRead:
        def __getattr__(self, name):
            raise AssertionError("Missing host tail must fail before SQL or mutation")

    payload = store.PolicyImport(
        project_id=helper.SCOPE.project_id,
        purpose="actual policy purpose",
        source=helper.SOURCE,
        reason="Controlled publication",
    )
    rejected(
        "CONTROLLED_PUBLICATION_TAIL_REQUIRED",
        lambda: owner.import_policy(
            NoRead(), None, helper.SCOPE.product_id, payload, command_id=uuid4(), request_key="k"
        ),
    )


def test_canonical_typed_semantic_preserves_full_material_not_token_or_hash():
    first = proposal()
    token = first.model_copy(update={"approval_token": "named-proof-token-123456789"})
    assert service.semantic(first) == service.semantic(token)
    assert service.semantic(first)["action"]["expected_issue_revision"] == 4
    assert "approval_token" not in service.semantic(first)
    assert owner.same({"x": 1}, {"x": True}) is False
    assert owner.same({"x": 1}, {"x": 1.0}) is False


def actual_consumption():
    p = proposal().model_copy(update={"approval_token": "selection-token-1234567890"})
    ctx = Context(
        helper.SCOPE.tenant_id,
        helper.uid("engineer"),
        helper.uid("engineer"),
        category_id=CategoryUUID(int=1000000),
    )
    cmd = Command(
        command_id=uuid4(),
        idempotency_key="exact-selection-key",
        operation=service.OPERATION,
        product_id=helper.SCOPE.product_id,
        expected_revision=8,
        source_read_set=[{"artifact_id": helper.SOURCE.id, "expected_revision": 1}],
        payload=p.model_dump(mode="json"),
        category_id=CategoryUUID(int=1000000),
    )
    s = Session(bind=SimpleNamespace())
    s.begin()
    now = datetime.now(UTC)
    proof = Confirmation(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=cmd.product_id,
        actor_id=ctx.actor_id,
        subject_id=cmd.product_id,
        operation=cmd.operation,
        revision=cmd.expected_revision,
        token_hash=common_digest(p.approval_token),
        payload_digest=material_digest(ctx, cmd, p, service),
        snapshot={"actual": "selection-review"},
        created_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        consumed=False,
    )
    make_transient_to_detached(proof)
    s.add(proof)
    host = ConsumptionHost({service.OPERATION: service})
    return s, ctx, cmd, p, proof, host


def test_real_named_uuid_capture_is_first_action_no_sql_and_not_historical_true(monkeypatch):
    s, ctx, cmd, p, proof, host = actual_consumption()
    monkeypatch.setattr(
        s, "flush", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("hook SQL prohibited"))
    )
    bound = host.bind_before_transition(
        s, ctx, cmd, p, service, proof, reviewed_snapshot=proof.snapshot
    )
    proof.consumed = True
    marker = host.capture_after_transition(s, ctx, cmd, p, service, proof, binding=bound)
    assert marker.proof_id == proof.id and marker.tier == "T2"
    assert host.require_live(s, ctx, cmd, p, service, proof, binding=bound, marker=marker) is marker
    proof.snapshot = {"modified": "review"}
    rejected(
        "FACT_CONSUMPTION_MATERIAL_CHANGED",
        lambda: host.require_live(s, ctx, cmd, p, service, proof, binding=bound, marker=marker),
    )
    s.close()
    s, ctx, cmd, p, proof, host = actual_consumption()
    proof.consumed = True
    rejected(
        "FACT_UNCONSUMED_MATERIAL_BINDING_REQUIRED",
        lambda: host.bind_before_transition(
            s, ctx, cmd, p, service, proof, reviewed_snapshot=proof.snapshot
        ),
    )
    s.close()


def read_work(monkeypatch):
    p = proposal()
    ctx = Context(
        helper.SCOPE.tenant_id,
        helper.uid("engineer"),
        helper.uid("engineer"),
        category_id=CategoryUUID(int=1000000),
    )
    s = Session(bind=SimpleNamespace())
    s.begin()
    service.configure(s.get_bind())
    row = SimpleNamespace(
        id=uuid4(),
        change_id=p.change_id,
        project_id=helper.SCOPE.project_id,
        owner_id=helper.uid("maker"),
        visibility="category",
        revision=2,
        request_sha256="b" * 64,
        required_source_read_set=[],
    )
    request = SimpleNamespace(
        id=p.change_id,
        status="analysis",
        roots=(),
        references=(),
        scope=helper.SCOPE,
        sources=(helper.SOURCE,),
        audience=(f"product:{helper.SCOPE.product_id}",),
    )
    current = SimpleNamespace(id=uuid4())
    action = SimpleNamespace(
        action_id=p.action.action_id, action_sha256="a" * 64, executor_id=helper.uid("maker")
    )
    basis = SimpleNamespace(
        issue_id=p.action.issue_id,
        issue_version_id=uuid4(),
        issue_revision=4,
        capa_id=p.action.capa_id,
        nature="synthetic",
        owner_id=row.owner_id,
        visibility=row.visibility,
        sources=(helper.SOURCE,),
        required_source_read_set=[],
    )
    policyrow = SimpleNamespace(id=uuid4(), revision=1)
    policy = SimpleNamespace(
        source=helper.SOURCE,
        nature="synthetic",
        valid_until=p.valid_until,
        required_source_read_set=[],
        model_dump=lambda **kw: {"original_policy": "bounded"},
    )
    material = store.SelectionMaterial(
        schema_version="pdos-controlled-change-selection-v1",
        scope=helper.SCOPE,
        purpose="actual purpose",
        change_id=request.id,
        item=p.item,
        issue_id=basis.issue_id,
        capa_id=basis.capa_id,
        action_id=action.action_id,
        action_sha256=action.action_sha256,
        executor_id=action.executor_id,
        decider_id=ctx.actor_id,
        status=p.status,
        valid_until=p.valid_until,
        reason=p.reason,
        nature=basis.nature,
    )
    fixed = {"actual immutable object": "complete source/owner substitute"}
    sourcebasis = {"actual": "security metadata substitute"}
    auth = {
        "authorized": True,
        "qualified": True,
        "synthetic": True,
        "roles": [p.item.discipline],
        "required_source_read_set": [],
    }
    product = SimpleNamespace(revision=8)
    monkeypatch.setattr(
        service, "_one", lambda s, cls, *a, **kw: product if cls is Product else row
    )
    monkeypatch.setattr(service, "snapshot", lambda *a: request)
    monkeypatch.setattr(service, "current_fixed", lambda *a, **kw: (current, row))
    monkeypatch.setattr(
        owner, "_caller", lambda *a, **kw: ("actual current caller substitute", p.valid_until)
    )
    monkeypatch.setattr(owner, "_project", lambda *a: (None, "actual current project substitute"))
    monkeypatch.setattr(owner.old, "_runtime_stamp", lambda *a: "runtime-stable")
    monkeypatch.setattr(owner.old, "_seed", lambda *a: (helper.SCOPE, "actual purpose"))
    monkeypatch.setattr(owner, "policy_callback", lambda *a, **kw: policy)
    monkeypatch.setattr(owner, "policy_pointer", lambda *a, **kw: (None, policyrow))
    monkeypatch.setattr(owner, "action_basis", lambda *a: (basis, action))
    monkeypatch.setattr(owner, "_current_issue_revision", lambda *a: 4)
    monkeypatch.setattr(owner, "original", lambda *a: (material, None))
    monkeypatch.setattr(owner, "objects", lambda *a: (deepcopy(fixed), [], (helper.SOURCE,)))
    monkeypatch.setattr(owner, "authority", lambda *a: (deepcopy(auth), p.valid_until))
    monkeypatch.setattr(owner, "selection_pointer", lambda *a, **kw: (None, None))
    monkeypatch.setattr(owner, "_source_guard", lambda *a, **kw: deepcopy(sourcebasis))
    cmd = Command(
        command_id=uuid4(),
        idempotency_key="actual-selection-key",
        operation=service.OPERATION,
        product_id=helper.SCOPE.product_id,
        expected_revision=8,
        source_read_set=[{"artifact_id": helper.SOURCE.id, "expected_revision": 1}],
        payload=p.model_dump(mode="json"),
        category_id=CategoryUUID(int=1000000),
    )
    return SimpleNamespace(
        s=s,
        ctx=ctx,
        cmd=cmd,
        payload=p,
        row=row,
        request=request,
        pointer=current,
        action=action,
        basis=basis,
        material=material,
        product=product,
    )


def test_actual_dto_read_to_noio_orm_stage_keeps_action_intent_and_named_group_fields(monkeypatch):
    work = read_work(monkeypatch)
    phase, _ = service._read(work.s, work.ctx, work.cmd, work.payload, new_write=True)
    saved = service.review(phase)
    assert len(saved) == 13 and saved["selection"]["action_sha256"] == work.action.action_sha256
    assert "graph coverage" not in saved["after"]
    json.dumps(saved, allow_nan=False)
    _, ctx, cmd, p, proof, host = actual_consumption()
    # A real persistent consumption control is exercised separately above;
    # this ORM construction test uses its actual marker-shaped fields only.
    bound = host.bind_before_transition(
        proof._sa_instance_state.session,
        ctx,
        cmd,
        p,
        service,
        proof,
        reviewed_snapshot=proof.snapshot,
    )
    proof.consumed = True
    marker = host.capture_after_transition(
        proof._sa_instance_state.session, ctx, cmd, p, service, proof, binding=bound
    )
    monkeypatch.setattr(
        work.s,
        "flush",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("stage flush prohibited")),
    )
    atom = service._stage_without_io(work.s, work.ctx, work.cmd, phase, marker, datetime.now(UTC))
    assert atom.action_id == work.payload.action.action_id
    assert atom.intent_id == work.payload.item.intent.id
    assert atom.shared_proof_id == marker.proof_id
    assert atom.confirmation_material_sha256 == marker.material_sha256
    assert atom.material_sha256 == digest(work.material)
    assert atom.input_snapshot["review"] == saved
    assert atom.input_snapshot["shared_proof"] == {"id": str(marker.proof_id), "tier": "T2"}
    pointer = next(v for v in work.s.new if isinstance(v, store.ChangeSelectionCurrent))
    assert pointer.fact_id == atom.id and pointer.owner_id == work.row.owner_id
    assert len([v for v in work.s.new if isinstance(v, Confirmation)]) == 0
    work.s.close()
    proof._sa_instance_state.session.close()


@pytest.mark.parametrize("change", ["action", "source", "authority", "runtime"])
def test_post_all_io_refresh_rejects_changed_owner_source_or_runtime(change, monkeypatch):
    work = read_work(monkeypatch)
    calls = [0]
    if change == "action":

        def action(*a):
            calls[0] += 1
            return (
                work.basis,
                work.action if calls[0] == 1 else SimpleNamespace(action_sha256="c" * 64),
            )

        monkeypatch.setattr(owner, "action_basis", action)
    elif change == "source":
        monkeypatch.setattr(
            owner,
            "_source_guard",
            lambda *a, io=True, **kw: {"actual": "old" if io else "withdrawn"},
        )
    elif change == "authority":

        def authority(*a):
            calls[0] += 1
            return (
                {
                    "roles": [work.payload.item.discipline],
                    "synthetic": True,
                    "required_source_read_set": [],
                    "epoch": calls[0],
                },
                work.payload.valid_until,
            )

        monkeypatch.setattr(owner, "authority", authority)
    else:

        def runtime(*a):
            calls[0] += 1
            return calls[0]

        monkeypatch.setattr(owner.old, "_runtime_stamp", runtime)
    rejected(
        "SOURCE_STALE",
        lambda: service._read(work.s, work.ctx, work.cmd, work.payload, new_write=True),
    )
    assert len(work.s.new) == 0
    work.s.close()


def test_current_cas_is_newwrite_only_but_replay_still_rechecks_owner(monkeypatch):
    work = read_work(monkeypatch)
    freshrow = SimpleNamespace(**{**work.row.__dict__, "id": uuid4(), "revision": 3})
    monkeypatch.setattr(service, "current_fixed", lambda *a, **kw: (work.pointer, freshrow))
    rejected(
        "VERSION_CONFLICT",
        lambda: service._read(work.s, work.ctx, work.cmd, work.payload, new_write=True),
    )
    phase, _ = service._read(work.s, work.ctx, work.cmd, work.payload, new_write=False)
    assert phase.row.id == work.row.id and phase.current_revision == 3
    monkeypatch.setattr(
        owner,
        "_source_guard",
        lambda *a, **kw: (_ for _ in ()).throw(
            DomainError("SOURCE_UNAVAILABLE", "Actual original withdrawn", 409)
        ),
    )
    rejected(
        "SOURCE_UNAVAILABLE",
        lambda: service._read(work.s, work.ctx, work.cmd, work.payload, new_write=False),
    )
    work.s.close()


def test_product_watermark_precedes_new_current_mutation_but_replay_keeps_old_command(monkeypatch):
    work = read_work(monkeypatch)
    work.product.revision = 9
    rejected(
        "VERSION_CONFLICT",
        lambda: service._read(work.s, work.ctx, work.cmd, work.payload, new_write=True),
    )
    assert len(work.s.new) == 0
    phase, _ = service._read(work.s, work.ctx, work.cmd, work.payload, new_write=False)
    assert phase.row is work.row
    work.s.close()


def test_future_professional_activation_during_sql_cannot_cross_end_clock(monkeypatch):
    start = datetime.now(UTC)
    now = [start]
    monkeypatch.setattr(owner, "clock", lambda: now[0])
    monkeypatch.setattr(
        owner.old,
        "_authority",
        lambda *a, **kw: {
            "fact_refs": [{"id": str(uuid4()), "revision": 1}],
            "valid_until": (start + timedelta(hours=1)).isoformat(),
        },
    )
    future = SimpleNamespace(
        valid_from=start + timedelta(seconds=1), valid_until=start + timedelta(hours=1)
    )

    class Read:
        def scalars(self, query):
            now[0] += timedelta(seconds=2)
            return [future]

    ctx = Context(
        helper.SCOPE.tenant_id,
        helper.uid("engineer"),
        helper.uid("engineer"),
        category_id=CategoryUUID(int=1000000),
    )
    rejected(
        "SOURCE_STALE",
        lambda: owner.authority(
            Read(), ctx, helper.SCOPE.product_id, helper.SCOPE, service.OPERATION, "actual purpose"
        ),
    )


def test_approved_action_owner_final_io_cannot_outlive_original_approver_deadline(monkeypatch):
    work = read_work(monkeypatch)
    start = datetime.now(UTC)
    now = [start]
    monkeypatch.setattr(owner, "clock", lambda: now[0])
    order = SimpleNamespace(
        id=uuid4(),
        plan=SimpleNamespace(items=(work.payload.item,), expires_at=work.payload.valid_until),
        approvals=(SimpleNamespace(expires_at=work.payload.valid_until),),
    )
    request = SimpleNamespace(
        id=work.payload.change_id, scope=helper.SCOPE, roots=(), references=(), orders=(order,)
    )
    monkeypatch.setattr(owner, "current_fixed", lambda *a, **kw: (work.pointer, work.row))
    monkeypatch.setattr(owner, "snapshot", lambda *a: request)
    monkeypatch.setattr(owner, "approved_order", lambda *a: start + timedelta(seconds=1))
    monkeypatch.setattr(
        owner,
        "selection_callback",
        lambda *a, **kw: SimpleNamespace(valid_until=work.payload.valid_until),
    )
    monkeypatch.setattr(
        owner,
        "selection_pointer",
        lambda *a, **kw: (None, SimpleNamespace(material=work.material.model_dump(mode="json"))),
    )

    def caller(*a, **kw):
        now[0] = start + timedelta(seconds=2)
        return "current caller", work.payload.valid_until

    monkeypatch.setattr(owner, "_caller", caller)
    rejected(
        "SOURCE_STALE",
        lambda: owner.ApprovedActionIntentOwner().read(
            work.s,
            work.ctx,
            work.cmd.product_id,
            change_id=request.id,
            order_id=order.id,
            item_id=work.payload.item.id,
            action_id=work.payload.action.action_id,
        ),
    )
    assert len(work.s.new) == 0
    work.s.close()


def test_real_ownedobject_shape_uses_fixed_view_reads_and_scope_not_undefined_dto(monkeypatch):
    p = proposal()
    object_value = OwnedObject(
        p.item.selection.objects[0],
        "fixed",
        helper.SCOPE,
        helper.uid("maker"),
        "product",
        {"actual_configuration": "fixed"},
        [{"artifact_id": str(helper.SOURCE.id), "expected_revision": 1}],
        {"security": 3},
        True,
    )

    class Reader:
        def __init__(self, *a):
            pass

        def resolve(self, ref):
            return object_value

    monkeypatch.setattr(owner, "OwnerReader", Reader)
    monkeypatch.setattr(owner.old, "_issue_loader", lambda *a: object())
    request = SimpleNamespace(scope=helper.SCOPE, audience=("product",))
    fixed, reads, sources = owner.objects(None, None, helper.SCOPE.product_id, request, p.item)
    assert next(iter(fixed.values()))[
        "view"
    ] == object_value.view and reads == object_value.reads * len(
        (*p.item.selection.objects, *p.item.intent.basis)
    )
    assert object_value.source in sources
