"""Synthetic authenticated review → named qualification → runtime eligibility only."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import (
    SkillQualification,
    TenantAdministrator,
    TenantPilotAdmission,
    TenantSkillEnablement,
)
from pdos_next.agent_kernel.policy import qualified
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.models import Audit, Confirmation, Outbox, Receipt
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.agent_kernel.test_skill_management import command as toggle
from tests.agent_kernel.test_transactions import human_session


def path(setup, suffix):
    return f"/v1/categories/{setup.category}/{suffix}"


def post(f, data, suffix="commands"):
    return f.client.post(path(f.setup, suffix), headers=f.setup.headers, json=data)


def reading(f):
    value = f.client.get(
        path(f.setup, "agent-skill-qualification?skill_key=public_research"),
        headers=f.setup.headers,
    )
    assert value.status_code == 200, value.text
    return value.json()


def command(f, operation, payload):
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "category_id": str(f.setup.category),
        "product_id": None,
        "expected_revision": 1,
        "source_read_set": [],
        "payload": payload,
    }


def confirmed(f, data):
    preview = post(f, data, "commands/preview")
    if preview.status_code == 422:
        from pdos_next.contracts import Command
        from pdos_next.service import preview_command

        with human_session(f.setup) as session:
            preview_command(session, f.setup.ctx, Command.model_validate(data))
    assert preview.status_code == 200, preview.text
    original = preview.json()["command"]
    result = post(f, original)
    assert result.status_code == 200, result.text
    return original, result.json(), preview.json()


def review(f, number=10, *, critical=False, offset=0):
    current = reading(f)
    payload = {
        key: current[key] for key in ("skill_key", "skill_digest", "tool_digest", "model_digest")
    }
    payload.update(
        personally_reviewed=True,
        cases=[
            {
                "source_ref": f"synthetic:own-case-{index + offset}",
                "material_kind": "synthetic",
                "conclusion": "本人核对：保留一个未知项。",
                "severity": "critical" if critical else "unknown",
            }
            for index in range(number)
        ],
    )
    original, receipt, _ = confirmed(f, command(f, "ai.skill.review.record", payload))
    return (
        original,
        receipt,
        [{"batch_id": receipt["subject_id"], "index": index} for index in range(number)],
    )


def grant_command(f, refs, decision="批准"):
    current = reading(f)
    payload = {
        "skill_key": current["skill_key"],
        "expected_revision": current["revision"],
        "decision": decision,
        "reason": "本人对合成案例的具名试点决定。",
        "case_refs": refs,
    }
    if decision == "批准":
        payload.update(
            {key: current[key] for key in ("skill_digest", "tool_digest", "model_digest")}
        )
    return command(f, "ai.skill.qualify", payload)


@pytest.fixture
def f(setup):
    from types import SimpleNamespace

    client, ports, data = configured(setup)
    response, _ = submit(setup, client, data)
    assert response.status_code == 200, response.text
    result = SimpleNamespace(setup=setup, client=client, ports=ports)
    confirmed(result, toggle(setup))
    return result


def eligible(f):
    skill, tools = SkillCatalog().configuration("public_research"), default_registry()
    with human_session(f.setup) as session:
        from pdos_next.agent_kernel.skill_qualification import current_model

        model = current_model(session, f.setup.tenant).metadata
        return qualified(
            session,
            f.setup.ctx,
            skill,
            model.model_version,
            model_digest=model_identity(model),
            tool_digest=tool_identity(skill, tools),
            lock=True,
        )


def test_batch_t1_named_t2_atom_replay_and_actual_policy(f):
    original, saved, refs = review(f)
    assert not eligible(f)
    data = grant_command(f, refs)
    assert post(f, data).json()["code"] == "NAMED_DECISION_REQUIRED"
    original_grant, receipt, preview = confirmed(f, data)
    assert preview["write_tier"] == "T2" and preview["expires_at"] is None
    assert preview["review"]["cases"][0]["criteria"]["coverage"] == "unknown"
    assert eligible(f)
    assert reading(f)["qualification"]["state"] == "qualified"
    assert post(f, original_grant).json() == receipt
    assert post(f, original, "agent-skill-qualification/recover").json() == {"receipt": saved}
    assert post(f, original_grant, "agent-skill-qualification/recover").json() == {
        "receipt": receipt
    }
    with Session(f.setup.admin) as session:
        for record in (saved, receipt):
            row = session.get(Receipt, UUID(record["id"]))
            assert session.get(Confirmation, row.confirmation_id).consumed
            for model in (Audit, Outbox):
                assert (
                    session.scalar(
                        select(func.count()).select_from(model).where(model.receipt_id == row.id)
                    )
                    == 1
                )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SkillQualification)
                .where(SkillQualification.tenant_id == f.setup.tenant)
            )
            == 1
        )


@pytest.mark.parametrize(
    "change",
    [
        "not_pilot",
        "disabled",
        "content",
        "model",
        "tools",
        "critical",
        "other_person",
        "duplicate",
        "nine",
    ],
)
def test_grant_rechecks_actual_scope_versions_and_selected_reviews(f, change, monkeypatch):
    _, _, refs = review(f, number=9 if change == "nine" else 10, critical=change == "critical")
    data = grant_command(f, refs)
    with Session(f.setup.admin) as session, session.begin():
        if change == "not_pilot":
            session.get(TenantPilotAdmission, f.setup.tenant).active = False
        if change == "disabled":
            session.scalar(
                select(TenantSkillEnablement).where(
                    TenantSkillEnablement.tenant_id == f.setup.tenant
                )
            ).enabled = False
        if change == "other_person":
            # Select an unseen case id; persisted records stay immutable.
            data["payload"]["case_refs"][0]["batch_id"] = str(uuid4())
    if change == "duplicate":
        data["payload"]["case_refs"][1] = data["payload"]["case_refs"][0]
    if change in {"content", "model", "tools"}:
        field = {"content": "skill_digest", "model": "model_digest", "tools": "tool_digest"}[change]
        data["payload"][field] = "0" * 64
    response = post(f, data, "commands/preview")
    assert response.status_code in (409, 422, 403), response.text
    assert not eligible(f)


def test_critical_review_pauses_next_t0_and_named_rereview_can_resume(f):
    _, _, refs = review(f)
    confirmed(f, grant_command(f, refs))
    assert eligible(f)
    review(f, number=1, critical=True, offset=20)
    assert not eligible(f) and reading(f)["qualification"]["state"] == "paused"
    assert post(f, grant_command(f, refs), "commands/preview").status_code == 409
    _, _, fresh = review(f, offset=30)
    confirmed(f, grant_command(f, fresh))
    assert eligible(f)
    _, revoked, _ = confirmed(f, grant_command(f, [], "撤销"))
    assert not eligible(f) and revoked["result"]["decision"] == "撤销"
    assert len(reading(f)["reviews"]) == 3


def test_revoke_survives_model_removal_and_trial_shutdown(f, monkeypatch):
    _, _, refs = review(f)
    confirmed(f, grant_command(f, refs))
    with Session(f.setup.admin) as session, session.begin():
        session.get(TenantPilotAdmission, f.setup.tenant).active = False
    from pdos_next.agent_kernel import skill_qualification

    monkeypatch.setattr(skill_qualification, "current_model", lambda *_args, **_kwargs: None)
    _, receipt, _ = confirmed(
        f,
        command(
            f,
            "ai.skill.qualify",
            {
                "skill_key": "public_research",
                "expected_revision": 2,
                "decision": "撤销",
                "reason": "暂停合成试点",
            },
        ),
    )
    assert receipt["result"]["next_revision"] == 3
    monkeypatch.undo()
    assert not eligible(f)


def test_human_owner_privacy_and_direct_fact_writes_are_rejected(f):
    _, _, refs = review(f)
    peer = {"Authorization": f"Bearer {f.setup.tokens[f.setup.peer]}"}
    value = f.client.get(
        path(f.setup, "agent-skill-qualification?skill_key=public_research"), headers=peer
    )
    assert (
        value.status_code == 200 and value.json()["reviews"] == [] and not value.json()["can_edit"]
    )
    forged = grant_command(f, refs)
    assert (
        f.client.post(path(f.setup, "commands/preview"), headers=peer, json=forged).status_code
        == 403
    )
    with pytest.raises(DBAPIError), human_session(f.setup) as session:
        session.execute(
            text("UPDATE tenant_pilot_admissions SET active=true WHERE tenant_id=:tenant"),
            {"tenant": f.setup.tenant},
        )
    with pytest.raises(DBAPIError), human_session(f.setup) as session:
        session.execute(
            text("UPDATE tenant_skill_enablements SET pilot=true WHERE tenant_id=:tenant"),
            {"tenant": f.setup.tenant},
        )
    with pytest.raises(DBAPIError), human_session(f.setup) as session:
        session.execute(
            text("UPDATE agent_skill_review_batches SET cases='[]'::jsonb WHERE id=:id"),
            {"id": refs[0]["batch_id"]},
        )


def test_prepared_approval_current_administrator_and_skill_revision_rechecked(f):
    _, _, refs = review(f)
    prepared = post(f, grant_command(f, refs), "commands/preview").json()["command"]
    confirmed(f, toggle(f.setup, False, revision=1))
    assert post(f, prepared).json()["code"] == "VERSION_CONFLICT"
    data = grant_command(f, [], "撤销")
    with Session(f.setup.admin) as session, session.begin():
        session.scalar(
            select(TenantAdministrator).where(TenantAdministrator.tenant_id == f.setup.tenant)
        ).active = False
    assert post(f, data, "commands/preview").status_code == 403


def test_active_qualification_invalidates_on_actual_skill_tool_model_and_pilot_change(f):
    _, _, refs = review(f)
    confirmed(f, grant_command(f, refs))
    assert eligible(f)
    skill, tools = SkillCatalog().configuration("public_research"), default_registry()
    from pdos_next.agent_kernel.skill_qualification import current_model

    with human_session(f.setup) as session:
        metadata = current_model(session, f.setup.tenant).metadata
        model_digest = model_identity(metadata)
        for selected_skill, selected_tool, selected_model in (
            (
                replace(skill, content=skill.content + " changed"),
                tool_identity(skill, tools),
                model_digest,
            ),
            (skill, "0" * 64, model_digest),
            (skill, tool_identity(skill, tools), "0" * 64),
        ):
            assert not qualified(
                session,
                f.setup.ctx,
                selected_skill,
                metadata.model_version,
                tool_digest=selected_tool,
                model_digest=selected_model,
                lock=True,
            )
    with Session(f.setup.admin) as session, session.begin():
        session.get(TenantPilotAdmission, f.setup.tenant).active = False
    assert not eligible(f)


def test_case_or_qualification_failure_rolls_back_fact_state_and_consumed_proof(f, monkeypatch):
    from pdos_next.agent_kernel import skill_qualification

    _, _, refs = review(f)
    original = post(f, grant_command(f, refs), "commands/preview").json()["command"]
    apply = skill_qualification.apply_validated

    def failing(*args):
        result = apply(*args)
        args[0].add(result[0])
        args[0].flush()
        raise RuntimeError("synthetic failure after pending qualification write")

    monkeypatch.setattr(skill_qualification, "apply_validated", failing)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        post(f, original)
    assert not eligible(f)
    with Session(f.setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SkillQualification)
                .where(SkillQualification.tenant_id == f.setup.tenant)
            )
            == 0
        )
        assert (
            session.scalar(
                select(TenantSkillEnablement).where(
                    TenantSkillEnablement.tenant_id == f.setup.tenant
                )
            ).revision
            == 1
        )
    monkeypatch.setattr(skill_qualification, "apply_validated", apply)
    assert post(f, original).status_code == 200
    assert eligible(f)


def test_pause_batch_does_not_count_as_new_review_after_its_own_critical_error(f):
    _, _, refs = review(f)
    confirmed(f, grant_command(f, refs))
    current = reading(f)
    cases = [
        {
            "source_ref": f"synthetic:mixed-{i}",
            "material_kind": "synthetic",
            "conclusion": "本人实际审阅",
            "severity": "critical" if i == 10 else "none",
        }
        for i in range(11)
    ]
    payload = {
        key: current[key] for key in ("skill_key", "skill_digest", "tool_digest", "model_digest")
    }
    _, receipt, _ = confirmed(
        f,
        command(
            f, "ai.skill.review.record", {**payload, "cases": cases, "personally_reviewed": True}
        ),
    )
    selected = [{"batch_id": receipt["subject_id"], "index": i} for i in range(10)]
    assert not eligible(f)
    assert post(f, grant_command(f, selected), "commands/preview").status_code == 409


def test_quality_identity_excludes_credentials_and_prices_but_tracks_relevant_tool_contract():
    from dataclasses import replace

    from pdos_next.agent_kernel.registry import ToolRegistry
    from tests.agent_kernel.test_gateway import configured_route

    route = configured_route()
    assert model_identity(route) == model_identity(replace(route, configuration_digest="a" * 64))
    assert model_identity(route) != model_identity(replace(route, model="different-model"))
    skill, tools = SkillCatalog().configuration("public_research"), default_registry()
    specs = [tools.get(name) for name in skill.operations]
    extra = replace(specs[0], name="unrelated.synthetic-tool")
    assert tool_identity(skill, tools) == tool_identity(skill, ToolRegistry([*specs, extra]))
    relevant = specs[0]
    changed = ToolRegistry(
        [replace(spec, version="changed") if spec.name == relevant.name else spec for spec in specs]
    )
    assert tool_identity(skill, tools) != tool_identity(skill, changed)


def test_named_review_qualification_is_consumed_by_actual_t0_domain_command(f):
    from pdos_next.agent_kernel.bindings import execution_key
    from tests.agent_kernel.test_domain_adapter_transactions import fixture

    _, _, refs = review(f)
    confirmed(f, grant_command(f, refs))
    actual = fixture(f.setup)
    intent = execution_key(actual.scope.run_id, actual.source.model_call_id, 0)
    receipt = actual.adapter.execute(
        actual.scope, actual.spec.name, actual.arguments, intent, source=actual.source
    )
    assert receipt["agent_run_id"] == str(actual.scope.run_id)
    assert receipt["writer_id"] == str(f.setup.agent)
    assert receipt["requester_id"] == str(f.setup.human)
    confirmed(f, grant_command(f, [], "撤销"))
    assert not eligible(f)
    # Completed facts remain readable and replay to the same receipt after revocation.
    assert (
        actual.adapter.execute(
            actual.scope, actual.spec.name, actual.arguments, intent, source=actual.source
        )
        == receipt
    )
