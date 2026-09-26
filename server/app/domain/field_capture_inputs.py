"""Typed, deliberately incomplete human drafts; submission validates actual business facts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CaptureMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=128)
    value: str = Field(max_length=2000)
    unit: str = Field(default="", max_length=32)
    target: str = Field(default="", max_length=2000)
    verdict: Literal["pass", "fail", "info"] = "info"


class CaptureDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["issue", "test"] = "issue"
    title: str = Field(default="", max_length=512)
    recognition_id: UUID | None = None
    recognition_note: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=16000)
    issue_type: Literal["engineering", "quality", "supplier", "test_failure", "certification"] = (
        "engineering"
    )
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    sample_id: UUID | None = None
    sample_reason: str = Field(default="", max_length=2000)
    test_case_id: UUID | None = None
    test_case_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    status: Literal["in_progress", "passed", "failed", "aborted"] = "in_progress"
    conditions: str = Field(default="", max_length=10000)
    equipment: str = Field(default="", max_length=256)
    environment: str = Field(default="", max_length=256)
    metrics: list[CaptureMetric] = Field(default_factory=list, max_length=100)
    expected_completion_at: datetime | None = None
    executed_at: datetime | None = None
    execution_time_precision: Literal["unknown", "day", "instant"] = "unknown"
    execution_time_reason: str = Field(default="", max_length=2000)
    configuration_mode: Literal["current", "revision", "unknown"] = "unknown"
    configuration_revision_id: UUID | None = None
    configuration_reason: str = Field(default="", max_length=2000)
    evidence_document_id: UUID | None = None
