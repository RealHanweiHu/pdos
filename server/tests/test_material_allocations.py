"""Cross-project pool arithmetic with read-query doubles; no live database."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import Connection

from app.domain import material_allocations, material_movements

TENANT, PROJECT, OTHER, SOURCE, A, B, GRANT = (UUID(int=i) for i in range(1, 8))
KEY = ("ERP", "pool", "part")
NOW = datetime(2020, 1, 1, tzinfo=UTC)


def test_pool_deducts_all_projects_and_unreconciled_partial_issues_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dict(
        id=SOURCE,
        project_id=PROJECT,
        source_system="ERP",
        external_pool_id="pool",
        external_item_id="part",
        unit="个",
        quantity=Decimal("12"),
        quality_status="released",
        fresh_until=NOW + timedelta(days=1),
    )
    allocations = [
        dict(
            id=str(A),
            project_id=str(PROJECT),
            unit="个",
            remaining_quantity="4",
            source_system="ERP",
            external_pool_id="pool",
            external_item_id="part",
        ),
        dict(
            id=str(B),
            project_id=str(OTHER),
            unit="个",
            remaining_quantity="3",
            source_system="ERP",
            external_pool_id="pool",
            external_item_id="part",
        ),
    ]
    connection = MagicMock()
    supply, grants = MagicMock(), MagicMock()
    supply.mappings.return_value = iter([source])
    grants.mappings.return_value = iter([])
    connection.execute.side_effect = [supply, grants]
    monkeypatch.setattr(material_allocations, "_active", lambda *args, **kwargs: allocations)
    monkeypatch.setattr(
        material_movements,
        "pending_issued",
        lambda *args: {str(A): Decimal("2"), str(B): Decimal("1")},
    )
    pool = material_allocations._pools(
        cast(Connection, connection), TENANT, PROJECT, [KEY], as_of=NOW
    )[KEY]
    assert pool["reserved_quantity"] == "10"
    assert pool["pending_issue_quantity"] == "3"
    assert pool["available_quantity"] == "2"
    assert pool["allocatable"]


def test_latest_foreign_pool_without_current_grant_cannot_reuse_old_local_supply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = dict(
        id=SOURCE,
        project_id=OTHER,
        source_system="ERP",
        external_pool_id="pool",
        external_item_id="part",
        unit="个",
        quantity=Decimal("12"),
        quality_status="released",
        fresh_until=NOW + timedelta(days=1),
    )
    connection = MagicMock()
    supply, grants = MagicMock(), MagicMock()
    supply.mappings.return_value = iter([source])
    grants.mappings.return_value = iter([])
    connection.execute.side_effect = [supply, grants]
    monkeypatch.setattr(material_allocations, "_active", lambda *args, **kwargs: [])
    pool = material_allocations._pools(
        cast(Connection, connection), TENANT, PROJECT, [KEY], as_of=NOW
    )[KEY]
    assert pool["state"] == "current_source_unreadable"
    assert pool["source"] is None and pool["available_quantity"] is None
    assert not pool["allocatable"]
