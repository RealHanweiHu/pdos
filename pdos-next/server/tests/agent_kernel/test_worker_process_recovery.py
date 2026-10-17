"""Actual API lifespan, production Worker subprocess, Temporal and PG checkpoints."""

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import AgentRun, TenantSkillEnablement
from pdos_next.agent_kernel.session_checkpoints import LAYOUT_KEY, main_checkpoint_config
from pdos_next.agent_kernel.temporal_port import workflow_id
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.models import Claim, Receipt, now
from tests.agent_kernel.test_domain_adapter_transactions import fixture
from tests.agent_kernel.test_model_configuration_transactions import configured, submit

pytestmark = pytest.mark.skipif(
    os.environ.get("PDOS_WORKER_PROCESS_CHECK") != "verified-local-synthetic",
    reason="Explicit verified local Temporal/PG process profile required",
)


def wait_for(predicate, process=None, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process is not None:
            assert process.poll() is None, "Worker exited; inspect its private synthetic log"
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("Actual Worker/Temporal state did not reach the expected checkpoint")


class WorkerProcess:
    def __init__(self, setup, directory, ports, arguments):
        self.environment = dict(os.environ)
        self.environment.update(
            PDOS_WORKFLOW_TENANTS=str(setup.tenant),
            PDOS_WORKFLOWS_ENABLED="1",
            PDOS_CHECKPOINT_DATABASE_URL=os.environ["M2_TEST_CHECKPOINT_URL"].replace(
                "postgresql://", "postgresql+psycopg://", 1
            ),
            PDOS_OBJECT_ROOT=str(directory / "objects"),
            PDOS_OBJECT_LIFECYCLE_PROFILE="local-synthetic-v1",
        )
        path = directory / "offline-worker.json"
        path.write_text(json.dumps({
            "tenant_id": str(setup.tenant), "arguments": arguments,
            "secret_reference": str(ports.secrets.binding.reference),
            "secret_version": str(ports.secrets.binding.version),
        }))
        path.chmod(0o600)
        self.environment["PDOS_WORKER_FIXTURE"] = str(path)
        self.directory, self.process, self.logs = directory, None, []

    def start(self):
        log = (self.directory / f"worker-{len(self.logs)}.log").open("wb")
        self.logs.append(log)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "tests.agent_kernel.worker_process_fixture"],
            env=self.environment, stdout=log, stderr=subprocess.STDOUT,
        )
        return self.process

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=15)
        for log in self.logs:
            log.flush()

    def close(self):
        self.stop()
        for log in self.logs:
            log.close()


def prepare(setup, monkeypatch):
    assert os.environ.get("PDOS_WORKER_PROCESS_CHECK") == "verified-local-synthetic"
    assert os.environ["PDOS_TEMPORAL_ADDRESS"].startswith("127.0.0.1:")
    assert os.environ["PDOS_TEMPORAL_NAMESPACE"].startswith("pdos-next-m3-worker-")
    f = fixture(setup)
    management, ports, command = configured(setup)
    saved, _ = submit(setup, management, command)
    assert saved.status_code == 200, saved.text
    with Session(setup.admin) as session, session.begin():
        value = session.get(TenantSkillEnablement, f.qualification.id)
        value.qualified_model_version = None  # T1 only; never grant a real qualification.
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        register_agreement(session, setup.ctx, AgreementInput(
            provider="synthetic-offline-provider", expected_revision=0,
            data_categories=["internal"], decision="批准", idempotency_key=str(uuid4()),
            retention_terms="fixture-only:no-contract-or-egress", training_terms="synthetic only",
            signed_on=now() - timedelta(minutes=1), expires_at=now() + timedelta(hours=1),
        ))
    original = Bootstrap.binding_for

    def binding(self, *args):
        value = original(self, *args)
        value.token_limit = 500000  # Offline conservative byte accounting, no provider spend.
        return value

    monkeypatch.setattr(Bootstrap, "binding_for", binding)
    app = create_app(setup.engine, setup.auth, agent_runtime_ports=ports, workflow_enabled=True)
    payload = {
        "goal": "Synthetic actual process recovery", "idempotency_key": str(uuid4()),
        "product_id": str(setup.product),
        "sources": [{"artifact_id": f.arguments["artifact_id"], "expected_revision": 1}],
    }
    return ports, f.arguments, app, payload


def temporal_state(identity, setup, *, result=False):
    async def read():
        client = await Client.connect(
            os.environ["PDOS_TEMPORAL_ADDRESS"],
            namespace=os.environ["PDOS_TEMPORAL_NAMESPACE"],
        )
        handle = client.get_workflow_handle(workflow_id(setup.tenant, identity))
        description = await handle.describe()
        if not result:
            return description.run_id, description.status.name
        output = await asyncio.wait_for(handle.result(), 30)
        history = await handle.fetch_history()
        starts, signals, activities = [], [], []
        for event in history.events:
            for field, target in (
                ("workflow_execution_started_event_attributes", starts),
                ("workflow_execution_signaled_event_attributes", signals),
                ("activity_task_scheduled_event_attributes", activities),
            ):
                if event.HasField(field):
                    target.extend(json.loads(p.data) for p in getattr(event, field).input.payloads)
        fields = {"tenant_id", "category_id", "actor_id", "requester_id", "subject_id"}
        assert len(starts) == 1 and set(starts[0]) == fields
        assert all(set(value) <= fields | {"answer_ref"} for value in activities)
        assert all(str(UUID(value)) == value for value in signals)
        return description.run_id, output, {
            "history_reference_fields": sorted(fields),
            "answer_signals": len(signals), "activities": len(activities),
        }

    return asyncio.run(read())


def saved_checkpoint(identity, setup):
    with Session(setup.admin) as session:
        row = session.get(AgentRun, identity)
        config = main_checkpoint_config(scope_for_run(row), row.versions.get(LAYOUT_KEY))
    url = os.environ["M2_TEST_CHECKPOINT_URL"].replace("postgresql+psycopg://", "postgresql://")
    with PostgresSaver.from_conn_string(url) as saver:
        checkpoint = saver.get_tuple(config)
        assert checkpoint is not None
        return (
            config["configurable"]["thread_id"],
            checkpoint.checkpoint["id"], checkpoint.metadata["step"],
        )


def test_production_worker_restarts_waiting_run_and_committed_answer_becomes_real_t1_claim(
    setup, monkeypatch, tmp_path
):
    ports, arguments, app, payload = prepare(setup, monkeypatch)
    worker = WorkerProcess(setup, tmp_path, ports, arguments)
    path = f"/v1/categories/{setup.category}/agent-runs"
    try:
        with TestClient(app) as api:
            started = api.post(path, headers=setup.headers, json=payload)
            assert started.status_code == 202, started.text
            identity = UUID(started.json()["run_id"])
            process = worker.start()

            def waiting():
                response = api.get(path + "/" + str(identity), headers=setup.headers)
                assert response.status_code == 200, response.text
                return response.json()["status"] == "waiting_input"

            wait_for(waiting, process)
            initial_temporal_run, _ = temporal_state(identity, setup)
            before_checkpoint = saved_checkpoint(identity, setup)
            worker.stop()
            answer = api.post(path + f"/{identity}/answers", headers=setup.headers, json={
                "answers": {"region": "US"}, "idempotency_key": str(uuid4()),
            })
            assert answer.status_code == 202, answer.text
            restarted = worker.start()
            wait_for(lambda: api.get(path + "/" + str(identity), headers=setup.headers)
                     .json()["status"] == "completed", restarted)
            temporal_run, result, history = temporal_state(identity, setup, result=True)
            assert temporal_run == initial_temporal_run
            after_checkpoint = saved_checkpoint(identity, setup)
            assert after_checkpoint[0] == before_checkpoint[0]
            assert after_checkpoint[1] != before_checkpoint[1]
            assert after_checkpoint[2] > before_checkpoint[2]
            assert result["status"] == "completed"
            replay = api.post(path, headers=setup.headers, json=payload)
            assert replay.json()["run_id"] == str(identity)
            events = api.get(path + f"/{identity}/events", headers=setup.headers).json()
            candidate = next(row["event"] for row in events["items"]
                             if row["event"]["type"] == "claim_candidate")
            command_path = f"/v1/categories/{setup.category}/commands"
            preview = api.post(command_path + "/preview", headers=setup.headers,
                               json=candidate["command"])
            assert preview.status_code == 200, preview.text
            confirmed = api.post(
                command_path, headers=setup.headers, json=preview.json()["command"]
            )
            assert confirmed.status_code == 200, confirmed.text
            same = api.post(command_path, headers=setup.headers, json=preview.json()["command"])
            assert same.json()["id"] == confirmed.json()["id"]
            with Session(setup.admin) as session:
                receipts = list(session.scalars(select(Receipt).where(
                    Receipt.agent_run_id == identity, Receipt.operation == "evidence.claim.record"
                )))
                assert len(receipts) == 1
                claim = session.get(Claim, receipts[0].subject_id)
                assert claim.writer_id == setup.agent and claim.human_owner_id == setup.human
                assert session.get(AgentRun, identity).held_tokens == 0
            print(json.dumps({"run_id": str(identity), "temporal_run_id": temporal_run,
                              "same_temporal_run": True, **history,
                              "same_checkpoint_thread": True,
                              "worker_processes": 2, "actual_claims": 1, "real_model_calls": 0}))
    finally:
        worker.close()


def test_cancel_while_production_worker_is_offline_remains_cancelled_after_restart(
    setup, monkeypatch, tmp_path
):
    ports, arguments, app, payload = prepare(setup, monkeypatch)
    worker = WorkerProcess(setup, tmp_path, ports, arguments)
    path = f"/v1/categories/{setup.category}/agent-runs"
    try:
        with TestClient(app) as api:
            started = api.post(path, headers=setup.headers, json=payload)
            assert started.status_code == 202, started.text
            identity = UUID(started.json()["run_id"])
            process = worker.start()
            wait_for(lambda: api.get(path + f"/{identity}", headers=setup.headers)
                     .json()["status"] == "waiting_input", process)
            temporal_run, _ = temporal_state(identity, setup)
            worker.stop()
            cancelled = api.post(path + f"/{identity}/cancel", headers=setup.headers)
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["status"] == "cancelled"
            assert cancelled.json()["held_tokens"] == 0
            restarted = worker.start()
            wait_for(lambda: temporal_state(identity, setup)[1] == "CANCELED", restarted)
            assert temporal_state(identity, setup)[0] == temporal_run
            current = api.get(path + f"/{identity}", headers=setup.headers)
            assert current.json()["status"] == "cancelled"
            with Session(setup.admin) as session:
                row = session.get(AgentRun, identity)
                assert row.cancel_epoch == 1 and row.held_tokens == 0
                assert session.scalar(select(Receipt).where(
                    Receipt.agent_run_id == identity, Receipt.operation == "evidence.claim.record"
                )) is None
            print(json.dumps({"run_id": str(identity), "same_temporal_run": True,
                              "worker_processes": 2, "cancelled": True, "actual_claims": 0,
                              "held_tokens": 0, "real_model_calls": 0}))
    finally:
        worker.close()


def test_continuation_uses_one_pg_thread_and_recovers_its_own_wait_after_worker_restart(
    setup, monkeypatch, tmp_path
):
    ports, arguments, app, payload = prepare(setup, monkeypatch)
    worker = WorkerProcess(setup, tmp_path, ports, arguments)
    path = f"/v1/categories/{setup.category}/agent-runs"
    try:
        with TestClient(app) as api:
            root_reply = api.post(path, headers=setup.headers, json=payload)
            assert root_reply.status_code == 202, root_reply.text
            root = UUID(root_reply.json()["run_id"])
            process = worker.start()
            wait_for(lambda: api.get(path + f"/{root}", headers=setup.headers)
                     .json()["status"] == "waiting_input", process)
            answer = api.post(path + f"/{root}/answers", headers=setup.headers, json={
                "answers": {"region": "US"}, "idempotency_key": str(uuid4()),
            })
            assert answer.status_code == 202, answer.text
            wait_for(lambda: api.get(path + f"/{root}", headers=setup.headers)
                     .json()["status"] == "completed", process)
            _, _, root_history = temporal_state(root, setup, result=True)
            events = api.get(path + f"/{root}/events", headers=setup.headers).json()
            candidate = next(row["event"] for row in events["items"]
                             if row["event"]["type"] == "claim_candidate")
            command_path = f"/v1/categories/{setup.category}/commands"
            preview = api.post(command_path + "/preview", headers=setup.headers,
                               json=candidate["command"])
            assert preview.status_code == 200, preview.text
            confirmed = api.post(command_path, headers=setup.headers,
                                 json=preview.json()["command"])
            assert confirmed.status_code == 200, confirmed.text
            root_checkpoint = saved_checkpoint(root, setup)
            worker.stop()

            continuation = {
                "goal": "Synthetic continued work", "idempotency_key": str(uuid4()),
                "continue_from_run_id": str(root),
            }
            child_reply = api.post(path, headers=setup.headers, json=continuation)
            assert child_reply.status_code == 202, child_reply.text
            child = UUID(child_reply.json()["run_id"])
            assert child_reply.json()["session_id"] == root_reply.json()["session_id"]
            process = worker.start()
            wait_for(lambda: api.get(path + f"/{child}", headers=setup.headers)
                     .json()["status"] == "waiting_input", process)
            child_temporal, _ = temporal_state(child, setup)
            child_checkpoint = saved_checkpoint(child, setup)
            assert child_checkpoint[0] == root_checkpoint[0]
            assert child_checkpoint[1] != root_checkpoint[1]
            assert saved_checkpoint(root, setup) == root_checkpoint
            worker.stop()

            answer = api.post(path + f"/{child}/answers", headers=setup.headers, json={
                "answers": {"followup_scope": "Keep the original unknowns"},
                "idempotency_key": str(uuid4()),
            })
            assert answer.status_code == 202, answer.text
            process = worker.start()
            wait_for(lambda: api.get(path + f"/{child}", headers=setup.headers)
                     .json()["status"] == "completed", process)
            temporal_run, result, history = temporal_state(child, setup, result=True)
            assert temporal_run == child_temporal and result["status"] == "completed"
            assert saved_checkpoint(root, setup) == root_checkpoint
            assert saved_checkpoint(child, setup)[2] > child_checkpoint[2]
            replay = api.post(path, headers=setup.headers, json=continuation)
            assert replay.status_code == 202 and replay.json()["run_id"] == str(child)
            with Session(setup.admin) as session:
                for identity in (root, child):
                    row = session.get(AgentRun, identity)
                    assert row.held_tokens == 0 and row.state == "completed"
                    assert row.versions["context_snapshots"]
                    for snapshot in row.versions["context_snapshots"].values():
                        assert snapshot["read_set"] == row.read_sources
                        assert snapshot["scope"]["requester_id"] == str(row.requester_id)
                receipts = list(session.scalars(select(Receipt).where(
                    Receipt.agent_run_id.in_([root, child]),
                    Receipt.operation == "evidence.claim.record",
                )))
                assert len(receipts) == 1 and receipts[0].agent_run_id == root
                assert session.get(Claim, receipts[0].subject_id) is not None
            url = os.environ["M2_TEST_CHECKPOINT_URL"].replace(
                "postgresql+psycopg://", "postgresql://"
            )
            with PostgresSaver.from_conn_string(url) as saver:
                rows = list(saver.list({"configurable": {"thread_id": root_checkpoint[0]}}))
            assert {row.config["configurable"]["checkpoint_ns"] for row in rows} == {
                f"run:{root}", f"run:{child}",
            }
            assert {row.metadata["pdos_run_id"] for row in rows} == {str(root), str(child)}
            print(json.dumps({
                "root_run_id": str(root), "continued_run_id": str(child),
                "temporal_run_id": temporal_run, "same_temporal_run_after_restart": True,
                "one_conversation_thread": True, "independent_run_namespaces": 2,
                "root_checkpoint_unchanged": True, "worker_processes": 3,
                "history": history, "root_history": root_history,
                "actual_claims": 1, "child_claims": 0, "held_tokens": 0,
                "real_model_calls": 0,
            }))
    finally:
        worker.close()
