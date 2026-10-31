"""Server-frozen lookup effort over actual immutable read/model claims."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import Field, ValidationError
from sqlalchemy import select

from pdos_next.agent_kernel.bindings import ModelBinding
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.read_execution import ReadBinding
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

KEY = "assistant_depth"
TOOLS = frozenset({"assistant.search", "assistant.extract"})


class DeepenInput(StrictModel):
    continue_from_run_id: UUID
    goal: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=8, max_length=160)


@dataclass(frozen=True)
class ReadLimits:
    searches: int
    extract_sources: int


LIMITS = {"quick": ReadLimits(1, 3), "deep": ReadLimits(4, 8)}


def starting_profile(requested, parent):
    if requested not in {None, "deep"} or requested == "deep" and parent is None:
        raise DomainError("INVALID_PAYLOAD", "深入查须从当前本人会话中的原运行继续。", 422)
    return {"version": 1, "mode": "deep" if requested else "quick",
            "parent_run_id": str(parent.id) if parent else None}


def prepare_deep(session, ctx, requested: DeepenInput):
    from pdos_next.agent_kernel.api import StartInput
    from pdos_next.agent_kernel.conversation import prepare

    original = StartInput(**requested.model_dump())
    effective, parent = prepare(session, ctx, original)
    return effective, parent, starting_profile("deep", parent)


def mode_for(run) -> Literal["quick", "deep"] | None:
    profile = run.versions.get(KEY)
    if profile is None:
        return None  # Pre-profile Runs retain their original recovery contract.
    parent = str(run.continued_from_id) if run.continued_from_id else None
    if (not isinstance(profile, dict) or set(profile) != {"version", "mode", "parent_run_id"}
        or type(profile["version"]) is not int or profile["version"] != 1
        or profile["mode"] not in LIMITS or profile["parent_run_id"] != parent
        or profile["mode"] == "deep" and parent is None):
        raise DomainError("VERSION_CONFLICT", "查找深度未绑定本次实际续接，请重新发起。")
    return profile["mode"]


def _exhausted():
    raise DomainError(
        "MODEL_BUDGET_EXCEEDED", "本轮查找预算已用完，请先交付已核对结果；需要时继续深入查。",
    )


def admit_read(mode, tool, arguments, *, other_search_calls=0):
    if mode is None:
        return
    if mode not in LIMITS or type(other_search_calls) is not int or other_search_calls < 0:
        raise DomainError("VERSION_CONFLICT", "查找预算缺少当前运行的可信计数。")
    limits = LIMITS[mode]
    if tool == "assistant.search" and other_search_calls >= limits.searches:
        _exhausted()
    if tool == "assistant.extract":
        identities = arguments.get("citation_ids")
        if (not isinstance(identities, list) or not identities
            or len(identities) > limits.extract_sources):
            _exhausted()


def _arguments(session, scope, run, call):
    """Read parameters from an actual completed model response, never a counter JSON."""
    try:
        binding = ReadBinding.model_validate(call.execution_binding)
        model = session.get(AgentToolCall, binding.model_call_id)
        model_binding = ModelBinding.model_validate(model.execution_binding)
        arguments = model.result["calls"][binding.response_index]
        if (call.tenant_id != run.tenant_id or call.run_id != run.id
            or binding.tenant_id != run.tenant_id or binding.run_id != run.id
            or binding.isolation != "main" or binding.read_kind != "ordinary/v1"
            or binding.tool != call.tool or binding.call_key != call.call_key
            or binding.model_call_id != model.id
            or binding.model_version != model_binding.model_version
            or binding.model_route_digest != model_binding.model_route_digest
            or binding.tool_definitions_digest != model_binding.tool_definitions_digest
            or binding.prompt_digest != model_binding.prompt_digest
            or binding.cancel_epoch != scope.cancel_epoch or model_binding.isolation != "main"
            or model_binding.cancel_epoch != scope.cancel_epoch
            or model.tenant_id != run.tenant_id or model.run_id != run.id
            or model.tool != "model" or model.state != "completed"
            or model.error_code is not None or call.receipt_id is not None
            or arguments["name"] != call.tool
            or digest([call.tool, arguments["arguments"]]) != call.input_digest):
            raise ValueError
        return arguments["arguments"]
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, ValidationError):
        raise DomainError("SOURCE_UNAVAILABLE", "查找配额缺少真实模型读取账本。") from None


def admit_call(session, scope, run, call_id, tool, arguments):
    """Called under the existing Run lock and run-wide composition fence, after claim.

    The same call is excluded on retry. Completed restores skip this path. Scope,
    read source and current route were verified by BoundHost before the claim.
    """
    mode = mode_for(run)
    if mode is None or tool not in TOOLS:
        return
    from .assistant_schemas import AssistantSearchInput, ExtractInput

    try:
        (AssistantSearchInput if tool == "assistant.search" else ExtractInput).model_validate(
            arguments,
        )
    except ValidationError:
        raise DomainError("INVALID_PAYLOAD", "查找须使用登记的原生参数。", 422) from None
    calls = session.scalars(select(AgentToolCall).where(
        AgentToolCall.tenant_id == run.tenant_id, AgentToolCall.run_id == run.id,
        AgentToolCall.tool.in_(TOOLS), AgentToolCall.state.in_(["started", "completed"]),
        AgentToolCall.id != call_id,
    )).all()
    searches = sum(call.tool == "assistant.search" for call in calls)
    admit_read(mode, tool, arguments, other_search_calls=searches)
    if tool == "assistant.extract":
        from .assistant_ledger import select_issued

        ids = set(arguments["citation_ids"])
        for call in calls:
            if call.tool == "assistant.extract":
                ids.update(_arguments(session, scope, run, call)["citation_ids"])
        selected = select_issued(session, scope, [UUID(str(value)) for value in ids])
        fixed = {(row["source_type"], row["source_id"], row["source_revision"], row["content_hash"])
                 for row in selected.values()}
        if len(fixed) > LIMITS[mode].extract_sources:
            _exhausted()


def context_value(run):
    mode = mode_for(run)
    if mode is None:
        return None
    limits = LIMITS[mode]
    return {"version": 1, "mode": mode, "max_search_calls": limits.searches,
            "max_extract_sources": limits.extract_sources, "rules": [
                "沿用已核对的历史引用或明确选定材料，不为复用固定来源重复检索。",
                "快查先交付已核对的部分；资料较多或需要继续检索时，可提议在同会话深入查。",
                "深入查仍按当前权限和固定版本读取，主模型与业务批准规则不变。",
            ]}


CONTEXT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "version": {"const": 1}, "mode": {"enum": ["quick", "deep"]},
        "max_search_calls": {"type": "integer", "minimum": 1, "maximum": 4},
        "max_extract_sources": {"type": "integer", "minimum": 3, "maximum": 8},
        "rules": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["version", "mode", "max_search_calls", "max_extract_sources", "rules"],
}
