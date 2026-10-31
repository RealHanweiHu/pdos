"""Issue creation and CAPA observation dates from native immutable Issue facts.

No inferred issue owner, action deadline, verification signer or severity is
introduced. Every row is an ordinary owner READ with its fixed native version.
"""

from sqlalchemy import DateTime, and_, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.orm import load_only

from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.quality_execution.service import _snapshot
from pdos_next.personal_summary import LIMIT, _categories, _item, _time, _url
from pdos_next.personal_summary_schemas import Coverage, NextStep, ObjectRef, Person, Relationship
from pdos_next.personal_summary_templates import duties


def assigned(ctx):
    return func.jsonb_path_exists(
        QualityIssueVersion.issue_snapshot,
        cast(
            literal("$.capa.actions[*] ? (@.executor_id == $person && @.completion == null)"),
            JSONPATH,
        ),
        func.jsonb_build_object("person", str(ctx.requester_id)),
    )


def quality_duty(ctx, at):
    from pdos_next.domain.professional_authority.models import ProfessionalFact as Fact

    f = (
        duties(ctx, at)
        .with_only_columns(
            Fact.id,
            Fact.tenant_id,
            Fact.category_id,
            Fact.product_id,
            Fact.project_id,
            Fact.role,
        )
        .subquery("summary_quality_current_duties")
    )
    v = QualityIssueVersion
    return (
        select(f.c.id)
        .where(
            f.c.tenant_id == v.tenant_id,
            f.c.category_id == v.category_id,
            f.c.product_id == v.product_id,
            f.c.project_id == v.project_id,
            f.c.role == "quality",
        )
        .exists()
    )


def query(ctx, selection, at, kind, *, product_id=None):
    v, c = QualityIssueVersion, QualityIssueCurrent
    keys = ("tenant_id", "category_id", "product_id", "project_id", "issue_id")
    duty = quality_duty(ctx, at)
    following = or_(v.project_id.in_(selection.followed_project_ids), duty)
    mine = assigned(ctx)
    base = (
        select(v, duty.label("quality_duty"))
        .join(
            c,
            and_(
                *(getattr(v, key) == getattr(c, key) for key in keys),
                v.id == c.issue_version_id,
                v.revision == c.issue_revision,
            ),
        )
        .where(
            v.tenant_id == ctx.tenant_id,
        or_(v.visibility != "private", v.owner_id == ctx.requester_id),
            v.issue_snapshot["merged_into"].astext.is_(None),
            v.issue_snapshot["closure"].astext.is_(None),
            v.status != "closed",
        )
    )
    if kind == "quality_issue_opened":
        base = base.where(or_(following, mine))
    else:
        until = v.issue_snapshot["capa"]["requirement"]["observation_until"].astext
        base = base.where(
            cast(until, DateTime(timezone=True)) <= at,
            or_(
                v.issue_snapshot["capa"]["effectiveness"].astext.is_(None),
                v.issue_snapshot["capa"]["effectiveness"]["result"].astext != "effective",
            ),
            or_(
                mine if "action" in selection.groups else literal(False),
                following if "following" in selection.groups else literal(False),
            ),
        )
    return _categories(base, v.category_id, selection, product=v.product_id, product_id=product_id)


def relationship(row, issue, ctx, has_duty):
    if issue.capa and any(
        a.executor_id == ctx.requester_id and a.completion is None for a in issue.capa.actions
    ):
        return Relationship(
            kind="named_capa_executor", text="原 CAPA 有具名指定给你、尚未登记完成的措施。"
        )
    if has_duty:
        return Relationship(
            kind="current_quality_duty",
            text=("你在该固定项目有当前有效的品质职责；这不指定本问题的下一办理人。"),
        )
    return Relationship(kind="subscriber", text="这是你显式选择关注项目中的问题。")


def items(row, has_duty, ctx, at, kind, selection):
    issue = _snapshot(row)
    if issue.merged_into or issue.closure or issue.status == "closed":
        return []
    link = relationship(row, issue, ctx, has_duty)
    source = ObjectRef(
        kind="quality_issue",
        id=row.issue_id,
        version_id=row.id,
        revision=row.revision,
        category_id=row.category_id,
        product_id=row.product_id,
        project_id=row.project_id,
    )
    opened = next((h for h in issue.history if h.operation == "quality.issue.create"), None)
    facts = {
        "issue_status_as_recorded": issue.status,
        "risk_as_recorded": issue.risk,
        "opened_at_as_recorded": opened.at.isoformat() if opened else None,
        "needs_recheck_as_recorded": issue.needs_recheck,
        "recheck_reasons_as_recorded": list(issue.recheck_reasons),
    }
    if kind == "quality_issue_opened":
        return [
            _item(
                identity="quality_issue_opened:" + str(issue.id),
                kind=kind,
                group="following",
                title="开放问题 · " + issue.title,
                source=source,
                recorded_at=row.created_at,
                state=issue.status,
                relationship=link,
                next_step=NextStep(
                    kind="navigation",
                    text=("在原问题核对分诊、措施与当前状态；问题办理负责人未单独登记。"),
                ),
                url=_url(row.category_id, row.project_id),
                facts=facts,
            )
        ]
    capa = issue.capa
    if (
        not capa
        or _time(capa.requirement.observation_until) > _time(at)
        or capa.effectiveness
        and capa.effectiveness.result == "effective"
    ):
        return []
    pending = [
        a for a in capa.actions if a.executor_id == ctx.requester_id and a.completion is None
    ]
    group = "action" if pending and "action" in selection.groups else "following"
    return [
        _item(
            identity="capa_observation_due:" + str(capa.id),
            kind=kind,
            group=group,
            title="CAPA 观察期已到 · " + issue.title,
            source=source,
            recorded_at=row.created_at,
            state="observation_period_reached",
            relationship=link,
            next_step=NextStep(
                kind="navigation",
                responsible=Person(id=ctx.requester_id) if pending else None,
                text=(
                    "核对原 CAPA 尚未登记完成的本人措施："
                    + "；".join(a.text for a in pending)
                    + "。观察截止不是措施完成期限，有效性仍须原具名流程核对。"
                )
                if pending
                else (
                    "在原 CAPA 核对有效性与后续安排；观察期到达不代表有效、关闭或措施逾期，"
                    "复核责任人未单独登记。"
                ),
            ),
            url=_url(row.category_id, row.project_id),
            facts={
                **facts,
                "capa_id": str(capa.id),
                "observation_until_as_recorded": capa.requirement.observation_until.isoformat(),
                "date_kind": "effectiveness_observation_end",
                "action_due_at_as_recorded": None,
                "pending_own_actions": [a.model_dump(mode="json") for a in pending],
                "effectiveness_as_recorded": capa.effectiveness.result
                if capa.effectiveness
                else None,
            },
        )
    ]


def read(s, ctx, selection, at, *, product_id=None):
    rows, coverage = [], []
    v = QualityIssueVersion
    for kind in ("quality_issue_opened", "capa_observation_due"):
        if kind in selection.excluded_kinds or not set(selection.groups) & (
            {"following"} if kind == "quality_issue_opened" else {"action", "following"}
        ):
            continue
        base = query(ctx, selection, at, kind, product_id=product_id)
        total = s.scalar(select(func.count()).select_from(base.with_only_columns(v.id).subquery()))
        found = s.execute(
            base.options(
                load_only(
                    v.id,
                    v.tenant_id,
                    v.category_id,
                    v.product_id,
                    v.project_id,
                    v.issue_id,
                    v.revision,
                    v.status,
                    v.issue_snapshot,
                    v.snapshot_sha256,
                    v.created_at,
                )
            )
            .order_by(v.created_at.desc(), v.id.desc())
            .limit(LIMIT + 1)
        ).all()
        mapped = [
            item
            for row, duty in found[:LIMIT]
            for item in items(row, duty, ctx, at, kind, selection)
        ]
        rows.extend(mapped)
        coverage.append(
            Coverage(
                source=kind, returned=len(mapped), available=total, has_more=len(found) > LIMIT
            )
        )
    return rows, coverage
