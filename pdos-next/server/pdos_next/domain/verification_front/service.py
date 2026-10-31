"""Professional front-stage host adapter using the existing verification kernel.

All writes belong to the host command transaction and common receipt. Preview
simulates sealed candidates; execution first inserts actual professional facts,
then lets the kernel resolve them. No physical handoff, reservation or TestRun.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select

from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.supply_execution.service import (
    _build,
    _human,
    _linked,
    _read_evidence,
    _sources,
)
from pdos_next.domain.verification.ports import Invocation
from pdos_next.domain.verification.rules import accepted_coverage, coverage_gaps, document_gaps
from pdos_next.domain.verification_execution import service as preparation_service
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.request_proof import snapshot_get, snapshot_scalar
from pdos_next.schemas.resource_readiness.contracts import ExecutionWindow
from pdos_next.schemas.verification.contracts import (
    EventTime,
    MethodPrepare,
    RequestCreate,
    ScheduleProposal,
    SourceRef,
    VerificationRequest,
)
from pdos_next.service import digest, require_access

from .adapters import (
    METHOD_POSITION,
    PROFESSIONAL_PREFIX,
    WINDOW_POSITION,
    TransactionCommands,
    authority_dto,
    handler,
    professional_documents,
    professional_key,
)
from .models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
    MethodApplicability,
    VerificationWindowProposal,
)
from .schemas import MethodPreparePayload, RequestCreatePayload, ScheduleProposePayload

OPERATIONS = {
    "request_create": "verification.request.create",
    "method_prepare": "verification.method.prepare",
    "schedule_propose": "verification.schedule.propose",
}
PHYSICAL_CAPABILITIES = {
    key: False
    for key in (
        "handoff_offer",
        "handoff_accept",
        "schedule_promise",
        "run_plan",
        "run_start",
        "results_import",
        "professional_review",
        "disposition_decide",
    )
}
category_lifecycle_fence = True

EFFECT = "保存具名专业验证前段事实；不交样、不接收、不承诺、不预约占用或开测。"


def _json(value):
    return json.loads(
        json.dumps(
            value,
            default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v),
            ensure_ascii=False,
        )
    )


def _assess(s, ctx, product_id, project_id, operation, purpose, *, write=False, at=None):
    from pdos_next.domain.professional_authority.service import assess

    value = assess(s, ctx, product_id, project_id, operation, purpose, at or now(), write=write)
    if value.get("scope") != {
        "tenant_id": str(ctx.tenant_id),
        "product_id": str(product_id),
        "project_id": str(project_id),
    } or value.get("subject_id") != str(ctx.requester_id):
        raise DomainError("INTEGRITY_MISMATCH", "专业授权未绑定当前具名范围。", 403)
    return _json(value)


def _recheck(s, ctx, product_id, project_id, snapshot, *, at=None):
    from pdos_next.domain.professional_authority.service import recheck_snapshot

    return recheck_snapshot(
        s,
        ctx,
        product_id,
        project_id,
        snapshot,
        at or now(),
        write=False,
        retained=at is not None,
    )


def semantic(payload):
    raw = payload.model_dump(mode="json")
    raw.pop("confirmation_token", None)
    for key in ("assessments", "resource_intents", "sources"):
        if key in raw:
            if key == "assessments":
                for item in raw[key]:
                    item["sources"].sort(key=lambda v: json.dumps(v, sort_keys=True))
            raw[key].sort(key=lambda v: json.dumps(v, sort_keys=True))
    if len(json.dumps(raw, ensure_ascii=False).encode()) > 1_000_000:
        raise DomainError("INVALID_PAYLOAD", "前段验证输入超过1MB上限。", 422)
    return raw


def request_subject(payload):
    return payload.request_id


def replay_subject(*args):
    # Host semantic Receipt/RequestKey dedup handles both request IDs and key aliases.
    return None


def _current(s, ctx, product_id, request_id, *, lock=False):
    query = select(FormalVerificationCurrent).where(
        FormalVerificationCurrent.tenant_id == ctx.tenant_id,
        FormalVerificationCurrent.product_id == product_id,
        FormalVerificationCurrent.request_id == request_id,
    )
    pointer = snapshot_scalar(
        s,
        (FormalVerificationCurrent, product_id, request_id),
        query,
        lock=lock,
        scope_id=product_id,
    )
    if pointer is None:
        return None, None
    row = _row(s, ctx, product_id, pointer.request_version_id)
    if row.request_id != request_id or row.revision != pointer.request_revision:
        raise DomainError("INTEGRITY_MISMATCH", "正式请求当前指针无法核对。")
    return pointer, row


def _row(s, ctx, product_id, identity):
    row = snapshot_get(s, FormalVerificationRequest, identity, scope_id=product_id)
    if row is None or row.tenant_id != ctx.tenant_id or row.product_id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "正式验证请求不在当前可用范围。", 403)
    return row


def _version(s, ctx, product_id, request_id, revision):
    row = snapshot_scalar(
        s,
        (FormalVerificationRequest, "version", product_id, request_id, revision),
        select(FormalVerificationRequest).where(
            FormalVerificationRequest.tenant_id == ctx.tenant_id,
            FormalVerificationRequest.product_id == product_id,
            FormalVerificationRequest.request_id == request_id,
            FormalVerificationRequest.revision == revision,
        ),
        scope_id=product_id,
    )
    if row is None:
        raise DomainError("VERSION_CONFLICT", "固定请求前版不存在，请重新读取。")
    return row


def _snapshot(row):
    value = VerificationRequest.model_validate(row.request_snapshot)
    if digest(value.model_dump(mode="json")) != row.snapshot_sha256 or (
        value.id != row.request_id
        or value.revision != row.revision
        or value.scope.tenant_id != row.tenant_id
        or value.scope.product_id != row.product_id
        or value.scope.project_id != row.project_id
        or value.build.id != row.build_id
        or value.build.revision != row.build_revision
        or value.status
        not in {"draft", "offered", "accepted", "scheduled", "executing", "reported", "disposed"}
        or value.status != row.status
        or (
            value.status in {"draft", "offered", "accepted", "scheduled"}
            and any(getattr(value.timeline, name) is not None for name in EXECUTION_TIMES[2:])
        )
        or (
            value.status == "executing" and (value.timeline.final_result or value.timeline.disposed)
        )
        or (value.status in {"reported", "disposed"} and value.timeline.final_result is None)
        or ((value.timeline.disposed is not None) != (value.status == "disposed"))
        or (
            (value.timeline.promised_start is not None)
            != (value.status in {"scheduled", "executing", "reported", "disposed"})
        )
        or (
            (value.timeline.actual_start is not None)
            != (value.status in {"executing", "reported", "disposed"})
        )
        or (
            value.status == "scheduled"
            and row.operation
            not in {
                "verification.schedule.promise",
                "verification.handoff.accept",
                "verification.handoff.return",
            }
        )
        or (
            value.status == "executing"
            and row.operation
            not in {
                "verification.schedule.promise",
                "verification.handoff.accept",
                "verification.handoff.return",
                "test.run.start",
                "test.results.import",
                "test.run.review",
                "test.disposition.decide",
            }
        )
        or (
            value.status == "reported"
            and row.operation
            not in {"test.results.import", "test.run.review", "test.disposition.decide"}
        )
        or (value.status == "disposed" and row.operation != "test.disposition.decide")
        or (
            value.status == "draft"
            and (
                value.samples
                or value.acceptances
                or value.returns
                or value.offered_coverage
                or any(getattr(value.timeline, name) is not None for name in PHYSICAL_TIMES)
            )
        )
        or (
            value.status != "draft"
            and (not value.samples or not value.offered_coverage or value.timeline.offered is None)
        )
        or (
            value.status in {"accepted", "scheduled", "executing", "reported", "disposed"}
            and (not value.acceptances or value.timeline.accepted is None)
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "固定请求快照或交接/未开测边界无法核对。")
    expected = {professional_key(item.id) for item in value.items}
    actual = {doc.id for doc in value.documents if doc.id.startswith(PROFESSIONAL_PREFIX)}
    if expected != actual or any(
        not doc.required for doc in value.documents if doc.id.startswith(PROFESSIONAL_PREFIX)
    ):
        raise DomainError("INTEGRITY_MISMATCH", "逐项专业适用证明缺失。")
    for doc in value.documents:
        if (
            doc.id.startswith(PROFESSIONAL_PREFIX)
            and doc.source is not None
            and (
                doc.source.kind != "domain"
                or doc.source.revision != 1
                or doc.source.position != METHOD_POSITION
            )
        ):
            raise DomainError("INTEGRITY_MISMATCH", "原文引用不能代替专业适用事实。")
    return value


PHYSICAL_TIMES = (
    "sample_ready",
    "offered",
    "accepted",
    "promised_start",
    "actual_start",
    "preliminary_result",
    "final_result",
    "disposed",
)
EXECUTION_TIMES = (
    "promised_start",
    "actual_start",
    "preliminary_result",
    "final_result",
    "disposed",
)


def _payload_refs(payload):
    refs = list(getattr(payload, "sources", ()))
    if isinstance(payload, MethodPreparePayload):
        refs.extend(ref for item in payload.assessments for ref in item.sources)
    if isinstance(payload, ScheduleProposePayload):
        refs.extend(ref for ref in (payload.duration_basis, payload.calendar_source) if ref)
    values = {
        json.dumps(ref.model_dump(mode="json"), sort_keys=True): ref.model_dump(mode="json")
        for ref in refs
    }
    return [values[key] for key in sorted(values)]


@dataclass
class Bound:
    build: object
    preparation: object
    base: VerificationRequest
    previous: object
    authority: dict
    references: list
    reads: list
    visibility: str
    at: datetime


def _load(s, ctx, command, product, payload, *, require_reads=True):
    write = not getattr(s, "info", {}).get("read_snapshot", False)
    _human(s, ctx, product.id, write=write)
    require_access(s, ctx, product.id, write=True, lock=write)
    if product.tenant_id != ctx.tenant_id or command.product_id != product.id:
        raise DomainError("FORBIDDEN_SCOPE", "验证不在当前型号范围。", 403)
    if isinstance(payload, RequestCreatePayload):
        prep, _ = preparation_service.get_preparation(s, ctx, product.id, payload.preparation_id)
        if prep.revision != payload.expected_preparation_revision or (
            prep.snapshot_sha256 != payload.preparation_sha256
        ):
            raise DomainError("VERSION_CONFLICT", "指定准备版与摘要不一致。")
        from pdos_next.enterprise_search.verification_adoption import recheck_request

        recheck_request(s, ctx, prep)
        base, previous = preparation_service._snapshot(prep), None
    else:
        previous = _version(
            s, ctx, product.id, payload.request_id, payload.expected_request_revision
        )
        prep, _ = preparation_service.get_preparation(s, ctx, product.id, previous.preparation_id)
        base = _snapshot(previous)
        if base.status != "draft":
            raise DomainError("INVALID_STATE", "已进入实物交接的请求须在交接办理中续接。")
        if prep.revision != previous.preparation_revision or prep.snapshot_sha256 != (
            previous.preparation_sha256
        ):
            raise DomainError("INTEGRITY_MISMATCH", "固定原准备绑定无法核对。")
    build = _build(s, ctx, product.id, base.build.id)
    _, engineering, manufacturing, planned_reads = _linked(
        s, ctx, product.id, build, new_consumption=True
    )
    if (
        base.build.product_id != product.id
        or base.build.project_id != build.project_id
        or (
            base.build.revision != build.revision
            or str(base.build.engineering_configuration.id) != engineering["id"]
            or base.build.engineering_configuration.revision != engineering["revision"]
            or str(base.build.manufacturing_configuration.id) != manufacturing["id"]
            or base.build.manufacturing_configuration.revision != manufacturing["revision"]
        )
    ):
        raise DomainError("SOURCE_CHANGED", "固定Build与双配置不能一致核对。")
    references = _payload_refs(payload)
    refs = {
        json.dumps(v, sort_keys=True): v
        for v in [*prep.sources, *(previous.sources if previous else []), *references]
    }
    references = [refs[key] for key in sorted(refs)]
    at = now()
    authority = _assess(
        s, ctx, product.id, build.project_id, command.operation, base.purpose, write=write, at=at
    )
    reads = _merge_reads(
        planned_reads,
        prep.required_source_read_set,
        references,
        previous.required_source_read_set if previous else [],
        authority["required_source_read_set"],
    )
    if require_reads:
        supplied = {
            str(read.artifact_id): read.expected_revision for read in command.source_read_set
        }
        if any(supplied.get(read["artifact_id"]) != read["expected_revision"] for read in reads):
            raise DomainError(
                "MISSING_REQUIRED_EVIDENCE", "需要固定准备、双配置和专业事实全部来源。"
            )
    _, private = _sources(s, ctx, product.id, reads, references)
    visibility = "private" if private or prep.visibility != "category" else "category"
    if previous is not None:
        if visibility == "private" and previous.visibility == "category":
            raise DomainError("FORBIDDEN_SCOPE", "私有来源不能加入共享正式请求。", 403)
        visibility = previous.visibility
    return Bound(build, prep, base, previous, authority, references, reads, visibility, now())


def validate(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    # Current authority before Receipt replay; latest-pointer CAS is after dedup.
    _authorize(bound, ctx)
    if isinstance(payload, ScheduleProposePayload):
        _check_existing_proofs(s, ctx, product.id, bound.base)


def _authorize(bound, ctx):
    from pdos_next.domain.verification.handlers import VerificationHandler

    dto = authority_dto(bound.authority, ctx.requester_id, bound.at)
    VerificationHandler(None)._authorize(dto, bound.authority["operation"])


def _new_write(s, ctx, command, product, payload, bound):
    write = not getattr(s, "info", {}).get("read_snapshot", False)
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围版本已变化。")
    pointer, current = _current(s, ctx, product.id, payload.request_id, lock=write)
    expected = 0 if isinstance(payload, RequestCreatePayload) else payload.expected_request_revision
    if (current.revision if current else 0) != expected:
        raise DomainError("VERSION_CONFLICT", "正式请求当前版本已变化。")
    if current is not None and current.id != bound.previous.id:
        raise DomainError("VERSION_CONFLICT", "续版须基于固定当前请求。")
    return pointer


def _child_id(command, item_key):
    return uuid5(NAMESPACE_URL, f"pdos-verification:{command.command_id}:{item_key}")


def _method_candidate(ctx, command, payload, bound, assessment):
    item = next(item for item in bound.base.items if item.id == assessment.item_id)
    if assessment.status == "applicable":
        ordinary = [
            doc for doc in bound.base.documents if not doc.id.startswith(PROFESSIONAL_PREFIX)
        ]
        trial = VerificationRequest.model_validate(
            {**bound.base.model_dump(), "documents": ordinary}
        )
        if document_gaps(trial, {item.id}):
            raise DomainError(
                "METHOD_EVIDENCE_INCOMPLETE", "缺失方法、判据或资料不能声明专业适用。", 422
            )
    snapshot = {
        "item_id": item.id,
        "status": assessment.status,
        "conditions": list(assessment.conditions),
        "reason": assessment.reason,
        "fixed_item": item.model_dump(mode="json"),
        "build": bound.base.build.model_dump(mode="json"),
        "reviewer_id": str(ctx.requester_id),
        "reviewed_at": bound.at.isoformat(),
        "original_timezone": "UTC",
        "sources": [ref.model_dump(mode="json") for ref in assessment.sources],
    }
    return MethodApplicability(
        id=_child_id(command, f"method:{item.id}"),
        tenant_id=ctx.tenant_id,
        product_id=bound.base.scope.product_id,
        project_id=bound.build.project_id,
        request_id=payload.request_id,
        request_version_id=bound.previous.id,
        request_revision=bound.previous.revision,
        item_id=item.id,
        revision=1,
        owner_id=ctx.requester_id,
        visibility=bound.visibility,
        status=assessment.status,
        engineering_configuration_id=bound.base.build.engineering_configuration.id,
        engineering_configuration_revision=bound.base.build.engineering_configuration.revision,
        manufacturing_configuration_id=bound.base.build.manufacturing_configuration.id,
        manufacturing_configuration_revision=bound.base.build.manufacturing_configuration.revision,
        method_ref=item.method.model_dump(mode="json") if item.method else None,
        assessment_snapshot=snapshot,
        authority_snapshot=bound.authority,
        sources=bound.references,
        required_source_read_set=bound.reads,
        snapshot_sha256=digest(snapshot),
        created_at=bound.at,
    )


def _window_candidate(ctx, command, payload, bound):
    window = ExecutionWindow(
        start=payload.start, finish=payload.finish, original_timezone=payload.original_timezone
    )
    gaps = [
        {
            "code": "RESOURCE_RESERVATION_UNCONNECTED",
            "detail": "暂定建议不占用资源；正式预约未接通。",
        }
    ]
    if payload.duration_basis is None:
        gaps.append(
            {"code": "DURATION_UNKNOWN", "detail": "缺少权威工时依据；输入区间不是工时承诺。"}
        )
    if payload.calendar_source is None:
        gaps.append({"code": "CALENDAR_UNKNOWN", "detail": "资源工作日历未核验。"})
    if not payload.resource_intents:
        gaps.append({"code": "RESOURCE_REQUIREMENTS_UNKNOWN", "detail": "所需资源集合未知。"})
    for item in payload.resource_intents:
        if item.resource_id is None or item.units is None:
            gaps.append({"code": "RESOURCE_IDENTITY_OR_UNITS_UNKNOWN", "detail": item.label})
    return VerificationWindowProposal(
        id=_child_id(command, "window"),
        tenant_id=ctx.tenant_id,
        product_id=bound.base.scope.product_id,
        project_id=bound.build.project_id,
        request_id=payload.request_id,
        request_version_id=bound.previous.id,
        request_revision=bound.previous.revision,
        revision=1,
        owner_id=ctx.requester_id,
        visibility=bound.visibility,
        status="tentative",
        window=window.model_dump(mode="json"),
        input_snapshot=semantic(payload),
        reason=payload.reason,
        resources=[item.model_dump(mode="json") for item in payload.resource_intents],
        gaps=gaps,
        authority_snapshot=bound.authority,
        sources=bound.references,
        required_source_read_set=bound.reads,
        snapshot_sha256=digest(semantic(payload)),
        occupancy=0,
        created_at=bound.at,
    )


def _children(ctx, command, payload, bound):
    if isinstance(payload, MethodPreparePayload):
        if {item.item_id for item in payload.assessments} != {item.id for item in bound.base.items}:
            raise DomainError("INVALID_COVERAGE", "专业适用核对须逐项覆盖固定测试项。", 422)
        return [
            _method_candidate(ctx, command, payload, bound, item) for item in payload.assessments
        ]
    if isinstance(payload, ScheduleProposePayload):
        if payload.start < bound.at:
            raise DomainError("INVALID_EVENT_TIME", "前置暂定窗口不能回填过去时段。", 422)
        return [_window_candidate(ctx, command, payload, bound)]
    return []


def _method_check(s, ctx, product_id, row, request, *, prospective=False, positive=True):
    item = next((item for item in request.items if item.id == row.item_id), None)
    snap = row.assessment_snapshot
    if (
        row.tenant_id != ctx.tenant_id
        or row.product_id != product_id
        or (
            row.project_id != request.scope.project_id
            or row.request_id != request.id
            or (positive and row.status != "applicable")
            or row.revision != 1
            or item is None
            or snap.get("fixed_item") != item.model_dump(mode="json")
            or snap.get("build") != request.build.model_dump(mode="json")
            or snap.get("reviewer_id") != str(row.owner_id)
            or row.authority_snapshot.get("subject_id") != str(row.owner_id)
            or row.authority_snapshot.get("operation") != "verification.method.prepare"
            or row.authority_snapshot.get("purpose") != request.purpose
            or row.method_ref != (item.method.model_dump(mode="json") if item.method else None)
            or row.snapshot_sha256 != digest(snap)
            or row.engineering_configuration_id != request.build.engineering_configuration.id
            or row.engineering_configuration_revision
            != request.build.engineering_configuration.revision
            or row.manufacturing_configuration_id != request.build.manufacturing_configuration.id
            or row.manufacturing_configuration_revision
            != request.build.manufacturing_configuration.revision
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "专业方法适用记录与固定项/计划双配置不一致。")
    if not prospective:
        parent = _row(s, ctx, product_id, row.request_version_id)
        if parent.revision != row.request_revision or parent.request_id != request.id:
            raise DomainError("INTEGRITY_MISMATCH", "专业核对前版绑定无法核对。")
        _sources(s, ctx, product_id, row.required_source_read_set, row.sources)
        if not _recheck(s, ctx, product_id, row.project_id, row.authority_snapshot)["current"]:
            raise DomainError("SOURCE_STALE", "原具名核对人的专业资格或授权依据已变化。")


def _check_existing_proofs(s, ctx, product_id, request):
    for doc in request.documents:
        if doc.id.startswith(PROFESSIONAL_PREFIX) and doc.source:
            row = snapshot_get(s, MethodApplicability, doc.source.id, scope_id=product_id)
            if row is None or doc.source.kind != "domain" or doc.source.position != METHOD_POSITION:
                raise DomainError("SOURCE_UNAVAILABLE", "固定专业适用记录不存在。")
            _method_check(s, ctx, product_id, row, request)


def _kernel_payload(command, payload, bound, children):
    if isinstance(payload, RequestCreatePayload):
        return RequestCreate(
            request_id=payload.request_id,
            build_id=bound.base.build.id,
            expected_build_revision=bound.base.build.revision,
            title=bound.base.title,
            purpose=bound.base.purpose,
            items=bound.base.items,
            documents=professional_documents(bound.base.items, bound.base.documents),
            expected_at=bound.base.expected_at,
            expected_timezone=bound.base.expected_timezone,
            return_form=bound.base.return_form,
        )
    if isinstance(payload, MethodPreparePayload):
        refs = {
            row.item_id: SourceRef(id=row.id, revision=1, kind="domain", position=METHOD_POSITION)
            for row in children
            if row.status == "applicable"
        }
        ordinary = [
            doc for doc in bound.base.documents if not doc.id.startswith(PROFESSIONAL_PREFIX)
        ]
        return MethodPrepare(
            items=bound.base.items,
            documents=professional_documents(bound.base.items, ordinary, refs),
            tentative_start=bound.base.tentative_start,
        )
    return ScheduleProposal(
        at=EventTime(
            occurred_at=payload.start,
            original_timezone=payload.original_timezone,
            source=SourceRef(
                id=children[0].id, revision=1, kind="domain", position=WINDOW_POSITION
            ),
        )
    )


def _kernel(
    s, ctx, command, product, bound, children, record, *, accepted=False, prospective=False
):
    sealed = {row.id: row for row in children}
    artifact_refs = {
        preparation_service._source(
            SimpleNamespace(**{**ref, "artifact_id": UUID(ref["artifact_id"])})
        ): ref
        for ref in bound.references
    }

    def check_source(scope, source, purpose):
        if scope != bound.base.scope:
            raise DomainError("FORBIDDEN_SCOPE", "来源不在固定服务器范围。", 403)
        if source.kind == "artifact":
            if source not in artifact_refs:
                raise DomainError("MISSING_REQUIRED_EVIDENCE", "来源位置不是固定精确原文引用。")
            return  # _load already locked and verified exact quote/hash/security/ACL.
        if source.kind != "domain":
            raise DomainError("SOURCE_UNAVAILABLE", "前段来源仅允许固定原文和已登记专业事实。")
        row = sealed.get(source.id) if prospective else None
        if source.position == METHOD_POSITION:
            row = row or snapshot_get(s, MethodApplicability, source.id, scope_id=product.id)
            if row is None or source.revision != 1:
                raise DomainError("SOURCE_UNAVAILABLE", "专业适用记录不存在。")
            _method_check(
                s, ctx, product.id, row, bound.base, prospective=prospective and source.id in sealed
            )
        elif source.position == WINDOW_POSITION:
            row = row or s.get(VerificationWindowProposal, source.id)
            if (
                row is None
                or source.revision != 1
                or row.occupancy != 0
                or (
                    row.tenant_id != ctx.tenant_id
                    or row.product_id != product.id
                    or row.project_id != bound.build.project_id
                    or row.request_id != bound.base.id
                    or row.snapshot_sha256 != digest(row.input_snapshot)
                )
            ):
                raise DomainError("INTEGRITY_MISMATCH", "暂定窗口事实不能一致核对。")
            fixed_window = ScheduleProposePayload.model_validate(row.input_snapshot)
            expected_window = ExecutionWindow(
                start=fixed_window.start,
                finish=fixed_window.finish,
                original_timezone=fixed_window.original_timezone,
            ).model_dump(mode="json")
            if (
                row.window != expected_window
                or fixed_window.request_id != row.request_id
                or (
                    fixed_window.expected_request_revision != row.request_revision
                    or row.resources
                    != [item.model_dump(mode="json") for item in fixed_window.resource_intents]
                    or row.authority_snapshot.get("subject_id") != str(row.owner_id)
                    or row.authority_snapshot.get("operation") != "verification.schedule.propose"
                    or row.authority_snapshot.get("purpose") != bound.base.purpose
                )
            ):
                raise DomainError("INTEGRITY_MISMATCH", "暂定窗口原始输入或专业事实绑定不一致。")
            if not (prospective and source.id in sealed):
                parent = _row(s, ctx, product.id, row.request_version_id)
                if parent.request_id != bound.base.id or parent.revision != row.request_revision:
                    raise DomainError("INTEGRITY_MISMATCH", "暂定窗口审阅前版不一致。")
                _sources(s, ctx, product.id, row.required_source_read_set, row.sources)
                if not _recheck(s, ctx, product.id, row.project_id, row.authority_snapshot)[
                    "current"
                ]:
                    raise DomainError("SOURCE_STALE", "原暂定建议专业依据已变化。")
        else:
            raise DomainError("SOURCE_UNAVAILABLE", "未知专业领域来源位置。")

    commands = TransactionCommands(
        authority_dto(bound.authority, ctx.requester_id, bound.at),
        bound.base if bound.previous else None,
        record,
        accepted_confirmation=accepted,
    )
    return handler(commands, bound.base.build, bound.build.status, check_source), commands


def _invocation(command, payload, kernel_payload):
    from pdos_next.domain.verification.handlers import semantic_digest

    return Invocation(
        command_id=command.command_id,
        operation=command.operation,
        subject_id=payload.request_id,
        expected_revision=0
        if isinstance(payload, RequestCreatePayload)
        else payload.expected_request_revision,
        semantic_digest=semantic_digest(kernel_payload),
    )


def _stored_input(payload, bound, children):
    raw = semantic(payload)
    raw["method_assessment_refs"] = (
        [
            {"id": str(row.id), "revision": 1}
            for row in children
            if isinstance(row, MethodApplicability)
        ]
        if isinstance(payload, MethodPreparePayload)
        else deepcopy(
            bound.previous.input_snapshot.get("method_assessment_refs", [])
            if bound.previous
            else []
        )
    )
    return raw


def _record(s, ctx, command, product, payload, bound, pointer, mutation, children):
    value = mutation.request
    if mutation.run is not None or value is None or value.status != "draft":
        raise DomainError("INTEGRITY_MISMATCH", "前段命令不能写入实物执行状态。")
    row = FormalVerificationRequest(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=bound.build.project_id,
        build_id=bound.build.id,
        build_revision=bound.build.revision,
        request_id=payload.request_id,
        revision=value.revision,
        previous_request_id=bound.previous.id if bound.previous else None,
        previous_revision=bound.previous.revision if bound.previous else None,
        owner_id=bound.previous.owner_id if bound.previous else ctx.requester_id,
        visibility=bound.visibility,
        status="draft",
        operation=command.operation,
        preparation_id=bound.preparation.id,
        preparation_revision=bound.preparation.revision,
        preparation_sha256=bound.preparation.snapshot_sha256,
        purpose=value.purpose,
        request_snapshot=value.model_dump(mode="json"),
        input_snapshot=_stored_input(payload, bound, children),
        snapshot_sha256=digest(value.model_dump(mode="json")),
        sources=bound.references,
        required_source_read_set=bound.reads,
        authority_snapshot=bound.authority,
        intent_digest=digest(
            {
                "operation": command.operation,
                "payload": semantic(payload),
                "actor": ctx.requester_id,
            }
        ),
        reason=payload.reason,
        created_at=bound.at,
    )
    s.add(row)
    s.flush()
    if pointer is None:
        s.add(
            FormalVerificationCurrent(
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                request_id=payload.request_id,
                request_version_id=row.id,
                request_revision=row.revision,
            )
        )
    else:
        pointer.request_version_id, pointer.request_revision = row.id, row.revision
    s.flush()
    return row


def apply(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _authorize(bound, ctx)
    pointer = _new_write(s, ctx, command, product, payload, bound)
    children = _children(ctx, command, payload, bound)
    for row in children:
        s.add(row)
    # Parent is the already persisted reviewed version, so these are actual UOW facts.
    s.flush()
    kernel_payload = _kernel_payload(command, payload, bound, children)
    recorded = []

    def save(mutation):
        row = _record(s, ctx, command, product, payload, bound, pointer, mutation, children)
        recorded.append(row)
        return row

    kernel, _ = _kernel(
        s,
        ctx,
        command,
        product,
        bound,
        children,
        save,
        accepted=isinstance(payload, MethodPreparePayload),
    )
    kernel.execute(_invocation(command, payload, kernel_payload), kernel_payload)
    return recorded[0], "verification_request", bound.visibility


def _authority_rows(s, ctx, product_id, project_id, purpose):
    return {
        key: _assess(s, ctx, product_id, project_id, operation, purpose)
        for key, operation in OPERATIONS.items()
    }


def _caps(authorities, *, source_current=True, current=True):
    return {
        **PHYSICAL_CAPABILITIES,
        **{
            key: source_current
            and current
            and value["authorized"] is True
            and value["qualified"] is True
            for key, value in authorities.items()
        },
    }


def _assessment_view(s, ctx, product_id, row, request, *, prospective=False):
    status, reasons = True, []
    if not prospective:
        try:
            _method_check(s, ctx, product_id, row, request, positive=False)
            _sources(s, ctx, product_id, row.required_source_read_set, row.sources)
            checked = _recheck(s, ctx, product_id, row.project_id, row.authority_snapshot)
            status, reasons = checked["current"], checked["reason_codes"]
        except DomainError as error:
            status, reasons = False, [error.reason]
    value = row.assessment_snapshot
    return {
        "id": str(row.id),
        "revision": row.revision,
        "item_id": row.item_id,
        "status": row.status,
        "conditions": value["conditions"],
        "reason": value["reason"],
        "reviewer_id": value["reviewer_id"],
        "reviewed_at": None if prospective else value["reviewed_at"],
        "request_version_id": str(row.request_version_id),
        "request_revision": row.request_revision,
        "build": value["build"],
        "method_ref": row.method_ref,
        "authority": row.authority_snapshot,
        "current": status,
        "reason_codes": reasons,
        "sources": row.sources,
        "required_source_read_set": row.required_source_read_set,
        "sha256": None if prospective else row.snapshot_sha256,
    }


def _window_view(s, ctx, product_id, row, *, prospective=False):
    current, reasons = True, []
    if not prospective:
        try:
            _sources(s, ctx, product_id, row.required_source_read_set, row.sources)
            result = _recheck(s, ctx, product_id, row.project_id, row.authority_snapshot)
            current, reasons = result["current"], result["reason_codes"]
        except DomainError as error:
            current, reasons = False, [error.reason]
    return {
        "id": str(row.id),
        "revision": row.revision,
        "status": row.status,
        "request_version_id": str(row.request_version_id),
        "request_revision": row.request_revision,
        "window": row.window,
        "resources": row.resources,
        "gaps": row.gaps,
        "readiness": "UNKNOWN",
        "occupancy": 0,
        "reason": row.reason,
        "created_at": None if prospective else row.created_at.isoformat(),
        "authority": row.authority_snapshot,
        "current": current,
        "reason_codes": reasons,
        "sources": row.sources,
        "required_source_read_set": row.required_source_read_set,
    }


def _view(
    s,
    ctx,
    product_id,
    row,
    request,
    preparation,
    *,
    current=True,
    prospective=False,
    children=(),
    assess_capabilities=True,
):
    source_status = "current" if prospective else _read_evidence(s, ctx, product_id, row)
    # Fixed owner output retains the saved parent/child proofs below, while
    # prospective caller command abilities are only needed by the normal UI.
    authorities = (
        _authority_rows(s, ctx, product_id, row.project_id, request.purpose)
        if assess_capabilities
        else {}
    )
    command_reads = _merge_reads(
        row.required_source_read_set,
        *(value["required_source_read_set"] for value in authorities.values()),
    )
    method_ids = {
        doc.source.id
        for doc in request.documents
        if doc.id.startswith(PROFESSIONAL_PREFIX) and doc.source
    }
    method_ids.update(
        UUID(ref["id"]) for ref in row.input_snapshot.get("method_assessment_refs", [])
    )
    proposed = {child.id: child for child in children}
    methods = []
    for identity in sorted(method_ids, key=str):
        method = proposed.get(identity) or snapshot_get(
            s, MethodApplicability, identity, scope_id=product_id
        )
        if method is None:
            raise DomainError("INTEGRITY_MISMATCH", "固定专业适用记录缺失。")
        view = _assessment_view(
            s, ctx, product_id, method, request, prospective=prospective and identity in proposed
        )
        original = next(
            item for item in preparation.input_snapshot["items"] if item["id"] == method.item_id
        )
        view["original_method"] = original["method"]
        methods.append(view)
    for child in children:
        if isinstance(child, MethodApplicability) and child.id not in method_ids:
            methods.append(_assessment_view(s, ctx, product_id, child, request, prospective=True))
    window_ids = {request.tentative_start.source.id} if request.tentative_start else set()
    windows = []
    for identity in window_ids:
        window = proposed.get(identity) or s.get(VerificationWindowProposal, identity)
        if window is None:
            raise DomainError("INTEGRITY_MISMATCH", "固定暂定窗口记录缺失。")
        windows.append(
            _window_view(
                s, ctx, product_id, window, prospective=prospective and identity in proposed
            )
        )
    documents_ready = (
        source_status == "current"
        and not document_gaps(request)
        and len(methods) == len(request.items)
        and all(item["current"] and item["status"] == "applicable" for item in methods)
    )
    raw = request.model_dump(mode="json")
    if prospective:
        if row.revision == 1:
            raw["timeline"]["request_created"]["occurred_at"] = None
            raw["timeline"]["request_created"]["received_at"] = None
        if row.operation == "verification.method.prepare" and raw["timeline"]["documents_complete"]:
            raw["timeline"]["documents_complete"]["occurred_at"] = None
            raw["timeline"]["documents_complete"]["received_at"] = None
    return {
        "id": None if prospective else str(row.id),
        "request_id": str(row.request_id),
        "revision": row.revision,
        "previous_request_id": str(row.previous_request_id) if row.previous_request_id else None,
        "previous_revision": row.previous_revision,
        "project_id": str(row.project_id),
        "build": request.build.model_dump(mode="json"),
        "preparation_id": str(row.preparation_id),
        "preparation_revision": row.preparation_revision,
        "preparation_sha256": row.preparation_sha256,
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "status": request.status,
        "operation": row.operation,
        "title": request.title,
        "purpose": request.purpose,
        "return_form": request.return_form,
        "items": deepcopy(preparation.input_snapshot["items"]),
        "documents": deepcopy(preparation.input_snapshot["documents"]),
        "professional_documents": [
            doc.model_dump(mode="json")
            for doc in request.documents
            if doc.id.startswith(PROFESSIONAL_PREFIX)
        ],
        "request_snapshot": raw,
        "document_gaps": [gap.model_dump(mode="json") for gap in document_gaps(request)],
        "coverage_gaps": [
            gap.model_dump(mode="json")
            for gap in coverage_gaps(request, accepted_coverage(request))
        ],
        "method_assessments": methods,
        "window_proposals": windows,
        "documents_ready": documents_ready,
        "document_milestone_current": documents_ready
        if request.timeline.documents_complete
        else None,
        "first_requested_at": None
        if prospective and row.revision == 1
        else request.timeline.request_created.received_at.isoformat(),
        "created_at": None if prospective else row.created_at.isoformat(),
        "sha256": None if prospective else row.snapshot_sha256,
        "reason": row.reason,
        "sources": row.sources,
        "required_source_read_set": command_reads,
        "authority": authorities,
        "capabilities": _caps(
            authorities,
            source_current=source_status == "current",
            current=current and request.status == "draft",
        ),
        "source_status": source_status,
        "is_current": current,
        "freshness": "requires_recalculation"
        if source_status != "current"
        or (request.timeline.documents_complete and not documents_ready)
        else "current"
        if current
        else "historical",
        "zero_occupancy": request.timeline.actual_start is None,
        "physical_timeline_empty": not any(
            getattr(request.timeline, name) is not None for name in PHYSICAL_TIMES
        ),
        "blockers": [
            {
                "code": "TEST_EXECUTION_UNCONNECTED",
                "detail": "实物交样与品质接收请在样件交接入口办理；正式预约、开测与结果仍未接通。",
            }
        ],
    }


def preview_view(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _authorize(bound, ctx)
    _new_write(s, ctx, command, product, payload, bound)
    children = _children(ctx, command, payload, bound)
    kernel_payload = _kernel_payload(command, payload, bound, children)
    kernel, commands = _kernel(
        s, ctx, command, product, bound, children, lambda _: None, prospective=True
    )
    invocation = _invocation(command, payload, kernel_payload)
    kernel.preview(
        command.operation, invocation.subject_id, invocation.expected_revision, kernel_payload
    )
    _, mutation = kernel._prepare(commands.authority, invocation, kernel_payload)
    request = mutation.request
    row = SimpleNamespace(
        id=None,
        request_id=payload.request_id,
        revision=request.revision,
        previous_request_id=bound.previous.id if bound.previous else None,
        previous_revision=bound.previous.revision if bound.previous else None,
        project_id=bound.build.project_id,
        preparation_id=bound.preparation.id,
        preparation_revision=bound.preparation.revision,
        preparation_sha256=bound.preparation.snapshot_sha256,
        owner_id=bound.previous.owner_id if bound.previous else ctx.requester_id,
        visibility=bound.visibility,
        operation=command.operation,
        reason=payload.reason,
        input_snapshot=_stored_input(payload, bound, children),
        sources=bound.references,
        required_source_read_set=bound.reads,
    )
    before = (
        _view(s, ctx, product.id, bound.previous, bound.base, bound.preparation)
        if bound.previous
        else None
    )
    after = _view(
        s, ctx, product.id, row, request, bound.preparation, prospective=True, children=children
    )
    return {
        "operation": command.operation,
        "effect": EFFECT,
        "reason": payload.reason,
        "before": before,
        "after": after,
        "authority": bound.authority,
        "required_source_read_set": bound.reads,
        "gap_changes": preparation_service._changes(before, after),
    }


def get_request(s, ctx, product_id, identity, *, assess_capabilities=True):
    _human(s, ctx, product_id)
    row = _row(s, ctx, product_id, identity)
    request = _snapshot(row)
    prep, _ = preparation_service.get_preparation(s, ctx, product_id, row.preparation_id)
    _, latest = _current(s, ctx, product_id, row.request_id)
    return row, _view(
        s,
        ctx,
        product_id,
        row,
        request,
        prep,
        current=latest is not None and latest.id == row.id,
        assess_capabilities=assess_capabilities,
    )


def list_verification(s, ctx, product_id):
    _human(s, ctx, product_id)
    from pdos_next.domain.verification_execution.models import VerificationPreparation

    identities = s.scalars(
        select(FormalVerificationRequest.id)
        .where(
            FormalVerificationRequest.tenant_id == ctx.tenant_id,
            FormalVerificationRequest.product_id == product_id,
        )
        .order_by(FormalVerificationRequest.created_at, FormalVerificationRequest.id)
    ).all()
    requests, preparations, current, unavailable, groups = [], [], {}, 0, {}
    for identity in identities:
        try:
            _, view = get_request(s, ctx, product_id, identity)
        except DomainError:
            unavailable += 1
            continue
        requests.append(view)
        if view["is_current"]:
            current[view["request_id"]] = {
                "request_version_id": view["id"],
                "revision": view["revision"],
            }
        groups[(view["project_id"], view["purpose"])] = view["authority"]
    prep_ids = s.scalars(
        select(VerificationPreparation.id)
        .where(
            VerificationPreparation.tenant_id == ctx.tenant_id,
            VerificationPreparation.product_id == product_id,
        )
        .order_by(VerificationPreparation.created_at, VerificationPreparation.id)
    ).all()
    for identity in prep_ids:
        try:
            row, view = preparation_service.get_preparation(s, ctx, product_id, identity)
            authority = _authority_rows(s, ctx, product_id, row.project_id, view["purpose"])
            refs = _merge_reads(
                view["required_source_read_set"],
                *(value["required_source_read_set"] for value in authority.values()),
            )
            view.update(
                authority=authority,
                capabilities=_caps(authority, source_current=view["source_status"] == "current"),
                required_source_read_set=refs,
            )
            preparations.append(view)
            groups[(str(row.project_id), view["purpose"])] = authority
        except DomainError:
            unavailable += 1
    caps = {
        **PHYSICAL_CAPABILITIES,
        **{
            key: any(view["capabilities"][key] for view in [*requests, *preparations])
            for key in OPERATIONS
        },
    }
    return {
        "requests": requests,
        "current_by_request": current,
        "preparations": preparations,
        "capabilities": caps,
        "authority_by_project": [
            {"project_id": project, "purpose": purpose, "operations": authority}
            for (project, purpose), authority in sorted(groups.items())
        ],
        "blockers": [
            {
                "code": "TEST_EXECUTION_UNCONNECTED",
                "detail": "实物交样与品质接收请在样件交接入口办理；正式预约、开测与结果仍未接通。",
            }
        ],
        "has_more": False,
        "unavailable_count": unavailable,
    }
