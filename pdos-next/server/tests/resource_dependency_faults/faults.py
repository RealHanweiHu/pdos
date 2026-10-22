"""Root-only real transaction probes; importing this module performs no I/O.

The caller must first verify the exact independent TEST_DATABASE_URL target.
No fixture, grant, clock, source validator or business result is substituted.
Hooks attach only to the Session performing one exact prepared command.
"""

from contextlib import contextmanager
from copy import deepcopy

from sqlalchemy import event, inspect, select, text

from pdos_next import service as common
from pdos_next.domain.build_operational_facts.models import OperationalAsset, ResourceOccupancy
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.models import (
    SampleRunUsage,
    SampleUsageSentinel,
    TestResourceReservation,
)
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Product, Receipt, RequestKey

FAULT_CODE = "VERSION_CONFLICT"
MISSING_GROUP_MESSAGE = (
    "Versioned Start requires its common receipt, request key, audit and outbox atom"
)
WRONG_PROOF_MESSAGE = (
    "Versioned dependency requires the exact immutable Start and saved reservation"
)

ATOM_MODELS = (
    Product,
    Confirmation,
    TestResourceReservation,
    ResourceOccupancy,
    SampleRunUsage,
    SampleUsageSentinel,
    OperationalAsset,
    FormalVerificationRequest,
    FormalVerificationCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
    VerificationRunCurrent,
    VerificationLaunchFact,
    Receipt,
    RequestKey,
    Audit,
    Outbox,
)


def snapshot(session, tenant_id):
    """Full rows, not merely counts, cover pointers/epochs/T1/common logs together."""
    return {
        model.__tablename__: sorted(
            common.digest(dict(row))
            for row in session.execute(
                select(model.__table__).where(model.__table__.c.tenant_id == tenant_id)
            ).mappings()
        )
        for model in ATOM_MODELS
    }


def _same_command(command, target):
    return (
        command.operation == target.operation == "test.run.start"
        and command.command_id == target.command_id
        and command.product_id == target.product_id
        and command.idempotency_key == target.idempotency_key
    )


@contextmanager
def fail_after_final_common_flush(monkeypatch, target):
    """Raise after the actual Receipt/Key/Audit/Outbox exist in one HTTP UOW.

    RequestKey is inserted through the real atomic Core upsert, which flushes
    Audit/Outbox first. Check all four stored rows after that actual operation;
    an ORM-only pending-row hook would silently miss the Core request key.
    """
    original_append, original_key = common.append_receipt, common.remember_key
    trace = {"attached": False, "armed": False, "fired": False, "flushed_common_rows": 0}
    captured = {}

    def append(session, ctx, command, *args, **kwargs):
        receipt = original_append(session, ctx, command, *args, **kwargs)
        if _same_command(command, target):
            assert inspect(receipt).persistent and receipt.operation == "test.run.start"
            assert receipt.actor_id == receipt.requester_id == ctx.actor_id
            assert receipt.run_id is None and receipt.agent_run_id is None
            assert receipt.subject_type == "test_run" and receipt.subject_revision == 2
            trace["attached"] = True
            captured.update(session=session, receipt=receipt)
        return receipt

    def remember(session, ctx, key, request_digest, receipt):
        original_key(session, ctx, key, request_digest, receipt)
        if captured.get("session") is not session or captured.get("receipt") is not receipt:
            return
        assert key == target.idempotency_key and request_digest == receipt.request_digest
        keys = list(session.scalars(select(RequestKey).where(RequestKey.receipt_id == receipt.id)))
        audits = list(session.scalars(select(Audit).where(Audit.receipt_id == receipt.id)))
        outboxes = list(session.scalars(select(Outbox).where(Outbox.receipt_id == receipt.id)))
        assert len(keys) == len(audits) == len(outboxes) == 1
        assert keys[0].key == key and keys[0].digest == receipt.request_digest
        assert audits[0].actor_id == ctx.actor_id and audits[0].operation == "test.run.start"
        assert (
            outboxes[0].type == "test.run_started" and outboxes[0].subject_id == receipt.subject_id
        )
        trace.update(armed=True, fired=True, flushed_common_rows=4)
        raise DomainError(FAULT_CODE, "明确测试故障：共同全组已写入但尚未commit。", 409)

    with monkeypatch.context() as patch:
        patch.setattr(common, "append_receipt", append)
        patch.setattr(common, "remember_key", remember)
        yield trace


@contextmanager
def require_deferred_atom_before_common_key(monkeypatch, target):
    """Run only the actual new constraint before its future Key/Audit/Outbox exist.

    Real Receipt INSERT has happened; real Audit/Outbox are pending and actual
    RequestKey has not been added. This intentionally incomplete group must fail
    the next_0029 deferred trigger; no existing immutable row is removed.
    """
    original = common.append_receipt
    trace = {"fired": False}

    def append(session, ctx, command, *args, **kwargs):
        receipt = original(session, ctx, command, *args, **kwargs)
        if _same_command(command, target):
            assert inspect(receipt).persistent
            assert not any(isinstance(row, RequestKey) for row in session.new)
            assert sum(isinstance(row, Audit) for row in session.new) == 1
            assert sum(isinstance(row, Outbox) for row in session.new) == 1
            trace["fired"] = True
            # Textual SET does not autoflush pending ORM Audit/Outbox. This checks
            # only the real new trigger, not unrelated deferred constraint order.
            session.execute(text("SET CONSTRAINTS test_resource_dependency_required IMMEDIATE"))
        return receipt

    with monkeypatch.context() as patch:
        patch.setattr(common, "append_receipt", append)
        yield trace


@contextmanager
def mismatch_pending_original_start_proof(monkeypatch, target):
    """Corrupt only a new Start DTO snapshot before its first INSERT.

    Reservation and its full record stay intact. A second structurally valid
    v2 record carries a different complete pointer epoch/hash in the pending
    Start; the actual next_0029 cross-row trigger must reject it after real
    execute. Never UPDATE/DELETE an immutable committed row or disable a trigger.
    """
    original = launch._record
    trace = {"fired": False}

    def record(session, ctx, command, product, payload, bound, pointers, mutation):
        if not _same_command(command, target):
            return original(session, ctx, command, product, payload, bound, pointers, mutation)

        def before_flush(active, _context, _instances):
            rows = [
                row
                for row in active.new
                if isinstance(row, VerificationRunVersion)
                and row.tenant_id == ctx.tenant_id
                and row.run_id == payload.run_id
                and row.operation == "test.run.start"
                and row.revision == 2
            ]
            if not rows or trace["fired"]:
                return
            assert len(rows) == 1
            row = rows[0]
            assert inspect(row).pending
            raw = deepcopy(row.input_snapshot)
            material = deepcopy(raw["resource_dependency_proof"]["material"])
            material["epoch"] += 1
            raw["resource_dependency_proof"] = resources._stored_fingerprint_v2(material)
            row.input_snapshot = raw
            trace["fired"] = True

        event.listen(session, "before_flush", before_flush)
        try:
            return original(session, ctx, command, product, payload, bound, pointers, mutation)
        finally:
            event.remove(session, "before_flush", before_flush)

    with monkeypatch.context() as patch:
        patch.setattr(launch, "_record", record)
        yield trace
