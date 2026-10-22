"""Pure source-query and attention DTO checks; no database or business emulator."""

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine

from pdos_next import personal_attention
from pdos_next.domain.project_risk.models import ProjectRiskFollowup, ProjectRiskFollowupCurrent
from pdos_next.domain.work_management.models import BINDING, SCOPE
from pdos_next.personal_attention_common import columns
from pdos_next.personal_attention_project_risk import queries


def sql(value):
    return str(value.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Risk attention pure checks must not connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


@pytest.fixture
def ctx():
    return SimpleNamespace(tenant_id=uuid4(), requester_id=uuid4())


def test_native_risk_query_is_read_only_and_metadata_only(ctx):
    (query,) = queries(ctx)
    selected = sql(query)
    assert isinstance(queries(ctx), tuple)
    assert tuple(query.selected_columns.keys()) == tuple(
        column.name
        for column in columns(
            key="key",
            kind="project_risk",
            queue="decide",
            tenant_id=ctx.tenant_id,
            source_id=uuid4(),
            category_id=uuid4(),
            recorded_at=datetime.now(UTC),
            title="Native risk",
            reason="Actual responsibility",
            state="open",
            responsible_id=ctx.requester_id,
            responsibility="g0_risk_followup",
            target="project",
        )
    )
    assert "FOR UPDATE" not in selected
    assert not re.search(r"\b(?:INSERT|UPDATE|DELETE|SECURITY DEFINER)\b", selected)
    assert all(
        field not in selected
        for field in (".body", "source_basis", "proposal_decisions", "proposals", "originals")
    )
    assert "work_task" not in selected


@pytest.mark.parametrize("queue", ["receive", "verify", "external", "unknown"])
def test_risk_followup_does_not_claim_other_queues(ctx, queue):
    assert queries(ctx, queue) == ()


def test_actual_project_binding_and_exact_current_are_required(ctx):
    (query,) = queries(ctx, "decide")
    selected = sql(query)
    current, version = ProjectRiskFollowupCurrent.__tablename__, ProjectRiskFollowup.__tablename__
    for field in SCOPE:
        assert f"{current}.{field} = project_open_items.{field}" in selected
    for field in BINDING:
        assert f"{current}.{field} = {version}.{field}" in selected
    for field in ("risk_id", "g0_decision_id", "revision", "state"):
        assert f"{current}.{field} = {version}.{field}" in selected
    assert f"{current}.version_id = {version}.id" in selected
    assert f"{current}.g0_decision_id = project_open_items.g0_decision_id" in selected
    assert f"{version}.g0_decision_id = project_open_items.g0_decision_id" in selected
    for field in ("tenant_id", "category_id", "product_id"):
        assert f"projects.{field} = project_open_items.{field}" in selected
    assert "projects.id = project_open_items.project_id" in selected
    assert "projects.g0_decision_id = project_open_items.g0_decision_id" in selected
    assert f"{current}.owner_id = projects.owner_id" in selected
    assert f"{current}.visibility = projects.visibility" in selected


def test_missing_or_mismatched_review_is_not_confused_with_initial_open(ctx):
    selected = sql(queries(ctx)[0].whereclause)
    current, version = ProjectRiskFollowupCurrent.__tablename__, ProjectRiskFollowup.__tablename__
    assert f"{current}.id IS NULL" in selected and "NOT (EXISTS" in selected
    assert "native_risk_any_current.tenant_id = project_open_items.tenant_id" in selected
    assert "native_risk_any_current.risk_id = project_open_items.id" in selected
    assert f"{current}.id IS NOT NULL" in selected
    assert f"{version}.id IS NOT NULL" in selected
    assert f"{current}.state = 'open'" in selected
    assert "project_open_items.status = 'open'" in selected
    assert "project_open_items.kind = 'risk'" in selected
    assert f"project_open_items.owner_id = '{ctx.requester_id}'" in selected
    assert f"project_open_items.tenant_id = '{ctx.tenant_id}'" in selected


def test_key_and_responsibility_stay_on_native_risk_while_version_watermark_changes(ctx):
    query = queries(ctx)[0]
    key = sql(query.selected_columns.key)
    assert "'project_risk:'" in key and "project_open_items.id" in key
    assert "revision" not in key and "version_id" not in key
    assert "project_open_items.id" in sql(query.selected_columns.source_id)
    assert "project_open_items.owner_id" in sql(query.selected_columns.responsible_id)
    assert "projects.owner_id" in sql(query.selected_columns.owner_id)
    assert "projects.visibility" in sql(query.selected_columns.visibility)
    version_id = sql(query.selected_columns.version_id)
    assert "project_open_items.id" in version_id
    assert f"{ProjectRiskFollowup.__tablename__}.id" in version_id
    assert "ELSE" in version_id
    recorded = sql(query.selected_columns.recorded_at)
    assert "project_open_items.created_at" in recorded
    assert f"{ProjectRiskFollowup.__tablename__}.created_at" in recorded


def test_g0_date_is_not_promoted_to_personal_commitment_or_approval(ctx):
    query = queries(ctx)[0]
    assert "CAST(NULL AS TIMESTAMP WITH TIME ZONE)" in sql(query.selected_columns.due_at)
    assert "g0_due_date" in sql(query.selected_columns.details)
    assert "CAST(project_open_items.due_date AS VARCHAR)" in sql(query.selected_columns.details)
    assert "decision_id" in sql(query.selected_columns.details)
    assert "不构成个人承诺" in sql(query.selected_columns.reason)
    assert "不作专业审批" in sql(query.selected_columns.reason)
    assert "g0_risk_followup" in sql(query.selected_columns.responsibility)
    assert "named_reviewer" not in sql(query)


def test_write_permission_only_changes_blocked_metadata(ctx):
    query = queries(ctx)[0]
    assert "grants.can_write IS true" in sql(query.selected_columns.blocked_code)
    assert "READ_ONLY" in sql(query.selected_columns.blocked_code)
    assert "grants.can_write IS true" not in sql(query.whereclause)
    assert "grants.expires_at" in sql(query.selected_columns.valid_until)
    assert "grants.expires_at > transaction_timestamp()" in sql(query)


@pytest.mark.parametrize("revision", [None, 1, 3])
def test_common_dto_keeps_native_identity_date_and_real_followup_watermark(ctx, revision):
    stable = uuid4()
    version = stable if revision is None else uuid4()
    at = datetime(2026, 10, 19, 9, tzinfo=UTC)
    details = {
        "view": "work",
        "g0_due_date": "2026-10-21",
        "decision_id": str(uuid4()),
        "internal_followup_only": True,
    }
    row = dict(
        tenant_id=ctx.tenant_id,
        responsible_id=ctx.requester_id,
        queue="decide",
        key=f"project_risk:{stable}",
        kind="project_risk",
        title="Actual G0 risk",
        reason="G0 原安排期限不构成个人承诺，内部跟进不作专业审批。",
        state="open",
        target="project",
        responsibility="g0_risk_followup",
        source_id=stable,
        version_id=version,
        revision=revision,
        epoch=None,
        recorded_at=at,
        due_at=None,
        valid_until=None,
        blocked_code=None,
        blocked_message=None,
        responsible_name=None,
        category_id=uuid4(),
        category_name="Actual category",
        product_id=uuid4(),
        product_name="Actual product",
        project_id=uuid4(),
        project_name="Actual project",
        details=details,
    )
    result = personal_attention.entry(row, ctx, "decide")
    assert result["id"] == f"project_risk:{stable}"
    assert result["source"] == {
        "id": str(stable),
        "version_id": str(version),
        "revision": revision,
        "epoch": None,
    }
    assert result["responsible"] == {"id": str(ctx.requester_id), "name": None}
    assert result["due_at"] is None and result["details"] == details
    assert result["recorded_at"] == at.isoformat()
