"""Actual native material reader composition with no-connect SQL substitutes.

Physical/project/configuration/source readers and selected Publication reader
execute unmodified. Retained professional IO is explicit synthetic input; none
of these cases attests PG/RLS, asset acceptance, start or a production Pilot.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from manufacturing_preparation import test_publication_service as publication_samples
from manufacturing_preparation.test_publication_material_owner import (
    world as native_world,  # noqa: F401
)
from manufacturing_preparation.test_publication_rules import case as publication_case  # noqa: F401
from sqlalchemy import select

from pdos_next.contracts import SourceRead
from pdos_next.domain.build_execution.models import ActualConfiguration, BuildLot
from pdos_next.domain.builds.models import Build
from pdos_next.domain.manufacturing_baseline import publication_service as publications
from pdos_next.domain.manufacturing_baseline import service as preparations
from pdos_next.domain.manufacturing_baseline.publication_material_owner import (
    ActualPublicationMaterialOwner,
)
from pdos_next.domain.manufacturing_baseline.publication_schemas import ResourceRequirement
from pdos_next.domain.manufacturing_trials.native_material_owner import ActualPilotMaterialOwner
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant
from pdos_next.schemas.manufacturing_trials.contracts import LotBasis, PilotCreate, Ref
from pdos_next.schemas.verification.contracts import SourceRef


@pytest.fixture
def work(request, monkeypatch):
    original = request.getfixturevalue("native_world")
    s, ctx, pid = original.s, original.ctx, original.pid
    execute = s.execute

    def direct_columns(statement, *args, **kwargs):
        descriptions = statement.column_descriptions
        models = {value["entity"] for value in descriptions}
        if len(models) != 1 or descriptions[0]["expr"] is descriptions[0]["entity"]:
            return execute(statement, *args, **kwargs)
        model = next(iter(models))
        rows = s.scalars(select(model).where(*statement._where_criteria))
        values = [
            {column.key: getattr(row, column.key) for column in statement.selected_columns}
            for row in rows
        ]
        return SimpleNamespace(mappings=lambda: values)

    # Only projected SQL is replaced, not any owner/current/source predicate.
    monkeypatch.setattr(s, "execute", direct_columns)
    source = original.case.read_only.model_dump(mode="json")
    reads = [{key: source[key] for key in ("artifact_id", "expected_revision")}]
    at = datetime.now(UTC) - timedelta(minutes=2)
    build = s.add_row(
        Build(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=pid,
            project_id=original.project.id,
            project_revision=original.project.revision,
            engineering_configuration_id=original.engineering.id,
            manufacturing_configuration_id=original.process.id,
            previous_build_id=None,
            owner_id=ctx.actor_id,
            name="actual native Pilot Build",
            type="pilot",
            purpose=original.project.purpose,
            planned_quantity=Decimal("12"),
            unit="台",
            planned_start=None,
            planned_end=None,
            verification_objectives="actual observations",
            disposition_plan="retain unknown",
            visibility="private",
            revision=1,
            status="planned",
            created_at=at,
        )
    )
    actual = s.add_row(
        ActualConfiguration(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=pid,
            project_id=build.project_id,
            build_id=build.id,
            build_revision=1,
            owner_id=ctx.actor_id,
            visibility="private",
            revision=1,
            reason="saved actual configuration IO",
            sources=[source],
            required_source_read_set=reads,
            status="recorded",
            planned_engineering_configuration_id=original.engineering.id,
            planned_manufacturing_configuration_id=original.process.id,
            actual_engineering_configuration_id=original.engineering.id,
            actual_engineering_revision=original.engineering.revision,
            actual_manufacturing_configuration_id=original.process.id,
            actual_manufacturing_revision=original.process.revision,
            observed_at=at,
            differences=[],
            created_at=at,
        )
    )
    lot = s.add_row(
        BuildLot(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=pid,
            project_id=build.project_id,
            build_id=build.id,
            build_revision=1,
            owner_id=ctx.actor_id,
            visibility="private",
            revision=1,
            reason="actual external lot IO",
            sources=[source],
            required_source_read_set=reads,
            status="observed",
            actual_configuration_id=actual.id,
            actual_configuration_revision=1,
            lot_label="native-observed-12",
            observed_unit_count=12,
            unit="台",
            observation_system="explicit-pure-original",
            observation_external_id="lot-original-12",
            observation_nature="synthetic",
            occurred_at=at,
            received_at=at,
            created_at=at,
        )
    )
    scalar = s.scalar

    def physical_aggregates(statement, *args, **kwargs):
        column = list(statement.selected_columns)[0]
        if getattr(column, "name", None) == "count":
            return 0
        if getattr(column, "name", None) == "sum":
            return lot.observed_unit_count
        return scalar(statement, *args, **kwargs)

    monkeypatch.setattr(s, "scalar", physical_aggregates)
    basis = LotBasis(
        build=Ref(kind="build", id=build.id, revision=1),
        lot=Ref(kind="build_lot", id=lot.id, revision=1),
        actual_configuration=Ref(kind="actual_configuration", id=actual.id, revision=1),
        engineering_configuration=Ref(
            kind="engineering_configuration",
            id=original.engineering.id,
            revision=original.engineering.revision,
        ),
        process_revision=Ref(
            kind="process_revision", id=original.process.id, revision=original.process.revision
        ),
        unit="台",
    )
    payload = PilotCreate(
        pilot_id=uuid4(),
        basis=basis,
        purpose=original.project.purpose,
        source=SourceRef(
            kind="artifact",
            id=original.case.read_only.artifact_id,
            revision=1,
            position="line:2;quote_sha256:"
            + sha256(original.case.read_only.quote.encode()).hexdigest(),
        ),
    )
    value = SimpleNamespace(
        **{**vars(original), "build": build, "actual": actual, "lot": lot, "payload": payload}
    )
    value.owner = ActualPilotMaterialOwner(s.get_bind())
    value.read = lambda: value.owner.read(s, value.ctx, pid, value.payload)
    return value


def _publish_fixture(work, monkeypatch):
    """Construct synthetic SQL rows with actual common writer hooks, not new truth.

    The fixture writer has explicit lower-level professional/SQL substitutes.
    Afterward all those monkeypatches are restored before the real read path.
    """
    material = (
        ActualPublicationMaterialOwner(work.s.get_bind())
        .read(work.s, work.ctx, work.pid, work.case.payload)
        .material
    )
    real_evidence = preparations.evidence._evidence
    with monkeypatch.context() as fixture_patch:
        fixture_patch.setattr(
            publication_samples, "publication_case", SimpleNamespace(__wrapped__=lambda: work.case)
        )
        factory = publication_samples.work.__wrapped__(fixture_patch)
        saved = next(factory)
        saved.material = material
        saved.command = saved.command.model_copy(
            update={
                "source_read_set": [
                    SourceRead.model_validate(v.model_dump(mode="json"))
                    for v in material.required_source_read_set
                ]
            }
        )

        def evidence_io(_s, caller, pid, reads, refs=(), **kwargs):
            assert _s is saved.s and caller.tenant_id == work.ctx.tenant_id and pid == work.pid
            return real_evidence(work.s, work.ctx, pid, reads, refs, **kwargs)

        fixture_patch.setattr(publications.evidence, "_evidence", evidence_io)
        row, _receipt = publication_samples.finish(saved, publication_samples.write(saved))
        records = {model: list(rows) for model, rows in saved.s.rows.items()}
        try:
            next(factory)
        except StopIteration:
            pass
    for model, rows in records.items():
        if model is Grant:
            continue
        existing = {value.id for value in work.s.rows.get(model, ())}
        work.s.rows.setdefault(model, []).extend(
            value for value in rows if value.id not in existing
        )
    publications.configure(work.s.get_bind())
    # This is retained professional IO only; source/group/current/body readers
    # remain actual. It does not grant Pilot resource qualification.
    monkeypatch.setattr(
        publications,
        "_recheck",
        lambda *args, **kwargs: {"current": True, "historical_valid": True},
    )
    monkeypatch.setattr(publications, "signature_current", lambda *args, **kwargs: True)
    work.payload = work.payload.model_copy(
        update={
            "manufacturing_baseline": Ref(
                kind="manufacturing_baseline", id=row.id, revision=row.revision
            )
        }
    )
    return row


def reject(call, reason=None):
    with pytest.raises(DomainError) as error:
        call()
    if reason:
        assert error.value.reason == reason


def test_actual_physical_readers_preserve_lot_nature_and_explicit_missing_publication(work):
    value = work.read()
    assert value.material.lot["observation"]["nature"] == "synthetic"
    assert value.material.lot["observed_unit_count"] == 12
    assert value.material.actual_configuration["id"] == str(work.actual.id)
    assert value.material.publication is None
    assert "MANUFACTURING_PUBLICATION_MISSING" in {v.code for v in value.material.gaps}
    assert value.material.qualification == "unknown" and value.material.start_authorized is False
    json.dumps(value.source_basis, allow_nan=False)
    fresh = work.owner.refresh(work.s, work.ctx, work.pid, work.payload, value)
    assert fresh.material == value.material and fresh.checked_at >= value.checked_at
    assert not (work.s.new or work.s.dirty or work.s.deleted)


def test_selected_publication_uses_actual_formal_group_and_cannot_grant_resources(
    work, monkeypatch
):
    row = _publish_fixture(work, monkeypatch)
    value = work.read()
    assert value.material.publication["id"] == str(row.id)
    assert value.material.publication["baseline"]["id"] == str(work.case.material.baseline.id)
    assert value.source_basis["publication"]["receipt_id"] == str(row.receipt_id)
    assert "PILOT_RESOURCE_READINESS_OWNER_UNCONNECTED" in {v.code for v in value.material.gaps}
    assert value.material.start_authorized is False and value.material.manufacturing_release is None


@pytest.mark.parametrize("fault", ("site", "line", "document", "expired"))
def test_selected_publication_actual_scope_or_time_failure_is_not_an_unknown_fallback(
    work, monkeypatch, fault
):
    if fault in {"site", "expired"}:
        updates = (
            {"site": "另一实际场地"}
            if fault == "site"
            else {"valid_until": datetime.now(UTC) - timedelta(minutes=1)}
        )
        work.case.payload = work.case.payload.model_copy(
            update={"applicability": work.case.payload.applicability.model_copy(update=updates)}
        )
    _publish_fixture(work, monkeypatch)
    if fault == "line":
        work.payload = work.payload.model_copy(
            update={"line": Ref(kind="line", id=uuid4(), revision=1)}
        )
    elif fault == "document":
        work.payload = work.payload.model_copy(
            update={"instructions": (Ref(kind="work_instruction", id=uuid4(), revision=1),)}
        )
    reject(work.read, "SOURCE_STALE" if fault == "expired" else "FORBIDDEN_SCOPE")


def test_actual_publication_requirement_retains_named_resource_gap(work, monkeypatch):
    resource = uuid4()
    group = next(value for value in work.case.payload.requirements if value.kind == "equipment")
    requirement = ResourceRequirement(
        text="本原文明确要求的设备尚待实际验收",
        sources=group.sources,
        operation_keys=("assemble",),
        resource={"kind": "equipment", "id": resource, "revision": 3},
    )
    work.case.payload = work.case.payload.model_copy(
        update={
            "requirements": tuple(
                value.model_copy(update={"requirements": (requirement,)})
                if value is group
                else value
                for value in work.case.payload.requirements
            )
        }
    )
    _publish_fixture(work, monkeypatch)
    value = work.read()
    gap = next(
        v for v in value.material.gaps if v.code == "PUBLISHED_RESOURCE_REQUIREMENT_UNVERIFIED"
    )
    assert str(resource) in gap.detail and "v3" in gap.detail and requirement.text in gap.detail
    assert gap.state == "unknown" and value.material.qualification == "unknown"


def test_t1_draft_id_is_not_a_formal_publication(work):
    publications.configure(work.s.get_bind())
    work.payload = work.payload.model_copy(
        update={
            "manufacturing_baseline": Ref(
                kind="manufacturing_baseline", id=work.case.material.baseline.id, revision=1
            )
        }
    )
    reject(work.read, "FORBIDDEN_SCOPE")


@pytest.mark.parametrize(
    "field",
    ("build", "lot", "actual_configuration", "engineering_configuration", "process_revision"),
)
def test_actual_fixed_physical_versions_cannot_be_replaced(work, field):
    value = getattr(work.payload.basis, field)
    work.payload = work.payload.model_copy(
        update={
            "basis": work.payload.basis.model_copy(
                update={field: value.model_copy(update={"revision": value.revision + 1})}
            )
        }
    )
    reject(work.read)


def test_lot_and_actual_configuration_must_belong_to_same_build(work):
    work.lot.build_id = uuid4()
    reject(work.read, "CONFIGURATION_MISMATCH")


def test_unknown_native_source_is_not_a_silent_empty_source_success(work):
    work.payload = work.payload.model_copy(
        update={
            "source": work.payload.source.model_copy(update={"kind": "domain", "id": work.lot.id})
        }
    )
    reject(work.read, "INTEGRATION_REQUIRED")


def test_withdrawal_is_rejected_by_actual_source_owner(work):
    next(
        value for value in work.s.rows[Artifact] if value.id == work.payload.source.id
    ).status = "withdrawn"
    reject(work.read, "SOURCE_UNAVAILABLE")


@pytest.mark.parametrize("field", ("forged", "basis", "caller", "transaction", "payload", "clock"))
def test_refresh_rejects_unissued_or_changed_read_binding(work, field):
    value = work.read()
    if field == "forged":
        value = replace(value)
    elif field == "basis":
        value.source_basis["artifacts"].clear()
    elif field == "caller":
        work.ctx = replace(work.ctx, actor_id=uuid4(), requester_id=uuid4())
    elif field == "transaction":
        work.s.rollback()
        work.s.begin()
    elif field == "payload":
        work.payload = work.payload.model_copy(update={"pilot_id": uuid4()})
    else:
        object.__setattr__(value, "checked_at", value.checked_at + timedelta(seconds=1))
    reject(lambda: work.owner.refresh(work.s, work.ctx, work.pid, work.payload, value))


def test_later_lot_change_is_rejected_on_actual_refresh(work):
    value = work.read()
    work.lot.observed_unit_count += 1
    reject(
        lambda: work.owner.refresh(work.s, work.ctx, work.pid, work.payload, value), "SOURCE_STALE"
    )


def test_single_snapshot_read_does_not_emulate_concurrency_with_a_second_owner_pass(
    work, monkeypatch
):
    original = preparations.evidence._evidence
    changed = False

    def after_source(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            work.lot.observed_unit_count += 1
        return result

    monkeypatch.setattr(preparations.evidence, "_evidence", after_source)
    value = work.read()
    # The lower SQL substitute deliberately violates the real held snapshot.
    # Preserve its one-read result; a later explicit current check rejects the
    # changed direct Lot watermark, without replaying the upstream readers.
    assert value.material.lot["observed_unit_count"] == 12
    reject(
        lambda: work.owner.current(
            work.s, work.ctx, work.pid, value.material.model_dump(mode="json"), value.source_basis
        ),
        "SOURCE_STALE",
    )


def test_same_uow_cached_material_has_no_new_select_or_complete_collect(work, monkeypatch):
    collect = work.owner._collect
    calls = []

    def once(*args):
        calls.append(True)
        return collect(*args)

    monkeypatch.setattr(work.owner, "_collect", once)
    value = work.read()
    query_count = len(work.s.queries)
    assert work.read() is value
    assert len(calls) == 1 and len(work.s.queries) == query_count


def test_persisted_current_and_refresh_use_direct_rows_without_rebuilding_owners(work, monkeypatch):
    value = work.read()

    def no_collect(*args, **kwargs):
        raise AssertionError("current/refresh must not recollect owners")

    monkeypatch.setattr(work.owner, "_collect", no_collect)
    work.s.rollback()
    work.s.begin()
    assert work.owner.current(
        work.s, work.ctx, work.pid, value.material.model_dump(mode="json"), value.source_basis
    )
    # Cross-request persisted reads are legal; an opaque handle still cannot
    # cross the UOW that issued it.
    reject(
        lambda: work.owner.refresh(work.s, work.ctx, work.pid, work.payload, value),
        "FACT_CALLER_UOW_CHANGED",
    )
    work.project.purpose = "changed actual purpose"
    reject(
        lambda: work.owner.current(
            work.s, work.ctx, work.pid, value.material.model_dump(mode="json"), value.source_basis
        ),
        "SOURCE_STALE",
    )


def test_last_actual_source_io_cannot_outlive_current_caller_grant(work, monkeypatch):
    original = preparations.evidence._evidence

    def after_source(*args, **kwargs):
        result = original(*args, **kwargs)
        work.s.rows[Grant][0].expires_at = datetime.now(UTC) - timedelta(microseconds=1)
        return result

    monkeypatch.setattr(preparations.evidence, "_evidence", after_source)
    reject(work.read, "FORBIDDEN_SCOPE")
