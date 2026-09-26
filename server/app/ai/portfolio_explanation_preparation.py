"""Full saved portfolio facts, current access and exact field citations."""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from app.ai.executor import PromptFile
from app.ai.project_discussion_sources import actor, json_encoded
from app.contracts.portfolio_explanation import PortfolioExplanation, Selection
from app.domain.portfolio_comparisons import readable
from app.domain.portfolio_selections import comparison, recheck_comparison
from app.domain.product_workspace import ProductWorkError, digest

PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "portfolio_explanation_v1.json").read_text()
)
encoded = json_encoded


def prompt_for(snapshot: dict[str, Any]) -> PromptFile:
    if snapshot["projection_version"] != "portfolio-explanation-context.v1":
        raise ProductWorkError("原组合解释资料版本不可用")
    return PROMPT


def version(run_context: dict[str, Any], snapshot: dict[str, Any]) -> str:
    expected = prompt_for(snapshot).version
    if run_context.get("portfolio_prompt_version") != expected:
        raise ProductWorkError("原组合解释运行版本不一致")
    return expected


def source_state(
    c: Connection, tenant: UUID, project: UUID, selection: Selection, actor_id: UUID
) -> dict[str, Any]:
    context = actor(c, tenant, actor_id)
    saved = comparison(c, context, selection.comparison_id)
    readable(c, context, saved["inputs"])
    projects = sorted(UUID(p["project_id"]) for p in saved["inputs"]["projects"])
    if project != projects[0]:
        raise ProductWorkError("组合解释须绑定原比较的固定项目范围")
    snapshot = saved["snapshot"]
    try:
        recheck_comparison(c, context, saved)
        source_now: dict[str, Any] = {"current": True, "reason": None}
    except ProductWorkError as error:
        source_now = {"current": False, "reason": str(error)}
    refs = []

    def reference(key: str, label: str, fields: dict[str, Any]) -> None:
        refs.append(
            {
                "reference_id": f"portfolio:{saved['id']}:{key}",
                "label": label,
                "fields": fields,
                "digest": digest(fields),
                "omitted_fields": [],
            }
        )

    reference(
        "policy",
        "原评分政策、公式与比较范围",
        {
            "comparison_id": str(saved["id"]),
            "comparison_digest": saved["payload_digest"],
            "comparison_at": snapshot["comparison_at"],
            "policy": snapshot["policy"],
            "projects": snapshot["projects"],
            "project_weights": saved["inputs"]["projects"],
            "calendars": snapshot["calendars"],
            "calculation": {k: v for k, v in snapshot["result"].items() if k != "alternatives"},
            "source_now": source_now,
        },
    )
    for alternative in snapshot["result"]["alternatives"]:
        reference(alternative["key"], alternative["title"], alternative)
    limits = ["解释固定历史比较，不代表当前批准、预约、基线或承诺；质量风险为具名假设。"]
    if not source_now["current"]:
        limits.append("当前来源或政策已变化，采用前须重新比较；原比较数值保持历史含义。")
    result = {
        "project_id": str(project),
        "project_ids": [str(p) for p in projects],
        "actor_id": str(actor_id),
        "selection": selection.model_dump(mode="json"),
        "comparison_digest": saved["payload_digest"],
        "source_now": source_now,
        "projection_version": "portfolio-explanation-context.v1",
        "model_context": {
            "question": "解释所选组合比较的全部方案差异、取舍、假设与不可行或缺数原因。",
            "references": refs,
            "coverage_limits": limits,
            "omitted_references": [],
        },
    }
    if len(encoded(result)) > 140000:
        raise ProductWorkError(
            "完整组合资料超出本次解释容量，请缩小比较范围后保存新比较；未截断原资料"
        )
    return {**result, "digest": digest(result)}


def rebuild(c: Connection, tenant: UUID, project: UUID, snapshot: dict[str, Any]) -> dict[str, Any]:
    return source_state(
        c,
        tenant,
        project,
        Selection.model_validate(snapshot["selection"]),
        UUID(snapshot["actor_id"]),
    )


def validate_assessment(output: PortfolioExplanation, snapshot: dict[str, Any]) -> None:
    refs = {r["reference_id"]: r for r in snapshot["model_context"]["references"]}
    originals = {r["fields"]["key"]: r for r in refs.values() if "key" in r["fields"]}
    if {v.alternative_key for v in output.alternatives} != set(originals):
        raise ProductWorkError("解释须完整对应原比较的全部方案")
    statements = list(output.observations)
    for option in output.alternatives:
        original = originals[option.alternative_key]
        for field in ("eligibility", "time", "cost", "quality", "capacity"):
            statement = getattr(option, field)
            if not any(c.reference_id == original["reference_id"] for c in statement.citations):
                raise ProductWorkError("各维度解释须引用对应原方案，不能借用其他方案的分数或依据")
            statements.append(statement)
        statements.extend(option.tradeoffs)
    for statement in statements:
        for citation in statement.citations:
            ref = refs.get(citation.reference_id)
            if ref is None or ref["digest"] != citation.digest:
                raise ProductWorkError("解释引用不属于原固定资料")
            value = ref["fields"]
            for key in citation.field_path:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                elif isinstance(value, list) and key.isdecimal() and int(key) < len(value):
                    value = value[int(key)]
                else:
                    raise ProductWorkError("解释引用字段不在本次实际读取范围")
            if citation.quoted_value != (value if isinstance(value, str) else encoded(value)):
                raise ProductWorkError("解释引用值与原字段不符")
