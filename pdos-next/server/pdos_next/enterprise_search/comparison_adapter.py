"""Main-loop comparison orchestration; raw differences remain inside the child graph."""

from copy import deepcopy
from uuid import UUID

from pdos_next.errors import DomainError

from . import assistant_ledger as ledger
from .assistant_schemas import CompareInput
from .comparison import align


def selected(adapter, scope, arguments):
    data = CompareInput.model_validate(arguments)
    citations = adapter._selected(scope, [data.left_citation_id, data.right_citation_id])
    actual, missing = adapter._current(scope, citations, body=True)
    if missing:
        raise DomainError("SOURCE_UNAVAILABLE", "比较的固定来源当前不可读取。")
    if any(source["nature"] != "untrusted" for source in actual.values()):
        raise DomainError("INVALID_PAYLOAD", "结构化定义请使用已有规格或定义比较工具。", 422)
    left, right = str(data.left_citation_id), str(data.right_citation_id)
    aligned = align(left, actual[left], right, actual[right])
    if data.cursor > len(aligned["changes"]):
        raise DomainError("INVALID_PAYLOAD", "比较游标超出固定变化集合。", 422)
    return data, citations, actual, aligned


def compare(adapter, scope, arguments, intent_key):
    call_id = adapter._started(scope, "assistant.compare", arguments, intent_key)
    data, citations, actual, aligned = selected(adapter, scope, arguments)
    changes = aligned["changes"][data.cursor : data.cursor + data.batch_size]
    outcome = {"rows": [], "rejected": [], "complete": True}
    if changes:
        if adapter.comparison_graph is None:
            raise DomainError("SOURCE_UNAVAILABLE", "隔离比较执行端口尚未配置。")
        outcome = adapter.comparison_graph(
            scope.child("assistant_compare", citation_ids={UUID(cid) for cid in citations}),
            citations,
            actual,
            changes,
            call_id,
        )
    next_cursor = data.cursor + len(changes)
    more = next_cursor < len(aligned["changes"])
    return {
        "version": 1,
        "kind": "comparison",
        "citation_ids": list(citations),
        "rows": outcome["rows"],
        "rejected": outcome["rejected"],
        "stats": aligned["stats"],
        "unmatched": aligned["unmatched"],
        "alignment_basis": aligned["alignment_basis"],
        "cursor": data.cursor,
        "next_cursor": next_cursor if more else None,
        "has_more": more,
        "batch_complete": outcome["complete"],
        "as_of": max(source["as_of"] for source in actual.values()).isoformat(),
        "partial": aligned["partial"] or not outcome["complete"] or more,
    }


def restore(adapter, scope, arguments, previous):
    data, citations, _actual, aligned = selected(adapter, scope, arguments)
    expected = {
        row["change_id"]: row
        for row in aligned["changes"][data.cursor : data.cursor + data.batch_size]
    }
    if (
        list(citations) != previous["citation_ids"]
        or previous["stats"] != aligned["stats"]
        or previous["unmatched"] != aligned["unmatched"]
        or previous["alignment_basis"] != aligned["alignment_basis"]
    ):
        ledger.deny("comparison_changed")
    for row in previous["rows"]:
        fixed = expected.get(row["change_id"])
        if fixed is None or any(row[key] != value for key, value in fixed.items()):
            ledger.deny("comparison_row_changed")
        if row["impact"] is not None:
            impact = row["impact"]
            if not any(
                side
                and side["citation_id"] == impact["citation_id"]
                and impact["quote"] in side["quote"]
                for side in (fixed["old"], fixed["new"])
            ):
                ledger.deny("comparison_impact_changed")
    return deepcopy(previous)
