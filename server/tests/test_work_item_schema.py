from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    CheckConstraint,
    Connection,
    ForeignKeyConstraint,
    Index,
    Table,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.schema import Constraint

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]


def constraint_names(table: Table, constraint_type: type[Constraint]) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and isinstance(constraint.name, str)
    }


def index_names(table: Table) -> set[str]:
    return {
        index.name
        for index in table.indexes
        if isinstance(index, Index) and isinstance(index.name, str)
    }


def test_work_item_metadata_freezes_dependency_and_lifecycle_contracts() -> None:
    assert "blocked_reason" in tables.tasks.c
    assert "workflow_id" in tables.tasks.c
    assert "workflow_id" in tables.issues.c
    assert {
        "ck_tasks_title_nonblank",
        "ck_tasks_blocked_reason_consistent",
        "ck_tasks_completion_consistent",
        "ck_tasks_stage_pair_consistent",
    } <= constraint_names(tables.tasks, CheckConstraint)
    assert {
        "fk_tasks_tenant_project_workflow",
        "fk_tasks_tenant_workflow_stage",
    } <= constraint_names(tables.tasks, ForeignKeyConstraint)
    assert {
        "ck_issues_title_nonblank",
        "ck_issues_closed_at_consistent",
        "ck_issues_stage_pair_consistent",
    } <= constraint_names(tables.issues, CheckConstraint)
    assert {
        "fk_issues_tenant_project_workflow",
        "fk_issues_tenant_workflow_stage",
    } <= constraint_names(tables.issues, ForeignKeyConstraint)
    assert {
        "ck_risks_title_nonblank",
        "ck_risks_closed_at_consistent",
    } <= constraint_names(tables.risks, CheckConstraint)
    assert {
        "ix_tasks_tenant_project_updated",
        "ix_issues_tenant_project_updated",
        "ix_risks_tenant_project_updated",
    } <= index_names(tables.tasks) | index_names(tables.issues) | index_names(tables.risks)

    assert {
        "ck_task_dependencies_no_self_reference",
    } <= constraint_names(tables.task_dependencies, CheckConstraint)
    assert {
        "uq_task_dependencies_tenant_project_edge",
    } <= constraint_names(tables.task_dependencies, UniqueConstraint)
    assert {
        "fk_task_dependencies_tenant_project_task",
        "fk_task_dependencies_tenant_project_predecessor",
    } <= constraint_names(tables.task_dependencies, ForeignKeyConstraint)
    assert "ix_task_dependencies_tenant_project_predecessor" in index_names(
        tables.task_dependencies
    )


@pytest.fixture
def work_item_schema_database_url() -> Iterator[str]:
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


def seed_project(connection: Connection, tenant_id: UUID, suffix: str) -> tuple[UUID, UUID, UUID]:
    workflow_id = uuid4()
    stage_id = uuid4()
    project_id = uuid4()
    connection.execute(
        tables.workflows.insert(),
        {
            "id": workflow_id,
            "tenant_id": tenant_id,
            "code": f"WF-{suffix}",
            "name": f"Workflow {suffix}",
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
            "id": project_id,
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "current_stage_id": stage_id,
            "code": f"PRJ-{suffix}",
            "name": f"Project {suffix}",
        },
    )
    return project_id, workflow_id, stage_id


def test_database_rejects_invalid_work_item_scope_and_lifecycle(
    work_item_schema_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(work_item_schema_database_url))
    tenant_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "work-items", "name": "Work Items"},
            )
            project_id, workflow_id, stage_id = seed_project(connection, tenant_id, "ONE")
            other_project_id, _, other_stage_id = seed_project(connection, tenant_id, "TWO")

            task_id = uuid4()
            connection.execute(
                tables.tasks.insert(),
                {
                    "id": task_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "stage_id": stage_id,
                    "title": "Valid task",
                },
            )
            other_task_id = uuid4()
            connection.execute(
                tables.tasks.insert(),
                {
                    "id": other_task_id,
                    "tenant_id": tenant_id,
                    "project_id": other_project_id,
                    "title": "Other task",
                },
            )

            invalid_tasks = (
                {"title": "   "},
                {"title": "Blocked without reason", "status": "blocked"},
                {"title": "Done without timestamp", "status": "done"},
                {
                    "title": "Cross-workflow stage",
                    "workflow_id": workflow_id,
                    "stage_id": other_stage_id,
                },
            )
            for values in invalid_tasks:
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.tasks.insert(),
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            **values,
                        },
                    )

            for dependency_values in (
                {"task_id": task_id, "depends_on_task_id": task_id},
                {"task_id": task_id, "depends_on_task_id": other_task_id},
            ):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.task_dependencies.insert(),
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            **dependency_values,
                        },
                    )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.issues.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "workflow_id": workflow_id,
                        "stage_id": other_stage_id,
                        "title": "Cross-workflow issue",
                    },
                )
            for table in (tables.issues, tables.risks):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        table.insert(),
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "title": "Closed without timestamp",
                            "status": "closed",
                        },
                    )

            connection.execute(
                tables.tasks.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "title": "Valid completed task",
                    "status": "done",
                    "completed_at": datetime.now(UTC),
                },
            )
    finally:
        engine.dispose()
