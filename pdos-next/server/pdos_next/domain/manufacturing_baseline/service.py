"""Controlled T1 manufacturing preparation owner, not a manufacturing release.

Common owns Product/Command locks, Confirmation False -> True, Receipt,
Audit, Outbox, RequestKey and COMMIT; saved preparation versions remain draft.
"""

import sys
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import event, exists, inspect, select

from pdos_next.contracts import Command, SourceRead
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.capa_effectiveness.facts import canonical_reads, json_value
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.preproject.baseline import validate_sources
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.projects import service as projects
from pdos_next.domain.verification_front.service import _recheck
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Product, Receipt, RequestKey, now
from pdos_next.quality_result_bridge import _runtime_stamp as bridge_stamp
from pdos_next.service import Context, digest, material_digest, require_access

from .consumption import ConsumptionHost
from .models import BaselineDocumentLink, PreparationCurrent, PreparationVersion
from .rules import check_material, exact_sources, require, semantic, source_reads, source_refs
from .schemas import KINDS, PAYLOADS, BaselinePayload, ObjectRef

SCHEMA_VERSION = "pdos-manufacturing-preparation-v1"
category_lifecycle_fence = True
EVENTS = MappingProxyType(
    {
        "npi.work_instruction.record": "work_instruction.recorded",
        "npi.control_plan.record": "control_plan.recorded",
        "npi.manufacturing_baseline.record": "manufacturing_baseline.recorded",
    }
)
_CAPABILITY = object()


def configure(engine):
    """Trusted startup only; this does not install command/tier/role matrices."""
    module = sys.modules[__name__]
    engine._pdos_manufacturing_preparation_consumption = ConsumptionHost(
        {op: module for op in PAYLOADS}
    )


def _host(s):
    value = getattr(s.get_bind(), "_pdos_manufacturing_preparation_consumption", None)
    require(
        isinstance(value, ConsumptionHost),
        "INTEGRATION_REQUIRED",
        "制造准备的共同确认消费端口尚未接通。",
        503,
    )
    return value


def _runtime(s):
    return digest(
        {
            "evidence": evidence._runtime_stamp(s),
            "bridge": bridge_stamp(s),
            "host": id(getattr(s.get_bind(), "_pdos_manufacturing_preparation_consumption", None)),
            "callbacks": [
                id(_load),
                id(_refresh),
                id(get_preparation),
                id(_authority),
                id(evidence._evidence),
                id(configurations.get_process),
            ],
        }
    )


def _command(ctx, command, payload):
    require(
        isinstance(ctx, Context)
        and isinstance(command, Command)
        and ctx.actor_id == ctx.requester_id
        and ctx.run_id is None,
        "NAMED_DECISION_REQUIRED",
        "须由当前具名本人办理制造准备。",
        403,
    )
    require(
        command.operation in PAYLOADS
        and type(payload) is PAYLOADS[command.operation]
        and type(payload).model_validate(command.payload) == payload,
        "COMMAND_PAYLOAD_MISMATCH",
        "操作与实际完整载荷不能替换。",
        422,
    )
    require(
        len(str(semantic(payload)).encode()) <= 1_000_000,
        "MATERIAL_TOO_LARGE",
        "本次准备材料超过有界上限，请缩小范围。",
        422,
    )


def _persistent_product(s, ctx, command, product):
    require(isinstance(product, Product), "ACTUAL_PRODUCT_REQUIRED", "缺真实Product。", 503)
    state = inspect(product)
    require(
        state.persistent
        and state.session is s
        and not state.deleted
        and not {"id", "tenant_id", "revision"} & state.unloaded,
        "ACTUAL_PRODUCT_REQUIRED",
        "Product须来自当前实际Session。",
        503,
    )
    require(
        product.id == command.product_id and product.tenant_id == ctx.tenant_id,
        "FORBIDDEN_SCOPE",
        "型号范围不一致。",
        403,
    )


def _authority(s, ctx, command, project, *, write=False):
    evaluated_at = now()
    result = professional.assess(
        s,
        ctx,
        command.product_id,
        project.id,
        command.operation,
        project.purpose,
        evaluated_at,
        write=write,
    )
    require(
        "PROFESSIONAL_OPERATION_NOT_CONFIGURED" not in result["reason_codes"],
        "INTEGRATION_REQUIRED",
        "制造准备的职责操作矩阵尚未登记。",
        503,
    )
    require(
        result.get("scope")
        == {
            "tenant_id": str(ctx.tenant_id),
            "product_id": str(command.product_id),
            "project_id": str(project.id),
        }
        and result.get("subject_id") == str(ctx.requester_id)
        and result.get("operation") == command.operation
        and result.get("purpose") == project.purpose,
        "INTEGRITY_MISMATCH",
        "实际专业核对范围或具名本人不一致。",
        503,
    )
    require(
        result["authorized"] is True
        and result["qualified"] is True
        and "manufacturing" in result["roles"],
        "QUALIFICATION_REQUIRED",
        "当前本人、制造职责及精确用途资格未满足。",
        403,
    )
    _deadline(result, evaluated_at)
    _deadline(result, now())
    return result, None


def _deadline(authority, at, scope_deadline=None):
    require(
        professional.authority_time_current(authority, at),
        "SOURCE_STALE",
        "实际职责或资格区间不再满足当前操作。",
    )
    if scope_deadline is not None:
        require(at < scope_deadline, "SOURCE_STALE", "明确临时授权区间已到期。")


def _row(s, ctx, pid, ref):
    row = s.scalar(
        select(PreparationVersion)
        .where(
            PreparationVersion.tenant_id == ctx.tenant_id,
            PreparationVersion.product_id == pid,
            PreparationVersion.id == ref.id,
        )
        .execution_options(populate_existing=True)
    )
    require(
        row is not None and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        "所选固定准备版本不可读取。",
        403,
    )
    require(
        row.kind == ref.kind and type(row.revision) is int and row.revision == ref.revision,
        "VERSION_CONFLICT",
        "固定准备版本或类型不匹配。",
    )
    return row


def _pointer(s, ctx, pid, row, *, lock=False):
    query = select(PreparationCurrent).where(
        PreparationCurrent.tenant_id == ctx.tenant_id,
        PreparationCurrent.product_id == pid,
        PreparationCurrent.project_id == row.project_id,
        PreparationCurrent.kind == row.kind,
        PreparationCurrent.series_id == row.series_id,
    )
    query = query.execution_options(populate_existing=True)
    return s.scalar(query.with_for_update() if lock else query)


def _record_input(row):
    """Fixed columns cannot widen audience or alter the previewed semantic."""
    try:
        command = Command.model_validate(row.input_snapshot["command"])
        payload = PAYLOADS[row.operation].model_validate(row.input_snapshot["semantic"])
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise DomainError("STORED_ATOM_MISMATCH", "固定准备原输入不能完整核对。", 503) from error
    require(
        KINDS[row.operation] == row.kind
        and row.project_id == payload.project_id
        and row.visibility == payload.visibility
        and row.title == payload.title
        and (row.process_id, row.process_revision) == (payload.process.id, payload.process.revision)
        and row.operation_key == getattr(payload, "operation_key", None)
        and (row.previous_id, row.previous_revision)
        == (payload.previous_id, payload.expected_previous_revision)
        and row.body.get("schema_version") == SCHEMA_VERSION
        and row.body.get("scope") == {"project_id": str(row.project_id), "purpose": row.purpose}
        and row.body.get("kind") == row.kind
        and row.body.get("status") == "draft"
        and row.body.get("input") == semantic(payload)
        and command.operation == row.operation
        and command.product_id == row.product_id
        and command.expected_revision == row.shared_proof_revision
        and "confirmation_token" not in command.payload,
        "STORED_ATOM_MISMATCH",
        "固定准备列或受众偏离原实质预览。",
        503,
    )
    return command, payload


def _retained_group(s, ctx, pid, row):
    """Stored common group is historical evidence, never a live consumption marker."""
    proof = s.get(Confirmation, row.shared_proof_id)
    receipts = list(
        s.scalars(
            select(Receipt).where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.product_id == pid,
                Receipt.subject_type == row.kind,
                Receipt.subject_id == row.id,
                Receipt.subject_revision == row.revision,
            )
        )
    )
    require(len(receipts) == 1, "STORED_ATOM_INCOMPLETE", "固定准备回执不能唯一核对。", 503)
    receipt = receipts[0]
    command, operation_payload = _record_input(row)
    require(
        proof is not None
        and proof.consumed is True
        and (
            proof.tenant_id,
            proof.product_id,
            proof.actor_id,
            proof.subject_id,
            proof.operation,
            proof.revision,
        )
        == (row.tenant_id, pid, row.owner_id, pid, row.operation, row.shared_proof_revision)
        and type(proof.revision) is int
        and proof.token_hash == row.token_sha256
        and proof.payload_digest == row.material_sha256
        and digest(proof.snapshot) == digest(row.review)
        and proof.created_at <= row.proof_consumed_at <= row.created_at < proof.expires_at
        and proof.expires_at == row.proof_expires_at
        and semantic(operation_payload) == row.input_snapshot["semantic"]
        and row.body.get("input") == semantic(operation_payload)
        and row.body.get("kind") == row.kind
        and row.body.get("status") == "draft"
        and row.sources == exact_sources(operation_payload)
        and digest(row.body) == row.body_sha256
        and configurations._merge_reads(
            [v.model_dump(mode="json") for v in command.source_read_set]
        )
        == row.required_source_read_set
        and digest([json_value(v) for v in canonical_reads(command.source_read_set)])
        == row.read_set_sha256
        and material_digest(
            Context(row.tenant_id, row.owner_id, row.owner_id),
            command,
            operation_payload,
            sys.modules[__name__],
        )
        == row.material_sha256
        and digest(row.purpose) == row.purpose_sha256
        and receipt.command_id == command.command_id
        and receipt.operation == row.operation
        and receipt.actor_id == receipt.requester_id == row.owner_id
        and receipt.visibility == row.visibility
        and receipt.intent_digest == row.intent_digest
        and receipt.run_id is None
        and receipt.request_digest == row.input_snapshot["request_digest"]
        and command.product_id == pid
        and command.expected_revision == row.shared_proof_revision
        and type(receipt.result.get("revision")) is int
        and receipt.result.get("id") == str(row.id)
        and receipt.result["revision"] == row.revision
        and receipt.result.get("status") == "draft",
        "STORED_ATOM_MISMATCH",
        "固定准备与原共同确认或回执材料不匹配。",
        503,
    )
    audits = list(
        s.scalars(
            select(Audit).where(Audit.tenant_id == row.tenant_id, Audit.receipt_id == receipt.id)
        )
    )
    outboxes = list(
        s.scalars(
            select(Outbox).where(Outbox.tenant_id == row.tenant_id, Outbox.receipt_id == receipt.id)
        )
    )
    keys = list(
        s.scalars(
            select(RequestKey).where(
                RequestKey.tenant_id == row.tenant_id,
                RequestKey.receipt_id == receipt.id,
                RequestKey.actor_id == row.owner_id,
                RequestKey.key == command.idempotency_key,
            )
        )
    )
    request_bound = len(keys) == 1 and keys[0].digest == row.input_snapshot["request_digest"]
    if not keys and receipt.actor_id != ctx.actor_id:
        # A readable peer Receipt does not expose its author's private key row.
        # The existing database check binds that Receipt under this caller only.
        from pdos_next.receipt_request_binding import readable_receipt_request_bound

        request_bound = readable_receipt_request_bound(s, ctx, pid, receipt.id)
    require(
        len(audits) == len(outboxes) == 1
        and audits[0].actor_id == row.owner_id
        and audits[0].operation == row.operation
        and outboxes[0].type == EVENTS[row.operation]
        and outboxes[0].actor_id == row.owner_id
        and outboxes[0].subject_id == row.id
        and outboxes[0].subject_revision == row.revision
        and outboxes[0].correlation_id == command.command_id
        and request_bound,
        "STORED_ATOM_INCOMPLETE",
        "固定准备缺同一操作的唯一审计、事件或原请求关联。",
        503,
    )
    # Original signer is assessed only as retained evidence. Caller ACL/current
    # professional write authority is never borrowed from this historical context.
    retained = _recheck(s, ctx, pid, row.project_id, row.authority_snapshot, at=row.created_at)
    return receipt, retained.get("current") is True


def _request_digest(command, payload):
    # Exact current common.execute request identity, not digest(Command).
    return digest(
        {
            "operation": command.operation,
            "category_id": command.category_id,
            "product_id": command.product_id,
            "expected_revision": command.expected_revision,
            "source_read_set": [v.model_dump(mode="json") for v in command.source_read_set],
            "payload": payload.model_dump(mode="json"),
        }
    )


@contextmanager
def _fresh_selects(s):
    # Stack-local SELECT refresh, no Session/global qualification cache. Does not
    # expire the current loaded Confirmation or reset its pending False->True.
    def actual_rows(state):
        if state.is_select:
            state.update_execution_options(populate_existing=True)

    event.listen(s, "do_orm_execute", actual_rows)
    try:
        with s.no_autoflush:
            yield
    finally:
        event.remove(s, "do_orm_execute", actual_rows)


def _saved_command(command):
    value = command.model_dump(mode="json")
    value["payload"].pop("confirmation_token", None)
    return value


def get_preparation(s, ctx, pid, ref):
    """Readable fixed history; stale public source stays history, private ACL never bypassed."""
    uow, ctx_sha = _uow(s), digest(vars(ctx))
    with _fresh_selects(s):
        value = _get_preparation(s, ctx, pid, ref)
    _same_uow(s, uow, ctx, ctx_sha)
    return value


def _get_preparation(s, ctx, pid, ref):
    _uow(s)
    runtime = _runtime(s)
    require_access(s, ctx, pid)
    row = _row(s, ctx, pid, ref)
    receipt, retained_current = _retained_group(s, ctx, pid, row)
    project, _, _ = projects._project(s, ctx, pid, row.project_id)
    pointer = _pointer(s, ctx, pid, row)
    pointer_identity = None if pointer is None else (pointer.version_id, pointer.revision)
    current = pointer_identity == (row.id, row.revision)
    status = configurations._source_state(s, ctx, pid, row.required_source_read_set)
    if project.purpose != row.purpose or not retained_current:
        status = "needs_recheck"
    if status == "current":
        refs = source_refs(PAYLOADS[row.operation].model_validate(row.input_snapshot["semantic"]))
        basis, _, _ = evidence._evidence(
            s, ctx, pid, row.required_source_read_set, refs, io=not s.info.get("read_snapshot")
        )
        if basis != row.source_basis:
            status = "needs_recheck"
    if row.kind == "manufacturing_baseline":
        payload = PAYLOADS[row.operation].model_validate(row.input_snapshot["semantic"])
        expected = {
            (item.operation_key, kind, ref.id, ref.revision)
            for item in payload.operations
            for kind in ("work_instruction", "control_plan")
            if (ref := getattr(item, kind)) is not None
        }
        children = list(
            s.scalars(
                select(BaselineDocumentLink)
                .where(
                    BaselineDocumentLink.tenant_id == ctx.tenant_id,
                    BaselineDocumentLink.product_id == pid,
                    BaselineDocumentLink.baseline_id == row.id,
                )
                .execution_options(populate_existing=True)
            )
        )
        actual = {
            (v.operation_key, v.document_kind, v.document_id, v.document_revision) for v in children
        }
        require(
            len(children) == len(expected)
            and actual == expected
            and all(
                v.project_id == row.project_id
                and v.baseline_revision == row.revision
                and v.process_id == row.process_id
                and v.process_revision == row.process_revision
                for v in children
            ),
            "STORED_CHILD_SET_MISMATCH",
            "固定基线的实际文档关系集合不完整或被替换。",
            503,
        )
        for child in children:
            _, view = get_preparation(
                s,
                ctx,
                pid,
                ObjectRef(
                    kind=child.document_kind, id=child.document_id, revision=child.document_revision
                ),
            )
            if view["source_status"] != "current" or view["is_current"] is not True:
                status = "needs_recheck"
    require(runtime == _runtime(s), "SOURCE_STALE", "读取期间实际owner或issuer发生变化。")
    require_access(s, ctx, pid)  # Last caller ACL after byte reads.
    require(runtime == _runtime(s), "SOURCE_STALE", "末次ACL读取期间owner或issuer变化。")
    latest_pointer = _pointer(s, ctx, pid, row)
    require(
        pointer_identity
        == (
            None if latest_pointer is None else (latest_pointer.version_id, latest_pointer.revision)
        ),
        "RECHECK_REQUIRED",
        "读取期间Current已变。",
    )
    require_access(s, ctx, pid)  # Last Current IO precedes this fresh caller/expiry gate.
    require(runtime == _runtime(s), "SOURCE_STALE", "末端caller核对期间owner发生变化。")
    result = {
        "schema_version": SCHEMA_VERSION,
        "id": str(row.id),
        "kind": row.kind,
        "revision": row.revision,
        "series_id": str(row.series_id),
        "project_id": str(row.project_id),
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "title": row.title,
        "status": "draft",
        "purpose": row.purpose,
        "process": {"id": str(row.process_id), "revision": row.process_revision},
        "operation_key": row.operation_key,
        "previous_id": str(row.previous_id) if row.previous_id else None,
        "previous_revision": row.previous_revision,
        "created_at": row.created_at.isoformat(),
        "is_current": current,
        "source_status": status,
        "required_source_read_set": deepcopy(row.required_source_read_set),
        "body": deepcopy(row.body),
        "sources": deepcopy(row.sources),
        "receipt_id": str(receipt.id),
        "manufacturing_release": None,
        "qualification": "unknown",
        "negative_enumeration_complete": False,
    }
    return row, result


@dataclass(frozen=True)
class Bound:
    project: object
    process: object
    previous: object
    body: dict
    reads: list
    basis: dict
    authority: dict
    previous_view: dict | None
    documents: dict
    runtime: str
    authority_deadline: datetime | None = None


def _load(s, ctx, command, product, payload, *, require_reads=True):
    uow, ctx_sha = _uow(s), digest(vars(ctx))
    with _fresh_selects(s):
        bound = _load_fixed(s, ctx, command, product, payload, require_reads=require_reads)
    _same_uow(s, uow, ctx, ctx_sha)
    return bound


def _definition_reads(definition):
    """Consume the explicit Artifact closure returned by definition_view.

    G0 definitions may have no Artifact edges. An explicit empty list is then
    complete; an absent DTO or a non-current source projection still fails.
    """
    require(
        type(definition) is dict
        and type(definition.get("sources")) is list
        and len(definition["sources"]) <= 20,
        "INVALID_FIXED_DEFINITION",
        "固定定义未提供完整有界来源引用。",
        503,
    )
    require(
        definition.get("source_status") == "current",
        "RECHECK_REQUIRED",
        "固定定义的来源状态须重新核对。",
    )
    reads = []
    for reference in definition["sources"]:
        require(
            type(reference) is dict
            and all(
                key in reference for key in ("artifact_id", "expected_revision", "line", "quote")
            )
            and type(reference.get("expected_revision")) is int
            and type(reference.get("line")) is int
            and reference["line"] >= 1
            and type(reference.get("quote")) is str
            and 1 <= len(reference["quote"]) <= 4000,
            "INVALID_FIXED_DEFINITION",
            "固定定义的精确来源身份、版本或定位不完整。",
            503,
        )
        try:
            fixed = SourceRead.model_validate(
                {key: reference[key] for key in ("artifact_id", "expected_revision")}
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise DomainError(
                "INVALID_FIXED_DEFINITION", "固定定义的精确来源引用不能核对。", 503
            ) from error
        require(
            reference.get("status") == "active",
            "RECHECK_REQUIRED",
            "固定定义的某项来源已经失效或需重核。",
        )
        reads.append(
            {"artifact_id": str(fixed.artifact_id), "expected_revision": fixed.expected_revision}
        )
    return configurations._merge_reads(reads)


def _load_fixed(s, ctx, command, product, payload, *, require_reads=True):
    _command(ctx, command, payload)
    _uow(s)
    _persistent_product(s, ctx, command, product)
    stamp = _runtime(s)
    configurations._human(s, ctx, command.product_id)
    project, link, definition = projects._project(s, ctx, command.product_id, payload.project_id)
    validate_sources(s, ctx, definition)
    process, process_view = configurations.get_process(
        s, ctx, command.product_id, payload.process.id
    )
    engineering = configurations._row(
        s, ctx, command.product_id, EngineeringConfiguration, process.engineering_configuration_id
    )
    require(
        process.revision == payload.process.revision
        and process_view["source_status"] == "current"
        and engineering.definition_id == link.definition_id
        and engineering.definition_revision == link.definition_revision,
        "RECHECK_REQUIRED",
        "制造配置必须固定到本项目的真实定义与工程/BOM版本。",
    )
    require(
        all(
            row.visibility != "private" or payload.visibility == "private"
            for row in (project, process, engineering)
        )
        and (definition["visibility"] != "private" or payload.visibility == "private"),
        "FORBIDDEN_SCOPE",
        "私有项目或配置不能扩为共享制造准备。",
        403,
    )
    previous, previous_view = None, None
    if payload.previous_id is not None:
        previous, previous_view = get_preparation(
            s,
            ctx,
            command.product_id,
            ObjectRef(
                kind=KINDS[command.operation],
                id=payload.previous_id,
                revision=payload.expected_previous_revision,
            ),
        )
        old_process = configurations._row(
            s, ctx, command.product_id, ProcessRevision, previous.process_id
        )
        require(
            previous.owner_id == ctx.requester_id
            and previous.project_id == project.id
            and previous.visibility == payload.visibility
            and previous.purpose == project.purpose
            and old_process.series_id == process.series_id
            and previous.operation_key == getattr(payload, "operation_key", None),
            "FORBIDDEN_SCOPE",
            "续版不能改变原owner、受众、用途或制造工序系列。",
            403,
        )
        require(previous_view["source_status"] == "current", "RECHECK_REQUIRED", "旧版依据需重核。")
    documents = {}
    groups = [
        process.required_source_read_set,
        engineering.required_source_read_set,
        _definition_reads(definition),
        source_reads(payload),
    ]
    if isinstance(payload, BaselinePayload):
        for item in payload.operations:
            for kind in ("work_instruction", "control_plan"):
                ref = getattr(item, kind)
                if ref is None:
                    continue
                child, viewed = get_preparation(s, ctx, command.product_id, ref)
                require(child.project_id == project.id, "FORBIDDEN_SCOPE", "资料不能跨项目。", 403)
                documents[(item.operation_key, kind)] = viewed
                groups.append(child.required_source_read_set)
    gaps = check_material(payload, process_view, documents)
    authority, authority_deadline = _authority(s, ctx, command, project)
    groups.append(authority["required_source_read_set"])
    reads = configurations._merge_reads(*groups)
    if require_reads:
        supplied = configurations._merge_reads(
            [v.model_dump(mode="json") for v in command.source_read_set]
        )
        require(
            supplied == reads,
            "MISSING_REQUIRED_EVIDENCE",
            "须完整保留服务器当前固定来源读集。",
            422,
        )
    basis, private, _ = evidence._evidence(s, ctx, command.product_id, reads, source_refs(payload))
    require(
        not private or payload.visibility == "private",
        "FORBIDDEN_SCOPE",
        "私有来源不能被共享制造准备扩大。",
        403,
    )
    require_access(s, ctx, command.product_id)
    require(stamp == _runtime(s), "SOURCE_STALE", "owner/issuer配置在完整IO中发生变化。")
    _deadline(authority, now(), authority_deadline)  # Fresh after last actual source/ACL IO.
    body = {
        "schema_version": SCHEMA_VERSION,
        "kind": KINDS[command.operation],
        "status": "draft",
        "input": semantic(payload),
        "scope": {"project_id": str(project.id), "purpose": project.purpose},
        "process_snapshot": process_view,
        "document_bindings": [
            {
                "operation_key": key[0],
                "kind": key[1],
                "id": view["id"],
                "revision": view["revision"],
                "body_sha256": digest(view["body"]),
            }
            for key, view in documents.items()
        ],
        "gaps": gaps,
        "qualification": "unknown",
        "manufacturing_release": None,
        "negative_enumeration_complete": False,
    }
    return Bound(
        project,
        process,
        previous,
        body,
        reads,
        basis,
        authority,
        previous_view,
        documents,
        stamp,
        authority_deadline,
    )


def _cas(s, ctx, command, product, payload, bound):
    uow, ctx_sha = _uow(s), digest(vars(ctx))
    with _fresh_selects(s):
        _cas_fixed(s, ctx, command, product, payload, bound)
    _same_uow(s, uow, ctx, ctx_sha)


def _cas_fixed(s, ctx, command, product, payload, bound):
    require_access(s, ctx, command.product_id, write=True, lock=True)
    require(product.revision == command.expected_revision, "VERSION_CONFLICT", "产品水位已变。")
    if bound.previous is not None:
        pointer = _pointer(s, ctx, command.product_id, bound.previous, lock=True)
        require(
            pointer is not None
            and pointer.version_id == bound.previous.id
            and pointer.revision == payload.expected_previous_revision,
            "VERSION_CONFLICT",
            "续版须对应本对象的真实Current。",
        )
    authority, authority_deadline = _authority(s, ctx, command, bound.project, write=True)
    require(
        digest(authority) == digest(bound.authority)
        and authority_deadline == bound.authority_deadline,
        "RECHECK_REQUIRED",
        "当前具名资格材料或实际生效边界已变。",
    )


def _seal(bound):
    return digest(
        {
            "body": bound.body,
            "reads": bound.reads,
            "basis": bound.basis,
            "authority": bound.authority,
            "authority_deadline": bound.authority_deadline,
            "previous": bound.previous_view,
            "documents": list(bound.documents.values()),
            "runtime": bound.runtime,
        }
    )


def _refresh(s, ctx, command, product, payload, bound):
    # Force actual ORM Current/fixed/source queries to refresh without expiring
    # the loaded persistent Confirmation needed by the real transition hook.
    latest = _load(s, ctx, command, product, payload)
    require(
        _seal(latest) == _seal(bound),
        "RECHECK_REQUIRED",
        "固定对象、来源或当前资格已变，请重新核对。",
    )
    _cas(s, ctx, command, product, payload, latest)
    _deadline(latest.authority, now(), latest.authority_deadline)
    require(bound.runtime == _runtime(s), "SOURCE_STALE", "末端owner/issuer发生变化。")
    return latest


def _review(payload, bound):
    revision = bound.previous.revision + 1 if bound.previous is not None else 1
    return {
        "operation": next(op for op, typ in PAYLOADS.items() if typ is type(payload)),
        "before": deepcopy(bound.previous_view),
        "after": {
            "id": None,
            "revision": revision,
            "status": "draft",
            "created_at": None,
            "time_policy": "server_on_save",
            "body": deepcopy(bound.body),
        },
        "effect": (
            "保存固定制造准备草稿；不发布制造基线，不改变旧Build或实际制造，"
            "不授工装/试产/放行资格。"
        ),
        "authority": deepcopy(bound.authority),
        "required_source_read_set": deepcopy(bound.reads),
        "reason": payload.reason,
        "read_basis": deepcopy(bound.basis),
    }


class Prepared:
    """Single-attempt actual Session/UOW phase; cannot be copied or serialized."""

    __slots__ = (
        "session",
        "uow",
        "ctx_sha",
        "command_sha",
        "product",
        "payload_sha",
        "bound",
        "seal",
        "review",
        "review_sha",
        "used",
    )

    def __init__(self, token, s, ctx, command, product, payload, bound):
        require(token is _CAPABILITY, "INVALID_PHASE", "缺实际准备阶段。", 503)
        self.session, self.uow, self.product = s, _uow(s), product
        self.ctx_sha, self.command_sha = digest(vars(ctx)), digest(command)
        self.payload_sha, self.bound, self.seal = digest(semantic(payload)), bound, _seal(bound)
        self.review = _review(payload, bound)
        self.review_sha, self.used = digest(self.review), False

    def __reduce__(self):
        raise TypeError("Phase stays in one actual transaction")

    def __copy__(self):
        raise TypeError("Phase is one-use")

    def __deepcopy__(self, memo):
        raise TypeError("Phase is one-use")


def _phase(s, ctx, command, product, payload, phase):
    require(
        isinstance(phase, Prepared)
        and phase.session is s
        and phase.product is product
        and phase.used is False,
        "INVALID_PHASE",
        "准备阶段已使用或换事务。",
        503,
    )
    _same_uow(s, phase.uow, ctx, phase.ctx_sha)
    require(
        digest(command) == phase.command_sha
        and digest(semantic(payload)) == phase.payload_sha
        and _seal(phase.bound) == phase.seal
        and digest(phase.review) == phase.review_sha,
        "PHASE_MATERIAL_CHANGED",
        "原command/key/读集或准备材料被替换。",
        503,
    )
    _persistent_product(s, ctx, command, product)
    require(phase.bound.runtime == _runtime(s), "SOURCE_STALE", "阶段owner/issuer配置变化。")


def validate(s, ctx, command, product, payload):
    with s.no_autoflush:
        _load(s, ctx, command, product, payload)


def preview_view(s, ctx, command, product, payload):
    with s.no_autoflush:
        bound = _load(s, ctx, command, product, payload)
        _cas(s, ctx, command, product, payload, bound)
        bound = _refresh(s, ctx, command, product, payload, bound)
        return _review(payload, bound)


def prepare_preview(s, ctx, command, product, payload):
    """One actual caller/UOW preparation; not a transport or authority cache."""
    _host(s)
    with s.no_autoflush:
        bound = _load(s, ctx, command, product, payload)
        _cas(s, ctx, command, product, payload, bound)
        return Prepared(_CAPABILITY, s, ctx, command, product, payload, bound)


def preview_prepared(s, ctx, command, product, payload, phase):
    _phase(s, ctx, command, product, payload, phase)
    phase.used = True
    with s.no_autoflush:
        bound = _refresh(s, ctx, command, product, payload, phase.bound)
        _same_uow(s, phase.uow, ctx, phase.ctx_sha)
        # Refresh compares the complete source/Current/authority material;
        # no clock-only widening or returned synthetic qualification.
        return _review(payload, bound)


def prepare_write_review(s, ctx, command, product, payload, proof=None):
    _host(s)
    with s.no_autoflush:
        bound = _load(s, ctx, command, product, payload)
        _cas(s, ctx, command, product, payload, bound)
        bound = _refresh(s, ctx, command, product, payload, bound)
        phase = Prepared(_CAPABILITY, s, ctx, command, product, payload, bound)
        return phase, deepcopy(phase.review)


def bind_consumption(s, ctx, command, product, payload, phase, proof):
    _phase(s, ctx, command, product, payload, phase)
    return _host(s).bind_before_transition(
        s,
        ctx,
        command,
        payload,
        sys.modules[__name__],
        proof,
        reviewed_snapshot=phase.review,
    )


def record_consumption(s, ctx, command, product, payload, phase, proof, binding):
    marker = _host(s).capture_after_transition(
        s, ctx, command, payload, sys.modules[__name__], proof, binding=binding
    )  # Capture the actual first transition clock before even phase hashing.
    _phase(s, ctx, command, product, payload, phase)
    return marker


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    _phase(s, ctx, command, product, payload, phase)
    phase.used = True  # No re-attempt in same UOW even on exceptions.
    require(
        isinstance(consumption, tuple) and len(consumption) == 2,
        "LIVE_CONSUMPTION_REQUIRED",
        "缺实际共同确认消费绑定。",
        503,
    )
    binding, marker = consumption
    with s.no_autoflush:
        bound = _refresh(s, ctx, command, product, payload, phase.bound)
        previous = bound.previous
        pointer = None
        if previous is not None:
            # This final Current/CAS IO must precede require_live and saved_at.
            pointer = _pointer(s, ctx, product.id, previous, lock=True)
            require(
                pointer is not None
                and pointer.version_id == previous.id
                and pointer.revision == previous.revision,
                "VERSION_CONFLICT",
                "保存时Current已变。",
            )
        _same_uow(s, phase.uow, ctx, phase.ctx_sha)
        require(bound.runtime == _runtime(s), "SOURCE_STALE", "末次Current读取期间owner变化。")
        live = _host(s).require_live(
            s,
            ctx,
            command,
            payload,
            sys.modules[__name__],
            binding.proof,
            binding=binding,
            marker=marker,
        )
        require(
            digest(binding.proof.snapshot) == phase.review_sha,
            "PHASE_MATERIAL_CHANGED",
            "原确认实质材料不匹配。",
            503,
        )
        saved_at = now()  # Server save clock; not an invented manufacturing event.
        _deadline(bound.authority, saved_at, bound.authority_deadline)
        require(
            live.consumed_at <= saved_at < live.expires_at,
            "CONFIRMATION_REQUIRED",
            "完整owner核对后确认已到期。",
        )
        identity = uuid4()
        row = PreparationVersion(
            id=identity,
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=payload.project_id,
            kind=KINDS[command.operation],
            series_id=previous.series_id if previous else identity,
            revision=previous.revision + 1 if previous else 1,
            previous_id=previous.id if previous else None,
            previous_revision=previous.revision if previous else None,
            owner_id=ctx.requester_id,
            visibility=payload.visibility,
            title=payload.title,
            status="draft",
            process_id=payload.process.id,
            process_revision=payload.process.revision,
            operation_key=getattr(payload, "operation_key", None),
            purpose=bound.project.purpose,
            purpose_sha256=digest(bound.project.purpose),
            operation=command.operation,
            body=deepcopy(bound.body),
            body_sha256=digest(bound.body),
            input_snapshot={
                "semantic": semantic(payload),
                "command": _saved_command(command),
                "request_digest": _request_digest(command, payload),
            },
            sources=exact_sources(payload),
            required_source_read_set=deepcopy(bound.reads),
            source_basis=deepcopy(bound.basis),
            authority_snapshot=deepcopy(bound.authority),
            review=deepcopy(phase.review),
            created_at=saved_at,
            **live.storage_columns(),
        )
        s.add(row)
        s.flush([row])  # Root's deferred common atom must complete or all rolls back.
        if isinstance(payload, BaselinePayload):
            for item in payload.operations:
                for kind in ("work_instruction", "control_plan"):
                    ref = getattr(item, kind)
                    if ref is not None:
                        s.add(
                            BaselineDocumentLink(
                                tenant_id=ctx.tenant_id,
                                product_id=product.id,
                                project_id=payload.project_id,
                                baseline_id=row.id,
                                baseline_revision=row.revision,
                                baseline_kind=row.kind,
                                process_id=row.process_id,
                                process_revision=row.process_revision,
                                operation_key=item.operation_key,
                                document_kind=kind,
                                document_id=ref.id,
                                document_revision=ref.revision,
                            )
                        )
        if previous is None:
            s.add(
                PreparationCurrent(
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    project_id=payload.project_id,
                    kind=row.kind,
                    series_id=row.series_id,
                    owner_id=row.owner_id,
                    visibility=row.visibility,
                    version_id=row.id,
                    revision=row.revision,
                )
            )
        else:
            pointer.version_id, pointer.revision = row.id, row.revision
        return row, row.kind, row.visibility


def apply(s, ctx, command, product, payload):
    # Root must opt this family into actual phased common consume. No fallback
    # that treats a historical consumed boolean as this request's transition.
    raise DomainError(
        "PHASED_COMMON_INTEGRATION_REQUIRED", "须由共同事务执行准备/真实消费/保存。", 503
    )


def replay_subject_type(payload):
    return KINDS[next(op for op, typ in PAYLOADS.items() if typ is type(payload))]


def replay_subject(s, ctx, command, product, payload):
    intent = digest(
        {
            "operation": command.operation,
            "product": command.product_id,
            "payload": semantic(payload),
            "named_actor": ctx.requester_id,
            "source_revision": None,
            "private_owner": ctx.requester_id if payload.visibility == "private" else None,
        }
    )
    row = s.scalar(
        select(PreparationVersion).where(
            PreparationVersion.tenant_id == ctx.tenant_id,
            PreparationVersion.product_id == product.id,
            PreparationVersion.owner_id == ctx.requester_id,
            PreparationVersion.operation == command.operation,
            PreparationVersion.intent_digest == intent,
        )
    )
    if row is None:
        return None
    get_preparation(
        s, ctx, command.product_id, ObjectRef(kind=row.kind, id=row.id, revision=row.revision)
    )
    return row


def inputs(s, ctx, product_id, command):
    require(command.product_id == product_id, "FORBIDDEN_SCOPE", "型号范围不一致。", 403)
    require_access(s, ctx, product_id, write=True, lock=True)
    product = s.scalar(
        select(Product)
        .where(Product.tenant_id == ctx.tenant_id, Product.id == product_id)
        .with_for_update()
    )
    payload = PAYLOADS.get(command.operation)
    require(payload is not None, "UNKNOWN_OPERATION", "未登记该制造准备动作。", 422)
    payload = payload.model_validate(command.payload)
    with s.no_autoflush:
        bound = _load(s, ctx, command, product, payload, require_reads=False)
        _cas(s, ctx, command, product, payload, bound)
        # Prepared command comes from actual server reads, not caller defaults.
        updated = command.model_copy(
            update={"source_read_set": [SourceRead.model_validate(v) for v in bound.reads]}
        )
        bound = _refresh(s, ctx, updated, product, payload, bound)
        return {"command": updated.model_dump(mode="json"), "review": _review(payload, bound)}


def list_preparations(s, ctx, product_id, *, project_id, process_id=None, history_cursor=None):
    from pdos_next.capa_history import page_query, page_rows

    require_access(s, ctx, product_id)
    projects._project(s, ctx, product_id, project_id)
    query = select(PreparationVersion).where(
        PreparationVersion.tenant_id == ctx.tenant_id,
        PreparationVersion.product_id == product_id,
        PreparationVersion.project_id == project_id,
    )
    if process_id is not None:
        query = query.where(PreparationVersion.process_id == process_id)
    joined = (
        (PreparationCurrent.tenant_id == PreparationVersion.tenant_id)
        & (PreparationCurrent.product_id == PreparationVersion.product_id)
        & (PreparationCurrent.project_id == PreparationVersion.project_id)
        & (PreparationCurrent.kind == PreparationVersion.kind)
        & (PreparationCurrent.series_id == PreparationVersion.series_id)
        & (PreparationCurrent.version_id == PreparationVersion.id)
        & (PreparationCurrent.revision == PreparationVersion.revision)
    )
    current_rows = list(s.scalars(query.join(PreparationCurrent, joined)))
    historical, history_page = page_rows(
        s.scalars(
            page_query(
                query.where(~exists(select(PreparationCurrent.id).where(joined))),
                PreparationVersion.created_at,
                PreparationVersion.id,
                "preparation",
                history_cursor,
                kinds={"preparation"},
            )
        ),
        "preparation",
        kinds={"preparation"},
    )
    views, unavailable = [], 0
    for row in [*current_rows, *historical]:
        try:
            _, view = get_preparation(
                s, ctx, product_id, ObjectRef(kind=row.kind, id=row.id, revision=row.revision)
            )
        except DomainError as error:
            if error.status == 403:
                unavailable += 1
                continue
            raise
        views.append(view)
    return {
        "schema_version": SCHEMA_VERSION,
        "versions": views,
        "has_more": bool(history_page["next_cursor"]),
        "history_page": history_page,
        "unavailable_count": unavailable,
        "qualification": "unknown",
        "manufacturing_release": None,
        "negative_enumeration_complete": False,
    }


def qualified_pilot_baseline(*args, **kwargs):
    raise DomainError(
        "MANUFACTURING_BASELINE_RELEASE_REQUIRED",
        "草稿准备不能替代具名发布制造基线及实际资产验收。",
        503,
    )
