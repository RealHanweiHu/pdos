"""Capture and verify the complete, read-only CEHub cutover inventory."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.migrations.cehub_v1 import (
    SOURCE_SYSTEM,
    CeHubSourceAdapter,
    cehub_psycopg_database_url,
    source_project_inventory_fingerprint,
)
from scripts.migrate_cehub_v1 import validate_migration_endpoints

FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_PROJECT_CATEGORIES = frozenset({"npd", "obt"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture or verify every CEHub project before the final cutover migration."
    )
    parser.add_argument(
        "--source-schema",
        default=os.environ.get("CEHUB_SOURCE_SCHEMA", "public"),
    )
    parser.add_argument("--report", required=True, type=Path)
    mode = parser.add_subparsers(dest="mode", required=True)
    mode.add_parser("capture", help="capture the full inventory for Data Owner review")
    verify = mode.add_parser("verify", help="verify the approved inventory immediately before use")
    verify.add_argument(
        "--expected-project-id",
        action="append",
        required=True,
        dest="expected_project_ids",
        help="approved CEHub source project id; repeat for every project, including archived ones",
    )
    return parser.parse_args()


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"required environment variable is missing: {name}")
    return value


def assess_cutover_inventory(
    *,
    projects: tuple[dict[str, Any], ...],
    source_schema: str,
    mode: str,
    expected_project_ids: tuple[str, ...] = (),
    approved_fingerprint: str | None = None,
) -> dict[str, object]:
    fingerprint = source_project_inventory_fingerprint(projects)
    actual_ids = tuple(str(project["source_id"]) for project in projects)
    unsupported = tuple(
        {
            "source_id": str(project["source_id"]),
            "project_number": str(project["project_number"]),
            "category": str(project["category"]),
        }
        for project in projects
        if str(project["category"]).strip().lower() not in SUPPORTED_PROJECT_CATEGORIES
    )
    errors: list[dict[str, object]] = []
    if not projects:
        errors.append(
            {
                "code": "EMPTY_SOURCE_INVENTORY",
                "message": "CEHub contains no projects; Data Owner review is required.",
            }
        )
    if unsupported:
        errors.append(
            {
                "code": "UNSUPPORTED_PROJECT_CATEGORY",
                "message": "The frozen v1 migrator supports only NPD and OBT projects.",
                "projects": list(unsupported),
            }
        )

    normalized_expected_ids = tuple(
        dict.fromkeys(project_id.strip() for project_id in expected_project_ids)
    )
    if mode == "verify":
        if any(not project_id for project_id in normalized_expected_ids):
            errors.append(
                {
                    "code": "BLANK_EXPECTED_PROJECT_ID",
                    "message": "Approved project ids must be nonblank source ids.",
                }
            )
        missing = sorted(set(actual_ids) - set(normalized_expected_ids))
        unexpected = sorted(set(normalized_expected_ids) - set(actual_ids))
        if missing or unexpected:
            errors.append(
                {
                    "code": "INVENTORY_SCOPE_MISMATCH",
                    "message": (
                        "Approved project ids must exactly match the complete source inventory."
                    ),
                    "missing_from_approval": missing,
                    "not_in_source": unexpected,
                }
            )
        if (
            approved_fingerprint is None
            or FINGERPRINT_PATTERN.fullmatch(approved_fingerprint) is None
            or not hmac.compare_digest(approved_fingerprint, fingerprint)
        ):
            errors.append(
                {
                    "code": "INVENTORY_FINGERPRINT_MISMATCH",
                    "message": (
                        "The current source inventory is not the Data Owner-approved inventory."
                    ),
                }
            )

    archived_count = sum(bool(project["archived"]) for project in projects)
    return {
        "mode": mode,
        "status": ("blocked" if errors else "review_required" if mode == "capture" else "ready"),
        "source_system": SOURCE_SYSTEM,
        "source_schema": source_schema,
        "inventory_fingerprint": fingerprint,
        "project_count": len(projects),
        "active_project_count": len(projects) - archived_count,
        "archived_project_count": archived_count,
        "actual_project_ids": list(actual_ids),
        "expected_project_ids": list(normalized_expected_ids),
        "errors": errors,
        "projects": list(projects),
    }


def _write_secure_report(report: dict[str, object], path: Path) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("cutover inventory report path must not be a symbolic link")
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
        validate_migration_endpoints(source_url=source_url, target_url=target_url)
        approved_fingerprint = None
        expected_project_ids: tuple[str, ...] = ()
        if arguments.mode == "verify":
            approved_fingerprint = _required_environment(
                "PDOS_CUTOVER_APPROVED_INVENTORY_FINGERPRINT"
            )
            expected_project_ids = tuple(arguments.expected_project_ids)
    except ValueError as error:
        raise SystemExit(f"cutover inventory refused: {error}") from error

    source_engine = create_engine(cehub_psycopg_database_url(source_url), pool_pre_ping=True)
    try:
        adapter = CeHubSourceAdapter(source_engine, source_schema=arguments.source_schema)
        projects = adapter.read_project_inventory()
        report = assess_cutover_inventory(
            projects=projects,
            source_schema=arguments.source_schema,
            mode=arguments.mode,
            expected_project_ids=expected_project_ids,
            approved_fingerprint=approved_fingerprint,
        )
        _write_secure_report(report, arguments.report)
        return 0 if report["status"] in {"review_required", "ready"} else 2
    except (SQLAlchemyError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "message": "cutover inventory was not captured; inspect server-side logs",
                },
                sort_keys=True,
            )
        )
        return 3
    finally:
        source_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
