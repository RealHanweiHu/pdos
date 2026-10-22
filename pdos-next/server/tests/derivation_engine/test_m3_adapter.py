"""Pure M3/legacy adapter tests: no app, sessions, database or model calls."""

from copy import deepcopy
from decimal import Decimal, localcontext
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from pdos_next.domain.products import variants
from pdos_next.schemas.products.derivation import (
    AdoptionSelection,
    ApplicabilityScope,
    DerivationRequest,
    ObjectReference,
    ReuseAssessment,
    SpecSnapshot,
)
from pdos_next.schemas.products.variants import RebaseChoice


def object_ref(kind="claim", number=30):
    return {
        "type": kind,
        "id": str(UUID(int=number)),
        "version": 2,
        "statement": "Fixed source",
        "line": None,
        "quote": None,
    }


def m3_spec(**changes):
    return {
        "key": "pressure",
        "parameter": "Rated pressure",
        "value_type": "number",
        "availability": "known",
        "value": "150.000000000001",
        "lower": None,
        "upper": None,
        "text": None,
        "unit": "psi",
        "tolerance": "0.01",
        "test_conditions": [],
        "condition_note": "25 °C; fixed hose",
        "method": "Calibrated gauge",
        "acceptance_criterion": "Within tolerance",
        "nature": "decided",
        "state": "proposed",
        "owner_id": str(UUID(int=20)),
        "reason": "Fixed proposal specification",
        "parameter_id": str(UUID(int=40)),
        "parameter_version": 3,
        "item_status": "confirmed",
        "modality": "must",
        "exceptions": [{"market": "US", "condition": "indoor"}],
        "applicable_variants": [{"variant_id": str(UUID(int=50)), "scope": "US"}],
        "source_refs": [object_ref()],
        "sources": [],
        "origin": "ai_draft",
        "writer_id": str(UUID(int=21)),
        "run_id": str(UUID(int=22)),
        "confirmed_by": str(UUID(int=23)),
        "receipt_id": str(UUID(int=24)),
        **changes,
    }


def view(number=1, revision=1, **changes):
    return {
        "id": str(UUID(int=number)),
        "category_id": str(UUID(int=100)),
        "product_id": str(UUID(int=101)),
        "revision": revision,
        "title": "Parent definition",
        "status": "draft",
        "owner_id": str(UUID(int=20)),
        "purpose": "Pressure regulation",
        "use_cases": [],
        "requirements": [],
        "constraints": [],
        "unknowns": [],
        "exclusions": [],
        "sources": [],
        "source_refs": [object_ref()],
        "specs": [m3_spec()],
        **changes,
    }


def request(new_spec=None):
    old = variants.snapshot_from_definition(view())
    return DerivationRequest(
        old_parent=old,
        new_parent=variants.snapshot_from_definition(
            view(2, 2, specs=[new_spec or m3_spec(value="160")])
        ),
        child=variants.snapshot_from_definition(view(3)),
        pinned_parent=old.ref,
    )


def selection(req):
    return AdoptionSelection(
        request_digest=variants.compare_snapshots(req).request_digest,
        paths=("specs/pressure",),
        sources=(ObjectReference.model_validate(object_ref("human", 31)),),
        reason="Adopt this specification",
        scope=ApplicabilityScope(
            category_id=req.child.ref.category_id,
            product_id=req.child.ref.product_id,
            description="Selected customer configuration",
        ),
    )


class AllowedPort:
    def assess(self, check):
        return ReuseAssessment(
            audience="allowed",
            cross_customer="not_required",
            applicability="applicable",
            basis=("Test-only authoritative port",),
        )


def test_real_definition_shape_preserves_all_spec_fields_and_exact_decimals():
    original = view()
    before = deepcopy(original)
    with localcontext() as context:
        context.prec = 4
        snapshot = variants.snapshot_from_definition(original)
    spec = snapshot.content.specs[0]
    assert spec.model_dump(mode="json") == m3_spec()
    assert spec.value == Decimal("150.000000000001")
    assert original == before


@pytest.mark.parametrize(
    "kind,target",
    [
        ("number", {"value": "150"}),
        ("range", {"lower": "120", "upper": "150"}),
        ("text", {"text_value": "Portable"}),
        ("boolean", {"text_value": "false"}),
        ("enum", {"text_value": "CO2"}),
    ],
)
def test_five_m3_value_types_and_proposal_field_aliases(kind, target):
    raw = m3_spec(value_type=kind, value=None, lower=None, upper=None, tolerance=None)
    raw.pop("text")
    raw.pop("method")
    raw.update(target, verification_method="Fixed verification method")
    parsed = variants.snapshot_from_definition(view(specs=[raw])).content.specs[0]
    assert parsed.value_type == kind
    assert parsed.method == "Fixed verification method"
    assert parsed.text == target.get("text_value")


@pytest.mark.parametrize(
    "kind", ["human", "snapshot", "knowledge", "parameter", "definition", "claim"]
)
def test_non_artifact_evidence_is_computable_and_remains_in_adoption(kind):
    raw = m3_spec(value="160", source_refs=[object_ref(kind)])
    req = request(raw)
    candidate = variants.accept_changes(req, selection(req), AllowedPort())
    adopted = candidate.content.specs[0]
    assert adopted.source_refs[0].type == kind
    assert adopted.source_refs[0] in candidate.traces[0].sources
    assert not any(gap.code == "missing_definition_source" for gap in candidate.missing)


def test_adoption_keeps_source_provenance_in_trace_without_inheriting_confirmation():
    req = request()
    before = req.model_dump(mode="json")
    candidate = variants.accept_changes(req, selection(req), AllowedPort())
    adopted, trace = candidate.content.specs[0], candidate.traces[0]
    assert trace.source_spec == req.new_parent.content.specs[0]
    assert trace.source_spec.confirmed_by == UUID(int=23)
    assert trace.source_spec.receipt_id == UUID(int=24)
    assert adopted.confirmed_by is None and adopted.receipt_id is None
    assert adopted.item_status == "ai_draft" and adopted.state == "needs_confirmation"
    assert adopted.origin == "ai_draft" and adopted.writer_id == UUID(int=21)
    assert adopted.run_id == UUID(int=22)
    assert adopted.parameter_id == UUID(int=40) and adopted.parameter_version == 3
    assert req.model_dump(mode="json") == before


def test_incomplete_specifications_remain_computable_with_diagnostics():
    unknown = m3_spec(
        availability="unknown",
        value=None,
        unit=None,
        condition_note=None,
        item_status="unknown",
        source_refs=[],
        sources=[],
    )
    req = request(unknown)
    result = variants.compare_snapshots(req)
    diff = next(row for row in result.differences if row.path == "specs/pressure")
    assert diff.new_parent.state == "unknown"
    codes = {gap.code for gap in result.missing}
    assert {"unknown_specification", "missing_unit", "missing_test_conditions"} <= codes
    assert diff.new_parent.value.value is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("parameter_version", 4),
        ("condition_note", "0 °C"),
        ("source_refs", [object_ref("claim", 99)]),
        ("origin", "human"),
    ],
)
def test_m3_semantics_change_comparison_and_bound_digest(field, value):
    req = request(m3_spec(**{field: value}))
    result = variants.compare_snapshots(req)
    diff = next(row for row in result.differences if row.path == "specs/pressure")
    assert diff.classification == "parent_only" and field in diff.changed_fields
    assert result.request_digest != variants.compare_snapshots(request(m3_spec())).request_digest


def test_legacy_adapter_preserves_full_m3_values_and_calls_rich_engine(monkeypatch):
    calls = []
    actual = variants.compare_snapshots

    def observe(req, **kwargs):
        calls.append(req)
        return actual(req, **kwargs)

    monkeypatch.setattr(variants, "compare_snapshots", observe)
    old, new, child = view(), view(2, 2, specs=[m3_spec(value="160")]), view(3)
    changes = variants.three_way(old, new, child)
    assert len(calls) == 1
    assert changes[0]["category"] == "parent_only"
    assert changes[0]["new_parent"]["parameter_version"] == 3
    assert changes[0]["new_parent"]["source_refs"] == [object_ref()]
    merged = variants.merge_content(old, new, child, [])
    assert len(calls) == 2
    assert merged["specs"][0]["value"] == "160"
    assert merged["specs"][0]["origin"] == "ai_draft"


def test_explicit_legacy_override_uses_rich_conflict_classification():
    old, new, child = view(), view(2, 2, purpose="New parent use"), view(3)
    current = SimpleNamespace(
        id=UUID(int=3),
        revision=1,
        variant_id=UUID(int=50),
        applicability=["Customer use"],
        reason="Explicit local purpose",
        overrides={"purpose": child["purpose"]},
    )
    changes = variants.three_way(old, new, child, current=current)
    assert changes == [
        {
            "path": "purpose",
            "old_parent": old["purpose"],
            "new_parent": new["purpose"],
            "current_child": child["purpose"],
            "category": "conflict",
        }
    ]
    picked = RebaseChoice(path="purpose", selection="child", reason="Keep local scope")
    assert (
        variants.merge_content(old, new, child, [picked], current=current)["purpose"]
        == child["purpose"]
    )


def test_adapter_rejects_unknown_business_fields_instead_of_silently_dropping_them():
    with pytest.raises(ValidationError):
        variants.snapshot_from_definition(view(specs=[m3_spec(invented_business_field="lost")]))


def test_known_missing_unit_is_diagnostic_not_a_new_g0_gate():
    req = request(m3_spec(unit=None))
    result = variants.compare_snapshots(req)
    assert any(gap.code == "missing_unit" for gap in result.missing)
    assert req.new_parent.content.specs[0].availability == "known"


@pytest.mark.parametrize("value", [True, 1.1, "NaN", "Infinity"])
def test_rich_adapter_never_coerces_inexact_or_nonfinite_numbers(value):
    with pytest.raises(ValidationError):
        SpecSnapshot.model_validate(m3_spec(value=value))


def test_dictionary_keys_remain_lossless_and_paths_escape_nested_syntax():
    key = "输出压力/主泵~精度"
    req = request(m3_spec(key=key, value="160"))
    result = variants.compare_snapshots(req)
    path = "specs/输出压力~1主泵~0精度"
    assert any(row.path == path for row in result.differences)
    chosen = selection(req).model_copy(update={"paths": (path,)})
    candidate = variants.accept_changes(req, chosen, AllowedPort())
    assert any(spec.key == key for spec in candidate.content.specs)


def test_production_comparison_calls_rich_engine_without_database(monkeypatch):
    from pdos_next import service
    from pdos_next.domain.preproject import baseline

    monkeypatch.setattr(baseline, "validate_sources", lambda *a, **kw: ())

    old, new, child = view(), view(2, 2, specs=[m3_spec(value="160")]), view(3)
    current = SimpleNamespace(
        id=UUID(int=3),
        revision=1,
        variant_id=UUID(int=50),
        parent_definition_id=UUID(int=1),
        parent_revision=1,
        applicability=["Fixed scope"],
        reason="Explicit difference",
        overrides={},
        effective_definition=child,
        definition_id=None,
    )
    monkeypatch.setattr(service, "require_access", lambda *a, **kw: None)
    monkeypatch.setattr(
        variants,
        "_variant_revision",
        lambda *a: (SimpleNamespace(id=UUID(int=50), name="Variant"), current),
    )
    monkeypatch.setattr(
        variants,
        "_parent",
        lambda s, ctx, product, parent, *a: old if parent == UUID(int=1) else new,
    )
    result = variants.compare_variant(None, None, UUID(int=101), UUID(int=50), UUID(int=2))
    expected = variants.compare_snapshots(
        variants._comparison_request(old, new, child, current=current), include_legacy_title=True
    )
    assert result["request_digest"] == expected.request_digest
    assert result["changes"][0]["new_parent"]["source_refs"] == [object_ref()]
    assert result["required_source_read_set"] == []


def test_production_assembly_uses_engine_and_still_invokes_write_validation(monkeypatch):
    old, new, child = view(), view(2, 2, specs=[m3_spec(value="160")]), view(3)
    new["visibility"] = "private"
    current = SimpleNamespace(
        id=UUID(int=3),
        revision=1,
        variant_id=UUID(int=50),
        parent_definition_id=UUID(int=1),
        parent_revision=1,
        applicability=["Fixed scope"],
        reason="Explicit difference",
        overrides={},
        effective_definition=child,
        definition_id=None,
        visibility="private",
    )
    monkeypatch.setattr(variants, "_variant_revision", lambda *a: (None, current))
    monkeypatch.setattr(
        variants,
        "_parent",
        lambda s, ctx, product, parent, *a: old if parent == UUID(int=1) else new,
    )
    compared, validated = [], []
    engine = variants.compare_snapshots

    def compare(req, **kwargs):
        compared.append(req)
        return engine(req, **kwargs)

    # This test isolates wiring only: business-source checks remain with the
    # existing writer, not the calculation DTO or a pretend validation port.
    monkeypatch.setattr(variants, "compare_snapshots", compare)
    monkeypatch.setattr(variants, "effective_definition", lambda p, overrides, *a: overrides)
    monkeypatch.setattr(variants, "validate_definition", lambda *a: validated.append(a[-1]))
    payload = SimpleNamespace(
        parent_definition_id=UUID(int=2),
        expected_parent_revision=2,
        variant_id=UUID(int=50),
        expected_variant_revision=1,
        choices=[],
        sources=[],
        reason="Adopt parent update",
    )
    _, _, result = variants._assemble(None, None, None, SimpleNamespace(id=UUID(int=101)), payload)
    assert len(compared) == 1 and validated == [result]
    assert result["specs"][0]["value"] == "160"
    assert result["specs"][0]["parameter_version"] == 3


def test_explicit_override_without_evidence_remains_visible_and_needs_evidence():
    old, new, child = view(source_refs=[]), view(2, 2, purpose="New use"), view(3, source_refs=[])
    child["specs"][0]["source_refs"] = []
    current = SimpleNamespace(
        id=UUID(int=3),
        revision=1,
        variant_id=UUID(int=50),
        applicability=["Fixed scope"],
        reason="Explicit local purpose",
        overrides={"purpose": child["purpose"]},
    )
    req = variants._comparison_request(old, new, child, current=current)
    result = variants.compare_snapshots(req)
    row = next(row for row in result.differences if row.path == "field/purpose")
    assert row.classification == "conflict"
    assert any(gap.code == "missing_override_source" for gap in result.missing)


def test_view_adapter_preserves_explicit_section_deletion():
    raw = view(deleted_fields=["constraints"])
    raw.pop("constraints")
    snapshot = variants.snapshot_from_definition(raw)
    assert variants.merge_paths(snapshot)["field/constraints"].state == "deleted"


def g0_current(child=None, **changes):
    child = child or view(70, 3, variant_id=str(UUID(int=50)))
    override = {
        "path": "specs/pressure",
        "operation": "set",
        "reason": "Explicit proposal choice",
        "sources": [object_ref("claim", 80)],
        "scope": {
            "category_id": child["category_id"],
            "product_id": child["product_id"],
            "variant_id": None,
            "description": "EU household products",
        },
    }
    return SimpleNamespace(
        **{
            "id": UUID(int=71),
            "revision": 1,
            "definition_id": UUID(child["id"]),
            "variant_id": UUID(int=50),
            "parent_definition_id": UUID(int=1),
            "parent_revision": 1,
            "reason": "G0 rationale differs from explicit choice",
            "applicability": [],
            "sources": [object_ref("definition", 1)],
            "overrides": {
                "request_digest": "frozen-proposal-digest",
                "differences": [{"path": "specs/pressure", "override": override}],
            },
            **changes,
        }
    )


def test_g0_comparison_uses_canonical_identity_and_original_explicit_trace():
    old, new, child = view(), view(2, 2), view(70, 3, variant_id=str(UUID(int=50)))
    current = g0_current(child)
    frozen = deepcopy(current.overrides)
    request = variants._comparison_request(old, new, child, current=current)
    assert request.child.ref.definition_id == UUID(int=70)
    assert request.child.ref.definition_id != current.id
    assert request.child.ref.revision == 3 and request.child.ref.revision != current.revision
    override = request.overrides[0]
    assert override.reason == "Explicit proposal choice"
    assert override.sources == (ObjectReference.model_validate(object_ref("claim", 80)),)
    assert override.scope.variant_id == UUID(int=50)
    assert override.scope.description == "EU household products"
    assert current.overrides == frozen
    variants.compare_snapshots(request)


def test_g0_comparison_digest_binds_definition_not_variant_revision_row():
    old, new, child = view(), view(2, 2), view(70, 3)
    current = g0_current(child)

    def digest(current, child):
        return variants.compare_snapshots(
            variants._comparison_request(old, new, child, current=current)
        ).request_digest

    first = digest(current, child)
    current.id = UUID(int=72)
    assert digest(current, child) == first
    child["id"], current.definition_id = str(UUID(int=73)), UUID(int=73)
    assert digest(current, child) != first


@pytest.mark.parametrize(
    "field,value",
    [
        ("category_id", str(UUID(int=200))),
        ("product_id", str(UUID(int=201))),
        ("variant_id", str(UUID(int=202))),
    ],
)
def test_g0_override_scope_mismatch_cannot_be_silently_rebound(field, value):
    child = view(70, 3)
    current = g0_current(child)
    current.overrides["differences"][0]["override"]["scope"][field] = value
    with pytest.raises(variants.DerivationError, match="OVERRIDE_SCOPE_MISMATCH"):
        variants._comparison_request(view(), view(2, 2), child, current=current)


def test_g0_canonical_reference_mismatch_is_rejected():
    from pdos_next.errors import DomainError

    current = g0_current()
    with pytest.raises(DomainError):
        variants._comparison_request(view(), view(2, 2), view(99), current=current)


def test_g0_invalid_difference_path_is_not_reinterpreted():
    current = g0_current()
    current.overrides["differences"][0]["path"] = "field/purpose"
    with pytest.raises(variants.DerivationError, match="INVALID_OVERRIDE_PATH"):
        variants._comparison_request(view(), view(2, 2), view(70, 3), current=current)


@pytest.fixture
def g0_comparison(monkeypatch):
    monkeypatch.setattr(variants, "_validate_g0_comparison", lambda *a: None)
    from pdos_next import service
    from pdos_next.domain.preproject import baseline

    old, child = view(), view(70, 3, variant_id=str(UUID(int=50)))
    current = g0_current(child)
    reads, calculations = [], []
    engine = variants.compare_snapshots

    def compare(request, **kwargs):
        calculations.append((request, kwargs))
        return engine(request, **kwargs)

    monkeypatch.setattr(service, "require_access", lambda *a, **kw: None)
    monkeypatch.setattr(
        variants,
        "_variant_revision",
        lambda *a: (SimpleNamespace(id=UUID(int=50), name="Actual variant"), current),
    )
    monkeypatch.setattr(variants, "_revision_content", lambda *a: child)
    monkeypatch.setattr(variants, "_parent", lambda *a: deepcopy(old))
    monkeypatch.setattr(
        baseline, "validate_sources", lambda s, ctx, view: reads.append((s, ctx, view))
    )
    monkeypatch.setattr(variants, "compare_snapshots", compare)
    return SimpleNamespace(
        old=old, child=child, current=current, reads=reads, calculations=calculations
    )


def test_compare_g0_fixed_parent_revalidates_typed_sources_once(g0_comparison):
    f = g0_comparison
    result = variants.compare_variant(
        "session", "context", UUID(int=101), UUID(int=50), UUID(int=1)
    )
    assert len(f.reads) == 1 and f.reads[0][:2] == ("session", "context")
    read = f.reads[0][2]
    assert read["id"] == str(UUID(int=70)) and read["revision"] == 3
    assert read["specs"][0]["parameter_id"] == str(UUID(int=40))
    assert object_ref("claim", 80) in read["source_refs"]
    assert {"type": "definition", "id": str(UUID(int=1)), "version": 1} in read["source_refs"]
    assert read["specs"][0]["source_refs"] == [object_ref()]
    request, mode = f.calculations[0]
    assert request.old_parent == request.new_parent
    assert mode["allow_same_parent"] is True
    assert result["old_parent_id"] == result["new_parent_id"] == str(UUID(int=1))
    assert object_ref("claim", 80) in result["source_refs"]


def test_compare_g0_unreadable_source_stops_before_calculation(g0_comparison, monkeypatch):
    from pdos_next.domain.preproject import baseline
    from pdos_next.errors import DomainError

    def unreadable(*args, **kwargs):
        raise DomainError("SOURCE_UNAVAILABLE", "Claim unreadable")

    monkeypatch.setattr(baseline, "validate_sources", unreadable)
    with pytest.raises(DomainError, match="Claim unreadable"):
        variants.compare_variant("session", "context", UUID(int=101), UUID(int=50), UUID(int=1))
    assert not g0_comparison.calculations


@pytest.fixture
def signed_g0_trace(monkeypatch):
    from pdos_next.domain.preproject import baseline, derivation
    from pdos_next.domain.preproject.schemas import SpecItem
    from pdos_next.service import digest

    context = SimpleNamespace(tenant_id=UUID(int=400), category_id=UUID(int=100))
    proposal_id, submission_id, decision_id = (UUID(int=i) for i in (401, 402, 403))
    parent = view()
    child = view(
        70,
        1,
        variant_id=str(UUID(int=50)),
        g0_decision_id=str(decision_id),
        source_proposal_id=str(proposal_id),
        source_submission_id=str(submission_id),
        source_proposal_revision=3,
    )
    raw = m3_spec()
    spec = {key: value for key, value in raw.items() if key in SpecItem.model_fields}
    spec.update(text_value=raw["text"], verification_method=raw["method"])
    document = {
        "entry_kind": "derivative",
        "target_kind": "new_variant",
        "title": "Proposed variant",
        "baseline_product_id": parent["product_id"],
        "baseline_definition_id": parent["id"],
        "baseline_definition_revision": 1,
        "source_refs": [],
        "context_refs": [],
        "items": [
            {"kind": "spec", "content": spec, "source_refs": [object_ref()], "origin": "human"},
            {
                "kind": "difference",
                "content": {
                    "area": "specification",
                    "item_ref": "pressure",
                    "change": "changed",
                    "reason": "Explicit proposal choice",
                    "applicability": "EU products",
                    "sources": [object_ref("claim", 80)],
                },
                "source_refs": [object_ref("claim", 80)],
            },
        ],
    }
    expected = derivation.calculation(parent, document, proposal_id=proposal_id, revision=3)
    current = g0_current(
        child,
        overrides={
            "request_digest": expected["request_digest"],
            "differences": expected["differences"],
        },
    )
    submission = SimpleNamespace(
        id=submission_id,
        proposal_id=proposal_id,
        revision=3,
        document_digest=digest(document),
        frozen_document=document,
    )
    decision = SimpleNamespace(
        id=decision_id,
        proposal_id=proposal_id,
        submission_id=submission_id,
        created_definition_id=UUID(child["id"]),
        created_product_id=UUID(child["product_id"]),
        created_variant_id=UUID(int=50),
        outcome="approved",
        review_digest=submission.document_digest,
    )
    reads, recomputed = [], []

    def read(*args, **kwargs):
        reads.append((args, kwargs))
        return deepcopy(parent)

    original = derivation.calculation

    def calculate(*args, **kwargs):
        recomputed.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(baseline, "published_baseline", read)
    monkeypatch.setattr(derivation, "calculation", calculate)

    class Session:
        def __init__(self):
            self.rows, self.queries = [decision, submission], []

        def scalar(self, query):
            self.queries.append(query)
            return self.rows.pop(0)

    return SimpleNamespace(
        ctx=context,
        parent=parent,
        child=child,
        current=current,
        submission=submission,
        decision=decision,
        reads=reads,
        recomputed=recomputed,
        session=Session(),
    )


def test_g0_stored_trace_is_recomputed_from_actual_visible_submission(signed_g0_trace):
    f = signed_g0_trace
    before = deepcopy(f.current.overrides)
    variants._validate_g0_comparison(f.session, f.ctx, f.current, f.child)
    assert len(f.session.queries) == 2 and len(f.recomputed) == 1
    args, kwargs = f.recomputed[0]
    assert args == (f.parent, f.submission.frozen_document)
    assert kwargs == {"proposal_id": f.submission.proposal_id, "revision": 3}
    args, kwargs = f.reads[0]
    assert args == (f.session, f.ctx, UUID(int=101), 1)
    assert kwargs["definition_id"] == UUID(int=1)
    assert {ref.id for ref in kwargs["extra_refs"] if ref.type == "claim"} == {
        UUID(int=30),
        UUID(int=80),
    }
    assert f.current.overrides == before


@pytest.mark.parametrize("field", ["request_digest", "reason", "sources", "description"])
def test_g0_inserted_calculation_trace_cannot_replace_signed_trace(signed_g0_trace, field):
    from pdos_next.errors import DomainError

    f = signed_g0_trace
    if field == "request_digest":
        f.current.overrides[field] = "invented"
    else:
        override = next(
            row["override"] for row in f.current.overrides["differences"] if row.get("override")
        )
        if field == "description":
            override["scope"][field] = "Another market"
        else:
            override[field] = [] if field == "sources" else "Invented rationale"
    with pytest.raises(DomainError) as error:
        variants._validate_g0_comparison(f.session, f.ctx, f.current, f.child)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert error.value.detail["reason"] == "variant_derivation_trace_unavailable"


@pytest.mark.parametrize("invisible", ["decision", "submission"])
def test_g0_comparison_does_not_bypass_source_proposal_rls(signed_g0_trace, invisible):
    from pdos_next.errors import DomainError

    f = signed_g0_trace
    f.session.rows[0 if invisible == "decision" else 1] = None
    with pytest.raises(DomainError) as error:
        variants._validate_g0_comparison(f.session, f.ctx, f.current, f.child)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert not f.reads and not f.recomputed


@pytest.mark.parametrize("mismatch", ["definition", "variant", "submission", "revision", "digest"])
def test_g0_comparison_requires_actual_signed_identity(signed_g0_trace, mismatch):
    from pdos_next.errors import DomainError

    f = signed_g0_trace
    if mismatch in {"definition", "variant"}:
        setattr(f.decision, f"created_{mismatch}_id", UUID(int=999))
    elif mismatch == "submission":
        f.child["source_submission_id"] = str(UUID(int=999))
    elif mismatch == "revision":
        f.child["source_proposal_revision"] = 4
    else:
        f.submission.frozen_document["title"] = "changed after signing"
    with pytest.raises(DomainError) as error:
        variants._validate_g0_comparison(f.session, f.ctx, f.current, f.child)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert not f.reads and not f.recomputed


def test_compare_g0_rejects_trace_before_running_untrusted_comparison(g0_comparison, monkeypatch):
    from pdos_next.errors import DomainError

    def invalid(*args):
        raise DomainError("SOURCE_UNAVAILABLE", "Trace differs from signed input")

    monkeypatch.setattr(variants, "_validate_g0_comparison", invalid)
    with pytest.raises(DomainError, match="Trace differs"):
        variants.compare_variant("session", "context", UUID(int=101), UUID(int=50), UUID(int=1))
    assert not g0_comparison.reads and not g0_comparison.calculations
