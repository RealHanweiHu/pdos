"""Native authenticated owner-goal history after source withdrawal; root runs PG.

Native register/start and production finish persist synthetic records. Only isolated
ACL reduction uses the test administrator. No real model or provider is called.
"""

from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.work_state import PAGE_MATERIAL_BOUNDARY
from pdos_next.agent_kernel.work_state_models import AgentWorkState
from pdos_next.database import tenant_session
from pdos_next.models import Grant, ObjectAudience, Product
from tests.agent_kernel.test_run_continuation import finish, path, scope, start
from tests.preproject.test_g0 import post, request


def shared_source(setup):
    response = post(setup, request(setup, "evidence.artifact.register", {
        "title": "Owner history isolated source", "content": "PRIVATE_SOURCE_BODY",
        "source_label": "PRIVATE_SOURCE_LABEL", "visibility": "audience",
    }), actor=setup.peer)
    assert response.status_code == 200, response.text
    identity = UUID(response.json()["subject_id"])
    with Session(setup.admin) as session, session.begin():
        audience = ObjectAudience(tenant_id=setup.tenant, category_id=setup.category,
            object_type="artifact_versions", subject_id=identity, owner_id=setup.peer,
            principal_id=setup.human)
        session.add(audience)
        session.flush()
        return identity, audience.id


def complete(setup, identity):
    Bootstrap(setup.engine).store.finish(scope(setup, identity), {
        "status": "completed", "summary": "PRIVATE_MODEL_REPLY", "result": {},
        "questions": [], "unfinished": [],
    })


def withdraw(setup, audience):
    with Session(setup.admin) as session, session.begin():
        session.delete(session.get(ObjectAudience, audience))


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def clean(response, source):
    for secret in (str(source), "PRIVATE_MODEL_REPLY", "PRIVATE_SOURCE_BODY",
                   "PRIVATE_SOURCE_LABEL", "SERVER_ATTACHED_MARKER"):
        assert secret not in response.text
    return ok(response)


def base(setup):
    return f"/v1/categories/{setup.category}"


def test_hidden_owner_get_heads_search_and_paging_keep_only_recorded_user_goals(setup):
    source, audience = shared_source(setup)
    sources = [{"artifact_id": str(source), "expected_revision": 1}]
    original = "本人原话 50%_\\ 保留未知条件。"
    first, first_row = start(setup, goal=original + PAGE_MATERIAL_BOUNDARY +
                             "SERVER_ATTACHED_MARKER", sources=sources)
    complete(setup, first)
    second, _ = start(setup, goal="本人第二轮原话。", continue_from_run_id=str(first))
    complete(setup, second)
    third, third_row = start(setup, goal="本人另一会话原话。", sources=sources)
    complete(setup, third)
    withdraw(setup, audience)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human,
                        requester_id=setup.human, category_id=setup.category) as session:
        assert session.get(AgentRun, first) is None
        assert session.get(AgentRun, second) is None
    detail = clean(setup.client.get(path(setup) + f"/{first}", headers=setup.headers), source)
    assert detail["goal"] == original and detail["status"] == "hidden"
    assert detail["history_hidden"] is True
    assert detail["result"] is None and detail["versions"] == {}
    assert detail["created_at"] is None and detail["recorded_at"]
    assert detail["process"] is detail["reverted"] is detail["cancel_epoch"] is None
    assert detail["conversation"] == {
        "previous_run_id": None, "next_run_id": None, "links_unavailable": True,
    }

    def get(route, **params):
        response = setup.client.get(base(setup) + route, headers=setup.headers, params=params)
        return clean(response, source)

    for query, kind in (("50%_\\", "goal"), (str(first), "run_id")):
        [item] = get("/agent-sessions", q=query)["items"]
        assert item["run_count"] == 2
        assert item["latest_run"]["run_id"] == str(second)
        assert item["matched_run"]["goal"] == original
        assert item["matched_run"]["match_kind"] == kind
        assert item["matched_run"]["history_hidden"] is True
    assert get("/agent-sessions", q="SERVER_ATTACHED_MARKER")["items"] == []
    page = get("/agent-sessions", page_size=1)
    tail = get("/agent-sessions", page_size=1, cursor=page["next_cursor"])
    assert {page["items"][0]["session_id"], tail["items"][0]["session_id"]} == {
        first_row["session_id"], third_row["session_id"]}
    assert tail["next_cursor"] is None
    route = f"/agent-sessions/{first_row['session_id']}/runs"
    page = get(route, page_size=1)
    tail = get(route, page_size=1, cursor=page["next_cursor"])
    assert {page["items"][0]["run_id"], tail["items"][0]["run_id"]} == {
        str(first), str(second)}
    assert all(row["history_hidden"] and row["created_at"] is None and row["recorded_at"]
               and row["conversation"] == {
                   "previous_run_id": None, "next_run_id": None, "links_unavailable": True,
               } for row in page["items"] + tail["items"])
    assert tail["next_cursor"] is None
    legacy_ids, cursor = [], None
    for _ in range(3):
        page = get("/agent-runs", page_size=1, **({"cursor": cursor} if cursor else {}))
        legacy_ids.extend(row["run_id"] for row in page["items"])
        cursor = page["next_cursor"]
    assert set(legacy_ids) == {str(first), str(second), str(third)} and cursor is None

    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert setup.client.get(path(setup) + f"/{first}", headers=peer).status_code == 403
    assert ok(setup.client.get(base(setup) + "/agent-sessions", headers=peer))["items"] == []
    with Session(setup.admin) as session:
        before = session.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.tenant_id == setup.tenant))
    for suffix in ("process", "events", "candidates", "continuation"):
        denied = setup.client.get(path(setup) + f"/{first}/{suffix}", headers=setup.headers)
        assert denied.status_code == 403, denied.text
    denied = setup.client.post(path(setup), headers=setup.headers, json={
        "goal": "不可由原话目录取得续接权", "idempotency_key": str(uuid4()),
        "continue_from_run_id": str(first),
    })
    assert denied.status_code == 403, denied.text
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.tenant_id == setup.tenant)) == before


def test_hidden_owner_projection_rechecks_product_and_category_scope(setup):
    source, audience = shared_source(setup)
    identity, row = start(setup, product_id=str(setup.product), goal="PARENT_SCOPE_ONLY_GOAL",
                         sources=[{"artifact_id": str(source), "expected_revision": 1}])
    complete(setup, identity)
    withdraw(setup, audience)
    assert ok(setup.client.get(path(setup) + f"/{identity}", headers=setup.headers))[
        "history_hidden"] is True
    with Session(setup.admin) as session, session.begin():
        product = session.get(Product, setup.product)
        product.owner_id, product.visibility = setup.peer, "private"
        session.execute(delete(ObjectAudience).where(
            ObjectAudience.tenant_id == setup.tenant, ObjectAudience.object_type == "products",
            ObjectAudience.subject_id == setup.product, ObjectAudience.principal_id == setup.human))
    assert setup.client.get(path(setup) + f"/{identity}", headers=setup.headers).status_code == 403
    listed = setup.client.get(base(setup) + "/agent-sessions", headers=setup.headers,
                              params={"q": "PARENT_SCOPE_ONLY_GOAL"})
    assert ok(listed)["items"] == []
    assert setup.client.get(base(setup) + f"/agent-sessions/{row['session_id']}/runs",
                            headers=setup.headers).status_code == 404
    with Session(setup.admin) as session, session.begin():
        session.execute(delete(Grant).where(Grant.category_id == setup.category,
                                           Grant.principal_id == setup.human))
    assert setup.client.get(path(setup) + f"/{identity}", headers=setup.headers).status_code == 403
    assert setup.client.get(base(setup) + "/agent-sessions",
                            headers=setup.headers).status_code == 403


def test_legacy_hidden_run_without_work_state_stays_unavailable_without_backfill(setup):
    source, audience = shared_source(setup)
    identity, _ = start(setup, sources=[{"artifact_id": str(source), "expected_revision": 1}])
    finish(setup, identity)  # Deliberately legacy/raw fixture, not production record_finish.
    with Session(setup.admin) as session:
        assert session.scalar(select(AgentWorkState.id).where(
            AgentWorkState.run_id == identity)) is None
    withdraw(setup, audience)
    assert setup.client.get(path(setup) + f"/{identity}", headers=setup.headers).status_code == 403
    assert ok(setup.client.get(base(setup) + "/agent-sessions", headers=setup.headers))[
        "items"] == []
