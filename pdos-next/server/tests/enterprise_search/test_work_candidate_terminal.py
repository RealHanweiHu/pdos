"""Completed candidates remain readable; starting new work still requires an active Run."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_next.enterprise_search import work_followup_candidates as candidates
from pdos_next.errors import DomainError
from pdos_next.service import Context


@pytest.fixture
def case():
    tenant, human, category = uuid4(), uuid4(), uuid4()
    ctx = Context(tenant, human, human, category_id=category)
    session = SimpleNamespace(info={"scope": (tenant, human, human, category)})
    run = SimpleNamespace(
        id=uuid4(), tenant_id=tenant, requester_id=human, writer_id=uuid4(),
        category_id=category, product_id=uuid4(), project_id=uuid4(), proposal_id=None,
        session_id=uuid4(), private_context=False, data_categories=["internal"],
        customer_identities=[], state="completed", trigger="conversation", cancel_epoch=0,
        reverted_at=None,
    )
    return SimpleNamespace(session=session, ctx=ctx, run=run)


@pytest.mark.parametrize("state", ["completed", "partial", "failed"])
def test_terminal_native_candidate_is_readable_but_cannot_prepare_another_model_write(case, state):
    case.run.state = state
    assert candidates._run(case.session, case.ctx, case.run) is case.run
    with pytest.raises(DomainError) as failure:
        candidates._run(case.session, case.ctx, case.run, creating=True)
    assert failure.value.code == "CANCELLED_RUN"
    assert "已结束运行" in failure.value.message


@pytest.mark.parametrize("state", ["queued", "running", "waiting_input"])
def test_active_native_candidate_creation_still_uses_the_original_binding(case, state):
    case.run.state = state
    assert candidates._run(case.session, case.ctx, case.run, creating=True) is case.run


@pytest.mark.parametrize("revoked", ["cancelled", "reverted"])
def test_terminal_read_does_not_restore_cancelled_or_reverted_candidate(case, revoked):
    if revoked == "cancelled":
        case.run.state = "cancelled"
    else:
        case.run.reverted_at = object()
    with pytest.raises(DomainError) as failure:
        candidates._run(case.session, case.ctx, case.run)
    assert failure.value.code == "CANCELLED_RUN"
    assert "取消或撤回" in failure.value.message


def test_terminal_read_still_rejects_the_event_from_a_previous_cancel_epoch(case):
    case.run.cancel_epoch = 1
    event = SimpleNamespace(
        tenant_id=case.run.tenant_id, run_id=case.run.id,
        body={"type": "domain_candidate", "kind": candidates.KIND, "version": 1,
              "cancel_epoch": 0},
    )
    with pytest.raises(DomainError) as failure:
        candidates.read(case.session, case.ctx, case.run, event)
    assert failure.value.code == "FORBIDDEN_SCOPE"


def test_completed_candidate_cannot_be_read_through_another_humans_transaction(case):
    case.session.info["scope"] = (case.run.tenant_id, uuid4(), uuid4(), case.run.category_id)
    with pytest.raises(DomainError) as failure:
        candidates._run(case.session, case.ctx, case.run)
    assert failure.value.code == "FORBIDDEN_SCOPE"
