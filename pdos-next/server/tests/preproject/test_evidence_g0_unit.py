"""Pinned G0 evidence, bottom-source counting and metadata-only withdrawal views."""

from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.preproject import category_service, claim_access, root_sources, service
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.errors import DomainError


class MemorySession:
    def __init__(self, rows=(), metadata=()):
        self.rows, self.metadata, self.added = list(rows), list(metadata), []

    def scalars(self, query):
        return self.rows

    def execute(self, query, parameters=None):
        return self.metadata

    def add(self, row):
        self.added.append(row)


@pytest.fixture
def ctx():
    return NS(tenant_id=uuid4(), category_id=uuid4(), requester_id=uuid4())


def ref(kind="claim", identity=None, version=1, **extra):
    return {"type": kind, "id": str(identity or uuid4()), "version": version, **extra}


def link(item_id, evidence_type="claim", **extra):
    return NS(
        **{
            "id": uuid4(),
            "target_type": "proposal_item",
            "target_id": item_id,
            "target_version": 1,
            "evidence_type": evidence_type,
            "evidence_id": uuid4(),
            "evidence_version": 1,
            "evidence_locator": "line:2",
            "relation": "supports",
            "reverted_by_receipt_id": None,
            **extra,
        }
    )


def frozen_link_doc(link_row):
    reference = ref(link_row.evidence_type, link_row.evidence_id)
    item = {
        "item_id": str(link_row.target_id),
        "version": link_row.target_version,
        "kind": "section",
        "content": {"text": "合成立项依据"},
        "direct_source_refs": [],
        "source_refs": [reference],
        "evidence_links": [
            {
                "id": str(link_row.id),
                "status": "active",
                "relation": link_row.relation,
                "evidence": {**reference, "locator": link_row.evidence_locator},
                "target": {
                    "type": "proposal_item",
                    "id": str(link_row.target_id),
                    "version": link_row.target_version,
                },
            }
        ],
    }
    return {
        "items": [item],
        "source_refs": [reference],
        "direct_source_refs": [],
        "context_refs": [],
    }


def test_claim_reference_is_pinned_but_does_not_accept_caller_privacy():
    body = ref()
    assert Reference.model_validate(body).type == "claim"
    with pytest.raises(ValidationError):
        Reference.model_validate({**body, "privacy": "shared"})


@pytest.mark.parametrize("status", [None, "withdrawn", "active"])
def test_approval_rechecks_only_artifact_status_before_complete_source_union(
    ctx, monkeypatch, status
):
    from pdos_next.domain.preproject import baseline

    identity = uuid4()
    document = {"source_refs": [ref("artifact", identity, line=1, quote="Fixed")], "items": []}
    calls, queries = [], []

    def scalar(query):
        queries.append(str(query))
        return status

    monkeypatch.setattr(baseline, "validate_references", lambda *a: calls.append("union"))
    monkeypatch.setattr(service, "_references", lambda *a, **kw: calls.append("direct"))
    monkeypatch.setattr(
        root_sources, "validate_document_links", lambda *a, **kw: calls.append("links")
    )
    if status == "active":
        service._check_document_references(NS(scalar=scalar), ctx, document, approved=True)
        assert calls == ["union", "direct", "links"]
    else:
        with pytest.raises(DomainError) as error:
            service._check_document_references(NS(scalar=scalar), ctx, document, approved=True)
        assert error.value.code == "SOURCE_STALE"
        assert error.value.detail["reason"] == "original_withdrawn"
        assert calls == []
    assert len(queries) == 1
    assert queries[0].startswith("SELECT artifact_versions.status")
    assert "artifact_versions.content" not in queries[0]


def test_claim_lock_order_is_uuid_order_and_keeps_approval_revalidation(ctx, monkeypatch):
    low, high = UUID(int=2), UUID(int=10)
    calls, locks = [], []

    def resolve(s, scope, identity, version, **flags):
        calls.append((identity, version, flags))
        return NS(id=identity)

    monkeypatch.setattr(claim_access, "resolve", resolve)
    monkeypatch.setattr(
        claim_access, "lock_references", lambda s, scope, identities: locks.append(identities)
    )
    root_sources.lock_claim_refs(
        MemorySession(),
        ctx,
        [
            Reference.model_validate(ref(identity=high)),
            Reference.model_validate(ref(identity=low)),
            Reference.model_validate(ref(identity=high)),
        ],
        approved=True,
    )
    assert [call[0] for call in calls] == [low, high]
    assert locks == [[low, high]]
    assert all(call[2] == {"approved": True, "source_lock": True} for call in calls)


def test_bottom_sources_count_actual_sources_and_preserve_reference_multiplicity(ctx, monkeypatch):
    active, withdrawn, snapshot = uuid4(), uuid4(), uuid4()
    rows = [
        NS(id=active, revision=1, status="active"),
        NS(id=withdrawn, revision=2, status="withdrawn"),
    ]
    monkeypatch.setattr(
        claim_access,
        "source_reference",
        lambda row: Reference(type="snapshot", id=snapshot, version=1, line=2, quote="原文"),
    )
    monkeypatch.setattr(claim_access, "source_privacy", lambda *a: "shared")
    refs = [
        Reference.model_validate(ref(identity=identity)) for identity in (active, withdrawn, active)
    ]
    roots, privacy = root_sources.roots(MemorySession(rows), ctx, refs, {})
    assert [(r.type, r.id) for r in roots] == [("snapshot", snapshot), ("snapshot", snapshot)]
    assert service._source_counts(roots) == {("snapshot", snapshot, 1): 2}
    assert set(privacy.values()) == {"shared"}


def test_removing_one_item_claim_keeps_another_reference_to_same_source(ctx, monkeypatch):
    identity, snapshot = uuid4(), uuid4()
    monkeypatch.setattr(
        claim_access,
        "source_reference",
        lambda row: Reference(type="snapshot", id=snapshot, version=1),
    )
    monkeypatch.setattr(claim_access, "source_privacy", lambda *a: "shared")
    session = MemorySession([NS(id=identity, revision=1, status="active")])
    pointer = NS(ref_count=2, privacy="shared")
    session.scalar = lambda query: pointer
    session.flush = lambda: None
    owner = NS(id=uuid4(), private_source_count=0, visibility="private")
    service._sources(
        session,
        ctx,
        owner,
        [],
        [Reference.model_validate(ref(identity=identity))],
        reference_privacy={},
    )
    assert pointer.ref_count == 1 and owner.private_source_count == 0


def test_submitted_old_knowledge_remains_valid_after_background_withdrawal(ctx):
    from pdos_next.domain.preproject.category_models import KnowledgeEntry

    identity, lineage = uuid4(), uuid4()
    fixed = NS(category_id=ctx.category_id, lineage_id=lineage, version=1, action="add")
    current = NS(current_version=2, status="withdrawn")
    session = MemorySession()
    session.get = lambda model, key: fixed if model is KnowledgeEntry else current
    refs = [Reference.model_validate(ref("knowledge", identity))]
    assert service._references(session, ctx, refs, approved=True)[0][1] == "shared"
    with pytest.raises(DomainError) as error:
        service._references(session, ctx, refs)
    assert error.value.detail["reason"] == "knowledge_unreadable"


def test_claim_reference_checks_source_even_during_draft_creation(ctx, monkeypatch):
    identity = uuid4()
    flags = []

    def resolve(s, scope, key, version, **options):
        flags.append(options)
        return NS(id=key, quote="逐字来源", line=2)

    monkeypatch.setattr(claim_access, "resolve", resolve)
    monkeypatch.setattr(claim_access, "source_privacy", lambda *a: "shared")
    result = service._references(
        MemorySession(), ctx, [Reference.model_validate(ref(identity=identity))]
    )
    assert result[0][1] == "shared" and flags[0]["approved"] is True
    with pytest.raises(DomainError) as error:
        service._references(
            MemorySession(), ctx, [Reference.model_validate(ref(identity=identity, quote="编造"))]
        )
    assert error.value.detail["reason"] == "quote_not_in_source"


def test_item_projection_adds_live_links_and_only_metadata_for_withdrawn_claims(ctx):
    item_id = uuid4()
    active = link(item_id)
    withdrawn = link(item_id, reverted_by_receipt_id=uuid4())
    historical = link(item_id, target_version=99)
    item = {
        "item_id": str(item_id),
        "version": 1,
        "content": {"value": "42"},
        "source_refs": [],
        "origin": "human",
        "writer_id": str(uuid4()),
    }
    before = deepcopy(item)
    session = MemorySession(
        [active, withdrawn, historical],
        [
            (active.evidence_id, 1, "active"),
            (withdrawn.evidence_id, 2, "withdrawn"),
        ],
    )
    projected = root_sources.project_items(session, ctx, [item])[0]
    assert item == before
    assert (
        projected["content"] == before["content"] and projected["writer_id"] == before["writer_id"]
    )
    assert projected["source_refs"] == [ref(identity=active.evidence_id)]
    assert {r["id"] for r in projected["evidence_links"]} == {str(active.id), str(withdrawn.id)}
    assert projected["source_changes"] == [
        {
            **ref(identity=withdrawn.evidence_id),
            "current_version": 2,
            "status": "withdrawn",
        }
    ]


def test_withdrawal_projection_never_reexposes_embedded_quote_or_statement():
    identity = uuid4()
    reference = ref(
        identity=identity, quote="历史客户原话", statement="历史身份", content={"text": "秘密"}
    )
    original = {
        "source_refs": [reference],
        "source_changes": [
            {
                **ref(identity=identity),
                "current_version": 2,
                "status": "withdrawn",
            }
        ],
    }
    result = root_sources.redact_references(original, {str(identity): (2, "withdrawn")})
    assert result["source_refs"] == [ref(identity=identity)]
    assert result["source_changes"][0]["status"] == "withdrawn"
    assert original["source_refs"][0]["quote"] == "历史客户原话"


@pytest.mark.parametrize("locator", [None, "line:1", "line:2", "lines:1:2", "chars:0:2"])
def test_real_text_locators_accept_complete_document_or_actual_ranges(locator):
    root_sources.validate_locator(locator, "第一行\n第二行")


@pytest.mark.parametrize(
    "locator",
    ["line:0", "line:3", "lines:2:1", "chars:-1:2", "chars:0:99", "chars:2:2", "unknown:1"],
)
def test_locator_cannot_claim_text_outside_source(locator):
    with pytest.raises(DomainError) as error:
        root_sources.validate_locator(locator, "第一行\n第二行")
    assert error.value.detail["reason"] == "source_locator_invalid"


def test_frozen_artifact_link_rechecks_stored_identity_and_locator_without_quote(ctx, monkeypatch):
    from pdos_next.domain.preproject import evidence_service

    row = link(uuid4(), evidence_type="artifact")
    doc = frozen_link_doc(row)
    observed = []
    monkeypatch.setattr(
        evidence_service,
        "_source",
        lambda s, c, r: (observed.append(r) or NS(), "shared", NS(content="一\n二")),
    )
    assert root_sources.ordinary_refs(doc) == []
    result = root_sources.validate_document_links(MemorySession([row]), ctx, doc, approved=True)
    assert len(result) == 1 and observed[0].id == row.evidence_id
    assert result[0].quote is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_version", 2),
        ("target_version", 2),
        ("evidence_locator", "line:1"),
        ("reverted_by_receipt_id", uuid4()),
    ],
)
def test_changed_or_reverted_link_cannot_approve_frozen_document(ctx, field, value):
    row = link(uuid4(), evidence_type="artifact")
    doc = frozen_link_doc(row)
    setattr(row, field, value)
    with pytest.raises(DomainError) as error:
        root_sources.validate_document_links(MemorySession([row]), ctx, doc, approved=True)
    assert error.value.detail["reason"] in {"evidence_link_reverted", "evidence_link_changed"}


def test_document_recheck_separates_plain_references_from_link_metadata(ctx, monkeypatch):
    from pdos_next.domain.preproject import baseline

    row = link(uuid4(), evidence_type="artifact")
    doc = frozen_link_doc(row)
    calls = []

    def tree(session, actual_ctx, refs):
        assert actual_ctx is ctx
        assert [(ref.type, ref.id, ref.version) for ref in refs] == [
            ("artifact", row.evidence_id, row.evidence_version)
        ]
        calls.append("tree")

    monkeypatch.setattr(baseline, "validate_references", tree)
    monkeypatch.setattr(service, "_references", lambda s, c, refs, **kw: calls.append(refs))
    monkeypatch.setattr(
        root_sources, "validate_document_links", lambda *a, **kw: calls.append("link")
    )
    def artifact_status(query):
        assert str(query).startswith("SELECT artifact_versions.status")
        assert row.evidence_id in query.compile().params.values()
        return "active"

    service._check_document_references(NS(scalar=artifact_status), ctx, doc, approved=True)
    assert calls == ["tree", [], "link"]


def test_approved_decision_consumes_deduplicated_pinned_claims_with_real_foreign_keys(
    ctx, monkeypatch
):
    identity = uuid4()
    claim = NS(id=identity, revision=3)
    monkeypatch.setattr(root_sources, "lock_claim_refs", lambda *a, **kw: {identity: claim})
    decision = NS(
        id=uuid4(),
        outcome="approved",
        created_product_id=uuid4(),
        created_definition_id=uuid4(),
        receipt_id=uuid4(),
    )
    session = MemorySession()
    root_sources.consume_claims(
        session, ctx, [Reference.model_validate(ref(identity=identity, version=3))], decision
    )
    assert len(session.added) == 1
    consumption = session.added[0]
    assert (consumption.claim_id, consumption.claim_version) == (identity, 3)
    assert consumption.decision_id == decision.id
    assert consumption.definition_id == decision.created_definition_id
    assert consumption.receipt_id == decision.receipt_id
    assert consumption.product_id == decision.created_product_id


def test_submission_or_return_is_not_a_signed_claim_consumption(ctx, monkeypatch):
    monkeypatch.setattr(root_sources, "lock_claim_refs", lambda *a, **kw: {})
    session = MemorySession()
    with pytest.raises(DomainError) as error:
        root_sources.consume_claims(
            session, ctx, [], NS(outcome="returned", created_definition_id=None)
        )
    assert error.value.detail["reason"] == "unsigned_consumption" and session.added == []


@pytest.mark.parametrize(
    "claim_privacy,source_privacy", [("private", "shared"), ("shared", "private")]
)
def test_knowledge_rejects_private_claim_or_private_underlying_source(
    ctx, monkeypatch, claim_privacy, source_privacy
):
    monkeypatch.setattr(claim_access, "resolve", lambda *a, **kw: NS(privacy=claim_privacy))
    monkeypatch.setattr(claim_access, "source_privacy", lambda *a: source_privacy)
    with pytest.raises(DomainError) as error:
        category_service.check_shared_sources(
            MemorySession(), ctx, [Reference.model_validate(ref())]
        )
    assert error.value.detail["reason"] == "private_source_in_shared"


def test_knowledge_projection_marks_withdrawn_claim_without_changing_material(ctx):
    identity, entry_id = uuid4(), uuid4()
    entry = {
        "id": str(entry_id),
        "version": 1,
        "content": {"definition": "业务值保留"},
        "source_refs": [ref(identity=identity, quote="撤回的历史原话")],
    }
    before = deepcopy(entry)
    result = root_sources.project_knowledge(
        MemorySession(metadata=[(identity, 2, "withdrawn")]), ctx, [entry]
    )[0]
    assert entry == before and result["content"] == entry["content"]
    assert result["source_refs"] == [ref(identity=identity)]
    assert result["source_changes"][0]["status"] == "withdrawn"
