"""Root-run native summary/own-binding UI fixture; collection is offline.

The repo's real five-case fixture creates the origin and verified binding. Official
HTTPS is httpx.MockTransport. This module starts only loopback HTTP when explicitly
executed by root with the already reviewed isolated PG/checkpoint environment.
"""
# ruff: noqa: F401,F811 -- native pytest fixture dependency tree is re-exported

import asyncio
import json
import os
import socket
import stat
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx
import pytest
import uvicorn
from pdos_next import models as common_models  # noqa: F401 -- common metadata before child models
from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.models import (
    AgentRun,
    AgentToolCall,
    TenantSkillEnablement,
    ValidationBudget,
)
from pdos_next.agent_kernel.temporal_port import RuntimeTemporal
from pdos_next.api import create_app
from pdos_next.dingtalk.models import Delivery, Message
from pdos_next.dingtalk.summary_models import SummaryDelivery
from pdos_next.domain.automations.models import AutomationRuleCurrent, AutomationRuleVersion
from pdos_next.domain.automations.schemas import ZERO_MODEL_BUDGET
from pdos_next.domain.automations.service_models import AutomationServiceGrant
from pdos_next.models import Artifact, Confirmation, Receipt, now
from pdos_next.service import digest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.conftest import engines, setup
from tests.dingtalk.test_summary_delivery_pg import (
    channel,
    complete,
    original_security_work,
    summary_channel,
    summary_work,
    work_case,
)


class NativeUiBoundary:
    """Pass native bytes unchanged; UI writes are only original T1 and receipt lookup."""

    def __init__(self, app, category, delivery):
        self.app = app
        self.commands = f"/v1/categories/{category}/commands"
        self.reconcile = f"/v1/personal/inbox/summary-deliveries/{delivery}/reconcile"
        self.allowed, self.denied = Counter(), Counter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        key = method + " " + path
        if method not in {"GET", "HEAD"} and not (
            method == "POST" and path in {self.commands, self.commands + "/preview", self.reconcile}
        ):
            self.denied[key] += 1
            body = (
                b'{"code":"FORBIDDEN_SCOPE","message":"Use native summary T1 or original receipt."}'
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            return await send({"type": "http.response.body", "body": body})
        self.allowed[key] += 1
        return await self.app(scope, receive, send)


def local_web(value):
    url = urlsplit(value)
    assert url.scheme == "http" and url.hostname == "127.0.0.1" and url.port
    assert not url.username and not url.password and url.path in {"", "/"}
    assert not url.query and not url.fragment
    return value.rstrip("/")


def private_folder(value):
    folder = Path(value)
    assert folder.is_absolute() and not folder.exists() and not folder.is_symlink()
    assert folder.resolve().is_relative_to(Path("/tmp").resolve()) and folder.parent.is_dir()
    folder.mkdir(mode=0o700)
    os.chmod(folder, 0o700)
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    return folder


def write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def counts(work):
    models = (
        Artifact,
        AgentRun,
        AgentToolCall,
        ValidationBudget,
        TenantSkillEnablement,
        Message,
        Delivery,
        SummaryDelivery,
        AutomationRuleCurrent,
        AutomationRuleVersion,
        AutomationServiceGrant,
    )
    with Session(work.setup.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.tenant_id == work.setup.tenant,
                )
            )
            for model in models
        }


def finish_checks(work, boundary, baseline, original, delivery_id, ui_name):
    """Assert actual UI-created native atoms; never synthesize missing outcomes."""
    setup = work.setup
    current = counts(work)
    with Session(setup.admin) as session:
        run = session.get(AgentRun, UUID(work.reference["run_id"]))
        assert run.requester_id == setup.human and run.category_id == setup.category
        assert run.result == original and run.state in {"completed", "partial"}
        rows = session.scalars(
            select(AutomationRuleCurrent)
            .join(
                AutomationRuleVersion,
                (AutomationRuleVersion.tenant_id == AutomationRuleCurrent.tenant_id)
                & (AutomationRuleVersion.id == AutomationRuleCurrent.version_id),
            )
            .where(
                AutomationRuleCurrent.tenant_id == setup.tenant,
                AutomationRuleCurrent.owner_id == setup.human,
                AutomationRuleVersion.spec["name"].astext == ui_name,
            )
        ).all()
        assert len(rows) == 1, "Create the named new rule through the original browser form"
        rule = rows[0]
        assert rule.state == "active" and rule.published_version_id
        active = session.get(AutomationRuleVersion, rule.published_version_id)
        assert active.action == "activate" and active.state == "active"
        assert active.actor_id == active.requester_id == active.owner_id == setup.human
        assert active.confirmation_id is not None and active.receipt_id is not None
        spec = active.spec
        assert spec["personal_summary"]["dingtalk_binding_id"] == work.binding["binding_id"]
        assert spec["skill_keys"] == [] and spec["validation_budget_id"] is None
        assert spec["budget"] == dict(ZERO_MODEL_BUDGET) and spec["token_limit"] == 1
        drafts = session.scalars(
            select(AutomationRuleVersion).where(
                AutomationRuleVersion.tenant_id == setup.tenant,
                AutomationRuleVersion.rule_id == rule.rule_id,
                AutomationRuleVersion.action == "draft",
            )
        ).all()
        assert drafts and any(d.spec == spec and d.revision < active.revision for d in drafts)
        receipt = session.get(Receipt, active.receipt_id)
        confirmation = session.get(Confirmation, active.confirmation_id)
        assert receipt.operation == "ai.automation.activate"
        assert (
            receipt.subject_id == active.id
            and receipt.actor_id == receipt.requester_id == setup.human
        )
        assert confirmation.consumed and confirmation.id == receipt.confirmation_id
        grant = session.scalar(
            select(AutomationServiceGrant).where(
                AutomationServiceGrant.tenant_id == setup.tenant,
                AutomationServiceGrant.published_version_id == active.id,
            )
        )
        assert grant and grant.owner_id == setup.human and grant.writer_id == setup.agent
        delivered = session.get(SummaryDelivery, delivery_id)
        assert delivered.owner_id == setup.human and delivered.run_id == run.id
        assert delivered.binding_id == UUID(work.binding["binding_id"])
        assert delivered.state == "delivered" and delivered.attempts == 1
        assert delivered.p26["provider"] == "dingtalk" and delivered.provider_receipt
        assert UUID(work.work.receipt["subject_id"]) in delivered.source_ids
        assert delivered.summary_sha256 == digest(original["result"]["personal_summary"])
        safe_status = {
            "delivery_id": str(delivered.id),
            "run_id": str(delivered.run_id),
            "state": delivered.state,
            "attempts": delivered.attempts,
            "provider": delivered.p26["provider"],
            "error_code": delivered.error_code,
        }
        final_rule = {
            "rule_id": str(rule.rule_id),
            "state": rule.state,
            "published_version_id": str(active.id),
            "revision": active.revision,
            "binding_id": spec["personal_summary"]["dingtalk_binding_id"],
            "native_receipt_id": str(active.receipt_id),
            "native_confirmation_id": str(active.confirmation_id),
            "draft_versions": len(drafts),
            "service_grant_id": str(grant.id),
        }
    for model in (
        Artifact,
        AgentRun,
        AgentToolCall,
        ValidationBudget,
        TenantSkillEnablement,
        Message,
        Delivery,
        SummaryDelivery,
    ):
        assert current[model.__tablename__] == baseline[model.__tablename__]
    assert (
        current[ValidationBudget.__tablename__] == current[TenantSkillEnablement.__tablename__] == 0
    )
    assert work.wire.calls.count("/v1.0/robot/oToMessages/batchSend") == 1
    assert work.wire.calls.count("/v1.0/robot/oToMessages/readStatus") >= 1
    assert boundary.allowed["GET /v1/personal/inbox/summary-channels"] >= 1
    assert boundary.allowed["GET /v1/personal/inbox/summary-deliveries"] >= 1
    assert boundary.allowed[f"GET /v1/categories/{setup.category}/agent-runs/{run.id}"] >= 1
    assert boundary.allowed["POST " + boundary.commands] >= 2
    assert boundary.allowed["POST " + boundary.commands + "/preview"] >= 1
    assert boundary.allowed["POST " + boundary.reconcile] >= 1
    assert not boundary.denied, dict(boundary.denied)
    # Ordinary native reads verify the same persisted facts after the UI round trip.
    detail = work.channel.client.get(
        f"/v1/categories/{setup.category}/automation-rules/{rule.rule_id}",
        headers=setup.headers,
    )
    assert detail.status_code == 200, detail.text
    assert work.binding["binding_id"] in detail.text
    return {
        "synthetic": True,
        "native_ui_checks_passed": True,
        "before_counts": baseline,
        "after_counts": current,
        "ui_rule": final_rule,
        "summary_status": safe_status,
        "original_run_result_sha256": digest(original),
        "native_http_counts": dict(boundary.allowed),
        "official_mock_path_counts": dict(Counter(work.wire.calls)),
        "mock_body_sends": 1,
        "real_provider_calls": 0,
        "new_chat_runs": 0,
        "new_inbound_messages": 0,
    }


async def serve(work, boundary, listener, folder, metadata, finish):
    setup = work.setup
    server = uvicorn.Server(
        uvicorn.Config(
            boundary,
            host="127.0.0.1",
            port=listener.getsockname()[1],
            log_level="error",
            access_log=False,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    verified = None
    try:
        async with asyncio.timeout(15):
            while not server.started:
                assert not task.done(), "API failed before readiness"
                await asyncio.sleep(0.05)
        api_base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        token = setup.headers["Authorization"].removeprefix("Bearer ")
        write_private(
            folder / "storage.json",
            {
                "cookies": [
                    {
                        "name": "pdos-next-session",
                        "value": token,
                        "domain": "127.0.0.1",
                        "path": "/",
                        "httpOnly": True,
                        "secure": False,
                        "sameSite": "Lax",
                    }
                ],
                "origins": [],
            },
        )
        write_private(
            folder / "ready.json",
            {
                **metadata,
                "api_base": api_base,
                "storage": str(folder / "storage.json"),
                "server_bound": True,
            },
        )
        print(f"SUMMARY_DINGTALK_BROWSER_READY {folder / 'ready.json'} API={api_base}", flush=True)
        timeout = int(os.environ.get("PDOS_BROWSER_TIMEOUT_SECONDS", "2400"))
        assert 30 <= timeout <= 12600
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=3) as client:
            own = await client.get(api_base + "/v1/session", headers=setup.headers)
            assert own.status_code == 200 and own.json()["principal_id"] == str(setup.human)
            async with asyncio.timeout(timeout):
                while not (folder / "finish").exists():
                    assert not task.done(), "API exited during UI verification"
                    if verified is None:
                        try:
                            response = await client.get(
                                metadata["web_base"] + "/api/v1/session",
                                headers={"Cookie": "pdos-next-session=" + token},
                            )
                            if response.status_code == 200 and response.json().get(
                                "principal_id"
                            ) == str(setup.human):
                                verified = {
                                    "actual_web_base": metadata["web_base"],
                                    "actual_api_base": api_base,
                                    "fresh_principal_id": str(setup.human),
                                    "verified_at": now().isoformat(),
                                }
                                write_private(folder / "web-verified.json", verified)
                                print("SUMMARY_DINGTALK_WEB_VERIFIED", flush=True)
                        except (httpx.HTTPError, ValueError):
                            pass
                    await asyncio.sleep(0.3 if verified else 1)
            assert verified, "The selected actual frontend did not use this fresh login"
            result = finish()
            write_private(folder / "result.json", {**result, "web": verified})
            print(f"SUMMARY_DINGTALK_BROWSER_FINISHED {folder / 'result.json'}", flush=True)
    except BaseException as error:
        if not (folder / "result.json").exists():
            write_private(
                folder / "result.json",
                {
                    "synthetic": True,
                    "native_ui_checks_passed": False,
                    "failure_type": type(error).__name__,
                    "failure": str(error),
                    "web": verified,
                },
            )
        raise
    finally:
        server.should_exit = True
        await task


@pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True)
def test_summary_dingtalk_browser(summary_channel, setup):
    work = summary_channel
    assert work.setup is setup
    assert setup.test_authorization_window == timedelta(hours=4)
    web = local_web(os.environ["PDOS_BROWSER_WEB_URL"])
    folder = private_folder(os.environ["PDOS_BROWSER_DIR"])
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", int(os.environ.get("PDOS_BROWSER_API_PORT", "0"))))
    listener.listen(128)
    try:
        complete(work)  # Original registered no-model summary; native business fixture facts.
        sent = work.service.deliver(work.reference)  # Exactly one official MockTransport body send.
        assert sent["state"] == "unknown" and sent["attempts"] == 1
        identity = UUID(sent["delivery_id"])
        with Session(setup.admin) as session:
            run = session.get(AgentRun, UUID(work.reference["run_id"]))
            original = deepcopy(run.result)
        baseline = counts(work)
        ui_name = "浏览器：本人钉钉工作摘要"
        ports = Bootstrap(setup.engine).api_ports(RuntimeTemporal())
        api = create_app(
            setup.engine, setup.auth, agent_runtime_ports=RuntimePorts(),
            agent_api_ports=ports, workflow_enabled=False,
        )
        boundary = NativeUiBoundary(api, setup.category, identity)
        metadata = {
            "synthetic": True,
            "web_base": web,
            "tenant_id": str(setup.tenant),
            "principal_id": str(setup.human),
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "project_id": str(work.work.work.project_id),
            "binding_id": work.binding["binding_id"],
            "binding_epoch": work.binding["epoch"],
            "run_id": work.reference["run_id"],
            "delivery_id": str(identity),
            "initial_delivery_state": sent["state"],
            "ui_rule_name": ui_name,
            "authorization_until": setup.test_authorization_until.isoformat(),
            "baseline_counts": baseline,
            "original_run_result_sha256": digest(original),
            "ui_paths": {
                "settings": "/?" + urlencode({"area": "settings", "category": str(setup.category)}),
                "original_run": f"/dingtalk/runs/{run.id}?category={setup.category}",
            },
            "required_ui": [
                "new summary draft, select actual own binding",
                "original preview and one T1 confirmation, refresh persisted choice",
                "open original category-bound Run and structured summary",
                "read original unknown status then lookup receipt to delivered",
            ],
            "transport": "official httpx.MockTransport only; no model/KMS network",
        }
        asyncio.run(
            serve(
                work,
                boundary,
                listener,
                folder,
                metadata,
                lambda: finish_checks(work, boundary, baseline, original, identity, ui_name),
            )
        )
    finally:
        listener.close()
