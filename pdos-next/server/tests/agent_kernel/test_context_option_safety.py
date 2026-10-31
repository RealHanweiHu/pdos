"""SQL ordering/selection contracts only; ordinary PG and scan proofs are separate."""

from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from sqlalchemy import ARRAY, Boolean, Engine, Integer, String, column, select, table
from sqlalchemy.dialects.postgresql import UUID, dialect

from pdos_next.agent_kernel import context_corrections
from pdos_next.enterprise_search import assistant_sources, context_option_safety, sources


def catalog():
    return table(
        "native_option_catalog",
        column("tenant_id", UUID),
        column("category_id", UUID),
        column("source_type", String),
        column("source_id", UUID),
        column("source_revision", Integer),
        column("object_id", UUID),
        column("title", String),
        column("is_current", Boolean),
        column("original_ids", ARRAY(UUID)),
        column("body", String),
        column("structured", String),
    )


def sql(statement):
    return str(statement.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("pure option tests cannot connect to PostgreSQL")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)


def test_original_proofs_cover_all_matching_keys_without_title_or_page_materialization(monkeypatch):
    source, tenant, category = catalog(), uuid4(), uuid4()
    statement = select(source.c.source_id, source.c.title).where(
        source.c.tenant_id == tenant,
        source.c.category_id == category,
        source.c.title.icontains("literal%_", autoescape=True),
    )
    originals = {uuid4() for _ in range(43)}
    safe = set(sorted(originals)[:1])
    session = object()
    calls = []

    class MetadataSession:
        def scalars(self, candidates):
            assert set(candidates.selected_columns.keys()) == {"original_id"}
            query = sql(candidates)
            assert "SELECT DISTINCT unnest(" in query
            assert "LIMIT" not in query and "ORDER BY" not in query
            assert str(tenant) in query and str(category) in query
            assert "ESCAPE '/'" in query and "literal/%/_" in query.replace("%%", "%")
            assert "native_option_catalog.title," not in query
            assert "body" not in query and "structured" not in query
            calls.append("dependencies")
            return originals

    session = MetadataSession()

    def check(actual, identities):
        assert actual is session and identities == originals
        calls.append("actual_scan_gate")
        return safe

    monkeypatch.setattr(context_option_safety, "safe_originals", check)
    filtered = context_option_safety.before_paging(session, source, statement)
    query = sql(filtered.order_by(source.c.title).limit(41))
    assert calls == ["dependencies", "actual_scan_gate"]
    assert "original_ids <@ ARRAY[" in query
    assert str(next(iter(safe))) in query
    assert all(str(identity) not in query for identity in originals - safe)
    assert query.index("<@") < query.index("ORDER BY") < query.index("LIMIT 41")
    assert list(filtered.selected_columns) == list(statement.selected_columns)


def test_no_safe_originals_still_allows_sources_without_originals_and_never_skips_gate(monkeypatch):
    source, original = catalog(), uuid4()
    seen = []
    monkeypatch.setattr(
        context_option_safety, "safe_originals", lambda _s, ids: seen.append(ids) or set()
    )
    query = sql(
        context_option_safety.before_paging(
            NS(scalars=lambda _q: [original]), source, select(source.c.source_id)
        )
    )
    assert seen == [{original}]
    assert "original_ids <@ ARRAY[]::UUID[]" in query
    assert "false" not in query.lower() and "is_current" not in query


def option_case(monkeypatch, *, count=41, historical=False):
    source = catalog()
    run = NS(tenant_id=uuid4(), category_id=uuid4())
    rows = [
        {
            "source_type": "knowledge",
            "source_id": uuid4(),
            "object_id": uuid4(),
            "source_revision": 2,
            "title": f"Actually eligible {index:03}",
            "is_current": not historical,
        }
        for index in range(count)
    ]
    events = []
    monkeypatch.setattr(sources, "prepare_read", lambda *_a: events.append("prepare"))
    monkeypatch.setattr(sources, "retrieval_catalog", lambda _kinds: source)
    monkeypatch.setattr(
        context_option_safety, "safe_originals", lambda *_a: events.append("scan_gate") or set()
    )

    def current(_s, candidates):
        events.append("final_current")
        assert len(candidates) == count
        return candidates, {}

    monkeypatch.setattr(assistant_sources, "current", current)

    class Session:
        def scalars(self, statement):
            events.append(sql(statement))
            return []

        def execute(self, statement):
            text = sql(statement)
            assert events[-1] == "scan_gate"
            assert "<@" in text and "LIMIT 41" in text
            assert "body" not in statement.selected_columns.keys()
            events.append(text)
            return NS(mappings=lambda: NS(all=lambda: rows))

    return Session(), run, rows, events


@pytest.mark.parametrize("count", [0, 1, 40, 41])
def test_actual_options_hook_pages_only_eligible_metadata_and_keeps_current_defense(
    monkeypatch,
    count,
):
    session, run, rows, events = option_case(monkeypatch, count=count)
    value = context_corrections.options(session, None, run, "Actually eligible")
    assert value["has_more"] is (count > 40)
    assert value["items"] == [
        {**row, "source_id": str(row["source_id"]), "object_id": str(row["object_id"])}
        for row in rows[:40]
    ]
    assert events[-1] == "final_current"
    assert "LIMIT" not in events[1]
    assert value["artifact_history"] == "unavailable"


def test_object_history_query_keeps_native_version_identity_instead_of_forcing_current(monkeypatch):
    session, run, rows, events = option_case(monkeypatch, count=1, historical=True)
    identity = rows[0]["object_id"]
    value = context_corrections.options(session, None, run, "", object_id=identity)
    assert str(identity) in events[1]
    assert "is_current =" not in events[1]
    assert value["items"][0]["source_revision"] == 2
    assert value["items"][0]["is_current"] is False


def test_blank_chooser_does_not_issue_a_broad_dependency_or_scan_read(monkeypatch):
    session, run, _rows, events = option_case(monkeypatch, count=0)
    assert context_corrections.options(session, None, run, " ") == {"items": [], "has_more": False}
    assert events == ["prepare"]


def test_actual_nine_family_catalog_and_metadata_scan_query_compile_without_cte_collision():
    from pdos_next.enterprise_search.schemas import SOURCE_TYPES

    source = sources.retrieval_catalog(SOURCE_TYPES)
    statement = select(*[c for c in source.c if c.key not in {"body", "structured"}]).where(
        source.c.tenant_id == uuid4(),
        source.c.category_id == uuid4(),
        source.c.title.icontains("literal", autoescape=True),
    )
    seen = []

    class MetadataOnly:
        def scalars(self, query):
            assert set(query.selected_columns.keys()) == {"original_id"}
            compiled = sql(query)
            assert "LIMIT" not in compiled and "SELECT DISTINCT unnest(" in compiled
            seen.append(compiled)
            return []

    # With no original IDs the real safe_originals path reads no runtime or DB.
    query = context_option_safety.before_paging(MetadataOnly(), source, statement)
    assert seen and "LIMIT 41" in sql(query.limit(41))
    assert "is_current = true" not in sql(query.limit(41)).lower()
