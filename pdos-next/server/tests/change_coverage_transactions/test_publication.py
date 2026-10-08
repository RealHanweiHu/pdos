"""One shared real-clock PG fixture: synthetic host coverage, atomic faults/retry.

Root alone runs this candidate against its verified isolated database. No owner,
qualification, source-byte, concrete registry, fixed proof or success is mocked.
The whole eight-facet original is a synthetic host statement for this fixed
fixture's objects, never evidence of real inventory/production/customer scope.
"""

# ruff: noqa: F811 - imported fixtures register the one existing dependency tree.

import hashlib
import json
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

import pytest
from change_execution.test_transactions import (  # noqa: F401
    accepted_work,
    capture,
    change_work,
    created,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import event, func, select
from test_project_first_plan import cmd, post
from test_resource_dependency_execution import engines  # noqa: F401 - verified exact target fixture

from pdos_next.change_dependency_clock import ChangeDependencyClock
from pdos_next.change_order_service import current_fixed
from pdos_next.change_order_service import snapshot as change_snapshot
from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import OperationalAsset, ResourceOccupancy
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_coverage_owner import importer, models, owner, registry, schemas, trust
from pdos_next.domain.change_execution import service as change_service
from pdos_next.domain.change_execution.models import (
    ChangeCurrent,
    ChangeGraphCapture,
    ChangeRequestVersion,
)
from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_execution import service as quality_service
from pdos_next.domain.test_resources.models import (
    SampleRunUsage,
    SampleUsageSentinel,
)
from pdos_next.domain.test_resources.models import (
    TestResourceReservation as ResourceReservation,
)
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
    UploadedOriginal,
    now,
)
from pdos_next.schemas.change_control.contracts import GraphSnapshot
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest as common_digest

CASE_NODE_LIMIT = 32  # Narrower than the owner's unchanged hard limit of 250.
SOURCE_LIMIT = 20
FAULT_MESSAGE = "Synthetic coverage publication fault after actual flush"
ATOM_MODELS = (
    Product,
    Principal,
    Grant,
    Artifact,
    UploadedOriginal,
    OperationalAsset,
    ChangeDependencyClock,
    ChangeRequestVersion,
    ChangeCurrent,
    ChangeGraphCapture,
    Project,
    models.ChangeCoverageFact,
    models.ChangeCoverageCurrent,
    ProfessionalFact,
    ProfessionalCurrent,
    VerificationRunVersion,
    VerificationRunCurrent,
    VerificationLaunchFact,
    ResourceReservation,
    ResourceOccupancy,
    SampleRunUsage,
    SampleUsageSentinel,
    Receipt,
    RequestKey,
    Audit,
    Outbox,
    Confirmation,
)


def effect_hashes(work, session=None):
    """Actual complete rows, including old Start/Current/authority/clock/common proof."""

    def read(s):
        return {
            model.__tablename__: sorted(
                common_digest(
                    {column.name: getattr(row, column.name) for column in model.__table__.columns}
                )
                for row in s.scalars(select(model).where(model.tenant_id == work.setup.tenant))
            )
            for model in ATOM_MODELS
        }

    if session is not None:
        return read(session)
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        return read(s)


def registered_original(work, raw, *, title):
    """Use the actual common NativeArtifact registration and exact full-line SHA."""
    text = json.dumps(
        raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    response = post(
        work.quality,
        cmd(
            work.quality,
            "evidence.artifact.register",
            {
                "title": title,
                "content": text,
                "source_label": "Synthetic bounded coverage host fixture only",
                "visibility": "private",
            },
        ),
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["subject_type"] == "artifact" and saved["subject_revision"] == 1
    return SourceRef(
        id=UUID(saved["subject_id"]),
        revision=1,
        kind="artifact",
        position="line:1;quote_sha256:" + hashlib.sha256(text.encode()).hexdigest(),
    )


def publish(work, issuer, payload, command_id, request_key):
    # Any exception leaves this entire tenant_session context: no savepoint,
    # partial rollback, reused aborted Session, or catch-then-commit path.
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        return importer.trusted_import(
            s,
            work.quality.ctx,
            work.setup.product,
            issuer,
            payload,
            command_id=command_id,
            request_key=request_key,
        )


def common_rows(s, work, command_id, request_key):
    receipt = s.scalar(
        select(Receipt).where(
            Receipt.tenant_id == work.setup.tenant,
            Receipt.product_id == work.setup.product,
            Receipt.command_id == command_id,
            Receipt.operation == schemas.OPERATION,
        )
    )
    assert receipt is not None
    counts = [
        s.scalar(select(func.count()).select_from(model).where(*where))
        for model, where in (
            (Receipt, (Receipt.id == receipt.id,)),
            (Audit, (Audit.receipt_id == receipt.id, Audit.operation == schemas.OPERATION)),
            (Outbox, (Outbox.receipt_id == receipt.id, Outbox.type == schemas.EVENT)),
            (RequestKey, (RequestKey.receipt_id == receipt.id, RequestKey.key == request_key)),
        )
    ]
    assert counts == [1, 1, 1, 1]
    return receipt


@contextmanager
def publication_fault(s, work, material, command_id, request_key, monkeypatch, *, mode):
    """Only explicit failures: preserve every actual owner read and real flush."""
    state = {"armed": False, "fired": False, "flushed_common_rows": 0}
    if mode == "outbox_insert":

        def fail_insert(_mapper, _connection, target):
            if target.type == schemas.EVENT and target.correlation_id == command_id:
                state.update(armed=True, fired=True)
                raise RuntimeError(FAULT_MESSAGE)

        event.listen(Outbox, "before_insert", fail_insert)
        try:
            yield state
        finally:
            event.remove(Outbox, "before_insert", fail_insert)
        return

    assert mode in {"after_full_flush", "clock_after_full_flush"}
    actual_flush = s.flush
    with monkeypatch.context() as patch:

        def flush(objects=None):
            keys = [r for r in s.new if isinstance(r, RequestKey) and r.key == request_key]
            audits = [r for r in s.new if isinstance(r, Audit) and r.operation == schemas.OPERATION]
            outboxes = [
                r
                for r in s.new
                if isinstance(r, Outbox)
                and r.type == schemas.EVENT
                and r.correlation_id == command_id
            ]
            armed = len(keys) == len(audits) == len(outboxes) == 1
            actual_flush(objects)
            if armed:
                assert objects is None and state["fired"] is False
                common_rows(s, work, command_id, request_key)
                state.update(armed=True, fired=True, flushed_common_rows=4)
                if mode == "after_full_flush":
                    raise RuntimeError(FAULT_MESSAGE)
                # Fault only. Actual business/PG/qualification clocks and all
                # prior fixture facts are untouched; never used for success.
                patch.setattr(
                    owner, "clock", lambda: material.valid_until + timedelta(microseconds=1)
                )

        patch.setattr(s, "flush", flush)
        yield state


def test_actual_synthetic_coverage_publication_whole_rollback_and_same_key_recovery(
    change_work, monkeypatch
):
    work = change_work
    started = monotonic()
    _, _, change_id = created(work)
    captured, _ = capture(work, change_id)
    graph = GraphSnapshot.model_validate(captured["capture"]["graph"])
    assert all(v.status == "unknown" for v in graph.coverage)
    assert 1 <= len(graph.nodes) <= CASE_NODE_LIMIT
    assert 1 <= len(captured["required_source_read_set"]) <= SOURCE_LIMIT
    assert graph.nature == "synthetic" and graph.expires_at > now()
    original_capture = deepcopy(captured["capture"])

    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        _, change = current_fixed(s, work.quality.ctx, work.setup.product, UUID(change_id))
        request = change_snapshot(change)
        fast_scope = change_service._scope_seed(
            s, work.quality.ctx, work.setup.product, (*request.roots, *request.references)
        )
        for ref in (*request.roots, *request.references):
            if ref.kind in {"issue", "capa"}:
                assert (
                    quality_service._change_scope_for_change(
                        s, work.quality.ctx, work.setup.product, ref
                    )
                    == fast_scope
                )
        scope, purpose = owner.fixed_seed(
            s, work.quality.ctx, work.setup.product, (*request.roots, *request.references)
        )
        assert fast_scope == (scope, purpose)
        basis = owner.inspect_basis(
            s, work.quality.ctx, work.setup.product, change_id=request.id, purpose=purpose
        )
        assert basis["scope"] == scope.model_dump(mode="json")
        assert digest(basis["closure"]["projection"]) == digest(registry.graph_projection(graph))
        project = s.get(Project, scope.project_id)
        assert project.visibility == "product" and project.owner_id != change.owner_id
        assert change.owner_id == work.quality.human and change.visibility == "private"
        material = schemas.CoverageMaterial(
            schema_version="pdos-controlled-change-coverage-v1",
            scope=scope,
            purpose=purpose,
            change_id=request.id,
            origin_version_id=change.id,
            origin_revision=change.revision,
            owner_id=change.owner_id,
            visibility=change.visibility,
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
                        "Synthetic host explicitly enumerates this fixed fixture closure; "
                        "no real inventory, production, customer or training attestation"
                    ),
                }
                for facet in schemas.FACETS
            ),
            closure_sha256=basis["closure_sha256"],
            valid_from=graph.captured_at,
            valid_until=graph.expires_at,
            nature="synthetic",
        )

    valid_raw = material.model_dump(mode="json")
    missing_scope = deepcopy(valid_raw)
    missing_scope.pop("scope")
    missing_facet = deepcopy(valid_raw)
    missing_facet["facets"] = missing_facet["facets"][:-1]
    originals = {
        "valid": registered_original(
            work, valid_raw, title="Synthetic whole bounded eight-facet coverage"
        ),
        "missing_scope": registered_original(
            work, missing_scope, title="Deliberately invalid missing coverage scope"
        ),
        "missing_facet": registered_original(
            work, missing_facet, title="Deliberately invalid missing coverage facet"
        ),
    }
    # Native registrations advance the real dependency clock. They do not enter
    # this fixed domain topology or change its registry closure SHA.
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        after_registration = owner.inspect_basis(
            s, work.quality.ctx, work.setup.product, change_id=material.change_id, purpose=purpose
        )
        assert after_registration["dependency_epoch"] > basis["dependency_epoch"]
        assert after_registration["closure"] == basis["closure"]
        assert after_registration["closure_sha256"] == material.closure_sha256
    issuer = trust.configure(
        work.setup.engine,
        work.professional_issuer,
        scope=scope,
        approvals=(
            schemas.OriginalApproval(source=originals["valid"], material_sha256=digest(material)),
        ),
    )
    payload = schemas.CoverageImport(
        project_id=scope.project_id,
        change_id=material.change_id,
        purpose=purpose,
        source=originals["valid"],
        reason="Synthetic trusted host publication; no execution/approval permission",
    )
    command_id, request_key = uuid4(), f"synthetic-coverage:{uuid4()}"
    baseline = effect_hashes(work)
    faults = {}
    try:
        for invalid in ("missing_scope", "missing_facet"):
            with pytest.raises(DomainError) as failure:
                publish(
                    work,
                    issuer,
                    payload.model_copy(update={"source": originals[invalid]}),
                    command_id,
                    request_key,
                )
            assert failure.value.code == "MISSING_REQUIRED_EVIDENCE" and failure.value.status == 422
            assert effect_hashes(work) == baseline

        for mode in ("outbox_insert", "after_full_flush", "clock_after_full_flush"):
            expected = DomainError if mode == "clock_after_full_flush" else RuntimeError
            with pytest.raises(expected) as failure:
                with tenant_session(work.setup.engine, work.setup.tenant) as s:
                    with publication_fault(
                        s, work, material, command_id, request_key, monkeypatch, mode=mode
                    ) as state:
                        importer.trusted_import(
                            s,
                            work.quality.ctx,
                            work.setup.product,
                            issuer,
                            payload,
                            command_id=command_id,
                            request_key=request_key,
                        )
            assert state["armed"] is True and state["fired"] is True
            assert state["flushed_common_rows"] == (0 if mode == "outbox_insert" else 4)
            if mode == "clock_after_full_flush":
                assert failure.value.code == "COVERAGE_OWNER_STALE" and failure.value.status == 409
            else:
                assert str(failure.value) == FAULT_MESSAGE
            faults[mode] = deepcopy(state)
            assert effect_hashes(work) == baseline

        # All failures escaped whole transaction. Retry the exact source, finite
        # issuer, semantic payload, command and original key; no new TTL or proof.
        assert now() < material.valid_until
        receipt = publish(work, issuer, payload, command_id, request_key)
        assert receipt["subject_type"] == schemas.FAMILY and receipt["subject_revision"] == 1
        committed = effect_hashes(work)
        assert committed != baseline
        for model in (
            models.ChangeCoverageFact,
            models.ChangeCoverageCurrent,
            Receipt,
            RequestKey,
            Audit,
            Outbox,
        ):
            assert len(committed[model.__tablename__]) == len(baseline[model.__tablename__]) + 1
        with tenant_session(work.setup.engine, work.setup.tenant) as s:
            saved = s.get(models.ChangeCoverageFact, UUID(receipt["subject_id"]))
            assert saved.material == valid_raw and saved.material_sha256 == digest(material)
            assert (
                saved.origin_version_id == material.origin_version_id and saved.origin_revision == 1
            )
            assert saved.issuer_stamp == trust.stamp(issuer) and saved.nature == "synthetic"
            assert saved.dependency_epoch == after_registration["dependency_epoch"]
            assert saved.source == originals["valid"].model_dump(mode="json")
            assert 1 <= len(saved.required_source_read_set) <= SOURCE_LIMIT
            assert originals["valid"] in tuple(SourceRef.model_validate(v) for v in saved.sources)
            assert common_rows(s, work, command_id, request_key).id == UUID(receipt["id"])
            current = owner.read(
                s,
                work.quality.ctx,
                work.setup.product,
                change_id=material.change_id,
                purpose=purpose,
                graph=graph,
                origin_version=(material.origin_version_id, material.origin_revision),
            )
            assert len(current.coverage) == len(graph.nodes) * 8
            assert {v.facet for v in current.coverage} == set(schemas.FACETS)
            assert all(
                v.status == "complete" and v.source == originals["valid"] for v in current.coverage
            )
            assert current.valid_until <= material.valid_until == graph.expires_at
            assert 1 <= len(current.required_source_read_set) <= SOURCE_LIMIT
            assert current.source_basis["dependency_epoch"] == saved.dependency_epoch
            refreshed = owner.refresh(
                s,
                work.quality.ctx,
                work.setup.product,
                current,
                change_id=material.change_id,
                purpose=purpose,
                graph=graph,
                origin_version=(material.origin_version_id, material.origin_revision),
            )
            assert refreshed.source_basis == current.source_basis
            assert refreshed.valid_until <= current.valid_until
            old_capture = s.get(ChangeGraphCapture, UUID(original_capture["id"]))
            assert old_capture.graph_snapshot == original_capture["graph"]
            assert old_capture.expires_at == graph.expires_at
            assert effect_hashes(work, s) == committed
        assert publish(work, issuer, payload, command_id, request_key) == receipt
        assert effect_hashes(work) == committed

        report = os.environ.get("PDOS_ROOT_COVERAGE_PUBLICATION_REPORT")
        if report:
            with Path(report).open("x") as stream:
                json.dump(
                    {
                        "status": "PASS_ACTUAL_SYNTHETIC_COVERAGE_WHOLE_TX_FAULT_RETRY",
                        "synthetic_only": True,
                        "full_ab_owner_read_positive": False,
                        "project_owner_differs_from_change_owner": True,
                        "actual_nodes": len(graph.nodes),
                        "case_node_limit": CASE_NODE_LIMIT,
                        "owner_node_limit": schemas.MAX_NODES,
                        "source_limit": SOURCE_LIMIT,
                        "actual_source_reads": len(current.required_source_read_set),
                        "coverage_entries": len(current.coverage),
                        "facets": list(schemas.FACETS),
                        "material_sha256": digest(material),
                        "closure_sha256": material.closure_sha256,
                        "source": originals["valid"].model_dump(mode="json"),
                        "baseline_table_count": len(ATOM_MODELS),
                        "whole_rows_unchanged_after_each_fault": True,
                        "faults": faults,
                        "same_original_key_receipt_recovered_without_new_effects": True,
                        "old_graph_unchanged_and_ttl_not_extended": True,
                        "body_elapsed_seconds": monotonic() - started,
                    },
                    stream,
                    indent=2,
                )
                stream.write("\n")
    finally:
        trust.disable(work.setup.engine, scope=scope)
