from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from g0_fixture import create_g0_project
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
    setup.g0 = create_g0_project(setup)
    registered = post(
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
    )
    assert registered.status_code == 200, registered.text
    return registered.json()["subject_id"], setup.g0.definition_id


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
    return setup.g0.project_id


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


@pytest.mark.parametrize("visibility", ["private", "category"])
def test_independent_project_creation_is_closed_without_writes(setup, definition, visibility):
    command = project_command(setup, definition)
    command["payload"]["visibility"] = visibility
    models = (Project, ProjectProductLink, Confirmation, Receipt, Audit, Outbox)
    with Session(setup.admin) as session:
        before = [session.scalar(select(func.count()).select_from(model)) for model in models]
    for preview in (True, False):
        refused = post(setup, command, preview)
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as session:
        after = [session.scalar(select(func.count()).select_from(model)) for model in models]
        assert after == before


def test_g0_has_one_fixed_project_link_and_named_owner(setup, definition, project):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(Project, UUID(project))
        assert row.owner_id == setup.human and row.product_id == setup.product
        assert row.g0_decision_id is not None
        link = session.scalar(
            select(ProjectProductLink).where(ProjectProductLink.project_id == row.id)
        )
        assert str(link.definition_id) == definition[1] and link.definition_revision == 1


@pytest.mark.parametrize("change", ["payload", "read_set", "expected_revision", "actor"])
def test_confirmation_cannot_authorize_changed_scope(setup, definition, project, proposal, change):
    preview = post(setup, application(setup, definition, project, proposal), True)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    headers = setup.headers
    if change == "payload":
        prepared["payload"]["expected_project_revision"] = 2
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
        assert s.scalar(select(func.count()).select_from(PlanRevision)) == 0
        assert s.get(Project, UUID(project)).current_plan_id is None
        assert (
            s.scalar(
                select(Confirmation).where(Confirmation.operation == "work.plan.apply")
            ).consumed
            is False
        )


@pytest.mark.parametrize("condition", ["expired", "grant", "source"])
def test_current_expiry_permission_and_source_rechecked_after_preview(
    setup, definition, project, proposal, condition
):
    preview = post(setup, application(setup, definition, project, proposal), True)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    with Session(setup.admin) as s, s.begin():
        if condition == "expired":
            s.execute(
                update(Confirmation)
                .where(
                    Confirmation.product_id == setup.product,
                    Confirmation.operation == "work.plan.apply",
                )
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
        assert s.scalar(
            select(func.count()).select_from(PlanRevision).where(
                PlanRevision.tenant_id == setup.tenant,
                PlanRevision.project_id == UUID(project),
            )
        ) == 0
        row = s.get(Project, UUID(project))
        assert row.revision == 1 and row.current_plan_id is None


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


def test_g0_reviewer_can_read_but_not_write_plan_and_snapshots_are_immutable(
    setup, definition, project, proposal
):
    accepted(setup, application(setup, definition, project, proposal))
    peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    visible = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects",
        headers=peer_headers,
    )
    assert visible.status_code == 200, visible.text
    assert [item["id"] for item in visible.json()["items"]] == [project]
    peer_command = proposal_command(setup, definition, project)
    peer_command["source_read_set"] = []
    peer_write = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers=peer_headers,
        json=peer_command,
    )
    assert peer_write.status_code == 403, peer_write.text
    foreign = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects",
        headers={"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
    )
    assert foreign.status_code == 403
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
    derived = create_g0_project(setup, visibility="category")
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        project = session.get(Project, UUID(derived.project_id))
        assert project.owner_id == setup.human and project.visibility == "category"
        assert project.g0_decision_id is not None
    headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    replay = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=headers, json=derived.command
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == derived.receipt["id"]
    visible = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects", headers=headers
    )
    assert visible.status_code == 200, visible.text
    assert [row["id"] for row in visible.json()["items"]] == [derived.project_id]


def test_direct_project_plan_reads_actual_g0_candidate_and_applied_result(
    setup, definition, project
):
    path = f"/v1/categories/{setup.category}/products/{setup.product}/projects/{project}"
    first = setup.client.get(path, headers=setup.headers)
    assert first.status_code == 200, first.text
    value = first.json()
    assert value["has_more"] is False and value["unavailable_count"] == 0
    assert [row["id"] for row in value["items"]] == [project]
    assert value["items"][0]["definition"]["id"] == setup.g0.definition_id
    assert value["items"][0]["plan"] is None
    command = proposal_command(setup, definition, project)
    command["source_read_set"] = value["items"][0]["required_source_read_set"]
    saved = post(setup, command)
    assert saved.status_code == 200, saved.text
    candidate = setup.client.get(path, headers=setup.headers).json()["items"][0]
    assert [row["id"] for row in candidate["proposals"]] == [saved.json()["subject_id"]]
    apply = application(setup, definition, project, saved.json()["subject_id"])
    apply["source_read_set"] = candidate["required_source_read_set"]
    receipt, confirmed = accepted(setup, apply)
    replay = post(setup, confirmed)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    result = setup.client.get(path, headers=setup.headers).json()["items"][0]
    assert result["plan"]["id"] == receipt["subject_id"]
    assert result["revision"] == 2 and len(result["tasks"]) == 2
    assert result["plan"]["forecast"]["latest_finish"] is None
    personal = setup.client.get(f"/v1/personal/projects/{project}", headers=setup.headers)
    assert personal.status_code == 200, personal.text
    assert personal.json()["items"][0]["project"]["plan"]["id"] == receipt["subject_id"]
    assert personal.json()["items"][0]["project"]["task_count"] == 2


def test_direct_project_read_does_not_fall_back_or_write_after_scope_change(setup):
    original_product = setup.product
    actual = create_g0_project(setup)
    path = f"/v1/categories/{setup.category}/products/{setup.product}/projects/{actual.project_id}"
    models = (Project, PlanProposal, PlanRevision, ProjectTask, Receipt, Confirmation)
    with Session(setup.admin) as session:
        before = [session.scalar(select(func.count()).select_from(model)) for model in models]
    for suffix in [str(uuid4()), actual.project_id]:
        target_product = setup.product if suffix != actual.project_id else original_product
        response = setup.client.get(
            f"/v1/categories/{setup.category}/products/{target_product}/projects/{suffix}",
            headers=setup.headers,
        )
        assert response.status_code == 404, response.text
        assert "items" not in response.json()
    assert setup.client.get(path, headers=setup.headers).status_code == 200
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Grant)
            .where(Grant.principal_id == setup.human, Grant.category_id == setup.category)
            .values(expires_at=now() - timedelta(minutes=1))
        )
    revoked = setup.client.get(path, headers=setup.headers)
    assert revoked.status_code == 403, revoked.text
    with Session(setup.admin) as session:
        after = [session.scalar(select(func.count()).select_from(model)) for model in models]
        assert after == before
