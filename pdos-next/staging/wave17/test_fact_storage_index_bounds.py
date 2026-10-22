"""Offline index/foreign-key bounds only; no PG, writer or owner attestation."""

import fact_registry_storage as registry
import fact_storage_models as storage
import pytest
from pdos_next.errors import DomainError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.sqltypes import Uuid

# PostgreSQL B-tree v4, standard 8192-byte page and 64-bit MAXALIGN=8.
# Reserve PageHeaderData, three line pointers, BTPageOpaqueData and heap TID.
BLOCK_BYTES = 8192
ALIGN_BYTES = 8


def align(value):
    return (value + ALIGN_BYTES - 1) // ALIGN_BYTES * ALIGN_BYTES


BTREE_V4_MAX_ITEM_BYTES = (
    BLOCK_BYTES - align(24 + 3 * 4) - align(16)
) // 3 // ALIGN_BYTES * ALIGN_BYTES - align(6)


def index_keys(table):
    keys = [("primary", tuple(table.primary_key.columns))]
    keys += [
        ("unique", tuple(constraint.columns))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    keys += [("index", tuple(index.columns)) for index in table.indexes]
    return keys


def column_bytes(column):
    """Uncompressed worst UTF-8 datum bound, never assumed ASCII/compression."""
    if isinstance(column.type, Uuid):
        return 16
    if isinstance(column.type, Integer):
        return 4
    if isinstance(column.type, String) and column.type.length is not None:
        # 4-byte varlena header plus 4 bytes per Unicode scalar. Even hexadecimal
        # SHA/closed enum columns use this intentionally conservative bound.
        return 4 + 4 * column.type.length
    pytest.fail(f"Unbounded or unsupported indexed type: {column.table.name}.{column.name}")


def tuple_bound(columns):
    # Overestimate by aligning every datum separately; reserve a NULL bitmap
    # even for NOT NULL keys and one extra line pointer. No dedup/TOAST credit.
    return (
        align(8 + (len(columns) + 7) // 8)
        + sum(align(column_bytes(column)) for column in columns)
        + 4
    )


@pytest.mark.parametrize("model", storage.STAGED_MODELS)
def test_all_actual_primary_unique_and_secondary_indexes_fit_8kb_utf8_bound(model):
    assert BTREE_V4_MAX_ITEM_BYTES == 2704
    keys = index_keys(model.__table__)
    assert keys
    for kind, columns in keys:
        assert "purpose" not in {column.name for column in columns}
        size = tuple_bound(columns)
        assert size <= BTREE_V4_MAX_ITEM_BYTES, (
            model.__tablename__,
            kind,
            tuple(column.name for column in columns),
            size,
        )


def test_bound_rejects_original_long_purpose_and_2000_character_issuer_keys():
    rule = storage.RuleFact.__table__
    widest = max(index_keys(rule), key=lambda item: tuple_bound(item[1]))[1]
    # Reconstruct the original *width* without importing its old declarations
    # into shared metadata: two 2000-char issuer values and indexed purpose.
    old_bound = tuple_bound(widest) + 2 * (align(4 + 4 * 2000) - align(4 + 4 * 100))
    old_bound += align(4 + 4 * 2000)
    assert old_bound > BTREE_V4_MAX_ITEM_BYTES
    assert len("\U0010ffff".encode("utf-8")) == 4


@pytest.mark.parametrize("model", [storage.RuleFact, storage.RuleCurrent, storage.ObservationFact])
def test_issuer_limits_are_explicit_db_types_and_checks_without_truncation(model):
    table = model.__table__
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    for name in ("issuer_key", "issuer_version"):
        assert table.c[name].type.length == 100
        assert f"{name} VARCHAR(100) NOT NULL" in ddl
        assert f"length({name}) BETWEEN 1 AND 100" in ddl
        assert column_bytes(table.c[name]) == 404
    if "external_id" in table.c:
        assert table.c.external_id.type.length == 200
        assert column_bytes(table.c.external_id) == 804
    assert "substring(" not in ddl.lower() and "left(" not in ddl.lower()


@pytest.mark.parametrize("model", storage.STAGED_MODELS)
def test_full_purpose_stays_required_in_row_and_anchor_without_secondary_truth(model):
    table = model.__table__
    checks = " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert not table.c.purpose.nullable and table.c.purpose.type.length is None
    assert "length(purpose) BETWEEN 1 AND 2000" in checks
    assert "anchor_snapshot->'origin'->>'purpose'=purpose" in checks
    assert "anchor_snapshot" in table.c and "anchor_sha256" in table.c
    assert not any("purpose" in column.name and column.name != "purpose" for column in table.c)
    if "fact_body" in table.c:
        assert "(fact_body->'body')->>'purpose'=purpose" in checks


@pytest.mark.parametrize(
    "model",
    [storage.RuleFact, storage.ObservationFact, storage.RuleCurrent, storage.ObservationCurrent],
)
def test_changed_fk_targets_keep_exact_unique_scope_origin_anchor_and_series(model):
    tables = {value.__tablename__: value.__table__ for value in storage.STAGED_MODELS}
    found = 0
    for fk in model.__table__.constraints:
        if not isinstance(fk, ForeignKeyConstraint):
            continue
        target_table = fk.elements[0].column.table
        if target_table.name not in tables:
            continue
        targets = tuple(element.column.name for element in fk.elements)
        source = tuple(element.parent.name for element in fk.elements)
        actual_unique_keys = {
            tuple(column.name for column in columns)
            for kind, columns in index_keys(target_table)
            if kind in {"primary", "unique"}
        }
        assert targets in actual_unique_keys
        if "series_id" not in source:
            # Fixed Rule FK uses SCOPE/id/revision; purpose is verified by the
            # actual Rule dependency SQL, not an added hash or wider FK.
            continue
        found += 1
        assert "purpose" not in source and "purpose" not in targets
        assert set(storage.INDEX_BINDING + ("series_id",)) <= set(source)
        assert set(storage.SCOPE) <= set(targets)
        assert fk.deferrable and fk.initially == "DEFERRED"
    assert found >= 1


def test_rule_current_series_key_retains_full_anchor_and_external_identity():
    keys = {
        tuple(column.name for column in constraint.columns)
        for constraint in storage.RuleCurrent.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert storage.SCOPE + ("anchor_sha256", "issuer_key", "external_id") in keys
    assert storage.SCOPE + ("series_id",) in keys


def test_existing_registry_semantic_binding_still_rejects_purpose_change():
    assert "purpose" in storage.BINDING
    assert storage.INDEX_BINDING == tuple(c for c in storage.BINDING if c != "purpose")
    # Exercise the actual unchanged owner helper, not a second comparison.
    # These dictionaries are structural inputs only, not any live owner proof.
    original = {key: f"fixed-{key}" for key in storage.BINDING}
    original["anchor_snapshot"] = {"origin": {"purpose": original["purpose"]}}
    registry._Read._same_binding(None, original, dict(original))
    changed = dict(original, purpose="different actual purpose")
    with pytest.raises(DomainError) as error:
        registry._Read._same_binding(None, original, changed)
    assert error.value.code == "FACT_SERIES_SCOPE_OR_ANCHOR_MISMATCH"


@pytest.mark.parametrize("model", storage.STAGED_MODELS)
def test_offline_ddl_includes_declared_secondary_indexes(model):
    table = model.__table__
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert f"CREATE TABLE {table.name}" in ddl
    indexes = sorted(table.indexes, key=lambda index: index.name)
    assert len(indexes) == 1
    assert tuple(column.name for column in indexes[0].columns) == ("tenant_id",)
    assert str(CreateIndex(indexes[0]).compile(dialect=postgresql.dialect())) == (
        f"CREATE INDEX ix_{table.name}_tenant_id ON {table.name} (tenant_id)"
    )
