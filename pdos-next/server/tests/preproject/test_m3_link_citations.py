"""Canonical source citations: pure projection checks plus a root-run real G0 case."""
# ruff: noqa: F811 -- pytest injects the imported actual human G0 fixture.

from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from pdos_next.agent_kernel.models import PublicWebSnapshot
from pdos_next.domain.preproject import root_sources
from pdos_next.domain.preproject.evidence_models import EvidenceLink
from pdos_next.domain.preproject.models import ProposalSource, ProposalSubmission
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.domain.products.models import DefinitionSource, DefinitionSpecRow
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Product
from pdos_next.service import Context
from tests.agent_kernel.test_transactions import human_session
from tests.preproject.test_evidence_commands_pg import artifact, evidence_request
from tests.preproject.test_g0 import create, decide_request, post, read, save, submit
from tests.preproject.test_g0 import work as work
from tests.test_configurations import command


@pytest.mark.parametrize(("body", "locator", "expected"), [
    ("\n  actual quote  \n", None, {"line": 2, "quote": "actual quote"}),
    ("first\nsecond\nthird", "line:2", {"line": 2, "quote": "second"}),
    ("first\n \nthird\nfourth", "lines:2:3", {"line": 3, "quote": "third"}),
    ("prefix actual suffix", "chars:7:13", {"line": 1, "quote": "actual"}),
    ("甲乙\r\n 丙丁\r\n", "chars:1:7", {"line": 1, "quote": "乙"}),
    ("甲乙\r\n 丙丁\r\n", "chars:2:7", {"line": 2, "quote": "丙丁"}),
    ("repeat\nrepeat", "chars:7:10", {"line": 2, "quote": "rep"}),
    ("a\u2028b", "chars:1:3", {"line": 2, "quote": "b"}),
    ("x" * 5000, None, {"line": 1, "quote": "x" * 4000}),
    ("x" * 3999 + " y", None, {"line": 1, "quote": "x" * 3999}),
], ids=[
    "whole", "line", "lines", "chars", "unicode-crlf", "after-crlf", "repeated",
    "unicode-separator", "bounded", "bounded-space",
])
def test_citation_is_actual_nonblank_single_line_inside_complete_locator(body, locator, expected):
    result = root_sources._canonical_citation(body, locator)
    assert result == expected
    assert result["quote"] in body.splitlines()[result["line"] - 1]
    assert len(result["quote"]) <= 4000


@pytest.mark.parametrize(("body", "locator"), [
    ("", None), (" \r\n\t", None), ("a\n \nz", "line:2"),
    ("a\r\nb", "chars:1:3"), ("abc", "chars:0:4"), ("abc", "chars:-1:2"),
    ("abc", "chars:2:2"), ("abc", "line:0"), ("abc", "lines:1:2"),
    ("abc", "lines:2:1"), ("abc", "line:True"), ("abc", "line:1:extra"),
])
def test_invalid_empty_or_newline_only_locator_never_becomes_citation(body, locator):
    with pytest.raises(DomainError):
        root_sources._canonical_citation(body, locator)


class ProjectionSession:
    def __init__(self, ctx, source, link):
        self.info = {
            "scope": (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id),
            "read_snapshot": True,
        }
        self.source, self.link, self.statements = source, link, []

    def scalars(self, statement):
        self.statements.append(statement)
        assert statement.column_descriptions[0]["entity"] is EvidenceLink
        return [self.link]

    def scalar(self, statement):
        self.statements.append(statement)
        assert statement.column_descriptions[0]["entity"] in {Artifact, PublicWebSnapshot}
        return self.source

    def execute(self, statement, parameters):
        return [(self.link.evidence_id, 1, "active")]


@pytest.fixture
def projection(monkeypatch):
    from pdos_next import request_proof

    ctx = Context(uuid4(), uuid4(), uuid4(), category_id=uuid4())
    source = NS(
        id=uuid4(), tenant_id=ctx.tenant_id, category_id=ctx.category_id,
        product_id=uuid4(), revision=1, status="active", original_id=None,
        content="Actual first\n Actual second ", markdown="Actual first\n Actual second ",
    )
    link = NS(
        id=uuid4(), target_id=uuid4(), target_version=1, target_type="proposal_item",
        evidence_type="artifact", evidence_id=source.id, evidence_version=1,
        evidence_locator="line:2", relation="supports", reverted_by_receipt_id=None,
    )
    direct = {"type": "human", "id": str(ctx.requester_id), "version": 1, "statement": "Named"}
    item = {
        "item_id": str(link.target_id), "version": 1, "source_refs": [direct],
        "content": {"text": "Unchanged human content"}, "writer_id": str(ctx.requester_id),
    }
    session = ProjectionSession(ctx, source, link)
    proof = NS(authority={}, sources={}, source_rows={}, read_rows={})
    monkeypatch.setattr(request_proof, "request_proof", lambda actual: proof)
    return NS(ctx=ctx, source=source, link=link, item=item, session=session)


def project(fixture):
    return root_sources.project_items(fixture.session, fixture.ctx, [fixture.item])[0]


def test_artifact_projection_keeps_actual_product_direct_input_and_link(projection):
    f = projection
    before = deepcopy(f.item)
    result = project(f)
    assert f.item == before
    assert result["direct_source_refs"] == before["source_refs"]
    assert result["content"] == before["content"]
    assert result["source_refs"][-1] == {
        "type": "artifact", "id": str(f.source.id), "version": 1,
        "line": 2, "quote": "Actual second",
    }
    assert result["evidence_links"][0]["evidence"] == {
        "type": "artifact", "id": str(f.source.id), "version": 1, "locator": "line:2",
    }
    assert result["evidence_links"][0]["status"] == "active"
    # The actual source_for query restricts source scope to the RLS-loaded product.
    assert f.source.product_id in f.session.statements[-1].compile().params.values()
    assert all(statement._for_update_arg is None for statement in f.session.statements)


@pytest.mark.parametrize("status", ["ok", "partial"])
def test_snapshot_citation_uses_ordinary_read_and_has_no_row_write_lock(projection, status):
    f = projection
    f.link.evidence_type, f.source.status = "snapshot", status
    result = project(f)
    assert result["source_refs"][-1]["quote"] == "Actual second"
    assert result["evidence_links"][0]["status"] == "active"
    assert all(statement._for_update_arg is None for statement in f.session.statements)


@pytest.mark.parametrize("failure", [
    "withdrawn", "revision", "unreadable", "tenant", "scope", "no_scope", "locator",
    "snapshot_status", "snapshot_version",
])
def test_stale_projection_keeps_link_identity_without_quote_or_derived_ref(projection, failure):
    f = projection
    if failure == "withdrawn":
        f.source.status = "withdrawn"
    elif failure == "revision":
        f.source.revision = 2
    elif failure == "unreadable":
        f.session.source = None
    elif failure == "tenant":
        f.source.tenant_id = uuid4()
    elif failure == "scope":
        f.session.info["scope"] = (uuid4(), f.ctx.actor_id, f.ctx.requester_id, f.ctx.category_id)
    elif failure == "no_scope":
        f.session.info.pop("scope")
    elif failure == "locator":
        f.link.evidence_locator = "chars:0:9999"
    else:
        f.link.evidence_type = "snapshot"
        f.source.status = "failed" if failure == "snapshot_status" else "ok"
        f.link.evidence_version = 2 if failure == "snapshot_version" else 1
    result = project(f)
    assert result["source_refs"] == f.item["source_refs"]
    assert result["evidence_links"][0]["status"] == "stale"
    assert result["evidence_links"][0]["id"] == str(f.link.id)
    assert "quote" not in str(result["evidence_links"])


def test_original_security_failure_does_not_expose_canonical_quote(projection, monkeypatch):
    from pdos_next import original_security, originals

    f = projection
    f.source.original_id = uuid4()
    original = NS(id=f.source.original_id)
    checked = []

    def require_original(session, ctx, product_id, identity, *, lock):
        assert session is f.session and ctx == f.ctx
        assert product_id == f.source.product_id and identity == original.id
        assert lock is False
        return original

    def require_safe(session, ctx, row, *, lock):
        checked.append(row.id)
        raise DomainError("SOURCE_UNAVAILABLE", "Synthetic original withdrawal")

    monkeypatch.setattr(originals, "require_original", require_original)
    monkeypatch.setattr(original_security, "require_safe", require_safe)
    assert project(f)["evidence_links"][0]["status"] == "stale"
    assert checked == [original.id]


def test_claim_and_reverted_link_never_acquire_new_citations(projection):
    f = projection
    f.link.evidence_type = "claim"
    assert project(f)["source_refs"][-1] == {
        "type": "claim", "id": str(f.source.id), "version": 1,
    }
    f.link.evidence_type = "artifact"
    f.link.reverted_by_receipt_id = uuid4()
    f.session.statements.clear()
    result = project(f)
    assert result["source_refs"] == f.item["source_refs"]
    assert result["evidence_links"][0]["status"] == "reverted"
    assert len(f.session.statements) == 1


@pytest.mark.parametrize("source_scope", ["category", "product"])
def test_pg_actual_artifact_link_freezes_citation_and_g0_definition_remains_consumable(
    work, source_scope,
):
    from pdos_next.domain.preproject.baseline import validate_sources
    from pdos_next.domain.products.definitions import definition_view
    from pdos_next.domain.products.models import DefinitionRevision

    body = "Header\nSynthetic linked specification"
    source_product = work.product if source_scope == "product" else None
    if source_product is None:
        source = artifact(work, body=body)
    else:
        # The existing fixture Product is actually shared and the reviewer has
        # its ordinary category read grant. No new audience or write right is added.
        with human_session(work) as session:
            assert session.get(Product, source_product).visibility == "category"
        registered = post(work, command(work, "evidence.artifact.register", {
            "title": "Actual Product citation source",
            "source_label": "Synthetic human fixture", "content": body, "visibility": "category",
        }, []))
        assert registered.status_code == 200, registered.text
        source = UUID(registered.json()["subject_id"])
    proposal_id, _ = create(work)
    item = next(row for row in read(work, proposal_id).json()["items"] if (
        row["kind"] == "spec" and row["content"]["key"] == "display"
    ))
    direct = deepcopy(item["source_refs"])
    linked = post(work, evidence_request(work, "evidence.link.create", {
        "evidence": {"type": "artifact", "id": str(source), "version": 1, "locator": "line:2"},
        "target": {"type": "proposal_item", "id": item["item_id"], "version": item["version"]},
        "relation": "supports",
    }))
    assert linked.status_code == 200, linked.text
    expected = {
        "type": "artifact", "id": str(source), "version": 1,
        "line": 2, "quote": "Synthetic linked specification",
    }
    submit(work, proposal_id)
    frozen = read(work, proposal_id, work.peer).json()["submission"]["frozen_document"]
    fixed = next(row for row in frozen["items"] if row["item_id"] == item["item_id"])
    assert fixed["source_refs"] == [*direct, expected]
    assert fixed["direct_source_refs"] == direct
    assert "quote" not in str(fixed["evidence_links"])
    assert fixed["evidence_links"][0]["id"] == linked.json()["result"]["link_id"]
    decision = decide_request(work, proposal_id)
    decision["payload"]["project"]["owner_id"] = str(work.human)
    approved, _ = save(work, decision, actor=work.peer)
    with human_session(work) as session:
        definition = session.get(DefinitionRevision, UUID(approved["result"]["definition_id"]))
        actual_source = session.get(Artifact, source)
        assert actual_source.product_id == source_product
        assert actual_source.visibility == "category"
        assert definition.product_id != source_product
        sources = session.scalars(select(DefinitionSource).where(
            DefinitionSource.definition_id == definition.id,
        )).all()
        assert len(sources) == 1
        fixed_source = sources[0]
        assert fixed_source.tenant_id == work.tenant
        assert fixed_source.category_id == work.category
        assert fixed_source.product_id == definition.product_id
        assert {
            "type": "artifact", "id": str(fixed_source.artifact_id),
            "version": fixed_source.source_revision, "line": fixed_source.line,
            "quote": fixed_source.quote,
        } == expected
        assert Reference(**expected).model_dump(mode="json") in frozen["source_refs"]
        assert fixed_source.spec_keys == ["display"]
        spec = session.scalar(select(DefinitionSpecRow).where(
            DefinitionSpecRow.definition_id == definition.id, DefinitionSpecRow.key == "display",
        ))
        assert spec.source_refs == fixed["source_refs"]
        view = definition_view(session, work.ctx, definition)
        assert validate_sources(session, work.ctx, view) == ()
        submission = session.get(ProposalSubmission, definition.source_submission_id)
        assert submission.frozen_document == frozen
        counted = session.scalar(select(ProposalSource).where(
            ProposalSource.proposal_id == UUID(proposal_id), ProposalSource.source_id == source,
        ))
        assert counted.source_version == 1 and counted.ref_count == 1
