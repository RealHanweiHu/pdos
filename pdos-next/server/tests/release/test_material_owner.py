"""Actual release readers over explicit no-connect SQL/original fixtures.

These are owner composition and scope/watermark tests, not PG/RLS, qualification
or a release decision. Existing original readers and immutable snapshot checks
run unchanged; no business owner is replaced by a positive port.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from manufacturing_preparation.test_publication_material_owner import (
    world as native_world,  # noqa: F401
)
from manufacturing_preparation.test_publication_rules import case as publication_case  # noqa: F401
from manufacturing_trials.test_native_material_owner import work as native_work  # noqa: F401
from manufacturing_trials.test_native_statistics_owner import fixed_line
from manufacturing_trials.test_native_statistics_owner import work as statistics_work  # noqa: F401
from quality_issues.helpers import fixed_run
from sqlalchemy import select

from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.domain.products.models import DefinitionSource
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.release import material_owner as owner
from pdos_next.domain.release import rules, schemas
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from pdos_next.schemas.change_control.contracts import ChangeRequest
from pdos_next.schemas.quality_issues.contracts import FailureRef, Issue
from pdos_next.schemas.verification.contracts import TestRun as Run
from pdos_next.service import Context, digest


@pytest.fixture
def work(request, monkeypatch):
    physical = request.getfixturevalue("statistics_work")
    execute = physical.s.execute

    def quote_watermarks(statement, *args, **kwargs):
        if any(column.key == "quote_sha256" for column in statement.selected_columns):
            rows = physical.s.scalars(select(DefinitionSource).where(*statement._where_criteria))
            values = [
                {
                    column.key: sha256(row.quote.encode()).hexdigest()
                    if column.key == "quote_sha256"
                    else getattr(row, column.key)
                    for column in statement.selected_columns
                }
                for row in rows
            ]
            return SimpleNamespace(mappings=lambda: values)
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(physical.s, "execute", quote_watermarks)
    payload = schemas.PackageAssemblePayload(
        project_id=physical.project.id,
        subject_config={
            "definition": {
                "id": physical.engineering.definition_id,
                "revision": physical.engineering.definition_revision,
            },
            "engineering_configuration": (
                physical.payload.basis.engineering_configuration.model_dump(exclude={"kind"})
            ),
            "manufacturing_configuration": physical.payload.basis.process_revision.model_dump(
                exclude={"kind"}
            ),
        },
        release_scope={
            "quantity": "5",
            "unit": physical.lot.unit,
            "lots": [{"id": physical.lot.id, "revision": 1}],
            "site": physical.process.site,
            "regions": ["CN"],
        },
        purpose=physical.project.purpose,
        sources=(physical.payload.source.model_dump(mode="json"),),
        reason="固定真实本批材料，不声称具备放行政策或资产资格",
    )
    reader = owner.ActualReleaseMaterialOwner(physical.s.get_bind())
    value = SimpleNamespace(**vars(physical), release_payload=payload, release_owner=reader)
    value.read_release = lambda: reader.read(value.s, value.ctx, value.pid, value.release_payload)
    return value


def reject(call, code="SOURCE_STALE"):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == code


def test_actual_fixed_physical_inputs_are_read_without_inventing_release_policy(work):
    result = work.read_release()
    assert result.material.policy is None and result.material.checks == ()
    assert result.gaps == ("RELEASE_POLICY_MISSING",)
    assert result.material.subject_config == work.release_payload.subject_config
    assert {value.ref for value in result.material.objects} == set(
        rules.selected_objects(work.release_payload)
    )
    plan = rules.assemble(work.release_payload, result.material, owner_id=work.ctx.requester_id)
    assessment = rules.evaluate(
        plan, "manufacturing", work.release_payload.release_scope, at=datetime.now(UTC)
    )
    assert assessment.state == "UNKNOWN" and assessment.unknown == ("RELEASE_POLICY_MISSING",)
    assert result.source_basis["artifacts"] and result.required_source_read_set
    json.dumps(result.source_basis, allow_nan=False)
    assert work.release_owner.current(work.s, work.ctx, work.pid, result)
    assert not (work.s.new or work.s.dirty or work.s.deleted)


def test_same_uow_collects_once_and_cache_hit_has_no_select(work, monkeypatch):
    collect = work.release_owner._collect
    calls = []

    def counted(*args):
        calls.append(True)
        return collect(*args)

    monkeypatch.setattr(work.release_owner, "_collect", counted)
    result = work.read_release()
    queries = len(work.s.queries)
    assert work.read_release() is result
    assert len(calls) == 1 and len(work.s.queries) == queries


@pytest.mark.parametrize("fault", ("config", "quantity", "project", "shared", "exception"))
def test_no_fixed_scope_or_policy_fact_is_inferred_from_payload(work, fault):
    expected = "CONFIGURATION_MISMATCH"
    if fault == "config":
        work.actual.actual_manufacturing_configuration_id = uuid4()
    elif fault == "quantity":
        work.release_payload = work.release_payload.model_copy(
            update={
                "release_scope": work.release_payload.release_scope.model_copy(
                    update={"quantity": Decimal(work.lot.observed_unit_count + 1)}
                )
            }
        )
        expected = "FIXED_DENOMINATOR_CHANGED"
    elif fault == "project":
        work.release_payload = work.release_payload.model_copy(update={"project_id": uuid4()})
        expected = "FORBIDDEN_SCOPE"
    elif fault == "shared":
        work.release_payload = work.release_payload.model_copy(update={"visibility": "category"})
        expected = "FORBIDDEN_SCOPE"
    else:
        work.release_payload = work.release_payload.model_copy(
            update={"exceptions": (schemas.VersionRef(id=uuid4(), revision=1),)}
        )
        expected = "FORBIDDEN_SCOPE"
    reject(work.read_release, expected)


@pytest.mark.parametrize("fault", ("copy", "material", "caller", "uow", "source", "configuration"))
def test_opaque_binding_and_real_direct_watermark_changes_are_rejected(work, fault):
    result = work.read_release()
    expected = "SOURCE_STALE"
    if fault == "copy":
        result = replace(result)
    elif fault == "material":
        result.source_basis["artifacts"].clear()
    elif fault == "caller":
        work.ctx = Context(work.ctx.tenant_id, uuid4(), uuid4(), category_id=work.ctx.category_id)
        expected = "FORBIDDEN_SCOPE"
    elif fault == "uow":
        work.s.rollback()
        work.s.begin()
        expected = "FACT_CALLER_UOW_CHANGED"
    elif fault == "source":
        next(
            value for value in work.s.rows[Artifact] if value.id == work.payload.source.id
        ).status = "withdrawn"
        expected = "SOURCE_UNAVAILABLE"
    else:
        work.process.revision += 1
    reject(lambda: work.release_owner.current(work.s, work.ctx, work.pid, result), expected)


def test_persisted_material_current_uses_direct_rows_without_rebuilding_owner(work, monkeypatch):
    result = work.read_release()

    def forbidden(*args, **kwargs):
        raise AssertionError("current must not collect owners or reread original bytes")

    monkeypatch.setattr(work.release_owner, "_collect", forbidden)
    work.s.rollback()
    work.s.begin()
    assert work.release_owner.current(
        work.s, work.ctx, work.pid, result.material.model_dump(mode="json"), result.source_basis
    )
    work.project.purpose = "actual changed purpose"
    reject(
        lambda: work.release_owner.current(
            work.s, work.ctx, work.pid, result.material.model_dump(mode="json"), result.source_basis
        )
    )


def test_real_current_fact_asset_and_publication_do_not_grant_qualification(work, monkeypatch):
    fact = fixed_line(work, monkeypatch)
    work.release_payload = work.release_payload.model_copy(
        update={
            "manufacturing_publication": schemas.VersionRef.model_validate(
                work.payload.manufacturing_baseline.model_dump(exclude={"kind"})
            ),
            "release_scope": work.release_payload.release_scope.model_copy(
                update={
                    "lines": (
                        schemas.VersionRef(
                            id=work.payload.line.id, revision=work.payload.line.revision
                        ),
                    )
                }
            ),
        }
    )
    result = work.read_release()
    assert result.material.policy is None
    assert "RESOURCE_QUALIFICATION_OWNER_UNCONNECTED" in result.gaps
    assert result.source_basis["line_links"][0]["facts"][0]["fact_id"] == str(fact.id)
    assert {value.ref.kind for value in result.material.objects} >= {
        "line",
        "manufacturing_publication",
    }
    # The saved-publication fixture substitutes retained professional IO. Its
    # DTO alone cannot satisfy this reader's actual signature Current guard.
    reject(lambda: work.release_owner.current(work.s, work.ctx, work.pid, result))


def _run(work):
    raw = fixed_run().model_dump(mode="json")
    source = work.payload.source.model_dump(mode="json")

    def sources(value):
        if isinstance(value, dict):
            if {"kind", "id", "revision", "position"} <= set(value):
                return source
            return {key: sources(child) for key, child in value.items()}
        return [sources(child) for child in value] if isinstance(value, list) else value

    raw = sources(raw)
    raw["scope"] = work.case.scope.model_dump(mode="json")
    raw["build"].update(
        id=str(work.build.id), product_id=str(work.pid), project_id=str(work.project.id)
    )
    run = Run.model_validate(raw)
    row = work.s.add_row(
        VerificationRunVersion(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            project_id=work.project.id,
            build_id=work.build.id,
            build_revision=1,
            request_id=run.request_id,
            request_revision=run.request_revision,
            run_id=run.id,
            revision=run.revision,
            owner_id=work.ctx.actor_id,
            writer_id=work.ctx.actor_id,
            visibility="private",
            status=run.status,
            operation="test.results.import",
            run_snapshot=run.model_dump(mode="json"),
            execution_plan={},
            plan_sha256=digest({}),
            snapshot_sha256=digest(run.model_dump(mode="json")),
            sources=[source],
            required_source_read_set=work.actual.required_source_read_set,
        )
    )
    work.s.add_row(
        VerificationRunCurrent(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            request_id=run.request_id,
            run_id=run.id,
            run_version_id=row.id,
            run_revision=row.revision,
        )
    )
    return run


def test_actual_run_issue_and_change_snapshots_are_fixed_without_closing_issue(work):
    run = _run(work)
    issue = Issue(
        id=uuid4(),
        revision=1,
        scope=work.case.scope,
        audience=(f"category:{work.ctx.category_id}",),
        title="实际SQL形状的未关闭问题",
        failures=(
            FailureRef(
                identity="stored-failure",
                run={"id": run.id, "revision": run.revision},
                measurement_id=run.measurements[0].id,
                executor_id=work.ctx.actor_id,
                coverage=run.coverage[0],
                build=run.build,
                sample=run.samples[0],
                nature="synthetic",
                criterion=work.payload.source,
                method=work.payload.source,
                source=work.payload.source,
            ),
        ),
    )
    source = work.payload.source.model_dump(mode="json")
    row = work.s.add_row(
        QualityIssueVersion(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            project_id=work.project.id,
            issue_id=issue.id,
            revision=1,
            owner_id=work.ctx.actor_id,
            visibility="private",
            status="open",
            issue_snapshot=issue.model_dump(mode="json"),
            snapshot_sha256=digest(issue.model_dump(mode="json")),
            sources=[source],
            required_source_read_set=work.actual.required_source_read_set,
        )
    )
    pointer = work.s.add_row(
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
    change = ChangeRequest(
        id=uuid4(),
        revision=1,
        scope=work.case.scope,
        audience=issue.audience,
        requester_id=work.ctx.actor_id,
        title="未完成变更保持原义",
        reason="固定原文",
        roots=({"kind": "issue", "id": issue.id, "revision": 1},),
        references=(),
        sources=(work.payload.source,),
    )
    version = work.s.add_row(
        ChangeRequestVersion(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            project_id=work.project.id,
            change_id=change.id,
            revision=1,
            owner_id=work.ctx.actor_id,
            visibility="private",
            status=change.status,
            operation="change.request.create",
            request_snapshot=change.model_dump(mode="json"),
            request_sha256=digest(change.model_dump(mode="json")),
            sources=[source],
            required_source_read_set=work.actual.required_source_read_set,
        )
    )
    work.s.add_row(
        ChangeCurrent(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            product_id=work.pid,
            change_id=change.id,
            version_id=version.id,
            revision=1,
        )
    )
    work.release_payload = work.release_payload.model_copy(
        update={
            "verifications": (schemas.VersionRef(id=run.id, revision=run.revision),),
            "residuals": (
                schemas.ObjectRef(kind="issue", id=issue.id, revision=1),
                schemas.ObjectRef(kind="change", id=change.id, revision=1),
            ),
        }
    )
    result = work.read_release()
    assert {value.ref.kind for value in result.material.objects} >= {"test_run", "issue", "change"}
    assert issue.status == "open" and result.material.policy is None
    assert work.release_owner.current(work.s, work.ctx, work.pid, result)
    pointer.issue_revision += 1
    reject(lambda: work.release_owner.current(work.s, work.ctx, work.pid, result))
