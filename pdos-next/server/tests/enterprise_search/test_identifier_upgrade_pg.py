"""An existing derived rule version is replaced by the normal rebuild path."""

from pdos_next.enterprise_search import indexing
from pdos_next.enterprise_search.models import SearchChunk
from pdos_next.enterprise_search.tokenizer import CODE_RULE
from pdos_next.models import Artifact, Receipt
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.enterprise_search.test_retrieval_pg import index, query, register, session_for


def test_identifier_rule_version_rebuild_preserves_native_artifact_and_receipts(setup, monkeypatch):
    identity = register(setup, "首件检查记录", "资料编号：FA-2026-029；高度为21.00 mm。")
    # Build a predecessor-tagged projection, then restore the installed rule.
    # This tests version/work-key replacement, not a replay of the old parser.
    with monkeypatch.context() as patch:
        patch.setattr(indexing, "CODE_RULE", "enterprise-codes/v1")
        assert index(setup, identity)["status"] == "ready"
    with session_for(setup) as session:
        old = session.scalars(select(SearchChunk)).one()
        previous_key = old.work_key
        assert old.code_rule_version == "enterprise-codes/v1"

    def native_snapshot():
        with Session(setup.admin) as session:
            row = session.get(Artifact, identity)
            return (
                row.content, row.content_hash, row.revision, row.visibility, row.status,
                session.scalar(select(func.count()).select_from(Receipt).where(
                    Receipt.tenant_id == setup.tenant,
                )),
            )

    before = native_snapshot()
    assert indexing.rebuild(setup.engine, setup.ctx)["processed"] == 1
    with session_for(setup) as session:
        current = session.scalars(select(SearchChunk)).one()
        assert current.code_rule_version == CODE_RULE == "enterprise-codes/v2"
        assert current.work_key != previous_key and "FA-2026-029" in current.codes
    found = query(setup, "FA-2026-029这份检查记录")
    assert found["query_trace"]["codes"] == ["FA-2026-029"]
    assert found["items"][0]["source_id"] == str(identity)
    assert found["items"][0]["channel"] == "exact_code"
    assert native_snapshot() == before
