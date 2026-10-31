"""Bounded model views of durable reads. Handles never authorize source access."""

import json
import re
from uuid import UUID

from pydantic import Field

from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from .context_budget import estimate_tokens

HANDLE = re.compile(r"^result:([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}):([a-f0-9]{64})$")


class ResultReadInput(StrictModel):
    handle: str = Field(pattern=HANDLE.pattern)
    page: int = Field(default=1, strict=True, ge=1, le=1_000_000)


def serialized(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def handle_for(call_id, value):
    return f"result:{UUID(str(call_id))}:{digest(value)}"


def parse_handle(handle):
    match = HANDLE.fullmatch(handle) if isinstance(handle, str) else None
    if match is None:
        raise DomainError("VALIDATION_FAILED", "结果续读引用无效。")
    return UUID(match[1]), match[2]


def _chunks(text, cap):
    """Count the JSON-escaped fragment, including framing, before slicing.

    The fixed reserve covers IDs, counters and the next-page instruction. It is
    independent of fragment content (newlines/backslashes included).
    """
    budget = cap - 220
    if budget < 1:
        raise ValueError("Result envelope has no fragment budget")
    chunks, offset = [], 0
    while offset < len(text):
        low, high = 1, min(len(text) - offset, budget * 4)
        best = 0
        while low <= high:
            middle = (low + high) // 2
            fragment = serialized(text[offset:offset + middle])
            if estimate_tokens(fragment) <= budget:
                best, low = middle, middle + 1
            else:
                high = middle - 1
        if not best:
            raise ValueError("Result envelope cannot hold a JSON character")
        chunks.append(text[offset:offset + best])
        offset += best
    return chunks or [""]


def page_view(value, handle, page, cap=4_000):
    """Fragments reconstruct the exact JSON result; no summarizer/model is used."""
    text = serialized(value)
    chunks = _chunks(text, cap)
    if type(page) is not int or not 1 <= page <= len(chunks):
        raise DomainError("VALIDATION_FAILED", "结果页码超出可读取范围。")
    result = {
        "result_handle": handle,
        "truncated": True,
        "format": "json_fragment",
        "page": page,
        "total_pages": len(chunks),
        "total_characters": len(text),
        "total_estimated_tokens": estimate_tokens(text),
        "preview": chunks[page - 1],
        "read_more": {"tool": "result.read", "arguments": {"handle": handle, "page": page + 1}}
        if page < len(chunks) else None,
    }
    if isinstance(value, dict):
        for key in ("items", "rows", "results"):
            if isinstance(value.get(key), list):
                result["total_items"] = len(value[key])
                break
    if estimate_tokens(serialized(result)) > cap:
        raise DomainError(
            "CONTEXT_INCOMPLETE", "结果分页信封超过工具预算。",
            detail={"missing": [{"field": "tool_result", "reason": "result_envelope_budget"}]},
        )
    return result


def durable_read(store, scope, handle, registry):
    """Locate provenance only. The host must still execute the original read guard."""
    from .models import AgentToolCall
    from .read_execution import ReadBinding, ReadSource

    call_id, fingerprint = parse_handle(handle)
    with store.transaction(scope) as (session, _):
        call = session.get(AgentToolCall, call_id)
        if (
            call is None or call.tenant_id != scope.tenant_id or call.run_id != scope.run_id
            or call.state != "completed" or call.error_code is not None
            or call.receipt_id is not None or not isinstance(call.result, dict)
            or call.tool in {"model", "result.read"} or digest(call.result) != fingerprint
        ):
            raise DomainError("FORBIDDEN_SCOPE", "结果续读引用不属于当前运行的可信读取。")
        try:
            binding = ReadBinding.model_validate(call.execution_binding)
        except ValueError:
            raise DomainError("FORBIDDEN_SCOPE", "结果续读缺少可信读取来源。") from None
        if (
            binding.isolation != scope.isolation or binding.tool != call.tool
            or binding.run_id != scope.run_id or binding.call_key != call.call_key
        ):
            raise DomainError("FORBIDDEN_SCOPE", "结果续读不能跨运行或隔离边界。")
        model = session.get(AgentToolCall, binding.model_call_id)
        calls = model.result.get("calls") if model and isinstance(model.result, dict) else None
        if not isinstance(calls, list) or binding.response_index >= len(calls):
            raise DomainError("SOURCE_UNAVAILABLE", "原读取的模型来源不完整。")
        request = calls[binding.response_index]
        if not isinstance(request, dict) or request.get("name") != call.tool:
            raise DomainError("SOURCE_UNAVAILABLE", "原读取的模型来源不一致。")
        arguments = request.get("arguments")
        registry.authorize(scope, call.tool, arguments, {}, lambda *_: False)
        return registry.get(call.tool), arguments, call.call_key, ReadSource(
            model_call_id=binding.model_call_id, response_index=binding.response_index,
        ), fingerprint


def verify_historical_page(session, run, call, request, previous, *, parent_ids):
    """Prove a history page derives from a main read checked in the same batch.

    The caller still revalidates that original read through its registered local
    history reader. This function never repeats network/model work or grants an
    old Run new execution authority.
    """
    from .models import AgentToolCall
    from .read_execution import ReadBinding
    from .tools import default_registry

    data = ResultReadInput.model_validate(request["arguments"])
    identity, fingerprint = parse_handle(data.handle)
    parent = session.get(AgentToolCall, identity)
    if (
        identity not in parent_ids or parent is None or parent.run_id != run.id
        or parent.state != "completed" or parent.error_code is not None
        or parent.receipt_id is not None or parent.tool in {"model", "result.read"}
        or digest(parent.result) != fingerprint or request.get("name") != "result.read"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "历史续读的原结果已不可核对。")
    origin = ReadBinding.model_validate(parent.execution_binding)
    derived = ReadBinding.model_validate(call.execution_binding)
    if any(getattr(origin, key) != getattr(derived, key) for key in (
        "tenant_id", "category_id", "product_id", "proposal_id", "run_id", "session_id",
        "requester_id", "writer_id", "isolation", "cancel_epoch", "private_context",
        "data_categories", "customer_identities",
    )) or origin.isolation != "main" or derived.tool != "result.read":
        raise DomainError("FORBIDDEN_SCOPE", "历史续读不能跨运行、来源或隔离边界。")
    value = {**parent.result, "execution_ref": {
        "call_id": str(parent.id), "read_kind": origin.read_kind,
    }}
    spec = default_registry().get(parent.tool)
    expected = page_view(value, data.handle, data.page, min(spec.max_result_tokens, 4_000) - 64)
    if digest(expected) != digest(previous):
        raise DomainError("FORBIDDEN_SCOPE", "历史续读正文与原结果不一致。")


def incomplete_views(results):
    """Only a child which received every fragment may verify the original page."""
    pending = []
    for entry in results:
        view = entry.get("model_view", {})
        if entry.get("tool") == "result.read" or not view:
            continue
        handle, total = view["result_handle"], view["total_pages"]
        received = {view["page"]}
        for other in results:
            page = other.get("value", {})
            if (other.get("tool") == "result.read" and page.get("result_handle") == handle
                    and not page.get("error") and page.get("total_pages") == total):
                received.add(page["page"])
        missing = sorted(set(range(1, total + 1)) - received)
        if missing:
            pending.append({"handle": handle, "missing_pages": missing[:40],
                            "remaining_pages": len(missing), "tool": "result.read"})
    return pending
