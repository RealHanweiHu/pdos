"""Actual native status/Outbox/fixed answers; root runs isolated PG only."""
# ruff: noqa: F401, F811 -- original fixtures register the genuine native chain

from uuid import UUID

from pdos_next.enterprise_search.sources import prepare_read, select_sources
from tests.enterprise_search.role_native_source_harness import assert_native_proof_ports
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_business_sources_pg import (
    NativeClient,
    apply_event,
    native_session,
)
from tests.work_management_pg import test_workflow as work_flow
from tests.work_management_pg.test_workflow import original_security_work, work


def records(person):
    with native_session(person) as session:
        prepare_read(session, ["project_status"])
        return [
            dict(row)
            for row in session.execute(
                select_sources(
                    source_type="project_status",
                    include_body=True,
                )
            ).mappings()
        ]


def test_named_status_keeps_history_current_and_fixed_native_answer(work):
    person = work.setup
    first = work_flow.execute(
        work,
        work_flow.STATUS,
        work_flow.payload(
            work,
            fact_summary="Synthetic status: waiting for drawing",
            next_steps="Obtain drawing",
            task_refs=[],
        ),
    )[1]
    assert apply_event(person, first["id"])["processed"] == 1
    second = work_flow.execute(
        work,
        work_flow.STATUS,
        work_flow.payload(
            work,
            fact_summary="Synthetic status: drawing now recorded",
            next_steps="Check fit evidence",
            task_refs=[],
        ),
    )[1]
    assert apply_event(person, second["id"])["processed"] == 2
    assert apply_event(person, second["id"])["changed"] == 0
    by_id = {str(row["source_id"]): row for row in records(person)}
    assert not by_id[first["subject_id"]]["is_current"]
    row = by_id[second["subject_id"]]
    assert row["is_current"] and row["nature"] == "structured"
    assert row["project_id"] == work.project_id
    assert row["structured"]["facts"]["continuation_permission"] == "not_evaluated"
    assert_native_proof_ports(person, row, parents=[work.source["id"]])
    client = NativeClient(second["subject_id"], ["project_status"])
    owner, scope, host, _adapter = fixture(person, client, project_id=work.project_id)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    cited = output["result"]["assistant"]["sources"][0]
    assert cited["source_id"] == second["subject_id"] and cited["source_revision"] == 1
    assert "projectView=now" in cited["object_url"] and "panel=summary" in cited["object_url"]
    assert UUID(cited["source_id"]) in {r["source_id"] for r in records(person)}
