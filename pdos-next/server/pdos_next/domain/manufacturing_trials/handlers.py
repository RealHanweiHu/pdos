"""Canonical T1 preparation/observation handlers; no start, release or T2 action."""

import hashlib
import json
from uuid import UUID

from pydantic import BaseModel

from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import (
    Gap,
    Observation,
    PilotCreate,
    PilotRun,
    Ref,
    ResultRecord,
    ToolTrial,
    ToolTrialCreate,
)
from pdos_next.schemas.verification.contracts import SourceRef, TimeFact

from .ports import Authority, Invocation, Mutation, Outcome, Ports, Preview
from .rules import calculate, counts_from_units, readiness

OPERATIONS = {
    "npi.tooltrial.create": (ToolTrialCreate, "tooltrial.created"),
    "npi.pilot.create": (PilotCreate, "pilot.created"),
    "npi.pilot.result.record": (ResultRecord, "pilot.results_recorded"),
}


def semantic_digest(payload) -> str:
    # Array ordering is significant; no aliasing distinct fixed inputs via sorting.
    data = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def _references(value) -> tuple[Ref, ...]:
    refs = []
    if isinstance(value, Ref):
        refs.append(value)
    elif isinstance(value, BaseModel):
        for key in type(value).model_fields:
            refs.extend(_references(getattr(value, key)))
    elif isinstance(value, tuple):
        for item in value:
            refs.extend(_references(item))
    return tuple(dict.fromkeys(refs))


def _sources(value) -> tuple[SourceRef, ...]:
    refs = []
    if isinstance(value, SourceRef):
        refs.append(value)
    elif isinstance(value, BaseModel):
        for key in type(value).model_fields:
            refs.extend(_sources(getattr(value, key)))
    elif isinstance(value, tuple):
        for item in value:
            refs.extend(_sources(item))
    return tuple(dict.fromkeys(refs))


class ManufacturingTrialsHandler:
    def __init__(self, ports: Ports):
        self.ports = ports

    def _port(self, name):
        port = getattr(self.ports, name)
        if port is None:
            raise DomainError("INTEGRATION_REQUIRED", f"{name}受控接口待接入。", 503)
        return port

    def _authorize(self, authority: Authority):
        if not authority.authorized or not {"engineering", "npi", "production"}.intersection(
            authority.roles
        ):
            raise DomainError("FORBIDDEN", "当前范围/职责未授权。", 403)
        if authority.cancelled:
            raise DomainError("RUN_CANCELLED", "运行已撤回。")
        if not authority.qualified:
            raise DomainError("QUALIFICATION_REQUIRED", "当前能力或专业资格未满足。", 403)

    def _payload(self, operation, payload):
        if operation not in OPERATIONS:
            raise DomainError(
                "OPERATION_UNAVAILABLE", "该动作未注册；具名验收/制造放行归T2所有者。", 403
            )
        return OPERATIONS[operation][0].model_validate(payload)

    def _inspect(self, authority, subject_id, operation, payload, expected_revision):
        facts = self._port("facts")
        pilot = None
        preparation = None
        for ref in _references(payload):
            facts.check_ref(authority.scope, ref, operation)
        for source in _sources(payload):
            facts.source(authority.scope, source, operation)
        if isinstance(payload, (ToolTrialCreate, PilotCreate)):
            if (
                facts.verify_parameters(authority.scope, payload.parameters, operation)
                != payload.parameters
            ):
                raise DomainError("PARAMETER_SOURCE_MISMATCH", "参数原值/单位未获服务器来源核对。")
        if isinstance(payload, ToolTrialCreate):
            if subject_id != payload.trial_id or expected_revision != 0:
                raise DomainError("INVALID_TARGET", "试模创建仅接受新目标。", 422)
            preparation = facts.preparation(authority.scope, payload)
            gaps = list(preparation.gaps)
            if not payload.material_lots:
                gaps.append(
                    Gap(
                        code="MATERIAL_LOT_UNKNOWN",
                        state="unknown",
                        detail="实际材料批次尚未固定",
                        owner_role="production",
                    )
                )
            if not payload.parameters:
                gaps.append(
                    Gap(
                        code="PARAMETER_UNKNOWN",
                        state="unknown",
                        detail="实际工艺参数尚未固定",
                        owner_role="production",
                    )
                )
            # These document/sample/method/resource gaps remain separate owner facts.
            for item in payload.verification.items:
                for field in (
                    "drawing",
                    "method",
                    "criterion_source",
                    "unit",
                    "conditions",
                    "material",
                ):
                    if not getattr(item, field):
                        gaps.append(
                            Gap(
                                code=f"QUALITY_{field.upper()}_UNKNOWN",
                                state="unknown",
                                detail=f"{item.id}的{field}待准备",
                                owner_role="quality",
                            )
                        )
                if item.criterion is None and item.criterion_text is None:
                    gaps.append(
                        Gap(
                            code="QUALITY_CRITERION_UNKNOWN",
                            state="unknown",
                            detail=f"{item.id}判据未知",
                            owner_role="quality",
                        )
                    )
                if set(payload.cavities) - set(item.cavities):
                    gaps.append(
                        Gap(
                            code="CAVITY_COVERAGE_GAP",
                            state="unknown",
                            detail=f"{item.id}未覆盖本轮全部模穴",
                            owner_role="quality",
                        )
                    )
            for document in payload.verification.documents:
                if document.required and document.source is None:
                    gaps.append(
                        Gap(
                            code="DOCUMENT_UNKNOWN",
                            state="unknown",
                            detail=f"资料{document.id}待补",
                            owner_role="engineering",
                        )
                    )
            if not payload.verification.expected_at:
                gaps.append(
                    Gap(
                        code="EXPECTED_TIME_UNKNOWN",
                        state="unknown",
                        detail="品质预期时点未知",
                        owner_role="quality",
                    )
                )
        elif isinstance(payload, PilotCreate):
            if subject_id != payload.pilot_id or expected_revision != 0:
                raise DomainError("INVALID_TARGET", "试产扩展创建仅接受新目标。", 422)
            self._lot(authority, payload.basis)
            preparation = facts.preparation(authority.scope, payload)
            gaps = list(preparation.gaps)
            required = (
                "manufacturing_baseline",
                "line",
                "people",
                "material_lots",
                "fixtures",
                "equipment",
                "instructions",
                "control_plan",
                "risk",
                "reservation",
                "first_article",
                "parameters",
            )
            for key in required:
                if not getattr(payload, key):
                    gaps.append(
                        Gap(
                            code=f"MISSING_{key.upper()}",
                            state="unknown",
                            detail=f"{key}尚无固定权威引用",
                            owner_role="npi",
                        )
                    )
            for parameter in payload.parameters:
                if parameter.value is None:
                    gaps.append(
                        Gap(
                            code="PARAMETER_UNKNOWN",
                            state="unknown",
                            detail=f"参数{parameter.key}未知",
                            owner_role="production",
                        )
                    )
        else:
            pilot = self._port("commands").pilot(authority.scope, subject_id)
            if pilot.scope != authority.scope:
                raise DomainError("FORBIDDEN_SCOPE", "试产不在当前服务器范围。", 403)
            if (
                pilot.revision != expected_revision
                or payload.expected_pilot_revision != pilot.revision
            ):
                raise DomainError("VERSION_CONFLICT", "试产或结果版次已变化。")
            for ref in _references(pilot.details):
                facts.check_ref(authority.scope, ref, operation)
            for source in _sources(pilot.details):
                facts.source(authority.scope, source, operation)
            if (
                facts.verify_parameters(authority.scope, pilot.details.parameters, operation)
                != pilot.details.parameters
            ):
                raise DomainError("PARAMETER_SOURCE_MISMATCH", "固定参数与原来源不一致。")
            lot = self._lot(authority, pilot.details.basis)
            if (
                payload.scope.basis != pilot.details.basis
                or payload.scope.manufacturing_baseline != pilot.details.manufacturing_baseline
                or payload.scope.line != pilot.details.line
            ):
                raise DomainError("INCOMPATIBLE_SCOPE", "结果须固定试产实际批次/配置/工艺/线体。")
            if payload.scope.nature != lot.nature:
                raise DomainError("NATURE_MISMATCH", "合成/现实来源与原批次不一致。")
            if (
                payload.observed.occurred_at > authority.now
                or payload.scope.window_end > authority.now
            ):
                raise DomainError("FUTURE_OBSERVATION", "实际观察或统计窗口不得使用未来时间。", 422)
            if payload.previous_observation_id != pilot.latest_observation_id:
                raise DomainError("VERSION_CONFLICT", "必须从当前观察版追加修正，不覆盖历史。")
            counts = payload.counts or counts_from_units(payload)
            result = calculate(counts, payload.scope.minimum_sample)
            if counts.input_count is not None and counts.input_count > lot.observed_unit_count:
                raise DomainError("LOT_LIMIT", "统计投入超过已有实际批次范围。", 422)
            if pilot.latest_observation_id:
                previous = self._port("commands").observation(
                    authority.scope,
                    pilot.latest_observation_id,
                )
                if previous.pilot_id != pilot.id or previous.details.scope != payload.scope:
                    raise DomainError("FIXED_SCOPE_CHANGED", "修正不能改变分母范围/窗口/判据。")
                if (
                    previous.result.counts.input_count is not None
                    and previous.result.counts.input_count != counts.input_count
                ):
                    raise DomainError("FIXED_DENOMINATOR_CHANGED", "改变投入须建立独立新口径。")
                if previous.details.units and {u.sample for u in previous.details.units} != {
                    u.sample for u in payload.units
                }:
                    raise DomainError("FIXED_UNITS_CHANGED", "修正须保持相同实际单件范围。")
            verified_scope = facts.verify_result(authority.scope, pilot, payload)
            if verified_scope != payload.scope:
                raise DomainError("SOURCE_CHANGED", "结果范围/判据/样本阈值未获服务器原值核对。")
            preparation = facts.preparation(authority.scope, pilot.details)
            gaps = list(preparation.gaps)
            for warning in result.warnings:
                gaps.append(
                    Gap(code=warning, state="unknown", detail=warning, owner_role="production")
                )
        for ref in preparation.read_set:
            facts.check_ref(authority.scope, ref, operation)
        for source in preparation.sources:
            facts.source(authority.scope, source, operation)
        refs = (
            _references(payload)
            + (_references(pilot.details) if pilot else ())
            + preparation.read_set
        )
        # Preview binds whole original payload and locked current read-set/preparation gaps.
        body = {
            "payload": payload.model_dump(mode="json"),
            "scope": authority.scope.model_dump(mode="json"),
            "target": str(subject_id),
            "revision": expected_revision,
            "read_set": [r.model_dump(mode="json") for r in dict.fromkeys(refs)],
            "gaps": [g.model_dump(mode="json") for g in gaps],
            "preparation_sources": [s.model_dump(mode="json") for s in preparation.sources],
        }
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        return Preview(
            operation=operation,
            subject_id=subject_id,
            expected_revision=expected_revision,
            digest=digest,
            read_set=tuple(dict.fromkeys(refs)),
            gaps=tuple(gaps),
            summary="保存固定制造准备/不可变观察；不新增库存、不授权开工或放行。",
        ), pilot

    def _lot(self, authority, basis):
        lot = self._port("facts").lot(authority.scope, basis)
        if lot.scope != authority.scope or lot.basis != basis:
            raise DomainError("SOURCE_CHANGED", "实际批次/配置/单位与服务器原记录不一致。")
        if lot.observed_unit_count < 0:
            raise DomainError("INVALID_SERVER_FACT", "实际批次数量不有效。", 503)
        self._port("facts").source(authority.scope, lot.source, "manufacturing.lot")
        return lot

    def preview(self, operation: str, subject_id: UUID, expected_revision: int, payload) -> Preview:
        parsed = self._payload(operation, payload)
        authority = self._port("commands").context(operation, subject_id)
        self._authorize(authority)
        return self._inspect(authority, subject_id, operation, parsed, expected_revision)[0]

    def execute(self, invocation: Invocation, payload) -> Outcome:
        parsed = self._payload(invocation.operation, payload)
        if invocation.semantic_digest != semantic_digest(parsed):
            raise DomainError("INTENT_MISMATCH", "固定命令载荷摘要不一致。", 422)
        commands = self._port("commands")
        with commands.atomic():
            authority = commands.begin(invocation)
            if isinstance(authority, Outcome):
                # Port reauthorizes access without repeating revoked historical side effects.
                return authority
            self._authorize(authority)
            preview, pilot = self._inspect(
                authority,
                invocation.subject_id,
                invocation.operation,
                parsed,
                invocation.expected_revision,
            )
            commands.confirm(invocation, preview, authority)
            commands.recheck(authority, preview)
            if isinstance(parsed, ToolTrialCreate):
                trial = ToolTrial(
                    id=parsed.trial_id,
                    scope=authority.scope,
                    details=parsed,
                    readiness=readiness(preview.gaps),
                    writer_id=authority.actor_id,
                    received_at=authority.now,
                )
                mutation = Mutation(
                    before_revision=0,
                    trial=trial,
                    verification_intent=parsed.verification,
                    event="tooltrial.created",
                )
            elif isinstance(parsed, PilotCreate):
                created = PilotRun(
                    id=parsed.pilot_id,
                    scope=authority.scope,
                    details=parsed,
                    readiness=readiness(preview.gaps),
                    writer_id=authority.actor_id,
                    received_at=authority.now,
                )
                mutation = Mutation(before_revision=0, pilot=created, event="pilot.created")
            else:
                counts = parsed.counts or counts_from_units(parsed)
                observation = Observation(
                    id=parsed.observation_id,
                    pilot_id=pilot.id,
                    revision=pilot.revision,
                    details=parsed,
                    time=TimeFact(
                        **parsed.observed.model_dump(),
                        received_at=authority.now,
                        actor_id=authority.actor_id,
                    ),
                    result=calculate(counts, parsed.scope.minimum_sample),
                )
                next_pilot = PilotRun.model_validate(
                    {
                        **pilot.model_dump(),
                        "revision": pilot.revision + 1,
                        "latest_observation_id": observation.id,
                    }
                )
                mutation = Mutation(
                    before_revision=pilot.revision,
                    pilot=next_pilot,
                    observation=observation,
                    event="pilot.results_recorded",
                )
            return commands.record(invocation, mutation)
