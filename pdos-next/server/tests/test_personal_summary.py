"""Structured summaries remain ordinary current facts, without model authority."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pdos_next import personal_summary as summary
from pdos_next.domain.work_management.models import WorkCommitmentCurrent, WorkCommitmentVersion
from pdos_next.errors import DomainError
from pdos_next.personal_summary_schemas import Coverage, Selection
from pdos_next.service import Context
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql


@pytest.fixture
def case():
    tenant, person, category, product, project = (uuid4() for _ in range(5))
    return SimpleNamespace(
        ctx=Context(tenant, person, person),
        category=category,
        product=product,
        project=project,
        at=datetime(2026, 10, 29, 9, tzinfo=UTC),
    )


def attention(case, *, queue="decide", kind="project_risk"):
    identity = uuid4()
    return {
        "id": f"{kind}:{identity}",
        "kind": kind,
        "queue": queue,
        "source": {"id": str(identity), "version_id": str(uuid4()), "revision": 2, "epoch": None},
        "category": {"id": str(case.category), "name": "已读品类"},
        "product": {"id": str(case.product), "name": "已读型号"},
        "project": {"id": str(case.project), "name": "已读项目"},
        "title": "原记录标题",
        "reason": "你是原记录具名责任人。",
        "state": "open",
        "responsible": {"id": str(case.ctx.requester_id), "name": "实际责任人"},
        "responsibility": "g0_risk_followup",
        "recorded_at": case.at.isoformat(),
        "due_at": None,
        "blocked": None,
        "target": "project",
        "details": {},
    }


def entries(value):
    return [item for group in value.groups for item in (*group.items, *group.unchanged_items)]


def test_four_questions_and_three_groups_use_current_recorded_metadata(case):
    action = summary._attention(attention(case))
    waiting = summary._attention(attention(case, queue="external", kind="external_wait"))
    value = summary.compose(case.ctx, Selection(), case.at, [action, waiting], [])
    assert [group.id for group in value.groups] == ["action", "waiting", "following"]
    assert value.model_used is False and value.complete
    for item in entries(value):
        assert item.change.kind == "initial" and "首次列入" in item.change.text
        assert item.relationship.text == "你是原记录具名责任人。"
        assert item.next_step.responsible.id == case.ctx.requester_id
        assert item.next_step.kind == "navigation"
        assert f"project={case.project}" in item.continue_url
        assert item.health is None and item.possible_impact == "待确认"


def test_unchanged_facts_are_folded_and_new_read_timestamp_does_not_create_a_change(case):
    row = summary._attention(attention(case))
    first = summary.compose(case.ctx, Selection(), case.at, [row], [])
    next_ = summary.compose(
        case.ctx, Selection(), case.at + timedelta(days=7), [row], [], previous=first.baseline
    )
    assert not next_.groups[0].items
    assert len(next_.groups[0].unchanged_items) == 1 and next_.groups[0].unchanged_collapsed
    assert next_.groups[0].unchanged_items[0].change.kind == "unchanged"
    row = deepcopy(row)
    row["state_as_recorded"] = "updated_by_named_owner"
    changed = summary.compose(case.ctx, Selection(), case.at, [row], [], previous=first.baseline)
    assert changed.groups[0].items[0].change.kind == "updated"


def test_inaccessible_or_removed_item_is_not_replayed_or_declared_resolved(case):
    row = summary._attention(attention(case))
    first = summary.compose(case.ctx, Selection(), case.at, [row], [])
    current = summary.compose(case.ctx, Selection(), case.at, [], [], previous=first.baseline)
    assert not entries(current) and not current.baseline.watermarks
    assert current.missing_since_previous == "not_classified"
    assert "原记录标题" not in current.model_dump_json()


@pytest.mark.parametrize("field", ["tenant_id", "principal_id", "selection_digest"])
def test_previous_watermarks_never_cross_human_tenant_or_selection(case, field):
    first = summary.compose(case.ctx, Selection(), case.at, [], [])
    bad = first.baseline.model_copy(
        update={field: "a" * 64 if field == "selection_digest" else uuid4()}
    )
    with pytest.raises(DomainError) as error:
        summary.compose(case.ctx, Selection(), case.at, [], [], previous=bad)
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_group_type_and_category_unsubscription_only_narrow_current_results(case):
    row = summary._attention(attention(case))
    for selection in (
        Selection(groups=("waiting",)),
        Selection(excluded_kinds=(row["kind"],)),
        Selection(category_ids=(uuid4(),)),
    ):
        assert not entries(summary.compose(case.ctx, selection, case.at, [row], []))
    with pytest.raises(ValidationError):
        Selection.model_validate({"role": "manager", "read_all_projects": True})
    with pytest.raises(ValidationError):
        Selection(followed_project_ids=(case.project, case.project))


def test_output_and_source_limits_report_partial_and_do_not_mark_omitted_items_seen(case):
    rows = [summary._attention(attention(case)) for _ in range(3)]
    rows[1]["facts"]["details"] = {"blocking": True}
    value = summary.compose(
        case.ctx,
        Selection(max_items=1),
        case.at,
        rows,
        [
            Coverage(source="attention", returned=3, has_more=True),
        ],
    )
    assert not value.complete and value.omitted_current_items == 2
    assert len(entries(value)) == len(value.baseline.watermarks) == 1
    assert entries(value)[0].facts["details"]["blocking"] is True


def test_named_project_recorder_is_not_inferred_to_own_its_next_step_or_health(case):
    project = SimpleNamespace(
        id=case.project,
        category_id=case.category,
        product_id=case.product,
        revision=5,
        status="active",
        created_at=case.at,
        name="关注项目",
    )
    update = {
        "id": str(uuid4()),
        "revision": 1,
        "actor": {"id": str(uuid4()), "name": "具名记录人"},
        "fact_summary": "具名更新的原文中写了红色，摘要不自行提取风险等级。",
        "next_steps": "请在原项目明确下一责任人。",
        "task_refs": [],
        "created_at": case.at.isoformat(),
        "receipt_id": str(uuid4()),
    }
    row = summary._project(project, update)
    value = entries(summary.compose(case.ctx, Selection(), case.at, [row], []))[0]
    assert value.facts["latest_named_status"] == update and value.health is None
    assert value.next_step.responsible is None
    assert value.next_step.recorded_by.id == UUID(update["actor"]["id"])
    assert value.next_step.kind == "recorded" and value.relationship.kind == "subscriber"
    missing = summary._project(project, None)
    assert missing["next_step"].kind == "unknown" and missing["next_step"].recorded_by is None


def test_internal_wait_check_is_not_an_external_promise_or_overdue_result(case):
    row = attention(case, queue="external", kind="external_wait")
    row["due_at"] = (case.at - timedelta(days=2)).isoformat()
    row["details"] = {"next_check_is_internal": True, "delivery_state": "unverified"}
    item = entries(summary.compose(case.ctx, Selection(), case.at, [summary._attention(row)], []))[
        0
    ]
    assert item.state_as_recorded == "open"
    assert item.facts["details"]["next_check_is_internal"] is True
    assert item.facts["date_kind"] == "internal_check"
    assert "overdue" not in item.model_dump_json() and "已送达" not in item.model_dump_json()


def test_supply_unknown_quantity_time_and_external_responsible_remain_unknown(case):
    source = {
        "source_id": uuid4(),
        "source_revision": 2,
        "category_id": case.category,
        "product_id": case.product,
        "project_id": case.project,
        "created_at": case.at,
        "title": "已登记供应承诺",
        "read_basis_status": "needs_recheck",
        "structured": {
            "facts": {
                "build_id": str(uuid4()),
                "commitments": [
                    {
                        "record_id": "record-1",
                        "supplier_id": "supplier-as-recorded",
                        "material_id": "material-as-recorded",
                        "quantity": None,
                        "unit": None,
                        "expected_at": None,
                    }
                ],
            }
        },
    }
    item = entries(
        summary.compose(case.ctx, Selection(), case.at, list(summary._supply(source)), [])
    )[0]
    assert item.next_step.responsible is None and item.health is None
    assert item.facts["commitment_as_recorded"]["quantity"] is None
    assert item.facts["commitment_as_recorded"]["expected_at"] is None
    assert item.facts["source_basis_status"] == "needs_recheck"
    assert item.facts["fulfillment_status"] == "not_assessed"


def test_waiting_promise_binds_actual_recipient_promisor_scope_and_current_version(case):
    query = summary.waiting_promises(case.ctx)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    table, pointer = WorkCommitmentVersion.__tablename__, WorkCommitmentCurrent.__tablename__
    assert f"{table}.tenant_id = '{case.ctx.tenant_id}'" in sql
    assert f"{table}.recipient_id = '{case.ctx.requester_id}'" in sql
    assert f"{table}.promisor_id != '{case.ctx.requester_id}'" in sql
    for field in (
        *summary.BINDING,
        "task_id",
        "promisor_id",
        "recipient_id",
        "series_id",
        "revision",
    ):
        assert f"{table}.{field} = {pointer}.{field}" in sql
    assert f"{table}.id = {pointer}.version_id" in sql
    assert "fulfilled" in sql and "NOT (EXISTS" in sql
    assert "role" not in sql.lower() and "security definer" not in sql.lower()


def test_supply_read_uses_actual_owner_current_authority_and_category_narrowing(case):
    source = summary.supply_sources(case.ctx).subquery("supply_summary_scope")
    from sqlalchemy import select

    query = summary._categories(
        select(source), source.c.category_id, Selection(category_ids=(case.category,))
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert f"owner_id = '{case.ctx.requester_id}'" in sql
    assert f"category_id IN ('{case.category}')" in sql
    assert "current_setting('pdos.tenant_id', true)" in sql
    assert "is_current" in sql and "supply_current_snapshots" in sql
    assert "read_basis_status" in sql and "source_revision" in sql


class PersonalSession:
    def __init__(self, case):
        self.info = {
            "read_snapshot": True,
            "scope": (
                case.ctx.tenant_id,
                case.ctx.requester_id,
                case.ctx.requester_id,
                None,
            ),
        }
        self.principal = SimpleNamespace(active=True, kind="human")
        self.at = case.at

    def get(self, _model, _identity):
        return self.principal

    def scalar(self, _query):
        return self.at


@pytest.mark.parametrize(
    "change", ["writer", "category", "write", "agent_run", "inactive", "agent"]
)
def test_generation_rejects_borrowed_service_agent_or_nonpersonal_transaction(case, change):
    session, ctx = PersonalSession(case), case.ctx
    if change == "writer":
        ctx = replace(ctx, actor_id=uuid4())
    elif change == "category":
        ctx = replace(ctx, category_id=case.category)
    elif change == "write":
        session.info["read_snapshot"] = False
    elif change == "agent_run":
        ctx = replace(ctx, agent_run_id=uuid4())
    elif change == "inactive":
        session.principal.active = False
    else:
        session.principal.kind = "agent"
    with pytest.raises(DomainError) as error:
        summary.read(session, ctx, Selection(groups=()))
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_service_reads_selected_project_and_actual_latest_named_status_without_model(
    case, monkeypatch
):
    session = PersonalSession(case)
    project = SimpleNamespace(
        id=case.project,
        category_id=case.category,
        product_id=case.product,
        revision=5,
        status="active",
        created_at=case.at,
        name="关注项目",
    )

    def scalars(query):
        sql = str(
            query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
        assert str(case.ctx.tenant_id) in sql and str(case.project) in sql
        return SimpleNamespace(all=lambda: [project])

    session.scalars = scalars
    monkeypatch.setattr(
        summary,
        "latest_named_updates",
        lambda actual, ctx, projects: (
            {} if actual is session and ctx is case.ctx and projects == [project] else None
        ),
    )
    from pdos_next import personal_summary_gates, personal_summary_quality

    monkeypatch.setattr(personal_summary_quality, "read", lambda *_a, **_k: ([], []))
    monkeypatch.setattr(personal_summary_gates, "read", lambda *_a, **_k: ([], []))
    value = summary.read(
        session, case.ctx, Selection(groups=("following",), followed_project_ids=(case.project,))
    )
    assert value.model_used is False and value.complete
    assert entries(value)[0].state_as_recorded == "no_named_update"
    assert entries(value)[0].next_step.responsible is None
