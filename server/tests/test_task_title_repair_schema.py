from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def task_title_repair_database() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.downgrade(config, "0031_user_account_management")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
        engine.dispose()
        command.upgrade(config, "head")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_migration_repairs_only_manifest_bound_imported_task_titles(
    task_title_repair_database: str,
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    tenant_id = uuid4()
    actor_id = uuid4()
    workflow_id = uuid4()
    stage_id = uuid4()
    project_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    engine = create_engine(psycopg_database_url(task_title_repair_database))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": "repair-test", "name": "Repair Test"},
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": actor_id,
                    "tenant_id": tenant_id,
                    "username": "owner",
                    "display_name": "Owner",
                    "role": "owner",
                    "password_hash": None,
                },
            )
            connection.execute(
                tables.workflows.insert(),
                {
                    "id": workflow_id,
                    "tenant_id": tenant_id,
                    "code": f"npd-cehub-{project_id.hex}",
                    "name": "Imported NPD",
                },
            )
            connection.execute(
                tables.stages.insert(),
                {
                    "id": stage_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "dvt",
                    "name": "DVT 设计验证",
                    "sequence": 5,
                },
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "current_stage_id": stage_id,
                    "owner_user_id": actor_id,
                    "code": "REPAIR-1",
                    "name": "Imported project",
                    "status": "active",
                },
            )
            connection.execute(
                tables.tasks.insert(),
                {
                    "id": task_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "stage_id": stage_id,
                    "title": "v3",
                    "status": "todo",
                    "priority": "medium",
                },
            )
            connection.execute(
                tables.migration_runs.insert(),
                {
                    "id": run_id,
                    "tenant_id": tenant_id,
                    "actor_user_id": actor_id,
                    "source_system": "cehub-v3",
                    "source_schema": "public",
                    "source_fingerprint": "a" * 64,
                    "selected_project_ids": ["source-project"],
                    "status": "completed",
                    "stats": {},
                },
            )
            connection.execute(
                tables.migration_mappings.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "source_system": "cehub-v3",
                    "entity_type": "task",
                    "source_id": "source-task-row",
                    "target_id": task_id,
                    "source_hash": "b" * 64,
                },
            )

        command.upgrade(config, "0032_repair_task_titles")
        with engine.connect() as connection:
            assert (
                connection.scalar(select(tables.tasks.c.title).where(tables.tasks.c.id == task_id))
                == "安规与认证"
            )

        command.downgrade(config, "0031_user_account_management")
        with engine.connect() as connection:
            assert (
                connection.scalar(select(tables.tasks.c.title).where(tables.tasks.c.id == task_id))
                == "v3"
            )
    finally:
        engine.dispose()
