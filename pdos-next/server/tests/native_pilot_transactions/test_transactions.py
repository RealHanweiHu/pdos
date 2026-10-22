"""One candidate real API/PG Pilot case; Root alone executes it.

The reused S2 failure provides the actual same-project Issue. Only one terminal
failure is injected; source/authority/clock/consumption/business ports stay real.
"""

from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from pdos_next.domain.manufacturing_trials import native_service
from pdos_next.errors import DomainError
from pdos_next.models import RequestKey

from . import fixtures as helper


@pytest.mark.parametrize("launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True)
def test_actual_pilot_partial_correction_yields_issue_history_peer_replay_and_rollback(
    native_case, monkeypatch, record_property
):
    work, setup = native_case, native_case.setup
    record_property("fixture_nature", "synthetic originals and actual controlled synthetic imports")
    record_property(
        "qualification", "unknown; no Pilot start, factory qualification or manufacturing release"
    )
    record_property("project_id", str(work.project_id))
    record_property("prior_build_id", work.upstream.build_id)
    record_property("new_build_id", str(work.basis.build.id))

    before = helper.snapshots(work)
    command, review = helper.prepare(
        work, helper.CREATE_OPERATION, work.create.model_dump(mode="json")
    )
    assert review["after"]["qualification"] == "unknown"
    assert review["after"]["start_authorized"] is False
    state = helper.snapshots(work)
    for table, old in before.items():
        assert state[table]["count"] == old["count"] + (table == "confirmations")
    initial_proof = helper.proof(work, command)
    assert initial_proof[1] is False
    response = helper.post(setup, command)
    assert response.status_code == 200, response.text
    create_receipt = response.json()
    helper.assert_atom(work, command, create_receipt, helper.NativePilotRun)
    pilot = helper.read_pilot(work, work.create.details.pilot_id)
    assert pilot["current"]["revision"] == 1 and pilot["observations"] == []
    assert pilot["pilot"]["details"]["basis"]["lot"] == work.basis.lot.model_dump(mode="json")
    stats = pilot["pilot"]["material"]["statistics"]
    assert stats["resource"]["execution_authorized"] is False
    assert stats["resource"]["resources"][0]["acceptance"] == "unknown"

    partial, _ = helper.result_payload(work, work.create, exception=True)
    partial_command, _ = helper.prepare(
        work, helper.RESULT_OPERATION, partial.model_dump(mode="json")
    )
    partial_response = helper.post(setup, partial_command)
    assert partial_response.status_code == 200, partial_response.text
    partial_receipt = partial_response.json()
    helper.assert_atom(work, partial_command, partial_receipt, helper.NativePilotObservation)
    partial_view = helper.read_pilot(work, work.create.details.pilot_id)
    first = partial_view["observations"][0]
    assert partial_view["current"]["revision"] == 2
    metrics = first["projection"]["metrics"]
    assert Decimal(metrics["first_pass_yield"]["value"]) == Decimal("0.5")
    assert metrics["final_good_yield"]["value"] is None
    assert Decimal(metrics["final_good_yield"]["recorded_fraction"]) == Decimal("0.5")
    assert first["record"]["exceptions"][0]["issue"]["id"] == str(work.issue_id)
    original = helper.observation_snapshot(work, first["id"])

    complete, _ = helper.result_payload(
        work, work.create, revision=2, previous=first, complete=True, exception=True
    )
    complete_command, _ = helper.prepare(
        work, helper.RESULT_OPERATION, complete.model_dump(mode="json")
    )
    response = helper.post(setup, complete_command)
    assert response.status_code == 200, response.text
    complete_receipt = response.json()
    helper.assert_atom(work, complete_command, complete_receipt, helper.NativePilotObservation)
    final = helper.read_pilot(work, work.create.details.pilot_id)
    assert final["current"]["revision"] == 3 and len(final["observations"]) == 2
    latest = final["observations"][-1]
    assert latest["previous_observation_id"] == first["id"]
    assert latest["fixed_scope"]["cohort"]["fixed_input_count"] == work.population_count
    metrics = latest["projection"]["metrics"]
    assert Decimal(metrics["first_pass_yield"]["value"]) == Decimal("0.5")
    assert Decimal(metrics["final_good_yield"]["value"]) == Decimal("1")
    assert metrics["factory_qualification"] == "NOT_ASSESSED"
    assert final["qualification"] == "unknown" and final["manufacturing_release"] is None
    assert helper.observation_snapshot(work, first["id"]) == original

    # An already saved observation cannot be repurposed as a new Current write.
    before_stale = helper.snapshots(work)
    stale = helper.input_response(work, helper.RESULT_OPERATION, partial.model_dump(mode="json"))
    assert stale.status_code == 409, stale.text
    assert helper.snapshots(work) == before_stale
    for old_command, receipt in ((command, create_receipt), (complete_command, complete_receipt)):
        before_replay = helper.snapshots(work)
        replay = helper.post(setup, deepcopy(old_command))
        assert replay.status_code == 200 and replay.json() == receipt, replay.text
        assert helper.snapshots(work) == before_replay
        alias = {
            **deepcopy(old_command),
            "command_id": str(uuid4()),
            "idempotency_key": str(uuid4()),
        }
        replay = helper.post(setup, alias)
        assert replay.status_code == 200 and replay.json() == receipt, replay.text
        after = helper.snapshots(work)
        for table, old in before_replay.items():
            assert after[table]["count"] == old["count"] + (table == "request_keys")
    assert helper.read_pilot(work, work.create.details.pilot_id, actor=setup.peer) == final
    with helper.publication.session(work, setup.peer) as s:
        assert (
            list(
                s.scalars(
                    select(RequestKey).where(RequestKey.receipt_id == UUID(create_receipt["id"]))
                )
            )
            == []
        )

    listed = helper.list_pilots(work, actor=setup.peer)
    assert listed["project_id"] == str(work.project_id)
    assert len(listed["items"]) == 1 and listed["next_cursor"] is None

    third, _ = helper.result_payload(
        work, work.create, revision=3, previous=latest, complete=True, exception=True
    )
    failed_command, _ = helper.prepare(work, helper.RESULT_OPERATION, third.model_dump(mode="json"))
    before_failure = helper.snapshots(work, helper.ROLLBACK_MODELS)
    unconsumed = helper.proof(work, failed_command)
    real_finalize = native_service.finalize_receipt
    attempted = []

    def fail_tail(s, ctx, command, product, payload, subject, receipt):
        real_finalize(s, ctx, command, product, payload, subject, receipt)
        assert command.command_id == UUID(failed_command["command_id"])
        attempted.append(subject.id)
        raise DomainError("INTERNAL_ERROR", "Synthetic single terminal Pilot rollback")

    with monkeypatch.context() as fault:
        fault.setattr(native_service, "finalize_receipt", fail_tail)
        failed = helper.post(setup, failed_command)
    assert failed.status_code == 500 and failed.json()["code"] == "INTERNAL_ERROR", failed.text
    assert len(attempted) == 1
    assert helper.snapshots(work, helper.ROLLBACK_MODELS) == before_failure
    assert helper.proof(work, failed_command) == unconsumed
    assert helper.read_pilot(work, work.create.details.pilot_id) == final

    helper.withdraw(work, work.statistics_original_id)
    history = helper.read_pilot(work, work.create.details.pilot_id)
    assert len(history["observations"]) == 2
    assert history["pilot"]["source_status"] == "needs_recheck"
    assert history["observations"][-1]["record"] == latest["record"]
    frozen = helper.snapshots(work)
    refused = helper.input_response(work, helper.RESULT_OPERATION, third.model_dump(mode="json"))
    assert refused.status_code in {403, 409}, refused.text
    assert refused.json()["code"] in {"SOURCE_UNAVAILABLE", "SOURCE_STALE", "RECHECK_REQUIRED"}
    assert helper.snapshots(work) == frozen
    replay = helper.post(setup, complete_command)
    assert replay.status_code == 200 and replay.json() == complete_receipt, replay.text
    assert helper.snapshots(work) == frozen
    record_property("pilot_id", str(work.create.details.pilot_id))
    record_property("observation_ids", f"{first['id']},{latest['id']}")
    record_property("issue_id", str(work.issue_id))
