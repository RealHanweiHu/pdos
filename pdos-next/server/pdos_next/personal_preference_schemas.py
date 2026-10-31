"""Finite explicit settings. No authority, tool or learning controls."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from pdos_next.schema_base import StrictModel

AnswerLanguage = Literal["auto", "zh-CN", "zh-TW", "en", "ja"]
ResponseDetail = Literal["brief", "balanced", "detailed"]
Role = Literal[
    "product", "engineering", "quality", "manufacturing", "supply", "management", "other"
]


class Preferences(StrictModel):
    answer_language: AnswerLanguage = "auto"
    response_detail: ResponseDetail = "balanced"
    role: Role | None = None
    department: str | None = Field(default=None, max_length=80)
    favorite_category_ids: list[UUID] = Field(default_factory=list, max_length=10)
    favorite_project_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @field_validator("department")
    @classmethod
    def clean_department(cls, value):
        if value and any(ord(char) < 32 for char in value):
            raise ValueError("Department must be a single display label")
        return value or None

    @field_validator("favorite_category_ids", "favorite_project_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Navigation candidates must be unique")
        return value


class PreferenceSave(StrictModel):
    expected_revision: int = Field(ge=0, le=2147483646, strict=True)
    preferences: Preferences


class NavigationOptions(StrictModel):
    kind: Literal["category", "project"]
    query: str = Field(default="", max_length=100)
    cursor: UUID | None = None
    page_size: int = Field(default=30, ge=1, le=100)
