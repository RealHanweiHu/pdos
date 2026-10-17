"""Scoped originals, real pure graph rules and retained publication proof; no SQL IO."""

# ruff: noqa: F811 - imported fixture registers the explicit connection-free owner environment
import hashlib
import json
from uuid import uuid4

import pytest
from change_coverage_owner.test_owner_boundary import env, publish, read  # noqa: F401
from change_execution import kernel_helpers as helper
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from pdos_next import change_coverage_binding as binding
from pdos_next import service as common
from pdos_next.change_dependency_clock import ChangeDependencyClock
from pdos_next.domain.change_control.rules import compute_impact, digest, graph_sources
from pdos_next.domain.change_coverage_owner import models, owner, registry, schemas, trust
from pdos_next.domain.change_execution.graph import OwnedObject, capture_graph
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import (
    Edge,
    GraphSnapshot,
    PathApplicability,
    Ref,
)
from pdos_next.schemas.verification.contracts import SourceRef


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Owned pure checks must not open a database connection")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)


def scoped_graph():
    original = helper.graph()
    removed = {"tooling", "pilot_run", "manufacturing_release"}
    nodes = tuple(n for n in original.nodes if n.ref.kind not in removed)
    edges = tuple(
        e
        for e in original.edges
        if e.origin.kind not in removed and e.target.kind not in removed and e.origin.kind != "spec"
    )
    edges += tuple(
        Edge(
            id=name,
            origin=helper.ref(origin),
            target=helper.ref(target),
            source=helper.SOURCE,
            relation="fixed synthetic owner association",
        )
        for name, origin, target in (
            ("actual-definition-configuration", "spec", "engineering_configuration"),
            ("actual-configuration-bom", "engineering_configuration", "bom"),
            ("actual-bom-part", "bom", "part"),
            ("actual-operation-sop", "operation", "sop"),
        )
    )
    return GraphSnapshot.model_validate(
        {
            **original.model_dump(mode="python"),
            "nodes": nodes,
            "edges": edges,
            "coverage": tuple(c for c in original.coverage if c.node.kind not in removed),
            "path_applicability": tuple(
                PathApplicability(
                    node=helper.ref(kind),
                    targets=targets,
                    status="not_applicable",
                    reason=reason,
                    source=helper.SOURCE,
                )
                for kind, targets, reason in (
                    (
                        "operation",
                        ("tooling", "fixture"),
                        "Fixed manual assembly uses no tooling or fixture",
                    ),
                    (
                        "sop",
                        ("pilot_run",),
                        "Internal configuration revalidation does not authorize a pilot run",
                    ),
                )
            ),
        }
    )


def retained_publication(env):
    publish(env)
    current = read(env)
    approved = binding.covered_graph(env.graph, current)
    clock = next(r for r in env.rows if isinstance(r, ChangeDependencyClock))
    clock.epoch += 1
    return current, approved, clock


def retained_read(env, current, approved):
    return binding.read_retained_graph(
        env.s,
        env.ctx,
        env.pid,
        request=env.request,
        purpose=env.material.purpose,
        graph=approved,
        saved=current.source_basis,
    )


def test_v1_original_and_empty_graph_keep_exact_canonical_shape(env):
    raw = env.material.model_dump(mode="json")
    assert "paths" not in raw and "facet_states" not in raw
    assert schemas.CoverageMaterial.model_validate(raw).model_dump(mode="json") == raw
    legacy = env.graph.model_dump(mode="json")
    assert "path_applicability" not in legacy
    assert GraphSnapshot.model_validate(legacy).model_dump(mode="json") == legacy
    publish(env)
    assert all(c.status == "complete" for c in read(env).coverage)


@pytest.mark.parametrize("field", ["paths", "facet_states"])
def test_v1_cannot_silently_adopt_new_applicability_fields(env, field):
    raw = {**env.material.model_dump(mode="json"), field: []}
    with pytest.raises(ValidationError):
        schemas.CoverageMaterial.model_validate(raw)


def test_v2_actual_original_projects_exact_facet_state_and_source(env):
    operation = Ref(id=uuid4(), revision=1, kind="operation", key="assembly")
    sop = Ref(id=operation.id, revision=1, kind="sop", key=operation.key)
    for ref in (operation, sop):
        env.objects[ref.identity] = OwnedObject(
            ref, ref.kind, env.scope, env.ctx.actor_id, "product", {}, [], {}, True
        )
    env.links[env.graph.roots[0].identity] = ((operation, "fixed affected assembly"),)
    env.links[operation.identity] = ((sop, "fixed actual operation SOP"),)
    reader = registry.OwnerReader()
    reader.scope, reader.target = env.scope, env.request.audience
    env.graph = capture_graph(
        reader,
        identity=env.graph.id,
        roots=env.request.roots,
        captured_at=env.at,
        expires_at=env.graph.expires_at,
        nature="synthetic",
        sources=env.request.sources,
    )
    refs = tuple(n.ref for n in env.graph.nodes)
    raw = env.material.model_dump(mode="json")
    raw.update(
        schema_version="pdos-controlled-change-coverage-v2",
        nodes=[ref.model_dump(mode="json") for ref in refs],
        units=[{"unit": f"object:{ref.identity}", "object_identity": ref.identity} for ref in refs],
        facets=[
            {**facet, "nodes": [ref.model_dump(mode="json") for ref in refs]}
            for facet in raw["facets"]
        ],
        closure_sha256=registry.read_registry(env.s, env.ctx, env.pid, env.request).closure_sha256,
        paths=[
            {
                "node": ref.model_dump(mode="json"),
                "targets": list(targets),
                "status": "not_applicable",
                "reason": reason,
            }
            for ref, targets, reason in (
                (operation, ("tooling", "fixture"), "Manual assembly uses no tooling or fixture"),
                (sop, ("pilot_run",), "Internal revalidation is not a pilot run"),
            )
        ],
        facet_states=[
            {
                "node": raw["nodes"][0],
                "facet": "production_switch",
                "status": "not_applicable",
                "reason": "Internal revalidation excludes production switching",
            }
        ],
    )
    env.material = schemas.CoverageMaterial.model_validate(raw)
    content = json.dumps(env.material.model_dump(mode="json"), ensure_ascii=False)
    env.artifact.content, env.artifact.content_hash = content, common.digest(content)
    env.source = env.source.model_copy(
        update={"position": "line:1;quote_sha256:" + hashlib.sha256(content.encode()).hexdigest()}
    )
    env.payload = env.payload.model_copy(update={"source": env.source})
    # The test's actual original lookup binds this same Artifact ID/version.
    env.issuer = trust.configure(
        env.engine,
        env.professional,
        scope=env.scope,
        approvals=(
            schemas.OriginalApproval(source=env.source, material_sha256=digest(env.material)),
        ),
    )
    publish(env)
    current = read(env)
    selected = next(c for c in current.coverage if c.facet == "production_switch")
    assert (
        selected.status == "not_applicable" and selected.reason == raw["facet_states"][0]["reason"]
    )
    assert selected.source == env.source
    assert len(current.coverage) == 8 * len(refs)
    assert len(current.path_applicability) == 2
    assert {p.source for p in current.path_applicability} == {env.source}
    covered = binding.covered_graph(env.graph, current)
    assert covered.path_applicability == current.path_applicability
    assert covered.coverage == current.coverage
    assert current.source_basis["material_sha256"] == digest(env.material)


def test_supported_na_removes_only_exact_missing_continuations_and_keeps_real_rows():
    graph = scoped_graph()
    assessment = compute_impact(graph, 3)
    assert assessment.unknown == ()
    assert {r.node.ref.kind for r in assessment.known} >= {"part", "operation", "sop", "test_run"}
    assert all("tooling" != r.node.ref.kind for r in assessment.known)


def test_complete_facets_without_exact_path_declaration_still_leave_unknown():
    graph = scoped_graph()
    graph = graph.model_copy(update={"path_applicability": graph.path_applicability[1:]})
    unknown = compute_impact(graph, 3).unknown
    assert any(u.node == helper.ref("operation") and "tooling" in u.reason for u in unknown)


def test_real_tooling_relation_conflicts_with_na_and_is_never_hidden():
    graph = scoped_graph()
    tool = next(n for n in helper.graph().nodes if n.ref.kind == "tooling")
    graph = graph.model_copy(
        update={
            "nodes": (*graph.nodes, tool),
            "coverage": (
                *graph.coverage,
                *(c for c in helper.graph().coverage if c.node == tool.ref),
            ),
            "edges": (
                *graph.edges,
                *(
                    e
                    for e in helper.graph().edges
                    if e.origin.kind == "tooling" or e.target.kind == "tooling"
                ),
            ),
        }
    )
    assessment = compute_impact(graph, 3)
    assert any(r.node.ref == tool.ref for r in assessment.known)
    assert any(u.node == helper.ref("operation") and "冲突" in u.reason for u in assessment.unknown)


def test_indirect_configuration_membership_cannot_prove_part_used_by_operation():
    graph = scoped_graph()
    graph = graph.model_copy(
        update={
            "edges": (
                *(
                    e
                    for e in graph.edges
                    if not (e.origin.kind == "part" and e.target.kind == "operation")
                ),
                Edge(
                    id="same-configuration",
                    origin=helper.ref("engineering_configuration"),
                    target=helper.ref("operation"),
                    source=helper.SOURCE,
                    relation="same configuration only",
                ),
            )
        }
    )
    assert any(
        u.node == helper.ref("part") and "Operation" in u.reason
        for u in compute_impact(graph, 3).unknown
    )


@pytest.mark.parametrize("source,reason", [(None, "reason"), (helper.SOURCE, "")])
def test_unproven_or_unexplained_na_is_not_a_positive_declaration(source, reason):
    with pytest.raises(ValidationError):
        PathApplicability(
            node=helper.ref("sop"),
            targets=("pilot_run",),
            status="not_applicable",
            source=source,
            reason=reason,
        )


def test_path_sources_are_checked_and_raw_na_cannot_bypass_owner(env):
    graph = scoped_graph()
    source = SourceRef(id=uuid4(), revision=1, position="exact new original")
    paths = (graph.path_applicability[0].model_copy(update={"source": source}),)
    graph = graph.model_copy(update={"path_applicability": paths})
    assert source in graph_sources(graph)
    with pytest.raises(DomainError):
        binding.read_graph(
            env.s,
            env.ctx,
            env.pid,
            request=env.request,
            purpose=env.material.purpose,
            graph=graph,
            optional=True,
        )


def test_retained_proof_survives_new_epoch_but_is_not_current_coverage(env, monkeypatch):
    current, approved, clock = retained_publication(env)
    with pytest.raises(DomainError):
        read(env)

    def no_current_closure(*args, **kwargs):
        raise AssertionError("Retained publication must not claim a current registry closure")

    monkeypatch.setattr(registry, "read_registry", no_current_closure)
    retained = retained_read(env, current, approved)
    assert type(retained) is owner.RetainedCoverageRead
    assert not hasattr(retained, "coverage") and not hasattr(retained, "path_applicability")
    assert retained.source_basis == current.source_basis
    assert retained.source_basis["dependency_epoch"] != clock.epoch
    assert retained.observed_dependency_epoch == clock.epoch
    assert retained.source_basis["closure_sha256"] == env.material.closure_sha256
    refreshed = binding.refresh_retained_graph(
        env.s,
        env.ctx,
        env.pid,
        retained,
        request=env.request,
        purpose=env.material.purpose,
        graph=approved,
    )
    assert refreshed.source_basis == retained.source_basis
    owner.recheck_access(
        env.s, env.ctx, env.pid, refreshed, request=env.request, purpose=env.material.purpose
    )
    with pytest.raises(DomainError):
        binding.covered_graph(approved, retained)
    clock.epoch += 1
    with pytest.raises(DomainError):
        owner.recheck_access(
            env.s, env.ctx, env.pid, retained, request=env.request, purpose=env.material.purpose
        )


@pytest.mark.parametrize("drift", ["source", "issuer", "material", "closure", "graph", "coverage"])
def test_retained_epoch_exception_does_not_relax_original_proof(env, drift):
    current, approved, _ = retained_publication(env)
    if drift == "source":
        env.artifact.status = "withdrawn"
    elif drift == "issuer":
        trust.disable(env.engine, scope=env.scope)
    elif drift == "material":
        next(r for r in env.rows if isinstance(r, models.ChangeCoverageFact)).material_sha256 = (
            "a" * 64
        )
    elif drift == "closure":
        current.source_basis["closure_sha256"] = "a" * 64
    elif drift == "graph":
        approved = approved.model_copy(update={"id": uuid4()})
    else:
        approved = approved.model_copy(update={"coverage": ()})
    with pytest.raises(DomainError):
        retained_read(env, current, approved)


def test_retained_proof_rechecks_current_publisher_after_original_io(env, monkeypatch):
    from pdos_next import change_controlled_owner as controlled
    from pdos_next.models import Principal

    current, approved, _ = retained_publication(env)
    original = controlled._source_guard

    def revoke_publisher(*args, **kwargs):
        result = original(*args, **kwargs)
        next(row for row in env.rows if isinstance(row, Principal)).active = False
        return result

    monkeypatch.setattr(controlled, "_source_guard", revoke_publisher)
    with pytest.raises(DomainError) as error:
        retained_read(env, current, approved)
    assert error.value.status == 403


def test_retained_read_still_fences_clock_changes_during_source_io(env, monkeypatch):
    from pdos_next import change_controlled_owner as controlled

    current, approved, clock = retained_publication(env)
    original = controlled._source_guard

    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        clock.epoch += 1
        return result

    monkeypatch.setattr(controlled, "_source_guard", drift)
    with pytest.raises(DomainError):
        retained_read(env, current, approved)


def test_v2_original_rejects_wildcard_partial_or_unbound_path_claims(env):
    raw = {
        **env.material.model_dump(mode="json"),
        "schema_version": "pdos-controlled-change-coverage-v2",
    }
    raw["paths"] = [
        {
            "node": raw["nodes"][0],
            "targets": ["pilot_run"],
            "status": "not_applicable",
            "reason": "Arbitrary issue-wide exclusion",
        }
    ]
    with pytest.raises(ValidationError):
        schemas.CoverageMaterial.model_validate(raw)
