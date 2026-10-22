"""One actual S5 loop exporting unchanged paired GET DTOs for read-only UI QA.

Only root executes this test with explicitly verified isolated pdos_test URLs.
Originals, tasks, promises and reviews use existing real fixture/command flows.
No model, new domain endpoint, permission expansion or direct fact insertion.
"""

import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_original_security import security_work as base_security_work  # noqa: F401
from work_fulfillment_pg import test_workflow as fulfillment
from work_management_pg import test_workflow as flow
from work_management_pg.test_workflow import work as work_case  # noqa: F401

from pdos_next.api import create_app
from pdos_next.domain.work_fulfillment.models import (
    WorkCommitmentReview,
    WorkCommitmentReviewCurrent,
)
from pdos_next.domain.work_management.constants import (
    ACCEPT,
    ASSIGN,
    COMMIT,
    CREATE,
    REVIEW,
    START,
    SUBMIT,
)
from pdos_next.models import (
    Artifact,
    OriginalScanRequest,
    OriginalScanResult,
    OriginalSecurity,
    UploadedOriginal,
    now,
)


@pytest.fixture
def original_security_work(request):
    """Retain the existing synthetic scanner/store, explicitly disable workflows."""
    security = request.getfixturevalue("base_security_work")
    original_client = security.client
    client = TestClient(
        create_app(
            security.setup.engine,
            security.setup.auth,
            object_store=security.store,
            security_runtime=security.runtime,
            workflow_enabled=False,
        )
    )
    security.client = client
    try:
        yield security
    finally:
        security.client = original_client
        client.close()


@pytest.fixture
def projection_work(request):
    return request.getfixturevalue("work_case")


def _counts(work):
    # Deliberately enumerate only this loop's existing models. Do not inspect
    # Base.metadata while unrelated S3/S4/S5 schema work is in flight.
    models = (
        *flow.MODELS,
        WorkCommitmentReview,
        WorkCommitmentReviewCurrent,
        Artifact,
        OriginalSecurity,
        UploadedOriginal,
        OriginalScanRequest,
        OriginalScanResult,
    )
    with Session(work.setup.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in models
        }


def _paired_reads(work, phase):
    before = _counts(work)
    routes = {
        "project_work": flow.root(work) + "/project-work",
        "fulfillment": flow.root(work) + "/project-work/fulfillment",
    }
    bodies = {}
    for name, route in routes.items():
        response = work.setup.client.get(
            route,
            params={"project_id": str(work.project_id)},
            headers=flow.headers(work),
        )
        assert response.status_code == 200, response.text
        bodies[name] = response.json()
    after = _counts(work)
    assert before == after

    plain, reviews = bodies["project_work"], bodies["fulfillment"]
    assert plain["project"] == reviews["project"]
    assert plain["product_revision"] == reviews["product_revision"]
    by_id = {item["id"]: item for item in reviews["commitments"]}
    assert set(by_id) == {item["id"] for item in plain["commitments"]}
    for promise in plain["commitments"]:
        paired = by_id[promise["id"]]
        # Match the same actual immutable promise, never only its task/series.
        assert all(paired[key] == value for key, value in promise.items())
        task = next(item for item in plain["tasks"] if item["id"] == promise["task_id"])
        assert all(
            paired["task"][key] == task[key]
            for key in (
                "id",
                "version_id",
                "revision",
                "title",
                "state",
            )
        )
        if paired["submission"] is not None:
            submission = paired["submission"]
            assert any(
                row["id"] == submission["id"]
                and row["revision"] == submission["revision"]
                and row["action"] == "submit"
                for row in task["history"]
            )
    return {
        "phase": phase,
        "reader_id": str(work.setup.human),
        "routes": routes,
        **bodies,
        "read_only_counts": {"before": before, "after": after, "unchanged": True},
    }


def _export(work, phases):
    destination = os.environ.get("PDOS_PROJECT_COMMITMENT_PROJECTION_QA_RESPONSE_PATH")
    if not destination:
        return
    path = Path(destination)
    assert path.is_absolute(), "Actual paired DTO export requires an explicit absolute path"
    bundle = {
        "version": "project-commitment-projection-qa/v1",
        "fixture_nature": "actual HTTP/domain commands over isolated synthetic evidence",
        "scope": {
            "category_id": str(work.setup.category),
            "product_id": str(work.setup.product),
            "project_id": str(work.project_id),
            "principal_id": str(work.setup.human),
            "promisor_id": str(work.setup.peer),
        },
        "phases": phases,
        "limitations": [
            "Both actual GET JSON bodies retain their original unmodified shapes.",
            "Paired GETs have distinct snapshots/as_of; no shared transaction is implied.",
            "Current task/submission context adds no fixed refs to historical reviews.",
            "Synthetic scanner facts are not production qualification; no model/external calls.",
        ],
    }
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert all(token not in encoded for token in work.setup.tokens.values())
    for forbidden in ("confirmation_token", "approval_token", "storage_key", "locator_map"):
        assert forbidden not in encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")


def test_actual_paired_reads_keep_recipient_review_history_and_exact_version_fulfillment(
    projection_work,
):
    work, phases = projection_work, []
    setup = work.setup

    def step(operation, *, actor=None, **values):
        return flow.execute(work, operation, flow.payload(work, **values), actor=actor)[1]

    def promise(task, recipient, keys, *, replaces=None, promised_at=None):
        return step(
            COMMIT,
            task=task,
            recipient_id=str(recipient),
            outcome_keys=keys,
            promised_at=promised_at,
            original_timezone=flow.TIMEZONE,
            calendar_id=None,
            replaces=replaces,
            actor=setup.peer,
        )

    created = step(
        CREATE,
        title="Synthetic paired commitment projection",
        goal="Keep recipient-specific promise versions and independent actual reviews readable",
        outcomes=[
            {"key": "drawing", "text": "Required synthetic drawing", "required": True},
            {"key": "inspection", "text": "Optional synthetic inspection", "required": False},
        ],
        plan_task=None,
    )
    work.task_id = UUID(created["result"]["task_id"])
    assigned = step(
        ASSIGN,
        task=fulfillment._task_ref(created),
        assignee_id=str(setup.peer),
        recipient_id=str(setup.human),
    )
    accepted = step(ACCEPT, task=fulfillment._task_ref(assigned), actor=setup.peer)
    first_a = promise(fulfillment._task_ref(accepted), setup.human, ["drawing", "inspection"])
    deadline = (now() + timedelta(days=1)).isoformat()
    first_b = promise(
        fulfillment._task_ref(accepted), setup.peer, ["drawing"], promised_at=deadline
    )
    started = step(
        START, task=fulfillment._task_ref(accepted), **flow.clock_fields(), actor=setup.peer
    )
    submitted = step(
        SUBMIT,
        task=fulfillment._task_ref(started),
        **flow.clock_fields(),
        results=[
            {
                "key": key,
                "text": f"Actual isolated synthetic {key} material",
                "status": "present",
                "sources": [work.source],
            }
            for key in ("drawing", "inspection")
        ],
        actor=setup.peer,
    )
    returned = fulfillment._save(
        work,
        fulfillment._declaration(
            work,
            fulfillment._ref(first_a),
            fulfillment._task_ref(submitted),
            fulfillment._ref(submitted),
            decision="returned",
            checks=fulfillment._checks("drawing", "inspection", rejected=("inspection",)),
        ),
    )[1]
    received_b = fulfillment._save(
        work,
        fulfillment._declaration(
            work,
            fulfillment._ref(first_b),
            fulfillment._task_ref(submitted),
            fulfillment._ref(submitted),
            checks=fulfillment._checks("drawing"),
        ),
        actor=setup.peer,
    )[1]
    phases.append(_paired_reads(work, "returned_open_and_fulfilled"))
    first = {row["id"]: row for row in phases[-1]["fulfillment"]["commitments"]}
    a, b = first[first_a["subject_id"]], first[first_b["subject_id"]]
    assert a["recipient_id"] != b["recipient_id"]
    assert a["task"]["state"] == b["task"]["state"] == "submitted"
    assert a["fulfillment"]["state"] == "open" and a["fulfillment"]["revision"] == 1
    assert a["fulfillment"]["review"]["decision"] == "returned"
    assert a["fulfillment"]["review"]["receipt_id"] == returned["id"]
    assert b["fulfillment"]["state"] == "fulfilled"
    assert b["fulfillment"]["review"]["receipt_id"] == received_b["id"]
    assert a["promised_at"] is None and b["promised_at"] is not None

    successor_b = promise(
        fulfillment._task_ref(submitted),
        setup.peer,
        ["drawing"],
        replaces=fulfillment._ref(first_b),
        promised_at=deadline,
    )
    phases.append(_paired_reads(work, "successor_open_predecessor_fulfilled"))
    second = {row["id"]: row for row in phases[-1]["fulfillment"]["commitments"]}
    old_b, new_b = second[first_b["subject_id"]], second[successor_b["subject_id"]]
    assert old_b["series_id"] == new_b["series_id"]
    assert old_b["status"] == "superseded" and old_b["fulfillment"]["state"] == "fulfilled"
    assert new_b["status"] == "current" and new_b["revision"] == 2
    assert new_b["fulfillment"] == {"state": "open", "revision": 0, "review": None, "history": []}

    completed = step(
        REVIEW,
        task=fulfillment._task_ref(submitted),
        decision="accepted",
        **flow.clock_fields(),
        checks=fulfillment._checks("drawing", "inspection"),
    )
    received_a = fulfillment._save(
        work,
        fulfillment._declaration(
            work,
            fulfillment._ref(first_a),
            fulfillment._task_ref(completed),
            fulfillment._ref(submitted),
            revision=1,
            checks=fulfillment._checks("drawing", "inspection"),
        ),
    )[1]
    phases.append(_paired_reads(work, "completed_task_independent_fulfillment_history"))
    final = {row["id"]: row for row in phases[-1]["fulfillment"]["commitments"]}
    a, new_b = final[first_a["subject_id"]], final[successor_b["subject_id"]]
    assert a["task_revision"] == 3 and a["task"]["revision"] == 6
    assert a["task"]["state"] == new_b["task"]["state"] == "completed"
    assert a["submission"]["id"] == submitted["subject_id"]
    assert a["submission"]["revision"] == 5
    assert a["fulfillment"]["state"] == "fulfilled" and a["fulfillment"]["revision"] == 2
    assert [(row["decision"], row["state"]) for row in a["fulfillment"]["history"]] == [
        ("returned", "open"),
        ("accepted", "fulfilled"),
    ]
    assert a["fulfillment"]["review"]["receipt_id"] == received_a["id"]
    assert a["promised_at"] is None
    assert new_b["fulfillment"]["state"] == "open" and new_b["fulfillment"]["history"] == []
    assert final[first_b["subject_id"]]["fulfillment"]["state"] == "fulfilled"
    _export(work, phases)
