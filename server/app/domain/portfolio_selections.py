"""Named project consent to a fixed portfolio selection before execution preparation."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Key, Text
from app.db.schema import tables
from app.domain.baseline_changes import latest_baseline, latest_policy
from app.domain.cost_backtests import source_state
from app.domain.cost_definition_feedback import cost_access
from app.domain.cost_freezes import row as cost_row
from app.domain.document_previews import DocumentPreviewMissing, document_row, metadata
from app.domain.portfolio_comparisons import active, readable, record
from app.domain.portfolio_scoring import PortfolioComparison, PortfolioPolicy
from app.domain.portfolio_sources import capture
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project
from app.domain.resource_schedule_preparations import current_solver, get_schedule


class SelectionImpact(Contract):
    project_id: UUID
    reason: Text


class PortfolioSelectionDraft(Contract):
    request_id: UUID
    comparison_id: UUID
    expected_comparison_digest: Digest
    alternative_key: Key
    reason: Text
    impacts: list[SelectionImpact] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({p.project_id for p in self.impacts}) != len(self.impacts):
            raise ValueError("项目影响说明不能重复")
        return self


class PortfolioSelectionSave(PortfolioSelectionDraft):
    expected_digest: Digest


class PortfolioSelectionDecision(Contract):
    request_id: UUID
    selection_id: UUID
    project_id: UUID
    expected_digest: Digest
    action: Literal["approve", "reject", "withdraw"]
    reason: Text


def comparison(c: Connection, context: AuthContext, identity: UUID) -> Any:
    t = tables.portfolio_comparisons
    value = (
        c.execute(select(t).where(t.c.tenant_id == context.tenant.id, t.c.id == identity))
        .mappings()
        .one_or_none()
    )
    if value is None:
        raise ProductWorkAccessError("组合比较不存在或不可读取")
    return value


def selection(c: Connection, context: AuthContext, identity: UUID, *, lock: bool = False) -> Any:
    t = tables.portfolio_selections
    query = select(t).where(t.c.tenant_id == context.tenant.id, t.c.id == identity)
    value = c.execute(query.with_for_update() if lock else query).mappings().one_or_none()
    if value is None:
        raise ProductWorkAccessError("组合申请不存在或不可读取")
    return value


def parts(c: Connection, context: AuthContext, identity: UUID) -> list[Any]:
    t = tables.portfolio_selection_projects
    return list(
        c.execute(
            select(t)
            .where(t.c.tenant_id == context.tenant.id, t.c.selection_id == identity)
            .order_by(t.c.project_id)
        ).mappings()
    )


def decisions(c: Connection, context: AuthContext, identity: UUID) -> list[Any]:
    t = tables.portfolio_selection_decisions
    return list(
        c.execute(
            select(t)
            .where(t.c.tenant_id == context.tenant.id, t.c.selection_id == identity)
            .order_by(t.c.created_at, t.c.id)
        ).mappings()
    )


def state(values: list[Any], count: int) -> str:
    if any(v["action"] == "withdraw" for v in values):
        return "withdrawn"
    if any(v["action"] == "reject" for v in values):
        return "rejected"
    return (
        "approved_for_preparation"
        if sum(v["action"] == "approve" for v in values) == count
        else "pending"
    )


def recheck_comparison(c: Connection, context: AuthContext, saved: Any) -> None:
    readable(c, context, saved["inputs"])
    policy = active(c, context, saved["policy_id"])
    current = capture(
        c,
        context,
        PortfolioComparison.model_validate(saved["inputs"]),
        policy,
        require_recent_request=False,
    )
    active(c, context, saved["policy_id"])
    if current["payload_digest"] != saved["payload_digest"]:
        raise ProductWorkError("原比较的项目、政策或来源状态已变化，请重算比较后重新提出")


def prepare(
    c: Connection, context: AuthContext, command: PortfolioSelectionDraft
) -> dict[str, Any]:
    saved = comparison(c, context, command.comparison_id)
    readable(c, context, saved["inputs"])
    if saved["payload_digest"] != command.expected_comparison_digest:
        raise ProductWorkError("所选比较版本与审阅版本不同")
    expected = {UUID(p["project_id"]) for p in saved["inputs"]["projects"]}
    if {p.project_id for p in command.impacts} != expected:
        raise ProductWorkError("须逐项说明本次比较全部项目的拟采用影响")
    candidates = saved["snapshot"]["result"]["alternatives"]
    chosen = next((v for v in candidates if v["key"] == command.alternative_key), None)
    reference = next(v for v in candidates if v["key"] == saved["inputs"]["reference_key"])
    if chosen is None or chosen["score"] is None or chosen["blockers"]:
        raise ProductWorkError("只能提出原比较中可行且数据足够评分的方案")
    for project in sorted(expected, key=str):
        _project(c, context, project, write=True)
    recheck_comparison(c, context, saved)
    values = []
    for item in sorted(command.impacts, key=lambda v: str(v.project_id)):
        project = _project(c, context, item.project_id)
        if project["status"] not in ("approved", "active"):
            raise ProductWorkError("拟采用项目须处于已批准或进行中状态")
        baseline = latest_baseline(c, context.tenant.id, item.project_id)
        policy = latest_policy(c, context.tenant.id, item.project_id)
        if policy is None:
            raise ProductWorkError("请先在每个项目明确具名基线批准政策，再提出组合采用申请")
        person = _person(c, context, item.project_id, policy["approver_user_id"])
        if policy["four_eyes"] and context.user.id == person["id"]:
            raise ProductWorkError("项目政策要求提交人与批准人分开，请由独立提交人提出")
        own = next(v for v in chosen["projects"] if v["project_id"] == str(item.project_id))
        ref = next(v for v in reference["projects"] if v["project_id"] == str(item.project_id))
        difference = next(
            v for v in chosen["project_differences"] if v["project_id"] == str(item.project_id)
        )
        values.append(
            {
                "project_id": str(item.project_id),
                "project_name": project["name"],
                "policy_id": str(policy["id"]),
                "policy_version": policy["version"],
                "baseline_id": str(baseline["id"]),
                "approver_user_id": str(person["id"]),
                "approver_name": person["display_name"],
                "four_eyes": policy["four_eyes"],
                "authority_basis": policy["authority_basis"],
                "reason": item.reason,
                "selected": own,
                "reference": ref,
                "difference": difference,
                "calendar": saved["snapshot"]["calendars"][str(item.project_id)],
                "scoring_policy": saved["snapshot"]["policy"],
            }
        )
    snapshot = {
        "inputs": command.model_dump(mode="json"),
        "comparison_digest": saved["payload_digest"],
        "alternative_key": chosen["key"],
        "alternative_title": chosen["title"],
        "strategy": chosen["strategy"],
        "score": chosen["score"],
        "rank": chosen["rank"],
        "parts": values,
        "approval_scope": "portfolio_selection_only",
        "applied": False,
        "baseline_changed": False,
        "reservations_changed": False,
    }
    return {"snapshot": snapshot, "payload_digest": digest(snapshot)}


def check_own(c: Connection, context: AuthContext, saved: Any, part: Any) -> None:
    project = _project(c, context, part["project_id"], write=True)
    cost_access(c, context, part["project_id"])
    if project["status"] not in ("approved", "active"):
        raise ProductWorkError("项目状态已变化，请重新提出")
    policy = latest_policy(c, context.tenant.id, part["project_id"])
    if policy is None or policy["id"] != part["policy_id"]:
        raise ProductWorkError("本项目批准政策已变化，请重新提出")
    if latest_baseline(c, context.tenant.id, part["project_id"])["id"] != part["baseline_id"]:
        raise ProductWorkError("本项目基线已变化，请重算比较后重新提出")
    _person(c, context, part["project_id"], part["approver_user_id"])
    c.execute(select(func.cehub_project.lock_resource_inventory(context.tenant.id)))
    original = comparison(c, context, saved["comparison_id"])
    scoring = PortfolioPolicy.model_validate(active(c, context, original["policy_id"])["body"])
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    # Scope-specific approval never grants access to the other projects' source data.
    for source in (part["snapshot"]["selected"], part["snapshot"]["reference"]):
        schedule = get_schedule(c, context, part["project_id"], UUID(source["schedule_id"]))
        current_solver(c, context, part["project_id"], schedule)

        when = datetime.fromisoformat(source["schedule_as_of"])
        if (
            when > now
            or Decimal(str((now - when).total_seconds())) / 3600 > scoring.max_source_age_hours
        ):
            raise ProductWorkError("资源日期超出评分政策允许账龄，请重算比较")
        if source["cost"] is not None:
            original_cost = cost_row(
                c,
                context.tenant.id,
                part["project_id"],
                tables.cost_rollups,
                UUID(source["cost"]["id"]),
            )
            if not source_state(c, context.tenant.id, part["project_id"], original_cost)["current"]:
                raise ProductWorkError("本项目成本依据已变化，请重新计算")
            oldest = (
                now - timedelta(microseconds=int(scoring.max_source_age_hours * 3600000000))
            ).date()
            if not oldest <= date.fromisoformat(original_cost["command"]["as_of"]) <= now.date():
                raise ProductWorkError("本项目成本计价日超出政策允许账龄，请重新计算")
            if any(
                p["payload"].get("stage") == "quote"
                and not date.fromisoformat(p["payload"]["valid_from"])
                <= now.date()
                <= date.fromisoformat(p["payload"]["valid_until"])
                for p in original_cost["snapshot"]["inputs"]
            ):
                raise ProductWorkError("本项目引用的报价未生效或已过期")
        evidence = source["quality_evidence"]
        if evidence is not None:
            try:
                current = metadata(
                    document_row(c, context.tenant.id, part["project_id"], UUID(evidence["id"]))
                )
            except DocumentPreviewMissing as error:
                raise ProductWorkError(str(error)) from error
            if digest(current) != digest(evidence):
                raise ProductWorkError("本项目质量依据原件已变化，请重新核对")


class PortfolioSelectionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(self, context: AuthContext, command: PortfolioSelectionDraft) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        with self.engine.begin() as c:
            return prepare(c, context, command)

    def submit(self, context: AuthContext, command: PortfolioSelectionSave) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        try:
            with self.engine.begin() as c:
                t = tables.portfolio_selections
                signature = digest(command.model_dump(mode="json"))
                previous = (
                    c.execute(
                        select(t).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.created_by_user_id == context.user.id,
                            t.c.request_id == command.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if previous:
                    readable(
                        c, context, comparison(c, context, previous["comparison_id"])["inputs"]
                    )
                    if previous["request_digest"] != signature:
                        raise ProductWorkError("请求编号已用于另一份组合申请")
                    return {"id": str(previous["id"])}
                draft = PortfolioSelectionDraft.model_validate(
                    command.model_dump(exclude={"expected_digest"})
                )
                value = prepare(c, context, draft)
                if value["payload_digest"] != command.expected_digest:
                    raise ProductWorkError("申请依据或具名批准政策已变化，请重新预览")
                identity = uuid4()
                c.execute(
                    t.insert().values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        comparison_id=command.comparison_id,
                        alternative_key=command.alternative_key,
                        reason=command.reason,
                        inputs=draft.model_dump(mode="json"),
                        snapshot=value["snapshot"],
                        payload_digest=value["payload_digest"],
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                )
                for part in value["snapshot"]["parts"]:
                    project = UUID(part["project_id"])
                    c.execute(
                        tables.portfolio_selection_projects.insert().values(
                            tenant_id=context.tenant.id,
                            selection_id=identity,
                            project_id=project,
                            policy_id=UUID(part["policy_id"]),
                            baseline_id=UUID(part["baseline_id"]),
                            approver_user_id=UUID(part["approver_user_id"]),
                            snapshot=part,
                        )
                    )
                    record(
                        c,
                        context,
                        identity,
                        "selection_submitted",
                        {
                            "selection_id": str(identity),
                            "payload_digest": value["payload_digest"],
                            "project_impact": part,
                        },
                        project,
                    )
                return {"id": str(identity)}
        except IntegrityError as error:
            raise ProductWorkError("此比较方案已有申请，或提交状态已变化；请刷新原申请") from error

    def list(
        self,
        context: AuthContext,
        project: UUID,
        *,
        before: UUID | None = None,
        identity: UUID | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            _project(c, context, project)
            cost_access(c, context, project)
            t, p = tables.portfolio_selections, tables.portfolio_selection_projects
            query = (
                select(t)
                .join(p, (p.c.tenant_id == t.c.tenant_id) & (p.c.selection_id == t.c.id))
                .where(t.c.tenant_id == context.tenant.id, p.c.project_id == project)
            )
            if identity:
                query = query.where(t.c.id == identity)
            if before:
                cursor = c.execute(query.where(t.c.id == before)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("历史游标不属于本项目")
                query = query.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            found = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            if identity and not found:
                raise ProductWorkAccessError("组合申请不属于本项目")
            values = []
            policy = latest_policy(c, context.tenant.id, project)
            for saved in found[:20]:
                participants = parts(c, context, saved["id"])
                own = next(v for v in participants if v["project_id"] == project)
                actions = decisions(c, context, saved["id"])
                status = state(actions, len(participants))
                own_actions = [
                    v for v in actions if v["project_id"] == project or v["action"] == "withdraw"
                ]
                all_visible = True
                try:
                    readable(c, context, comparison(c, context, saved["comparison_id"])["inputs"])
                except (ProductWorkAccessError, PermissionError):
                    all_visible = False
                from app.domain.portfolio_execution_preparations import existing

                package = existing(c, context.tenant.id, saved["id"])
                from app.domain.portfolio_applications import (
                    existing as applied_existing,
                )
                from app.domain.portfolio_applications import (
                    receipt as applied_receipt,
                )

                applied = applied_existing(c, context.tenant.id, saved["id"])
                execution = None
                if package is not None:
                    execution = {
                        "id": str(package["id"]),
                        "created_at": package["created_at"].isoformat(),
                        "actor_user_id": str(package["actor_user_id"]),
                        "items": [
                            v
                            for v in package["receipt"]["items"]
                            if all_visible or v["project_id"] == str(project)
                        ],
                    }
                values.append(
                    {
                        "id": str(saved["id"]),
                        "comparison_id": str(saved["comparison_id"]),
                        "created_at": saved["created_at"].isoformat(),
                        "created_by_user_id": str(saved["created_by_user_id"]),
                        "payload_digest": saved["payload_digest"],
                        "application": applied_receipt(
                            c, applied, project=None if all_visible else project
                        )
                        if applied
                        else None,
                        "status": "applied"
                        if applied
                        else "execution_prepared"
                        if package is not None and status == "approved_for_preparation"
                        else status,
                        "execution": execution,
                        "can_preview_application": applied is None
                        and package is not None
                        and status == "approved_for_preparation"
                        and all_visible
                        and is_allowed(context.user.role, Action.TENANT_MANAGE),
                        "can_prepare_execution": package is None
                        and status == "approved_for_preparation"
                        and all_visible
                        and is_allowed(context.user.role, Action.PROJECT_EDIT),
                        "project_count": len(participants),
                        "approved_count": sum(a["action"] == "approve" for a in actions),
                        "part": _plain(own),
                        "decisions": [_plain(v) for v in own_actions],
                        "all_parts": [_plain(v) for v in participants] if all_visible else None,
                        "selection": _plain(saved) if all_visible else None,
                        "can_decide": status == "pending"
                        and not any(v["project_id"] == project for v in actions)
                        and own["approver_user_id"] == context.user.id
                        and policy is not None
                        and policy["id"] == own["policy_id"]
                        and not (
                            policy["four_eyes"] and saved["created_by_user_id"] == context.user.id
                        ),
                        "can_withdraw": applied is None
                        and status in ("pending", "approved_for_preparation")
                        and saved["created_by_user_id"] == context.user.id,
                    }
                )
            return {"items": values, "next": str(found[19]["id"]) if len(found) > 20 else None}

    def decide(self, context: AuthContext, command: PortfolioSelectionDecision) -> dict[str, Any]:
        try:
            with self.engine.begin() as c:
                _project(c, context, command.project_id, write=True)
                cost_access(c, context, command.project_id)
                saved = selection(c, context, command.selection_id, lock=True)
                participants = parts(c, context, saved["id"])
                own = next((v for v in participants if v["project_id"] == command.project_id), None)
                if own is None:
                    raise ProductWorkAccessError("组合申请不属于本项目")
                t = tables.portfolio_selection_decisions
                signature = digest(command.model_dump(mode="json"))
                prior = (
                    c.execute(
                        select(t).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.actor_user_id == context.user.id,
                            t.c.request_id == command.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior:
                    if prior["request_digest"] != signature:
                        raise ProductWorkError("请求编号已用于另一项裁决")
                    return _plain(prior)
                from app.domain.portfolio_applications import existing as applied_existing

                if applied_existing(c, context.tenant.id, saved["id"]):
                    raise ProductWorkError("组合已实际应用，请沿正式变更流程调整；不能撤回原申请")
                values = decisions(c, context, saved["id"])
                status = state(values, len(participants))
                if (
                    status in ("rejected", "withdrawn")
                    or saved["payload_digest"] != command.expected_digest
                ):
                    raise ProductWorkError("此申请已结束或审阅版本不同，请刷新")
                if command.action == "withdraw":
                    if saved["created_by_user_id"] != context.user.id:
                        raise ProductWorkAccessError("仅原提出人可撤回尚未正式应用的组合申请")
                else:
                    policy = latest_policy(c, context.tenant.id, command.project_id)
                    if (
                        policy is None
                        or policy["id"] != own["policy_id"]
                        or own["approver_user_id"] != context.user.id
                    ):
                        raise ProductWorkAccessError("仅本项目当前政策中的具名批准人可裁决")
                    _person(c, context, command.project_id, context.user.id)
                    if policy["four_eyes"] and saved["created_by_user_id"] == context.user.id:
                        raise ProductWorkAccessError("本项目政策要求提出人与批准人分开")
                    if any(v["project_id"] == command.project_id for v in values):
                        raise ProductWorkError("本项目已有裁决，请查看原记录")
                    if command.action == "approve":
                        check_own(c, context, saved, own)
                value = (
                    c.execute(
                        t.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            selection_id=saved["id"],
                            project_id=None if command.action == "withdraw" else command.project_id,
                            action=command.action,
                            reason=command.reason,
                            payload_digest=saved["payload_digest"],
                            actor_user_id=context.user.id,
                            request_id=command.request_id,
                            request_digest=signature,
                        )
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
                record(
                    c,
                    context,
                    saved["id"],
                    f"selection_{command.action}",
                    {
                        "decision_id": str(value["id"]),
                        "payload_digest": saved["payload_digest"],
                        "action": command.action,
                        "reason": command.reason,
                    },
                    command.project_id,
                )
                return _plain(value)
        except IntegrityError as error:
            raise ProductWorkError("裁决未重复保存，请刷新具名批准政策和原记录") from error
