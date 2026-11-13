"""AT-47 backup, restore and replay drill on one actual configuration-to-handoff chain (D211).

Opt-in only (PDOS_RESTORE_DRILL=1 and PDOS_EXTERNAL_HANDOFF_LINK=1) inside this
worktree's marked local environment: business database, LangGraph checkpoint
database, Agent runtime state database and the native Temporal dev server.

1. Build the real chain through public commands: engineering configuration and
   process, a test result imported from an uploaded report and computed against
   the accepted plan (D347), manufacturing publication with an uploaded original,
   a release package that fixes that test run, named engineering and
   manufacturing decisions, handoff authorization and its fixed delivery intent.
   Long-waiting maintenance workflows are in flight.
2. Back up every store at the moment the first send result is recorded as unknown.
3. The source keeps going (reconciliation, acceptances, effectiveness, conflict, and
   event delivery that starts a workflow), as production would after the backup.
4. Restore into a new marked environment and check: every table and the original
   file match the backup; the chain reads exactly as it did at the backup; replaying
   the original commands returns the original receipts and writes nothing; the
   unknown send stays unknown (no network send, one intent); the test result page
   reads as it did at the backup; undelivered events are
   delivered once, and their deterministic workflow IDs are not run a second time,
   both when Temporal is restored to the same point and when only the database is.
   The restored in-flight workflows replay against this checkout's workflow code.

No model, connector, socket to an external service or real delivery is used.
"""

# ruff: noqa: F811 - imported fixtures register the existing S2 dependency tree

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from manufacturing.external_handoff_transactions import harness
from manufacturing.preparation import publication_pg_helpers as upstream
from manufacturing.release_policy_transactions import test_decisions as flow
from projects.test_project_first_plan import accepted, post
from quality.execution.fixtures import (  # noqa: F401 - registers the S2 fixture tree
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
    results_work,
)
from security_fixture import synthetic_runtime
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from verification.results.fixtures import capture, current_rows
from verification.results.fixtures import command as result_command

from pdos_next.api import create_app
from pdos_next.core.database import engine_for, tenant_session
from pdos_next.core.models import UploadedOriginal
from pdos_next.core.safety import verify_test_target
from pdos_next.domain.builds.configurations.models import EngineeringConfiguration
from pdos_next.domain.manufacturing.release.policy_owner import ActualReleasePolicyOwner
from pdos_next.originals.access import object_reference
from pdos_next.originals.object_storage import LocalPrivateObjectStore
from tests.ui import test_project_release_packages_projection_pg as release_ui

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import backup_restore  # noqa: E402
import workflow_replay_check  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("PDOS_RESTORE_DRILL") != "1", reason="AT-47 drill is explicit opt-in"
)
TASK_QUEUE = "pdos-next-domain-v1"
# The drill's workflow-only worker polls its own queue so it never picks up other work.
MAINTENANCE_QUEUE = "pdos-next-drill-maintenance"


def _reads(work, client, package_id, publication_ref, handoff_id):
    """The chain as a person sees it: test result, publication, package, handoff."""
    root = harness._root(work)
    paths = {
        "test_results": (root + "/verification-results", {"build_id": work.results.build_id}),
        "publication": (
            upstream.root_url(work) + f"/{publication_ref['id']}",
            {"revision": publication_ref["revision"]},
        ),
        "package": (root + f"/release-packages/{package_id}", {}),
        "project_packages": (root + "/release-packages", {"project_id": str(work.project_id)}),
        "handoff": (root + f"/external-handoffs/{handoff_id}", {}),
        "handoff_receipts": (root + f"/external-handoffs/{handoff_id}/receipts", {}),
        "project_handoffs": (root + "/external-handoffs", {"project_id": str(work.project_id)}),
    }
    result = {}
    for name, (path, params) in paths.items():
        response = client.get(path, params=params, headers=work.setup.headers)
        assert response.status_code == 200, (name, response.text)
        result[name] = response.json()
    return result


def _counts(admin, tenant, models):
    with Session(admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == tenant)
            )
            for model in models
        }


def _workflow_runs(address, workflow_id):
    """Every run recorded for one workflow ID (visibility settles before counting)."""
    from temporalio.client import Client

    async def count():
        client = await Client.connect(address, namespace="pdos-next")
        await asyncio.sleep(1.0)
        return [
            execution.run_id
            async for execution in client.list_workflows(query=f'WorkflowId="{workflow_id}"')
        ]

    return asyncio.run(count())


def _unknown_handoffs(admin, tenant):
    from sqlalchemy import text

    with admin.connect() as connection:
        return connection.execute(
            text(
                "SELECT count(*) FROM external_handoff_currents WHERE tenant_id=:t "
                "AND (projection->>'delivery_unknown')::boolean"
            ),
            {"t": tenant},
        ).scalar_one()


def _pending_events(admin, tenant):
    from sqlalchemy import text

    with admin.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM outbox_events WHERE tenant_id=:t AND delivered_at IS NULL"),
            {"t": tenant},
        ).scalar_one()


def _dispatch_all(dispatch_engine, tenant, address):
    """Deliver every pending event once through the real Temporal consumer."""
    from temporalio.client import Client

    from pdos_next.core.dispatch.outbox import dispatch_once
    from pdos_next.workflows.transport import TemporalSender

    async def run():
        client = await Client.connect(address, namespace="pdos-next")
        sender = TemporalSender(client, task_queue=TASK_QUEUE, dispatch_engine=dispatch_engine)
        started = []

        async def recording(event):
            identity = await sender(event)
            if identity is not None:
                started.append({"event_type": event.event_type, "workflow_id": identity})
            return identity

        totals = {"delivered": 0, "unknown": 0, "rounds": 0}
        while True:
            result = await dispatch_once(dispatch_engine, tenant, recording)
            totals["rounds"] += 1
            totals["delivered"] += result["delivered"]
            totals["unknown"] += result["unknown"]
            if result["delivered"] == result["unknown"] == 0:
                break
        totals["workflows"] = started
        return totals

    return asyncio.run(run())


def _start_maintenance(address, tenant):
    """Start the real long-waiting maintenance workflows and let them reach a wait."""
    from temporalio.client import Client
    from temporalio.worker import Worker

    from pdos_next.workflows.maintenance import MaintenanceSender, TenantMaintenance, workflow_id

    async def run():
        client = await Client.connect(address, namespace="pdos-next")
        await MaintenanceSender(client, task_queue=MAINTENANCE_QUEUE).discover(tenant)
        identities = [
            workflow_id(job, tenant) for job in ("checkpoint_retention", "original_rescan")
        ]
        # Workflow code only: each run schedules its first Activity, which no worker
        # picks up, so both stay running with real history, like an in-flight pass.
        async with Worker(client, task_queue=MAINTENANCE_QUEUE, workflows=[TenantMaintenance]):
            for _ in range(100):
                histories = [
                    await client.get_workflow_handle(identity).fetch_history()
                    for identity in identities
                ]
                if all(
                    any(e.HasField("activity_task_scheduled_event_attributes") for e in h.events)
                    for h in histories
                ):
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("maintenance workflows did not reach their Activity")
        runs = {}
        for identity in identities:
            description = await client.get_workflow_handle(identity).describe()
            runs[identity] = description.run_id
        return runs

    return asyncio.run(run())


def _serve_restored_temporal(directory):
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tools/backup_restore.py"), "serve-temporal", str(directory)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(200):
        state = json.loads((directory / "restore.json").read_text())
        port = state.get("temporal_port")
        if port:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    time.sleep(1.0)
                    return process, f"127.0.0.1:{port}"
            except OSError:
                pass
        time.sleep(0.1)
    process.kill()
    raise AssertionError("restored Temporal did not start")


def _restored_engines(directory, monkeypatch):
    runtime = json.loads((directory / "runtime.json").read_text())
    monkeypatch.setenv("TEST_DATABASE_URL", runtime["admin_url"])
    monkeypatch.setenv("TEST_DATABASE_MARKER", runtime["marker"])
    monkeypatch.setenv("TEST_DATABASE_PORT", str(runtime["port"]))
    engines = SimpleNamespace(
        admin=engine_for(runtime["admin_url"]),
        app=engine_for(runtime["app_url"]),
        auth=engine_for(runtime["auth_url"]),
        dispatch=engine_for(runtime["dispatch_url"]),
    )
    for engine in (engines.admin, engines.app, engines.dispatch):
        verify_test_target(engine)
    engines.app._pdos_dispatch_engine = engines.dispatch
    return engines


def _differences(left, right, path=""):
    if isinstance(left, dict) and isinstance(right, dict):
        found = []
        for key in sorted(set(left) | set(right)):
            found += _differences(left.get(key), right.get(key), f"{path}.{key}")
        return found
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        found = []
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            found += _differences(a, b, f"{path}[{index}]")
        return found
    return [] if left == right else [{"path": path, "backup": left, "restored": right}]


@pytest.fixture
def drill_case(results_work, tmp_path, monkeypatch):
    """The publication chain on top of an actual, passing test result (D347).

    As native_case does for its failing run: the publication reuses the tested
    configuration and the results' original store, so one project holds the whole
    configuration → test → publication → decision → handoff chain.
    """
    results = results_work
    draft, _ = capture(
        results, tuple(range(len(results.report_rows))), artifact_id=results.report_artifact
    )
    results.result_receipt, _ = accepted(
        results.quality, result_command(results, "test.results.import", captured=draft, final=True)
    )
    fixed = current_rows(results)
    assert fixed.run.result == "pass"
    assert all(row.result == "pass" for row in fixed.run.computed_results)
    monkeypatch.setattr(
        upstream, "initial_configuration", lambda selected: deepcopy(results.config)
    )
    monkeypatch.setattr(upstream, "LocalPrivateObjectStore", lambda _path: results.report_store)
    factory = upstream.publication_case.__wrapped__(results.setup, tmp_path)
    work = next(factory)
    work.results, work.test_run = results, fixed.run
    work.objects_root = tmp_path / "result-originals"
    try:
        yield work
    finally:
        factory.close()


def test_at47_backup_restore_replay_keeps_chain_and_sends_nothing_twice(
    drill_case, monkeypatch, tmp_path
):
    assert os.environ.get("PDOS_EXTERNAL_HANDOFF_LINK") == "1", "Explicit isolated opt-in"
    evidence_dir = Path(os.environ["PDOS_RESTORE_DRILL_EVIDENCE"])
    assert evidence_dir.is_absolute()
    work, setup = drill_case, drill_case.setup
    test_run = {"id": str(work.test_run.id), "revision": work.test_run.revision}
    workflows_state = json.loads((ROOT / ".local/workflows.json").read_text())
    source_temporal = f"127.0.0.1:{workflows_state['server_port']}"
    evidence = {
        "version": "pdos-at47-drill/v1",
        "scenario": "AT-47 备份恢复重放：配置到交接链可核对，不重复外发",
        "environment": "local marked synthetic environment; native Temporal dev server (SQLite)",
        "steps": {},
    }

    # 1. The real chain up to the named decisions (same commands as the UI handoff test).
    upstream.import_authority(work, setup.human)
    upstream.save_drafts(work)
    command, _ = upstream.prepare_publication(work, upstream.publication_payload(work))
    response = post(setup, command)
    assert response.status_code == 200, response.text
    publication = upstream.publication(work, response.json())
    publication_ref = {"id": publication["id"], "revision": publication["revision"]}
    with upstream.session(work) as session:
        engineering = session.get(
            EngineeringConfiguration, UUID(work.config["engineering"]["subject_id"])
        )
        configuration = {
            "definition": {
                "id": str(engineering.definition_id),
                "revision": engineering.definition_revision,
            },
            "engineering_configuration": {
                "id": str(engineering.id),
                "revision": engineering.revision,
            },
            "manufacturing_configuration": work.process_ref,
        }
    release_scope = {
        "quantity": None,
        "unit": None,
        "lots": [],
        "site": "SYN-INTERNAL-LAB",
        "lines": [],
        "regions": ["CN", "DE"],
    }
    document = {"kind": "artifact", "id": work.document_source, "revision": 1}
    flow.authorize(
        work, setup.human, "engineering", ["release.policy.import", "release.engineering.approve"]
    )
    flow.authorize(work, setup.peer, "manufacturing", ["release.manufacturing.approve"])
    harness.prepare_authority(work)
    policy = release_ui._policy(
        work,
        configuration,
        release_scope,
        document,
        {"kind": "manufacturing_publication", **publication_ref},
    )
    _, policy_source = release_ui._import_policy(
        work, ActualReleasePolicyOwner(setup.engine), policy
    )
    command, material = flow.inputs(
        work,
        "release.package.assemble",
        {
            "project_id": str(work.project_id),
            "subject_config": configuration,
            "release_scope": release_scope,
            "purpose": work.purpose,
            "manufacturing_publication": publication_ref,
            "verifications": [test_run],
            "documents": [document],
            "sources": [flow.source(work.document_source, upstream.LINES[0])],
            "visibility": "category",
            "reason": "AT-47 drill: fixed synthetic documentation packet",
        },
    )
    response = flow.send(work, command)
    assert response.status_code == 200, response.text
    package = flow.fixed(work, response.json()["subject_id"])
    # The package fixes the actual test run, not a copy of its conclusion.
    assert test_run["id"] in json.dumps(package), "test run missing from the fixed package"
    evidence["steps"]["chain"] = {
        "links": ["configuration", "test_result", "publication", "decisions", "handoff"],
        "test_run": {
            **test_run,
            "status": work.test_run.status,
            "result": work.test_run.result,
            "import_receipt": work.results.result_receipt["id"],
        },
    }
    decisions = []
    for discipline, actor in (("engineering", setup.human), ("manufacturing", setup.peer)):
        command, material = flow.inputs(
            work,
            f"release.{discipline}.approve",
            {
                "package": {"id": package["id"], "revision": package["revision"]},
                "release_scope": release_scope,
                "purpose": work.purpose,
                "expiry": None,
                "sources": [policy_source],
                "reason": "AT-47 drill: named synthetic decision",
            },
            actor,
        )
        preview = flow.send(work, command, actor=actor, preview=True)
        assert preview.status_code == 200, preview.text
        response = flow.send(work, preview.json()["command"], actor=actor)
        assert response.status_code == 200, response.text
        decisions.append(response.json()["subject_id"])

    # Long-waiting workflows in flight at the backup moment.
    maintenance_runs = _start_maintenance(source_temporal, setup.tenant)
    evidence["steps"]["in_flight_workflows_before_backup"] = maintenance_runs

    # 2. Back up when the first send result is recorded as unknown.
    sent_commands, at_backup = [], {}
    original_send, original_reading = harness._send, harness._reading

    def recording_send(selected, command, *, preview=False):
        response = original_send(selected, command, preview=preview)
        if not preview and response.status_code == 200:
            sent_commands.append((deepcopy(command), response.json()))
        return response

    def backup_on_unknown(selected, identity):
        actual = original_reading(selected, identity)
        if actual["as_of"]["receipt_count"] == 1 and not at_backup:
            assert actual["reading"]["delivery_unknown"] is True
            at_backup["reads"] = _reads(
                work, setup.client, package["id"], publication_ref, identity
            )
            at_backup["counts"] = _counts(setup.admin, setup.tenant, harness.MODELS)
            started = time.monotonic()
            at_backup["directory"] = backup_restore.backup(objects=work.objects_root)
            at_backup["seconds"] = round(time.monotonic() - started, 2)
            at_backup["commands"] = list(sent_commands)
        return actual

    monkeypatch.setattr(harness, "_send", recording_send)
    monkeypatch.setattr(harness, "_reading", backup_on_unknown)
    summary = harness.run(work, package, decisions)
    monkeypatch.setattr(harness, "_send", original_send)
    monkeypatch.setattr(harness, "_reading", original_reading)
    backup_dir = at_backup["directory"]
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    authorization_command, authorization_receipt = at_backup["commands"][0]
    unknown_command, unknown_receipt = at_backup["commands"][1]
    assert authorization_receipt["subject_id"] == summary["handoff_id"]
    evidence["steps"]["backup"] = {
        "taken_at_phase": "sent_outcome_unknown (receipt_count=1)",
        "seconds": at_backup["seconds"],
        "bytes": sum(path.stat().st_size for path in backup_dir.iterdir()),
        "databases": {
            name: {
                "tables": len(db["tables"]),
                "rows": sum(t["rows"] for t in db["tables"].values()),
            }
            for name, db in manifest["databases"].items()
        },
        "alembic_version": manifest["databases"]["business"]["alembic_version"],
        "objects": len(manifest["objects"]["files"]),
        "temporal_history_file": manifest.get("temporal_sqlite"),
        "kms": manifest["kms"],
    }

    # 3. The source continues: five more receipts were recorded, and event delivery
    #    now starts the original's security workflow on the source Temporal.
    source_final = _reads(work, setup.client, package["id"], publication_ref, summary["handoff_id"])
    assert source_final["handoff"]["as_of"]["receipt_count"] == len(summary["receipts"]) == 6
    source_delivery = _dispatch_all(setup.dispatch, setup.tenant, source_temporal)
    security_ids = sorted(
        {
            row["workflow_id"]
            for row in source_delivery["workflows"]
            if "security" in row["workflow_id"]
        }
    )
    assert security_ids, source_delivery
    source_runs = {identity: _workflow_runs(source_temporal, identity) for identity in security_ids}
    assert all(len(runs) == 1 for runs in source_runs.values())
    evidence["steps"]["source_after_backup"] = {
        "receipts_recorded_after_backup": len(summary["receipts"]) - 1,
        "events_delivered": source_delivery["delivered"],
        "workflows_started": source_delivery["workflows"],
    }

    # 4a. Restore into a new marked environment; every table and the original match.
    started = time.monotonic()
    restored_dir = backup_restore.restore(backup_dir)
    restore_seconds = round(time.monotonic() - started, 2)
    restored_b = None
    temporal_process = None
    try:
        report = json.loads((restored_dir / "verify.json").read_text())
        assert set(report["summary"].values()) == {"match"}, report["summary"]
        restored = _restored_engines(restored_dir, monkeypatch)
        store = LocalPrivateObjectStore(restored_dir / "objects")
        client = TestClient(
            create_app(
                restored.app,
                restored.auth,
                object_store=store,
                security_runtime=synthetic_runtime(),
            )
        )
        with tenant_session(
            restored.app,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            original = session.get(UploadedOriginal, work.original_id)
            restored_bytes = store.read_original(object_reference(original))
        assert restored_bytes == ("\n".join(upstream.LINES) + "\n").encode("utf-8")

        # 4b. The chain reads exactly as at the backup moment, not as the source does now.
        restored_work = SimpleNamespace(**{**vars(work), "setup": SimpleNamespace(**vars(setup))})
        restored_work.setup.client = client
        # Without the host's issuer configuration (process config, not data) every
        # currentness answer degrades to needs_recheck, and a professional authority
        # (the test result page's disposition authority) reads "issuer unavailable"
        # with no facts; nothing else differs.
        unconfigured = _reads(
            restored_work, client, package["id"], publication_ref, summary["handoff_id"]
        )
        degraded = {
            name: _differences(at_backup["reads"][name], unconfigured[name])
            for name in unconfigured
        }
        degraded_fields = sorted(
            {row["path"].rsplit(".", 1)[-1] for rows in degraded.values() for row in rows}
        )
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "at47-unconfigured-differences.json").write_text(
            json.dumps(degraded, ensure_ascii=False, indent=2, default=str) + "\n"
        )
        authority = [
            row for rows in degraded.values() for row in rows if ".authority." in row["path"]
        ]
        # A run's read set includes its authority's sources: unconfigured, it only
        # loses those entries and never gains or changes one.
        read_sets = [
            row
            for rows in degraded.values()
            for row in rows
            if ".authority." not in row["path"]
            and row["path"].endswith(".required_source_read_set")
        ]
        currentness = [
            row
            for rows in degraded.values()
            for row in rows
            if row not in authority and row not in read_sets
        ]
        assert all(
            row["path"].startswith(".runs[")
            and isinstance(row["restored"], list)
            and all(item in row["backup"] for item in row["restored"])
            and len(row["restored"]) < len(row["backup"])
            for row in read_sets
        ), read_sets
        assert {row["path"].rsplit(".", 1)[-1] for row in currentness} <= {
            "applicability",
            "source_status",
        }, degraded
        assert all(
            row["backup"] == "current" and row["restored"] == "needs_recheck" for row in currentness
        ), degraded
        assert all(row["path"].startswith(".runs[") for row in authority), authority
        # Issuer and synthetic-authority policy are host configuration: unconfigured,
        # each authority keeps its own reasons, adds only these two, holds no facts or
        # source reads, and its basis digest (over that state) changes accordingly.
        host_reasons = {"TRUSTED_ISSUER_UNAVAILABLE", "SYNTHETIC_AUTHORITY_NOT_ALLOWED"}
        unavailable = {
            "reason_codes": lambda before, after: (
                "TRUSTED_ISSUER_UNAVAILABLE" in after
                and set(before) <= set(after)
                and set(after) - set(before) <= host_reasons
            ),
            "fact_refs": lambda before, after: after == [],
            "required_source_read_set": lambda before, after: after == [],
            "facts_revision": lambda before, after: isinstance(after, str) and after != before,
            "authorized": lambda before, after: after is False,
            "qualified": lambda before, after: after in (None, False),
            "valid_until": lambda before, after: after is None,
        }
        assert all(
            unavailable[row["path"].rsplit(".", 1)[-1]](row["backup"], row["restored"])
            for row in authority
        ), authority
        # A redeploy brings the same issuer configuration back; then the chain reads
        # exactly as at the backup moment, not as the source does now.
        host_configuration = sorted(
            key
            for key in vars(setup.engine)
            if key.startswith("_pdos_")
            and any(word in key for word in ("issuer", "synthetic", "epoch"))
        )
        for key in host_configuration:
            setattr(restored.app, key, getattr(setup.engine, key))
        restored_reads = _reads(
            restored_work, client, package["id"], publication_ref, summary["handoff_id"]
        )
        differences = {
            name: _differences(at_backup["reads"][name], restored_reads[name])
            for name in restored_reads
        }
        assert all(not paths for paths in differences.values()), differences
        # The test result page reads as at the backup moment, with the same run.
        assert test_run["id"] in json.dumps(restored_reads["test_results"])
        assert restored_reads["test_results"] == at_backup["reads"]["test_results"]
        handoff = restored_reads["handoff"]
        assert handoff["as_of"]["receipt_count"] == 1
        assert handoff["reading"]["delivery_unknown"] is True
        assert handoff["reading"]["sent"]["state"] != "succeeded"
        assert handoff["network_send"] is False and handoff["reading"]["network_send"] is False
        lost = len(source_final["handoff_receipts"]["items"]) - len(
            restored_reads["handoff_receipts"]["items"]
        )
        evidence["steps"]["restore"] = {
            "seconds": restore_seconds,
            "verify": report["summary"],
            "original_bytes_match": True,
            "chain_reads_equal_backup_moment": sorted(restored_reads),
            "without_host_issuer_configuration": {
                "degraded_fields": degraded_fields,
                "authority_reads_issuer_unavailable": sorted({row["path"] for row in authority}),
                "run_read_sets_without_authority_sources": sorted(
                    {row["path"] for row in read_sets}
                ),
                "degraded_reads": {
                    name: [row["path"] for row in rows] for name, rows in degraded.items() if rows
                },
                "value_change": "current -> needs_recheck",
            },
            "host_configuration_reapplied": host_configuration,
            "handoff_at_restore": {
                "receipt_count": handoff["as_of"]["receipt_count"],
                "delivery_unknown": handoff["reading"]["delivery_unknown"],
                "status": handoff["reading"]["status"],
                "network_send": handoff["network_send"],
            },
            "receipts_after_backup_not_in_restore": lost,
        }

        # 4c. Replaying the original commands returns the original receipts, writes nothing.
        before = _counts(restored.admin, setup.tenant, harness.MODELS)
        assert before == at_backup["counts"]
        for command, receipt in (
            (authorization_command, authorization_receipt),
            (unknown_command, unknown_receipt),
        ):
            replay = client.post(
                f"/v1/categories/{setup.category}/commands", headers=setup.headers, json=command
            )
            assert replay.status_code == 200 and replay.json() == receipt, replay.text
        after = _counts(restored.admin, setup.tenant, harness.MODELS)
        assert after == before
        from pdos_next.domain.manufacturing.external_handoff.models import (
            ExternalDeliveryIntent,
            ExternalHandoffAuthorization,
        )

        with Session(restored.admin) as session:
            intents = list(
                session.scalars(
                    select(ExternalDeliveryIntent).where(
                        ExternalDeliveryIntent.tenant_id == setup.tenant
                    )
                )
            )
            authorizations = list(
                session.scalars(
                    select(ExternalHandoffAuthorization).where(
                        ExternalHandoffAuthorization.tenant_id == setup.tenant
                    )
                )
            )
        assert len(intents) == len(authorizations) == 1
        assert all(row.network_send is False for row in (*intents, *authorizations))
        evidence["steps"]["command_replay"] = {
            "replayed": ["external handoff authorization (T2)", "first receipt (sent: unknown)"],
            "same_receipts_returned": True,
            "row_counts_unchanged": after,
            "delivery_intents": len(intents),
            "network_send": False,
        }

        # 4d. Outbound audit before any worker starts on the restored database.
        audit = backup_restore.audit_outbound(restored_dir)
        unknown_handoffs = _unknown_handoffs(restored.admin, setup.tenant)
        assert unknown_handoffs == 1 and audit["external_handoff_currents"]["count"] >= 1
        pending = _pending_events(restored.admin, setup.tenant)
        assert pending > 0 and audit["outbox_events"]["count"] >= pending
        evidence["steps"]["outbound_audit"] = {
            "drill_tenant_pending_events": pending,
            "drill_tenant_unknown_handoff_sends": unknown_handoffs,
            "all_tenants": {
                table: {k: v for k, v in row.items() if k != "ids"} for table, row in audit.items()
            },
        }

        # 4e. Case A — Temporal restored to the same point: in-flight workflows are there,
        #     replay against this checkout, and each event starts its workflow once.
        temporal_process, restored_temporal = _serve_restored_temporal(restored_dir)
        restored_maintenance = {
            identity: _workflow_runs(restored_temporal, identity) for identity in maintenance_runs
        }
        assert restored_maintenance == {k: [v] for k, v in maintenance_runs.items()}

        async def replay_restored():
            from temporalio.client import Client

            client = await Client.connect(restored_temporal, namespace="pdos-next")
            directory = tmp_path / "restored-histories"
            await workflow_replay_check.export(
                client, directory, workflow_replay_check.DEFAULT_QUERY, 100
            )
            return await workflow_replay_check.replay(directory)

        replayed = asyncio.run(replay_restored())
        assert replayed["passed"] and replayed["histories"] >= 2, replayed
        for identity in security_ids:
            assert _workflow_runs(restored_temporal, identity) == []
        first = _dispatch_all(restored.dispatch, setup.tenant, restored_temporal)
        second = _dispatch_all(restored.dispatch, setup.tenant, restored_temporal)
        assert first["delivered"] == pending and first["unknown"] == 0
        assert second["delivered"] == 0 and second["workflows"] == []
        case_a = {
            identity: _workflow_runs(restored_temporal, identity) for identity in security_ids
        }
        assert all(len(runs) == 1 for runs in case_a.values()), case_a
        evidence["steps"]["case_a_temporal_restored_too"] = {
            "in_flight_workflows_present": {k: len(v) for k, v in restored_maintenance.items()},
            "replay_check": replayed,
            "first_delivery": {k: first[k] for k in ("delivered", "unknown")},
            "second_delivery": {k: second[k] for k in ("delivered", "unknown")},
            "runs_per_workflow_id": {k: len(v) for k, v in case_a.items()},
        }

        # 4f. Case B — only the database goes back; Temporal already ran those workflows.
        restored_b = backup_restore.restore(backup_dir)
        engines_b = _restored_engines(restored_b, monkeypatch)
        before_b = {
            identity: _workflow_runs(source_temporal, identity) for identity in security_ids
        }
        delivery_b = _dispatch_all(engines_b.dispatch, setup.tenant, source_temporal)
        after_b = {identity: _workflow_runs(source_temporal, identity) for identity in security_ids}
        assert delivery_b["delivered"] == pending
        assert before_b == after_b == source_runs, (before_b, after_b)
        evidence["steps"]["case_b_database_only"] = {
            "events_redelivered": delivery_b["delivered"],
            "workflow_ids_reused": sorted({row["workflow_id"] for row in delivery_b["workflows"]}),
            "runs_per_workflow_id_before": {k: len(v) for k, v in before_b.items()},
            "runs_per_workflow_id_after": {k: len(v) for k, v in after_b.items()},
        }
        for engine in (engines_b.admin, engines_b.app, engines_b.auth, engines_b.dispatch):
            engine.dispose()
        for engine in (restored.admin, restored.app, restored.auth, restored.dispatch):
            engine.dispose()
        client.close()
    finally:
        if temporal_process is not None:
            temporal_process.terminate()
            temporal_process.wait(timeout=20)
        for directory in (restored_dir, restored_b):
            if directory is not None and directory.exists():
                backup_restore.destroy(directory)
        # The dumps hold only this synthetic tenant's data; the manifest goes to evidence.
        shutil.rmtree(backup_dir)
    evidence["result"] = "passed"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "at47-drill.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    manifest_copy = {k: v for k, v in manifest.items() if k not in {"roles"}}
    (evidence_dir / "at47-backup-manifest.json").write_text(
        json.dumps(manifest_copy, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
