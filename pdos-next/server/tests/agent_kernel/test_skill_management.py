from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel import skill_management
from pdos_next.agent_kernel.models import TenantAdministrator, TenantSkillEnablement
from pdos_next.agent_kernel.policy import qualified, skill_enabled
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.models import Audit, Category, Confirmation, Grant, Outbox, Receipt, now
from tests.agent_kernel.test_transactions import run


def path(setup, suffix="agent-skills"):
    return f"/v1/categories/{setup.category}/{suffix}"


def promote(setup):
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))


def command(setup, enabled=True, revision=0):
    skill = SkillCatalog().configuration("public_research")
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": "ai.skill.enable",
        "category_id": str(setup.category),
        "product_id": None,
        "expected_revision": 1,
        "source_read_set": [],
        "payload": {
            "skill_key": skill.key,
            "expected_revision": revision,
            "enabled": enabled,
            "skill_version": skill.version,
            "skill_digest": skill.digest,
        },
    }


def post(setup, data, suffix="commands"):
    return setup.client.post(path(setup, suffix), headers=setup.headers, json=data)


def preview(setup, data):
    result = post(setup, data, "commands/preview")
    assert result.status_code == 200, result.text
    return result.json()


def test_member_reads_real_catalog_but_only_current_admin_can_preview(setup):
    value = setup.client.get(path(setup), headers=setup.headers)
    assert value.status_code == 200
    data = value.json()
    assert data["can_edit"] is False and data["category_revision"] == 1
    assert {row["skill_key"] for row in data["items"]} == {
        row["key"] for row in SkillCatalog().index
    }
    assert all(not row["enabled"] and row["revision"] == 0 for row in data["items"])
    assert post(setup, command(setup), "commands/preview").status_code == 403
    peer = {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    assert setup.client.get(path(setup), headers=peer).status_code == 403


def test_t1_one_confirmation_atom_no_qualification_and_exact_replay_after_expiry(setup):
    promote(setup)
    data = command(setup)
    assert post(setup, data).json()["code"] == "CONFIRMATION_REQUIRED"
    prepared = preview(setup, data)
    assert prepared["review"]["qualification_changed"] is False
    assert prepared["review"]["scope"] == "tenant"
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(TenantSkillEnablement).where(TenantSkillEnablement.tenant_id == setup.tenant)
            )
            is None
        )
    result = post(setup, prepared["command"])
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert receipt["subject_revision"] == 1 and receipt["result"]["enabled"] is True
    assert receipt["operation"] == "ai.skill.enable" and receipt["agent_run_id"] is None
    with Session(setup.admin) as session, session.begin():
        row = session.get(TenantSkillEnablement, UUID(receipt["subject_id"]))
        assert row.enabled and row.revision == 1 and row.receipt_id == UUID(receipt["id"])
        assert not row.pilot and not row.review_case_refs and row.reviewed_by is None
        saved = session.get(Receipt, UUID(receipt["id"]))
        confirmation = session.get(Confirmation, saved.confirmation_id)
        assert confirmation.consumed
        confirmation.expires_at = now() - timedelta(days=1)
        for model in (Audit, Outbox):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.receipt_id == saved.id)
                )
                == 1
            )
    assert post(setup, prepared["command"]).json() == receipt
    assert post(setup, prepared["command"], "agent-skills/recover").json() == {"receipt": receipt}
    store, bound = run(setup)
    with store.transaction(bound) as (session, _):
        skill = SkillCatalog().configuration("public_research")
        assert skill_enabled(session, bound, skill)
        assert not qualified(session, bound, skill, "synthetic-model")


def test_disable_blocks_next_use_without_erasing_review_records(setup):
    promote(setup)
    skill = SkillCatalog().configuration("public_research")
    reviewed = now()
    refs = [f"synthetic-reviewed-case-{index}" for index in range(10)]
    with Session(setup.admin) as session, session.begin():
        session.add(
            TenantSkillEnablement(
                tenant_id=setup.tenant,
                skill_key=skill.key,
                enabled=True,
                pilot=True,
                qualified_skill_version=skill.version,
                qualified_model_version="synthetic-model",
                reviewed_by=setup.human,
                reviewed_at=reviewed,
                review_case_refs=refs,
            )
        )
    original = preview(setup, command(setup, False))["command"]
    assert post(setup, original).status_code == 200
    store, bound = run(setup)
    with store.transaction(bound) as (session, _):
        assert not skill_enabled(session, bound, skill)
        assert not qualified(session, bound, skill, "synthetic-model")
    current = setup.client.get(path(setup), headers=setup.headers).json()
    row = next(item for item in current["items"] if item["skill_key"] == skill.key)
    assert row["qualification_record"] == "recorded" and not row["enabled"]
    with Session(setup.admin) as session:
        saved = session.scalar(
            select(TenantSkillEnablement).where(TenantSkillEnablement.tenant_id == setup.tenant)
        )
        assert saved.review_case_refs == refs and saved.reviewed_at == reviewed
        assert saved.qualified_skill_version == skill.version
        assert saved.qualified_model_version == "synthetic-model" and saved.pilot


def test_prepared_toggle_does_not_overwrite_new_tenant_state(setup):
    promote(setup)
    first = preview(setup, command(setup))["command"]
    stale = preview(setup, command(setup, False))["command"]
    assert post(setup, first).status_code == 200
    assert post(setup, stale).json()["code"] == "VERSION_CONFLICT"
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(TenantSkillEnablement).where(TenantSkillEnablement.tenant_id == setup.tenant)
            ).revision
            == 1
        )


def test_skill_content_change_invalidates_preview_without_any_file_or_db_qualification_write(
    setup, monkeypatch
):
    promote(setup)
    original = preview(setup, command(setup))["command"]
    current = SkillCatalog()
    skill = current.configuration("public_research")
    current._skills[skill.key] = replace(
        skill, content=skill.content + "\nChanged synthetic content"
    )
    monkeypatch.setattr(skill_management, "SkillCatalog", lambda: current)
    assert post(setup, original).json()["code"] == "VERSION_CONFLICT"


def test_current_admin_revocation_stops_new_action_but_exact_read_only_recovery_survives(setup):
    promote(setup)
    original = preview(setup, command(setup))["command"]
    assert post(setup, original, "agent-skills/recover").json() == {"receipt": None}
    saved = post(setup, original).json()
    next_toggle = preview(setup, command(setup, False, revision=1))["command"]
    with Session(setup.admin) as session, session.begin():
        session.scalar(
            select(TenantAdministrator).where(TenantAdministrator.tenant_id == setup.tenant)
        ).active = False
    assert post(setup, next_toggle).status_code == 403
    assert post(setup, original, "agent-skills/recover").json() == {"receipt": saved}
    changed = {**original, "payload": {**original["payload"], "enabled": False}}
    assert (
        post(setup, changed, "agent-skills/recover").json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    )


def test_payload_cannot_enable_unknown_package_or_set_qualification(setup):
    promote(setup)
    data = command(setup)
    forged = {**data, "payload": {**data["payload"], "pilot": True}}
    assert post(setup, forged, "commands/preview").status_code == 422
    data["payload"].update(skill_key="not-configured", skill_version=None, skill_digest=None)
    assert post(setup, data, "commands/preview").json()["code"] == "SOURCE_UNAVAILABLE"
    data["operation"] = "ai.skill.qualify"
    assert post(setup, data, "agent-skills/recover").status_code == 422


def test_removed_skill_can_be_seen_and_disabled_without_loading_it(setup, monkeypatch):
    promote(setup)
    catalog = SkillCatalog()
    skill = catalog.configuration("public_research")
    with Session(setup.admin) as session, session.begin():
        session.add(
            TenantSkillEnablement(tenant_id=setup.tenant, skill_key=skill.key, enabled=True)
        )
    del catalog._skills[skill.key]
    monkeypatch.setattr(skill_management, "SkillCatalog", lambda: catalog)
    read = setup.client.get(path(setup), headers=setup.headers).json()
    item = next(value for value in read["items"] if value["skill_key"] == skill.key)
    assert not item["available"] and item["enabled"]
    data = command(setup, False)
    data["payload"].update(skill_version=None, skill_digest=None)
    prepared = preview(setup, data)["command"]
    assert post(setup, prepared).status_code == 200


def test_concurrent_first_toggles_from_two_categories_share_one_tenant_revision(setup):
    from pdos_next.contracts import Command
    from pdos_next.database import category_transaction
    from pdos_next.errors import DomainError
    from pdos_next.service import execute, preview_command

    promote(setup)
    category = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Category(
                id=category,
                tenant_id=setup.tenant,
                name="第二个合成品类",
                purpose="验证租户共用技能版本",
                owner_id=setup.human,
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=category,
                principal_id=setup.human,
                can_write=True,
                expires_at=now() + timedelta(hours=1),
            )
        )
    first = preview(setup, command(setup))["command"]
    other_ctx = replace(setup.ctx, category_id=category)
    other = command(setup)
    other["category_id"] = str(category)
    second = category_transaction(
        setup.engine,
        other_ctx,
        lambda session: preview_command(session, other_ctx, Command.model_validate(other)),
    )["command"]
    barrier = Barrier(2)

    def write(value):
        ctx, data = value
        barrier.wait(timeout=10)
        try:
            return category_transaction(
                setup.engine,
                ctx,
                lambda session: execute(session, ctx, Command.model_validate(data)),
            )
        except DomainError as failure:
            return failure.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [(setup.ctx, first), (other_ctx, second)]))
    assert sum(isinstance(value, dict) for value in results) == 1
    assert "VERSION_CONFLICT" in results
    with Session(setup.admin) as session:
        rows = session.scalars(
            select(TenantSkillEnablement).where(TenantSkillEnablement.tenant_id == setup.tenant)
        ).all()
        assert len(rows) == 1 and rows[0].revision == 1


def test_actual_toggle_http_latency_and_sql_count(setup):
    import json
    from math import ceil
    from statistics import median
    from time import perf_counter

    from sqlalchemy import event

    promote(setup)
    telemetry = {"active": False, "sql": 0}
    durations, counts = [], []

    def count(*_args):
        if telemetry["active"]:
            telemetry["sql"] += 1

    engines = {setup.engine, setup.auth}
    for engine in engines:
        event.listen(engine, "before_cursor_execute", count)
    try:
        for revision in range(20):
            original = preview(setup, command(setup, revision % 2 == 0, revision))["command"]
            telemetry.update(active=True, sql=0)
            start = perf_counter()
            result = post(setup, original)
            durations.append((perf_counter() - start) * 1000)
            telemetry["active"] = False
            counts.append(telemetry["sql"])
            assert result.status_code == 200, result.text
    finally:
        for engine in engines:
            event.remove(engine, "before_cursor_execute", count)
    print(
        "SKILL_TIMING="
        + json.dumps(
            {
                "operation": "ai.skill.enable",
                "samples": 20,
                "actual_http": True,
                "median_ms": round(median(durations), 2),
                "p95_ms": round(sorted(durations)[ceil(len(durations) * 0.95) - 1], 2),
                "max_ms": round(max(durations), 2),
                "sql_count_min": min(counts),
                "sql_count_max": max(counts),
                "counts_include_auth_and_domain": True,
                "scope": "one synthetic tenant and one skill; not full S1 performance acceptance",
            }
        )
    )
