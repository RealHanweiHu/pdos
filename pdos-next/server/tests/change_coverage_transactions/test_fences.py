"""Real permission row locks; no coverage qualification or publication is claimed."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.change_coverage_owner import owner
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product, now
from pdos_next.service import Context


def test_actual_publisher_a_reader_b_fenced_until_transaction_end(setup):
    ctx = Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category)

    def revoke(model, identity):
        try:
            with Session(setup.admin) as session, session.begin():
                session.execute(text("SET LOCAL lock_timeout='500ms'"))
                if model is Principal:
                    session.execute(
                        update(Principal).where(Principal.id == identity).values(active=False)
                    )
                else:
                    session.execute(
                        update(Grant)
                        .where(Grant.principal_id == identity, Grant.category_id == setup.category)
                        .values(can_write=False)
                    )
        except DBAPIError as error:
            return error.orig.sqlstate
        return "COMMITTED"

    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=setup.category,
    ) as session:
        session.scalar(select(Product).where(Product.id == setup.product).with_for_update())
        before, until = owner.lock_people(session, ctx, setup.product, setup.human)
        assert {row[0] for row in before} == {setup.human, setup.peer} and until > now()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(revoke, Principal, setup.human).result(timeout=5) == "55P03"
            assert pool.submit(revoke, Grant, setup.human).result(timeout=5) == "55P03"
        assert owner.lock_people(session, ctx, setup.product, setup.human)[0] == before
    assert revoke(Principal, setup.human) == "COMMITTED"
    with (
        pytest.raises(DomainError) as inactive,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=setup.category,
        ) as session,
    ):
        owner.lock_people(session, ctx, setup.product, setup.human)
    assert inactive.value.status == 403


@pytest.mark.parametrize("field", ["can_write", "expires_at", "access_epoch"])
def test_actual_pending_grant_revocation_never_reset_by_fresh_lock(setup, field):
    with (
        pytest.raises(DomainError),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.ctx.actor_id,
            requester_id=setup.ctx.requester_id,
            category_id=setup.category,
        ) as session,
    ):
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        )
        value = (
            False
            if field == "can_write"
            else now() - timedelta(seconds=1)
            if field == "expires_at"
            else grant.access_epoch + 1
        )
        setattr(grant, field, value)
        saved = deepcopy(grant.__dict__[field])
        try:
            owner.lock_people(session, setup.ctx, setup.product, setup.peer)
        finally:
            assert grant.__dict__[field] == saved
