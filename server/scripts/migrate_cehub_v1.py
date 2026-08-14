"""Run the bounded CEHub-to-PDOS v1 migration with explicit operator intent."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from app.db.url import psycopg_database_url
from app.deployment.preflight import (
    EXPECTED_CA_PATH,
    UnsafeProductionConfigurationError,
    validate_production_database_url,
)
from app.migrations.cehub_v1 import (
    MigrationReport,
    MigrationValidationError,
    cehub_psycopg_database_url,
    migrate_cehub_v1,
)

SOURCE_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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


def migration_apply_confirmation(
    *,
    tenant_id: UUID,
    source_fingerprint: str,
    project_ids: tuple[str, ...],
) -> str:
    normalized_project_ids = tuple(dict.fromkeys(project_id.strip() for project_id in project_ids))
    if not normalized_project_ids or any(not project_id for project_id in normalized_project_ids):
        raise ValueError("apply confirmation requires bounded project selectors")
    if SOURCE_FINGERPRINT_PATTERN.fullmatch(source_fingerprint) is None:
        raise ValueError("approved source fingerprint must be a SHA-256 hex digest")
    return f"apply:{tenant_id}:{source_fingerprint}:{','.join(normalized_project_ids)}"


def validate_migration_endpoints(*, source_url: str, target_url: str) -> None:
    try:
        validate_production_database_url(target_url, username="pdos_app")
        source = make_url(source_url)
        target = make_url(target_url)
    except (ArgumentError, UnsafeProductionConfigurationError) as error:
        raise ValueError("migration database endpoints are not approved for production") from error
    if not source.drivername.startswith("postgresql") or not source.password:
        raise ValueError("CEHub source must be an authenticated PostgreSQL endpoint")
    if source.host != target.host or (source.port or 5432) != target.port:
        raise ValueError("CEHub source and PDOS target must use the same approved RDS instance")
    if not source.database or source.database == target.database:
        raise ValueError("source and target database names must differ")
    if not source.username or source.username == target.username:
        raise ValueError("CEHub source must use an independent login role")
    if source.query.get("sslmode") != "verify-full":
        raise ValueError("CEHub source TLS must verify the RDS host")
    if source.query.get("sslrootcert") != EXPECTED_CA_PATH:
        raise ValueError("CEHub source must use the bundled RDS CA")


def _write_report(report: MigrationReport, path: Path | None) -> None:
    serialized = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("migration report path must not be a symbolic link")
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(file_descriptor, 0o600)
            report_file = os.fdopen(file_descriptor, "w", encoding="utf-8")
            file_descriptor = -1
            with report_file:
                report_file.write(f"{serialized}\n")
                report_file.flush()
                os.fsync(report_file.fileno())
            os.replace(temporary_path, path)
        except BaseException:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            temporary_path.unlink(missing_ok=True)
            raise


def main() -> int:
    arguments = parse_args()
    try:
        source_url = _required_environment("CEHUB_SOURCE_DATABASE_URL")
        target_url = _required_environment("DATABASE_URL")
        tenant_id = UUID(_required_environment("PDOS_TENANT_ID"))
        actor_user_id = UUID(_required_environment("PDOS_MIGRATION_ACTOR_USER_ID"))
        validate_migration_endpoints(source_url=source_url, target_url=target_url)
        approved_source_fingerprint = None
        if arguments.apply:
            approved_source_fingerprint = _required_environment(
                "PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT"
            )
            expected_confirmation = migration_apply_confirmation(
                tenant_id=tenant_id,
                source_fingerprint=approved_source_fingerprint,
                project_ids=tuple(arguments.project_ids),
            )
            actual_confirmation = os.environ.get("PDOS_MIGRATION_APPLY_CONFIRM", "").strip()
            if not hmac.compare_digest(actual_confirmation, expected_confirmation):
                raise SystemExit(
                    "apply refused: after explicit approval set "
                    f"PDOS_MIGRATION_APPLY_CONFIRM={expected_confirmation}"
                )
    except ValueError as error:
        raise SystemExit(f"migration refused: {error}") from error
    source_engine = create_engine(cehub_psycopg_database_url(source_url), pool_pre_ping=True)
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
                expected_source_fingerprint=approved_source_fingerprint,
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
