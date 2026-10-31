"""Source-grain SQL controls only; no database or embedding execution."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import CTE

from pdos_next.enterprise_search import embedding_hybrid as hybrid
from pdos_next.enterprise_search import embedding_sources as sources
from pdos_next.enterprise_search.schemas import SOURCE_TYPES, SearchInput
from tests.enterprise_search.test_embedding_ann_sql import ScanSession

METADATA_FIELDS = (
    "source_type",
    "source_id",
    "object_id",
    "source_revision",
    "content_hash",
    "title",
    "category_id",
    "product_id",
    "project_id",
    "proposal_id",
    "nature",
    "private",
    "customer_original",
    "is_current",
    "read_basis_status",
)


@pytest.fixture
def authority_context(monkeypatch):
    tenant, category, actor, original = (uuid4() for _ in range(4))
    ctx = SimpleNamespace(
        tenant_id=tenant, category_id=category, actor_id=actor, requester_id=actor
    )
    monkeypatch.setattr(
        sources,
        "_narrow",
        lambda *_: {
            "category_id": category,
            "product_id": None,
            "project_id": None,
            "proposal_id": None,
        },
    )
    monkeypatch.setattr(sources, "prepare_read", lambda *_: None)
    monkeypatch.setattr(sources, "dependency_originals", lambda *_: {original})

    def scan_proof(_session, identities):
        assert identities == {original}
        return {original}

    monkeypatch.setattr(sources, "safe_originals", scan_proof)
    return ctx, original


def scoped_source(statement):
    return next(
        node
        for node in visitors.iterate(statement)
        if isinstance(node, CTE) and node.name == "embedding_scoped_authority"
    )


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize("families", [["artifact"], sorted(SOURCE_TYPES)], ids=["artifact", "all"])
def test_source_spool_has_only_required_metadata_and_preserves_authority_and_chunk_guards(
    authority_context, families
):
    ctx, original = authority_context
    included, excluded = uuid4(), uuid4()
    data = SearchInput(
        query="synthetic SQL control",
        source_types=families,
        after=datetime(2026, 10, 1, tzinfo=UTC),
        before=datetime(2026, 10, 30, tzinfo=UTC),
    )
    filters = {
        "include_sources": [("artifact", included, 3, "b" * 64)],
        "exclude_sources": [("artifact", excluded)],
        "current_only": True,
        "allow_customer_private": False,
    }
    baseline = sources.readable_chunks(object(), ctx, data, **filters)
    materialized = sources.readable_chunks(
        object(), ctx, data, materialize_authority=True, **filters
    )
    old_source, new_source = scoped_source(baseline), scoped_source(materialized)
    assert "embedding_scoped_authority AS MATERIALIZED" not in sql(baseline)
    assert "embedding_scoped_authority AS MATERIALIZED" in sql(materialized)
    assert {column.key for column in new_source.element.selected_columns} == {
        *METADATA_FIELDS,
        "tenant_id",
        "original_ids",
        "created_at",
    }
    assert {"body", "structured"} <= set(old_source.c.keys())
    assert {"body", "structured"}.isdisjoint(new_source.c.keys())
    assert list(baseline.selected_columns.keys()) == list(materialized.selected_columns.keys())
    assert [sql(clause) for clause in old_source.element._where_criteria] == [
        sql(clause) for clause in new_source.element._where_criteria
    ]
    assert [sql(clause) for clause in baseline._where_criteria] == [
        sql(clause) for clause in materialized._where_criteria
    ]
    assert [sql(join[1]) for join in baseline._setup_joins] == [
        sql(join[1]) for join in materialized._setup_joins
    ]
    compiled = materialized.compile(dialect=postgresql.dialect())
    text = str(compiled)
    for predicate in (
        "enterprise_search_chunks.tenant_id = embedding_scoped_authority.tenant_id",
        "enterprise_search_chunks.category_id = embedding_scoped_authority.category_id",
        "enterprise_search_chunks.source_revision = embedding_scoped_authority.source_revision",
        "enterprise_search_chunks.content_hash = embedding_scoped_authority.content_hash",
        "enterprise_search_sources.work_key = enterprise_search_chunks.work_key",
        "enterprise_search_sources.source_revision = enterprise_search_chunks.source_revision",
        "enterprise_search_sources.content_hash = enterprise_search_chunks.content_hash",
        "enterprise_search_sources.last_error IS NULL",
        "enterprise_search_chunks.tokenizer_version =",
        "enterprise_search_chunks.code_rule_version =",
        "enterprise_search_chunks.chunker_version =",
        "embedding_scoped_authority.original_ids <@",
        "embedding_scoped_authority.created_at >=",
        "embedding_scoped_authority.created_at <",
    ):
        assert predicate in text
    assert original in compiled.params.values()
    assert "ready" in compiled.params.values()
    assert any(
        ("artifact", included, 3, "b" * 64) in value
        for value in compiled.params.values()
        if isinstance(value, list)
    )


def test_fixed_batch_reader_keeps_inline_source_and_exact_id_hash_binding(authority_context):
    ctx, _original = authority_context
    chunk, source_id = uuid4(), uuid4()
    manifest = {
        "chunks": [
            {
                "chunk_id": str(chunk),
                "source_type": "artifact",
                "source_id": str(source_id),
                "source_revision": 3,
                "content_hash": "b" * 64,
                "chunk_hash": "a" * 64,
                "work_key": "c" * 64,
            }
        ]
    }
    observed = []

    def execute(statement):
        observed.append(statement)
        row = {**manifest["chunks"][0], "chunk_id": chunk, "source_id": source_id}
        return SimpleNamespace(mappings=lambda: [row])

    rows = sources.fixed_rows(SimpleNamespace(execute=execute), ctx, manifest)
    assert len(rows) == len(observed) == 1
    statement = observed[0]
    assert "embedding_scoped_authority AS MATERIALIZED" not in sql(statement)
    assert "text" in statement.selected_columns.keys()
    assert [chunk] in statement.compile(dialect=postgresql.dialect()).params.values()


@pytest.mark.parametrize("strategy", ["exact", "iterative"])
def test_only_semantic_owner_enables_source_grain_materialization(
    monkeypatch, authority_context, strategy
):
    ctx, _original = authority_context
    requested = []

    def readable(session, context, data, **options):
        requested.append(options)
        return sources.readable_chunks(session, context, data, **options)

    class MaterializedScan(ScanSession):
        def execute(self, statement):
            if not sql(statement).startswith("SET LOCAL"):
                assert "embedding_scoped_authority AS MATERIALIZED" in sql(statement)
            return super().execute(statement)

    monkeypatch.setattr(hybrid, "readable_chunks", readable)
    monkeypatch.setattr(hybrid, "active", lambda *_: (None, SimpleNamespace(dimensions=2)))
    evidence = {}
    rows = hybrid.semantic_rows(
        MaterializedScan(1001, [11]),
        ctx,
        SearchInput(query="synthetic SQL control", source_types=["artifact"], limit=10),
        uuid4(),
        (1.0, 0.0),
        strategy=strategy,
        scan_evidence=evidence,
    )
    assert requested == [{"materialize_authority": True}]
    assert len(rows) == 11 and evidence["executed_strategy"] == strategy
