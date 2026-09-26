"""Frozen project cost sources and exact citation validation for model suggestions."""

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from app.ai.cost_discussion_sources import projection, references
from app.ai.executor import PromptFile
from app.ai.project_discussion_sources import actor, json_encoded
from app.contracts.cost_reduction import CostAssessment, Selection
from app.domain.product_workspace import ProductWorkError, digest

PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "cost_reduction_v1.json").read_text()
)
DISCUSSION_PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "cost_reduction_v2.json").read_text()
)


def prompt_for(snapshot: dict[str, Any]) -> PromptFile:
    return DISCUSSION_PROMPT if snapshot.get("discussion_input") else PROMPT


def version(run_context: dict[str, Any], snapshot: dict[str, Any]) -> str:
    expected = prompt_for(snapshot).version
    if run_context.get("cost_prompt_version") != expected:
        raise ProductWorkError("原成本运行提示词与资料版本不一致")
    return expected


def rebuild(c: Connection, tenant: UUID, project: UUID, snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("discussion_input")
    return source_state(
        c,
        tenant,
        project,
        Selection.model_validate(snapshot["selection"]),
        UUID(snapshot["actor_id"]),
        UUID(value["discussion_run_id"]) if value else None,
    )


encoded = json_encoded


def source_state(
    c: Connection,
    tenant: UUID,
    project: UUID,
    selection: Selection,
    actor_id: UUID,
    discussion_run_id: UUID | None = None,
) -> dict[str, Any]:
    context = actor(c, tenant, actor_id)
    chosen = [
        ("cost_gap_observation", selection.observation_id),
        *(("cost_alternative", v) for v in selection.alternative_ids),
        *(("cost_backtest", v) for v in selection.backtest_ids),
    ]
    refs = []
    limits = []
    for kind, identity in chosen:
        title, fields, omitted = projection(c, context, project, kind, identity)
        refs.extend(references(title, kind, identity, fields, omitted))
        limits.extend(omitted)
    result = {
        "project_id": str(project),
        "actor_id": str(actor_id),
        "selection": selection.model_dump(mode="json"),
        "projection_version": "cost-reduction-context.v1",
        "model_context": {
            "question": (
                "围绕所选Cost Gap提出可核对的降本备选；说明费用范围与各类代价，"
                "保留未知项和验证要求。"
            ),
            "references": refs,
            "coverage_limits": list(dict.fromkeys(limits)),
            "omitted_references": [],
        },
    }
    if discussion_run_id is not None:
        from app.ai.cost_discussion_input import model_fields, read

        discussion = read(c, context, project, discussion_run_id, selection.observation_id)
        result["discussion_input"] = discussion
        result["projection_version"] = "cost-reduction-context.v2"
        refs.extend(
            references(
                "成本多专业讨论回执",
                "cost_discussion",
                discussion_run_id,
                model_fields(discussion),
                ["讨论意见不代替原成本事实或验证结论"],
            )
        )
    if len(encoded(result)) > 140000:
        raise ProductWorkError("本次成本资料超过分析容量，请减少附加方案／回测后重新准备")
    return {**result, "digest": digest(result)}


def validate_assessment(output: CostAssessment, snapshot: dict[str, Any]) -> None:
    refs = {r["reference_id"]: r for r in snapshot["model_context"]["references"]}
    statements = list(output.observations)
    for option in output.options:
        statements.extend(
            getattr(option, k)
            for k in (
                "scope",
                "expected_cost_effect",
                "quality_impact",
                "schedule_impact",
                "supplier_impact",
                "nre_impact",
                "verification",
                "correspondence_basis",
            )
        )
    if snapshot.get("discussion_input"):
        for option in output.options:
            citations = [
                citation
                for key in (
                    "scope",
                    "expected_cost_effect",
                    "quality_impact",
                    "schedule_impact",
                    "supplier_impact",
                    "nre_impact",
                    "verification",
                    "correspondence_basis",
                )
                for citation in getattr(option, key).citations
            ]
            if not any(not v.reference_id.startswith("cost_discussion:") for v in citations):
                raise ProductWorkError("备选须有实际成本字段依据，不能仅以讨论意见作为事实")
    for statement in statements:
        for citation in statement.citations:
            ref = refs.get(citation.reference_id)
            if ref is None or ref["digest"] != citation.digest:
                raise ProductWorkError("建议引用须来自本次固定的实际成本资料")
            value: Any = ref["fields"]
            for key in citation.field_path:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                elif isinstance(value, list) and key.isdecimal() and int(key) < len(value):
                    value = value[int(key)]
                else:
                    raise ProductWorkError("引用字段不在本次实际读取范围")
            if citation.quoted_value != (value if isinstance(value, str) else encoded(value)):
                raise ProductWorkError("引用原文与固定字段不一致")
