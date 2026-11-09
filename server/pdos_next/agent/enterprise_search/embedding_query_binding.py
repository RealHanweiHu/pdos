"""An independent derived READ fee binding; never a chat ModelBinding or tool schema."""

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from pdos_next.agent.kernel.bindings import ModelBinding
from pdos_next.agent.kernel.execution import check_run_binding
from pdos_next.agent.kernel.models import AgentToolCall
from pdos_next.agent.kernel.read_execution import (
    ReadBinding,
    ReadSource,
    build_read_binding,
)
from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

TOOL = "embedding.query.internal"
# memory.search binds a query vector only for the owner's episode vectors (P85 第 3 项).
PARENT_TOOLS = frozenset({"assistant.search", "memory.search"})
SNAPSHOT = "embedding_query_profile"


class QueryProfile(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile_version_id: UUID
    binding_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    dimensions: int = Field(strict=True, ge=1, le=2000)
    scan_strategy: Literal["exact", "iterative"] = "exact"


class QueryBinding(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["embedding_query"] = "embedding_query"
    proof_version: int = Field(default=1, strict=True, ge=1, le=1)
    parent_read_call_id: UUID
    parent_input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    profile_version_id: UUID
    profile_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    query_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    cancel_epoch: int = Field(strict=True, ge=0)


def source(session, scope, run, identity, arguments):
    """The actual READ and its completed model reply own query text and identity."""
    from pdos_next.agent.kernel.tools import default_registry

    check_run_binding(run, scope)
    parent = session.get(AgentToolCall, identity)
    if (
        not parent
        or parent.tenant_id != scope.tenant_id
        or parent.run_id != run.id
        or parent.tool not in PARENT_TOOLS
        or parent.state != "started"
        or parent.error_code is not None
        or parent.receipt_id is not None
        or parent.input_digest != digest([parent.tool, arguments])
    ):
        raise DomainError("FORBIDDEN_SCOPE", "Query embedding 缺少实际主图检索调用。")
    try:
        binding = ReadBinding.model_validate(parent.execution_binding)
        model = session.get(AgentToolCall, binding.model_call_id)
        if (
            model is None
            or model.tenant_id != run.tenant_id
            or model.run_id != run.id
            or model.tool != "model"
            or model.state != "completed"
            or model.error_code is not None
            or model.receipt_id is not None
        ):
            raise ValueError
        model_binding = ModelBinding.model_validate(model.execution_binding)
        expected = build_read_binding(
            scope,
            run,
            default_registry().get(parent.tool),
            ReadSource(model_call_id=model.id, response_index=binding.response_index),
            model_binding,
        )
        request = model.result["calls"][binding.response_index]
        if (
            binding != expected
            or binding.read_kind != "ordinary/v1"
            or binding.isolation != "main"
            or request["name"] != parent.tool
            or request["arguments"] != arguments
            or not isinstance(arguments.get("query"), str)
            or not arguments["query"].strip()
        ):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        raise DomainError(
            "FORBIDDEN_SCOPE", "Query embedding 须继承完整实际模型读取证明。"
        ) from None
    return parent, arguments["query"]


def bind(parent, profile, query, cancel_epoch):
    return QueryBinding(
        parent_read_call_id=parent.id,
        parent_input_digest=parent.input_digest,
        profile_version_id=profile.profile_version_id,
        profile_digest=profile.binding_digest,
        query_digest=digest(query),
        cancel_epoch=cancel_epoch,
    )


def key(run_id, parent_id):
    return f"embedding-query:{run_id}:{parent_id}"


def payload(parent_id, profile, query):
    return {
        "parent_read_call_id": str(parent_id),
        "profile_version_id": str(profile.profile_version_id),
        "query": query,
    }
