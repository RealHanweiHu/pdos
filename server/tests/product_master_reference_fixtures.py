"""Synthetic published product fixture helpers; callers must supply isolated pdos_test."""

from contextlib import suppress
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.db.schema import tables
from app.db.test_safety import UnsafeTestDatabaseError, configured_test_database_url
from tests.test_product_planning_findings_api import setup_candidate
from tests.test_product_work_result_evidence_api import evidence
from tests.test_test_runs_api import Scope


def checked_master_reference_test_database_url() -> str:
    """Reject known retained DBs before the shared migration/tenant cleanup fixture."""
    value = configured_test_database_url()
    target = make_url(value)
    host = (target.host or "").lower().rstrip(".")
    local = host == "localhost"
    with suppress(ValueError):
        local = local or ip_address(host).is_loopback
    if local and target.port in {57432, 57433, 57434, 57439, 57440}:
        raise UnsafeTestDatabaseError(
            "Refusing master-reference tests: target is a retained or reserved integration DB"
        )
    return value


@pytest.fixture(scope="session", autouse=True)
def master_reference_database_guard() -> None:
    # Session scope puts this check before the function-scoped shared fixture,
    # which upgrades and clears tenants. URL shape is not allocation authorization.
    checked_master_reference_test_database_url()


@dataclass
class MasterCandidate:
    scope: Scope
    client: TestClient
    base: str
    headers: dict[str, str]
    definition: dict[str, Any]
    reference: dict[str, Any]

    @property
    def product_id(self) -> UUID:
        return UUID(self.definition["product_id"])

    @property
    def url(self) -> str:
        return self.base + f"/products/{self.product_id}/master-references"

    def read(self, headers: dict[str, str] | None = None) -> dict[str, Any]:
        response = self.client.get(self.url, headers=headers or self.headers)
        assert response.status_code == 200, response.text
        return dict(response.json())

    def request(self, **changes: Any) -> dict[str, Any]:
        body: dict[str, Any] = dict(
            request_id=str(uuid4()),
            expected_context_digest=self.read()["context_digest"],
            action="register",
            previous_id=None,
            system_kind="erp",
            source_system="SYNTHETIC_ERP",
            master_kind="material",
            external_id="TEST-MATERIAL",
            external_revision="A",
            external_as_of=self.reference["as_of"],
            sources=[self.reference],
            reason="合成内部引用核对",
        )
        body.update(changes)
        return body

    def save(
        self, body: dict[str, Any], status: int = 201, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        response = self.client.post(self.url, headers=headers or self.headers, json=body)
        assert response.status_code == status, response.text
        return dict(response.json())

    def state(self) -> tuple[list[dict[str, Any]], int, int]:
        table = tables.product_master_references
        with self.scope.engine.connect() as c:
            rows = [
                dict(row)
                for row in c.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == self.scope.tenant_id,
                        table.c.product_id == self.product_id,
                    )
                    .order_by(table.c.created_at, table.c.id)
                ).mappings()
            ]
            events = c.execute(
                select(func.count())
                .select_from(tables.events)
                .where(tables.events.c.tenant_id == self.scope.tenant_id)
            ).scalar_one()
            audits = c.execute(
                select(func.count())
                .select_from(tables.audit_log)
                .where(tables.audit_log.c.tenant_id == self.scope.tenant_id)
            ).scalar_one()
        return rows, events, audits

    def evidence(self, kind: Literal["body", "metadata", "blank"]) -> dict[str, Any]:
        return evidence(self.scope, kind)


def seed_master_candidate(
    client: TestClient, scope: Scope, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> MasterCandidate:
    base, headers, definition, calls = setup_candidate(
        client, scope, tmp_path, monkeypatch, "product_definition", revision=True, seed_only=True
    )
    assert calls == []
    return MasterCandidate(scope, client, base, headers, definition, evidence(scope, "body"))
