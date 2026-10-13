"""Parse inventory persistence, seal coverage and dispatch over the marked database."""
# ruff: noqa: F811 -- pytest uses the explicitly imported marked database fixtures

from uuid import UUID

from sqlalchemy import select

from pdos_next.agent_kernel.extract_read_ledger import ExtractReadLedger
from pdos_next.agent_kernel.extract_sources import seal_for
from pdos_next.database import tenant_session
from pdos_next.models import Artifact, UploadedOriginal
from tests.agent_kernel.test_extract_dispatch_pg import (
    extract as dispatch_extract,
)
from tests.agent_kernel.test_extract_dispatch_pg import (
    fixture as dispatch_fixture,
)
from tests.agent_kernel.test_m3_original_binding_pg import uploaded
from tests.evidence_processing.test_parse_inventory import mixed_pdf
from tests.preproject.test_g0 import work as work
from tests.test_durable_evidence import upload_input
from tests.test_original_security import security_work as security_work

PDF = "application/pdf"


def uploaded_pdf(work, security_work, *, text_pages=(True, False)):
    from security_fixture import secured_parse

    response = security_work.client.post(
        f"/v1/categories/{work.category}/originals",
        headers=work.headers,
        json=upload_input(
            mixed_pdf(text_pages), filename="synthetic.pdf", source_label="synthetic pdf"
        ).model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    root_id = UUID(response.json()["subject_id"])
    parsed = secured_parse(
        work.engine,
        {
            "tenant_id": str(work.tenant),
            "category_id": str(work.category),
            "product_id": None,
            "actor_id": str(work.human),
            "requester_id": str(work.human),
            "subject_id": str(root_id),
        },
        security_work.store,
    )
    assert parsed["status"] == "parsed", parsed
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        row = session.scalar(select(Artifact).where(Artifact.original_id == root_id))
        return root_id, row.id


def original_row(work, root_id):
    from types import SimpleNamespace

    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        row = session.get(UploadedOriginal, root_id)
        return SimpleNamespace(
            status=row.status, parse_code=row.parse_code, parse_manifest=row.parse_manifest
        )


def sealed(work, version_id, revision=1):
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        seal, _ = seal_for(session, work.ctx, None, version_id, revision)
    return seal


def pdf_row(artifact_id, text):
    return {
        "artifact_version_id": artifact_id,
        "locator": "page:1",
        "quote": text,
        "kind": "compliance",
        "statement": "合成 PDF 合规要求",
        "missing": [],
    }


def test_text_parse_persists_line_inventory_and_seal_coverage(work, security_work):
    root_id, version_id = uploaded(work, security_work)
    row = original_row(work, root_id)
    assert row.status == "parsed" and row.parse_code is None
    manifest = row.parse_manifest
    assert manifest["basis"] == "line" and manifest["parser_version"] == "pdos-evidence-v1"
    assert [item["line"] for item in manifest["expected_locations"]] == [1]
    seal = sealed(work, version_id)
    assert seal.parse_manifest is not None and seal.parse_manifest.basis == "line"
    coverage = ExtractReadLedger([seal]).coverage(seal.artifact_id)
    locations = coverage["original_locations"]
    assert locations["extent_known"] is True
    assert locations["fully_represented"] is True
    assert locations["unrepresented"] == [] and locations["unlisted"] == []
    assert locations["reason"] is None


def test_partial_pdf_persists_full_page_extent_and_reports_unrepresented(work, security_work):
    root_id, version_id = uploaded_pdf(work, security_work)
    row = original_row(work, root_id)
    assert row.status == "parsed" and row.parse_code == "PARTIAL_TEXT"
    manifest = row.parse_manifest
    assert manifest["basis"] == "page"
    assert [item["page"] for item in manifest["expected_locations"]] == [1, 2]
    seal = sealed(work, version_id)
    assert seal.parse_manifest is not None
    coverage = ExtractReadLedger([seal]).coverage(seal.artifact_id)
    locations = coverage["original_locations"]
    assert locations["extent_known"] is True
    assert [item["page"] for item in locations["represented"]] == [1]
    assert [item["page"] for item in locations["unrepresented"]] == [2]
    assert locations["fully_represented"] is False
    assert locations["reason"] == "PARTIAL_TEXT"


def test_failed_parse_leaves_extent_honestly_unknown(work, security_work):
    response = security_work.client.post(
        f"/v1/categories/{work.category}/originals",
        headers=work.headers,
        json=upload_input(
            b"\xff\xfe not utf-8 \x00", source_label="broken synthetic"
        ).model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    root_id = UUID(response.json()["subject_id"])
    from security_fixture import secured_parse

    parsed = secured_parse(
        work.engine,
        {
            "tenant_id": str(work.tenant),
            "category_id": str(work.category),
            "product_id": None,
            "actor_id": str(work.human),
            "requester_id": str(work.human),
            "subject_id": str(root_id),
        },
        security_work.store,
    )
    assert parsed["status"] == "failed", parsed
    row = original_row(work, root_id)
    assert row.status == "failed" and row.parse_manifest is None
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        assert session.scalar(select(Artifact).where(Artifact.original_id == root_id)) is None


def test_dispatch_over_partial_original_reports_exact_extent_and_replays(work, security_work):
    owner, scope, host, client, calls, source, version_id, _, args = dispatch_fixture(
        work, security_work, rows_factory=pdf_row, uploader=uploaded_pdf,
        mount_quote="Synthetic page text",
    )
    result = dispatch_extract(host, scope, source, args)
    assert result["failures"] == []
    assert [row["quote"] for row in result["rows"]] == ["Synthetic page text"]
    assert result["rows"][0]["locator"] == "page:1"
    coverage = result["coverage"][0]
    locations = coverage["original_locations"]
    assert [item["page"] for item in locations["represented"]] == [1]
    assert [item["page"] for item in locations["unrepresented"]] == [2]
    assert locations["fully_represented"] is False
    assert locations["reason"] == "PARTIAL_TEXT"
    replay = dispatch_extract(host, scope, source, args)
    assert replay == result
    assert [kind for kind, _ in calls] == ["main", "child-read", "child-answer"]
