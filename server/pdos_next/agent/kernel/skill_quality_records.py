"""Named spot checks of sampled T0 runs and frozen evaluation sets (P42, P109–P110).

Both are T1 records of the current human tenant administrator; neither grants or
restores a qualification. A critical spot check stops T0 for the current
qualification decision in the same transaction (P42); the hold itself is written
by the database from the recorded mark, never from caller-supplied facts.
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import func, select, text

from pdos_next.agent.model_configuration.commands import CurrentAdministrator
from pdos_next.agent.model_configuration.ports import ManagementContext
from pdos_next.core.models import now
from pdos_next.core.request_proof import command_inputs_once
from pdos_next.core.schema_base import StrictModel
from pdos_next.errors import DomainError

from .models import SkillEvalSet, SkillSpotCheck, TenantSkillEnablement
from .skills import SkillCatalog

CRITICAL_KINDS = {
    "scope": "越权，或写错项目、品类、受众",
    "fabrication": "编造来源、数值或人员职责",
    "override": "覆盖人工值，或修改已承接、已提交的任务",
    "red_line": "缺少红线成果的计划仍然生效",
    "commitment_baseline": "把计划日期写成承诺，或改变基线",
}
OUTCOMES = {"correct": "正确", "ordinary_error": "普通错误", "critical_error": "关键错误"}
SAMPLE_REASONS = {"hash_20_percent": "20% 抽样", "weekly_minimum": "每周至少 2 次补足"}


class RecordSpotCheck(StrictModel):
    skill_key: str = Field(min_length=1, max_length=160)
    run_id: UUID
    outcome: Literal["correct", "ordinary_error", "critical_error"]
    critical_kinds: list[
        Literal["scope", "fabrication", "override", "red_line", "commitment_baseline"]
    ] = Field(default_factory=list, max_length=5)
    note: str = Field(default="", max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def marked(self):
        if len(set(self.critical_kinds)) != len(self.critical_kinds):
            raise ValueError("关键错误类别不得重复。")
        if (self.outcome == "critical_error") != bool(self.critical_kinds):
            raise ValueError("关键错误须选择至少一类（P42 五类），其他结论不选类别。")
        if self.outcome != "correct" and not self.note.strip():
            raise ValueError("标注错误时请写明具体问题。")
        return self


class EvalCase(StrictModel):
    case_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    case_type: Literal["C", "D", "N", "M"]
    category_ref: str = Field(min_length=1, max_length=160)
    material_kind: Literal["own", "synthetic"]
    inputs: list[str] = Field(min_length=1, max_length=20)
    must_cover: list[str] = Field(default_factory=list, max_length=30)
    must_not: list[str] = Field(default_factory=list, max_length=30)
    keep_unknown: list[str] = Field(default_factory=list, max_length=30)
    traps: list[str] = Field(default_factory=list, max_length=20)
    key_points: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def bounded(self):
        for field in ("inputs", "must_cover", "must_not", "keep_unknown", "traps", "key_points"):
            values = getattr(self, field)
            if any(not value.strip() or len(value) > 1000 for value in values):
                raise ValueError("案例条目不能为空，且每条不超过 1000 字。")
        if not (self.must_cover or self.must_not or self.keep_unknown):
            raise ValueError("请至少写一条参考要点（必须覆盖、不得出现或应保持未知）。")
        return self


class RegisterEvalSet(StrictModel):
    skill_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    cases: list[EvalCase] = Field(min_length=1, max_length=60)
    reference_points_signed: Literal[True]
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def unique_cases(self):
        if not self.title.strip():
            raise ValueError("请填写评测集名称。")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("案例编号不得重复。")
        return self


@dataclass
class Prepared:
    review: dict
    row: TenantSkillEnablement | None = None
    version: int | None = None
    digest: str | None = None
    confirmation_id: UUID | None = None


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def cases_digest(cases):
    canonical = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _admin(session, ctx, command, scope):
    if command.product_id is not None or command.source_read_set:
        raise DomainError("FORBIDDEN_SCOPE", "资格记录只接受当前租户的技能配置。", 403)
    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前品类范围已变化，请刷新。")
    if not CurrentAdministrator(session, ctx).is_current_human_admin(
        ManagementContext(ctx.tenant_id, ctx.actor_id)
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "请由当前租户管理员本人办理。", 403)


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    from .skill_qualification import lock_skill

    _admin(session, ctx, command, scope)
    row = lock_skill(session, ctx, payload.skill_key)
    if isinstance(payload, RegisterEvalSet):
        skill = SkillCatalog().configuration(payload.skill_key)
        if not skill:
            raise DomainError("SOURCE_UNAVAILABLE", "技能包未登记。", 404)
        version = 1 + session.scalar(
            select(func.count())
            .select_from(SkillEvalSet)
            .where(
                SkillEvalSet.tenant_id == ctx.tenant_id,
                SkillEvalSet.skill_key == payload.skill_key,
            )
        )
        cases = [case.model_dump(mode="json") for case in payload.cases]
        digest = cases_digest(cases)
        return Prepared(
            {
                "skill_key": payload.skill_key,
                "skill_version": skill.version,
                "title": payload.title,
                "version": version,
                "case_count": len(cases),
                "case_types": dict(sorted(Counter(case["case_type"] for case in cases).items())),
                "material_kinds": dict(
                    sorted(Counter(case["material_kind"] for case in cases).items())
                ),
                "categories": sorted({case["category_ref"] for case in cases}),
                "cases_sha256": digest,
                "cases": cases,
                "effect": (
                    f"登记为第 {version} 版评测集并固定内容；之后不能修改，只能登记新版本。"
                    "登记不授予任何资格，AI 身份不能写入。"
                ),
            },
            row,
            version,
            digest,
        )
    if (
        not row
        or not row.qualification_id
        or not row.reviewed_at
        or row.qualification_revoked
    ):
        raise DomainError("QUALIFICATION_REQUIRED", "当前没有可抽检的自动执行资格。", 403)
    sampled = session.execute(
        text(
            "SELECT s.sampled,s.reason,s.first_at FROM kernel_skill_spot_check_sample("
            ":tenant,:skill,:skill_version,:model_version,:since,500) s WHERE s.run_id=:run"
        ),
        {
            "tenant": ctx.tenant_id,
            "skill": payload.skill_key,
            "skill_version": row.qualified_skill_version,
            "model_version": row.qualified_model_version,
            "since": row.reviewed_at,
            "run": payload.run_id,
        },
    ).one_or_none()
    if not sampled or not sampled.sampled:
        raise DomainError("VALIDATION_FAILED", "该运行不在当前资格的抽检样本中。", 422)
    if session.scalar(
        select(SkillSpotCheck.id).where(
            SkillSpotCheck.tenant_id == ctx.tenant_id,
            SkillSpotCheck.qualification_id == row.qualification_id,
            SkillSpotCheck.run_id == payload.run_id,
        )
    ):
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "该运行已在当前资格下标注。")
    critical = payload.outcome == "critical_error"
    return Prepared(
        {
            "skill_key": payload.skill_key,
            "skill_version": row.qualified_skill_version,
            "model_version": row.qualified_model_version,
            "run_id": str(payload.run_id),
            "run_first_at": sampled.first_at.isoformat(),
            "sample_reason": SAMPLE_REASONS.get(sampled.reason, sampled.reason),
            "outcome": payload.outcome,
            "outcome_label": OUTCOMES[payload.outcome],
            "critical_kinds": [CRITICAL_KINDS[kind] for kind in payload.critical_kinds],
            "note": payload.note,
            "effect": (
                "立即暂停该资格的自动执行，降回一次确认，并在技能资格页置顶；"
                "恢复须在此之后重新审阅，由 ai.skill.qualify 具名批准。"
                if critical
                else "计入人工修改率（P42）；不改变资格。"
                if payload.outcome == "ordinary_error"
                else "记录本次抽检结论；不改变资格。"
            ),
        },
        row,
    )


def validate(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload).review


def apply_validated(session, ctx, command, scope, payload, plan):
    receipt = uuid4()
    if isinstance(payload, RegisterEvalSet):
        cases = plan.review["cases"]
        result = SkillEvalSet(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            created_at=now(),
            registered_by=ctx.actor_id,
            skill_key=payload.skill_key,
            version=plan.version,
            title=payload.title.strip(),
            cases=cases,
            case_count=len(cases),
            cases_sha256=plan.digest,
            receipt_id=receipt,
        )
        result.action_result = {
            "skill_key": payload.skill_key,
            "version": plan.version,
            "case_count": len(cases),
            "cases_sha256": plan.digest,
        }
        subject = "skill_eval_set"
    else:
        row = plan.row
        result = SkillSpotCheck(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            created_at=now(),
            reviewed_by=ctx.actor_id,
            skill_key=payload.skill_key,
            qualification_id=row.qualification_id,
            skill_version=row.qualified_skill_version,
            model_version=row.qualified_model_version,
            run_id=payload.run_id,
            outcome=payload.outcome,
            critical_kinds=list(payload.critical_kinds),
            note=payload.note.strip(),
            receipt_id=receipt,
        )
        hold = None
        if payload.outcome == "critical_error":
            session.add(result)
            session.flush([result])
            hold = session.scalar(
                text(
                    "SELECT kernel_skill_quality_hold(CAST(:tenant AS uuid),"
                    "CAST(:skill AS varchar),'critical_spot_check',CAST(:spot AS uuid),"
                    "NULL::integer,NULL::numeric)"
                ),
                {"tenant": ctx.tenant_id, "skill": payload.skill_key, "spot": result.id},
            )
            if hold is None:
                raise DomainError("VERSION_CONFLICT", "资格已变化，请重新核对抽检。")
        result.action_result = {
            "skill_key": payload.skill_key,
            "run_id": str(payload.run_id),
            "outcome": payload.outcome,
            "hold_id": str(hold) if hold else None,
        }
        subject = "skill_spot_check"
    result.prepared_receipt_id, result.confirmation_id = receipt, plan.confirmation_id
    return result, subject, "private"
