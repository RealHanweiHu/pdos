from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_trusted_source_work import claim_cmd, command, post, source

from pdos_next.clock import now, using_clock
from pdos_next.models import Artifact, Grant, Outbox, Receipt, RequestKey


@pytest.mark.parametrize("product_scope", [True, False])
def test_held_membership_proof_still_checks_actual_temporary_deadline(setup, product_scope):
    from pdos_next.database import tenant_session
    from pdos_next.errors import DomainError
    from pdos_next.service import require_access

    at = now()
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        )
        grant.expires_at = at + timedelta(seconds=10)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        with using_clock(lambda: at):
            require_access(
                session, setup.ctx, setup.product if product_scope else None, write=True, lock=True
            )
        with using_clock(lambda: at + timedelta(seconds=10)):
            with pytest.raises(DomainError) as error:
                require_access(
                    session,
                    setup.ctx,
                    setup.product if product_scope else None,
                    write=True,
                    lock=True,
                )
            assert error.value.code == "FORBIDDEN_SCOPE"


def test_exact_replay_uses_read_authority_after_source_withdrawal_and_write_revocation(setup):
    artifact, _ = source(setup)
    cmd = claim_cmd(setup, artifact)
    original = post(setup, cmd).json()
    with Session(setup.admin) as s, s.begin():
        s.get(Artifact, UUID(artifact)).status = "withdrawn"
        grant = s.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        )
        grant.can_write = False
    statements = []

    def count(_conn, _cursor, sql, _params, _context, _many):
        statements.append(sql)

    event.listen(setup.engine, "before_cursor_execute", count)
    try:
        replay = post(setup, cmd)
    finally:
        event.remove(setup.engine, "before_cursor_execute", count)
    assert replay.status_code == 200 and replay.json()["id"] == original["id"]
    assert not any("artifact_versions" in sql for sql in statements)
    assert not any("FOR UPDATE" in sql for sql in statements)
    fresh = post(setup, {**cmd, "idempotency_key": str(uuid4())})
    assert fresh.status_code == 200 and fresh.json()["id"] == original["id"]
    changed = post(
        setup,
        {
            **cmd,
            "idempotency_key": str(uuid4()),
            "payload": {**cmd["payload"], "statement": "Different write intent"},
        },
    )
    assert changed.status_code == 403


def test_expired_confirmation_replay_returns_original_but_new_intent_rejects(setup):
    artifact, _ = source(setup)
    recorded = post(setup, claim_cmd(setup, artifact)).json()
    path = (
        f"/v1/categories/{setup.category}/products/{setup.product}/receipts/"
        f"{recorded['id']}/revert-preview"
    )
    preview = setup.client.post(path, headers=setup.headers).json()
    cmd = command(
        setup,
        "ai.run.revert",
        {"receipt_id": recorded["id"], "confirmation_token": preview["confirmation_token"]},
    )
    original = post(setup, cmd)
    assert original.status_code == 200
    pending_receipt = post(
        setup, claim_cmd(setup, artifact, statement="A separate pending confirmation")
    ).json()
    pending_preview = setup.client.post(
        path.replace(recorded["id"], pending_receipt["id"]), headers=setup.headers
    ).json()
    pending = command(
        setup,
        "ai.run.revert",
        {
            "receipt_id": pending_receipt["id"],
            "confirmation_token": pending_preview["confirmation_token"],
        },
    )
    clock = now() + timedelta(minutes=11)
    with using_clock(lambda: clock):
        replay = post(setup, cmd)
        expired = post(setup, pending)
    assert replay.status_code == 200 and replay.json()["id"] == original.json()["id"]
    assert expired.status_code == 409
    assert expired.json()["code"] == "CONFIRMATION_REQUIRED"
    with Session(setup.admin) as s:
        assert not s.scalar(
            select(RequestKey.id).where(RequestKey.key == pending["idempotency_key"])
        )


def test_direct_sources_are_read_once_even_when_handler_reuses_them(setup):
    artifact, _ = source(setup)
    statements = []

    def count(_conn, _cursor, sql, _params, _context, _many):
        # Scope affiliation is checked before parent lock ordering. Only the
        # complete source material is a reusable evidence read/validation.
        if (
            sql.lstrip().startswith("SELECT")
            and "FROM artifact_versions" in sql
            and "artifact_versions.content" in sql
        ):
            statements.append(sql)

    event.listen(setup.engine, "before_cursor_execute", count)
    try:
        response = post(setup, claim_cmd(setup, artifact))
    finally:
        event.remove(setup.engine, "before_cursor_execute", count)
    assert response.status_code == 200, response.text
    assert len(statements) == 1


def test_receipt_audit_outbox_key_rollback_is_atomic(setup):
    artifact, _ = source(setup)
    cmd = claim_cmd(setup, artifact)

    def fail(*_):
        raise RuntimeError("proof rollback injection")

    event.listen(Outbox, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="proof rollback"):
            post(setup, cmd)
    finally:
        event.remove(Outbox, "before_insert", fail)
    with Session(setup.admin) as s:
        assert (
            s.scalar(
                select(RequestKey).where(
                    RequestKey.tenant_id == setup.tenant, RequestKey.key == cmd["idempotency_key"]
                )
            )
            is None
        )
        assert (
            s.scalar(
                select(Receipt).where(
                    Receipt.tenant_id == setup.tenant, Receipt.operation == "evidence.claim.record"
                )
            )
            is None
        )


def test_transaction_retry_rebuilds_proof_and_commits_only_once(setup):
    artifact, _ = source(setup)
    cmd = claim_cmd(setup, artifact)
    attempts = []

    class Abort(Exception):
        sqlstate = "40001"

    def fail_twice(_mapper, connection, _target):
        attempts.append(connection)
        if len(attempts) < 3:
            raise DBAPIError(None, None, Abort("synthetic serialization abort"))

    event.listen(Outbox, "before_insert", fail_twice)
    try:
        response = post(setup, cmd)
    finally:
        event.remove(Outbox, "before_insert", fail_twice)
    assert response.status_code == 200, response.text
    assert len(attempts) == len({id(c) for c in attempts}) == 3
    with Session(setup.admin) as s:
        receipts = list(
            s.scalars(
                select(Receipt).where(
                    Receipt.tenant_id == setup.tenant, Receipt.operation == "evidence.claim.record"
                )
            )
        )
        assert len(receipts) == 1
        assert len(list(s.scalars(select(Outbox).where(Outbox.receipt_id == receipts[0].id)))) == 1


def test_public_error_category_has_specific_reason_without_identity_leak(setup):
    cmd = command(setup, "evidence.artifact.register", {"content": "missing fields"})
    response = post(setup, cmd)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["detail"]["reason"] == "INVALID_PAYLOAD"


def test_read_snapshot_is_repeatable_readonly_and_memo_ends_with_transaction(setup):
    from sqlalchemy import text

    from pdos_next.database import tenant_session
    from pdos_next.request_proof import snapshot_scalar

    artifact_id, _ = source(setup)
    identity = UUID(artifact_id)
    statements = []

    def count(_conn, _cursor, sql, _params, _context, _many):
        if sql.lstrip().startswith("SELECT") and "FROM artifact_versions" in sql:
            statements.append(sql)

    event.listen(setup.engine, "before_cursor_execute", count)
    try:
        for _ in range(2):
            with tenant_session(
                setup.engine,
                setup.tenant,
                actor_id=setup.human,
                requester_id=setup.human,
                category_id=setup.category,
                read_snapshot=True,
            ) as s:
                assert s.scalar(text("SHOW transaction_read_only")) == "on"
                assert s.scalar(text("SHOW transaction_isolation")) == "repeatable read"
                query = select(Artifact).where(Artifact.id == identity)
                first = snapshot_scalar(s, (Artifact, identity), query)
                assert first is not None
                assert snapshot_scalar(s, (Artifact, identity), query) is first
        assert len(statements) == 2
    finally:
        event.remove(setup.engine, "before_cursor_execute", count)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
        read_snapshot=True,
    ) as s:
        with pytest.raises(DBAPIError) as error:
            s.execute(
                text("UPDATE artifact_versions SET status='withdrawn' WHERE id=:id"),
                {"id": identity},
            )
        assert error.value.orig.sqlstate == "25006"


def test_locked_scope_reads_upgrade_once_and_flush_discards_cached_scalars(setup):
    from pdos_next.contracts import Command
    from pdos_next.database import tenant_session
    from pdos_next.models import Product
    from pdos_next.request_proof import snapshot_scalar
    from pdos_next.service import Context, command_scope

    ctx = Context(setup.tenant, setup.human, setup.human, category_id=setup.category)
    value = Command.model_validate(
        command(
            setup,
            "evidence.artifact.register",
            {
                "title": "locked scalar proof",
                "source_label": "synthetic",
                "content": "current scope only",
                "visibility": "private",
            },
        )
    )
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        product = command_scope(s, ctx, value, lock=True)
        statements = []

        def count(_conn, _cursor, sql, _params, _context, _many):
            if sql.lstrip().startswith("SELECT") and "FROM products" in sql:
                statements.append(sql)

        event.listen(setup.engine, "before_cursor_execute", count)
        try:
            query = select(Product.name).where(Product.id == product.id)
            key = ("scalar-name", product.id)
            assert snapshot_scalar(s, key, query, scope_id=product.id) == product.name
            snapshot_scalar(s, key, query, scope_id=product.id)
            assert len(statements) == 1
            snapshot_scalar(s, key, query, lock=True, scope_id=product.id)
            snapshot_scalar(s, key, query, lock=True, scope_id=product.id)
            assert len(statements) == 2 and "FOR UPDATE" in statements[-1]
            product.name = "updated inside the same command"
            s.flush()
            assert snapshot_scalar(s, key, query, scope_id=product.id) == product.name
            assert len(statements) == 3
            from sqlalchemy import update

            s.execute(update(Product).where(Product.id == product.id).values(name="direct DML"))
            assert snapshot_scalar(s, key, query, scope_id=product.id) == "direct DML"
            assert len(statements) == 4
        finally:
            event.remove(setup.engine, "before_cursor_execute", count)


@pytest.mark.parametrize("reader", ["batch", "scoped"])
def test_lock_upgrade_reads_committed_peer_change_into_held_orm_identity(setup, reader):
    from pdos_next.database import tenant_session
    from pdos_next.models import Product
    from pdos_next.request_proof import batch_read, scoped_rows

    query = select(Product).where(Product.id == setup.product)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:

        def read(lock):
            if reader == "batch":
                return batch_read(session, Product, [setup.product], lock=lock)[setup.product]
            return scoped_rows(session, (Product, setup.product), query, lock=lock)[0]

        held = read(False)
        with Session(setup.admin) as peer, peer.begin():
            peer.get(Product, setup.product).name = "committed before the dependency lock"
        locked = read(True)
        assert locked is held and locked.name == "committed before the dependency lock"
        assert read(True) is locked


def test_savepoint_rollback_cannot_reuse_authority_after_its_lock_is_released(setup):
    from pdos_next.database import tenant_session
    from pdos_next.errors import DomainError
    from pdos_next.service import require_access

    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        with pytest.raises(RuntimeError, match="rollback the dependency locks"):
            with session.begin_nested():
                require_access(session, setup.ctx, setup.product, write=True, lock=True)
                raise RuntimeError("rollback the dependency locks")
        with Session(setup.admin) as peer, peer.begin():
            grant = peer.scalar(
                select(Grant).where(
                    Grant.category_id == setup.category,
                    Grant.principal_id == setup.human,
                )
            )
            grant.can_write = False
        with pytest.raises(DomainError) as error:
            require_access(session, setup.ctx, setup.product, write=True, lock=True)
        assert error.value.reason == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("mutation", ["source", "authority"])
def test_direct_dml_invalidates_source_and_authority_proofs_in_same_uow(setup, mutation):
    from sqlalchemy import update

    from pdos_next.errors import DomainError
    from pdos_next.service import require_access, source_for

    artifact, _ = source(setup)
    identity = UUID(artifact)
    # This mutation port is the database owner. It exercises actual Core DML
    # without pretending an application caller owns Grant administration.
    with Session(setup.admin) as session, session.begin():
        require_access(session, setup.ctx, setup.product, write=True, lock=True)
        assert source_for(session, setup.ctx, setup.product, identity).status == "active"
        with pytest.raises(RuntimeError, match="restore the real savepoint"):
            with session.begin_nested():
                if mutation == "source":
                    session.execute(
                        update(Artifact)
                        .where(Artifact.id == identity)
                        .values(status="withdrawn")
                        .execution_options(synchronize_session=False)
                    )
                    with pytest.raises(DomainError) as error:
                        source_for(session, setup.ctx, setup.product, identity)
                    assert error.value.reason == "SOURCE_UNAVAILABLE"
                else:
                    session.execute(
                        update(Grant)
                        .where(
                            Grant.category_id == setup.category,
                            Grant.principal_id == setup.human,
                        )
                        .values(can_write=False)
                        .execution_options(synchronize_session=False)
                    )
                    with pytest.raises(DomainError) as error:
                        require_access(session, setup.ctx, setup.product, write=True, lock=True)
                    assert error.value.reason == "FORBIDDEN_SCOPE"
                raise RuntimeError("restore the real savepoint")
        require_access(session, setup.ctx, setup.product, write=True, lock=True)
        assert source_for(session, setup.ctx, setup.product, identity).status == "active"
