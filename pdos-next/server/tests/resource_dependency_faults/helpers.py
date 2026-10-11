"""Root may call these on an already prepared, NOT YET saved Start.

No test fixture is defined: reuse the existing real-window parent case. The
Root must have verified TEST_DATABASE_URL/marker/head29 before calling.
"""

from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.test_resources.models import TestResourceReservation
from pdos_next.models import Confirmation
from pdos_next.service import digest, execute

from .faults import (
    FAULT_CODE,
    MISSING_GROUP_MESSAGE,
    WRONG_PROOF_MESSAGE,
    fail_after_final_common_flush,
    mismatch_pending_original_start_proof,
    require_deferred_atom_before_common_key,
    snapshot,
)


def _baseline(work, prepared):
    """Verify the precondition instead of claiming a fault against a replayed Run."""
    command = Command.model_validate(prepared)
    assert command.operation == "test.run.start"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        assert (
            session.scalar(
                select(TestResourceReservation.id).where(
                    TestResourceReservation.tenant_id == work.setup.tenant,
                    TestResourceReservation.run_id == UUID(command.payload["run_id"]),
                )
            )
            is None
        )
        token_hash = digest(command.payload["confirmation_token"])
        assert (
            session.scalar(
                select(Confirmation.consumed).where(
                    Confirmation.tenant_id == work.setup.tenant,
                    Confirmation.token_hash == token_hash,
                )
            )
            is False
        )
        return command, snapshot(session, work.setup.tenant)


def _unchanged(work, baseline):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        assert snapshot(session, work.setup.tenant) == baseline


def one_api_fault_and_lawful_retry(work, prepared, monkeypatch):
    """Smallest recommended addition: one failed real HTTP Tx and exact retry."""
    command, baseline = _baseline(work, prepared)
    with fail_after_final_common_flush(monkeypatch, command) as trace:
        failed = work.quality.client.post(
            f"/v1/categories/{work.setup.category}/commands",
            json=deepcopy(prepared),
            headers=work.quality.headers,
        )
    assert failed.status_code == 409, failed.text
    assert failed.json()["detail"]["reason"] == FAULT_CODE
    assert trace == {"attached": True, "armed": True, "fired": True, "flushed_common_rows": 4}
    _unchanged(work, baseline)
    # Same command/idempotency/read set/token/actual event. No fresh preview,
    # renewed grant, advanced clock, extra Start or new future-window fixture.
    retried = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/commands",
        json=deepcopy(prepared),
        headers=work.quality.headers,
    )
    assert retried.status_code == 200, retried.text
    return retried.json(), deepcopy(prepared), trace


def deferred_negatives_before_retry(work, prepared, monkeypatch):
    """Optional two actual DDL negatives, all before the final successful Start.

    Every attempt is a fresh outer caller transaction, same lawful event and
    confirmed request. Both failures must leave all complete rows unchanged.
    Do not call after one_api_fault_and_lawful_retry saved the original Run.
    """
    command, baseline = _baseline(work, prepared)
    with require_deferred_atom_before_common_key(monkeypatch, command) as missing:
        with pytest.raises(DBAPIError, match=MISSING_GROUP_MESSAGE):
            with tenant_session(
                work.setup.engine,
                work.setup.tenant,
                actor_id=work.quality.ctx.actor_id,
                requester_id=work.quality.ctx.requester_id,
                category_id=work.setup.category,
            ) as session:
                execute(session, work.quality.ctx, command)
    assert missing["fired"]
    _unchanged(work, baseline)
    with mismatch_pending_original_start_proof(monkeypatch, command) as wrong:
        with pytest.raises(DBAPIError, match=WRONG_PROOF_MESSAGE):
            with tenant_session(
                work.setup.engine,
                work.setup.tenant,
                actor_id=work.quality.ctx.actor_id,
                requester_id=work.quality.ctx.requester_id,
                category_id=work.setup.category,
            ) as session:
                execute(session, work.quality.ctx, command)
                session.execute(text("SET CONSTRAINTS test_resource_dependency_required IMMEDIATE"))
    assert wrong["fired"]
    _unchanged(work, baseline)
    return {"missing_common_group_rejected": True, "wrong_complete_start_proof_rejected": True}
