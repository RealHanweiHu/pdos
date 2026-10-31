from copy import deepcopy
from uuid import uuid4

from pdos_next.domain.work_management.constants import ASSIGN, CREATE
from pdos_next.domain.work_management.templates import catalog
from tests.work_management_pg.test_workflow import (
    execute,
    headers,
    original_security_work,  # noqa: F401
    payload,
    root,
    send,
    work,  # noqa: F401
    workspace,
)


def test_template_task_persists_real_phase_outcomes_and_survives_assignment(work):  # noqa: F811
    response = work.setup.client.get(
        root(work) + f"/project-work/templates?project_id={work.project_id}", headers=headers(work)
    )
    assert response.status_code == 200, response.text
    template = next(row for row in response.json()["items"] if row["checks"])
    command, receipt = execute(
        work,  # noqa: F401
        CREATE,
        payload(
            work,  # noqa: F401
            title=template["title"],
            goal=template["goal"],
            outcomes=template["checks"],
            npi_template=template["reference"],
        ),
    )
    assert send(work, command).json()["id"] == receipt["id"]
    task = workspace(work)["tasks"][0]
    assert task["npi_template"] == template["reference"]
    assert task["outcomes"] == template["checks"]
    execute(
        work,  # noqa: F401
        ASSIGN,
        payload(
            work,  # noqa: F401
            task={"id": task["id"], "revision": task["revision"]},
            assignee_id=str(work.setup.peer),
            recipient_id=str(work.setup.human),
        ),
    )
    assert workspace(work)["tasks"][0]["npi_template"] == template["reference"]


def test_template_cannot_forge_phase_or_replace_project_evidence(work):  # noqa: F811
    from test_project_first_plan import cmd

    template = deepcopy(catalog()["items"][0])
    template["reference"]["phase_name"] = "forged"
    data = payload(
        work,  # noqa: F401
        title=template["title"],
        goal=template["goal"],
        outcomes=[{"key": "report", "text": "真实成果", "required": True}],
        npi_template=template["reference"],
    )
    request = cmd(work.setup, CREATE, data)
    result = work.setup.client.post(
        root(work) + "/project-work/inputs", headers=headers(work), json=request
    )
    assert result.status_code == 409, result.text
    data["npi_template"] = catalog()["items"][0]["reference"]
    data["sources"] = []
    assert send(work, cmd(work.setup, CREATE, data)).status_code == 422
    assert (
        work.setup.client.get(
            root(work) + f"/project-work/templates?project_id={uuid4()}", headers=headers(work)
        ).status_code
        == 403
    )
