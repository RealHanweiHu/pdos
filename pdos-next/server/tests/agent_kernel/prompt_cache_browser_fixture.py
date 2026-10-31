"""Root-run protocol UI fixture; collection never starts DB or loopback services."""
# ruff: noqa: F401,F811 -- imported original pytest fixture dependency tree

import asyncio
import json
import os
import socket
from collections import Counter
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
import pytest
import uvicorn
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import RuntimePorts
from pdos_next.agent_kernel.models import ProviderDataAgreement
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.models import Audit, Outbox, Receipt, now
from tests.agent_kernel.test_management_api import promote
from tests.conftest import engines, setup

PROVIDER = "synthetic-prompt-cache-ui"
PROTECTED = (
    "artifact_versions", "agent_sessions", "agent_runs", "agent_tool_calls",
    "model_invocations", "model_budget_reservations", "enterprise_embedding_calls",
    "agent_validation_budgets",
)
pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_PORT") != "53502"
    or not os.environ.get("TEST_DATABASE_URL") or not os.environ.get("TEST_DATABASE_MARKER"),
    reason="Root must bind the existing explicitly guarded 53502/pdos_test fixture",
)


def write_json(path, value, *, private=True):
    mode = 0o600 if private else 0o644
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "w") as stream:
        os.fchmod(stream.fileno(), mode)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def local_web(value):
    url = urlsplit(value)
    assert url.scheme == "http" and url.hostname == "127.0.0.1" and url.port
    assert not url.username and not url.password and url.path in {"", "/"}
    assert not url.query and not url.fragment
    return value.rstrip("/")


def protected_state(person):
    with Session(person.admin) as session:
        return {
            table: dict(session.execute(text(
                "SELECT count(*) AS count, "
                "md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY id), '')) AS digest "
                f"FROM public.{table} t WHERE tenant_id=:tenant"
            ), {"tenant": person.tenant}).mappings().one())
            for table in PROTECTED
        }


class ProtocolOnly:
    def __init__(self, app, path):
        self.app, self.path = app, path
        self.allowed, self.denied = Counter(), Counter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        key = method + " " + path
        if method not in {"GET", "HEAD"} and not (
            method == "POST" and path in {self.path, self.path + "/recover"}
        ):
            self.denied[key] += 1
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json")]})
            return await send({"type": "http.response.body", "body": (
                b'{"code":"FORBIDDEN_SCOPE","message":"Protocol UI writes only."}'
            )})
        self.allowed[key] += 1
        return await self.app(scope, receive, send)


def agreements(person):
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        category_id=person.category) as session:
        return session.scalar(select(func.count()).select_from(ProviderDataAgreement))


async def finish_checks(person, client, api_base, path, baseline, boundary, preview):
    assert preview is not None, "Request the preview checkpoint before the first approval"
    response = await client.get(api_base + path, headers=person.headers)
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["can_edit"] is True and len(current["items"]) == 1
    assert current["items"][0]["provider"] == PROVIDER
    assert current["items"][0]["revision"] == 2
    assert current["items"][0]["prompt_cache_allowed"] is False
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        category_id=person.category) as session:
        rows = session.scalars(select(ProviderDataAgreement).order_by(
            ProviderDataAgreement.revision,
        )).all()
        assert len(rows) == 2 and [row.revision for row in rows] == [1, 2]
        assert [row.prompt_cache_allowed for row in rows] == [True, False]
        checked = []
        for row in rows:
            assert row.provider == PROVIDER and row.registered_by == person.human and row.active
            receipt = session.get(Receipt, row.receipt_id)
            assert receipt.operation == "provider.agreement.register"
            assert receipt.category_id == person.category
            assert receipt.subject_type == "provider_agreement"
            assert receipt.actor_id == receipt.requester_id == person.human
            assert receipt.agent_run_id is receipt.run_id is None
            assert receipt.subject_id == row.id and receipt.subject_revision == row.revision
            assert receipt.result["tier"] == "T2" and receipt.result["decision"] == "批准"
            assert receipt.result["id"] == str(row.id) and receipt.result["provider"] == PROVIDER
            assert receipt.result["decided_by"] == str(person.human)
            assert receipt.result["revision"] == row.revision
            assert receipt.result["prompt_cache_allowed"] is row.prompt_cache_allowed
            assert session.scalar(select(func.count()).select_from(Audit).where(
                Audit.receipt_id == receipt.id,
            )) == 1
            assert session.scalar(select(func.count()).select_from(Outbox).where(
                Outbox.receipt_id == receipt.id,
                Outbox.type == "provider.agreement_registered", Outbox.subject_id == row.id,
            )) == 1
            checked.append({"id": str(row.id), "revision": row.revision,
                            "prompt_cache_allowed": row.prompt_cache_allowed,
                            "receipt_id": str(receipt.id), "tier": "T2"})
    assert protected_state(person) == baseline
    assert boundary.allowed["POST " + path] == 2, "Exactly two UI registration attempts expected"
    return {"synthetic": True, "native_ui_checks_passed": True, "versions": checked,
            "preview_checkpoint": preview, "protected_state_unchanged": True,
            "before": baseline, "after": protected_state(person),
            "allowed_http": dict(boundary.allowed), "denied_http": dict(boundary.denied),
            "real_model_calls": 0, "real_embedding_calls": 0, "real_outbound_calls": 0}


async def serve(person, boundary, listener, folder, web, baseline):
    api_base = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(boundary, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    verified, preview = None, None
    token = person.headers["Authorization"].removeprefix("Bearer ")
    try:
        async with asyncio.timeout(15):
            while not server.started:
                assert not task.done(), "API exited before serving"
                await asyncio.sleep(0.05)
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=3) as client:
            own = await client.get(api_base + "/v1/session", headers=person.headers)
            assert own.status_code == 200 and own.json()["principal_id"] == str(person.human)
            denied = await client.post(api_base + "/v1/personal/agent-runs", json={})
            assert denied.status_code == 403
            assert agreements(person) == 0 and protected_state(person) == baseline
            write_json(folder / "storage.json", {"cookies": [{
                "name": "pdos-next-session", "value": token, "domain": "127.0.0.1",
                "path": "/", "httpOnly": True, "secure": False, "sameSite": "Lax",
            }], "origins": []})
            metadata = {
                "synthetic": True, "api_served": True, "api_base": api_base, "web_base": web,
                "tenant_id": str(person.tenant), "principal_id": str(person.human),
                "category_id": str(person.category), "provider": PROVIDER,
                "storage_path": str(folder / "storage.json"),
                "state_path": str(folder / "state.json"),
                "preview_marker": str(folder / "preview"),
                "preview_verified_path": str(folder / "preview-verified.json"),
                "finish_marker": str(folder / "finish"), "result_path": str(folder / "result.json"),
                "web_verified_path": str(folder / "web-verified.json"),
                "settings_path": "/?" + urlencode({"area": "settings",
                                                    "category": str(person.category)}),
                "agreement_api_path": boundary.path,
                "signed_on_suggestion": (now() - timedelta(days=1)).isoformat(),
                "expires_at_suggestion": (now() + timedelta(days=30)).isoformat(),
                "authorization_until": person.test_authorization_until.isoformat(),
                "baseline": baseline,
            }
            write_json(folder / "state.json", metadata)
            write_json(folder / "ready.json", metadata, private=False)
            print(f"PROMPT_CACHE_BROWSER_READY {folder / 'ready.json'} API={api_base}", flush=True)
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
                                print("PROMPT_CACHE_WEB_VERIFIED", flush=True)
                        except (httpx.HTTPError, ValueError):
                            pass
                    if preview is None and (folder / "preview").exists():
                        assert verified is not None, "Web must use this fresh API before preview"
                        assert agreements(person) == 0
                        assert protected_state(person) == baseline
                        assert boundary.allowed["POST " + boundary.path] == 0
                        preview = {"agreement_count": 0, "native_register_posts": 0,
                                   "protected_state_unchanged": True,
                                   "checked_at": now().isoformat()}
                        write_json(folder / "preview-verified.json", preview, private=False)
                        print("PROMPT_CACHE_PREVIEW_ZERO_WRITES", flush=True)
                    await asyncio.sleep(0.3 if verified else 1)
            assert verified is not None, "Actual web must serve the fresh session before finish"
            result = await finish_checks(person, client, api_base, boundary.path,
                                         baseline, boundary, preview)
            write_json(folder / "result.json", {**result, "web": verified}, private=False)
            print(f"PROMPT_CACHE_BROWSER_FINISHED {folder / 'result.json'}", flush=True)
    except BaseException as error:
        if not (folder / "result.json").exists():
            write_json(folder / "result.json", {"synthetic": True,
                       "native_ui_checks_passed": False, "failure_type": type(error).__name__,
                       "failure": str(error), "web": verified}, private=False)
        raise
    finally:
        server.should_exit = True
        await task


@pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True)
def test_prompt_cache_browser(setup):
    web = local_web(os.environ["PDOS_BROWSER_WEB_URL"])
    folder = Path(os.environ["PDOS_BROWSER_DIR"])
    assert folder.is_absolute() and not folder.exists() and not folder.is_symlink()
    assert folder.resolve().is_relative_to(Path("/tmp").resolve()) and folder.parent.is_dir()
    folder.mkdir(mode=0o700)
    os.chmod(folder, 0o700)
    promote(setup)
    assert agreements(setup) == 0
    baseline = protected_state(setup)
    assert all(row["count"] == 0 for row in baseline.values())
    app = create_app(setup.engine, setup.auth, agent_runtime_ports=RuntimePorts(),
                     workflow_enabled=False)
    boundary = ProtocolOnly(app, f"/v1/categories/{setup.category}/provider-agreements")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    try:
        asyncio.run(serve(setup, boundary, listener, folder, web, baseline))
    finally:
        listener.close()
