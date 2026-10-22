"""Actual deferred proof pairing across a SAVEPOINT and its rollback."""

from uuid import UUID

import pytest
from quality_followup_transactions.fixtures import complete_command, fixed_issue, root_command
from quality_followup_transactions.test_transactions import prepared
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.models import Confirmation
from pdos_next.service import digest, execute

pytest_plugins = ["quality_followup_transactions.fixtures"]


def test_actual_followup_savepoint_commits_and_orphan_consumption_rolls_back(followup_work):
    work = followup_work
    before = fixed_issue(work)
    approved = Command.model_validate(prepared(work, root_command(work)))
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        with session.begin_nested():
            receipt = execute(session, work.quality.ctx, approved)
            saved = UUID(str(receipt["subject_id"]))
        # The deferred counterpart pair must survive a released SAVEPOINT.
    current = fixed_issue(work)
    assert current.id == saved and current.revision == before.revision + 1
    assert current.issue_snapshot["root_cause"] is not None
    assert fixed_issue(work, before.revision).issue_snapshot == before.issue_snapshot

    completion = prepared(work, complete_command(work))
    token_hash = digest(completion["payload"]["confirmation_token"])
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        confirmation = session.scalar(
            select(Confirmation).where(Confirmation.token_hash == token_hash)
        )
        assert confirmation is not None and confirmation.consumed is False
        proof_id = confirmation.id
        with pytest.raises(DBAPIError) as rejected:
            with session.begin_nested():
                session.execute(
                    text("UPDATE confirmations SET consumed=true WHERE id=:id"),
                    {"id": proof_id},
                )
                session.execute(text("SET CONSTRAINTS quality_followup_proof_required IMMEDIATE"))
        assert getattr(rejected.value.orig, "sqlstate", None) == "P0001"
        session.expire_all()
        assert session.get(Confirmation, proof_id).consumed is False
    assert fixed_issue(work).id == current.id
    assert all(action["completion"] is None for action in current.issue_snapshot["capa"]["actions"])
