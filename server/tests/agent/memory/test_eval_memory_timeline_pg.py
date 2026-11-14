"""Model-free replay of the memory timeline candidates (P121; target architecture §8, B0).

Each timeline in ``docs/evaluations/xiaopai-memory-v0/timelines.json`` is replayed
against the isolated ``pdos_test`` database through the same entry points the
memory tests use: the HTTP Run start, ``KernelStore.finish``, the notes API, the
``memory.search`` tool and the Run's frozen envelope. No provider is called and
no answer quality is scored; the replay only records what the server returned.

Three groups:

* ``no_memory``: every Session has "不进记忆" on (baseline 0).
* ``history_only``: no memory tool at all. A harness-side search over the actor's
  own finished Runs (own words plus the stored answer summary) stands in for
  "search the raw history" (baseline 1). It is an evaluation emulation read with
  an explicit owner filter, not a product path.
* ``real``: the current implementation (baseline 2).
* ``real_proposals_open``: the current implementation with the prompt-version
  gate of ``memory_candidates`` opened inside this test process only. Released
  prompts keep it closed (D298); this group shows what the server's
  deterministic admission would do once a prompt version is released.

Some timelines also publish category parameters through the ordinary command
API (``parameter`` events) so a question has a domain truth that memory must not
override (T03, T05, T24); the ``domain`` probe reads them back through the
registered ``category.parameters.list`` tool in a fresh Run.

Observations go to ``PDOS_MEMORY_TIMELINE_OUTPUT_DIR`` when it is set, so
``tools/xiaopai_memory_timeline_baseline.py`` can score them; otherwise to the
test's temporary folder. The gates are scored by that tool, not asserted here.
"""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import AgentRun
from pdos_next.agent.kernel.persistence import KernelStore
from pdos_next.agent.kernel.work_state import PAGE_MATERIAL_BOUNDARY, user_goal
from pdos_next.agent.memory import assemble
from pdos_next.agent.memory.index import index_episode
from pdos_next.agent.memory.models import MemoryCandidate, MemoryEpisode, MemoryNote
from pdos_next.agent.memory.recall import frozen_catalog, keyword_score
from pdos_next.agent.memory.tool import memory_search
from tests.agent.memory.support import scope, start

ROOT = Path(__file__).resolve().parents[4]
CASE_FILE = ROOT / "docs/evaluations/xiaopai-memory-v0/timelines.json"
CASES = json.loads(CASE_FILE.read_text())
GROUPS = ("no_memory", "history_only", "real", "real_proposals_open")
OBSERVATION = "xiaopai-memory-timeline-observation/v0"
BASE = "/v1/personal/memory"
TERMINAL = ("completed", "partial", "failed", "cancelled")


class Replay:
    def __init__(self, setup, group):
        self.setup, self.group = setup, group
        self.people = {"owner": setup.human, "peer": setup.peer}
        self.actor_of = {value: key for key, value in self.people.items()}
        self.runs, self.notes, self.revisions = {}, {}, {}
        self.created_notes = 0
        self._reads = None

    # -- helpers ----------------------------------------------------------
    def headers(self, actor):
        return {"Authorization": f"Bearer {self.setup.tokens[self.people[actor]]}"}

    def off(self, item):
        return self.group == "no_memory" or bool(item.get("memory_off"))

    def begin(self, actor, goal, *, off):
        body = {"memory_off": True} if off else {}
        run_id, _ = start(self.setup, headers=self.headers(actor), goal=goal, **body)
        return run_id

    def run_scope(self, actor, run_id):
        return scope(self.setup, run_id, requester=self.people[actor])

    def run_key(self, identity):
        return next((key for key, value in self.runs.items() if str(value) == str(identity)),
                    "other")

    def note_key(self, identity):
        return next((key for key, value in self.notes.items() if str(value) == str(identity)),
                    "other")

    def owner_key(self, run_id):
        with Session(self.setup.admin) as session:
            requester = session.scalar(select(AgentRun.requester_id).where(AgentRun.id == run_id))
        return self.actor_of.get(requester, "other")

    # -- events -----------------------------------------------------------
    def run(self, event):
        actor, goal = event["actor"], event["goal"]
        if event.get("page_material"):
            goal = f"{goal}{PAGE_MATERIAL_BOUNDARY}{event['page_material']}"
        run_id = self.begin(actor, goal, off=self.off(event))
        self.runs[event["id"]] = run_id
        result = {
            "status": event.get("status", "completed"),
            "summary": event.get("summary", "合成结果。"),
            "questions": [],
            "unfinished": list(event.get("unfinished", [])),
            "result": {"context_proposals": {
                "constraints": [],
                "memory_candidates": list(event.get("memory_candidates", [])),
            }},
        }
        KernelStore(self.setup.engine).finish(self.run_scope(actor, run_id), result)
        if event.get("index", True):
            with Session(self.setup.admin) as session:
                row = session.scalar(select(MemoryEpisode).where(MemoryEpisode.run_id == run_id))
            if row is not None:
                index_episode(self.setup.engine, {
                    "tenant_id": str(self.setup.tenant), "owner_id": str(row.owner_id),
                    "episode_id": str(row.id)})

    def parameter(self, event):
        """A domain fact: a category parameter a person published (category.parameter.publish)."""
        from tests.categories.preproject.test_g0 import request, save

        fields = ("key", "name", "value_type", "unit", "direction", "standard_condition",
                  "method", "acceptance_criterion", "change_note")
        payload = {"parameter_id": None, "expected_current_version": 0,
                   **{name: event.get(name) for name in fields}}
        save(self.setup, request(self.setup, "category.parameter.publish", payload),
             actor=self.people[event["actor"]])

    def note(self, event):
        response = self.setup.client.post(
            f"{BASE}/notes", headers=self.headers(event["actor"]),
            json={"request_key": str(uuid4()),
                  "note": {"kind": event["kind"], "text": event["text"],
                           "scope": {"kind": "global"}}})
        assert response.status_code == 200, response.text
        self.notes[event["id"]] = response.json()["note"]["note_id"]
        self.revisions[event["id"]] = 1
        self.created_notes += 1

    def revise(self, event):
        key = event["note"]
        response = self.setup.client.post(
            f"{BASE}/notes/{self.notes[key]}/revisions", headers=self.headers(event["actor"]),
            json={"request_key": str(uuid4()), "expected_revision": self.revisions[key],
                  "note": {"kind": event["kind"], "text": event["text"],
                           "scope": {"kind": "global"}}})
        assert response.status_code == 200, response.text
        self.revisions[key] += 1

    def forget(self, event):
        key = event["note"]
        response = self.setup.client.post(
            f"{BASE}/notes/{self.notes[key]}/deletion", headers=self.headers(event["actor"]),
            json={"request_key": str(uuid4()), "expected_revision": self.revisions[key]})
        assert response.status_code == 200, response.text

    # -- probes -----------------------------------------------------------
    def history_search(self, probe):
        """Baseline 1 emulation: the actor's own finished Runs, own words plus answer summary."""
        from pdos_next.agent.enterprise_search.tokenizer import analyze, analyze_query

        parsed = analyze_query(probe["query"])
        person = self.people[probe["actor"]]
        with Session(self.setup.admin) as session:
            rows = session.scalars(select(AgentRun).where(
                AgentRun.tenant_id == self.setup.tenant, AgentRun.requester_id == person,
                AgentRun.trigger == "conversation", AgentRun.state.in_(TERMINAL),
            )).all()
        scored = []
        for row in rows:
            if (row.versions or {}).get("memory_mode", {}).get("off"):
                continue
            words = analyze(f"{user_goal(row.goal)} {(row.result or {}).get('summary', '')}")
            value = keyword_score(parsed, words["counts"], words["codes"])
            if value > 0:
                scored.append((value, row))
        scored.sort(key=lambda item: (-item[0], -item[1].created_at.timestamp(), str(item[1].id)))
        return {"emulated": True, "status": "completed",
                "returned": [{"run": self.run_key(row.id),
                              "owner": self.actor_of.get(row.requester_id, "other")}
                             for _value, row in scored[:5]]}

    def search(self, probe):
        kinds = probe.get("search_kinds", ["episode"])
        if self.group == "history_only":
            return self.history_search(probe) if kinds == ["episode"] else {"not_applicable": True}
        run_id = self.begin(probe["actor"], probe["goal"], off=self.off(probe))
        result = memory_search(KernelStore(self.setup.engine))(
            self.run_scope(probe["actor"], run_id), {"query": probe["query"], "kinds": kinds})
        retrieval = result.get("retrieval", {})
        from pdos_next.agent.memory.recall import ANSWER_LABEL

        answers = [item["answer"] for item in result.get("items", []) if item.get("answer")]
        return {
            "status": result.get("status"),
            "returned": [{"run": self.run_key(item["run_id"]),
                          "owner": self.owner_key(item["run_id"])}
                         for item in result.get("items", [])],
            "notes": [self.note_key(item["note_id"]) for item in result.get("notes", [])],
            "texts": [item.get("text", "") for item in result.get("notes", [])],
            "index_pending": retrieval.get("index_pending", 0),
            "semantic": (retrieval.get("semantic") or {}).get("status"),
            "channels": retrieval.get("channels", []),
            # T03-T05: whatever memory returns is labelled as not being a business fact.
            "fact_policy": bool(result.get("fact_policy")),
            "answers_labelled": bool(answers) and all(
                item.get("label") == ANSWER_LABEL for item in answers),
        }

    def resident(self, probe):
        if self.group == "history_only":
            return {"not_applicable": True}
        run_id = self.begin(probe["actor"], probe["goal"], off=self.off(probe))
        with KernelStore(self.setup.engine).transaction(
            self.run_scope(probe["actor"], run_id), lock=True,
        ) as (session, run):
            notes = assemble.frozen(session, run)
            recent = frozen_catalog(session, run)
        entries = [item for zone in ("constraints", "aliases", "background")
                   for item in (notes or {}).get(zone, [])]
        catalog = (recent or {}).get("recent_episodes", [])
        return {
            "notes": [self.note_key(item["note_id"]) for item in entries],
            "texts": [item["text"] for item in entries],
            "catalog": [self.run_key(item["run_id"]) for item in catalog],
            "catalog_fields": sorted({key for item in catalog for key in item}),
            "catalog_has_unfinished": any("unfinished" in item for item in catalog),
            "target_in_catalog": set(probe.get("expect_catalog", [])) <= {
                self.run_key(item["run_id"]) for item in catalog},
        }

    def domain(self, probe):
        """The domain truth a question rests on, read through the registered tool in a new Run."""
        if self._reads is None:
            from pdos_next.agent.kernel.bootstrap import Bootstrap, RuntimePorts

            self._reads = Bootstrap(self.setup.engine, ports=RuntimePorts()).adapters().read_tools
        run_id = self.begin(probe["actor"], probe["goal"], off=self.off(probe))
        items = self._reads["category.parameters.list"](
            self.run_scope(probe["actor"], run_id), {}).get("items", [])
        found = [item for item in items if item.get("key") == probe["parameter_key"]]
        return {"found": len(found),
                "criterion": found[0].get("acceptance_criterion") if found else None,
                "origin": found[0].get("origin") if found else None}

    def candidates(self, probe):
        if self.group == "history_only":
            return {"not_applicable": True}
        run_ids = [self.runs[key] for key in probe["of_runs"]]
        with Session(self.setup.admin) as session:
            admitted = session.scalar(select(func.count()).select_from(MemoryCandidate).where(
                MemoryCandidate.run_id.in_(run_ids)))
            rejected = [reason.get("reason") for run_id in run_ids for reason in (
                (session.get(AgentRun, run_id).versions.get("work_state_proposals") or {})
                .get("rejected", []))]
        return {"admitted": admitted, "rejected": rejected}

    # -- whole timeline ---------------------------------------------------
    def replay(self, timeline):
        for event in timeline["events"]:
            getattr(self, event["op"])(event)
        probes = []
        for probe in timeline["probes"]:
            probes.append({"id": probe["id"], "probe": probe["probe"],
                           **getattr(self, probe["probe"])(probe)})
        with Session(self.setup.admin) as session:
            written = set(session.scalars(select(MemoryEpisode.run_id).where(
                MemoryEpisode.run_id.in_(list(self.runs.values())))).all()) if self.runs else set()
            notes = session.scalar(select(func.count()).select_from(MemoryNote).where(
                MemoryNote.tenant_id == self.setup.tenant))
        return {
            "version": OBSERVATION, "group": self.group, "timeline": timeline["id"],
            "scripted": True, "real_model_calls": 0, "model_quality_score": None,
            "probes": probes,
            "episodes_written": sorted(key for key, value in self.runs.items()
                                       if value in written),
            "unexpected_notes": notes - self.created_notes,
        }


class _AnyVersion:
    """Stands in for "this prompt version is released"; test process only."""

    def __contains__(self, _version):
        return True


def test_case_file_is_a_candidate_set_with_known_shapes():
    assert CASES["version"] == "xiaopai-memory-timelines/v0"
    ids = [timeline["id"] for timeline in CASES["timelines"]]
    assert len(ids) == len(set(ids)) and ids
    for timeline in CASES["timelines"]:
        assert timeline["status"] in {"candidate", "confirmed"}
        assert timeline["split"] in {"dev", "holdout"}
        assert {event["op"] for event in timeline["events"]} <= {
            "run", "note", "revise", "forget", "parameter"}
        assert {probe["probe"] for probe in timeline["probes"]} <= {
            "search", "resident", "candidates", "domain"}


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("timeline", CASES["timelines"], ids=lambda item: item["id"])
def test_replay_records_what_the_server_returned(setup, tmp_path, monkeypatch, group, timeline):
    if group == "real_proposals_open":
        from pdos_next.agent.memory import candidates

        monkeypatch.setattr(candidates, "MEMORY_CANDIDATE_PROMPT_VERSIONS", _AnyVersion())
    observation = Replay(setup, group).replay(timeline)
    assert [item["id"] for item in observation["probes"]] == [
        probe["id"] for probe in timeline["probes"]]
    folder = Path(os.environ.get("PDOS_MEMORY_TIMELINE_OUTPUT_DIR") or tmp_path)
    (folder / f"{group}-{timeline['id']}.json").write_text(
        json.dumps(observation, ensure_ascii=False, indent=2) + "\n")
