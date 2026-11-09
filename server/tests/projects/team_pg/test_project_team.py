"""Project team (P34-1, P55, P56, P60-4) over real G0 projects and database guards."""

# ruff: noqa: F811

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from g0_fixture import add_category_human, create_g0_project
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import TenantAdministrator
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Grant, ObjectAudience, Principal, Product, now
from pdos_next.core.service import Context
from pdos_next.domain.categories.products.models import DefinitionRevision
from pdos_next.domain.projects.models import Project
from pdos_next.domain.projects.team import service
from pdos_next.domain.projects.team.models import (
    MemberAudience,
    MemberRole,
    ProjectMember,
    RoleCatalogVersion,
    TeamChange,
)
from projects.work_pg.test_workflow import original_security_work, work  # noqa: F401

TABLES = (
    "project_role_catalog_versions",
    "project_team_changes",
    "project_members",
    "project_member_roles",
)


def team_path(setup, project):
    return (
        f"/v1/categories/{setup.category}/products/{project.product_id}"
        f"/projects/{project.project_id}/team"
    )


def headers(setup, person):
    return {"Authorization": f"Bearer {setup.tokens[person]}"}


def read(setup, project, person=None):
    response = setup.client.get(
        team_path(setup, project), headers=headers(setup, person or setup.human)
    )
    assert response.status_code == 200, response.text
    return response.json()


def change(setup, project, changes, *, person=None, revision=None, key=None):
    body = {
        "expected_revision": read(setup, project)["revision"] if revision is None else revision,
        "request_key": str(key or uuid4()),
        "changes": changes,
    }
    return setup.client.post(
        team_path(setup, project), headers=headers(setup, person or setup.human), json=body
    ), body


def audience(setup, project):
    with Session(setup.admin) as s:
        return set(
            s.scalars(
                select(ObjectAudience.principal_id).where(
                    ObjectAudience.tenant_id == setup.tenant,
                    ObjectAudience.object_type == "projects",
                    ObjectAudience.subject_id == project.project_id,
                )
            )
        )


def members(view):
    return {item["principal_id"]: item for item in view["members"]}


def sees_project(setup, project, person):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=person, category_id=setup.category
    ) as s:
        return s.get(Project, project.project_id) is not None


def test_g0_registers_audience_as_team_and_owner_maintains_it(setup):
    project = create_g0_project(setup, visibility="private")
    newcomer = add_category_human(setup, name="合成结构工程师")
    view = read(setup, project)
    # P55: the G0 audience (proposal owner/project owner and reviewer) is the team.
    assert set(members(view)) == {str(setup.human), str(setup.peer)}
    assert all(item["roles"] == [] for item in view["members"])
    assert members(view)[str(setup.human)]["is_owner"] is True
    assert view["revision"] == 1 and view["can_manage"] is True
    assert view["membership_controls_visibility"] is True
    assert view["catalog"]["revision"] == 0 and view["catalog"]["default"] is True
    assert {role["name"] for role in view["catalog"]["roles"]} >= {"产品经理", "电池安全"}
    assert audience(setup, project) == {setup.human, setup.peer}
    with Session(setup.admin) as s:
        decided = s.execute(
            text(
                "SELECT result FROM action_receipts WHERE operation='proposal.g0.decide' "
                "AND subject_id=:id"
            ),
            {"id": project.proposal_id},
        ).scalar()
    assert sorted(decided["project_member_ids"]) == sorted([str(setup.human), str(setup.peer)])

    response, body = change(
        setup,
        project,
        [
            {
                "action": "add",
                "principal_id": str(newcomer),
                "roles": [{"key": "mechanical", "lead": True}],
            },
            {
                "action": "set_roles",
                "principal_id": str(setup.peer),
                "roles": [{"key": "quality", "lead": True}, {"key": "mechanical"}],
            },
        ],
    )
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["revision"] == 2
    assert members(view)[str(newcomer)]["roles"] == [
        {"key": "mechanical", "name": "结构", "lead": True}
    ]
    assert members(view)[str(newcomer)]["added_by"] == str(setup.human)
    assert "mechanical" not in view["vacant_roles"] and "quality" not in view["roles_without_lead"]
    # Private project: joining is joining the project audience.
    assert audience(setup, project) == {setup.human, setup.peer, newcomer}
    assert sees_project(setup, project, newcomer)
    # Same request replays; a stale revision and a second lead are refused.
    replay = setup.client.post(
        team_path(setup, project), headers=headers(setup, setup.human), json=body
    )
    assert replay.status_code == 200 and replay.json()["revision"] == 2
    stale, _ = change(
        setup, project, [{"action": "set_roles", "principal_id": str(newcomer)}], revision=1
    )
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    double, _ = change(
        setup,
        project,
        [
            {
                "action": "set_roles",
                "principal_id": str(setup.human),
                "roles": [{"key": "mechanical", "lead": True}],
            }
        ],
    )
    assert double.status_code == 422 and double.json()["detail"]["reason"] == "one_lead_per_role"
    # The lead can move in one request.
    moved, _ = change(
        setup,
        project,
        [
            {
                "action": "set_roles",
                "principal_id": str(newcomer),
                "roles": [{"key": "mechanical"}],
            },
            {
                "action": "set_roles",
                "principal_id": str(setup.human),
                "roles": [{"key": "mechanical", "lead": True}],
            },
        ],
    )
    assert moved.status_code == 200, moved.text
    # Only the project owner maintains the team.
    peer_write, _ = change(
        setup,
        project,
        [{"action": "set_roles", "principal_id": str(setup.peer)}],
        person=setup.peer,
    )
    assert peer_write.status_code == 403 and peer_write.json()["detail"]["reason"] == "owner_only"
    assert "candidates" not in read(setup, project, setup.peer)

    # Leaving: off the audience at once, history and roles at departure kept.
    left, _ = change(setup, project, [{"action": "remove", "principal_id": str(newcomer)}])
    assert left.status_code == 200, left.text
    view = left.json()
    assert str(newcomer) not in members(view)
    assert view["departed"][0]["principal_id"] == str(newcomer)
    assert view["departed"][0]["roles"] == [{"key": "mechanical", "name": "结构", "lead": False}]
    assert audience(setup, project) == {setup.human, setup.peer}
    assert not sees_project(setup, project, newcomer)
    owner_out, _ = change(setup, project, [{"action": "remove", "principal_id": str(setup.human)}])
    assert owner_out.status_code == 422 and owner_out.json()["detail"]["reason"] == "owner_stays"
    # Re-joining opens a new stint.
    back, _ = change(setup, project, [{"action": "add", "principal_id": str(newcomer)}])
    assert back.status_code == 200, back.text
    with Session(setup.admin) as s:
        stints = s.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == project.project_id,
                ProjectMember.principal_id == newcomer,
            )
        ).all()
    assert len(stints) == 2 and sum(row.left_at is None for row in stints) == 1


def test_membership_is_not_a_permission_root(setup):
    project = create_g0_project(setup, visibility="private")
    outsider = add_category_human(setup, name="合成无授权同事")
    with Session(setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(Grant.tenant_id == setup.tenant, Grant.principal_id == outsider)
            .values(expires_at=now() - timedelta(minutes=1))
        )
    candidates = {item["principal_id"]: item for item in read(setup, project)["candidates"]}
    assert candidates[str(outsider)]["grant"] == "expired"
    assert str(setup.agent) not in candidates
    refused, _ = change(setup, project, [{"action": "add", "principal_id": str(outsider)}])
    assert refused.status_code == 403
    assert refused.json()["detail"]["reason"] == "category_grant_required"
    assert "需要品类授权" in refused.json()["message"]
    # 小Pai is never a member.
    agent, _ = change(setup, project, [{"action": "add", "principal_id": str(setup.agent)}])
    assert agent.status_code == 422 and agent.json()["detail"]["reason"] == "agent_not_member"
    # A member whose grant lapses stays on the team but is shown as needing a grant;
    # the team never restores visibility the category no longer gives.
    with Session(setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(Grant.tenant_id == setup.tenant, Grant.principal_id == setup.peer)
            .values(expires_at=now() - timedelta(minutes=1))
        )
    assert members(read(setup, project))[str(setup.peer)]["grant"] == "expired"
    assert not sees_project(setup, project, setup.peer)


def test_category_shared_team_does_not_change_visibility(setup):
    project = create_g0_project(setup, visibility="category")
    bystander = add_category_human(setup, name="合成品类同事")
    assert sees_project(setup, project, bystander)
    view = read(setup, project)
    assert view["membership_controls_visibility"] is False
    added, _ = change(setup, project, [{"action": "add", "principal_id": str(bystander)}])
    assert added.status_code == 200, added.text
    removed, _ = change(setup, project, [{"action": "remove", "principal_id": str(bystander)}])
    assert removed.status_code == 200, removed.text
    assert sees_project(setup, project, bystander)


def make_admin(setup, person):
    with Session(setup.admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=person))


def test_role_catalog_versions_and_referenced_roles(setup):
    project = create_g0_project(setup, visibility="private")
    root = "/v1/role-catalog"
    current = setup.client.get(root, headers=setup.headers).json()
    assert current["revision"] == 0 and current["can_publish"] is False
    roles = current["roles"]
    body = {"expected_revision": 0, "request_key": str(uuid4()), "roles": roles}
    assert setup.client.post(root, headers=setup.headers, json=body).status_code == 403
    make_admin(setup, setup.human)
    edited = [*roles, {"name": "成本", "active": True}]
    body = {"expected_revision": 0, "request_key": str(uuid4()), "roles": edited}
    first = setup.client.post(root, headers=setup.headers, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 1 and first.json()["default"] is False
    cost = next(role for role in first.json()["roles"] if role["name"] == "成本")
    assert cost["key"].startswith("r_")
    assert setup.client.post(root, headers=setup.headers, json=body).json()["revision"] == 1
    stale = setup.client.post(
        root, headers=setup.headers, json={**body, "request_key": str(uuid4())}
    )
    assert stale.status_code == 409
    # A tenant-added role can be assigned; then it can only be deactivated.
    held, _ = change(
        setup,
        project,
        [
            {
                "action": "set_roles",
                "principal_id": str(setup.peer),
                "roles": [{"key": cost["key"]}, {"key": "battery_safety"}],
            }
        ],
    )
    assert held.status_code == 200, held.text
    remaining = [role for role in first.json()["roles"] if role["key"] != "battery_safety"]
    deleted = setup.client.post(
        root,
        headers=setup.headers,
        json={"expected_revision": 1, "request_key": str(uuid4()), "roles": remaining},
    )
    assert deleted.status_code == 409
    assert deleted.json()["detail"]["reason"] == "role_referenced"
    assert "电池安全" in deleted.json()["message"]
    deactivated = [
        {**role, "active": role["key"] != "battery_safety"} for role in first.json()["roles"]
    ]
    second = setup.client.post(
        root,
        headers=setup.headers,
        json={"expected_revision": 1, "request_key": str(uuid4()), "roles": deactivated},
    )
    assert second.status_code == 200, second.text
    # Existing holders keep a deactivated role; nobody new can take it.
    keep, _ = change(
        setup,
        project,
        [
            {
                "action": "set_roles",
                "principal_id": str(setup.peer),
                "roles": [{"key": "battery_safety"}],
            }
        ],
    )
    assert keep.status_code == 200, keep.text
    give, _ = change(
        setup,
        project,
        [
            {
                "action": "set_roles",
                "principal_id": str(setup.human),
                "roles": [{"key": "battery_safety"}],
            }
        ],
    )
    assert give.status_code == 422 and give.json()["detail"]["reason"] == "role_inactive"
    # Category-scoped calls cannot touch the tenant catalog.
    scoped = setup.client.get(
        f"/v1/categories/{setup.category}/role-catalog", headers=setup.headers
    )
    assert scoped.status_code == 404


def test_database_guards_and_no_agent_access(setup):
    project = create_g0_project(setup, visibility="private")
    newcomer = add_category_human(setup, name="合成新成员")
    with Session(setup.admin) as s:
        for table in TABLES:
            assert s.scalar(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname=:t"
                ),
                {"t": table},
            )
            for privilege in ("SELECT", "INSERT,UPDATE,DELETE"):
                assert not s.scalar(
                    text("SELECT has_table_privilege('pdos_agent',:t,:p)"),
                    {"t": table, "p": privilege},
                )
    # An agent-acting session on behalf of the owner sees and changes nothing.
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.agent,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        for model in (TeamChange, ProjectMember, MemberRole, RoleCatalogVersion):
            assert s.scalars(select(model).where(model.tenant_id == setup.tenant)).all() == []

    def owner_session():
        return tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        )

    def team_change(s):
        latest = s.scalar(
            select(TeamChange.revision)
            .where(TeamChange.project_id == project.project_id)
            .order_by(TeamChange.revision.desc())
            .limit(1)
        )
        row = TeamChange(
            tenant_id=setup.tenant,
            project_id=project.project_id,
            revision=latest + 1,
            source="owner",
            author_id=setup.human,
            request_key=uuid4(),
            request_sha256="0" * 64,
            changes=[],
        )
        s.add(row)
        s.flush()
        return row

    def join(s, person, change_row):
        s.add(
            ProjectMember(
                tenant_id=setup.tenant,
                project_id=project.project_id,
                principal_id=person,
                joined_at=now(),
                added_by=setup.human,
                joined_change_id=change_row.id,
            )
        )
        s.flush()

    # The agent principal cannot be inserted as a member even by the owner.
    with pytest.raises(DBAPIError, match="active named person"):
        with owner_session() as s:
            join(s, setup.agent, team_change(s))
    # A member row without the matching audience row fails at commit, and vice versa.
    with pytest.raises(DBAPIError, match="differs from its current members"):
        with owner_session() as s:
            join(s, newcomer, team_change(s))
    with pytest.raises(DBAPIError, match="differs from its current members"):
        with owner_session() as s:
            s.add(
                ObjectAudience(
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    object_type="projects",
                    subject_id=project.project_id,
                    owner_id=setup.human,
                    principal_id=newcomer,
                )
            )
            s.flush()
    # History rows are append only: no privilege for the app, a trigger for everyone else.
    rewrite = (
        update(TeamChange).where(TeamChange.project_id == project.project_id).values(changes=[])
    )
    with pytest.raises(DBAPIError, match="permission denied"):
        with owner_session() as s:
            s.execute(rewrite)
    with pytest.raises(DBAPIError, match="append only"):
        with Session(setup.admin) as s, s.begin():
            s.execute(rewrite)
    # The reviewer cannot write the owner's team directly either.
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.peer, category_id=setup.category
        ) as s:
            s.add(
                TeamChange(
                    tenant_id=setup.tenant,
                    project_id=project.project_id,
                    revision=2,
                    source="owner",
                    author_id=setup.peer,
                    request_key=uuid4(),
                    request_sha256="0" * 64,
                    changes=[],
                )
            )
            s.flush()
    with Session(setup.admin) as s:
        assert s.scalar(select(Principal.kind).where(Principal.id == setup.agent)) == "agent"


def visible(setup, person, model, identity):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=person, category_id=setup.category
    ) as s:
        return s.get(model, identity) is not None


def upstream_rows(setup, person):
    with Session(setup.admin) as s:
        return {
            (row.object_type, row.inserted, row.released_at is not None)
            for row in s.scalars(
                select(MemberAudience).where(
                    MemberAudience.tenant_id == setup.tenant, MemberAudience.principal_id == person
                )
            )
        }


def test_private_member_gets_and_loses_the_owned_model_and_definition(setup):
    project = create_g0_project(setup, visibility="private")
    newcomer = add_category_human(setup, name="合成新成员")
    assert not visible(setup, newcomer, Product, UUID(project.product_id))
    added, _ = change(setup, project, [{"action": "add", "principal_id": str(newcomer)}])
    assert added.status_code == 200, added.text
    assert members(added.json())[str(newcomer)]["needs_model_access"] == []
    # Joining brings the model and G0 definition the project owner owns.
    for model, identity in (
        (Project, project.project_id),
        (Product, UUID(project.product_id)),
        (DefinitionRevision, UUID(project.definition_id)),
    ):
        assert visible(setup, newcomer, model, identity)
    assert upstream_rows(setup, newcomer) == {
        ("products", True, False),
        ("definition_revisions", True, False),
    }
    removed, _ = change(setup, project, [{"action": "remove", "principal_id": str(newcomer)}])
    assert removed.status_code == 200, removed.text
    assert removed.json()["departed"][0]["handover_pending"] is False
    # Full removal leaves nothing visible that joining added.
    for model, identity in (
        (Project, project.project_id),
        (Product, UUID(project.product_id)),
        (DefinitionRevision, UUID(project.definition_id)),
    ):
        assert not visible(setup, newcomer, model, identity)
    assert upstream_rows(setup, newcomer) == {
        ("products", True, True),
        ("definition_revisions", True, True),
    }
    # The reviewer's model access came from G0, not from the team, and stays.
    out, _ = change(setup, project, [{"action": "remove", "principal_id": str(setup.peer)}])
    assert out.status_code == 200, out.text
    assert not visible(setup, setup.peer, Project, project.project_id)
    assert visible(setup, setup.peer, Product, UUID(project.product_id))


def test_unhanded_work_keeps_only_own_items_until_the_removal_completes(setup, monkeypatch):
    project = create_g0_project(setup, visibility="private")
    newcomer = add_category_human(setup, name="合成待交接成员")
    joined, _ = change(setup, project, [{"action": "add", "principal_id": str(newcomer)}])
    assert joined.status_code == 200, joined.text
    open_work = {"tasks": 1, "commitments": 1, "external_waits": 0}
    real = service.pending_items
    monkeypatch.setattr(
        service,
        "pending_items",
        lambda s, ctx, project_row, person: (
            open_work if person == newcomer else real(s, ctx, project_row, person)
        ),
    )
    assert members(read(setup, project))[str(newcomer)]["pending"] == open_work
    left, _ = change(setup, project, [{"action": "remove", "principal_id": str(newcomer)}])
    assert left.status_code == 200, left.text
    view = left.json()
    assert str(newcomer) not in members(view)
    assert view["departed"][0]["handover_pending"] is True
    assert view["departed"][0]["pending"] == open_work
    # P56 (D37 ⑤): membership, roles and the project audience end now; only the
    # model claims the person's own open items still need stay until it settles.
    # The full lane path over real work is in discussions_pg/test_handover_and_tasks.py.
    assert not visible(setup, newcomer, Project, project.project_id)
    assert audience(setup, project) == {setup.human, setup.peer}
    assert visible(setup, newcomer, Product, UUID(project.product_id))
    early, _ = change(setup, project, [{"action": "complete", "principal_id": str(newcomer)}])
    assert early.status_code == 422 and early.json()["detail"]["reason"] == "handover_open"
    open_work.update(tasks=0, commitments=0)
    done, _ = change(setup, project, [{"action": "complete", "principal_id": str(newcomer)}])
    assert done.status_code == 200, done.text
    assert done.json()["departed"][0]["handover_pending"] is False
    assert not visible(setup, newcomer, Project, project.project_id)
    assert not visible(setup, newcomer, Product, UUID(project.product_id))
    again, _ = change(setup, project, [{"action": "complete", "principal_id": str(newcomer)}])
    assert again.status_code == 409


def test_rejoining_during_handover_keeps_the_added_model_access(setup, monkeypatch):
    project = create_g0_project(setup, visibility="private")
    newcomer = add_category_human(setup, name="合成回归成员")
    change(setup, project, [{"action": "add", "principal_id": str(newcomer)}])
    monkeypatch.setattr(
        service,
        "pending_items",
        lambda *_args: {"tasks": 1, "commitments": 0, "external_waits": 0},
    )
    change(setup, project, [{"action": "remove", "principal_id": str(newcomer)}])
    back, _ = change(setup, project, [{"action": "add", "principal_id": str(newcomer)}])
    assert back.status_code == 200, back.text
    assert back.json()["departed"][0]["handover_pending"] is False
    assert visible(setup, newcomer, Product, UUID(project.product_id))
    # The new membership now owns the rows the first one added.
    assert upstream_rows(setup, newcomer) == {
        ("products", True, True),
        ("definition_revisions", True, True),
        ("products", True, False),
        ("definition_revisions", True, False),
    }


def test_model_owned_by_someone_else_is_not_extended(setup, monkeypatch):
    import g0_fixture

    lead = add_category_human(setup, name="合成项目负责人")
    run = g0_fixture.run_command

    def decide_with_lead(target, operation, payload, **options):
        if operation == "proposal.g0.decide":
            payload = {**payload, "project": {**payload["project"], "owner_id": str(lead)}}
        return run(target, operation, payload, **options)

    monkeypatch.setattr(g0_fixture, "run_command", decide_with_lead)
    project = create_g0_project(setup, visibility="private")
    newcomer = add_category_human(setup, name="合成待授权成员")
    added, _ = change(
        setup, project, [{"action": "add", "principal_id": str(newcomer)}], person=lead
    )
    assert added.status_code == 200, added.text
    gaps = members(added.json())[str(newcomer)]["needs_model_access"]
    assert {gap["object"] for gap in gaps} == {"型号", "立项定义"}
    assert {gap["owner_name"] for gap in gaps} == {"Synthetic owner"}
    assert visible(setup, newcomer, Project, project.project_id)
    assert not visible(setup, newcomer, Product, UUID(project.product_id))
    assert upstream_rows(setup, newcomer) == set()


def test_pending_items_count_an_actual_assigned_task(work):
    from pdos_next.domain.projects.work.constants import ASSIGN, CREATE
    from projects.work_pg import test_workflow as flow

    setup = work.setup
    _, created = flow.execute(
        work,
        CREATE,
        flow.payload(
            work,
            title="合成交接任务",
            goal="确认待交接计数",
            outcomes=[{"key": "drawing", "text": "图纸", "required": True}],
            plan_task=None,
        ),
    )
    work.task_id = UUID(created["result"]["task_id"])
    flow.execute(
        work,
        ASSIGN,
        flow.payload(
            work,
            task=flow.task(work, "proposed"),
            assignee_id=str(setup.peer),
            recipient_id=str(setup.human),
        ),
    )
    with flow.scoped(work) as s:
        project = s.get(Project, work.project_id)
        ctx = Context(setup.tenant, setup.human, setup.human, category_id=setup.category)
        assert service.pending_items(s, ctx, project, setup.peer) == {
            "tasks": 1,
            "commitments": 0,
            "external_waits": 0,
        }
        assert service.pending_items(s, ctx, project, setup.human)["tasks"] == 0
