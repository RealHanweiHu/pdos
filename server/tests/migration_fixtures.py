"""Run a historical migration operation against the test DB, then restore all DDL."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.test_migrations import EXPECTED_HEAD


def migrate_test_database_in_steps(config: Config, engine: Engine, target: str) -> None:
    """Bound DDL locks for long historical test round trips, one revision per commit.

    Production migration transactions stay unchanged. The caller must restore
    head in a finally block because successful historical steps are committed.
    """
    expected_url = make_url(psycopg_database_url(configured_test_database_url()))
    assert engine.url == expected_url
    assert make_url(psycopg_database_url(os.environ["DATABASE_URL"])) == expected_url
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [EXPECTED_HEAD]
    revisions = list(script.walk_revisions())
    assert all(
        item.down_revision == following.revision
        for item, following in zip(revisions, revisions[1:], strict=False)
    )
    assert revisions[-1].down_revision is None
    positions = {item.revision: index for index, item in enumerate(revisions)}
    positions["base"] = len(revisions)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == "pdos_test"
        current = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    desired = EXPECTED_HEAD if target == "head" else target
    current_position = positions[current or "base"]
    target_position = positions[desired]
    # The frozen revision graph is identical for every step. Reuse the graph
    # already validated above instead of importing hundreds of migration modules
    # again for each revision. Alembic still owns each operation and transaction;
    # this test-only patch ends before the helper returns, including on failure.
    with patch("alembic.command.ScriptDirectory.from_config", return_value=script):
        if current_position < target_position:
            for revision in revisions[current_position:target_position]:
                assert isinstance(revision.down_revision, str) or revision.down_revision is None
                next_revision = revision.down_revision or "base"
                command.downgrade(config, next_revision)
        else:
            for revision in reversed(revisions[target_position:current_position]):
                command.upgrade(config, revision.revision)
    with engine.connect() as connection:
        actual = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    assert (actual or "base") == desired


@contextmanager
def rollback_migration_operations(engine: Engine) -> Iterator[Connection]:
    # The guarded fixture owns the isolated DB. Never change its Alembic version
    # or retain historical DDL in the shared current-head schema.
    with engine.connect() as connection:
        transaction = connection.begin()
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            EXPECTED_HEAD
        )
        try:
            with Operations.context(MigrationContext.configure(connection)):
                yield connection
        finally:
            transaction.rollback()
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == EXPECTED_HEAD
            )
