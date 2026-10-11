"""Root-only real API closure in one finite synthetic fixture; never run by a subagent.

The existing professional/Source/Owner/common ports stay actual. No fault hooks,
clock replacement, formal approvals, TTL extensions or new Run credentials.
"""

# ruff: noqa: F811 - imported fixtures register the existing one dependency tree.

import json
import os
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from change_coverage_transactions.test_publication import (
    CASE_NODE_LIMIT,
    SOURCE_LIMIT,
    common_rows,
    effect_hashes,
    engines,  # noqa: F401 - verified real target fixture
    publish,
    registered_original,
)
from change_execution.test_transactions import (  # noqa: F401
    accepted_work,
    capture,
    capture_post,
    change_work,
    command,
    counts,
    created,
    current,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import func, select
from test_project_first_plan import post

from pdos_next.change_order_service import current_fixed
from pdos_next.change_order_service import snapshot as change_snapshot
from pdos_next.database import tenant_session
from pdos_next.domain.change_control.rules import MANUFACTURING, NEXT, digest
from pdos_next.domain.change_coverage_owner import models, owner, registry, schemas, trust
from pdos_next.domain.change_execution.models import ChangeGraphCapture
from pdos_next.models import Artifact, Audit, Outbox, Receipt, RequestKey, now
from pdos_next.schemas.change_control.contracts import GraphSnapshot, ImpactAssessment
from pdos_next.service import digest as common_digest

REPORT_ENV = "PDOS_ROOT_MINIMAL_PUBLIC_COVERAGE_CAPTURE_REPORT"


def row_snapshot(s, model, identity, work):
    row = s.get(model, UUID(str(identity)))
    assert row is not None and row.tenant_id == work.setup.tenant
    if hasattr(row, "product_id"):
        assert row.product_id == work.setup.product
    return {column.name: deepcopy(getattr(row, column.name)) for column in model.__table__.columns}


def expect_http(response, expected):
    code = (
        response.json().get("code")
        if response.headers.get("content-type", "").startswith("application/json")
        else None
    )
    assert response.status_code == expected, (
        f"Actual HTTP status {response.status_code}, code {code}"
    )
    return response.json()


def read_keys(reads):
    pairs = {(row["artifact_id"], row["expected_revision"]) for row in reads}
    assert len(pairs) == len(reads) and 1 <= len(pairs) <= SOURCE_LIMIT
    assert len({identity for identity, _ in pairs}) == len(pairs)
    return pairs


def impact_common_group(s, work, value, receipt):
    saved = s.scalar(
        select(Receipt).where(
            Receipt.tenant_id == work.setup.tenant,
            Receipt.product_id == work.setup.product,
            Receipt.command_id == UUID(value["command_id"]),
            Receipt.operation == "change.impact.compute",
        )
    )
    assert saved.id == UUID(receipt["id"]) and saved.subject_id == UUID(receipt["subject_id"])
    assert saved.subject_type == "change_request" and saved.subject_revision == 2
    for model, conditions in (
        (Audit, (Audit.receipt_id == saved.id, Audit.operation == saved.operation)),
        (Outbox, (Outbox.receipt_id == saved.id, Outbox.type == "change.impact_created")),
        (
            RequestKey,
            (RequestKey.receipt_id == saved.id, RequestKey.key == value["idempotency_key"]),
        ),
    ):
        assert s.scalar(select(func.count()).select_from(model).where(*conditions)) == 1
    return saved


def missing_next(assessment):
    """Check actual fixed known nodes and explicit edges, never add missing paths."""
    graph = assessment.graph
    result = []
    for known in assessment.known:
        ref = known.node.ref
        expected = NEXT.get(ref.kind)
        actual = {edge.target.kind for edge in graph.edges if edge.origin == ref}
        if expected and not actual.intersection(expected):
            facet = "manufacturing" if ref.kind in MANUFACTURING else "engineering"
            assert any(
                value.node == ref and value.facet == facet and "有出处边" in value.reason
                for value in assessment.unknown
            )
            result.append((ref.identity, facet))
    assert result and any(facet == "manufacturing" for _, facet in result)
    return result


def report_once(report):
    target = os.environ.get(REPORT_ENV)
    if not target:
        return
    with os.fdopen(
        os.open(Path(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")


def test_actual_minimal_public_complete_capture_impact_and_original_command_recovery(change_work):
    """Root-only actual closure; independent deep successor read remains uncovered."""
    work = change_work
    started = monotonic()
    report = {
        "status": "FAIL_ACTUAL_MINIMAL_PUBLIC_COVERAGE_CAPTURE_IMPACT",
        "synthetic_only": True,
        "phase": "candidate-preflight",
        "phase_elapsed_seconds": {},
        "remaining_window_seconds_by_phase": {},
        "real_qualification_or_release_claimed": False,
        "standalone_deep_successor_proof_not_tested": True,
    }
    issuer = None
    scope = None
    material = None
    last_phase = started

    def phase(name):
        nonlocal last_phase
        at = monotonic()
        report["phase_elapsed_seconds"][report["phase"]] = at - last_phase
        report["phase"] = name
        last_phase = at
        if material is not None:
            remaining = (material.valid_until - now()).total_seconds()
            report["remaining_window_seconds"] = remaining
            report["remaining_window_seconds_by_phase"][name] = remaining
            assert remaining > 0, (
                f"Original finite coverage window exhausted at {name}; never extend"
            )

    try:
        phase("create-and-initial-unknown-capture")
        _, _, change_id = created(work)
        captured, old_payload = capture(work, change_id)
        graph = GraphSnapshot.model_validate(captured["capture"]["graph"])
        assert all(entry.status == "unknown" for entry in graph.coverage)
        assert len(graph.coverage) == 8 * len(graph.nodes)
        assert 1 <= len(graph.nodes) <= CASE_NODE_LIMIT == 32
        assert graph.nature == "synthetic" and graph.expires_at is None
        read_keys(captured["required_source_read_set"])
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.ctx.actor_id,
            requester_id=work.quality.ctx.requester_id,
            category_id=work.setup.category,
        ) as s:
            old_capture = row_snapshot(s, ChangeGraphCapture, graph.id, work)
            _, origin = current_fixed(s, work.quality.ctx, work.setup.product, UUID(change_id))
            request = change_snapshot(origin)
            scope, purpose = owner.fixed_seed(
                s, work.quality.ctx, work.setup.product, (*request.roots, *request.references)
            )
            basis = owner.inspect_basis(
                s, work.quality.ctx, work.setup.product, change_id=request.id, purpose=purpose
            )
            assert digest(basis["closure"]["projection"]) == digest(
                registry.graph_projection(graph)
            )
            material = schemas.CoverageMaterial(
                schema_version="pdos-controlled-change-coverage-v1",
                scope=scope,
                purpose=purpose,
                change_id=request.id,
                origin_version_id=origin.id,
                origin_revision=origin.revision,
                owner_id=origin.owner_id,
                visibility=origin.visibility,
                publisher_id=work.quality.human,
                roots=request.roots,
                nodes=tuple(node.ref for node in graph.nodes),
                units=tuple(
                    {"unit": f"object:{node.ref.identity}", "object_identity": node.ref.identity}
                    for node in graph.nodes
                ),
                facets=tuple(
                    {
                        "facet": facet,
                        "nodes": tuple(node.ref for node in graph.nodes),
                        "statement": (
                            "Synthetic fixed host enumeration only; no real production, "
                            "inventory, customer or training attestation"
                        ),
                    }
                    for facet in schemas.FACETS
                ),
                closure_sha256=basis["closure_sha256"],
                valid_from=graph.captured_at,
                valid_until=graph.captured_at + timedelta(hours=1),
                nature="synthetic",
            )
        assert old_capture["graph_sha256"] == digest(graph)
        report.update(
            actual_nodes=len(graph.nodes),
            coverage_entries=len(graph.coverage),
            original_captured_at=graph.captured_at.isoformat(),
            original_valid_until=None,
        )

        phase("native-original-and-one-trusted-publication")
        original = registered_original(
            work,
            material.model_dump(mode="json"),
            title="Synthetic minimal bounded public API coverage closure",
        )
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.ctx.actor_id,
            requester_id=work.quality.ctx.requester_id,
            category_id=work.setup.category,
        ) as s:
            native = row_snapshot(s, Artifact, original.id, work)
            assert native["content_hash"] == original.position.split("quote_sha256:")[1]
        issuer = trust.configure(
            work.setup.engine,
            work.professional_issuer,
            scope=scope,
            approvals=(
                schemas.OriginalApproval(source=original, material_sha256=digest(material)),
            ),
        )
        payload = schemas.CoverageImport(
            project_id=scope.project_id,
            change_id=material.change_id,
            purpose=purpose,
            source=original,
            reason="Synthetic publication for actual public capture; no approval or release",
        )
        pub_command, pub_key = uuid4(), f"synthetic-public-coverage:{uuid4()}"
        publication = publish(work, issuer, payload, pub_command, pub_key)
        assert (
            publication["subject_type"] == schemas.FAMILY and publication["subject_revision"] == 1
        )
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.ctx.actor_id,
            requester_id=work.quality.ctx.requester_id,
            category_id=work.setup.category,
        ) as s:
            fact = row_snapshot(s, models.ChangeCoverageFact, publication["subject_id"], work)
            assert fact["material"] == material.model_dump(mode="json") and fact[
                "material_sha256"
            ] == digest(material)
            assert (
                fact["valid_from"] == graph.captured_at
                and fact["valid_until"] == material.valid_until
            )
            assert fact["dependency_epoch"] > basis["dependency_epoch"] and fact[
                "source"
            ] == original.model_dump(mode="json")
            assert common_rows(s, work, pub_command, pub_key).id == UUID(publication["id"])
            coverage_pointer, _ = owner.pointer(
                s, work.quality.ctx, work.setup.product, scope, material.change_id, purpose
            )
            coverage_current = row_snapshot(
                s, models.ChangeCoverageCurrent, coverage_pointer.id, work
            )
            assert row_snapshot(s, Artifact, original.id, work) == native

        phase("new-key-public-complete-capture")
        before_capture = counts(work)
        fresh_payload = {
            **deepcopy(old_payload),
            "capture_key": str(uuid4()),
            "reason": "Read the finite published coverage with a new fixed graph key",
        }
        fresh = expect_http(capture_post(work, fresh_payload), 200)
        complete = GraphSnapshot.model_validate(fresh["capture"]["graph"])
        assert complete.id != graph.id and complete.revision == 1
        assert (
            complete.scope == graph.scope
            and complete.audience == graph.audience
            and complete.roots == graph.roots
        )
        assert complete.nature == "synthetic" and len(complete.nodes) == len(graph.nodes)
        assert digest(registry.graph_projection(complete)) == digest(
            registry.graph_projection(graph)
        )
        assert len(complete.coverage) == 8 * len(complete.nodes)
        assert {entry.facet for entry in complete.coverage} == set(schemas.FACETS)
        assert all(
            entry.status == "complete" and entry.source == original for entry in complete.coverage
        )
        assert complete.captured_at >= graph.captured_at
        assert complete.expires_at is None and fresh["capture"]["expires_at"] is None
        assert material.valid_until > now()
        capture_reads = read_keys(fresh["required_source_read_set"])
        assert (
            read_keys(captured["required_source_read_set"]) <= capture_reads
            and (str(original.id), original.revision) in capture_reads
        )
        after_capture = counts(work)
        assert (
            after_capture[ChangeGraphCapture.__tablename__]
            == before_capture[ChangeGraphCapture.__tablename__] + 1
        )
        assert all(
            after_capture[name] == count
            for name, count in before_capture.items()
            if name != ChangeGraphCapture.__tablename__
        )
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.ctx.actor_id,
            requester_id=work.quality.ctx.requester_id,
            category_id=work.setup.category,
        ) as s:
            complete_row = row_snapshot(s, ChangeGraphCapture, complete.id, work)
            assert complete_row["graph_snapshot"] == complete.model_dump(
                mode="json"
            ) and complete_row["graph_sha256"] == digest(complete)
            assert complete_row["expires_at"] == complete.expires_at
            saved_proof = deepcopy(complete_row["source_basis"]["coverage"])
            assert (
                saved_proof["graph"]["id"] == str(complete.id)
                and saved_proof["graph"]["expires_at"] is None
            )
            assert saved_proof["fact_id"] == publication["subject_id"] and saved_proof[
                "material_sha256"
            ] == digest(material)
            assert read_keys(saved_proof["reads"]) <= capture_reads
            assert (
                saved_proof["binding"]["version_id"] == str(material.origin_version_id)
                and saved_proof["binding"]["revision"] == 1
            )
            assert original.model_dump(mode="json") in complete_row["sources"]
            assert row_snapshot(s, ChangeGraphCapture, graph.id, work) == old_capture
            assert (
                row_snapshot(s, models.ChangeCoverageFact, publication["subject_id"], work) == fact
            )

        phase("actual-impact-inputs")
        value, inputs = command(work, "change.impact.compute", fresh["impact_payload"])
        input_reads = read_keys(inputs["required_source_read_set"])
        assert (
            capture_reads <= input_reads
            and value["source_read_set"] == inputs["required_source_read_set"]
        )
        reviewed = GraphSnapshot.model_validate(
            inputs["review"]["after"]["assessments"][-1]["graph"]
        )
        assert reviewed == complete
        before_impact, _ = current(work, change_id)
        phase("actual-common-impact-current-successor")
        receipt = expect_http(post(work.quality, value), 200)
        after_impact, pointer_after = current(work, change_id)
        assert receipt["subject_type"] == "change_request" and receipt["subject_revision"] == 2
        assert pointer_after == {"version_id": UUID(receipt["subject_id"]), "revision": 2}
        assert (
            after_impact["previous_version_id"] == before_impact["id"]
            and after_impact["previous_revision"] == 1
        )
        assert (
            after_impact["owner_id"] == before_impact["owner_id"]
            and after_impact["visibility"] == before_impact["visibility"] == "private"
        )
        request_after = after_impact["request_snapshot"]
        assert request_after["status"] == "analysis" and request_after["orders"] == []
        assert (
            request_after["roots"] == before_impact["request_snapshot"]["roots"]
            and request_after["audience"] == before_impact["request_snapshot"]["audience"]
        )
        assessment = ImpactAssessment.model_validate(request_after["assessments"][-1])
        assert assessment.graph == complete and assessment.unknown
        actual_missing_next = missing_next(assessment)
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.ctx.actor_id,
            requester_id=work.quality.ctx.requester_id,
            category_id=work.setup.category,
        ) as s:
            impact_common_group(s, work, value, receipt)

        phase("same-original-command-current-recovery")
        committed = effect_hashes(work)
        assert expect_http(post(work.quality, deepcopy(value)), 200) == receipt
        assert effect_hashes(work) == committed
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.ctx.actor_id,
            requester_id=work.quality.ctx.requester_id,
            category_id=work.setup.category,
        ) as s:
            assert (
                row_snapshot(s, models.ChangeCoverageFact, publication["subject_id"], work) == fact
            )
            assert (
                row_snapshot(s, models.ChangeCoverageCurrent, coverage_current["id"], work)
                == coverage_current
            )
            assert row_snapshot(s, ChangeGraphCapture, graph.id, work) == old_capture
            assert row_snapshot(s, ChangeGraphCapture, complete.id, work) == complete_row
            assert row_snapshot(s, Artifact, original.id, work) == native
            assert material.origin_version_id == before_impact["id"]
            assert material.origin_revision == 1
            assert effect_hashes(work, s) == committed
        assert current(work, change_id) == (after_impact, pointer_after)
        phase("finished-within-original-window")
        report.update(
            status="PASS_ACTUAL_MINIMAL_PUBLIC_COVERAGE_CAPTURE_IMPACT_CURRENT_RECOVERY",
            actual_source_reads=len(input_reads),
            material_sha256=digest(material),
            original_source_line_sha256=original.position.split("quote_sha256:")[1],
            old_capture_full_row_sha256=common_digest(old_capture),
            new_graph_sha256=digest(complete),
            complete_graph_valid_until=None,
            complete_facets_with_missing_next=len(actual_missing_next),
            impact_unknowns=len(assessment.unknown),
            old_unknown_capture_full_row_unchanged=True,
            old_key_replay_refusal_not_tested=True,
            source_hash_and_original_ttl_unchanged=True,
            same_original_command_recovered=True,
            coverage_publication_origin_and_fixed_scope_preserved=True,
            standalone_deep_successor_proof_not_tested=True,
            no_formal_approval_or_new_run=True,
        )
    except BaseException as error:
        report["failure_type"] = type(error).__name__
        raise
    finally:
        finished = monotonic()
        report["body_elapsed_seconds"] = finished - started
        report["phase_elapsed_seconds"][report["phase"]] = finished - last_phase
        if material is not None:
            report["remaining_window_seconds_at_exit"] = (
                material.valid_until - now()
            ).total_seconds()
        if issuer is not None:
            trust.disable(work.setup.engine, scope=scope)
        report_once(report)
