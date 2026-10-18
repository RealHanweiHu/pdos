"""Finite browser work loop over existing real synthetic logins and sources.

The root performs every command through the UI. This helper never creates or
previews a command, renews a login/Grant, changes a clock or edits a business row.
"""

import os
import socket
import stat
import threading
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import UUID

import uvicorn
from pydantic_core import to_jsonable_python
from release_policy_browser_seed.harness import _write_private_new
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.projects.models import Project
from pdos_next.domain.work_management import service
from pdos_next.domain.work_management.constants import (
    COMMIT,
    CREATE,
    OPERATIONS,
    STATUS,
)
from pdos_next.domain.work_management.models import (
    ProjectStatusUpdate,
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
)
from pdos_next.domain.work_management.schemas import PAYLOADS, TaskSnapshot
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    Grant,
    LoginSession,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
    now,
)
from pdos_next.safety import verify_test_target
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context, digest, material_digest

_HEAD = "s0_0785"
_MAXIMUM_WAIT_SECONDS = 1200
_MODELS = (
    WorkTaskVersion,
    WorkTaskCurrent,
    WorkCommitmentVersion,
    WorkCommitmentCurrent,
    ProjectStatusUpdate,
)


def _environment(setup):
    if os.environ.get("PDOS_PROJECT_WORK_BROWSER_SEED") != "1":
        raise RuntimeError("Project work browser checkpoint requires explicit local opt-in")
    directory = Path(os.environ["PDOS_PROJECT_WORK_BROWSER_DIR"])
    if (
        not directory.is_absolute()
        or directory.resolve() != directory
        or ".local" not in directory.parts
        or directory.is_symlink()
    ):
        raise RuntimeError("Use a fresh absolute private directory under .local")
    directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    state = directory.stat()
    if (
        not directory.is_dir()
        or stat.S_IMODE(state.st_mode) != 0o700
        or state.st_uid != os.getuid()
        or any(directory.iterdir())
    ):
        raise RuntimeError("Browser seed directory must be fresh, owned and mode 0700")
    port = int(os.environ["PDOS_PROJECT_WORK_BROWSER_PORT"])
    database_port = int(os.environ["TEST_DATABASE_PORT"])
    if (
        not 1024 <= port <= 65535
        or port == database_port
        or not os.environ.get("TEST_DATABASE_MARKER")
    ):
        raise RuntimeError("Use an explicit independent marker and separate loopback API port")
    for name in ("TEST_DATABASE_URL", "DATABASE_URL", "AUTH_DATABASE_URL", "DISPATCH_DATABASE_URL"):
        target = make_url(os.environ[name])
        if (
            target.drivername != "postgresql+psycopg"
            or target.host not in {"127.0.0.1", "localhost"}
            or target.port != database_port
            or target.database != "pdos_test"
            or target.query
        ):
            raise RuntimeError("All engines must use the explicit independent pdos_test")
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    with setup.admin.connect() as connection:
        if (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            != _HEAD
        ):
            raise RuntimeError("Project work browser seed requires actual reviewed s0_0785 head")
    return directory, port


def _rows(s, model, work):
    setup = work.setup
    return list(
        s.scalars(
            select(model).where(
                model.tenant_id == setup.tenant,
                model.category_id == setup.category,
                model.product_id == setup.product,
                model.project_id == work.project_id,
            )
        )
    )


def _snapshot(rows):
    return {
        str(row.id): to_jsonable_python(
            {column.key: deepcopy(getattr(row, column.key)) for column in row.__table__.columns}
        )
        for row in rows
    }


def _participants(work, captured):
    setup, actors = work.setup, {}
    with Session(setup.admin) as s:
        product = s.get(Product, setup.product)
        project = s.get(Project, work.project_id)
        assert product is not None and (product.tenant_id, product.category_id) == (
            setup.tenant,
            setup.category,
        )
        assert project is not None and (
            project.tenant_id,
            project.product_id,
            project.owner_id,
            project.visibility,
        ) == (setup.tenant, setup.product, setup.human, "category")
        for name, identity in (("human", setup.human), ("peer", setup.peer)):
            token = setup.tokens[identity]
            login, person = s.get(LoginSession, digest(token)), s.get(Principal, identity)
            grant = s.scalar(
                select(Grant).where(
                    Grant.tenant_id == setup.tenant,
                    Grant.category_id == setup.category,
                    Grant.principal_id == identity,
                )
            )
            assert login is not None and not login.revoked and captured < login.expires_at
            assert (login.tenant_id, login.principal_id) == (setup.tenant, identity)
            assert person is not None and person.active and person.kind == "human"
            assert grant is not None and grant.can_write
            assert grant.expires_at is None or captured < grant.expires_at
            deadlines = [login.expires_at] + ([grant.expires_at] if grant.expires_at else [])
            actors[name] = {
                "principal_id": str(identity),
                "bearer": token,
                "login_expires_at": login.expires_at.isoformat(),
                "grant_id": str(grant.id),
                "grant_epoch": grant.access_epoch,
                "grant_expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
                "effective_until": min(deadlines).isoformat(),
            }
        return (
            product.revision,
            {
                "id": str(project.id),
                "revision": project.revision,
                "name": project.name,
                "owner_id": str(project.owner_id),
                "visibility": project.visibility,
            },
            actors,
        )


def _before(work):
    with Session(work.setup.admin) as s:
        before = {model.__tablename__: _snapshot(_rows(s, model, work)) for model in _MODELS}
        assert [len(before[model.__tablename__]) for model in _MODELS] == [8, 1, 2, 2, 1]
        source = s.get(Artifact, UUID(work.source["id"]))
        assert source is not None and source.status == "active"
        assert (source.tenant_id, source.category_id, source.product_id) == (
            work.setup.tenant,
            work.setup.category,
            work.setup.product,
        )
        return before, _snapshot([source])


def _common_atom(work, row_id, model, operation, actor):
    setup = work.setup
    ctx = Context(setup.tenant, actor, actor, category_id=setup.category)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=actor, requester_id=actor, category_id=setup.category
    ) as s:
        row = s.get(model, row_id)
        receipt = s.get(Receipt, row.receipt_id)
        assert row.actor_id == row.writer_id == row.requester_id == actor
        assert row.operation == receipt.operation == operation
        assert receipt.command_id == row.command_id
        assert receipt.subject_id == row.id and receipt.subject_revision == row.revision
        assert receipt.subject_type == (
            "work_commitment"
            if model is WorkCommitmentVersion
            else "project_status_update"
            if model is ProjectStatusUpdate
            else "work_task"
        )
        assert receipt.actor_id == receipt.requester_id == actor
        assert receipt.run_id is receipt.agent_run_id is None
        assert (
            receipt.request_digest == row.request_digest
            and receipt.intent_digest == row.intent_digest
        )
        assert row.body_sha256 == digest(row.body)
        key = None
        for actual in (Audit, Outbox, RequestKey):
            entries = list(s.scalars(select(actual).where(actual.receipt_id == receipt.id)))
            assert len(entries) == 1 and entries[0].actor_id == actor
            entry = entries[0]
            if actual is Audit:
                assert entry.operation == operation
            elif actual is Outbox:
                assert (
                    entry.type,
                    entry.subject_id,
                    entry.subject_revision,
                    entry.correlation_id,
                ) == (OPERATIONS[operation][1], row.id, row.revision, row.command_id)
            else:
                key = entry
                assert entry.digest == row.request_digest
                assert digest(entry.key) == row.command["original_key_sha256"]
        assert "idempotency_key" not in row.command["envelope"]
        assert "confirmation_token" not in row.command["envelope"]["payload"]
        assert SourceRef.model_validate(work.source) in tuple(
            SourceRef.model_validate(value) for value in row.sources
        )
        if operation == CREATE:
            assert row.confirmation_id is receipt.confirmation_id is None
        else:
            proof = s.get(Confirmation, row.confirmation_id)
            assert proof is not None and proof.consumed is True
            assert (
                proof.id == receipt.confirmation_id
                and proof.operation == operation
                and proof.actor_id == actor
            )
            assert proof.created_at <= row.created_at <= receipt.created_at < proof.expires_at
            assert proof.snapshot == row.command["review"]
            command = Command.model_validate(
                {**row.command["envelope"], "idempotency_key": key.key}
            )
            payload = PAYLOADS[operation].model_validate(command.payload)
            assert proof.payload_digest == material_digest(ctx, command, payload, service)


def _after(work, before, source_before):
    setup = work.setup
    with Session(setup.admin) as s:
        rows = {model: _rows(s, model, work) for model in _MODELS}
        new = {}
        for model in _MODELS:
            old = before[model.__tablename__]
            actual = _snapshot(rows[model])
            assert {key: actual[key] for key in old} == old
            new[model] = [row for row in rows[model] if str(row.id) not in old]
        assert [len(new[model]) for model in _MODELS] == [8, 1, 2, 2, 1]
        assert _snapshot([s.get(Artifact, UUID(work.source["id"]))]) == source_before
        tasks = sorted(new[WorkTaskVersion], key=lambda row: row.revision)
        task_id = tasks[0].task_id
        assert all(row.task_id == task_id and row.owner_id == setup.human for row in tasks)
        assert [row.revision for row in tasks] == list(range(1, 9))
        assert [row.action for row in tasks] == [
            "create",
            "assign",
            "accept",
            "start",
            "submit",
            "review",
            "submit",
            "review",
        ]
        assert [row.state for row in tasks] == [
            "proposed",
            "assigned",
            "accepted",
            "in_progress",
            "submitted",
            "in_progress",
            "submitted",
            "completed",
        ]
        assert [row.actor_id for row in tasks] == [
            setup.human,
            setup.human,
            setup.peer,
            setup.peer,
            setup.peer,
            setup.human,
            setup.peer,
            setup.human,
        ]
        plans = [TaskSnapshot.model_validate(row.body) for row in tasks]
        assert plans[1].assignee_id == setup.peer and plans[1].recipient_id == setup.human
        required = {value.key for value in plans[0].outcomes if value.required}
        assert required
        first_present = {
            value.key for value in plans[4].submission.results if value.status == "present"
        }
        assert not required <= first_present
        assert plans[5].review.decision == "returned"
        assert plans[5].submission == plans[4].submission
        assert plans[7].review.decision == "accepted"
        assert required <= {
            value.key for value in plans[7].submission.results if value.status == "present"
        }
        assert all(plan.actual_start == plans[3].actual_start for plan in plans[3:])
        pointer = new[WorkTaskCurrent][0]
        assert (pointer.task_id, pointer.version_id, pointer.revision, pointer.state) == (
            task_id,
            tasks[-1].id,
            8,
            "completed",
        )
        commitments = new[WorkCommitmentVersion]
        assert {row.recipient_id for row in commitments} == {setup.human, setup.peer}
        assert all(
            row.task_id == task_id
            and row.task_revision == 3
            and row.promisor_id == setup.peer
            and row.revision == 1
            and row.replaces_id is None
            for row in commitments
        )
        assert {row.version_id for row in new[WorkCommitmentCurrent]} == {
            row.id for row in commitments
        }
        update = new[ProjectStatusUpdate][0]
        assert update.actor_id == setup.human and update.task_refs == [
            {"id": str(task_id), "revision": 8}
        ]
        atoms = [(row.id, WorkTaskVersion, row.operation, row.actor_id) for row in tasks]
        atoms.extend((row.id, WorkCommitmentVersion, COMMIT, setup.peer) for row in commitments)
        atoms.append((update.id, ProjectStatusUpdate, STATUS, setup.human))
        result = {
            "task": {"id": str(task_id), "revision": 8},
            "task_fact_count": 8,
            "commitments": [
                {"id": str(row.id), "revision": row.revision, "recipient_id": str(row.recipient_id)}
                for row in commitments
            ],
            "status_update": {"id": str(update.id), "revision": 1},
            "original_rows_unchanged": True,
            "source_unchanged": True,
        }
    for atom in atoms:
        _common_atom(work, *atom)
    return result


def _finished(path):
    if not path.exists():
        return False
    state = path.lstat()
    assert stat.S_ISREG(state.st_mode) and state.st_uid == os.getuid(), (
        "Use an owned regular finish file"
    )
    return True


def run_browser_seed(work):
    """Serve the actual app, await explicit UI work, then read its saved atoms."""
    setup = work.setup
    directory, port = _environment(setup)
    captured = now()
    before, source_before = _before(work)
    revision, project, actors = _participants(work, captured)
    effective_until = min(
        datetime.fromisoformat(value["effective_until"]) for value in actors.values()
    )
    wait_seconds = min(_MAXIMUM_WAIT_SECONDS, (effective_until - captured).total_seconds())
    assert wait_seconds > 0, "Existing browser credentials have already expired"
    sock, server, thread = None, None, None
    errors = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
        server = uvicorn.Server(
            uvicorn.Config(
                setup.client.app, host="127.0.0.1", port=port, log_level="warning", access_log=False
            )
        )

        def serve():
            try:
                server.run(sockets=[sock])
            except BaseException as error:
                errors.append(type(error).__name__)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        started_by = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < started_by:
            time.sleep(0.1)
        assert server.started and not errors, "Own actual project work API startup failed"
        _write_private_new(
            directory / "seed.json",
            {
                "schema_version": "pdos-project-work-browser-seed-v1",
                "synthetic": True,
                "created_at": captured.isoformat(),
                "database_head": _HEAD,
                "api_host": "127.0.0.1",
                "api_port": port,
                "tenant_id": str(setup.tenant),
                "category_id": str(setup.category),
                "product_id": str(setup.product),
                "product_revision": revision,
                "project_id": str(work.project_id),
                "project": project,
                "actors": actors,
                "effective_until": effective_until.isoformat(),
                "sources": [SourceRef.model_validate(work.source).model_dump(mode="json")],
                "plan_task": None,
                "outcome_keys": ["drawing", "inspection"],
                "original_timezone": "Asia/Shanghai",
                "calendar_id": None,
                "finish_file": str(directory / "finish"),
                "maximum_wait_seconds": wait_seconds,
                "boundary": (
                    "Only existing human/peer logins and actual source references. Root UI "
                    "creates one new task, two separate recipient commitments, partial "
                    "submission and owner return, complete submission and owner acceptance, "
                    "and one named status update. No automatic command, permission renewal, "
                    "model call or external action."
                ),
            },
        )
        print("Actual synthetic project work browser scope ready; API port", port, flush=True)
        deadline = time.monotonic() + min(wait_seconds, (effective_until - now()).total_seconds())
        while not _finished(directory / "finish") and time.monotonic() < deadline:
            assert thread.is_alive() and not errors, "Own actual API stopped before browser finish"
            time.sleep(0.2)
        assert _finished(directory / "finish"), "Finite browser checkpoint elapsed without finish"
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(10)
            if thread.is_alive():
                server.force_exit = True
                thread.join(5)
        if sock is not None:
            sock.close()
        (directory / "seed.json").unlink(missing_ok=True)
        assert thread is None or not thread.is_alive(), "Own actual API did not stop"
    result = _after(work, before, source_before)
    _write_private_new(directory / "result.json", result)
    return result
