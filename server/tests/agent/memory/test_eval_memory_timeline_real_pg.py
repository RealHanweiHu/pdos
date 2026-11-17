"""Real-model answers to the memory timeline questions (P121 B0; baselines 0-2 and ceiling).

Opt-in only: it sends synthetic questions to the configured provider and costs real
tokens. It runs only when ``PDOS_MEMORY_TIMELINE_REAL`` names the host's model runtime
metadata file (the API key stays in the host's secure store and is never read here).
Everything else is the isolated ``pdos_test`` and a local Temporal server.

For each timeline the history is replayed with scripted finishes, exactly as the
model-free replay does, so every group starts from the same recorded past. Only
the timeline's ``questions`` are answered by the real model, each in a new Session,
through the registered 小Pai workflow. Four groups:

* ``no_memory``: every Session has "不进记忆" on (baseline 0).
* ``history_only``: raw-history retrieval (baseline 1, user 2026-11-13: registered
  for evaluation only). Inside this test process the ``memory.search`` handler is
  replaced by ``history_only_search`` below, and the Run envelope carries neither
  personal notes nor the recent-episode catalog. Tool names, schemas, the prompt and
  ``conversation.history`` are unchanged, so the tool surface the model sees is the
  same as in ``real``. Nothing is added to the product's tool registry.
* ``real``: the current implementation (baseline 2).
* ``ideal``: the ceiling of target architecture §8.3, "ideal memory" (an evaluation
  emulation, not a product feature). Inside this test process the frozen
  recent-episode catalog is replaced by the question's annotated Runs (``ideal_runs``,
  by default ``expect_usage_runs``), each with the answer summary and unfinished items
  written into the catalog line, so the facts are in the Run's context from the first
  model call; and ``memory.search`` returns exactly those Runs for any query, with the
  stored answer excerpt, through the same per-item recheck and usage list. Personal
  notes, ``conversation.history``, the prompt and every tool definition stay as in
  ``real``. A question with no annotated Run gets an empty catalog and no episodes.

A question can also name a ``fault``. ``memory_unavailable`` (T24) makes
``memory.search`` fail with a domain error and drops the notes and catalog from the
envelope, in this test process only, as if the memory store could not be read.

``PDOS_MEMORY_TIMELINE_REAL_REPEATS`` runs every question that many times per group
(``-k rep0`` etc. select one repeat). ``PDOS_MEMORY_TIMELINE_REAL_TOKEN_CAP`` stops
starting new questions once the observations already in the output folder used that
many tokens; ``PDOS_MEMORY_TIMELINE_REAL_RUN_ALERT`` writes a ``STOP`` file there, and
every later question is skipped, as soon as a single question uses more than that.

One JSON observation per question goes to ``PDOS_MEMORY_TIMELINE_OUTPUT_DIR``.
Nothing is judged here; ``tools/xiaopai_memory_timeline_baseline.py score-real``
checks key facts and the server's usage list by rule.
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

from pdos_next.agent.kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.models import AgentRun, AgentToolCall, TenantAdministrator
from pdos_next.agent.kernel.temporal_port import TemporalPort, workflow_id
from pdos_next.api import create_app
from pdos_next.workflows.worker import graph_plugin
from pdos_next.workflows.xiaopai_graph import XiaopaiGraphWork
from tests.agent.kernel import test_budget_management as budgets
from tests.agent.kernel.test_model_configuration_transactions import submit
from tests.agent.memory.test_eval_memory_timeline_pg import CASES, Replay

BINARY = Path(__file__).resolve().parents[4] / ".local/tools/temporal"
SOURCE = os.environ.get("PDOS_MEMORY_TIMELINE_REAL")
OBSERVATION = "xiaopai-memory-timeline-real-observation/v0"
GROUPS = tuple(filter(None, os.environ.get(
    "PDOS_MEMORY_TIMELINE_REAL_GROUPS", "no_memory,real").split(",")))
REPEATS = int(os.environ.get("PDOS_MEMORY_TIMELINE_REAL_REPEATS") or 1)
TOKEN_CAP = int(os.environ.get("PDOS_MEMORY_TIMELINE_REAL_TOKEN_CAP") or 0)
RUN_ALERT = int(os.environ.get("PDOS_MEMORY_TIMELINE_REAL_RUN_ALERT") or 0)
FAULT_MESSAGE = "个人记忆暂时无法读取。"
ONLY = set(filter(None, os.environ.get("PDOS_MEMORY_TIMELINE_REAL_ONLY", "").split(",")))
# Diagnostics only (D477): record why a result failed verification or a node stopped.
DIAGNOSE = bool(os.environ.get("PDOS_MEMORY_TIMELINE_REAL_DIAGNOSE"))
REPLY = "没有更多信息。请只根据你能查到的以往记录回答；查不到就直接说明查不到。"
RUN_SECONDS = 900

pytestmark = pytest.mark.skipif(
    not SOURCE or not BINARY.is_file(),
    reason="Opt-in real-provider run: set PDOS_MEMORY_TIMELINE_REAL",
)


def selected(timeline, group=None):
    return [question for question in timeline.get("questions", [])
            if (not ONLY or f"{timeline['id']}/{question['id']}" in ONLY)
            and (group is None or group in question.get("groups", (group,)))]


TIMELINES = [timeline for timeline in CASES["timelines"] if selected(timeline)]


def ideal_runs(question):
    return question.get("ideal_runs", question.get("expect_usage_runs", []))


def spent(folder):
    """Tokens already used by the observations in the output folder (all processes)."""
    total = 0
    for path in folder.glob("*.real.json"):
        try:
            total += json.loads(path.read_text()).get("used_tokens") or 0
        except ValueError:
            continue
    return total


def host_config(tmp_path, tenant):
    """The host's provider entry, rebound to this run's synthetic tenant."""
    source = json.loads(Path(SOURCE).read_text())
    model, secret = source["models"][0], source["secrets"][0]
    path = tmp_path / "model-runtime.json"
    path.touch(mode=0o600)
    path.write_text(json.dumps({
        "format_version": source["format_version"], "kms": source["kms"],
        "secrets": [{**secret, "tenant_id": str(tenant)}],
        "models": [{**model, "tenant_id": str(tenant)}],
    }))
    return path, model


def configure_model(setup, tmp_path, monkeypatch, group, state):
    path, model = host_config(tmp_path, setup.tenant)
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    monkeypatch.setenv("PDOS_ENVIRONMENT", "development")
    monkeypatch.setenv("PDOS_STATE_DB_PORT", os.environ["TEST_DATABASE_PORT"])
    monkeypatch.setenv("PDOS_STATE_DB_MARKER", os.environ["TEST_DATABASE_MARKER"])
    from fastapi.testclient import TestClient

    from pdos_next.agent.model_configuration.host import runtime_ports
    from pdos_next.schemas.model_configuration import ModelMetadata

    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    ports = runtime_ports(setup.engine)
    management = TestClient(create_app(setup.engine, setup.auth, agent_runtime_ports=ports))
    saved, _ = submit(setup, management, {
        "command_id": str(uuid4()), "idempotency_key": str(uuid4()),
        "operation": "model.configuration.save", "category_id": str(setup.category),
        "expected_revision": 1, "product_id": None, "source_read_set": [],
        "payload": {"expected_revision": 0, "enabled": True, "metadata": ModelMetadata(
            protocol=model["protocol"], base_url=model["base_url"], model=model["model"],
            model_version=model["model_version"], context_window_tokens=200_000,
        ).model_dump(mode="json")},
    })
    assert saved.status_code == 200, saved.text
    budgets.allocate(setup)
    bootstrap = Bootstrap(setup.engine, ports=ports)
    monkeypatch.setattr(setup.engine, "_pdos_agent_kernel_adapters", None, raising=False)
    adapters = bootstrap.adapters()
    from pdos_next.agent.memory import assemble, recall

    search, catalog, notes = (adapters.read_tools["memory.search"], recall.frozen_catalog,
                              assemble.frozen)
    if group == "history_only":
        search = history_only_search(bootstrap.store)
        catalog = notes = lambda _session, _run: None
    if group == "ideal":
        search, catalog = ideal_search(bootstrap.store, state), ideal_catalog(state)
    # Evaluation only: the per-question fault (T24) wraps whatever the group uses.
    adapters.read_tools["memory.search"] = faulty(search, state)
    monkeypatch.setattr(recall, "frozen_catalog", faulty(catalog, state, envelope=True))
    monkeypatch.setattr(assemble, "frozen", faulty(notes, state, envelope=True))
    configure_agent_kernel(setup.engine, adapters)
    return ports, bootstrap, model


def history_only_search(store):
    """Evaluation only: ``memory.search`` answered from the raw history (baseline 1).

    Candidates are the requester's own earlier finished Runs in the Run's own range,
    read inside the Run's ordinary transaction under row-level security. Each is
    matched on the person's own words plus the stored answer summary, by keyword
    score only: no recency or pin weighting, no notes. Cards have exactly the shape
    of the real tool and pass the same per-item recheck, so the history reviewer and
    the usage list work unchanged; reading an answer still takes
    ``conversation.history``.
    """
    from pdos_next.agent.enterprise_search.tokenizer import analyze, analyze_query
    from pdos_next.agent.kernel.tool_arguments import tool_arguments
    from pdos_next.agent.memory import recall
    from pdos_next.agent.memory.models import MemoryEpisode

    def handler(scope, arguments):
        payload = tool_arguments(recall.MemorySearchInput, arguments)
        with store.transaction(scope, lock=True) as (session, run):
            kind, _condition = recall.scope_filter(run)
            response = {
                "version": recall.VERSION,
                "scope": {"kind": kind, "narrowed_to": payload.narrow_to},
                "items": [], "returned": 0, "next_offset": None,
                "unavailable_kinds": [item for item in payload.kinds if item == "scope_note"],
                "retrieval": {"channels": ["keyword"], "semantic": recall.SEMANTIC_OFF,
                              "ranking_version": "eval-history-only/v0;own-words+answer-summary",
                              "index_pending": 0},
                "fact_policy": recall.FACT_POLICY,
            }
            blocked = recall.unavailable(run, session)
            if blocked is not None:
                response.update(status=blocked[0], message=blocked[1])
                return response
            if "note" in payload.kinds:
                response.update(notes=[], notes_status="completed")
            response["status"] = "completed"
            if "episode" not in payload.kinds:
                return response
            parsed = analyze_query(payload.query)
            rows = session.execute(
                select(MemoryEpisode, AgentRun.result["summary"].astext)
                .join(AgentRun, AgentRun.id == MemoryEpisode.run_id)
                .where(*recall._base(run, payload))
            ).all()
            scored = []
            for episode, summary in rows:
                words = analyze(f"{episode.goal} {summary or ''}")
                value = recall.keyword_score(parsed, words["counts"], words["codes"])
                if value > 0:
                    scored.append((value, episode))
            scored.sort(key=lambda item: (-item[0], -item[1].created_at.timestamp(),
                                          str(item[1].id)))
            window = [episode for _value, episode in scored][payload.offset:]
            kept, access = recall.recheck(session, run, window[:recall.RECHECK_LIMIT],
                                          limit=payload.page_size)
            response["items"] = [recall.card(episode, state, where, receipts, {}, run)
                                 for episode, state, where, receipts in kept]
            response["returned"] = len(response["items"])
            recall.record_usage(
                run, episodes=[item["run_id"] for item in response["items"]], access=access,
                retrieval={"channels": ["keyword"], "semantic": "not_enabled",
                           "index_pending": 0})
            return response

    return handler


def faulty(callback, state, *, envelope=False):
    """Evaluation only: the memory store "cannot be read" while a question names that fault."""
    from pdos_next.errors import DomainError

    def wrapped(*args):
        if state.get("fault") == "memory_unavailable":
            if envelope:
                return None
            raise DomainError("SOURCE_UNAVAILABLE", FAULT_MESSAGE)
        return callback(*args)

    return wrapped


def _ideal_episodes(session, run, state):
    from pdos_next.agent.memory import recall
    from pdos_next.agent.memory.index import summaries
    from pdos_next.agent.memory.models import MemoryEpisode

    order = [str(value) for value in state.get("ideal", [])]
    rows = session.scalars(select(MemoryEpisode).where(
        MemoryEpisode.run_id.in_([UUID(value) for value in order]),
        MemoryEpisode.owner_id == run.requester_id)).all() if order else []
    rows = sorted(rows, key=lambda row: order.index(str(row.run_id)))
    kept, access = recall.recheck(session, run, rows, limit=10)
    return kept, access, summaries(session, [item[0] for item in kept])


def ideal_catalog(state):
    """Ceiling only: the catalog holds the annotated Runs, answer and unfinished items included."""
    from pdos_next.agent.memory import recall

    def frozen(session, run):
        if "memory_context" in run.versions:
            return run.versions["memory_context"]
        value = None
        if recall.unavailable(run, session) is None:
            kept, access, answers = _ideal_episodes(session, run, state)
            lines = []
            for episode, _state, _scope, _receipts in kept[:recall.CATALOG_SIZE]:
                line = recall.first_sentence(episode.goal, recall.CATALOG_GOAL_CHARS)
                line += f"｜当时小Pai 的回答：{answers.get(episode.run_id) or '（无）'}"
                unfinished = state.get("unfinished", {}).get(str(episode.run_id))
                if unfinished:
                    line += "｜当时未完成：" + "；".join(unfinished)
                lines.append({"run_id": str(episode.run_id), "session_id": str(episode.session_id),
                              "as_of": episode.created_at.date().isoformat(), "goal": line})
            if lines:
                value = {
                    "zone": "background",
                    "label": ("历史（as_of）：你本人在当前范围与本次相关的以往工作，"
                              "含当时小Pai 回答的摘录。不是业务事实，不能作为依据引用。"),
                    "how_to_use": ("需要更多细节时用 memory.search 或 "
                                   "conversation.history(session_id=…)。"),
                    "recent_episodes": lines,
                }
                ids = [item["run_id"] for item in lines]
                recall.record_usage(run, episodes=ids, catalog=ids,
                                    access={key: access[key] for key in access if key in ids})
        if run.state in recall.ACTIVE:
            run.versions = {**run.versions, "memory_context": value}
        return value

    return frozen


def ideal_search(store, state):
    """Ceiling only: ``memory.search`` returns exactly the annotated Runs for any query.

    Notes still come from the real note search; cards have the real shape, carry the
    stored answer excerpt and pass the same per-item recheck and usage list.
    """
    from pdos_next.agent.kernel.tool_arguments import tool_arguments
    from pdos_next.agent.memory import recall
    from pdos_next.agent.memory.note_search import search_notes

    def handler(scope, arguments):
        payload = tool_arguments(recall.MemorySearchInput, arguments)
        with store.transaction(scope, lock=True) as (session, run):
            kind, _condition = recall.scope_filter(run)
            response = {
                "version": recall.VERSION,
                "scope": {"kind": kind, "narrowed_to": payload.narrow_to},
                "items": [], "returned": 0, "next_offset": None,
                "unavailable_kinds": [item for item in payload.kinds if item == "scope_note"],
                "retrieval": {"channels": ["keyword"], "semantic": recall.SEMANTIC_OFF,
                              "ranking_version": "eval-ideal/v0;annotated-runs",
                              "index_pending": 0},
                "fact_policy": recall.FACT_POLICY,
            }
            blocked = recall.unavailable(run, session)
            if blocked is not None:
                response.update(status=blocked[0], message=blocked[1])
                return response
            if "note" in payload.kinds:
                response.update(search_notes(session, run, payload))
            response["status"] = "completed"
            if "episode" not in payload.kinds or payload.offset:
                return response
            kept, access, answers = _ideal_episodes(session, run, state)
            kept = kept[:payload.page_size]
            response["items"] = [recall.card(episode, item_state, where, receipts, {}, run,
                                             answer=answers.get(episode.run_id),
                                             matched=("episode", "answer"))
                                 for episode, item_state, where, receipts in kept]
            response["returned"] = len(response["items"])
            ids = [item["run_id"] for item in response["items"]]
            recall.record_usage(
                run, episodes=ids, access={key: access[key] for key in access if key in ids},
                retrieval={"channels": ["keyword"], "semantic": "not_enabled",
                           "index_pending": 0})
            return response

    return handler


def observed(setup, replay, run_id):
    """Server facts about one finished question: answer, ledger and the usage list."""
    with Session(setup.admin) as session:
        run = session.get(AgentRun, run_id)
        calls = session.execute(
            select(AgentToolCall.tool, AgentToolCall.state, func.count())
            .where(AgentToolCall.run_id == run_id)
            .group_by(AgentToolCall.tool, AgentToolCall.state)
        ).all()
        usage = (run.versions or {}).get("memory_usage") or {}
        sessions = {str(value) for value in usage.get("sessions", [])}
        read_sessions = sorted(
            key for key, value in replay.runs.items()
            if str(session.scalar(select(AgentRun.session_id).where(AgentRun.id == value)))
            in sessions)
        result = run.result or {}
        from pdos_next.agent.memory.models import MemoryCandidate, MemoryNote

        admitted = session.scalar(select(func.count()).select_from(MemoryCandidate).where(
            MemoryCandidate.run_id == run_id))
        rejected = [item.get("reason") for item in
                    ((run.versions or {}).get("work_state_proposals") or {}).get("rejected", [])]
        notes_now = session.scalar(select(func.count()).select_from(MemoryNote).where(
            MemoryNote.tenant_id == setup.tenant))
        return {
            "state": run.state, "error_code": run.error_code,
            "used_tokens": run.used_tokens, "held_tokens": run.held_tokens,
            "answer": result.get("summary", ""),
            "answer_blob": json.dumps(result, ensure_ascii=False),
            "unfinished": result.get("unfinished", []),
            "ledger": sorted(f"{tool}:{state}:{count}" for tool, state, count in calls),
            "memory_tool_calls": {tool: sum(count for name, _state, count in calls if name == tool)
                                  for tool in ("memory.search", "conversation.history")},
            "usage": {
                "episodes": sorted({replay.run_key(value) for value in usage.get("episodes", [])}),
                "catalog": sorted({replay.run_key(value) for value in usage.get("catalog", [])}),
                "sessions_read": read_sessions,
                "notes": sorted({replay.note_key(item["note_id"])
                                 for item in usage.get("notes", [])}),
                "note_revisions": {replay.note_key(item["note_id"]): item.get("revision")
                                   for item in usage.get("notes", [])},
            },
            # T13: what this Run left behind on the write side.
            "memory_candidates": {"admitted": admitted, "rejected": rejected},
            "new_notes": notes_now - replay.created_notes,
            "memory_off": bool((run.versions or {}).get("memory_mode", {}).get("off")),
        }


@pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True)
@pytest.mark.parametrize("repeat", range(REPEATS), ids=lambda value: f"rep{value}")
@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("timeline", TIMELINES, ids=lambda item: item["id"])
def test_real_model_answers_timeline_questions(setup, tmp_path, monkeypatch, group, timeline,
                                               repeat):
    assert group in {"no_memory", "history_only", "real", "ideal"}
    questions = selected(timeline, group)
    if not questions:
        pytest.skip(f"No question of {timeline['id']} runs in {group}")
    folder = Path(os.environ.get("PDOS_MEMORY_TIMELINE_OUTPUT_DIR") or tmp_path)
    if (folder / "STOP").exists():
        pytest.skip("Stopped: " + (folder / "STOP").read_text().strip())
    replay = Replay(setup, group)
    for event in timeline["events"]:
        getattr(replay, event["op"])(event)
    state = {"fault": None, "ideal": [], "unfinished": {
        str(replay.runs[event["id"]]): event["unfinished"] for event in timeline["events"]
        if event["op"] == "run" and event.get("unfinished")}}
    ports, bootstrap, model = configure_model(setup, tmp_path, monkeypatch, group, state)
    summaries = {event["id"]: event for event in timeline["events"] if event["op"] == "run"}
    path = f"/v1/categories/{setup.category}/agent-runs"
    records, reasons = [], []
    if DIAGNOSE:
        import sys

        from pdos_next.errors import DomainError

        original = DomainError.__init__

        def explain(self, code, message, *args, **kwargs):
            original(self, code, message, *args, **kwargs)
            frames, frame = [], sys._getframe(1)
            while frame is not None and len(frames) < 4:
                name = frame.f_code.co_filename
                if "/pdos_next/" in name:
                    frames.append(f"{name.split('/pdos_next/')[-1]}:{frame.f_lineno}:"
                                  f"{frame.f_code.co_name}")
                frame = frame.f_back
            reasons.append({"code": self.code, "reason": self.reason,
                            "message": str(self.message)[:300], "frames": frames})

        monkeypatch.setattr(DomainError, "__init__", explain)
        # What exactly the model wrote when its final output failed the structure check.
        from pydantic import ValidationError

        from pdos_next.agent.kernel.types import AgentOutput

        checked = AgentOutput.model_validate.__func__

        def recorded(cls, value, *args, **kwargs):
            try:
                return checked(cls, value, *args, **kwargs)
            except ValidationError:
                shape = value if isinstance(value, dict) else {"_": repr(value)[:200]}
                reasons.append({"code": "OUTPUT_STRUCTURE", "reason": "raw", "frames": [],
                                "message": json.dumps({
                                    "result_type": type(shape.get("result")).__name__,
                                    "questions": shape.get("questions"),
                                }, ensure_ascii=False, default=repr)[:1500]})
                raise

        monkeypatch.setattr(AgentOutput, "model_validate", classmethod(recorded))

    async def diagnostics(environment, handle):
        """Verification feedback sent back to the model, read from the workflow history."""
        import re

        from tests.agent.kernel.xiaopai_graph_plugin_harness import payloads

        feedback, turns = [], 0
        async for execution in environment.client.list_workflows(f'WorkflowId="{handle.id}"'):
            history = await environment.client.get_workflow_handle(
                execution.id, run_id=execution.run_id).fetch_history()
            text = payloads(history)
            feedback.extend(re.findall(r"字段核对错误：(\[.*?\])。list_type", text))
            turns += text.count("model_started")
        value = {"verification_feedback": sorted(set(feedback)), "domain_errors": list(reasons)}
        reasons.clear()
        return value

    async def one(environment, http, question):
        state["fault"] = question.get("fault")
        state["ideal"] = ([replay.runs[key] for key in ideal_runs(question)]
                          if group == "ideal" else [])
        injected = [" ".join([summaries[key].get("summary", ""), *summaries[key].get(
            "unfinished", [])]) for key in ideal_runs(question)] if group == "ideal" else []
        began = time.monotonic()
        started = await http.post(path, headers=replay.headers(question["actor"]), json={
            "goal": question["goal"], "idempotency_key": str(uuid4()),
            **({"memory_off": True} if replay.off(question) else {}),
        })
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
                await handle.terminate(reason="memory timeline evaluation time limit")
                break
            pending = await handle.query(XiaopaiGraphWork.pending_input)
            if pending and "questions" in pending[0] and replied < 2:
                asked.extend(item.get("text") or item.get("question") or ""
                             for item in pending[0]["questions"])
                answers = {item["id"]: REPLY for item in pending[0]["questions"]}
                submitted = await http.post(
                    f"{path}/{run_id}/answers", headers=replay.headers(question["actor"]),
                    json={"answers": answers, "idempotency_key": "answer:" + str(uuid4())})
                assert submitted.status_code == 202, submitted.text
                replied += 1
                while await handle.query(XiaopaiGraphWork.pending_input):
                    await asyncio.sleep(0.2)
        status = "timeout"
        if not timed_out:
            status = (await asyncio.wait_for(task, 60)).get("status")
        extra = {"diagnostics": await diagnostics(environment, handle)} if DIAGNOSE else {}
        return {
            **extra,
            "version": OBSERVATION, "group": group, "timeline": timeline["id"],
            "question": question["id"], "repeat": repeat, "fault": question.get("fault"),
            "ideal_runs": ideal_runs(question) if group == "ideal" else [],
            "injected_text": "\n".join(injected), "model": model["model"],
            "model_version": model["model_version"], "scripted_history": True,
            "status": status, "seconds": round(time.monotonic() - began, 1),
            "clarifications": asked, **observed(setup, replay, run_id),
        }

    async def actual():
        environment = await WorkflowEnvironment.start_local(dev_server_existing_path=str(BINARY))
        try:
            port = TemporalPort(environment.client, task_queue="memory-eval-" + str(uuid4()))

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
                    for question in questions:
                        if (folder / "STOP").exists():
                            stopped.append((folder / "STOP").read_text().strip())
                            break
                        if TOKEN_CAP and spent(folder) >= TOKEN_CAP:
                            stopped.append(f"token cap {TOKEN_CAP} reached")
                            break
                        record = await one(environment, http, question)
                        records.append(record)
                        if RUN_ALERT and (record["used_tokens"] or 0) > RUN_ALERT:
                            (folder / "STOP").write_text(
                                f"{group}/{timeline['id']}/{question['id']}/rep{repeat} used "
                                f"{record['used_tokens']} tokens (alert {RUN_ALERT})\n")
                        name = (f"{group}-{timeline['id']}-{question['id']}.r{repeat}"
                                ".real.json")
                        (folder / name).write_text(
                            json.dumps(record, ensure_ascii=False, indent=2) + "\n")
                        print("REAL", group, timeline["id"], question["id"], f"rep{repeat}",
                              record["status"],
                              record["seconds"], record["used_tokens"], record["usage"],
                              record["answer"][:200].replace("\n", " "))
        finally:
            await environment.shutdown()

    stopped = []
    asyncio.run(actual())
    assert all(item["held_tokens"] == 0 for item in records)
    if stopped:
        pytest.skip("Stopped before every question ran: " + stopped[0])
    assert len(records) == len(questions)
