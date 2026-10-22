"""Relative clocks use the actual owner interface without replacing the service identity."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from pdos_next.domain.automations import trigger_sources as sources
from pdos_next.domain.automations.schemas import Conditions, RelativeTrigger
from pdos_next.domain.projects.models import PlanRevision, ProjectTask
from pdos_next.domain.work_management.models import WorkTaskCurrent
from pdos_next.domain.work_management.schemas import CommitmentSnapshot, TaskSnapshot
from pdos_next.errors import DomainError
from pdos_next.service import Context

AT = datetime(2026, 10, 18, 10, tzinfo=UTC)
CLOCKS = ("earliest_start", "earliest_finish", "latest_start", "latest_finish")


class ReadSQL:
    def __init__(self, case):
        self.case, self.statements = case, []

    def get(self, model, identity):
        assert model is PlanRevision and identity == self.case.project.current_plan_id
        self.statements.append((model, identity))
        return self.case.plan

    def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        assert entity in {ProjectTask, WorkTaskCurrent}
        self.statements.append(statement)
        return self.case.plan_task if entity is ProjectTask else self.case.task_pointer

    def add(self, *args):
        raise AssertionError("Trigger source reads cannot add facts")

    def execute(self, *args):
        raise AssertionError("No command, write or alternate identity transport")

    def flush(self):
        raise AssertionError("Read-only trigger material cannot flush business facts")


@pytest.fixture
def case(monkeypatch):
    tenant, category, ai, owner_id, pid, project_id, task_id, promisor = (uuid4() for _ in range(8))
    ctx = Context(tenant, ai, owner_id, category_id=category)
    scope = {
        "tenant_id": tenant,
        "category_id": category,
        "product_id": pid,
        "project_id": project_id,
    }
    project = SimpleNamespace(
        **{key: value for key, value in scope.items() if key != "project_id"},
        id=project_id,
        current_plan_id=uuid4(),
        revision=2,
    )
    plan = SimpleNamespace(**scope, id=project.current_plan_id, revision=1, status="applied")
    calendar = {
        "key": "original-calendar",
        "version": "1",
        "timezone": "Asia/Shanghai",
        "timezone_rules_sha256": "a" * 64,
    }
    plan_task = SimpleNamespace(
        **scope,
        id=task_id,
        key="DVT",
        plan_id=plan.id,
        forecast={
            "key": "DVT",
            "calendar_ref": calendar,
            **{clock: (AT + timedelta(hours=i)).isoformat() for i, clock in enumerate(CLOCKS)},
        },
    )
    commitment_id, series = uuid4(), uuid4()
    commitment = SimpleNamespace(
        **scope,
        id=commitment_id,
        revision=3,
        series_id=series,
        task_id=task_id,
        task_revision=5,
        promisor_id=promisor,
        recipient_id=owner_id,
        promised_at=AT,
        original_timezone="Asia/Shanghai",
        calendar_id=None,
        owner_id=owner_id,
        visibility="category",
    )
    commitment_pointer = SimpleNamespace(
        **scope,
        version_id=commitment_id,
        revision=3,
        series_id=series,
        task_id=task_id,
        promisor_id=promisor,
        recipient_id=owner_id,
    )
    promise = CommitmentSnapshot(
        revision=3,
        task_id=task_id,
        task_revision=5,
        promisor_id=promisor,
        recipient_id=owner_id,
        outcome_keys=("report",),
        promised_at=AT,
        original_timezone="Asia/Shanghai",
        calendar_id=None,
        recorded_at=AT,
    )
    task_snapshot = TaskSnapshot(
        task_id=task_id,
        revision=5,
        state="accepted",
        title="Actual task",
        goal="Actual result",
        outcomes=[{"key": "report", "text": "Report", "required": True}],
        assignee_id=promisor,
        recipient_id=owner_id,
    )
    task_row = SimpleNamespace(**scope, id=uuid4(), task_id=task_id, revision=5, state="accepted")
    task_pointer = SimpleNamespace(
        **scope, version_id=task_row.id, task_id=task_id, revision=5, state="accepted"
    )
    value = SimpleNamespace(
        ctx=ctx,
        pid=pid,
        project=project,
        plan=plan,
        plan_task=plan_task,
        commitment=commitment,
        commitment_pointer=commitment_pointer,
        promise=promise,
        task_snapshot=task_snapshot,
        task_row=task_row,
        task_pointer=task_pointer,
    )
    value.sql = ReadSQL(value)
    value.project_read = Mock(return_value=project)
    value.commitment_read = Mock(return_value=(commitment, promise, commitment_pointer))
    value.task_read = Mock(return_value=(task_row, task_snapshot, task_pointer))
    value.access = Mock()
    value.fulfillment_read = Mock(return_value=False)
    monkeypatch.setattr(sources.owner, "project", value.project_read)
    monkeypatch.setattr(sources.owner, "commitment", value.commitment_read)
    monkeypatch.setattr(sources.owner, "task", value.task_read)
    monkeypatch.setattr(sources, "require_access", value.access)
    monkeypatch.setattr(sources, "commitment_fulfilled", value.fulfillment_read)
    return value


def relative(case, *, source_kind="plan_task", **values):
    config = {
        "source_kind": source_kind,
        "project_id": case.project.id,
        "task_id": case.plan_task.id,
        "clock": "latest_finish",
        "offset_seconds": -60,
    }
    if source_kind == "commitment":
        config.update(
            clock="promised_at",
            promisor_id=case.commitment.promisor_id,
            recipient_id=case.commitment.recipient_id,
        )
    return SimpleNamespace(product_id=case.pid, trigger_config=RelativeTrigger(**(config | values)))


def condition(case, *, product=True, **values):
    return SimpleNamespace(
        product_id=case.pid if product else None,
        conditions=Conditions(task_id=case.task_pointer.task_id, **values),
    )


@pytest.mark.parametrize("clock,index", list(zip(CLOCKS, range(4), strict=True)))
def test_plan_uses_exact_selected_forecast_clock_and_original_context(case, clock, index):
    spec = relative(case, clock=clock, offset_seconds=90)
    # Saved JSON and typed declarations resolve through the same closed config.
    spec.trigger_config = spec.trigger_config.model_dump(mode="json")
    first = sources.relative_due(case.sql, case.ctx, spec)
    assert first["scheduled_at"] == AT + timedelta(hours=index, seconds=90)
    assert first["origin"]["source_at"] == (AT + timedelta(hours=index)).isoformat()
    assert first["origin"]["plan_id"] == str(case.plan.id)
    assert first["origin"]["plan_revision"] == 1 and first["origin"]["task_key"] == "DVT"
    assert first["origin"]["calendar_ref"] == case.plan_task.forecast["calendar_ref"]
    assert first["origin"]["original_timezone"] == "Asia/Shanghai"
    assert first == sources.relative_due(case.sql, case.ctx, spec)
    assert len(first["target_key"]) < 200
    json.dumps(first["origin"])
    case.project_read.assert_called_with(case.sql, case.ctx, case.pid, case.project.id)
    case.commitment_read.assert_not_called()
    params = case.sql.statements[1].compile().params.values()
    assert {
        case.ctx.tenant_id,
        case.ctx.category_id,
        case.pid,
        case.project.id,
        case.plan.id,
        case.plan_task.id,
    } <= set(params)
    assert case.ctx.actor_id != case.ctx.requester_id


def test_plan_explicit_null_is_unknown_but_absent_field_or_current_plan_is_not_a_fake_empty(case):
    spec = relative(case)
    case.plan_task.forecast["latest_finish"] = None
    result = sources.relative_due(case.sql, case.ctx, spec)
    assert result["scheduled_at"] is None and result["origin"]["source_at"] is None
    del case.plan_task.forecast["latest_finish"]
    with pytest.raises(DomainError) as missing:
        sources.relative_due(case.sql, case.ctx, spec)
    assert missing.value.reason == "INTEGRITY_MISMATCH"
    case.project.current_plan_id = None
    with pytest.raises(DomainError):
        sources.relative_due(case.sql, case.ctx, spec)


@pytest.mark.parametrize("field", ["category_id", "product_id", "project_id", "plan_id"])
def test_plan_task_from_a_different_current_scope_is_rejected(case, field):
    setattr(case.plan_task, field, uuid4())
    with pytest.raises(DomainError) as error:
        sources.relative_due(case.sql, case.ctx, relative(case))
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_target_changes_with_actual_plan_version_instead_of_guessing_a_latest_plan(case):
    spec = relative(case)
    original = sources.relative_due(case.sql, case.ctx, spec)
    case.project.current_plan_id = case.plan.id = case.plan_task.plan_id = uuid4()
    case.plan.revision = 2
    changed = sources.relative_due(case.sql, case.ctx, spec)
    assert changed["target_key"] != original["target_key"]
    assert changed["origin"]["plan_revision"] == 2
    assert changed["scheduled_at"] == original["scheduled_at"]


def test_commitment_keeps_actual_promisor_recipient_version_and_nullable_date(case):
    spec = relative(case, source_kind="commitment", offset_seconds=-3600)
    result = sources.relative_due(case.sql, case.ctx, spec)
    assert result["scheduled_at"] == AT - timedelta(hours=1)
    assert result["origin"]["clock"] == "promised_at"
    assert result["origin"]["commitment_id"] == str(case.commitment.id)
    assert result["origin"]["commitment_revision"] == 3
    assert result["origin"]["task_revision"] == 5
    assert result["origin"]["calendar_id"] is None
    case.commitment_read.assert_called_once_with(
        case.sql,
        case.ctx,
        case.pid,
        case.commitment.task_id,
        case.commitment.promisor_id,
        case.commitment.recipient_id,
    )
    assert case.sql.statements == []
    case.commitment.promised_at = None
    case.promise = case.promise.model_copy(update={"promised_at": None})
    case.commitment_read.return_value = (case.commitment, case.promise, case.commitment_pointer)
    unknown = sources.relative_due(case.sql, case.ctx, spec)
    assert unknown["scheduled_at"] is None and unknown["origin"]["source_at"] is None
    assert unknown["target_key"] != result["target_key"]


@pytest.mark.parametrize("fault", ["missing", "project", "recipient", "current", "time"])
def test_missing_or_mismatched_commitment_cannot_fall_back_to_plan_forecast(case, fault):
    spec = relative(case, source_kind="commitment")
    if fault == "missing":
        case.commitment_read.return_value = (None, None, None)
    elif fault == "project":
        case.commitment.project_id = uuid4()
    elif fault == "recipient":
        case.commitment_pointer.recipient_id = uuid4()
    elif fault == "current":
        case.commitment_pointer.version_id = uuid4()
    else:
        case.commitment.promised_at = AT + timedelta(days=1)
    with pytest.raises(DomainError):
        sources.relative_due(case.sql, case.ctx, spec)
    assert case.sql.statements == []


def test_no_condition_task_is_eligible_without_reading_unrelated_objects(case):
    result = sources.condition_state(
        case.sql, case.ctx, SimpleNamespace(product_id=None, conditions=Conditions())
    )
    assert result == "eligible" and case.sql.statements == []
    case.task_read.assert_not_called()
    case.access.assert_not_called()


@pytest.mark.parametrize(
    "state,expected",
    [("accepted", "eligible"), ("assigned", "waiting"), ("completed", "goal_reached")],
)
def test_task_condition_uses_actual_current_state_and_does_not_infer_from_dates(
    case, state, expected
):
    case.task_snapshot = case.task_snapshot.model_copy(update={"state": state})
    case.task_row.state = case.task_pointer.state = state
    case.task_read.return_value = (case.task_row, case.task_snapshot, case.task_pointer)
    spec = condition(case, only_states=["accepted"])
    assert sources.condition_state(case.sql, case.ctx, spec) == expected
    case.task_read.assert_called_once_with(case.sql, case.ctx, case.pid, case.task_pointer.task_id)
    case.access.assert_called_once_with(case.sql, case.ctx, case.pid)
    params = case.sql.statements[0].compile().params.values()
    assert {case.ctx.tenant_id, case.ctx.category_id, case.pid, case.task_pointer.task_id} <= set(
        params
    )


def test_category_condition_derives_actual_product_when_none_is_declared(case):
    assert sources.condition_state(case.sql, case.ctx, condition(case, product=False)) == "eligible"
    case.access.assert_called_once_with(case.sql, case.ctx, case.pid)
    case.task_read.assert_called_once_with(case.sql, case.ctx, case.pid, case.task_pointer.task_id)


@pytest.mark.parametrize(
    "fault", ["missing", "category", "product", "owner_denied", "state_changed"]
)
def test_condition_keeps_missing_or_lost_scope_errors_instead_of_returning_empty_or_waiting(
    case, fault
):
    spec = condition(case)
    if fault == "missing":
        case.task_pointer = None
    elif fault == "category":
        case.task_pointer.category_id = uuid4()
    elif fault == "product":
        case.task_pointer.product_id = uuid4()
    elif fault == "owner_denied":
        case.task_read.side_effect = DomainError("FORBIDDEN_SCOPE", "Actual access revoked", 403)
    else:
        case.task_row.state = "submitted"
    with pytest.raises(DomainError):
        sources.condition_state(case.sql, case.ctx, spec)
    if fault in {"missing", "category", "product"}:
        case.task_read.assert_not_called()


def test_origins_are_copies_and_reads_do_not_mutate_actual_source_material(case):
    before = deepcopy(case.plan_task.forecast)
    result = sources.relative_due(case.sql, case.ctx, relative(case))
    result["origin"]["calendar_ref"]["timezone"] = "UTC"
    assert case.plan_task.forecast == before
