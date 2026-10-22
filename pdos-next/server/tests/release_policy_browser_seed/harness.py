"""Keep a real synthetic package alive for two explicit browser decisions.

The caller has already imported the controlled policy and assembled package v2.
This helper never prepares, previews or executes either T2 command. Only an
explicit local host opt-in exports the two existing short-lived fixture logins.
"""

import json
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
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
from pdos_next.domain.release import service
from pdos_next.domain.release.models import ReleaseDecision
from pdos_next.domain.release.policy_models import ReleasePolicyCurrent, ReleasePolicyFact
from pdos_next.models import Audit, Confirmation, Grant, LoginSession, Outbox, Product, Receipt
from pdos_next.safety import verify_test_target
from pdos_next.service import digest

_HEAD = "s0_0782"
_WAIT_SECONDS = 1200


def _environment(setup):
    if os.environ.get("PDOS_RELEASE_POLICY_BROWSER_SEED") != "1":
        raise RuntimeError("Release policy browser handoff requires explicit local opt-in")
    directory = Path(os.environ["PDOS_RELEASE_POLICY_BROWSER_DIR"])
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
        raise RuntimeError("Browser seed directory must not contain seed.json or finish")
    port = int(os.environ["PDOS_RELEASE_POLICY_BROWSER_PORT"])
    database_port = int(os.environ["TEST_DATABASE_PORT"])
    if not 1024 <= port <= 65535 or port == database_port:
        raise RuntimeError("Choose an explicit unused loopback API port separate from PostgreSQL")
    if not os.environ.get("TEST_DATABASE_MARKER"):
        raise RuntimeError("The explicit independent test marker is required")
    for name in ("TEST_DATABASE_URL", "DATABASE_URL", "AUTH_DATABASE_URL", "DISPATCH_DATABASE_URL"):
        target = make_url(os.environ[name])
        if (
            target.drivername != "postgresql+psycopg"
            or target.host not in {"127.0.0.1", "localhost"}
            or target.port != database_port
            or target.database != "pdos_test"
            or target.query
        ):
            raise RuntimeError("All engines must use the explicit independent pdos_test target")
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    with setup.admin.connect() as connection:
        if (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            != _HEAD
        ):
            raise RuntimeError("Browser seed requires the actual reviewed s0_0782 head")
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


def _logins(work, captured):
    setup, actors = work.setup, {}
    with Session(setup.admin) as s:
        product = s.get(Product, setup.product)
        assert (
            product is not None
            and product.tenant_id == setup.tenant
            and product.category_id == setup.category
        )
        product_metadata = {
            "id": str(product.id),
            "revision": product.revision,
            "name": product.name,
        }
        for discipline, identity in (("engineering", setup.human), ("manufacturing", setup.peer)):
            operation = f"release.{discipline}.approve"
            token = setup.tokens[identity]
            login = s.get(LoginSession, digest(token))
            grant = s.scalar(
                select(Grant).where(
                    Grant.tenant_id == setup.tenant,
                    Grant.category_id == setup.category,
                    Grant.principal_id == identity,
                )
            )
            assert login is not None and not login.revoked and login.expires_at > captured
            assert (login.tenant_id, login.principal_id) == (setup.tenant, identity)
            assert grant is not None and grant.can_write and grant.expires_at > captured
            pointers = list(
                s.scalars(
                    select(ProfessionalCurrent).where(
                        ProfessionalCurrent.tenant_id == setup.tenant,
                        ProfessionalCurrent.product_id == setup.product,
                        ProfessionalCurrent.project_id == work.project_id,
                        ProfessionalCurrent.subject_id == identity,
                    )
                )
            )
            facts, deadlines = [], [login.expires_at, grant.expires_at]
            for pointer in pointers:
                fact = s.get(ProfessionalFact, pointer.fact_id)
                assert fact is not None
                assert (
                    fact.tenant_id,
                    fact.product_id,
                    fact.project_id,
                    fact.subject_id,
                    fact.revision,
                    fact.series_id,
                ) == (
                    setup.tenant,
                    setup.product,
                    work.project_id,
                    identity,
                    pointer.fact_revision,
                    pointer.series_id,
                )
                if (
                    fact.role != discipline
                    or operation not in fact.operations
                    or work.purpose not in fact.purposes
                ):
                    continue
                assert fact.state == "active" and fact.nature == "synthetic"
                assert fact.valid_from <= captured < fact.valid_until
                facts.append(
                    {
                        "id": str(fact.id),
                        "revision": fact.revision,
                        "kind": fact.kind,
                        "role": fact.role,
                        "nature": fact.nature,
                        "operations": fact.operations,
                        "purposes": fact.purposes,
                        "valid_from": fact.valid_from.isoformat(),
                        "valid_until": fact.valid_until.isoformat(),
                    }
                )
                deadlines.append(fact.valid_until)
            assert {fact["kind"] for fact in facts} == {"duty", "qualification"}
            actors[discipline] = {
                "principal_id": str(identity),
                "operation": operation,
                "bearer": token,
                "login_expires_at": login.expires_at.isoformat(),
                "grant_id": str(grant.id),
                "grant_epoch": grant.access_epoch,
                "grant_expires_at": grant.expires_at.isoformat(),
                "professional_facts": facts,
                "effective_until": min(deadlines).isoformat(),
            }
    return product_metadata, actors


def _prepared_only(work, package, decision_payload, policy_ref):
    setup = work.setup
    assert "approval_token" not in decision_payload and "confirmation_token" not in decision_payload
    assert decision_payload["expiry"] is None
    assert decision_payload["package"] == {"id": package["id"], "revision": package["revision"]}
    assert decision_payload["purpose"] == work.purpose and package["revision"] == 2
    with upstream.session(work) as s:
        row, actual = service.get_package(s, setup.ctx, setup.product, UUID(package["id"]))
        assert row.project_id == work.project_id and actual["package"] == package["package"]
        assert actual["decisions"] == [] and actual["applicability"] == "current"
        assert {value["state"] for value in actual["assessments"].values()} == {"READY"}
        assert (
            s.scalar(
                select(ReleaseDecision.id).where(
                    ReleaseDecision.tenant_id == setup.tenant,
                    ReleaseDecision.product_id == setup.product,
                    ReleaseDecision.project_id == work.project_id,
                )
            )
            is None
        )
        assert (
            s.scalar(
                select(Confirmation.id).where(
                    Confirmation.tenant_id == setup.tenant,
                    Confirmation.product_id == setup.product,
                    Confirmation.operation.in_(
                        ("release.engineering.approve", "release.manufacturing.approve")
                    ),
                )
            )
            is None
        )
        policy = s.get(ReleasePolicyFact, UUID(policy_ref["id"]))
        current = s.scalar(
            select(ReleasePolicyCurrent).where(
                ReleasePolicyCurrent.tenant_id == setup.tenant,
                ReleasePolicyCurrent.product_id == setup.product,
                ReleasePolicyCurrent.project_id == work.project_id,
            )
        )
        assert policy is not None and policy.status == "active" and policy.nature == "synthetic"
        assert policy.revision == policy_ref["revision"] and policy.source == policy_ref["source"]
        assert (
            current is not None
            and current.fact_id == policy.id
            and current.revision == policy.revision
        )
        assert policy.material["scope"] == {
            "tenant_id": str(setup.tenant),
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
        }
    return digest(package["package"])


def _decisions_after_browser(work, package, expected_package_hash, decision_payload):
    setup = work.setup
    with upstream.session(work) as s:
        _, viewed = service.get_package(s, setup.ctx, setup.product, UUID(package["id"]))
        assert (
            digest(viewed["package"]) == expected_package_hash
            and viewed["package"] == package["package"]
        )
        assert len(viewed["decisions"]) == 2 and {
            row["discipline"] for row in viewed["decisions"]
        } == {"engineering", "manufacturing"}
    identities = []
    for discipline, actor in (("engineering", setup.human), ("manufacturing", setup.peer)):
        with upstream.session(work, actor=actor) as s:
            rows = list(
                s.scalars(
                    select(ReleaseDecision).where(
                        ReleaseDecision.tenant_id == setup.tenant,
                        ReleaseDecision.category_id == setup.category,
                        ReleaseDecision.product_id == setup.product,
                        ReleaseDecision.project_id == work.project_id,
                        ReleaseDecision.package_id == UUID(package["id"]),
                        ReleaseDecision.discipline == discipline,
                    )
                )
            )
            assert len(rows) == 1
            decision = rows[0]
            operation = f"release.{discipline}.approve"
            assert (
                decision.actor_id,
                decision.requester_id,
                decision.writer_id,
                decision.owner_id,
            ) == (actor, actor, actor, actor)
            assert (
                decision.package_revision == package["revision"] and decision.operation == operation
            )
            assert decision.write_tier == "T2" and decision.status == "approved"
            assert decision.body["purpose"] == decision_payload["purpose"]
            assert decision.body["release_scope"] == decision_payload["release_scope"]
            assert decision.body["scope"] == {
                "tenant_id": str(setup.tenant),
                "product_id": str(setup.product),
                "project_id": str(work.project_id),
            }
            assert decision.body["expiry"] is None and decision.proof_expires_at is None
            assert (
                decision.body["external_received"] is False
                and decision.body["external_effective"] is False
                and decision.body["customer_acceptance"] is None
            )
            receipt = s.get(Receipt, decision.receipt_id)
            confirmation = s.get(Confirmation, decision.shared_proof_id)
            assert receipt is not None and confirmation is not None
            assert receipt.confirmation_id == confirmation.id == decision.shared_proof_id
            assert (
                receipt.subject_id == decision.id and receipt.subject_revision == decision.revision
            )
            assert (
                receipt.operation == operation and receipt.actor_id == receipt.requester_id == actor
            )
            assert (
                receipt.command_id == decision.command_id
                and receipt.run_id is None
                and receipt.agent_run_id is None
            )
            assert confirmation.actor_id == actor and confirmation.operation == operation
            assert confirmation.consumed is True and confirmation.expires_at is None
            assert (
                confirmation.created_at
                <= decision.proof_consumed_at
                <= decision.created_at
                <= receipt.created_at
            )
            assert confirmation.token_hash == decision.token_sha256
            audits = list(
                s.scalars(
                    select(Audit).where(
                        Audit.tenant_id == setup.tenant, Audit.receipt_id == receipt.id
                    )
                )
            )
            outboxes = list(
                s.scalars(
                    select(Outbox).where(
                        Outbox.tenant_id == setup.tenant, Outbox.receipt_id == receipt.id
                    )
                )
            )
            assert len(audits) == len(outboxes) == 1
            assert audits[0].actor_id == actor and audits[0].operation == operation
            assert (
                outboxes[0].type,
                outboxes[0].subject_id,
                outboxes[0].subject_revision,
                outboxes[0].actor_id,
                outboxes[0].correlation_id,
            ) == (
                f"release.{discipline}_approved",
                decision.id,
                decision.revision,
                actor,
                receipt.command_id,
            )
            identities.append(str(decision.id))
    assert len(set(identities)) == 2
    return identities


def run_browser_seed(work, *, package, decision_payload, policy_ref):
    """Wait for the root browser, then verify actual independent persisted T2s."""
    setup = work.setup
    directory, port = _environment(setup)
    captured = upstream.now()
    expected_package_hash = _prepared_only(work, package, decision_payload, policy_ref)
    product, actors = _logins(work, captured)
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
        seed = {
            "schema_version": "pdos-release-policy-browser-seed-v1",
            "synthetic": True,
            "created_at": captured.isoformat(),
            "api_host": "127.0.0.1",
            "api_port": port,
            "database_head": _HEAD,
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "product": product,
            "project_id": str(work.project_id),
            "purpose": work.purpose,
            "actors": actors,
            "effective_until": min(value["effective_until"] for value in actors.values()),
            "package": {
                "id": package["id"],
                "revision": package["revision"],
                "receipt_id": package["receipt_id"],
            },
            "decision_payload": deepcopy(decision_payload),
            "policy_ref": deepcopy(policy_ref),
            "finish_file": str(directory / "finish"),
            "maximum_wait_seconds": _WAIT_SECONDS,
            "boundary": (
                "Finite synthetic internal documentation scope only. No T2 was prepared or "
                "executed by this seed. Browser decisions require their actual named persons "
                "and common one-time approval. No physical resource qualification, external "
                "receipt, customer acceptance or production effect. Do not renew credentials, "
                "authority or clocks."
            ),
        }
        _write_private_new(directory / "seed.json", seed)
        print("Actual synthetic release browser scope ready; API port", port, flush=True)
        deadline = time.monotonic() + _WAIT_SECONDS
        while not (directory / "finish").exists() and time.monotonic() < deadline:
            assert thread.is_alive() and not errors, (
                "Own synthetic API stopped before browser finish"
            )
            time.sleep(0.2)
        assert (directory / "finish").exists(), (
            "Finite browser checkpoint elapsed without finish signal"
        )
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
    return _decisions_after_browser(work, package, expected_package_hash, decision_payload)
