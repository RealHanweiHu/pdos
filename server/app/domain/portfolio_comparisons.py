"""Portfolio scoring policy, immutable comparisons and scope-aware source selection."""

from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.cost_definition_feedback import cost_access
from app.domain.plan_scenarios import _calendar_access
from app.domain.portfolio_scoring import (
    FORMULA,
    PortfolioComparison,
    PortfolioComparisonSave,
    PortfolioPolicy,
)
from app.domain.portfolio_sources import capture
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def latest(c: Connection, tenant: UUID) -> Any:
    t = tables.portfolio_scoring_policies
    return (
        c.execute(select(t).where(t.c.tenant_id == tenant).order_by(t.c.version.desc()).limit(1))
        .mappings()
        .one_or_none()
    )


def active(c: Connection, context: AuthContext, identity: UUID) -> Any:
    row = latest(c, context.tenant.id)
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    if row is None or row["id"] != identity or row["body"]["status"] != "active":
        raise ProductWorkError("请选择当前启用的组合评分政策；缺少政策时不能代填权重")
    policy = PortfolioPolicy.model_validate(row["body"])
    if not policy.valid_from <= now < policy.valid_until:
        raise ProductWorkError("组合评分政策未生效或已过期")
    return row


def readable(c: Connection, context: AuthContext, inputs: dict[str, Any]) -> None:
    for part in inputs["projects"]:
        project = UUID(part["project_id"])
        _project(c, context, project)
        cost_access(c, context, project)


def record(
    c: Connection,
    context: AuthContext,
    identity: UUID,
    action: str,
    body: dict[str, Any],
    project: UUID | None = None,
) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=project
    ).record(
        EventDraft(
            event_id=f"portfolio:{identity}:{action}:{project}",
            event_type="PORTFOLIO_COMPARISON_RECORDED",
            source="planning_service",
            entity_id=identity,
            payload={"id": str(identity), "action": action},
        ),
        AuditDraft(action=f"portfolio.{action}", after_snapshot=body),
    )


class PortfolioComparisonService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def policies(self, context: AuthContext, before: int | None = None) -> dict[str, Any]:
        _calendar_access(context)
        with self.engine.connect() as c:
            t = tables.portfolio_scoring_policies
            current = latest(c, context.tenant.id)
            query = select(t).where(t.c.tenant_id == context.tenant.id)
            if before is not None:
                query = query.where(t.c.version < before)
            rows = list(c.execute(query.order_by(t.c.version.desc()).limit(21)).mappings())
            return {
                "current": _plain(current) if current else None,
                "items": [_plain(row) for row in rows[:20]],
                "next": rows[19]["version"] if len(rows) > 20 else None,
                "can_manage": is_allowed(context.user.role, Action.TENANT_MANAGE),
                "can_compare": is_allowed(context.user.role, Action.PROJECT_EDIT),
                "formula": FORMULA,
            }

    def publish(self, context: AuthContext, command: PortfolioPolicy) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as c:
            c.execute(select(func.cehub_project.lock_resource_inventory(context.tenant.id)))
            t = tables.portfolio_scoring_policies
            signature = digest(command.model_dump(mode="json"))
            prior = (
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
            if prior:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("请求编号已用于另一项评分政策")
                return _plain(prior)
            previous = latest(c, context.tenant.id)
            if command.expected_version != (previous["version"] if previous else 0):
                raise ProductWorkError("评分政策版本已变化，请刷新")
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            if command.status == "active" and not command.valid_from <= now < command.valid_until:
                raise ProductWorkError("发布启用政策时，有效期须覆盖当前时点")
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        version=command.expected_version + 1,
                        formula_version=FORMULA,
                        body=command.model_dump(mode="json"),
                        created_by_user_id=context.user.id,
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
                "policy_published",
                {"id": str(saved["id"]), "version": saved["version"], "status": command.status},
            )
            return _plain(saved)

    def options(
        self,
        context: AuthContext,
        project: UUID,
        kind: Literal["schedule", "cost", "evidence"],
        before: UUID | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            _project(c, context, project)
            cost_access(c, context, project)
            t = {
                "schedule": tables.project_resource_schedules,
                "cost": tables.cost_rollups,
                "evidence": tables.documents,
            }[kind]
            query = select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if before:
                cursor = c.execute(query.where(t.c.id == before)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("来源游标不属于所选项目")
                query = query.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            rows = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            items = []
            for row in rows[:20]:
                if kind == "schedule":
                    title = c.execute(
                        select(tables.project_schedule_scenarios.c.title).where(
                            tables.project_schedule_scenarios.c.tenant_id == context.tenant.id,
                            tables.project_schedule_scenarios.c.id == row["scenario_id"],
                        )
                    ).scalar_one()
                    details = {
                        "finish": row["result"]["project_finish"],
                        "status": row["result"]["solution_status"],
                        "scenario_id": str(row["scenario_id"]),
                        "as_of": row["result"]["as_of"],
                    }
                elif kind == "cost":
                    title = row["title"]
                    details = {
                        "currency": row["command"]["currency"],
                        "stage": row["command"]["stage"],
                        "quantity": row["command"]["product_quantity"],
                        "unit_total": row["result"]["unit_total"],
                        "nre_total": row["result"]["nre_total"],
                        "as_of": row["command"]["as_of"],
                    }
                else:
                    title, details = row["filename"], {"classification": row["classification"]}
                items.append(
                    {
                        "id": str(row["id"]),
                        "title": title,
                        "created_at": row["created_at"].isoformat(),
                        "details": details,
                    }
                )
            return {"items": items, "next": str(rows[19]["id"]) if len(rows) > 20 else None}

    def preview(self, context: AuthContext, command: PortfolioComparison) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        with self.engine.begin() as c:
            policy = active(c, context, command.policy_id)
            value = capture(c, context, command, policy)
            active(c, context, command.policy_id)
            return value

    def save(self, context: AuthContext, command: PortfolioComparisonSave) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        try:
            with self.engine.begin() as c:
                t = tables.portfolio_comparisons
                signature = digest(command.model_dump(mode="json"))
                prior = (
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
                if prior:
                    readable(c, context, prior["inputs"])
                    if prior["request_digest"] != signature:
                        raise ProductWorkError("请求编号已用于另一份组合比较")
                    return {"id": str(prior["id"])}
                policy = active(c, context, command.policy_id)
                draft = PortfolioComparison.model_validate(
                    command.model_dump(exclude={"expected_digest"})
                )
                value = capture(c, context, draft, policy)
                active(c, context, command.policy_id)
                if value["payload_digest"] != command.expected_digest:
                    raise ProductWorkError("比较依据或缺项已变化，请重新预览")
                identity = uuid4()
                c.execute(
                    t.insert().values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        policy_id=policy["id"],
                        title=command.title,
                        inputs=draft.model_dump(mode="json"),
                        snapshot=value["snapshot"],
                        payload_digest=value["payload_digest"],
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                )
                scope = {p.project_id: p for p in command.projects}
                for alternative in command.alternatives:
                    for choice in alternative.choices:
                        c.execute(
                            tables.portfolio_comparison_sources.insert().values(
                                tenant_id=context.tenant.id,
                                comparison_id=identity,
                                alternative_key=alternative.key,
                                project_id=choice.project_id,
                                schedule_id=choice.schedule_id,
                                cost_rollup_id=choice.cost_rollup_id,
                                evidence_id=choice.evidence_id,
                                calendar_version_id=scope[choice.project_id].calendar_version_id,
                            )
                        )
                for project in command.projects:
                    record(
                        c,
                        context,
                        identity,
                        "comparison_saved",
                        {
                            "id": str(identity),
                            "policy_id": str(policy["id"]),
                            "alternative_count": len(command.alternatives),
                        },
                        project.project_id,
                    )
                return {"id": str(identity)}
        except IntegrityError as error:
            raise ProductWorkError("比较未重复保存，请刷新记录或重试同一请求") from error

    def list(
        self, context: AuthContext, before: UUID | None = None, record_id: UUID | None = None
    ) -> dict[str, Any]:
        _calendar_access(context)
        with self.engine.connect() as c:
            t = tables.portfolio_comparisons
            query = select(t).where(t.c.tenant_id == context.tenant.id)
            if record_id:
                value = c.execute(query.where(t.c.id == record_id)).mappings().one_or_none()
                if value is None:
                    raise ProductWorkAccessError("组合比较不存在或不可读取")
                readable(c, context, value["inputs"])
                return {"record": _plain(value)}
            if before:
                cursor = c.execute(query.where(t.c.id == before)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("组合历史游标无效")
                query = query.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            rows = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            items = []
            for value in rows[:20]:
                try:
                    readable(c, context, value["inputs"])
                except (ProductWorkAccessError, PermissionError):
                    continue
                items.append(
                    {
                        "id": str(value["id"]),
                        "title": value["title"],
                        "created_at": value["created_at"].isoformat(),
                        "policy_version": value["snapshot"]["policy"]["version"],
                        "alternatives": [
                            {
                                key: a[key]
                                for key in ("key", "title", "strategy", "score", "rank", "blockers")
                            }
                            for a in value["snapshot"]["result"]["alternatives"]
                        ],
                    }
                )
            return {"items": items, "next": str(rows[19]["id"]) if len(rows) > 20 else None}
