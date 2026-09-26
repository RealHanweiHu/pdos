"""Evidence-scoped management facts for an explicit set of readable projects."""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select

from app.ai.executor import PromptFile
from app.ai.project_discussion_sources import actor, json_encoded
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.executive_brief import ExecutiveBrief, ExecutiveSelection
from app.domain.my_work import _page_summary
from app.domain.portfolio_control_queue import LABELS, link, queue_query
from app.domain.portfolio_health import project_health
from app.domain.portfolio_progress import capture, policy
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.resource_reservations import _project

PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "executive_control_tower_v1.json").read_text()
)
PROJECTION = "executive-control-tower-context.v1"
NODE_LIMIT = 30
QUEUE_LIMIT = 100
encoded = json_encoded


def prompt_for(snapshot: dict[str, Any]) -> PromptFile:
    if snapshot["projection_version"] != PROJECTION:
        raise ProductWorkError("原管理摘要资料版本不可用")
    return PROMPT


def version(run_context: dict[str, Any], snapshot: dict[str, Any]) -> str:
    expected = prompt_for(snapshot).version
    if run_context.get("executive_prompt_version") != expected:
        raise ProductWorkError("管理摘要原运行版本不一致")
    return expected


def readable(c: Connection, context: AuthContext, snapshot: dict[str, Any]) -> None:
    from app.domain.build_materials import BuildMaterialService
    from app.domain.cost_definition_feedback import cost_access
    from app.domain.portfolio_escalations import source_access

    _role(context, Action.PROJECT_VIEW)
    if str(context.user.id) != snapshot["actor_id"]:
        raise ProductWorkAccessError("管理摘要仅供原发起人读取")
    for identity in snapshot["selection"]["project_ids"]:
        _project(c, context, UUID(identity))
    for ref in snapshot["model_context"]["references"]:
        fields = ref["fields"]
        if ref["reference_id"].endswith(":health"):
            project = UUID(ref["project_id"])
            for dimension in fields["dimensions"]:
                if dimension["missing"] == ["当前没有本维度来源读取权限"]:
                    continue
                if dimension["dimension"] == "quality":
                    _role(context, Action.QUALITY_VIEW)
                elif dimension["dimension"] == "cost":
                    cost_access(c, context, project)
                elif dimension["dimension"] in ("supplier", "certification"):
                    BuildMaterialService._authorize(c, context, project)
        elif ref["reference_id"].startswith("executive:queue:"):
            if not source_access(
                c,
                context,
                {
                    "project_id": UUID(fields["project_id"]),
                    "source_id": UUID(fields["id"]),
                    "source_kind": fields["kind"],
                },
            ):
                raise ProductWorkAccessError("原管理摘要事项的读取范围已变化")


def rebuild(c: Connection, tenant: UUID, project: UUID, snapshot: dict[str, Any]) -> dict[str, Any]:
    context = actor(c, tenant, UUID(snapshot["actor_id"]))
    readable(c, context, snapshot)
    selection = ExecutiveSelection.model_validate(snapshot["selection"])
    if project != min(selection.project_ids):
        raise ProductWorkError("管理摘要原项目范围不一致")
    return source_state(c, context, selection)


def source_state(
    c: Connection, context: AuthContext, selection: ExecutiveSelection
) -> dict[str, Any]:
    _role(context, Action.PROJECT_VIEW)
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    age_policy = policy(c, context, now)
    refs: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []

    def reference(
        key: str,
        label: str,
        fields: dict[str, Any],
        project: UUID | None,
        href: str,
        omitted: list[str] | None = None,
    ) -> None:
        refs.append(
            {
                "reference_id": f"executive:{key}",
                "label": label,
                "project_id": str(project) if project else None,
                "fields": fields,
                "digest": digest(fields),
                "href": href,
                "omitted_fields": omitted or [],
            }
        )

    reference(
        "health-policy",
        "本次健康判定政策",
        {
            "policy": age_policy.model_dump(mode="json") if age_policy else None,
            "missing": [] if age_policy else ["没有当前有效健康政策，不判正常或补权重"],
        },
        None,
        "/portfolio",
    )
    for project in selection.project_ids:
        actual = _project(c, context, project)
        href = f"/projects?project={project}&tab=overview"
        health = project_health(c, context, actual, now, age_policy)
        progress, nodes = capture(c, context, actual, now, age_policy)
        dimensions = [
            {
                k: v[k]
                for k in (
                    "dimension",
                    "label",
                    "metric",
                    "unit",
                    "scope",
                    "value",
                    "score",
                    "status",
                    "missing",
                    "source_count",
                    "source_digest",
                    "rule",
                )
            }
            for v in health["dimensions"]
        ]
        reference(
            f"project:{project}:health",
            f"{actual['code']} · 六维健康",
            {
                "project_id": str(project),
                "project_code": actual["code"],
                "project_name": actual["name"],
                "project_status": actual["status"],
                "score": health["score"],
                "unknown_dimensions": health["unknown_dimensions"],
                "alert_dimensions": health["alert_dimensions"],
                "dimensions": dimensions,
                "evaluation_digest": health["evaluation_digest"],
            },
            project,
            href,
            ["各维度完整原件和来源明细；保留原计数/摘要标识，沿健康看板回查"],
        )
        reference(
            f"project:{project}:progress",
            f"{actual['code']} · 正式计划与预测",
            progress,
            project,
            href + "#schedule-forecasts",
        )
        unfinished = [v for v in nodes if not v["completed_with_evidence"]]
        selected_nodes = sorted(
            unfinished,
            key=lambda v: (
                v["status"] != "blocked",
                not (v["business_designation"] and v["business_designation"]["is_key"]),
                v["critical"] is not True,
                v["forecast_covered"] is True,
                v["baseline_finish"] or "9999",
                v["node_id"],
            ),
        )
        reference(
            f"project:{project}:nodes",
            f"{actual['code']} · 关注节点",
            {
                "project_id": str(project),
                "unfinished_total": len(unfinished),
                "included_count": min(len(selected_nodes), NODE_LIMIT),
                "omitted_count": max(0, len(selected_nodes) - NODE_LIMIT),
                "ordering": "阻塞、具名业务关键、当前关键路径、预测缺口优先，再按基线日期",
                "all_nodes_digest": digest(nodes),
                "items": selected_nodes[:NODE_LIMIT],
            },
            project,
            href + "#schedule-forecasts",
        )
        if len(selected_nodes) > NODE_LIMIT:
            omissions.append(
                {
                    "project_id": str(project),
                    "kind": "unfinished_nodes",
                    "count": len(selected_nodes) - NODE_LIMIT,
                }
            )

    query, q, _, _, unavailable = queue_query(c, context, now)
    query = query.where(q.c.project_id.in_(selection.project_ids), q.c.kind != "discussion_brief")
    order = (
        q.c.overdue.desc(),
        q.c.priority.desc(),
        q.c.waiting_since.asc().nullslast(),
        q.c.kind,
        q.c.id,
    )
    count, revision = c.execute(_page_summary(query, order)).one()
    grouped = query.subquery()
    counts = {
        key: amount
        for key, amount in c.execute(
            select(grouped.c.kind, func.count()).group_by(grouped.c.kind)
        ).all()
    }
    found = list(c.execute(query.order_by(*order).limit(QUEUE_LIMIT)).mappings())
    reference(
        "queue-summary",
        "所选项目的待决与例外计数",
        {
            "total": count,
            "counts": counts,
            "labels": LABELS,
            "revision": revision,
            "included_count": len(found),
            "omitted_count": max(0, count - len(found)),
            "unavailable": unavailable,
            "ordering": "过期、原业务优先级、原等待起点；无自动升级或个人排名",
            "timing_basis": "仅列原等待起点；Cost Gap取最新观察登记，不当作持续超标时长",
            "excluded": ["私人讨论摘要不随管理摘要转授"],
        },
        None,
        "/portfolio",
    )
    for row in found:
        item = _plain(row)
        reference(
            f"queue:{row['kind']}:{row['id']}",
            LABELS[row["kind"]],
            {**item, "label": LABELS[row["kind"]]},
            row["project_id"],
            link(item),
        )
    if count > len(found):
        omissions.append({"kind": "queue_details", "count": count - len(found)})
    limits = [
        "本次为所选项目在读取时点的快照；日/周用途中仍是当前状态，未计算期间新增或环比。",
        "六维指标沿原登记范围、原政策及缺源规则；缺项不代表正常，不推定完整业务覆盖。",
        "仅含六维健康、正式进度、关注节点和可读待办；未纳入资源争用、产品机会/DCP、完整短缺与供应商跨项目暴露。",
        "关键路径与具名业务关键里程碑分别保留；当前预测覆盖不证明持续覆盖或北极星达标。",
        "下一步只能建议具名人员沿原入口办理，不批准、改期、分配资源或发送通知。",
    ]
    basis = {
        "projection_version": PROJECTION,
        "actor_id": str(context.user.id),
        "selection": selection.model_dump(mode="json"),
        "references": refs,
        "coverage_limits": limits,
        "omitted_references": omissions,
    }
    result = {
        "project_id": str(min(selection.project_ids)),
        "projection_version": PROJECTION,
        "actor_id": str(context.user.id),
        "selection": selection.model_dump(mode="json"),
        "as_of": now.isoformat(),
        "digest": digest(basis),
        "model_context": {
            "question": "解释所选项目的组合异常、缺数和待决事项，给出有原字段依据的人工下一步。",
            "reading_time": now.isoformat(),
            "references": refs,
            "coverage_limits": limits,
            "omitted_references": omissions,
        },
    }
    if len(json_encoded(result)) > 200000:
        raise ProductWorkError("管理摘要资料超过本次阅读容量，请减少所选项目；未静默截断字段")
    return result


def validate_assessment(output: ExecutiveBrief, snapshot: dict[str, Any]) -> None:
    if snapshot["projection_version"] != PROJECTION:
        raise ProductWorkError("原管理摘要资料版本不可用")
    refs = {v["reference_id"]: v for v in snapshot["model_context"]["references"]}
    selected = set(snapshot["selection"]["project_ids"])
    if {str(v.project_id) for v in output.projects} != selected:
        raise ProductWorkError("管理解释须逐一对应所有所选项目，不可遗漏或增加项目")
    statements = list(output.portfolio_observations)
    for project in output.projects:
        local = [project.situation, *project.exceptions, *project.human_next_steps]
        for statement in local:
            if not any(
                refs.get(v.reference_id, {}).get("project_id") == str(project.project_id)
                for v in statement.citations
            ):
                raise ProductWorkError("逐项目解释须引用本项目原依据")
        statements.extend(local)
    for statement in statements:
        for citation in statement.citations:
            ref = refs.get(citation.reference_id)
            if ref is None or ref["digest"] != citation.digest:
                raise ProductWorkError("管理摘要引用不属于固定资料")
            value = ref["fields"]
            for key in citation.field_path:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                elif isinstance(value, list) and key.isdecimal() and int(key) < len(value):
                    value = value[int(key)]
                else:
                    raise ProductWorkError("摘要引用超出实际读取字段范围")
            if citation.quoted_value != (value if isinstance(value, str) else json_encoded(value)):
                raise ProductWorkError("摘要引用值与原字段不一致")


class ExecutivePreparationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, selection: ExecutiveSelection) -> dict[str, Any]:
        from app.ai.capability_contract import resolve_capability

        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return {
                **source_state(c, context, selection),
                "status": "prepared",
                "rollout": resolve_capability(
                    "executive_intelligence.executive_brief"
                ).rollout.value,
                "prompt_version": PROMPT.version,
            }
