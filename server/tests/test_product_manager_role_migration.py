"""Role constraint and narrow function rewrites round trip without remapping users."""

from importlib import import_module
from types import ModuleType
from uuid import uuid4

import pytest
from sqlalchemy import Connection, create_engine, inspect, select, text

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.migration_fixtures import rollback_migration_operations
from tests.test_user_admin_api import isolated_user_admin_database as isolated_user_admin_database


def definitions(connection: Connection, migration: ModuleType) -> dict[str, str]:
    return {
        name: str(
            connection.execute(
                text("SELECT pg_get_functiondef(CAST(:name AS regprocedure))"), {"name": name}
            ).scalar_one()
        )
        for name, _, _ in migration.REPLACEMENTS
    }


def test_product_manager_migration_restores_every_original_guard_and_role_constraint(
    isolated_user_admin_database: str,
) -> None:
    migration = import_module("migrations.versions.0417_product_manager_role")
    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with rollback_migration_operations(engine) as c:
            upgraded = definitions(c, migration)
            for name, old, new in migration.REPLACEMENTS:
                assert upgraded[name].count(new) == 1 and old not in upgraded[name]
            constraints = inspect(c).get_check_constraints("users", schema="cehub_core")
            assert "product_manager" in next(
                row["sqltext"] for row in constraints if row["name"] == "ck_users_role_allowed"
            )
            migration.downgrade()
            previous = definitions(c, migration)
            for name, old, new in migration.REPLACEMENTS:
                assert previous[name] == upgraded[name].replace(new, old)
            constraints = inspect(c).get_check_constraints("users", schema="cehub_core")
            assert "product_manager" not in next(
                row["sqltext"] for row in constraints if row["name"] == "ck_users_role_allowed"
            )
            migration.upgrade()
            assert definitions(c, migration) == upgraded
    finally:
        engine.dispose()


def test_downgrade_refuses_product_manager_accounts_even_when_inactive(
    isolated_user_admin_database: str,
) -> None:
    migration = import_module("migrations.versions.0417_product_manager_role")
    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with rollback_migration_operations(engine) as c:
            tenant = uuid4()
            c.execute(tables.tenants.insert().values(id=tenant, slug=str(tenant), name="合成角色"))
            person = uuid4()
            c.execute(
                tables.users.insert().values(
                    id=person,
                    tenant_id=tenant,
                    username="product-person",
                    display_name="合成产品经理",
                    role="product_manager",
                    is_active=False,
                )
            )
            before = definitions(c, migration)
            with pytest.raises(RuntimeError, match="Cannot downgrade 0417"):
                migration.downgrade()
            assert definitions(c, migration) == before
            assert (
                c.execute(
                    select(tables.users.c.role).where(tables.users.c.id == person)
                ).scalar_one()
                == "product_manager"
            )
    finally:
        engine.dispose()
