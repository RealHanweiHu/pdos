"""Read-only research subtasks in the same registered 小Pai graph and Temporal Activity."""

import asyncio
import json
from contextlib import nullcontext
from dataclasses import asdict

from pdos_next.errors import DomainError
from pdos_next.research.tools import ReadInput, SearchInput
from pdos_next.research.types import LedgerDraft

from .graph import AgentKernel, Budget
from .host import BoundHost
from .read_execution import ReadSource
from .research_read_ledger import page_result, restore_page, restore_search
from .tools import default_registry


class ResearchGraph:
    def __init__(
        self, host, *, checkpointer_factory=None, artifacts=None, registered_reads=None,
        instruction_for=None,
    ):
        self.host, self.checkpointer_factory = host, checkpointer_factory
        self.artifacts = artifacts
        self.registered_reads = registered_reads
        self.instruction_for = instruction_for

    async def __call__(self, task, child):
        loop = asyncio.get_running_loop()
        scope = child._scope  # Already created by the server's ResearchService, never model input.
        context = json.loads(json.dumps(asdict(task), default=str))
        host = self.host
        artifacts = self.artifacts
        registered_read = getattr(self.registered_reads, "read", None)
        instruction_for = self.instruction_for
        instruction = instruction_for(scope) if instruction_for else None

        class ReadOnlyHost:
            def current(self, bound):
                host.current(bound)
                if instruction_for and instruction_for(bound) != instruction:
                    raise DomainError("VERSION_CONFLICT", "原研究子任务说明不能静默替换。")

            def enabled(self, *_):
                return False

            def qualified(self, *_):
                return False

            def restore_checkpoint(self, bound, state):
                from .research_checkpoint import restore_reads

                self.current(bound)
                if instruction:
                    try:
                        actual = json.loads(state["messages"][0]["content"])["context"]
                        if actual["research_skill"] != instruction.context():
                            raise ValueError
                    except (KeyError, IndexError, TypeError, ValueError):
                        raise DomainError(
                            "VERSION_CONFLICT", "原研究检查点技能说明已变化。"
                        ) from None
                restore_reads(host, child, state, self.read)

            def context(self, *_):
                return {
                    "research_task": context,
                    "output_contract": LedgerDraft.model_json_schema(),
                    "instruction": "Return result.rows as LedgerDraft objects. "
                    "Search then read sources. "
                    "Quote only exact substrings at a location you actually read.",
                    **({"research_skill": instruction.context()} if instruction else {}),
                }

            def model(self, bound, **kwargs):
                self.current(bound)
                if instruction:
                    try:
                        initial = kwargs["messages"][0]
                        actual = json.loads(initial["content"])["context"]["research_skill"]
                        if initial["role"] != "user" or actual != instruction.context():
                            raise ValueError
                    except (KeyError, IndexError, TypeError, ValueError):
                        raise DomainError(
                            "VERSION_CONFLICT", "原研究检查点未包含固定的子任务说明。"
                        ) from None
                    kwargs["loaded_skills"] = (instruction.skill,)
                if hasattr(host, "gateway"):
                    return host.gateway.turn(
                        bound, emit=lambda event: self.emit(bound, event), **kwargs
                    )
                return host.model(bound, **kwargs)

            def read(self, bound, spec, arguments, intent_key, *, source: ReadSource | None = None):
                self.current(bound)
                if spec.name == "research.search":
                    data = SearchInput.model_validate(arguments)

                    def callback(*_):
                        hits = asyncio.run_coroutine_threadsafe(
                            child.search(data.query), loop
                        ).result()
                        return {
                            "hits": [asdict(h) for h in hits],
                            "provider": child._service.search_adapter.provider,
                        }

                    def restore(previous):
                        return restore_search(child, data.query, previous, current=self.current)

                elif spec.name == "research.read":
                    data = ReadInput.model_validate(arguments)
                    if (
                        isinstance(host, BoundHost) and callable(registered_read)
                        and callable(getattr(host, "read_callback", None))
                    ):
                        if not isinstance(source, ReadSource):
                            raise DomainError("FORBIDDEN_SCOPE", "研究读取缺少实际模型账本来源。")
                        registered = registered_read(
                            host, child, spec, arguments, intent_key, source=source,
                        )
                        if registered is not None:
                            if artifacts is not None:
                                for page in child.pages.values():
                                    if str(page.snapshot.id) == registered["snapshot_id"]:
                                        artifacts.save_snapshot(bound, page.snapshot)
                            return registered

                    def callback(*_):
                        page = asyncio.run_coroutine_threadsafe(
                            child.read(data.url, cursor=data.cursor), loop
                        ).result()
                        if artifacts is not None:
                            artifacts.save_snapshot(bound, page.snapshot)
                        return page_result(page)

                    def restore(previous):
                        return restore_page(
                            child, data, previous, artifacts=artifacts, current=self.current
                        )

                else:
                    raise DomainError("FORBIDDEN_SCOPE", "研究子任务只拥有 search/read。")
                read_callback = getattr(host, "read_callback", None)
                if callable(read_callback):
                    return read_callback(
                        bound, spec, arguments, intent_key, source=source,
                        callback=callback, restore=restore, read_kind="ordinary/v1",
                    )
                if source is not None:
                    raise DomainError("FORBIDDEN_SCOPE", "研究读取缺少实际模型账本宿主。")
                # Legacy pure graph harnesses produce no trusted execution reference.
                return callback()

            def prepare(self, *_):
                raise DomainError("FORBIDDEN_SCOPE", "研究子任务无写权。")

            def write(self, *_):
                raise DomainError("FORBIDDEN_SCOPE", "研究子任务无写权。")

            def receipt(self, *_):
                raise DomainError("FORBIDDEN_SCOPE", "研究子任务无写权。")

            def verify(self, bound, output, results):
                self.current(bound)
                rows = []
                for raw in output["result"].get("rows", []):
                    draft = LedgerDraft.model_validate(raw)
                    child.verify(draft)
                    rows.append(draft.model_dump(mode="json"))
                return {**output, "result": {"rows": rows}}

            def emit(self, bound, event):
                # Raw child source text never re-enters the main model or its process payload.
                host.emit(
                    bound,
                    {
                        "type": "research_child",
                        "event_type": event.get("type"),
                        "task_key": task.key,
                        **{key: event[key] for key in ("tool", "status", "code") if key in event},
                    },
                )

            def finish(self, bound, output):
                self.current(bound)  # Never finish the parent Run.

        def execute():
            checkpoint = (
                self.checkpointer_factory() if self.checkpointer_factory else nullcontext(None)
            )
            with checkpoint as saver:
                execution = (
                    {"job_id": str(child.job_id), "task": context}
                    if getattr(child, "job_id", None) is not None else context
                )
                state = AgentKernel(
                    ReadOnlyHost(), default_registry(), budget=Budget(model_turns=8, tool_calls=20)
                ).execute(scope, goal=task.focus, execution_key=execution, checkpointer=saver)
            if state.get("__interrupt__"):
                raise DomainError("SOURCE_UNAVAILABLE", "研究子任务未完成，需主循环澄清。")
            output = state["output"]
            if output["status"] != "completed":
                raise DomainError("SOURCE_UNAVAILABLE", "研究子任务未形成已核对台账。")
            return output["result"].get("rows", [])

        return await asyncio.to_thread(execute)
