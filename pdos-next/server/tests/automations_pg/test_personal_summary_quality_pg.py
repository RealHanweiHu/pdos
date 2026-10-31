"""Actual native Issue/CAPA → ordinary owner summary/readback; root executes PG.

No clock, source, Issue body, executor or business ownership is patched. The only
negative mutation expires the actual recipient's category grant. This extends
source integration; the separate existing Automation/Temporal tests own admission.
"""
# ruff: noqa: F401, F811 -- upstream fixture dependencies are intentionally re-exported

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from quality_execution.fixtures import (
    accepted_work,
    command,
    create_issue,
    current_rows,
    issue_current,
    known_configuration,
    launch_work,
    operational_work,
    publish_policy,
    quality_work,
    ready_work,
    results_work,
    triage,
    upload_report,
)
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_project_first_plan import post

from pdos_next import personal_summary, personal_summary_runtime, personal_summary_templates
from pdos_next.database import tenant_session
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.models import Grant, now
from pdos_next.personal_summary_schemas import Selection
from pdos_next.service import Context


@pytest.fixture
def summary_quality_work(quality_work):
    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work)
    triage(work, first)
    issue = issue_current(work, first["result"]["issue_id"])
    draft = command(
        work,
        "quality.capa.draft",
        {
            "issue_id": issue["issue_id"],
            "expected_issue_revision": issue["revision"],
            "capa_id": str(uuid4()),
            "hypotheses": [
                {
                    "text": "Synthetic hypothesis, not a root cause.",
                    "sources": [work.hypothesis_source.model_dump(mode="json")],
                }
            ],
            "actions": [
                {
                    "id": str(uuid4()),
                    "kind": "corrective",
                    "text": "Actual named pending quality action",
                    "executor_id": str(work.quality.human),
                }
            ],
            "requirement": {
                "method": "Independent evidence",
                "acceptance": "Fixed pairs pass",
                "observation_until": (now() - timedelta(minutes=1)).isoformat(),
                "required_failure_ids": [f["identity"] for f in issue["issue"]["failures"]],
            },
        },
    )
    saved = post(work.quality, draft)
    assert saved.status_code == 200, saved.text
    work.summary_issue = issue_current(work, issue["issue_id"])
    return work


def owner_read(work, previous=None):
    ctx = Context(work.setup.tenant, work.quality.human, work.quality.human)
    choice = Selection(
        category_ids=(work.setup.category,),
        groups=("action", "following"),
        excluded_kinds=tuple(
            k
            for k in personal_summary_templates.KINDS
            if k not in {"quality_issue_opened", "capa_observation_due"}
        ),
    )
    with tenant_session(
        work.setup.engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        read_snapshot=True,
    ) as s:
        options = personal_summary_templates.read(s, ctx, work.setup.category, work.setup.product)
        summary = personal_summary.read(
            s, ctx, choice, previous=previous, product_id=work.setup.product
        )
        return summary, options


def entries(summary):
    return [item for group in summary.groups for item in (*group.items, *group.unchanged_items)]


def test_actual_native_quality_duty_issue_and_capa_due_use_fixed_owner_facts(summary_quality_work):
    work = summary_quality_work
    summary, options = owner_read(work)
    assert options["default_template"] == "quality"
    assert "quality" in options["basis"]["current_duty_roles"]
    assert summary.model_used is False and summary.principal_id == work.quality.human
    items = {item.kind: item for item in entries(summary)}
    assert set(items) == {"quality_issue_opened", "capa_observation_due"}
    opened, due = items["quality_issue_opened"], items["capa_observation_due"]
    assert opened.next_step.responsible is None
    assert due.next_step.responsible.id == work.quality.human
    assert due.facts["action_due_at_as_recorded"] is None
    assert due.facts["effectiveness_as_recorded"] is None and due.health is None
    assert due.object.version_id == UUID(work.summary_issue["id"])
    assert due.object.revision == work.summary_issue["revision"]
    again, _ = owner_read(work, summary.baseline)
    assert all(not group.items for group in again.groups)
    assert len(entries(again)) == 2 and all(i.change.kind == "unchanged" for i in entries(again))
    assert {c.source for c in summary.coverage} >= {"quality_issue_opened", "capa_observation_due"}


def test_actual_quality_source_readback_is_hidden_after_owner_grant_revocation(
    summary_quality_work,
):
    work = summary_quality_work
    summary, _ = owner_read(work)
    sources = {item.object for item in entries(summary)}
    ctx = Context(work.setup.tenant, work.quality.human, work.quality.human)
    binding = SimpleNamespace(
        tenant_id=ctx.tenant_id,
        requester_id=ctx.requester_id,
        category_id=work.setup.category,
        product_id=work.setup.product,
    )
    with tenant_session(
        work.setup.engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        read_snapshot=True,
    ) as s:
        assert personal_summary_runtime._readable_sources(s, binding, sources) == sources
    original = summary.model_dump(mode="json")
    with Session(work.setup.admin) as s, s.begin():
        s.execute(
            update(Grant)
            .where(
                Grant.tenant_id == ctx.tenant_id,
                Grant.principal_id == ctx.requester_id,
                Grant.category_id == work.setup.category,
            )
            .values(expires_at=now() - timedelta(seconds=1))
        )
    with tenant_session(
        work.setup.engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        read_snapshot=True,
    ) as s:
        assert (
            s.scalar(
                select(QualityIssueVersion.id).where(
                    QualityIssueVersion.id == UUID(work.summary_issue["id"]),
                )
            )
            is None
        )
        assert personal_summary_runtime._readable_sources(s, binding, sources) == set()
    assert summary.model_dump(mode="json") == original
