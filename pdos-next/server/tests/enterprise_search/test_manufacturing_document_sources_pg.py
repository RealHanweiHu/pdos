"""Real draft and named publication identities, Current and ordinary source roots."""
# ruff: noqa: F401, F811 -- original fixture uses actual native commands

from uuid import UUID

from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingPublicationDocument,
)
from pdos_next.enterprise_search.sources import prepare_read, select_sources
from sqlalchemy import select
from tests.enterprise_search.role_native_source_harness import assert_native_proof_ports
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_business_sources_pg import (
    NativeClient,
    apply_event,
    native_session,
)
from tests.manufacturing_preparation import publication_pg_helpers as publication
from tests.manufacturing_preparation.publication_pg_helpers import publication_case
from tests.manufacturing_preparation_transactions import fixtures as preparation
from tests.manufacturing_preparation_transactions.test_transactions import save


def records(person):
    with native_session(person) as session:
        prepare_read(session, ["manufacturing_document"])
        return [
            dict(row)
            for row in session.execute(
                select_sources(
                    source_type="manufacturing_document",
                    include_body=True,
                )
            ).mappings()
        ]


def test_draft_revision_does_not_replace_formal_fixed_document_and_answer_keeps_link_identity(
    publication_case,
):
    work, person = publication_case, publication_case.setup
    publication.import_authority(work, person.human)
    publication.save_drafts(work)
    first = work.documents["work_instruction"]
    for kind in ("work_instruction", "control_plan"):
        assert apply_event(person, work.draft_receipts[kind]["id"])["processed"] == 1
    command, _review = publication.prepare_publication(work, publication.publication_payload(work))
    response = publication.post(person, command)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert apply_event(person, receipt["id"])["processed"] == 2
    with publication.session(work) as session:
        links = list(
            session.scalars(
                select(ManufacturingPublicationDocument).where(
                    ManufacturingPublicationDocument.publication_id == UUID(receipt["subject_id"]),
                )
            )
        )
        fixed = next(row for row in links if row.document_kind == "work_instruction")
        identity, revision = fixed.id, fixed.publication_revision
    next_payload = preparation.payload(
        work, "work_instruction", previous=first, revision=2,
    )
    next_payload["visibility"] = first["visibility"]
    replacement, replacement_receipt, next_draft = save(
        work, preparation.inputs(work, "work_instruction", next_payload),
    )
    assert replacement and apply_event(person, replacement_receipt["id"])["processed"] == 2
    by_id = {row["source_id"]: row for row in records(person)}
    assert not by_id[UUID(first["id"])]["is_current"]
    assert by_id[UUID(next_draft["id"])]["is_current"]
    formal = by_id[identity]
    assert formal["is_current"] and formal["source_revision"] == revision
    assert formal["structured"]["facts"]["status"] == "published"
    assert formal["structured"]["facts"]["document"]["document_id"] == first["id"]
    assert identity != UUID(first["id"]) and identity != UUID(receipt["subject_id"])
    assert_native_proof_ports(
        person,
        formal,
        parents=[
            first["id"],
            receipt["subject_id"],
            work.document_source,
        ],
    )
    assert formal["customer_original"] and UUID(str(work.original_id)) in formal["original_ids"]
    client = NativeClient(str(identity), ["manufacturing_document"])
    owner, scope, host, _adapter = fixture(person, client, project_id=work.project_id)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    cited = output["result"]["assistant"]["sources"][0]
    assert cited["source_id"] == str(identity)
    assert "projectView=prep" in cited["object_url"] and "panel=publication" in cited["object_url"]
    before = {row["source_id"] for row in records(person)}
    publication.withdraw_original(work)
    assert before and not ({row["source_id"] for row in records(person)} & before)
