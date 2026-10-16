"""Default API/Worker research, durable child, verified ledger and actual T1 snapshot."""

import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import (
    AgentRun,
    AgentToolCall,
    PublicWebSnapshot,
    TenantAdministrator,
    TenantSkillEnablement,
    ValidationBudget,
)
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.model_configuration.kms import AliyunKms
from pdos_next.models import Receipt, now
from pdos_next.service import digest
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from tests.agent_kernel.test_cost_budget import wallet
from tests.agent_kernel.test_domain_adapter_transactions import fixture
from tests.agent_kernel.test_model_configuration_transactions import submit
from tests.agent_kernel.test_worker_process_recovery import temporal_state, wait_for
from tests.model_configuration.test_host_runtime import KmsSdk, document, write_config

pytestmark = pytest.mark.skipif(
    os.environ.get("PDOS_WORKER_PROCESS_CHECK") != "verified-local-synthetic",
    reason="Explicit verified local Temporal/PG process profile required",
)

URL = "https://maker.example/specs"
RAW = "HOST_RAW_SENTINEL_stays_inside_read_only_child"


class OfflineResearchClient:
    def __init__(self):
        self.turns = {"main": 0, "research": 0}

    def turn(self, route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        from pdos_next.agent_kernel.types import ModelTurn, ToolCall
        from pdos_next.providers.types import ProviderUsage

        assert in_registered_agent_graph()
        assert route.api_key.get_secret_value() == "synthetic-only-key"
        messages = kwargs["messages"]
        context = json.loads(messages[0]["content"])["context"]
        kind = "research" if "research_task" in context else "main"
        number = 1 + sum(row["role"] == "tool" for row in messages)
        self.turns[kind] = number
        print(json.dumps({"mode": kind, "turn": number}), flush=True)
        results = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
        assert all("error" not in result for result in results), results

        def tool(name, arguments):
            return ModelTurn(
                usage=ProviderUsage(20, 10),
                calls=(ToolCall(id=f"{kind}-{number}", name=name, arguments=arguments),),
            )

        if kind == "research":
            if number == 1:
                return tool("research.search", {"query": "synthetic pump"})
            if number == 2:
                assert results[-1]["hits"][0]["url"] == URL
                return tool("research.read", {"url": URL})
            assert number == 3
            page = results[-1]
            assert RAW in page["markdown"]
            output = {
                "rows": [
                    {
                        "brand": "Synthetic",
                        "model": "P1",
                        "free_key": "pressure",
                        "value": "20",
                        "unit": "psi",
                        "condition": "25 C",
                        "quote": "Pressure: 20 psi at 25 C.",
                        "snapshot_id": page["snapshot_id"],
                        "locator": page["locator"],
                    }
                ]
            }
        else:
            assert RAW not in json.dumps(messages)
            if number == 1:
                return tool("skill.load", {"name": "public_research"})
            if number == 2:
                return tool(
                    "research.fanout",
                    {
                        "tasks": [{"key": "specs", "focus": "synthetic pump"}],
                    },
                )
            if number == 3:
                ledger = results[-1]
                assert ledger["status"] == "completed" and len(ledger["ledger"]) == 1
                assert len(ledger["snapshot_read_refs"]) == 1 and ledger["failures"] == []
                return tool(
                    "research.snapshot.register",
                    {
                        "snapshot_id": ledger["snapshots"][0]["id"],
                    },
                )
            assert number == 4 and results[-1]["requires_human"] is True
            output = {"snapshot_confirmation_pending": True, "research": {"source_count": 999}}
        return ModelTurn(
            usage=ProviderUsage(20, 10),
            structured={
                "status": "completed",
                "summary": "Synthetic verified research",
                "result": output,
            },
        )

    def close(self):
        pass


@pytest.mark.parametrize("confirmation", ["api", "browser_success", "browser_recovery", "restart"])
def test_default_research_worker_retains_child_checkpoint_and_actual_snapshot(
    setup, monkeypatch, tmp_path, confirmation
):
    fixtures = [fixture(setup, skill_key=key) for key in ("proposal_drafting", "public_research")]
    monkeypatch.setattr(AliyunKms, "sdk", lambda _self: KmsSdk())
    value = document(setup.tenant)
    value["research"] = {
        "search_endpoint": "http://127.0.0.1:18888/search",
        "search_provider": "synthetic-search",
        "artifact_root": str(tmp_path.parent / "shared-research"),
    }
    monkeypatch.setenv(
        "PDOS_TENANT_RUNTIME_CONFIG", str(write_config(tmp_path / "host.json", value))
    )
    checkpoint_input = os.environ["M2_TEST_CHECKPOINT_URL"].replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    checkpoint_url = verified_checkpoint_url(checkpoint_input)
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
        for f in fixtures:
            session.get(TenantSkillEnablement, f.qualification.id).qualified_model_version = None
    budget_id = wallet(setup)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        for provider in ("synthetic@1",):
            register_agreement(
                session,
                setup.ctx,
                AgreementInput(
                    provider=provider,
                    expected_revision=0,
                    data_categories=["internal"],
                    decision="批准",
                    idempotency_key=str(uuid4()),
                    retention_terms="synthetic-only:no-real-contract",
                    training_terms="fixture-only",
                    signed_on=now() - timedelta(minutes=1),
                    expires_at=now() + timedelta(hours=1),
                ),
            )
    process = None
    with (tmp_path / "research-worker.log").open("wb") as log:
        try:
            with TestClient(create_app(setup.engine, setup.auth, workflow_enabled=True)) as api:
                saved, _ = submit(
                    setup,
                    api,
                    {
                        "command_id": str(uuid4()),
                        "idempotency_key": str(uuid4()),
                        "category_id": str(setup.category),
                        "operation": "model.configuration.save",
                        "expected_revision": 1,
                        "source_read_set": [],
                        "payload": {
                            "expected_revision": 0,
                            "enabled": True,
                            "metadata": {
                                "protocol": "openai-compatible",
                                "base_url": "https://synthetic.invalid/v1",
                                "model": "synthetic-model",
                                "model_version": "synthetic@1",
                            },
                        },
                    },
                )
                assert saved.status_code == 200, saved.text
                path = f"/v1/categories/{setup.category}/agent-runs"
                accepted = api.post(
                    path,
                    headers=setup.headers,
                    json={
                        "goal": "Synthetic default host public research",
                        "idempotency_key": str(uuid4()),
                    },
                )
                assert accepted.status_code == 202, accepted.text
                identity = UUID(accepted.json()["run_id"])
                env = dict(
                    os.environ,
                    PDOS_WORKFLOW_TENANTS=str(setup.tenant),
                    PDOS_CHECKPOINT_DATABASE_URL=checkpoint_input,
                    PDOS_OBJECT_ROOT=str(tmp_path / "objects"),
                    PDOS_OBJECT_LIFECYCLE_PROFILE="local-synthetic-v1",
                )
                if confirmation == "restart":
                    env["PDOS_RESEARCH_RESTART_FIXTURE"] = str(tmp_path)
                process = subprocess.Popen(
                    [sys.executable, "-m", "tests.agent_kernel.test_research_runtime_process"],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                restarts = []
                if confirmation == "restart":
                    for phase in ("search", "read"):
                        marker = tmp_path / f"restart-{phase}.json"
                        wait_for(marker.exists, process, seconds=90)
                        stamp = json.loads(marker.read_text())
                        assert stamp["run_id"] == str(identity)
                        with Session(setup.admin) as session:
                            fanout = session.scalar(select(AgentToolCall).where(
                                AgentToolCall.run_id == identity,
                                AgentToolCall.tool == "research.fanout",
                            ))
                            assert fanout.state == "started"
                            fanout_id = str(fanout.id)
                            actual_job = str(uuid5(identity, "research.fanout:" + fanout.call_key))
                        with PostgresSaver.from_conn_string(checkpoint_url) as saver:
                            prefix = f"xiaopai:{setup.tenant}:{stamp['session_id']}:{identity}:"
                            execution = {"job_id": actual_job, "task": stamp["context"]}
                            thread = prefix + digest([identity, "research", execution])
                            latest = saver.get_tuple({"configurable": {"thread_id": thread}})
                            assert latest is not None
                            assert any(
                                row["tool"] == f"research.{phase}"
                                for row in latest.checkpoint["channel_values"]["tool_results"]
                            )
                        current_temporal, _ = temporal_state(identity, setup)
                        restarts.append(dict(
                            phase=phase, child_thread=thread, temporal_run_id=current_temporal,
                            fanout_call_id=fanout_id,
                            checkpoint_id=latest.config["configurable"]["checkpoint_id"],
                        ))
                        process.kill()
                        process.wait(timeout=10)
                        process = subprocess.Popen(
                            [sys.executable, "-m",
                             "tests.agent_kernel.test_research_runtime_process"],
                            env=env, stdout=log, stderr=subprocess.STDOUT,
                        )

                def terminal():
                    result = api.get(path + f"/{identity}", headers=setup.headers).json()
                    return (
                        result if result["status"] in {"completed", "partial", "failed"} else None
                    )

                result = wait_for(terminal, process, seconds=90)
                assert result["status"] == "completed", result
                report = result["result"]["result"]["research"]
                assert report["source_count"] == report["row_count"] == 1
                assert (
                    len(report["jobs"]) == 1
                    and report["jobs"][0]["coverage"][0]["accepted_rows"] == 1
                )
                assert RAW not in json.dumps(report)
                events = api.get(path + f"/{identity}/events", headers=setup.headers)
                assert RAW not in events.text
                outbound = [
                    row["event"]
                    for row in events.json()["items"]
                    if row["event"].get("channel") == "research"
                ]
                assert {row["provider"] for row in outbound} == {
                    "synthetic-search",
                    "public-web:maker.example",
                }
                assert len(outbound) == 2 and all(row["agreement_id"] is None for row in outbound)
                assert all(row["data_categories"] == ["public"] for row in outbound)
                candidate = next(
                    row["event"]
                    for row in events.json()["items"]
                    if row["event"]["type"] == "snapshot_candidate"
                )
                candidates = api.get(path + f"/{identity}/candidates", headers=setup.headers)
                assert candidates.status_code == 200, candidates.text
                item = candidates.json()["items"][0]
                assert item["state"] == "pending" and item["command"] == candidate["command"]
                assert item["summary"]["title"] == "Synthetic specs" and RAW not in candidates.text
                if confirmation.startswith("browser_"):
                    with Session(setup.admin) as session:
                        assert (
                            session.scalar(
                                select(PublicWebSnapshot).where(
                                    PublicWebSnapshot.registered_by_run_id == identity
                                )
                            )
                            is None
                        )
                        budget = session.get(ValidationBudget, budget_id)
                        assert budget.calls == 7 and budget.held_micro_usd == 0
                    print(
                        json.dumps(
                            {
                                "run_id": str(identity),
                                "event_id": item["event_id"],
                                "confirmation": confirmation,
                                "pending_snapshot": True,
                                "host_config": str(tmp_path / "host.json"),
                                "external_calls": 0,
                            }
                        )
                    )
                    return
                adopted, command = submit(setup, api, candidate["command"])
                assert adopted.status_code == 200, adopted.text
                repeated, _ = submit(setup, api, command, preview=False)
                assert repeated.json()["id"] == adopted.json()["id"]
                after = api.get(path + f"/{identity}/candidates", headers=setup.headers).json()[
                    "items"
                ][0]
                assert after["state"] == "adopted" and after["command"] is None
                assert after["receipt"]["id"] == adopted.json()["id"]
                with Session(setup.admin) as session:
                    run = session.get(AgentRun, identity)
                    snapshot = session.scalar(
                        select(PublicWebSnapshot).where(
                            PublicWebSnapshot.registered_by_run_id == identity
                        )
                    )
                    assert snapshot and snapshot.url == URL and RAW in snapshot.markdown
                    assert session.get(Receipt, snapshot.receipt_id).agent_run_id == identity
                    budget = session.get(ValidationBudget, budget_id)
                    assert budget.calls == 7 and budget.spent_micro_usd == 840
                    assert budget.held_micro_usd == 0 and run.held_tokens == 0
                    fanout = session.scalar(
                        select(AgentToolCall).where(
                            AgentToolCall.run_id == identity,
                            AgentToolCall.tool == "research.fanout",
                        )
                    )
                    previous, job_id = fanout.result, fanout.result["job_id"]
                    if confirmation == "restart":
                        assert len({row["child_thread"] for row in restarts}) == 1
                        assert len({row["temporal_run_id"] for row in restarts}) == 1
                        assert len({row["fanout_call_id"] for row in restarts}) == 1
                        assert str(fanout.id) == restarts[0]["fanout_call_id"]
                        assert temporal_state(identity, setup)[0] == restarts[0]["temporal_run_id"]
                        assert job_id == str(uuid5(identity, "research.fanout:" + fanout.call_key))
                        log.flush()
                        worker_output = (tmp_path / "research-worker.log").read_text()
                        assert worker_output.count('"transport": "search"') == 1
                        assert worker_output.count('"transport": "web"') == 1
                        print(json.dumps(dict(
                            actual_worker_processes=3, hard_restarts=2, restarts=restarts,
                            same_research_call=True, model_calls=budget.calls,
                            search_requests=1, web_requests=1,
                        )), flush=True)
                    session.expunge(run)
                owner = Bootstrap(setup.engine)

                def no_model(*_args, **_kwargs):
                    pytest.fail("Completed fanout replay must not make a new model request")

                from pdos_next.agent_kernel import gateway

                monkeypatch.setattr(gateway.AgentProviderClient, "turn", no_model)
                scope = owner.store.scope(
                    tenant_id=setup.tenant,
                    requester_id=setup.human,
                    writer_id=setup.agent,
                    category_id=setup.category,
                    run_id=identity,
                )
                restored = owner.adapters().read_restores["research.fanout"](
                    scope,
                    {"tasks": [{"key": "specs", "focus": "synthetic pump"}]},
                    previous,
                )
                assert restored == previous and restored["job_id"] == job_id
                prefix = f"xiaopai:{run.tenant_id}:{run.session_id}:{run.id}"
                with PostgresSaver.from_conn_string(checkpoint_url) as saver:
                    with saver.conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s",
                            (prefix + "%",),
                        )
                        threads = {row["thread_id"] for row in cursor.fetchall()}
                    assert len(threads) == 2 and prefix in threads
                    child = saver.get_tuple(
                        {"configurable": {"thread_id": next(iter(threads - {prefix}))}}
                    )
                    assert {
                        r["tool"] for r in child.checkpoint["channel_values"]["tool_results"]
                    } == {
                        "research.search",
                        "research.read",
                    }
                print(
                    json.dumps(
                        {
                            "run_id": str(identity),
                            "snapshot_id": str(snapshot.id),
                            "job_id": job_id,
                            "model_calls": 7,
                            "cost_micro_usd": 840,
                            "checkpoint_threads": 2,
                            "exact_job_replay": True,
                            "external_model_calls": 0,
                            "external_search_read_calls": 0,
                        }
                    )
                )
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=15)


if __name__ == "__main__":
    import asyncio

    import httpx

    from pdos_next.agent_kernel import gateway
    from pdos_next.research import search, service
    from pdos_next.research.web import HTTPResponse
    from pdos_next.workflows.worker import main

    real_search, real_service = search.SearxSearchAdapter, service.ResearchService

    def offline_search(request):
        print(json.dumps({"transport": "search"}), flush=True)
        assert request.url.params["q"] == "synthetic pump"
        return httpx.Response(
            200, json={"results": [{"url": URL, "title": "Synthetic pump specs"}]}
        )

    async def public_dns(_host):
        return ("8.8.8.8",)

    class Web:
        async def request(self, url, address, _limits):
            print(json.dumps({"transport": "web"}), flush=True)
            assert url == URL and address == "8.8.8.8"
            return HTTPResponse(
                200,
                (("content-type", "text/html"),),
                (
                    f"<title>Synthetic specs</title><p>Pressure: 20 psi at 25 C.</p><p>{RAW}</p>"
                ).encode(),
            )

    search.SearxSearchAdapter = lambda *args, **kwargs: real_search(
        *args, transport=httpx.MockTransport(offline_search), **kwargs
    )
    service.ResearchService = lambda *args, **kwargs: real_service(
        *args, transport=Web(), resolver=public_dns, **kwargs
    )
    AliyunKms.sdk = lambda _self: KmsSdk()
    gateway.AgentProviderClient = OfflineResearchClient
    if os.environ.get("PDOS_RESEARCH_RESTART_FIXTURE"):
        from pathlib import Path

        original_turn = gateway.AgentGateway.turn

        def before_new_model(self, bound, **kwargs):
            messages = kwargs["messages"]
            if bound.isolation == "research" and messages[-1]["role"] == "tool":
                previous = json.loads(messages[-1]["content"])
                phase = "search" if "hits" in previous else "read"
                marker = Path(os.environ["PDOS_RESEARCH_RESTART_FIXTURE"]) / f"restart-{phase}.json"
                if not marker.exists():
                    marker.write_text(json.dumps(dict(
                        run_id=str(bound.run_id), session_id=str(bound.session_id), phase=phase,
                        context=json.loads(messages[0]["content"])["context"]["research_task"],
                    )))
                    while True:
                        time.sleep(0.1)
            return original_turn(self, bound, **kwargs)

        gateway.AgentGateway.turn = before_new_model
    asyncio.run(main())
