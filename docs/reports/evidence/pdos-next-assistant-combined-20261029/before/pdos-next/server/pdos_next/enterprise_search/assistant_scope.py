"""One server-triggered category fallback after current authorized candidates are known."""

from uuid import UUID

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.search_preferences import SearchPreferences
from pdos_next.service import digest

from . import assistant_ledger as ledger
from .assistant_sources import current
from .query import search

MIN_CURRENT = 3


def _verified(session, result):
    provisional = {str(i): row for i, row in enumerate(result["items"])}
    actual, missing = current(session, provisional)
    items = [
        {**item, "private": actual[key]["private"],
         "customer_original": actual[key]["customer_original"],
         **({"dependency_basis": actual[key]["dependency_basis"]}
            if actual[key].get("dependency_basis") else {})}
        for key, item in provisional.items() if key in actual
    ]
    result = {**result, "items": items, "returned": len(items)}
    result["direct_returned"] = sum(item.get("channel") != "relation" for item in items)
    result["related_returned"] = len(items) - result["direct_returned"]
    if missing:
        result["coverage"] = {**result["coverage"], "status": "partial",
                              "notice": "部分来源的当前依据尚未完成核对。"}
    return result


def retrieve(session, ctx, scope, data):
    primary = _verified(session, search(session, ctx, data))
    if not scope.project_id and not scope.proposal_id:
        return primary
    run = session.get(AgentRun, scope.run_id)
    if run is None:
        ledger.deny("run_unreadable")
    state = run.versions.get("work_state")
    if state is not None and digest(state) != run.versions.get("work_state_digest"):
        ledger.deny("work_state_changed")
    preferences = SearchPreferences.model_validate(
        state.get("search_preferences", {}) if state is not None
        else run.versions.get("requested_search_preferences", {})
    )
    label = "当前项目" if scope.project_id else "当前提案"
    groups = [("current", label, primary)]
    identities = {(item["source_type"], item["source_id"]) for item in primary["items"]}
    if preferences.scope == "same_category" and len(identities) < MIN_CURRENT:
        category = primary["scope"]["category_id"]
        if category is None:
            ledger.deny("category_root_required")
        fallback = _verified(session, search(
            session, ctx,
            data.model_copy(update={"category_id": UUID(category), "product_id": None,
                                    "project_id": None, "proposal_id": None}),
            exclude_project=scope.project_id, exclude_proposal=scope.proposal_id,
            exclude_sources=identities,
            allow_customer_private=preferences.include_customer_private,
        ))
        groups.append(("same_category", "同品类其他项目", fallback))
    items, descriptors = [], []
    for key, name, group in groups:
        items.extend({**item, "group": key, "group_label": name} for item in group["items"])
        descriptors.append({"id": key, "label": name, "returned": group["returned"],
                            "truncated": group["truncated"], "coverage": group["coverage"],
                            "scope": group["scope"]})
    for rank, item in enumerate(items, 1):
        item["rank"] = rank
    partial = any(group[2]["coverage"]["status"] == "partial" for group in groups)
    checked = [group[2]["coverage"]["indexed_as_of"] for group in groups
               if group[2]["coverage"]["indexed_as_of"]]
    direct = sum(item.get("channel") != "relation" for item in items)
    return {
        **primary, "items": items, "returned": len(items), "direct_returned": direct,
        "related_returned": len(items) - direct,
        "truncated": any(group[2]["truncated"] for group in groups),
        "related_truncated": any(group[2]["related_truncated"] for group in groups),
        "groups": descriptors,
        "scope_policy": {"version": "same-category-once-threshold3/v1",
                         "scope": preferences.scope, "fallback_performed": len(groups) == 2,
                         "include_customer_private": preferences.include_customer_private},
        "coverage": {"status": "partial" if partial else "current",
                     "notice": "部分当前可读来源尚未完成索引或当前依据复核。" if partial else None,
                     "indexed_as_of": min(checked) if checked else None},
    }
