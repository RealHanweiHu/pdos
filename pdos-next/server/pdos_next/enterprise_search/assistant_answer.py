"""Final answer sources and four lookup states come exclusively from actual read proofs."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from pdos_next.agent_kernel.assistant_result import attach as ordinary_answer
from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.errors import DomainError

from . import assistant_ledger as ledger
from .assistant_sources import current


def readable_runs(session, runs):
    """Validate actual provenance, then batch the authority check across output origins."""
    citations, by_run = {}, {}
    for run in runs:
        try:
            values, _historical = ledger.carried(session, scope_for_run(run))
        except DomainError as error:
            if error.code not in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
                raise
            continue
        citations.update(values)
        by_run[run.id] = set(values)
    actual, missing = current(session, citations, allow_updated=set(citations))
    return {
        identity: {cid: actual[cid] for cid in ids}
        for identity, ids in by_run.items()
        if not ids.intersection(missing)
    }


def checked_sources(session, run):
    values = readable_runs(session, [run])
    if run.id not in values:
        raise DomainError("FORBIDDEN_SCOPE", "这次回答依赖的资料已不可读取，原内容已隐藏。", 403)
    return values[run.id]


def stored_answer(session, run):
    """HTTP retrieval rechecks own and actually carried source ACLs in the same RR snapshot."""
    actual = checked_sources(session, run)
    value = deepcopy(run.result)
    if isinstance(value, dict):
        answer = value.get("result", {}).get("assistant")
        if isinstance(answer, dict):
            from .navigation import links

            destinations = links(session, actual)
            for source in answer.get("sources", []):
                source.pop("object_url", None)
                source.pop("object_label", None)
                source.update(destinations.get(source.get("citation_id"), {}))
                current_source = actual.get(source.get("citation_id"))
                if current_source:
                    source["read_basis_status"] = current_source["read_basis_status"]
                    source["fixed_body_available"] = current_source["fixed_body_available"]
                    review = current_source.get("knowledge_review") or (current_source.get("structured") or {}).get("knowledge_review")
                    if review:
                        source["knowledge_review"] = review
        if isinstance(answer, dict) and any(row.get("updated") for row in actual.values()):
            answer["notice"] = "资料已更新；这条历史回答保留原版本，当前事实请重新查询。"
            for source in answer.get("sources", []):
                if actual.get(source.get("citation_id"), {}).get("updated"):
                    source["currentness"] = "updated"
    return value


def attach(adapter, scope, output, tool_results):
    with adapter.store.transaction(scope) as (session, _run):
        calls = ledger.completed(session, scope)
        citations = ledger.issued(session, scope)
        attempted = (
            session.scalar(
                select(AgentToolCall.id)
                .where(
                    AgentToolCall.run_id == scope.run_id,
                    AgentToolCall.tool.in_(ledger.TOOLS),
                )
                .limit(1)
            )
            is not None
        )
    if not attempted:
        return ordinary_answer(output, tool_results)
    result = deepcopy(output)
    body = result.setdefault("result", {})
    proposed = body.pop("assistant", {})
    proposed = proposed if isinstance(proposed, dict) else {}
    requested, invalid = [], False
    raw_ids = proposed.get("citation_ids", [])
    if not isinstance(raw_ids, list) or len(raw_ids) > 20:
        invalid, raw_ids = True, []
    for raw in raw_ids:
        try:
            requested.append(str(UUID(str(raw))))
        except ValueError:
            invalid = True
    requested = list(dict.fromkeys(requested))
    inherited = {cid for cid, item in citations.items() if "origin_run_id" in item}
    actual, missing = adapter._current(scope, citations, body=True, allow_updated=inherited)
    from .assistant_sources import human_snapshot
    from .navigation import links

    with human_snapshot(adapter.store.engine, scope) as session:
        destinations = links(session, actual)
    evidence = []
    partial = bool(missing)
    for call, _arguments in calls:
        if call.tool in ledger.ROOT_TOOLS | {"assistant.citations.read"}:
            partial |= call.result.get("coverage", {}).get("status") == "partial"
            continue
        if call.tool == "assistant.compare":
            continue  # Its batches are assembled together below.
        partial |= bool(call.result.get("partial"))
        for row in call.result.get("rows", []):
            cid = row.get("citation_id")
            source = actual.get(cid)
            if source is None or row.get("quote") not in source["body"]:
                continue
            if "values" in row and row["values"] != source["structured"]:
                continue
            evidence.append(row)
    from .comparison_result import assemble

    comparison, compared_evidence, compared_unknowns = assemble(calls, citations, actual)
    evidence.extend(compared_evidence)
    if comparison is not None:
        partial |= not comparison["complete"]
    from .task_result import assemble as assemble_task

    task_result, task_evidence, task_unknowns = assemble_task(
        proposed.get("task_result"), evidence, actual
    )
    evidence.extend(task_evidence)
    # Cell references are selectors, not independent authority. assemble_task
    # returns them only after matching the actual extraction and current source.
    requested = list(dict.fromkeys([*requested, *(row["citation_id"] for row in task_evidence)]))
    partial |= bool(task_unknowns)
    valid_ids = {row["citation_id"] for row in evidence}
    invalid |= bool(set(requested) - valid_ids)
    cited = [identity for identity in requested if identity in valid_ids]
    sources = []
    seen = set()
    for row in evidence:
        cid = row["citation_id"]
        if cid not in cited or (cid, row["quote"]) in seen:
            continue
        seen.add((cid, row["quote"]))
        source, item = actual[cid], citations[cid]
        sources.append(
            {
                "citation_id": cid,
                **{
                    key: item[key]
                    for key in (
                        "source_type",
                        "source_id",
                        "source_revision",
                        "content_hash",
                        "category_id",
                        "product_id",
                        "project_id",
                        "proposal_id",
                        "nature",
                    )
                },
                **({"knowledge_review": source["knowledge_review"]} if source.get("knowledge_review") else {}),
                "title": source["title"],
                "object_id": item.get("object_id", item["source_id"]),
                **destinations.get(cid, {}),
                "quote": row["quote"],
                "locator": row["locator"],
                "currentness": "history"
                if not source["is_current"] or cid in inherited and source["updated"]
                else "current",
                "read_basis_status": source["read_basis_status"],
                "fixed_body_available": source["fixed_body_available"],
                **({"relation": item["relation"]} if item.get("relation") else {}),
                **(
                    {"group": item["group"], "group_label": item["group_label"]}
                    if item.get("group") in {"current", "same_category"}
                    else {}
                ),
                "url": (
                    f"/api/v1/categories/{scope.category_id}"
                    if scope.category_id
                    else "/api/v1/personal"
                )
                + f"/agent-runs/{scope.run_id}/assistant-sources/{cid}"
                + (f"?change_id={row['change_id']}" if row.get("change_id") else ""),
            }
        )
    found = len({(row["source_type"], row["source_id"]) for row in actual.values()})
    successful_searches = [call for call, _args in calls if call.tool in ledger.ROOT_TOOLS]
    extracted = any(call.tool == "assistant.extract" for call, _args in calls)
    extracted |= comparison is not None
    scope_text = (
        "当前项目的可读资料"
        if scope.project_id
        else "当前提案的可读资料"
        if scope.proposal_id
        else "当前型号的可读资料"
        if scope.product_id
        else "当前品类的可读资料"
        if scope.category_id
        else "本人当前可读的公司资料"
    )
    grouped_searches = [call.result for call in successful_searches if call.result.get("groups")]
    if any(
        item.get("scope_policy", {}).get("fallback_performed") for item in grouped_searches
    ) or any(citations[cid].get("group") == "same_category" for cid in cited):
        scope_text += "及同品类其他项目的可读资料"
    lookup = "cited" if cited else "uncited" if found else "no_match"
    notice = (
        None
        if cited
        else (f"找到 {found} 条相关记录" if found else f"在{scope_text}中没有找到相关记录")
    )
    if not successful_searches and not extracted:
        partial, notice = True, "本次公司资料检索尚未完成，请重新查询。"
    elif missing:
        notice = "部分资料当前无法复核，请重新查询。"
    elif any(actual[cid]["read_basis_status"] == "needs_recheck" for cid in cited):
        notice = "部分引用的登记依据已变化，历史记录保留，当前适用性待重核。"
    elif any(not actual[cid]["is_current"] for cid in cited):
        notice = "引用保留原历史版本；当前事实请重新查询。"
    unknowns = proposed.get("unknowns", [])
    unknowns = (
        [value[:500] for value in unknowns[:10] if isinstance(value, str)]
        if isinstance(unknowns, list)
        else []
    )
    unknowns.extend(compared_unknowns)
    unknowns.extend(task_unknowns)
    assistant = {
        "version": 1,
        "kind": "enterprise" if cited else "general",
        "lookup": lookup,
        "citation_ids": cited,
        "sources": sources,
        "notice": notice,
        "scope_label": scope_text,
        "matched_count": found,
        "as_of": successful_searches[-1].result["as_of"]
        if successful_searches
        else max(
            (actual[row["citation_id"]]["as_of"].isoformat() for row in evidence), default=None
        ),
        "coverage": {
            "returned": len(sources),
            "unavailable": [{"citation_id": cid, "code": code} for cid, code in missing.items()],
        },
        "unknowns": unknowns,
    }
    if grouped_searches:
        # Counts describe only the latest actual grouped read, never model claims.
        latest = grouped_searches[-1]
        assistant["search_groups"] = [
            {
                **group,
                "returned": sum(
                    item["citation_id"] in actual
                    for item in latest["items"]
                    if item["group"] == group["id"]
                ),
                "truncated": group["truncated"] if not missing else False,
            }
            for group in latest["groups"]
        ]
        assistant["scope_policy"] = latest["scope_policy"]
    if comparison is not None:
        assistant["comparison"] = comparison
        if not comparison["complete"]:
            result["summary"] = "本次只完成部分资料比较，未核对的变化或解析缺口仍待处理。"
        elif comparison["stats"]["changes"] == 0:
            result["summary"] = "按已记录的解析内容对齐比较，未发现段落或单元格值差异。"
    if task_result is not None:
        assistant["task_result"] = task_result
    if task_unknowns:
        result["summary"] = "部分任务结果未通过引用或登记字段核对，未核对的内容已标为待确认。"
    if missing or invalid:
        # Unconstrained prose could contain a revoked quote even if the model did
        # not cite it. Keep verified source rows, discard the dependent prose.
        result["summary"] = "部分引用已变化、不可用或尚未核对，请重新查询后继续。"
        assistant.pop("comparison", None)
        assistant.pop("task_result", None)
        assistant["unknowns"] = ["部分引用未通过当前复核，请重新查询。"]
        body = {}
        partial = True
    body["assistant"] = assistant
    result["result"] = body
    if partial:
        result["status"] = "partial"
        result["unfinished"] = [*result.get("unfinished", []), "企业资料的引用或覆盖尚未完整核对。"]
    return result
