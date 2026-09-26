"""Pre-project product matrix facts; explicit scope, omissions and field citations."""

from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, select

from app.ai.project_discussion_sources import actor, json_encoded
from app.auth.repository import AuthContext
from app.contracts.product_matrix_explanation import (
    MatrixExplanationSelection,
    ProductMatrixExplanation,
)
from app.db.schema import tables
from app.domain.product_matrix_records import read_view, record_row
from app.domain.product_roadmap import latest_rows
from app.domain.product_roadmap import source as roadmap_source
from app.domain.product_roadmap import view as roadmap_view
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _space,
    digest,
)

PROJECTION = "product-matrix-context.v1"


class MatrixPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = Field(min_length=1, max_length=128)
    agent_key: Literal["product_management_intelligence"]
    system_prompt: str = Field(min_length=1, max_length=100000)
    instruction: str = Field(min_length=1, max_length=100000)


PROMPT = MatrixPrompt.model_validate_json(
    (Path(__file__).with_name("prompts") / "product_matrix_v1.json").read_text()
)


def prompt_for(snapshot: dict[str, Any]) -> MatrixPrompt:
    if snapshot["projection_version"] != PROJECTION:
        raise ProductWorkError("原产品矩阵资料版本不可用")
    return PROMPT


def version(run_context: dict[str, Any], snapshot: dict[str, Any]) -> str:
    expected = prompt_for(snapshot).version
    if run_context.get("matrix_prompt_version") != expected:
        raise ProductWorkError("原矩阵运行版本不一致")
    return expected


def model_context(snapshot: dict[str, Any], instruction: str) -> dict[str, Any]:
    context = snapshot["model_context"]
    return {
        "question": context["question"]
        + "\n读取范围与限制："
        + json_encoded(
            {
                "coverage_limits": context["coverage_limits"],
                "omitted_references": context["omitted_references"],
            }
        )
        + ("\n本次用户要求：" + instruction if instruction else ""),
        "references": [
            {
                "reference_id": ref["reference_id"],
                "entity": "product_matrix",
                "label": ref["label"],
                "excerpt": json_encoded(
                    {k: ref[k] for k in ("digest", "fields", "omitted_fields")}
                ),
            }
            for ref in context["references"]
        ],
    }


def readable(c: Connection, context: AuthContext, snapshot: dict[str, Any]) -> None:
    if snapshot["actor_id"] != str(context.user.id):
        raise ProductWorkAccessError("本次矩阵分析资料仅供原发起人读取")
    space = UUID(snapshot["market_space_id"])
    _space(c, context, space)
    record_row(c, context, space, UUID(snapshot["selection"]["record_id"]))


def source_state(
    c: Connection, context: AuthContext, space_id: UUID, selection: MatrixExplanationSelection
) -> dict[str, Any]:
    _space(c, context, space_id)
    saved = read_view(c, context, space_id, record_row(c, context, space_id, selection.record_id))
    result = saved["result"]
    original = result["snapshot"]
    products = {item["id"]: item for item in original["products"]}
    criterion_keys = [item["criterion"]["key"] for item in result["criteria"]]
    refs: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []

    def reference(key: str, label: str, fields: dict[str, Any], href: str | None = None) -> None:
        refs.append(
            {
                "reference_id": f"matrix:{saved['id']}:{key}",
                "label": label,
                "fields": fields,
                "digest": digest(fields),
                "href": href,
                "omitted_fields": [],
            }
        )

    reference(
        "record",
        "原对照范围、规则与当前来源状态",
        {
            "record_id": saved["id"],
            "record_version": saved["version"],
            "title": saved["title"],
            "actor_name": saved["actor_name"],
            "recorded_at": saved["created_at"],
            "reason": saved["reason"],
            "result_digest": saved["result_digest"],
            "formula_version": saved["formula_version"],
            "scope": result["scope"],
            "formula": result["formula"],
            "input_digest": result["input_digest"],
            "product_ids": list(products),
            "criterion_keys": criterion_keys,
            "source_changes": saved["source_changes"],
            "current_source_warnings": saved["current_source_warnings"],
        },
    )
    used_facts = {item["criterion"]["source_locator"] for item in result["criteria"]}
    reference(
        "market",
        "原市场细分与已选需求",
        {
            "segment": original["segment"],
            "facts": [item for item in original["facts"] if item["locator"] in used_facts],
            "source_warnings_at_calculation": original["source_warnings"],
        },
    )
    omitted_facts = [
        item["locator"] for item in original["facts"] if item["locator"] not in used_facts
    ]
    if omitted_facts:
        omissions.append(
            {
                "kind": "market_facts",
                "locators": omitted_facts,
                "reason": "原对照未选作判据，模型未读取正文",
            }
        )
    for product_id, product in products.items():
        mapped = {
            mapping["item_key"]
            for item in result["criteria"]
            if item["criterion"]["mode"] == "numeric_spec"
            for mapping in item["criterion"]["mappings"]
            if mapping["product_id"] == product_id
        }
        content = product["content"]
        omitted_items = [
            item["item_key"] for item in content["items"] if item["item_key"] not in mapped
        ]
        if omitted_items:
            omissions.append(
                {
                    "kind": "unmapped_specifications",
                    "product_id": product_id,
                    "item_keys": omitted_items,
                    "reason": "不属于本次人工对应范围，模型未读取原规格正文",
                }
            )
        reference(
            f"product:{product_id}",
            f"{product['code']} · {product['name']} · 原发布定义",
            {
                **{
                    key: product[key]
                    for key in (
                        "id",
                        "code",
                        "name",
                        "level",
                        "lifecycle",
                        "regions",
                        "channels",
                        "path",
                        "definition_id",
                        "definition_revision",
                        "release_id",
                        "released_at",
                        "definition_digest",
                    )
                },
                "definition": {
                    key: content[key]
                    for key in (
                        "target_users",
                        "scenarios",
                        "included_features",
                        "excluded_features",
                        "target_cost",
                        "price_position",
                        "launch_window",
                        "region_constraints",
                        "service_requirements",
                        "success_criteria",
                    )
                },
                "mapped_specifications": [
                    item for item in content["items"] if item["item_key"] in mapped
                ],
                "coverage_totals": next(
                    item for item in result["product_summary"] if item["product_id"] == product_id
                ),
                "source_warnings_at_calculation": product["source_warnings"],
            },
            product["href"],
        )
    for item in result["criteria"]:
        # Full mapped specification details appear once in each product reference.
        fields = {
            key: item[key]
            for key in ("criterion", "market_fact", "counts", "selected_portfolio_status")
        }
        fields["cells"] = [
            {
                key: cell[key]
                for key in ("product_id", "status", "item_key", "source_path", "reason")
            }
            for cell in item["cells"]
        ]
        reference(
            f"criterion:{digest(item['criterion']['key'])[:24]}",
            f"原判据 · {item['criterion']['interpretation']}",
            fields,
        )
    reference("overlap", "引擎记录的共同匹配判据", {"pairs": result["overlap"]})
    selected_products: set[str] = set()
    for identity in selection.roadmap_ids:
        t = tables.product_roadmap_revisions
        row = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.market_space_id == space_id,
                    t.c.id == identity,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or str(row["product_id"]) not in products:
            raise ProductWorkAccessError("所选路线图不属于原对照的可读产品范围")
        product_id = str(row["product_id"])
        if product_id in selected_products:
            raise ProductWorkError("每个产品本次只能选择一个路线图版本")
        selected_products.add(product_id)
        _, current = roadmap_source(c, context, space_id, row["product_id"])
        roadmap = roadmap_view(c, context, row, current)
        reference(
            f"roadmap:{identity}",
            f"{products[product_id]['code']} · 路线图 v{row['version']}",
            {
                **{
                    key: roadmap[key]
                    for key in (
                        "id",
                        "product_id",
                        "version",
                        "state",
                        "body",
                        "source_snapshot",
                        "source_digest",
                        "actor_name",
                        "created_at",
                        "reason",
                        "source_current",
                        "source_warnings",
                    )
                },
                "matches_saved_definition": str(row["release_id"])
                == products[product_id]["release_id"],
            },
            f"/product-work?space={space_id}&tab=matrix&roadmap_product={product_id}#product-roadmap",
        )
    limits = [
        "解释具名保存的历史对照，不替代现行产品定义或路线图发布。",
        "声明覆盖和标称目标匹配不代表实测质量、验证通过、销量或市场份额。",
        "蚕食和平台复用只能提出待验证假设，不补算分数、概率、金额或收益。",
        "当前来源变化与原计算结果分列，停用/过期来源须重新核对。",
        "路线图为具名计划；与原定义不一致的路线图不能推定同版产品安排。",
        "产品未立项不阻止本次资料读取；未读取工程实测、ERP/PLM主数据或实际上市反馈。",
    ]
    missing_roadmaps = sorted(set(products) - selected_products)
    if missing_roadmaps:
        omissions.append(
            {
                "kind": "unselected_roadmaps",
                "product_ids": missing_roadmaps,
                "reason": "本次未选择路线图；不据此判断产品没有计划",
            }
        )
    value = {
        "market_space_id": str(space_id),
        "actor_id": str(context.user.id),
        "selection": selection.model_dump(mode="json"),
        "projection_version": PROJECTION,
        "record_result_digest": saved["result_digest"],
        "product_ids": list(products),
        "criterion_keys": criterion_keys,
        "model_context": {
            "question": "解释所选市场对照的产品定位、声明缺口与重叠，并提出有依据的复用/补证假设。",
            "references": refs,
            "coverage_limits": limits,
            "omitted_references": omissions,
        },
    }
    if len(json_encoded(value)) > 240000:
        raise ProductWorkError(
            "本次完整资料超出分析容量，请缩小判据/产品范围保存新对照或减少选入路线图；未静默截断"
        )
    return {**value, "digest": digest(value)}


def rebuild(c: Connection, tenant_id: UUID, snapshot: dict[str, Any]) -> dict[str, Any]:
    context = actor(c, tenant_id, UUID(snapshot["actor_id"]))
    readable(c, context, snapshot)
    return source_state(
        c,
        context,
        UUID(snapshot["market_space_id"]),
        MatrixExplanationSelection.model_validate(snapshot["selection"]),
    )


def validate_assessment(output: ProductMatrixExplanation, snapshot: dict[str, Any]) -> None:
    refs = {ref["reference_id"]: ref for ref in snapshot["model_context"]["references"]}
    prefix = f"matrix:{snapshot['selection']['record_id']}:"
    if {str(item.product_id) for item in output.products} != set(snapshot["product_ids"]):
        raise ProductWorkError("矩阵解释须完整对应全部所选产品")
    if {item.criterion_key for item in output.criteria} != set(snapshot["criterion_keys"]):
        raise ProductWorkError("矩阵解释须完整对应全部原判据")
    statements = list(output.summary)
    for item in output.products:
        for statement in (item.positioning, item.coverage):
            if not any(
                citation.reference_id == f"{prefix}product:{item.product_id}"
                for citation in statement.citations
            ):
                raise ProductWorkError("产品定位与覆盖须引用该产品原字段")
            statements.append(statement)
    for criterion in output.criteria:
        if not any(
            citation.reference_id == f"{prefix}criterion:{digest(criterion.criterion_key)[:24]}"
            for citation in criterion.explanation.citations
        ):
            raise ProductWorkError("判据解释须引用该项原计算")
        statements.extend([criterion.explanation, *criterion.human_next_steps])
    for hypothesis in (*output.positioning_hypotheses, *output.platform_reuse_hypotheses):
        if not {str(identity) for identity in hypothesis.product_ids} <= set(
            snapshot["product_ids"]
        ):
            raise ProductWorkError("定位/复用假设不能引入本次未读产品")
        if not all(
            any(
                citation.reference_id == f"{prefix}product:{identity}"
                for citation in hypothesis.hypothesis.citations
            )
            for identity in hypothesis.product_ids
        ):
            raise ProductWorkError("定位/复用假设须分别引用所有相关产品")
        statements.append(hypothesis.hypothesis)
    for statement in statements:
        for citation in statement.citations:
            ref = refs.get(citation.reference_id)
            if ref is None or ref["digest"] != citation.digest:
                raise ProductWorkError("引用不是本次固定读取资料")
            value = ref["fields"]
            for key in citation.field_path:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                elif isinstance(value, list) and key.isdecimal() and int(key) < len(value):
                    value = value[int(key)]
                else:
                    raise ProductWorkError("引用字段超出实际读取范围")
            if citation.quoted_value != (value if isinstance(value, str) else json_encoded(value)):
                raise ProductWorkError("引用值与原字段不一致")


class ProductMatrixPreparationService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def options(self, context: AuthContext, space_id: UUID, record_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            _space(c, context, space_id)
            saved = record_row(c, context, space_id, record_id)
            products = saved["result"]["snapshot"]["products"]
            latest = latest_rows(c, context.tenant.id, [UUID(item["id"]) for item in products])
            return {
                "record_id": str(record_id),
                "title": saved["title"],
                "products": [
                    {
                        "product_id": item["id"],
                        "code": item["code"],
                        "name": item["name"],
                        "roadmap": _plain(latest[item["id"]]) if item["id"] in latest else None,
                    }
                    for item in products
                ],
            }

    def read(
        self, context: AuthContext, space_id: UUID, selection: MatrixExplanationSelection
    ) -> dict[str, Any]:
        from app.ai.capability_contract import resolve_capability
        from app.ai.product_matrix_runs import KEY, authorize

        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            snapshot = source_state(c, context, space_id, selection)
            can_request = False
            try:
                authorize(c, context, space_id, selection.record_id, write=True)
                can_request = True
            except (ValueError, LookupError, PermissionError):
                pass
            rollout = resolve_capability(KEY).rollout.value
            return {
                **snapshot,
                "status": "prepared",
                "prompt_version": PROMPT.version,
                "can_request": can_request,
                "rollout": rollout,
                "generation_available": can_request and rollout == "live",
                "generation_message": "可根据本次固定资料生成分析"
                if rollout == "live" and can_request
                else "可准备资料及回查本人原运行；模型生成待阶段评测和当前范围授权",
            }
