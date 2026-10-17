"""Finite read-only browser handoff over already-persisted synthetic facts.

No command, new login, qualification, approval, receipt or clock extension is
performed here. A method filter keeps this fixture server read-only while the
root browser inspects the actual app's existing handoff and receipt history.
"""

import json
import os
import socket
import stat
import threading
import time
from pathlib import Path
from uuid import UUID

import uvicorn
from manufacturing_preparation import publication_pg_helpers as upstream
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from pdos_next.domain.external_handoff.models import (
    ExternalDeliveryIntent,
    ExternalHandoffAuthorization,
    ExternalHandoffCurrent,
    ExternalReceipt,
)
from pdos_next.models import Grant, LoginSession, Principal, Product, now
from pdos_next.safety import verify_test_target
from pdos_next.service import digest

_MODELS = (
    ExternalHandoffAuthorization,
    ExternalDeliveryIntent,
    ExternalHandoffCurrent,
    ExternalReceipt,
)
_MAXIMUM_WAIT_SECONDS = 1200


class _ReadOnlyApp:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            response = JSONResponse(
                {
                    "reason": "READ_ONLY_FIXTURE",
                    "detail": "This finite browser fixture only reads existing facts.",
                },
                status_code=403,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _environment(setup):
    if os.environ.get("PDOS_EXTERNAL_HANDOFF_BROWSER_SEED") != "1":
        raise RuntimeError("Read-only handoff browser seed requires explicit opt-in")
    directory = Path(os.environ["PDOS_EXTERNAL_HANDOFF_BROWSER_DIR"])
    if (
        not directory.is_absolute()
        or directory.resolve() != directory
        or ".local" not in directory.parts
        or directory.is_symlink()
    ):
        raise RuntimeError("Use a fresh absolute private directory under .local")
    directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    state = directory.stat()
    if not directory.is_dir() or stat.S_IMODE(state.st_mode) & 0o077 or state.st_uid != os.getuid():
        raise RuntimeError("Browser seed directory must belong only to its local owner")
    if any(
        (directory / name).exists() or (directory / name).is_symlink()
        for name in ("seed.json", "finish")
    ):
        raise RuntimeError("Use a new directory without seed.json or finish")
    port = int(os.environ["PDOS_EXTERNAL_HANDOFF_BROWSER_PORT"])
    database_port = int(os.environ["TEST_DATABASE_PORT"])
    if (
        not 1024 <= port <= 65535
        or port == database_port
        or not os.environ.get("TEST_DATABASE_MARKER")
    ):
        raise RuntimeError(
            "Explicit independent marker and a separate unused loopback port are required"
        )
    for name in ("TEST_DATABASE_URL", "DATABASE_URL", "AUTH_DATABASE_URL", "DISPATCH_DATABASE_URL"):
        target = make_url(os.environ[name])
        if (
            target.drivername != "postgresql+psycopg"
            or target.host not in {"127.0.0.1", "localhost"}
            or target.port != database_port
            or target.database != "pdos_test"
            or target.query
        ):
            raise RuntimeError("All engines must target the explicit independent pdos_test")
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    with setup.admin.connect() as connection:
        if (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            != "s0_0783"
        ):
            raise RuntimeError("Read-only browser seed requires actual reviewed head s0_0783")
    return directory, port


def _write_private_new(path, value):
    content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            assert stat.S_IMODE(os.fstat(output.fileno()).st_mode) == 0o600
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _existing_read_scope(work, handoff_id):
    setup, captured = work.setup, now()
    token = setup.tokens[setup.human]
    with Session(setup.admin) as s:
        product = s.get(Product, setup.product)
        handoff = s.get(ExternalHandoffAuthorization, UUID(str(handoff_id)))
        login = s.get(LoginSession, digest(token))
        person = s.get(Principal, setup.human)
        grant = s.scalar(
            select(Grant).where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.human,
            )
        )
        assert product is not None and (product.tenant_id, product.category_id) == (
            setup.tenant,
            setup.category,
        )
        assert handoff is not None and (
            handoff.tenant_id,
            handoff.category_id,
            handoff.product_id,
            handoff.project_id,
        ) == (setup.tenant, setup.category, setup.product, work.project_id)
        assert login is not None and not login.revoked and login.expires_at > captured
        assert (login.tenant_id, login.principal_id) == (setup.tenant, setup.human)
        assert person is not None and person.active and person.kind == "human"
        assert grant is not None and (grant.expires_at is None or captured < grant.expires_at)
        deadlines = [login.expires_at]
        if grant.expires_at is not None:
            deadlines.append(grant.expires_at)
        return {
            "schema_version": "pdos-external-handoff-readonly-browser-seed-v1",
            "synthetic": True,
            "read_only": True,
            "created_at": captured.isoformat(),
            "tenant_id": str(setup.tenant),
            "principal_id": str(setup.human),
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "product_revision": product.revision,
            "project_id": str(work.project_id),
            "handoff": {"id": str(handoff.id), "revision": handoff.revision},
            "package": {"id": str(handoff.package_id), "revision": handoff.package_revision},
            "bearer": token,
            "login_expires_at": login.expires_at.isoformat(),
            "grant_expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            "effective_until": min(deadlines).isoformat(),
        }


def run_browser_seed(work, handoff_id):
    """Serve existing facts, wait for finish, then prove no business row changed."""
    setup = work.setup
    directory, port = _environment(setup)
    seed = _existing_read_scope(work, handoff_id)
    before = upstream.snapshots(work, _MODELS)
    sock, server, thread = None, None, None
    errors = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
        server = uvicorn.Server(
            uvicorn.Config(
                _ReadOnlyApp(setup.client.app),
                host="127.0.0.1",
                port=port,
                log_level="warning",
                access_log=False,
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
        assert server.started and not errors, "Own read-only API startup failed"
        seed.update(
            api_host="127.0.0.1",
            api_port=port,
            finish_file=str(directory / "finish"),
            maximum_wait_seconds=_MAXIMUM_WAIT_SECONDS,
        )
        _write_private_new(directory / "seed.json", seed)
        print("Actual synthetic read-only handoff browser scope ready; API port", port, flush=True)
        deadline = time.monotonic() + _MAXIMUM_WAIT_SECONDS
        while not (directory / "finish").exists() and time.monotonic() < deadline:
            assert thread.is_alive() and not errors, "Own read-only API stopped before finish"
            time.sleep(0.2)
        assert (directory / "finish").exists(), "Finite read-only browser checkpoint elapsed"
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
        assert thread is None or not thread.is_alive(), "Own read-only API did not stop"
    assert upstream.snapshots(work, _MODELS) == before, (
        "Read-only browser changed existing handoff facts"
    )
