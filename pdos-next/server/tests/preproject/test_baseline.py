"""Publication baseline policy/digest tests; no database fixtures are used."""

from copy import deepcopy
from decimal import Decimal, localcontext
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.domain.preproject import baseline
from pdos_next.errors import DomainError

REAL_VALIDATE_SOURCES = baseline.validate_sources

TENANT, CATEGORY, PRODUCT, DEFINITION, ACTOR, RECEIPT, VARIANT = (UUID(int=i) for i in range(1, 8))


def ref(number=20):
    return {
        "artifact_id": str(UUID(int=number)),
        "expected_revision": 1,
        "line": 1,
        "quote": "Fixed source quote",
        "title": "Current display name",
        "status": "active",
        "spec_keys": ["pressure"],
    }


def spec(**changes):
    return {
        "key": "pressure",
        "parameter": "Pressure",
        "value_type": "number",
        "availability": "known",
        "value": "1234567890123456789012345.123456789012",
        "unit": "psi",
        "reason": "Fixed parent value",
        "test_conditions": ["25C", "nominal"],
        "sources": [{k: v for k, v in ref().items() if k not in {"title", "status", "spec_keys"}}],
        "parameter_id": str(UUID(int=21)),
        "parameter_version": 2,
        "item_status": "confirmed",
        "condition_note": "Calibrated",
        "source_refs": [
            {
                "type": "claim",
                "id": str(UUID(int=22)),
                "version": 3,
                "statement": "Fixed claim",
            }
        ],
        "origin": "ai_draft",
        "writer_id": str(UUID(int=23)),
        "run_id": str(UUID(int=24)),
        "confirmed_by": str(ACTOR),
        "receipt_id": str(UUID(int=25)),
        **changes,
    }


def view(**changes):
    return {
        "id": str(DEFINITION),
        "category_id": str(CATEGORY),
        "product_id": str(PRODUCT),
        "variant_id": None,
        "revision": 1,
        "owner_id": str(ACTOR),
        "title": "Fixed title",
        "purpose": "Fixed purpose",
        "visibility": "private",
        "status": "published",
        "sealed": True,
        "publication_receipt_id": str(RECEIPT),
        "use_cases": ["Fixed use"],
        "requirements": [],
        "constraints": [],
        "unknowns": [],
        "exclusions": [],
        "change_reason": "Initial scope",
        "created_at": "2026-10-10T00:00:00+00:00",
        "sources": [ref()],
        "specs": [spec()],
        "source_status": "current",
        **changes,
    }


class Session:
    """Only public scalar/scalars reads; writes or privileged calls are impossible."""

    def __init__(self, rows):
        self.rows, self.queries = rows, []

    def scalar(self, query):
        self.queries.append(query)
        return self.rows.pop(0)

    def scalars(self, query):
        self.queries.append(query)
        return self.rows.pop(0)


@pytest.fixture
def fixture(monkeypatch):
    from pdos_next import service

    ctx = NS(
        tenant_id=TENANT,
        category_id=CATEGORY,
        actor_id=ACTOR,
        requester_id=ACTOR,
        run_id=None,
        agent_run_id=None,
    )
    product = NS(id=PRODUCT, tenant_id=TENANT, category_id=CATEGORY)
    variant = NS(id=VARIANT, tenant_id=TENANT, category_id=CATEGORY, product_id=PRODUCT)
    definition = NS(
        id=DEFINITION,
        tenant_id=TENANT,
        category_id=CATEGORY,
        product_id=PRODUCT,
        variant_id=None,
        revision=1,
        status="published",
        sealed=True,
        publication_receipt_id=RECEIPT,
        g0_decision_id=None,
    )
    signer = NS(id=ACTOR, tenant_id=TENANT, kind="human", active=True)
    document = view()
    receipt = NS(
        id=RECEIPT,
        tenant_id=TENANT,
        category_id=CATEGORY,
        product_id=PRODUCT,
        operation="product.definition.publish",
        subject_type="definition_revision",
        subject_id=DEFINITION,
        subject_revision=1,
        actor_id=ACTOR,
        requester_id=ACTOR,
        run_id=None,
        agent_run_id=None,
        result={"definition_digest": baseline.publication_digest(document)},
    )
    # Receipt tests isolate source resolution; dedicated traversal tests below use it.
    monkeypatch.setattr(baseline, "validate_sources", lambda *args, **kwargs: ())
    monkeypatch.setattr(baseline, "read_blocks", lambda *args: {})
    from pdos_next.domain.products import platforms

    monkeypatch.setattr(platforms, "read", lambda *args, **kw: {"items": [], "next_cursor": None})
    accesses = []
    monkeypatch.setattr(service, "require_access", lambda *args, **kw: accesses.append(args[2]))
    monkeypatch.setattr(baseline, "definition_view", lambda *args: deepcopy(document))
    return NS(
        ctx=ctx,
        product=product,
        variant=variant,
        definition=definition,
        signer=signer,
        document=document,
        receipt=receipt,
        accesses=accesses,
    )


def session(f):
    return Session([f.product, f.definition, f.receipt, f.signer])


def assert_unpublished(f, s=None):
    with pytest.raises(DomainError) as error:
        baseline.published_baseline(s or session(f), f.ctx, PRODUCT, 1, DEFINITION)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert error.value.detail["reason"] == "baseline_not_published"


def test_digest_preserves_decimal_precision_and_uuid_representation():
    raw, equivalent = view(), view()
    equivalent["id"] = DEFINITION
    equivalent["product_id"] = PRODUCT
    equivalent["specs"][0]["value"] = Decimal(raw["specs"][0]["value"])
    before = deepcopy(raw)
    with localcontext() as context:
        context.prec = 3
        first = baseline.publication_digest(raw)
        assert first == baseline.publication_digest(equivalent)
    assert baseline.publication_document(raw)["specs"][0]["value"] == raw["specs"][0]["value"]
    assert raw == before


def test_source_labels_statuses_ui_and_publication_pointer_are_not_fixed_content():
    original, changed = view(), view()
    changed.update(
        status="draft",
        sealed=False,
        publication_receipt_id=None,
        source_status="needs_recheck",
        differences=["dynamic"],
        baseline_kind="draft",
    )
    changed["sources"][0].update(title="Renamed file", status="stale", label="UI only")
    changed["specs"][0]["sources"][0].update(title="Dynamic source title", status="active")
    assert baseline.publication_digest(changed) == baseline.publication_digest(original)
    changed["title"] = "Different immutable definition title"
    assert baseline.publication_digest(changed) != baseline.publication_digest(original)


@pytest.mark.parametrize(
    "field,value",
    [
        ("parameter_version", 3),
        ("item_status", "expert_pending"),
        ("condition_note", "0C"),
        ("origin", "human"),
        ("writer_id", str(UUID(int=80))),
        ("run_id", str(UUID(int=81))),
        ("confirmed_by", str(UUID(int=82))),
        ("receipt_id", str(UUID(int=83))),
        ("exceptions", [{"scope": "indoor"}]),
        ("applicable_variants", [{"region": "US"}]),
    ],
)
def test_digest_binds_complete_m3_spec_semantics(field, value):
    original, changed = view(), view(specs=[spec(**{field: value})])
    assert baseline.publication_digest(original) != baseline.publication_digest(changed)


def test_digest_binds_fixed_source_ids_versions_quotes_and_spec_relations():
    for change in (
        {"artifact_id": str(UUID(int=99))},
        {"expected_revision": 2},
        {"quote": "Changed quote"},
        {"spec_keys": ["other"]},
    ):
        changed = view()
        changed["sources"][0].update(change)
        assert baseline.publication_digest(changed) != baseline.publication_digest(view())


def test_digest_ignores_collection_order_and_decimal_scale():
    original = view(
        sources=[ref(), ref(26)], specs=[spec(value="150.0"), spec(key="other", value="160")]
    )
    reordered = deepcopy(original)
    reordered["sources"].reverse()
    reordered["specs"].reverse()
    reordered["specs"][1]["value"] = Decimal("1.50E+2")
    reordered["specs"][1]["test_conditions"].reverse()
    assert baseline.publication_digest(reordered) == baseline.publication_digest(original)


def test_unknown_spec_field_cannot_escape_digest():
    with pytest.raises(ValueError):
        baseline.publication_digest(view(specs=[spec(unknown_business_field="lost")]))


def test_published_baseline_reads_exact_scope_and_receipt(fixture):
    f = fixture
    s = session(f)
    result = baseline.published_baseline(s, f.ctx, PRODUCT, 1, DEFINITION)
    assert result["baseline_kind"] == "published"
    assert result["publication"]["definition_digest"] == f.receipt.result["definition_digest"]
    assert result["publication"]["synthetic"] is False
    assert f.accesses == [PRODUCT]
    for query in s.queries:
        sql = str(query.compile(dialect=postgresql.dialect()))
        assert "tenant_id" in sql and "FOR UPDATE" not in sql
    assert "variant_id IS NULL" in str(s.queries[1])


def test_synthetic_publication_stays_explicit(fixture):
    f = fixture
    f.receipt.result["synthetic"] = True
    result = baseline.published_baseline(session(f), f.ctx, PRODUCT, 1)
    assert result["publication"]["synthetic"] is True


def test_current_caller_and_historical_signer_need_not_be_same_human(fixture):
    f = fixture
    f.ctx.actor_id = f.ctx.requester_id = UUID(int=70)
    f.signer.active = False
    result = baseline.published_baseline(session(f), f.ctx, PRODUCT, 1)
    assert result["baseline_kind"] == "published"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", UUID(int=90)),
        ("category_id", UUID(int=90)),
        ("product_id", UUID(int=90)),
        ("variant_id", VARIANT),
        ("status", "draft"),
        ("sealed", False),
        ("publication_receipt_id", None),
    ],
)
def test_unpublished_or_wrong_scope_definition_never_becomes_baseline(fixture, field, value):
    f = fixture
    setattr(f.definition, field, value)
    assert_unpublished(f)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", UUID(int=90)),
        ("category_id", UUID(int=90)),
        ("product_id", UUID(int=90)),
        ("operation", "proposal.g0.decide"),
        ("subject_type", "proposal_decision"),
        ("subject_id", UUID(int=90)),
        ("subject_revision", 2),
        ("actor_id", UUID(int=90)),
        ("requester_id", UUID(int=90)),
        ("run_id", UUID(int=90)),
        ("agent_run_id", UUID(int=90)),
        ("result", {}),
        ("result", {"definition_digest": "0" * 64}),
    ],
)
def test_invalid_receipt_is_not_publication(fixture, field, value):
    f = fixture
    setattr(f.receipt, field, value)
    assert_unpublished(f)


@pytest.mark.parametrize("field,value", [("kind", "agent"), ("tenant_id", UUID(int=90))])
def test_publication_signer_must_be_same_tenant_human(fixture, field, value):
    f = fixture
    setattr(f.signer, field, value)
    assert_unpublished(f)


@pytest.mark.parametrize("position", [0, 1, 2, 3])
def test_rls_hidden_rows_are_unavailable(fixture, position):
    f = fixture
    rows = [f.product, f.definition, f.receipt, f.signer]
    rows[position] = None
    assert_unpublished(f, Session(rows))


def test_version_mismatch_is_explicit_conflict(fixture):
    f = fixture
    with pytest.raises(DomainError) as error:
        baseline.published_baseline(session(f), f.ctx, PRODUCT, 2, DEFINITION)
    assert error.value.code == "VERSION_CONFLICT"
    assert error.value.detail["reason"] == "baseline_version_changed"


def test_variant_baseline_requires_visible_matching_variant(fixture):
    f = fixture
    f.definition.variant_id = VARIANT
    f.document["variant_id"] = str(VARIANT)
    f.receipt.result["definition_digest"] = baseline.publication_digest(f.document)
    result = baseline.published_baseline(
        Session([f.product, f.variant, f.definition, f.receipt, f.signer]),
        f.ctx,
        PRODUCT,
        1,
        DEFINITION,
        VARIANT,
    )
    assert result["variant_id"] == str(VARIANT)
    with pytest.raises(DomainError):
        baseline.published_baseline(
            Session([f.product, None]), f.ctx, PRODUCT, 1, DEFINITION, VARIANT
        )


def test_source_read_guard_failure_is_preserved(fixture, monkeypatch):
    f = fixture

    def denied(*args):
        raise DomainError("SOURCE_UNAVAILABLE", "Source audience revoked", 403)

    monkeypatch.setattr(baseline, "definition_view", denied)
    with pytest.raises(DomainError) as error:
        baseline.published_baseline(session(f), f.ctx, PRODUCT, 1)
    assert error.value.status == 403
    assert error.value.message == "Source audience revoked"


def test_digest_mismatch_after_content_change_is_unavailable(fixture):
    f = fixture
    f.document["specs"][0]["source_refs"][0]["version"] = 99
    assert_unpublished(f)


def test_read_prefers_publication_over_later_draft_and_g0(fixture, monkeypatch):
    f = fixture
    g0 = NS(
        **{
            **vars(f.definition),
            "id": UUID(int=11),
            "status": "draft",
            "g0_decision_id": UUID(int=10),
        }
    )
    draft = NS(**{**vars(g0), "id": UUID(int=12), "revision": 3, "sealed": False})
    s = Session([f.product, [draft, g0, f.definition], f.receipt, f.signer])
    result = baseline.read_baseline(s, f.ctx, PRODUCT)
    assert result["baseline_kind"] == "published" and result["derivation_eligible"]
    assert set(result["unavailable_blocks"]) == {"bom", "certification", "tooling", "platform"}
    assert all(
        block["items"] == [] and block["status"] == "unknown" for block in result["blocks"].values()
    )


def test_g0_fallback_is_not_a_published_baseline(fixture):
    f = fixture
    f.definition.status = "draft"
    f.definition.g0_decision_id = UUID(int=10)
    result = baseline.read_baseline(Session([f.product, [f.definition]]), f.ctx, PRODUCT)
    assert result["baseline_kind"] == "g0" and not result["derivation_eligible"]
    assert_unpublished(f)


def test_draft_and_empty_fallbacks_are_explicit(fixture):
    f = fixture
    f.definition.status, f.definition.sealed = "draft", False
    result = baseline.read_baseline(Session([f.product, [f.definition]]), f.ctx, PRODUCT)
    assert result["baseline_kind"] == "draft" and not result["derivation_eligible"]
    result = baseline.read_baseline(Session([f.product, []]), f.ctx, PRODUCT)
    assert result["definition"] is None and result["baseline_kind"] == "unavailable"


def test_unreadable_definition_is_not_returned_by_fallback(fixture, monkeypatch):
    f = fixture
    f.definition.status, f.definition.sealed = "draft", False

    def denied(*args):
        raise DomainError("SOURCE_UNAVAILABLE", "Hidden source", 403)

    monkeypatch.setattr(baseline, "definition_view", denied)
    result = baseline.read_baseline(Session([f.product, [f.definition]]), f.ctx, PRODUCT)
    assert result["definition"] is None and result["unavailable_definition_count"] == 1


def test_source_tree_uses_one_union_lock_and_actual_products(monkeypatch):
    from pdos_next.domain.preproject import claim_access, root_sources
    from pdos_next.domain.preproject import service as proposals

    child_id, child_product = UUID(int=90), UUID(int=91)
    root = view()
    root["source_refs"] = [{"type": "definition", "id": str(child_id), "version": 4}]
    child = view()
    child.update(
        id=str(child_id),
        product_id=str(child_product),
        revision=4,
        sources=[ref(30)],
        specs=[],
        source_refs=[
            {"type": "claim", "id": str(UUID(int=10)), "version": 1},
            {"type": "snapshot", "id": str(UUID(int=31)), "version": 1},
            {"type": "human", "id": str(ACTOR), "version": 1, "statement": "Named"},
            {"type": "knowledge", "id": str(UUID(int=32)), "version": 2},
        ],
    )
    calls = []

    def lock(s, ctx, refs, **kwargs):
        ids = {r.id for r in refs if r.type == "claim"}
        calls.append(("claims", ids))
        return {
            identity: NS(quote="Fixed claim", line=1, revision=3 if identity == UUID(int=22) else 1)
            for identity in ids
        }

    monkeypatch.setattr(root_sources, "lock_claim_refs", lock)
    monkeypatch.setattr(baseline, "definition_view", lambda *args: child)
    monkeypatch.setattr(
        claim_access,
        "load_source",
        lambda s, ctx, r, **kw: calls.append(("artifact", r.id, kw["product_id"])),
    )
    monkeypatch.setattr(
        proposals,
        "_references",
        lambda s, ctx, refs, **kw: calls.extend((r.type, r.id) for r in refs),
    )
    ctx = NS(tenant_id=TENANT, category_id=CATEGORY)
    row = NS(tenant_id=TENANT, category_id=CATEGORY, revision=4)
    knowledge = NS(
        tenant_id=TENANT,
        category_id=CATEGORY,
        version=2,
        action="add",
        source_refs=[],
        kind="boundary",
        content={"definition": "Fixed boundary"},
    )
    source = NS(id=UUID(int=20), product_id=PRODUCT)
    child_source = NS(id=UUID(int=30), product_id=child_product)
    s = Session([row, knowledge, source, child_source, source])
    baseline.validate_sources(s, ctx, root)
    assert not s.rows
    assert calls[0] == ("claims", {UUID(int=10), UUID(int=22)})
    assert sum(call[0] == "claims" for call in calls) == 1
    assert ("artifact", UUID(int=20), PRODUCT) in calls
    assert ("artifact", UUID(int=30), child_product) in calls
    for kind in ("human", "snapshot", "knowledge", "parameter"):
        assert any(call[0] == kind for call in calls)


def test_definition_source_cycle_rejected_before_claim_locks(monkeypatch):
    from pdos_next.domain.preproject import root_sources

    doc = view()
    doc.update(
        sources=[],
        specs=[],
        source_refs=[{"type": "definition", "id": str(DEFINITION), "version": 1}],
    )
    monkeypatch.setattr(baseline, "definition_view", lambda *args: doc)
    monkeypatch.setattr(
        root_sources, "lock_claim_refs", lambda *a, **kw: pytest.fail("lock before traversal")
    )
    row = NS(tenant_id=TENANT, category_id=CATEGORY, revision=1)
    with pytest.raises(DomainError) as error:
        baseline.validate_sources(Session([row]), NS(tenant_id=TENANT, category_id=CATEGORY), doc)
    assert error.value.detail["reason"] == "baseline_source_cycle"


def test_source_failure_blocks_derivation_without_falling_back(fixture, monkeypatch):
    def stale(*args, **kwargs):
        if kwargs.get("history_permissions"):
            return ()
        baseline.fail("SOURCE_STALE", "claim_withdrawn", "Withdrawn")

    monkeypatch.setattr(baseline, "validate_sources", stale)
    with pytest.raises(DomainError) as error:
        baseline.published_baseline(session(fixture), fixture.ctx, PRODUCT, 1)
    assert error.value.code == "SOURCE_STALE"
    s = Session([fixture.product, [fixture.definition], fixture.receipt, fixture.signer])
    result = baseline.read_baseline(s, fixture.ctx, PRODUCT)
    assert result["baseline_kind"] == "published"
    assert result["definition"]["id"] == str(DEFINITION)
    assert result["derivation_eligible"] is False
    assert result["source_issues"] == [{"code": "SOURCE_STALE", "reason": "claim_withdrawn"}]


def test_read_exact_revision_filters_query_and_keeps_draft(fixture):
    fixture.definition.status = "draft"
    fixture.definition.sealed = False
    s = Session([fixture.product, [fixture.definition]])
    result = baseline.read_baseline(s, fixture.ctx, PRODUCT, definition_revision=1)
    assert result["baseline_kind"] == "draft"
    assert result["derivation_eligible"] is False
    assert 1 in s.queries[1].compile().params.values()


@pytest.mark.parametrize("source_kind", ["artifact", "snapshot", "parameter", "knowledge"])
def test_real_traversal_propagates_resolver_rejection(monkeypatch, source_kind):
    from pdos_next.domain.preproject import claim_access, root_sources
    from pdos_next.domain.preproject import service as proposals

    doc = view()
    doc.update(
        sources=[],
        specs=[],
        source_refs=[
            {
                "type": source_kind,
                "id": str(UUID(int=80)),
                "version": 2,
                "line": 1,
                "quote": "Fixed",
            }
        ],
    )
    calls = []
    monkeypatch.setattr(root_sources, "lock_claim_refs", lambda *args, **kw: {})

    def reject(*args, **kwargs):
        calls.append(kwargs)
        baseline.fail("SOURCE_STALE", "test_source_stale", "Stale")

    monkeypatch.setattr(claim_access, "load_source", reject)
    monkeypatch.setattr(proposals, "_references", reject)
    with pytest.raises(DomainError) as error:
        rows = (
            [
                NS(
                    tenant_id=TENANT,
                    category_id=CATEGORY,
                    version=2,
                    action="add",
                    source_refs=[],
                    kind="boundary",
                    content={"definition": "Fixed boundary"},
                )
            ]
            if source_kind == "knowledge"
            else [NS(id=UUID(int=80), product_id=PRODUCT)]
            if source_kind == "artifact"
            else []
        )
        baseline.validate_sources(Session(rows), NS(tenant_id=TENANT, category_id=CATEGORY), doc)
    assert error.value.detail["reason"] == "test_source_stale"
    if source_kind == "artifact":
        assert calls == [{"product_id": PRODUCT, "lock": True}]
    else:
        assert calls == [{"approved": True}]


@pytest.mark.parametrize("read_snapshot", [False, True])
def test_tree_and_extra_claims_share_order_and_complete_frozen_consumption(
    monkeypatch, read_snapshot
):
    from pdos_next.domain.preproject import claim_access
    from pdos_next.domain.preproject.schemas import Reference

    child_id = UUID(int=90)
    root = view(
        sources=[ref()],
        specs=[],
        source_refs=[
            {"type": "claim", "id": str(UUID(int=30)), "version": 3},
            {"type": "definition", "id": str(child_id), "version": 4},
        ],
    )
    child = view(
        id=str(child_id),
        revision=4,
        sources=[],
        specs=[],
        source_refs=[
            {"type": "claim", "id": str(UUID(int=10)), "version": 1},
        ],
    )
    extra = [
        Reference(type="claim", id=UUID(int=20), version=2),
        Reference(type="claim", id=UUID(int=30), version=3),
    ]
    calls = []
    monkeypatch.setattr(baseline, "definition_view", lambda *args: child)

    def lock(s, ctx, identities):
        assert not read_snapshot, "read snapshots must never acquire Claim row locks"
        calls.append(("lock", identities))

    def resolve(s, ctx, identity, version, **kwargs):
        assert kwargs == (
            {"approved": True}
            if read_snapshot
            else {
                "approved": True,
                "source_lock": True,
            }
        )
        calls.append(("resolve", identity, version))
        return NS(revision=version, quote="Fixed claim", line=1)

    def source(s, ctx, reference, **kwargs):
        assert kwargs == {"product_id": PRODUCT, "lock": not read_snapshot}
        calls.append(("source", reference.id))

    monkeypatch.setattr(claim_access, "lock_references", lock)
    monkeypatch.setattr(claim_access, "resolve", resolve)
    monkeypatch.setattr(claim_access, "load_source", source)
    row = NS(tenant_id=TENANT, category_id=CATEGORY, revision=4)
    s = Session([row, NS(id=UUID(int=20), product_id=PRODUCT)])
    s.info = {"read_snapshot": read_snapshot}
    returned = baseline.validate_sources(
        s, NS(tenant_id=TENANT, category_id=CATEGORY), root, extra_refs=extra
    )
    identities = [UUID(int=10), UUID(int=20), UUID(int=30)]
    if not read_snapshot:
        assert calls.pop(0) == ("lock", identities)
    assert calls == [
        *(("resolve", identity, index) for index, identity in enumerate(identities, 1)),
        ("source", UUID(int=20)),
    ]
    assert [(ref.id, ref.version) for ref in returned] == list(
        zip(identities, (1, 2, 3), strict=True)
    )
    assert not s.rows


@pytest.mark.parametrize("ancestor_field", ["derived_from_definition_id", "parent_definition_id"])
def test_ancestor_knowledge_claim_closure_uses_actual_fixed_versions(monkeypatch, ancestor_field):
    from pdos_next.domain.preproject import root_sources
    from pdos_next.domain.preproject import service as proposals
    from pdos_next.domain.preproject.schemas import Reference

    ancestor_id, knowledge_id, claim_id = (UUID(int=i) for i in (90, 91, 92))
    root = view(sources=[], specs=[], **{ancestor_field: str(ancestor_id)})
    if ancestor_field == "derived_from_definition_id":
        root["derived_from_definition_revision"] = 7
    ancestor = view(
        id=str(ancestor_id),
        revision=7,
        sources=[],
        specs=[],
        source_refs=[{"type": "knowledge", "id": str(knowledge_id), "version": 3}],
    )
    claim_ref = Reference(type="claim", id=claim_id, version=4)
    knowledge = NS(
        tenant_id=TENANT,
        category_id=CATEGORY,
        version=3,
        action="supersede",
        kind="boundary",
        content={"definition": "Fixed boundary"},
        source_refs=[claim_ref.model_dump(mode="json")],
    )
    parent = NS(tenant_id=TENANT, category_id=CATEGORY, revision=7)
    calls = []
    monkeypatch.setattr(baseline, "definition_view", lambda *args: ancestor)
    monkeypatch.setattr(proposals, "_references", lambda *args, **kwargs: None)

    def lock(s, ctx, refs, **kwargs):
        calls.extend(refs)
        return {claim_id: NS(revision=4, quote="Fixed", line=1)}

    monkeypatch.setattr(root_sources, "lock_claim_refs", lock)
    returned = baseline.validate_sources(
        Session([parent, knowledge]), NS(tenant_id=TENANT, category_id=CATEGORY), root
    )
    assert returned == (claim_ref,)
    assert any(
        ref.type == "definition" and ref.id == ancestor_id and ref.version == 7 for ref in calls
    )
    assert claim_ref in calls


@pytest.mark.parametrize(
    "cycle_kind", ["knowledge", "parent_definition_id", "derived_from_definition_id"]
)
def test_ancestry_and_knowledge_cycles_fail_before_locks(monkeypatch, cycle_kind):
    from pdos_next.domain.preproject import root_sources

    root = view(sources=[], specs=[])
    if cycle_kind == "knowledge":
        ref = {"type": "knowledge", "id": str(UUID(int=91)), "version": 3}
        root["source_refs"] = [ref]
        rows = [
            NS(
                tenant_id=TENANT,
                category_id=CATEGORY,
                version=3,
                action="add",
                source_refs=[ref],
                kind="boundary",
                content={"definition": "Fixed boundary"},
            )
        ]
    else:
        root[cycle_kind] = str(DEFINITION)
        root["derived_from_definition_revision"] = 1
        rows = [NS(tenant_id=TENANT, category_id=CATEGORY, revision=1)]
        monkeypatch.setattr(baseline, "definition_view", lambda *args: root)
    monkeypatch.setattr(
        root_sources, "lock_claim_refs", lambda *a, **kw: pytest.fail("unexpected lock")
    )
    with pytest.raises(DomainError) as error:
        baseline.validate_sources(Session(rows), NS(tenant_id=TENANT, category_id=CATEGORY), root)
    assert error.value.detail["reason"] == "baseline_source_cycle"


@pytest.mark.parametrize("kind", ["published", "g0", "draft"])
@pytest.mark.parametrize("source_kind", ["claim", "artifact", "knowledge"])
def test_all_baseline_kinds_hide_unreadable_typed_spec_sources(
    fixture, monkeypatch, kind, source_kind
):
    from pdos_next.domain.preproject import claim_access

    source_ref = {"type": source_kind, "id": str(UUID(int=80)), "version": 1}
    fixture.document.update(
        sources=[],
        specs=[
            spec(sources=[], parameter_id=None, parameter_version=None, source_refs=[source_ref])
        ],
    )
    fixture.definition.status = "published" if kind == "published" else "draft"
    fixture.definition.sealed = kind != "draft"
    fixture.definition.g0_decision_id = UUID(int=99) if kind == "g0" else None
    fixture.receipt.result["definition_digest"] = baseline.publication_digest(fixture.document)
    monkeypatch.setattr(baseline, "validate_sources", REAL_VALIDATE_SOURCES)

    def denied(*args, **kwargs):
        baseline.fail("NOT_FOUND", "claim_not_found", "Not readable", 404)

    monkeypatch.setattr(claim_access, "resolve", denied)
    rows = [fixture.product, [fixture.definition]]
    if kind == "published":
        rows.extend([fixture.receipt, fixture.signer])
    if source_kind != "claim":
        rows.append(None)
    result = baseline.read_baseline(Session(rows), fixture.ctx, PRODUCT)
    assert result["definition"] is None
    assert result["baseline_kind"] == "unavailable"
    assert result["unavailable_definition_count"] == 1


def test_withdrawn_claim_history_is_preserved_only_after_body_access(fixture, monkeypatch):
    from pdos_next.domain.preproject import claim_access, root_sources

    identity = UUID(int=80)
    fixture.document.update(
        sources=[],
        specs=[
            spec(
                sources=[],
                parameter_id=None,
                parameter_version=None,
                source_refs=[
                    {
                        "type": "claim",
                        "id": str(identity),
                        "version": 1,
                        "quote": "Private quote",
                        "line": 1,
                        "statement": "Private statement",
                    }
                ],
            )
        ],
    )
    fixture.receipt.result["definition_digest"] = baseline.publication_digest(fixture.document)
    monkeypatch.setattr(baseline, "validate_sources", REAL_VALIDATE_SOURCES)
    claim = NS(
        revision=1,
        quote="Private quote",
        line=1,
        product_id=PRODUCT,
        source_kind="artifact",
        artifact_id=UUID(int=81),
        source_revision=1,
    )

    def history(s, ctx, identity, version, **kwargs):
        assert kwargs == {"allow_withdrawn": True}
        return claim

    def withdrawn(*args, **kwargs):
        baseline.fail("SOURCE_STALE", "claim_withdrawn", "Withdrawn")

    monkeypatch.setattr(claim_access, "resolve", history)
    monkeypatch.setattr(root_sources, "lock_claim_refs", withdrawn)
    artifact = NS(tenant_id=TENANT, category_id=CATEGORY, product_id=PRODUCT, original_id=None)
    result = baseline.read_baseline(
        Session(
            [
                fixture.product,
                [fixture.definition],
                fixture.receipt,
                fixture.signer,
                artifact,
            ]
        ),
        fixture.ctx,
        PRODUCT,
    )
    assert result["baseline_kind"] == "published"
    assert result["derivation_eligible"] is False
    assert result["source_issues"] == [{"code": "SOURCE_STALE", "reason": "claim_withdrawn"}]
    assert result["definition"]["specs"][0]["source_refs"] == [
        {"type": "claim", "id": str(identity), "version": 1}
    ]
    assert "Private quote" not in str(result)
    assert "Private statement" not in str(result)


def test_metadata_only_withdrawal_does_not_authorize_history(fixture, monkeypatch):
    def metadata_only(*args, **kwargs):
        assert kwargs.get("history_permissions") is True
        baseline.fail("SOURCE_STALE", "claim_withdrawn", "Body is no longer readable")

    monkeypatch.setattr(baseline, "validate_sources", metadata_only)
    result = baseline.read_baseline(
        Session(
            [
                fixture.product,
                [fixture.definition],
                fixture.receipt,
                fixture.signer,
            ]
        ),
        fixture.ctx,
        PRODUCT,
    )
    assert result["definition"] is None
    assert result["baseline_kind"] == "unavailable"


def test_unreadable_candidate_falls_back_to_older_readable_definition(fixture, monkeypatch):
    newer = NS(**vars(fixture.definition))
    newer.id, newer.revision, newer.status, newer.sealed = UUID(int=99), 2, "draft", False
    older = fixture.definition
    older.status, older.sealed, older.g0_decision_id = "draft", False, None
    visits = []
    monkeypatch.setattr(
        baseline, "definition_view", lambda s, ctx, row: view(id=str(row.id), revision=row.revision)
    )

    def validate(s, ctx, doc, **kwargs):
        visits.append((doc["revision"], kwargs.get("history_permissions", False)))
        if doc["revision"] == 2:
            baseline.fail("FORBIDDEN_SCOPE", "source_unreadable", "Revoked")
        return ()

    monkeypatch.setattr(baseline, "validate_sources", validate)
    result = baseline.read_baseline(
        Session([fixture.product, [newer, older]]), fixture.ctx, PRODUCT
    )
    assert result["definition"]["revision"] == 1
    assert result["unavailable_definition_count"] == 1
    assert visits == [(2, True), (1, True), (1, False)]
