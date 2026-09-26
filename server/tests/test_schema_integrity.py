"""Whole-schema checks for the cumulative migration integration boundary."""

from collections import Counter

from sqlalchemy import UniqueConstraint, create_mock_engine

from app.db.schema import metadata


def test_constraint_names_do_not_collide_within_a_table() -> None:
    engine = create_mock_engine("postgresql+psycopg://", lambda *_args, **_kwargs: None)
    preparer = engine.dialect.identifier_preparer
    for table in metadata.tables.values():
        names = Counter(preparer.format_constraint(item) for item in table.constraints)
        repeated = {name for name, count in names.items() if count > 1}
        assert not repeated, (table.fullname, repeated)


def test_every_foreign_key_targets_a_complete_unique_key() -> None:
    for table in metadata.tables.values():
        for reference in table.foreign_key_constraints:
            target = reference.referred_table
            target_columns = {element.column.name for element in reference.elements}
            unique_keys = [{column.name for column in target.primary_key}]
            unique_keys.extend(
                {column.name for column in constraint.columns}
                for constraint in target.constraints
                if isinstance(constraint, UniqueConstraint)
            )
            unique_keys.extend(
                {column.name for column in index.columns}
                for index in target.indexes
                if index.unique and index.dialect_options["postgresql"]["where"] is None
            )
            assert target_columns in unique_keys, (
                table.fullname,
                reference.name,
                target.fullname,
                target_columns,
            )
