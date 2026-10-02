"""Frozen product-analysis prompt, source refresh and field-exact citation validation."""

import json
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection

from app.ai.product_work_preparation import authorize, source_state
from app.ai.project_discussion_sources import actor
from app.auth.repository import AuthContext
from app.contracts.common_objects import SourceRef
from app.contracts.product_work_ai import (
    REQUIRED_SECTIONS,
    ProductResearchAssessment,
    ProductWorkAssessment,
    ProductWorkSelection,
)
from app.domain.product_evidence import resolve_evidence
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError

MODEL_CONTEXT_VERSION = "product-work-source-adapter.v2"


class ProductPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str
    agent_key: Literal["product_management_intelligence"]
    system_prompt: str
    instruction: str


PROMPT = ProductPrompt.model_validate_json(
    (Path(__file__).with_name("prompts") / "product_work_v1.json").read_text()
)


RESEARCH_PROMPT = ProductPrompt.model_validate_json(
    (Path(__file__).with_name("prompts") / "product_research_v2.json").read_text()
)


EVIDENCE_PROMPT = ProductPrompt.model_validate_json(
    (Path(__file__).with_name("prompts") / "product_evidence_v3.json").read_text()
)


DISCOVERY_PROMPT = ProductPrompt.model_validate_json(
    (Path(__file__).with_name("prompts") / "product_discovery_v4.json").read_text()
)


LEGACY_PLANNING_PROMPT = ProductPrompt.model_validate_json(
    (Path(__file__).with_name("prompts") / "product_planning_v5.json").read_text()
)


PLANNING_PROMPT = ProductPrompt.model_validate_json(
    (Path(__file__).with_name("prompts") / "product_planning_v6.json").read_text()
)

RFQ_PROMPT = ProductPrompt.model_validate_json(
    (Path(__file__).with_name("prompts") / "product_rfq_v6.json").read_text()
)


def contract(
    version: str | None = None, *, capability: str | None = None
) -> tuple[ProductPrompt, type[ProductWorkAssessment]]:
    if version == RFQ_PROMPT.version or (version is None and capability == "rfq_requirements"):
        from app.contracts.product_rfq_ai import ProductRfqAssessment

        return RFQ_PROMPT, ProductRfqAssessment
    if version == LEGACY_PLANNING_PROMPT.version:
        from app.contracts.product_planning_ai import ProductPlanningAssessment

        return LEGACY_PLANNING_PROMPT, ProductPlanningAssessment
    if version == PLANNING_PROMPT.version or (
        version is None and capability in ("product_strategy", "product_definition")
    ):
        from app.contracts.product_planning_ai import ProductPlanningAssessment

        return PLANNING_PROMPT, ProductPlanningAssessment
    if version == DISCOVERY_PROMPT.version or (
        version is None and capability in ("opportunity_mapping", "experiment_design")
    ):
        from app.contracts.product_discovery_ai import ProductDiscoveryAssessment

        return DISCOVERY_PROMPT, ProductDiscoveryAssessment
    if version == EVIDENCE_PROMPT.version or (
        version is None and capability in ("competitor_analysis", "market_analysis")
    ):
        from app.contracts.product_evidence_ai import ProductEvidenceAssessment

        return EVIDENCE_PROMPT, ProductEvidenceAssessment
    if version == RESEARCH_PROMPT.version or (
        version is None and capability == "research_planning"
    ):
        return RESEARCH_PROMPT, ProductResearchAssessment
    if version in (None, PROMPT.version):
        return PROMPT, ProductWorkAssessment
    raise ProductWorkError("原产品分析合同版本不可用")


def key(capability: str) -> str:
    if capability not in REQUIRED_SECTIONS:
        raise ProductWorkError("不支持的产品工作能力")
    return f"product_management_intelligence.{capability}"


def model_context(
    snapshot: dict[str, Any],
    instruction: str = "",
    *,
    prompt_version: str | None = None,
    tenant_id: UUID | None = None,
) -> dict[str, Any]:
    selection = ProductWorkSelection.model_validate(snapshot["selection"])
    details = {
        "context_version": MODEL_CONTEXT_VERSION,
        "capability": selection.capability,
        "required_sections": list(REQUIRED_SECTIONS[selection.capability]),
        "warnings": snapshot["warnings"],
        "coverage_limits": snapshot["coverage_limits"],
        "user_instruction": instruction,
    }

    if prompt_version in (
        EVIDENCE_PROMPT.version,
        DISCOVERY_PROMPT.version,
        PLANNING_PROMPT.version,
        LEGACY_PLANNING_PROMPT.version,
    ):
        from app.ai.product_evidence_context import catalog

        if tenant_id is None:
            raise ProductWorkError("候选来源目录缺少服务器范围")
        details["evidence_references"] = catalog(snapshot, tenant_id)
    # Use the gateway's existing public shape, as the matrix adapter does.
    # Keep exact source fields inside each excerpt; do not widen the shared allowlist.
    return {
        "question": selection.question
        + "\n本次分析范围与要求："
        + json.dumps(details, ensure_ascii=False, sort_keys=True),
        "references": [
            {
                "reference_id": ref["reference_id"],
                "entity": "product_work",
                "label": ref["label"],
                "excerpt": json.dumps(
                    {"digest": ref["digest"], "fields": ref["fields"]},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
            for ref in snapshot["references"]
        ],
    }


def readable(c: Connection, context: AuthContext, snapshot: dict[str, Any]) -> None:
    if snapshot["actor_id"] != str(context.user.id):
        raise ProductWorkAccessError("分析仅供原发起人读取")
    selection = ProductWorkSelection.model_validate(snapshot["selection"])
    space_id = UUID(snapshot["market_space_id"])
    authorize(c, context, space_id, selection.product_line_id)
    # Re-read all selected records and embedded citations, not merely the space membership.
    source_state(c, context, space_id, selection)
    original = tuple(
        SourceRef(
            tenant_id=context.tenant.id,
            kind="evidence_snapshot",
            ref_id=UUID(ref["reference_id"].split(":", 1)[1]),
            as_of=ref["fields"]["captured_at"],
            digest=ref["fields"]["content_digest"],
        )
        for ref in snapshot["references"]
        if ref["reference_id"].startswith("evidence:")
    )
    resolve_evidence(c, context, original)


def rebuild(c: Connection, tenant_id: UUID, snapshot: dict[str, Any]) -> dict[str, Any]:
    context = actor(c, tenant_id, UUID(snapshot["actor_id"]))
    return source_state(
        c,
        context,
        UUID(snapshot["market_space_id"]),
        ProductWorkSelection.model_validate(snapshot["selection"]),
        private_link_version=snapshot.get("private_attachment_link_version", "legacy"),
    )


def validate_assessment(output: ProductWorkAssessment, snapshot: dict[str, Any]) -> None:
    if output.capability != snapshot["selection"]["capability"]:
        raise ProductWorkError("分析能力与原请求不一致")
    refs = {ref["reference_id"]: ref for ref in snapshot["references"]}
    statements = [*output.summary, *output.next_steps]
    for section in output.sections:
        statements.extend(section.statements)
    from app.contracts.product_rfq_ai import ProductRfqAssessment

    if isinstance(output, ProductRfqAssessment):
        statements.extend(item.basis for item in output.requirements)
    validate_statements(statements, refs)
    if output.capability == "market_analysis":
        sizing = next(section for section in output.sections if section.key == "market_size")
        for statement in sizing.statements:
            if statement.nature != "hypothesis" and not any(
                citation.reference_id.startswith("segment:")
                and citation.field_path[0] == "sizing_result"
                for citation in statement.citations
            ):
                raise ProductWorkError("市场规模结论须引用原确定性计算；缺失时只列待验证假设或缺项")


def validate_statements(statements: Any, refs: dict[str, Any]) -> None:
    for statement in statements:
        for citation in statement.citations:
            ref = refs.get(citation.reference_id)
            if ref is None or citation.digest != ref["digest"]:
                raise ProductWorkError("分析引用不是本次固定来源")
            value = ref["fields"]
            for part in citation.field_path:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
                    value = value[int(part)]
                else:
                    raise ProductWorkError("分析引用字段未在本次读取范围内")
            encoded = (
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, sort_keys=True)
            )
            excerpt = (
                (
                    (
                        citation.reference_id.startswith("evidence:")
                        and tuple(citation.field_path) == ("content",)
                    )
                    or (
                        citation.reference_id.startswith("file:")
                        and tuple(citation.field_path) == ("text",)
                    )
                )
                and isinstance(value, str)
                and citation.quoted_value in value
            )
            if citation.quoted_value != encoded and not excerpt:
                raise ProductWorkError("分析引用内容与原字段不一致")
