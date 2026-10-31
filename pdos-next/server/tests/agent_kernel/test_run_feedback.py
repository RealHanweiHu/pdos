"""Private human feedback, immutable actual version identity and exact request recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from pdos_next.agent_kernel.models import AgentEvent, AgentInput, AgentToolCall
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.clock import now
from pdos_next.models import Grant, Receipt
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from tests.agent_kernel.test_transactions import run


def sample(setup, **kwargs):
    store, scope = run(setup, **kwargs)
    skill = SkillCatalog().load("public_research", scope, lambda *_: True)
    identity = store.emit(
        scope,
        {
            "type": "skill_loaded",
            "key": skill.key,
            "version": skill.version,
            "digest": skill.digest,
            "isolation": "main",
        },
    )
    with store.transaction(scope, lock=True) as (_, row):
        row.versions = {
            "model_version": "synthetic-model@1",
            "model_route_digest": "a" * 64,
            "tool_definitions": {"main": "b" * 64},
            "prompt_prefixes": {"main": "c" * 64},
            "not_feedback_identity": {"private_text": "must not be copied"},
        }
    return store, scope, identity


def url(setup, scope):
    return f"/v1/categories/{setup.category}/agent-runs/{scope.run_id}/feedback"


def request(skill=None):
    return {
        "idempotency_key": str(uuid4()),
        "categories": ["wrong_value", "missing_source"],
        "comment": "Specific synthetic value and evidence issue",
        "skill_load_event_id": str(skill) if skill else None,
    }


def post(setup, scope, body):
    return setup.client.post(url(setup, scope), headers=setup.headers, json=body)


def test_feedback_is_actual_human_record_with_frozen_skill_model_and_no_business_side_effect(setup):
    store, scope, skill = sample(setup)
    store.finish(scope, {"status": "partial", "summary": "Synthetic partial", "result": {}})
    before = setup.client.get(
        url(setup, scope).removesuffix("/feedback"), headers=setup.headers
    ).json()["process"]
    body = request(skill)
    saved = post(setup, scope, body)
    assert saved.status_code == 200, saved.text
    feedback = saved.json()["feedback"]
    assert feedback["recorded_by"] == str(setup.human)
    assert feedback["versions"]["model_version"] == "synthetic-model@1"
    assert feedback["versions"]["skills"][0]["load_event_id"] == str(skill)
    assert feedback["request"]["categories"] == ["missing_source", "wrong_value"]
    assert "must not be copied" not in saved.text and "not_feedback_identity" not in saved.text
    after = setup.client.get(
        url(setup, scope).removesuffix("/feedback"), headers=setup.headers
    ).json()["process"]
    assert after["ended_at"] == before["ended_at"] and after["business_receipt_count"] == 0
    with Session(setup.admin) as s:
        for model in [AgentInput, AgentToolCall, Receipt]:
            assert (
                s.scalar(
                    select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
                )
                == 0
            )
        actual = s.get(AgentEvent, feedback["id"])
        assert actual.run_id == scope.run_id and actual.body["type"] == "run_feedback"


def test_original_feedback_replays_after_time_and_never_loads_current_model_or_skill(
    setup, monkeypatch
):
    _, scope, skill = sample(setup)
    body = request(skill)
    first = post(setup, scope, body).json()
    from pdos_next.clock import using_clock

    future = now() + timedelta(minutes=5)
    monkeypatch.setattr(
        SkillCatalog, "load", lambda *_: pytest.fail("Feedback cannot load the current skill")
    )
    with using_clock(lambda: future):
        replay = post(setup, scope, {**body, "categories": list(reversed(body["categories"]))})
    assert replay.status_code == 200 and replay.json() == first
    read = setup.client.get(
        url(setup, scope) + "?request_key=" + body["idempotency_key"], headers=setup.headers
    )
    assert read.status_code == 200 and read.json()["items"] == [first["feedback"]]
    assert post(setup, scope, {**body, "comment": "different"}).status_code == 409
    assert len(setup.client.get(url(setup, scope), headers=setup.headers).json()["items"]) == 1


def test_duplicate_concurrent_http_requests_append_one_feedback(setup):
    _, scope, _ = sample(setup)
    body = request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: post(setup, scope, body), range(2)))
    assert [value.status_code for value in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert len(setup.client.get(url(setup, scope), headers=setup.headers).json()["items"]) == 1


def test_feedback_scope_and_actual_skill_cannot_be_overridden_and_read_access_suffices(setup):
    _, scope, _ = sample(setup)
    _, other, foreign_skill = sample(setup)
    assert post(setup, scope, request(foreign_skill)).status_code == 403
    assert post(setup, scope, {**request(), "model_version": "invented"}).status_code == 422
    assert (
        post(setup, scope, {**request(), "categories": ["wrong_value", "wrong_value"]}).status_code
        == 422
    )
    assert (
        setup.client.get(
            url(setup, scope), headers={"Authorization": "Bearer " + setup.tokens[setup.peer]}
        ).status_code
        == 403
    )
    with Session(setup.admin) as s, s.begin():
        grant = s.scalar(
            select(Grant).where(
                Grant.principal_id == setup.human, Grant.category_id == setup.category
            )
        )
        grant.can_write = False
    assert post(setup, scope, request()).status_code == 200
    with Session(setup.admin) as s, s.begin():
        s.scalar(
            select(Grant).where(
                Grant.principal_id == setup.human, Grant.category_id == setup.category
            )
        ).expires_at = now() - timedelta(seconds=1)
    assert setup.client.get(url(setup, scope), headers=setup.headers).status_code == 403
    assert post(setup, other, request()).status_code == 403


def test_feedback_has_complete_pagination_and_original_request_lookup_independent_of_page(setup):
    _, scope, _ = sample(setup)
    bodies = [request() for _ in range(8)]
    ids = {post(setup, scope, body).json()["feedback"]["id"] for body in bodies}
    found = []
    cursor = None
    while True:
        result = setup.client.get(
            url(setup, scope) + "?page_size=3" + (f"&before={cursor}" if cursor else ""),
            headers=setup.headers,
        ).json()
        found += [row["id"] for row in result["items"]]
        cursor = result["next_before"]
        if not cursor:
            break
    assert set(found) == ids and len(found) == 8
    result = setup.client.get(
        url(setup, scope) + "?request_key=" + bodies[0]["idempotency_key"], headers=setup.headers
    )
    assert result.json()["items"][0]["request"]["idempotency_key"] == bodies[0]["idempotency_key"]
    assert (
        setup.client.get(url(setup, scope) + "?before=99999", headers=setup.headers).status_code
        == 403
    )
    assert setup.client.get(
        url(setup, scope) + "?before=1&request_key=" + bodies[0]["idempotency_key"],
        headers=setup.headers,
    ).status_code in {403, 422}


def test_failed_append_rolls_back_and_retry_keeps_original_request(setup):
    _, scope, _ = sample(setup)
    body = request()

    def fail(_, __, target):
        if target.body.get("type") == "run_feedback":
            raise RuntimeError("Synthetic feedback persistence failure")

    event.listen(AgentEvent, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="Synthetic feedback"):
            post(setup, scope, body)
    finally:
        event.remove(AgentEvent, "before_insert", fail)
    assert setup.client.get(url(setup, scope), headers=setup.headers).json()["items"] == []
    assert post(setup, scope, body).status_code == 200


def test_personal_unavailable_work_accepts_own_feedback_without_fabricated_versions(setup):
    from pdos_next.agent_kernel.persistence import create_run
    from pdos_next.database import tenant_session
    from pdos_next.service import Context

    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human
    ) as s:
        identity = create_run(
            s,
            Context(setup.tenant, setup.human, setup.human),
            goal="Synthetic personal work",
            writer_id=setup.agent,
            intent_key=str(uuid4()),
        ).id
    path = f"/v1/personal/agent-runs/{identity}/feedback"
    result = setup.client.post(path, headers=setup.headers, json=request())
    assert (
        result.status_code == 200 and result.json()["feedback"]["versions"]["model_version"] is None
    )
    assert setup.client.get(path, headers=setup.headers).json()["current_versions"]["skills"] == []


def test_private_feedback_does_not_enter_process_or_model_projected_context(setup):
    from pdos_next.agent_kernel.bootstrap import Bootstrap

    _, scope, _ = sample(setup)
    body = {**request(), "comment": "PRIVATE-FEEDBACK-CUSTOMER-MARKER"}
    assert post(setup, scope, body).status_code == 200
    process = setup.client.get(
        url(setup, scope).removesuffix("/feedback") + "/process", headers=setup.headers
    )
    assert "PRIVATE-FEEDBACK" not in process.text
    host = Bootstrap(setup.engine)
    assert "PRIVATE-FEEDBACK" not in str(host.project_context(scope, "Synthetic public goal"))


def test_feedback_is_not_an_agent_write_port_and_reads_only_run_identity_columns(setup):
    from pdos_next.agent_kernel.run_feedback import FeedbackInput, lookup, record
    from pdos_next.database import tenant_session
    from pdos_next.errors import DomainError
    from pdos_next.service import Context

    _, scope, _ = sample(setup)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.agent,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        with pytest.raises(DomainError) as failure:
            record(
                session,
                Context(setup.tenant, setup.agent, setup.human, category_id=setup.category),
                lookup(session, scope.run_id, lock=True),
                FeedbackInput.model_validate(request()),
            )
        assert failure.value.code == "FORBIDDEN_SCOPE"
    statements = []

    def observe(_, __, statement, *___):
        statements.append(statement)

    event.listen(setup.engine, "before_cursor_execute", observe)
    try:
        response = setup.client.get(url(setup, scope), headers=setup.headers)
    finally:
        event.remove(setup.engine, "before_cursor_execute", observe)
    assert response.status_code == 200
    sql = "\n".join(statements)
    assert "agent_runs.result" not in sql and "agent_runs.goal" not in sql
    assert "agent_runs.versions," not in sql and response.json()["items"] == []
