"""Whole-scope health ordering under one current policy and database snapshot."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role
from app.contracts.common_objects import Contract
from app.db.schema import tables
from app.domain.organization import active_delegated_principals
from app.domain.portfolio_health import project_health
from app.domain.portfolio_health_policy import HealthPolicy, latest
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest


class HealthOverview(Contract):
    search: str = Field(default="", max_length=200)
    project_status: (
        Literal["draft", "proposed", "approved", "active", "on_hold", "completed", "archived"]
        | None
    ) = None
    focus: Literal["all", "alerts", "unknown"] = "all"
    order: Literal["alerts", "score", "unknown", "code"] = "alerts"
    offset: int = Field(default=0, ge=0)
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def compact(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "dimensions": [
            {
                key: value
                for key, value in dimension.items()
                if key not in ("sources", "severe_ids", "retired_ids")
            }
            for dimension in item["dimensions"]
        ],
    }


class PortfolioHealthOverviewService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, command: HealthOverview) -> dict[str, Any]:
        _role(context, Action.PROJECT_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            saved = latest(c, context.tenant.id)
            policy = HealthPolicy.model_validate(saved["body"]) if saved else None
            if (
                not policy
                or policy.status != "active"
                or not policy.valid_from <= now < policy.valid_until
            ):
                policy = None
            p = tables.projects
            query = select(p).where(p.c.tenant_id == context.tenant.id)
            if context.user.role not in (Role.OWNER, Role.ADMIN):
                principals = active_delegated_principals(
                    c, tenant_id=context.tenant.id, delegate_user_id=context.user.id, moment=now
                )
                query = query.where(
                    p.c.id.in_(
                        select(tables.project_members.c.project_id).where(
                            tables.project_members.c.tenant_id == context.tenant.id,
                            tables.project_members.c.user_id.in_((context.user.id, *principals)),
                        )
                    )
                )
            if command.search:
                query = query.where(
                    p.c.code.icontains(command.search, autoescape=True)
                    | p.c.name.icontains(command.search, autoescape=True)
                )
            if command.project_status:
                query = query.where(p.c.status == command.project_status)
            items = [
                compact(project_health(c, context, actual, now, policy))
                for actual in c.execute(query.order_by(p.c.id)).mappings()
            ]
            totals = {
                "projects": len(items),
                "with_alerts": sum(v["alert_dimensions"] > 0 for v in items),
                "with_unknown": sum(v["unknown_dimensions"] > 0 for v in items),
                "comparable": sum(v["score"] is not None for v in items),
            }
            if command.focus == "alerts":
                items = [v for v in items if v["alert_dimensions"] > 0]
            elif command.focus == "unknown":
                items = [v for v in items if v["unknown_dimensions"] > 0]

            def ordering(v: dict[str, Any]) -> tuple[Any, ...]:
                comparable = v["score"] is not None
                score = Decimal(v["score"]) if comparable else Decimal(0)
                tie = (v["code"], v["project_id"])
                if command.order == "code":
                    return tie
                if command.order == "score":
                    return (not comparable, score, *tie)
                if command.order == "unknown":
                    return (-v["unknown_dimensions"], -v["alert_dimensions"], *tie)
                return (
                    -v["alert_dimensions"],
                    -v["unknown_dimensions"],
                    not comparable,
                    score,
                    *tie,
                )

            items.sort(key=ordering)
            saved_value = _plain(saved) if saved else None
            revision = digest(
                {
                    "items": items,
                    "totals": totals,
                    "policy": saved_value,
                    "filters": command.model_dump(mode="json", exclude={"offset", "revision"}),
                }
            )
            if command.offset and command.revision != revision:
                raise ProductWorkError("项目依据、健康政策或读取范围已变化，请刷新第一页后继续")
            return {
                "items": items[command.offset : command.offset + 20],
                "total": len(items),
                "next_offset": command.offset + 20 if command.offset + 20 < len(items) else None,
                "revision": revision,
                "totals": totals,
                "as_of": now.isoformat(),
                "policy": saved_value,
                "policy_applied": policy is not None,
                "policy_missing": None
                if policy
                else "尚无当前有效健康政策，仅展示已读取指标，不判正常或补权重",
                "scope": "all_visible_projects_matching_search_and_status; registered_sources_only",
                "ordering_version": "portfolio-health-order.v1",
                "detail_mode": "recheck_current_project_evidence_on_demand",
            }
