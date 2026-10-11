"""Build execution adapter in the caller's single command transaction.

No commit, public authority importer, receipt, AI eligibility or duplicate reservation.
"""

import json
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.supply_execution.service import (
    _build,
    _human,
    _linked,
    _read_evidence,
    _sources,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, now
from pdos_next.request_proof import command_inputs_once, snapshot_get, snapshot_scalar
from pdos_next.service import digest

from .models import (
    BuildAssessmentCurrent,
    BuildAuthorizationCurrent,
    BuildAuthorizationDecision,
    BuildExecutionAssessment,
    BuildStart,
)
from .rules import (
    CONTROLS,
    EXPLORATION_BOUNDARY,
    readiness_result,
    require_candidate,
    require_ready,
    validate_professional_review,
    validate_scope,
    validate_start_event,
    validate_start_time,
)
from .schemas import (
    BuildAssessmentPayload,
    BuildAuthorizationPayload,
    BuildExecutionScope,
    BuildStartPayload,
)

category_lifecycle_fence = True

ASSESS = "build.readiness.compute"
ROLES = {
    "build.engineering.authorize": "engineering",
    "build.manufacturing.authorize": "manufacturing",
}
EFFECTS = {
    ASSESS: "保存固定用途、数量、场地与窗口的执行准备度评估；不批准、不预约或开工。",
    "build.engineering.authorize": "具名工程批准或撤销固定执行范围；不替代制造批准或实际开工。",
    "build.manufacturing.authorize": "具名制造批准或撤销固定执行范围；不替代工程批准或实际开工。",
    "build.start": "同一事务核对两项具名批准并占用完整物料与资源，记录有精确事件来源的实际开工。",
}


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        value = asdict(value)
    return json.loads(
        json.dumps(
            value,
            default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v),
            ensure_ascii=False,
        )
    )


def semantic(payload):
    raw = payload.model_dump(mode="json")
    raw.pop("confirmation_token", None)
    raw.pop("approval_token", None)
    if "sources" in raw:
        raw["sources"].sort(key=lambda ref: json.dumps(ref, sort_keys=True))
    if "professional_assessments" in raw:
        for item in raw["professional_assessments"]:
            item["sources"].sort(key=lambda ref: json.dumps(ref, sort_keys=True))
        raw["professional_assessments"].sort(key=lambda item: item["rule_id"])
        raw["accepted_controls"].sort()
    if "execution_scope" in raw:
        value = format(payload.execution_scope.quantity, "f")
        raw["execution_scope"]["quantity"] = (
            value.rstrip("0").rstrip(".") if "." in value else value
        )
    return raw


def _identity(command):
    return uuid5(NAMESPACE_URL, f"pdos-build-execution:{command.command_id}:{command.operation}")


def _current_assessment(s, ctx, product_id, build_id, *, lock=False):
    query = select(BuildAssessmentCurrent).where(
        BuildAssessmentCurrent.tenant_id == ctx.tenant_id,
        BuildAssessmentCurrent.product_id == product_id,
        BuildAssessmentCurrent.build_id == build_id,
    )
    pointer = snapshot_scalar(
        s, (BuildAssessmentCurrent, product_id, build_id), query, lock=lock, scope_id=product_id
    )
    return pointer, _row(
        s, ctx, product_id, BuildExecutionAssessment, pointer.assessment_id
    ) if pointer else None


def _current_decision(s, ctx, product_id, build_id, role, *, lock=False):
    query = select(BuildAuthorizationCurrent).where(
        BuildAuthorizationCurrent.tenant_id == ctx.tenant_id,
        BuildAuthorizationCurrent.product_id == product_id,
        BuildAuthorizationCurrent.build_id == build_id,
        BuildAuthorizationCurrent.role == role,
    )
    pointer = snapshot_scalar(
        s,
        (BuildAuthorizationCurrent, product_id, build_id, role),
        query,
        lock=lock,
        scope_id=product_id,
    )
    return pointer, _row(
        s, ctx, product_id, BuildAuthorizationDecision, pointer.decision_id
    ) if pointer else None


def _row(s, ctx, product_id, model, identity):
    row = snapshot_get(s, model, identity, scope_id=product_id)
    return _validated_row(s, ctx, product_id, row)


def _validated_row(s, ctx, product_id, row):
    """Validate a complete row already actually selected under this caller's RLS.

    This is not an authority proof or a Session cache. The original Build
    scope read and every fixed-field/content-hash check still run for each use.
    """
    if row is None or row.tenant_id != ctx.tenant_id or row.product_id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "执行评估、批准或开工事实不在当前可读范围。", 403)
    build = _build(s, ctx, product_id, row.build_id)
    return _validate_row_material(row, build)


def _validate_row_material(row, build):
    if (
        row.project_id != build.project_id
        or row.engineering_configuration_id != build.engineering_configuration_id
        or row.manufacturing_configuration_id != build.manufacturing_configuration_id
    ):
        raise DomainError("INTEGRITY_MISMATCH", "执行事实与固定本轮、项目或双配置无法核对。")
    if row.snapshot_sha256 != digest(_material(row)):
        raise DomainError("INTEGRITY_MISMATCH", "执行事实固定摘要无法核对。")
    return row


def _start(s, ctx, product_id, build_id):
    return snapshot_scalar(
        s,
        (BuildStart, "by-build", product_id, build_id),
        select(BuildStart).where(
            BuildStart.tenant_id == ctx.tenant_id,
            BuildStart.product_id == product_id,
            BuildStart.build_id == build_id,
        ),
        scope_id=product_id,
    )


def _material(row):
    common = {
        key: _json(getattr(row, key))
        for key in (
            "id",
            "build_id",
            "project_id",
            "engineering_configuration_id",
            "manufacturing_configuration_id",
            "revision",
            "owner_id",
            "visibility",
            "status",
            "required_source_read_set",
            "reason",
        )
    }
    if isinstance(row, BuildExecutionAssessment):
        keys = (
            "build_revision",
            "engineering_configuration_revision",
            "manufacturing_configuration_revision",
            "previous_assessment_id",
            "previous_revision",
            "execution_scope",
            "result",
        )
    elif isinstance(row, BuildAuthorizationDecision):
        keys = (
            "role",
            "action",
            "previous_decision_id",
            "previous_revision",
            "assessment_id",
            "assessment_revision",
            "assessment_sha256",
            "valid_until",
            "authority_snapshot",
            "fact_binding",
            "sources",
        )
    else:
        keys = (
            "build_revision",
            "assessment_id",
            "assessment_revision",
            "assessment_sha256",
            "engineering_authorization_id",
            "engineering_authorization_revision",
            "manufacturing_authorization_id",
            "manufacturing_authorization_revision",
            "occurred_at",
            "occurred_timezone",
            "execution_scope",
            "event_source",
            "authority_snapshot",
            "reservations",
            "sources",
        )
    common.update({key: _json(getattr(row, key)) for key in keys})
    return common


def _authority(s, ctx, product_id, build, operation, purpose, at, *, write=False):
    from pdos_next.domain.professional_authority.service import assess

    value = assess(s, ctx, product_id, build.project_id, operation, purpose, at, write=write)
    if value.get("scope") != {
        "tenant_id": str(ctx.tenant_id),
        "product_id": str(product_id),
        "project_id": str(build.project_id),
    } or value.get("subject_id") != str(ctx.requester_id):
        raise DomainError("INTEGRITY_MISMATCH", "专业权威未绑定当前人员与项目。", 403)
    return _json(value)


def _require_authority(value, role, *, until=None):
    if (
        not value.get("authorized")
        or value.get("qualified") is not True
        or role not in value.get("roles", [])
    ):
        raise DomainError(
            "PROFESSIONAL_AUTHORITY_REQUIRED",
            "本动作需要当前具名人员的用途限定职责与有效专业资格。",
            403,
        )


def _recheck_authority(s, ctx, product_id, project_id, snapshot, at, *, retained=False):
    from pdos_next.domain.professional_authority.service import recheck_snapshot

    try:
        UUID(snapshot["subject_id"])
    except (ValueError, TypeError, KeyError):
        raise DomainError("INTEGRITY_MISMATCH", "具名专业批准的人员身份无法核对。") from None
    result = recheck_snapshot(
        s,
        ctx,
        product_id,
        project_id,
        snapshot,
        at,
        retained=retained,
    )
    if not result.get("current"):
        raise DomainError(
            "PROFESSIONAL_AUTHORITY_CHANGED",
            "原批准人的职责、资格、签发状态或依据已变化，请重新批准。",
            409,
        )
    return result["assessment"]


def _port_scope(scope):
    from pdos_next.domain.build_operational_facts.service import OperationalScope

    return OperationalScope(
        purpose=scope.purpose,
        quantity=scope.quantity,
        unit=scope.unit,
        site=scope.site,
        window=scope.execution_window(),
    )


def _bundle(s, ctx, product_id, build, scope, at, *, write=False, saved_start=None):
    from pdos_next.domain.build_operational_facts.service import load_bundle, recheck_reservation

    validate_scope(build, scope)
    if saved_start is None:
        value = load_bundle(s, ctx, product_id, build.id, _port_scope(scope), at, write=write)
    else:
        value = recheck_reservation(
            s,
            ctx,
            product_id,
            build.id,
            _port_scope(scope),
            saved_start.id,
            saved_start.intent_digest,
            at,
        )
    raw = _json(value)
    if (
        raw.get("build_revision") != build.revision
        or str(raw.get("engineering_configuration_id")) != str(build.engineering_configuration_id)
        or str(raw.get("manufacturing_configuration_id"))
        != str(build.manufacturing_configuration_id)
    ):
        raise DomainError("INTEGRITY_MISMATCH", "操作事实未固定本轮与双配置。")
    actual, actual_reads, deviation = _actual_binding(s, ctx, product_id, build)
    raw["actual_configuration_binding"] = actual
    raw["required_source_read_set"] = _reads(raw["required_source_read_set"], actual_reads)
    raw["checks"].append(
        {
            "dimension": "configuration",
            "code": "ACTUAL_CONFIGURATION_DEVIATION" if deviation else "ACTUAL_CONFIGURATION_MATCH",
            "status": "BLOCKED" if deviation else "READY",
            "detail": "已记录偏离计划的实际配置，需停工与重新核对。"
            if deviation
            else "当前已记录实际配置未偏离固定计划。",
        }
    )
    if deviation:
        raw["state"] = "BLOCKED"
    return raw


def _actual_binding(s, ctx, product_id, build):
    from sqlalchemy import func

    from pdos_next.domain.build_execution.models import ActualConfiguration
    from pdos_next.request_proof import request_proof, scoped_rows

    rows = scoped_rows(
        s,
        (ActualConfiguration, build.id),
        select(ActualConfiguration)
        .where(
            ActualConfiguration.tenant_id == ctx.tenant_id,
            ActualConfiguration.product_id == product_id,
            ActualConfiguration.build_id == build.id,
        )
        .order_by(ActualConfiguration.id),
    )
    proof = request_proof(s)
    key = ("actual-configuration-completeness", build.id, tuple(row.id for row in rows))
    if key not in proof.read_rows:
        proof.read_rows[key] = s.scalar(
            func.build_actual_count(ctx.tenant_id, build.category_id, product_id, build.id)
        )
    if proof.read_rows[key] != len(rows):
        raise DomainError(
            "SOURCE_UNAVAILABLE", "本轮实物配置含当前不可读依据，须由有权限的人员核对。", 403
        )
    facts, reads, deviation = [], [], False
    for row in rows:
        reads.extend(row.required_source_read_set)
        differs = (
            bool(row.differences)
            or row.actual_engineering_configuration_id != build.engineering_configuration_id
            or row.actual_manufacturing_configuration_id != build.manufacturing_configuration_id
        )
        deviation |= differs
        facts.append(
            {
                "id": str(row.id),
                "revision": row.revision,
                "sha256": digest(
                    {
                        "engineering_id": str(row.actual_engineering_configuration_id),
                        "engineering_revision": row.actual_engineering_revision,
                        "manufacturing_id": str(row.actual_manufacturing_configuration_id),
                        "manufacturing_revision": row.actual_manufacturing_revision,
                        "differences": row.differences,
                    }
                ),
                "deviation": differs,
            }
        )
    return facts, _reads(reads), deviation


def _reads(*groups):
    return _merge_reads(*[_json(group) for group in groups])


def _exact_reads(s, ctx, product_id, command, required, references=(), *, build=None):
    if build is not None and command.payload.get("action") != "revoke":
        _linked(s, ctx, product_id, build, new_consumption=True)
    actual = {str(ref.artifact_id): ref.expected_revision for ref in command.source_read_set}
    if any(actual.get(ref["artifact_id"]) != ref["expected_revision"] for ref in required):
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE",
            "本动作须携带固定配置、当前事实及专业权威的完整来源读集。",
            409,
        )
    _, private = _sources(s, ctx, product_id, required, references)
    if build is not None and build.visibility == "category" and private:
        raise DomainError(
            "PRIVATE_SOURCE_SCOPE",
            "本轮共享执行范围不能加入私人依据，请使用匹配范围的固定事实。",
            403,
        )


def _scope_of(assessment):
    return BuildExecutionScope.model_validate(assessment.execution_scope)


def _assessment(s, ctx, product_id, payload):
    row = _row(s, ctx, product_id, BuildExecutionAssessment, payload.assessment_id)
    if (
        row.revision != payload.expected_assessment_revision
        or row.snapshot_sha256 != payload.expected_assessment_sha256
    ):
        raise DomainError(
            "ASSESSMENT_VERSION_CONFLICT", "固定评估版本或摘要已变化，请重新读取。", 409
        )
    return row, _build(s, ctx, product_id, row.build_id), _scope_of(row)


def _current_assessment_guard(s, ctx, product_id, row):
    pointer, _ = _current_assessment(s, ctx, product_id, row.build_id)
    if (
        pointer is None
        or pointer.assessment_id != row.id
        or pointer.assessment_revision != row.revision
    ):
        raise DomainError("ASSESSMENT_VERSION_CONFLICT", "批准或开工须使用本轮当前执行评估。", 409)


def _binding(bundle):
    return {
        key: deepcopy(bundle.get(key))
        for key in (
            "facts_revision",
            "fact_refs",
            "valid_until",
            "nature",
            "build_revision",
            "engineering_configuration_id",
            "engineering_configuration_revision",
            "manufacturing_configuration_id",
            "manufacturing_configuration_revision",
            "actual_configuration_binding",
        )
    }


def _match_bundle(assessment, bundle, at):
    require_ready(bundle, at)
    if _binding(bundle) != _binding(assessment.result):
        raise DomainError(
            "OPERATIONAL_FACTS_CHANGED",
            "物料、资源、资格、占用或当前来源已变化，请重新评估与批准。",
            409,
        )


def _match_execution_bundle(assessment, bundle, at):
    """An already-started Build may gain matching observations; its approved basis stays fixed."""
    require_ready(bundle, at)
    expected, current = _binding(assessment.result), _binding(bundle)
    fixed_observations = expected.pop("actual_configuration_binding") or []
    observations = current.pop("actual_configuration_binding") or []
    indexed = {row["id"]: row for row in observations}
    if (
        expected != current
        or len(indexed) != len(observations)
        or any(indexed.get(row["id"]) != row for row in fixed_observations)
        or any(row.get("deviation") is not False for row in observations)
    ):
        raise DomainError(
            "OPERATIONAL_FACTS_CHANGED",
            "原批准依据或实际配置已变化，须停工重新核对。",
            409,
        )


def _decision_guard(s, ctx, product_id, row, assessment, role, scope, at, *, retained=False):
    pointer, _ = _current_decision(s, ctx, product_id, row.build_id, role)
    if (
        pointer is None
        or pointer.decision_id != row.id
        or pointer.decision_revision != row.revision
        or row.role != role
        or row.action != "approve"
        or row.status != "approved"
    ):
        raise DomainError("AUTHORIZATION_NOT_CURRENT", "所选专业批准已撤销或被后续决定替代。", 409)
    if (
        row.assessment_id != assessment.id
        or row.assessment_revision != assessment.revision
        or row.assessment_sha256 != assessment.snapshot_sha256
    ):
        raise DomainError(
            "AUTHORIZATION_SCOPE_MISMATCH", "两项批准必须绑定同一当前评估与固定执行范围。", 409
        )
    if row.valid_until is not None and (
        row.valid_until <= at or row.valid_until < scope.window_end
    ):
        raise DomainError("AUTHORIZATION_EXPIRED", "专业批准已失效或未覆盖执行窗口。", 409)
    _require_authority(
        _recheck_authority(
            s, ctx, product_id, row.project_id, row.authority_snapshot, at, retained=retained
        ),
        role,
        until=scope.window_end,
    )
    if row.fact_binding.get("accepted_controls") != sorted(CONTROLS):
        raise DomainError("INTEGRITY_MISMATCH", "专业决定缺少固定用途执行约束。", 409)
    reviews = row.fact_binding.get("professional_assessments", [])
    from .schemas import ProfessionalApplicability

    review_payload = BuildAuthorizationPayload(
        assessment_id=row.assessment_id,
        expected_assessment_revision=row.assessment_revision,
        expected_assessment_sha256=row.assessment_sha256,
        action="approve",
        valid_until=row.valid_until,
        sources=row.sources,
        reason=row.reason,
        accepted_controls=tuple(row.fact_binding["accepted_controls"]),
        professional_assessments=tuple(
            ProfessionalApplicability.model_validate(item) for item in reviews
        ),
    )
    validate_professional_review(review_payload, role, scope, at)


@command_inputs_once
def _start_inputs(s, ctx, command, product, payload, at):
    assessment, build, scope = _assessment(s, ctx, product.id, payload)
    _current_assessment_guard(s, ctx, product.id, assessment)
    require_candidate(assessment.result)
    engineering = _row(
        s, ctx, product.id, BuildAuthorizationDecision, payload.engineering_authorization_id
    )
    manufacturing = _row(
        s, ctx, product.id, BuildAuthorizationDecision, payload.manufacturing_authorization_id
    )
    if (
        engineering.revision != payload.expected_engineering_authorization_revision
        or manufacturing.revision != payload.expected_manufacturing_authorization_revision
    ):
        raise DomainError("AUTHORIZATION_VERSION_CONFLICT", "专业批准版本无法核对。", 409)
    for role, row in (("engineering", engineering), ("manufacturing", manufacturing)):
        _decision_guard(s, ctx, product.id, row, assessment, role, scope, at)
    actor = _authority(s, ctx, product.id, build, "build.start", scope.purpose, at, write=True)
    _require_authority(actor, "manufacturing", until=scope.window_end)
    event = payload.event_source.model_dump(mode="json")
    validate_start_event(
        event["quote"],
        build_id=build.id,
        scope=scope,
        engineering_id=build.engineering_configuration_id,
        manufacturing_id=build.manufacturing_configuration_id,
        occurred_at=payload.occurred_at,
    )
    validate_start_time(scope, payload.occurred_at, at, (engineering, manufacturing))
    saved = _start(s, ctx, product.id, build.id)
    if saved is not None:
        saved = _row(s, ctx, product.id, BuildStart, saved.id)
        if saved.intent_digest != digest(semantic(payload)):
            raise DomainError(
                "BUILD_ALREADY_STARTED", "本轮已有实际开工事实，不重复开工或占用。", 409
            )
        _recheck_authority(s, ctx, product.id, build.project_id, saved.authority_snapshot, at)
    bundle = _bundle(s, ctx, product.id, build, scope, at, write=True, saved_start=saved)
    _match_bundle(assessment, bundle, at)
    event_reads = [
        {"artifact_id": event["artifact_id"], "expected_revision": event["expected_revision"]}
    ]
    reads = _reads(
        assessment.required_source_read_set,
        engineering.required_source_read_set,
        manufacturing.required_source_read_set,
        actor["required_source_read_set"],
        bundle["required_source_read_set"],
        event_reads,
    )
    _exact_reads(s, ctx, product.id, command, reads, (event,), build=build)
    source = s.get(Artifact, payload.event_source.artifact_id)
    if (
        source.content.splitlines()[payload.event_source.line - 1].strip()
        != payload.event_source.quote.strip()
    ):
        raise DomainError("START_EVENT_MISMATCH", "开工事件依据必须是所指原文完整一行。", 422)
    return assessment, build, scope, engineering, manufacturing, actor, bundle, reads, saved


@command_inputs_once
def _authorization_inputs(s, ctx, command, product, payload, at):
    role = ROLES[command.operation]
    assessment, build, scope = _assessment(s, ctx, product.id, payload)
    authority = _authority(
        s, ctx, product.id, build, command.operation, scope.purpose, at, write=True
    )
    _require_authority(
        authority, role, until=scope.window_end if payload.action == "approve" else None
    )
    if payload.action == "approve":
        require_candidate(assessment.result)
        validate_professional_review(payload, role, scope, at)
        _current_assessment_guard(s, ctx, product.id, assessment)
        bundle = _bundle(s, ctx, product.id, build, scope, at, write=True)
        _match_bundle(assessment, bundle, at)
        if payload.valid_until is not None and (
            payload.valid_until <= at or payload.valid_until < scope.window_end
        ):
            raise DomainError(
                "AUTHORIZATION_WINDOW_NOT_COVERED", "批准有效期须覆盖固定执行窗口且当前有效。", 409
            )
    else:
        # Withdrawal of a current decision is possible even after assessment replacement.
        bundle = assessment.result
    raw = semantic(payload)
    sources = raw["sources"]
    professional_sources = [
        ref for item in raw["professional_assessments"] for ref in item["sources"]
    ]
    reads = _reads(
        assessment.required_source_read_set,
        authority["required_source_read_set"],
        bundle["required_source_read_set"],
        [
            {"artifact_id": ref["artifact_id"], "expected_revision": ref["expected_revision"]}
            for ref in [*sources, *professional_sources]
        ],
    )
    _exact_reads(s, ctx, product.id, command, reads, [*sources, *professional_sources], build=build)
    return role, assessment, build, scope, authority, bundle, reads, sources


def validate(s, ctx, command, product, payload):
    _human(s, ctx, product.id, write=True)
    if isinstance(payload, BuildAssessmentPayload):
        build = _build(s, ctx, product.id, payload.build_id)
        _, _, _, linked_reads = _linked(s, ctx, product.id, build)
        bundle = _bundle(s, ctx, product.id, build, payload.execution_scope, now(), write=True)
        _exact_reads(
            s,
            ctx,
            product.id,
            command,
            _reads(linked_reads, bundle["required_source_read_set"]),
            build=build,
        )
    elif isinstance(payload, BuildAuthorizationPayload):
        _authorization_inputs(s, ctx, command, product, payload, now())
    elif isinstance(payload, BuildStartPayload):
        _start_inputs(s, ctx, command, product, payload, now())
    else:
        raise DomainError("INVALID_PAYLOAD", "执行动作的输入类型不匹配。", 422)


def _assessment_cas(s, ctx, product_id, build, payload, *, lock=False):
    pointer, previous = _current_assessment(s, ctx, product_id, build.id, lock=lock)
    if (previous.id if previous else None) != payload.previous_assessment_id or (
        previous.revision if previous else 0
    ) != payload.expected_previous_revision:
        raise DomainError(
            "ASSESSMENT_VERSION_CONFLICT", "当前执行评估已推进，请重读当前版后复评。", 409
        )
    return pointer, previous


def _decision_cas(s, ctx, product_id, build, role, payload, *, lock=False):
    pointer, previous = _current_decision(s, ctx, product_id, build.id, role, lock=lock)
    if (previous.id if previous else None) != payload.previous_decision_id or (
        previous.revision if previous else 0
    ) != payload.expected_previous_revision:
        raise DomainError(
            "AUTHORIZATION_VERSION_CONFLICT", "该专业当前决定已推进，请重新核对。", 409
        )
    if payload.action == "revoke" and (
        previous is None or previous.assessment_id != payload.assessment_id
    ):
        raise DomainError("AUTHORIZATION_SCOPE_MISMATCH", "撤销须固定当前专业决定及其原评估。", 409)
    return pointer, previous


def _scope_view(scope):
    raw = scope.model_dump(mode="json")
    quantity = format(scope.quantity, "f")
    raw["quantity"] = quantity.rstrip("0").rstrip(".") if "." in quantity else quantity
    return raw


def _assessment_candidate(s, ctx, command, product, payload, at):
    build = _build(s, ctx, product.id, payload.build_id)
    if build.revision != payload.expected_build_revision:
        raise DomainError("BUILD_VERSION_CONFLICT", "固定试制计划版本已变化。", 409)
    if _start(s, ctx, product.id, build.id) is not None:
        raise DomainError(
            "BUILD_ALREADY_STARTED", "本轮已实际开工，执行评估不覆盖既有开工事实。", 409
        )
    _, previous = _assessment_cas(s, ctx, product.id, build, payload)
    _, engineering, manufacturing, linked_reads = _linked(s, ctx, product.id, build)
    result = readiness_result(
        _bundle(s, ctx, product.id, build, payload.execution_scope, at, write=True),
        build_type=build.type,
        purpose=payload.execution_scope.purpose,
    )
    reads = _reads(linked_reads, result["required_source_read_set"])
    _exact_reads(s, ctx, product.id, command, reads, build=build)
    row = BuildExecutionAssessment(
        id=_identity(command),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=build.project_id,
        build_id=build.id,
        build_revision=build.revision,
        engineering_configuration_id=build.engineering_configuration_id,
        manufacturing_configuration_id=build.manufacturing_configuration_id,
        engineering_configuration_revision=engineering["revision"],
        manufacturing_configuration_revision=manufacturing["revision"],
        revision=previous.revision + 1 if previous else 1,
        previous_assessment_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        owner_id=previous.owner_id if previous else ctx.requester_id,
        visibility=previous.visibility if previous else build.visibility,
        status=result["state"],
        execution_scope=_scope_view(payload.execution_scope),
        result=result,
        required_source_read_set=reads,
        intent_digest=digest(semantic(payload)),
        reason=payload.reason,
    )
    row.snapshot_sha256 = digest(_material(row))
    return row, previous


def _authorization_candidate(s, ctx, command, product, payload, at):
    role, assessment, build, scope, authority, bundle, reads, sources = _authorization_inputs(
        s, ctx, command, product, payload, at
    )
    _, previous = _decision_cas(s, ctx, product.id, build, role, payload)
    if payload.action == "approve" and _start(s, ctx, product.id, build.id) is not None:
        raise DomainError("BUILD_ALREADY_STARTED", "本轮已开工，不补造或替换开工前的批准。", 409)
    row = BuildAuthorizationDecision(
        id=_identity(command),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=build.project_id,
        build_id=build.id,
        engineering_configuration_id=build.engineering_configuration_id,
        manufacturing_configuration_id=build.manufacturing_configuration_id,
        role=role,
        revision=previous.revision + 1 if previous else 1,
        previous_decision_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        assessment_id=assessment.id,
        assessment_revision=assessment.revision,
        assessment_sha256=assessment.snapshot_sha256,
        owner_id=ctx.requester_id,
        visibility=build.visibility,
        action=payload.action,
        status="approved" if payload.action == "approve" else "revoked",
        valid_until=payload.valid_until,
        authority_snapshot=authority,
        fact_binding={
            **_binding(bundle),
            "professional_assessments": semantic(payload)["professional_assessments"],
            "accepted_controls": semantic(payload)["accepted_controls"],
            "template": "internal-build-manufacturing.v1",
        },
        sources=sources,
        required_source_read_set=reads,
        intent_digest=digest(semantic(payload)),
        reason=payload.reason,
    )
    row.snapshot_sha256 = digest(_material(row))
    return row, previous, assessment


def _candidate_base(row):
    result = _material(row)
    result.update(
        {
            "snapshot_sha256": row.snapshot_sha256,
            "created_at": None,
            "source_status": "current",
            "server_on_save": ["created_at"],
        }
    )
    if isinstance(row, BuildExecutionAssessment):
        result["is_current"] = True
        result["exploration_boundary"] = deepcopy(EXPLORATION_BOUNDARY)
    return result


def _resolved(assessment, engineering, manufacturing):
    result = deepcopy(assessment.result)
    reviews = {
        item["rule_id"]: (item, decision)
        for decision in (engineering, manufacturing)
        for item in decision.fact_binding["professional_assessments"]
    }
    for check in result["checks"]:
        if check["code"] in reviews:
            item, decision = reviews[check["code"]]
            check.update(
                {
                    "status": "READY",
                    "detail": item["reason"],
                    "freshness": "current_named_decision",
                    "source": deepcopy(item["sources"]),
                    "decision_id": str(decision.id),
                    "decision_revision": decision.revision,
                }
            )
    result.update(
        {
            "state": "READY_WITH_CONDITIONS",
            "controls": sorted(CONTROLS),
            "limit": "仅固定用途的内部prototype/tool_trial制造，"
            "不授专业发布、TestRun或外部交付资格。",
        }
    )
    return result


def preview_view(s, ctx, command, product, payload):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围版本已经变化。", 409)
    validate(s, ctx, command, product, payload)
    at = now()
    if isinstance(payload, BuildAssessmentPayload):
        row, previous = _assessment_candidate(s, ctx, command, product, payload, at)
        before = _view(s, ctx, product.id, previous) if previous else None
        after = _candidate_base(row)
    elif isinstance(payload, BuildAuthorizationPayload):
        row, previous, assessment = _authorization_candidate(s, ctx, command, product, payload, at)
        before = _view(s, ctx, product.id, previous) if previous else None
        after = {**_candidate_base(row), "execution_scope": deepcopy(assessment.execution_scope)}
    else:
        assessment, build, scope, engineering, manufacturing, authority, bundle, reads, saved = (
            _start_inputs(s, ctx, command, product, payload, at)
        )
        before = _view(s, ctx, product.id, saved) if saved else None
        after = {
            "id": str(_identity(command)),
            "revision": 1,
            "build_id": str(build.id),
            "project_id": str(build.project_id),
            "status": "executing",
            "owner_id": str(ctx.requester_id),
            "visibility": build.visibility,
            "assessment_id": str(assessment.id),
            "assessment_revision": assessment.revision,
            "assessment_sha256": assessment.snapshot_sha256,
            "engineering_authorization_id": str(engineering.id),
            "engineering_authorization_revision": engineering.revision,
            "manufacturing_authorization_id": str(manufacturing.id),
            "manufacturing_authorization_revision": manufacturing.revision,
            "execution_scope": _scope_view(scope),
            "occurred_at": payload.occurred_at.isoformat(),
            "occurred_timezone": payload.occurred_timezone,
            "event_source": payload.event_source.model_dump(mode="json"),
            "authority_snapshot": authority,
            "fact_binding": _binding(bundle),
            "execution_result": _resolved(assessment, engineering, manufacturing),
            "reservations": {
                "disposition": "atomic_on_save",
                "material_holds": None,
                "resource_reservations": None,
            },
            "required_source_read_set": reads,
            "created_at": None,
            "source_status": "current",
            "server_on_save": [
                "created_at",
                "atomic_material_holds",
                "atomic_resource_reservations",
            ],
            "reason": payload.reason,
        }
    return {
        "operation": command.operation,
        "name": "试制执行",
        "effect": EFFECTS[command.operation],
        "before": before,
        "after": after,
        "reason": payload.reason,
    }


def apply(s, ctx, command, product, payload):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围版本已经变化。", 409)
    at = now()
    if isinstance(payload, BuildAssessmentPayload):
        row, _ = _assessment_candidate(s, ctx, command, product, payload, at)
        pointer, _ = _assessment_cas(
            s, ctx, product.id, _build(s, ctx, product.id, row.build_id), payload, lock=True
        )
        s.add(row)
        s.flush()
        if pointer is None:
            s.add(
                BuildAssessmentCurrent(
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    project_id=row.project_id,
                    build_id=row.build_id,
                    assessment_id=row.id,
                    assessment_revision=row.revision,
                )
            )
        else:
            pointer.assessment_id, pointer.assessment_revision = row.id, row.revision
        s.flush()
        return row, "build_execution_assessment", row.visibility
    if isinstance(payload, BuildAuthorizationPayload):
        row, _, _ = _authorization_candidate(s, ctx, command, product, payload, at)
        pointer, _ = _decision_cas(
            s,
            ctx,
            product.id,
            _build(s, ctx, product.id, row.build_id),
            row.role,
            payload,
            lock=True,
        )
        s.add(row)
        s.flush()
        if pointer is None:
            s.add(
                BuildAuthorizationCurrent(
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    project_id=row.project_id,
                    build_id=row.build_id,
                    role=row.role,
                    decision_id=row.id,
                    decision_revision=row.revision,
                )
            )
        else:
            pointer.decision_id, pointer.decision_revision = row.id, row.revision
        s.flush()
        return row, "build_authorization", row.visibility
    assessment, build, scope, engineering, manufacturing, authority, bundle, reads, saved = (
        _start_inputs(s, ctx, command, product, payload, at)
    )
    if saved is not None:
        raise DomainError(
            "BUILD_ALREADY_STARTED", "既有开工应由共同回执重放，不生成第二次开工。", 409
        )
    from pdos_next.domain.build_operational_facts.service import reserve

    identity, intent = _identity(command), digest(semantic(payload))
    reservations = reserve(
        s,
        ctx,
        product.id,
        build.id,
        _port_scope(scope),
        owner_execution_id=identity,
        intent_digest=intent,
        expected_facts_revision=bundle["facts_revision"],
        at=at,
    )
    row = BuildStart(
        id=identity,
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=build.project_id,
        build_id=build.id,
        build_revision=build.revision,
        engineering_configuration_id=build.engineering_configuration_id,
        manufacturing_configuration_id=build.manufacturing_configuration_id,
        assessment_id=assessment.id,
        assessment_revision=assessment.revision,
        assessment_sha256=assessment.snapshot_sha256,
        engineering_authorization_id=engineering.id,
        engineering_authorization_revision=engineering.revision,
        manufacturing_authorization_id=manufacturing.id,
        manufacturing_authorization_revision=manufacturing.revision,
        revision=1,
        owner_id=ctx.requester_id,
        visibility=build.visibility,
        status="executing",
        occurred_at=payload.occurred_at,
        occurred_timezone=payload.occurred_timezone,
        execution_scope=_scope_view(scope),
        event_source=payload.event_source.model_dump(mode="json"),
        authority_snapshot=authority,
        reservations={
            **_json(reservations),
            "execution_result": _resolved(assessment, engineering, manufacturing),
        },
        sources=[payload.event_source.model_dump(mode="json")],
        required_source_read_set=reads,
        intent_digest=intent,
        reason=payload.reason,
    )
    row.snapshot_sha256 = digest(_material(row))
    return row, "build_start", row.visibility


def assessment_inputs(s, ctx, product_id, payload):
    """Scope-dependent source discovery only; no assessment, confirmation or reservation."""
    _human(s, ctx, product_id, write=True)
    build = _build(s, ctx, product_id, payload.build_id)
    if build.revision != payload.expected_build_revision:
        raise DomainError("BUILD_VERSION_CONFLICT", "固定计划版本已变化。", 409)
    _, _, _, linked_reads = _linked(s, ctx, product_id, build)
    result = readiness_result(
        _bundle(s, ctx, product_id, build, payload.execution_scope, now()),
        build_type=build.type,
        purpose=payload.execution_scope.purpose,
    )
    reads = _reads(linked_reads, result["required_source_read_set"])
    _, private = _sources(s, ctx, product_id, reads)
    if build.visibility == "category" and private:
        raise DomainError("PRIVATE_SOURCE_SCOPE", "共享本轮不能使用私人操作事实来源。", 403)
    return {
        "build_id": str(build.id),
        "build_revision": build.revision,
        "execution_scope": _scope_view(payload.execution_scope),
        "result": result,
        "required_source_read_set": reads,
        "effect": "只核对当前输入与所需来源；未保存评估、批准、预约或开工。",
    }


def _view(s, ctx, product_id, row):
    if row is None:
        return None
    # ACL failure hides derived contents. Visible expired sources remain historical.
    row = _row(s, ctx, product_id, type(row), row.id)
    state = _read_evidence(s, ctx, product_id, row)
    raw = _material(row)
    raw.update(
        {
            "snapshot_sha256": row.snapshot_sha256,
            "created_at": row.created_at.isoformat(),
            "source_status": state,
        }
    )
    if isinstance(row, BuildExecutionAssessment):
        pointer, _ = _current_assessment(s, ctx, product_id, row.build_id)
        raw["is_current"] = pointer is not None and pointer.assessment_id == row.id
        raw["expected_previous_revision"] = row.previous_revision or 0
        raw["exploration_boundary"] = deepcopy(EXPLORATION_BOUNDARY)
    elif isinstance(row, BuildAuthorizationDecision):
        pointer, _ = _current_decision(s, ctx, product_id, row.build_id, row.role)
        raw["is_current"] = pointer is not None and pointer.decision_id == row.id
        raw["professional_assessments"] = deepcopy(
            row.fact_binding.get("professional_assessments", [])
        )
        raw["accepted_controls"] = deepcopy(row.fact_binding.get("accepted_controls", []))
        raw["expected_previous_revision"] = row.previous_revision or 0
        assessment = _row(s, ctx, product_id, BuildExecutionAssessment, row.assessment_id)
        raw["execution_scope"] = deepcopy(assessment.execution_scope)
        raw["expired"] = row.valid_until is not None and row.valid_until <= now()
    else:
        raw["execution_result"] = deepcopy(row.reservations.get("execution_result"))
    return raw


def _allowed(authority, role, scope):
    try:
        _require_authority(authority, role, until=scope.window_end)
        return True
    except DomainError:
        return False


def _saved_capabilities(
    s, ctx, product_id, build, assessment, decisions, saved, *, as_of=None, include_actions=True
):
    """Stored execution result plus exact Current/source watermarks; no reallocation."""
    from .current import _require, authority_watermarks, reservation_watermarks

    at = as_of or now()
    caps = {
        "readiness_compute": False,
        "engineering_approve": False,
        "engineering_revoke": False,
        "manufacturing_approve": False,
        "manufacturing_revoke": False,
        "start": False,
        "authority": {"start": deepcopy(saved.authority_snapshot)},
        "revoke_authority": {},
        "blockers": [],
        "required_source_read_set": deepcopy(saved.required_source_read_set),
        "needs_input": assessment is None,
        "execution_status": "executing",
        "stop_required": True,
        "execution_qualification": "needs_recheck",
    }
    try:
        _require(
            assessment is not None
            and assessment.id == saved.assessment_id
            and assessment.revision == saved.assessment_revision
            and assessment.snapshot_sha256 == saved.assessment_sha256
        )
        _require(digest(_material(saved)) == saved.snapshot_sha256, "INTEGRITY_MISMATCH")
        scope = _scope_of(assessment)
        for role in ("engineering", "manufacturing"):
            decision = decisions.get(role)
            _require(
                decision is not None
                and decision.action == "approve"
                and decision.id == getattr(saved, f"{role}_authorization_id")
                and decision.revision == getattr(saved, f"{role}_authorization_revision")
                and decision.assessment_id == assessment.id
                and decision.assessment_sha256 == assessment.snapshot_sha256,
                "AUTHORIZATION_NOT_CURRENT",
            )
            _require(
                decision.valid_until is None or decision.valid_until > at, "AUTHORIZATION_EXPIRED"
            )
            authority_watermarks(
                s,
                ctx,
                product_id,
                build.project_id,
                decision.authority_snapshot,
                at,
                retained=as_of is not None,
            )
        authority_watermarks(
            s,
            ctx,
            product_id,
            build.project_id,
            saved.authority_snapshot,
            at,
            retained=as_of is not None,
        )
        reservation_watermarks(s, ctx, product_id, build, assessment, saved, _port_scope(scope), at)
        actual, actual_reads, deviation = _actual_binding(s, ctx, product_id, build)
        fixed = assessment.result.get("actual_configuration_binding") or []
        indexed = {row["id"]: row for row in actual}
        _require(not deviation, "ACTUAL_CONFIGURATION_DEVIATION")
        _require(all(indexed.get(row["id"]) == row for row in fixed))
        reads = _reads(saved.required_source_read_set, actual_reads)
        _, private = _sources(s, ctx, product_id, reads)
        _require(not private or build.visibility != "category", "PRIVATE_SOURCE_SCOPE")
        resolved = _resolved(assessment, decisions["engineering"], decisions["manufacturing"])
        _require(resolved == saved.reservations["execution_result"], "INTEGRITY_MISMATCH")
        caps.update(
            current_result=deepcopy(saved.reservations["execution_result"]),
            required_source_read_set=reads,
            stop_required=False,
            execution_qualification="limited_current",
        )
    except DomainError as error:
        if error.status == 403 and error.reason in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
            raise
        caps["blockers"].append({"code": error.reason, "detail": error.message})
    if include_actions and as_of is None and assessment is not None:
        from pdos_next.service import require_access

        try:
            require_access(s, ctx, product_id, write=True)
            _human(s, ctx, product_id)
        except DomainError:
            return caps
        scope = _scope_of(assessment)
        for role in ("engineering", "manufacturing"):
            try:
                value = _authority(
                    s, ctx, product_id, build, f"build.{role}.authorize", scope.purpose, at
                )
                caps["authority"][f"{role}_authorize"] = value
                caps["revoke_authority"][role] = value
                _require_authority(value, role)
                decision = decisions.get(role)
                if decision is not None:
                    _sources(s, ctx, product_id, decision.required_source_read_set)
                    caps[f"{role}_revoke"] = decision.action == "approve"
            except DomainError:
                pass
    return caps


def _capabilities(s, ctx, product_id, build, assessment, decisions, saved, *, as_of=None):
    from pdos_next.service import require_access

    if saved is not None:
        return _saved_capabilities(
            s, ctx, product_id, build, assessment, decisions, saved, as_of=as_of
        )
    at, blockers = as_of or now(), []
    caps = {
        "readiness_compute": False,
        "engineering_approve": False,
        "engineering_revoke": False,
        "manufacturing_approve": False,
        "manufacturing_revoke": False,
        "start": False,
        "authority": {},
        "revoke_authority": {},
        "blockers": blockers,
        "required_source_read_set": [],
        "needs_input": assessment is None,
        "execution_status": "executing" if saved else "planned",
        "stop_required": False,
        "execution_qualification": "not_started" if saved is None else "needs_recheck",
    }
    try:
        require_access(s, ctx, product_id, write=True)
        _human(s, ctx, product_id)
        caps["readiness_compute"] = saved is None
    except DomainError as error:
        blockers.append({"code": error.reason, "detail": "当前人员不能办理本轮执行动作。"})
    if assessment is None:
        blockers.append(
            {
                "code": "EXECUTION_ASSESSMENT_REQUIRED",
                "detail": "请填写固定执行范围并保存准备度评估。",
            }
        )
        return caps
    scope = _scope_of(assessment)
    caps["required_source_read_set"] = deepcopy(assessment.required_source_read_set)
    for operation, key in (
        *[(operation, f"{role}_authorize") for operation, role in ROLES.items()],
        ("build.start", "start"),
    ):
        caps["authority"][key] = _authority(s, ctx, product_id, build, operation, scope.purpose, at)
        if saved is not None and operation == "build.start":
            caps["authority"][key] = _recheck_authority(
                s,
                ctx,
                product_id,
                build.project_id,
                saved.authority_snapshot,
                at,
                retained=as_of is not None,
            )
    current = False
    try:
        bundle = _bundle(s, ctx, product_id, build, scope, at, saved_start=saved)
        caps["required_source_read_set"] = _reads(
            assessment.required_source_read_set, bundle["required_source_read_set"]
        )
        caps["current_result"] = readiness_result(
            bundle, build_type=build.type, purpose=scope.purpose
        )
        blockers.extend(
            {"code": check["code"], "detail": check["detail"]}
            for check in bundle["checks"]
            if check["status"] in {"BLOCKED", "UNKNOWN"}
        )
        if saved:
            _match_execution_bundle(assessment, bundle, at)
        else:
            _match_bundle(assessment, bundle, at)
        require_candidate(assessment.result)
        # Newly observed matching configurations remain source-controlled too.
        _, private = _sources(s, ctx, product_id, bundle["required_source_read_set"])
        if private and build.visibility == "category":
            raise DomainError("PRIVATE_SOURCE_SCOPE", "来源受众与本轮共享范围不一致。", 403)
        current = True
    except DomainError as error:
        blockers.append({"code": error.reason, "detail": error.message})
        caps["stop_required"] = saved is not None
    for role in ("engineering", "manufacturing"):
        caps[f"{role}_approve"] = (
            saved is None
            and current
            and _allowed(caps["authority"][f"{role}_authorize"], role, scope)
        )
        decision = decisions.get(role)
        if decision is None:
            blockers.append(
                {
                    "code": f"{role.upper()}_AUTHORIZATION_REQUIRED",
                    "detail": "尚无对应专业的当前具名批准。",
                }
            )
            continue
        try:
            old_assessment = _row(
                s, ctx, product_id, BuildExecutionAssessment, decision.assessment_id
            )
            revoke_authority = _authority(
                s,
                ctx,
                product_id,
                build,
                f"build.{role}.authorize",
                _scope_of(old_assessment).purpose,
                at,
            )
            caps["revoke_authority"][role] = revoke_authority
            _require_authority(revoke_authority, role)
            _sources(s, ctx, product_id, decision.required_source_read_set)
            caps[f"{role}_revoke"] = decision.action == "approve"
        except DomainError:
            caps[f"{role}_revoke"] = False
    if all(role in decisions for role in ("engineering", "manufacturing")) and current:
        try:
            for role, decision in decisions.items():
                _decision_guard(
                    s,
                    ctx,
                    product_id,
                    decision,
                    assessment,
                    role,
                    scope,
                    at,
                    retained=as_of is not None,
                )
                _sources(s, ctx, product_id, decision.required_source_read_set)
            _require_authority(caps["authority"]["start"], "manufacturing", until=scope.window_end)
            # Preview separately checks the actual event source/time.
            caps["start"] = saved is None
            if saved:
                _recheck_authority(
                    s,
                    ctx,
                    product_id,
                    build.project_id,
                    saved.authority_snapshot,
                    at,
                    retained=as_of is not None,
                )
                _sources(s, ctx, product_id, saved.required_source_read_set)
                caps["execution_qualification"] = "limited_current"
                caps["stop_required"] = False
                caps["current_result"] = _resolved(
                    assessment, decisions["engineering"], decisions["manufacturing"]
                )
        except DomainError as error:
            blockers.append({"code": error.reason, "detail": error.message})
            caps["stop_required"] = saved is not None
    if not scope.window_start <= at < scope.window_end:
        caps["start"] = False
        blockers.append(
            {
                "code": "OUTSIDE_EXECUTION_WINDOW",
                "detail": "当前时点不在固定执行窗口，实际开工仍须以事件时钟核对。",
            }
        )
    return caps


def list_execution(s, ctx, product_id):
    from pdos_next.domain.builds.models import Build
    from pdos_next.service import require_access

    require_access(s, ctx, product_id)
    result = {
        "assessments": [],
        "current_assessment_by_build": {},
        "authorizations": [],
        "current_authorization_by_build": {},
        "starts": [],
        "capabilities_by_build": {},
        "capabilities": {
            "public_authority_import": False,
            "ai_t2": False,
            "external_delivery": False,
            "test_run_start": False,
        },
    }
    for model, key in (
        (BuildExecutionAssessment, "assessments"),
        (BuildAuthorizationDecision, "authorizations"),
        (BuildStart, "starts"),
    ):
        rows = s.scalars(
            select(model)
            .where(model.tenant_id == ctx.tenant_id, model.product_id == product_id)
            .order_by(model.created_at, model.id)
        ).all()
        for row in rows:
            try:
                result[key].append(_view(s, ctx, product_id, row))
            except DomainError as error:
                if error.reason in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
                    continue
                raise
    builds = s.scalars(
        select(Build)
        .where(Build.tenant_id == ctx.tenant_id, Build.product_id == product_id)
        .order_by(Build.created_at, Build.id)
    ).all()
    for build in builds:
        try:
            _, assessment = _current_assessment(s, ctx, product_id, build.id)
            if assessment is not None:
                _read_evidence(s, ctx, product_id, assessment)
                result["current_assessment_by_build"][str(build.id)] = {
                    "assessment_id": str(assessment.id),
                    "revision": assessment.revision,
                }
            decisions = {}
            for role in ("engineering", "manufacturing"):
                try:
                    _, decision = _current_decision(s, ctx, product_id, build.id, role)
                    if decision is not None:
                        _read_evidence(s, ctx, product_id, decision)
                        decisions[role] = decision
                        result["current_authorization_by_build"].setdefault(str(build.id), {})[
                            role
                        ] = {"decision_id": str(decision.id), "revision": decision.revision}
                except DomainError as error:
                    if error.reason not in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
                        raise
            saved = _start(s, ctx, product_id, build.id)
            if saved is not None:
                saved = _row(s, ctx, product_id, BuildStart, saved.id)
                _read_evidence(s, ctx, product_id, saved)
            result["capabilities_by_build"][str(build.id)] = _capabilities(
                s, ctx, product_id, build, assessment, decisions, saved
            )
        except DomainError as error:
            if error.reason not in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
                raise
    return result


def get_assessment(s, ctx, product_id, identity):
    row = _row(s, ctx, product_id, BuildExecutionAssessment, identity)
    return row, _view(s, ctx, product_id, row)


def _projection_current(s, ctx, product_id, build):
    """Read this Build's complete Current set in one RLS snapshot query."""
    from sqlalchemy import literal
    from sqlalchemy.orm import aliased

    from pdos_next.request_proof import request_proof

    if build.tenant_id != ctx.tenant_id or build.product_id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "执行投影不在当前构建范围。", 403)
    # Start is unique and immutable for this Build. Sample inspection already
    # read it under this exact RR/RLS scope; other callers still read it here.
    saved = _start(s, ctx, product_id, build.id)
    proof = request_proof(s)
    key = ("build-projection-current", product_id, build.id)
    if key not in proof.scalar_rows:
        engineering = aliased(BuildAuthorizationCurrent)
        manufacturing = aliased(BuildAuthorizationCurrent)
        engineering_fact = aliased(BuildAuthorizationDecision)
        manufacturing_fact = aliased(BuildAuthorizationDecision)
        # execution_projection already read this exact Build under the same RR
        # RLS snapshot. Its identity anchors the direct Current query; repeating
        # the Build SELECT would re-evaluate the same full ancestor ACL set.
        selected_build = select(
            literal(build.tenant_id).label("tenant_id"),
            literal(build.product_id).label("product_id"),
            literal(build.id).label("id"),
        ).subquery()
        scope = selected_build.c
        query = (
            select(
                BuildAssessmentCurrent,
                BuildExecutionAssessment,
                engineering,
                engineering_fact,
                manufacturing,
                manufacturing_fact,
            )
            .select_from(selected_build)
            .outerjoin(
                BuildAssessmentCurrent,
                (BuildAssessmentCurrent.tenant_id == scope.tenant_id)
                & (BuildAssessmentCurrent.product_id == scope.product_id)
                & (BuildAssessmentCurrent.build_id == scope.id),
            )
            .outerjoin(
                BuildExecutionAssessment,
                BuildExecutionAssessment.id == BuildAssessmentCurrent.assessment_id,
            )
            .outerjoin(
                engineering,
                (engineering.tenant_id == scope.tenant_id)
                & (engineering.product_id == scope.product_id)
                & (engineering.build_id == scope.id)
                & (engineering.role == "engineering"),
            )
            .outerjoin(engineering_fact, engineering_fact.id == engineering.decision_id)
            .outerjoin(
                manufacturing,
                (manufacturing.tenant_id == scope.tenant_id)
                & (manufacturing.product_id == scope.product_id)
                & (manufacturing.build_id == scope.id)
                & (manufacturing.role == "manufacturing"),
            )
            .outerjoin(manufacturing_fact, manufacturing_fact.id == manufacturing.decision_id)
        )
        proof.scalar_rows[key] = s.execute(query).one()
    pointer, assessment, ep, ef, mp, mf = proof.scalar_rows[key]
    if assessment is not None:
        if pointer.assessment_revision != assessment.revision:
            raise DomainError("INTEGRITY_MISMATCH", "执行评估 Current 无法核对。")
        assessment = _row(s, ctx, product_id, BuildExecutionAssessment, assessment.id)
    decisions = {}
    for role, current, fact in (("engineering", ep, ef), ("manufacturing", mp, mf)):
        if fact is not None:
            if current.decision_revision != fact.revision or fact.role != role:
                raise DomainError("INTEGRITY_MISMATCH", "执行批准 Current 无法核对。")
            decisions[role] = _row(s, ctx, product_id, BuildAuthorizationDecision, fact.id)
    if saved is not None:
        saved = _row(s, ctx, product_id, BuildStart, saved.id)
    return assessment, decisions, saved


def _writer_projection_scope(s, ctx, product_id):
    """Actual clean held Product scope; a marker alone never proves raw rows."""
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.orm import Session, SessionTransaction

    from pdos_next.database import require_context
    from pdos_next.domain.builds.models import Build
    from pdos_next.models import Product
    from pdos_next.request_proof import request_proof

    if (
        not isinstance(s, Session)
        or s.is_active is not True
        or not s.in_transaction()
        or s.info.get("read_snapshot") is True
        or s.new
        or s.dirty
        or s.deleted
    ):
        return None
    require_context(s, ctx)
    scope = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    if s.info.get("scope") != scope:
        return None
    proof = request_proof(s)
    if product_id not in proof.scope_locks or s.get_transaction() is not proof.transaction:
        return None
    chain, seen = [], set()
    node = s._transaction
    while node is not None:
        if (
            not isinstance(node, SessionTransaction)
            or node.session is not s
            or node.is_active is not True
            or id(node) in seen
            or len(chain) >= 128
        ):
            return None
        seen.add(id(node))
        chain.append(node)
        node = node.parent
    if not chain or chain[-1] is not proof.transaction:
        return None
    if s.get_nested_transaction() is not next((node for node in chain if node.nested), None):
        return None
    try:
        bind = s.get_bind()
        if not isinstance(bind, (Engine, Connection)) or any(
            s.get_bind(mapper=model) is not bind
            for model in (
                Product,
                Build,
                BuildAssessmentCurrent,
                BuildExecutionAssessment,
                BuildAuthorizationCurrent,
                BuildAuthorizationDecision,
                BuildStart,
            )
        ):
            return None
    except Exception:
        # Binding resolution is only an optimization prerequisite. An unknown
        # or routed bind uses the same original ordered domain reads.
        return None
    # Inspect only connections already enlisted by the real gate SELECT.
    # Calling s.connection() here could enlist a new bind after s.bind changed
    # and falsely associate the old Product marker with another database UOW.
    enlisted = getattr(proof.transaction, "_connections", None)
    if not isinstance(enlisted, dict) or bind not in enlisted:
        return None
    entry = enlisted[bind]
    if not isinstance(entry, tuple) or len(entry) != 4:
        return None
    connection, transaction = entry[:2]
    if (
        not isinstance(connection, Connection)
        or connection.closed
        or connection.invalidated
        or getattr(transaction, "is_active", False) is not True
        or not connection.in_transaction()
        or connection.get_transaction() is not transaction
        or set(enlisted) != {connection, connection.engine}
        or any(
            not isinstance(value, tuple)
            or len(value) != 4
            or value[0] is not connection
            or value[1] is not transaction
            for value in enlisted.values()
        )
        or (isinstance(bind, Engine) and connection.engine is not bind)
        or (isinstance(bind, Connection) and connection is not bind)
    ):
        return None
    return (
        digest(vars(ctx)),
        scope,
        tuple(chain),
        proof.transaction,
        proof.mutation_epoch,
        bind,
        connection,
        transaction,
    )


def _writer_projection_query(build):
    """Complete fresh fields, never ORM identity-map or cached Current values."""
    from sqlalchemy import literal

    ac = BuildAssessmentCurrent.__table__.alias("owner_assessment_current")
    af = BuildExecutionAssessment.__table__.alias("owner_assessment_fact")
    ec = BuildAuthorizationCurrent.__table__.alias("owner_engineering_current")
    ef = BuildAuthorizationDecision.__table__.alias("owner_engineering_fact")
    mc = BuildAuthorizationCurrent.__table__.alias("owner_manufacturing_current")
    mf = BuildAuthorizationDecision.__table__.alias("owner_manufacturing_fact")
    owners = (
        ("ac", ac, BuildAssessmentCurrent),
        ("af", af, BuildExecutionAssessment),
        ("ec", ec, BuildAuthorizationCurrent),
        ("ef", ef, BuildAuthorizationDecision),
        ("mc", mc, BuildAuthorizationCurrent),
        ("mf", mf, BuildAuthorizationDecision),
    )
    anchor = select(
        literal(build.tenant_id).label("tenant_id"),
        literal(build.product_id).label("product_id"),
        literal(build.id).label("id"),
    ).subquery()
    scope = anchor.c

    def current_on(table):
        return (
            (table.c.tenant_id == scope.tenant_id)
            & (table.c.product_id == scope.product_id)
            & (table.c.build_id == scope.id)
        )

    query = select(
        *(
            column.label(f"{prefix}_{column.key}")
            for prefix, table, _ in owners
            for column in table.c
        )
    ).select_from(anchor)
    query = (
        query.outerjoin(ac, current_on(ac))
        .outerjoin(af, af.c.id == ac.c.assessment_id)
        .outerjoin(ec, current_on(ec) & (ec.c.role == "engineering"))
        .outerjoin(ef, ef.c.id == ec.c.decision_id)
        .outerjoin(mc, current_on(mc) & (mc.c.role == "manufacturing"))
        .outerjoin(mf, mf.c.id == mc.c.decision_id)
    )
    return query, owners


def _projection_ordered(s, ctx, product_id, build):
    """The original writer path, including its exact error/role order."""
    _, assessment = _current_assessment(s, ctx, product_id, build.id)
    decisions = {}
    for role in ("engineering", "manufacturing"):
        try:
            _, decision = _current_decision(s, ctx, product_id, build.id, role)
            if decision is not None:
                decisions[role] = decision
        except DomainError as error:
            if error.reason not in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
                raise
    saved = _start(s, ctx, product_id, build.id)
    if saved is not None:
        saved = _validated_row(s, ctx, product_id, saved)
    return assessment, decisions, saved


def _writer_projection_stamp(s, ctx, product_id, token):
    """Actual RLS Product clock and DB identity, on the already enlisted UOW.

    The clock is never an authority/source proof. Its conditional scalar read
    keeps malformed or missing GUCs out of category_access's UUID casts; the
    returned DB scope is still rejected explicitly instead of borrowing info.
    """
    from sqlalchemy import and_, case, func

    from pdos_next.models import Product

    names = ("tenant_id", "actor_id", "requester_id", "category_id")
    expected = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    settings = tuple(func.current_setting(f"pdos.{name}", True) for name in names)
    matches = and_(
        *(setting == (str(value) if value is not None else "")
          for setting, value in zip(settings, expected, strict=True))
    )
    clock = (
        select(Product.lifecycle_epoch)
        .where(
            Product.tenant_id == ctx.tenant_id,
            Product.category_id == ctx.category_id,
            Product.id == product_id,
        )
        .scalar_subquery()
    )
    query = select(
        *(setting.label(name) for name, setting in zip(names, settings, strict=True)),
        case((matches, clock), else_=None).label("lifecycle_epoch"),
    )
    # _writer_projection_scope proved this is the one actual, active,
    # already-enlisted Connection. Do not resolve or enlist a different bind.
    selected = list(token[-2].execute(query).mappings())
    if len(selected) != 1:
        raise DomainError("FORBIDDEN_SCOPE", "请求身份与数据库事务范围不符。", 403)
    row = selected[0]
    try:
        db_scope = tuple(UUID(row.get(name)) for name in names)
    except (AttributeError, TypeError, ValueError):
        raise DomainError("FORBIDDEN_SCOPE", "请求身份与数据库事务范围不符。", 403) from None
    if db_scope != expected:
        raise DomainError("FORBIDDEN_SCOPE", "请求身份与数据库事务范围不符。", 403)
    epoch = row.get("lifecycle_epoch")
    if type(epoch) is not int:
        # The real Product clock is NOT NULL. A NULL means this fresh RLS
        # read has no visible Product; do not inherit an older scalar proof.
        raise DomainError("FORBIDDEN_SCOPE", "请求身份与数据库事务范围不符。", 403)
    return epoch


def _projection_writer(s, ctx, product_id, build):
    """Share complete raw owner fields only while the actual DB clock matches.

    Each invocation reads Product's RLS clock and four DB scope GUCs anew.
    Legal Current changes, including this Session's untracked SQL, advance
    that clock. Every hit reconstructs all models and runs the original
    scope/hash guards; source, issuer, clock and execution guards run later
    as before. Nothing here caches an affirmative execution projection.
    """
    from sqlalchemy.exc import DBAPIError

    from pdos_next.request_proof import request_proof

    if not all(
        isinstance(value, UUID)
        for value in (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    ):
        # Legacy/category-less callers retain the original ordered semantics;
        # this clock optimization requires a complete server-bound DB scope.
        return None
    token = _writer_projection_scope(s, ctx, product_id)
    if token is None:
        return None
    epoch = _writer_projection_stamp(s, ctx, product_id, token)
    if _writer_projection_scope(s, ctx, product_id) != token:
        return None
    query, owners = _writer_projection_query(build)
    # This one fixed query factory has exact role literals and bindings. Use
    # its stable full table/column/mapper signature instead of compiling the
    # complete SQL text on every invocation. Actual execution still compiles
    # normally on a miss; the full scope and actual bind are in this key.
    signature = tuple(
        (
            prefix,
            table.name,
            model,
            tuple(model.__table__.c),
            tuple(table.c.keys()),
            tuple(
                (attribute.key, tuple(attribute.columns))
                for attribute in model.__mapper__.column_attrs
            ),
        )
        for prefix, table, model in owners
    )
    key = (
        "build-projection-writer-raw",
        (
            ctx.tenant_id, product_id, build.tenant_id, build.category_id,
            build.product_id, build.project_id, build.id,
        ),
        token,
        epoch,
        signature,
    )
    proof = request_proof(s)
    retained = proof.scalar_rows.get(key)
    if retained is not None:
        selected_rows = deepcopy(retained)
    else:
        try:
            with s.no_autoflush, s.begin_nested():
                selected_rows = tuple(dict(row) for row in s.execute(query).mappings())
        except DBAPIError:
            # SAVEPOINT rollback legitimately invalidates request proof markers.
            # Do not rebuild markers by hand; ordered loaders read normally.
            return None
    if _writer_projection_scope(s, ctx, product_id) != token or len(selected_rows) != 1:
        return None
    selected = selected_rows[0]
    rows = []
    for prefix, table, model in owners:
        fields = {column.key: selected[f"{prefix}_{column.key}"] for column in table.c}
        if fields["id"] is None:
            return None
        # Some full SQL columns (audience_dependencies) intentionally have
        # no mapped Python attribute. Preserve their real SQL/RLS read, but
        # construct only each mapper's exact single-column property name.
        values = {}
        for property_ in model.__mapper__.column_attrs:
            if len(property_.columns) != 1:
                return None
            column = property_.columns[0]
            if table.original.c.get(column.key) is not column or column.key not in fields:
                return None
            values[property_.key] = fields[column.key]
        # Detached local field values retain the original type-dispatched
        # material/hash validator. They are never added to this Session/cache.
        rows.append(model(**values))
    ac, af, ec, ef, mc, mf = rows
    for current, fact, identity, revision, role in (
        (ac, af, "assessment_id", "assessment_revision", None),
        (ec, ef, "decision_id", "decision_revision", "engineering"),
        (mc, mf, "decision_id", "decision_revision", "manufacturing"),
    ):
        if (
            (current.tenant_id, current.product_id, current.project_id, current.build_id)
            != (ctx.tenant_id, product_id, build.project_id, build.id)
            or (fact.tenant_id, fact.product_id, fact.project_id, fact.build_id)
            != (ctx.tenant_id, product_id, build.project_id, build.id)
            or getattr(current, identity) != fact.id
            or getattr(current, revision) != fact.revision
            or (role is not None and (current.role != role or fact.role != role))
        ):
            return None
    assessment = _validated_row(s, ctx, product_id, af)
    decisions = {}
    for role, fact in (("engineering", ef), ("manufacturing", mf)):
        try:
            decisions[role] = _validated_row(s, ctx, product_id, fact)
        except DomainError as error:
            if error.reason not in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
                raise
    saved = _start(s, ctx, product_id, build.id)
    if saved is not None:
        saved = _validated_row(s, ctx, product_id, saved)
    if (
        retained is None
        and set(decisions) == {"engineering", "manufacturing"}
        and _writer_projection_scope(s, ctx, product_id) == token
    ):
        # Only an actual complete matched set with all original row validators
        # successful is retained. Deep copies keep mutable JSON out of callers.
        # Existing flush/direct-mutation/rollback invalidators clear this map.
        proof.scalar_rows[key] = deepcopy(selected_rows)
    return assessment, decisions, saved


def execution_projection(s, ctx, product_id, build_id, *, retained_at=None):
    """Historical start stays executing; current authority/fact drift requires stop/recheck."""
    from pdos_next.service import require_access

    require_access(s, ctx, product_id)
    build = _build(s, ctx, product_id, build_id)
    # This port is called once per sample. Read only this Build's current chain,
    # applying the same guards as its list projection instead of every history row.
    try:
        packed = getattr(s, "info", {}).get("read_snapshot") is True
        if packed:
            assessment, decisions, saved = _projection_current(s, ctx, product_id, build)
        else:
            owner_rows = _projection_writer(s, ctx, product_id, build)
            if owner_rows is None:
                owner_rows = _projection_ordered(s, ctx, product_id, build)
            assessment, decisions, saved = owner_rows
        if assessment is not None:
            _read_evidence(s, ctx, product_id, assessment)
        for role, decision in tuple(decisions.items()):
            try:
                _read_evidence(s, ctx, product_id, decision)
            except DomainError as error:
                decisions.pop(role)
                if error.reason not in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
                    raise
        if saved is not None:
            _read_evidence(s, ctx, product_id, saved)
        if saved is not None:
            result = _saved_capabilities(
                s,
                ctx,
                product_id,
                build,
                assessment,
                decisions,
                saved,
                as_of=retained_at,
                include_actions=False,
            )
        else:
            result = _capabilities(
                s, ctx, product_id, build, assessment, decisions, saved, as_of=retained_at
            )
        if retained_at is not None:
            # A historical evidence check never grants a present execution action.
            for key in (
                "readiness_compute",
                "engineering_approve",
                "engineering_revoke",
                "manufacturing_approve",
                "manufacturing_revoke",
                "start",
            ):
                result[key] = False
            result["evaluation_nature"] = "retained_execution_at_saved_start"
        return result
    except DomainError as error:
        if error.reason not in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
            raise
        return None


list_build_start = list_execution
