"""A committed evidence fact prevents destructive schema downgrade."""
# ruff: noqa: F811 -- pytest injects the re-exported marked fixture

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from migrations.versions.s0_0733_preproject_evidence import downgrade
from tests.preproject.test_evidence_commands_pg import artifact, link_claim, record_claim
from tests.preproject.test_g0 import create, read
from tests.preproject.test_g0 import work as work


def test_evidence_downgrade_refuses_committed_fact_and_preserves_document(work):
    claim = record_claim(work, artifact(work))
    proposal_id, _ = create(work)
    link, _ = link_claim(work, proposal_id, claim["subject_id"])
    before = read(work, proposal_id).json()
    with work.admin.connect() as connection:
        original_head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        connection.rollback()
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(DBAPIError, match="downgrade refuses persisted facts") as error:
                    downgrade()
                assert error.value.orig.sqlstate == "23514"
        finally:
            transaction.rollback()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == original_head
        assert connection.scalar(
            text("SELECT count(*) FROM evidence_links WHERE id=:identity"),
            {"identity": link["result"]["link_id"]},
        ) == 1
    assert read(work, proposal_id).json() == before
