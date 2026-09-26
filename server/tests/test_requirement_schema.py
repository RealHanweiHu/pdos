from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, create_engine
from sqlalchemy.exc import IntegrityError

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]


def check_names(table_name: str) -> set[str]:
    table = getattr(tables, table_name)
    names: set[str] = set()
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint) and isinstance(constraint.name, str):
            names.add(constraint.name)
    return names


def test_requirement_pool_metadata_enforces_nonblank_and_array_contracts() -> None:
    assert {
        "ck_requirements_code_nonblank",
        "ck_requirements_title_nonblank",
        "ck_requirements_acceptance_criteria_array",
    } <= check_names("requirements")
    assert {
        "ck_customers_code_nonblank",
        "ck_customers_name_nonblank",
    } <= check_names("customers")

    requirement_indexes = {index.name for index in tables.requirements.indexes}
    assert "ix_requirements_tenant_updated" in requirement_indexes


@pytest.fixture
def requirement_schema_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def test_database_rejects_blank_requirement_and_non_array_criteria(
    requirement_schema_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(requirement_schema_database_url))
    tenant_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "requirement-schema", "name": "Requirement Schema"},
            )
            for invalid_values in (
                {"code": "   ", "title": "Valid title"},
                {"code": "REQ-001", "title": "   "},
                {
                    "code": "REQ-002",
                    "title": "Valid title",
                    "acceptance_criteria": {"invalid": "object"},
                },
            ):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.requirements.insert(),
                        {"id": uuid4(), "tenant_id": tenant_id, **invalid_values},
                    )
    finally:
        engine.dispose()
