"""Shared real physical chain; root alone runs the verified PostgreSQL contracts."""

# ruff: noqa: F811 - pytest fixture imports are intentional

import json
from uuid import UUID

import pytest
from build_start.test_transactions import import_authority
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_build_execution import actual_command
from test_project_first_plan import accepted, cmd, post
from verification_handoff.fixtures import (  # noqa: F401 - fixture dependency exports
    artifact,
    handoff_work,
    known_configuration,
    operational_work,
    readiness,
    ready_work,
)

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.build_execution.models import SampleUnit
from pdos_next.domain.build_start.service import execution_projection, list_execution
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.sample_handoff.models import SampleReadinessCurrent, SampleReadinessFact
from pdos_next.domain.sample_handoff.service import inspect_sample
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Receipt, now
from pdos_next.service import digest, execute


def listing(work, *, caller=None, purpose=None):
    setup = caller or work.setup
    response = setup.client.get(
        f"/v1/products/{setup.product}/sample-handoff",
        headers=setup.headers,
        params={"purpose": purpose or work.scope.purpose, "build_id": work.build_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def state_command(work, sample, *, state="hold", previous=None, occurred_at=None, **changes):
    at = occurred_at or now()
    reference = artifact(
        work.setup,
        json.dumps(
            {
                "sample_id": sample["id"],
                "lot_id": sample["lot_id"],
                "actual_configuration_id": sample["actual_configuration_id"],
                "build_id": work.build_id,
                "state": state,
                "purpose": work.scope.purpose,
                "occurred_at": at.isoformat(),
            }
        ),
    )
    data = listing(work)
    previous = previous or data["current_by_sample"][sample["id"]]
    command = cmd(
        work.setup,
        "build.sample.readiness.record",
        {
            "sample_id": sample["id"],
            "expected_sample_revision": sample["revision"],
            "previous_readiness_id": previous["readiness_id"],
            "expected_previous_revision": previous["revision"],
            "state": state,
            "purpose": work.scope.purpose,
            "occurred_at": at.isoformat(),
            "occurred_timezone": "UTC",
            "event_source": reference,
            "sources": [reference],
            "reason": "Explicit synthetic readiness transition",
            **changes,
        },
    )
    command["source_read_set"] = _merge_reads(
        data["availability_by_sample"][sample["id"]]["required_source_read_set"],
        data["capabilities_by_sample"][sample["id"]]["required_source_read_set"],
        [reference],
    )
    return command


def count(work, model):
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        return session.scalar(select(func.count()).select_from(model))


def test_targeted_execution_projection_preserves_qualification_stop_and_source_guards(handoff_work):
    work = handoff_work
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        direct = execution_projection(
            session, work.setup.ctx, work.setup.product, UUID(work.build_id)
        )
        listed = list_execution(session, work.setup.ctx, work.setup.product)[
            "capabilities_by_build"
        ][work.build_id]
        assert direct is not None
        assert direct["execution_status"] == "executing"
        assert direct["execution_qualification"] == "limited_current"
        assert direct["stop_required"] is False
        # The operational source union includes observations added after Start.
        # Equality must also preserve the actual source binding and rule checks.
        for key in (
            "execution_status",
            "execution_qualification",
            "stop_required",
            "required_source_read_set",
            "current_result",
            "blockers",
        ):
            assert direct[key] == listed[key], key
        assert direct["required_source_read_set"]


def test_ready_is_exact_purpose_current_and_three_readers_have_same_objective_fingerprint(
    handoff_work,
):
    work = handoff_work
    manufacture, engineering, quality = (
        listing(work, caller=setup) for setup in (work.setup, work.engineer, work.quality)
    )
    for sample in work.samples:
        identity = sample["id"]
        observations = [
            data["availability_by_sample"][identity] for data in (manufacture, engineering, quality)
        ]
        assert {value["availability"] for value in observations} == {"ready"}
        assert len({value["facts_revision"] for value in observations}) == 1
        value = observations[0]
        assert value["clocks"]["occurred_at"] <= value["clocks"]["received_at"]
        assert value["actual_configuration"]["id"] == sample["actual_configuration_id"]
        assert value["lot"]["id"] == sample["lot_id"]
        assert value["build"]["start_id"] == work.start_receipt["subject_id"]
        assert value["current_readiness"]["source_ref"]["kind"] == "domain"
        assert value["current_readiness"]["source_ref"]["position"] == "sample-readiness"
        assert (
            next(row for row in quality["samples"] if row["id"] == identity)["availability"]
            == "unknown"
        )
        other = listing(work, caller=work.quality, purpose="Different exact purpose")
        assert other["availability_by_sample"][identity]["availability"] == "unknown"
        assert (
            "SAMPLE_PURPOSE_NOT_READY" in other["availability_by_sample"][identity]["reason_codes"]
        )
        with tenant_session(work.setup.engine, work.setup.tenant) as session:
            row = session.get(SampleUnit, UUID(identity))
            assert row.availability == "unknown"
            readonly = inspect_sample(
                session,
                work.quality.ctx,
                work.setup.product,
                {"id": identity, "revision": sample["revision"]},
                work.scope.purpose,
            )
            assert readonly["availability"] == "ready"
    assert quality["capabilities"]["quality_accept"] is False
    assert all(
        not cap["ready"] and not cap["hold"] for cap in quality["capabilities_by_sample"].values()
    )


def test_hold_blocks_all_purposes_and_receipt_replay_never_rewinds_current(handoff_work):
    work, sample = handoff_work, handoff_work.samples[0]
    old_pointer = listing(work)["current_by_sample"][sample["id"]]
    hold_command = state_command(work, sample)
    held, prepared_hold = accepted(work.setup, hold_command)
    assert held["subject_type"] == "sample_readiness_fact"
    for purpose in (work.scope.purpose, "Unrelated purpose"):
        data = listing(work, caller=work.quality, purpose=purpose)
        assert data["availability_by_sample"][sample["id"]]["availability"] == "hold"
    resumed, _ = readiness(work, sample, state="ready")
    current = listing(work)["current_by_sample"][sample["id"]]
    assert current == {"readiness_id": resumed["subject_id"], "revision": 3}
    replay = post(work.setup, prepared_hold)
    assert replay.status_code == 200 and replay.json()["id"] == held["id"]
    assert listing(work)["current_by_sample"][sample["id"]] == current
    stale = state_command(work, sample, previous=old_pointer, reason="New stale-pointer intent")
    rejected = post(work.setup, stale, True)
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "SAMPLE_READINESS_VERSION_CONFLICT"
    history = [row for row in listing(work)["readiness_facts"] if row["sample_id"] == sample["id"]]
    assert [(row["revision"], row["state"]) for row in history] == [
        (1, "ready"),
        (2, "hold"),
        (3, "ready"),
    ]


def test_new_observation_source_withdrawal_blocks_current_ready_and_new_ready_write(handoff_work):
    work, sample = handoff_work, handoff_work.samples[0]
    new_ref = artifact(
        work.setup, "Synthetic additional same-plan actual configuration observation"
    )
    planned = {**work.config, "build": {"subject_id": work.build_id}}
    added = actual_command(work.setup, planned, observed_at=now().isoformat())
    added["payload"]["sources"].append(new_ref)
    added["source_read_set"] = _merge_reads(added["source_read_set"], [new_ref])
    accepted(work.setup, added)
    assert (
        listing(work, caller=work.quality)["availability_by_sample"][sample["id"]]["availability"]
        == "ready"
    )
    with Session(work.setup.admin) as session, session.begin():
        session.execute(
            update(Artifact)
            .where(Artifact.id == UUID(new_ref["artifact_id"]))
            .values(status="withdrawn")
        )
    data = listing(work, caller=work.quality)
    assert data["availability_by_sample"][sample["id"]]["availability"] == "unknown"
    assert data["availability_by_sample"][sample["id"]]["reason_codes"]
    assert data["current_by_sample"][sample["id"]]["revision"] == 1
    # A bad-news hold remains recordable with current sample sources/qualification.
    blocked = post(work.setup, state_command(work, sample, state="ready"), True)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "BUILD_EXECUTION_NOT_CURRENT"
    held, _ = accepted(work.setup, state_command(work, sample, state="hold"))
    assert held["subject_revision"] == 2
    assert (
        listing(work, caller=work.quality)["availability_by_sample"][sample["id"]]["availability"]
        == "hold"
    )


def test_signer_qualification_revoke_restore_epoch_does_not_revive_readiness(handoff_work):
    work, sample = handoff_work, handoff_work.samples[0]
    old = work.extra_authority[("manufacturing", "qualification")]
    changes = {
        "operations": ["build.sample.readiness.record"],
        "external_id": f"synthetic-handoff-manufacturing-qualification-{work.setup.human}",
        "previous_id": old["subject_id"],
        "expected_previous_revision": old["subject_revision"],
    }
    revoked = import_authority(work, "manufacturing", "qualification", state="revoked", **changes)
    assert (
        listing(work, caller=work.quality)["availability_by_sample"][sample["id"]]["availability"]
        == "unknown"
    )
    denied = post(work.setup, state_command(work, sample), True)
    assert denied.status_code == 403 and denied.json()["code"] == "MANUFACTURING_AUTHORITY_REQUIRED"
    changes.update(
        previous_id=revoked["subject_id"], expected_previous_revision=revoked["subject_revision"]
    )
    import_authority(work, "manufacturing", "qualification", state="active", **changes)
    data = listing(work, caller=work.quality)
    assert data["availability_by_sample"][sample["id"]]["availability"] == "unknown"
    assert (
        "SAMPLE_AUTHORITY_CHANGED" in data["availability_by_sample"][sample["id"]]["reason_codes"]
    )
    assert data["current_by_sample"][sample["id"]]["revision"] == 1


def test_physical_fact_and_current_pointer_immutable_history_cannot_be_overwritten(handoff_work):
    work, sample = handoff_work, handoff_work.samples[0]
    original = listing(work)["current_by_sample"][sample["id"]]
    held, _ = readiness(work, sample, state="hold")
    with pytest.raises(DBAPIError):
        with Session(work.setup.admin) as session, session.begin():
            session.execute(
                update(SampleReadinessFact)
                .where(SampleReadinessFact.id == UUID(original["readiness_id"]))
                .values(status="hold")
            )
    with pytest.raises(DBAPIError):
        with Session(work.setup.admin) as session, session.begin():
            session.execute(
                update(SampleReadinessCurrent)
                .where(SampleReadinessCurrent.sample_id == UUID(sample["id"]))
                .values(readiness_id=UUID(original["readiness_id"]), readiness_revision=1)
            )
    assert listing(work)["current_by_sample"][sample["id"]] == {
        "readiness_id": held["subject_id"],
        "revision": 2,
    }


def test_shared_transaction_failure_rolls_back_fact_pointer_receipt_and_confirmation(
    handoff_work, monkeypatch
):
    from pdos_next import service as common

    work, sample = handoff_work, handoff_work.samples[0]
    before = listing(work)["current_by_sample"][sample["id"]]
    command = state_command(work, sample)
    preview = post(work.setup, command, True)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    before_counts = {
        model: count(work, model) for model in (SampleReadinessFact, Receipt, Audit, Outbox)
    }
    original = common.append_receipt

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic failure at common receipt boundary")

    monkeypatch.setattr(common, "append_receipt", fail)
    with pytest.raises(RuntimeError):
        with tenant_session(work.setup.engine, work.setup.tenant) as session:
            execute(session, work.setup.ctx, Command.model_validate(prepared))
    monkeypatch.setattr(common, "append_receipt", original)
    assert {model: count(work, model) for model in before_counts} == before_counts
    assert listing(work)["current_by_sample"][sample["id"]] == before
    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        confirmation = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(prepared["payload"]["confirmation_token"])
            )
        )
        assert confirmation is not None and confirmation.consumed is False
    retried = post(work.setup, prepared)
    assert retried.status_code == 200, retried.text
    assert retried.json()["subject_revision"] == 2
