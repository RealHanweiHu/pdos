"""Read projection boundaries and stable scope-bound pagination."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.errors import DomainError
from pdos_next.project_activity import _cursor, _decode, _refs, activity_records
from pdos_next.service import Context


def test_cursor_preserves_watermark_and_rejects_rebinding_and_future():
    point = datetime(2026, 10, 18, tzinfo=UTC)
    scope = [str(uuid4()) for _ in range(5)]
    row = {"id": uuid4(), "recorded_at": point - timedelta(seconds=1)}
    cursor = _cursor(scope, point, row)
    assert _decode(cursor, scope, point + timedelta(seconds=5)) == (
        point,
        (row["recorded_at"], row["id"]),
    )
    for other in (scope[:4] + [str(uuid4())], [str(uuid4())] + scope[1:]):
        with pytest.raises(DomainError) as error:
            _decode(cursor, other, point)
        assert error.value.status == 403
    with pytest.raises(DomainError):
        _decode(cursor, scope, point - timedelta(seconds=1))


@pytest.mark.parametrize("value", ["bad=", "!", "x" * 2049, "", "null"])
def test_invalid_cursor_is_never_treated_as_first_page(value):
    with pytest.raises(DomainError):
        _decode(value, [], datetime.now(UTC))


def test_reference_metadata_drops_embedded_text_and_preserves_versions():
    identity = str(uuid4())
    values = [
        {
            "kind": "artifact",
            "id": identity,
            "revision": 2,
            "position": "line:2",
            "content": "PRIVATE",
            "quote": "SECRET",
        }
    ]
    assert _refs(values) == [
        {"kind": "artifact", "id": identity, "revision": 2, "position": "line:2"}
    ]
    assert _refs(values, tasks=True) == [{"id": identity, "revision": 2}]


def test_union_selects_no_complete_documents_or_conversations():
    ctx = Context(uuid4(), uuid4(), uuid4(), category_id=uuid4())
    query = activity_records(ctx, uuid4(), uuid4())
    sql = str(query.select().compile(dialect=postgresql.dialect()))
    for private in (
        "agent_sessions",
        "agent_run_versions",
        "agent_messages",
        "source_basis",
        "command_body",
        "content_hash",
    ):
        assert private not in sql
    assert "outbox_events.schema_version" in sql and "outbox_events.correlation_id" in sql
    assert "action_receipts.subject_revision" in sql
    # Only explicit JSON subfields appear when a source uses a frozen body.
    assert not any(
        str(column).endswith(".body")
        for branch in query.element.selects
        for column in branch.selected_columns
    )


def test_registered_activity_links_name_real_workspaces_not_fixed_record_details():
    from pdos_next.project_activity import LINK_LABELS
    from pdos_next.project_activity_catalog import SOURCES

    assert {source.view for source in SOURCES} <= set(LINK_LABELS)
    assert all(label.startswith("打开") for label in LINK_LABELS.values())
    assert LINK_LABELS["plan"] == "打开工作与计划"
