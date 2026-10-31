"""The shared SQL statement must still reauthorize each principal and transaction."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.enterprise_search.assistant_sources import current
from pdos_next.models import Grant, now
from tests.enterprise_search.test_retrieval_pg import index, query, register, session_for


def test_cached_statement_never_reuses_source_rows_or_requester_authority(setup):
    private = register(setup, "缓存复核本人私有", "缓存复核本人原文。", visibility="private")
    shared = register(setup, "缓存复核共享", "缓存复核共享原文。")
    for identity in (private, shared):
        index(setup, identity)
    selected = {
        str(identity): query(setup, str(identity), source_types=["artifact"])["items"][0]
        for identity in (private, shared)
    }

    def check(actor, visible):
        with session_for(setup, actor=actor, personal=True) as session:
            actual, missing = current(session, selected, with_body=True)
        assert set(actual) == {str(value) for value in visible}
        assert set(missing) == set(selected) - set(actual)
        assert all(row["body"] for row in actual.values())

    check(setup.human, (private, shared))
    check(setup.peer, (shared,))
    check(setup.human, (private, shared))
    with Session(setup.admin) as session, session.begin():
        membership = session.scalar(select(Grant).where(
            Grant.tenant_id == setup.tenant, Grant.principal_id == setup.peer,
            Grant.category_id == setup.category,
        ))
        membership.expires_at = now() - timedelta(seconds=1)
    check(setup.peer, ())
    check(setup.human, (private, shared))
    with tenant_session(
        setup.engine, setup.other_tenant, actor_id=setup.other_human,
        requester_id=setup.other_human, category_id=None, read_snapshot=True,
    ) as session:
        actual, missing = current(session, selected, with_body=True)
    assert not actual and set(missing) == set(selected)
