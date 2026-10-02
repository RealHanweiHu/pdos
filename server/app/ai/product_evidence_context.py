"""Evidence and business targets bound to the immutable, authorized source pack."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.contracts.common_objects import SourceRef
from app.domain.product_workspace import ProductWorkError

VERSION = "product-evidence-v3"


def catalog(snapshot: dict[str, Any], tenant_id: UUID) -> list[dict[str, Any]]:
    return [
        dict(
            label=ref["label"],
            reference=SourceRef(
                tenant_id=tenant_id,
                kind="evidence_snapshot",
                ref_id=UUID(ref["reference_id"].split(":", 1)[1]),
                as_of=ref["fields"]["captured_at"],
                digest=ref["fields"]["content_digest"],
            ).model_dump(mode="json"),
        )
        for ref in snapshot["references"]
        if ref["reference_id"].startswith("evidence:")
    ]


def validate_refs(value: Any, snapshot: dict[str, Any], tenant_id: UUID) -> None:
    from app.contracts.product_discovery_ai import ExperimentContent, OpportunityContent
    from app.contracts.product_planning_ai import DefinitionCandidate, StrategyCandidate
    from app.contracts.product_records import FactStatement

    records = {item["reference_id"]: item["fields"] for item in snapshot["references"]}
    allowed = [item["reference"] for item in catalog(snapshot, tenant_id)]

    def visit(item: Any) -> None:
        if isinstance(item, FactStatement) and item.approval is not None:
            raise ProductWorkError("候选事实不接受批准引用")
        if isinstance(item, StrategyCandidate):
            parent = records.get(f"opportunity:{item.opportunity_id}")
            if (
                not parent
                or parent["state"] == "closed"
                or not {str(route.solution_id) for route in item.route_comparisons}.issubset(
                    {solution["id"] for solution in parent["solutions"]}
                )
            ):
                raise ProductWorkError("策略须绑定本次未关闭机会中的原比较方案")
            for constraint in item.professional_constraints:
                if constraint.work_item_id:
                    work = records.get(f"work:{constraint.work_item_id}")
                    if (
                        not work
                        or work["action_type"] not in ("discipline_review", "constraint_review")
                        or work["state"] == "cancelled"
                    ):
                        raise ProductWorkError("专业约束须关联本次已读取的有效评审工作")
            if item.supersedes_id:
                previous = records.get(f"strategy:{item.supersedes_id}")
                if not previous or previous["state"] != "published":
                    raise ProductWorkError("策略修订须引用本次已读取的已发布原版")
        if isinstance(item, DefinitionCandidate):
            product = records.get(f"product:{item.product_id}")
            strategy = records.get(f"strategy:{item.strategy_id}")
            if (
                not product
                or product["lifecycle"] == "retired"
                or not strategy
                or strategy["state"] != "published"
            ):
                raise ProductWorkError("定义须绑定本次有效产品和已发布策略")
            if product.get("derived_from") is not None and item.supersedes_id is None:
                raise ProductWorkError(
                    "派生产品首版须由人工从当前发布父定义派生并锁定父版；"
                    "请使用“从当前发布父定义派生”入口，AI候选不能代选父版"
                )
            if item.supersedes_id:
                previous = records.get(f"definition:{item.supersedes_id}")
                if (
                    not previous
                    or previous["state"] != "published"
                    or previous["product_id"] != str(item.product_id)
                ):
                    raise ProductWorkError("定义修订须引用本次同产品的已发布原版")
                if not {i["item_key"] for i in previous["content"]["items"]}.issubset(
                    {i.item_key for i in item.items}
                ):
                    raise ProductWorkError("定义修订必须保留原稳定条目标识")
        if isinstance(item, OpportunityContent):
            if f"segment:{item.segment_id}" not in records:
                raise ProductWorkError("机会须绑定本次已读取的市场细分")
            if item.parent_opportunity_id:
                parent = records.get(f"opportunity:{item.parent_opportunity_id}")
                if not parent or parent["segment_id"] != str(item.segment_id):
                    raise ProductWorkError("父机会须为本次已读取的同一细分分支")
        if isinstance(item, ExperimentContent):
            parent = records.get(f"opportunity:{item.opportunity_id}")
            if (
                not parent
                or parent["state"] == "closed"
                or str(item.solution_id) not in {solution["id"] for solution in parent["solutions"]}
            ):
                raise ProductWorkError("实验须绑定本次未关闭机会中的原方案")
        if isinstance(item, SourceRef):
            if item.model_dump(mode="json") not in allowed:
                raise ProductWorkError(
                    "候选只能引用本次已读取的原证据快照，不接受模型或客户端自造引用"
                )
        elif isinstance(item, BaseModel):
            for name in type(item).model_fields:
                visit(getattr(item, name))
        elif isinstance(item, (tuple, list)):
            for child in item:
                visit(child)

    visit(value)
