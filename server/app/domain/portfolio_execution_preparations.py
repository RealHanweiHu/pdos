"""Prepare exact approved portfolio dates into real project baseline requests atomically."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.baseline_changes import (
    BaselineChangeDraft,
    BaselineChangeService,
    latest_baseline,
    latest_policy,
)
from app.domain.portfolio_comparisons import readable, record
from app.domain.portfolio_selections import (
    comparison,
    decisions,
    parts,
    recheck_comparison,
    selection,
    state,
)
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.project_execution import _person
from app.domain.project_scenario_capacity import get_scenario
from app.domain.resource_reservations import _project
from app.domain.resource_schedule_preparations import (
    ResourceSchedulePreparation,
    ResourceSchedulePreparationService,
    get_schedule,
)


class PortfolioExecutionPreparation(Contract):
    request_id: UUID
    selection_id: UUID
    expected_digest: Digest
    reason: Text


def origin(c: Connection, tenant: UUID, project: UUID, scenario: UUID) -> Any:
    t = tables.portfolio_execution_projects
    return (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant, t.c.project_id == project, t.c.scenario_id == scenario
            )
        )
        .mappings()
        .one_or_none()
    )


def existing(c: Connection, tenant: UUID, selected: UUID) -> Any:
    t = tables.portfolio_execution_preparations
    return (
        c.execute(select(t).where(t.c.tenant_id == tenant, t.c.selection_id == selected))
        .mappings()
        .one_or_none()
    )


def date_values(result: dict[str, Any]) -> dict[str, Any]:
    return {
        n["node_id"]: {
            key: datetime.fromisoformat(n[key]).astimezone(UTC).isoformat() if n.get(key) else None
            for key in ("start", "finish", "remaining_work_start")
        }
        for n in result["nodes"]
    }


def verify_baseline_origin(
    c: Connection,
    context: AuthContext,
    project: UUID,
    change: Any,
    *,
    applying: bool = False,
    preparation_id: UUID | None = None,
) -> None:
    bound = origin(c, context.tenant.id, project, change["scenario_id"])
    if bound is None:
        return
    if applying and preparation_id != bound["preparation_id"]:
        raise ProductWorkError("此基线属于组合执行准备，请通过组合的整批独立应用办理")
    if applying:
        _role(context, Action.TENANT_MANAGE)
    if bound["change_id"] != change["id"] or bound["change_digest"] != change["payload_digest"]:
        raise ProductWorkError("组合执行须沿用原固定基线申请，不能替换批准内容")
    package = (
        c.execute(
            select(tables.portfolio_execution_preparations).where(
                tables.portfolio_execution_preparations.c.tenant_id == context.tenant.id,
                tables.portfolio_execution_preparations.c.id == bound["preparation_id"],
            )
        )
        .mappings()
        .one()
    )
    saved = selection(c, context, package["selection_id"], lock=True)
    participants = parts(c, context, saved["id"])
    if state(decisions(c, context, saved["id"]), len(participants)) != "approved_for_preparation":
        raise ProductWorkError("原组合采用申请已撤回或未全部同意，不能继续批准正式计划")
    own = next(p for p in participants if p["project_id"] == project)
    from app.domain.portfolio_selections import check_own

    check_own(c, context, saved, own)


class PortfolioExecutionPreparationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def prepare(
        self, context: AuthContext, command: PortfolioExecutionPreparation
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        try:
            with self.engine.begin() as c:
                preliminary = selection(c, context, command.selection_id)
                original = comparison(c, context, preliminary["comparison_id"])
                readable(c, context, original["inputs"])
                participants = parts(c, context, preliminary["id"])
                for part in participants:
                    _project(c, context, part["project_id"], write=True)
                saved = selection(c, context, preliminary["id"], lock=True)
                fingerprint = digest(command.model_dump(mode="json"))
                prior = existing(c, context.tenant.id, saved["id"])
                if prior:
                    if (
                        prior["actor_user_id"] == context.user.id
                        and prior["request_id"] == command.request_id
                        and prior["request_digest"] != fingerprint
                    ):
                        raise ProductWorkError("请求编号已用于另一份执行准备")
                    return {
                        "id": str(prior["id"]),
                        "selection_id": str(saved["id"]),
                        "reused": True,
                    }
                approvals = decisions(c, context, saved["id"])
                if (
                    saved["payload_digest"] != command.expected_digest
                    or state(approvals, len(participants)) != "approved_for_preparation"
                ):
                    raise ProductWorkError("须各项目对同一版本全部具名同意后，再准备正式执行")
                recheck_comparison(c, context, original)
                prepared = []
                identity = uuid4()
                for part in participants:
                    project = part["project_id"]
                    policy = latest_policy(c, context.tenant.id, project)
                    if (
                        policy is None
                        or policy["id"] != part["policy_id"]
                        or latest_baseline(c, context.tenant.id, project)["id"]
                        != part["baseline_id"]
                    ):
                        raise ProductWorkError(
                            "至少一个项目的基线或批准政策已变化，请重新提出组合方案"
                        )
                    _person(c, context, project, part["approver_user_id"])
                    if policy["four_eyes"] and policy["approver_user_id"] == context.user.id:
                        raise ProductWorkError("正式计划的准备人与批准人须按项目政策分开")
                    source = get_schedule(
                        c, context, project, UUID(part["snapshot"]["selected"]["schedule_id"])
                    )
                    t = tables.project_resource_schedule_preparations
                    prior_source = (
                        c.execute(
                            select(t).where(
                                t.c.tenant_id == context.tenant.id,
                                t.c.project_id == project,
                                t.c.schedule_id == source["id"],
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if prior_source:
                        resource = _plain(prior_source)
                    else:
                        resource = ResourceSchedulePreparationService(
                            self.engine
                        ).prepare_in_connection(
                            c,
                            context,
                            project,
                            ResourceSchedulePreparation(
                                request_id=uuid5(command.request_id, f"resource:{project}"),
                                schedule_id=source["id"],
                                expected_result_digest=source["result_digest"],
                                title=f"组合采用 · {part['snapshot']['project_name']}"[:2048],
                                reason=part["snapshot"]["reason"],
                            ),
                            preserve_source_dates=True,
                        )
                    scenario_id = UUID(resource["scenario_id"])
                    if (
                        prior_source is not None
                        and c.execute(
                            select(tables.baseline_change_requests.c.id)
                            .where(
                                tables.baseline_change_requests.c.tenant_id == context.tenant.id,
                                tables.baseline_change_requests.c.project_id == project,
                                tables.baseline_change_requests.c.scenario_id == scenario_id,
                            )
                            .limit(1)
                        ).first()
                    ):
                        raise ProductWorkError(
                            "此资源准备已有独立基线申请，请沿原办理或重新计算资源方案"
                        )
                    if origin(c, context.tenant.id, project, scenario_id) is not None:
                        raise ProductWorkError(
                            "所选资源方案已有组合执行准备，请沿原回执办理或重新计算方案"
                        )
                    scenario = get_scenario(c, context, project, scenario_id)
                    if date_values(scenario["result"]) != date_values(source["result"]):
                        raise ProductWorkError(
                            "正式准备的节点日期与获同意方案不同，请重算比较并重新审阅"
                        )
                    checks = tables.project_scenario_capacity_checks
                    check = (
                        c.execute(
                            select(checks)
                            .where(
                                checks.c.tenant_id == context.tenant.id,
                                checks.c.project_id == project,
                                checks.c.scenario_id == scenario_id,
                            )
                            .order_by(checks.c.created_at.desc(), checks.c.id.desc())
                            .limit(1)
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if check is None:
                        raise ProductWorkError("正式计划准备缺少原容量回执")
                    change = BaselineChangeService(self.engine).prepare_in_connection(
                        c,
                        context,
                        project,
                        BaselineChangeDraft(
                            request_id=uuid5(command.request_id, f"baseline:{project}"),
                            scenario_id=scenario_id,
                            capacity_check_id=check["id"],
                            policy_id=part["policy_id"],
                            expected_baseline_id=part["baseline_id"],
                            reason=part["snapshot"]["reason"],
                        ),
                        calculation_as_of=datetime.fromisoformat(source["result"]["as_of"]),
                    )
                    if date_values(change["snapshot"]["result"]) != date_values(source["result"]):
                        raise ProductWorkError(
                            "正式基线申请日期与获同意方案不同，请重算比较后重新准备"
                        )
                    if change["snapshot"]["blockers"]:
                        raise ProductWorkError(
                            "正式基线申请仍有缺项：" + "；".join(change["snapshot"]["blockers"][:8])
                        )
                    if policy["four_eyes"] and change["created_by_user_id"] == str(
                        part["approver_user_id"]
                    ):
                        raise ProductWorkError("正式基线申请须由独立提出人提交")
                    prepared.append(
                        {
                            "project_id": str(project),
                            "project_name": part["snapshot"]["project_name"],
                            "schedule_id": str(source["id"]),
                            "source_result_digest": source["result_digest"],
                            "resource_preparation_id": resource["id"],
                            "scenario_id": str(scenario_id),
                            "capacity_check_id": str(check["id"]),
                            "change_id": change["id"],
                            "change_digest": change["payload_digest"],
                            "baseline_id": str(part["baseline_id"]),
                            "policy_id": str(part["policy_id"]),
                            "approver_user_id": str(part["approver_user_id"]),
                            "dates": date_values(source["result"]),
                            "dates_changed": False,
                        }
                    )
                receipt = {
                    "selection_id": str(saved["id"]),
                    "selection_digest": saved["payload_digest"],
                    "comparison_id": str(original["id"]),
                    "comparison_digest": original["payload_digest"],
                    "approvals": [
                        {
                            "id": str(a["id"]),
                            "project_id": str(a["project_id"]),
                            "actor_user_id": str(a["actor_user_id"]),
                            "payload_digest": a["payload_digest"],
                        }
                        for a in approvals
                    ],
                    "items": prepared,
                    "baseline_changed": False,
                    "reservations_changed": False,
                    "commitments_changed": False,
                    "requires_baseline_approval": True,
                    "requires_independent_application": True,
                }
                c.execute(
                    tables.portfolio_execution_preparations.insert().values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        selection_id=saved["id"],
                        selection_digest=saved["payload_digest"],
                        reason=command.reason,
                        receipt=receipt,
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                )
                for item in prepared:
                    project = UUID(item["project_id"])
                    c.execute(
                        tables.portfolio_execution_projects.insert().values(
                            tenant_id=context.tenant.id,
                            preparation_id=identity,
                            project_id=project,
                            selection_id=saved["id"],
                            schedule_id=UUID(item["schedule_id"]),
                            resource_preparation_id=UUID(item["resource_preparation_id"]),
                            scenario_id=UUID(item["scenario_id"]),
                            capacity_check_id=UUID(item["capacity_check_id"]),
                            change_id=UUID(item["change_id"]),
                            change_digest=item["change_digest"],
                            receipt=item,
                        )
                    )
                    record(
                        c,
                        context,
                        identity,
                        "execution_prepared",
                        {
                            "preparation_id": str(identity),
                            "selection_id": str(saved["id"]),
                            "item": item,
                        },
                        project,
                    )
                return {"id": str(identity), "selection_id": str(saved["id"]), "reused": False}
        except IntegrityError as error:
            raise ProductWorkError(
                "整批执行准备未保存；请刷新原申请和基线记录，原预约与基线未改动"
            ) from error
