from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, Connection, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.schema import Constraint

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]


def named_constraints(table_name: str, constraint_type: type[Constraint]) -> set[str]:
    return {
        constraint.name
        for constraint in getattr(tables, table_name).constraints
        if isinstance(constraint, constraint_type) and isinstance(constraint.name, str)
    }


def test_project_metadata_freezes_instance_contracts() -> None:
    assert {
        "ck_workflows_code_nonblank",
        "ck_workflows_name_nonblank",
    } <= named_constraints("workflows", CheckConstraint)
    assert {
        "ck_stages_code_nonblank",
        "ck_stages_name_nonblank",
    } <= named_constraints("stages", CheckConstraint)
    assert {
        "ck_projects_code_nonblank",
        "ck_projects_name_nonblank",
    } <= named_constraints("projects", CheckConstraint)
    assert {
        "uq_projects_tenant_development_case",
        "uq_projects_tenant_workflow",
    } <= named_constraints("projects", UniqueConstraint)
    assert "ix_projects_tenant_updated" in {index.name for index in tables.projects.indexes}


@pytest.fixture
def project_schema_database_url() -> Iterator[str]:
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


def seed_case(connection: Connection, tenant_id: UUID) -> UUID:
    requirement_id = uuid4()
    case_id = uuid4()
    connection.execute(
        tables.requirements.insert(),
        {
            "id": requirement_id,
            "tenant_id": tenant_id,
            "code": "REQ-PROJECT",
            "title": "Project requirement",
            "status": "converted",
        },
    )
    connection.execute(
        tables.development_cases.insert(),
        {
            "id": case_id,
            "tenant_id": tenant_id,
            "requirement_id": requirement_id,
            "code": "CASE-PROJECT",
            "title": "Project case",
            "status": "approved",
        },
    )
    return case_id


def test_database_rejects_blank_and_reused_project_instances(
    project_schema_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(project_schema_database_url))
    tenant_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "project-schema", "name": "Project Schema"},
            )
            case_id = seed_case(connection, tenant_id)

            for invalid_values in (
                {"code": "   ", "name": "Valid"},
                {"code": "NPD", "name": "   "},
            ):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.workflows.insert(),
                        {"id": uuid4(), "tenant_id": tenant_id, **invalid_values},
                    )

            workflow_id = uuid4()
            stage_id = uuid4()
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": "PRJ-001-NPD",
                    "name": "NPD workflow",
                },
            )
            for invalid_values in (
                {"code": "   ", "name": "Valid"},
                {"code": "concept", "name": "   "},
            ):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.stages.insert(),
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "workflow_id": workflow_id,
                            "sequence": 1,
                            **invalid_values,
                        },
                    )
            connection.execute(
                tables.stages.insert(),
                {
                    "id": stage_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "concept",
                    "name": "Concept",
                    "sequence": 1,
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "development_case_id": case_id,
                    "workflow_id": workflow_id,
                    "current_stage_id": stage_id,
                    "code": "PRJ-001",
                    "name": "Project One",
                },
            )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.projects.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "development_case_id": case_id,
                        "workflow_id": workflow_id,
                        "current_stage_id": stage_id,
                        "code": "PRJ-002",
                        "name": "Reused instances",
                    },
                )
            for invalid_values in (
                {"code": "   ", "name": "Valid"},
                {"code": "PRJ-003", "name": "   "},
            ):
                invalid_workflow_id = uuid4()
                connection.execute(
                    tables.workflows.insert(),
                    {
                        "id": invalid_workflow_id,
                        "tenant_id": tenant_id,
                        "code": f"INVALID-{invalid_workflow_id}",
                        "name": "Invalid project workflow",
                    },
                )
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.projects.insert(),
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "workflow_id": invalid_workflow_id,
                            **invalid_values,
                        },
                    )
    finally:
        engine.dispose()
