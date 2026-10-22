"""Shared real physical chain; root alone runs the verified PostgreSQL contracts."""

# ruff: noqa: F811 - pytest fixture imports are intentional

import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from sqlalchemy import event, func, select, text, update
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
from pdos_next.domain.build_start import service as starts
from pdos_next.domain.build_start.service import execution_projection, list_execution
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.sample_handoff.models import SampleReadinessCurrent, SampleReadinessFact
from pdos_next.domain.sample_handoff.service import inspect_sample
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Product, Receipt, now
from pdos_next.request_proof import request_proof, scope_is_held
from pdos_next.service import command_scope, digest, execute


def listing(work, *, caller=None, purpose=None):
    setup = caller or work.setup
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/sample-handoff",
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
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        return session.scalar(select(func.count()).select_from(model))


def test_targeted_execution_projection_preserves_qualification_stop_and_source_guards(handoff_work):
    work = handoff_work
    effect_models = (Receipt, Audit, Outbox, Confirmation)
    baseline = {model: count(work, model) for model in effect_models}
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        gate_command = Command(
            command_id=uuid4(),
            idempotency_key=str(uuid4()),
            operation="build.readiness.compute",
            category_id=work.setup.category,
            product_id=work.setup.product,
            expected_revision=1,
            payload={},
        )
        scope = command_scope(session, work.setup.ctx, gate_command, lock=True)
        proof = request_proof(session)
        assert scope.id == work.setup.product and scope_is_held(session, scope.id)
        assert scope.id in proof.scope_locks and proof.mutation_epoch == 0
        assert session.info["read_snapshot"] is False
        assert not (session.new or session.dirty or session.deleted)
        packed_queries, mutations = [], []

        def observe(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().startswith(("INSERT", "UPDATE", "DELETE")):
                mutations.append(statement.split()[0])
            if not (
                statement.lstrip().startswith("SELECT") and "owner_assessment_current" in statement
            ):
                return
            assert not executemany
            assert session.is_active and session.get_transaction() is proof.transaction
            assert session.get_nested_transaction() is not None
            assert scope_is_held(session, scope.id) and proof.mutation_epoch == 0
            assert not (session.new or session.dirty or session.deleted)
            assert all(
                name in statement
                for name in (
                    "owner_assessment_fact",
                    "owner_engineering_current",
                    "owner_engineering_fact",
                    "owner_manufacturing_current",
                    "owner_manufacturing_fact",
                    "audience_dependencies",
                )
            )
            packed_queries.append((connection, statement))

        event.listen(work.setup.engine, "before_cursor_execute", observe)
        try:
            direct = execution_projection(
                session, work.setup.ctx, work.setup.product, UUID(work.build_id)
            )
            repeated = execution_projection(
                session, work.setup.ctx, work.setup.product, UUID(work.build_id)
            )
        finally:
            event.remove(work.setup.engine, "before_cursor_execute", observe)
        assert len(packed_queries) == 1
        assert packed_queries[0][0] is session.get_transaction()._connections[session.get_bind()][0]
        assert not mutations
        assert request_proof(session) is proof and proof.mutation_epoch == 0
        assert scope.id in proof.scope_locks and session.get_nested_transaction() is None
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
            assert repeated[key] == direct[key], key
        assert direct["required_source_read_set"]
        assert not (session.new or session.dirty or session.deleted)
    assert {model: count(work, model) for model in effect_models} == baseline


def test_watched_owner_projection_reloads_legal_raw_current_successor_without_python_epoch(
    handoff_work, monkeypatch
):
    """Ordinary app-role SQL advances exact Current; no fake locks or trigger bypass."""
    work = handoff_work
    effects = (starts.BuildExecutionAssessment, Receipt, Audit, Outbox, Confirmation)
    baseline = {model: count(work, model) for model in effects}
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        command = Command(
            command_id=uuid4(),
            idempotency_key=str(uuid4()),
            operation="build.readiness.compute",
            category_id=work.setup.category,
            product_id=work.setup.product,
            expected_revision=1,
            payload={},
        )
        scope = command_scope(session, work.setup.ctx, command, lock=True)
        proof = request_proof(session)
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        assert scope.id == work.setup.product and scope_is_held(session, scope.id)
        assert scope.id in proof.scope_locks
        assert session.info["read_snapshot"] is False
        experiment = session.begin_nested()
        try:
            pointer = session.scalar(
                select(starts.BuildAssessmentCurrent).where(
                    starts.BuildAssessmentCurrent.tenant_id == work.setup.tenant,
                    starts.BuildAssessmentCurrent.product_id == work.setup.product,
                    starts.BuildAssessmentCurrent.build_id == UUID(work.build_id),
                )
            )
            original_assessment = session.scalar(
                select(starts.BuildExecutionAssessment).where(
                    starts.BuildExecutionAssessment.id == pointer.assessment_id
                )
            )
            assert original_assessment is not None
            old_id, old_revision = original_assessment.id, original_assessment.revision
            # Genuine mapper fields plus the real domain material/hash. The
            # app INSERT obeys fixed scope, source/audience and lineage triggers.
            values = {
                attribute.key: deepcopy(getattr(original_assessment, attribute.key))
                for attribute in starts.BuildExecutionAssessment.__mapper__.column_attrs
            }
            values.update(
                id=uuid4(),
                created_at=now(),
                revision=old_revision + 1,
                previous_assessment_id=old_id,
                previous_revision=old_revision,
            )
            successor = starts.BuildExecutionAssessment(**values)
            successor.snapshot_sha256 = digest(starts._material(successor))
            successor.intent_digest = digest(
                {"test": "watched-current", "previous": str(old_id), "id": str(successor.id)}
            )
            session.add(successor)
            session.flush()
            epoch = proof.mutation_epoch
            assert epoch > 0 and not (session.new or session.dirty or session.deleted)
            assert scope.id in proof.scope_locks and session.get_transaction() is proof.transaction
            packed_connections, selected = [], []
            actual_owner = starts._projection_writer

            def observed_owner(*args, **kwargs):
                result = actual_owner(*args, **kwargs)
                if result is not None:
                    selected.append((result[0].id, result[0].revision))
                return result

            def observe(connection, _cursor, statement, _params, _context, _many):
                if (
                    statement.lstrip().startswith("SELECT")
                    and "owner_assessment_current" in statement
                ):
                    assert scope_is_held(session, scope.id)
                    assert session.get_transaction() is proof.transaction
                    assert session.get_nested_transaction() is not None
                    assert proof.mutation_epoch == epoch
                    packed_connections.append(connection)

            monkeypatch.setattr(starts, "_projection_writer", observed_owner)
            event.listen(work.setup.engine, "before_cursor_execute", observe)
            try:
                before = execution_projection(
                    session, work.setup.ctx, work.setup.product, UUID(work.build_id)
                )
                repeated = execution_projection(
                    session, work.setup.ctx, work.setup.product, UUID(work.build_id)
                )
                assert before is not None and repeated == before
                assert before["execution_qualification"] == "limited_current"
                assert before["stop_required"] is False and before["required_source_read_set"]
                assert len(packed_connections) == 1
                db_before = session.scalar(
                    select(Product.lifecycle_epoch).where(
                        Product.tenant_id == work.setup.tenant,
                        Product.category_id == work.setup.category,
                        Product.id == work.setup.product,
                    )
                )
                advanced = session.execute(
                    text(
                        "UPDATE public.build_current_execution_assessments "
                        "SET assessment_id=:next_id, assessment_revision=:next_revision "
                        "WHERE tenant_id=:tenant AND category_id=:category "
                        "AND product_id=:product AND project_id=:project AND build_id=:build "
                        "AND id=:pointer AND assessment_id=:previous "
                        "AND assessment_revision=:previous_revision "
                        "RETURNING assessment_id, assessment_revision"
                    ),
                    {
                        "next_id": successor.id,
                        "next_revision": successor.revision,
                        "tenant": work.setup.tenant,
                        "category": work.setup.category,
                        "product": work.setup.product,
                        "project": pointer.project_id,
                        "build": UUID(work.build_id),
                        "pointer": pointer.id,
                        "previous": old_id,
                        "previous_revision": old_revision,
                    },
                ).one()
                assert tuple(advanced) == (successor.id, successor.revision)
                assert proof.mutation_epoch == epoch, (
                    "Raw text mutation must stay untracked in Python"
                )
                db_after = session.scalar(
                    select(Product.lifecycle_epoch).where(
                        Product.tenant_id == work.setup.tenant,
                        Product.category_id == work.setup.category,
                        Product.id == work.setup.product,
                    )
                )
                assert db_after > db_before
                after = execution_projection(
                    session, work.setup.ctx, work.setup.product, UUID(work.build_id)
                )
                again = execution_projection(
                    session, work.setup.ctx, work.setup.product, UUID(work.build_id)
                )
                assert after is not None and again == after
                assert after["execution_status"] == "executing"
                assert after["execution_qualification"] == "needs_recheck"
                assert after["stop_required"] is True
                assert selected == [
                    (old_id, old_revision),
                    (old_id, old_revision),
                    (successor.id, successor.revision),
                    (successor.id, successor.revision),
                ]
                assert len(packed_connections) == 2
                assert packed_connections[0] is packed_connections[1]
                assert request_proof(session) is proof and proof.mutation_epoch == epoch
                assert not (session.new or session.dirty or session.deleted)
            finally:
                event.remove(work.setup.engine, "before_cursor_execute", observe)
                monkeypatch.setattr(starts, "_projection_writer", actual_owner)
        finally:
            experiment.rollback()
        # Real rollback restores both the inserted successor and the pointer;
        # it legitimately invalidates the optimization's old lock/cache proof.
        assert (
            session.scalar(
                select(starts.BuildAssessmentCurrent.assessment_id).where(
                    starts.BuildAssessmentCurrent.id == pointer.id
                )
            )
            == old_id
        )
    assert {model: count(work, model) for model in effects} == baseline


def test_watched_owner_projection_rejects_changed_actual_actor_scope_and_regates_after_rollback(
    handoff_work,
):
    """A valid UUID DB scope change cannot inherit old info/marker/raw authority."""
    work = handoff_work
    effects = (Receipt, Audit, Outbox, Confirmation)
    baseline = {model: count(work, model) for model in effects}
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        command = Command(
            command_id=uuid4(),
            idempotency_key=str(uuid4()),
            operation="build.readiness.compute",
            category_id=work.setup.category,
            product_id=work.setup.product,
            expected_revision=1,
            payload={},
        )
        scope = command_scope(session, work.setup.ctx, command, lock=True)
        proof = request_proof(session)
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        assert scope.id == work.setup.product and scope.id in proof.scope_locks
        first = execution_projection(session, work.setup.ctx, scope.id, UUID(work.build_id))
        assert first is not None and first["execution_qualification"] == "limited_current"
        build = starts._build(session, work.setup.ctx, scope.id, UUID(work.build_id))
        saved_info, epoch = session.info["scope"], proof.mutation_epoch
        changed_actor = work.engineer.human
        if changed_actor == work.setup.ctx.actor_id:
            changed_actor = work.quality.human
        assert changed_actor != work.setup.ctx.actor_id
        changed_scope = session.begin_nested()
        try:
            session.execute(
                text("SELECT set_config('pdos.actor_id', :actor, true)"),
                {"actor": str(changed_actor)},
            )
            assert (
                session.scalar(text("SELECT current_setting('pdos.actor_id')::uuid"))
                == changed_actor
            )
            assert (
                session.scalar(text("SELECT current_setting('pdos.requester_id')::uuid"))
                == work.setup.ctx.requester_id
            )
            assert session.info["scope"] == saved_info and proof.mutation_epoch == epoch
            assert scope_is_held(session, scope.id)
            # GUCs are returned even when Product RLS hides the old caller's
            # clock. A real different actor must not fall back to old info or
            # an old raw owner set as an affirmative execution result.
            with pytest.raises(DomainError) as error:
                starts._projection_writer(session, work.setup.ctx, scope.id, build)
            assert error.value.reason == "FORBIDDEN_SCOPE" and error.value.status == 403
            assert session.is_active and proof.mutation_epoch == epoch
        finally:
            changed_scope.rollback()
        assert (
            session.scalar(text("SELECT current_setting('pdos.actor_id')::uuid"))
            == work.setup.ctx.actor_id
        )
        assert session.info["scope"] == saved_info
        assert proof.mutation_epoch > epoch and scope.id not in proof.scope_locks
        assert not scope_is_held(session, scope.id)
        # Reacquire the genuine Product FOR UPDATE gate after rollback; never
        # restore a marker, transaction proof or cached raw row by hand.
        restored_scope = command_scope(session, work.setup.ctx, command, lock=True)
        assert restored_scope.id == scope.id and scope_is_held(session, scope.id)
        restored = execution_projection(session, work.setup.ctx, scope.id, UUID(work.build_id))
        assert restored == first
        assert not (session.new or session.dirty or session.deleted)
    assert {model: count(work, model) for model in effects} == baseline


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
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            category_id=work.setup.category,
        ) as session:
            row = session.get(SampleUnit, UUID(identity))
            assert row.availability == "unknown"
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.human,
            category_id=work.setup.category,
            read_snapshot=True,
        ) as session:
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
    assert rejected.json()["detail"]["reason"] == "SAMPLE_READINESS_VERSION_CONFLICT"
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
    assert blocked.json()["detail"]["reason"] == "BUILD_EXECUTION_NOT_CURRENT"
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
    assert (
        denied.status_code == 403
        and denied.json()["detail"]["reason"] == "MANUFACTURING_AUTHORITY_REQUIRED"
    )
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
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            category_id=work.setup.category,
        ) as session:
            execute(session, work.setup.ctx, Command.model_validate(prepared))
    monkeypatch.setattr(common, "append_receipt", original)
    assert {model: count(work, model) for model in before_counts} == before_counts
    assert listing(work)["current_by_sample"][sample["id"]] == before
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
        assert confirmation is not None and confirmation.consumed is False
    retried = post(work.setup, prepared)
    assert retried.status_code == 200, retried.text
    assert retried.json()["subject_revision"] == 2
