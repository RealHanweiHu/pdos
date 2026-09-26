"""Typed supplemental Risk fields, pinned by the project's creation template."""

import math
from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.process_template_fields import TemplateFieldError


class RiskField(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=200)
    label_en: str = Field(min_length=1, max_length=200)
    help_text: str = Field(default="", max_length=2000)
    kind: Literal["text", "number", "boolean", "date", "choice"]
    required_at: Literal["response", "closed"] | None = None
    choices: list[str] = Field(default_factory=list, max_length=50)
    max_length: int = Field(default=2000, ge=1, le=5000)
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = Field(default="", max_length=50)

    @model_validator(mode="after")
    def valid_definition(self) -> "RiskField":
        if self.key in {
            "id",
            "tenant_id",
            "project_id",
            "title",
            "description",
            "status",
            "owner_user_id",
            "likelihood",
            "impact",
            "score",
            "mitigation_plan",
            "contingency_plan",
            "target_date",
            "closed_at",
            "draft_state",
            "origin_key",
            "rule_key",
            "source_entity",
            "source_entity_id",
            "source_finding_id",
            "dismissed_at",
            "created_at",
            "updated_at",
            "template_fields",
        }:
            raise ValueError("补充字段不能替代风险的现有业务字段")
        if self.kind == "choice":
            self.choices = [item.strip() for item in self.choices]
            if (
                not self.choices
                or len(set(self.choices)) != len(self.choices)
                or any(not item or len(item) > 200 for item in self.choices)
            ):
                raise ValueError("选项须非空、不重复且不超过200字")
        elif self.choices:
            raise ValueError("只有选项字段可以配置候选值")
        if self.kind != "number" and (
            self.minimum is not None or self.maximum is not None or self.unit
        ):
            raise ValueError("只有数值字段可以配置范围和单位")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("字段数值下限不能大于上限")
        return self


def definitions(snapshot: dict[str, Any]) -> list[RiskField]:
    fields = [RiskField.model_validate(item) for item in snapshot.get("risk_fields", [])]
    if len(fields) > 30 or len({item.key for item in fields}) != len(fields):
        raise TemplateFieldError("风险补充字段最多30项，标识不能重复")
    return fields


def project_fields(
    c: Connection, tenant: UUID, project: UUID
) -> tuple[list[RiskField], dict[str, Any] | None]:
    v = tables.project_template_versions
    row = (
        c.execute(
            select(v).where(
                v.c.tenant_id == tenant,
                v.c.project_id == project,
                v.c.revision == 1,
                v.c.status.in_(("active", "superseded")),
                v.c.difference["adoption_scope"].as_string() == "project_creation",
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return [], None
    return definitions(row["snapshot"]), {
        "project_template_version_id": str(row["id"]),
        "template_id": row["template_id"],
        "template_version": row["template_version"],
        "template_digest": row["digest"],
    }


def validate_values(fields: list[RiskField], values: object, status: str) -> dict[str, Any]:
    if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
        raise TemplateFieldError("补充字段内容必须是按字段标识保存的对象")
    known = {field.key for field in fields}
    if values.keys() - known:
        raise TemplateFieldError("包含当前项目模板未定义的补充字段，请重新读取表单")
    ranks = {"open": 0, "response": 1, "mitigating": 1, "watching": 1, "closed": 2}
    normalized: dict[str, Any] = {}
    for field in fields:
        value = values.get(field.key)
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            if field.required_at and ranks[status] >= ranks[field.required_at]:
                checkpoint = {"response": "处理或观察", "closed": "关闭"}[field.required_at]
                raise TemplateFieldError(
                    f"请填写“{field.label}”，此项在进入{checkpoint}时必填",
                    field_key=field.key,
                    kind="missing",
                )
            continue
        valid = True
        if field.kind == "text":
            valid = isinstance(value, str) and len(value) <= field.max_length
        elif field.kind == "choice":
            valid = isinstance(value, str) and value in field.choices
        elif field.kind == "boolean":
            valid = isinstance(value, bool)
        elif field.kind == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    valid = (
                        math.isfinite(value)
                        and (field.minimum is None or value >= field.minimum)
                        and (field.maximum is None or value <= field.maximum)
                    )
                except OverflowError:
                    valid = False
        elif field.kind == "date":
            try:
                valid = (
                    isinstance(value, str)
                    and len(value) == 10
                    and date.fromisoformat(value).isoformat() == value
                )
            except ValueError:
                valid = False
        if not valid:
            raise TemplateFieldError(
                f"“{field.label}”的值不符合类型、长度、范围或选项要求", field_key=field.key
            )
        normalized[field.key] = value
    return normalized
