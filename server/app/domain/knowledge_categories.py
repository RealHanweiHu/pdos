"""Human-confirmed classes for reusable knowledge, separate from source tags."""

from typing import Literal

KnowledgeKind = Literal["design_rule", "failure_case", "supplier_experience", "benchmark"]
KNOWLEDGE_KINDS = frozenset({"design_rule", "failure_case", "supplier_experience", "benchmark"})
KNOWLEDGE_KIND_LABELS = {
    "design_rule": "设计规则",
    "failure_case": "失败案例",
    "supplier_experience": "供应商经验",
    "benchmark": "对标资料",
}


class KnowledgeClassificationError(ValueError):
    pass


def require_knowledge_kind(kind: object) -> None:
    if not isinstance(kind, str) or kind not in KNOWLEDGE_KINDS:
        raise KnowledgeClassificationError(
            "请先将候选归入设计规则、失败案例、供应商经验或对标资料，再提交审核"
        )
