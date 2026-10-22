"""Fixed handoff/receipt candidates, no network, actual-owner or T2 substitute."""

from datetime import datetime

from pdos_next.domain.release import rules as release
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context

from .schemas import (
    ActualData,
    AuthorizationPlan,
    AuthorizePayload,
    HandoffReading,
    ReceiptActualData,
    ReceiptFact,
    ReceiptPlan,
    ReceiptRecordPayload,
    StageReading,
    VersionRef,
)


def _require(test, detail, code="INTEGRITY_MISMATCH", status=409):
    if not test:
        raise DomainError(code, detail, status)


def semantic(payload):
    value = payload.model_dump(mode="json")
    value.pop("approval_token", None)
    return value


def manifest_digest(files):
    """Digest the actual exchanged manifest, excluding local citation metadata."""
    return release.digest(
        sorted(
            [value.model_dump(mode="json", exclude={"sources"}) for value in files],
            key=lambda value: (value["logical_name"], value["artifact"]["id"]),
        )
    )


def mappings_digest(mappings):
    return release.digest(
        sorted(
            [value.model_dump(mode="json", exclude={"sources"}) for value in mappings],
            key=lambda value: (value["ref"]["kind"], value["ref"]["id"]),
        )
    )


def scope_covers(bound, selected):
    """Use release containment, without treating omitted values as unlimited."""
    if not release.scope_contains(bound, selected):
        return False
    for field in ("lots", "lines", "regions", "site", "quantity", "unit"):
        limit, chosen = getattr(bound, field), getattr(selected, field)
        if chosen is None and limit is not None:
            return False
        if isinstance(chosen, tuple) and not chosen and limit != ():
            return False
    return True


def _sources(actual, declaration):
    required = tuple(dict.fromkeys(release._sources(declaration)))
    # Compare exact owner-verified reference fields, regardless of DTO subclass.
    verified_sources = tuple(
        SourceRef.model_validate({name: getattr(value, name) for name in SourceRef.model_fields})
        for value in actual.sources
    )
    sources = tuple(dict.fromkeys((*verified_sources, *required)))
    reads = release._canonical_reads(actual.required_source_read_set)
    verified = set(verified_sources)
    known = {(value.artifact_id, value.expected_revision) for value in reads}
    current = set(required) <= verified and all(
        (value.id, value.revision) in known for value in sources if value.kind == "artifact"
    )
    return sources, reads, current


def prepare(payload, data, *, ctx: Context, at: datetime):
    """Prepare only; the host must prove the owner read and consume common T2."""
    payload, data = AuthorizePayload.model_validate(payload), ActualData.model_validate(data)
    _require(at.utcoffset() is not None, "须使用服务器aware时钟。")
    _require(
        type(ctx) is Context
        and ctx.actor_id == ctx.requester_id
        and ctx.run_id is None
        and ctx.tenant_id == data.scope.tenant_id
        and ctx.category_id == data.category_id
        and payload.project_id == data.scope.project_id,
        "移交授权须绑定当前具名本人及实际品类、项目。",
        "FORBIDDEN_SCOPE",
        403,
    )
    package = data.package
    _require(
        package.scope == data.scope
        and package.category_id == data.category_id
        and payload.package == data.package_ref,
        "须引用本项目的实际固定包。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        payload.visibility == "private" or data.visibility != "private",
        "私有发布依据不能借移交扩大共享。",
        "FORBIDDEN_SCOPE",
        403,
    )
    unknown, blocked = [], []
    if data.package_current is not True:
        unknown.append("PACKAGE_APPLICABILITY_UNKNOWN")
    if data.sources_current is not True:
        unknown.append("HANDOFF_SOURCES_UNKNOWN")
    if (
        payload.subject_config != package.declaration.subject_config
        or payload.purpose != package.declaration.purpose
        or not scope_covers(package.declaration.release_scope, payload.release_scope)
    ):
        unknown.append("PACKAGE_SCOPE_NOT_COVERED")
    _require(
        len({value.ref for value in data.decisions}) == len(data.decisions),
        "实际批准身份不能重复，不能默认选第一条或最新一条。",
    )
    by_ref = {value.ref: value for value in data.decisions}
    limits = list(package.declaration.limits)
    for discipline, ref in (
        ("engineering", payload.engineering_decision),
        ("manufacturing", payload.manufacturing_decision),
    ):
        actual = by_ref.get(ref)
        if actual is None:
            unknown.append(discipline.upper() + "_DECISION_MISSING")
            continue
        plan = actual.plan
        _require(
            plan.scope == data.scope
            and plan.category_id == data.category_id
            and plan.discipline == discipline
            and plan.package == data.package_ref
            and plan.package_sha256 == package.body_sha256
            and plan.subject_config == payload.subject_config
            and plan.purpose == payload.purpose
            and plan.customer_acceptance is None
            and plan.external_received is False
            and plan.external_effective is False,
            "专业决定须精确绑定同一包、定义、双配置及用途，不能代替外部接收。",
        )
        if (
            actual.current is not True
            or (plan.expiry is not None and at >= plan.expiry)
            or not scope_covers(plan.release_scope, payload.release_scope)
            or plan.assessment.state not in {"READY", "READY_WITH_CONDITIONS"}
            or plan.assessment.blocked
            or plan.assessment.unknown
        ):
            unknown.append(discipline.upper() + "_DECISION_NOT_APPLICABLE")
        limits.extend(plan.limits)
    if (
        data.contract_read is not True
        or data.required_mapping_refs is None
        or data.required_manifest_refs is None
    ):
        unknown.append("HANDOFF_CONTRACT_NOT_READ")
    else:
        if not set(data.required_mapping_refs) <= {value.ref for value in payload.mappings}:
            unknown.append("REQUIRED_MAPPING_MISSING")
        if not set(data.required_manifest_refs) <= {value.artifact for value in payload.manifest}:
            unknown.append("REQUIRED_MANIFEST_FILE_MISSING")
    _require(
        len({value.ref for value in data.mappings}) == len(data.mappings)
        and len({value.artifact for value in data.files}) == len(data.files),
        "实际映射与文件素材须唯一，不能按时间默选。",
    )
    actual_mappings = {value.ref: value for value in data.mappings}
    actual_files = {value.artifact: value for value in data.files}
    for value in payload.mappings:
        actual = actual_mappings.get(value.ref)
        if actual is None:
            unknown.append("MAPPING_MATERIAL_MISSING")
        elif value != actual:
            blocked.append("MAPPING_MATERIAL_MISMATCH")
    for value in payload.manifest:
        actual = actual_files.get(value.artifact)
        if actual is None:
            unknown.append("MANIFEST_MATERIAL_MISSING")
        elif value != actual:
            blocked.append("MANIFEST_CONTENT_MISMATCH")
    sources, reads, current = _sources(data, payload)
    if not current:
        unknown.append("HANDOFF_REQUIRED_SOURCE_NOT_VERIFIED")
    unique_limits = tuple({release.digest(value): value for value in limits}.values())
    body = {
        "declaration": semantic(payload),
        "scope": data.scope.model_dump(mode="json"),
        "category_id": str(data.category_id),
        "package_sha256": package.body_sha256,
        "signers": [str(ctx.actor_id)],
        "limits": [value.model_dump(mode="json") for value in unique_limits],
    }
    return AuthorizationPlan(
        scope=data.scope,
        category_id=data.category_id,
        declaration=AuthorizePayload.model_validate(semantic(payload)),
        package_sha256=package.body_sha256,
        manifest_sha256=manifest_digest(payload.manifest),
        mappings_sha256=mappings_digest(payload.mappings),
        content_sha256=release.digest(body),
        limits=unique_limits,
        signers=(ctx.actor_id,),
        state="BLOCKED" if blocked else "UNKNOWN" if unknown else "READY",
        unknown=tuple(dict.fromkeys(unknown)),
        blocked=tuple(dict.fromkeys(blocked)),
        sources=sources,
        required_source_read_set=reads,
        prepared_at=at,
    )


def require_authorizable(plan):
    plan = AuthorizationPlan.model_validate(plan)
    _require(
        plan.state == "READY" and not plan.unknown and not plan.blocked,
        "实际固定包、各专业范围或移交原件尚不可执行。",
    )
    return plan


def _mismatches(original, authorization):
    declaration = authorization.declaration
    pairs = (
        (original.destination == declaration.destination, "DESTINATION_MISMATCH"),
        (original.external_id == declaration.external_id, "EXTERNAL_ID_MISMATCH"),
        (original.manifest_sha256 == authorization.manifest_sha256, "MANIFEST_MISMATCH"),
        (
            scope_covers(declaration.release_scope, original.release_scope),
            "RECEIVED_SCOPE_MISMATCH",
        ),
    )
    return tuple(reason for matches, reason in pairs if not matches)


def _same_occurrence(left, right):
    return all(
        getattr(left, field) == getattr(right, field)
        for field in (
            "handoff",
            "intent",
            "destination",
            "external_id",
            "manifest_sha256",
            "release_scope",
            "stage",
        )
    )


def _reconciliation(original, history):
    if original.reconciles is None:
        if original.stage == "sent" and any(
            value.original.stage == "sent"
            and value.original.outcome == "unknown"
            and not any(
                other.original.reconciles == VersionRef(id=value.id, revision=value.revision)
                for other in history
            )
            for value in history
        ):
            raise DomainError(
                "EXTERNAL_OUTCOME_UNKNOWN", "原发送结果未知，须对账原意图，不能盲目新增发送。", 409
            )
        return
    previous = next(
        (
            value
            for value in history
            if VersionRef(id=value.id, revision=value.revision) == original.reconciles
        ),
        None,
    )
    _require(
        previous is not None
        and previous.original.outcome in {"unknown", "rejected", "failed"}
        and original.outcome != "unknown"
        and _same_occurrence(previous.original, original)
        and not any(value.original.reconciles == original.reconciles for value in history),
        "对账须显式引用同意图、阶段、manifest及范围的原未决事实，不能覆盖历史。",
    )


def prepare_receipt(payload, data, *, history=(), at: datetime):
    payload = ReceiptRecordPayload.model_validate(payload)
    data = ReceiptActualData.model_validate(data)
    history = tuple(ReceiptFact.model_validate(value) for value in history)
    original = data.original
    _require(
        at.utcoffset() is not None and original.occurred_at <= at,
        "实际回执发生钟不能在接收钟之后。",
        "INVALID_EVENT_TIME",
        422,
    )
    _require(
        payload.handoff == data.handoff == original.handoff
        and payload.intent == data.intent == original.intent
        and payload.source == data.source
        and data.authorization.scope == data.scope
        and data.authorization.category_id == data.category_id,
        "回执原件须属于实际同一移交和发送意图。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        all(
            value.original.handoff == data.handoff and value.original.intent == data.intent
            for value in history
        ),
        "历史回执须属于本次实际移交意图。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _reconciliation(original, history)
    unknown = []
    if (
        data.authorized is not True
        or data.authorization.state != "READY"
        or data.authorization.unknown
        or data.authorization.blocked
    ):
        unknown.append("ACTUAL_HANDOFF_AUTHORIZATION_MISSING")
    if data.issuer is None or data.issuer_current is not True:
        unknown.append("ACTUAL_RECEIPT_ISSUER_MISSING")
    elif data.issuer.system != original.destination.system:
        unknown.append("ACTUAL_RECEIPT_ISSUER_SCOPE_MISMATCH")
    if data.sources_current is not True:
        unknown.append("ACTUAL_RECEIPT_SOURCE_UNKNOWN")
    sources, reads, current = _sources(data, payload)
    if not current:
        unknown.append("RECEIPT_ORIGINAL_NOT_VERIFIED")
    return ReceiptPlan(
        scope=data.scope,
        category_id=data.category_id,
        original=original,
        source=data.source,
        issuer=data.issuer,
        mismatches=_mismatches(original, data.authorization),
        state="UNKNOWN" if unknown else "READY",
        unknown=tuple(unknown),
        sources=sources,
        required_source_read_set=reads,
        received_at=at,
    )


def require_recordable(plan):
    plan = ReceiptPlan.model_validate(plan)
    _require(
        plan.state == "READY" and not plan.unknown and plan.issuer is not None,
        "实际可信宿主及回执原文尚未核对。",
    )
    return plan


def fold(*, handoff, intent, authorization, receipts):
    """Project saved facts without altering unknown/rejected or inferring stages."""
    handoff, intent = VersionRef.model_validate(handoff), VersionRef.model_validate(intent)
    authorization = AuthorizationPlan.model_validate(authorization)
    values = tuple(ReceiptFact.model_validate(value) for value in receipts)
    _require(
        len({VersionRef(id=value.id, revision=value.revision) for value in values}) == len(values),
        "回执版本身份不能重复。",
    )
    # The actual owner supplies immutable append/version order. Equal clocks
    # or UUID ordering cannot invent the order of business occurrences.
    ordered = values
    checked = []
    for value in ordered:
        _require(
            value.original.handoff == handoff
            and value.original.intent == intent
            and value.original.occurred_at <= value.received_at,
            "历史回执须属于同一实际移交意图和接收时钟。",
        )
        _reconciliation(value.original, checked)
        checked.append(value)
    superseded = {
        value.original.reconciles for value in ordered if value.original.reconciles is not None
    }

    def stage_reading(stage):
        active = [
            value
            for value in ordered
            if value.original.stage == stage
            and VersionRef(id=value.id, revision=value.revision) not in superseded
        ]
        mismatch = tuple(
            dict.fromkeys(
                reason for value in active for reason in _mismatches(value.original, authorization)
            )
        )
        outcomes = {value.original.outcome for value in active}
        covered = tuple(
            value.original.release_scope
            for value in active
            if value.original.outcome == "succeeded"
            and not _mismatches(value.original, authorization)
        )
        state = (
            "not_recorded"
            if not active
            else "conflict"
            if mismatch or len(outcomes) != 1
            else next(iter(outcomes))
        )
        if state == "succeeded" and not any(
            scope_covers(value, authorization.declaration.release_scope) for value in covered
        ):
            state = "partial"
        return StageReading(
            stage=stage,
            state=state,
            active=tuple(VersionRef(id=value.id, revision=value.revision) for value in active),
            covered_scopes=covered,
            mismatches=mismatch,
        )

    sent, accepted, effective = (
        stage_reading(stage) for stage in ("sent", "accepted", "effective")
    )
    return HandoffReading(
        status="reconciled"
        if effective.state == "succeeded"
        else "acknowledged"
        if accepted.state == "succeeded"
        else "sent"
        if sent.state == "succeeded"
        else "authorized",
        sent=sent,
        accepted=accepted,
        effective=effective,
        delivery_unknown=any(
            value.original.stage == "sent"
            and value.original.outcome == "unknown"
            and VersionRef(id=value.id, revision=value.revision) not in superseded
            for value in ordered
        ),
        rejected=any(
            value.original.outcome == "rejected"
            and VersionRef(id=value.id, revision=value.revision) not in superseded
            for value in ordered
        ),
        failed=any(
            value.original.outcome == "failed"
            and VersionRef(id=value.id, revision=value.revision) not in superseded
            for value in ordered
        ),
        conflict=any(value.state == "conflict" for value in (sent, accepted, effective)),
        history=ordered,
    )
