"""Historical identity discovery over already RLS-filtered query results."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.domain.preproject.category_service import _private_checks
from pdos_next.domain.preproject.evidence_models import EvidenceLink
from pdos_next.domain.preproject.models import (
    ProposalItemVersion,
    ProposalRevision,
    ProposalSource,
    ProposalSubmission,
)
from pdos_next.models import Artifact, Claim, UploadedOriginal


class ReadableRows:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    def scalars(self, statement):
        self.queries.append(statement)
        return self.rows.get(statement.column_descriptions[0]["entity"], [])


@pytest.mark.parametrize("history", ["current", "item", "revision", "submission", "link", "run"])
def test_removed_source_filename_remains_an_identity_token(history):
    tenant, category, proposal, source, original, claim_id, run_id = (uuid4() for _ in range(7))
    ctx = SimpleNamespace(tenant_id=tenant, category_id=category)
    row = SimpleNamespace(id=proposal, source_refs=[], context_refs=[], customer_identities=[])
    reference = {"type": "original", "id": str(source), "version": 1}
    rows = {
        Artifact: [SimpleNamespace(id=source, original_id=original, content="Synthetic source")],
        UploadedOriginal: ["客户X需求.xlsx"],
    }
    if history == "current":
        rows[ProposalSource] = [SimpleNamespace(source_type="original", source_id=source)]
    elif history == "item":
        rows[ProposalItemVersion] = [SimpleNamespace(source_refs=[reference])]
    elif history == "revision":
        rows[ProposalRevision] = [SimpleNamespace(changed_items=[{"source_refs": [reference]}])]
    elif history == "submission":
        rows[ProposalSubmission] = [
            SimpleNamespace(
                frozen_document={"items": [{"source_refs": [reference]}]},
                context_refs=[],
            )
        ]
    elif history == "link":
        rows[EvidenceLink] = [SimpleNamespace(evidence_type="artifact", evidence_id=source)]
    else:
        rows[Claim] = [
            SimpleNamespace(
                id=claim_id,
                proposal_id=proposal,
                artifact_id=None,
                privacy="private",
                run_id=run_id,
            )
        ]
        rows[AgentRun] = [
            SimpleNamespace(
                read_sources=[
                    {
                        "artifact_id": str(source),
                        "expected_revision": 1,
                        "product_id": None,
                    }
                ]
            )
        ]
    session = ReadableRows(rows)
    checked = _private_checks(session, ctx, row, {"text": "客户X需求.xlsx 的研究摘要"})
    assert checked["hits"] == [{"kind": "filename", "value": "客户X需求.xlsx"}]
    assert not checked["filenames_clean"] and checked["identities_clean"]
    artifact_query = next(
        q for q in session.queries if q.column_descriptions[0]["entity"] is Artifact
    )
    assert source in next(
        v for v in artifact_query.compile().params.values() if isinstance(v, list)
    )
    if history == "run":
        query = next(q for q in session.queries if q.column_descriptions[0]["entity"] is AgentRun)
        assert proposal in query.compile().params.values()
        assert "private_context IS true" in str(query)
        assert (
            tenant in query.compile().params.values()
            and category in query.compile().params.values()
        )


def test_historical_reference_does_not_bypass_current_source_read_authority():
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    source = uuid4()
    row = SimpleNamespace(id=uuid4(), source_refs=[], context_refs=[], customer_identities=[])
    # The historical reference is readable, but RLS hides its actual source now.
    session = ReadableRows(
        {
            ProposalItemVersion: [
                SimpleNamespace(
                    source_refs=[
                        {
                            "type": "original",
                            "id": str(source),
                            "version": 1,
                        }
                    ]
                )
            ]
        }
    )
    checked = _private_checks(session, ctx, row, {"text": "客户X需求.xlsx 的研究摘要"})
    assert checked["filenames_clean"] and checked["hits"] == []
    assert all(q.column_descriptions[0]["entity"] is not UploadedOriginal for q in session.queries)


@pytest.mark.parametrize("source_kind", ["artifact", "claim"])
def test_public_research_body_is_not_treated_as_uploaded_original(source_kind):
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    source, claim_id = uuid4(), uuid4()
    body = "Public synthetic research states a reusable requirement."
    row = SimpleNamespace(
        id=uuid4(),
        source_refs=[
            {
                "type": source_kind,
                "id": str(source if source_kind == "artifact" else claim_id),
                "version": 1,
            }
        ],
        context_refs=[],
        customer_identities=[],
    )
    rows = {Artifact: [SimpleNamespace(id=source, original_id=None, content=body)]}
    if source_kind == "claim":
        rows[Claim] = [
            SimpleNamespace(
                id=claim_id,
                proposal_id=row.id,
                artifact_id=source,
                privacy="shared",
                run_id=None,
            )
        ]
    checked = _private_checks(ReadableRows(rows), ctx, row, {"text": body})
    assert checked["hits"] == []
    assert checked["overlap_warnings"] == []
    assert checked["refs_clean"] and checked["filenames_clean"] and checked["identities_clean"]


def test_uploaded_original_body_keeps_existing_overlap_warning():
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    source = uuid4()
    body = "Synthetic uploaded requirement text."
    row = SimpleNamespace(
        id=uuid4(),
        source_refs=[{"type": "original", "id": str(source), "version": 1}],
        context_refs=[],
        customer_identities=[],
    )
    session = ReadableRows(
        {
            Artifact: [SimpleNamespace(id=source, original_id=uuid4(), content=body)],
            UploadedOriginal: ["private-requirement.txt"],
        }
    )
    checked = _private_checks(session, ctx, row, {"text": body})
    assert checked["hits"] == []
    assert checked["overlap_warnings"] == [
        {"source_index": 0, "characters": len(body), "quote": body}
    ]
