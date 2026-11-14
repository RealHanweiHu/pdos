"""Prompt A/B with the real model for the memory-proposal contract (D298, P121 第 8、9 项).

Opt-in only: it sends synthetic messages to the configured provider and costs real
tokens. It runs only when ``PDOS_MEMORY_PROPOSAL_AB_REAL`` names the host's model
runtime metadata file (the API key stays in the host's secure store and is never
read here). Everything else is the isolated ``pdos_test`` and a local Temporal.

Two arms, each a whole "before" or "after":

* ``baseline``: active prompt 1.0.0, ``memory.search`` defined as before this change
  (no personal notes, aliases, vectors or ``as_of`` in its calling note or schema),
  the proposal gate closed. Set only inside this test process.
* ``candidate``: prompt draft 1.1.0 (``memory_candidates`` in the output contract),
  today's ``memory.search`` definition, and the gate open for 1.1.0 only. Also set
  only inside this test process; nothing here activates or releases a prompt.

Two parts:

* ``timeline``: the existing memory timeline questions, current implementation
  (``real`` group of ``test_eval_memory_timeline_real_pg``), once per arm.
* ``probes``: ``docs/evaluations/xiaopai-memory-v0/proposal-probes.json``; each probe
  is a new Session whose turns are sent in order.

One JSON observation per question or probe goes under
``PDOS_MEMORY_PROPOSAL_AB_OUTPUT_DIR/<arm>/<part>/``. Nothing is judged here;
``tools/xiaopai_memory_proposal_ab.py`` scores by rule.
"""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from pdos_next.agent.kernel.activities import KernelActivities
from pdos_next.agent.kernel.models import AgentRun, AgentToolCall
from pdos_next.agent.kernel.prompts import PromptCatalog
from pdos_next.agent.kernel.temporal_port import TemporalPort, workflow_id
from pdos_next.agent.kernel.work_state import PAGE_MATERIAL_BOUNDARY
from pdos_next.agent.memory import candidates
from pdos_next.agent.memory.models import MemoryCandidate, MemoryProposalVoid
from pdos_next.api import create_app
from pdos_next.workflows.worker import graph_plugin
from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork
from tests.agent.memory import test_eval_memory_timeline_real_pg as timeline_real

ROOT = Path(__file__).resolve().parents[4]
SOURCE = os.environ.get("PDOS_MEMORY_PROPOSAL_AB_REAL")
OUTPUT = os.environ.get("PDOS_MEMORY_PROPOSAL_AB_OUTPUT_DIR")
ARMS = tuple(filter(None, os.environ.get(
    "PDOS_MEMORY_PROPOSAL_AB_ARMS", "baseline,candidate").split(",")))
ONLY = set(filter(None, os.environ.get("PDOS_MEMORY_PROPOSAL_AB_ONLY", "").split(",")))
CANDIDATE = "1.1.0"
OBSERVATION = "xiaopai-memory-proposal-ab-observation/v0"
PROBES = json.loads(
    (ROOT / "docs/evaluations/xiaopai-memory-v0/proposal-probes.json").read_text())["probes"]
REPLY = "没有更多信息，按你的理解处理。"
RUN_SECONDS = 600
# memory.search as registered before this change (commit fbcda6bc), for the baseline arm.
BASELINE_WHEN = (
    "需要回忆你本人以往和小Pai做过的工作（例如“上周比过的方案”“上次那份报价”）时调用；"
    "默认只查当前范围，个人入口查本人全部；结果是带 as_of 的情景卡，不是业务事实，"
    "不能作为依据引用，要看当时的回答再用 conversation.history 并传 session_id"
)

pytestmark = pytest.mark.skipif(
    not SOURCE or not OUTPUT or not timeline_real.BINARY.is_file(),
    reason="Opt-in real-provider run: set PDOS_MEMORY_PROPOSAL_AB_REAL and _OUTPUT_DIR",
)


def facts(setup, run_id):
    """Server facts every observation carries, so the two arms can be told apart."""
    with Session(setup.admin) as session:
        run = session.get(AgentRun, run_id)
        versions = run.versions or {}
        stored = session.scalars(select(MemoryCandidate).where(
            MemoryCandidate.run_id == run_id).order_by(MemoryCandidate.created_at)).all()
        return {
            "prompt_version": (versions.get("prompt_identities", {}).get("main") or {}).get(
                "version"),
            "tool_definitions_digest": (versions.get("tool_definitions") or {}).get("main"),
            "candidates": [{"origin": row.origin, "kind": row.kind, "text": row.text,
                            "scope_kind": row.scope_kind, "alias_term": row.alias_term,
                            "trigger": row.trigger} for row in stored],
            "proposals_rejected": [item.get("reason") for item in (
                versions.get("work_state_proposals") or {}).get("rejected", [])],
            "voids": session.scalar(select(func.count()).select_from(MemoryProposalVoid).where(
                MemoryProposalVoid.session_id == run.session_id)),
        }


def use_arm(monkeypatch, arm):
    assert arm in {"baseline", "candidate"}
    monkeypatch.setattr(timeline_real, "SOURCE", SOURCE)
    if arm == "candidate":
        monkeypatch.setattr(PromptCatalog, "active",
                            property(lambda self: self.version(CANDIDATE)))
        monkeypatch.setattr(candidates, "MEMORY_CANDIDATE_PROMPT_VERSIONS",
                            frozenset({CANDIDATE}))
        return
    from pdos_next.agent.kernel import command_usage
    from pdos_next.agent.memory.recall import MemorySearchInput

    usage = replace(command_usage.registry()["memory.search"], when=BASELINE_WHEN)
    schema = MemorySearchInput.model_json_schema()
    schema["properties"].pop("as_of")
    original = timeline_real.Bootstrap

    def bootstrap(*args, **kwargs):
        value = original(*args, **kwargs)
        spec = value.registry._specs["memory.search"]
        value.registry._specs["memory.search"] = replace(
            spec, description=usage.description("memory.search", "READ", "read"),
            input_schema=schema)
        return value

    monkeypatch.setattr(timeline_real, "Bootstrap", bootstrap)


def folder(arm, part):
    path = Path(OUTPUT) / arm / part
    path.mkdir(parents=True, exist_ok=True)
    return path


TIMELINES = [item for item in timeline_real.CASES["timelines"] if item.get("questions")
             and (not ONLY or f"timeline:{item['id']}" in ONLY or "timeline" in ONLY)]
SELECTED = [item for item in PROBES if not ONLY or item["id"] in ONLY or "probes" in ONLY]


@pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True)
@pytest.mark.parametrize("arm", ARMS)
@pytest.mark.parametrize("timeline", TIMELINES, ids=lambda item: item["id"])
def test_existing_timeline_questions_per_arm(setup, tmp_path, monkeypatch, arm, timeline):
    use_arm(monkeypatch, arm)
    target = folder(arm, "timeline")
    monkeypatch.setenv("PDOS_MEMORY_TIMELINE_OUTPUT_DIR", str(target))
    monkeypatch.setattr(timeline_real, "ONLY", set())
    plain = timeline_real.observed

    def observed(setup_value, replay, run_id):
        return {**plain(setup_value, replay, run_id), "arm": arm, **facts(setup_value, run_id)}

    monkeypatch.setattr(timeline_real, "observed", observed)
    timeline_real.test_real_model_answers_timeline_questions(
        setup, tmp_path, monkeypatch, "real", timeline)


@pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True)
@pytest.mark.parametrize("arm", ARMS)
def test_proposal_probes_per_arm(setup, tmp_path, monkeypatch, arm):
    if not SELECTED:
        pytest.skip("No probe selected")
    use_arm(monkeypatch, arm)
    ports, bootstrap, model = timeline_real.configure_model(setup, tmp_path, monkeypatch, "real")
    target = folder(arm, "probes")
    path = f"/v1/categories/{setup.category}/agent-runs"

    async def turn(environment, http, body):
        began = time.monotonic()
        started = await http.post(path, headers=setup.headers, json={
            **body, "idempotency_key": str(uuid4())})
        assert started.status_code == 202, started.text
        run_id = UUID(started.json()["run_id"])
        handle = environment.client.get_workflow_handle(workflow_id(setup.tenant, run_id))
        task = asyncio.ensure_future(handle.result())
        asked, replied, timed_out = [], 0, False
        while not task.done():
            await asyncio.wait([task], timeout=1)
            if task.done():
                break
            if time.monotonic() - began > RUN_SECONDS:
                timed_out = True
                task.cancel()
                await handle.terminate(reason="memory proposal evaluation time limit")
                break
            pending = await handle.query(XiaopaiGraphWork.pending_input)
            if pending and "questions" in pending[0] and replied < 1:
                asked.extend(item.get("text") or item.get("question") or ""
                             for item in pending[0]["questions"])
                submitted = await http.post(
                    f"{path}/{run_id}/answers", headers=setup.headers,
                    json={"answers": {item["id"]: REPLY for item in pending[0]["questions"]},
                          "idempotency_key": "answer:" + str(uuid4())})
                assert submitted.status_code == 202, submitted.text
                replied += 1
                while await handle.query(XiaopaiGraphWork.pending_input):
                    await asyncio.sleep(0.2)
        status = "timeout" if timed_out else (await asyncio.wait_for(task, 60)).get("status")
        with Session(setup.admin) as session:
            run = session.get(AgentRun, run_id)
            calls = session.execute(
                select(AgentToolCall.tool, func.count()).where(AgentToolCall.run_id == run_id)
                .group_by(AgentToolCall.tool)).all()
            result = run.result or {}
            value = {
                "run_id": str(run_id), "goal": body["goal"].partition(PAGE_MATERIAL_BOUNDARY)[0],
                "status": status, "state": run.state, "error_code": run.error_code,
                "seconds": round(time.monotonic() - began, 1),
                "used_tokens": run.used_tokens, "held_tokens": run.held_tokens,
                "answer": result.get("summary", ""), "unfinished": result.get("unfinished", []),
                "final_questions": [item.get("text") or item.get("question") or ""
                                    for item in result.get("questions", [])],
                "clarifications": asked,
                "tool_calls": {tool: count for tool, count in sorted(calls)},
            }
        return run_id, {**value, **facts(setup, run_id)}

    async def actual():
        environment = await WorkflowEnvironment.start_local(
            dev_server_existing_path=str(timeline_real.BINARY))
        try:
            port = TemporalPort(environment.client, task_queue="memory-ab-" + str(uuid4()))

            def binding(*args):
                value = bootstrap.binding_for(*args)
                value.token_limit = 2_000_000  # Same per-run allowance as the real evaluations.
                return value

            app = create_app(
                setup.engine, setup.auth, agent_runtime_ports=ports,
                agent_api_ports=replace(bootstrap.api_ports(port), binding_for=binding),
            )
            plugin, run_activities = graph_plugin(setup.engine, technical_engine=setup.dispatch)
            legacy = KernelActivities(setup.engine, technical_engine=setup.dispatch)
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    environment.client, task_queue=port.task_queue,
                    workflows=[XiaopaiGraphWork],
                    activities=[*run_activities, legacy.reconcile],
                    plugins=[plugin], activity_executor=executor,
                ), httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://synthetic.local",
                ) as http:
                    for probe in SELECTED:
                        turns, previous = [], None
                        for item in probe["turns"]:
                            goal = item["goal"]
                            if item.get("page_material"):
                                goal = f"{goal}{PAGE_MATERIAL_BOUNDARY}{item['page_material']}"
                            body = {"goal": goal}
                            if previous is not None:
                                body["continue_from_run_id"] = str(previous)
                            previous, record = await turn(environment, http, body)
                            turns.append(record)
                        with Session(setup.admin) as session:
                            first = session.get(AgentRun, UUID(turns[0]["run_id"]))
                            pending = [row.text for row in session.scalars(
                                select(MemoryCandidate).where(
                                    MemoryCandidate.session_id == first.session_id)).all()
                                if candidates.status(
                                    row, None, row.created_at,
                                    voided=row.id in candidates._voided(session, [row]),
                                ) == "pending"]
                        record = {
                            "version": OBSERVATION, "arm": arm, "probe": probe["id"],
                            "expect": probe["expect"], "model": model["model"],
                            "model_version": model["model_version"], "turns": turns,
                            "pending_candidates_at_end": pending,
                        }
                        (target / f"{probe['id']}.json").write_text(
                            json.dumps(record, ensure_ascii=False, indent=2) + "\n")
                        last = turns[-1]
                        print("AB", arm, probe["id"], last["status"],
                              sum(item["used_tokens"] or 0 for item in turns),
                              [item["candidates"] for item in turns],
                              [item["proposals_rejected"] for item in turns],
                              last["answer"][:160].replace("\n", " "))
        finally:
            await environment.shutdown()

    asyncio.run(actual())
    assert len(list(target.glob("*.json"))) >= len(SELECTED)
