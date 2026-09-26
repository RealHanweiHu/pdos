"""Versioned test baselines and deterministic, evidence-backed item coverage."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, select

from app.db.schema import tables

PENDING_TEMPLATE_MESSAGE = "当前产品类型的测试模板尚待专业确认；可准备差异候选或手工录入测试计划"

CATALOG_PATH = Path(__file__).with_suffix("")


class TemplateError(ValueError):
    pass


class Exclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class TemplateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    template_id: str = Field(min_length=1, max_length=128)
    version: int = Field(gt=0)
    product_type: str = Field(min_length=1, max_length=128)
    exclusions: list[Exclusion] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_exclusions(self) -> TemplateSelection:
        if len({item.key for item in self.exclusions}) != len(self.exclusions):
            raise ValueError("duplicate exclusions")
        return self


def catalog() -> list[dict[str, Any]]:
    # Catalog data has methods/criteria only. Never load a supplied path or
    # infer product type from a model code or an Excel layout fingerprint.
    return [json.loads(path.read_text()) for path in sorted(CATALOG_PATH.glob("*.json"))]


def template_snapshot(selection: TemplateSelection, actor_user_id: UUID) -> dict[str, Any]:
    template = next(
        (
            item
            for item in catalog()
            if item["id"] == selection.template_id and item["version"] == selection.version
        ),
        None,
    )
    if template is None or template["product_type"] != selection.product_type:
        raise TemplateError("模板版本与产品类型不匹配")
    keys = {item["key"] for item in template["items"]}
    if len(keys) != len(template["items"]):
        raise TemplateError("模板存在重复测试项标识")
    exclusions = {item.key: item.reason for item in selection.exclusions}
    if exclusions.keys() - keys:
        raise TemplateError("不适用项不在所选模板中")
    if all(item["key"] in exclusions for item in template["items"] if item["required"]):
        raise TemplateError("不能将全部必测项设为不适用")
    digest = hashlib.sha256(
        json.dumps(template, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return {
        **template,
        "digest": digest,
        "confirmed_by_user_id": str(actor_user_id),
        "confirmed_at": datetime.now(UTC).isoformat(),
        "items": [
            {
                **item,
                "applicable": item["key"] not in exclusions,
                "exclusion_reason": exclusions.get(item["key"]),
            }
            for item in template["items"]
        ],
    }


def instantiate_cases(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    plan_id: UUID,
    actor_user_id: UUID,
    snapshot: dict[str, Any],
) -> None:
    for item in snapshot["items"]:
        if not item["applicable"]:
            continue
        specification_id = UUID(item["specification_id"]) if item.get("specification_id") else None
        if (
            specification_id is not None
            and connection.execute(
                select(tables.specifications.c.id).where(
                    tables.specifications.c.tenant_id == tenant_id,
                    tables.specifications.c.project_id == project_id,
                    tables.specifications.c.id == specification_id,
                )
            ).scalar_one_or_none()
            is None
        ):
            raise TemplateError("继承的规格验证关系已不属于当前项目，请重新核对")
        connection.execute(
            tables.test_cases.insert().values(
                id=uuid4(),
                tenant_id=tenant_id,
                project_id=project_id,
                plan_id=plan_id,
                created_by_user_id=actor_user_id,
                title=item["title"],
                category=item["category"],
                acceptance_criteria=item["acceptance_criteria"],
                method=item["method"],
                severity="major",
                template_item_key=item["key"],
                specification_id=specification_id,
            )
        )


def coverage(
    snapshot: dict[str, Any] | None,
    cases: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    if snapshot is None:
        return {
            "status": "unconfigured",
            "required": None,
            "covered": None,
            "coverage_percent": None,
            "items": [],
        }
    by_key = {
        case.get("template_item_key"): case for case in cases if case.get("template_item_key")
    }
    latest: dict[UUID, dict[str, Any]] = {}
    for run in runs:
        if run["draft_state"] != "confirmed":
            continue
        case_id = run["test_case_id"]
        if case_id not in latest or run["run_number"] > latest[case_id]["run_number"]:
            latest[case_id] = run
    items = []
    for item in snapshot["items"]:
        case = by_key.get(item["key"])
        latest_run = latest.get(case["id"]) if case else None
        state = "missing_case" if case is None else "missing_evidence"
        if not item["applicable"]:
            state = "not_applicable"
        # A manual reset or newer case decision invalidates older evidence.
        elif (
            latest_run
            and latest_run["evidence_document_id"]
            and latest_run["status"] in {"passed", "failed"}
            and case
            and case["status"] == latest_run["status"]
            and case["updated_at"] <= latest_run["updated_at"]
        ):
            state = latest_run["status"]
        items.append(
            {
                "key": item["key"],
                "title": item["title"],
                "required": item["required"],
                "state": state,
                "reason": item["exclusion_reason"],
                "case_id": str(case["id"]) if case else None,
                "evidence_document_id": str(latest_run["evidence_document_id"])
                if latest_run and latest_run["evidence_document_id"]
                else None,
            }
        )
    required = [item for item in items if item["required"] and item["state"] != "not_applicable"]
    covered = sum(item["state"] in {"passed", "failed"} for item in required)
    return {
        "status": "configured",
        "template_name": snapshot["name"],
        "version": snapshot["version"],
        "required": len(required),
        "covered": covered,
        "passed": sum(item["state"] == "passed" for item in required),
        "failed": sum(item["state"] == "failed" for item in required),
        "missing": len(required) - covered,
        "not_applicable": sum(item["state"] == "not_applicable" for item in items),
        "coverage_percent": round(100 * covered / len(required), 1) if required else None,
        "items": items,
    }


def plan_coverage(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, plan: dict[str, Any]
) -> dict[str, Any]:
    cases = [
        dict(row)
        for row in connection.execute(
            select(tables.test_cases).where(
                tables.test_cases.c.tenant_id == tenant_id,
                tables.test_cases.c.project_id == project_id,
                tables.test_cases.c.plan_id == plan["id"],
            )
        ).mappings()
    ]
    runs = (
        [
            dict(row)
            for row in connection.execute(
                select(tables.test_runs).where(
                    tables.test_runs.c.tenant_id == tenant_id,
                    tables.test_runs.c.project_id == project_id,
                    tables.test_runs.c.test_case_id.in_([case["id"] for case in cases]),
                )
            ).mappings()
        ]
        if cases
        else []
    )
    return {
        **coverage(plan["template_snapshot"], cases, runs),
        **project_test_scope_status(
            connection, tenant_id=tenant_id, project_id=project_id, plan=plan
        ),
    }


def project_template_snapshot(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    selection: TemplateSelection,
    actor_user_id: UUID,
) -> dict[str, Any]:
    """Apply confirmed product features when creating a new test-plan version."""
    from app.domain.project_templates import active_version

    active = active_version(connection, tenant_id=tenant_id, project_id=project_id)
    if active is None:
        return template_snapshot(selection, actor_user_id)
    configuration = active["snapshot"]
    profile = configuration.get("test_profile")
    if profile is None:
        raise TemplateError("当前产品类型尚无已确认测试模板，请先准备该类型的测试差异候选")
    if (selection.template_id, selection.version, selection.product_type) != (
        profile["template_id"],
        profile["version"],
        profile["product_type"],
    ):
        raise TemplateError("测试模板不匹配项目已确认的产品类型及版本")
    exclusions = {item.key: item for item in selection.exclusions}
    for key, feature in profile.get("feature_requirements", {}).items():
        if not configuration["feature_values"][feature]:
            exclusions[key] = Exclusion(key=key, reason=f"项目产品配置确认不含功能：{feature}")
        elif key in exclusions:
            raise TemplateError("项目已确认启用的功能不能作为不适用项跳过")
    snapshot = template_snapshot(
        selection.model_copy(update={"exclusions": list(exclusions.values())}), actor_user_id
    )
    snapshot["project_template_version_id"] = str(active["id"])
    snapshot["product_features"] = configuration["feature_values"]
    snapshot["project_template_digest"] = active["digest"]
    return snapshot


def project_catalog(connection: Connection, *, tenant_id: UUID, project_id: UUID) -> dict[str, Any]:
    from app.domain.project_templates import active_version

    active = active_version(connection, tenant_id=tenant_id, project_id=project_id)
    if active is None:
        return {
            "templates": catalog(),
            "product_scope_message": "尚未采用项目产品模板，请核对产品类型和适用项",
        }
    profile = active["snapshot"].get("test_profile")
    if profile is None:
        return {
            "templates": [],
            "product_scope_message": PENDING_TEMPLATE_MESSAGE,
        }
    items = [
        item
        for item in catalog()
        if item["id"] == profile["template_id"]
        and item["version"] == profile["version"]
        and item["product_type"] == profile["product_type"]
    ]
    for item in items:
        item["locked_exclusions"] = {
            key: f"项目产品配置确认不含功能：{feature}"
            for key, feature in profile.get("feature_requirements", {}).items()
            if not active["snapshot"]["feature_values"][feature]
        }
        item["required_enabled"] = [
            key
            for key, feature in profile.get("feature_requirements", {}).items()
            if active["snapshot"]["feature_values"][feature]
        ]
    return {
        "templates": items,
        "product_scope_message": f"使用项目已确认产品配置 v{active['revision']}",
    }


def project_test_scope_status(
    connection: Connection, *, tenant_id: UUID, project_id: UUID, plan: Any
) -> dict[str, str]:
    from app.domain.project_templates import active_version

    active = active_version(connection, tenant_id=tenant_id, project_id=project_id)
    if active is None:
        return {"scope_status": "unconfigured", "scope_message": "项目产品范围尚未版本化"}
    profile = active["snapshot"].get("test_profile")
    snapshot = plan["template_snapshot"] or {}
    compatible = (
        profile is not None
        and all(snapshot.get(key) == profile.get(key) for key in ("version", "product_type"))
        and snapshot.get("id") == profile["template_id"]
    )
    if compatible:
        by_key = {item["key"]: item for item in snapshot.get("items", [])}
        compatible = all(
            key in by_key
            and bool(by_key[key]["applicable"]) == active["snapshot"]["feature_values"][feature]
            for key, feature in profile.get("feature_requirements", {}).items()
        )
    return {
        "scope_status": "current" if compatible else "changed",
        "scope_message": "测试适用性匹配当前产品范围"
        if compatible
        else "产品类型或功能范围已变化，需审阅测试差异并建立新版本",
    }
