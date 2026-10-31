"""Shared organization grouping and private following, using real domain projects."""

# ruff: noqa: F811
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from work_management_pg import test_workflow as flow
from work_management_pg.test_workflow import original_security_work, work  # noqa: F401

from pdos_next.database import tenant_session
from pdos_next.models import Grant
from pdos_next.project_sets.models import ProjectSet, ProjectSetLink

ROOT = "/v1/project-sets"


def save(setup, **overrides):
    return {
        "name": "合成项目集",
        "description": "共享整理",
        "expected_revision": 0,
        "request_key": str(uuid4()),
        **overrides,
    }


def test_shared_edit_retry_conflict_and_tenant_boundary(setup):
    request = save(setup)
    first = setup.client.post(ROOT, headers=setup.headers, json=request)
    assert first.status_code == 200, first.text
    assert setup.client.post(ROOT, headers=setup.headers, json=request).json() == first.json()
    identity = first.json()["id"]
    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert setup.client.get(ROOT, headers=peer).json()["items"][0]["id"] == identity
    edited = setup.client.post(
        ROOT, headers=peer, json=save(setup, set_id=identity, expected_revision=1, name="共同修改")
    )
    assert edited.status_code == 200, edited.text
    stale = setup.client.post(
        ROOT, headers=setup.headers, json=save(setup, set_id=identity, expected_revision=1)
    )
    assert stale.status_code == 409
    assert setup.client.get(ROOT, headers=setup.headers).json()["items"][0]["name"] == "共同修改"
    outsider = {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    assert setup.client.get(ROOT, headers=outsider).json() == {"items": [], "links": []}
    assert (
        setup.client.post(
            ROOT, headers=outsider, json=save(setup, set_id=identity, expected_revision=2)
        ).status_code
        == 403
    )


def test_move_retry_transfer_atomicity_and_revoked_scope(work):
    setup = work.setup
    headers = flow.headers(work)
    first = setup.client.post(ROOT, headers=headers, json=save(setup)).json()["id"]
    second = setup.client.post(ROOT, headers=headers, json=save(setup, name="第二项目集")).json()[
        "id"
    ]
    move = {
        "set_id": first,
        "projects": [{"project_id": str(work.project_id), "expected_revision": 0}],
        "request_key": str(uuid4()),
    }
    response = setup.client.post(ROOT + "/move", headers=headers, json=move)
    assert response.status_code == 200, response.text
    assert setup.client.post(ROOT + "/move", headers=headers, json=move).json() == response.json()
    bad = {
        "set_id": second,
        "projects": [
            {"project_id": str(work.project_id), "expected_revision": 1},
            {"project_id": str(uuid4()), "expected_revision": 0},
        ],
        "request_key": str(uuid4()),
    }
    assert setup.client.post(ROOT + "/move", headers=headers, json=bad).status_code == 403
    assert setup.client.get(ROOT, headers=headers).json()["links"][0]["set_id"] == first
    transfer = {**bad, "projects": bad["projects"][:1], "request_key": str(uuid4())}
    result = setup.client.post(
        ROOT + "/move", headers=flow.headers(work, setup.peer), json=transfer
    )
    assert result.status_code == 200, result.text
    assert result.json()["items"][0]["revision"] == 2
    assert (
        setup.client.post(
            ROOT + "/move", headers=headers, json={**move, "request_key": str(uuid4())}
        ).status_code
        == 409
    )
    with Session(setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(Grant.tenant_id == setup.tenant, Grant.principal_id == setup.peer)
            .values(expires_at=flow.now())
        )
    hidden = setup.client.get(ROOT, headers=flow.headers(work, setup.peer)).json()
    assert len(hidden["items"]) == 2 and hidden["links"] == []
    assert (
        setup.client.post(
            ROOT + "/move", headers=flow.headers(work, setup.peer), json=transfer
        ).status_code
        == 403
    )


def test_project_follow_is_private_and_uses_actual_project_update(work):
    setup = work.setup
    request = {
        "kind": "project",
        "target_id": str(work.project_id),
        "expected_revision": 0,
        "observed_token": "none",
        "mark_read": False,
        "archived": False,
        "followed": True,
        "request_key": str(uuid4()),
    }
    result = setup.client.post(
        "/v1/personal/inbox/states", headers=flow.headers(work), json=request
    )
    assert result.status_code == 200, result.text
    assert (
        setup.client.get(
            "/v1/personal/inbox/states", headers=flow.headers(work, setup.peer)
        ).json()["items"]
        == []
    )
    update_result = flow.execute(
        work,
        flow.STATUS,
        flow.payload(work, fact_summary="合成状态", next_steps="继续检查", task_refs=[]),
    )[1]
    assert update_result
    project = setup.client.get(
        f"/v1/personal/projects/{work.project_id}", headers=flow.headers(work)
    ).json()["items"][0]
    token = project["project"]["latest_status_update"]["id"]
    read = {
        **request,
        "expected_revision": 1,
        "observed_token": token,
        "mark_read": True,
        "request_key": str(uuid4()),
    }
    response = setup.client.post("/v1/personal/inbox/states", headers=flow.headers(work), json=read)
    assert response.status_code == 200, response.text
    assert response.json()["read_through"] == token
    with Session(setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(Grant.tenant_id == setup.tenant, Grant.principal_id == setup.human)
            .values(expires_at=flow.now())
        )
    assert (
        setup.client.get("/v1/personal/inbox/states", headers=flow.headers(work)).json()["items"]
        == []
    )


def test_database_no_agent_access_and_history_immutable(setup):
    from sqlalchemy.exc import DBAPIError

    from pdos_next.project_sets.api import SaveSet
    from pdos_next.project_sets.api import save as save_domain
    from pdos_next.service import Context

    request = save(setup)
    setup.client.post(ROOT, headers=setup.headers, json=request).raise_for_status()
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human) as s:
        with pytest.raises(DBAPIError):
            s.execute(update(ProjectSet).values(name="overwrite"))
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.agent, requester_id=setup.human
    ) as s:
        assert list(s.scalars(select(ProjectSet))) == []
        assert list(s.scalars(select(ProjectSetLink))) == []
        with pytest.raises(Exception) as failure:
            save_domain(
                s,
                Context(tenant_id=setup.tenant, actor_id=setup.agent, requester_id=setup.human),
                SaveSet(**request),
            )
        assert (
            getattr(failure.value, "status", None) == 403
            or getattr(failure.value, "status_code", None) == 403
        )
