from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.db.namespaces import SCHEMAS
from app.db.schema import metadata, tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]
FINAL_ENTITY_TABLES = {
    ("cehub_project", "crm_requirement_intakes"),
    ("cehub_supplier", "suppliers"),
    ("cehub_cost", "costs"),
    ("cehub_project", "resources"),
}
SPEC_BUSINESS_ENTITY_TABLES = {
    "tenant": ("cehub_core", "tenants"),
    "user": ("cehub_core", "users"),
    "customer": ("cehub_core", "customers"),
    "requirement": ("cehub_project", "requirements"),
    "development_case": ("cehub_project", "development_cases"),
    "project": ("cehub_project", "projects"),
    "workflow": ("cehub_project", "workflows"),
    "stage": ("cehub_project", "stages"),
    "gate": ("cehub_project", "gates"),
    "task": ("cehub_project", "tasks"),
    "issue": ("cehub_project", "issues"),
    "risk": ("cehub_project", "risks"),
    "decision": ("cehub_project", "decisions"),
    "specification": ("cehub_product", "specifications"),
    "development_bom": ("cehub_product", "development_boms"),
    "ecr": ("cehub_product", "engineering_change_requests"),
    "ecn": ("cehub_product", "engineering_change_notices"),
    "build": ("cehub_product", "build_batches"),
    "sample": ("cehub_product", "samples"),
    "test": ("cehub_quality", "test_plans"),
    "certification": ("cehub_quality", "certifications"),
    "supplier": ("cehub_supplier", "suppliers"),
    "cost": ("cehub_cost", "costs"),
    "resource": ("cehub_project", "resources"),
    "memory": ("cehub_memory", "memories"),
    "ai_finding": ("cehub_ai", "findings"),
}


@pytest.fixture(scope="module")
def final_entity_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        yield test_url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_metadata_contains_crm_supplier_cost_and_resource_entities() -> None:
    actual = {(table.schema, table.name) for table in metadata.tables.values()}
    assert actual >= FINAL_ENTITY_TABLES
    assert not tables.crm_requirement_intakes.c.requirement_id.nullable
    assert not tables.suppliers.c.code.nullable
    assert not tables.costs.c.amount.nullable
    assert not tables.resources.c.resource_type.nullable


def test_all_26_business_and_ai_entities_have_canonical_tables() -> None:
    assert len(SPEC_BUSINESS_ENTITY_TABLES) == 26
    actual = {(table.schema, table.name) for table in metadata.tables.values()}
    assert actual >= set(SPEC_BUSINESS_ENTITY_TABLES.values())
    assert (tables.events.schema, tables.events.name) == ("cehub_event", "events")


def test_final_entity_migration_matches_metadata_and_single_head(
    final_entity_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(final_entity_database_url))
    try:
        inspector = inspect(engine)
        assert all(
            table in inspector.get_table_names(schema=schema)
            for schema, table in FINAL_ENTITY_TABLES
        )
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_server_default": True,
                    "compare_type": True,
                    "include_schemas": True,
                    "include_name": lambda name, type_, parent_names: (
                        name in SCHEMAS
                        if type_ == "schema"
                        else parent_names.get("schema_name") in SCHEMAS
                        if type_ == "table"
                        else True
                    ),
                },
            )
            assert compare_metadata(context, metadata) == []
    finally:
        engine.dispose()
    assert ScriptDirectory.from_config(Config(str(SERVER_ROOT / "alembic.ini"))).get_heads() == [
        "0031_project_planning"
    ]


def test_supplier_cost_and_resource_foreign_keys_reject_cross_tenant_scope(
    final_entity_database_url: str,
) -> None:
    ids = {
        name: uuid4()
        for name in (
            "tenant_a",
            "tenant_b",
            "user_a",
            "user_b",
            "workflow_a",
            "workflow_b",
            "project_a",
            "project_b",
            "supplier_a",
            "supplier_b",
        )
    }
    engine = create_engine(psycopg_database_url(final_entity_database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                [
                    {"id": ids["tenant_a"], "slug": f"entity-a-{ids['tenant_a']}", "name": "A"},
                    {"id": ids["tenant_b"], "slug": f"entity-b-{ids['tenant_b']}", "name": "B"},
                ],
            )
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": ids["user_a"],
                        "tenant_id": ids["tenant_a"],
                        "username": "entity-a",
                        "display_name": "A",
                        "role": "owner",
                    },
                    {
                        "id": ids["user_b"],
                        "tenant_id": ids["tenant_b"],
                        "username": "entity-b",
                        "display_name": "B",
                        "role": "owner",
                    },
                ],
            )
            connection.execute(
                tables.workflows.insert(),
                [
                    {
                        "id": ids["workflow_a"],
                        "tenant_id": ids["tenant_a"],
                        "code": "wf-a",
                        "name": "A",
                    },
                    {
                        "id": ids["workflow_b"],
                        "tenant_id": ids["tenant_b"],
                        "code": "wf-b",
                        "name": "B",
                    },
                ],
            )
            connection.execute(
                tables.projects.insert(),
                [
                    {
                        "id": ids["project_a"],
                        "tenant_id": ids["tenant_a"],
                        "workflow_id": ids["workflow_a"],
                        "code": "prj-a",
                        "name": "A",
                    },
                    {
                        "id": ids["project_b"],
                        "tenant_id": ids["tenant_b"],
                        "workflow_id": ids["workflow_b"],
                        "code": "prj-b",
                        "name": "B",
                    },
                ],
            )
            connection.execute(
                tables.suppliers.insert(),
                [
                    {
                        "id": ids["supplier_a"],
                        "tenant_id": ids["tenant_a"],
                        "code": "sup-a",
                        "name": "A",
                    },
                    {
                        "id": ids["supplier_b"],
                        "tenant_id": ids["tenant_b"],
                        "code": "sup-b",
                        "name": "B",
                    },
                ],
            )

        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                tables.costs.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "supplier_id": ids["supplier_b"],
                    "code": "cross-supplier",
                    "cost_type": "material",
                    "amount": 1,
                    "currency": "CNY",
                },
            )
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                tables.resources.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_a"],
                    "assigned_user_id": ids["user_b"],
                    "code": "cross-user",
                    "name": "Cross",
                    "resource_type": "person",
                },
            )
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                tables.resources.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": ids["tenant_a"],
                    "project_id": ids["project_b"],
                    "code": "cross-project",
                    "name": "Cross",
                    "resource_type": "equipment",
                },
            )
    finally:
        engine.dispose()


def test_final_entity_migration_refuses_lossy_downgrade(
    final_entity_database_url: str,
) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(final_entity_database_url))
    tenant_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"entity-guard-{tenant_id}", "name": "Guard"},
            )
            connection.execute(
                tables.suppliers.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "code": "guard",
                    "name": "Guard",
                },
            )

        with pytest.raises(RuntimeError, match="refusing lossy downgrade"):
            command.downgrade(config, "0028_erp_handoff_executor")
    finally:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        command.upgrade(config, "head")
        engine.dispose()
