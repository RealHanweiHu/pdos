from __future__ import annotations

from copy import deepcopy
from typing import cast

from scripts.check_cehub_cutover_inventory import assess_cutover_inventory


def _projects() -> tuple[dict[str, object], ...]:
    return (
        {
            "source_id": "active-1",
            "project_number": "S18-01",
            "name": "Active",
            "category": "npd",
            "current_phase": "dvt",
            "archived": False,
            "lifecycle": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
            "source_hash": "a" * 64,
        },
        {
            "source_id": "archive-1",
            "project_number": "OLD-01",
            "name": "Archived",
            "category": "obt",
            "current_phase": "mp",
            "archived": True,
            "lifecycle": "active",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2026-07-01T00:00:00+00:00",
            "source_hash": "b" * 64,
        },
    )


def test_capture_includes_active_and_archived_projects_for_human_review() -> None:
    report = assess_cutover_inventory(
        projects=_projects(),
        source_schema="public",
        mode="capture",
    )

    assert report["status"] == "review_required"
    assert report["project_count"] == 2
    assert report["active_project_count"] == 1
    assert report["archived_project_count"] == 1
    assert report["actual_project_ids"] == ["active-1", "archive-1"]
    assert report["errors"] == []


def test_verify_requires_exact_scope_and_approved_fingerprint() -> None:
    capture = assess_cutover_inventory(
        projects=_projects(),
        source_schema="public",
        mode="capture",
    )
    report = assess_cutover_inventory(
        projects=_projects(),
        source_schema="public",
        mode="verify",
        expected_project_ids=("active-1", "archive-1"),
        approved_fingerprint=str(capture["inventory_fingerprint"]),
    )

    assert report["status"] == "ready"
    assert report["errors"] == []


def test_verify_fails_closed_on_scope_source_drift_or_unknown_category() -> None:
    capture = assess_cutover_inventory(
        projects=_projects(),
        source_schema="public",
        mode="capture",
    )
    changed = list(deepcopy(_projects()))
    changed[0]["category"] = "service"
    changed[0]["updated_at"] = "2026-08-13T00:00:00+00:00"
    report = assess_cutover_inventory(
        projects=tuple(changed),
        source_schema="public",
        mode="verify",
        expected_project_ids=("active-1",),
        approved_fingerprint=str(capture["inventory_fingerprint"]),
    )

    assert report["status"] == "blocked"
    errors = cast(list[dict[str, object]], report["errors"])
    assert {error["code"] for error in errors} == {
        "UNSUPPORTED_PROJECT_CATEGORY",
        "INVENTORY_SCOPE_MISMATCH",
        "INVENTORY_FINGERPRINT_MISMATCH",
    }
