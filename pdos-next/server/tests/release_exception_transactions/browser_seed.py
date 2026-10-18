"""Finite actual browser T2s over the existing isolated synthetic fixture.

This helper exports existing logins and fixed materials only. It never creates
or previews a command, refreshes credentials, grants authority or moves a clock.
The root browser performs the named approval and peer withdrawal through the app.
"""

import os
import socket
import stat
import threading
import time
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import uvicorn
from manufacturing_preparation import publication_pg_helpers as upstream
from pydantic_core import to_jsonable_python
from release_policy_browser_seed.harness import _write_private_new
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
from pdos_next.domain.release.models import ReleasePackage
from pdos_next.domain.release_exceptions import rules
from pdos_next.domain.release_exceptions.constants import DECIDE, OPERATIONS, WITHDRAW
from pdos_next.domain.release_exceptions.models import (
    ReleaseExceptionCurrent as Current,
)
from pdos_next.domain.release_exceptions.models import (
    ReleaseExceptionDecision as Decision,
)
from pdos_next.domain.release_exceptions.schemas import DecidePayload
from pdos_next.models import (
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
from pdos_next.service import digest

_HEAD = "s0_0784"
_MAXIMUM_WAIT_SECONDS = 1200


def _environment(setup):
    if os.environ.get("PDOS_RELEASE_EXCEPTION_BROWSER_SEED") != "1":
        raise RuntimeError("Exception browser T2s require explicit isolated local opt-in")
    directory = Path(os.environ["PDOS_RELEASE_EXCEPTION_BROWSER_DIR"])
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
        raise RuntimeError("Browser seed directory must be fresh and owned with mode 0700")
    port = int(os.environ["PDOS_RELEASE_EXCEPTION_BROWSER_PORT"])
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
            raise RuntimeError("All engines must target the explicit independent pdos_test")
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    with setup.admin.connect() as connection:
        if (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            != _HEAD
        ):
            raise RuntimeError("Exception browser seed requires actual reviewed head s0_0784")
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
        assert product is not None and (product.tenant_id, product.category_id) == (
            setup.tenant,
            setup.category,
        )
        for name, identity, operation in (
            ("human", setup.human, DECIDE),
            ("peer", setup.peer, WITHDRAW),
        ):
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
            deadlines = [login.expires_at]
            if grant.expires_at is not None:
                deadlines.append(grant.expires_at)
            facts = []
            for pointer in s.scalars(
                select(ProfessionalCurrent).where(
                    ProfessionalCurrent.tenant_id == setup.tenant,
                    ProfessionalCurrent.product_id == setup.product,
                    ProfessionalCurrent.project_id == work.project_id,
                    ProfessionalCurrent.subject_id == identity,
                )
            ):
                fact = s.get(ProfessionalFact, pointer.fact_id)
                assert fact is not None and fact.revision == pointer.fact_revision
                if operation not in fact.operations or work.purpose not in fact.purposes:
                    continue
                assert fact.state == "active" and fact.nature == "synthetic"
                assert fact.valid_from <= captured < fact.valid_until
                facts.append(
                    {
                        "id": str(fact.id),
                        "revision": fact.revision,
                        "kind": fact.kind,
                        "role": fact.role,
                        "operations": fact.operations,
                        "valid_from": fact.valid_from.isoformat(),
                        "valid_until": fact.valid_until.isoformat(),
                    }
                )
                deadlines.append(fact.valid_until)
            assert {value["kind"] for value in facts} == {"duty", "qualification"}
            actors[name] = {
                "principal_id": str(identity),
                "bearer": token,
                "operation": operation,
                "login_expires_at": login.expires_at.isoformat(),
                "grant_id": str(grant.id),
                "grant_epoch": grant.access_epoch,
                "grant_can_write": grant.can_write,
                "grant_expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
                "professional_facts": facts,
                "effective_until": min(deadlines).isoformat(),
            }
        return product.revision, actors


def _before(work, basis_package, decide_payload):
    payload = DecidePayload.model_validate(decide_payload)
    assert payload.approval_token is None
    assert payload.basis_package.model_dump(mode="json") == {
        "id": basis_package["id"],
        "revision": basis_package["revision"],
    }
    assert payload.purpose == work.purpose
    with Session(work.setup.admin) as s:
        package = s.get(ReleasePackage, payload.basis_package.id)
        assert package is not None and package.project_id == work.project_id
        assert package.revision == payload.basis_package.revision
        assert package.body["declaration"]["exceptions"] == []
        assert package.body == basis_package["package"]
        decisions, currents = _rows(s, Decision, work), _rows(s, Current, work)
        assert len(decisions) == 2 and {row.action for row in decisions} == {
            "approved",
            "withdrawn",
        }
        assert len(currents) == 1 and currents[0].action == "withdrawn"
        return rules.semantic(payload), _snapshot(decisions), _snapshot(currents)


def _common_atom(work, identity, actor, operation):
    """Read each participant's real private request binding under their own caller."""
    with upstream.session(work, actor) as s:
        row = s.get(Decision, identity)
        assert row is not None
        receipt, proof = s.get(Receipt, row.receipt_id), s.get(Confirmation, row.shared_proof_id)
        assert receipt is not None and proof is not None
        assert row.actor_id == row.writer_id == row.requester_id == actor
        assert row.operation == operation and row.write_tier == "T2"
        assert receipt.subject_type == "release_exception" and receipt.subject_id == row.id
        assert receipt.subject_revision == row.revision == 1
        assert receipt.actor_id == receipt.requester_id == actor and receipt.operation == operation
        assert receipt.command_id == row.command_id
        assert receipt.confirmation_id == proof.id == row.shared_proof_id
        assert (
            receipt.request_digest == row.request_digest
            and receipt.intent_digest == row.intent_digest
        )
        assert receipt.result == {"id": str(row.id), "revision": 1, "status": row.action}
        assert receipt.run_id is receipt.agent_run_id is None
        assert proof.operation == operation and proof.actor_id == actor
        assert proof.consumed is True and proof.expires_at is row.proof_expires_at is None
        assert proof.created_at <= row.proof_consumed_at <= row.created_at <= receipt.created_at
        assert proof.payload_digest == row.material_sha256 and proof.token_hash == row.token_sha256
        assert proof.snapshot == row.input_snapshot["review"]
        for model in (Audit, Outbox, RequestKey):
            members = list(s.scalars(select(model).where(model.receipt_id == receipt.id)))
            assert len(members) == 1 and members[0].actor_id == actor
            member = members[0]
            if model is Audit:
                assert member.operation == operation
            elif model is Outbox:
                assert (
                    member.type,
                    member.subject_id,
                    member.subject_revision,
                    member.correlation_id,
                ) == (OPERATIONS[operation][1], row.id, 1, row.command_id)
            else:
                assert member.digest == row.request_digest
                assert digest(member.key) == row.input_snapshot["original_key_sha256"]
        assert "idempotency_key" not in row.input_snapshot["command"]
        assert "approval_token" not in row.input_snapshot["command"]["payload"]


def _after(work, basis_package, payload, withdrawal_source, before_decisions, before_currents):
    with Session(work.setup.admin) as s:
        decisions, currents = _rows(s, Decision, work), _rows(s, Current, work)
        snapshots, current_snapshots = _snapshot(decisions), _snapshot(currents)
        assert len(snapshots) == len(before_decisions) + 2
        assert len(current_snapshots) == len(before_currents) + 1
        assert {key: snapshots[key] for key in before_decisions} == before_decisions
        assert {key: current_snapshots[key] for key in before_currents} == before_currents
        new_rows = [row for row in decisions if str(row.id) not in before_decisions]
        by_action = {row.action: row for row in new_rows}
        assert set(by_action) == {"approved", "withdrawn"}
        approved, withdrawn = by_action["approved"], by_action["withdrawn"]
        assert approved.series_id == approved.id and approved.previous_id is None
        assert withdrawn.series_id == approved.id and withdrawn.previous_id == approved.id
        assert withdrawn.previous_revision == approved.revision == 1
        assert approved.body["declaration"] == payload
        assert withdrawn.body["declaration"]["exception"] == {"id": str(approved.id), "revision": 1}
        assert withdrawn.body["declaration"]["sources"] == [withdrawal_source]
        for row in (approved, withdrawn):
            assert (row.basis_package_id, row.basis_package_revision) == (
                UUID(basis_package["id"]),
                basis_package["revision"],
            )
            assert row.body["selected_checks"] == approved.body["selected_checks"]
            assert row.owner_id == approved.owner_id and row.visibility == approved.visibility
        selected = [row for row in currents if row.series_id == approved.id]
        assert len(selected) == 1 and selected[0].action == "withdrawn"
        assert selected[0].epoch == 2 and selected[0].decision_id == withdrawn.id
        assert selected[0].decision_revision == 1
        approved_id, withdrawn_id = approved.id, withdrawn.id
    _common_atom(work, approved_id, work.setup.human, DECIDE)
    _common_atom(work, withdrawn_id, work.setup.peer, WITHDRAW)
    return {
        "series_id": str(approved_id),
        "approved": {"id": str(approved_id), "revision": 1},
        "withdrawn": {"id": str(withdrawn_id), "revision": 1},
        "current_epoch": 2,
    }


def run_browser_seed(work, basis_package, decide_payload, withdrawal_source):
    """Serve actual app, wait for root UI, then read its two immutable T2 atoms."""
    setup = work.setup
    directory, port = _environment(setup)
    captured = now()
    payload, before_decisions, before_currents = _before(work, basis_package, decide_payload)
    source = SourceRef.model_validate(withdrawal_source)
    assert source.kind == "artifact"
    withdrawal_source = source.model_dump(mode="json")
    product_revision, actors = _participants(work, captured)
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
        assert server.started and not errors, "Own actual synthetic API startup failed"
        _write_private_new(
            directory / "seed.json",
            to_jsonable_python(
                {
                    "schema_version": "pdos-release-exception-browser-seed-v1",
                    "synthetic": True,
                    "created_at": captured.isoformat(),
                    "database_head": _HEAD,
                    "api_host": "127.0.0.1",
                    "api_port": port,
                    "tenant_id": str(setup.tenant),
                    "category_id": str(setup.category),
                    "product_id": str(setup.product),
                    "product_revision": product_revision,
                    "project_id": str(work.project_id),
                    "purpose": work.purpose,
                    "actors": actors,
                    "effective_until": min(value["effective_until"] for value in actors.values()),
                    "basis_package": deepcopy(basis_package),
                    "decide_payload": payload,
                    "withdrawal_source": withdrawal_source,
                    "finish_file": str(directory / "finish"),
                    "maximum_wait_seconds": _MAXIMUM_WAIT_SECONDS,
                    "boundary": (
                        "Two finite synthetic browser T2s only: human approval, then peer "
                        "withdrawal. This seed creates no command, login or qualification and "
                        "renews no deadline. No external send, customer acceptance "
                        "or production use."
                    ),
                }
            ),
        )
        print("Actual synthetic exception browser scope ready; API port", port, flush=True)
        deadline = time.monotonic() + _MAXIMUM_WAIT_SECONDS
        while not (directory / "finish").exists() and time.monotonic() < deadline:
            assert thread.is_alive() and not errors, (
                "Own synthetic API stopped before browser finish"
            )
            time.sleep(0.2)
        assert (directory / "finish").exists(), "Finite browser checkpoint elapsed without finish"
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
        assert thread is None or not thread.is_alive(), "Own synthetic API did not stop"
    return _after(
        work, basis_package, payload, withdrawal_source, before_decisions, before_currents
    )
