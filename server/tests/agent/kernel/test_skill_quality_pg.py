"""T0 value metrics and P41 automatic step-back are computed from receipts only (D117, D37 ⑧).

A real named qualification is granted for ``public_research`` through the existing
commands; synthetic completed T0 writes, withdrawals and later human changes are then
written as facts. The withdrawal threshold gates every T0 skill package (P109).
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel import skill_quality
from pdos_next.agent.kernel.models import AgentRun, AgentToolCall, TenantSkillEnablement
from pdos_next.agent.kernel.persistence import finish_run_revert
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Receipt, now
from tests.agent.kernel.test_skill_qualification import (
    confirmed,
    eligible,
    grant_command,
    reading,
    review,
)
from tests.agent.kernel.test_skill_qualification import f as f  # noqa: F401 (fixture)
from tests.agent.kernel.test_transactions import human_session, run

SKILL = "public_research"


def qualify(f):
    _, _, refs = review(f, offset=uuid4().int % 10_000 * 100)
    confirmed(f, grant_command(f, refs))
    assert eligible(f)
    with Session(f.setup.admin) as s:
        row = s.scalar(
            select(TenantSkillEnablement).where(
                TenantSkillEnablement.tenant_id == f.setup.tenant,
                TenantSkillEnablement.skill_key == SKILL,
            )
        )
        return row.qualified_skill_version, row.qualified_model_version, row.reviewed_at


def receipt(setup, *, actor, subject, operation, run_id=None, at=None, subject_type="claim"):
    identity = uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(
            Receipt(
                id=identity,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=None,
                command_id=uuid4(),
                actor_id=actor,
                requester_id=setup.human,
                operation=operation,
                subject_type=subject_type,
                subject_id=subject,
                subject_revision=1,
                visibility="private",
                request_digest=uuid4().hex + uuid4().hex,
                intent_digest=uuid4().hex + uuid4().hex,
                result={"synthetic": True},
                agent_run_id=run_id,
                created_at=at or now(),
            )
        )
    return identity


def t0_run(setup, version, model, *, writes=1, at=None, skill=SKILL):
    """One run whose completed T0 domain writes are on the execution ledger."""
    _, scope = run(setup)
    at = at or now()
    subjects = []
    for index in range(writes):
        subject = uuid4()
        written = receipt(
            setup,
            actor=setup.agent,
            subject=subject,
            operation="evidence.claim.record",
            run_id=scope.run_id,
            at=at + timedelta(microseconds=index),
        )
        with Session(setup.admin) as s, s.begin():
            s.add(
                AgentToolCall(
                    id=uuid4(),
                    tenant_id=setup.tenant,
                    run_id=scope.run_id,
                    call_key=f"t0-{index}",
                    tool="evidence.claim.record",
                    input_digest=uuid4().hex + uuid4().hex,
                    execution_binding={
                        "kind": "domain_t0",
                        "operation": "evidence.claim.record",
                        "model_version": model,
                        "model_route_digest": "a" * 64,
                        "tool_definitions_digest": "b" * 64,
                        "cancel_epoch": 0,
                        "skill": {
                            "key": skill,
                            "version": version,
                            "digest": "c" * 64,
                            "load_event_id": str(uuid4()),
                        },
                        "model_call_id": str(uuid4()),
                        "response_index": index,
                        "command_digest": "d" * 64,
                    },
                    state="completed",
                    result={"receipt": str(written)},
                    receipt_id=written,
                    created_at=at + timedelta(microseconds=index),
                )
            )
        subjects.append(subject)
    return scope.run_id, subjects


def withdraw_run(setup, run_id):
    """Whole-run withdrawal through the actual human revert stamp."""
    identity = receipt(
        setup, actor=setup.human, subject=run_id, operation="ai.run.revert",
        subject_type="agent_run",
    )
    with Session(setup.admin) as s:
        epoch = s.get(AgentRun, run_id).cancel_epoch
    with human_session(setup) as s:
        finish_run_revert(
            s, setup.ctx, run_id, revert_receipt_id=identity, expected_cancel_epoch=epoch
        )


def counts(setup, version, model, since=None):
    with human_session(setup) as s:
        return skill_quality.counts(s, setup.tenant, SKILL, version, model, since)


def quality(f, headers=None):
    return f.client.get(
        f"/v1/categories/{f.setup.category}/agent-skill-quality?skill_key={SKILL}",
        headers=headers or f.setup.headers,
    )


def test_counts_follow_withdrawals_and_later_human_changes_only(f):
    version, model, since = qualify(f)
    runs = [t0_run(f.setup, version, model, writes=2) for _ in range(3)]
    withdraw_run(f.setup, runs[0][0])
    # A single-item withdrawal (claim revert) and a later human change by subject.
    receipt(f.setup, actor=f.setup.human, subject=runs[1][1][0], operation="ai.run.revert")
    receipt(f.setup, actor=f.setup.human, subject=runs[2][1][1], operation="evidence.claim.patch")
    # An AI write on the same subject and another skill's write are not human changes.
    receipt(f.setup, actor=f.setup.agent, subject=runs[2][1][0], operation="evidence.claim.patch")
    t0_run(f.setup, version, model, skill="category_framing")
    value = counts(f.setup, version, model, since)
    assert value == skill_quality.Counts(
        runs_window=3, runs_withdrawn=2, writes_window=6, writes_changed=1, writes_withdrawn=3
    )
    # Another model version is a separate tenant × skill × model window.
    assert counts(f.setup, version, model + "-other").runs_window == 0


@pytest.mark.parametrize(
    ("total", "withdrawn", "eligible_after"),
    [(20, 1, True), (20, 2, False), (19, 5, True)],
    ids=["five_percent_is_not_over", "over_five_percent", "window_not_full_is_na"],
)
def test_withdrawal_threshold_gates_every_t0_skill(f, total, withdrawn, eligible_after):
    version, model, _ = qualify(f)
    runs = [t0_run(f.setup, version, model) for _ in range(total)]
    for run_id, _ in runs[:withdrawn]:
        withdraw_run(f.setup, run_id)
    # P109: the withdrawal threshold applies to every T0 skill package; the
    # modification and framework-check thresholds gate work_management only.
    assert skill_quality.gating(SKILL) == (skill_quality.WITHDRAWAL,)
    assert skill_quality.gating("work_management") == skill_quality.RULES
    assert eligible(f) is eligible_after
    state = reading(f)["qualification"]
    if eligible_after:
        assert state["state"] == "qualified" and state["downgrade_reason"] is None
    else:
        assert state["state"] == "downgraded" and state["downgrade_reason"] == "withdrawal"


def test_downgrade_stays_until_a_new_named_qualification_starts_a_new_window(f):
    version, model, _ = qualify(f)
    runs = [t0_run(f.setup, version, model) for _ in range(20)]
    for run_id, _ in runs[:3]:
        withdraw_run(f.setup, run_id)
    assert not eligible(f)
    # No new T0 run can enter the frozen window, so the step-back does not decay.
    assert not eligible(f) and reading(f)["qualification"]["state"] == "downgraded"
    # Time alone does not restore T0; a new named decision on fresh reviews does.
    _, _, fresh = review(f, offset=900)
    confirmed(f, grant_command(f, fresh))
    assert eligible(f) and reading(f)["qualification"]["state"] == "qualified"


def test_value_view_is_admin_only_and_lists_basis_runs(f):
    version, model, _ = qualify(f)
    runs = [t0_run(f.setup, version, model) for _ in range(3)]
    withdraw_run(f.setup, runs[1][0])
    receipt(f.setup, actor=f.setup.human, subject=runs[2][1][0], operation="evidence.claim.patch")
    response = quality(f)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_judgement"] is False
    group = body["groups"][0]
    assert (group["skill_version"], group["model_version"]) == (version, model)
    assert group["runs_total"] == 3 and group["metrics"]["withdrawal_rate"] == pytest.approx(1 / 3)
    assert group["metrics"]["retention_rate"] == pytest.approx(2 / 3)
    assert group["metrics"]["untouched_rate"] == pytest.approx(1 / 3)
    current = body["current"]
    assert current["basis"] == {
        "withdrawal": [str(runs[1][0])],
        "modification": [str(runs[2][0])],
    }
    rules = {rule["key"]: rule for rule in current["rules"]}
    assert rules["withdrawal"]["state"] == "insufficient" and rules["withdrawal"]["gating"]
    assert not rules["modification"]["gating"]
    assert rules["framework_check"]["state"] == "unavailable"
    # Spot check sample: fewer than two runs a week are all sampled (P42).
    sample = current["spot_check"]
    assert sum(week["sampled"] for week in sample["weeks"]) >= min(2, 3)
    peer = {"Authorization": f"Bearer {f.setup.tokens[f.setup.peer]}"}
    assert quality(f, peer).status_code == 403


def test_definer_functions_refuse_other_tenants_and_non_administrators(f):
    version, model, since = qualify(f)
    t0_run(f.setup, version, model)
    with human_session(f.setup) as s:
        assert s.execute(
            text(
                "SELECT * FROM kernel_skill_quality_counts(:t,:k,:v,:m,NULL,20,50)"
            ),
            {"t": uuid4(), "k": SKILL, "v": version, "m": model},
        ).all() == []
    with pytest.raises(DBAPIError), tenant_session(
        f.setup.engine,
        f.setup.tenant,
        actor_id=f.setup.peer,
        requester_id=f.setup.peer,
        category_id=f.setup.category,
    ) as s:
        s.execute(
            text("SELECT * FROM kernel_skill_quality_groups(:t,:k)"),
            {"t": f.setup.tenant, "k": SKILL},
        ).all()
    with f.setup.engine.connect() as c:
        for name in ("kernel_skill_t0_facts", "kernel_skill_quality_basis"):
            assert not c.execute(
                text(
                    "SELECT has_function_privilege('pdos_agent',p.oid,'EXECUTE') "
                    "FROM pg_proc p WHERE p.proname=:n"
                ),
                {"n": name},
            ).scalar_one()
        assert not c.execute(
            text(
                "SELECT has_function_privilege('pdos_next_app',p.oid,'EXECUTE') "
                "FROM pg_proc p WHERE p.proname='kernel_skill_t0_facts'"
            )
        ).scalar_one()
