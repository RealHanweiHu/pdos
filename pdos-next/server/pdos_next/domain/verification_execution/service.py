"""Human preparation versions, using pure verification rules without granting qualifications."""

import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.database import category_for_product
from pdos_next.domain.configurations.service import _decimal, _merge_reads
from pdos_next.domain.supply_execution.service import (
    _build,
    _human,
    _linked,
    _read_evidence,
    _sources,
)
from pdos_next.domain.verification.rules import coverage_gaps, document_gaps
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from pdos_next.request_proof import snapshot_scalar
from pdos_next.schemas.verification.contracts import (
    BuildRef,
    ConfigurationRef,
    DocumentRequirement,
    EventTime,
    NumericCriterion,
    Scope,
    SourceRef,
    TestItem,
    TimeFact,
    Timeline,
    VerificationRequest,
)
from pdos_next.service import require_access

from .models import VerificationCurrent, VerificationPreparation
from .schemas import PreparationRecordPayload

category_lifecycle_fence = True

EFFECT = (
    "保存人工验证准备的固定版本与资料、数量、模穴缺项；"
    "尚未交样、正式接收、预约或开测，不授方法适用、专业资格或批准。"
)


def _capabilities(can_write=True):
    return {
        "preparation_record": can_write,
        "request_create": False,
        "handoff_offer": False,
        "handoff_accept": False,
        "schedule_promise": False,
        "run_plan": False,
        "run_start": False,
        "results_import": False,
        "professional_review": False,
        "disposition_decide": False,
    }


def _blockers(build=None, samples=()):
    items = [
        {
            "code": "PROFESSIONAL_QUALIFICATION_UNCONNECTED",
            "detail": "品质/测试职责和专业资格接口尚未接通。",
            "sample_id": None,
        },
        {
            "code": "RESOURCE_QUALIFICATION_UNCONNECTED",
            "detail": "设备校准、治具适用、人员与资源预约核对尚未接通。",
            "sample_id": None,
        },
        {
            "code": "SAMPLE_CONSUMPTION_UNCONNECTED",
            "detail": "样件预约、破坏性消耗及并发复查接口尚未接通。",
            "sample_id": None,
        },
    ]
    if build is not None and build.status not in {"executing", "evaluating", "closed"}:
        items.insert(
            0,
            {
                "code": "BUILD_NOT_EXECUTING",
                "detail": "本轮Build仍为计划，外部产出观察不证明已获授权开工。",
                "sample_id": None,
            },
        )
    for sample in samples:
        availability = sample["availability"]
        items.append(
            {
                "code": "SAMPLE_ON_HOLD"
                if availability == "hold"
                else "SAMPLE_AVAILABILITY_UNKNOWN",
                "detail": "参考样件处于暂缓状态，不能据此接收或开测。"
                if availability == "hold"
                else "参考样件可用性未知，未成为已交接或接收范围。",
                "sample_id": sample["id"],
            }
        )
    return items


def _row(s, ctx, product_id, identity, *, write=False):
    row = snapshot_scalar(
        s,
        (VerificationPreparation, product_id, identity),
        select(VerificationPreparation).where(
            VerificationPreparation.id == identity,
            VerificationPreparation.tenant_id == ctx.tenant_id,
            VerificationPreparation.product_id == product_id,
        ),
        scope_id=product_id,
    )
    if (
        row is None
        or (row.visibility == "private" and row.owner_id != ctx.requester_id)
        or (write and row.owner_id != ctx.requester_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "验证准备不在当前可用范围。", 403)
    build = _build(s, ctx, product_id, row.build_id)
    if row.project_id != build.project_id:
        raise DomainError("FORBIDDEN_SCOPE", "验证准备不属于该固定项目。", 403)
    return row, build


def _version(s, ctx, product_id, request_id, revision):
    identity = s.scalar(
        select(VerificationPreparation.id).where(
            VerificationPreparation.tenant_id == ctx.tenant_id,
            VerificationPreparation.product_id == product_id,
            VerificationPreparation.request_id == request_id,
            VerificationPreparation.revision == revision,
        )
    )
    if identity is None:
        raise DomainError("VERSION_CONFLICT", "指定的准备前版不存在，请重新读取。")
    return _row(s, ctx, product_id, identity, write=True)[0]


def _current(s, ctx, product_id, request_id, *, lock=False):
    query = select(VerificationCurrent).where(
        VerificationCurrent.tenant_id == ctx.tenant_id,
        VerificationCurrent.product_id == product_id,
        VerificationCurrent.request_id == request_id,
    )
    pointer = snapshot_scalar(
        s, (VerificationCurrent, product_id, request_id), query, lock=lock, scope_id=product_id
    )
    if pointer is None:
        return None, None
    row, _ = _row(s, ctx, product_id, pointer.preparation_id)
    if row.request_id != pointer.request_id or row.revision != pointer.preparation_revision:
        raise DomainError("INTEGRITY_MISMATCH", "验证准备当前指针无法核对。")
    return pointer, row


def _snapshot(row):
    from pdos_next.service import digest

    value = VerificationRequest.model_validate(row.request_snapshot)
    if (
        value.id != row.request_id
        or value.revision != row.revision
        or value.build.id != row.build_id
        or value.build.revision != row.build_revision
        or value.scope.tenant_id != row.tenant_id
        or value.scope.product_id != row.product_id
        or value.scope.project_id != row.project_id
        or digest(value.model_dump(mode="json")) != row.snapshot_sha256
        or value.status != "draft"
        or value.samples
        or value.acceptances
        or value.offered_coverage
        or value.returns
        or any(
            getattr(value.timeline, field) is not None
            for field in Timeline.model_fields
            if field != "request_created"
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "固定验证准备的身份、摘要或未执行状态无法核对。")
    return value


def _references(payload):
    refs = [*payload.sources]
    for item in payload.items:
        refs.extend(ref for ref in (item.drawing, item.method, item.criterion_source) if ref)
        if item.criterion:
            refs.append(item.criterion.source)
    refs.extend(document.source for document in payload.documents if document.source)
    values = {json.dumps(ref.model_dump(mode="json"), sort_keys=True): ref for ref in refs}
    return [values[key].model_dump(mode="json") for key in sorted(values)]


def semantic(payload):
    raw = payload.model_dump(mode="json")
    raw.pop("confirmation_token", None)
    for item in raw["items"]:
        item["cavities"].sort()
        if item["criterion"] is not None:
            for field in ("lower", "upper"):
                if item["criterion"][field] is not None:
                    number = Decimal(item["criterion"][field])
                    item["criterion"][field] = "0" if number == 0 else _decimal(number)
    for document in raw["documents"]:
        document["item_ids"].sort()
    raw["items"].sort(key=lambda item: item["id"])
    raw["documents"].sort(key=lambda document: document["id"])
    raw["sources"].sort(
        key=lambda ref: (ref["artifact_id"], ref["expected_revision"], ref["line"], ref["quote"])
    )
    if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > 1_000_000:
        raise DomainError("INVALID_PAYLOAD", "验证准备超过本轮1MB上限，请收敛测试项和引用。", 422)
    return raw


def _inputs(s, ctx, command, product, payload):
    write = not getattr(s, "info", {}).get("read_snapshot", False)
    _human(s, ctx, product.id, write=write)
    require_access(s, ctx, product.id, write=True, lock=write)
    if product.tenant_id != ctx.tenant_id or command.product_id != product.id:
        raise DomainError("FORBIDDEN_SCOPE", "验证准备不在当前型号范围。", 403)
    from pdos_next.enterprise_search.verification_adoption import recheck_preparation

    recheck_preparation(s, ctx, command)
    build = _build(s, ctx, product.id, payload.build_id)
    _, engineering, manufacturing, planned_reads = _linked(
        s, ctx, product.id, build, new_consumption=True
    )
    # Select the intended historical predecessor, never a newer pointer before receipt replay.
    previous = (
        _version(s, ctx, product.id, payload.request_id, payload.expected_request_revision)
        if payload.expected_request_revision
        else None
    )
    if previous is not None and (
        previous.build_id != build.id or previous.project_id != build.project_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "同一逻辑请求不能转到另一Build或项目。", 403)
    if previous is None:
        _, existing = _current(s, ctx, product.id, payload.request_id)
        if existing is not None and existing.owner_id != ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "逻辑请求不在当前负责人的办理范围。", 403)
    references = _references(payload)
    reads = _merge_reads(
        planned_reads, references, previous.required_source_read_set if previous else []
    )
    supplied = {str(ref.artifact_id): ref.expected_revision for ref in command.source_read_set}
    if any(supplied.get(ref["artifact_id"]) != ref["expected_revision"] for ref in reads):
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE", "验证准备需全部嵌套原文、固定配置及前版来源。"
        )
    try:
        _, private = _sources(s, ctx, product.id, reads, references)
    except DomainError as error:
        if error.reason == "MISSING_REQUIRED_EVIDENCE":
            raise DomainError(error.reason, "准备资料须在指定原文行精确定位。", 422) from None
        raise
    visibility = (
        "private"
        if build.visibility == "private"
        or private
        or (previous and previous.visibility == "private")
        else "category"
    )
    if previous is not None and previous.visibility != visibility:
        raise DomainError("FORBIDDEN_SCOPE", "续版须保留原受众；私有依据请另建独立准备请求。", 403)
    return build, engineering, manufacturing, previous, references, reads, visibility


def validate(s, ctx, command, product, payload: PreparationRecordPayload):
    _inputs(s, ctx, command, product, payload)


def _new_write(s, ctx, command, product, payload, values):
    write = not getattr(s, "info", {}).get("read_snapshot", False)
    build, _, _, previous, _, _, _ = values
    if (
        command.expected_revision != product.revision
        or build.revision != payload.expected_build_revision
    ):
        raise DomainError("VERSION_CONFLICT", "产品或固定Build版本已变化，请重新读取。")
    pointer, current = _current(s, ctx, product.id, payload.request_id, lock=write)
    if (current.revision if current else 0) != payload.expected_request_revision:
        raise DomainError("VERSION_CONFLICT", "准备请求当前版本已变化，请基于真实当前版修订。")
    if current is not None and (
        previous is None
        or current.id != previous.id
        or current.owner_id != ctx.requester_id
        or current.build_id != build.id
        or current.build_revision != build.revision
        or current.project_id != build.project_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "续版必须保留原负责人和固定Build范围。", 403)
    return pointer


def _source(reference):
    if reference is None:
        return None
    return SourceRef(
        id=reference.artifact_id,
        revision=reference.expected_revision,
        kind="artifact",
        position=f"line:{reference.line};quote_sha256:{hashlib.sha256(reference.quote.encode('utf-8')).hexdigest()}",
    )


def _request(ctx, command, payload, values, saved_at):
    # Selection order and Decimal representation cannot change one stable preparation intent.
    payload = PreparationRecordPayload.model_validate(semantic(payload))
    build, engineering, manufacturing, previous, _, _, _ = values
    items = []
    for item in payload.items:
        raw = item.model_dump(exclude={"drawing", "method", "criterion", "criterion_source"})
        items.append(
            TestItem(
                **raw,
                drawing=_source(item.drawing),
                method=_source(item.method),
                criterion_source=_source(item.criterion_source),
                criterion=NumericCriterion(
                    lower=item.criterion.lower,
                    upper=item.criterion.upper,
                    source=_source(item.criterion.source),
                )
                if item.criterion
                else None,
            )
        )
    first = (
        _snapshot(previous).timeline.request_created
        if previous
        else TimeFact(
            occurred_at=saved_at,
            received_at=saved_at,
            original_timezone="UTC",
            actor_id=ctx.actor_id,
            source=SourceRef(id=command.command_id, revision=1, kind="command", position="receipt"),
        )
    )
    return VerificationRequest(
        id=payload.request_id,
        revision=payload.expected_request_revision + 1,
        scope=Scope(
            tenant_id=ctx.tenant_id, product_id=command.product_id, project_id=build.project_id
        ),
        build=BuildRef(
            id=build.id,
            revision=build.revision,
            product_id=command.product_id,
            project_id=build.project_id,
            engineering_configuration=ConfigurationRef(
                id=build.engineering_configuration_id, revision=engineering["revision"]
            ),
            manufacturing_configuration=ConfigurationRef(
                id=build.manufacturing_configuration_id, revision=manufacturing["revision"]
            ),
        ),
        title=payload.title,
        purpose=payload.purpose,
        return_form=payload.return_form,
        items=tuple(items),
        documents=tuple(
            DocumentRequirement(
                **document.model_dump(exclude={"source"}), source=_source(document.source)
            )
            for document in payload.documents
        ),
        expected_at=payload.expected_at,
        expected_timezone=payload.expected_timezone,
        tentative_start=EventTime(
            occurred_at=payload.tentative_at,
            original_timezone=payload.tentative_timezone,
            source=_source(payload.sources[0]),
        )
        if payload.tentative_at
        else None,
        timeline=Timeline(request_created=first),
    )


def _gap_view(request):
    return (
        [gap.model_dump(mode="json") for gap in document_gaps(request)],
        [gap.model_dump(mode="json") for gap in coverage_gaps(request, ())],
    )


def _view(row, request, build, *, is_current, source_status):
    documents, coverage = _gap_view(request)
    raw = deepcopy(row.input_snapshot)
    return {
        "id": str(row.id),
        "request_id": str(row.request_id),
        "revision": row.revision,
        "previous_preparation_id": str(row.previous_preparation_id)
        if row.previous_preparation_id
        else None,
        "previous_revision": row.previous_revision,
        "build_id": str(row.build_id),
        "build_revision": row.build_revision,
        "build": request.build.model_dump(mode="json"),
        "project_id": str(row.project_id),
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "status": row.status,
        "request_state": request.status,
        "reason": row.reason,
        "created_at": row.created_at.isoformat(),
        "first_prepared_at": request.timeline.request_created.occurred_at.isoformat(),
        **{
            field: raw[field]
            for field in (
                "title",
                "purpose",
                "return_form",
                "items",
                "documents",
                "expected_at",
                "expected_timezone",
                "tentative_at",
                "tentative_timezone",
            )
        },
        "input_snapshot": raw,
        "request_snapshot": request.model_dump(mode="json"),
        "sha256": row.snapshot_sha256,
        "sources": deepcopy(row.sources),
        "required_source_read_set": deepcopy(row.required_source_read_set),
        "source_status": source_status,
        "is_current": is_current,
        "freshness": "requires_recalculation"
        if source_status != "current"
        else "current"
        if is_current
        else "historical",
        "document_gaps": documents,
        "coverage_gaps": coverage,
        "capabilities": _capabilities(),
        "blockers": _blockers(build),
        "time_policy": "server_recorded",
        "method_applicability": "unknown",
        "qualification_status": "unknown",
        "reference_samples_are_accepted": False,
    }


def _changes(before, after):
    result = {}
    for field, key in (("document_gaps", "documents"), ("coverage_gaps", "coverage")):
        old = {json.dumps(gap, sort_keys=True): gap for gap in before[field]} if before else {}
        new = {json.dumps(gap, sort_keys=True): gap for gap in after[field]}
        result[key] = {
            "added": [new[key] for key in sorted(new.keys() - old.keys())],
            "resolved": [old[key] for key in sorted(old.keys() - new.keys())],
        }
    return result


def preview_view(s, ctx, command, product, payload):
    from types import SimpleNamespace

    values = _inputs(s, ctx, command, product, payload)
    _new_write(s, ctx, command, product, payload, values)
    build, _, _, previous, references, reads, visibility = values
    candidate = _request(ctx, command, payload, values, now())
    before = (
        _view(
            previous,
            _snapshot(previous),
            build,
            is_current=True,
            source_status=_read_evidence(s, ctx, product.id, previous),
        )
        if previous
        else None
    )
    future = SimpleNamespace(
        id=None,
        request_id=payload.request_id,
        revision=payload.expected_request_revision + 1,
        previous_preparation_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        build_id=build.id,
        build_revision=build.revision,
        project_id=build.project_id,
        owner_id=ctx.requester_id,
        visibility=visibility,
        status="prepared",
        reason=payload.reason,
        created_at=candidate.timeline.request_created.received_at,
        input_snapshot=semantic(payload),
        snapshot_sha256=None,
        sources=references,
        required_source_read_set=reads,
    )
    after = _view(future, candidate, build, is_current=True, source_status="current")
    after["id"], after["created_at"], after["sha256"] = None, None, None
    after["time_policy"] = "server_on_save"
    if previous is None:
        after["first_prepared_at"] = None
        first = after["request_snapshot"]["timeline"]["request_created"]
        first["occurred_at"] = first["received_at"] = None
    return {
        "operation": command.operation,
        "name": payload.title,
        "effect": EFFECT,
        "reason": payload.reason,
        "before": before,
        "after": after,
        "gap_changes": _changes(before, after),
    }


def apply(s, ctx, command, product, payload):
    from pdos_next.service import digest

    values = _inputs(s, ctx, command, product, payload)
    pointer = _new_write(s, ctx, command, product, payload, values)
    build, _, _, previous, references, reads, visibility = values
    saved_at = now()
    request = _request(ctx, command, payload, values, saved_at)
    raw = request.model_dump(mode="json")
    row = VerificationPreparation(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=build.project_id,
        build_id=build.id,
        build_revision=build.revision,
        request_id=payload.request_id,
        revision=payload.expected_request_revision + 1,
        owner_id=ctx.requester_id,
        visibility=visibility,
        reason=payload.reason,
        created_at=saved_at,
        previous_preparation_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        input_snapshot=semantic(payload),
        request_snapshot=raw,
        snapshot_sha256=digest(raw),
        sources=references,
        required_source_read_set=reads,
    )
    s.add(row)
    s.flush()
    if pointer is None:
        pointer = VerificationCurrent(
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            request_id=payload.request_id,
            preparation_id=row.id,
            preparation_revision=row.revision,
        )
        s.add(pointer)
    else:
        pointer.preparation_id, pointer.preparation_revision = row.id, row.revision
    s.flush()
    return row, "verification_preparation", row.visibility


def get_preparation(s, ctx, product_id, identity, *, include_capabilities=True):
    _human(s, ctx, product_id)
    row, build = _row(s, ctx, product_id, identity)
    request = _snapshot(row)
    state = _read_evidence(s, ctx, product_id, row)
    _linked(s, ctx, product_id, build)
    _, current = _current(s, ctx, product_id, row.request_id)
    view = _view(
        row,
        request,
        build,
        is_current=current is not None and current.id == row.id,
        source_status=state,
    )
    view["capabilities"] = _capabilities(
        include_capabilities and _can_write(s, ctx, product_id) and row.owner_id == ctx.requester_id
    )
    return row, view


def _reference_samples(s, ctx, product_id):
    from pdos_next.domain.build_execution.models import SampleUnit
    from pdos_next.domain.build_execution.service import get_sample

    identities = s.scalars(
        select(SampleUnit.id)
        .where(
            SampleUnit.tenant_id == ctx.tenant_id,
            SampleUnit.product_id == product_id,
            (SampleUnit.visibility == "category") | (SampleUnit.owner_id == ctx.requester_id),
        )
        .order_by(SampleUnit.created_at.desc(), SampleUnit.id)
        .limit(101)
    ).all()
    views, unavailable = [], 0
    for identity in identities[:100]:
        try:
            views.append(get_sample(s, ctx, product_id, identity)[1])
        except DomainError as error:
            if error.status != 403:
                raise
            unavailable += 1
    return views, len(identities) > 100, unavailable


def _can_write(s, ctx, product_id):
    return bool(
        s.scalar(
            select(Grant.can_write).where(
                Grant.tenant_id == ctx.tenant_id,
                Grant.category_id == category_for_product(product_id),
                Grant.principal_id == ctx.requester_id,
                (Grant.expires_at.is_(None) | (Grant.expires_at > now())),
            )
        )
    )


def list_verification(s, ctx, product_id):
    _human(s, ctx, product_id)
    can_write = _can_write(s, ctx, product_id)
    result = {
        "preparations": [],
        "current_by_request": {},
        "runs": [],
        "reference_samples": [],
        "capabilities": _capabilities(can_write),
        "blockers": _blockers(),
        "has_more": False,
        "unavailable_count": 0,
    }
    rows = s.scalars(
        select(VerificationPreparation)
        .where(
            VerificationPreparation.tenant_id == ctx.tenant_id,
            VerificationPreparation.product_id == product_id,
            (VerificationPreparation.visibility == "category")
            | (VerificationPreparation.owner_id == ctx.requester_id),
        )
        .order_by(VerificationPreparation.created_at.desc(), VerificationPreparation.id)
        .limit(101)
    ).all()
    result["has_more"] = len(rows) > 100
    for row in rows[:100]:
        try:
            view = get_preparation(s, ctx, product_id, row.id)[1]
            view["capabilities"] = _capabilities(can_write and row.owner_id == ctx.requester_id)
            result["preparations"].append(view)
            if view["is_current"]:
                result["current_by_request"][view["request_id"]] = {
                    "preparation_id": view["id"],
                    "revision": view["revision"],
                }
        except DomainError as error:
            if error.status != 403:
                raise
            result["unavailable_count"] += 1
    samples, more, unavailable = _reference_samples(s, ctx, product_id)
    result["reference_samples"] = samples
    result["has_more"] |= more
    result["unavailable_count"] += unavailable
    result["blockers"] = _blockers(samples=samples)
    visible_builds = {view["build_id"] for view in result["preparations"]} | {
        sample["build_id"] for sample in samples
    }
    if any(
        _build(s, ctx, product_id, UUID(identity)).status
        not in {"executing", "evaluating", "closed"}
        for identity in visible_builds
    ):
        result["blockers"].insert(
            0,
            {
                "code": "BUILD_NOT_EXECUTING",
                "detail": "可见Build仍为计划；参考样件不证明已获授权开工。",
                "sample_id": None,
            },
        )
    for view in result["preparations"]:
        build = _build(s, ctx, product_id, UUID(view["build_id"]))
        view["blockers"] = _blockers(
            build, [sample for sample in samples if sample["build_id"] == view["build_id"]]
        )
    return result
