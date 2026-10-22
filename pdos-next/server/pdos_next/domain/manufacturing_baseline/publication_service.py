"""Actual phased named publication; common owns consumption and the atomic tail.

The material owner reads fixed originals. Professional authority, previous/Current
and the common false-to-true consumption remain independent checks. Publication
does not alter preparation drafts or grant asset/Pilot/manufacturing release.
"""

import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from uuid import UUID, uuid4

from pydantic import ValidationError
from pydantic_core import to_jsonable_python
from sqlalchemy import exists, select

from pdos_next.clock import proof_deadline_current
from pdos_next.contracts import Command, SourceRead
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.capa_effectiveness.facts import canonical_reads, json_value
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.professional_authority.signature_watermarks import signature_current
from pdos_next.domain.projects import service as projects
from pdos_next.domain.verification_front.service import _recheck
from pdos_next.errors import DomainError
from pdos_next.models import (
    Audit,
    Confirmation,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
    now,
)
from pdos_next.receipt_request_binding import readable_receipt_request_bound
from pdos_next.service import Context, digest, material_digest, require_access

from . import publication_rules as rules
from . import service as preparation
from .consumption import ConsumptionHost
from .publication_models import (
    ManufacturingBaselinePublication as Publication,
)
from .publication_models import (
    ManufacturingBaselinePublicationCurrent as Current,
)
from .publication_models import ManufacturingPublicationDocument as Document
from .publication_schemas import (
    EVENT,
    OPERATION,
    SCHEMA_VERSION,
    SUBJECT_TYPE,
    PublicationCurrent,
    PublicationDecision,
    PublicationPlan,
    PublicationReceipt,
    PublicationRecord,
    PublishPayload,
    VersionRef,
)
from .rules import require
from .schemas import Closed, RequiredRead, Revision

semantic = rules.semantic
category_lifecycle_fence = True
EVENTS = MappingProxyType({OPERATION: EVENT})
_CAPABILITY = object()


def _intent(ctx, command, payload):
    return digest(
        {
            "operation": OPERATION,
            "category": command.category_id,
            "product": command.product_id,
            "payload": semantic(payload),
            "named_actor": ctx.requester_id,
            "source_revision": None,
            "private_owner": ctx.requester_id if payload.visibility == "private" else None,
        }
    )


class SavedCommand(Closed):
    """Exact public command projection, deliberately excluding the private key."""

    command_id: UUID
    operation: str
    category_id: UUID
    product_id: UUID
    expected_revision: Revision
    source_read_set: tuple[SourceRead, ...]
    payload: dict


@dataclass(frozen=True)
class Runtime:
    owner: object
    consumption: ConsumptionHost
    module: object


def configure(engine):
    from .publication_material_owner import ActualPublicationMaterialOwner

    module = sys.modules[__name__]
    value = Runtime(
        ActualPublicationMaterialOwner(engine), ConsumptionHost({OPERATION: module}), module
    )
    engine._pdos_manufacturing_publication = value
    return value


def _runtime(s):
    value = getattr(s.get_bind(), "_pdos_manufacturing_publication", None)
    require(
        type(value) is Runtime and value.module is sys.modules[__name__],
        "INTEGRATION_REQUIRED",
        "制造基线发布的实际材料与共同消费端口尚未接通。",
        503,
    )
    return value


def _stamp(s):
    value = _runtime(s)
    return (
        id(value),
        id(getattr(value.owner.read, "__func__", value.owner.read)),
        id(getattr(value.owner.refresh, "__func__", value.owner.refresh)),
        preparation._runtime(s),
        id(_compose),
        id(_read_record),
        id(preparation._authority),
    )


def _command(ctx, command, product, payload, s):
    require(
        isinstance(ctx, Context)
        and ctx.actor_id == ctx.requester_id
        and ctx.run_id is None
        and ctx.agent_run_id is None,
        "NAMED_DECISION_REQUIRED",
        "制造基线发布须由当前有权的具名本人办理。",
        403,
    )
    require(
        isinstance(command, Command)
        and command.operation == OPERATION
        and type(payload) is PublishPayload
        and PublishPayload.model_validate(command.payload) == payload
        and command.category_id == ctx.category_id,
        "COMMAND_PAYLOAD_MISMATCH",
        "发布操作、范围或完整输入不能替换。",
        422,
    )
    preparation._persistent_product(s, ctx, command, product)
    require(
        product.category_id == ctx.category_id,
        "FORBIDDEN_SCOPE",
        "发布须使用实际型号所属品类。",
        403,
    )


def _pointer(s, ctx, pid, row, *, lock=False):
    query = select(Current).where(
        Current.tenant_id == ctx.tenant_id,
        Current.category_id == ctx.category_id,
        Current.product_id == pid,
        Current.project_id == row.project_id,
        Current.series_id == row.series_id,
    )
    query = query.execution_options(populate_existing=True, autoflush=False)
    value = s.scalar(query.with_for_update() if lock else query)
    if value is not None:
        require(
            value.owner_id == row.owner_id and value.visibility == row.visibility,
            "STORED_ATOM_MISMATCH",
            "发布Current的范围、属主或受众不能替换。",
            503,
        )
    return value


def _pointer_value(row, scope):
    return PublicationCurrent(
        scope=scope,
        category_id=row.category_id,
        series_id=row.series_id,
        owner_id=row.owner_id,
        visibility=row.visibility,
        version=VersionRef(id=row.version_id, revision=row.revision),
        epoch=row.epoch,
    )


def _row(s, ctx, pid, identity, revision=None):
    row = s.scalar(
        select(Publication)
        .where(
            Publication.tenant_id == ctx.tenant_id,
            Publication.category_id == ctx.category_id,
            Publication.product_id == pid,
            Publication.id == identity,
        )
        .execution_options(populate_existing=True, autoflush=False)
    )
    require(
        row is not None and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        "所选固定发布版本不可读取。",
        403,
    )
    require(
        revision is None or (type(revision) is int and row.revision == revision),
        "VERSION_CONFLICT",
        "所选发布版本不匹配。",
    )
    return row


def _saved_input(row):
    try:
        raw = row.input_snapshot
        command = SavedCommand.model_validate(raw["command"])
        payload = PublishPayload.model_validate(raw["semantic"])
        plan = PublicationPlan.model_validate(raw["plan"])
        previous_current = (
            PublicationCurrent.model_validate(raw["previous_current"])
            if raw["previous_current"] is not None
            else None
        )
        require(
            set(raw)
            == {"command", "original_key_sha256", "semantic", "plan", "review", "previous_current"}
            and isinstance(raw["review"], dict)
            and isinstance(raw["original_key_sha256"], str)
            and re.fullmatch(r"[a-f0-9]{64}", raw["original_key_sha256"]) is not None
            and "approval_token" not in command.payload
            and payload.approval_token is None
            and command.operation == row.operation == OPERATION
            and command.command_id == row.command_id
            and command.product_id == row.product_id
            and command.category_id == row.category_id
            and command.expected_revision == row.shared_proof_revision
            and command.payload == semantic(payload)
            and semantic(PublishPayload.model_validate(command.payload)) == semantic(payload)
            and semantic(payload) == plan.input_snapshot
            and plan.payload_sha256 == row.payload_sha256
            and plan.body == row.body
            and plan.body_sha256 == row.body_sha256
            and plan.scope.tenant_id == row.tenant_id
            and plan.category_id == row.category_id
            and plan.scope.product_id == row.product_id
            and plan.scope.project_id == row.project_id == payload.project_id
            and plan.owner_id == row.owner_id
            and plan.visibility == row.visibility == payload.visibility
            and plan.purpose == row.purpose == payload.purpose
            and (plan.baseline.id, plan.baseline.revision, plan.baseline.kind)
            == (row.baseline_id, row.baseline_revision, row.baseline_kind)
            and (plan.process.id, plan.process.revision) == (row.process_id, row.process_revision)
            and row.sources == [v.model_dump(mode="json") for v in plan.sources]
            and row.required_source_read_set
            == [v.model_dump(mode="json") for v in plan.required_source_read_set]
            and row.gaps == [v.model_dump(mode="json") for v in plan.gaps]
            and (row.previous_id, row.previous_revision)
            == (payload.previous_id, payload.expected_previous_revision)
            and row.status == "published"
            and row.write_tier == "T2",
            "STORED_ATOM_MISMATCH",
            "发布固定列、完整输入或实质预览不能核对。",
            503,
        )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise DomainError("STORED_ATOM_MISMATCH", "发布原始固定材料不完整。", 503) from error
    return command, payload, plan, previous_current


def _common_record(s, ctx, pid, row):
    command, payload, plan, previous_current = _saved_input(row)
    proof = s.get(Confirmation, row.shared_proof_id, populate_existing=True)
    writer = s.get(Principal, row.actor_id, populate_existing=True)
    receipt = s.scalar(
        select(Receipt)
        .where(
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.product_id == pid,
            Receipt.id == row.receipt_id,
        )
        .execution_options(populate_existing=True, autoflush=False)
    )
    author = Context(row.tenant_id, row.actor_id, row.actor_id, category_id=row.category_id)
    require(
        proof is not None
        and writer is not None
        and writer.tenant_id == row.tenant_id
        and writer.kind == "human"
        and receipt is not None
        and row.writer_id == row.actor_id == row.requester_id
        and proof.consumed is True
        and (
            proof.tenant_id,
            proof.product_id,
            proof.actor_id,
            proof.subject_id,
            proof.operation,
            proof.revision,
        )
        == (
            row.tenant_id,
            pid,
            row.actor_id,
            pid,
            OPERATION,
            row.shared_proof_revision,
        )
        and type(proof.revision) is int
        and proof.token_hash == row.token_sha256
        and proof.payload_digest == row.material_sha256
        and material_digest(author, command, payload, sys.modules[__name__]) == row.material_sha256
        and proof.expires_at == row.proof_expires_at
        and proof.created_at <= row.proof_consumed_at <= row.created_at
        and (proof.expires_at is None or row.created_at < proof.expires_at)
        and digest(proof.snapshot) == digest(row.input_snapshot["review"])
        and receipt.run_id is None
        and receipt.agent_run_id is None
        and receipt.request_digest == row.request_digest
        and receipt.intent_digest == row.intent_digest
        and row.intent_digest == _intent(author, command, payload)
        and digest([json_value(v) for v in canonical_reads(command.source_read_set)])
        == row.read_set_sha256,
        "STORED_ATOM_MISMATCH",
        "发布版本与实际共同消费、原具名人或固定预览不匹配。",
        503,
    )
    audits = list(
        s.scalars(
            select(Audit).where(Audit.tenant_id == ctx.tenant_id, Audit.receipt_id == receipt.id)
        )
    )
    events = list(
        s.scalars(
            select(Outbox).where(Outbox.tenant_id == ctx.tenant_id, Outbox.receipt_id == receipt.id)
        )
    )
    keys = list(
        s.scalars(
            select(RequestKey).where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.actor_id == row.actor_id,
                RequestKey.receipt_id == receipt.id,
                RequestKey.digest == row.request_digest,
            )
        )
    )
    bound = (
        sum(
            sha256(key.key.encode("utf-8")).hexdigest() == row.input_snapshot["original_key_sha256"]
            for key in keys
        )
        == 1
    )
    if not keys and receipt.actor_id != ctx.actor_id:
        bound = readable_receipt_request_bound(s, ctx, pid, receipt.id)
    require(
        len(audits) == len(events) == 1
        and audits[0].actor_id == row.actor_id
        and audits[0].operation == OPERATION
        and events[0].type == EVENT
        and events[0].actor_id == row.actor_id
        and events[0].subject_id == row.id
        and type(events[0].subject_revision) is int
        and events[0].subject_revision == row.revision
        and events[0].schema_version == 1
        and events[0].correlation_id == row.command_id
        and bound is True,
        "STORED_ATOM_INCOMPLETE",
        "发布缺同一原操作的审计、事件或实际请求关联。",
        503,
    )
    retained = _recheck(s, ctx, pid, row.project_id, row.authority_snapshot, at=row.created_at)
    require(
        retained.get("historical_valid") is True,
        "STORED_ATOM_MISMATCH",
        "原发布人的实际制造职责与用途资格不能核对。",
        503,
    )
    links = list(
        s.scalars(
            select(Document).where(
                Document.tenant_id == ctx.tenant_id,
                Document.category_id == ctx.category_id,
                Document.product_id == pid,
                Document.publication_id == row.id,
            )
        )
    )
    expected = {
        (v.operation_key, kind, ref.id, ref.revision)
        for v in plan.operations
        for kind in ("work_instruction", "control_plan")
        if (ref := getattr(v, kind)) is not None
    }
    require(
        len(links) == len(expected)
        and {(v.operation_key, v.document_kind, v.document_id, v.document_revision) for v in links}
        == expected
        and all(
            (v.project_id, v.publication_revision, v.process_id, v.process_revision)
            == (row.project_id, row.revision, row.process_id, row.process_revision)
            for v in links
        ),
        "STORED_CHILD_SET_MISMATCH",
        "发布的固定工序文档关系集合不能核对。",
        503,
    )
    result = PublicationRecord(
        ref=VersionRef(id=row.id, revision=row.revision),
        series_id=row.series_id,
        previous=plan.previous,
        plan=plan,
        actor_id=row.actor_id,
        created_at=row.created_at,
        decision=PublicationDecision(
            id=proof.id,
            scope=plan.scope,
            category_id=row.category_id,
            actor_id=row.actor_id,
            requester_id=row.requester_id,
            actor_kind="human",
            command_id=row.command_id,
            subject_id=pid,
            product_revision=row.shared_proof_revision,
            consumed_at=row.proof_consumed_at,
            expires_at=row.proof_expires_at,
            token_sha256=row.token_sha256,
            material_sha256=row.material_sha256,
            payload_sha256=row.payload_sha256,
            body_sha256=row.body_sha256,
            read_set_sha256=row.read_set_sha256,
        ),
        receipt=PublicationReceipt.model_validate(
            {name: getattr(receipt, name) for name in PublicationReceipt.model_fields}
        ),
        authority_snapshot=deepcopy(row.authority_snapshot),
        source_basis=deepcopy(row.source_basis),
    )
    return result, previous_current


def _read_record(s, ctx, pid, row):
    record, saved_current = _common_record(s, ctx, pid, row)
    previous = None
    if row.previous_id is not None:
        previous_row = _row(s, ctx, pid, row.previous_id, row.previous_revision)
        previous, _ = _common_record(s, ctx, pid, previous_row)
    rules.check_publication_record(
        record, record.plan, previous=previous, current=saved_current, at=now()
    )
    return record


def _view(row, plan, receipt_id, pointer, status):
    return {
        "schema_version": SCHEMA_VERSION,
        "id": str(row.id),
        "revision": row.revision,
        "series_id": str(row.series_id),
        "previous_id": str(row.previous_id) if row.previous_id else None,
        "previous_revision": row.previous_revision,
        "project_id": str(row.project_id),
        "owner_id": str(row.owner_id),
        "writer_id": str(row.writer_id),
        "visibility": row.visibility,
        "status": "published",
        "purpose": row.purpose,
        "body": deepcopy(plan.body),
        "gaps": [v.model_dump(mode="json") for v in plan.gaps],
        "process": plan.process.model_dump(mode="json"),
        "baseline": plan.baseline.model_dump(mode="json"),
        "receipt_id": str(receipt_id),
        "created_at": row.created_at.isoformat(),
        "is_current": pointer is not None
        and (pointer.version_id, pointer.revision) == (row.id, row.revision),
        "source_status": status,
        "sources": [v.model_dump(mode="json") for v in plan.sources],
        "required_source_read_set": [
            v.model_dump(mode="json") for v in plan.required_source_read_set
        ],
        "qualification": "unknown",
        "manufacturing_release": None,
    }


def _source_basis(s, ctx, pid, reads, plan, material_read):
    raw, private, _ = evidence._evidence(s, ctx, pid, reads, rules.source_refs(plan))
    require(
        not private or plan.visibility == "private",
        "FORBIDDEN_SCOPE",
        "私人原始材料不能扩大为共享发布。",
        403,
    )
    # Owner material contains native ORM UUIDs inside ordinary dictionaries.
    # Normalize only this persisted projection; the opaque owner read remains
    # unchanged and must still pass its actual same-UOW refresh checks.
    return to_jsonable_python(
        {
            "artifact_sources": [
                {"id": key, "status": "active", **deepcopy(raw[key])} for key in sorted(raw)
            ],
            "material_owner": deepcopy(material_read.source_basis),
        }
    )


def get_publication_fact(s, ctx, pid, publication_id, revision=None):
    """Read a signed immutable publication through its direct Current/watermarks.

    The T2 transaction established the reciprocal decision and fixed document
    links. A downstream T1 consumer keeps that signature and compares direct
    source metadata; it does not re-run publication preparation or requalify the
    original signer. The caller holds a model gate or a read snapshot.
    """
    from pdos_next.request_proof import snapshot_get, snapshot_scalar

    require_access(s, ctx, pid)
    row = snapshot_get(s, Publication, publication_id, scope_id=pid)
    require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid)
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        "所选固定发布版本不可读取。",
        403,
    )
    require(
        revision is None or row.revision == revision, "VERSION_CONFLICT", "所选发布版本不匹配。"
    )
    _, _, plan, _ = _saved_input(row)
    pointer = snapshot_scalar(
        s,
        (Current, row.series_id),
        select(Current).where(
            Current.tenant_id == ctx.tenant_id,
            Current.category_id == ctx.category_id,
            Current.product_id == pid,
            Current.project_id == row.project_id,
            Current.series_id == row.series_id,
        ),
        scope_id=pid,
    )
    from pdos_next.domain.projects.models import Project

    project = snapshot_get(s, Project, row.project_id, scope_id=pid)
    require(
        project is not None
        and (project.tenant_id, project.product_id) == (ctx.tenant_id, pid)
        and (project.visibility != "private" or project.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        "所选发布的实际项目不可读取。",
        403,
    )
    status = (
        "current"
        if (
            project.purpose == row.purpose
            and signature_current(s, ctx, pid, row.project_id, row.authority_snapshot)
        )
        else "needs_recheck"
    )
    try:
        raw, _, _ = evidence._evidence(
            s, ctx, pid, row.required_source_read_set, rules.source_refs(plan), io=False
        )
        actual = [{"id": key, "status": "active", **raw[key]} for key in sorted(raw)]
        if actual != row.source_basis.get("artifact_sources"):
            status = "needs_recheck"
    except DomainError as error:
        if error.status in {401, 403} or error.code not in {"SOURCE_STALE", "SOURCE_UNAVAILABLE"}:
            raise
        status = "needs_recheck"
    return row, _view(row, plan, row.receipt_id, pointer, status)


def get_publication(s, ctx, pid, publication_id, revision=None):
    return get_publication_fact(s, ctx, pid, publication_id, revision)


@dataclass(frozen=True)
class Bound:
    material_read: object
    plan: PublicationPlan
    reads: list
    basis: dict
    authority: dict
    authority_deadline: object
    project: object
    previous: object
    previous_record: PublicationRecord | None
    previous_view: dict | None
    current: PublicationCurrent | None
    runtime: tuple


def _compose(s, ctx, command, product, payload, material_read, *, retained_current=None):
    _command(ctx, command, product, payload, s)
    stamp = _stamp(s)
    project, _, _ = projects._project(s, ctx, product.id, payload.project_id)
    require(
        project.purpose == payload.purpose == material_read.material.baseline.purpose,
        "FORBIDDEN_SCOPE",
        "发布用途须对应实际项目及固定基线。",
        403,
    )
    previous, previous_record, previous_view, current = None, None, None, None
    if payload.previous_id is not None:
        previous = _row(s, ctx, product.id, payload.previous_id, payload.expected_previous_revision)
        previous_record = _read_record(s, ctx, product.id, previous)
        pointer = _pointer(s, ctx, product.id, previous)
        current = retained_current or (
            _pointer_value(pointer, previous_record.plan.scope) if pointer is not None else None
        )
        previous_view = _view(
            previous, previous_record.plan, previous.receipt_id, pointer, "current"
        )
    authority, deadline = preparation._authority(s, ctx, command, project)
    reads = configurations._merge_reads(
        [v.model_dump(mode="json") for v in material_read.required_source_read_set],
        authority["required_source_read_set"],
    )
    material = material_read.material.model_copy(
        update={"required_source_read_set": tuple(RequiredRead.model_validate(v) for v in reads)}
    )
    require(
        material.scope.tenant_id == ctx.tenant_id
        and material.scope.product_id == product.id
        and material.scope.project_id == project.id
        and material.category_id == product.category_id
        and material.product_revision == product.revision,
        "FORBIDDEN_SCOPE",
        "实际材料范围或型号水位不一致。",
        403,
    )
    plan = rules.prepare_publication(payload, material, previous=previous_record, current=current)
    basis = _source_basis(s, ctx, product.id, reads, plan, material_read)
    require_access(s, ctx, product.id)
    require(stamp == _stamp(s), "SOURCE_STALE", "材料读取期间发布owner或来源端口已变化。")
    preparation._deadline(authority, now(), deadline)
    return Bound(
        material_read,
        plan,
        reads,
        basis,
        authority,
        deadline,
        project,
        previous,
        previous_record,
        previous_view,
        current,
        stamp,
    )


def _load(s, ctx, command, product, payload, *, require_reads=True):
    _command(ctx, command, product, payload, s)
    captured, caller = _uow(s), digest(vars(ctx))
    with preparation._fresh_selects(s):
        material = _runtime(s).owner.read(s, ctx, product.id, payload)
        bound = _compose(s, ctx, command, product, payload, material)
    if require_reads:
        _reads(command, bound)
    _same_uow(s, captured, ctx, caller)
    return bound


def _reads(command, bound):
    require(
        configurations._merge_reads([v.model_dump(mode="json") for v in command.source_read_set])
        == bound.reads,
        "MISSING_REQUIRED_EVIDENCE",
        "发布须使用服务器核对的完整来源读集。",
        422,
    )


def _seal(bound):
    return digest(
        {
            "plan": bound.plan.model_dump(mode="json"),
            "reads": bound.reads,
            "basis": bound.basis,
            "authority": bound.authority,
            "deadline": bound.authority_deadline,
            "previous": bound.previous_record.model_dump(mode="json")
            if bound.previous_record
            else None,
            "current": bound.current.model_dump(mode="json") if bound.current else None,
            "runtime": bound.runtime,
        }
    )


def _cas(s, ctx, command, product, bound, *, published=None):
    require_access(s, ctx, product.id, write=True, lock=True)
    require(product.revision == command.expected_revision, "VERSION_CONFLICT", "型号水位已变化。")
    selected = published or bound.previous
    if selected is not None:
        pointer = _pointer(s, ctx, product.id, selected, lock=True)
        expected = (
            (published.id, published.revision)
            if published
            else (bound.previous.id, bound.previous.revision)
        )
        require(
            pointer is not None and (pointer.version_id, pointer.revision) == expected,
            "VERSION_CONFLICT",
            "保存时须对应本发布系列的真实Current。",
        )
        if published is None:
            require(
                _pointer_value(pointer, bound.plan.scope) == bound.current,
                "VERSION_CONFLICT",
                "发布Current的原水位已变化。",
            )
    else:
        pointer = None
    authority, deadline = preparation._authority(s, ctx, command, bound.project, write=True)
    require(
        digest(authority) == digest(bound.authority) and deadline == bound.authority_deadline,
        "RECHECK_REQUIRED",
        "当前具名人的制造职责、用途资格或来源已变化。",
    )
    return pointer


def _refresh(s, ctx, command, product, payload, bound, *, published=None):
    captured, caller = _uow(s), digest(vars(ctx))
    with preparation._fresh_selects(s):
        material = _runtime(s).owner.refresh(s, ctx, product.id, payload, bound.material_read)
        latest = _compose(
            s,
            ctx,
            command,
            product,
            payload,
            material,
            retained_current=bound.current if published is not None else None,
        )
        _reads(command, latest)
        require(
            _seal(latest) == _seal(bound), "RECHECK_REQUIRED", "发布固定材料或原审阅范围已变化。"
        )
        pointer = _cas(s, ctx, command, product, latest, published=published)
    _same_uow(s, captured, ctx, caller)
    return latest, pointer


def _review(payload, bound):
    return {
        "operation": OPERATION,
        "before": deepcopy(bound.previous_view),
        "after": {
            "id": None,
            "revision": bound.previous.revision + 1 if bound.previous else 1,
            "status": "published",
            "created_at": None,
            "time_policy": "server_on_save",
            "body": deepcopy(bound.plan.body),
        },
        "effect": "具名发布固定制造基线与工序资料；资产、试产及制造放行资格仍由实际业务核对。",
        "authority": deepcopy(bound.authority),
        "required_source_read_set": deepcopy(bound.reads),
        "read_basis": deepcopy(bound.basis),
        "reason": payload.reason,
        "gaps": [v.model_dump(mode="json") for v in bound.plan.gaps],
    }


class Prepared:
    def __init__(self, token, s, ctx, command, product, payload, bound):
        require(token is _CAPABILITY, "INVALID_PHASE", "缺实际发布准备阶段。", 503)
        self.session, self.uow, self.product = s, _uow(s), product
        self.ctx_sha, self.command_sha = digest(vars(ctx)), digest(command)
        self.payload_sha, self.bound, self.seal = digest(semantic(payload)), bound, _seal(bound)
        self.review = _review(payload, bound)
        self.review_sha, self.used = digest(self.review), False

    def __reduce__(self):
        raise TypeError("Publication phase stays in one actual transaction")

    def __copy__(self):
        raise TypeError("Publication phase is one-use")

    def __deepcopy__(self, memo):
        raise TypeError("Publication phase is one-use")


def _phase(s, ctx, command, product, payload, phase):
    require(
        type(phase) is Prepared
        and phase.session is s
        and phase.product is product
        and not phase.used,
        "INVALID_PHASE",
        "发布准备已使用或换事务。",
        503,
    )
    _same_uow(s, phase.uow, ctx, phase.ctx_sha)
    _command(ctx, command, product, payload, s)
    require(
        digest(command) == phase.command_sha
        and digest(semantic(payload)) == phase.payload_sha
        and _seal(phase.bound) == phase.seal
        and digest(phase.review) == phase.review_sha
        and phase.bound.runtime == _stamp(s),
        "PHASE_MATERIAL_CHANGED",
        "原命令、读集或实质发布材料被替换。",
        503,
    )


def validate(s, ctx, command, product, payload):
    with s.no_autoflush:
        _load(s, ctx, command, product, payload)


def prepare_preview(s, ctx, command, product, payload):
    with s.no_autoflush:
        bound = _load(s, ctx, command, product, payload)
        _cas(s, ctx, command, product, bound)
        return Prepared(_CAPABILITY, s, ctx, command, product, payload, bound)


def preview_prepared(s, ctx, command, product, payload, phase):
    _phase(s, ctx, command, product, payload, phase)
    phase.used = True
    with s.no_autoflush:
        latest, _ = _refresh(s, ctx, command, product, payload, phase.bound)
        return _review(payload, latest)


def preview_view(s, ctx, command, product, payload):
    phase = prepare_preview(s, ctx, command, product, payload)
    return preview_prepared(s, ctx, command, product, payload, phase)


def prepare_write_review(s, ctx, command, product, payload, proof=None):
    with s.no_autoflush:
        bound = _load(s, ctx, command, product, payload)
        bound, _ = _refresh(s, ctx, command, product, payload, bound)
        phase = Prepared(_CAPABILITY, s, ctx, command, product, payload, bound)
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


def _saved_command(command, payload):
    value = command.model_dump(mode="json")
    value.pop("idempotency_key")
    # Persist the already validated semantics, including declared schema
    # defaults. The original command stays intact for live/idempotent binding.
    value["payload"] = semantic(payload)
    return value


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    _phase(s, ctx, command, product, payload, phase)
    phase.used = True
    require(
        type(consumption) is tuple and len(consumption) == 2,
        "LIVE_CONSUMPTION_REQUIRED",
        "缺本次实际共同消费。",
        503,
    )
    binding, marker = consumption
    with s.no_autoflush:
        bound, pointer = _refresh(s, ctx, command, product, payload, phase.bound)
        _same_uow(s, phase.uow, ctx, phase.ctx_sha)
        require(bound.runtime == _stamp(s), "SOURCE_STALE", "末次owner核对期间运行端口变化。")
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
        saved_at = now()
        preparation._deadline(bound.authority, saved_at, bound.authority_deadline)
        require(
            live.tier == "T2"
            and live.consumed_at <= saved_at
            and proof_deadline_current("T2", live.expires_at, saved_at)
            and digest(binding.proof.snapshot) == phase.review_sha,
            "NAMED_DECISION_REQUIRED",
            "完整核对后的共同消费或有效期不再满足发布。",
        )
        identity, receipt_id = uuid4(), uuid4()
        previous, plan = bound.previous, bound.plan
        row = Publication(
            id=identity,
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            product_id=product.id,
            project_id=payload.project_id,
            series_id=previous.series_id if previous else identity,
            revision=previous.revision + 1 if previous else 1,
            previous_id=previous.id if previous else None,
            previous_revision=previous.revision if previous else None,
            owner_id=plan.owner_id,
            writer_id=ctx.actor_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            visibility=plan.visibility,
            purpose=plan.purpose,
            baseline_kind=plan.baseline.kind,
            baseline_id=plan.baseline.id,
            baseline_revision=plan.baseline.revision,
            process_id=plan.process.id,
            process_revision=plan.process.revision,
            status="published",
            operation=OPERATION,
            write_tier="T2",
            body=deepcopy(plan.body),
            body_sha256=plan.body_sha256,
            payload_sha256=plan.payload_sha256,
            input_snapshot={
                "command": _saved_command(command, payload),
                "semantic": semantic(payload),
                "original_key_sha256": sha256(command.idempotency_key.encode("utf-8")).hexdigest(),
                "plan": plan.model_dump(mode="json"),
                "review": deepcopy(phase.review),
                "previous_current": bound.current.model_dump(mode="json")
                if bound.current
                else None,
            },
            sources=[v.model_dump(mode="json") for v in plan.sources],
            required_source_read_set=deepcopy(bound.reads),
            source_basis=deepcopy(bound.basis),
            authority_snapshot=deepcopy(bound.authority),
            gaps=[v.model_dump(mode="json") for v in plan.gaps],
            command_id=command.command_id,
            receipt_id=receipt_id,
            request_digest=preparation._request_digest(command, payload),
            created_at=saved_at,
            **live.storage_columns(),
        )
        row.prepared_receipt_id, row.confirmation_id = receipt_id, live.proof_id
        row._publication_finalization = (phase, binding, marker, bound)
        s.add(row)
        s.flush([row])
        for item in plan.operations:
            for kind in ("work_instruction", "control_plan"):
                ref = getattr(item, kind)
                if ref is not None:
                    s.add(
                        Document(
                            id=uuid4(),
                            tenant_id=ctx.tenant_id,
                            category_id=ctx.category_id,
                            product_id=product.id,
                            project_id=payload.project_id,
                            publication_id=row.id,
                            publication_revision=row.revision,
                            process_id=row.process_id,
                            process_revision=row.process_revision,
                            operation_key=item.operation_key,
                            document_kind=kind,
                            document_id=ref.id,
                            document_revision=ref.revision,
                        )
                    )
        if pointer is None:
            s.add(
                Current(
                    id=uuid4(),
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    product_id=product.id,
                    project_id=payload.project_id,
                    series_id=row.series_id,
                    owner_id=row.owner_id,
                    visibility=row.visibility,
                    version_id=row.id,
                    revision=row.revision,
                    epoch=1,
                )
            )
        else:
            pointer.version_id, pointer.revision = row.id, row.revision
            pointer.epoch += 1
        return row, SUBJECT_TYPE, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    state = getattr(subject, "_publication_finalization", None)
    require(
        type(subject) is Publication and isinstance(state, tuple) and len(state) == 4,
        "INVALID_PHASE",
        "缺原共同尾部发布绑定。",
        503,
    )
    phase, binding, marker, bound = state
    try:
        require(
            phase.used
            and phase.session is s
            and phase.product is product
            and digest(command) == phase.command_sha
            and digest(semantic(payload)) == phase.payload_sha
            and _seal(phase.bound) == phase.seal
            and digest(phase.review) == phase.review_sha
            and receipt.id == subject.receipt_id == subject.prepared_receipt_id
            and receipt.confirmation_id == subject.shared_proof_id,
            "PHASE_MATERIAL_CHANGED",
            "共同回执或原实质预览已变化。",
            503,
        )
        _same_uow(s, phase.uow, ctx, phase.ctx_sha)
        latest, _ = _refresh(s, ctx, command, product, payload, bound, published=subject)
        _read_record(s, ctx, product.id, subject)
        require(latest.runtime == _stamp(s), "SOURCE_STALE", "共同尾部owner已变化。")
        _runtime(s).consumption.require_live(
            s,
            ctx,
            command,
            payload,
            sys.modules[__name__],
            binding.proof,
            binding=binding,
            marker=marker,
        )
        saved_at = now()
        preparation._deadline(latest.authority, saved_at, latest.authority_deadline)
        require(
            proof_deadline_current("T2", marker.expires_at, saved_at),
            "NAMED_DECISION_REQUIRED",
            "共同尾部实际有效期已到。",
        )
    finally:
        del subject._publication_finalization


def apply(*args, **kwargs):
    raise DomainError("PHASED_COMMON_INTEGRATION_REQUIRED", "须由共同事务具名消费后发布。", 503)


def replay_subject_type(payload):
    return SUBJECT_TYPE


def replay_subject(s, ctx, command, product, payload):
    intent = _intent(ctx, command, payload)
    row = s.scalar(
        select(Publication).where(
            Publication.tenant_id == ctx.tenant_id,
            Publication.category_id == ctx.category_id,
            Publication.product_id == product.id,
            Publication.actor_id == ctx.actor_id,
            Publication.operation == OPERATION,
            Publication.intent_digest == intent,
        )
    )
    if row is not None:
        get_publication(s, ctx, product.id, row.id, row.revision)
    return row


def inputs(s, ctx, pid, command):
    require(command.product_id == pid, "FORBIDDEN_SCOPE", "型号范围不一致。", 403)
    require_access(s, ctx, pid, write=True, lock=True)
    product = s.scalar(
        select(Product)
        .where(
            Product.tenant_id == ctx.tenant_id,
            Product.id == pid,
        )
        .with_for_update()
    )
    payload = PublishPayload.model_validate(command.payload)
    with s.no_autoflush:
        bound = _load(s, ctx, command, product, payload, require_reads=False)
        _cas(s, ctx, command, product, bound)
        updated = command.model_copy(
            update={"source_read_set": [SourceRead.model_validate(v) for v in bound.reads]}
        )
        bound, _ = _refresh(s, ctx, updated, product, payload, bound)
        return {"command": updated.model_dump(mode="json"), "review": _review(payload, bound)}


def list_publications(s, ctx, pid, *, project_id, history_cursor=None):
    from pdos_next.capa_history import page_query, page_rows

    require_access(s, ctx, pid)
    projects._project(s, ctx, pid, project_id)
    query = select(Publication).where(
        Publication.tenant_id == ctx.tenant_id,
        Publication.category_id == ctx.category_id,
        Publication.product_id == pid,
        Publication.project_id == project_id,
    )
    joined = (
        (Current.tenant_id == Publication.tenant_id)
        & (Current.category_id == Publication.category_id)
        & (Current.product_id == Publication.product_id)
        & (Current.project_id == Publication.project_id)
        & (Current.series_id == Publication.series_id)
        & (Current.version_id == Publication.id)
        & (Current.revision == Publication.revision)
    )
    current = list(s.scalars(query.join(Current, joined)))
    historical, page = page_rows(
        s.scalars(
            page_query(
                query.where(~exists(select(Current.id).where(joined))),
                Publication.created_at,
                Publication.id,
                "publication",
                history_cursor,
                kinds={"publication"},
            )
        ),
        "publication",
        kinds={"publication"},
    )
    versions, unavailable = [], 0
    for row in [*current, *historical]:
        try:
            _, view = get_publication(s, ctx, pid, row.id, row.revision)
        except DomainError as error:
            if error.status == 403:
                unavailable += 1
                continue
            raise
        versions.append(view)
    return {
        "schema_version": SCHEMA_VERSION,
        "versions": versions,
        "history_page": page,
        "has_more": bool(page["next_cursor"]),
        "unavailable_count": unavailable,
        "qualification": "unknown",
        "manufacturing_release": None,
    }
