"""Read-only research subtasks in the same registered 小Pai graph and Temporal Activity."""

import asyncio
import json
from contextlib import nullcontext
from dataclasses import asdict

from pdos_next.errors import DomainError
from pdos_next.research.tools import ReadInput, SearchInput
from pdos_next.research.types import LedgerDraft

from .graph import AgentKernel, Budget
from .tools import default_registry


class ResearchGraph:
    def __init__(self, host, *, checkpointer_factory=None):
        self.host, self.checkpointer_factory = host, checkpointer_factory

    async def __call__(self, task, child):
        loop = asyncio.get_running_loop()
        scope = child._scope  # Already created by the server's ResearchService, never model input.
        context = json.loads(json.dumps(asdict(task), default=str))
        host = self.host

        class ReadOnlyHost:
            def current(self, bound):
                host.current(bound)

            def enabled(self, *_):
                return False

            def qualified(self, *_):
                return False

            def context(self, *_):
                return {
                    "research_task": context,
                    "output_contract": LedgerDraft.model_json_schema(),
                    "instruction": "Return result.rows as LedgerDraft objects. "
                    "Search then read sources. "
                    "Quote only exact substrings at a location you actually read.",
                }

            def model(self, bound, **kwargs):
                if hasattr(host, "gateway"):
                    return host.gateway.turn(
                        bound, emit=lambda event: self.emit(bound, event), **kwargs
                    )
                return host.model(bound, **kwargs)

            def read(self, bound, spec, arguments, intent_key):
                self.current(bound)
                if spec.name == "research.search":
                    data = SearchInput.model_validate(arguments)
                    hits = asyncio.run_coroutine_threadsafe(child.search(data.query), loop).result()
                    return {"hits": [asdict(h) for h in hits]}
                if spec.name == "research.read":
                    data = ReadInput.model_validate(arguments)
                    page = asyncio.run_coroutine_threadsafe(
                        child.read(data.url, cursor=data.cursor), loop
                    ).result()
                    return {
                        "snapshot_id": str(page.snapshot.id),
                        "locator": page.locator,
                        "markdown": page.markdown,
                        "next_cursor": page.next_cursor,
                    }
                raise DomainError("FORBIDDEN_SCOPE", "研究子任务只拥有 search/read。")

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
                state = AgentKernel(
                    ReadOnlyHost(), default_registry(), budget=Budget(model_turns=8, tool_calls=20)
                ).execute(scope, goal=task.focus, execution_key=context, checkpointer=saver)
            if state.get("__interrupt__"):
                raise DomainError("SOURCE_UNAVAILABLE", "研究子任务未完成，需主循环澄清。")
            output = state["output"]
            if output["status"] != "completed":
                raise DomainError("SOURCE_UNAVAILABLE", "研究子任务未形成已核对台账。")
            return output["result"].get("rows", [])

        return await asyncio.to_thread(execute)
