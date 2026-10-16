"""Stable registry schemas; parameter authority is projected by the host, never a tool input."""

from dataclasses import asdict

from pydantic import Field

from pdos_next.agent_kernel.registry import ToolSpec
from pdos_next.schema_base import StrictModel

from .service import _invoke
from .types import ResearchTask


class SearchInput(StrictModel):
    query: str = Field(min_length=1)


class ReadInput(StrictModel):
    url: str
    cursor: int = Field(default=0, ge=0)


class TaskInput(StrictModel):
    key: str = Field(min_length=1)
    focus: str = Field(min_length=1)
    brand: str | None = None
    source_type: str | None = None


class FanoutInput(StrictModel):
    tasks: list[TaskInput] = Field(min_length=1)


def research_tools():
    return [
        ToolSpec(
            "research.search",
            "搜索公开线索；查询须经服务器出站政策检查。",
            SearchInput.model_json_schema(),
            {"type": "object"},
            "research",
            "READ",
            taint="external_metadata",
            parallel_safe=True,
        ),
        ToolSpec(
            "research.read",
            "仅隔离研究子任务读取本轮已发现网址；允许续读。",
            ReadInput.model_json_schema(),
            {"type": "object"},
            "research",
            "READ",
            taint="untrusted_external",
            parallel_safe=True,
        ),
        ToolSpec(
            "research.fanout",
            "派发只读研究并返回逐字核对的台账与代码生成的覆盖。",
            FanoutInput.model_json_schema(),
            {"type": "object"},
            "research",
            "READ",
            taint="verified_external_rows",
            parallel_safe=True,
        ),
    ]


class ResearchToolHost:
    def __init__(self, service, *, researcher, parameter_versions):
        self.service, self.researcher = service, researcher
        self.parameter_versions = parameter_versions

    async def call(self, scope, name, arguments, *, job_id=None, pin_plan=None):
        if name == "research.search":
            payload = SearchInput.model_validate(arguments)
            return [asdict(hit) for hit in await self.service.search(scope, payload.query)]
        if name == "research.read":
            payload = ReadInput.model_validate(arguments)
            # Only this page enters child context; the full snapshot stays in the host.
            page = await self.service.read(scope, payload.url, cursor=payload.cursor)
            return {
                "snapshot_id": str(page.snapshot.id),
                "url": page.snapshot.final_url,
                "title": page.snapshot.title,
                "content_hash": page.snapshot.content_hash,
                "locator": page.locator,
                "markdown": page.markdown,
                "next_cursor": page.next_cursor,
            }
        if name == "research.fanout":
            payload = FanoutInput.model_validate(arguments)
            parameters = tuple(await _invoke(self.parameter_versions, scope))
            tasks = tuple(
                ResearchTask(task.key, task.focus, task.brand, task.source_type, parameters)
                for task in payload.tasks
            )
            if pin_plan is not None:
                pin_plan(tasks)
            result = await self.service.fanout(scope, tasks, self.researcher, job_id=job_id)
            return result.to_dict()
        raise ValueError("Unregistered research tool")
