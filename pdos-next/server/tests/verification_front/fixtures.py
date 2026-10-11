"""Explicit isolated PG fixtures; synthetic import is never a production credential."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from test_build_execution import actual, lot, planned  # noqa: F401
from test_builds import configuration, definition, project  # noqa: F401
from test_project_first_plan import accepted, cmd
from test_verification_execution import (
    command as preparation_command,
)
from test_verification_execution import (
    payload as preparation_payload,
)
from test_verification_execution import (
    reference,
    row_for,
    verification_work,  # noqa: F401
)

from pdos_next.database import tenant_session
from pdos_next.domain.professional_authority.service import (
    configure_local_synthetic,
    trusted_import,
)
from pdos_next.models import now


@pytest.fixture
def front_work(setup, verification_work):  # noqa: F811 - imported fixture
    work = verification_work
    data = preparation_payload(work)
    item = data["items"][0]
    item["method"] = reference(work, 2)
    item["criterion"] = {"lower": "9.5", "upper": "10.5", "source": reference(work, 2)}
    data["documents"][0]["source"] = reference(work, 3)
    receipt, _ = accepted(setup, preparation_command(setup, work, data))
    prep = row_for(setup, receipt)
    previous_registry = getattr(setup.engine, "_pdos_professional_issuers", None)
    previous_synthetic = getattr(setup.engine, "_pdos_professional_synthetic", None)
    issuer = configure_local_synthetic(
        setup.engine,
        tenant_id=setup.tenant,
        product_id=setup.product,
        project_id=UUID(prep["project_id"]),
        enabled=True,
        key=f"synthetic-wave10-{setup.tenant}",
    )
    result = SimpleNamespace(setup=setup, work=work, preparation=prep, issuer=issuer, facts={})
    try:
        for kind in ("duty", "qualification"):
            result.facts[kind] = import_fact(result, kind)
        yield result
    finally:
        if previous_registry is None:
            if hasattr(setup.engine, "_pdos_professional_issuers"):
                delattr(setup.engine, "_pdos_professional_issuers")
        else:
            setup.engine._pdos_professional_issuers = previous_registry
        if previous_synthetic is None:
            if hasattr(setup.engine, "_pdos_professional_synthetic"):
                delattr(setup.engine, "_pdos_professional_synthetic")
        else:
            setup.engine._pdos_professional_synthetic = previous_synthetic


def import_fact(work, kind, *, previous=None, **changes):
    setup = work.setup
    data = {
        "product_id": setup.product,
        "project_id": UUID(work.preparation["project_id"]),
        "subject_id": setup.human,
        "external_id": f"SYN-{kind}-{setup.human}",
        "kind": kind,
        "role": "quality",
        "operations": [
            "verification.request.create",
            "verification.method.prepare",
            "verification.schedule.propose",
        ],
        "purposes": [work.preparation["purpose"]],
        "state": "active",
        "valid_from": now() - timedelta(days=1),
        "valid_until": now() + timedelta(days=1),
        "previous_id": previous["id"] if previous else None,
        "expected_previous_revision": previous["revision"] if previous else 0,
        "approval": {
            "system": "synthetic-unit-import",
            "external_id": f"SYN-{kind}-APPROVAL",
            "version": "fixture-only-v1",
            "approved_by": "Synthetic issuer; no real qualification",
            "issued_at": now() - timedelta(hours=1),
        },
        "sources": [reference(work.work, 1)],
        "reason": "Explicit synthetic professional fixture",
        **changes,
    }
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        return trusted_import(session, setup.ctx, work.issuer, data)


def listed(work, *, headers=None):
    response = work.setup.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-professional",
        headers=headers or work.setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def current_preparation(work):
    return next(row for row in listed(work)["preparations"] if row["id"] == work.preparation["id"])


def create_command(work, **changes):
    prep = current_preparation(work)
    data = {
        "request_id": str(uuid4()),
        "preparation_id": prep["id"],
        "expected_preparation_revision": prep["revision"],
        "preparation_sha256": prep["sha256"],
        "reason": "Synthetic fixed request; no handoff authority",
        **changes,
    }
    command = cmd(work.setup, "verification.request.create", data)
    command["source_read_set"] = prep["required_source_read_set"]
    return command


def send(work, command, *, preview=False, headers=None):
    return work.setup.client.post(
        f"/v1/categories/{work.setup.category}/commands" + ("/preview" if preview else ""),
        headers=headers or work.setup.headers,
        json=command,
    )


def request_row(work, receipt):
    return next(row for row in listed(work)["requests"] if row["id"] == receipt["subject_id"])


def created(work):
    command = create_command(work)
    response = send(work, command)
    assert response.status_code == 200, response.text
    return response.json(), request_row(work, response.json()), command


def method_command(work, row, *, status="applicable"):
    data = {
        "request_id": row["request_id"],
        "expected_request_revision": row["revision"],
        "assessments": [
            {
                "item_id": item["id"],
                "status": status,
                "conditions": [],
                "reason": "Synthetic scoped method review",
                "sources": [reference(work.work, 2)] if status == "applicable" else [],
            }
            for item in row["items"]
        ],
        "reason": "Synthetic qualified reviewer fact; no actual test qualification",
    }
    command = cmd(work.setup, "verification.method.prepare", data)
    command["source_read_set"] = row["required_source_read_set"]
    return command


def reviewed(work, command):
    response = send(work, command, preview=True)
    assert response.status_code == 200, response.text
    return response.json()["command"]


def method_saved(work, row, *, status="applicable"):
    prepared = reviewed(work, method_command(work, row, status=status))
    response = send(work, prepared)
    assert response.status_code == 200, response.text
    return response.json(), request_row(work, response.json()), prepared


def schedule_command(work, row):
    start = now() + timedelta(days=2)
    command = cmd(
        work.setup,
        "verification.schedule.propose",
        {
            "request_id": row["request_id"],
            "expected_request_revision": row["revision"],
            "start": start.isoformat(),
            "finish": (start + timedelta(hours=2)).isoformat(),
            "original_timezone": "America/Los_Angeles",
            "resource_intents": [],
            "duration_basis": None,
            "calendar_source": None,
            "sources": [],
            "reason": "Synthetic proposed interval with unknown resources; zero occupancy",
        },
    )
    command["source_read_set"] = deepcopy(row["required_source_read_set"])
    return command
