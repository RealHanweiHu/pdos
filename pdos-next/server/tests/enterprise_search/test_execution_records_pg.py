"""Actual command facts keep distinct fixed citations and preserve review history."""
# ruff: noqa: F811, F401 -- actual fixture tree, not fabricated execution rows

import os
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, post
from verification_results.fixtures import (
    accepted_work,
    capture,
    command,
    current_rows,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
    results_work,
)

from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.domain.build_start.models import BuildStart
from pdos_next.enterprise_search.sources import prepare_read, select_sources
from pdos_next.models import Artifact, Receipt
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_assistant_temporal_pg import run_http_case
from tests.enterprise_search.test_business_sources_pg import (
    NativeClient,
    apply_event,
    native_search,
    native_session,
)


def records(person, kind):
    with native_session(person) as session:
        prepare_read(session, [kind])
        return [
            dict(row)
            for row in session.execute(
                select_sources(source_type=kind, include_body=True)
            ).mappings()
        ]


def answer(person, source, project_id):
    client = NativeClient(
        str(source["source_id"]), [source["source_type"]], expected_scope=str(project_id)
    )
    owner, scope, host, _ = fixture(person, client, project_id=project_id)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    citation = output["result"]["assistant"]["sources"][0]
    assert citation["source_id"] == str(source["source_id"])
    assert client.calls == 3
    return scope, citation, client, owner._assistant_adapter


def restore_reads(adapter, scope):
    with adapter.store.transaction(scope) as (session, _):
        calls = session.scalars(
            select(AgentToolCall).where(
                AgentToolCall.run_id == scope.run_id,
                AgentToolCall.tool.in_(["assistant.search", "assistant.extract"]),
            )
        ).all()
        saved = {call.tool: call.result for call in calls}
    assert adapter.restore_search(scope, {}, saved["assistant.search"]) == saved["assistant.search"]
    extraction = saved["assistant.extract"]
    assert (
        adapter.restore_extract(
            scope, {"citation_ids": [row["citation_id"] for row in extraction["rows"]]}, extraction
        )
        == extraction
    )


def test_fixed_execution_and_professional_records_are_citable_without_raw_measurements(
    results_work,
):
    work, person = results_work, results_work.setup
    project_id = UUID(work.config["project"])
    build_operations = {
        "build.create",
        "build.start",
        "build.configuration.actual.record",
        "build.output.record",
    }
    unindexed = native_search(person, work.build_id, ["build"])
    assert unindexed["items"] == [] and unindexed["coverage"]["status"] == "partial"
    with Session(person.admin) as session:
        receipts = session.scalars(
            select(Receipt.id).where(
                Receipt.tenant_id == person.tenant, Receipt.operation.in_(build_operations)
            )
        ).all()
    assert len(receipts) >= 4
    for identity in receipts:
        assert apply_event(person, identity)["processed"] == 1
        assert apply_event(person, identity)["changed"] == 0
    build_rows = records(person, "build")
    assert len({row["source_id"] for row in build_rows}) >= 4
    by_kind = {
        row["structured"]["facts"].get("record_kind", "build_plan"): row for row in build_rows
    }
    assert set(by_kind) == {"build_plan", "build_start", "actual_configuration", "build_output"}
    assert all(str(row["object_id"]) == work.build_id for row in build_rows)
    start = by_kind["build_start"]
    start_facts = start["structured"]["facts"]
    assert start_facts["status"] == "executing"
    assert start_facts["occurred_timezone"] == "UTC" and start_facts["occurred_at"]
    assert start_facts["continuation_permission"] == "not_evaluated"
    assert by_kind["build_output"]["structured"]["facts"]["observation_nature"] == "synthetic"
    assert (
        by_kind["actual_configuration"]["structured"]["facts"]["actual_engineering_revision"] == 1
    )
    assert all(
        '"authority_snapshot"' not in row["body"] and '"position"' not in row["body"]
        for row in build_rows
    )
    build_scope, build_citation, build_provider, build_adapter = answer(person, start, project_id)

    captured, _ = capture(work, tuple(range(len(work.report_rows))))
    imported, _ = accepted(
        work.quality, command(work, "test.results.import", captured=captured, final=True)
    )
    assert apply_event(work.quality, imported["id"])["processed"] == 2
    computed = post(work.quality, command(work, "test.result.compute"))
    assert computed.status_code == 200, computed.text
    review_text = "固定范围的专业评审已登记，数值判定与本结论分别保留。"
    reviewed, _ = accepted(work.quality, command(work, "test.run.review", text=review_text))
    assert apply_event(work.quality, reviewed["id"])["processed"] == 2
    review_row = next(
        row
        for row in records(work.quality, "test_run")
        if row["is_current"] and row["structured"]["facts"].get("operation") == "test.run.review"
    )
    facts = review_row["structured"]["facts"]
    assert facts["professional_conclusion"]["text"] == review_text
    assert facts["professional_conclusion"]["actor_id"] == str(work.quality.human)
    assert facts["professional_conclusion"]["at"]["received_at"]
    assert facts["result"] == "pass" and facts["disposition"] is None
    assert facts["coverage"] and all(row["result"] == "pass" for row in facts["computed_results"])
    assert all(
        marker not in review_row["body"]
        for marker in ('"raw_value"', '"position"', '"input_snapshot"', '"authority_snapshot"')
    )
    run_scope, citation, provider, run_adapter = answer(work.quality, review_row, project_id)
    assert review_text in citation["quote"]

    disposition_text = "按本次已登记结果完成测试处置。"
    disposed, _ = accepted(
        work.quality, command(work, "test.disposition.decide", text=disposition_text)
    )
    assert apply_event(work.quality, disposed["id"])["processed"] == 2
    current = [row for row in records(work.quality, "test_run") if row["is_current"]]
    action = next(
        row
        for row in current
        if row["structured"]["facts"].get("operation") == "test.disposition.decide"
    )
    assert action["structured"]["facts"]["professional_conclusion"]["text"] == review_text
    assert action["structured"]["facts"]["disposition"]["text"] == disposition_text
    assert action["source_id"] != review_row["source_id"]
    old = next(
        row
        for row in records(work.quality, "test_run")
        if row["source_id"] == review_row["source_id"]
    )
    assert not old["is_current"] and old["body"] == review_row["body"]
    saved = work.quality.client.get(
        f"/v1/categories/{person.category}/agent-runs/{run_scope.run_id}",
        headers=work.quality.headers,
    )
    assert saved.status_code == 200, saved.text
    previous = saved.json()["result"]["result"]["assistant"]
    assert previous["sources"][0]["currentness"] == "updated"
    assert review_text in previous["sources"][0]["quote"]
    restore_reads(run_adapter, run_scope)
    assert provider.calls == 3

    with Session(person.admin) as session, session.begin():
        root = session.get(BuildStart, start["source_id"]).event_source["artifact_id"]
        session.get(Artifact, UUID(root)).revision += 1
    visible = native_search(person, str(start["source_id"]), ["build"])
    assert visible["items"][0]["read_basis_status"] == "needs_recheck"
    after = next(row for row in records(person, "build") if row["source_id"] == start["source_id"])
    assert after["body"] == start["body"] and after["content_hash"] == start["content_hash"]
    restore_reads(build_adapter, build_scope)
    saved = person.client.get(
        f"/v1/categories/{person.category}/agent-runs/{build_scope.run_id}", headers=person.headers
    )
    assert saved.status_code == 200, saved.text
    historical = saved.json()["result"]["result"]["assistant"]["sources"][0]
    assert historical["currentness"] == "updated"
    assert historical["read_basis_status"] == "needs_recheck"
    page = person.client.get(build_citation["url"].removeprefix("/api"), headers=person.headers)
    assert page.status_code == 200 and build_citation["quote"] in page.json()["text"]
    assert build_provider.calls == 3
    _, rechecked, _, _ = answer(person, after, project_id)
    assert rechecked["read_basis_status"] == "needs_recheck"
    with Session(person.admin) as session, session.begin():
        session.get(Artifact, UUID(root)).status = "withdrawn"
    assert native_search(person, str(start["source_id"]), ["build"])["items"] == []
    saved = person.client.get(
        f"/v1/categories/{person.category}/agent-runs/{build_scope.run_id}", headers=person.headers
    )
    assert saved.status_code == 403


@pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit verified local Temporal and checkpoint runtime required",
)
def test_professional_record_runs_through_authenticated_temporal_and_fixed_source(
    results_work, monkeypatch
):
    work = results_work
    captured, _ = capture(work, tuple(range(len(work.report_rows))))
    accepted(work.quality, command(work, "test.results.import", captured=captured, final=True))
    computed = post(work.quality, command(work, "test.result.compute"))
    assert computed.status_code == 200, computed.text
    receipt, _ = accepted(
        work.quality,
        command(
            work, "test.run.review", text="SYNTHETIC_NAMED_REVIEW_ONLY_IN_FIXED_SOURCE_20261028"
        ),
    )
    assert apply_event(work.quality, receipt["id"])["processed"] == 2
    reviewed = next(
        row
        for row in records(work.quality, "test_run")
        if row["is_current"] and row["structured"]["facts"].get("operation") == "test.run.review"
    )
    run_http_case(
        work.quality,
        monkeypatch,
        NativeClient(str(reviewed["source_id"]), ["test_run"]),
        expected_kind="test_run",
        expected_calls=3,
        forbidden_history_tokens=("SYNTHETIC_NAMED_REVIEW_ONLY_IN_FIXED_SOURCE_20261028",),
    )
