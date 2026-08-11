from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, UniqueConstraint, create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.schema import Constraint

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]


def named_constraints(table_name: str, constraint_type: type[Constraint]) -> set[str]:
    return {
        constraint.name
        for constraint in getattr(tables, table_name).constraints
        if isinstance(constraint, constraint_type) and isinstance(constraint.name, str)
    }


def test_development_case_metadata_freezes_conversion_contracts() -> None:
    assert {
        "ck_development_cases_code_nonblank",
        "ck_development_cases_title_nonblank",
        "ck_development_cases_business_case_object",
    } <= named_constraints("development_cases", CheckConstraint)
    assert "uq_development_cases_tenant_requirement" in named_constraints(
        "development_cases", UniqueConstraint
    )
    assert "ix_development_cases_tenant_updated" in {
        index.name for index in tables.development_cases.indexes
    }


@pytest.fixture
def development_case_schema_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def test_database_rejects_invalid_and_duplicate_development_cases(
    development_case_schema_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(development_case_schema_database_url))
    tenant_id = uuid4()
    requirement_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "case-schema", "name": "Case Schema"},
            )
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": requirement_id,
                    "tenant_id": tenant_id,
                    "code": "REQ-001",
                    "title": "Requirement",
                },
            )
            for invalid_values in (
                {"code": "   ", "title": "Valid"},
                {"code": "CASE-001", "title": "   "},
                {"code": "CASE-002", "title": "Valid", "business_case": []},
                {"code": "CASE-003", "title": "Valid", "status": "proposed"},
            ):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.development_cases.insert(),
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "requirement_id": requirement_id,
                            **invalid_values,
                        },
                    )

            connection.execute(
                tables.development_cases.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "requirement_id": requirement_id,
                    "code": "CASE-VALID",
                    "title": "Valid case",
                },
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.development_cases.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "requirement_id": requirement_id,
                        "code": "CASE-DUPLICATE-REQUIREMENT",
                        "title": "Duplicate conversion",
                    },
                )
    finally:
        engine.dispose()


def test_migration_maps_legacy_proposed_status_both_directions(
    development_case_schema_database_url: str,
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(development_case_schema_database_url))
    command.downgrade(config, "0004_requirement_pool")
    tenant_id = uuid4()
    requirement_id = uuid4()
    case_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "legacy-case", "name": "Legacy Case"},
            )
            connection.execute(
                tables.requirements.insert(),
                {
                    "id": requirement_id,
                    "tenant_id": tenant_id,
                    "code": "REQ-LEGACY",
                    "title": "Legacy requirement",
                },
            )
            connection.execute(
                tables.development_cases.insert(),
                {
                    "id": case_id,
                    "tenant_id": tenant_id,
                    "requirement_id": requirement_id,
                    "code": "CASE-LEGACY",
                    "title": "Legacy case",
                    "status": "proposed",
                },
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.development_cases.c.status).where(
                        tables.development_cases.c.id == case_id
                    )
                ).scalar_one()
                == "evaluating"
            )
        command.downgrade(config, "0004_requirement_pool")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.development_cases.c.status).where(
                        tables.development_cases.c.id == case_id
                    )
                ).scalar_one()
                == "proposed"
            )
    finally:
        command.upgrade(config, "head")
        engine.dispose()
