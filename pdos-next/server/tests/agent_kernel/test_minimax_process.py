"""Default production Worker and actual DB/Temporal; only KMS and HTTP I/O are synthetic."""

import json
import os
import subprocess
import sys
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentRun,
    AgentToolCall,
    TenantAdministrator,
    TenantSkillEnablement,
    ValidationBudget,
)
from pdos_next.agent_kernel.session_checkpoints import LAYOUT_KEY, main_checkpoint_config
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.model_configuration.kms import AliyunKms
from pdos_next.models import Receipt, now
from pdos_next.providers.agent_client import AgentProviderClient, tool_name
from pdos_next.providers.agent_wire import FINISH_TOOL
from tests.agent_kernel.test_cost_budget import wallet
from tests.agent_kernel.test_domain_adapter_transactions import fixture
from tests.agent_kernel.test_worker_process_recovery import (
    saved_checkpoint,
    temporal_state,
    wait_for,
)
from tests.model_configuration.test_host_runtime import KmsSdk, document, write_config

pytestmark = pytest.mark.skipif(
    os.environ.get("PDOS_WORKER_PROCESS_CHECK") != "verified-local-synthetic",
    reason="Explicit verified local Temporal/PG process profile required",
)

PRIVATE_Q = "SYNTHETIC_PRIVATE_MINIMAX_QUESTION"
PRIVATE_ACTION = "SYNTHETIC_PRIVATE_MINIMAX_ACTION"
PRIVATE_FINAL = "SYNTHETIC_PRIVATE_MINIMAX_FINAL"
PROVIDER = "synthetic-minimax-cn-m3"


class ResponseBytes(httpx.SyncByteStream):
    def __init__(self, value):
        self.value = value

    def __iter__(self):
        for start in range(0, len(self.value), 31):
            yield self.value[start : start + 31]


class MiniMaxWire:
    def __call__(self, request):
        assert str(request.url) == "https://api.minimax.cn/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-only-key"
        body = json.loads(request.content)
        assert body["model"] == "MiniMax-M3" and body["reasoning_split"] is True
        assert "response_format" not in body and body["stream"] is True
        assert body["tools"][-1]["function"]["name"] == FINISH_TOOL
        assert "result_json" in body["tools"][-1]["function"]["parameters"]["properties"]
        history = body["messages"]
        answered = []
        for index, message in enumerate(history):
            if message["role"] == "user":
                try:
                    if json.loads(message["content"]).get("answers"):
                        answered.append(index)
                except (ValueError, AttributeError):
                    pass
        previous = [message for message in history if message["role"] == "assistant"]
        created = [
            message
            for message in previous
            if any(
                call["function"]["name"] == tool_name("proposal.create")
                for call in message.get("tool_calls", [])
            )
        ]
        if answered:
            question = next(message for message in previous if PRIVATE_Q in str(message))
            position = history.index(question)
            assert question["content"] == "<think>" + PRIVATE_Q + "</think>"
            assert history[position + 1]["tool_call_id"] == "minimax-question"
            assert json.loads(history[position + 1]["content"]) == {"response_received": True}
            assert position + 1 < answered[-1]
        if not answered:
            phase, identity, name, content, reasoning = (
                "question",
                "minimax-question",
                FINISH_TOOL,
                "<think>" + PRIVATE_Q + "</think>",
                None,
            )
            arguments = {
                "status": "needs_input",
                "summary": "合成区域待确认",
                "result_json": "{}",
                "questions": [
                    {
                        "id": "region",
                        "question": "研究哪个区域？",
                        "why": "确定范围",
                        "options": [{"value": "US", "label": "合成美国市场"}],
                        "recommended": {"value": "US", "reason": "合成案例"},
                        "allow_free_text": True,
                        "depends_on": [],
                    }
                ],
                "unfinished": ["等待本人答复"],
            }
        elif not created:
            phase, identity, name, content, reasoning = (
                "proposal",
                "minimax-create",
                tool_name("proposal.create"),
                "",
                PRIVATE_ACTION,
            )
            arguments = {
                "title": "合成 MiniMax M3 提案候选",
                "entry_kind": "new_product",
                "brief": "仅验证原生协议、持久恢复与本人采用，不是真实研究结论。",
            }
        else:
            assert created[-1]["reasoning_content"] == PRIVATE_ACTION
            result = next(
                message
                for message in history
                if message["role"] == "tool" and message["tool_call_id"] == "minimax-create"
            )
            assert json.loads(result["content"])["state"] == "candidate"
            phase, identity, name, content, reasoning = (
                "final",
                "minimax-final",
                FINISH_TOOL,
                "",
                PRIVATE_FINAL,
            )
            arguments = {
                "status": "completed",
                "summary": "合成提案候选已保存，等待本人采用。",
                "result_json": "{}",
                "questions": [],
                "unfinished": [],
            }
        deltas = [{"content": content[:4]}, {"content": content[4:]}]
        if reasoning:
            deltas += [{"reasoning_content": reasoning[:7]}, {"reasoning_content": reasoning[7:]}]
        encoded = json.dumps(arguments, ensure_ascii=False)
        midpoint = len(encoded) // 2
        deltas += [
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": identity,
                        "type": "function",
                        "function": {"name": name, "arguments": encoded[:midpoint]},
                    }
                ]
            },
            {"tool_calls": [{"index": 0, "function": {"arguments": encoded[midpoint:]}}]},
        ]
        packets = [
            {"id": "synthetic-" + phase, "choices": [{"index": 0, "delta": delta}]}
            for delta in deltas
        ]
        packets += [
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 30,
                    "completion_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 5},
                    "completion_tokens_details": {"reasoning_tokens": 12},
                },
            },
        ]
        wire = (
            "".join(
                "data: " + json.dumps(packet, ensure_ascii=False) + "\r\n\r\n" for packet in packets
            )
            + "data: [DONE]\r\n\r\n"
        ).encode()
        print(json.dumps({"event": "synthetic_minimax_http", "phase": phase}), flush=True)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=ResponseBytes(wire)
        )


def test_default_minimax_wire_restarts_question_and_creates_one_actual_t1_proposal(
    setup, monkeypatch, tmp_path
):
    f = fixture(setup, skill_key="proposal_drafting")
    sdk = KmsSdk()
    monkeypatch.setattr(AliyunKms, "sdk", lambda _self: sdk)
    config = document(setup.tenant)
    config["models"][0].update(
        base_url="https://api.minimax.cn/v1",
        model="MiniMax-M3",
        model_version="MiniMax-M3",
        provider=PROVIDER,
    )
    path = write_config(tmp_path / "runtime.json", config)
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
        session.get(TenantSkillEnablement, f.qualification.id).qualified_model_version = None
    budget_id = wallet(setup)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        register_agreement(
            session,
            setup.ctx,
            AgreementInput(
                provider=PROVIDER,
                expected_revision=0,
                data_categories=["internal"],
                decision="批准",
                idempotency_key=str(uuid4()),
                retention_terms="synthetic fixture only, no real agreement",
                training_terms="synthetic only",
                signed_on=now() - timedelta(minutes=1),
                expires_at=now() + timedelta(hours=1),
            ),
        )
    environment = dict(
        os.environ,
        PDOS_WORKFLOW_TENANTS=str(setup.tenant),
        PDOS_CHECKPOINT_DATABASE_URL=os.environ["M2_TEST_CHECKPOINT_URL"].replace(
            "postgresql://", "postgresql+psycopg://", 1
        ),
        PDOS_OBJECT_ROOT=str(tmp_path / "objects"),
        PDOS_OBJECT_LIFECYCLE_PROFILE="local-synthetic-v1",
    )
    process, logs = None, []

    def start_worker():
        log = (tmp_path / f"minimax-worker-{len(logs)}.log").open("wb")
        logs.append(log)
        return subprocess.Popen(
            [sys.executable, "-m", "tests.agent_kernel.test_minimax_process"],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    def stop_worker():
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)

    try:
        with TestClient(create_app(setup.engine, setup.auth, workflow_enabled=True)) as api:
            command_path = f"/v1/categories/{setup.category}/commands"
            command = {
                "command_id": str(uuid4()),
                "idempotency_key": str(uuid4()),
                "category_id": str(setup.category),
                "product_id": None,
                "operation": "model.configuration.save",
                "expected_revision": 1,
                "source_read_set": [],
                "payload": {
                    "expected_revision": 0,
                    "enabled": True,
                    "metadata": {
                        "protocol": "openai-compatible",
                        "base_url": "https://api.minimax.cn/v1",
                        "model": "MiniMax-M3",
                        "model_version": "MiniMax-M3",
                    },
                },
            }
            preview = api.post(command_path + "/preview", headers=setup.headers, json=command)
            assert preview.status_code == 200, preview.text
            saved = api.post(command_path, headers=setup.headers, json=preview.json()["command"])
            assert saved.status_code == 200, saved.text
            agent_path = f"/v1/categories/{setup.category}/agent-runs"
            accepted = api.post(
                agent_path,
                headers=setup.headers,
                json={
                    "goal": "合成 MiniMax M3 工具续接与提案候选",
                    "idempotency_key": str(uuid4()),
                    "sources": [
                        {"artifact_id": f.arguments["artifact_id"], "expected_revision": 1}
                    ],
                },
            )
            assert accepted.status_code == 202, accepted.text
            identity = UUID(accepted.json()["run_id"])
            process = start_worker()
            wait_for(
                lambda: (
                    api.get(agent_path + f"/{identity}", headers=setup.headers).json()["status"]
                    == "waiting_input"
                ),
                process,
                seconds=60,
            )
            original_temporal, _ = temporal_state(identity, setup)
            original_checkpoint = saved_checkpoint(identity, setup)
            stop_worker()
            answer = api.post(
                agent_path + f"/{identity}/answers",
                headers=setup.headers,
                json={
                    "answers": {"region": "US"},
                    "idempotency_key": str(uuid4()),
                },
            )
            assert answer.status_code == 202, answer.text
            process = start_worker()
            wait_for(
                lambda: (
                    api.get(agent_path + f"/{identity}", headers=setup.headers).json()["status"]
                    == "completed"
                ),
                process,
                seconds=60,
            )
            temporal_run, _, history = temporal_state(identity, setup, result=True)
            assert temporal_run == original_temporal
            checkpoint = saved_checkpoint(identity, setup)
            assert (
                checkpoint[0] == original_checkpoint[0] and checkpoint[2] > original_checkpoint[2]
            )
            events = api.get(agent_path + f"/{identity}/events", headers=setup.headers)
            candidate = next(
                row["event"]
                for row in events.json()["items"]
                if row["event"]["type"] == "domain_candidate"
            )
            preview = api.post(
                command_path + "/preview", headers=setup.headers, json=candidate["command"]
            )
            assert preview.status_code == 200, preview.text
            adopted = api.post(command_path, headers=setup.headers, json=preview.json()["command"])
            assert adopted.status_code == 200, adopted.text
            replay = api.post(command_path, headers=setup.headers, json=preview.json()["command"])
            assert replay.json()["id"] == adopted.json()["id"]
            for suffix in ("", "/events", "/process", "/stream"):
                public = api.get(agent_path + f"/{identity}" + suffix, headers=setup.headers)
                assert public.status_code == 200
                assert all(
                    marker not in public.text
                    for marker in (PRIVATE_Q, PRIVATE_ACTION, PRIVATE_FINAL)
                )
            with Session(setup.admin) as session:
                row = session.get(AgentRun, identity)
                assert row.held_tokens == 0 and row.used_tokens == 150
                budget = session.get(ValidationBudget, budget_id)
                assert budget.calls == 3 and budget.spent_micro_usd == 639
                assert budget.held_micro_usd == 0
                calls = list(
                    session.scalars(
                        select(AgentToolCall).where(
                            AgentToolCall.run_id == identity, AgentToolCall.tool == "model"
                        )
                    )
                )
                assert len(calls) == 3 and all(call.cost_state == "actual" for call in calls)
                private = str([call.result["continuation"] for call in calls])
                assert all(
                    marker in private for marker in (PRIVATE_Q, PRIVATE_ACTION, PRIVATE_FINAL)
                )
                assert (
                    len(
                        list(
                            session.scalars(
                                select(Receipt).where(
                                    Receipt.agent_run_id == identity,
                                    Receipt.operation == "proposal.create",
                                )
                            )
                        )
                    )
                    == 1
                )
                assert not any(
                    marker in str(event.body)
                    for event in session.scalars(
                        select(AgentEvent).where(AgentEvent.run_id == identity)
                    )
                    for marker in (PRIVATE_Q, PRIVATE_ACTION, PRIVATE_FINAL)
                )
                address = main_checkpoint_config(scope_for_run(row), row.versions.get(LAYOUT_KEY))
            url = os.environ["M2_TEST_CHECKPOINT_URL"].replace(
                "postgresql+psycopg://", "postgresql://"
            )
            with PostgresSaver.from_conn_string(url) as saver:
                persisted = saver.get_tuple(address)
                assert all(
                    marker in str(persisted.checkpoint["channel_values"])
                    for marker in (PRIVATE_Q, PRIVATE_ACTION, PRIVATE_FINAL)
                )
            print(
                json.dumps(
                    {
                        "run_id": str(identity),
                        "same_temporal_run": True,
                        "same_checkpoint_thread": True,
                        "worker_processes": 2,
                        "native_http_attempts": 3,
                        "private_continuation_persisted": True,
                        "public_reasoning_exposed": False,
                        "actual_t1_proposals": 1,
                        "held_tokens": 0,
                        "synthetic_cost_micro_usd": 639,
                        "history": history,
                        "real_model_calls": 0,
                        "real_kms_calls": 0,
                        "worker_log_directory": str(tmp_path),
                    }
                )
            )
    finally:
        stop_worker()
        for log in logs:
            log.close()


if __name__ == "__main__":
    import asyncio

    from pdos_next.agent_kernel import gateway
    from pdos_next.workflows.worker import main

    assert os.environ.get("PDOS_WORKER_PROCESS_CHECK") == "verified-local-synthetic"
    assert os.environ["PDOS_TEMPORAL_ADDRESS"].startswith("127.0.0.1:")
    sdk = KmsSdk()
    AliyunKms.sdk = lambda _self: sdk
    gateway.AgentProviderClient = lambda: AgentProviderClient(httpx.MockTransport(MiniMaxWire()))
    asyncio.run(main())
