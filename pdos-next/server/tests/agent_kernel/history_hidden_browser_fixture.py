"""Explicit root-run hidden-history UI fixture; collection starts no DB or service."""
# ruff: noqa: F401,F811 -- original pytest fixture dependency tree

import asyncio
import copy
import os
import socket
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.api import create_app
from pdos_next.models import ObjectAudience, now
from tests.agent_kernel.prompt_cache_browser_fixture import (
    PROTECTED,
    local_web,
    protected_state,
    write_json,
)
from tests.agent_kernel.test_run_continuation import path, scope, start
from tests.conftest import engines, setup
from tests.preproject.test_g0 import post, request

GOAL = "只核对充气泵的压力单位，未知处保留未知。"
SUMMARY = "合成历史结果：压力单位尚未核实，未执行任何业务动作。HIDDEN_SUMMARY_MARKER"
HIDDEN_MESSAGE = "原回答所依据的资料已不可读，保留你的原话。"
EXTRA_PROTECTED = (
    "uploaded_originals", "original_scan_requests", "original_scan_results", "original_security",
    "object_audiences", "agent_work_states", "agent_run_events", "action_receipts",
    "audit_entries", "outbox_events",
)
pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_PORT") != "53502"
    or not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("TEST_DATABASE_MARKER"),
    reason="Root must bind the existing explicitly guarded 53502/pdos_test fixture",
)


def snapshot(person):
    value = protected_state(person)
    assert set(value) == set(PROTECTED)
    with Session(person.admin) as session:
        for table in EXTRA_PROTECTED:
            value[table] = dict(session.execute(text(
                "SELECT count(*) AS count, "
                "md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY id), '')) AS digest "
                f"FROM public.{table} t WHERE tenant_id=:tenant"
            ), {"tenant": person.tenant}).mappings().one())
    return value


def assert_hidden(response, identity):
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["run_id"] == str(identity) and value["goal"] == GOAL
    assert value["history_hidden"] is True and value["status"] == "hidden"
    assert value["hidden_message"] == HIDDEN_MESSAGE
    assert value["result"] is None and value["versions"] == {}
    assert value["process"] is None and value["reconciliation"] is None
    assert SUMMARY not in response.text and "HIDDEN_SUMMARY_MARKER" not in response.text
    return value


def prepare(person):
    registered = post(person, request(person, "evidence.artifact.register", {
        "title": "浏览器撤权合成历史资料", "content": "合成原文，仅用于权限撤回验证。",
        "source_label": "浏览器只读验收合成来源", "visibility": "audience",
    }), actor=person.peer)
    assert registered.status_code == 200, registered.text
    artifact = UUID(registered.json()["subject_id"])
    with Session(person.admin) as session, session.begin():
        audience = ObjectAudience(tenant_id=person.tenant, category_id=person.category,
            object_type="artifact_versions", subject_id=artifact, owner_id=person.peer,
            principal_id=person.human)
        session.add(audience)
        session.flush()
        audience_id = audience.id
    identity, accepted = start(person, goal=GOAL,
        sources=[{"artifact_id": str(artifact), "expected_revision": 1}])
    owner = Bootstrap(person.engine, ports=RuntimePorts())
    owner.store.finish(scope(person, identity), {
        "status": "completed", "summary": SUMMARY, "result": {},
        "questions": [], "unfinished": ["核实压力单位"],
    })
    run_path = path(person) + f"/{identity}"
    before = person.client.get(run_path, headers=person.headers)
    assert before.status_code == 200, before.text
    assert before.json()["goal"] == GOAL and before.json()["result"]["summary"] == SUMMARY
    with Session(person.admin) as session, session.begin():
        session.delete(session.get(ObjectAudience, audience_id))
    hidden = assert_hidden(person.client.get(run_path, headers=person.headers), identity)
    peer = person.client.get(run_path, headers={
        "Authorization": f"Bearer {person.tokens[person.peer]}",
    })
    assert peer.status_code == 403 and GOAL not in peer.text and SUMMARY not in peer.text
    baseline = snapshot(person)
    assert baseline["agent_runs"]["count"] == 1
    assert baseline["artifact_versions"]["count"] == 1
    for table in ("agent_tool_calls", "model_invocations", "model_budget_reservations",
                  "enterprise_embedding_calls", "uploaded_originals"):
        assert baseline[table]["count"] == 0
    return {"run_id": identity, "run_path": run_path,
            "session_id": accepted["session_id"], "recorded_at": hidden["recorded_at"],
            "source_id": str(artifact), "source_receipt_id": registered.json().get("id"),
            "summary_visible_before_revoke": True}, baseline


class ReadOnly:
    def __init__(self, app):
        self.app = app
        self.allowed, self.denied, self.responses = Counter(), Counter(), Counter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        key = scope["method"] + " " + scope["path"]
        if scope["method"] not in {"GET", "HEAD"}:
            self.denied[key] += 1
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json")]})
            return await send({"type": "http.response.body", "body": (
                b'{"code":"FORBIDDEN_SCOPE","message":"Read-only browser fixture."}'
            )})
        self.allowed[key] += 1

        async def observed(message):
            if message["type"] == "http.response.start":
                self.responses[f"{key} {message['status']}"] += 1
            await send(message)

        return await self.app(scope, receive, observed)


async def serve(person, boundary, listener, folder, web, prepared, baseline):
    api_base = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(boundary, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    verified = None
    token = person.headers["Authorization"].removeprefix("Bearer ")
    try:
        async with asyncio.timeout(15):
            while not server.started:
                assert not task.done(), "API exited before serving"
                await asyncio.sleep(0.05)
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=3) as client:
            own = await client.get(api_base + "/v1/session", headers=person.headers)
            assert own.status_code == 200 and own.json()["principal_id"] == str(person.human)
            assert_hidden(await client.get(api_base + prepared["run_path"],
                headers=person.headers), prepared["run_id"])
            denied = await client.post(api_base + path(person), json={}, headers=person.headers)
            assert denied.status_code == 403 and snapshot(person) == baseline
            # Exclude preparation/boundary probes from the actual browser period.
            boundary.allowed.clear()
            boundary.denied.clear()
            boundary.responses.clear()
            write_json(folder / "storage.json", {"cookies": [{
                "name": "pdos-next-session", "value": token, "domain": "127.0.0.1",
                "path": "/", "httpOnly": True, "secure": False, "sameSite": "Lax",
            }], "origins": []})
            run_link = f"/dingtalk/runs/{prepared['run_id']}?" + urlencode({
                "category": str(person.category),
            })
            metadata = {"synthetic": True, "api_served": True, "api_base": api_base,
                "web_base": web, "tenant_id": str(person.tenant),
                "principal_id": str(person.human), "category_id": str(person.category),
                **{key: str(value) if isinstance(value, UUID) else value
                   for key, value in prepared.items()},
                "run_link": run_link, "browser_url": web + run_link,
                "expected_goal": GOAL, "expected_hidden_message": HIDDEN_MESSAGE,
                "forbidden_summary_marker": "HIDDEN_SUMMARY_MARKER",
                "storage_path": str(folder / "storage.json"),
                "finish_marker": str(folder / "finish"), "result_path": str(folder / "result.json"),
                "web_verified_path": str(folder / "web-verified.json"),
                "authorization_until": person.test_authorization_until.isoformat(),
                "baseline": baseline}
            write_json(folder / "state.json", metadata)
            write_json(folder / "ready.json", metadata, private=False)
            print(f"HISTORY_HIDDEN_BROWSER_READY {folder / 'ready.json'} API={api_base}",
                  flush=True)
            timeout = int(os.environ.get("PDOS_BROWSER_TIMEOUT_SECONDS", "2400"))
            assert 30 <= timeout <= 12600
            async with asyncio.timeout(timeout):
                while not (folder / "finish").exists():
                    assert not task.done(), "API exited during browser checks"
                    if verified is None:
                        try:
                            response = await client.get(web + "/api/v1/session", headers={
                                "Cookie": "pdos-next-session=" + token,
                            })
                            if response.status_code == 200 and response.json().get(
                                "principal_id"
                            ) == str(person.human):
                                verified = {"api_base": api_base, "web_base": web,
                                    "principal_id": str(person.human),
                                    "verified_at": now().isoformat()}
                                write_json(folder / "web-verified.json", verified, private=False)
                                print("HISTORY_HIDDEN_WEB_VERIFIED", flush=True)
                        except (httpx.HTTPError, ValueError):
                            pass
                    await asyncio.sleep(0.3 if verified else 1)
            assert verified is not None, "Actual web must serve the fresh session before finish"
            allowed, denied, responses = (Counter(boundary.allowed), Counter(boundary.denied),
                                           Counter(boundary.responses))
            key = "GET " + prepared["run_path"]
            assert allowed[key] >= 2, "Open the actual Run and reload it before finish"
            assert responses[key + " 200"] == allowed[key]
            forbidden = {route: count for route, count in (allowed + denied).items()
                         if route.split(" ", 1)[1].startswith(prepared["run_path"] + "/")}
            assert forbidden == {}, (
                "Hidden Run must not request events/candidates/process/continuation"
            )
            assert not denied, "The hidden viewer must not attempt a mutation"
            assert_hidden(await client.get(api_base + prepared["run_path"],
                headers=person.headers), prepared["run_id"])
            after = snapshot(person)
            assert after == baseline, "Read-only browser inspection changed protected native tables"
            result = {"synthetic": True, "native_readonly_checks_passed": True,
                "summary_visible_before_revoke": True, "hidden_goal_refresh_reads": allowed[key],
                "forbidden_run_subresource_requests": forbidden, "protected_state_unchanged": True,
                "before": baseline, "after": after, "allowed_http": dict(allowed),
                "denied_http": dict(denied), "response_http": dict(responses),
                "new_runs": 0, "new_model_calls": 0, "new_embedding_calls": 0,
                "real_model_calls": 0, "real_embedding_calls": 0, "real_outbound_calls": 0,
                "web": verified, "run_id": str(prepared["run_id"])}
            write_json(folder / "result.json", result, private=False)
            print(f"HISTORY_HIDDEN_BROWSER_FINISHED {folder / 'result.json'}", flush=True)
    except BaseException as error:
        if not (folder / "result.json").exists():
            write_json(folder / "result.json", {"synthetic": True,
                "native_readonly_checks_passed": False, "failure_type": type(error).__name__,
                "failure": str(error), "allowed_http": dict(boundary.allowed),
                "denied_http": dict(boundary.denied), "response_http": dict(boundary.responses),
                "web": verified}, private=False)
        raise
    finally:
        server.should_exit = True
        await task


@pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True)
def test_history_hidden_browser(setup):
    web = local_web(os.environ["PDOS_BROWSER_WEB_URL"])
    folder = Path(os.environ["PDOS_BROWSER_DIR"])
    assert folder.is_absolute() and not folder.exists() and not folder.is_symlink()
    assert folder.resolve().is_relative_to(Path("/tmp").resolve()) and folder.parent.is_dir()
    folder.mkdir(mode=0o700)
    os.chmod(folder, 0o700)
    app = create_app(setup.engine, setup.auth, agent_runtime_ports=RuntimePorts(),
                     workflow_enabled=False)
    person = copy.copy(setup)
    with TestClient(app) as client:
        person.client = client
        prepared, baseline = prepare(person)
    boundary = ReadOnly(app)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    try:
        asyncio.run(serve(person, boundary, listener, folder, web, prepared, baseline))
    finally:
        listener.close()
