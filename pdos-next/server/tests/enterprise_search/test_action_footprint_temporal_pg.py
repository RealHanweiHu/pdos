"""Actual registered graph: uncited context cannot enter a wider action candidate.

Root runs the native PG/Temporal fixtures. Offline provider output deliberately
attempts laundering; every source/read/model response is produced by real native
commands and registered graph calls. No ledger or business row is fabricated.
"""
# ruff: noqa: F401,F811 -- imported native fixture dependency tree

import asyncio
import json
import os
from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from build_operational_facts.fixtures import configuration, definition, operational_work, project
from build_start.test_transactions import ready_work
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.domain.builds.models import Build
from pdos_next.domain.verification_execution.models import VerificationPreparation
from pdos_next.providers.types import ProviderUsage
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.enterprise_search.test_assistant_pg import SyntheticClient
from tests.enterprise_search.test_retrieval_pg import index
from tests.enterprise_search.test_verification_action_temporal_pg import prepared, totals
from tests.enterprise_search.verification_action_harness import (
    PREPARATION,
    VerificationClient,
    actual_runtime,
    bound_target,
    candidate,
    json_messages,
    start,
)
from tests.enterprise_search.verification_negative_fixture import private_action_work
from tests.test_project_first_plan import post
from tests.test_trusted_source_work import command
from verification_handoff.fixtures import handoff_work, known_configuration

pytestmark = pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit guarded PG, local Temporal and verified checkpoint runtime required",
)


class ParentClient(SyntheticClient):
    def __init__(self, selected):
        super().__init__()
        self.selected = str(selected)
        self.source_cids, self.private_title = {}, None

    def turn(self, route, **kwargs):
        names = {tool["name"] for tool in kwargs["tools"]}
        child = names == {"assistant.passage.read", "result.read"}
        values = [
            value for row, value in json_messages(kwargs["messages"]) if row["role"] == "tool"
        ]
        if not child and values and "items" in values[-1] and values[-1]["items"]:
            self.calls += 1
            items = values[-1]["items"]
            self.source_cids = {item["source_id"]: item["citation_id"] for item in items}
            self.private_title = next((item["title"] for item in items if item["private"]), None)
            return ModelTurn(
                calls=(
                    ToolCall(
                        id=str(uuid4()),
                        name="assistant.extract",
                        arguments={"citation_ids": list(self.source_cids.values())},
                    ),
                ),
                usage=ProviderUsage(10, 2),
            )
        turn = super().turn(route, **kwargs)
        if not child and turn.structured:
            body = deepcopy(turn.structured)
            body["result"]["assistant"]["citation_ids"] = [self.source_cids[self.selected]]
            if self.private_title:
                body["summary"] += "；原讨论还出现：" + self.private_title
            return replace(turn, structured=body)
        return turn


class LatePrivateClient(VerificationClient):
    def __init__(self, source, purpose):
        super().__init__(source, purpose)
        self.inject_source = None
        self.inject_state = 0
        self.injected_quote = None

    def turn(self, route, **kwargs):
        names = {tool["name"] for tool in kwargs["tools"]}
        child = names == {"assistant.passage.read", "result.read"}
        if self.phase == "action" and not child and self.step == 2:
            values = [
                value for row, value in json_messages(kwargs["messages"]) if row["role"] == "tool"
            ]
            if self.inject_state == 0:
                self.calls += 1
                self.inject_state = 1
                return self._read("assistant.search", {"query": self.inject_source})
            if self.inject_state == 1:
                self.calls += 1
                self.inject_state = 2
                item = next(
                    item for item in values[-1]["items"] if item["source_id"] == self.inject_source
                )
                return self._read("assistant.extract", {"citation_ids": [item["citation_id"]]})
            if self.inject_state == 2:
                self.inject_state = 3
                self.injected_quote = values[-1]["rows"][0]["quote"]
                assert "SYNTHETIC_PRIVATE_ACTION_BODY" in self.injected_quote
                turn = super().turn(route, **kwargs)
                assert turn.calls[0].name == PREPARATION
                args = deepcopy(turn.calls[0].arguments)
                args["reason"] = "原生模型故意尝试携带未选私有材料：" + self.injected_quote
                self.arguments = args
                call = turn.calls[0].model_copy(update={"arguments": args})
                return replace(turn, calls=(call,))
        return super().turn(route, **kwargs)

    @staticmethod
    def _read(name, arguments):
        return ModelTurn(
            calls=(ToolCall(id=str(uuid4()), name=name, arguments=arguments),),
            usage=ProviderUsage(10, 2),
        )


def register(person, title, body, *, private=False):
    response = post(
        person,
        command(
            person,
            "evidence.artifact.register",
            {
                "title": title,
                "content": body,
                "source_label": "I14 native synthetic action evidence",
                "visibility": "private" if private else "category",
            },
        ),
    )
    assert response.status_code == 200, response.text
    identity = response.json()["subject_id"]
    index(person, UUID(identity))
    return {
        "artifact_id": identity,
        "expected_revision": 1,
        "line": 1,
        "quote": body.splitlines()[0],
    }


def materials(work):
    person, selection = bound_target(work)
    public = register(person, "I14 public discussion", "漏气：更换密封圈。RAW_ONLY_CHILD_MARKER")
    execution = register(person, "I14 current execution", "Synthetic drawing\nEXECUTION_RAW_ONLY")
    return person, selection, public, execution


async def parent_answer(runtime, selection):
    identity, _handle = await start(
        runtime,
        {
            "goal": "以前漏气怎么处理？",
            "idempotency_key": str(uuid4()),
            "product_id": str(runtime.person.product),
            "project_id": selection["project_id"],
        },
        accepted_statuses=("completed", "partial"),
    )
    response = await runtime.http.get(runtime.path + f"/{identity}", headers=runtime.person.headers)
    assert response.status_code == 200, response.text
    assistant = response.json()["result"]["result"]["assistant"]
    assert assistant["lookup"] == "cited" and len(assistant["citation_ids"]) == 1
    return identity, assistant


def action_payload(parent, answer, selection, execution):
    return {
        "goal": "依据明确所选讨论准备3件复验，未知方法和合格判据保留待确认。",
        "idempotency_key": str(uuid4()),
        "continue_from_run_id": str(parent),
        "sources": [{"artifact_id": execution["artifact_id"], "expected_revision": 1}],
        "verification_action": {"selection": selection, "citation_ids": answer["citation_ids"]},
    }


def actual_run(person, identity):
    with tenant_session(
        person.engine,
        person.tenant,
        actor_id=person.human,
        requester_id=person.human,
        category_id=person.category,
        read_snapshot=True,
    ) as session:
        run = session.get(AgentRun, identity)
        return deepcopy(run.read_sources), deepcopy(run.versions.get("verification_action"))


def test_parent_uncited_private_context_is_denied_before_shared_action_run_is_created(
    handoff_work,
    monkeypatch,
):
    person, selection, public, execution = materials(handoff_work)
    private = register(
        person, "SYNTHETIC_PRIVATE_DISCUSSION_TITLE", "漏气：更换密封圈。", private=True
    )
    provider = VerificationClient(execution, handoff_work.scope.purpose)
    provider.parent = ParentClient(public["artifact_id"])

    async def actual():
        async with actual_runtime(person, provider, monkeypatch) as runtime:
            parent, answer = await parent_answer(runtime, selection)
            assert provider.parent.source_cids[private["artifact_id"]] not in answer["citation_ids"]
            with Session(person.admin) as session:
                target = session.get(Build, UUID(selection["id"]))
                assert target.visibility == "category"
                original = session.get(AgentRun, parent)
                assert not original.private_context
                assert "SYNTHETIC_PRIVATE_DISCUSSION_TITLE" in original.result["summary"]
                before_runs = set(
                    session.scalars(
                        select(AgentRun.id).where(
                            AgentRun.tenant_id == person.tenant,
                        )
                    )
                )
            before, calls = totals(person), provider.calls
            provider.phase = "action"
            denied = await runtime.http.post(
                runtime.path,
                headers=person.headers,
                json=action_payload(parent, answer, selection, execution),
            )
            assert denied.status_code == 403, denied.text
            assert denied.json()["detail"]["reason_key"] == "assistant_action_audience_widened"
            assert totals(person) == before and provider.calls == calls
            with Session(person.admin) as session:
                assert (
                    set(
                        session.scalars(
                            select(AgentRun.id).where(
                                AgentRun.tenant_id == person.tenant,
                            )
                        )
                    )
                    == before_runs
                )

    asyncio.run(actual())


def test_child_new_private_context_cannot_become_a_shared_candidate_through_special_guard(
    handoff_work,
    monkeypatch,
):
    person, selection, public, execution = materials(handoff_work)
    provider = LatePrivateClient(execution, handoff_work.scope.purpose)
    provider.parent = ParentClient(public["artifact_id"])

    async def actual():
        async with actual_runtime(person, provider, monkeypatch) as runtime:
            parent, answer = await parent_answer(runtime, selection)
            private = register(
                person,
                "I14 child private context",
                "漏气：更换密封圈。SYNTHETIC_PRIVATE_ACTION_BODY",
                private=True,
            )
            provider.inject_source = private["artifact_id"]
            provider.phase = "action"
            before = totals(person)
            payload = action_payload(parent, answer, selection, execution)
            # This real Human explicitly adds B to this turn's discussion reads.
            # Ordinary context_selection correctly filters B when only execution
            # was chosen; a synthetic provider cannot request an out-of-choice read.
            payload["sources"].append(
                {"artifact_id": private["artifact_id"], "expected_revision": 1}
            )
            identity, _handle = await start(
                runtime,
                payload,
                accepted_statuses=("completed", "partial"),
            )
            assert provider.injected_quote is not None
            response = await runtime.http.get(
                runtime.path + f"/{identity}/candidates", headers=person.headers
            )
            assert response.status_code == 200 and response.json()["items"] == [], response.text
            assert totals(person) == before
            reasons = [
                value.get("error", {}).get("detail", {}).get("reason_key")
                for _names, messages in provider.messages
                for row, value in json_messages(messages)
                if row["role"] == "tool"
            ]
            assert "assistant_action_audience_widened" in reasons
            reads, action = actual_run(person, identity)
            assert {execution["artifact_id"], private["artifact_id"]} <= {
                ref["artifact_id"] for ref in reads
            }
            assert action["citation_ids"] == answer["citation_ids"]
            assert provider.arguments["sources"] == [execution]
            assert provider.arguments["items"][0]["drawing"] == execution
            with Session(person.admin) as session:
                original_choice = session.get(AgentRun, identity).versions[
                    "requested_context_selection"
                ]
                assert {ref["source_id"] for ref in original_choice["sources"]} == {
                    execution["artifact_id"],
                    private["artifact_id"],
                }
                events = session.scalars(
                    select(AgentEvent).where(
                        AgentEvent.run_id == identity,
                        AgentEvent.body["type"].astext == "verification_candidate",
                    )
                ).all()
                assert events == []
                model = session.scalars(
                    select(AgentToolCall).where(
                        AgentToolCall.run_id == identity,
                        AgentToolCall.tool == "model",
                    )
                ).all()
                assert any(
                    "SYNTHETIC_PRIVATE_ACTION_BODY" in json.dumps(row.result) for row in model
                )

    asyncio.run(actual())


def test_private_native_target_preserves_explicit_citations_without_binding_uncited_context(
    private_action_work,
    monkeypatch,
):
    person, selection, public, execution = materials(private_action_work)
    private = register(
        person, "SYNTHETIC_PRIVATE_DISCUSSION_TITLE", "漏气：更换密封圈。", private=True
    )
    provider = VerificationClient(execution, private_action_work.scope.purpose)
    provider.parent = ParentClient(public["artifact_id"])

    async def actual():
        async with actual_runtime(person, provider, monkeypatch) as runtime:
            parent, answer = await parent_answer(runtime, selection)
            provider.phase = "action"
            identity, _handle = await start(
                runtime, action_payload(parent, answer, selection, execution)
            )
            pending = await candidate(runtime, identity)
            assert pending["state"] == "pending"
            before = totals(person)
            adopted = await prepared(runtime, identity, pending)
            assert totals(person) == (before[0] + 1, before[1])
            reads, action = actual_run(person, identity)
            assert private["artifact_id"] not in {ref["artifact_id"] for ref in reads}
            assert action["citation_ids"] == answer["citation_ids"]
            with Session(person.admin) as session:
                event = session.get(AgentEvent, UUID(pending["event_id"]))
                proof = event.body["source_proof"]
                assert [ref["citation_id"] for ref in proof["discussion_sources"]] == answer[
                    "citation_ids"
                ]
                assert private["artifact_id"] not in json.dumps(proof["execution_references"])
                row = session.get(
                    VerificationPreparation, UUID(adopted["preparation"]["preparation_id"])
                )
                assert row.visibility == "private" and row.owner_id == person.human

    asyncio.run(actual())
