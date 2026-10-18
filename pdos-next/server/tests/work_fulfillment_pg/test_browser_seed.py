"""Explicit private browser seed; root alone runs the guarded PG/HTTP setup.

The existing login and grants are retained without renewal. Native registered
evidence lets a later real API process read this case after fixture teardown.
This test starts no server and performs no fulfillment review for the browser.
"""

import os
import stat
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from release_policy_browser_seed.harness import _write_private_new
from sqlalchemy.orm import Session
from test_project_first_plan import cmd
from work_management_pg import test_workflow as flow
from work_management_pg.test_workflow import original_security_work  # noqa: F401
from work_management_pg.test_workflow import work as work_case  # noqa: F401

from pdos_next.domain.work_management.constants import ACCEPT, ASSIGN, COMMIT, CREATE, START, SUBMIT
from pdos_next.models import LoginSession, now
from pdos_next.service import digest


@pytest.fixture
def browser_work(request):
    return request.getfixturevalue("work_case")


def _destination():
    path = Path(os.environ["PDOS_FULFILLMENT_BROWSER_STATE"])
    assert path.is_absolute() and path.resolve() == path, "Use an absolute non-symlink seed path"
    directory = path.parent
    directory.mkdir(mode=0o700, exist_ok=True)
    state = directory.stat()
    assert directory.is_dir() and not directory.is_symlink()
    assert state.st_uid == os.getuid() and stat.S_IMODE(state.st_mode) == 0o700
    assert not path.exists(), "A browser seed must be a new private file"
    return path


@pytest.mark.skipif(
    not os.environ.get("PDOS_FULFILLMENT_BROWSER_STATE"),
    reason="Explicit absolute private PDOS_FULFILLMENT_BROWSER_STATE is required",
)
def test_prepare_actual_submitted_promise_for_recipient_browser_review(browser_work):
    path = _destination()
    work, setup = browser_work, browser_work.setup
    line = "Synthetic native drawing and optional inspection delivered for recipient review."
    registered = flow.send(
        work,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic durable browser fulfillment original",
                "content": line,
                "source_label": "Explicit isolated browser fixture, not production qualification",
                "visibility": "category",
            },
        ),
    )
    assert registered.status_code == 200, registered.text
    work.source = {
        "kind": "artifact",
        "id": registered.json()["subject_id"],
        "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(line.encode()).hexdigest(),
    }

    def step(operation, *, actor=None, **values):
        return flow.execute(work, operation, flow.payload(work, **values), actor=actor)[1]

    def task_ref(receipt):
        return {"id": receipt["result"]["task_id"], "revision": receipt["subject_revision"]}

    created = step(
        CREATE,
        title="Synthetic browser promise with optional inspection",
        goal="Recipient checks every explicitly promised result independently of task completion",
        outcomes=[
            {"key": "drawing", "text": "Required drawing", "required": True},
            {"key": "inspection", "text": "Optional inspection", "required": False},
        ],
        plan_task=None,
    )
    work.task_id = UUID(created["result"]["task_id"])
    assigned = step(
        ASSIGN,
        task=task_ref(created),
        assignee_id=str(setup.peer),
        recipient_id=str(setup.human),
    )
    accepted = step(ACCEPT, task=task_ref(assigned), actor=setup.peer)
    commitment = step(
        COMMIT,
        task=task_ref(accepted),
        recipient_id=str(setup.human),
        outcome_keys=["drawing", "inspection"],
        promised_at=None,
        original_timezone=flow.TIMEZONE,
        calendar_id=None,
        replaces=None,
        actor=setup.peer,
    )
    started = step(START, task=task_ref(accepted), **flow.clock_fields(), actor=setup.peer)
    step(
        SUBMIT,
        task=task_ref(started),
        **flow.clock_fields(),
        results=[
            {
                "key": key,
                "text": f"Actual synthetic {key} result for explicit browser acceptance",
                "status": "present",
                "sources": [work.source],
            }
            for key in ("drawing", "inspection")
        ],
        actor=setup.peer,
    )
    recipient_token = setup.tokens[setup.human]
    with Session(setup.admin) as session:
        login = session.get(LoginSession, digest(recipient_token))
        assert login is not None and login.principal_id == setup.human
        assert login.expires_at > now()
    _write_private_new(
        path,
        {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
            "promisor_id": str(setup.peer),
            "recipient_id": str(setup.human),
            "recipient_token": recipient_token,
            "task_id": str(work.task_id),
            "commitment_id": commitment["subject_id"],
        },
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
