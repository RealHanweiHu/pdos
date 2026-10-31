from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def planning_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        command.upgrade(config, "head")
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def test_0031_backfills_stage_actuals_from_history_and_guards_cancelled_downgrade(
    planning_database_url: str,
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(planning_database_url))
    tenant_id, workflow_id, project_id = uuid4(), uuid4(), uuid4()
    stage_ids = [uuid4(), uuid4(), uuid4()]
    created_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    advanced_at = datetime(2026, 9, 15, 10, 30, tzinfo=UTC)
    try:
        command.downgrade(config, "0030_phase_three_agents")
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"planning-{tenant_id}", "name": "Planning"},
            )
            connection.execute(
                tables.workflows.insert(),
                {"id": workflow_id, "tenant_id": tenant_id, "code": "npd-x", "name": "NPD"},
            )
            connection.execute(
                tables.stages.insert(),
                [
                    {
                        "id": stage_id,
                        "tenant_id": tenant_id,
                        "workflow_id": workflow_id,
                        "code": f"s{index}",
                        "name": f"Stage {index}",
                        "sequence": index,
                    }
                    for index, stage_id in enumerate(stage_ids, start=1)
                ],
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "current_stage_id": stage_ids[1],
                    "code": "PRJ-HISTORY",
                    "name": "History",
                    "status": "active",
                    "created_at": created_at,
                },
            )
            connection.execute(
                tables.events.insert(),
                {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "event_id": f"project:{project_id}:stage:{uuid4()}",
                    "event_type": "PROJECT_STAGE_CHANGED",
                    "schema_version": 1,
                    "source": "project_service",
                    "entity": "project",
                    "entity_id": project_id,
                    "payload": {
                        "from_stage_id": str(stage_ids[0]),
                        "to_stage_id": str(stage_ids[1]),
                    },
                    "timestamp": advanced_at,
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            rows = {
                row.id: row
                for row in connection.execute(
                    select(
                        tables.stages.c.id,
                        tables.stages.c.entered_at,
                        tables.stages.c.exited_at,
                        tables.stages.c.planned_start_date,
                    ).where(tables.stages.c.workflow_id == workflow_id)
                )
            }
        assert (rows[stage_ids[0]].entered_at, rows[stage_ids[0]].exited_at) == (
            created_at,
            advanced_at,
        )
        assert (rows[stage_ids[1]].entered_at, rows[stage_ids[1]].exited_at) == (advanced_at, None)
        assert (rows[stage_ids[2]].entered_at, rows[stage_ids[2]].exited_at) == (None, None)
        assert all(row.planned_start_date is None for row in rows.values())

        with engine.begin() as connection:
            connection.execute(
                tables.projects.update()
                .where(tables.projects.c.id == project_id)
                .values(status="cancelled")
            )
        with pytest.raises(DBAPIError):
            command.downgrade(config, "0030_phase_three_agents")
    finally:
        engine.dispose()
