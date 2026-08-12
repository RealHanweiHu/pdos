"""Run the bounded CEHub-to-PDOS v1 migration with explicit operator intent."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.db.url import psycopg_database_url
from app.migrations.cehub_v1 import MigrationReport, MigrationValidationError, migrate_cehub_v1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Migrate selected NPD/OBT projects from a read-only CEHub snapshot into PDOS.")
    )
    parser.add_argument(
        "--project-id",
        action="append",
        required=True,
        dest="project_ids",
        help=("CEHub project id or unique project number; repeat for a bounded multi-project run"),
    )
    parser.add_argument(
        "--source-schema",
        default=os.environ.get("CEHUB_SOURCE_SCHEMA", "public"),
    )
    parser.add_argument("--report", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"required environment variable is missing: {name}")
    return value


def _write_report(report: MigrationReport, path: Path | None) -> None:
    serialized = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{serialized}\n", encoding="utf-8")
        path.chmod(0o600)


def main() -> int:
    arguments = parse_args()
    source_url = _required_environment("CEHUB_SOURCE_DATABASE_URL")
    target_url = _required_environment("DATABASE_URL")
    tenant_id = UUID(_required_environment("PDOS_TENANT_ID"))
    actor_user_id = UUID(_required_environment("PDOS_MIGRATION_ACTOR_USER_ID"))
    if make_url(source_url).database == make_url(target_url).database:
        raise SystemExit("source and target database names must differ")

    source_engine = create_engine(psycopg_database_url(source_url), pool_pre_ping=True)
    target_engine = create_engine(psycopg_database_url(target_url), pool_pre_ping=True)
    try:
        try:
            report = migrate_cehub_v1(
                source_engine=source_engine,
                target_engine=target_engine,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_ids=tuple(arguments.project_ids),
                source_schema=arguments.source_schema,
                dry_run=bool(arguments.dry_run),
            )
        except MigrationValidationError as exc:
            _write_report(exc.report, arguments.report)
            return 2
        except (SQLAlchemyError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "message": "migration did not run; inspect server-side logs",
                    },
                    sort_keys=True,
                )
            )
            return 3
        _write_report(report, arguments.report)
        return 0 if report.status in {"ready", "completed"} else 2
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
