"""Real host transaction guards; only root executes against the isolated test database."""

# ruff: noqa: F811 - pytest fixture dependency imports are deliberate
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, post
from verification_handoff.fixtures import handoff as handoff_command

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import OperationalAsset, ResourceOccupancy
from pdos_next.domain.test_resources.models import (
    SampleRunUsage,
    SampleUsageSentinel,
    TestResourceReservation,
)
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Principal, Receipt, RequestKey
from pdos_next.schemas.verification.contracts import EventTime
from pdos_next.service import Context, digest, execute
from pdos_next.test_resource_import import import_test_resource_fact
from verification_launch.fixtures import (  # noqa: F401
    accepted_work,
    advance_clock,
    command,
    current,
    fixed_run,
    known_configuration,
    launch_work,
    listing,
    operational_work,
    planned,
    promised,
    ready_work,
    started,
)


def counts(work):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        return {
            model.__tablename__: s.scalar(select(func.count()).select_from(model))
            for model in (
                FormalVerificationRequest,
                VerificationRunIdentity,
                VerificationRunVersion,
                VerificationRunCurrent,
                VerificationLaunchFact,
                TestResourceReservation,
                SampleRunUsage,
                SampleUsageSentinel,
                ResourceOccupancy,
                Receipt,
                Audit,
                Outbox,
                RequestKey,
            )
        }


def preview(work, value):
    result = post(work.quality, value, True)
    assert result.status_code == 200, result.text
    return result.json()


def unconsumed(work, prepared):
    token = prepared["payload"]["confirmation_token"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        assert (
            s.scalar(select(Confirmation.consumed).where(Confirmation.token_hash == digest(token)))
            is False
        )


def test_fixed_full_accepted_plan_promise_and_atomic_actual_start_leave_old_history(
    launch_work, monkeypatch
):
    work = launch_work
    baseline = counts(work)
    old = deepcopy(work.accepted_request)
    view = listing(work)
    assert len(view["reference_samples"]) == 2
    assert all(
        row["label"] and row["actual_configuration"]["revision"] == 1
        for row in view["reference_samples"]
    )
    row = current(work, view)
    assert row["capabilities"]["run_plan"]
    plan_receipt, _ = planned(work)
    assert plan_receipt["subject_type"] == "test_run"
    after_plan = listing(work)
    saved = fixed_run(work, after_plan)
    assert saved["status"] == "planned" and saved["zero_occupancy"] and saved["occupancy"] == []
    assert saved["run_snapshot"]["coverage"] == old["accepted_coverage"]
    assert len(saved["run_snapshot"]["coverage"]) == 1
    assert saved["execution_plan"] == work.plan.model_dump(mode="json")
    assert current(work, after_plan)["id"] == old["id"]
    plan_counts = counts(work)
    for table in (TestResourceReservation, ResourceOccupancy, SampleRunUsage, SampleUsageSentinel):
        assert plan_counts[table.__tablename__] == baseline[table.__tablename__]
    promised_value = command(work, "verification.schedule.promise")
    promise_receipt, _ = accepted(work.quality, promised_value)
    assert promise_receipt["subject_type"] == "verification_request"
    after_promise = listing(work)
    assert current(work, after_promise)["status"] == "scheduled"
    assert fixed_run(work, after_promise)["id"] == saved["id"]
    promise_counts = counts(work)
    for table in (TestResourceReservation, ResourceOccupancy, SampleRunUsage, SampleUsageSentinel):
        assert promise_counts[table.__tablename__] == baseline[table.__tablename__]
    advance_clock(work, monkeypatch)
    actual = command(work, "test.run.start")
    before = counts(work)
    start_receipt, prepared = accepted(work.quality, actual)
    assert start_receipt["subject_type"] == "test_run"
    after = counts(work)
    for model, increase in (
        (VerificationRunVersion, 1),
        (VerificationLaunchFact, 1),
        (FormalVerificationRequest, 1),
        (TestResourceReservation, 1),
        (ResourceOccupancy, 2),
        (SampleRunUsage, 1),
        (Receipt, 1),
        (Audit, 1),
        (Outbox, 1),
    ):
        assert after[model.__tablename__] == before[model.__tablename__] + increase
    after_start = listing(work)
    running = fixed_run(work, after_start)
    request = current(work, after_start)
    assert running["status"] == "running" and running["revision"] == 2
    assert running["result"] == "pending" and not running["zero_occupancy"]
    assert request["status"] == "executing" and request["coverage_gaps"]
    assert datetime.fromisoformat(
        request["timeline"]["actual_start"]["occurred_at"]
    ) == datetime.fromisoformat(actual["payload"]["at"]["occurred_at"])
    assert request["timeline"]["final_result"] is None and request["timeline"]["disposed"] is None
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        history = s.get(FormalVerificationRequest, UUID(old["id"]))
        assert history.request_snapshot == old["request_snapshot"]
        use = s.scalar(select(SampleRunUsage).where(SampleRunUsage.run_id == work.binding.run_id))
        assert use.sample_id == work.binding.pairs[0].sample.id and use.state == "reserved"
        assert EventTime.model_validate(
            use.source_basis["actual_start"]
        ) == EventTime.model_validate(actual["payload"]["at"])
    unconsumed_token = prepared["payload"]["confirmation_token"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        assert (
            s.scalar(
                select(Confirmation.consumed).where(
                    Confirmation.token_hash == digest(unconsumed_token)
                )
            )
            is True
        )


def test_inputs_are_readonly_even_when_sentinels_do_not_exist(launch_work):
    work = launch_work
    before = counts(work)
    value = command(work, "test.run.plan")
    assert value["source_read_set"]
    assert counts(work) == before
    reviewed = preview(work, value)
    assert reviewed["review"]["after"]["occupancy_effect"] == "none"
    assert counts(work) == before
    unconsumed(work, reviewed["command"])


@pytest.mark.parametrize(
    "operation", ["test.run.plan", "verification.schedule.promise", "test.run.start"]
)
def test_same_key_and_cross_key_same_intent_replay_do_not_duplicate_truth(
    launch_work, monkeypatch, operation
):
    work = launch_work
    if operation == "test.run.plan":
        value = command(work, operation)
    elif operation == "verification.schedule.promise":
        planned(work)
        value = command(work, operation)
    else:
        promised(work)
        advance_clock(work, monkeypatch)
        value = command(work, operation)
    receipt, prepared = accepted(work.quality, value)
    before = counts(work)
    again = post(work.quality, prepared)
    assert again.status_code == 200 and again.json()["id"] == receipt["id"]
    alias = deepcopy(prepared)
    alias.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    replay = post(work.quality, alias)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == receipt["id"]
    after = counts(work)
    assert after[RequestKey.__tablename__] == before[RequestKey.__tablename__] + 1
    for table in before.keys() - {RequestKey.__tablename__}:
        assert after[table] == before[table]


def test_complete_accepted_scope_and_fixed_resource_binding_cannot_be_shrunk_or_replaced(
    launch_work,
):
    work = launch_work
    value = command(work, "test.run.plan")
    wrong = deepcopy(value)
    wrong["payload"]["execution_plan"]["conditions"] = "Client changed trusted conditions"
    result = post(work.quality, wrong, True)
    assert (
        result.status_code == 409
        and result.json()["detail"]["reason"] == "TEST_PLAN_SCOPE_MISMATCH"
    )
    omitted = deepcopy(value)
    omitted["payload"]["coverage"] = []
    result = post(work.quality, omitted, True)
    assert result.status_code == 422 and result.json()["detail"]["reason"] == "INVALID_PAYLOAD"
    assert not listing(work)["runs"]


def test_plan_cas_concurrency_creates_one_identity_and_one_run_receipt(launch_work):
    work = launch_work
    one = command(work, "test.run.plan")
    two = deepcopy(one)
    two.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    two["payload"]["reason"] = "A distinct plan intent"
    prepared = [preview(work, v)["command"] for v in (one, two)]
    before = counts(work)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda v: post(work.quality, v), prepared))
    assert sorted(v.status_code for v in responses) == [200, 409]
    after = counts(work)
    for table in (VerificationRunIdentity, VerificationRunVersion, VerificationLaunchFact, Receipt):
        assert after[table.__tablename__] == before[table.__tablename__] + 1
    assert after[ResourceOccupancy.__tablename__] == before[ResourceOccupancy.__tablename__]


def test_source_withdrawal_blocks_old_confirmation_and_keeps_every_effect_unwritten(launch_work):
    work = launch_work
    prepared = preview(work, command(work, "test.run.plan"))["command"]
    before = counts(work)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        s.execute(
            update(Artifact)
            .where(Artifact.id == UUID(work.actual_source["artifact_id"]))
            .values(status="withdrawn")
        )
    result = post(work.quality, prepared)
    assert result.status_code == 409 and result.json()["detail"]["reason"] == "SOURCE_UNAVAILABLE"
    assert counts(work) == before
    unconsumed(work, prepared)


def test_historical_resource_decision_callback_is_not_replayed_by_confirmed_start(
    launch_work, monkeypatch
):
    work = launch_work
    promised(work)
    advance_clock(work, monkeypatch)
    calls = []
    original = work.test_issuer.verify_named_decision

    def observed(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    # Observe a real registered issuer's callback without supplying any proof.
    # Keep key/version/epoch/token identical to the originally signed fact.
    registered = replace(work.test_issuer, verify_named_decision=observed)
    registry = dict(work.setup.engine._pdos_test_resource_issuers)
    registry[registered.key] = registered
    with monkeypatch.context() as observer:
        observer.setattr(work.setup.engine, "_pdos_test_resource_issuers", registry)
        prepared = preview(work, command(work, "test.run.start"))["command"]
        before = counts(work)
        work.test_decisions_current = False
        result = post(work.quality, prepared)
        assert result.status_code == 200, result.text
        assert result.json()["subject_type"] == "test_run"
        assert calls == []
        after = counts(work)
        assert (
            after[TestResourceReservation.__tablename__]
            == before[TestResourceReservation.__tablename__] + 1
        )
        assert after[SampleRunUsage.__tablename__] == before[SampleRunUsage.__tablename__] + 1
        assert after[ResourceOccupancy.__tablename__] > before[ResourceOccupancy.__tablename__]
        assert current(work)["status"] == "executing"


def test_direct_resource_current_successor_blocks_old_start_confirmation_without_effects(
    launch_work, monkeypatch
):
    work = launch_work
    promised(work)
    advance_clock(work, monkeypatch)
    prepared = preview(work, command(work, "test.run.start"))["command"]
    successor = work.test_input.model_copy(
        update={
            "expected_previous_id": work.test_fact_id,
            "expected_previous_revision": 1,
            "reason": "Actual signed resource Current successor after Start preview",
        }
    )
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        receipt = import_test_resource_fact(
            s,
            work.quality.ctx,
            work.setup.product,
            work.test_issuer,
            successor,
            request_key=str(uuid4()),
            command_id=uuid4(),
        )
        assert UUID(receipt["subject_id"]) != work.test_fact_id
    before = counts(work)
    result = post(work.quality, prepared)
    assert result.status_code == 409
    assert result.json()["detail"]["reason"] == "RESOURCE_FACTS_CHANGED"
    assert counts(work) == before and current(work)["status"] == "scheduled"
    unconsumed(work, prepared)


def test_end_of_common_audit_outbox_failure_rolls_back_start_occupancy_usage_and_token(
    launch_work, monkeypatch
):
    import pdos_next.service as common

    work = launch_work
    promised(work)
    advance_clock(work, monkeypatch)
    prepared = preview(work, command(work, "test.run.start"))["command"]
    before = counts(work)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        epochs = {r.id: r.occupancy_epoch for r in s.scalars(select(OperationalAsset))}
    append = common.append_receipt

    def fail(*args, **kwargs):
        append(*args, **kwargs)
        raise RuntimeError("Synthetic failure after receipt audit outbox")

    monkeypatch.setattr(common, "append_receipt", fail)
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        post(work.quality, prepared)
    assert counts(work) == before
    unconsumed(work, prepared)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        assert {r.id: r.occupancy_epoch for r in s.scalars(select(OperationalAsset))} == epochs
    monkeypatch.setattr(common, "append_receipt", append)
    retry = post(work.quality, prepared)
    assert retry.status_code == 200, retry.text


def test_build_writer_or_agent_cannot_claim_quality_or_write_run_directly(launch_work):
    work = launch_work
    value = command(work, "test.run.plan")
    result = post(work.setup, value, True)
    assert (
        result.status_code == 403 and result.json()["detail"]["reason"] == "QUALIFICATION_REQUIRED"
    )
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as s:
        with pytest.raises(DomainError) as error:
            execute(
                s,
                Context(work.setup.tenant, work.setup.agent, work.setup.agent),
                Command.model_validate(value),
            )
        assert error.value.reason == "FORBIDDEN_SCOPE"
    with Session(work.setup.admin) as s:
        for table in (
            VerificationRunIdentity,
            VerificationRunVersion,
            VerificationRunCurrent,
            VerificationLaunchFact,
        ):
            assert (
                s.scalar(
                    text("SELECT has_table_privilege('pdos_agent', :table, 'INSERT')"),
                    {"table": table.__tablename__},
                )
                is False
            )


def test_immutable_run_identity_versions_and_cross_tenant_rls(launch_work):
    work = launch_work
    planned(work)
    row = fixed_run(work)
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.human,
            category_id=work.setup.category,
        ) as s:
            s.execute(
                update(VerificationRunVersion)
                .where(VerificationRunVersion.id == UUID(row["id"]))
                .values(reason="tampered")
            )
    with pytest.raises(DBAPIError, match="immutable"):
        with Session(work.setup.admin) as s, s.begin():
            s.execute(
                update(VerificationRunVersion)
                .where(VerificationRunVersion.id == UUID(row["id"]))
                .values(reason="tampered")
            )
    with pytest.raises(DBAPIError, match="immutable"):
        with Session(work.setup.admin) as s, s.begin():
            s.execute(
                update(VerificationRunIdentity)
                .where(VerificationRunIdentity.id == work.binding.run_id)
                .values(request_id=uuid4())
            )
    with Session(work.setup.admin) as s:
        other_tenant = s.get(Principal, work.setup.other_human).tenant_id
    with tenant_session(work.setup.engine, other_tenant) as s:
        assert s.scalar(select(func.count()).select_from(VerificationRunVersion)) == 0


def test_acceptance_continues_request_without_rewriting_existing_run(launch_work):
    work = launch_work
    planned(work)
    before = fixed_run(work)
    second = next(
        v
        for v in work.samples
        if v["id"] not in {c["sample_id"] for c in before["run_snapshot"]["coverage"]}
    )
    accepted(
        work.quality,
        handoff_command(
            work,
            operation="verification.handoff.accept",
            coverage=[{"sample_id": second["id"], "item_id": "dimension"}],
        ),
    )
    assert len(current(work)["accepted_coverage"]) == 2
    after = fixed_run(work)
    assert after["run_snapshot"] == before["run_snapshot"]
    assert after["execution_plan"] == before["execution_plan"]
