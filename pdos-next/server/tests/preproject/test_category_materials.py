"""Pure material admission tests; intentionally no database fixtures."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.preproject import category_reads, category_service
from pdos_next.domain.preproject.category_schemas import KnowledgeAdd, KnowledgePromote
from pdos_next.domain.preproject.deidentification import check_content
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.errors import DomainError


def test_no_caller_origin_and_content_shape():
    with pytest.raises(ValidationError):
        KnowledgeAdd(kind="boundary", content={"definition": "用途"}, origin="human")
    with pytest.raises(ValidationError):
        KnowledgeAdd(kind="competitor", content={"definition": "不是竞品结构"})
    with pytest.raises(ValidationError):
        KnowledgeAdd(
            kind="voice", content={"label": "反馈", "source_platform": "资料", "sample_size": 99}
        )


def test_deidentification_blocks_names_files_urls_and_nested_backrefs():
    checks = check_content(
        {
            "definition": "ＡＣＭＥ 的 RFQ.PDF https://example.test/secret",
            "material": {"source_item_refs": [{"item_id": str(uuid4())}]},
        },
        identities=["acme"],
        filenames=["rfq.pdf"],
    )
    assert not checks["identities_clean"]
    assert not checks["filenames_clean"]
    assert not checks["refs_clean"]
    assert {h["kind"] for h in checks["hits"]} == {"identity", "filename", "url", "private_ref"}


def test_overlap_is_warning_not_identity_veto():
    checks = check_content({"definition": "便携式气泵"}, originals=["便携式气泵适用骑行"])
    assert checks["hits"] == []
    assert checks["overlap_warnings"]
    assert all(checks[key] for key in ("refs_clean", "filenames_clean", "identities_clean"))


@pytest.mark.parametrize("status", ["ok", "partial"])
def test_actual_snapshot_status_and_exact_line(status):
    session = SimpleNamespace(
        scalar=lambda _: SimpleNamespace(
            visibility="category",
            status=status,
            markdown="第一行\n逐字引用片段",
        )
    )
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    ref = Reference(type="snapshot", id=uuid4(), version=1, line=2, quote="引用片段")
    category_service.check_shared_sources(session, ctx, [ref])
    with pytest.raises(DomainError) as caught:
        category_service.check_shared_sources(session, ctx, [ref.model_copy(update={"line": 1})])
    assert caught.value.detail["reason"] == "quote_not_in_snapshot"


def test_private_snapshot_not_promoted_by_read_access():
    session = SimpleNamespace(scalar=lambda _: SimpleNamespace(visibility="private", status="ok"))
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    ref = Reference(type="snapshot", id=uuid4(), version=1, line=1, quote="内容")
    with pytest.raises(DomainError) as caught:
        category_service.check_shared_sources(session, ctx, [ref])
    assert caught.value.detail["reason"] == "private_source_in_shared"


def test_promotion_apply_refuses_identity_even_with_confirmation():
    payload = KnowledgePromote(
        source_proposal_id=uuid4(),
        source_proposal_revision=1,
        kind="boundary",
        content={"definition": "ACME"},
        deidentified_confirmed=True,
        confirmation_token="token",
    )
    validated = category_service.ValidatedMaterial(
        {}, checks=check_content(payload.content, identities=["ACME"])
    )
    with pytest.raises(DomainError) as caught:
        category_service.apply_validated(None, None, None, None, payload, validated)
    assert caught.value.detail["reason"] == "identity_not_removed"


def test_knowledge_read_filters_are_scope_bound(monkeypatch):
    queries = []
    monkeypatch.setattr(category_reads, "_scope", lambda *args: None)
    session = SimpleNamespace(
        execute=lambda q: queries.append(q) or SimpleNamespace(all=lambda: [])
    )
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    result = category_reads.knowledge(
        session, ctx, origin="ai_draft", region="欧盟", kind="regulation", include_history=True
    )
    sql = str(queries[0])
    assert "category_knowledge_entries.tenant_id" in sql
    assert "category_knowledge_entries.category_id" in sql
    assert "category_knowledge_entries.origin =" in sql
    assert "ANY (category_knowledge_entries.regions)" in sql
    assert "category_knowledge_current.status =" in sql
    assert "current_entry_id = category_knowledge_entries.id" not in sql
    assert result["items"] == []


def test_competitor_promotion_has_valid_content_without_source_backlinks():
    metric = {
        "parameter_id": str(uuid4()),
        "parameter_version": 1,
        "value": "12.1",
        "unit": "psi",
        "nature": "inferred",
    }
    payload = KnowledgePromote(
        source_proposal_id=uuid4(),
        source_proposal_revision=1,
        kind="competitor",
        deidentified_confirmed=True,
        content={
            "brand": "Generic",
            "model": "Portable",
            "metrics": [metric],
            "prices": [{"amount": "0.1"}],
        },
    )
    assert category_service._references(payload) == []
    assert check_content(payload.content)["hits"] == []
    linked = KnowledgeAdd(
        kind="competitor",
        content={
            "brand": "Generic",
            "model": "Portable",
            "metrics": [
                {
                    **metric,
                    "source_ref": {
                        "type": "snapshot",
                        "id": str(uuid4()),
                        "version": 1,
                        "line": 1,
                        "quote": "12.1",
                    },
                }
            ],
        },
    )
    assert len(category_service._references(linked)) == 1
    assert check_content(linked.content)["refs_clean"] is False


def test_competitor_filters_share_one_observation_and_precede_pagination(monkeypatch):
    from sqlalchemy.dialects import postgresql

    queries = []
    monkeypatch.setattr(category_reads, "_scope", lambda *args: None)
    session = SimpleNamespace(
        execute=lambda q: queries.append(q) or SimpleNamespace(all=lambda: [])
    )
    ctx = SimpleNamespace(tenant_id=uuid4(), category_id=uuid4())
    identity = uuid4()
    category_reads.competitors(
        session, ctx, parameter_ids=[identity], brand="Example", nature="claimed", page_size=2
    )
    query = queries[0].compile(dialect=postgresql.dialect())
    sql = str(query)
    assert sql.index("EXISTS") < sql.index("LIMIT")
    assert sql.count("jsonb_array_elements") == 1
    assert "observation.value" in sql
    assert "current_entry_id = category_knowledge_entries.id" in sql
    assert "active" in query.params.values()
    assert "Example" in query.params.values() and "claimed" in query.params.values()
    assert [str(identity)] in query.params.values()
    assert [] in query.params.values()  # No invented observation when a group is absent.
    assert 3 in query.params.values()  # One lookahead row for the requested two-row page.


def test_competitor_groups_keep_versions_units_and_conditions_separate(monkeypatch):
    identity = str(uuid4())
    observations = [
        {
            "parameter_id": identity,
            "parameter_version": version,
            "unit": unit,
            "condition_note": condition,
            "nature": "claimed",
            "value": "12.5",
        }
        for version, unit, condition in [
            (1, "psi", None),
            (2, "psi", None),
            (1, "bar", None),
            (1, "psi", "cold"),
        ]
    ]
    content = {
        "brand": "Example",
        "model": "Pump",
        "metrics": observations,
        "features": [],
        "prices": [
            {"amount": "9.90", "currency": "USD", "includes_tax": None, "includes_shipping": False}
        ],
    }
    page = {"items": [{"content": content}], "next_cursor": "unchanged", "as_of": "watermark"}
    calls = []
    monkeypatch.setattr(category_reads, "knowledge", lambda *args, **kw: calls.append(kw) or page)
    result = category_reads.competitors(None, None, parameter_ids=[identity], nature="claimed")
    groups = result["items"][0]["comparison_groups"]
    assert len(groups) == 4
    assert result["items"][0]["content"]["prices"] == content["prices"]
    assert result["next_cursor"] == "unchanged"
    assert calls[0]["status"] == "active" and calls[0]["include_history"] is False
