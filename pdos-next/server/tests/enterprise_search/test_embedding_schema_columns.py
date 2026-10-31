"""Catch declared_attr shadowing and compare all six actual ORM tables to DDL."""

import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from migrations.schema_s0_0836 import SCHEMA_SQL
from pdos_next.enterprise_search import embedding_models
from pdos_next.enterprise_search.embedding_models import EmbeddingBatch, EmbeddingCall


def test_all_actual_orm_columns_types_checks_and_declared_fields_match_create_table():
    # Exercise installed source and numbered migration. The standalone stage
    # audit is evidence only; repository tests must not depend on /tmp files.
    sql = "\n".join(SCHEMA_SQL)
    for name in (
        "EmbeddingProfileHead",
        "EmbeddingProfile",
        "EmbeddingBudget",
        "EmbeddingBatch",
        "EmbeddingCall",
        "ChunkEmbedding",
    ):
        model = getattr(embedding_models, name)
        assert set(model.__annotations__) <= set(model.__table__.columns.keys())
        compiled = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect())).strip()
        actual = (
            re.search(rf"CREATE TABLE {model.__tablename__} \(.*?\n\);", sql, re.DOTALL)
            .group(0)
            .rstrip(";")
        )
        assert " ".join(compiled.split()) == " ".join(actual.split())


def test_scope_columns_are_real_nonnull_columns_and_not_inherited_none_attributes():
    for model in (EmbeddingBatch, EmbeddingCall):
        assert model.__table__.c.category_id.nullable is False
        assert hasattr(model.category_id, "property")
        query = str(select(model).where(model.category_id == uuid4()))
        assert model.__tablename__ + ".category_id =" in query and "WHERE false" not in query


def test_disabling_never_reads_potentially_unavailable_source_projection(monkeypatch):
    from types import SimpleNamespace as NS

    from pdos_next.enterprise_search import embedding_profiles, embedding_sources
    from pdos_next.enterprise_search.embedding_schemas import SaveEmbeddingProfile
    from tests.enterprise_search.test_embedding_hybrid import metadata

    monkeypatch.setattr(embedding_profiles, "admin", lambda *_: None)

    def source_unavailable(*_args, **_kwargs):
        raise AssertionError("Stopping must not read or estimate source bodies")

    monkeypatch.setattr(embedding_sources, "readable_chunks", source_unavailable)
    budget = NS(revision=0, spent_micro_usd=0, held_micro_usd=0)
    head = NS(revision=0)
    rows = iter([budget, head])
    session = NS(info={}, execute=lambda *_: None, scalar=lambda *_: next(rows))
    ctx = NS(tenant_id=uuid4())
    command = NS(product_id=None, source_read_set=[], expected_revision=1)
    payload = SaveEmbeddingProfile(
        profile_id=uuid4(),
        expected_revision=0,
        metadata=metadata(),
        enabled=False,
        expected_budget_revision=0,
        index_budget_micro_usd=100,
    )
    value = embedding_profiles.prepared(session, ctx, command, NS(revision=1), payload)
    assert value["expected_sources"] is None and value["estimated_cost_micro_usd"] is None
    assert value["estimate_truncated"] is False
