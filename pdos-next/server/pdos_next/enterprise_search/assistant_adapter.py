"""Enterprise READ tools over the existing immutable call ledger and source authority."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest

from . import assistant_ledger as ledger
from .assistant_schemas import (
    AssistantSearchInput,
    CitationsInput,
    ExtractInput,
    MaterialsInput,
    PassageInput,
)
from .assistant_sources import current, human_snapshot
from .locations import span


def structured_quote(source):
    """Prefer a readable literal field; never paraphrase it into a quotation."""
    preferred = {"text", "definition", "title", "reason", "purpose", "request_content", "method"}

    def strings(value):
        if isinstance(value, dict):
            for key, field in value.items():
                if key in preferred and isinstance(field, str) and field.strip():
                    yield field[:1000]
            for field in value.values():
                yield from strings(field)
        elif isinstance(value, list):
            for field in value:
                yield from strings(field)

    return next(
        (value for value in strings(source["structured"]) if value in source["body"]),
        source["body"][:1000],
    )


class AssistantReadAdapter:
    def __init__(self, store, commands, *, graph=None, query_embedding=None):
        self.store, self.commands, self.graph = store, commands, graph
        self.comparison_graph = None
        self.query_embedding = query_embedding

    def handlers(self):
        return {
            "assistant.search": self.search,
            "assistant.extract": self.extract,
            "assistant.citations.read": self.citations,
            "assistant.materials.read": self.materials,
            "assistant.compare": self.compare,
            "assistant.passage.read": self.passage,
        }

    def resumes(self):
        return {
            "assistant.search": self.search, "assistant.extract": self.extract,
            "assistant.citations.read": self.citations,
            "assistant.materials.read": self.materials,
            "assistant.compare": self.compare,
        }

    def restores(self):
        return {
            "assistant.search": self.restore_search, "assistant.extract": self.restore_extract,
            "assistant.citations.read": self.restore_citations,
            "assistant.materials.read": self.restore_search,
            "assistant.compare": self.restore_compare,
        }

    def materials(self, scope, arguments, *, intent_key=None):
        from .assistant_materials import read

        call_id = self._started(scope, "assistant.materials.read", arguments, intent_key)
        data = MaterialsInput.model_validate(arguments)
        with human_snapshot(self.store.engine, scope) as session:
            return read(session, scope, data, call_id)

    def compare(self, scope, arguments, *, intent_key=None):
        from .comparison_adapter import compare

        return compare(self, scope, arguments, intent_key)

    def restore_compare(self, scope, arguments, previous):
        from .comparison_adapter import restore

        return restore(self, scope, arguments, previous)

    def citations(self, scope, arguments, *, intent_key=None):
        from pdos_next.agent_kernel.models import AgentRun

        from .assistant_inheritance import page

        self._started(scope, "assistant.citations.read", arguments, intent_key)
        data = CitationsInput.model_validate(arguments)
        with human_snapshot(self.store.engine, scope) as session:
            run = session.get(AgentRun, scope.run_id)
            exclusions = run.versions.get("work_state", {}).get("exclusions", [])
            return page(session, run, data, excluded={item["id"] for item in exclusions})

    def restore_citations(self, scope, _arguments, previous):
        selected = self._selected(scope, [UUID(row["citation_id"]) for row in previous["items"]])
        _actual, missing = self._current(scope, selected, allow_updated=set(selected))
        if missing:
            raise DomainError("SOURCE_UNAVAILABLE", "原续接引用已不可读。")
        return deepcopy(previous)

    def _started(self, scope, name, arguments, intent_key):
        if scope.isolation != "main":
            ledger.deny("main_only")
        with self.store.transaction(scope) as (session, _run):
            call = session.scalar(
                select(AgentToolCall).where(
                    AgentToolCall.run_id == scope.run_id,
                    AgentToolCall.call_key == intent_key,
                    AgentToolCall.tool == name,
                    AgentToolCall.state == "started",
                )
            )
            if call is None or call.input_digest != digest([name, arguments]):
                ledger.deny("active_call_required")
            return call.id

    def _selected(self, scope, identities=None):
        with self.store.transaction(scope) as (session, _run):
            return (
                ledger.issued(session, scope)
                if identities is None
                else ledger.select_issued(
                    session,
                    scope,
                    identities,
                )
            )

    def _current(self, scope, citations, *, body=False, allow_updated=frozenset()):
        with human_snapshot(self.store.engine, scope) as session:
            return current(session, citations, with_body=body, allow_updated=allow_updated)

    def _carried(self, scope):
        with self.store.transaction(scope) as (session, _run):
            return ledger.carried(session, scope)

    def search(self, scope, arguments, *, intent_key=None):
        from .assistant_scope import retrieve

        call_id = self._started(scope, "assistant.search", arguments, intent_key)
        data = AssistantSearchInput.model_validate(arguments)
        updates = {}
        if scope.product_id is not None:
            if data.product_id not in (None, scope.product_id):
                ledger.deny("scope_expansion")
            updates["product_id"] = scope.product_id
        if scope.project_id and data.project_id not in (None, scope.project_id):
            ledger.deny("scope_expansion")
        if scope.project_id:
            updates["project_id"] = scope.project_id
        if scope.proposal_id:
            if data.proposal_id not in (None, scope.proposal_id):
                ledger.deny("scope_expansion")
            updates["proposal_id"] = scope.proposal_id
        data = data.model_copy(update=updates)
        query = (
            self.query_embedding.prepare(scope, call_id, arguments)
            if self.query_embedding else None
        )
        with human_snapshot(self.store.engine, scope) as session:
            result = retrieve(
                session,
                Context(
                    scope.tenant_id,
                    scope.requester_id,
                    scope.requester_id,
                    category_id=scope.category_id,
                ),
                scope, data, searcher=query.search if query is not None else None,
            )
            items = [{**item, "citation_id": ledger.citation_id(scope.run_id, call_id, item)}
                     for item in result["items"]]
        result["items"], result["returned"] = items, len(items)
        return result

    def restore_search(self, scope, _arguments, previous):
        actual = self._selected(scope, [UUID(row["citation_id"]) for row in previous["items"]])
        if any(actual[row["citation_id"]] != row for row in previous["items"]):
            ledger.deny("search_result_changed")
        rows, missing = self._current(scope, actual)
        if missing:
            code = (
                "SOURCE_STALE"
                if set(missing.values()) <= {"source_changed", "source_dependency_changed"}
                else "SOURCE_UNAVAILABLE"
            )
            raise DomainError(code, "原检索引用已变化或不可用，请重新查询。")
        return deepcopy(previous)

    @staticmethod
    def region(item, source):
        if source["nature"] == "structured":
            # Extraction may select any registered field in this fixed record.
            # Keep every such field reachable through bounded, reauthorized pages.
            return 0, len(source["body"])
        start = max(0, item["locator"]["char_start"] - 1000)
        end = min(len(source["body"]), item["locator"]["char_end"] + 1000)
        if not 0 <= start < end <= len(source["body"]):
            raise DomainError("SOURCE_UNAVAILABLE", "引用的固定定位不完整。")
        return start, end

    def passage(self, scope, arguments, *, historical=False):
        data = PassageInput.model_validate(arguments)
        if scope.isolation != "assistant_extract" or data.citation_id not in scope.citation_ids:
            ledger.deny("isolated_citation_required")
        selected = self._selected(scope, [data.citation_id])
        inherited = {
            cid for cid, item in selected.items()
            if "origin_run_id" in item or historical and item["source_type"] == "knowledge"
        }
        actual, missing = self._current(scope, selected, body=True, allow_updated=inherited)
        if missing:
            raise DomainError("SOURCE_UNAVAILABLE", "固定引用当前不可读取。")
        cid = str(data.citation_id)
        source = actual[cid]
        start, end = self.region(selected[cid], source)
        offset = start + data.cursor
        if offset >= end:
            raise DomainError("INVALID_PAYLOAD", "段落游标超出服务器绑定范围。", 422)
        stop = min(offset + data.page_chars, end)
        return {
            "citation_id": cid,
            "source_revision": source["source_revision"],
            "content_hash": source["content_hash"],
            "read_basis_status": source["read_basis_status"],
            "text": source["body"][offset:stop],
            "locator": span(source, offset, stop),
            "range_chars": end - start,
            "next_cursor": stop - start if stop < end else None,
        }

    def extract(self, scope, arguments, *, intent_key=None):
        call_id = self._started(scope, "assistant.extract", arguments, intent_key)
        data = ExtractInput.model_validate(arguments)
        selected = self._selected(scope, data.citation_ids)
        inherited = {cid for cid, item in selected.items() if "origin_run_id" in item}
        actual, missing = self._current(scope, selected, body=True, allow_updated=inherited)
        rows, coverage, rejected = [], [], []
        failures = [{"citation_id": cid, "code": code} for cid, code in missing.items()]
        for cid in selected:
            source = actual.get(cid)
            if source is None:
                continue
            if source["nature"] == "structured":
                values = source["structured"]
                # Domain field bounds already govern this complete registered
                # record. The host limits its model view with controlled result.read.
                rows.append(
                    {
                        "citation_id": cid,
                        "statement": "已读取固定版本的企业结构化记录。",
                        "quote": structured_quote(source),
                        "values": values,
                        "as_of": source["as_of"].isoformat(),
                        "read_basis_status": source["read_basis_status"],
                        "locator": {
                            "json_pointer": "/content"
                            if source["source_type"] == "knowledge"
                            else "/facts"
                        },
                    }
                )
                coverage.append({"citation_id": cid, "complete": True, "kind": "structured"})
            else:
                if self.graph is None:
                    raise DomainError("SOURCE_UNAVAILABLE", "隔离提取执行端口尚未配置。")
                try:
                    outcome = self.graph(
                        scope.child("assistant_extract", citation_ids={UUID(cid)}),
                        selected[cid],
                        source,
                        data.question,
                        call_id,
                    )
                except DomainError as error:
                    failures.append({"citation_id": cid, "code": error.code})
                    continue
                rows.extend(outcome["rows"])
                coverage.append(outcome["coverage"])
                rejected.extend(outcome["rejected"])
        return {
            "version": 1,
            "rows": rows,
            "row_count": len(rows),
            "coverage": coverage,
            "failures": failures,
            "rejected": rejected,
            "partial": bool(failures or rejected or any(not row["complete"] for row in coverage)),
        }

    def restore_extract(self, scope, arguments, previous):
        selected = self._selected(scope, ExtractInput.model_validate(arguments).citation_ids)
        inherited = {cid for cid, item in selected.items() if "origin_run_id" in item}
        actual, missing = self._current(scope, selected, body=True, allow_updated=inherited)
        if missing:
            code = (
                "SOURCE_STALE"
                if set(missing.values()) <= {"source_changed", "source_dependency_changed"}
                else "SOURCE_UNAVAILABLE"
            )
            raise DomainError(code, "原提取引用已变化或不可用，请重新查询。")
        for row in previous["rows"]:
            source = actual.get(row["citation_id"])
            if source is None or row["quote"] not in source["body"]:
                ledger.deny("evidence_changed")
            if "values" in row and row["values"] != source["structured"]:
                ledger.deny("structured_evidence_changed")
        return deepcopy(previous)

    def guard(self, scope):
        if scope.isolation in {"assistant_extract", "assistant_compare"}:
            self._selected(scope, scope.citation_ids)
        with self.store.transaction(scope) as (session, run):
            action = any(run.versions.get(key) is not None
                         for key in ("verification_action", "work_followup_action"))
            if not action:
                selected, historical = ledger.carried(session, scope)
        with human_snapshot(self.store.engine, scope) as session:
            if action:
                from pdos_next.agent_kernel.models import AgentRun

                from .action_sources import _discussion_footprint

                ctx = Context(scope.tenant_id, scope.requester_id, scope.requester_id,
                              category_id=scope.category_id)
                _selected, historical, selected = _discussion_footprint(
                    session, ctx, session.get(AgentRun, scope.run_id),
                )
            actual, missing = current(session, selected, allow_updated=historical)
        if missing:
            raise DomainError("SOURCE_UNAVAILABLE", "运行携带的企业引用已失效，请重新查询。")
        if action:
            from .action_taint import classify

            taint = classify(actual)
            if (taint["private"] and not scope.private_context
                or taint["customer_original"] and "customer_original" not in scope.data_categories):
                raise DomainError(
                    "CONVERSATION_HISTORY_REVOKED",
                    "旧运行未绑定完整来源分类，请从原讨论重新续接。",
                )
        categories = set(scope.data_categories)
        for source in actual.values():
            categories.add("internal")
            if source["customer_original"]:
                categories.add("customer_original")
        return frozenset(categories)

    def guard_action(self, scope, tool):
        with self.store.transaction(scope) as (_session, run):
            work_action = deepcopy(run.versions.get("work_followup_action"))
        if work_action is not None:
            if tool != "work.task.create":
                raise DomainError("FORBIDDEN_SCOPE", "本次资料跟进只准备任务创建候选。", 403)
            from pdos_next.agent_kernel.models import AgentRun

            from .work_followup_actions import check_action

            with human_snapshot(self.store.engine, scope) as session:
                ctx = Context(scope.tenant_id, scope.requester_id, scope.requester_id,
                              category_id=scope.category_id)
                check_action(session, ctx, session.get(AgentRun, scope.run_id), work_action)
            return
        from .verification_candidates import PREPARATION

        if tool == PREPARATION:
            with self.store.transaction(scope) as (_session, run):
                action = deepcopy(run.versions.get("verification_action"))
            if action is not None:
                from pdos_next.agent_kernel.models import AgentRun

                from .verification_actions import check_action

                with human_snapshot(self.store.engine, scope) as session:
                    ctx = Context(tenant_id=scope.tenant_id, actor_id=scope.requester_id,
                                  requester_id=scope.requester_id, category_id=scope.category_id)
                    check_action(session, ctx, session.get(AgentRun, scope.run_id), action)
                return
        selected, historical = self._carried(scope)
        if not selected:
            return
        with human_snapshot(self.store.engine, scope) as session:
            actual, missing = current(session, selected, allow_updated=historical)
        if missing:
            raise DomainError("SOURCE_UNAVAILABLE", "运行携带的企业依据已不可用。")
        with self.store.transaction(scope) as (_session, run):
            bound = {(row["artifact_id"], row["expected_revision"]) for row in run.read_sources}
        unbound = any(
            item["source_type"] != "artifact"
            or (item["source_id"], item["source_revision"]) not in bound
            or source["private"]
            and not scope.private_context
            or source["customer_original"]
            and "customer_original" not in scope.data_categories
            for cid, item in selected.items()
            for source in [actual[cid]]
        )
        if unbound:
            raise DomainError(
                "FORBIDDEN_SCOPE",
                "请先将所用资料与处理目标一并确认，再继续办理。",
                403,
                detail={"reason_key": "assistant_source_carry_required", "tool": tool},
            )
