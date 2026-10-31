"""Feed has no message side effect, model grant or result-body projection."""

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects.postgresql import dialect

from pdos_next import personal_summary_delivery as feed
from pdos_next.errors import DomainError
from pdos_next.service import Context


def test_feed_sql_binds_actual_owner_attempt_grant_publication_and_t1_without_body():
    tenant, human = uuid4(), uuid4()
    query = feed.query(Context(tenant, human, human))
    sql = str(query.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))
    assert str(tenant) in sql and str(human) in sql
    for table in ("automation_service_attempts", "automation_service_grants",
                  "automation_rule_versions", "action_receipts"):
        assert table in sql
    assert "request_digest" in sql and "confirmation_id" in sql
    assert "automation_service" in sql and "personal-summary/v1" in sql
    projection = sql.split("FROM")[0]
    assert "groups" not in projection and "facts" not in projection
    assert "baseline" not in projection and "body" not in projection
    assert "expires_at" not in sql  # expiration stops new execution, not own historical READ


@pytest.mark.parametrize("kind,active,snapshot", [("agent", True, True), ("human", False, True),
                                                 ("human", True, False)])
def test_feed_requires_current_human_ordinary_read_snapshot(kind, active, snapshot):
    tenant, human = uuid4(), uuid4()
    ctx = Context(tenant, human, human)
    s = SimpleNamespace(info={"read_snapshot": snapshot, "scope": (tenant, human, human, None)},
                        get=lambda *_a: SimpleNamespace(kind=kind, active=active, tenant_id=tenant))
    with pytest.raises(DomainError) as error:
        feed.read(s, ctx)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_read_returns_only_actual_completed_metadata_and_matching_inbox_token():
    tenant, human, run, category = (uuid4() for _ in range(4))
    ctx, at = Context(tenant, human, human), datetime(2026, 10, 29, tzinfo=UTC)
    row = {"run_id": run, "category_id": category, "category_name": "Category", "created_at": at,
           "status": "completed", "cancel_epoch": 0, "title": "My summary", "as_of": at.isoformat()}
    class Result:
        def mappings(self):
            return self

        def all(self):
            return [row]

    s = SimpleNamespace(info={"read_snapshot": True, "scope": (tenant, human, human, None)},
                        get=lambda *_a: SimpleNamespace(
                            kind="human", active=True, tenant_id=tenant,
                        ),
                        execute=lambda *_a: Result(), scalar=lambda *_a: at,
                        no_autoflush=nullcontext())
    actual = feed.read(s, ctx)
    assert actual["principal_id"] == str(human) and actual["next_cursor"] is None
    item, = actual["items"]
    assert item["run_id"] == str(run) and item["reading_token"] == "completed:0"
    assert "result" not in item and "summary" not in item and "owner_id" not in item
