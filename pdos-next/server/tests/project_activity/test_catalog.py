"""Metadata/SQL-only contracts for the project activity source catalogue."""

import re
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import BindParameter

from pdos_next import (  # initialize shared model relationships for independent collection
    models as registered_models,  # noqa: F401
)
from pdos_next.domain.build_execution.models import ActualConfiguration, SampleUnit
from pdos_next.domain.builds.models import BuildReadiness
from pdos_next.domain.configurations.models import (
    BomRevision,
    EngineeringConfiguration,
    ProcessRevision,
)
from pdos_next.domain.external_handoff.models import ExternalDeliveryIntent
from pdos_next.domain.preproject.models import ProposalDecision
from pdos_next.domain.projects.models import TaskDependency
from pdos_next.domain.verification_launch.models import VerificationLaunchFact
from pdos_next.domain.verification_results.models import MeasurementRecord
from pdos_next.domain.work_management.models import ProjectStatusUpdate, WorkTaskVersion
from pdos_next.project_activity_catalog import OPERATION_LABELS, SOURCES, ActivitySource
from pdos_next.service import EVENTS


def _source(model):
    return next(source for source in SOURCES if source.model is model)


def _sql(source, tenant_id, product_id, project_id):
    model = source.model
    product = model.product_id if source.product_column is None else source.product_column
    identity = model.id if source.subject_id is None else source.subject_id
    revision = model.revision if source.subject_revision is None else source.subject_revision
    project = (
        model.project_id == project_id
        if source.project_predicate is None
        else source.project_predicate(source, tenant_id, product_id, project_id)
    )
    return str(
        select(identity, revision, *source.columns.values())
        .select_from(model)
        .where(model.tenant_id == tenant_id, product == product_id, project)
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def test_descriptors_and_column_selections_cannot_be_mutated_after_registration():
    source = _source(WorkTaskVersion)
    assert isinstance(SOURCES, tuple) and isinstance(source, ActivitySource)
    with pytest.raises(FrozenInstanceError):
        source.subject_kind = "some_other_subject"
    with pytest.raises(TypeError):
        source.columns["summary"] = WorkTaskVersion.body


def test_every_operation_has_one_primary_subject_and_a_real_registered_event():
    pairs, operations = set(), set()
    for source in SOURCES:
        assert source.operations and isinstance(source.operations, tuple)
        assert source.subject_kind and source.label and source.view
        for operation in source.operations:
            assert operation in EVENTS and EVENTS[operation]
            pair = source.subject_kind, operation
            assert pair not in pairs, "A command must not duplicate its receipt activity"
            pairs.add(pair)
            operations.add(operation)
    assert operations == set(OPERATION_LABELS)
    for operation in operations:
        if operation.endswith(".compute"):
            assert "计算" in OPERATION_LABELS[operation]
            assert not any(
                word in OPERATION_LABELS[operation] for word in ("通过", "批准", "齐套完成")
            )


def test_destinations_are_actual_existing_workspace_panels():
    workspace = Path(__file__).resolve().parents[3] / "web/src/components/workspace.tsx"
    panels = set(re.findall(r'<WorkspacePanel\b[^>]*\bname="([^"]+)"', workspace.read_text()))
    assert panels and {source.view for source in SOURCES} <= panels
    assert _source(WorkTaskVersion).view == "plan"


def test_minimal_projections_compile_for_every_real_model_without_private_documents():
    allowed = {
        "title",
        "summary",
        "next_steps",
        "sources",
        "task_refs",
        "occurred_at",
        "original_timezone",
    }
    whole_private = {
        "body",
        "command",
        "source_basis",
        "original",
        "input_snapshot",
        "content",
        "material_snapshot",
    }
    scope = uuid4(), uuid4(), uuid4()
    for source in SOURCES:
        assert set(source.columns) <= allowed
        for expression in source.columns.values():
            clause = (
                expression.__clause_element__()
                if hasattr(expression, "__clause_element__")
                else expression
            )
            # JSON title selections are expressions over a body, never the body itself.
            assert getattr(clause, "name", None) not in whole_private
        sql = _sql(source, *scope)
        assert "SELECT" in sql and source.model.__tablename__ in sql
        assert all(str(identity) in sql for identity in scope)
        assert "FOR UPDATE" not in sql and not any(
            word in sql for word in ("INSERT INTO", "DELETE FROM", "UPDATE ")
        )


def test_current_capture_and_child_rows_do_not_create_duplicate_activities():
    models = {source.model for source in SOURCES}
    assert not models & {
        SampleUnit,
        ExternalDeliveryIntent,
        TaskDependency,
        VerificationLaunchFact,
        MeasurementRecord,
    }
    assert all("current" not in source.model.__tablename__ for source in SOURCES)
    assert all("capture" not in source.model.__tablename__ for source in SOURCES)
    change = next(source for source in SOURCES if "change.order.approve" in source.operations)
    assert change.subject_kind == "change_request"
    imported = next(source for source in SOURCES if "test.results.import" in source.operations)
    assert imported.subject_kind == "test_run"


@pytest.mark.parametrize("model", [EngineeringConfiguration, ProcessRevision])
def test_configuration_scope_uses_fixed_planned_and_actual_links_not_product_membership(model):
    source = _source(model)
    scope = uuid4(), uuid4(), uuid4()
    sql = _sql(source, *scope)
    assert "关联" in source.label and "关联" in OPERATION_LABELS[source.operations[0]]
    assert "EXISTS" in sql and " OR " in sql
    assert "builds.project_id" in sql and "actual_configurations.project_id" in sql
    assert "builds.tenant_id" in sql and "actual_configurations.tenant_id" in sql
    assert "builds.product_id" in sql and "actual_configurations.product_id" in sql
    key = "engineering" if model is EngineeringConfiguration else "manufacturing"
    assert f"builds.{key}_configuration_id = {model.__tablename__}.id" in sql
    assert f"actual_configurations.actual_{key}_revision = {model.__tablename__}.revision" in sql
    assert _sql(source, scope[0], scope[1], uuid4()) != sql


def test_bom_scope_follows_fixed_engineering_bom_revision_in_both_build_paths():
    sql = _sql(_source(BomRevision), uuid4(), uuid4(), uuid4())
    assert "builds.project_id" in sql and "actual_configurations.project_id" in sql
    assert "engineering_configurations.bom_id = bom_revisions.id" in sql
    assert "engineering_configurations.bom_revision = bom_revisions.revision" in sql
    assert (
        "engineering_configurations.revision = actual_configurations.actual_engineering_revision"
        in sql
    )


def test_readiness_resolves_its_actual_build_and_fixed_revision():
    sql = _sql(_source(BuildReadiness), uuid4(), uuid4(), uuid4())
    assert "builds.id = build_readiness.build_id" in sql
    assert "builds.revision = build_readiness.build_revision" in sql
    assert "builds.project_id" in sql


@pytest.mark.parametrize(
    "model", [EngineeringConfiguration, ProcessRevision, BomRevision, BuildReadiness]
)
def test_indirect_scope_correlates_the_actual_outer_project_in_receipt_proofs(model):
    source = _source(model)
    project = registered_models.Project
    predicate = source.project_predicate(source, uuid4(), project.product_id, project.id)
    sql = str(
        select(model.id)
        .select_from(model)
        .join(project, predicate)
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "JOIN projects ON" in sql
    assert ", projects" not in sql
    assert not re.search(r"FROM projects\b", sql)
    assert "project_id = projects.id" in sql


def test_g0_uses_actual_decision_project_product_and_proposal_receipt_subject():
    source = _source(ProposalDecision)
    assert source.subject_kind == "proposal" and source.operations == ("proposal.g0.decide",)
    assert source.subject_id.compare(ProposalDecision.proposal_id.__clause_element__())
    assert source.product_column.compare(ProposalDecision.created_product_id.__clause_element__())
    assert (
        isinstance(source.subject_revision, BindParameter) and source.subject_revision.value is None
    )
    assert hasattr(source.model, "receipt_id")
    sql = _sql(source, uuid4(), uuid4(), uuid4())
    assert "proposal_decisions.created_project_id" in sql
    assert "proposal_decisions.created_product_id" in sql
    assert "proposal_decisions.outcome = 'approved'" in sql
    assert "proposal_decisions.receipt_id IS NOT NULL" in sql


def test_named_status_keeps_its_explicit_published_text_and_fixed_task_references():
    source = _source(ProjectStatusUpdate)
    assert source.columns["summary"] is ProjectStatusUpdate.fact_summary
    assert source.columns["next_steps"] is ProjectStatusUpdate.next_steps
    assert source.columns["task_refs"] is ProjectStatusUpdate.task_refs
    assert source.model.receipt_id is ProjectStatusUpdate.receipt_id


def test_actual_configuration_keeps_observation_clock_without_a_fabricated_timezone():
    source = _source(ActualConfiguration)
    assert source.columns["occurred_at"] is ActualConfiguration.observed_at
    assert "original_timezone" not in source.columns


def test_work_occurrence_uses_only_the_current_action_clock_not_carried_history():
    source = _source(WorkTaskVersion)
    for key, field in (("occurred_at", "actual_at"), ("original_timezone", "original_timezone")):
        sql = str(
            select(source.columns[key]).compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for operation in ("start", "submit", "review"):
            assert f"work.task.{operation}" in sql
        for path in ("actual_start", "submission", "review", field):
            assert path in sql
        assert "ELSE" not in sql  # no known actual clock on create/assign/accept
