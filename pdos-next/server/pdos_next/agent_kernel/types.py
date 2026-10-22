"""Immutable server bindings; model dictionaries never deserialize authority."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic import Field

from pdos_next.schema_base import StrictModel

Tier = Literal["READ", "T0", "T1", "T2-prepare-only"]
Isolation = Literal["main", "research", "extract", "mcp"]


@dataclass(frozen=True)
class RunScope:
    tenant_id: UUID
    requester_id: UUID
    writer_id: UUID
    session_id: UUID
    run_id: UUID
    category_id: UUID | None
    product_id: UUID | None = None
    proposal_id: UUID | None = None
    cancel_epoch: int = 0
    private_context: bool = False
    data_categories: frozenset[str] = frozenset({"public"})
    customer_identities: tuple[str, ...] = field(default=(), repr=False)
    isolation: Isolation = "main"
    artifact_ids: frozenset[UUID] = frozenset()
    trigger: str = "conversation"
    project_id: UUID | None = field(default=None, kw_only=True)

    def child(self, isolation: Isolation, *, artifact_ids=frozenset()):
        from dataclasses import replace

        return replace(self, isolation=isolation, artifact_ids=frozenset(artifact_ids))


class ToolCall(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=160)
    arguments: dict


class ClarifyOption(StrictModel):
    value: str
    label: str


class ClarifyQuestion(StrictModel):
    id: str
    question: str
    why: str
    options: list[ClarifyOption] = Field(default_factory=list)
    recommended: dict | None = None
    allow_free_text: bool = True
    depends_on: list[str] = Field(default_factory=list)


class AgentOutput(StrictModel):
    status: Literal["completed", "partial", "needs_input"]
    summary: str
    result: dict = Field(default_factory=dict)
    questions: list[ClarifyQuestion] = Field(default_factory=list, max_length=3)
    unfinished: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ModelTurn:
    text: str = ""
    calls: tuple[ToolCall, ...] = ()
    usage: object | None = None
    request_id: str | None = None
    structured: dict | None = None
    ledger_call_id: UUID | None = None  # Set only by the server gateway, never the provider.
    continuation: dict | None = field(default=None, repr=False)  # Private provider protocol only.


class WireRecommendation(StrictModel):
    value: str
    reason: str


class WireQuestion(StrictModel):
    id: str
    question: str
    why: str
    options: list[ClarifyOption]
    recommended: WireRecommendation | None
    allow_free_text: bool
    depends_on: list[str]


class WireAgentOutput(StrictModel):
    """Finite native grammar; business candidate JSON is checked by its domain schema."""

    status: Literal["completed", "partial", "needs_input"]
    summary: str
    result_json: str
    questions: list[WireQuestion] = Field(max_length=3)
    unfinished: list[str]
