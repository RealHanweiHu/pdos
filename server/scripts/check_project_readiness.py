"""Read-only production check for Project list and response compatibility."""

from __future__ import annotations

import os
from uuid import UUID

from sqlalchemy import URL, Engine, create_engine, make_url

from app.api.projects import project_response
from app.db.url import psycopg_database_url
from app.domain.projects import ProjectService
from app.settings import get_settings


def read_only_database_url(value: str) -> URL:
    url = make_url(psycopg_database_url(value))
    existing_options = url.query.get("options", "")
    read_only_option = "-cdefault_transaction_read_only=on"
    options = f"{existing_options} {read_only_option}".strip()
    return url.update_query_dict({"options": options})


def validate_project_readiness(*, engine: Engine, tenant_id: UUID) -> int:
    with engine.connect() as connection:
        default_read_only = connection.exec_driver_sql(
            "SHOW default_transaction_read_only"
        ).scalar_one()
        transaction_read_only = connection.exec_driver_sql(
            "SHOW transaction_read_only"
        ).scalar_one()
    if default_read_only != "on" or transaction_read_only != "on":
        raise RuntimeError("Project readiness connection is not read-only")

    records = ProjectService(engine).list(tenant_id=tenant_id, member_user_id=None)
    for record in records:
        project_response(record)
    return len(records)


def main() -> int:
    raw_tenant_id = os.getenv("PDOS_TENANT_ID")
    try:
        if raw_tenant_id is None:
            raise ValueError("PDOS_TENANT_ID is required")
        tenant_id = UUID(raw_tenant_id)
        engine = create_engine(
            read_only_database_url(get_settings().database_url),
            pool_pre_ping=True,
        )
        try:
            project_count = validate_project_readiness(engine=engine, tenant_id=tenant_id)
        finally:
            engine.dispose()
    except Exception as error:
        print(f"Project readiness failed ({type(error).__name__}); no state was changed")
        return 1
    print(f"Project readiness passed for {project_count} Projects; no state was changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
