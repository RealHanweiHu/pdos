"""Unfinished research retains its server parameter plan; a finished job never restarts."""

from uuid import uuid4

import pytest

from pdos_next.agent_kernel.research_adapter import ResearchArtifacts, ResearchReadAdapter
from pdos_next.errors import DomainError
from pdos_next.research.tools import ResearchToolHost
from pdos_next.research.types import LedgerDraft, ParameterVersion
from tests.agent_kernel.research.test_research import scope, service


class ProcessStopped(BaseException):
    pass


def composition(tmp_path, researcher):
    bound = scope()
    artifacts = ResearchArtifacts(tmp_path, current=lambda _: None)
    instance = service()
    instance.snapshot_sink = artifacts.save_snapshot
    parameters = [ParameterVersion(uuid4(), 1)]
    host = ResearchToolHost(
        instance, researcher=researcher, parameter_versions=lambda _: parameters,
    )
    adapter = ResearchReadAdapter(host, artifacts, user_messages=lambda _: [])
    return adapter, bound, parameters, instance


def test_unfinished_job_refuses_changed_server_parameter_versions_before_new_work(tmp_path):
    calls = []

    async def interrupted(*_):
        calls.append(True)
        raise ProcessStopped()

    adapter, bound, parameters, _ = composition(tmp_path, interrupted)
    arguments = {"tasks": [{"key": "specs", "focus": "public pressure"}]}
    with pytest.raises(ProcessStopped):
        adapter.resume(bound, arguments, intent_key="same-server-call")
    parameters[0] = ParameterVersion(parameters[0].parameter_id, 2)
    with pytest.raises(DomainError) as error:
        adapter.resume(bound, arguments, intent_key="same-server-call")
    assert error.value.code == "DUPLICATE_INTENT_CONFLICT" and len(calls) == 1


def test_saved_job_recovers_after_parent_settle_is_missed_without_research_or_network(tmp_path):
    calls = []

    async def researcher(_task, child):
        calls.append(True)
        hits = await child.search("pump")
        page = await child.read(hits[0].url)
        return [LedgerDraft(
            brand="Maker", model="P1", free_key="pressure", value=20,
            quote="Pressure: 20 psi", snapshot_id=page.snapshot.id, locator=page.locator,
        )]

    adapter, bound, _, instance = composition(tmp_path, researcher)
    arguments = {"tasks": [{"key": "specs", "focus": "public pressure"}]}
    first = adapter.resume(bound, arguments, intent_key="same-server-call")
    before = len(instance.transport.requests), len(instance.search_adapter.queries)
    assert adapter.resume(bound, arguments, intent_key="same-server-call") == first
    assert len(calls) == 1
    assert before == (len(instance.transport.requests), len(instance.search_adapter.queries))


def test_identical_tasks_in_different_jobs_have_independent_child_checkpoints():
    import asyncio
    from contextlib import nullcontext
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver

    from pdos_next.agent_kernel.research_graph import ResearchGraph
    from pdos_next.research.types import ResearchTask
    from tests.agent_kernel.test_research_instruction import Host

    host, saver = Host(), InMemorySaver()
    graph = ResearchGraph(host, checkpointer_factory=lambda: nullcontext(saver))
    bound, task = scope().child("research"), ResearchTask("same", "same public question")
    first = SimpleNamespace(_scope=bound, job_id=uuid4())
    second = SimpleNamespace(_scope=bound, job_id=uuid4())
    assert asyncio.run(graph(task, first)) == []
    assert asyncio.run(graph(task, second)) == []
    assert len(host.models) == 2
    assert asyncio.run(graph(task, first)) == [] and len(host.models) == 2
