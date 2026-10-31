"""Server-created execution facts. These objects never enter provider tool payloads."""

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from pdos_next.schema_base import StrictModel

Hash = str


class SkillBinding(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=160)
    digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    load_event_id: UUID


class WriteSource(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    skill: SkillBinding
    model_call_id: UUID
    response_index: int = Field(ge=0)


class ModelBinding(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["model"] = "model"
    model_version: str = Field(min_length=1, max_length=160)
    model_route_digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    tool_definitions_digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    isolation: Literal[
        "main", "research", "extract", "mcp", "assistant_extract", "assistant_compare"
    ]
    cancel_epoch: int = Field(ge=0)
    loaded_skills: tuple[SkillBinding, ...] = ()


class DomainBinding(WriteSource):
    kind: Literal["domain_t0"] = "domain_t0"
    operation: str = Field(min_length=1, max_length=160)
    model_version: str = Field(min_length=1, max_length=160)
    model_route_digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    tool_definitions_digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    cancel_epoch: int = Field(ge=0)
    command_digest: Hash = Field(pattern=r"^[a-f0-9]{64}$")


def execution_key(run_id, model_call_id, response_index):
    """Native model call IDs are protocol labels, never authority or idempotency keys."""
    return f"agent:{run_id}:model:{model_call_id}:{response_index}"
