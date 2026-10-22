"""M3 model read ports: actual Run selectors, readonly sessions and outbound limits."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel import domain_reads as module
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.preproject import access as access_module
from pdos_next.domain.preproject import baseline, derivation, views
from pdos_next.errors import DomainError

PRODUCT, DEFINITION, PROPOSAL = (UUID(int=i) for i in (20, 21, 22))


def parent_view():
    return {
        "id": str(DEFINITION),
        "revision": 2,
        "category_id": str(UUID(int=6)),
        "product_id": str(PRODUCT),
        "variant_id": None,
        "title": "Public parent",
        "status": "published",
        "visibility": "category",
        "purpose": "Public product",
        "specs": [
            {
                "key": "pressure",
                "parameter": "Pressure",
                "value_type": "number",
                "availability": "known",
                "value": "10.000000000001",
                "unit": "Pa",
            }
        ],
    }


def proposal_doc():
    return {
        "entry_kind": "derivative",
        "target_kind": "new_product",
        "baseline_product_id": str(PRODUCT),
        "baseline_definition_id": str(DEFINITION),
        "baseline_definition_revision": 2,
        "source_refs": [],
        "items": [
            {
                "kind": "spec",
                "content": {
                    "key": "pressure",
                    "parameter": "Pressure",
                    "value_type": "number",
                    "availability": "known",
                    "value": "12.000000000001",
                    "unit": "Pa",
                },
                "source_refs": [],
            }
        ],
    }


def args():
    return {
        "baseline": {"product_id": str(PRODUCT), "definition_revision": 2},
        "proposed": {"proposal_id": str(PROPOSAL), "revision": 3},
    }


@pytest.fixture
def port(monkeypatch):
    scope = RunScope(*(UUID(int=i) for i in range(1, 7)), proposal_id=PROPOSAL)
    data = asdict(scope)
    data["id"] = data.pop("run_id")
    run = NS(**data, read_sources=[], state="running", reverted_at=None)
    calls, sql = [], []

    class Session:
        info = {"read_snapshot": True}
        privacy = False

        def get(self, model, identity):
            assert model is AgentRun and identity == run.id
            return run

        def scalar(self, statement, params=None):
            sql.append((str(statement), params))
            assert "FOR UPDATE" not in str(statement) and "FOR SHARE" not in str(statement)
            return self.privacy

    session = Session()

    @contextmanager
    def readonly(engine, tenant, **kwargs):
        calls.append((engine, tenant, kwargs))
        assert kwargs["read_snapshot"] is True
        yield session

    monkeypatch.setattr(module, "tenant_session", readonly)
    product = NS(id=PRODUCT, visibility="category")
    monkeypatch.setattr(module, "require_access", lambda s, ctx, pid: product)
    row = NS(
        id=PROPOSAL,
        revision=3,
        category_id=scope.category_id,
        effective_visibility="category",
        private_source_count=0,
        customer_identities=[],
        baseline_product_id=PRODUCT,
        baseline_definition_id=DEFINITION,
        baseline_definition_revision=2,
    )
    monkeypatch.setattr(access_module, "proposal", lambda s, ctx, identity: row)
    document, parent = proposal_doc(), parent_view()
    monkeypatch.setattr(views, "document", lambda s, r: deepcopy(document))
    baseline_calls = []

    def read(s, ctx, product_id, **kwargs):
        baseline_calls.append((s, ctx, product_id, kwargs))
        return {
            "definition": deepcopy(parent),
            "baseline_kind": "published",
            "derivation_eligible": True,
            "source_issues": [],
            "blocks": {
                area: {"status": "unknown", "items": []}
                for area in ("bom", "certification", "tooling", "platform")
            },
            "unavailable_blocks": ["bom", "certification", "tooling", "platform"],
        }

    monkeypatch.setattr(baseline, "read_baseline", read)
    monkeypatch.setattr(derivation, "validate_baseline", lambda *a: deepcopy(parent))
    authority = []
    store = NS(engine="engine", authority=lambda *a: authority.append(a))
    reads = module.DomainReads(store, DomainCommands(None, catalog=None, registry=None, route=None))
    return NS(
        scope=scope,
        run=run,
        session=session,
        calls=calls,
        sql=sql,
        row=row,
        product=product,
        document=document,
        parent=parent,
        reads=reads,
        authority=authority,
        baseline_calls=baseline_calls,
    )


def test_schemas_and_handlers_are_registered_for_actual_ports(port):
    from pdos_next.agent_kernel.tools import default_registry

    registry = {tool["name"]: tool for tool in default_registry().definitions()}
    assert "calc.derivation_diff" in port.reads.handlers()
    assert "product.baseline.read" in port.reads.handlers()
    assert module.SCHEMAS["product.baseline.read"] is module.BaselineInput
    assert module.SCHEMAS["calc.derivation_diff"] is module.DerivationDiffInput
    assert "product.baseline.read" in registry and "calc.derivation_diff" in registry


def test_category_run_reads_public_actual_baseline_without_prebound_product(port):
    result = port.reads.call(
        port.scope,
        {"product_id": str(PRODUCT), "definition_revision": 2},
        name="product.baseline.read",
    )
    assert result["definition"]["id"] == str(DEFINITION)
    assert result["definition"]["specs"][0]["value"] == "10.000000000001"
    assert result["blocks"]["bom"]["status"] == "unknown"
    assert len(port.authority) == len(port.calls) == 1
    _, tenant, config = port.calls[0]
    assert tenant == port.scope.tenant_id
    assert (
        config["actor_id"] == port.scope.writer_id
        and config["requester_id"] == port.scope.requester_id
    )
    assert config["category_id"] == port.scope.category_id and config["read_snapshot"] is True
    assert port.baseline_calls[0][2:] == (PRODUCT, {"variant_id": None, "definition_revision": 2})
    assert port.sql[0][1] == {
        "tenant": port.scope.tenant_id,
        "category": port.scope.category_id,
        "definition": DEFINITION,
        "version": 2,
    }


def test_run_product_is_default_selector(port):
    port.scope = replace(port.scope, product_id=PRODUCT)
    port.run.product_id = PRODUCT
    result = port.reads.call(port.scope, {}, name="product.baseline.read")
    assert result["definition"]["id"] == str(DEFINITION)


def test_area_projection_preserves_unknown_blocks(port):
    result = port.reads.call(
        port.scope,
        {"product_id": str(PRODUCT), "areas": ["bom", "tooling"]},
        name="product.baseline.read",
    )
    assert result["definition"] is None and set(result["blocks"]) == {"bom", "tooling"}
    assert result["unavailable_blocks"] == ["bom", "tooling"]


@pytest.fixture
def bom_port(port, monkeypatch):
    from pdos_next.domain.configurations.models import (
        BomRevision,
        EngineeringConfiguration,
        PartIdentity,
    )
    from pdos_next.models import Artifact, Product, UploadedOriginal

    common = {
        "tenant_id": port.scope.tenant_id,
        "category_id": port.scope.category_id,
        "product_id": PRODUCT,
        "visibility": "category",
        "revision": 1,
        "sources": [],
        "required_source_read_set": [],
    }
    config = NS(
        **common,
        id=UUID(int=60),
        definition_id=DEFINITION,
        definition_revision=2,
        bom_id=UUID(int=61),
        bom_revision=1,
        design_versions={},
    )
    bom = NS(**common, id=UUID(int=61))
    part = NS(**common, id=UUID(int=62), external_design_refs=[])
    artifact = NS(**common, id=UUID(int=63), original_id=UUID(int=64), status="active")
    original = NS(**common, id=UUID(int=64))
    product = NS(**common, id=PRODUCT)
    rows = {
        (EngineeringConfiguration, config.id): config,
        (BomRevision, bom.id): bom,
        (PartIdentity, part.id): part,
        (Artifact, artifact.id): artifact,
        (UploadedOriginal, original.id): original,
        (Product, product.id): product,
    }
    source = {
        "artifact_id": str(artifact.id),
        "expected_revision": 1,
        "line": 1,
        "quote": "Saved source quote",
    }
    original_get = port.session.get
    monkeypatch.setattr(
        port.session,
        "get",
        lambda model, identity: (
            original_get(model, identity) if model is AgentRun else rows.get((model, identity))
        ),
    )
    lines = [NS(part_id=part.id, part_revision=1)]
    queries, source_reads = [], []

    def scalars(query):
        queries.append(query)
        return lines

    def read_source(session, ctx, pid, identity, version):
        source_reads.append((pid, identity, version))
        assert pid == PRODUCT and identity == artifact.id and version == artifact.revision
        return artifact

    monkeypatch.setattr(port.session, "scalars", scalars, raising=False)
    monkeypatch.setattr(module, "source_for", read_source)
    baseline_read = baseline.read_baseline

    def read(*args, **kwargs):
        result = baseline_read(*args, **kwargs)
        # Deliberately untrustworthy public labels: authorization must use rows.
        result["blocks"]["bom"] = {
            "status": "available",
            "items": [
                {
                    "configuration": {"id": str(config.id), "visibility": "category"},
                    "bom_id": str(bom.id),
                    "bom_revision": 1,
                    "bom": {
                        "visibility": "category",
                        "sources": [source],
                        "lines": [
                            {
                                "part": {
                                    "visibility": "category",
                                    "customer_number": "CUSTOMER-42",
                                },
                            }
                        ],
                    },
                }
            ],
        }
        return result

    monkeypatch.setattr(baseline, "read_baseline", read)
    return NS(
        port=port,
        config=config,
        bom=bom,
        part=part,
        artifact=artifact,
        original=original,
        product=product,
        source=source,
        source_reads=source_reads,
        rows=rows,
        queries=queries,
        lines=lines,
    )


def read_bom(fixture, areas=None):
    return fixture.port.reads.call(
        fixture.port.scope,
        {"product_id": str(PRODUCT), "areas": areas or ["bom"]},
        name="product.baseline.read",
    )


def test_public_bom_closure_uses_actual_rows_and_exact_sources(bom_port):
    f = bom_port
    f.config.sources = [f.source]
    f.bom.required_source_read_set = [f.source]
    f.part.external_design_refs = [{"basis": f.source}]
    result = read_bom(f)
    assert result["blocks"]["bom"]["items"][0]["bom"]["lines"][0]["part"] == {
        "visibility": "category",
        "customer_number": "CUSTOMER-42",
    }
    assert f.source_reads == [(PRODUCT, f.artifact.id, 1)]
    params = f.queries[0].compile().params
    assert set(params.values()) == {
        f.port.scope.tenant_id,
        f.port.scope.category_id,
        PRODUCT,
        f.bom.id,
    }


@pytest.mark.parametrize("name", ["config", "bom", "part"])
@pytest.mark.parametrize("visibility", ["private", "audience"])
def test_private_bom_objects_denied_despite_public_projection(bom_port, name, visibility):
    getattr(bom_port, name).visibility = visibility
    with pytest.raises(DomainError) as error:
        read_bom(bom_port)
    assert error.value.detail["reason"] == "private_material_context_binding_required"


@pytest.mark.parametrize("root", ["artifact", "original", "product"])
@pytest.mark.parametrize("edge", ["config", "bom", "part", "design", "external", "read_set"])
def test_private_bom_source_closure_denied_from_persisted_edges(bom_port, root, edge):
    f = bom_port
    getattr(f, root).visibility = "private"
    if edge == "design":
        f.config.design_versions = {"firmware": {"basis": f.source}}
    elif edge == "external":
        f.part.external_design_refs = [{"basis": f.source}]
    elif edge == "read_set":
        f.bom.required_source_read_set = [f.source]
    else:
        getattr(f, edge).sources = [f.source]
    with pytest.raises(DomainError) as error:
        read_bom(f)
    assert error.value.detail["reason"] == "private_material_context_binding_required"
    assert f.source_reads == [(PRODUCT, f.artifact.id, 1)]


def test_unrequested_private_bom_does_not_block_public_specification(bom_port):
    bom_port.bom.visibility = "private"
    result = read_bom(bom_port, ["specification"])
    assert result["definition"]["id"] == str(DEFINITION) and not result["blocks"]
    assert not bom_port.queries


@pytest.mark.parametrize("broken", ["missing_part", "part_revision", "definition", "bom_revision"])
def test_bom_actual_binding_is_required_before_model_projection(bom_port, broken):
    f = bom_port
    if broken == "missing_part":
        f.rows.pop(next(key for key in f.rows if key[1] == f.part.id))
    elif broken == "part_revision":
        f.lines[0].part_revision = 2
    elif broken == "definition":
        f.config.definition_id = UUID(int=999)
    else:
        f.bom.revision = 2
    with pytest.raises(DomainError) as error:
        read_bom(f)
    assert error.value.detail["reason"] == "private_material_context_binding_required"


@pytest.mark.parametrize(
    "name,arguments",
    [("product.baseline.read", {"product_id": str(PRODUCT)}), ("calc.derivation_diff", args())],
)
@pytest.mark.parametrize(
    "private_context,privacy", [(False, True), (True, True), (False, None), (True, None)]
)
def test_private_or_unreadable_definition_never_enters_model_run(
    port, name, arguments, private_context, privacy
):
    port.scope = replace(port.scope, private_context=private_context)
    port.run.private_context = private_context
    port.run.read_sources = [{"artifact_id": str(UUID(int=40)), "expected_revision": 1}]
    port.session.privacy = privacy
    with pytest.raises(DomainError) as error:
        port.reads.call(port.scope, arguments, name=name)
    assert error.value.detail["reason"] == "private_material_context_binding_required"


def test_private_product_denied_before_baseline_body_read(port):
    port.product.visibility = "private"
    with pytest.raises(DomainError):
        port.reads.call(port.scope, {"product_id": str(PRODUCT)}, name="product.baseline.read")
    assert not port.baseline_calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("effective_visibility", "private"),
        ("private_source_count", 1),
        ("customer_identities", ["Customer"]),
    ],
)
def test_private_proposal_or_unbound_customer_context_is_denied(port, field, value):
    setattr(port.row, field, value)
    with pytest.raises(DomainError) as error:
        port.reads.call(port.scope, args(), name="calc.derivation_diff")
    assert error.value.detail["reason"] == "private_material_context_binding_required"


def test_actual_bound_proposal_uses_unique_engine_and_exact_revision(port, monkeypatch):
    from pdos_next.domain.products import variants

    calls = []
    original = variants.compare_snapshots

    def compare(request, **kwargs):
        calls.append(request)
        return original(request, **kwargs)

    monkeypatch.setattr(variants, "compare_snapshots", compare)
    result = port.reads.call(port.scope, args(), name="calc.derivation_diff")
    assert len(calls) == 1
    assert calls[0].child.ref.definition_id == PROPOSAL and calls[0].child.ref.revision == 3
    assert calls[0].old_parent == calls[0].new_parent
    assert result["proposal"] == {"id": str(PROPOSAL), "revision": 3, "kind": "proposal"}
    assert result["differences"][0]["area"] == "specification"
    assert result["unavailable_blocks"] == ["bom", "certification", "tooling"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"proposed": {"proposal_id": str(UUID(int=99)), "revision": 3}}, "proposal_run_mismatch"),
        ({"proposed": {"proposal_id": str(PROPOSAL), "revision": 2}}, "proposal_revision_moved"),
        (
            {"baseline": {"product_id": str(PRODUCT), "definition_revision": 1}},
            "baseline_version_changed",
        ),
        (
            {
                "baseline": {
                    "product_id": str(PRODUCT),
                    "definition_revision": 2,
                    "definition_id": str(UUID(int=99)),
                }
            },
            "baseline_version_changed",
        ),
    ],
)
def test_selectors_cannot_override_actual_bindings(port, change, reason):
    with pytest.raises(DomainError) as error:
        port.reads.call(port.scope, {**args(), **change}, name="calc.derivation_diff")
    assert error.value.detail["reason"] == reason


def test_product_selector_does_not_replace_bound_run_product(port):
    port.scope = replace(port.scope, product_id=UUID(int=99))
    port.run.product_id = port.scope.product_id
    with pytest.raises(DomainError) as error:
        port.reads.call(port.scope, args(), name="calc.derivation_diff")
    assert error.value.detail["reason"] == "product_run_mismatch"


def test_actual_run_mismatch_is_checked_before_read(port):
    port.run.private_context = True
    with pytest.raises(DomainError):
        port.reads.call(port.scope, {"product_id": str(PRODUCT)}, name="product.baseline.read")
    assert not port.authority and not port.baseline_calls


@pytest.mark.parametrize(
    "extra",
    [
        {"tenant_id": str(UUID(int=99))},
        {"category_id": str(UUID(int=99))},
        {"old_parent": {}},
        {"three_way": {"old_parent": {}, "new_parent": {}, "child": {}}},
    ],
)
def test_model_snapshots_and_authority_fields_are_not_inputs(extra):
    with pytest.raises(ValidationError):
        module.DerivationDiffInput.model_validate({**args(), **extra})


def test_definition_proposed_form_is_explicitly_not_supported():
    with pytest.raises(ValidationError):
        module.DerivationDiffInput.model_validate(
            {**args(), "proposed": {"product_id": str(PRODUCT), "definition_revision": 1}}
        )


def test_no_business_quantity_upper_limit_on_area_input():
    assert len(module.BaselineInput(areas=["specification"] * 1001).areas) == 1001


def test_unknown_only_comparison_does_not_invent_rows(port):
    result = port.reads.call(port.scope, {**args(), "areas": ["bom"]}, name="calc.derivation_diff")
    assert result["differences"] == [] and result["difference_traces"] == []
    assert result["blocks"] == {
        "bom": {"status": "unknown", "items": [], "reason": "definition_binding_unavailable"}
    }


def test_area_selection_is_bound_into_tool_input_digest(port):
    full = port.reads.call(port.scope, args(), name="calc.derivation_diff")
    subset = port.reads.call(
        port.scope, {**args(), "areas": ["specification"]}, name="calc.derivation_diff"
    )
    assert full["request_digest"] != subset["request_digest"]
    assert full["derivation_request_digest"] == subset["derivation_request_digest"]
    assert (
        full["engine"] == "products.variants.compare_snapshots"
        and full["schema_version"] == "derivation.v1"
    )


@pytest.mark.parametrize(
    "privacy,visibility,root_privacy",
    [
        ("private", "category", "shared"),
        ("shared", "private", "shared"),
        ("shared", "category", "private"),
    ],
)
def test_claim_indirect_private_context_cannot_reach_public_comparison(
    port, monkeypatch, privacy, visibility, root_privacy
):
    from pdos_next.domain.preproject import claim_access

    ref = {"type": "claim", "id": str(UUID(int=40)), "version": 1}
    port.document["items"][0]["source_refs"] = [ref]
    observed = []

    def resolve(s, ctx, identity, version, **kwargs):
        observed.append(kwargs)
        return NS(privacy=privacy, visibility=visibility)

    monkeypatch.setattr(claim_access, "resolve", resolve)
    monkeypatch.setattr(claim_access, "source_privacy", lambda *a: root_privacy)
    with pytest.raises(DomainError) as error:
        port.reads.call(port.scope, args(), name="calc.derivation_diff")
    assert error.value.detail["reason"] == "private_material_context_binding_required"
    assert observed == [{"approved": True}]


def test_nested_difference_sources_are_checked_before_computation(port, monkeypatch):
    from pdos_next.domain.preproject import claim_access

    ref = {"type": "claim", "id": str(UUID(int=40)), "version": 1}
    port.document["items"].append(
        {
            "kind": "difference",
            "source_refs": [],
            "content": {"area": "specification", "sources": [ref]},
        }
    )
    monkeypatch.setattr(
        claim_access, "resolve", lambda *a, **kw: NS(privacy="private", visibility="category")
    )
    with pytest.raises(DomainError):
        port.reads.call(port.scope, args(), name="calc.derivation_diff")


def test_public_claim_is_readonly_and_uses_real_root_privacy(port, monkeypatch):
    from pdos_next.domain.preproject import claim_access

    ref = {"type": "claim", "id": str(UUID(int=40)), "version": 1}
    port.document["items"][0]["source_refs"] = [ref]
    observed = []

    def resolve(s, ctx, identity, version, **kwargs):
        assert s.info["read_snapshot"] is True
        observed.append((identity, version, kwargs))
        return NS(privacy="shared", visibility="category")

    monkeypatch.setattr(claim_access, "resolve", resolve)
    monkeypatch.setattr(claim_access, "source_privacy", lambda *a: "shared")
    result = port.reads.call(port.scope, args(), name="calc.derivation_diff")
    assert result["differences"] and observed == [(UUID(int=40), 1, {"approved": True})]


def test_knowledge_indirection_does_not_hide_private_claim(port, monkeypatch):
    from pdos_next.domain.preproject import claim_access
    from pdos_next.domain.preproject.category_models import KnowledgeEntry

    ref = {"type": "knowledge", "id": str(UUID(int=41)), "version": 2}
    port.document["items"][0]["source_refs"] = [ref]
    original = port.session.get

    def get(model, identity):
        if model is KnowledgeEntry:
            return NS(
                category_id=port.scope.category_id,
                version=2,
                source_refs=[{"type": "claim", "id": str(UUID(int=40)), "version": 1}],
            )
        return original(model, identity)

    monkeypatch.setattr(port.session, "get", get)
    monkeypatch.setattr(
        claim_access, "resolve", lambda *a, **kw: NS(privacy="private", visibility="category")
    )
    with pytest.raises(DomainError):
        port.reads.call(port.scope, args(), name="calc.derivation_diff")


def test_cancelled_actual_run_cannot_use_public_selector(port):
    port.run.state = "cancelled"
    with pytest.raises(DomainError) as error:
        port.reads.call(port.scope, {"product_id": str(PRODUCT)}, name="product.baseline.read")
    assert error.value.code == "CANCELLED_RUN" and not port.baseline_calls
