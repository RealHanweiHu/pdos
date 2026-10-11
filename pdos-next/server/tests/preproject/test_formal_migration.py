"""Exercise downgrade refusal against committed synthetic proposal data."""

# ruff: noqa: F811 -- imported pytest fixture
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from migrations.versions.s0_0729_preproject_g0 import downgrade
from migrations.versions.s0_0731_material_receipt_proofs import downgrade as proof_downgrade
from tests.preproject.test_g0 import create, read, request, save
from tests.preproject.test_g0 import work as work


def test_formal_downgrade_preserves_existing_proposal(work):
    proposal_id, _ = create(work)
    before = read(work, proposal_id).json()
    with work.admin.connect() as connection:
        original_head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        connection.rollback()
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="preserve business data"):
                    downgrade()
        finally:
            transaction.rollback()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == original_head
    assert read(work, proposal_id).json() == before


def test_material_proof_downgrade_preserves_saved_confirmation_links(work):
    from tests.preproject.test_material_commands_pg import parameter

    receipt, _ = save(work, request(work, "category.parameter.publish", parameter()))
    with work.admin.connect() as connection:
        original_head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        connection.rollback()
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="preserve receipt metadata"):
                    proof_downgrade()
        finally:
            transaction.rollback()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == original_head
        assert connection.scalar(
            text("SELECT confirmation_id IS NOT NULL FROM action_receipts WHERE id=:id"),
            {"id": receipt["id"]},
        )
