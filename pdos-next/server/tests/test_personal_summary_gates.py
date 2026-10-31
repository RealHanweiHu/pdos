"""Self-contained no-DB checks for recorded baseline dates and fixed sources."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pdos_next import personal_summary
from pdos_next import personal_summary_gates as gates
from pdos_next import personal_summary_runtime as runtime
from pdos_next import personal_summary_templates as templates
from pdos_next.domain.project_governance.models import GovernanceEvent
from pdos_next.personal_summary_schemas import Selection
from pdos_next.service import Context
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import dialect

AT = datetime(2026, 10, 29, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("pure summary gate tests cannot connect to a database")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)


@pytest.fixture
def case():
    tenant, person, category, product, identity, plan, stage = (uuid4() for _ in range(7))
    project = NS(
        id=identity,
        tenant_id=tenant,
        category_id=category,
        product_id=product,
        owner_id=person,
        name="Registered project",
        current_plan_id=plan,
    )
    event = NS(
        id=uuid4(),
        revision=4,
        created_at=AT - timedelta(hours=1),
        body={
            "template": {"id": "small-change@1", "name": "小改项目"},
            "stages": [{"id": str(stage), "key": "planning", "name": "计划"}],
            "position": 0,
            "bindings": {str(stage): {"task_key": "eng"}},
            "baseline": {
                "id": str(uuid4()),
                "revision": 3,
                "plan": {"id": str(plan), "revision": 1},
                "forecast": {
                    "tasks": [{"key": "eng", "latest_finish": (AT + timedelta(days=1)).isoformat()}]
                },
                "approved_by": str(person),
                "at": (AT - timedelta(hours=2)).isoformat(),
            },
        },
    )
    return NS(ctx=Context(tenant, person, person), project=project, event=event)


def sql(query):
    return str(query.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))


@pytest.mark.parametrize(
    ("delta", "included"),
    [(-1, False), (0, True), (1, True), (7 * 86400, True), (7 * 86400 + 1, False)],
)
def test_seven_day_window_uses_only_registered_timezone_aware_latest_finish(case, delta, included):
    task = case.event.body["baseline"]["forecast"]["tasks"][0]
    task["latest_finish"] = (AT + timedelta(seconds=delta)).isoformat()
    assert bool(gates.items(case.project, case.event, case.ctx, AT, Selection())) is included


@pytest.mark.parametrize("date", [None, "unknown", "2026-10-30", "2026-10-30T12:00:00", 0])
def test_unknown_or_naive_dates_are_not_invented(case, date):
    case.event.body["baseline"]["forecast"]["tasks"][0]["latest_finish"] = date
    assert gates.items(case.project, case.event, case.ctx, AT, Selection()) == []


@pytest.mark.parametrize(
    "missing", ["baseline", "binding", "task", "latest_finish", "plan", "approver", "approval_at"]
)
def test_missing_facts_do_not_create_a_deadline_or_approval(case, missing):
    body = case.event.body
    if missing == "baseline":
        body["baseline"] = None
    elif missing == "binding":
        body["bindings"] = {}
    elif missing == "task":
        body["baseline"]["forecast"]["tasks"] = []
    elif missing == "latest_finish":
        body["baseline"]["forecast"]["tasks"][0].pop("latest_finish")
    elif missing == "plan":
        case.project.current_plan_id = None
    else:
        body["baseline"].pop("approved_by" if missing == "approver" else "at")
    assert gates.items(case.project, case.event, case.ctx, AT, Selection()) == []


def test_current_plan_switch_rejects_previous_baseline_even_if_date_is_near(case):
    case.project.current_plan_id = uuid4()
    assert gates.items(case.project, case.event, case.ctx, AT, Selection()) == []


def test_current_and_future_adopted_stages_are_kept_but_passed_stages_are_excluded(case):
    body = case.event.body
    first = body["stages"][0]
    second = {"id": str(uuid4()), "key": "design", "name": "设计"}
    third = {"id": str(uuid4()), "key": "dvt", "name": "DVT"}
    body["stages"] = [first, second, third]
    body["bindings"] |= {s["id"]: {"task_key": "eng"} for s in (second, third)}
    body["position"] = 1
    rows = gates.items(case.project, case.event, case.ctx, AT, Selection())
    assert [r["facts"]["stage_name"] for r in rows] == ["设计", "DVT"]
    assert [r["facts"]["stage_position_as_recorded"] for r in rows] == ["current", "upcoming"]
    body["position"] = 3
    assert gates.items(case.project, case.event, case.ctx, AT, Selection()) == []


def test_relevance_is_actual_owner_or_explicit_follow_not_any_readable_human(case):
    p, e, ctx = case.project, case.event, case.ctx
    (own,) = gates.items(p, e, ctx, AT, Selection())
    assert own["group"] == "action" and own["relationship"].kind == "project_owner"
    p.owner_id = uuid4()
    assert gates.items(p, e, ctx, AT, Selection()) == []
    followed = Selection(followed_project_ids=(p.id,))
    (row,) = gates.items(p, e, ctx, AT, followed)
    assert row["group"] == "following" and row["relationship"].kind == "subscriber"
    assert row["next_step"].responsible.id == p.owner_id != ctx.requester_id
    assert (
        gates.items(p, e, ctx, AT, Selection(groups=("action",), followed_project_ids=(p.id,)))
        == []
    )
    p.owner_id = ctx.requester_id
    assert gates.items(p, e, ctx, AT, Selection(groups=("following",))) == []


def test_fixed_native_event_and_frozen_approval_are_preserved_without_health_or_commitment(case):
    (row,) = gates.items(case.project, case.event, case.ctx, AT, Selection())
    assert row["object"].kind == "project_governance"
    assert row["object"].id == case.project.id
    assert row["object"].version_id == case.event.id
    assert row["object"].revision == case.event.revision
    baseline = case.event.body["baseline"]
    assert row["facts"]["baseline_ref"] == {"id": baseline["id"], "revision": baseline["revision"]}
    assert row["facts"]["plan_as_approved"] == baseline["plan"]
    assert (
        row["facts"]["baseline_latest_finish_as_recorded"]
        == (baseline["forecast"]["tasks"][0]["latest_finish"])
    )
    assert row["facts"]["date_kind"] == "approved_baseline_estimate"
    assert "不代表承诺、实际完成或门禁通过" in row["next_step"].text
    result = personal_summary.compose(case.ctx, Selection(), AT, [row], [])
    item = result.groups[0].items[0]
    assert item.health is None and item.possible_impact == "待确认" and result.model_used is False
    assert item.next_step.recorded_by is None
    again = personal_summary.compose(
        case.ctx, Selection(), AT + timedelta(hours=1), [row], [], previous=result.baseline
    )
    assert again.groups[0].unchanged_items[0].change.kind == "unchanged"
    assert not again.groups[0].items


def test_query_selects_latest_ledger_and_current_plan_with_full_project_scope_before_limit(case):
    selection = Selection(
        category_ids=(case.project.category_id,), followed_project_ids=(case.project.id,)
    )
    query = sql(gates.query(case.ctx, selection, product_id=case.project.product_id).limit(101))
    for key in ("tenant_id", "category_id", "product_id"):
        assert f"project_governance_events.{key} = projects.{key}" in query
    assert "project_governance_events.project_id = projects.id" in query
    assert "ORDER BY project_governance_events.revision DESC" in query
    assert "CAST(projects.current_plan_id AS VARCHAR)" in query
    for identity in (
        case.ctx.tenant_id,
        case.ctx.requester_id,
        case.project.category_id,
        case.project.product_id,
        case.project.id,
    ):
        assert str(identity) in query
    assert "SECURITY DEFINER" not in query
    following = sql(
        gates.query(
            case.ctx, Selection(groups=("following",), followed_project_ids=(case.project.id,))
        )
    )
    assert "projects.owner_id =" not in following


def test_unsubscribed_gate_type_or_waiting_only_never_reads_source(case):
    class NoRead:
        def execute(self, *_args):
            raise AssertionError("unsubscribed source must not be read")

    for selection in (Selection(excluded_kinds=(gates.KIND,)), Selection(groups=("waiting",))):
        assert gates.read(NoRead(), case.ctx, selection, AT) == ([], [])


def test_candidate_overflow_reports_incomplete_coverage_instead_of_absence(case):
    class ManyRows:
        def execute(self, query):
            assert "LIMIT 101" in sql(query)
            return NS(all=lambda: [(case.project, case.event)] * 101)

    rows, (coverage,) = gates.read(ManyRows(), case.ctx, Selection(), AT)
    assert len(rows) == 100 and coverage.returned == 100 and coverage.has_more
    assert coverage.available is None


def test_runtime_rechecks_exact_governance_event_metadata_without_reading_latest_body(case):
    (row,) = gates.items(case.project, case.event, case.ctx, AT, Selection())
    source = row["object"]
    run = NS(
        tenant_id=case.ctx.tenant_id,
        requester_id=case.ctx.requester_id,
        category_id=case.project.category_id,
        product_id=case.project.product_id,
    )
    metadata = {
        "id": case.event.id,
        "source_id": case.project.id,
        "revision": case.event.revision,
        "category_id": case.project.category_id,
        "product_id": case.project.product_id,
        "project_id": case.project.id,
    }

    class Metadata:
        def __init__(self):
            self.rows = [metadata]
            self.queries = []

        def execute(self, query):
            self.queries.append(query)
            return NS(mappings=lambda: NS(all=lambda: self.rows))

    session = Metadata()
    assert runtime._source_models()["project_governance"] == (GovernanceEvent,)
    assert runtime._source_key(GovernanceEvent).key == "project_id"
    assert runtime._readable_sources(session, run, {source}) == {source}
    query = sql(session.queries[-1])
    assert str(case.event.id) in query and "project_governance_events" in query
    assert ".body" not in query and "latest" not in query
    for key in ("id", "source_id", "product_id", "project_id", "category_id"):
        session.rows = [{**metadata, key: uuid4()}]
        assert runtime._readable_sources(session, run, {source}) == set()
    session.rows = [{**metadata, "revision": case.event.revision + 1}]
    assert runtime._readable_sources(session, run, {source}) == set()
    session.rows = []
    assert runtime._readable_sources(session, run, {source}) == set()
    assert row["object"] == source


def test_product_and_general_presets_include_gate_and_other_presets_do_not(case):
    for template in templates.TEMPLATES:
        assert (gates.KIND in template["kinds"]) is (template["id"] in {"general", "product"})
    original = deepcopy(case.event.body)
    gates.items(case.project, case.event, case.ctx, AT, Selection())
    assert case.event.body == original
