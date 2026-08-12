from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from uuid import UUID

import pytest

from app.migrations.cehub_v1 import MigrationReport
from scripts.migrate_cehub_v1 import (
    _write_report,
    migration_apply_confirmation,
    validate_migration_endpoints,
)
from scripts.migrate_cehub_v1 import main as migration_cli_main

RDS_HOST = "pgm-2ze135h6045td5ujvo.pg.rds.aliyuncs.com"
CA_PATH = "/app/certs/ApsaraDB-CA-Chain.pem"
TARGET_URL = (
    f"postgresql://pdos_app:target-secret@{RDS_HOST}:5432/pdos"
    f"?sslmode=verify-full&sslrootcert={CA_PATH}"
)
SOURCE_URL = (
    f"postgresql://pdos_cehub_readonly:source-secret@{RDS_HOST}:5432/cehub"
    f"?sslmode=verify-full&sslrootcert={CA_PATH}&uselibpqcompat=true"
)


def migration_report() -> MigrationReport:
    return MigrationReport(
        mode="dry-run",
        status="ready",
        source_system="cehub-v3",
        source_schema="public",
        selected_project_ids=("zGpNH0Xq", "aBnbEdQG"),
        source_fingerprint="frozen-source-fingerprint",
        source_counts={"projects": 2},
        created_counts={"projects": 0},
        skipped_counts={"projects": 0},
        target_writes=0,
        errors=(),
        samples=(),
    )


def test_report_is_atomically_created_owner_only_even_with_open_umask(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path / "migration-report.json"
    previous_umask = os.umask(0)
    try:
        _write_report(migration_report(), report_path)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    assert json.loads(report_path.read_text())["target_writes"] == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_report_refuses_a_symbolic_link_without_touching_its_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "operator-owned.txt"
    target.write_text("must remain unchanged")
    report_path = tmp_path / "migration-report.json"
    report_path.symlink_to(target)

    with pytest.raises(ValueError, match="symbolic link"):
        _write_report(migration_report(), report_path)

    assert report_path.is_symlink()
    assert target.read_text() == "must remain unchanged"


def test_apply_confirmation_is_bound_to_tenant_fingerprint_and_bounded_scope() -> None:
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    fingerprint = "a" * 64

    confirmation = migration_apply_confirmation(
        tenant_id=tenant_id,
        source_fingerprint=fingerprint,
        project_ids=("C4s", "S18-01", "C4s"),
    )

    assert confirmation == f"apply:{tenant_id}:{fingerprint}:C4s,S18-01"
    assert confirmation != migration_apply_confirmation(
        tenant_id=tenant_id,
        source_fingerprint="b" * 64,
        project_ids=("C4s", "S18-01"),
    )
    with pytest.raises(ValueError, match="SHA-256"):
        migration_apply_confirmation(
            tenant_id=tenant_id,
            source_fingerprint="not-a-fingerprint",
            project_ids=("C4s",),
        )


def test_apply_cli_refuses_before_connecting_without_bound_human_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    fingerprint = "a" * 64
    monkeypatch.setenv(
        "CEHUB_SOURCE_DATABASE_URL",
        SOURCE_URL,
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        TARGET_URL,
    )
    monkeypatch.setenv("PDOS_TENANT_ID", tenant_id)
    monkeypatch.setenv("PDOS_MIGRATION_ACTOR_USER_ID", "22222222-2222-2222-2222-222222222222")
    monkeypatch.setenv("PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT", fingerprint)
    monkeypatch.delenv("PDOS_MIGRATION_APPLY_CONFIRM", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        ["migrate_cehub_v1", "--apply", "--project-id", "C4s"],
    )

    with pytest.raises(SystemExit, match="apply refused"):
        migration_cli_main()


def test_apply_cli_reports_missing_approval_without_echoing_database_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CEHUB_SOURCE_DATABASE_URL", SOURCE_URL)
    monkeypatch.setenv("DATABASE_URL", TARGET_URL)
    monkeypatch.setenv("PDOS_TENANT_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("PDOS_MIGRATION_ACTOR_USER_ID", "22222222-2222-2222-2222-222222222222")
    monkeypatch.delenv("PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        ["migrate_cehub_v1", "--apply", "--project-id", "C4s"],
    )

    with pytest.raises(SystemExit) as refused:
        migration_cli_main()

    message = str(refused.value)
    assert "PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT" in message
    assert SOURCE_URL not in message
    assert TARGET_URL not in message


@pytest.mark.parametrize(
    ("source_url", "target_url"),
    [
        (SOURCE_URL.replace(RDS_HOST, "other-rds.example"), TARGET_URL),
        (SOURCE_URL.replace("pdos_cehub_readonly", "pdos_app"), TARGET_URL),
        (SOURCE_URL.replace("/cehub?", "/pdos?"), TARGET_URL),
        (SOURCE_URL.replace("sslmode=verify-full", "sslmode=require"), TARGET_URL),
        (SOURCE_URL, TARGET_URL.replace("/pdos?", "/pdos_test?")),
    ],
)
def test_migration_cli_rejects_unapproved_source_or_target_endpoints(
    source_url: str,
    target_url: str,
) -> None:
    with pytest.raises(ValueError):
        validate_migration_endpoints(source_url=source_url, target_url=target_url)


def test_migration_cli_accepts_same_rds_distinct_roles_and_verified_tls() -> None:
    validate_migration_endpoints(source_url=SOURCE_URL, target_url=TARGET_URL)


def test_runbook_uses_the_exact_non_root_candidate_image_and_read_only_container() -> None:
    runbook = (
        Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "cehub-migration-v1.md"
    ).read_text()

    assert "PDOS_MIGRATION_IMAGE='pdos-api:<approved-git-sha>'" in runbook
    assert "docker image inspect" in runbook
    assert "--owner 10001 --group 10001" in runbook
    assert "docker run --rm --read-only --security-opt no-new-privileges" in runbook
    assert "--env-file .env.production" in runbook
    assert "dst=/reports" in runbook
    assert "PDOS_MIGRATION_REPORT_DIR" in runbook
    assert "$(pwd)/output/migrations" not in runbook
    assert "不能在宿主机直接运行 Python" in runbook
