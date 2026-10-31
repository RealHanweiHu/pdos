"""Native plan/stage/baseline commands and ordinary owner RLS; root runs PG.

No source body, business owner, clock or model is patched. Schedule starts in
actual future UTC. Only the final revocation test expires the real reader grant.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from g0_fixture import add_category_human, create_g0_project
from pdos_next import personal_summary, personal_summary_runtime, personal_summary_templates
from pdos_next.database import tenant_session
from pdos_next.domain.project_governance.models import GovernanceEvent
from pdos_next.domain.projects.models import Project
from pdos_next.models import Grant, now
from pdos_next.personal_summary_schemas import Selection
from pdos_next.service import Context
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, cmd, post, proposal_command
from test_project_governance import command, get


def apply_plan(work, *, base=None, revision=1):
    setup = work.setup
    proposed = proposal_command(setup, work.definition, work.project)
    proposed["payload"]["expected_project_revision"] = revision
    proposed["payload"]["base_plan_id"] = base
    proposed["payload"]["schedule"]["start"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    proposed["payload"]["schedule"]["calendar"] = {
        "version": "summary-gate-24h@1",
        "timezone": "UTC",
        "working_weekdays": list(range(7)),
        "intervals": [{"start_minute": 0, "end_minute": 1440}],
    }
    for task in proposed["payload"]["schedule"]["tasks"]:
        task.update(
            duration_min_minutes=60,
            duration_max_minutes=120,
            estimate_source="Synthetic named bounded estimate for summary",
        )
    candidate = post(setup, proposed)
    assert candidate.status_code == 200, candidate.text
    receipt, _ = accepted(
        setup,
        cmd(
            setup,
            "work.plan.apply",
            {
                "project_id": work.project,
                "proposal_id": candidate.json()["subject_id"],
                "expected_project_revision": revision,
            },
            work.definition[0],
        ),
    )
    return receipt["subject_id"]


def change(work, operation, revision, **fields):
    value = command(work.setup, work.definition, work.project, operation, revision, **fields)
    value["payload"]["expected_project_revision"] = 2
    return accepted(work.setup, value)[0]


@pytest.fixture
def gate_work(setup, request):
    visibility = getattr(request, "param", "category")
    g0 = create_g0_project(setup, visibility=visibility, name="Actual summary stage project")
    artifact = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic baseline summary input",
                "content": "Unverified synthetic input",
                "source_label": "Synthetic summary fixture",
                "visibility": "category",
            },
        ),
    )
    assert artifact.status_code == 200, artifact.text
    work = NS(
        setup=setup,
        project=g0.project_id,
        definition=(artifact.json()["subject_id"], g0.definition_id),
    )
    work.plan = apply_plan(work)
    change(work, "work.stage.adopt", 0, template="small-change@1")
    stages = get(setup, work.project)["stages"]
    change(work, "work.stage.milestone.bind", 1, stage_id=stages[0]["id"], task_key="eng")
    change(work, "work.stage.milestone.bind", 2, stage_id=stages[1]["id"], task_key="npi")
    work.approval = change(work, "work.baseline.approve", 3, plan={"id": work.plan, "revision": 1})
    return work


def choice(work, *, follow=False):
    return Selection(
        category_ids=(work.setup.category,),
        followed_project_ids=(UUID(work.project),) if follow else (),
        groups=("action", "following"),
        excluded_kinds=tuple(
            k for k in personal_summary_templates.KINDS if k != "upcoming_stage_gate"
        ),
    )


def entries(summary):
    return [item for group in summary.groups for item in (*group.items, *group.unchanged_items)]


def read(work, *, person=None, follow=False, previous=None):
    setup = work.setup
    person = person or setup.human
    ctx = Context(setup.tenant, person, person)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=person, requester_id=person, read_snapshot=True
    ) as s:
        assert s.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert s.scalar(text("SHOW transaction_read_only")) == "on"
        return personal_summary.read(
            s, ctx, choice(work, follow=follow), previous=previous, product_id=setup.product
        )


def readable(work, summary, *, person=None):
    setup = work.setup
    person = person or setup.human
    refs = {item.object for item in entries(summary)}
    binding = NS(
        tenant_id=setup.tenant,
        requester_id=person,
        category_id=setup.category,
        product_id=setup.product,
    )
    with tenant_session(
        setup.engine, setup.tenant, actor_id=person, requester_id=person, read_snapshot=True
    ) as s:
        return personal_summary_runtime._readable_sources(s, binding, refs)


def snapshot(work):
    with Session(work.setup.admin) as s:
        p = s.get(Project, UUID(work.project))
        count = s.scalar(
            select(func.count())
            .select_from(GovernanceEvent)
            .where(
                GovernanceEvent.tenant_id == work.setup.tenant,
                GovernanceEvent.project_id == p.id,
            )
        )
        return p.revision, p.current_plan_id, count


def test_native_approved_baseline_yields_current_and_future_fixed_estimates_without_writes(
    gate_work,
):
    work = gate_work
    before = snapshot(work)
    summary = read(work)
    rows = entries(summary)
    assert len(rows) == 2 and summary.model_used is False
    assert {i.facts["stage_position_as_recorded"] for i in rows} == {"current", "upcoming"}
    current = get(work.setup, work.project)
    baseline = current["baseline"]
    expected = {t["key"]: t["latest_finish"] for t in baseline["forecast"]["tasks"]}
    for item in rows:
        assert item.object.version_id == UUID(work.approval["subject_id"])
        assert item.object.revision == 4
        assert item.facts["baseline_ref"]["id"] == baseline["id"]
        assert item.facts["plan_as_approved"]["id"] == work.plan
        assert item.facts["baseline_latest_finish_as_recorded"] == expected[item.facts["task_key"]]
        assert item.facts["date_kind"] == "approved_baseline_estimate"
        assert item.health is None and item.possible_impact == "待确认"
        assert item.next_step.responsible.id == work.setup.human
        assert "不代表承诺、实际完成或门禁通过" in item.next_step.text
    assert readable(work, summary) == {i.object for i in rows}
    again = read(work, previous=summary.baseline)
    assert not any(g.items for g in again.groups)
    assert len(entries(again)) == 2 and all(i.change.kind == "unchanged" for i in entries(again))
    assert snapshot(work) == before


def test_readable_nonowner_needs_explicit_subscription_and_never_borrows_project_owner(gate_work):
    work = gate_work
    assert entries(read(work, person=work.setup.peer)) == []
    subscribed = read(work, person=work.setup.peer, follow=True)
    assert len(entries(subscribed)) == 2
    for item in entries(subscribed):
        assert item.group == "following" and item.relationship.kind == "subscriber"
        assert item.next_step.responsible.id == work.setup.human != work.setup.peer
    assert subscribed.principal_id == work.setup.peer
    assert readable(work, subscribed, person=work.setup.peer) == {
        item.object for item in entries(subscribed)
    }


def test_new_current_plan_does_not_reuse_old_approval_and_history_keeps_its_fixed_event(gate_work):
    work = gate_work
    original = read(work)
    fixed = original.model_dump(mode="json")
    new_plan = apply_plan(work, base=work.plan, revision=2)
    assert new_plan != work.plan
    assert entries(read(work, previous=original.baseline)) == []
    # Current RLS still permits the historical event; do not replace its body
    # with the newer plan or pretend it was approved for that plan.
    assert readable(work, original) == {item.object for item in entries(original)}
    assert original.model_dump(mode="json") == fixed


def test_actual_category_read_revocation_hides_native_event_and_original_refs(gate_work):
    work = gate_work
    original = read(work, person=work.setup.peer, follow=True)
    fixed = original.model_dump(mode="json")
    with Session(work.setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(
                Grant.tenant_id == work.setup.tenant,
                Grant.category_id == work.setup.category,
                Grant.principal_id == work.setup.peer,
            )
            .values(expires_at=now() - timedelta(seconds=1))
        )
    assert readable(work, original, person=work.setup.peer) == set()
    assert original.model_dump(mode="json") == fixed


@pytest.mark.parametrize("gate_work", ["private"], indirect=True)
def test_explicit_follow_does_not_grant_another_humans_private_project_or_fixed_event(gate_work):
    work = gate_work
    original = read(work)
    assert len(entries(original)) == 2
    # The actual G0 reviewer has native result/audience access even when the
    # originating proposal and materialized project remain private.
    assert len(entries(read(work, person=work.setup.peer, follow=True))) == 2
    outsider = add_category_human(work.setup, name="Synthetic unrelated summary subscriber")
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.setup.human,
                        requester_id=work.setup.human, read_snapshot=True) as s:
        assert s.get(Project, UUID(work.project)).visibility == "private"
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=outsider,
                        requester_id=outsider, read_snapshot=True) as s:
        assert s.scalar(select(Project.id).where(Project.id == UUID(work.project))) is None
        assert s.scalar(select(GovernanceEvent.id).where(
            GovernanceEvent.project_id == UUID(work.project),
        )) is None
    assert entries(read(work, person=outsider, follow=True)) == []
    assert readable(work, original, person=outsider) == set()
