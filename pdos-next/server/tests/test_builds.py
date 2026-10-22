from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, cmd, definition, post, project  # noqa: F401

from pdos_next.database import tenant_session
from pdos_next.domain.builds.models import Build, BuildReadiness
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Confirmation, Grant, Outbox, Product, now


@pytest.fixture
def configuration(setup, definition, project):  # noqa: F811 - imported pytest fixtures
    source, defined = definition
    reference = {
        "artifact_id": source,
        "expected_revision": 1,
        "line": 1,
        "quote": "Synthetic requirement is unverified",
    }
    common = {
        "visibility": "private",
        "reason": "Synthetic fixed preparation",
        "sources": [reference],
    }
    bom_payload = {
        **common,
        "name": "Synthetic BOM",
        "lines": [
            {
                "key": "motor",
                "part": {"name": "Synthetic motor", "internal_number": "RD-MOTOR"},
                "quantity": "2",
                "unit": "ea",
                "loss_rate": "0.1",
                "critical": True,
            },
            {
                "key": "unknown",
                "part": {"name": "Unknown housing"},
                "quantity": None,
                "unit": "ea",
                "loss_rate": None,
            },
        ],
    }
    bom, _ = accepted(setup, cmd(setup, "engineering.bom.revise", bom_payload, source))
    engineering_payload = {
        **common,
        "name": "Synthetic engineering configuration",
        "definition_id": defined,
        "expected_definition_revision": 1,
        "bom_id": bom["subject_id"],
        "expected_bom_revision": 1,
    }
    engineering, _ = accepted(
        setup, cmd(setup, "engineering.configuration.create", engineering_payload, source)
    )
    process_payload = {
        **common,
        "name": "Synthetic manufacturing configuration",
        "engineering_configuration_id": engineering["subject_id"],
        "expected_engineering_revision": 1,
        "operations": [
            {
                "key": "assembly",
                "name": "Synthetic assembly",
                "kind": "assembly",
                "bom_line_keys": ["motor"],
            }
        ],
    }
    process, _ = accepted(setup, cmd(setup, "npi.process.revise", process_payload, source))
    return {
        "source": source,
        "definition": defined,
        "project": project,
        "bom": bom,
        "engineering": engineering,
        "process": process,
        "bom_payload": bom_payload,
        "engineering_payload": engineering_payload,
        "process_payload": process_payload,
    }


def build_command(setup, config, **overrides):
    return cmd(
        setup,
        "build.create",
        {
            "project_id": config["project"],
            "expected_project_revision": 1,
            "engineering_configuration_id": config["engineering"]["subject_id"],
            "manufacturing_configuration_id": config["process"]["subject_id"],
            "name": "Synthetic first prototype",
            "type": "prototype",
            "purpose": "Verify preparation",
            "planned_quantity": "10",
            "unit": "ea",
            "planned_start": None,
            "planned_end": None,
            "verification_objectives": "Verify motor and housing fit",
            "disposition_plan": "Retain synthetic samples for review",
            **overrides,
        },
        config["source"],
    )


def listed(setup, headers=None):
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/builds",
        headers=headers or setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def counts(setup, table):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        return s.scalar(select(func.count()).select_from(table))


def test_plan_requires_confirmation_and_duplicate_is_one_atomic_receipt(setup, configuration):
    command = build_command(setup, configuration)
    assert post(setup, command).json()["code"] == "CONFIRMATION_REQUIRED"
    receipt, prepared = accepted(setup, command)
    assert post(setup, prepared).json()["id"] == receipt["id"]
    replay = {**prepared, "command_id": str(uuid4()), "idempotency_key": str(uuid4())}
    replay["payload"] = {**replay["payload"], "planned_quantity": "10.000"}
    assert post(setup, replay).json()["id"] == receipt["id"]
    row = listed(setup)["items"][0]
    assert row["status"] == "planned" and row["readiness"] is None
    assert row["planned_start"] is row["planned_end"] is None
    assert row["engineering_configuration"]["definition_id"] == configuration["definition"]
    assert (
        row["manufacturing_configuration"]["engineering_configuration_id"]
        == (configuration["engineering"]["subject_id"])
    )
    assert counts(setup, Build) == 1
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        for model in (Audit, Outbox):
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.receipt_id == UUID(receipt["id"]))
                )
                == 1
            )


def test_committed_request_replays_after_product_revision_advances(setup, configuration):
    receipt, prepared = accepted(setup, build_command(setup, configuration))
    with Session(setup.admin) as s, s.begin():
        s.execute(update(Product).where(Product.id == setup.product).values(revision=2))
    assert post(setup, prepared).json()["id"] == receipt["id"]
    fresh = build_command(setup, configuration, name="New build after product changes")
    assert post(setup, fresh, True).json()["code"] == "VERSION_CONFLICT"
    assert counts(setup, Build) == 1


@pytest.mark.parametrize("change", ["quantity", "engineering", "sources", "actor"])
def test_confirmation_does_not_cover_changed_material(setup, configuration, change):
    reviewed = post(setup, build_command(setup, configuration), True).json()["command"]
    headers = setup.headers
    if change == "quantity":
        reviewed["payload"]["planned_quantity"] = "99"
    elif change == "engineering":
        reviewed["payload"]["engineering_configuration_id"] = str(uuid4())
    elif change == "sources":
        reviewed["source_read_set"] = []
    else:
        headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    result = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=headers, json=reviewed
    )
    assert result.status_code in {403, 409}
    assert counts(setup, Build) == 0
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert (
            s.scalar(select(Confirmation).where(Confirmation.operation == "build.create")).consumed
            is False
        )


def test_readiness_unknowns_never_mean_start_and_readiness_replay_is_fixed(setup, configuration):
    built, _ = accepted(setup, build_command(setup, configuration))
    command = cmd(
        setup,
        "build.readiness.compute",
        {
            "build_id": built["subject_id"],
            "expected_build_revision": 1,
        },
        configuration["source"],
    )
    computed = post(setup, command)
    assert computed.status_code == 200, computed.text
    assert post(setup, command).json()["id"] == computed.json()["id"]
    row = listed(setup)["items"][0]
    result = row["readiness"]["result"]
    assert row["status"] == "planned" and result["ready"] is None
    assert result["hard_blocking"] is True and counts(setup, BuildReadiness) == 1
    demands = {item["item_id"]: item for item in result["demands"]}
    assert float(demands["motor"]["required_quantity"]) == 22
    assert demands["unknown"]["required_quantity"] is None
    assert result["coverage"]["input_snapshot"]["supply_scope_complete"] is False
    assert result["coverage"]["input_snapshot"]["pools"] == []
    # A preparation result cannot serve as the newly implemented start payload:
    # start requires its own exact assessment, both approvals and actual event.
    assert post(setup, {**command, "operation": "build.start"}).status_code == 422
    assert post(setup, {**command, "operation": "release.manufacturing.approve"}).status_code == 403


def test_new_configuration_revision_never_rewrites_old_build(setup, configuration):
    accepted(setup, build_command(setup, configuration))
    original = listed(setup)["items"][0]
    revised = {
        **configuration["bom_payload"],
        "previous_id": configuration["bom"]["subject_id"],
        "expected_previous_revision": 1,
        "reason": "Explicit new quantities",
    }
    revised["lines"] = deepcopy(revised["lines"])
    fixed_parts = {
        line["key"]: line for line in original["engineering_configuration"]["bom"]["lines"]
    }
    for line in revised["lines"]:
        line.pop("part")
        line["part_id"] = fixed_parts[line["key"]]["part_id"]
        line["expected_part_revision"] = fixed_parts[line["key"]]["expected_part_revision"]
    revised["lines"][0]["quantity"] = "7"
    bom, _ = accepted(setup, cmd(setup, "engineering.bom.revise", revised, configuration["source"]))
    engineering = {
        **configuration["engineering_payload"],
        "bom_id": bom["subject_id"],
        "expected_bom_revision": 2,
        "previous_id": configuration["engineering"]["subject_id"],
        "expected_previous_revision": 1,
        "reason": "Explicit next engineering revision",
    }
    new_eng, _ = accepted(
        setup, cmd(setup, "engineering.configuration.create", engineering, configuration["source"])
    )
    assert listed(setup)["items"][0] == original
    mismatch = post(
        setup,
        build_command(setup, configuration, engineering_configuration_id=new_eng["subject_id"]),
        True,
    )
    assert mismatch.status_code == 409 and mismatch.json()["code"] == "VALIDATION_FAILED"
    assert mismatch.json()["detail"]["reason"] == "CONFIGURATION_MISMATCH"


@pytest.mark.parametrize("change", ["withdraw", "stale", "grant"])
def test_saved_replay_requires_read_access_and_new_compute_requires_current_sources(
    setup, configuration, change
):
    receipt, prepared = accepted(setup, build_command(setup, configuration))
    with Session(setup.admin) as s, s.begin():
        if change == "grant":
            s.execute(
                update(Grant)
                .where(Grant.category_id == setup.category, Grant.principal_id == setup.human)
                .values(expires_at=now() - timedelta(seconds=1))
            )
        else:
            s.execute(
                update(Artifact)
                .where(Artifact.id == UUID(configuration["source"]))
                .values(**({"status": "withdrawn"} if change == "withdraw" else {"revision": 2}))
            )
    replay = post(setup, prepared)
    if change == "grant":
        assert replay.status_code == 403 and replay.json()["code"] == "FORBIDDEN_SCOPE", replay.text
    else:
        assert replay.status_code == 200 and replay.json()["id"] == receipt["id"], replay.text
    result = post(
        setup,
        cmd(
            setup,
            "build.readiness.compute",
            {
                "build_id": receipt["subject_id"],
                "expected_build_revision": 1,
            },
            configuration["source"],
        ),
    )
    assert result.status_code in {403, 409}
    assert counts(setup, BuildReadiness) == 0


def test_private_build_and_sources_are_not_visible_to_peer(setup, configuration):
    accepted(setup, build_command(setup, configuration))
    assert listed(setup, {"Authorization": f"Bearer {setup.tokens[setup.peer]}"})["items"] == []
    outsider = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/builds",
        headers={"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
    )
    assert outsider.status_code == 403


def test_historical_readiness_is_marked_stale_without_rewriting_snapshot(setup, configuration):
    receipt, _ = accepted(setup, build_command(setup, configuration))
    command = cmd(
        setup,
        "build.readiness.compute",
        {
            "build_id": receipt["subject_id"],
            "expected_build_revision": 1,
        },
        configuration["source"],
    )
    assert post(setup, command).status_code == 200
    before = listed(setup)["items"][0]
    with Session(setup.admin) as s, s.begin():
        s.execute(
            update(Artifact)
            .where(Artifact.id == UUID(configuration["source"]))
            .values(status="withdrawn")
        )
    after = listed(setup)["items"][0]
    assert after["source_status"] == "needs_recheck"
    assert after["readiness"]["is_current"] is False
    assert before["readiness"]["result"] == after["readiness"]["result"]


def test_failed_receipt_rolls_back_plan_and_confirmation(setup, configuration, monkeypatch):
    import pdos_next.service as commands

    prepared = post(setup, build_command(setup, configuration), True).json()["command"]
    original = commands.append_receipt

    def refuse(*args, **kwargs):
        if args[2].operation == "build.create":
            raise DomainError("SYNTHETIC_FAILURE", "Injected receipt failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(commands, "append_receipt", refuse)
    failed = post(setup, prepared)
    assert failed.status_code == 500 and failed.json()["code"] == "INTERNAL_ERROR"
    assert failed.json()["detail"]["reason"] == "UNREGISTERED_REASON"
    assert counts(setup, Build) == 0
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert (
            s.scalar(select(Confirmation).where(Confirmation.operation == "build.create")).consumed
            is False
        )
    monkeypatch.setattr(commands, "append_receipt", original)
    assert post(setup, prepared).status_code == 200


def test_concurrent_retry_produces_one_build(setup, configuration):
    prepared = post(setup, build_command(setup, configuration), True).json()["command"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: post(setup, prepared), range(3)))
    assert all(response.status_code == 200 for response in results)
    assert len({response.json()["id"] for response in results}) == 1
    assert counts(setup, Build) == 1


def test_build_snapshots_have_rls_and_no_application_update(setup, configuration):
    receipt, _ = accepted(setup, build_command(setup, configuration))
    with Session(setup.engine) as s:
        assert s.scalar(select(func.count()).select_from(Build)) == 0
    with (
        pytest.raises(DBAPIError),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as s,
    ):
        s.execute(
            update(Build).where(Build.id == UUID(receipt["subject_id"])).values(name="Override")
        )
    with setup.admin.connect() as connection:
        for name in ("builds", "build_readiness"):
            assert connection.scalar(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                    "WHERE relname=:name"
                ),
                {"name": name},
            )
            assert not connection.scalar(
                text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),
                {"name": name},
            )


@pytest.mark.parametrize("quantity", [0, -1, "NaN", "Infinity", 1.5, True, "0.000000001"])
def test_invalid_build_quantity_is_rejected(setup, configuration, quantity):
    result = post(setup, build_command(setup, configuration, planned_quantity=quantity), True)
    assert result.status_code == 422


@pytest.mark.parametrize(
    "change",
    [
        {"planned_start": "2026-10-02T08:00:00"},
        {"planned_start": "2026-10-03T08:00:00Z", "planned_end": "2026-10-02T08:00:00Z"},
        {"expected_project_revision": 99},
    ],
)
def test_invalid_or_stale_plan_rejected(setup, configuration, change):
    response = post(setup, build_command(setup, configuration, **change), True)
    if response.status_code == 200:
        response = post(setup, response.json()["command"])
    assert response.status_code in {409, 422}
    assert counts(setup, Build) == 0
