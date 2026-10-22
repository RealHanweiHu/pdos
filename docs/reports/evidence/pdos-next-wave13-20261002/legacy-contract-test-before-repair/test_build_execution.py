"""Actual facts are independent of Build authorization; root runs the real PG checks.

All observations and identities below are synthetic, explicitly unverified fixtures.
This module must only run against the verified isolated test database.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_builds import (  # noqa: F401 - imported fixture dependencies
    accepted,
    build_command,
    configuration,
    definition,
    project,
)
from test_builds import (
    listed as listed_builds,
)
from test_project_first_plan import cmd, post

from pdos_next.command_handlers import handler
from pdos_next.contracts import PAYLOADS, Command
from pdos_next.database import tenant_session
from pdos_next.domain.build_execution.models import (
    ActualConfiguration,
    BuildLot,
    SampleAllocation,
    SampleUnit,
)
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    Grant,
    Outbox,
    Product,
    Receipt,
    RequestKey,
    now,
)
from pdos_next.service import Context, digest

OPERATIONS = (
    "build.configuration.actual.record",
    "build.output.record",
    "build.sample.allocate",
)
MODELS = (ActualConfiguration, BuildLot, SampleAllocation, SampleUnit)


@pytest.fixture
def planned(setup, configuration):  # noqa: F811 - imported pytest fixture
    built, _ = accepted(setup, build_command(setup, configuration))
    computed = post(
        setup,
        cmd(
            setup,
            "build.readiness.compute",
            {"build_id": built["subject_id"], "expected_build_revision": 1},
            configuration["source"],
        ),
    )
    assert computed.status_code == 200, computed.text
    return {**configuration, "build": built, "before": deepcopy(listed_builds(setup)["items"][0])}


def count(setup, model):
    with tenant_session(setup.engine, setup.tenant) as session:
        return session.scalar(select(func.count()).select_from(model))


def request(setup, operation, payload, source, *, headers=None, preview=False):
    command = cmd(setup, operation, deepcopy(payload), source)
    return setup.client.post(
        "/v1/commands" + ("/preview" if preview else ""),
        headers=headers or setup.headers,
        json=command,
    )


def prepared(setup, command):
    response = post(setup, command, True)
    assert response.status_code == 200, response.text
    return response.json()["command"]


def execution_view(setup, *, headers=None):
    response = setup.client.get(
        f"/v1/products/{setup.product}/build-execution", headers=headers or setup.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def reference(planned):
    return {
        "artifact_id": planned["source"],
        "expected_revision": 1,
        "line": 1,
        "quote": "Synthetic requirement is unverified",
    }


def actual_command(setup, planned, **changes):
    return cmd(
        setup,
        OPERATIONS[0],
        {
            "build_id": planned["build"]["subject_id"],
            "expected_build_revision": 1,
            "actual_engineering_configuration_id": planned["engineering"]["subject_id"],
            "expected_actual_engineering_revision": 1,
            "actual_manufacturing_configuration_id": planned["process"]["subject_id"],
            "expected_actual_manufacturing_revision": 1,
            "observed_at": (now() - timedelta(minutes=5)).isoformat(),
            "differences": [],
            "reason": "Record external synthetic facts without authorization",
            "sources": [reference(planned)],
            **changes,
        },
        planned["source"],
    )


def output_command(setup, planned, actual, *, units=2, **changes):
    return cmd(
        setup,
        OPERATIONS[1],
        {
            "build_id": planned["build"]["subject_id"],
            "expected_build_revision": 1,
            "actual_configuration_id": actual["subject_id"],
            "expected_actual_configuration_revision": 1,
            "lot_label": f"SYN-LOT-{uuid4()}",
            "observed_unit_count": units,
            "unit": "ea",
            "observation": {
                "system": "Synthetic external observation",
                "external_id": str(uuid4()),
                "nature": "synthetic",
                "occurred_at": (now() - timedelta(minutes=1)).isoformat(),
            },
            "reason": "Record the observed quantity without starting a Build",
            "sources": [reference(planned)],
            **changes,
        },
        planned["source"],
    )


def allocation_command(setup, planned, lot, *, labels=None, **changes):
    return cmd(
        setup,
        OPERATIONS[2],
        {
            "lot_id": lot["subject_id"],
            "expected_lot_revision": 1,
            "reason": "Identify synthetic units; testing remains unavailable",
            "samples": [{"label": label} for label in (labels or [f"SYN-{uuid4()}"])],
            "sources": [reference(planned)],
            **changes,
        },
        planned["source"],
    )


@pytest.fixture
def actual(setup, planned):
    receipt, command = accepted(setup, actual_command(setup, planned))
    return {"receipt": receipt, "command": command}


@pytest.fixture
def lot(setup, planned, actual):
    receipt, command = accepted(setup, output_command(setup, planned, actual["receipt"]))
    return {"receipt": receipt, "command": command}


def command_for(setup, planned, actual, lot, operation):
    if operation == OPERATIONS[0]:
        return actual_command(
            setup, planned, reason="Another sourced observed actual configuration"
        )
    if operation == OPERATIONS[1]:
        return output_command(setup, planned, actual["receipt"])
    return allocation_command(setup, planned, lot["receipt"])


def confirmation(setup, command):
    with tenant_session(setup.engine, setup.tenant) as session:
        row = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(command["payload"]["confirmation_token"])
            )
        )
        assert row is not None
        return row.consumed


def assert_atomic_receipt(setup, receipt):
    with tenant_session(setup.engine, setup.tenant) as session:
        stored = session.get(Receipt, UUID(receipt["id"]))
        assert stored.subject_id == UUID(receipt["subject_id"])
        for model in (Audit, Outbox):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.receipt_id == stored.id)
                )
                == 1
            )


def assert_plan_unchanged(setup, planned):
    current = next(
        value
        for value in listed_builds(setup)["items"]
        if value["id"] == planned["build"]["subject_id"]
    )
    for key in (
        "revision",
        "status",
        "planned_quantity",
        "engineering_configuration",
        "manufacturing_configuration",
        "readiness",
    ):
        assert current[key] == planned["before"][key]
    assert current["status"] == "planned"
    assert current["readiness"]["status"] == "blocked"
    assert current["readiness"]["result"]["ready"] is None
    assert current["readiness"]["result"]["hard_blocking"] is True


@pytest.mark.parametrize(
    "operation",
    [
        "build.start",
        "verification.handoff.offer",
        "verification.handoff.accept",
        "test.run.start",
        "release.manufacturing.approve",
    ],
)
def test_unknown_preparation_does_not_enable_start_or_quality_execution(setup, planned, operation):
    response = request(
        setup,
        operation,
        {"build_id": planned["build"]["subject_id"], "expected_build_revision": 1},
        planned["source"],
    )
    assert response.status_code == (
        422
        if operation in {"build.start", "verification.handoff.offer", "verification.handoff.accept"}
        else 403
    ), response.text
    assert_plan_unchanged(setup, planned)


def test_actual_output_and_identity_allocation_preserve_the_fixed_plan(setup, planned, actual, lot):
    allocated, _ = accepted(
        setup, allocation_command(setup, planned, lot["receipt"], labels=["SYN-A", "SYN-B"])
    )
    assert_plan_unchanged(setup, planned)
    view = execution_view(setup)
    assert len(view["actual_configurations"]) == len(view["lots"]) == len(view["allocations"]) == 1
    assert len(view["samples"]) == 2
    recorded_lot = view["lots"][0]
    assert recorded_lot["observed_unit_count"] == 2
    assert recorded_lot["identified_count"] == 2
    assert recorded_lot["remaining_unit_count"] == 0
    assert {sample["label"] for sample in view["samples"]} == {"SYN-A", "SYN-B"}
    for sample in view["samples"]:
        assert sample["actual_configuration_id"] == actual["receipt"]["subject_id"]
        assert sample["lot_id"] == lot["receipt"]["subject_id"]
        assert sample["allocation_id"] == allocated["subject_id"]
        assert sample["availability"] == "unknown"
        assert sample["reservation"] is sample["consumption"] is None
    for receipt in (actual["receipt"], lot["receipt"], allocated):
        assert_atomic_receipt(setup, receipt)


def test_observed_overproduction_is_recorded_but_never_grants_start(setup, planned, actual):
    receipt, _ = accepted(setup, output_command(setup, planned, actual["receipt"], units=12))
    recorded = next(
        row for row in execution_view(setup)["lots"] if row["id"] == receipt["subject_id"]
    )
    assert recorded["observed_unit_count"] == 12
    assert recorded["over_planned_quantity"] is True
    accepted(
        setup,
        allocation_command(setup, planned, receipt, labels=[f"SYN-OVER-{i}" for i in range(12)]),
    )
    assert count(setup, SampleUnit) == 12
    assert_plan_unchanged(setup, planned)
    response = request(
        setup, "build.start", {"build_id": planned["build"]["subject_id"]}, planned["source"]
    )
    assert response.status_code == 422


def test_two_observed_lots_show_cumulative_over_plan_without_rejecting_actual_facts(
    setup, planned, actual
):
    first, _ = accepted(setup, output_command(setup, planned, actual["receipt"], units=6))
    first_view = next(
        value for value in execution_view(setup)["lots"] if value["id"] == first["subject_id"]
    )
    assert first_view["build_observed_unit_count"] == 6
    assert first_view["over_planned_quantity"] is False
    preview = post(setup, output_command(setup, planned, actual["receipt"], units=6), True)
    assert preview.status_code == 200, preview.text
    reviewed = preview.json()["review"]["after"]
    assert reviewed["build_observed_unit_count_before"] == 6
    assert reviewed["build_observed_unit_count_after"] == 12
    assert reviewed["over_planned_quantity"] is True
    saved = post(setup, preview.json()["command"])
    assert saved.status_code == 200, saved.text
    second = saved.json()
    lots = execution_view(setup)["lots"]
    assert {value["id"] for value in lots} == {first["subject_id"], second["subject_id"]}
    assert all(value["observed_unit_count"] == 6 for value in lots)
    assert all(value["build_observed_unit_count"] == 12 for value in lots)
    assert all(value["over_planned_quantity"] is True for value in lots)
    for index, recorded in enumerate((first, second)):
        accepted(
            setup,
            allocation_command(
                setup,
                planned,
                recorded,
                labels=[f"SYN-CUMULATIVE-{index}-{unit}" for unit in range(6)],
            ),
        )
    assert count(setup, SampleUnit) == 12
    assert_plan_unchanged(setup, planned)


def alternate_configurations(setup, planned):
    engineering_payload = {
        **deepcopy(planned["engineering_payload"]),
        "name": "Synthetic actual mechanical revision",
        "reason": "Record a distinct fixed external mechanical revision",
        "mechanical": {
            "system": "Synthetic PLM",
            "external_id": "CAD-ACTUAL-2",
            "revision": "R2",
            "basis": reference(planned),
        },
    }
    engineering, _ = accepted(
        setup,
        cmd(setup, "engineering.configuration.create", engineering_payload, planned["source"]),
    )
    process_payload = {
        **deepcopy(planned["process_payload"]),
        "name": "Synthetic actual manufacturing revision",
        "reason": "Record actual linked manufacturing with an explicit unknown method",
        "engineering_configuration_id": engineering["subject_id"],
    }
    process_payload["operations"][0]["notes"] = "Unverified distinct actual assembly context"
    process, _ = accepted(
        setup, cmd(setup, "npi.process.revise", process_payload, planned["source"])
    )
    return engineering, process


def actual_comparison(setup, planned, engineering, process):
    response = setup.client.get(
        f"/v1/products/{setup.product}/build-execution/compare",
        headers=setup.headers,
        params={
            "build_id": planned["build"]["subject_id"],
            "engineering_configuration_id": engineering["subject_id"],
            "manufacturing_configuration_id": process["subject_id"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_changed_actual_configuration_and_two_lots_never_average_or_rewrite_plan(
    setup, planned, actual, lot
):
    engineering, process = alternate_configurations(setup, planned)
    comparison = actual_comparison(setup, planned, engineering, process)
    assert comparison["differences"]
    changes = [
        {
            "path": difference["path"],
            "reason": "Explicit observed deviation",
            "sources": [reference(planned)],
        }
        for difference in comparison["differences"]
    ]
    recorded, _ = accepted(
        setup,
        actual_command(
            setup,
            planned,
            reason="Record synthetic changed actual configuration",
            actual_engineering_configuration_id=engineering["subject_id"],
            actual_manufacturing_configuration_id=process["subject_id"],
            differences=changes,
        ),
    )
    second_lot, _ = accepted(setup, output_command(setup, planned, recorded, units=1))
    accepted(
        setup, allocation_command(setup, planned, lot["receipt"], labels=["SYN-PLANNED-BASIS"])
    )
    accepted(setup, allocation_command(setup, planned, second_lot, labels=["SYN-ACTUAL-BASIS"]))
    view = execution_view(setup)
    lots_by_id = {row["id"]: row for row in view["lots"]}
    samples_by_label = {row["label"]: row for row in view["samples"]}
    assert (
        lots_by_id[lot["receipt"]["subject_id"]]["actual_configuration_id"]
        == actual["receipt"]["subject_id"]
    )
    assert lots_by_id[second_lot["subject_id"]]["actual_configuration_id"] == recorded["subject_id"]
    assert (
        samples_by_label["SYN-PLANNED-BASIS"]["actual_configuration_id"]
        == actual["receipt"]["subject_id"]
    )
    assert samples_by_label["SYN-ACTUAL-BASIS"]["actual_configuration_id"] == recorded["subject_id"]
    saved_actual = next(
        row for row in view["actual_configurations"] if row["id"] == recorded["subject_id"]
    )
    assert {item["path"] for item in saved_actual["differences"]} == {
        item["path"] for item in comparison["differences"]
    }
    for expected in comparison["differences"]:
        saved = next(
            item for item in saved_actual["differences"] if item["path"] == expected["path"]
        )
        assert saved["before"] == expected["before"] and saved["after"] == expected["after"]
    assert_plan_unchanged(setup, planned)


def test_actual_deviation_cannot_omit_changed_paths_or_forge_comparison_values(setup, planned):
    engineering, process = alternate_configurations(setup, planned)
    comparison = actual_comparison(setup, planned, engineering, process)
    command = actual_command(
        setup,
        planned,
        actual_engineering_configuration_id=engineering["subject_id"],
        actual_manufacturing_configuration_id=process["subject_id"],
        differences=[],
    )
    missing = post(setup, command, True)
    assert missing.status_code in {409, 422}, missing.text
    command["payload"]["differences"] = [
        {
            "path": difference["path"],
            "reason": "Explicit observed deviation",
            "sources": [reference(planned)],
            "before": "Invented planned firmware",
            "after": "Invented actual firmware",
        }
        for difference in comparison["differences"]
    ]
    forged = post(setup, command, True)
    assert forged.status_code == 422, forged.text
    assert count(setup, ActualConfiguration) == 0


def test_actual_engineering_and_manufacturing_must_be_a_linked_pair(setup, planned):
    engineering, _ = alternate_configurations(setup, planned)
    response = post(
        setup,
        actual_command(
            setup, planned, actual_engineering_configuration_id=engineering["subject_id"]
        ),
        True,
    )
    assert response.status_code == 409 and response.json()["code"] == "CONFIGURATION_MISMATCH"
    assert count(setup, ActualConfiguration) == 0


@pytest.mark.parametrize("operation", OPERATIONS)
def test_actual_operations_require_t1_and_stable_replay_has_one_receipt(
    setup, planned, actual, lot, operation
):
    command = command_for(setup, planned, actual, lot, operation)
    refused = post(setup, command)
    assert refused.status_code == 409 and refused.json()["code"] == "CONFIRMATION_REQUIRED"
    before = {model: count(setup, model) for model in MODELS}
    receipt, reviewed = accepted(setup, command)
    assert confirmation(setup, reviewed) is True
    assert post(setup, reviewed).json()["id"] == receipt["id"]
    replay = {**reviewed, "command_id": str(uuid4()), "idempotency_key": str(uuid4())}
    assert post(setup, replay).json()["id"] == receipt["id"]
    with Session(setup.admin) as session, session.begin():
        session.execute(update(Product).where(Product.id == setup.product).values(revision=2))
    replayed = post(setup, reviewed)
    assert replayed.status_code == 200 and replayed.json()["id"] == receipt["id"]
    target = {
        OPERATIONS[0]: ActualConfiguration,
        OPERATIONS[1]: BuildLot,
        OPERATIONS[2]: SampleAllocation,
    }
    assert count(setup, target[operation]) == before[target[operation]] + 1
    assert_atomic_receipt(setup, receipt)
    assert_plan_unchanged(setup, planned)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_actual_confirmation_binds_the_substantive_payload(setup, planned, actual, lot, operation):
    reviewed = prepared(setup, command_for(setup, planned, actual, lot, operation))
    before = {model: count(setup, model) for model in MODELS}
    changed = deepcopy(reviewed)
    field = {
        OPERATIONS[0]: ("reason", "Changed actual configuration reason"),
        OPERATIONS[1]: ("observed_unit_count", 99),
        OPERATIONS[2]: ("samples", [{"label": "SYN-SUBSTITUTED"}]),
    }[operation]
    changed["payload"][field[0]] = field[1]
    response = post(setup, changed)
    assert response.status_code == 409 and response.json()["code"] == "CONFIRMATION_SCOPE_CHANGED"
    assert confirmation(setup, reviewed) is False
    assert {model: count(setup, model) for model in MODELS} == before


@pytest.mark.parametrize("change", ["withdrawn", "stale", "grant", "actor", "expiry", "readset"])
def test_actual_confirmation_rechecks_current_sources_authority_and_expiry(
    setup, planned, actual, lot, change
):
    reviewed = prepared(setup, allocation_command(setup, planned, lot["receipt"]))
    headers = setup.headers
    if change == "actor":
        headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    elif change == "readset":
        reviewed["source_read_set"] = []
    else:
        with Session(setup.admin) as session, session.begin():
            if change == "grant":
                session.execute(
                    update(Grant)
                    .where(Grant.product_id == setup.product, Grant.principal_id == setup.human)
                    .values(expires_at=now() - timedelta(seconds=1))
                )
            elif change == "expiry":
                session.execute(
                    update(Confirmation)
                    .where(
                        Confirmation.token_hash == digest(reviewed["payload"]["confirmation_token"])
                    )
                    .values(expires_at=now() - timedelta(seconds=1))
                )
            else:
                session.execute(
                    update(Artifact)
                    .where(Artifact.id == UUID(planned["source"]))
                    .values(
                        **({"status": "withdrawn"} if change == "withdrawn" else {"revision": 2})
                    )
                )
    result = setup.client.post("/v1/commands", headers=headers, json=reviewed)
    assert result.status_code in {403, 409}, result.text
    assert count(setup, SampleAllocation) == count(setup, SampleUnit) == 0
    assert confirmation(setup, reviewed) is False


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("change", ["grant", "source"])
def test_current_access_and_sources_are_checked_even_for_committed_fact_replay(
    setup, planned, actual, lot, operation, change
):
    receipt, reviewed = accepted(setup, command_for(setup, planned, actual, lot, operation))
    with Session(setup.admin) as session, session.begin():
        if change == "grant":
            session.execute(
                update(Grant)
                .where(Grant.product_id == setup.product, Grant.principal_id == setup.human)
                .values(expires_at=now() - timedelta(seconds=1))
            )
        else:
            session.execute(
                update(Artifact)
                .where(Artifact.id == UUID(planned["source"]))
                .values(status="withdrawn")
            )
    response = post(setup, reviewed)
    assert response.status_code in {403, 409}, response.text
    assert_atomic_receipt(setup, receipt)


@pytest.mark.parametrize("actor,run", [("agent", False), ("human", True)])
def test_recording_physical_facts_requires_the_current_named_human_without_agent_run(
    setup, planned, actor, run
):
    command = Command.model_validate(actual_command(setup, planned))
    context = Context(setup.tenant, getattr(setup, actor), setup.human, uuid4() if run else None)
    with tenant_session(setup.engine, setup.tenant) as session:
        with pytest.raises(DomainError) as refused:
            handler(command.operation).validate(
                session,
                context,
                command,
                session.get(Product, setup.product),
                PAYLOADS[command.operation].model_validate(command.payload),
            )
    assert refused.value.code == "NAMED_DECISION_REQUIRED"
    assert count(setup, ActualConfiguration) == 0


def test_factual_sources_must_be_exact_and_cannot_be_omitted_from_the_read_set(setup, planned):
    fabricated = actual_command(setup, planned)
    fabricated["payload"]["sources"][0]["quote"] = "Invented actual production evidence"
    response = post(setup, fabricated, True)
    assert response.status_code == 409 and response.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    omitted = actual_command(setup, planned)
    omitted["source_read_set"] = []
    response = post(setup, omitted, True)
    assert response.status_code == 409 and response.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    assert count(setup, ActualConfiguration) == 0


@pytest.mark.parametrize("operation", OPERATIONS)
def test_end_of_transaction_failure_rolls_back_all_facts_and_t1_consumption(
    setup, planned, actual, lot, operation, monkeypatch
):
    import pdos_next.service as commands

    reviewed = prepared(setup, command_for(setup, planned, actual, lot, operation))
    before = {model: count(setup, model) for model in (*MODELS, Receipt, Audit, Outbox, RequestKey)}
    original = commands.append_receipt

    def fail_after_facts(session, context, command, *args, **kwargs):
        if command.operation == operation:
            raise DomainError("SYNTHETIC_RECEIPT_FAILURE", "Synthetic final-stage rollback")
        return original(session, context, command, *args, **kwargs)

    monkeypatch.setattr(commands, "append_receipt", fail_after_facts)
    failed = post(setup, reviewed)
    assert failed.status_code == 409 and failed.json()["code"] == "SYNTHETIC_RECEIPT_FAILURE"
    assert {model: count(setup, model) for model in before} == before
    assert confirmation(setup, reviewed) is False
    monkeypatch.setattr(commands, "append_receipt", original)
    retried = post(setup, reviewed)
    assert retried.status_code == 200, retried.text
    assert_atomic_receipt(setup, retried.json())


def test_concurrent_same_allocation_intent_creates_each_identity_only_once(setup, planned, lot):
    reviewed = prepared(
        setup, allocation_command(setup, planned, lot["receipt"], labels=["SYN-REPLAY"])
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: post(setup, reviewed), range(3)))
    assert all(response.status_code == 200 for response in responses), [r.text for r in responses]
    assert len({response.json()["id"] for response in responses}) == 1
    assert count(setup, SampleAllocation) == count(setup, SampleUnit) == 1
    assert_atomic_receipt(setup, responses[0].json())


def test_concurrent_distinct_allocations_cannot_exceed_observed_units(setup, planned, actual):
    output, _ = accepted(setup, output_command(setup, planned, actual["receipt"], units=1))
    reviewed = [
        prepared(setup, allocation_command(setup, planned, output, labels=[label]))
        for label in ("SYN-RACE-A", "SYN-RACE-B")
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda command: post(setup, command), reviewed))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert count(setup, SampleAllocation) == count(setup, SampleUnit) == 1
    recorded = next(
        row for row in execution_view(setup)["lots"] if row["id"] == output["subject_id"]
    )
    assert recorded["identified_count"] == 1 and recorded["remaining_unit_count"] == 0
    assert sum(confirmation(setup, command) for command in reviewed) == 1


def test_duplicate_physical_label_is_rejected_across_allocations_and_lots(
    setup, planned, actual, lot
):
    accepted(setup, allocation_command(setup, planned, lot["receipt"], labels=["SYN-ONE-IDENTITY"]))
    second, _ = accepted(setup, output_command(setup, planned, actual["receipt"], units=1))
    response = post(
        setup,
        allocation_command(setup, planned, second, labels=["SYN-ONE-IDENTITY"]),
        True,
    )
    if response.status_code == 200:
        response = post(setup, response.json()["command"])
    assert response.status_code == 409, response.text
    assert count(setup, SampleUnit) == count(setup, SampleAllocation) == 1


def test_allocation_cannot_create_more_identities_than_actual_output(setup, planned, lot):
    response = post(
        setup,
        allocation_command(setup, planned, lot["receipt"], labels=["SYN-A", "SYN-B", "SYN-C"]),
        True,
    )
    if response.status_code == 200:
        response = post(setup, response.json()["command"])
    assert response.status_code == 409, response.text
    assert count(setup, SampleAllocation) == count(setup, SampleUnit) == 0


def test_private_facts_and_samples_are_hidden_from_peer_and_other_tenant(setup, planned, lot):
    accepted(setup, allocation_command(setup, planned, lot["receipt"], labels=["SYN-PRIVATE"]))
    peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert all(
        execution_view(setup, headers=peer_headers)[key] == []
        for key in ("actual_configurations", "lots", "allocations", "samples")
    )
    outsider = setup.client.get(
        f"/v1/products/{setup.product}/build-execution",
        headers={"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
    )
    assert outsider.status_code == 403
    attempted = request(
        setup,
        OPERATIONS[2],
        allocation_command(setup, planned, lot["receipt"])["payload"],
        planned["source"],
        headers=peer_headers,
        preview=True,
    )
    assert attempted.status_code == 403


def test_same_external_observation_cannot_be_duplicated_by_changing_command_or_lot_label(
    setup, planned, actual, lot
):
    command = deepcopy(lot["command"])
    command["command_id"] = str(uuid4())
    command["idempotency_key"] = str(uuid4())
    command["payload"].pop("confirmation_token")
    command["payload"]["lot_label"] = "Renamed same external observation"
    response = post(setup, command, True)
    if response.status_code == 200:
        response = post(setup, response.json()["command"])
    assert response.status_code == 409, response.text
    assert count(setup, BuildLot) == 1


def test_actual_facts_cannot_cross_product_even_with_a_current_grant(setup, planned, actual):
    other_product = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Product(
                id=other_product,
                tenant_id=setup.tenant,
                owner_id=setup.human,
                name="Other isolated synthetic product",
                purpose="Verify actual objects stay within their fixed product",
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=setup.tenant,
                product_id=other_product,
                principal_id=setup.human,
                can_write=True,
                expires_at=now() + timedelta(hours=1),
            )
        )
    command = output_command(setup, planned, actual["receipt"])
    command["product_id"] = str(other_product)
    response = post(setup, command, True)
    assert response.status_code == 403, response.text
    assert count(setup, BuildLot) == 0
    with tenant_session(setup.engine, setup.tenant) as session:
        original = session.get(ActualConfiguration, UUID(actual["receipt"]["subject_id"]))
        values = {
            column.name: getattr(original, column.name)
            for column in ActualConfiguration.__table__.columns
        }
    values.update(id=uuid4(), product_id=other_product)
    with pytest.raises(DBAPIError), Session(setup.admin) as session, session.begin():
        session.add(ActualConfiguration(**values))
        session.flush()


def test_unknown_sample_availability_cannot_be_substituted_with_client_readiness(
    setup, planned, lot
):
    command = allocation_command(setup, planned, lot["receipt"], labels=["SYN-FAKE-READY"])
    command["payload"]["samples"][0].update(
        availability="available", qualified=True, applicable=True, consumed=False
    )
    response = post(setup, command, True)
    assert response.status_code == 422, response.text
    assert count(setup, SampleUnit) == 0


@pytest.mark.parametrize("field", ["tenant_id", "actor_id", "authorized", "received_at", "status"])
def test_output_payload_cannot_supply_trusted_scope_authority_or_receipt_facts(
    setup, planned, actual, field
):
    command = output_command(setup, planned, actual["receipt"])
    command["payload"][field] = {
        "tenant_id": str(setup.tenant),
        "actor_id": str(setup.human),
        "authorized": True,
        "received_at": now().isoformat(),
        "status": "executing",
    }[field]
    response = post(setup, command, True)
    assert response.status_code == 422, response.text
    assert count(setup, BuildLot) == 0


def test_all_actual_tables_are_forced_scoped_immutable_and_agent_has_zero_write(
    setup, planned, lot
):
    accepted(setup, allocation_command(setup, planned, lot["receipt"], labels=["SYN-IMMUTABLE"]))
    for model in MODELS:
        with Session(setup.engine) as session:
            assert session.scalar(select(func.count()).select_from(model)) == 0
        for engine in (setup.engine, setup.admin):
            with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
                session.execute(
                    update(model)
                    .where(model.tenant_id == setup.tenant)
                    .values(reason="Invalid overwrite of immutable observed history")
                )
    with setup.admin.connect() as connection:
        for model in MODELS:
            name = model.__tablename__
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


@pytest.mark.parametrize("count_value", [0, -1, True, 1.0, "2", 1000001])
def test_observed_output_count_must_be_a_positive_bounded_discrete_integer(
    setup, planned, actual, count_value
):
    response = post(
        setup, output_command(setup, planned, actual["receipt"], units=count_value), True
    )
    assert response.status_code == 422, response.text
    assert count(setup, BuildLot) == 0


@pytest.mark.parametrize(
    "change", ["mass_unit", "nature_unknown", "naive_time", "future", "received_at"]
)
def test_external_observation_cannot_claim_system_time_or_unsupported_facts(
    setup, planned, actual, change
):
    command = output_command(setup, planned, actual["receipt"])
    if change == "mass_unit":
        command["payload"]["unit"] = "kg"
    elif change == "nature_unknown":
        command["payload"]["observation"]["nature"] = "verified"
    elif change == "naive_time":
        command["payload"]["observation"]["occurred_at"] = "2026-10-02T01:00:00"
    elif change == "future":
        command["payload"]["observation"]["occurred_at"] = (now() + timedelta(days=1)).isoformat()
    else:
        command["payload"]["observation"]["received_at"] = now().isoformat()
    response = post(setup, command, True)
    assert response.status_code in {409, 422}, response.text
    assert count(setup, BuildLot) == 0
