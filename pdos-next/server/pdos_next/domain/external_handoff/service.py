"""Actual handoff authorization and controlled receipt recording, with no network IO.

One named common T2 creates the authorization, fixed intent and initial Current.
Each trusted original adds one receipt and advances that Current atomically.
"""

import sys
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from pydantic_core import to_jsonable_python
from sqlalchemy import inspect, select

from pdos_next.contracts import Command, SourceRead
from pdos_next.database import require_context
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.manufacturing_baseline.consumption import ConsumptionHost
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.signature_watermarks import signature_current
from pdos_next.domain.projects.models import Project
from pdos_next.domain.release.rules import digest as body_digest
from pdos_next.errors import DomainError
from pdos_next.models import Product, now
from pdos_next.request_proof import snapshot_get, snapshot_scalar
from pdos_next.service import command_digest, digest, require_access

from . import rules
from .constants import AUTHORIZE, RECEIPT_RECORD
from .models import ExternalDeliveryIntent as Intent
from .models import ExternalHandoffAuthorization as Authorization
from .models import ExternalHandoffCurrent as Current
from .models import ExternalReceipt as Receipt
from .models import delivery_intent_snapshot, initial_projection, projection_snapshot
from .schemas import (
    AuthorizationPlan,
    AuthorizePayload,
    ReceiptActualData,
    ReceiptFact,
    ReceiptPlan,
    ReceiptRecordPayload,
)

PAYLOADS = {AUTHORIZE: AuthorizePayload, RECEIPT_RECORD: ReceiptRecordPayload}
semantic = rules.semantic
category_lifecycle_fence = True
_CAPABILITY = object()


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


@dataclass(frozen=True)
class Runtime:
    owner: object
    evidence_owner: object
    consumption: ConsumptionHost


def configure(engine):
    from .evidence_owner import ActualHandoffEvidenceOwner
    from .material_owner import ActualHandoffMaterialOwner

    engine._pdos_external_handoff = Runtime(
        ActualHandoffMaterialOwner(engine),
        ActualHandoffEvidenceOwner(engine),
        ConsumptionHost({AUTHORIZE: sys.modules[__name__]}),
    )


def _runtime(s):
    value = getattr(s.get_bind(), "_pdos_external_handoff", None)
    _require(type(value) is Runtime, "移交实际读取端尚未接通。", "INTEGRATION_REQUIRED", 503)
    return value


def _command(s, ctx, command, product, payload):
    require_context(s, ctx)
    state = inspect(product, raiseerr=False)
    _require(
        isinstance(command, Command)
        and command.operation in PAYLOADS
        and type(payload) is PAYLOADS[command.operation]
        and PAYLOADS[command.operation].model_validate(command.payload) == payload
        and command.category_id == ctx.category_id,
        "命令、完整载荷与实际品类不匹配。",
        "COMMAND_PAYLOAD_MISMATCH",
        422,
    )
    _require(
        isinstance(product, Product)
        and state is not None
        and state.persistent
        and state.session is s
        and (product.tenant_id, product.category_id, product.id)
        == (ctx.tenant_id, ctx.category_id, command.product_id),
        "须使用本次实际型号。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(command.expected_revision == product.revision, "型号版本已变化。", "VERSION_CONFLICT")
    if command.operation == AUTHORIZE:
        _require(
            ctx.actor_id == ctx.requester_id and ctx.run_id is None and ctx.agent_run_id is None,
            "外部移交授权须由当前具名本人决定。",
            "NAMED_DECISION_REQUIRED",
            403,
        )


def _project(s, ctx, pid, identity):
    require_access(s, ctx, pid)
    row = snapshot_get(s, Project, identity, scope_id=pid)
    _require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid)
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "所选项目不可读取。",
        "FORBIDDEN_SCOPE",
        403,
    )
    return row


def _row(s, ctx, pid, identity, revision=None):
    require_access(s, ctx, pid)
    row = snapshot_get(s, Authorization, identity, scope_id=pid)
    _require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid)
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "所选移交授权不可读取。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(revision is None or row.revision == revision, "移交授权版本不符。", "VERSION_CONFLICT")
    plan = AuthorizationPlan.model_validate(row.body)
    _require(
        digest(row.body) == row.body_sha256
        and plan.scope.tenant_id == row.tenant_id
        and plan.scope.product_id == row.product_id
        and plan.scope.project_id == row.project_id
        and plan.category_id == row.category_id
        and plan.declaration.visibility == row.visibility
        and row.status == "authorized",
        "移交授权的实际内容绑定不完整。",
        "INTEGRITY_MISMATCH",
        503,
    )
    return row, plan


def _pointer(s, ctx, pid, handoff_id, *, lock=False):
    query = select(Current).where(
        Current.tenant_id == ctx.tenant_id,
        Current.category_id == ctx.category_id,
        Current.product_id == pid,
        Current.handoff_id == handoff_id,
    )
    if lock:
        return s.scalar(query.with_for_update().execution_options(populate_existing=True))
    return snapshot_scalar(s, (Current, handoff_id), query, scope_id=pid)


def _pointer_value(row):
    return (
        {
            "id": str(row.id),
            "handoff": {"id": str(row.handoff_id), "revision": row.handoff_revision},
            "intent": {"id": str(row.intent_id), "revision": row.intent_revision},
            "receipt_count": row.receipt_count,
            "latest_receipt": {
                "id": str(row.latest_receipt_id),
                "revision": row.latest_receipt_revision,
            }
            if row.latest_receipt_id
            else None,
            "epoch": row.epoch,
            "projection_sha256": row.projection_sha256,
        }
        if row is not None
        else None
    )


def _intent_row(s, ctx, pid, authorization, pointer):
    row = snapshot_get(s, Intent, pointer.intent_id, scope_id=pid)
    _require(
        row is not None
        and (
            row.tenant_id,
            row.category_id,
            row.product_id,
            row.project_id,
            row.owner_id,
            row.visibility,
            row.handoff_id,
            row.handoff_revision,
        )
        == (
            authorization.tenant_id,
            authorization.category_id,
            authorization.product_id,
            authorization.project_id,
            authorization.owner_id,
            authorization.visibility,
            authorization.id,
            authorization.revision,
        )
        and row.revision == pointer.intent_revision
        and digest(row.body) == row.body_sha256
        and row.authorization_sha256 == authorization.body_sha256
        and row.receipt_id == authorization.receipt_id
        and row.command_id == authorization.command_id,
        "移交发送意图须绑定原授权及同一共同事务。",
        "INTEGRITY_MISMATCH",
        503,
    )
    return row


def _history(s, ctx, pid, authorization, intent):
    result = []
    for row in s.scalars(
        select(Receipt)
        .where(
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.category_id == ctx.category_id,
            Receipt.product_id == pid,
            Receipt.handoff_id == authorization.id,
            Receipt.intent_id == intent.id,
        )
        .order_by(Receipt.sequence)
    ):
        plan = ReceiptPlan.model_validate(row.body)
        _require(
            row.sequence == len(result) + 1
            and digest(row.body) == row.body_sha256
            and plan.original.model_dump(mode="json") == row.original
            and plan.source.model_dump(mode="json") == row.source
            and plan.issuer is not None
            and plan.issuer.model_dump(mode="json") == row.issuer_snapshot,
            "移交回执原件顺序或固定内容不完整。",
            "INTEGRITY_MISMATCH",
            503,
        )
        result.append(
            ReceiptFact(
                id=row.id,
                revision=row.revision,
                original=plan.original,
                source=plan.source,
                issuer=plan.issuer,
                received_at=plan.received_at,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class Bound:
    material: object
    basis: dict
    candidate: object
    reads: tuple
    authority: dict
    diagnostics: tuple
    authorization: object = None
    intent: object = None
    pointer: dict | None = None
    history: tuple = ()


def _receipt_audience(authorization, read):
    private = any(
        value.get("visibility") == "private" or value.get("original_visibility") == "private"
        for value in read.source_basis["artifact_sources"].values()
    )
    _require(
        not private or authorization.visibility == "private",
        "私人回执原件不能扩大为共享移交记录。",
        "FORBIDDEN_SCOPE",
        403,
    )


def _load(s, ctx, command, product, payload, *, require_reads=True):
    _command(s, ctx, command, product, payload)
    runtime = _runtime(s)
    authorization, intent, pointer, history, authority = None, None, None, (), {}
    if command.operation == AUTHORIZE:
        read = runtime.owner.read(s, ctx, product.id, payload)
        material = read.actual
        candidate = rules.prepare(payload, material, ctx=ctx, at=now())
        basis = {
            "material_owner": deepcopy(read.source_basis),
            "artifact_sources": deepcopy(read.source_basis["artifact_sources"]),
        }
        authority = professional.assess(
            s, ctx, product.id, payload.project_id, AUTHORIZE, payload.purpose, now(), write=True
        )
    else:
        authorization, plan = _row(s, ctx, product.id, payload.handoff.id, payload.handoff.revision)
        pointer = _pointer(s, ctx, product.id, authorization.id, lock=True)
        _require(pointer is not None, "移交当前状态缺失。", "INTEGRITY_MISMATCH", 503)
        intent = _intent_row(s, ctx, product.id, authorization, pointer)
        _require(
            (intent.id, intent.revision) == (payload.intent.id, payload.intent.revision),
            "须登记原授权对应的发送意图。",
            "VERSION_CONFLICT",
        )
        read = runtime.evidence_owner.read_receipt(
            s, ctx, product.id, payload.source, project_id=authorization.project_id
        )
        _receipt_audience(authorization, read)
        _require(
            read.source_basis.get("scope") == plan.scope.model_dump(mode="json")
            and read.source_basis.get("category_id") == str(ctx.category_id),
            "回执issuer证明不属于所选实际移交项目。",
            "FORBIDDEN_SCOPE",
            403,
        )
        material = ReceiptActualData(
            scope=plan.scope,
            category_id=ctx.category_id,
            handoff=payload.handoff,
            intent=payload.intent,
            authorization=plan,
            authorized=True,
            source=payload.source,
            original=read.original,
            issuer=read.issuer,
            issuer_current=read.issuer_current,
            sources_current=read.sources_current,
            sources=read.sources,
            required_source_read_set=read.required_source_read_set,
        )
        history = _history(s, ctx, product.id, authorization, intent)
        _require(
            len(history) == pointer.receipt_count,
            "实际回执与Current数量不符。",
            "INTEGRITY_MISMATCH",
            503,
        )
        candidate = rules.prepare_receipt(payload, material, history=history, at=now())
        basis = {
            "artifact_sources": deepcopy(read.source_basis["artifact_sources"]),
            "receipt_evidence": deepcopy(read.source_basis),
            "previous_current": _pointer_value(pointer),
        }
    reads = {value.artifact_id: value for value in read.required_source_read_set}
    if authority:
        extra = []
        for raw in authority.get("required_source_read_set", ()):
            value = SourceRead.model_validate(raw)
            _require(
                value.artifact_id not in reads or reads[value.artifact_id] == value,
                "同一原件不能使用两个版本。",
            )
            if value.artifact_id not in reads:
                extra.append(value)
                reads[value.artifact_id] = value
        authority_basis, private, _ = (
            evidence._evidence(
                s, ctx, product.id, [v.model_dump(mode="json") for v in extra], (), io=True
            )
            if extra
            else ({}, False, None)
        )
        _require(
            not private or payload.visibility == "private",
            "私有授权依据不能扩大共享。",
            "FORBIDDEN_SCOPE",
            403,
        )
        basis.setdefault("artifact_sources", {}).update(to_jsonable_python(authority_basis))
        basis["authority_originals"] = {
            "reads": [v.model_dump(mode="json") for v in extra],
            "basis": to_jsonable_python(authority_basis),
        }
    reads = tuple(sorted(reads.values(), key=lambda value: str(value.artifact_id)))
    candidate = candidate.model_copy(update={"required_source_read_set": reads})
    if require_reads:
        _require(
            {(v.artifact_id, v.expected_revision) for v in command.source_read_set}
            == {(v.artifact_id, v.expected_revision) for v in reads},
            "须提交本次实际最小来源读集。",
            "RECHECK_REQUIRED",
        )
    return Bound(
        material,
        basis,
        candidate,
        reads,
        authority,
        tuple(getattr(read, "gaps", ())),
        authorization,
        intent,
        _pointer_value(pointer),
        history,
    )


def _review(command, bound):
    candidate = bound.candidate.model_dump(mode="json")
    candidate["prepared_at" if command.operation == AUTHORIZE else "received_at"] = None
    return {
        "operation": command.operation,
        "before": deepcopy(bound.pointer),
        "after": candidate,
        "authority": deepcopy(bound.authority),
        "required_source_read_set": [v.model_dump(mode="json") for v in bound.reads],
        "read_basis": deepcopy(bound.basis),
        "diagnostics": list(bound.diagnostics),
    }


def _bound_digest(bound):
    return digest(
        {
            "material": bound.material,
            "basis": bound.basis,
            "candidate": bound.candidate,
            "reads": bound.reads,
            "authority": bound.authority,
            "diagnostics": bound.diagnostics,
            "authorization": str(bound.authorization.id) if bound.authorization else None,
            "intent": str(bound.intent.id) if bound.intent else None,
            "pointer": bound.pointer,
            "history": bound.history,
        }
    )


class Prepared:
    def __init__(self, token, s, ctx, command, product, payload, bound):
        _require(token is _CAPABILITY, "缺本次移交准备。", "INVALID_PHASE", 503)
        self.session, self.product, self.uow = s, product, _uow(s)
        self.ctx_sha, self.command_sha = digest(vars(ctx)), digest(command)
        self.payload_sha, self.bound = digest(semantic(payload)), bound
        self.review = _review(command, bound)
        self.review_sha, self.runtime, self.used = digest(self.review), _runtime(s), False
        self.bound_sha = _bound_digest(bound)

    def __reduce__(self):
        raise TypeError("Handoff preparation stays in its actual transaction")


def _phase(s, ctx, command, product, payload, phase, *, used=False):
    _require(
        type(phase) is Prepared
        and phase.session is s
        and phase.product is product
        and phase.runtime is _runtime(s)
        and phase.used is used
        and phase.command_sha == digest(command)
        and phase.payload_sha == digest(semantic(payload))
        and phase.review_sha == digest(phase.review)
        and phase.bound_sha == _bound_digest(phase.bound),
        "本次移交命令、材料或准备事务已改变。",
        "INVALID_PHASE",
        503,
    )
    _same_uow(s, phase.uow, ctx, phase.ctx_sha)


def validate(s, ctx, command, product, payload):
    return Prepared(
        _CAPABILITY, s, ctx, command, product, payload, _load(s, ctx, command, product, payload)
    )


prepare_preview = validate


def preview_prepared(s, ctx, command, product, payload, phase):
    _phase(s, ctx, command, product, payload, phase)
    phase.used = True
    return deepcopy(phase.review)


def preview_view(s, ctx, command, product, payload):
    return preview_prepared(
        s, ctx, command, product, payload, prepare_preview(s, ctx, command, product, payload)
    )


def prepare_write_review(s, ctx, command, product, payload, proof=None):
    _require(command.operation == AUTHORIZE, "只有具名授权消费T2。")
    phase = validate(s, ctx, command, product, payload)
    rules.require_authorizable(phase.bound.candidate)
    auth = phase.bound.authority
    _require(
        auth.get("authorized") is True and auth.get("qualified") is True,
        "本人的当前职责与移交用途资格不足。",
        "QUALIFICATION_REQUIRED",
        403,
    )
    return phase, deepcopy(phase.review)


def bind_consumption(s, ctx, command, product, payload, phase, proof):
    _phase(s, ctx, command, product, payload, phase)
    return _runtime(s).consumption.bind_before_transition(
        s, ctx, command, payload, sys.modules[__name__], proof, reviewed_snapshot=phase.review
    )


def record_consumption(s, ctx, command, product, payload, phase, proof, binding):
    marker = _runtime(s).consumption.capture_after_transition(
        s, ctx, command, payload, sys.modules[__name__], proof, binding=binding
    )
    _phase(s, ctx, command, product, payload, phase)
    return marker


def _saved_input(command, payload, phase):
    value = command.model_dump(mode="json")
    value.pop("idempotency_key")
    value["payload"] = semantic(payload)
    return {
        "command": value,
        "semantic": semantic(payload),
        "review": deepcopy(phase.review),
        "original_key_sha256": sha256(command.idempotency_key.encode()).hexdigest(),
    }


def _intent_digest(ctx, command, payload):
    return digest(
        {
            "operation": command.operation,
            "category": ctx.category_id,
            "product": command.product_id,
            "payload": semantic(payload),
            "named_actor": ctx.requester_id,
            "source_revision": None,
            "private_owner": ctx.requester_id
            if getattr(payload, "visibility", "private") == "private"
            else None,
        }
    )


def _still_current(s, ctx, pid, bound, *, written=None):
    runtime = _runtime(s)
    if isinstance(bound.material, ReceiptActualData):
        current = runtime.evidence_owner.current(s, ctx, pid, bound.basis["receipt_evidence"])
        pointer = _pointer(s, ctx, pid, bound.authorization.id, lock=True)
        expected = bound.pointer
        if written is None:
            _require(
                _pointer_value(pointer) == expected, "移交回执序列已变化。", "VERSION_CONFLICT"
            )
        else:
            _require(
                pointer is not None
                and pointer.latest_receipt_id == written.id
                and pointer.receipt_count == written.sequence,
                "本次回执未推进同一Current。",
                "VERSION_CONFLICT",
            )
    else:
        current = runtime.owner.current(
            s, ctx, pid, bound.material, source_basis=bound.basis["material_owner"]
        )
    _require(current is True, "移交直接原件、当前对象或issuer水位已变化。", "RECHECK_REQUIRED")
    extra = bound.basis.get("authority_originals")
    if extra and extra["reads"]:
        actual, _, _ = evidence._evidence(s, ctx, pid, extra["reads"], (), io=False)
        _require(
            to_jsonable_python(actual) == extra["basis"],
            "本次职责原件水位变化。",
            "RECHECK_REQUIRED",
        )
    if bound.authority:
        _require(
            signature_current(s, ctx, pid, bound.material.scope.project_id, bound.authority)
            and professional.authority_time_current(bound.authority, now()),
            "本次具名移交职责或资格水位变化。",
            "QUALIFICATION_REQUIRED",
            403,
        )


def _columns(ctx, command, product, payload, phase, *, owner_id, visibility):
    bound = phase.bound
    return dict(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        project_id=bound.material.scope.project_id,
        revision=1,
        owner_id=owner_id,
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        visibility=visibility,
        operation=command.operation,
        body=bound.candidate.model_dump(mode="json"),
        body_sha256=body_digest(bound.candidate),
        material_snapshot=bound.material.model_dump(mode="json"),
        input_snapshot=_saved_input(command, payload, phase),
        source_basis=deepcopy(bound.basis),
        required_source_read_set=[v.model_dump(mode="json") for v in bound.reads],
        sources=[v.model_dump(mode="json") for v in bound.candidate.sources],
        command_id=command.command_id,
        receipt_id=uuid4(),
        request_digest=command_digest(command),
        **(
            {"intent_digest": _intent_digest(ctx, command, payload)}
            if command.operation == RECEIPT_RECORD
            else {}
        ),
        network_send=False,
        created_at=now(),
    )


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    _phase(s, ctx, command, product, payload, phase)
    _require(command.operation == AUTHORIZE, "只有移交授权消费具名T2。")
    bound = phase.bound
    _still_current(s, ctx, product.id, bound)
    candidate = rules.require_authorizable(bound.candidate)
    binding, marker = consumption
    live = _runtime(s).consumption.require_live(
        s,
        ctx,
        command,
        payload,
        sys.modules[__name__],
        binding.proof,
        binding=binding,
        marker=marker,
    )
    phase.used = True
    row = Authorization(
        **_columns(
            ctx,
            command,
            product,
            payload,
            phase,
            owner_id=ctx.requester_id,
            visibility=payload.visibility,
        ),
        write_tier="T2",
        status="authorized",
        purpose=payload.purpose,
        package_id=payload.package.id,
        package_revision=payload.package.revision,
        engineering_decision_id=payload.engineering_decision.id,
        engineering_decision_revision=payload.engineering_decision.revision,
        manufacturing_decision_id=payload.manufacturing_decision.id,
        manufacturing_decision_revision=payload.manufacturing_decision.revision,
        manifest_sha256=candidate.manifest_sha256,
        mappings_sha256=candidate.mappings_sha256,
        content_sha256=candidate.content_sha256,
        authority_snapshot=deepcopy(bound.authority),
        **live.storage_columns(),
    )
    # The child INSERT policies resolve this real parent inside the same transaction.
    s.add(row)
    s.flush([row])
    packet = delivery_intent_snapshot({"id": str(row.id), "revision": row.revision}, candidate)
    intent = Intent(
        id=uuid4(),
        tenant_id=row.tenant_id,
        category_id=row.category_id,
        product_id=row.product_id,
        project_id=row.project_id,
        owner_id=row.owner_id,
        visibility=row.visibility,
        handoff_id=row.id,
        handoff_revision=row.revision,
        revision=1,
        status="authorized",
        body=packet,
        body_sha256=digest(packet),
        authorization_sha256=row.body_sha256,
        destination=payload.destination.model_dump(mode="json"),
        external_id=payload.external_id,
        manifest_sha256=row.manifest_sha256,
        mappings_sha256=row.mappings_sha256,
        content_sha256=row.content_sha256,
        command_id=row.command_id,
        receipt_id=row.receipt_id,
        network_send=False,
        created_at=row.created_at,
    )
    s.add(intent)
    s.flush([intent])
    projection = initial_projection()
    s.add_all(
        [
            Current(
                id=uuid4(),
                tenant_id=row.tenant_id,
                category_id=row.category_id,
                product_id=row.product_id,
                project_id=row.project_id,
                owner_id=row.owner_id,
                visibility=row.visibility,
                handoff_id=row.id,
                handoff_revision=row.revision,
                intent_id=intent.id,
                intent_revision=1,
                receipt_count=0,
                latest_receipt_id=None,
                latest_receipt_revision=None,
                epoch=1,
                projection=projection,
                projection_sha256=digest(projection),
                created_at=row.created_at,
            ),
        ]
    )
    row.prepared_receipt_id, row.confirmation_id, row._handoff_phase = (
        row.receipt_id,
        live.proof_id,
        phase,
    )
    return row, "external_handoff", row.visibility


def apply_validated(s, ctx, command, product, payload, phase):
    _phase(s, ctx, command, product, payload, phase)
    _require(
        command.operation == RECEIPT_RECORD,
        "移交授权须经本人具名T2。",
        "NAMED_DECISION_REQUIRED",
        403,
    )
    bound = phase.bound
    _still_current(s, ctx, product.id, bound)
    candidate = rules.require_recordable(bound.candidate)
    phase.used = True
    pointer = _pointer(s, ctx, product.id, bound.authorization.id, lock=True)
    original = candidate.original
    row = Receipt(
        **_columns(
            ctx,
            command,
            product,
            payload,
            phase,
            owner_id=bound.authorization.owner_id,
            visibility=bound.authorization.visibility,
        ),
        handoff_id=bound.authorization.id,
        handoff_revision=bound.authorization.revision,
        intent_id=bound.intent.id,
        intent_revision=bound.intent.revision,
        sequence=pointer.receipt_count + 1,
        previous_receipt_id=pointer.latest_receipt_id,
        previous_receipt_revision=pointer.latest_receipt_revision,
        previous_sequence=pointer.receipt_count if pointer.receipt_count else None,
        write_tier="T0",
        status="recorded",
        original=original.model_dump(mode="json"),
        source=candidate.source.model_dump(mode="json"),
        issuer_snapshot=candidate.issuer.model_dump(mode="json"),
        stage=original.stage,
        outcome=original.outcome,
        destination=original.destination.model_dump(mode="json"),
        external_id=original.external_id,
        external_receipt_id=original.external_receipt_id,
        manifest_sha256=original.manifest_sha256,
        release_scope=original.release_scope.model_dump(mode="json"),
        occurred_at=original.occurred_at,
        received_at=candidate.received_at,
        reconciles_id=original.reconciles.id if original.reconciles else None,
        reconciles_revision=original.reconciles.revision if original.reconciles else None,
    )
    fact = ReceiptFact(
        id=row.id,
        revision=row.revision,
        original=original,
        source=candidate.source,
        issuer=candidate.issuer,
        received_at=candidate.received_at,
    )
    projection = projection_snapshot(
        rules.fold(
            handoff=payload.handoff,
            intent=payload.intent,
            authorization=bound.material.authorization,
            receipts=(*bound.history, fact),
        )
    )
    row.projection_after, row.projection_sha256 = projection, digest(projection)
    s.add(row)
    # Current's immediate guard sees this actual receipt before its CAS update.
    s.flush([row])
    pointer.receipt_count, pointer.latest_receipt_id, pointer.latest_receipt_revision = (
        row.sequence,
        row.id,
        row.revision,
    )
    pointer.epoch, pointer.projection, pointer.projection_sha256 = (
        row.sequence + 1,
        projection,
        row.projection_sha256,
    )
    row.prepared_receipt_id, row._handoff_phase = row.receipt_id, phase
    return row, "external_receipt", row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    phase = getattr(subject, "_handoff_phase", None)
    _phase(s, ctx, command, product, payload, phase, used=True)
    _require(subject.receipt_id == receipt.id, "缺本事务移交共同回执。", "INVALID_PHASE", 503)
    _still_current(s, ctx, product.id, phase.bound, written=subject)
    del subject._handoff_phase


def _header(row, pointer):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "project_id": str(row.project_id),
        "purpose": row.purpose,
        "package": {"id": str(row.package_id), "revision": row.package_revision},
        "visibility": row.visibility,
        "created_at": row.created_at.isoformat(),
        "receipt_id": str(row.receipt_id),
        "as_of": _pointer_value(pointer),
        "reading": deepcopy(pointer.projection) if pointer else None,
        "network_send": False,
    }


def get_handoff(s, ctx, pid, identity):
    row, plan = _row(s, ctx, pid, identity)
    pointer = _pointer(s, ctx, pid, row.id)
    _require(
        pointer is not None and digest(pointer.projection) == pointer.projection_sha256,
        "移交Current或投影摘要缺失。",
        "INTEGRITY_MISMATCH",
        503,
    )
    intent = _intent_row(s, ctx, pid, row, pointer)
    try:
        current = _runtime(s).owner.current(
            s,
            ctx,
            pid,
            row.material_snapshot,
            source_basis=row.source_basis["material_owner"],
        )
    except DomainError as error:
        if error.status in {401, 403} or error.code not in {
            "SOURCE_STALE",
            "RECHECK_REQUIRED",
            "SOURCE_UNAVAILABLE",
            "VERSION_CONFLICT",
        }:
            raise
        current = False
    return row, {
        **_header(row, pointer),
        "authorization": plan.model_dump(mode="json"),
        "authority": deepcopy(row.authority_snapshot),
        "intent": {
            "id": str(intent.id),
            "revision": intent.revision,
            "packet": deepcopy(intent.body),
        },
        "applicability": "current" if current is True else "needs_recheck",
    }


def list_handoffs(s, ctx, pid, *, project_id, history_cursor=None):
    _project(s, ctx, pid, project_id)
    query = select(Authorization).where(
        Authorization.tenant_id == ctx.tenant_id,
        Authorization.category_id == ctx.category_id,
        Authorization.product_id == pid,
        Authorization.project_id == project_id,
    )
    if history_cursor is not None:
        from uuid import UUID

        try:
            query = query.where(Authorization.id < UUID(history_cursor))
        except ValueError as error:
            raise DomainError("SOURCE_STALE", "移交分页位置无效。", 422) from error
    rows = list(s.scalars(query.order_by(Authorization.id.desc()).limit(21)))
    return {
        "items": [_header(row, _pointer(s, ctx, pid, row.id)) for row in rows[:20]],
        "next_cursor": str(rows[19].id) if len(rows) > 20 else None,
    }


def list_receipts(s, ctx, pid, identity, *, before_sequence=None):
    row, _ = _row(s, ctx, pid, identity)
    pointer = _pointer(s, ctx, pid, row.id)
    query = select(Receipt).where(
        Receipt.tenant_id == ctx.tenant_id, Receipt.product_id == pid, Receipt.handoff_id == row.id
    )
    if before_sequence is not None:
        _require(
            type(before_sequence) is int and before_sequence > 0,
            "回执分页序列无效。",
            "VALIDATION_FAILED",
            422,
        )
        query = query.where(Receipt.sequence < before_sequence)
    rows = list(s.scalars(query.order_by(Receipt.sequence.desc()).limit(21)))
    return {
        "as_of": _pointer_value(pointer),
        "items": [
            {
                "id": str(value.id),
                "revision": value.revision,
                "sequence": value.sequence,
                "original": deepcopy(value.original),
                "source": deepcopy(value.source),
                "issuer": deepcopy(value.issuer_snapshot),
                "mismatches": value.body["mismatches"],
                "receipt_id": str(value.receipt_id),
                "received_at": value.received_at.isoformat(),
            }
            for value in rows[:20]
        ],
        "before_sequence": rows[19].sequence if len(rows) > 20 else None,
    }


def inputs(s, ctx, pid, command):
    require_access(s, ctx, pid, write=True, lock=True)
    product = s.get(Product, pid)
    _require(
        command.product_id == pid and command.operation in PAYLOADS,
        "请选择当前型号的移交操作。",
        "FORBIDDEN_SCOPE",
        403,
    )
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    bound = _load(s, ctx, command, product, payload, require_reads=False)
    return to_jsonable_python(
        {
            "operation": command.operation,
            "payload": payload.model_dump(mode="json"),
            "required_source_read_set": bound.reads,
            "candidate": bound.candidate,
            "authority": bound.authority,
            "diagnostics": bound.diagnostics,
        }
    )
