"""Rebuild child read authority from completed server calls before using a saved graph."""

from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.research.service import safe_error
from pdos_next.research.types import ResearchFailure

from .deterministic_proofs import _historical_read
from .read_execution import ReadSource
from .tools import default_registry


def restore_reads(host, child, state, read):
    def deny(*_args, **_kwargs):
        raise DomainError("SOURCE_UNAVAILABLE", "研究检查点缺少原运行的实际读取回执。")

    try:
        for item in state.get("tool_results", []):
            tool, value = item["tool"], item["value"]
            if tool not in {"research.search", "research.read"} or item["tier"] != "READ":
                deny()
            if "error" in value:
                # A server-created checkpoint failure can only reduce coverage;
                # it never grants a URL or source authority and is never retried here.
                error = value["error"]
                child.failures.append(ResearchFailure(
                    child.task.key, tool.split(".")[1], error["code"], safe_error(error["message"]),
                ))
                continue
            reference = value["execution_ref"]
            with host.store.transaction(child._scope) as (session, _):
                _, call, binding, arguments = _historical_read(
                    session, child._scope, UUID(reference["call_id"]),
                    reference["read_kind"], deny=deny,
                )
                if (
                    call.tool != tool or binding.isolation != "research"
                    or value != {**call.result, "execution_ref": reference}
                ):
                    deny()
                intent = call.call_key
                source = ReadSource(
                    model_call_id=binding.model_call_id, response_index=binding.response_index,
                )
            # This route only sees an already-completed actual call. Existing
            # search/page/registered-page restores recheck the original material.
            restored = read(
                child._scope, default_registry().get(tool), arguments, intent, source=source,
            )
            if restored != value:
                deny()
    except (AttributeError, KeyError, TypeError, ValueError):
        deny()
