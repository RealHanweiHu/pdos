"""Actual native Change origins and title-only suggestions; root owns PG/browser execution."""
# ruff: noqa: F401,F811 -- existing native fixture dependency tree

import json
import statistics
from dataclasses import replace
from time import perf_counter
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from change_execution.test_transactions import change_work
from change_execution.test_transactions import command as change_command
from change_execution.test_transactions import create_payload as change_payload
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.database import tenant_session
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.enterprise_search.indexing import project
from pdos_next.enterprise_search.similar_history_models import SimilarHistoryFeedback
from pdos_next.models import Receipt
from sqlalchemy import event, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import post
from tests.enterprise_search.test_similar_history_pg import (
    accepted_work,
    create_issue,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)

pytestmark = pytest.mark.parametrize("setup", [{"test_authorization_hours": 4}], indirect=True)


@pytest.fixture
def similar_change_pair(change_work):
    """One existing quality/change chain, two native Changes and an unrelated Issue.

    Browser hook: item.funcargs['similar_change_pair'] exposes work, app, first,
    second, change_ids, issue, project_id and title_query. Receipts are original
    native response dictionaries; version IDs are their actual subject_id.
    """
    work = change_work
    issue, _command = create_issue(work, 1, title="D16 接口漏气历史问题")
    receipts, changes = [], []
    for suffix in ("A", "B"):
        payload = change_payload(work)
        payload["title"] = "D16 接口漏气历史变更 " + suffix
        command, inputs = change_command(work, "change.request.create", payload)
        response = post(work.quality, command)
        assert response.status_code == 200, response.text
        receipts.append(response.json())
        changes.append(inputs["change_id"])
    person = work.quality
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        requester_id=person.human, category_id=person.category) as session:
        # Every version is actual native history. Index its normal registered
        # projection; do not fabricate a current pointer or source/body/proof.
        for identity in session.scalars(select(QualityIssueVersion.id).where(
            QualityIssueVersion.tenant_id == person.tenant,
        )).all():
            for kind in ("issue", "capa"):
                assert project(session, person.ctx, kind, identity)["status"] in {
                    "ready", "unavailable",
                }
        for receipt in receipts:
            assert project(session, person.ctx, "change", UUID(receipt["subject_id"]))[
                "status"] == "ready"
    return SimpleNamespace(
        work=work, app=person.client.app, first=receipts[0], second=receipts[1],
        change_ids=changes, issue=issue, project_id=UUID(work.config["project"]),
        title_query="接口漏气",
    )


def change_path(case, index=0):
    person = case.work.quality
    return (f"/v1/categories/{person.category}/products/{person.product}"
            f"/change-execution/{case.change_ids[index]}/similar-history")


def title_path(case):
    person = case.work.quality
    return f"/v1/categories/{person.category}/products/{person.product}/similar-history"


def read_change(case, *, actor=None):
    person = actor or case.work.quality
    return person.client.get(change_path(case), headers=person.headers,
                             params={"version_id": case.first["subject_id"]})


def totals(case):
    person = case.work.quality
    with Session(person.admin) as session:
        return tuple(session.scalar(select(func.count()).select_from(model).where(
            model.tenant_id == person.tenant,
        )) for model in (Receipt, AgentRun, AgentToolCall, SimilarHistoryFeedback))


def test_native_change_details_exclude_self_and_registered_issue_and_reveal_no_private_trace(
    similar_change_pair,
):
    case, person = similar_change_pair, similar_change_pair.work.quality
    before = totals(case)
    response = read_change(case)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["anchor"]["kind"] == "change"
    assert value["anchor"]["change_id"] == case.change_ids[0]
    assert "issue_id" not in value["anchor"]
    assert 1 <= len(value["items"]) <= 5
    assert any(row["source_id"] == case.second["subject_id"] for row in value["items"])
    assert any(row["source_id"] == case.issue["subject_id"] for row in value["items"])
    assert not any(row["object_id"] in {case.change_ids[0], str(case.work.issue_id)}
                   for row in value["items"])
    assert all(not row["can_prepare_merge"] for row in value["items"])
    assert "request_snapshot" not in response.text and "source_read_set" not in response.text
    denied = read_change(case, actor=case.work.setup)
    assert denied.status_code == 403 and case.first["subject_id"] not in denied.text
    hidden = case.work.setup.client.get(title_path(case), headers=case.work.setup.headers,
        params={"kind": "change", "title": case.title_query, "project_id": str(case.project_id)})
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["items"] == []
    assert not any(identity in hidden.text for identity in case.change_ids)
    assert totals(case) == before
    assert person.client.app is case.app


def test_native_change_feedback_is_private_exact_append_only_and_cannot_merge(similar_change_pair):
    case, person = similar_change_pair, similar_change_pair.work.quality
    before = totals(case)
    body = {"version_id": case.first["subject_id"], "candidate_kind": "change",
            "candidate_source_id": case.second["subject_id"], "candidate_revision": 1,
            "action": "not_relevant", "request_key": str(uuid4())}
    path = change_path(case) + "/feedback"
    saved = person.client.post(path, headers=person.headers, json=body)
    assert saved.status_code == 200, saved.text
    assert person.client.post(path, headers=person.headers, json=body).json() == saved.json()
    conflict = person.client.post(path, headers=person.headers, json={**body, "action": "opened"})
    assert conflict.status_code == 409
    denied = person.client.post(path, headers=person.headers, json={
        **body, "action": "merge_prepared", "request_key": str(uuid4()),
    })
    assert denied.status_code == 403
    with Session(person.admin) as session:
        row = session.get(SimilarHistoryFeedback, UUID(saved.json()["feedback_id"]))
        assert row.change_id == UUID(case.change_ids[0])
        assert row.change_version_id == UUID(case.first["subject_id"]) and row.change_revision == 1
        assert row.issue_id is row.issue_version_id is row.issue_revision is None
        data = {col.key: getattr(row, col.key) for col in row.__table__.columns
                if col.key not in {"id", "created_at"}}
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        requester_id=person.human, category_id=person.category) as session:
        # Actual fixed version and logical identity may not be substituted.
        for patch in ({"change_id": UUID(case.change_ids[1])}, {"action": "merge_prepared"}):
            with pytest.raises(DBAPIError), session.begin_nested():
                session.add(SimilarHistoryFeedback(**{**data, **patch, "request_key": uuid4()}))
                session.flush()
    with tenant_session(person.engine, person.tenant, actor_id=case.work.setup.human,
                        category_id=person.category) as session:
        assert session.get(SimilarHistoryFeedback, UUID(saved.json()["feedback_id"])) is None
    assert totals(case) == (*before[:3], before[3] + 1)


def test_native_title_suggestions_for_both_forms_are_readonly_and_have_no_draft_identity(
    similar_change_pair,
):
    case, person = similar_change_pair, similar_change_pair.work.quality
    before = totals(case)
    for kind in ("issue", "change"):
        response = person.client.get(title_path(case), headers=person.headers, params={
            "kind": kind, "title": "  " + case.title_query + "  ",
            "project_id": str(case.project_id),
        })
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["anchor"]["kind"] == kind + "_draft"
        assert value["anchor"]["title"] == case.title_query
        assert not {"object_id", "issue_id", "change_id", "version_id", "revision"} & set(
            value["anchor"],
        )
        assert 1 <= len(value["items"]) <= 5
        assert all(not row["can_prepare_merge"] for row in value["items"])
        assert all(row["object_url"] for row in value["items"])
    assert person.client.get(title_path(case), headers=person.headers,
        params={"kind": "issue", "title": " "}).status_code == 422
    assert person.client.get(title_path(case), headers=person.headers,
        params={"kind": "issue", "title": "x" * 241}).status_code == 422
    assert person.client.post(title_path(case) + "/feedback", headers=person.headers,
                              json={}).status_code == 404
    assert totals(case) == before


def test_native_change_and_title_page_inclusive_p95_and_constant_sql(
    similar_change_pair, record_property,
):
    case, person = similar_change_pair, similar_change_pair.work.quality
    checks = [("change_detail", change_path(case), {"version_id": case.first["subject_id"]})]
    checks.extend((kind + "_draft", title_path(case), {"kind": kind, "title": case.title_query,
                   "project_id": str(case.project_id)}) for kind in ("issue", "change"))
    before = totals(case)
    output = []
    for name, path, params in checks:
        for _ in range(5):
            response = person.client.get(path, headers=person.headers, params=params)
            assert response.status_code == 200, response.text
        elapsed, counts = [], []
        for _ in range(40):
            statements = []
            def capture(_connection, _cursor, statement, *_args, statements=statements):
                statements.append(statement)
            event.listen(person.engine, "before_cursor_execute", capture)
            start = perf_counter()
            try:
                response = person.client.get(path, headers=person.headers, params=params)
            finally:
                event.remove(person.engine, "before_cursor_execute", capture)
            elapsed.append(perf_counter() - start)
            counts.append(len(statements))
            assert response.status_code == 200, response.text
        p95 = statistics.quantiles(elapsed, n=100, method="inclusive")[94]
        row = {"name": name, "warm": 5, "measured": 40, "inclusive_p95_seconds": p95,
               "sql_counts": counts, "runs": 0, "model_calls": 0, "egress": 0}
        output.append(row)
        assert len(set(counts)) == 1, row
        assert p95 <= 1.0, row
    record_property("similar_history_completion_performance", json.dumps(output))
    print(json.dumps(output))
    assert totals(case) == before
