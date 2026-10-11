"""Real PG/API handoff transactions; root alone executes in the isolated target."""

# ruff: noqa: F811 - imported fixtures are intentional

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_build_execution import actual_command
from test_project_first_plan import accepted, post

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_handoff.models import (
    ActualMethodApplicability,
    ActualMethodBatch,
    ActualMethodCurrent,
    VerificationHandoffFact,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Receipt, RequestKey
from pdos_next.service import Context, digest, execute
from verification_handoff.fixtures import (
    actual_method,
    artifact,
    command,
    current,
    handoff,
    handoff_work,  # noqa: F401
    known_configuration,  # noqa: F401
    listing,
    operational_work,  # noqa: F401
    readiness,
    ready_work,  # noqa: F401
    selected,  # noqa: F401
)  # noqa: F401 - fixture dependency registration


def count(work):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        return {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (
                FormalVerificationRequest,
                ActualMethodBatch,
                ActualMethodApplicability,
                ActualMethodCurrent,
                VerificationHandoffFact,
                Receipt,
                RequestKey,
                Audit,
                Outbox,
            )
        }


def review(setup, command):
    result = post(setup, command, True)
    assert result.status_code == 200, result.text
    return result.json()


def methods(work, *, status="applicable"):
    return accepted(work.quality, actual_method(work, status=status))


def offered(work):
    receipt, prepared = accepted(work.engineer, handoff(work))
    return receipt, prepared, current(work)


def test_three_named_roles_actual_method_offer_partial_accept_and_return_are_one_request_truth(
    handoff_work,
):
    work = handoff_work
    before = current(work)
    assert before["documents_ready"] and before["status"] == "draft"
    scoped = work.quality.client.get(
        f"/v1/categories/{work.quality.category}/products/{work.quality.product}/verification-handoff",
        headers=work.quality.headers,
        params={"build_id": work.build_id},
    )
    assert scoped.status_code == 200, scoped.text
    scoped = scoped.json()
    assert scoped["current_by_request"][work.request_id]["request_version_id"] == before["id"]
    assert scoped["requests"] and all(
        value["build"]["id"] == work.build_id for value in scoped["requests"]
    )
    assert work.setup.human != work.engineer.human != work.quality.human
    method_receipt, _ = methods(work)
    assert method_receipt["subject_type"] == "verification_actual_method"
    assert current(work)["id"] == before["id"]  # Actual does not overwrite planned method/request.
    offer_receipt, _, offered_row = offered(work)
    assert offer_receipt["subject_type"] == "verification_request"
    assert offered_row["revision"] == before["revision"] + 1 and offered_row["status"] == "offered"
    coverage = offered_row["offered_coverage"]
    accepted_receipt, accepted_command = accepted(
        work.quality,
        handoff(
            work,
            operation="verification.handoff.accept",
            coverage=coverage[:1],
            returned=coverage[1:],
        ),
    )
    row = current(work)
    assert row["status"] == "accepted" and row["revision"] == offered_row["revision"] + 1
    assert row["accepted_coverage"] == coverage[:1]
    assert row["returns"][-1]["next_owner_id"] == str(work.engineer.human)
    assert row["returns"][-1]["coverage"] == coverage[1:]
    assert any(g["code"] == "PARTIAL_SAMPLE_COUNT" for g in row["coverage_gaps"])
    assert row["timeline"]["request_created"] == before["timeline"]["request_created"]
    assert row["timeline"]["accepted"]["received_at"]
    assert all(
        row["timeline"][key] is None
        for key in (
            "promised_start",
            "actual_start",
            "preliminary_result",
            "final_result",
            "disposed",
        )
    )
    history = listing(work)
    assert len(history["requests"]) == 4 and not history["runs"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        for model in (Audit, Outbox):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.receipt_id == UUID(accepted_receipt["id"]))
                )
                == 1
            )
        assert session.get(
            FormalVerificationRequest, UUID(accepted_receipt["subject_id"])
        ).input_snapshot["method_assessment_refs"]
    initial = count(work)
    alias = deepcopy(accepted_command)
    alias.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    replay = post(work.quality, alias)
    assert replay.status_code == 200 and replay.json()["id"] == accepted_receipt["id"]
    after = count(work)
    assert after["verification_handoff_facts"] == initial["verification_handoff_facts"]
    assert after[Receipt.__tablename__] == initial[Receipt.__tablename__]
    returned_receipt, _ = accepted(
        work.quality, handoff(work, operation="verification.handoff.return", coverage=coverage[1:])
    )
    assert returned_receipt["subject_type"] == "verification_request"
    assert current(work)["status"] == "accepted"


def test_planned_positive_never_substitutes_actual_method_unknown(handoff_work):
    work = handoff_work
    assert current(work)["documents_ready"]
    methods(work, status="unknown")
    _, _, row = offered(work)
    command = handoff(
        work, operation="verification.handoff.accept", coverage=row["offered_coverage"]
    )
    refused = post(work.quality, command, True)
    assert (
        refused.status_code == 409 and refused.json()["detail"]["reason"] == "ACTUAL_METHOD_UNKNOWN"
    )
    assert current(work)["status"] == "offered" and not current(work)["acceptances"]


def test_same_actual_intent_new_key_replays_batch_before_pair_cas(handoff_work):
    work = handoff_work
    receipt, prepared = methods(work)
    before = count(work)
    alias = deepcopy(prepared)
    alias.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    result = post(work.quality, alias)
    assert result.status_code == 200 and result.json()["id"] == receipt["id"]
    after = count(work)
    assert (
        after["verification_actual_method_batches"] == before["verification_actual_method_batches"]
    )
    assert (
        after["verification_actual_method_applicabilities"]
        == before["verification_actual_method_applicabilities"]
    )
    assert after[Receipt.__tablename__] == before[Receipt.__tablename__]


def test_hold_after_accept_review_invalidates_confirmation_and_preserves_scope(handoff_work):
    work = handoff_work
    methods(work)
    _, _, row = offered(work)
    data = handoff(work, operation="verification.handoff.accept", coverage=row["offered_coverage"])
    prepared = review(work.quality, data)["command"]
    readiness(work, work.samples[0], state="hold")
    response = post(work.quality, prepared)
    # The old command lacks the new hold's exact source read set, so that current
    # evidence boundary may reject before availability is evaluated.
    assert response.status_code == 409 and response.json()["detail"]["reason"] in {
        "MISSING_REQUIRED_EVIDENCE",
        "SAMPLE_UNAVAILABLE",
    }
    refreshed = deepcopy(prepared)
    refreshed["source_read_set"] = handoff(
        work, operation="verification.handoff.accept", coverage=row["offered_coverage"]
    )["source_read_set"]
    result = post(work.quality, refreshed)
    assert result.status_code == 409 and result.json()["detail"]["reason"] == "SAMPLE_UNAVAILABLE"
    assert current(work)["status"] == "offered"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        confirmation = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(prepared["payload"]["confirmation_token"])
            )
        )
        assert confirmation is not None and not confirmation.consumed


def test_bad_actual_configuration_and_event_source_locator_are_rejected(handoff_work):
    work = handoff_work
    data = actual_method(work)
    data["payload"]["assessments"][0]["sample"]["actual_configuration"]["id"] = str(uuid4())
    result = post(work.quality, data, True)
    assert result.status_code == 409 and result.json()["detail"]["reason"] == "SOURCE_CHANGED"
    offer = handoff(work)
    offer["payload"]["at"]["source"]["position"] = "line:999;quote_sha256:invented"
    result = post(work.engineer, offer, True)
    assert (
        result.status_code == 409
        and result.json()["detail"]["reason"] == "MISSING_REQUIRED_EVIDENCE"
    )


def test_method_pair_concurrent_cas_has_one_batch_and_one_common_receipt(handoff_work):
    work = handoff_work
    one = actual_method(work)
    two = deepcopy(one)
    two.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    two["payload"]["reason"] = "Different independent actual review intent"
    prepared = [review(work.quality, value)["command"] for value in (one, two)]
    before = count(work)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda value: post(work.quality, value), prepared))
    assert sorted(response.status_code for response in replies) == [200, 409]
    rejected = next(response for response in replies if response.status_code == 409)
    assert rejected.json()["detail"]["reason"] in {"VERSION_CONFLICT", "CONFIRMATION_SCOPE_CHANGED"}
    after = count(work)
    assert (
        after["verification_actual_method_batches"]
        == before["verification_actual_method_batches"] + 1
    )
    assert (
        after["verification_actual_method_applicabilities"]
        == before["verification_actual_method_applicabilities"] + 2
    )
    assert after[Receipt.__tablename__] == before[Receipt.__tablename__] + 1


def test_terminal_common_receipt_failure_rolls_back_actual_facts_pointer_and_confirmation(
    handoff_work, monkeypatch
):
    import pdos_next.service as common

    work = handoff_work
    prepared = review(work.quality, actual_method(work))["command"]
    before = count(work)
    original = common.append_receipt

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic terminal receipt failure")

    monkeypatch.setattr(common, "append_receipt", fail)
    with pytest.raises(RuntimeError, match="Synthetic terminal receipt failure"):
        post(work.quality, prepared)
    assert count(work) == before
    monkeypatch.setattr(common, "append_receipt", original)
    result = post(work.quality, prepared)
    assert result.status_code == 200, result.text


def test_source_withdrawal_keeps_saved_receipt_replay_and_blocks_new_material(handoff_work):
    work = handoff_work
    receipt, prepared = methods(work)
    fresh_command = actual_method(work)
    before = count(work)
    with Session(work.setup.admin) as session, session.begin():
        session.execute(
            update(Artifact)
            .where(Artifact.id == UUID(work.source["artifact_id"]))
            .values(status="withdrawn")
        )
    result = post(work.quality, prepared)
    assert result.status_code == 200 and result.json()["id"] == receipt["id"], result.text
    fresh = post(work.quality, fresh_command, True)
    assert fresh.status_code == 409 and fresh.json()["detail"]["reason"] == "SOURCE_UNAVAILABLE", (
        fresh.text
    )
    assert count(work) == before
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        assert session.get(ActualMethodBatch, UUID(receipt["subject_id"])) is not None


def test_quality_and_engineering_roles_not_interchangeable_and_cross_tenant_hidden(handoff_work):
    work = handoff_work
    result = post(work.engineer, actual_method(work), True)
    assert (
        result.status_code == 403 and result.json()["detail"]["reason"] == "QUALIFICATION_REQUIRED"
    )
    response = work.setup.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-handoff",
        headers={"Authorization": f"Bearer {work.setup.tokens[work.setup.other_human]}"},
    )
    assert response.status_code == 403
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        with pytest.raises(DomainError) as error:
            execute(
                session,
                Context(work.setup.tenant, work.setup.agent, work.setup.agent),
                Command.model_validate(actual_method(work)),
            )
        assert error.value.reason == "FORBIDDEN_SCOPE"


def test_actual_fact_immutable_rls_agent_zero_write_and_current_pointer_cannot_backtrack(
    handoff_work,
):
    work = handoff_work
    methods(work)
    values = listing(work)["actual_methods"]
    row = values[0]
    with pytest.raises(DBAPIError, match="permission denied"):
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            category_id=work.setup.category,
        ) as session:
            session.execute(
                update(ActualMethodApplicability)
                .where(ActualMethodApplicability.id == UUID(row["id"]))
                .values(status="unknown")
            )
    with pytest.raises(DBAPIError, match="immutable"):
        with Session(work.setup.admin) as session, session.begin():
            session.execute(
                update(ActualMethodApplicability)
                .where(ActualMethodApplicability.id == UUID(row["id"]))
                .values(status="unknown")
            )
    with tenant_session(work.setup.engine, uuid4()) as session:
        assert session.scalar(select(func.count()).select_from(ActualMethodApplicability)) == 0
    with Session(work.setup.admin) as session:
        for name in (
            ActualMethodBatch.__tablename__,
            ActualMethodApplicability.__tablename__,
            ActualMethodCurrent.__tablename__,
            VerificationHandoffFact.__tablename__,
        ):
            assert not session.scalar(
                text("SELECT has_table_privilege('pdos_agent', :table, 'INSERT,UPDATE,DELETE')"),
                {"table": name},
            )


def test_stale_actual_qualification_keeps_real_pair_pointer_and_can_be_renewed(handoff_work):
    work = handoff_work
    old_receipt, old_command = methods(work)
    old = work.extra_authority[("quality", "qualification")]
    operations = [
        "verification.request.create",
        "verification.method.prepare",
        "verification.actual_method.prepare",
        "verification.handoff.accept",
        "verification.handoff.return",
    ]
    common = {
        "subject_id": str(work.quality.human),
        "operations": operations,
        "external_id": f"synthetic-handoff-quality-qualification-{work.quality.human}",
    }
    revoked = import_authority(
        work,
        "quality",
        "qualification",
        **common,
        state="revoked",
        previous_id=old["subject_id"],
        expected_previous_revision=old["subject_revision"],
    )
    data = listing(work)
    assert len(data["method_current_by_pair"]) == 2
    assert all(pointer["revision"] == 1 for pointer in data["method_current_by_pair"])
    assert all(not row["current"] for row in data["actual_methods"])
    import_authority(
        work,
        "quality",
        "qualification",
        **common,
        state="active",
        previous_id=revoked["subject_id"],
        expected_previous_revision=revoked["subject_revision"],
    )
    # Refresh the separate planned proof after its original reviewer epoch changed.
    plan = command(
        work,
        "verification.method.prepare",
        {
            "assessments": [
                {
                    "item_id": "dimension",
                    "status": "applicable",
                    "conditions": [],
                    "reason": "Renew planned proof under restored current authority",
                    "sources": [work.actual_source],
                }
            ]
        },
    )
    accepted(work.quality, plan)
    prepared = actual_method(work)
    assert {a["expected_assessment_revision"] for a in prepared["payload"]["assessments"]} == {1}
    accepted(work.quality, prepared)
    data = listing(work)
    assert {pointer["revision"] for pointer in data["method_current_by_pair"]} == {2}
    assert sum(row["current"] for row in data["actual_methods"]) == 2
    replay = post(work.quality, old_command)
    assert replay.status_code == 200 and replay.json()["id"] == old_receipt["id"], replay.text
    before = count(work)
    fresh = deepcopy(old_command)
    fresh["command_id"], fresh["idempotency_key"] = str(uuid4()), str(uuid4())
    fresh["payload"].pop("confirmation_token", None)
    fresh["payload"]["reason"] += "; new attempt against the old method version"
    denied = post(work.quality, fresh, True)
    assert denied.status_code == 409 and denied.json()["detail"]["reason"] == "SOURCE_STALE", (
        denied.text
    )
    assert count(work) == before


def test_withdrawn_new_same_plan_actual_observation_blocks_acceptance(handoff_work):
    from pdos_next.models import now

    work = handoff_work
    methods(work)
    _, _, offered_row = offered(work)
    independent = artifact(work.setup, "Synthetic independent same-plan actual observation")
    planned = {**work.config, "build": {"subject_id": work.build_id}}
    new_actual = actual_command(
        work.setup, planned, observed_at=now().isoformat(), sources=[independent]
    )
    new_actual["source_read_set"] = _merge_reads(new_actual["source_read_set"], [independent])
    accepted(work.setup, new_actual)
    data = handoff(
        work, operation="verification.handoff.accept", coverage=offered_row["offered_coverage"]
    )
    prepared = review(work.quality, data)["command"]
    before = count(work)
    with Session(work.setup.admin) as session, session.begin():
        session.execute(
            update(Artifact)
            .where(Artifact.id == UUID(independent["artifact_id"]))
            .values(status="withdrawn")
        )
    result = post(work.quality, prepared)
    # The complete command read set contains the new observation's source, so
    # common current-source validation rejects before the Build proof is read.
    assert result.status_code == 409 and result.json()["detail"]["reason"] == "SOURCE_UNAVAILABLE"
    assert count(work) == before
    assert current(work)["status"] == "offered"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        confirmation = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(prepared["payload"]["confirmation_token"])
            )
        )
        assert confirmation is not None and not confirmation.consumed
