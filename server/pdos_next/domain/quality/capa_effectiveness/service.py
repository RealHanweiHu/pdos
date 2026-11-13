"""T2 CAPA effectiveness decision on the canonical issue chain (P96 第 1–4 项, F47, D307).

A quality-role named person who did not carry out any CAPA action decides:
- effective: the issue closes in the same transaction (this decision is the
  independent verification the closing policy asks for);
- ineffective: the issue returns to "actioning" with root cause and CAPA
  cleared, so the existing root-cause and CAPA commands run a new round; the
  previous round stays in the immutable earlier issue versions;
- extend observation: the issue keeps waiting, with a later observation end.
Evidence is existing named review and observation records of this CAPA.
小Pai only prepares material; it never holds this decision.
"""

# ruff: noqa: E501 -- user-facing Chinese decision texts stay on one line.

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from pdos_next.core.models import now
from pdos_next.core.service import digest
from pdos_next.domain.named_records import service as records
from pdos_next.domain.projects.work.rules import require

from .schemas import OPERATION

EFFECTS = {
    "effective": "判定有效，同一事务关闭问题；关闭依据就是这次独立的有效性决定。",
    "ineffective": "判定无效，问题回到“措施中”；根因与 CAPA 清空，用现有的根因决定与 CAPA 起草重新办理，上一轮保留在历史版本里。",
    "extend_observation": "延长观察到新的截止日，问题仍待验证；到期后再决定。",
}
LABELS = {"effective": "有效", "ineffective": "无效", "extend_observation": "延长观察"}


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"approval_token"})


@dataclass
class Validated:
    row: object
    pointer: object
    issue: object
    evidence: list
    observation_end: str
    held: list
    review: dict


def _current(s, ctx, product_id, issue_id):
    from pdos_next.domain.quality.execution.models import QualityIssueCurrent, QualityIssueVersion
    from pdos_next.schemas.quality_issues.contracts import Issue

    pointer = s.scalar(
        select(QualityIssueCurrent)
        .where(
            QualityIssueCurrent.tenant_id == ctx.tenant_id,
            QualityIssueCurrent.product_id == product_id,
            QualityIssueCurrent.issue_id == issue_id,
        )
        .with_for_update()
    )
    require(pointer is not None, "问题不在当前可读范围。", "FORBIDDEN_SCOPE", 403)
    row = s.scalar(
        select(QualityIssueVersion).where(
            QualityIssueVersion.tenant_id == ctx.tenant_id,
            QualityIssueVersion.product_id == product_id,
            QualityIssueVersion.id == pointer.issue_version_id,
        )
    )
    require(
        row is not None and row.revision == pointer.issue_revision,
        "问题当前指针无法核对。",
        "INTEGRITY_MISMATCH",
    )
    issue = Issue.model_validate(row.issue_snapshot)
    require(
        digest(issue.model_dump(mode="json")) == row.snapshot_sha256,
        "问题版本摘要无法核对。",
        "INTEGRITY_MISMATCH",
    )
    return pointer, row, issue


def _observation_end(s, ctx, row, issue):
    """The requirement's end, moved only by earlier extend decisions on this issue."""
    from pdos_next.domain.quality.execution.models import QualityIssueVersion

    ends = [issue.capa.requirement.observation_until]
    for value in s.scalars(
        select(QualityIssueVersion.input_snapshot).where(
            QualityIssueVersion.tenant_id == ctx.tenant_id,
            QualityIssueVersion.product_id == row.product_id,
            QualityIssueVersion.issue_id == row.issue_id,
            QualityIssueVersion.operation == OPERATION,
        )
    ):
        if value.get("outcome") == "extend_observation" and value.get("capa_id") == str(
            issue.capa.id
        ):
            ends.append(datetime.fromisoformat(value["observation_until"]))
    return max(ends)


def action_executors(issue):
    """F47: the people who carried out this CAPA's actions may not decide its effectiveness."""
    return {str(action.executor_id) for action in issue.capa.actions}


def evidence(s, ctx, row, issue, refs, at):
    """Existing named reviews and current observations of this exact CAPA."""
    from pdos_next.domain.quality.capa.fact_storage_models import (
        NamedReviewRecord,
        ObservationCurrent,
        ObservationFact,
    )

    scope = {
        "tenant_id": ctx.tenant_id,
        "product_id": row.product_id,
        "project_id": row.project_id,
        "issue_id": issue.id,
        "capa_id": issue.capa.id,
    }
    out = []
    for ref in refs:
        if ref.kind == "review":
            fact = s.scalar(
                select(NamedReviewRecord).filter_by(**scope, id=ref.id, revision=ref.revision)
            )
            require(fact is not None, "具名复核不属于本 CAPA 或不可读。", "FORBIDDEN_SCOPE", 403)
            out.append(
                {
                    "kind": "review",
                    "id": str(fact.id),
                    "revision": fact.revision,
                    "actor_id": str(fact.reviewer_id),
                    "conclusion": (fact.fact_body or {}).get("conclusion"),
                    "current": fact.valid_until is None or fact.valid_until > at,
                }
            )
        else:
            fact = s.scalar(
                select(ObservationFact).filter_by(**scope, id=ref.id, revision=ref.revision)
            )
            require(fact is not None, "观察记录不属于本 CAPA 或不可读。", "FORBIDDEN_SCOPE", 403)
            pointer = s.scalar(
                select(ObservationCurrent).filter_by(**scope, series_id=fact.series_id)
            )
            out.append(
                {
                    "kind": "observation",
                    "id": str(fact.id),
                    "revision": fact.revision,
                    "actor_id": str(fact.executor_id),
                    "conclusion": None,
                    "current": pointer is not None and pointer.fact_id == fact.id,
                }
            )
    return out


def validate(s, ctx, command, product, payload):
    records.human_only(s, ctx)
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    at = now()
    pointer, row, issue = _current(s, ctx, product.id, payload.issue_id)
    require(
        issue.revision == payload.expected_issue_revision,
        "问题已有新版本，请核对后重试。",
        "VERSION_CONFLICT",
    )
    require(
        issue.status == "awaiting_verification"
        and issue.capa is not None
        and issue.root_cause is not None
        and issue.merged_into is None
        and all(action.completion is not None for action in issue.capa.actions),
        "只有措施全部完成、待验证的问题才能判定有效性。",
        "VALIDATION_FAILED",
    )
    executors = action_executors(issue)
    require(
        str(ctx.requester_id) not in executors,
        "措施实施人不能判定自己措施的有效性。",
        "INDEPENDENT_REVIEWER_REQUIRED",
        403,
    )
    held = records.require_role(
        s, ctx, product.id, row.project_id, OPERATION, row.purpose, {"quality"}, at
    )
    found = evidence(s, ctx, row, issue, payload.evidence, at)
    require(
        all(item["current"] for item in found), "引用的复核已过期或观察已有新版本。", "SOURCE_STALE"
    )
    end = _observation_end(s, ctx, row, issue)
    if payload.outcome == "effective":
        require(at >= end, "观察期尚未结束，不能判定有效；可选择延长观察。", "VALIDATION_FAILED")
        require(
            any(
                item["kind"] == "review"
                and item["conclusion"] == "applicable"
                and item["actor_id"] not in executors
                for item in found
            ),
            "判定有效须有独立的具名复核，且结论为适用。",
            "MISSING_REQUIRED_EVIDENCE",
        )
    if payload.outcome == "extend_observation":
        require(
            payload.observation_until > max(end, at),
            "新的观察截止日须晚于当前截止日和现在。",
            "VALIDATION_FAILED",
        )
    after_end = (
        payload.observation_until.isoformat() if payload.observation_until else end.isoformat()
    )
    review = {
        "operation": OPERATION,
        "issue": {"id": str(issue.id), "revision": issue.revision, "title": issue.title},
        "capa_id": str(issue.capa.id),
        "outcome": payload.outcome,
        "status_after": {
            "effective": "closed",
            "ineffective": "actioning",
            "extend_observation": "awaiting_verification",
        }[payload.outcome],
        "observation": {"before": end.isoformat(), "after": after_end},
        "evidence": found,
        "roles": held,
        "effect": EFFECTS[payload.outcome],
    }
    return Validated(row, pointer, issue, found, after_end, held, review)


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload).review


def _after(issue, payload, ctx, command, value, at):
    from pdos_next.schemas.quality_issues.contracts import (
        EffectivenessDecision,
        History,
        Issue,
        NamedConclusion,
        Ref,
    )
    from pdos_next.schemas.verification.contracts import SourceRef

    sources = tuple(
        SourceRef(
            id=item["id"],
            revision=item["revision"],
            kind="domain",
            position=f"capa-{item['kind']}:{item['id']}",
        )
        for item in value.evidence
    ) or (
        SourceRef(
            id=value.row.id, revision=value.row.revision, kind="domain", position="quality-issue"
        ),
    )
    note = f"CAPA 有效性判定：{LABELS[payload.outcome]}。{payload.text}"
    if payload.outcome == "extend_observation":
        note += f"（观察延长至 {value.observation_end}）"
    if payload.outcome == "ineffective":
        note += f"（上一轮根因与 CAPA 保留在第 {issue.revision} 版）"
    data = issue.model_dump(mode="json")
    data["revision"] = issue.revision + 1
    data["history"] = [
        *data["history"],
        History(
            command_id=command.command_id,
            operation=OPERATION,
            actor_id=ctx.requester_id,
            actor_kind="human",
            at=at,
            note=note[:4000],
        ).model_dump(mode="json"),
    ]
    if payload.outcome in {"effective", "ineffective"}:
        decision = EffectivenessDecision(
            text=payload.text,
            actor_id=ctx.requester_id,
            sources=sources,
            at=at,
            result=payload.outcome,
            evidence_ids=tuple(item["id"] for item in value.evidence),
            policy=Ref(id=issue.id, revision=issue.revision),
            read_digest=digest(value.evidence),
        ).model_dump(mode="json")
    if payload.outcome == "effective":
        data["status"] = "closed"
        data["capa"]["effectiveness"] = decision
        data["capa"]["effectiveness_history"] = [*data["capa"]["effectiveness_history"], decision]
        data["closure"] = NamedConclusion(
            text=payload.text, actor_id=ctx.requester_id, sources=sources, at=at
        ).model_dump(mode="json")
    elif payload.outcome == "ineffective":
        data["status"] = "actioning"
        data["root_cause"] = None
        data["capa"] = None
    return Issue.model_validate(data)


def apply_validated(s, ctx, command, product, payload, value):
    from pdos_next.domain.quality.execution.models import QualityIssueVersion

    at = now()
    before = value.row
    after = _after(value.issue, payload, ctx, command, value, at)
    raw = after.model_dump(mode="json")
    entered = semantic(payload)
    entered["capa_id"] = str(value.issue.capa.id)
    if payload.outcome == "extend_observation":
        entered["observation_until"] = value.observation_end
    row = QualityIssueVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=before.project_id,
        issue_id=before.issue_id,
        revision=after.revision,
        previous_issue_version_id=before.id,
        previous_revision=before.revision,
        owner_id=before.owner_id,
        writer_id=ctx.requester_id,
        visibility=before.visibility,
        purpose=before.purpose,
        status=after.status,
        operation=OPERATION,
        issue_snapshot=raw,
        snapshot_sha256=digest(raw),
        input_snapshot=entered,
        authority_snapshot={
            "operation": OPERATION,
            "roles": value.held,
            "actor_id": str(ctx.requester_id),
        },
        policy_snapshot=None,
        sources=deepcopy(before.sources),
        required_source_read_set=deepcopy(before.required_source_read_set),
        # Keep the issue's original basis intact for later follow-up rechecks.
        source_basis={
            **deepcopy(before.source_basis),
            "effectiveness": {"evidence": value.evidence, "observation_end": value.observation_end},
        },
        intent_digest=digest(
            {
                "operation": OPERATION,
                "actor": str(ctx.requester_id),
                "product": str(product.id),
                "payload": entered,
            }
        ),
        reason=payload.text,
    )
    s.add(row)
    s.flush()
    value.pointer.issue_version_id, value.pointer.issue_revision, value.pointer.epoch = (
        row.id,
        row.revision,
        value.pointer.epoch + 1,
    )
    row.action_result = {
        "issue_id": str(row.issue_id),
        "outcome": payload.outcome,
        "status": row.status,
        "observation_until": value.observation_end,
    }
    return row, "quality_issue", row.visibility


def waiting(s, ctx, product_id, project_id):
    """Issues of a project that await an effectiveness decision, with pickable evidence."""
    from pdos_next.domain.quality.capa.fact_storage_models import (
        NamedReviewRecord,
        ObservationCurrent,
        ObservationFact,
    )
    from pdos_next.domain.quality.execution.models import QualityIssueCurrent, QualityIssueVersion
    from pdos_next.schemas.quality_issues.contracts import Issue

    records.project(s, ctx, product_id, project_id)
    rows = s.scalars(
        select(QualityIssueVersion)
        .join(
            QualityIssueCurrent,
            (QualityIssueCurrent.tenant_id == QualityIssueVersion.tenant_id)
            & (QualityIssueCurrent.issue_version_id == QualityIssueVersion.id),
        )
        .where(
            QualityIssueVersion.tenant_id == ctx.tenant_id,
            QualityIssueVersion.product_id == product_id,
            QualityIssueVersion.project_id == project_id,
            QualityIssueVersion.status == "awaiting_verification",
        )
        .order_by(QualityIssueVersion.created_at.desc())
        .limit(50)
    ).all()
    at = now()
    out = []
    for row in rows:
        issue = Issue.model_validate(row.issue_snapshot)
        if issue.capa is None:
            continue
        scope = {
            "tenant_id": ctx.tenant_id,
            "product_id": product_id,
            "project_id": project_id,
            "issue_id": issue.id,
            "capa_id": issue.capa.id,
        }
        reviews = s.scalars(
            select(NamedReviewRecord)
            .filter_by(**scope)
            .order_by(NamedReviewRecord.created_at.desc())
            .limit(20)
        ).all()
        observations = s.scalars(
            select(ObservationFact)
            .join(
                ObservationCurrent,
                (ObservationCurrent.tenant_id == ObservationFact.tenant_id)
                & (ObservationCurrent.fact_id == ObservationFact.id),
            )
            .where(*(getattr(ObservationFact, key) == value for key, value in scope.items()))
            .limit(20)
        ).all()
        out.append(
            {
                "issue_id": str(issue.id),
                "revision": issue.revision,
                "title": issue.title,
                "capa_id": str(issue.capa.id),
                "observation_until": _observation_end(s, ctx, row, issue).isoformat(),
                "executors": sorted(action_executors(issue)),
                "reviews": [
                    {
                        "id": str(r.id),
                        "revision": r.revision,
                        "reviewer_id": str(r.reviewer_id),
                        "conclusion": (r.fact_body or {}).get("conclusion"),
                        "current": r.valid_until is None or r.valid_until > at,
                    }
                    for r in reviews
                ],
                "observations": [
                    {
                        "id": str(o.id),
                        "revision": o.revision,
                        "executor_id": str(o.executor_id),
                        "observed_until": o.observed_until.isoformat(),
                    }
                    for o in observations
                ],
            }
        )
    return {"project_id": str(project_id), "items": out}
