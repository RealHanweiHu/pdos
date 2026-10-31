"""Native physical offer fact uses its fixed request and ordinary Build relation."""
# ruff: noqa: F401, F811 -- original real fixture tree is explicitly imported

from uuid import UUID

from pdos_next.domain.verification_handoff.models import VerificationHandoffFact
from pdos_next.enterprise_search.sources import prepare_read, select_sources
from sqlalchemy import select
from tests.enterprise_search.role_native_source_harness import assert_native_proof_ports
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_business_sources_pg import (
    NativeClient,
    apply_event,
    native_search,
    native_session,
)
from tests.verification_handoff.test_transactions import (
    handoff_work,
    known_configuration,
    methods,
    offered,
    operational_work,
    ready_work,
)


def test_offer_is_a_fixed_physical_fact_with_explicit_build_and_current_destination(handoff_work):
    work, person = handoff_work, handoff_work.engineer
    methods(work)
    receipt, _prepared, offered_request = offered(work)
    assert apply_event(person, receipt["id"])["processed"] == 1
    assert apply_event(person, receipt["id"])["changed"] == 0
    with native_session(person) as session:
        prepare_read(session, ["verification_handoff"])
        facts = [
            dict(row)
            for row in session.execute(
                select_sources(
                    source_type="verification_handoff",
                    include_body=True,
                )
            ).mappings()
        ]
        actual = session.scalar(
            select(VerificationHandoffFact.id).where(
                VerificationHandoffFact.next_request_version_id == UUID(offered_request["id"]),
            )
        )
    row = next(row for row in facts if row["source_id"] == actual)
    assert row["nature"] == "structured" and row["is_current"]
    assert row["structured"]["facts"]["status_as_recorded"] == "offered"
    assert row["structured"]["facts"]["next_request_version_id"] == offered_request["id"]
    assert row["structured"]["facts"]["continuation_permission"] == "not_evaluated"
    assert_native_proof_ports(person, row)
    found = native_search(person, str(actual), ["verification_handoff", "build"])
    assert any(item.get("relation", {}).get("type") == "handoff_build" for item in found["items"])
    client = NativeClient(str(actual), ["verification_handoff"])
    owner, scope, host, _adapter = fixture(
        person, client, project_id=UUID(str(work.config["project"]))
    )
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    cited = output["result"]["assistant"]["sources"][0]
    assert cited["source_id"] == str(actual)
    assert "projectView=builds" in cited["object_url"] and "panel=handoff" in cited["object_url"]
    assert "build=" + work.build_id in cited["object_url"]
