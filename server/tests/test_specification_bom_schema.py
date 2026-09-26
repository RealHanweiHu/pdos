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


def test_specification_and_bom_metadata_freezes_the_system_of_record_boundary() -> None:
    assert tables.specifications.schema == "cehub_product"
    assert tables.development_boms.schema == "cehub_product"
    assert tables.development_bom_items.schema == "cehub_product"
    assert tables.erp_bom_references.schema == "cehub_product"
    assert tables.cost_bom_items.schema == "cehub_cost"

    assert {
        "ck_development_boms_type_allowed",
        "ck_development_boms_code_nonblank",
        "ck_development_boms_name_nonblank",
    } <= named_constraints("development_boms", CheckConstraint)
    assert {
        "uq_development_boms_tenant_project_code_version",
        "uq_development_boms_tenant_id_type",
    } <= named_constraints("development_boms", UniqueConstraint)
    assert "ck_erp_bom_references_type_allowed" in named_constraints(
        "erp_bom_references", CheckConstraint
    )
    assert "ck_cost_bom_items_cost_bom_only" in named_constraints("cost_bom_items", CheckConstraint)


@pytest.fixture
def specification_bom_database_url() -> Iterator[str]:
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


def seed_project(connection: Connection, *, tenant_id: UUID, slug: str) -> tuple[UUID, UUID]:
    user_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    connection.execute(
        tables.tenants.insert(),
        {"id": tenant_id, "slug": slug, "name": f"Tenant {slug}"},
    )
    connection.execute(
        tables.users.insert(),
        {
            "id": user_id,
            "tenant_id": tenant_id,
            "username": f"owner-{slug}",
            "display_name": f"Owner {slug}",
            "role": "owner",
        },
    )
    connection.execute(
        tables.workflows.insert(),
        {
            "id": workflow_id,
            "tenant_id": tenant_id,
            "code": f"npd-{slug}",
            "name": "NPD",
        },
    )
    connection.execute(
        tables.projects.insert(),
        {
            "id": project_id,
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "code": f"PRJ-{slug}",
            "name": f"Project {slug}",
        },
    )
    return project_id, user_id


def test_database_allows_only_development_bom_truth_and_tenant_safe_links(
    specification_bom_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(specification_bom_database_url))
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    try:
        with engine.begin() as connection:
            project_id, owner_id = seed_project(connection, tenant_id=tenant_id, slug="bom")
            other_project_id, other_owner_id = seed_project(
                connection,
                tenant_id=other_tenant_id,
                slug="other-bom",
            )
            specification_id = uuid4()
            connection.execute(
                tables.specifications.insert(),
                {
                    "id": specification_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "created_by_user_id": owner_id,
                    "code": "SPEC-001",
                    "title": "Portable pump specification",
                    "version": 1,
                    "content": {"rated_pressure_kpa": 1034},
                },
            )

            for bom_type in ("ebom", "prototype", "cost"):
                connection.execute(
                    tables.development_boms.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "specification_id": specification_id,
                        "created_by_user_id": owner_id,
                        "bom_type": bom_type,
                        "code": f"BOM-{bom_type}",
                        "name": f"{bom_type} BOM",
                        "version": 1,
                    },
                )

            for erp_owned_type in ("mbom", "routing", "production_version"):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        tables.development_boms.insert(),
                        {
                            "id": uuid4(),
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "created_by_user_id": owner_id,
                            "bom_type": erp_owned_type,
                            "code": f"INVALID-{erp_owned_type}",
                            "name": "Must stay in ERP",
                            "version": 1,
                        },
                    )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.specifications.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": other_project_id,
                        "created_by_user_id": other_owner_id,
                        "code": "CROSS-TENANT",
                        "title": "Cross-tenant specification",
                        "version": 1,
                    },
                )

            cost_bom = (
                connection.execute(
                    tables.development_boms.select().where(
                        tables.development_boms.c.tenant_id == tenant_id,
                        tables.development_boms.c.bom_type == "cost",
                    )
                )
                .mappings()
                .one()
            )
            cost_item_id = uuid4()
            connection.execute(
                tables.development_bom_items.insert(),
                {
                    "id": cost_item_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "bom_id": cost_bom["id"],
                    "line_number": 10,
                    "part_number": "PUMP-HOUSING",
                    "description": "Pump housing",
                    "quantity": "1.000000",
                    "unit": "ea",
                    "material_reference": "ERP-MAT-1001",
                },
            )
            connection.execute(
                tables.cost_bom_items.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "bom_id": cost_bom["id"],
                    "bom_type": "cost",
                    "bom_item_id": cost_item_id,
                    "currency": "CNY",
                    "unit_cost": "12.3400",
                },
            )
            connection.execute(
                tables.erp_bom_references.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "bom_id": cost_bom["id"],
                    "reference_type": "routing",
                    "source_system": "erp",
                    "external_id": "ROUTING-9001",
                },
            )

            ebom = (
                connection.execute(
                    tables.development_boms.select().where(
                        tables.development_boms.c.tenant_id == tenant_id,
                        tables.development_boms.c.bom_type == "ebom",
                    )
                )
                .mappings()
                .one()
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.cost_bom_items.insert(),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "bom_id": ebom["id"],
                        "bom_type": "ebom",
                        "bom_item_id": cost_item_id,
                        "currency": "CNY",
                        "unit_cost": "12.3400",
                    },
                )
    finally:
        engine.dispose()
