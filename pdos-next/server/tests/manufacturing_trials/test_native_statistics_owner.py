"""No-connect original/physical/resource composition, not PG authorization facts.

Actual public owner functions execute. SQL rows and the dependency clock are
explicit IO substitutes; no business writer, source owner or resource reader
is replaced by an always-positive port.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from manufacturing_preparation.test_publication_material_owner import (
    world as native_world,  # noqa: F401
)
from manufacturing_preparation.test_publication_rules import case as publication_case  # noqa: F401
from quality_issues.helpers import fixed_run

from pdos_next.domain.build_execution.models import SampleUnit
from pdos_next.domain.build_operational_facts import service as operational
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    OperationalAsset,
)
from pdos_next.domain.build_operational_facts.schemas import FactInput
from pdos_next.domain.manufacturing_resource_owner import owner as resources
from pdos_next.domain.manufacturing_trials import native_statistics_owner as owner
from pdos_next.domain.manufacturing_trials.native_schemas import StatisticsBasis
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.quality_execution.schemas import SourceRead as QualitySourceRead
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Receipt
from pdos_next.schemas.manufacturing_trials.contracts import (
    Ref,
    ResultRecord,
    UnitOutcome,
    YieldScope,
)
from pdos_next.schemas.quality_issues.contracts import FailureRef, Issue
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest

from .test_native_material_owner import _publish_fixture
from .test_native_material_owner import work as native_work  # noqa: F401


def original(work, value):
    line = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    identity = uuid4()
    row = work.s.add_row(
        Artifact(
            id=identity,
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            owner_id=work.ctx.actor_id,
            title="synthetic native Pilot original",
            visibility="private",
            revision=1,
            status="active",
            original_id=None,
            content=line,
            content_hash=digest(line),
            created_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    row.category_id = work.ctx.category_id
    receipt = work.s.add_row(
        Receipt(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            actor_id=work.ctx.actor_id,
            requester_id=work.ctx.actor_id,
            command_id=uuid4(),
            operation="evidence.artifact.register",
            subject_type="artifact",
            subject_id=identity,
            subject_revision=1,
            visibility="private",
            request_digest=digest(str(identity)),
            intent_digest=digest("explicit pure original registration SQL"),
            run_id=None,
            result={"id": str(identity), "revision": 1, "status": "active"},
        )
    )
    receipt.category_id = work.ctx.category_id
    return SourceRef(
        kind="artifact",
        id=identity,
        revision=1,
        position="line:1;quote_sha256:" + sha256(line.encode()).hexdigest(),
    )


@pytest.fixture
def work(request):
    value = request.getfixturevalue("native_work")
    at = datetime.now(UTC)
    value.statistics = StatisticsBasis(
        site=value.process.site,
        original_timezone="UTC",
        window_start=at - timedelta(hours=2),
        window_end=at - timedelta(hours=1),
        cohort_mode="entire_lot",
        statistics_basis_key="actual-lot-original",
        criterion_id=uuid4(),
        criterion_text=" 原始固定统计口径  保留空格 ",
        minimum_sample=1,
        operation_key="assemble",
        source=value.payload.source,
    )
    value.statistics = value.statistics.model_copy(
        update={
            "source": original(
                value, owner.statistics_declaration(value.payload.pilot_id, value.statistics)
            )
        }
    )
    value.statistics_owner = owner.ActualPilotStatisticsOwner(
        value.s.get_bind(), material_owner=value.owner
    )
    value.record = ResultRecord(
        observation_id=uuid4(),
        expected_pilot_revision=1,
        scope=YieldScope(
            basis=value.payload.basis,
            manufacturing_baseline=None,
            line=None,
            cohort_key=value.statistics.statistics_basis_key,
            window_start=value.statistics.window_start,
            window_end=value.statistics.window_end,
            criterion=Ref(kind="criterion", id=value.statistics.criterion_id, revision=1),
            nature=value.lot.observation_nature,
            minimum_sample=value.statistics.minimum_sample,
        ),
        counts={
            "input_count": 12,
            "output_count": 10,
            "first_pass": 8,
            "first_failed": 2,
            "first_unknown": 0,
            "final_good": 8,
            "reworked_good": 0,
            "scrap": 1,
            "rework_pending": 1,
            "undecided": 0,
            "unprocessed": 2,
            "rework_cycles": 0,
        },
        observed={
            "occurred_at": at - timedelta(hours=1, minutes=1),
            "original_timezone": "UTC",
            "source": value.payload.source,
        },
        source=value.payload.source,
    )
    value.record = value.record.model_copy(
        update={
            "source": original(value, owner.result_values(value.payload.pilot_id, value.record))
        }
    )
    value.read_stats = lambda **kwargs: value.statistics_owner.read(
        value.s,
        value.ctx,
        value.pid,
        value.payload,
        value.statistics,
        record=value.record,
        **kwargs,
    )
    return value


def rebind_originals(work):
    work.statistics = work.statistics.model_copy(
        update={
            "source": original(
                work, owner.statistics_declaration(work.payload.pilot_id, work.statistics)
            )
        }
    )
    work.record = work.record.model_copy(
        update={"source": original(work, owner.result_values(work.payload.pilot_id, work.record))}
    )


def fixed_line(work, monkeypatch):
    """Explicit actual-shaped SQL Fact/Asset rows, read by real resource owners."""
    _publish_fixture(work, monkeypatch)
    selected = work.case.payload.applicability.lines[0]
    work.payload = work.payload.model_copy(
        update={"line": Ref.model_validate(selected.model_dump())}
    )
    at = datetime.now(UTC)
    execution = {
        "purpose": "native-pilot-observation",
        "quantity": "12",
        "unit": "台",
        "site": work.process.site,
        "window": {
            "start": at - timedelta(hours=3),
            "finish": at + timedelta(hours=3),
            "original_timezone": "UTC",
        },
    }
    work.statistics = work.statistics.model_copy(
        update={"operational_scope": operational.OperationalScope.model_validate(execution)}
    )
    work.record = work.record.model_copy(
        update={
            "scope": work.record.scope.model_copy(
                update={
                    "manufacturing_baseline": work.payload.manufacturing_baseline,
                    "line": work.payload.line,
                }
            )
        }
    )
    issuer = operational.configure_local_synthetic(
        work.s.get_bind(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.project.id,
        enabled=True,
        test_marker_verified=True,
    )
    source = work.case.read_only.model_dump(mode="json")
    for artifact in work.s.rows[Artifact]:
        if artifact.created_at is None:
            artifact.created_at = at - timedelta(hours=4)
    data = FactInput.model_validate(
        {
            "build_id": work.build.id,
            "expected_build_revision": 1,
            "scope": execution,
            "external_id": "native-line-fact-pure",
            "valid_from": at - timedelta(hours=4),
            "valid_until": at + timedelta(hours=4),
            "sources": [source],
            "reason": "explicit synthetic saved resource Fact SQL",
            "resources": [
                {
                    "resource": work.payload.line.model_dump(mode="json"),
                    "purposes": [execution["purpose"]],
                    "operation_ids": ["assemble"],
                    "lifecycle": "active",
                    "sources": [source],
                }
            ],
            "requirements": [
                {
                    "operation_key": "assemble",
                    "uses": [{"resource": work.payload.line.model_dump(mode="json"), "units": "1"}],
                    "sources": [source],
                }
            ],
        }
    )
    build, eng, process, build_reads, scope, actual_execution = operational._scope(
        work.s, work.ctx, work.pid, work.build.id, data.scope, write=False
    )
    evidence_reads, _, basis = operational._evidence_basis(
        work.s, work.ctx, work.pid, operational._sources(data), build_reads
    )
    reads = owner._merge_reads(build_reads, evidence_reads)
    fact = work.s.add_row(
        BuildOperationalFact(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            project_id=work.project.id,
            build_id=build.id,
            build_revision=1,
            owner_id=work.ctx.actor_id,
            visibility="private",
            issuer_key=issuer.key,
            issuer_version=issuer.version,
            issuer_epoch=issuer.epoch,
            nature="synthetic",
            external_id=data.external_id,
            series_id=uuid4(),
            revision=1,
            previous_id=None,
            previous_revision=None,
            state="active",
            valid_from=data.valid_from,
            valid_until=data.valid_until,
            binding=operational._binding(build, eng, process, actual_execution),
            data=data.model_dump(mode="json"),
            sources=operational._sources(data),
            required_source_read_set=reads,
            source_basis=basis,
            reason=data.reason,
            fact_sha256="0" * 64,
        )
    )
    fact.fact_sha256 = operational._fact_hash(fact)
    work.s.add_row(
        BuildOperationalCurrent(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            project_id=work.project.id,
            build_id=build.id,
            fact_id=fact.id,
            fact_revision=1,
            epoch=1,
        )
    )
    for kind, aid, key, identity, revision, physical in operational._assets(
        data, work.ctx.tenant_id
    ):
        work.s.add_row(
            OperationalAsset(
                id=aid,
                tenant_id=work.ctx.tenant_id,
                kind=kind,
                external_key=key,
                identity=identity,
                revision=revision,
                data_sha256=operational.digest(physical),
                data={"value": physical, "state": "active"},
                occupancy_epoch=1,
            )
        )
    # Only trigger-maintained dependency-clock SQL is substituted. Real people,
    # issuer, Fact/Current, assets, original/evidence and relation logic remains.
    monkeypatch.setattr(resources, "lock_dependency_clock", lambda *a, **kw: 1)
    monkeypatch.setattr(resources, "closure_stamp", lambda *a, **kw: {"pure_SQL_clock": 1})
    rebind_originals(work)
    return fact


def reject(call, code):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == code


def test_real_original_and_lot_support_raw_facts_without_missing_line_positive(work):
    value = work.read_stats()
    assert value.fixed is value.batch is value.projection is None
    assert value.material["record"]["counts"]["input_count"] == 12
    assert value.material["lot"]["observation"]["nature"] == "synthetic"
    assert "PILOT_LINE_EXECUTION_BINDING_MISSING" in {gap.code for gap in value.gaps}
    assert value.material["qualification"] == "unknown"
    json.dumps(value.source_basis, allow_nan=False)
    assert (
        work.statistics_owner.refresh(
            work.s, work.ctx, work.pid, work.payload, work.statistics, value, record=work.record
        ).material
        == value.material
    )
    assert not (work.s.new or work.s.dirty or work.s.deleted)


def test_actual_fixed_line_fact_original_and_lot_produce_statistics_without_qualification(
    work, monkeypatch
):
    fact = fixed_line(work, monkeypatch)
    value = work.read_stats()
    assert value.fixed.cohort.fixed_input_count == work.lot.observed_unit_count == 12
    assert value.fixed.cohort.unit_refs is None
    assert value.batch.record == work.record
    assert value.projection.counts == work.record.counts
    assert value.material["resource"]["fact"]["id"] == str(fact.id)
    assert value.material["resource"]["execution_authorized"] is False
    assert value.material["resource"]["resources"][0]["acceptance"] == "unknown"
    assert "NATIVE_QUALIFICATION_OWNER_UNCONNECTED" in {gap.code for gap in value.gaps}
    json.dumps(value.source_basis, allow_nan=False)


def test_create_reads_actual_fixed_declaration_without_inventing_observation(work, monkeypatch):
    fixed_line(work, monkeypatch)
    value = work.statistics_owner.read(
        work.s, work.ctx, work.pid, work.payload, work.statistics, record=None
    )
    assert value.fixed is not None and value.batch is value.projection is None
    assert value.material["record"] is None and "record" not in value.material["originals"]


@pytest.mark.parametrize("fault", ("count", "criterion", "nature", "pilot", "unknown_format"))
def test_raw_or_declaration_tampering_is_not_an_unknown_success(work, fault):
    if fault == "count":
        work.record = work.record.model_copy(
            update={
                "counts": work.record.counts.model_copy(update={"scrap": 0, "rework_pending": 2})
            }
        )
    elif fault == "criterion":
        work.statistics = work.statistics.model_copy(update={"criterion_text": "另一原文"})
    elif fault == "nature":
        work.record = work.record.model_copy(
            update={"scope": work.record.scope.model_copy(update={"nature": "real"})}
        )
    elif fault == "pilot":
        work.payload = work.payload.model_copy(update={"pilot_id": uuid4()})
    else:
        work.record = work.record.model_copy(
            update={"source": original(work, {"schema_version": "unsupported"})}
        )
    reject(
        work.read_stats,
        "CONFIGURATION_MISMATCH"
        if fault == "nature"
        else "INTEGRATION_REQUIRED"
        if fault == "unknown_format"
        else "MISSING_REQUIRED_EVIDENCE",
    )


def test_raw_future_observation_is_rejected_after_original_read(work):
    at = datetime.now(UTC) + timedelta(hours=2)
    work.statistics = work.statistics.model_copy(
        update={"window_start": at, "window_end": at + timedelta(hours=1)}
    )
    work.record = work.record.model_copy(
        update={
            "scope": work.record.scope.model_copy(
                update={"window_start": at, "window_end": at + timedelta(hours=1)}
            ),
            "observed": work.record.observed.model_copy(update={"occurred_at": at}),
        }
    )
    rebind_originals(work)
    reject(work.read_stats, "FUTURE_OBSERVATION")


@pytest.mark.parametrize("fault", ("forged", "clock", "material", "caller", "uow", "payload"))
def test_exact_opaque_same_uow_and_payload_binding(work, fault):
    value = work.read_stats()
    if fault == "forged":
        value = replace(value)
    elif fault == "clock":
        object.__setattr__(value, "checked_at", value.checked_at + timedelta(seconds=1))
    elif fault == "material":
        value.material["lot"]["observed_unit_count"] += 1
    elif fault == "caller":
        work.ctx = replace(work.ctx, actor_id=uuid4(), requester_id=uuid4())
    elif fault == "uow":
        work.s.rollback()
        work.s.begin()
    else:
        work.payload = work.payload.model_copy(update={"pilot_id": uuid4()})
    reject(
        lambda: work.statistics_owner.refresh(
            work.s, work.ctx, work.pid, work.payload, work.statistics, value, record=work.record
        ),
        "FACT_CALLER_UOW_CHANGED" if fault in {"caller", "uow"} else "SOURCE_STALE",
    )


def test_unknown_statistics_still_checks_and_preserves_the_real_raw_original(work):
    work.statistics = None
    value = work.read_stats()
    assert value.fixed is value.batch is value.projection is None
    assert value.material["originals"]["record"]["record"]["counts"]["first_pass"] == 8
    assert "PILOT_STATISTICS_DECLARATION_MISSING" in {gap.code for gap in value.gaps}


def test_future_window_keeps_actual_fixed_scope_and_raw_batch_without_ratio(work, monkeypatch):
    fixed_line(work, monkeypatch)
    end = datetime.now(UTC) + timedelta(minutes=10)
    work.statistics = work.statistics.model_copy(update={"window_end": end})
    work.record = work.record.model_copy(
        update={"scope": work.record.scope.model_copy(update={"window_end": end})}
    )
    rebind_originals(work)
    value = work.read_stats()
    assert value.fixed is not None and value.batch.record == work.record
    assert value.projection is None
    assert "PILOT_STATISTICS_WINDOW_NOT_FINISHED" in {gap.code for gap in value.gaps}


def samples(work, count=2):
    result = []
    for index in range(count):
        row = work.s.add_row(
            SampleUnit(
                id=uuid4(),
                tenant_id=work.ctx.tenant_id,
                product_id=work.pid,
                project_id=work.project.id,
                build_id=work.build.id,
                build_revision=1,
                owner_id=work.ctx.actor_id,
                visibility="private",
                revision=1,
                reason="actual SampleUnit SQL substitute",
                sources=work.actual.sources,
                required_source_read_set=work.actual.required_source_read_set,
                status="identified",
                lot_id=work.lot.id,
                allocation_id=uuid4(),
                actual_configuration_id=work.actual.id,
                label=f"fixed-member-{index}",
                operation_key="assemble",
                cavity=None,
                custodian_id=None,
                custodian_label=None,
                location=None,
                destination=None,
                availability="unknown",
                created_at=datetime.now(UTC),
            )
        )
        result.append(Ref(kind="sample", id=row.id, revision=1))
    return tuple(result)


def test_actual_sample_subset_fixes_denominator_and_all_unit_states(work, monkeypatch):
    fixed_line(work, monkeypatch)
    members = samples(work)
    work.statistics = work.statistics.model_copy(
        update={"cohort_mode": "fixed_sampled_subset", "samples": members}
    )
    work.record = work.record.model_copy(
        update={
            "counts": None,
            "units": tuple(
                UnitOutcome(
                    sample=member,
                    first_result="pass",
                    final_state="good",
                    rework_cycles=0,
                    source=work.record.source,
                )
                for member in members
            ),
        }
    )
    rebind_originals(work)
    value = work.read_stats()
    assert value.fixed.cohort.fixed_input_count == 2
    assert value.fixed.cohort.population_count == 12
    assert value.fixed.cohort.unit_refs == members
    assert value.projection.counts.input_count == 2
    assert len(value.material["samples"]) == 2


def test_actual_sample_relation_error_is_not_a_missing_owner_gap(work):
    members = samples(work, 1)
    work.statistics = work.statistics.model_copy(
        update={"cohort_mode": "fixed_sampled_subset", "samples": members}
    )
    work.s.rows[SampleUnit][0].lot_id = uuid4()
    rebind_originals(work)
    reject(work.read_stats, "FORBIDDEN_SCOPE")


def test_fixed_scope_correction_cannot_replace_original_criterion(work, monkeypatch):
    fixed_line(work, monkeypatch)
    previous = work.read_stats().fixed
    work.statistics = work.statistics.model_copy(update={"criterion_id": uuid4()})
    work.record = work.record.model_copy(
        update={
            "scope": work.record.scope.model_copy(
                update={
                    "criterion": Ref(kind="criterion", id=work.statistics.criterion_id, revision=1)
                }
            )
        }
    )
    rebind_originals(work)
    reject(lambda: work.read_stats(previous_scope=previous), "FIXED_SCOPE_CHANGED")


def test_current_resource_unknown_preserves_verified_raw_and_original_scope_obligations(
    work, monkeypatch
):
    fixed_line(work, monkeypatch)
    previous = work.read_stats().fixed
    work.s.rows[BuildOperationalCurrent] = []
    # Actual direct DML/flush discards this cache. Our SQL substitute must
    # reproduce that invalidation instead of mutating rows behind a held proof.
    work.s.info["request_proof"].read_rows.clear()
    value = work.read_stats(previous_scope=previous)
    assert value.fixed is value.batch is value.projection is None
    assert value.material["record"]["observation_id"] == str(work.record.observation_id)
    assert "PILOT_STATISTICS_LINE_IDENTITY_UNKNOWN" in {gap.code for gap in value.gaps}


def test_issue_reference_is_read_by_actual_issue_owner_not_accepted_from_dto(work):
    work.record = work.record.model_copy(
        update={
            "exceptions": (
                {
                    "key": "unavailable-issue",
                    "description": "actual current Issue read required",
                    "source": work.record.source,
                    "issue": Ref(kind="issue", id=uuid4(), revision=1),
                },
            )
        }
    )
    work.record = ResultRecord.model_validate(work.record.model_dump(mode="json", warnings=False))
    rebind_originals(work)
    reject(work.read_stats, "FORBIDDEN_SCOPE")


def test_real_issue_view_typed_read_set_merges_into_native_raw_statistics(work):
    """Real quality reader/DTOs over SQL rows, with source status still unknown.

    This is a read-set adaptation test, not a successful failure verification or
    PG authorization proof. No quality/source owner is replaced with a port.
    """
    run = fixed_run()
    issue = Issue(
        id=uuid4(),
        revision=1,
        scope=work.case.scope,
        audience=(f"category:{work.ctx.category_id}",),
        title="Saved synthetic Issue",
        failures=(
            FailureRef(
                identity="stored-synthetic-failure",
                run={"id": run.id, "revision": run.revision},
                measurement_id=run.measurements[0].id,
                executor_id=work.ctx.actor_id,
                coverage=run.coverage[0],
                build=run.build,
                sample=run.samples[0],
                criterion=work.payload.source,
                method=work.payload.source,
                source=work.payload.source,
                nature="synthetic",
            ),
        ),
    )
    raw = issue.model_dump(mode="json")
    row = work.s.add_row(
        QualityIssueVersion(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            project_id=work.project.id,
            issue_id=issue.id,
            revision=1,
            owner_id=work.ctx.actor_id,
            writer_id=work.ctx.actor_id,
            visibility="private",
            purpose=work.project.purpose,
            status=issue.status,
            operation="quality.issue.create",
            issue_snapshot=raw,
            snapshot_sha256=digest(raw),
            source_basis={},
            created_at=datetime.now(UTC),
            reason="explicit saved Issue SQL substitute",
        )
    )
    work.s.add_row(
        QualityIssueCurrent(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            project_id=work.project.id,
            issue_id=issue.id,
            issue_version_id=row.id,
            issue_revision=1,
            epoch=1,
        )
    )
    _, actual_view = owner.quality.get_issue_for_change(
        work.s, work.ctx, work.pid, issue.id, 1, write=False
    )
    assert actual_view.is_current
    assert all(
        isinstance(value, QualitySourceRead) for value in actual_view.required_source_read_set
    )
    work.record = ResultRecord.model_validate(
        work.record.model_copy(
            update={
                "exceptions": (
                    {
                        "key": "saved-issue",
                        "description": "actual current Issue reference",
                        "source": work.record.source,
                        "issue": Ref(kind="issue", id=issue.id, revision=1),
                    },
                )
            }
        ).model_dump(mode="json", warnings=False)
    )
    rebind_originals(work)
    value = work.read_stats()
    assert {
        (read.artifact_id, read.expected_revision) for read in actual_view.required_source_read_set
    } <= {(read.artifact_id, read.expected_revision) for read in value.required_source_read_set}
    assert value.material["issues"][0]["issue_id"] == str(issue.id)
    assert "PILOT_ISSUE_SOURCE_RECHECK_REQUIRED" in {gap.code for gap in value.gaps}
    assert value.projection is None and value.material["qualification"] == "unknown"


def test_last_other_owner_io_cannot_leave_changed_original_as_verified(work, monkeypatch):
    read_original = owner._original
    changed = False

    def after_original(*args, **kwargs):
        nonlocal changed
        result = read_original(*args, **kwargs)
        if not changed:
            changed = True
            next(
                row for row in work.s.rows[Artifact] if row.id == work.statistics.source.id
            ).status = "withdrawn"
        return result

    monkeypatch.setattr(owner, "_original", after_original)
    reject(work.read_stats, "SOURCE_UNAVAILABLE")


def test_shared_physical_and_statistics_collect_once_then_cached_read_has_no_sql(work, monkeypatch):
    calls = {"physical": 0, "statistics": 0}
    for instance, key in ((work.owner, "physical"), (work.statistics_owner, "statistics")):
        collect = instance._collect

        def counted(*args, _collect=collect, _key=key):
            calls[_key] += 1
            return _collect(*args)

        monkeypatch.setattr(instance, "_collect", counted)
    physical = work.read()
    value = work.read_stats()
    query_count = len(work.s.queries)
    assert work.read_stats() is value
    assert work.read() is physical
    assert len(work.s.queries) == query_count
    assert calls == {"physical": 1, "statistics": 1}


@pytest.mark.parametrize("fault", ("sample", "resource_current", "asset", "issuer", "source"))
def test_light_statistics_current_rejects_actual_direct_dependency_drift(work, monkeypatch, fault):
    fixed_line(work, monkeypatch)
    members = samples(work, 1)
    work.statistics = work.statistics.model_copy(
        update={"cohort_mode": "fixed_sampled_subset", "samples": members}
    )
    work.record = work.record.model_copy(
        update={
            "counts": None,
            "units": (
                UnitOutcome(
                    sample=members[0],
                    first_result="pass",
                    final_state="good",
                    rework_cycles=0,
                    source=work.record.source,
                ),
            ),
        }
    )
    rebind_originals(work)
    value = work.read_stats()

    def forbidden(*args, **kwargs):
        raise AssertionError("light check must not rebuild owners or read original bytes")

    # Owner callables themselves remain installed (and runtime-bound); this
    # guard catches their internal recollection if the light path invokes it.
    monkeypatch.setattr(work.statistics_owner, "_collect", forbidden)
    monkeypatch.setattr(work.owner, "_collect", forbidden)
    assert work.statistics_owner.current(
        work.s, work.ctx, work.pid, value.material, value.source_basis
    )
    if fault == "sample":
        work.s.rows[SampleUnit][0].revision += 1
    elif fault == "resource_current":
        work.s.rows[BuildOperationalCurrent][0].epoch += 1
    elif fault == "asset":
        work.s.rows[OperationalAsset][0].data_sha256 = "f" * 64
    elif fault == "issuer":
        issuer = work.s.rows[BuildOperationalFact][0].issuer_key
        work.s.get_bind()._pdos_operational_issuer_epochs[issuer] += 1
    else:
        next(
            row for row in work.s.rows[Artifact] if row.id == work.statistics.source.id
        ).content_hash = "e" * 64
    work.s.info["request_proof"].read_rows.clear()
    work.s.info["request_proof"].scalar_rows.clear()
    reject(
        lambda: work.statistics_owner.current(
            work.s, work.ctx, work.pid, value.material, value.source_basis
        ),
        "SOURCE_STALE",
    )
