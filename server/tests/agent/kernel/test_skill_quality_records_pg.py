"""Holds, spot checks and evaluation sets are human or database records only (P42, P109–P110).

The qualification for ``public_research`` is granted through the real named commands;
T0 runs are synthetic ledger facts (see test_skill_quality_pg). Every record command is
previewed and confirmed once by the current tenant administrator.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel import skill_quality
from pdos_next.agent.kernel.models import (
    SkillEvalSet,
    SkillQualityHold,
    SkillReviewBatch,
    SkillSpotCheck,
)
from pdos_next.core.database import tenant_session
from tests.agent.kernel.test_skill_quality_pg import counts, qualify, t0_run, withdraw_run
from tests.agent.kernel.test_skill_qualification import (
    command,
    confirmed,
    eligible,
    grant_command,
    post,
    reading,
    review,
)
from tests.agent.kernel.test_skill_qualification import f as f  # noqa: F401 (fixture)
from tests.agent.kernel.test_transactions import human_session

SKILL = "public_research"


def holds(f):
    with Session(f.setup.admin) as s:
        return s.scalars(
            select(SkillQualityHold).where(SkillQualityHold.tenant_id == f.setup.tenant)
        ).all()


def quality(f, suffix=f"?skill_key={SKILL}", headers=None):
    response = f.client.get(
        f"/v1/categories/{f.setup.category}/agent-skill-quality{suffix}",
        headers=headers or f.setup.headers,
    )
    return response


def sampled_runs(f):
    body = quality(f).json()
    return [run["run_id"] for run in body["current"]["spot_check"]["runs"]]


def spot_check(f, run_id, outcome, kinds=(), note="本人核对：结论如上。"):
    payload = {
        "skill_key": SKILL,
        "run_id": str(run_id),
        "outcome": outcome,
        "critical_kinds": list(kinds),
        "note": "" if outcome == "correct" else note,
    }
    return command(f, "ai.skill.spot_check.record", payload)


def eval_case(case_id, **extra):
    return {
        "case_id": case_id,
        "case_type": "N",
        "category_ref": "auto-tire-inflator",
        "material_kind": "synthetic",
        "inputs": ["录制的研究快照 v1"],
        "must_cover": ["标注未知的工况"],
        **extra,
    }


def register(f, cases, title="公开研究资格集"):
    payload = {"skill_key": SKILL, "title": title, "cases": cases, "reference_points_signed": True}
    return confirmed(f, command(f, "ai.skill.eval_set.register", payload))


def test_crossed_threshold_is_recorded_once_and_needs_reviews_after_it(f):
    version, model, _ = qualify(f)
    _, _, before = review(f, offset=7000)
    runs = [t0_run(f.setup, version, model) for _ in range(20)]
    for run_id, _ in runs[:2]:
        withdraw_run(f.setup, run_id)
    # The first T0 attempt after the breach records the hold (the database recomputes).
    assert not eligible(f) and not eligible(f)
    [hold] = holds(f)
    assert hold.reason == "withdrawal" and hold.metrics == {"sample": 20, "count": 2}
    assert set(hold.basis_run_ids) == {runs[0][0], runs[1][0]}
    assert hold.owner_id == f.setup.human and hold.threshold == {"window": 20, "limit": 0.05}
    pinned = quality(f, "/holds").json()["holds"]
    assert [item["reason"] for item in pinned] == ["withdrawal"]
    assert pinned[0]["owner_name"] == "Synthetic owner"
    # Reviews recorded before the hold cannot restore T0; later ones can.
    assert post(f, grant_command(f, before), "commands/preview").status_code in (403, 409, 422)
    _, _, after = review(f, offset=8000)
    confirmed(f, grant_command(f, after))
    assert eligible(f) and quality(f, "/holds").json()["holds"] == []
    assert reading(f)["qualification"]["state"] == "qualified"


def test_withdrawal_command_path_records_the_hold_for_the_human(f):
    version, model, _ = qualify(f)
    runs = [t0_run(f.setup, version, model) for _ in range(20)]
    for run_id, _ in runs[:2]:
        withdraw_run(f.setup, run_id)
    with human_session(f.setup) as s:
        assert skill_quality.record_breaches(s, f.setup.tenant) == {SKILL: "withdrawal"}
    [hold] = holds(f)
    assert hold.triggered_by == f.setup.human


def test_hold_function_recomputes_and_refuses_invented_holds(f):
    version, model, _ = qualify(f)
    runs = [t0_run(f.setup, version, model) for _ in range(5)]
    withdraw_run(f.setup, runs[0][0])
    for window, limit in ((20, 0.05), (5, 0.5)):
        with pytest.raises(DBAPIError), human_session(f.setup) as s:
            s.execute(
                text(
                    "SELECT kernel_skill_quality_hold(CAST(:t AS uuid),CAST(:k AS varchar),"
                    "'withdrawal',NULL::uuid,CAST(:w AS integer),CAST(:l AS numeric))"
                ),
                {"t": f.setup.tenant, "k": SKILL, "w": window, "l": limit},
            )
    with pytest.raises(DBAPIError), human_session(f.setup) as s:
        s.execute(
            text(
                "SELECT kernel_skill_quality_hold(CAST(:t AS uuid),CAST(:k AS varchar),"
                "'critical_spot_check',CAST(:id AS uuid),NULL::integer,NULL::numeric)"
            ),
            {"t": f.setup.tenant, "k": SKILL, "id": uuid4()},
        )
    assert holds(f) == []
    with f.setup.engine.connect() as c:
        for name in ("kernel_skill_quality_hold", "kernel_skill_open_hold"):
            assert not c.execute(
                text(
                    "SELECT has_function_privilege('pdos_agent',p.oid,'EXECUTE') "
                    "FROM pg_proc p WHERE p.proname=:n"
                ),
                {"n": name},
            ).scalar_one()
        for table in ("agent_skill_quality_holds", "agent_skill_spot_checks",
                      "agent_skill_eval_sets"):
            assert not c.execute(
                text("SELECT has_table_privilege('pdos_agent',:t,'SELECT')"), {"t": table}
            ).scalar_one()
        assert not c.execute(
            text("SELECT has_table_privilege('pdos_next_app','agent_skill_quality_holds','INSERT')")
        ).scalar_one()


def test_spot_checks_mark_only_sampled_runs_and_critical_pauses(f):
    version, model, _ = qualify(f)
    runs = [t0_run(f.setup, version, model) for _ in range(3)]
    sampled = sampled_runs(f)
    # Three runs in one week: at least min(2, 3) are sampled (P42).
    assert len(sampled) >= 2
    unsampled = [str(run) for run, _ in runs if str(run) not in sampled]
    if unsampled:
        response = post(f, spot_check(f, unsampled[0], "correct"), "commands/preview")
        assert response.status_code == 422, response.text
    before = counts(f.setup, version, model)
    _, receipt, preview = confirmed(f, spot_check(f, sampled[0], "ordinary_error"))
    assert preview["review"]["outcome_label"] == "普通错误"
    assert receipt["result"]["hold_id"] is None
    after = counts(f.setup, version, model)
    assert after.writes_changed == before.writes_changed + 1
    assert eligible(f)
    duplicate = post(f, spot_check(f, sampled[0], "correct"), "commands/preview")
    assert duplicate.status_code == 409
    missing_kind = post(f, spot_check(f, sampled[1], "critical_error"), "commands/preview")
    assert missing_kind.status_code == 422
    _, critical, _ = confirmed(f, spot_check(f, sampled[1], "critical_error", ["fabrication"]))
    assert critical["result"]["hold_id"]
    assert not eligible(f) and reading(f)["qualification"]["state"] == "paused"
    [hold] = holds(f)
    assert hold.reason == "critical_spot_check" and hold.basis_run_ids == [UUID(sampled[1])]
    marks = quality(f).json()["current"]["spot_checks"]
    assert {mark["outcome"] for mark in marks} == {"ordinary_error", "critical_error"}
    peer = {"Authorization": f"Bearer {f.setup.tokens[f.setup.peer]}"}
    assert f.client.post(
        f"/v1/categories/{f.setup.category}/commands/preview", headers=peer,
        json=spot_check(f, sampled[0], "correct"),
    ).status_code == 403
    with pytest.raises(DBAPIError), tenant_session(
        f.setup.engine, f.setup.tenant, actor_id=f.setup.agent, requester_id=f.setup.human,
        category_id=f.setup.category,
    ) as s:
        s.execute(
            text("UPDATE agent_skill_spot_checks SET outcome='correct' WHERE tenant_id=:t"),
            {"t": f.setup.tenant},
        )


def test_eval_sets_are_frozen_versions_that_reviews_can_cite(f):
    _, first, preview = register(f, [eval_case("N-01"), eval_case("N-02", case_type="M")])
    assert preview["review"]["version"] == 1 and preview["review"]["case_types"] == {
        "M": 1, "N": 1
    }
    assert "不授予任何资格" in preview["review"]["effect"]
    _, second, _ = register(f, [eval_case("N-01")], title="公开研究资格集 v2")
    assert second["result"]["version"] == 2
    current = reading(f)
    eval_set = next(item for item in current["eval_sets"] if item["version"] == 1)
    assert eval_set["cases_sha256"] == first["result"]["cases_sha256"]
    payload = {
        key: current[key]
        for key in ("skill_key", "skill_digest", "tool_digest", "model_digest", "prompt_digest")
    }
    case = {"source_ref": "synthetic:N-01", "material_kind": "synthetic",
            "conclusion": "本人核对：覆盖未知工况。", "severity": "none"}
    wrong = command(f, "ai.skill.review.record", {
        **payload, "personally_reviewed": True, "cases": [case],
        "eval_set_id": eval_set["id"], "eval_case_ids": ["N-99"],
    })
    refused = post(f, wrong, "commands/preview")
    assert refused.status_code >= 400 and refused.json()["code"] == "SOURCE_UNAVAILABLE"
    confirmed(f, command(f, "ai.skill.review.record", {
        **payload, "personally_reviewed": True, "cases": [case],
        "eval_set_id": eval_set["id"], "eval_case_ids": ["N-01"],
    }))
    cited = next(item for item in reading(f)["eval_sets"] if item["version"] == 1)
    assert cited["reviewed_case_ids"] == ["N-01"]
    with Session(f.setup.admin) as s:
        batch = s.scalar(
            select(SkillReviewBatch).where(SkillReviewBatch.eval_set_id == eval_set["id"])
        )
        assert batch.cases[0]["eval_case_id"] == "N-01"
        assert s.scalar(
            select(func.count()).select_from(SkillEvalSet).where(
                SkillEvalSet.tenant_id == f.setup.tenant
            )
        ) == 2
        assert s.scalar(
            select(func.count()).select_from(SkillSpotCheck).where(
                SkillSpotCheck.tenant_id == f.setup.tenant
            )
        ) == 0
    with pytest.raises(DBAPIError), human_session(f.setup) as s:
        s.execute(
            text("UPDATE agent_skill_eval_sets SET title='改名' WHERE id=:id"),
            {"id": eval_set["id"]},
        )
    # A request that cites no evaluation set keeps its original digest shape.
    plain = command(f, "ai.skill.review.record", {
        **payload, "personally_reviewed": True, "cases": [{**case, "source_ref": "x"}],
    })
    from pdos_next.agent.kernel.skill_qualification import RecordReviews, semantic

    assert "eval_set_id" not in semantic(RecordReviews.model_validate(plain["payload"]))
