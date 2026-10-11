from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.manufacturing_trials.handlers import ManufacturingTrialsHandler
from pdos_next.domain.manufacturing_trials.ports import Ports
from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import Gap, ToolTrialCreate
from pdos_next.schemas.verification.contracts import RequestCreate
from pdos_next.schemas.verification.contracts import TestItem as VerificationItem

from .helpers import NOW, SOURCE, counts, create_pilot, creation, host, prepare, record, ref


def replace(record_instance, **changes):
    return type(record_instance).model_validate({**record_instance.model_dump(), **changes})


def trial():
    request = RequestCreate(
        request_id=UUID(int=50),
        build_id=UUID(int=11),
        expected_build_revision=1,
        title="合成品质请求",
        purpose="试模前方法准备",
        items=(VerificationItem(id="dimension", feature="尺寸", sample_count=2, cavities=("A",)),),
        return_form="原始值",
    )
    return ToolTrialCreate(
        trial_id=UUID(int=40),
        build=ref("build", 11),
        tooling=ref("tooling", 41),
        trial_round=1,
        purpose="合成试模",
        cavities=("A",),
        verification=request,
        source=SOURCE,
    )


def test_draft_process_unknown_never_start():
    handler, commands, _ = host()
    payload = creation()
    handler.execute(prepare(handler, commands, payload), payload)
    pilot = commands.pilots[payload.pilot_id]
    assert pilot.details.basis.process_revision.kind == "process_revision"
    assert pilot.details.manufacturing_baseline is None
    assert pilot.readiness.state == "UNKNOWN" and not pilot.readiness.start_authorized
    assert any(g.code == "MISSING_MANUFACTURING_BASELINE" for g in pilot.readiness.gaps)
    assert commands.events == ["pilot.created"]


def test_trial_round_atomic_quality_intent():
    handler, commands, facts = host()
    facts.gaps = (
        Gap(code="SAMPLE_UNKNOWN", detail="无实物", state="unknown", owner_role="production"),
        Gap(code="METHOD_UNKNOWN", detail="方法未知", state="unknown", owner_role="quality"),
    )
    payload = trial()
    handler.execute(prepare(handler, commands, payload, "npi.tooltrial.create"), payload)
    value = commands.trials[payload.trial_id]
    assert value.details.trial_round == 1 and value.write_tier == "T1"
    assert value.readiness.state == "UNKNOWN"
    assert commands.verifications[payload.verification.request_id] == payload.verification
    assert not commands.observations


@pytest.mark.parametrize("stage", ["domain", "verification", "event", "receipt"])
def test_atomic_rollback_recovery(stage):
    handler, commands, _ = host()
    payload = trial()
    invocation = prepare(handler, commands, payload, "npi.tooltrial.create")
    commands.fail_at = stage
    with pytest.raises(RuntimeError):
        handler.execute(invocation, payload)
    assert not commands.trials and not commands.verifications and not commands.events
    assert not commands.receipts and not commands.keys and not commands.intents
    assert not commands.proofs[invocation.confirmation_token][2]
    commands.fail_at = None
    handler.execute(invocation, payload)
    assert len(commands.trials) == len(commands.verifications) == len(commands.receipts) == 1


def test_receipt_replay_across_keys_and_current_acl():
    handler, commands, _, pilot = create_pilot()
    payload = record(pilot)
    invocation = prepare(handler, commands, payload, "npi.pilot.result.record", pilot.id)
    first = handler.execute(invocation, payload)
    replay = handler.execute(invocation, payload)
    other = handler.execute(replace(invocation, command_id=uuid4()), payload)
    assert first.receipt_id == replay.receipt_id == other.receipt_id
    assert replay.replayed and other.replayed
    assert len(commands.observations) == 1 and commands.pilots[pilot.id].revision == 2
    commands.authority = replace(commands.authority, authorized=False)
    with pytest.raises(DomainError, match="replay ACL"):
        handler.execute(invocation, payload)


def test_correction_append_keeps_history_denominator_time():
    handler, commands, _, pilot = create_pilot()
    first = record(pilot)
    handler.execute(prepare(handler, commands, first, "npi.pilot.result.record", pilot.id), first)
    current = commands.pilots[pilot.id]
    value = record(
        current,
        previous_observation_id=first.observation_id,
        correction_reason="合成第二次返工结果续版",
        counts=counts(final_good=9, reworked_good=3, rework_pending=0, rework_cycles=10),
    )
    handler.execute(prepare(handler, commands, value, "npi.pilot.result.record", pilot.id), value)
    assert len(commands.observations) == 2 and commands.pilots[pilot.id].revision == 3
    assert commands.observations[first.observation_id].result.counts.final_good == 8
    assert commands.observations[value.observation_id].result.counts.input_count == 10
    assert commands.observations[value.observation_id].time.received_at == NOW


@pytest.mark.parametrize(
    "change,code",
    [
        ("denominator", "FIXED_DENOMINATOR_CHANGED"),
        ("window", "FIXED_SCOPE_CHANGED"),
        ("criterion", "FIXED_SCOPE_CHANGED"),
        ("previous", "VERSION_CONFLICT"),
    ],
)
def test_correction_fixed_scope(change, code):
    handler, commands, _, pilot = create_pilot()
    first = record(pilot)
    handler.execute(prepare(handler, commands, first, "npi.pilot.result.record", pilot.id), first)
    current = commands.pilots[pilot.id]
    changes = dict(previous_observation_id=first.observation_id, correction_reason="更正来源核对")
    if change == "denominator":
        changes["counts"] = counts(input_count=None)
    elif change == "window":
        changes["scope"] = replace(first.scope, window_start=NOW - timedelta(hours=3))
    elif change == "criterion":
        changes["scope"] = replace(first.scope, criterion=ref("criterion", 555))
    else:
        changes["previous_observation_id"] = uuid4()
    with pytest.raises(DomainError) as error:
        handler.preview(
            "npi.pilot.result.record", pilot.id, current.revision, record(current, **changes)
        )
    assert error.value.reason == code


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit", "piece"),
        ("lot", ref("build_lot", 100)),
        ("actual_configuration", ref("actual_configuration", 100)),
        ("process_revision", ref("process_revision", 100)),
    ],
)
def test_actual_batch_config_unit_mismatch(field, value):
    handler, _, _, pilot = create_pilot()
    payload = record(pilot)
    value = replace(
        payload, scope=replace(payload.scope, basis=replace(payload.scope.basis, **{field: value}))
    )
    with pytest.raises(DomainError) as error:
        handler.preview("npi.pilot.result.record", pilot.id, 1, value)
    assert error.value.reason == "INCOMPATIBLE_SCOPE"


def test_server_lot_drift_quantity_limit():
    handler, commands, facts = host()
    payload = creation()
    facts.lot_facts = replace(facts.lot_facts, basis=replace(payload.basis, unit="台"))
    with pytest.raises(DomainError, match="不一致"):
        prepare(handler, commands, payload)
    handler, _, facts, pilot = create_pilot()
    facts.lot_facts = replace(facts.lot_facts, observed_unit_count=9)
    with pytest.raises(DomainError) as error:
        handler.preview("npi.pilot.result.record", pilot.id, 1, record(pilot))
    assert error.value.reason == "LOT_LIMIT"


def test_server_fixed_threshold():
    handler, _, facts, pilot = create_pilot()
    payload = record(pilot)
    facts.scope_override = replace(payload.scope, minimum_sample=100)
    with pytest.raises(DomainError) as error:
        handler.preview("npi.pilot.result.record", pilot.id, 1, payload)
    assert error.value.reason == "SOURCE_CHANGED"


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("authorized", False, "FORBIDDEN"),
        ("roles", ("quality",), "FORBIDDEN"),
        ("qualified", False, "QUALIFICATION_REQUIRED"),
        ("cancelled", True, "RUN_CANCELLED"),
    ],
)
def test_server_authority(field, value, code):
    handler, commands, _ = host()
    commands.authority = replace(commands.authority, **{field: value})
    with pytest.raises(DomainError) as error:
        handler.preview("npi.pilot.create", creation().pilot_id, 0, creation())
    assert error.value.reason == code


def test_current_qualification_revocation_rolls_back():
    handler, commands, _ = host()
    payload = creation()
    invocation = prepare(handler, commands, payload)
    commands.revoke_at_recheck = True
    with pytest.raises(DomainError) as error:
        handler.execute(invocation, payload)
    assert error.value.reason == "QUALIFICATION_REQUIRED"
    assert not commands.proofs[invocation.confirmation_token][2] and not commands.pilots


@pytest.mark.parametrize("change", ["expired", "gaps", "source", "ref"])
def test_confirm_expiry_drift_withdrawal(change):
    handler, commands, facts = host()
    payload = creation()
    invocation = prepare(handler, commands, payload)
    if change == "expired":
        digest, _, used = commands.proofs[invocation.confirmation_token]
        commands.proofs[invocation.confirmation_token] = (digest, NOW - timedelta(seconds=1), used)
    elif change == "gaps":
        facts.gaps = (
            Gap(
                code="FIXTURE_UNACCEPTED",
                detail="治具未验收",
                state="blocked",
                owner_role="engineering",
            ),
        )
    elif change == "source":
        facts.bad_source = True
    else:
        facts.revoked.add(payload.basis.process_revision.id)
    with pytest.raises(DomainError):
        handler.execute(invocation, payload)
    assert not commands.pilots


def test_hard_resource_gap_visible_candidate_only():
    handler, commands, facts = host()
    facts.gaps = (
        Gap(
            code="FIXTURE_UNACCEPTED",
            detail="治具未验收",
            state="blocked",
            owner_role="engineering",
        ),
    )
    payload = creation()
    handler.execute(prepare(handler, commands, payload), payload)
    value = commands.pilots[payload.pilot_id]
    assert value.readiness.state == "BLOCKED" and not value.readiness.start_authorized


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "qualified", "write_tier"])
def test_closed_payload(field):
    with pytest.raises(ValidationError):
        type(creation()).model_validate({**creation().model_dump(), field: "T0"})


def test_missing_ports_fail_closed_t2_unregistered():
    with pytest.raises(DomainError) as error:
        ManufacturingTrialsHandler(Ports()).preview(
            "npi.pilot.create", creation().pilot_id, 0, creation()
        )
    assert error.value.reason == "INTEGRATION_REQUIRED"
    handler, _, _ = host()
    for operation in ("npi.pilot.start", "manufacturing.release", "tooling.accept", "T0"):
        with pytest.raises(DomainError) as error:
            handler.preview(operation, creation().pilot_id, 0, {})
        assert error.value.reason == "OPERATION_UNAVAILABLE"


def test_optimistic_conflict_preserves_confirmation():
    handler, commands, _, pilot = create_pilot()
    value = record(pilot)
    invocation = prepare(handler, commands, value, "npi.pilot.result.record", pilot.id)
    commands.pilots[pilot.id] = replace(pilot, revision=2)
    with pytest.raises(DomainError) as error:
        handler.execute(invocation, value)
    assert error.value.reason == "VERSION_CONFLICT"
    assert not commands.proofs[invocation.confirmation_token][2] and not commands.observations


def test_result_failure_recover_same_intent():
    handler, commands, _, pilot = create_pilot()
    value = record(pilot)
    invocation = prepare(handler, commands, value, "npi.pilot.result.record", pilot.id)
    commands.fail_at = "receipt"
    with pytest.raises(RuntimeError):
        handler.execute(invocation, value)
    assert commands.pilots[pilot.id] == pilot and not commands.observations
    commands.fail_at = None
    outcome = handler.execute(invocation, value)
    assert outcome.revision == 2 and len(commands.observations) == 1


def test_unknown_denominator_may_be_resolved_for_same_server_fixed_cohort():
    handler, commands, _, pilot = create_pilot()
    first = record(pilot, counts=counts(input_count=None))
    handler.execute(prepare(handler, commands, first, "npi.pilot.result.record", pilot.id), first)
    current = commands.pilots[pilot.id]
    value = record(
        current,
        previous_observation_id=first.observation_id,
        correction_reason="同固定实际范围的分母来源已核对",
        counts=counts(),
    )
    handler.execute(prepare(handler, commands, value, "npi.pilot.result.record", pilot.id), value)
    assert commands.observations[first.observation_id].result.final_good_yield is None
    assert commands.observations[value.observation_id].result.counts.input_count == 10


def test_result_real_synthetic_mismatch_and_future_window():
    handler, _, _, pilot = create_pilot()
    payload = record(pilot)
    for scope, code in (
        (replace(payload.scope, nature="real"), "NATURE_MISMATCH"),
        (replace(payload.scope, window_end=NOW + timedelta(seconds=1)), "FUTURE_OBSERVATION"),
    ):
        with pytest.raises(DomainError) as error:
            handler.preview("npi.pilot.result.record", pilot.id, 1, replace(payload, scope=scope))
        assert error.value.reason == code


def test_second_extension_of_same_lot_rejected_and_proof_rolled_back():
    handler, commands, _, pilot = create_pilot()
    value = replace(pilot.details, pilot_id=uuid4())
    invocation = prepare(handler, commands, value)
    with pytest.raises(DomainError) as error:
        handler.execute(invocation, value)
    assert error.value.reason == "DUPLICATE_INTENT_CONFLICT"
    assert len(commands.pilots) == 1 and not commands.proofs[invocation.confirmation_token][2]


def test_preview_changed_payload_and_command_key_payload_conflict():
    handler, commands, _ = host()
    value = creation()
    invocation = prepare(handler, commands, value)
    with pytest.raises(DomainError) as error:
        handler.execute(invocation, replace(value, purpose="篡改实质输入"))
    assert error.value.reason == "INTENT_MISMATCH"
    handler.execute(invocation, value)
    from pdos_next.domain.manufacturing_trials.handlers import semantic_digest

    changed = replace(value, purpose="第二载荷")
    invocation = replace(invocation, semantic_digest=semantic_digest(changed))
    with pytest.raises(DomainError) as error:
        handler.execute(invocation, changed)
    assert error.value.reason == "DUPLICATE_INTENT_CONFLICT"


def test_lot_and_pilot_server_scope_is_not_model_supplied():
    handler, commands, facts = host()
    value = creation()
    foreign_scope = replace(commands.authority.scope, tenant_id=uuid4())
    facts.lot_facts = replace(facts.lot_facts, scope=foreign_scope)
    with pytest.raises(DomainError) as error:
        handler.preview("npi.pilot.create", value.pilot_id, 0, value)
    assert error.value.reason == "SOURCE_CHANGED"
    handler, commands, _, pilot = create_pilot()
    commands.pilots[pilot.id] = replace(pilot, scope=foreign_scope)
    with pytest.raises(DomainError) as error:
        handler.preview("npi.pilot.result.record", pilot.id, 1, record(pilot))
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_unit_result_source_and_server_membership_are_required():
    from pdos_next.schemas.manufacturing_trials.contracts import UnitOutcome

    handler, commands, facts, pilot = create_pilot()
    units = (
        UnitOutcome(
            sample=ref("sample", 100),
            first_result="fail",
            final_state="good",
            rework_cycles=3,
            source=SOURCE,
        ),
    )
    value = record(pilot, counts=None, units=units)
    invocation = prepare(handler, commands, value, "npi.pilot.result.record", pilot.id)
    facts.revoked.add(units[0].sample.id)
    with pytest.raises(DomainError) as error:
        handler.execute(invocation, value)
    assert error.value.reason == "SOURCE_UNAVAILABLE"
    assert not commands.observations
    facts.revoked.clear()
    facts.bad_source = True
    with pytest.raises(DomainError) as error:
        handler.execute(invocation, value)
    assert error.value.reason == "SOURCE_UNAVAILABLE"
    assert not commands.observations


def test_resource_qualification_fixed_readset_drift_invalidates_preview():
    handler, commands, facts = host()
    value = creation()
    invocation = prepare(handler, commands, value)
    facts.preparation_refs = (replace(facts.preparation_refs[0], revision=2),)
    with pytest.raises(DomainError) as error:
        handler.execute(invocation, value)
    assert error.value.reason == "CONFIRMATION_REQUIRED"
    assert not commands.pilots and not commands.proofs[invocation.confirmation_token][2]


def test_resource_fixed_refs_revocation_blocks_new_observation():
    handler, _, facts, pilot = create_pilot()
    facts.revoked.add(facts.preparation_refs[0].id)
    with pytest.raises(DomainError) as error:
        handler.preview("npi.pilot.result.record", pilot.id, 1, record(pilot))
    assert error.value.reason == "SOURCE_UNAVAILABLE"


def test_parameter_values_are_source_bound_not_model_facts():
    from pdos_next.schemas.manufacturing_trials.contracts import Parameter

    handler, commands, facts = host()
    parameter = Parameter(key="pressure", value="4.20", unit="MPa", source=SOURCE)
    value = replace(creation(), parameters=(parameter,))
    facts.parameters_override = (replace(parameter, value="9.00"),)
    with pytest.raises(DomainError) as error:
        handler.preview("npi.pilot.create", value.pilot_id, 0, value)
    assert error.value.reason == "PARAMETER_SOURCE_MISMATCH"
    assert not commands.pilots


def test_trial_parameter_raw_unit_mismatch_rejected():
    from pdos_next.schemas.manufacturing_trials.contracts import Parameter

    handler, commands, facts = host()
    parameter = Parameter(key="temperature", value="120", unit="C", source=SOURCE)
    value = replace(trial(), parameters=(parameter,))
    facts.parameters_override = (replace(parameter, unit="K"),)
    with pytest.raises(DomainError) as error:
        handler.preview("npi.tooltrial.create", value.trial_id, 0, value)
    assert error.value.reason == "PARAMETER_SOURCE_MISMATCH"
    assert not commands.trials
