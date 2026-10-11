from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.projects.models import (
    PlanProposal,
    PlanRevision,
    Project,
    ProjectProductLink,
    ProjectTask,
    ProjectWorkPackage,
    TaskDependency,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Confirmation, Grant, Outbox, Receipt, now


def cmd(setup, operation, payload, source=None):
    return {
        "category_id": str(setup.category),
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "product_id": str(setup.product),
        "expected_revision": 1,
        "source_read_set": [{"artifact_id": source, "expected_revision": 1}] if source else [],
        "payload": payload,
    }


def post(setup, command, preview=False):
    return setup.client.post(
        f"/v1/categories/{setup.category}/commands" + ("/preview" if preview else ""),
        headers=setup.headers,
        json=command,
    )


@pytest.fixture
def definition(setup):
    source = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic project input",
                "content": "Synthetic requirement is unverified",
                "source_label": "Synthetic fixture",
                "visibility": "private",
            },
        ),
    ).json()["subject_id"]
    result = post(
        setup,
        cmd(
            setup,
            "product.definition.draft",
            {
                "title": "Synthetic fixed draft",
                "purpose": "Verify real development project binding",
                "use_cases": ["Synthetic development"],
                "change_reason": "First draft",
                "sources": [
                    {
                        "artifact_id": source,
                        "expected_revision": 1,
                        "line": 1,
                        "quote": "Synthetic requirement is unverified",
                    }
                ],
            },
            source,
        ),
    )
    assert result.status_code == 200, result.text
    return source, result.json()["subject_id"]


def project_command(setup, definition):
    source, fixed = definition
    return cmd(
        setup,
        "project.create",
        {
            "name": "Synthetic development",
            "purpose": "Build and verify a synthetic design",
            "scope": "Engineering design and NPI preparation only",
            "definition_id": fixed,
            "expected_definition_revision": 1,
            "visibility": "private",
        },
        source,
    )


def accepted(setup, command):
    preview = post(setup, command, True)
    assert preview.status_code == 200, preview.text
    result = post(setup, preview.json()["command"])
    assert result.status_code == 200, result.text
    return result.json(), preview.json()["command"]


@pytest.fixture
def project(setup, definition):
    receipt, _ = accepted(setup, project_command(setup, definition))
    return receipt["subject_id"]


def proposal_command(setup, definition, project):
    return cmd(
        setup,
        "work.plan.propose",
        {
            "project_id": project,
            "expected_project_revision": 1,
            "reason": "Record bounded engineering estimate and unknown NPI duration",
            "schedule": {
                "start": "2026-10-02T01:00:00Z",
                "calendar": {
                    "version": "synthetic-workday@1",
                    "timezone": "Asia/Shanghai",
                    "working_weekdays": [0, 1, 2, 3, 4],
                    "intervals": [
                        {"start_minute": 540, "end_minute": 720},
                        {"start_minute": 780, "end_minute": 1020},
                    ],
                },
                "tasks": [
                    {
                        "key": "eng",
                        "title": "Engineering verification",
                        "discipline": "engineering",
                        "duration_min_minutes": 60,
                        "duration_max_minutes": 120,
                        "estimate_source": "Synthetic owner estimate for trial",
                    },
                    {
                        "key": "npi",
                        "title": "NPI preparation",
                        "discipline": "npi",
                        "depends_on": ["eng"],
                    },
                ],
            },
        },
        definition[0],
    )


@pytest.fixture
def proposal(setup, definition, project):
    result = post(setup, proposal_command(setup, definition, project))
    assert result.status_code == 200, result.text
    return result.json()["subject_id"]


def application(setup, definition, project, proposal):
    return cmd(
        setup,
        "work.plan.apply",
        {"project_id": project, "proposal_id": proposal, "expected_project_revision": 1},
        definition[0],
    )


def test_project_needs_material_once_confirmation_and_fixed_link(setup, definition):
    command = project_command(setup, definition)
    refused = post(setup, command)
    assert refused.status_code == 409 and refused.json()["code"] == "CONFIRMATION_REQUIRED"
    receipt, prepared = accepted(setup, command)
    assert receipt["result"]["transition_entry"] == "S0–M3 人工 T1；G0 落地后收紧为 T2"
    assert receipt["result"]["tier"] == "T1"
    assert receipt["result"]["created_by"] == str(setup.human)
    replay = post(setup, prepared)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    new_key = {**prepared, "idempotency_key": str(uuid4()), "command_id": str(uuid4())}
    assert post(setup, new_key).json()["id"] == receipt["id"]
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(Project)) == 1
        link = s.scalar(select(ProjectProductLink))
        assert str(link.definition_id) == definition[1] and link.definition_revision == 1
        assert s.scalar(select(Audit.id).where(Audit.receipt_id == UUID(receipt["id"])))
        assert (
            s.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
            == "project.created"
        )


@pytest.mark.parametrize("change", ["payload", "read_set", "expected_revision", "actor"])
def test_confirmation_cannot_authorize_changed_scope(setup, definition, change):
    preview = post(setup, project_command(setup, definition), True)
    prepared = preview.json()["command"]
    headers = setup.headers
    if change == "payload":
        prepared["payload"]["scope"] = "Changed development scope after preview"
    elif change == "read_set":
        prepared["source_read_set"] = []
    elif change == "expected_revision":
        prepared["expected_revision"] = 2
    else:
        headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    response = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=headers, json=prepared
    )
    assert response.status_code in {403, 409}
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(Project)) == 0
        assert s.scalar(select(Confirmation)).consumed is False


@pytest.mark.parametrize("condition", ["expired", "grant", "source"])
def test_current_expiry_permission_and_source_rechecked_after_preview(setup, definition, condition):
    prepared = post(setup, project_command(setup, definition), True).json()["command"]
    with Session(setup.admin) as s, s.begin():
        if condition == "expired":
            s.execute(
                update(Confirmation)
                .where(Confirmation.product_id == setup.product)
                .values(expires_at=now() - timedelta(seconds=1))
            )
        elif condition == "grant":
            s.execute(
                update(Grant)
                .where(Grant.category_id == setup.category, Grant.principal_id == setup.human)
                .values(can_write=False)
            )
        else:
            s.execute(
                update(Artifact)
                .where(Artifact.id == UUID(definition[0]))
                .values(status="withdrawn")
            )
    response = post(setup, prepared)
    assert response.status_code in {403, 409}
    with Session(setup.admin) as s:
        assert (
            s.scalar(
                select(func.count()).select_from(Project).where(Project.product_id == setup.product)
            )
            == 0
        )


def test_private_definition_cannot_expand_into_shared_project(setup, definition):
    command = project_command(setup, definition)
    command["payload"]["visibility"] = "category"
    refused = post(setup, command, True)
    assert refused.status_code == 403


def test_first_plan_preserves_four_independent_time_facts(setup, definition, project, proposal):
    receipt, prepared = accepted(setup, application(setup, definition, project, proposal))
    assert len(receipt["result"]["task_ids"]) == len(receipt["result"]["work_package_ids"]) == 2
    result = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects", headers=setup.headers
    )
    assert result.status_code == 200, result.text
    view = result.json()["items"][0]
    assert view["revision"] == 2 and view["definition"]["status"] == "draft"
    timeline = view["timeline"]
    assert timeline["baseline"] is timeline["commitment"] is timeline["actual"] is None
    tasks = {item["key"]: item for item in timeline["forecast"]["tasks"]}
    assert tasks["eng"]["earliest_finish"] != tasks["eng"]["latest_finish"]
    assert tasks["npi"]["earliest_finish"] is None and tasks["npi"]["latest_finish"] is None
    assert tasks["npi"]["unknown_reasons"] and tasks["npi"]["duration_min_minutes"] is None
    assert timeline["forecast"]["calendar_ref"]["timezone_rules_sha256"]
    assert post(setup, prepared).json()["id"] == receipt["id"]
    with Session(setup.admin) as s:
        confirmed = s.scalar(
            select(Confirmation).where(
                Confirmation.operation == "work.plan.apply",
                Confirmation.category_id == setup.category,
            )
        )
        assert confirmed.subject_type == "proposal" and confirmed.subject_id == UUID(proposal)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(ProjectTask)) == 2
        assert s.scalar(select(func.count()).select_from(TaskDependency)) == 1


def test_plan_failure_rolls_back_all_members_and_confirmation(
    setup, definition, project, proposal, monkeypatch
):
    import pdos_next.service as commands

    prepared = post(setup, application(setup, definition, project, proposal), True).json()[
        "command"
    ]

    def fail(*_args, **_kwargs):
        raise DomainError("SYNTHETIC_COMMIT_FAILURE", "Synthetic receipt failure")

    monkeypatch.setattr(commands, "append_receipt", fail)
    response = post(setup, prepared)
    assert response.status_code == 500
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        for model in (PlanRevision, ProjectWorkPackage, ProjectTask, TaskDependency):
            assert s.scalar(select(func.count()).select_from(model)) == 0
        row = s.get(Project, UUID(project))
        assert row.revision == 1 and row.current_plan_id is None
        confirmations = s.scalars(
            select(Confirmation).where(Confirmation.operation == "work.plan.apply")
        ).all()
        assert len(confirmations) == 1 and confirmations[0].consumed is False


def test_concurrent_same_application_has_one_atomic_group(setup, definition, project, proposal):
    prepared = post(setup, application(setup, definition, project, proposal), True).json()[
        "command"
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: post(setup, prepared), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json()["id"] == responses[1].json()["id"]
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(PlanRevision)) == 1
        assert s.scalar(select(func.count()).select_from(ProjectTask)) == 2


@pytest.mark.parametrize("problem", ["cycle", "missing_dependency", "missing_estimate_source"])
def test_invalid_schedule_never_persists_a_proposal(setup, definition, project, problem):
    command = proposal_command(setup, definition, project)
    tasks = command["payload"]["schedule"]["tasks"]
    if problem == "cycle":
        tasks[0]["depends_on"] = ["npi"]
    elif problem == "missing_dependency":
        tasks[0]["depends_on"] = ["absent"]
    else:
        tasks[0].pop("estimate_source")
    response = post(setup, command)
    assert response.status_code == 422, response.text
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(PlanProposal)) == 0


def test_plan_scope_and_snapshots_are_private_and_immutable(setup, definition, project, proposal):
    accepted(setup, application(setup, definition, project, proposal))
    for principal in (setup.peer, setup.other_human):
        response = setup.client.get(
            f"/v1/categories/{setup.category}/products/{setup.product}/projects",
            headers={"Authorization": f"Bearer {setup.tokens[principal]}"},
        )
        assert (
            response.status_code == 403
            if principal == setup.other_human
            else response.json()["items"] == []
        )
    with pytest.raises(DBAPIError), Session(setup.admin) as s, s.begin():
        s.execute(
            update(PlanProposal).where(PlanProposal.id == UUID(proposal)).values(reason="Overwrite")
        )
    with Session(setup.admin) as s:
        for model in (
            Project,
            ProjectProductLink,
            PlanProposal,
            PlanRevision,
            ProjectTask,
            ProjectWorkPackage,
            TaskDependency,
        ):
            allowed = s.scalar(
                select(func.has_table_privilege("pdos_agent", model.__tablename__, "INSERT"))
            )
            assert allowed is False


def test_named_baseline_approval_is_not_opened_by_a_plan_preview(setup, definition, project):
    command = deepcopy(proposal_command(setup, definition, project))
    command["operation"] = "work.baseline.approve"
    refused = post(setup, command, True)
    assert refused.status_code == 403
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.operation == "work.baseline.approve")
            )
            == 0
        )


def test_calendar_version_cannot_silently_change_across_candidates(
    setup, definition, project, proposal
):
    command = proposal_command(setup, definition, project)
    command["payload"]["schedule"]["calendar"]["holidays"] = ["2026-10-02"]
    response = post(setup, command)
    assert response.status_code == 409 and response.json()["code"] == "VERSION_CONFLICT"
    command["payload"]["schedule"]["calendar"]["version"] = "synthetic-workday@2"
    response = post(setup, command)
    assert response.status_code == 200, response.text
    listed = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects", headers=setup.headers
    ).json()
    versions = listed["items"][0]["proposals"]
    assert versions[0]["input_snapshot"]["calendar"]["holidays"] == ["2026-10-02"]
    assert versions[1]["input_snapshot"]["calendar"]["holidays"] == []
    assert versions[0]["input_snapshot"]["calendar"]["timezone_rules_sha256"]


def test_shared_project_semantics_include_the_accountable_owner(setup):
    source = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic shared development source",
                "content": "Synthetic shared requirement",
                "source_label": "Synthetic fixture",
                "visibility": "category",
            },
        ),
    ).json()["subject_id"]
    defined = post(
        setup,
        cmd(
            setup,
            "product.definition.draft",
            {
                "title": "Shared fixed draft",
                "purpose": "Verify trusted project owner binding",
                "visibility": "category",
                "use_cases": ["Synthetic development"],
                "change_reason": "Draft",
                "sources": [
                    {
                        "artifact_id": source,
                        "expected_revision": 1,
                        "line": 1,
                        "quote": "Synthetic shared requirement",
                    }
                ],
            },
            source,
        ),
    ).json()["subject_id"]
    command = project_command(setup, (source, defined))
    command["payload"]["visibility"] = "category"
    first, _ = accepted(setup, command)
    second_request = {**command, "command_id": str(uuid4()), "idempotency_key": str(uuid4())}
    headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview", headers=headers, json=second_request
    )
    assert preview.status_code == 200, preview.text
    second = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=headers, json=preview.json()["command"]
    )
    assert second.status_code == 200, second.text
    assert first["subject_id"] != second.json()["subject_id"]
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.get(Project, UUID(first["subject_id"])).owner_id == setup.human
        assert s.get(Project, UUID(second.json()["subject_id"])).owner_id == setup.peer
