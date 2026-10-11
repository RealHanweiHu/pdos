"""PostgreSQL history cursors preserve equal clocks and mixed fact families."""

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import DateTime, String, Uuid, column, select, values

from pdos_next.capa_history import page_query, page_rows
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError


def index(rows):
    return (
        values(
            column("created_at", DateTime(timezone=True)),
            column("id", Uuid),
            column("kind", String),
            name="synthetic_history",
        )
        .data(rows)
        .alias()
    )


def test_history_cursor_preserves_equal_clocks_mixed_kinds_and_concurrent_newer_rows(setup):
    at = datetime(2026, 10, 8, tzinfo=UTC)
    original = [
        (at, UUID(int=n), kind) for n in range(1, 28) for kind in ("rule", "observation", "review")
    ]
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
        read_snapshot=True,
    ) as s:
        collected, cursor, rows = [], None, original
        while True:
            table = index(rows)
            page, metadata = page_rows(
                s.execute(
                    page_query(select(table), table.c.created_at, table.c.id, table.c.kind, cursor)
                ),
                "kind",
            )
            collected.extend((row.created_at, row.id, row.kind) for row in page)
            cursor = metadata["next_cursor"]
            if cursor is None:
                break
            # A newly appended, later record must neither duplicate nor skip
            # records remaining behind the saved cursor.
            rows = [*original, (at + timedelta(seconds=1), UUID(int=1000), "rule")]
    assert collected == sorted(original, reverse=True)
    assert len(collected) == len(set(collected))


@pytest.mark.parametrize(
    "cursor",
    [
        "%",
        "null",
        "W10",
        base64.urlsafe_b64encode(
            json.dumps(["2026-10-08T00:00:00", str(UUID(int=1)), "rule"]).encode()
        ).decode(),
        base64.urlsafe_b64encode(
            json.dumps(["2026-10-08T00:00:00+00:00", "bad", "rule"]).encode()
        ).decode(),
    ],
)
def test_malformed_history_cursor_is_validation_failure(cursor):
    table = index([(datetime.now(UTC), UUID(int=1), "rule")])
    with pytest.raises(DomainError) as caught:
        page_query(select(table), table.c.created_at, table.c.id, table.c.kind, cursor)
    assert caught.value.code == "VALIDATION_FAILED"
