"""Derived scan hints retain native original authority and old-row fallback."""

# ruff: noqa: F401,F811 -- register the original upload/scan/parse fixture
from dataclasses import replace

from pdos_next.database import tenant_session
from pdos_next.enterprise_search.models import SearchSource
from pdos_next.enterprise_search.query import SearchInput, search
from pdos_next.models import OriginalSecurity
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from tests.enterprise_search.test_retrieval_pg import index
from tests.test_original_security import parsed, scan, security_work, uploaded


def test_scan_target_cache_falls_back_and_never_grants_original_readability(setup, security_work):
    first = uploaded(security_work, visibility="private", content=b"Original cachemarker evidence")
    identity = parsed(security_work, first)
    other = uploaded(security_work, visibility="category", content=b"Unrelated public original")
    other_identity = parsed(security_work, other)
    index(setup, identity)
    index(setup, other_identity)

    def hint(value):
        with Session(setup.admin) as session, session.begin():
            row = session.scalar(select(SearchSource).where(
                SearchSource.tenant_id == setup.tenant,
                SearchSource.source_type == "artifact", SearchSource.source_id == identity,
            ))
            assert row is not None
            row.original_ids = value

    def read(person):
        statements = []

        def track(*args):
            statements.append(args[2])

        event.listen(setup.engine, "before_cursor_execute", track)
        try:
            with tenant_session(setup.engine, setup.tenant, actor_id=person,
                                requester_id=person, read_snapshot=True) as session:
                value = search(session, replace(setup.ctx, actor_id=person,
                               requester_id=person, category_id=None),
                               SearchInput(query="cachemarker", source_types=["artifact"]))
        finally:
            event.remove(setup.engine, "before_cursor_execute", track)
        return value, len(statements)

    with Session(setup.admin) as session:
        assert session.scalar(select(SearchSource.original_ids).where(
            SearchSource.source_id == identity, SearchSource.tenant_id == setup.tenant,
        )) == [first]
    cached, cached_sql = read(setup.human)
    assert cached["coverage"]["status"] == "current"
    assert str(identity) in {row["source_id"] for row in cached["items"]}
    hint(None)
    legacy, legacy_sql = read(setup.human)
    assert legacy["items"] == cached["items"]
    assert legacy_sql == cached_sql + 1
    # A clean but unrelated hint cannot substitute the real private root.
    hint([other])
    wrong, _ = read(setup.human)
    assert str(identity) not in {row["source_id"] for row in wrong["items"]}
    peer, _ = read(setup.peer)
    assert str(identity) not in {row["source_id"] for row in peer["items"]}
    hint([first])
    before_scan = security_work.scanner.calls
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category) as session:
        epoch = session.scalar(select(OriginalSecurity.epoch).where(
            OriginalSecurity.original_id == first,
        ))
    scan(security_work, first, expected_epoch=epoch)
    pending, _ = read(setup.human)
    assert str(identity) not in {row["source_id"] for row in pending["items"]}
    assert security_work.scanner.calls == before_scan
