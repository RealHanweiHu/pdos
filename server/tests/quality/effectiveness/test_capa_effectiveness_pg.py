"""T2 CAPA effectiveness decision (D307, P96 第 1–4 项) on the isolated PG target.

The issue, CAPA, root cause, completion and observation come from the existing
real follow-up chain. That chain has one synthetic quality person who carried
out every action, so the independence refusal is tested for real and the write
paths replace only the executor set (and, for "effective", the review lookup).
"""

# ruff: noqa: F401, F811, E501 -- explicit fixture imports register the upstream tree

from datetime import timedelta
from uuid import UUID

import pytest
from builds.start.test_transactions import import_authority
from projects.test_project_first_plan import accepted, cmd, post
from sqlalchemy import select

from pdos_next.core.database import tenant_session
from pdos_next.core.models import Outbox, now
from pdos_next.domain.quality.capa.fact_storage_models import ObservationCurrent
from pdos_next.domain.quality.capa_effectiveness import service as effectiveness
from quality.followup_transactions.fixtures import (
    accepted_work,
    complete_command,
    current_rows,
    exact_source,
    fixed_issue,
    followup_integration_contract,
    followup_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
    root_command,
)
from quality.followup_transactions.test_capa_fact_flow import (
    test_actual_candidate_rule_and_observation_keep_complete_sources_current_and_receipt as record_observation,
)

OPERATION = "quality.capa.effectiveness.decide"


def grant(work):
    issue = fixed_issue(work)
    assert issue.status == "awaiting_verification"
    for kind in ("duty", "qualification"):
        import_authority(
            work,
            "quality",
            kind,
            subject_id=str(work.quality.human),
            operations=[OPERATION],
            purposes=[issue.purpose],
            external_id=f"synthetic-effectiveness-{work.issue_id}-{kind}",
        )
    return work


@pytest.fixture
def waiting(followup_work):
    work = followup_work
    accepted(work.quality, root_command(work))
    accepted(work.quality, complete_command(work, (0, 1)))
    return grant(work)


def decide(work, outcome, **changes):
    issue = fixed_issue(work)
    payload = {
        "issue_id": str(work.issue_id),
        "expected_issue_revision": issue.revision,
        "outcome": outcome,
        "text": f"合成有效性判定：{outcome}",
        **changes,
    }
    return cmd(work.quality, OPERATION, payload)


def named(work, value):
    shown = post(work.quality, value, True)
    assert shown.status_code == 200, shown.text
    assert shown.json()["write_tier"] == "T2" and shown.json()["named_decision"] is True
    saved = post(work.quality, shown.json()["command"])
    assert saved.status_code == 200, saved.text
    return saved.json(), shown.json()


def test_the_action_executor_cannot_decide_effectiveness(waiting):
    work = waiting
    refused = post(
        work.quality,
        decide(
            work, "extend_observation", observation_until=(now() + timedelta(days=7)).isoformat()
        ),
        True,
    )
    assert (
        refused.status_code == 403
        and refused.json()["code"] == "QUALIFICATION_REQUIRED"
        or refused.json()["detail"]["reason"] == "INDEPENDENT_REVIEWER_REQUIRED"
    )


def test_extend_then_effective_closes_in_the_same_transaction(waiting, monkeypatch):
    work = waiting
    monkeypatch.setattr(effectiveness, "action_executors", lambda issue: set())
    from datetime import datetime

    end = datetime.fromisoformat(
        fixed_issue(work).issue_snapshot["capa"]["requirement"]["observation_until"]
    )
    later = (max(end, now()) + timedelta(minutes=3)).replace(microsecond=0)
    receipt, shown = named(
        work, decide(work, "extend_observation", observation_until=later.isoformat())
    )
    assert shown["review"]["status_after"] == "awaiting_verification"
    issue = fixed_issue(work)
    assert issue.status == "awaiting_verification" and issue.operation == OPERATION
    assert issue.issue_snapshot["history"][-1]["operation"] == OPERATION
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        assert (
            s.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
            == "capa.effectiveness_decided"
        )
    earlier = post(
        work.quality,
        decide(
            work, "extend_observation", observation_until=(later - timedelta(minutes=1)).isoformat()
        ),
        True,
    )
    assert earlier.status_code == 409 and earlier.json()["code"] == "VALIDATION_FAILED"
    # Effective before the extended end is refused; afterwards it closes the issue.
    review = {"kind": "review", "id": str(work.issue_id), "revision": 1}
    monkeypatch.setattr(
        effectiveness,
        "evidence",
        lambda s, ctx, row, issue, refs, at: [
            {
                "kind": "review",
                "id": str(work.issue_id),
                "revision": 1,
                "actor_id": "independent",
                "conclusion": "applicable",
                "current": True,
            }
        ],
    )
    early = post(work.quality, decide(work, "effective", evidence=[review]), True)
    assert early.status_code == 409 and early.json()["code"] == "VALIDATION_FAILED"
    # Jump past the extended end; the role check already ran for real above, and
    # the synthetic duty facts end within the hour, so only that clock read is held.
    monkeypatch.setattr(effectiveness, "now", lambda: later + timedelta(minutes=1))
    monkeypatch.setattr(effectiveness.records, "require_role", lambda *args, **kwargs: ["quality"])
    closed, shown = named(work, decide(work, "effective", evidence=[review]))
    issue = fixed_issue(work)
    assert issue.status == "closed" and issue.issue_snapshot["closure"]["text"].startswith("合成")
    assert issue.issue_snapshot["capa"]["effectiveness"]["result"] == "effective"
    again = post(
        work.quality,
        decide(
            work, "extend_observation", observation_until=(later + timedelta(days=9)).isoformat()
        ),
        True,
    )
    assert again.status_code == 409 and again.json()["code"] == "VALIDATION_FAILED"
    assert closed["subject_type"] == "quality_issue"


def test_ineffective_returns_to_actioning_and_a_new_root_cause_round_runs(
    followup_work, monkeypatch
):
    work = followup_work
    record_observation(work)
    grant(work)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        observation = s.scalar(
            select(ObservationCurrent).where(ObservationCurrent.issue_id == work.issue_id)
        )
        evidence = {
            "kind": "observation",
            "id": str(observation.fact_id),
            "revision": observation.fact_revision,
        }
    monkeypatch.setattr(effectiveness, "action_executors", lambda issue: set())
    no_evidence = post(work.quality, decide(work, "ineffective"), True)
    assert no_evidence.status_code == 422
    effective_without_review = post(
        work.quality, decide(work, "effective", evidence=[evidence]), True
    )
    assert effective_without_review.status_code == 409
    receipt, shown = named(work, decide(work, "ineffective", evidence=[evidence]))
    assert (
        shown["review"]["evidence"][0]["kind"] == "observation"
        and shown["review"]["evidence"][0]["current"] is True
    )
    issue = fixed_issue(work)
    assert issue.status == "actioning"
    assert issue.issue_snapshot["root_cause"] is None and issue.issue_snapshot["capa"] is None
    previous = fixed_issue(work, issue.revision - 1)
    assert (
        previous.issue_snapshot["root_cause"] is not None
        and previous.issue_snapshot["capa"] is not None
    )
    # The existing CAPA draft and named root-cause commands run again on the new round.
    from uuid import uuid4

    from quality.followup_transactions.fixtures import quality_command

    work.capa_id = uuid4()
    drafted = post(
        work.quality,
        quality_command(
            work,
            "quality.capa.draft",
            {
                "issue_id": str(work.issue_id),
                "expected_issue_revision": issue.revision,
                "capa_id": str(work.capa_id),
                "hypotheses": [
                    {
                        "text": "Second-round synthetic hypothesis.",
                        "sources": [work.hypothesis_source.model_dump(mode="json")],
                    }
                ],
                "actions": [
                    {
                        "id": str(uuid4()),
                        "kind": "corrective",
                        "text": "Second-round action",
                        "executor_id": str(work.quality.human),
                    }
                ],
                "requirement": {
                    "method": "A separate owner-created verification Run",
                    "acceptance": "Exact affected pairs pass in the second round.",
                    "observation_until": (now() + timedelta(days=1)).isoformat(),
                    "required_failure_ids": [
                        f["identity"] for f in issue.issue_snapshot["failures"]
                    ],
                },
            },
        ),
    )
    assert drafted.status_code == 200, drafted.text
    second, _ = accepted(work.quality, root_command(work))
    assert (
        fixed_issue(work).issue_snapshot["root_cause"] is not None
        and second["operation"] == "quality.issue.root_cause.decide"
    )
