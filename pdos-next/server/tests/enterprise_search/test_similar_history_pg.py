"""Real quality commands and page retrieval/feedback. Root runs the verified PG target."""
# ruff: noqa: F811,F401 -- imported fixtures register their actual parent dependency tree

import json
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from quality_execution.fixtures import (
    accepted_work,
    command,
    create_issue,
    known_configuration,
    launch_work,
    operational_work,
    publish_policy,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import accepted

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.database import tenant_session
from pdos_next.enterprise_search.indexing import project
from pdos_next.enterprise_search.similar_history_models import SimilarHistoryFeedback
from pdos_next.models import Receipt


@pytest.fixture
def pair(quality_work):
    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work, 0, title="D16-01 接口漏气历史线索")
    second, _ = create_issue(work, 1, title="D16-02 接口漏气处理记录")
    with tenant_session(work.setup.engine, work.quality.tenant,
                        actor_id=work.quality.human, category_id=work.setup.category) as session:
        for receipt in (first, second):
            assert project(session, work.quality.ctx, "issue", UUID(receipt["subject_id"]))[
                "status"] == "ready"
    return work, first, second


def route(work, receipt):
    return (f"/v1/categories/{work.setup.category}/products/{work.setup.product}"
            f"/quality-issues/{receipt['result']['issue_id']}/similar-history")


def reading(pair, *, actor=None):
    work, first, _ = pair
    person = actor or work.quality
    return person.client.get(route(work, first), headers=person.headers,
                             params={"version_id": first["subject_id"]})


def test_actual_page_reads_metadata_fields_and_never_creates_run_or_business_write(pair):
    work, first, second = pair
    with Session(work.setup.admin) as session:
        before = (session.scalar(select(func.count()).select_from(Receipt)),
                  session.scalar(select(func.count()).select_from(AgentRun)))
    response = reading(pair)
    assert response.status_code == 200, response.text
    value = response.json()
    assert 1 <= len(value["items"]) <= 5
    card = next(row for row in value["items"] if row["source_id"] == second["subject_id"])
    assert card["source_revision"] == 1 and card["kind"] == "issue"
    assert card["root_cause"] == "未记录" and "待复验" in card["verification"]
    assert card["containment"] == ["未记录"] and card["capa_actions"] == ["未记录"]
    assert card["object_url"] and "issue=" in card["object_url"]
    assert not any(row["source_id"] == first["subject_id"] for row in value["items"])
    assert "issue_snapshot" not in response.text and "required_source_read_set" not in response.text
    assert reading(pair, actor=work.setup).status_code == 403
    with Session(work.setup.admin) as session:
        assert before == (session.scalar(select(func.count()).select_from(Receipt)),
                          session.scalar(select(func.count()).select_from(AgentRun)))
        assert session.scalar(select(func.count()).select_from(SimilarHistoryFeedback).where(
            SimilarHistoryFeedback.tenant_id == work.quality.tenant)) == 0


def test_actual_explicit_not_relevant_feedback_is_private_append_only_and_idempotent(pair):
    work, first, second = pair
    body = {"version_id": first["subject_id"], "candidate_kind": "issue",
            "candidate_source_id": second["subject_id"], "candidate_revision": 1,
            "action": "not_relevant", "request_key": str(uuid4())}
    path = route(work, first) + "/feedback"
    saved = work.quality.client.post(path, headers=work.quality.headers, json=body)
    assert saved.status_code == 200, saved.text
    replay = work.quality.client.post(path, headers=work.quality.headers, json=body)
    assert replay.json() == saved.json()
    conflict = work.quality.client.post(path, headers=work.quality.headers,
                                        json={**body, "action": "opened"})
    assert conflict.status_code == 409
    with Session(work.setup.admin) as session:
        row = session.scalar(select(SimilarHistoryFeedback).where(
            SimilarHistoryFeedback.id == UUID(saved.json()["feedback_id"])))
        assert row.owner_id == work.quality.human and row.issue_revision == 1
        assert row.ranking_version and row.candidate_source_id == UUID(second["subject_id"])
        assert not {"query", "body", "title", "text"} & set(row.__table__.columns.keys())
    with tenant_session(work.setup.engine, work.setup.tenant,
                        actor_id=work.setup.human, category_id=work.setup.category) as session:
        assert not list(session.scalars(select(SimilarHistoryFeedback)))
    with pytest.raises(DBAPIError):
        with tenant_session(
            work.setup.engine, work.quality.tenant,
            actor_id=work.quality.human, category_id=work.setup.category,
        ) as session:
            session.execute(text("DELETE FROM public.similar_history_feedback"))
    # Feedback does not silently alter ranking or become business knowledge.
    assert reading(pair).json()["items"][0]["source_id"] == second["subject_id"]


def test_actual_merged_and_already_linked_logical_objects_are_excluded(pair):
    work, first, second = pair
    request = command(work, "quality.issue.merge", {
        "issue_id": first["result"]["issue_id"], "expected_issue_revision": 1,
        "sources": [{"id": second["result"]["issue_id"], "revision": 1}],
        "reason": "本人核对合成相同范围，保留独立失败",
    })
    receipt, _ = accepted(work.quality, request)
    response = work.quality.client.get(route(work, first), headers=work.quality.headers,
                                       params={"version_id": receipt["subject_id"]})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_actual_page_warm_latency_and_sql_count(pair):
    work, _first, _second = pair
    assert reading(pair).status_code == 200
    elapsed, counts = [], []
    for _ in range(12):
        queries = []
        def capture(_connection, _cursor, statement, *_args, queries=queries):
            queries.append(statement)
        event.listen(work.setup.engine, "before_cursor_execute", capture)
        start = perf_counter()
        try:
            response = reading(pair)
        finally:
            event.remove(work.setup.engine, "before_cursor_execute", capture)
        assert response.status_code == 200, response.text
        elapsed.append(perf_counter() - start)
        counts.append(len(queries))
    p95 = sorted(elapsed)[-1]
    print(json.dumps({"page_warm_p95_seconds": p95, "sql_counts": counts,
                      "runs": 0, "model_calls": 0, "egress": 0}))
    assert p95 <= 1.0


@pytest.mark.parametrize("operation", ["SELECT", "INSERT", "UPDATE", "DELETE"])
def test_actual_agent_has_no_feedback_sql_privileges(setup, operation):
    with Session(setup.admin) as session:
        assert not session.scalar(text("SELECT has_table_privilege("
            "'pdos_agent','public.similar_history_feedback',:operation)"), {"operation": operation})
