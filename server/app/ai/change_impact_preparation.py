"""Actual, bounded engineering sources and cited output for the next application adapter."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select

from app.ai import change_professional_sources as professional_sources
from app.ai.change_schedule_sources import read_sources as schedule_sources
from app.ai.executor import PromptFile
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.change_work_package import ChangeImpactAssessment as ChangeImpactAssessment
from app.contracts.tool_payloads import (
    BoundHandle,
    CitedStatement,
    ImpactData,
    ImpactLink,
    TraceImpactInput,
)
from app.domain.change_execution_overview import _read as execution_overview
from app.domain.change_execution_results import _access
from app.domain.change_impact_graph import KINDS
from app.domain.change_impact_graph import _read as impact_graph
from app.domain.change_impact_scope import current_basis
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.professional_change_routes import impact_basis as professional_basis

PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "change_work_package_v3.json").read_text()
)
CONTEXT_VERSION = "change-work-package-context-v3"
MAX_CONTEXT_CHARS = 160_000
MAX_REFERENCE_CHARS = 12_000
FIELDS = (
    "id",
    "code",
    "title",
    "name",
    "description",
    "reason",
    "version",
    "revision_number",
    "status",
    "draft_state",
    "part_number",
    "material_reference",
    "quantity",
    "unit",
    "bom_type",
    "verification_method",
    "acceptance_criteria",
    "criticality",
    "content",
    "attributes",
    "serial_number",
    "fw_version",
    "pcb_version",
    "structure_version",
    "run_number",
    "conditions",
    "metrics",
    "result_notes",
    "executed_at",
    "execution_time_precision",
    "execution_time_source",
    "snapshot",
    "certificate_type",
    "certificate_number",
    "issuing_body",
    "valid_from",
    "valid_until",
    "completed_at",
    "evidence_reference",
    "root_cause",
    "resolution",
    "severity",
    "currency",
    "amount",
    "unit_cost",
    "filename",
    "size_bytes",
    "mime_type",
    "sha256",
    "approved_at",
    "updated_at",
)


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_assessment(value: ChangeImpactAssessment, snapshot: dict[str, Any]) -> None:
    """Check actual handles, source digests and exact field excerpts before creating a Finding."""
    references = {r["reference_id"]: r for r in snapshot["model_context"]["references"]}
    statements = list(value.summary)
    for item in value.impacts:
        target = references.get(item.target_reference_id)
        if target is None or target["category"] != "object":
            raise ProductWorkError("候选影响对象未在本次实际读取范围内")
        statements.append(item.basis)
        statements.extend(work.basis for work in item.proposed_work)
    for statement in statements:
        for citation in statement.citations:
            ref = references.get(citation.reference_id)
            if ref is None or ref["digest"] != citation.digest:
                raise ProductWorkError("模型引用不属于本次来源版本")
            current: Any = ref["fields"]
            for part in citation.field_path:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                elif isinstance(current, list) and part.isdecimal() and int(part) < len(current):
                    current = current[int(part)]
                else:
                    raise ProductWorkError("模型引用字段在本次资料中不存在")
            expected = current if isinstance(current, str) else encoded(current)
            if citation.quoted_value != expected:
                raise ProductWorkError("模型摘录与原字段值不一致")


def source_state(
    c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID, depth: int = 3
) -> dict[str, Any]:
    if not 1 <= depth <= 5:
        raise ProductWorkError("请选择1至5层分析范围")
    graph = impact_graph(c, tenant_id, project_id, ecr_id, depth)
    scope = current_basis(c, tenant_id, project_id, ecr_id)
    execution = execution_overview(c, tenant_id, project_id, ecr_id)
    schedule = schedule_sources(c, tenant_id, project_id, ecr_id, graph, depth)
    references: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    source_digests: dict[str, str] = {"schedule_sources": schedule["digest"]}
    used = 0

    def add(
        reference_id: str, category: str, label: str, fields: dict[str, Any], source_digest: str
    ) -> None:
        nonlocal used
        source_digests[reference_id] = source_digest
        selected = {}
        skipped = []
        size = 0
        for key, value in fields.items():
            length = len(encoded({key: value}))
            if size + length > MAX_REFERENCE_CHARS:
                skipped.append(key)
            else:
                selected[key] = value
                size += length
        reference = {
            "reference_id": reference_id,
            "category": category,
            "label": label,
            "fields": selected,
            "source_digest": source_digest,
            "omitted_fields": skipped,
        }
        reference["digest"] = digest(reference)
        length = len(encoded(reference))
        if used + length > MAX_CONTEXT_CHARS:
            omissions.append(
                {"reference_id": reference_id, "label": label, "reason": "输入容量上限"}
            )
            return
        used += length
        references.append(reference)

    ecr_table = KINDS["ecr"][0]
    ecr = _plain(
        dict(
            c.execute(
                select(ecr_table).where(
                    ecr_table.c.tenant_id == tenant_id,
                    ecr_table.c.project_id == project_id,
                    ecr_table.c.id == ecr_id,
                )
            )
            .mappings()
            .one()
        )
    )
    add(
        "ecr:" + str(ecr_id),
        "change",
        "工程变更 · " + ecr["code"],
        {k: ecr[k] for k in FIELDS if k in ecr and k != "snapshot"},
        digest(ecr),
    )
    comparisons = {
        k: graph[k]
        for k in (
            "analysis_state",
            "scope_revision",
            "analyzed_scope_revision",
            "scope_comparisons",
            "professional_comparisons",
        )
    }
    add(
        "analysis-comparisons:" + str(ecr_id),
        "comparison",
        "当前与已分析版本比较",
        comparisons,
        digest(comparisons),
    )
    schedule_head = schedule["references"][0]
    add(
        schedule_head["reference_id"],
        "schedule",
        schedule_head["label"],
        schedule_head["fields"],
        schedule_head["source_digest"],
    )
    professional = professional_basis(c, tenant_id, project_id, ecr_id)
    for entry in professional["sources"] if professional else []:
        source = entry["source"]
        content = source["snapshot"]
        head = {
            "source_kind": entry["kind"],
            "revision": source["revision_number"],
            "ready": entry["ready"],
            "routing_reason": entry["routing_reason"],
            **{k: v for k, v in content.items() if k not in {"lines", "sources"}},
        }
        if entry["kind"] == "cost_alternative":
            # Use the retained proposal once; nested case/observation copies add no new evidence.
            head = {
                **{k: head[k] for k in ("source_kind", "revision", "ready", "routing_reason")},
                **{
                    k: content[k]
                    for k in (
                        "command",
                        "comparison",
                        "evidence",
                        "baseline_source",
                        "proposal_source",
                    )
                },
                "case_id": content["case"]["id"],
                "issue_id": content["case"]["issue_id"],
                "observation_id": content["observation"]["id"],
                "baseline_calculation_id": content["baseline_calculation"]["id"],
                "proposal_calculation_id": (content["proposal_calculation"] or {}).get("id"),
                "notice": "历史费用与预期差额仅支持方案评估，工程批准、验证与实现效果分别办理",
            }
        add(
            "professional:" + source["id"],
            "professional",
            "专业工作包及转入依据",
            head,
            digest(entry),
        )
        for index, line in enumerate(content.get("lines", [])):
            add(
                "professional-line:" + source["id"] + ":" + str(index),
                "professional",
                "专业逐项评审依据",
                line,
                digest(line),
            )
    # Put the explicit human scope and existing execution gaps ahead of graph expansion.
    if scope:
        version = scope["version"]
        add(
            "scope:" + version["id"],
            "scope",
            "当前人工核对范围",
            {
                "revision": version["revision_number"],
                "coverage": version["snapshot"]["coverage"],
                "exclusions": version["snapshot"]["exclusions"],
                "ready": scope["ready"],
                "source_comparisons": scope["sources"],
            },
            digest(scope),
        )
        for item in version["snapshot"]["items"]:
            add(
                "scope-item:" + item["key"],
                "scope_item",
                "人工范围条目",
                {k: v for k, v in item.items() if k != "snapshot"},
                digest(item),
            )
    for row in execution["items"]:
        body = {
            k: row[k]
            for k in (
                "status",
                "required",
                "completion_criteria",
                "result_scope",
                "gaps",
                "follow_up_count",
            )
        }
        body["task"] = (
            {
                k: row["task"][k]
                for k in ("title", "status", "start_date", "due_date", "expected_output")
                if k in row["task"]
            }
            if row["task"]
            else None
        )
        body["result_version"] = row["result"]["revision_number"] if row["result"] else None
        body["confirmation"] = (
            {k: row["confirmation"][k] for k in ("outcome", "note", "created_at")}
            if row["confirmation"]
            else None
        )
        add("execution:" + row["item"]["key"], "execution", "本条执行结果与缺口", body, digest(row))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in graph["nodes"]:
        grouped[node["kind"]].append(node)
    for kind, nodes in sorted(grouped.items()):
        if kind == "ecr":
            continue
        t = KINDS[kind][0]
        filters = [t.c.tenant_id == tenant_id, t.c.id.in_([UUID(n["id"]) for n in nodes])]
        if "project_id" in t.c:
            filters.append(t.c.project_id == project_id)
        actual = {
            str(row["id"]): _plain(dict(row))
            for row in c.execute(select(t).where(*filters)).mappings()
        }
        for node in nodes:
            source = actual[node["id"]]
            # Snapshot is only exposed for immutable sample configuration, never arbitrary history.
            fields = {
                k: source[k]
                for k in FIELDS
                if k in source and (k != "snapshot" or kind == "configuration")
            }
            add(
                node["key"],
                "object",
                node["kind_label"] + " · " + node["label"],
                fields,
                node["digest"],
            )
    for entry in schedule["references"][1:]:
        add(
            entry["reference_id"],
            "schedule",
            entry["label"],
            entry["fields"],
            entry["source_digest"],
        )
    projections = professional_sources.collect(
        c, tenant_id, project_id, ecr_id, graph, professional, schedule
    )
    source_digests["professional_projections"] = projections["digest"]
    for entry in projections["references"]:
        add(
            entry["reference_id"],
            entry["category"],
            entry["label"],
            entry["fields"],
            entry["source_digest"],
        )
    included = {r["reference_id"] for r in references}
    for edge in graph["edges"]:
        if edge["source"] not in included or edge["target"] not in included:
            omissions.append(
                {
                    "reference_id": "edge:" + digest(edge),
                    "label": edge["label"],
                    "reason": "关系端点未完整纳入",
                }
            )
            continue
        add("edge:" + digest(edge), "relationship", edge["label"], edge, digest(edge))
    context: dict[str, Any] = {
        "question": "核对当前工程变更的逐对象影响、未知关系和复验/复审/复认证/协同建议。",
        "references": references,
        "professional_projections": professional_sources.project(projections, references),
        "coverage": {
            "professional_projection_version": professional_sources.VERSION,
            "professional_coverage": projections["coverage"],
            "depth": depth,
            "graph_limits": graph["limits"],
            "unresolved": [
                *graph["unresolved"],
                *({"kind": "schedule", "message": gap} for gap in schedule["gaps"]),
            ],
            "gaps": graph["gaps"],
            "omitted_reference_count": len(omissions),
            "partial_reference_count": sum(bool(r["omitted_fields"]) for r in references),
            "scope_gaps": execution["scope_gaps"],
        },
    }
    while len(encoded(context)) > MAX_CONTEXT_CHARS and references:
        removed = references.pop()
        omissions.append(
            {
                "reference_id": removed["reference_id"],
                "label": removed["label"],
                "reason": "完整输入容量上限",
            }
        )
        context["coverage"]["omitted_reference_count"] = len(omissions)
        context["professional_projections"] = professional_sources.project(projections, references)
    if not references or len(encoded(context)) > MAX_CONTEXT_CHARS:
        raise ProductWorkError("本次资料超出单次分析容量，请减少关联层数")
    context["coverage"]["partial_reference_count"] = sum(
        bool(r["omitted_fields"]) for r in references
    )
    basis = {
        "context_version": CONTEXT_VERSION,
        "ecr_id": str(ecr_id),
        "model_context": context,
        "source_digests": source_digests,
    }
    return {
        **basis,
        "digest": digest(basis),
        "omissions": omissions,
        "read_at": graph["as_of"],
        "prompt_version": PROMPT.version,
    }


def trace_impact(snapshot: dict[str, Any], request: TraceImpactInput) -> ImpactData:
    """Model-visible handles resolve only inside the server-provided source snapshot."""
    if request.depth > snapshot["model_context"]["coverage"]["depth"]:
        raise ProductWorkError("请求层数超过本次服务端已准备范围")
    if request.continuation is not None:
        raise ProductWorkError("本次固定读取没有续页句柄，请重新准备更合适的范围")
    refs = {r["reference_id"]: r for r in snapshot["model_context"]["references"]}
    roots = set()
    for handle in request.changed_objects:
        ref = refs.get(handle.handle)
        if ref is None or ref["category"] not in {"object", "change"}:
            raise ProductWorkError("影响对象不在本次服务端绑定范围内")
        version = ref["fields"].get("version", ref["fields"].get("revision_number"))
        if (
            handle.digest is not None
            and handle.digest != ref["digest"]
            or handle.version is not None
            and handle.version != version
        ):
            raise ProductWorkError("影响对象引用版本不一致")
        roots.add(handle.handle)
    edges = [r for r in refs.values() if r["category"] == "relationship"]
    seen = set(roots)
    selected = {}
    frontier = set(roots)
    for _ in range(request.depth):
        following = set()
        for edge in edges:
            a, b = edge["fields"]["source"], edge["fields"]["target"]
            if a in refs and b in refs and (a in frontier or b in frontier):
                selected[edge["reference_id"]] = edge
                following.update({a, b} - seen)
        seen.update(following)
        frontier = following
        if not frontier:
            break
    coverage = snapshot["model_context"]["coverage"]
    missing = [r["message"] for r in coverage["unresolved"]] + [
        r["message"] for r in coverage["gaps"]
    ]
    missing += list(coverage["graph_limits"]) + list(coverage["scope_gaps"])
    if coverage["omitted_reference_count"] or coverage["partial_reference_count"]:
        missing.append("本次有未纳入引用或省略字段，不能判断完整影响范围")
    missing.append(
        "结果仅覆盖本次已读取的显式关系；提议变更内容需另行逐对象专业判断，引用关系不代表执行依赖"
    )
    return ImpactData(
        links=tuple(
            ImpactLink(
                source=BoundHandle(
                    handle=edge["fields"]["source"], digest=refs[edge["fields"]["source"]]["digest"]
                ),
                target=BoundHandle(
                    handle=edge["fields"]["target"], digest=refs[edge["fields"]["target"]]["digest"]
                ),
                relation="source_reference",
                rationale=CitedStatement(
                    text=edge["fields"]["label"],
                    nature="observed",
                    citations=(BoundHandle(handle=edge["reference_id"], digest=edge["digest"]),),
                ),
            )
            for edge in selected.values()
        ),
        missing=tuple(dict.fromkeys(missing)),
    )


def read(
    engine: Engine, *, context: AuthContext, project_id: UUID, ecr_id: UUID, depth: int = 3
) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_VIEW)
    _access(engine, context, project_id, Action.QUALITY_VIEW)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        from app.ai.capability_contract import resolve_capability

        snapshot = source_state(c, context.tenant.id, project_id, ecr_id, depth)
        return {
            **snapshot,
            "rollout": resolve_capability(
                "engineering_intelligence.change_work_package"
            ).rollout.value,
            "can_request": is_allowed(context.user.role, Action.CHANGE_EDIT),
            "discussion_available": all(
                resolve_capability(key).rollout.value == "live"
                for key in (
                    "engineering_intelligence.discussion_convene",
                    "engineering_intelligence.change_discussion",
                    "engineering_intelligence.discussion_followup",
                )
            ),
        }
