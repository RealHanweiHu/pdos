"""Exercise downgrade refusal against committed synthetic proposal data."""

# ruff: noqa: F811 -- imported pytest fixture
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from migrations.versions.s0_0729_preproject_g0 import downgrade
from tests.preproject.test_g0 import create, read, work  # noqa: F401


def test_formal_downgrade_preserves_existing_proposal(work):
    proposal_id, _ = create(work)
    before = read(work, proposal_id).json()
    with work.admin.connect() as connection:
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="preserve business data"):
                    downgrade()
        finally:
            transaction.rollback()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "s0_0729"
    assert read(work, proposal_id).json() == before
