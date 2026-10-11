from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.capa_verification import commands, service
from pdos_next.domain.capa_verification.ports import require_effectiveness_bridge
from pdos_next.domain.capa_verification.schemas import (
    ActionBinding,
    CandidateBinding,
    CandidateInspect,
    FailurePairMapping,
    FollowupBasis,
    FollowupLinkPayload,
    OutputReading,
    OutputRef,
    ResolvedOutputs,
    SourceRead,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import EffectivenessRequirement
from pdos_next.schemas.verification.contracts import Scope


@pytest.fixture
def basis():
    source = SourceRead(artifact_id=uuid4(), expected_revision=1)
    value = FollowupBasis(
        scope=Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4()),
        issue_id=uuid4(),
        issue_version_id=uuid4(),
        issue_revision=4,
        capa_id=uuid4(),
        purpose="Inspect actual investigation",
        owner_id=uuid4(),
        visibility="category",
        nature="synthetic",
        requirement=EffectivenessRequirement(
            method="Independent inspection",
            acceptance="All exact original failures covered",
            observation_until=datetime(2026, 10, 2, tzinfo=UTC),
            required_failure_ids=("failure-a", "failure-b"),
        ),
        requirement_sha256="a" * 64,
        failure_ids=("failure-a", "failure-b"),
        failure_basis_sha256="b" * 64,
        actions=(ActionBinding(action_id=uuid4(), executor_id=uuid4(), action_sha256="c" * 64),),
        sources=(),
        required_source_read_set=(source,),
        source_basis_sha256="d" * 64,
        basis_sha256="0" * 64,
    )
    return value.model_copy(update={"basis_sha256": service._basis_digest(value)})


@pytest.fixture
def context(basis):
    return SimpleNamespace(
        tenant_id=basis.scope.tenant_id,
        requester_id=basis.owner_id,
        actor_id=basis.owner_id,
        run_id=None,
    )


def patch_reads(monkeypatch, basis):
    monkeypatch.setattr(service, "recheck_followup_basis", lambda *a, **k: basis)
    monkeypatch.setattr(service.quality, "_human", lambda *a, **k: None)
    monkeypatch.setattr(service, "source_basis", lambda *a, **k: ([{"stable": "source"}], False))


def output(basis, *, kind="build", snapshot=None):
    return OutputReading(
        ref=OutputRef(kind=kind, id=uuid4(), revision=1),
        owner_id=basis.owner_id,
        visibility="category",
        project_id=basis.scope.project_id,
        title="Real fixed owner output",
        status="planned",
        meaning="planned",
        source_status="current",
        snapshot=snapshot or {},
        required_source_read_set=basis.required_source_read_set,
        owner_basis_sha256="a" * 64,
    )


@pytest.mark.parametrize("revision", [True, 0, "1", 1.5])
def test_output_requires_actual_strict_revision(revision):
    with pytest.raises(ValidationError):
        OutputRef(kind="build", id=uuid4(), revision=revision)


@pytest.mark.parametrize("extra", [{"approved": True}, {"qualified": True}, {"current": True}])
def test_public_refs_cannot_supply_owner_facts(extra):
    with pytest.raises(ValidationError):
        OutputRef(kind="build", id=uuid4(), revision=1, **extra)


def test_key_is_not_a_generic_scope_bypass():
    with pytest.raises(ValidationError):
        OutputRef(kind="build", id=uuid4(), revision=1, key="foreign")
    assert OutputRef(kind="bom", id=uuid4(), revision=1, key="real-line").key == "real-line"


def test_candidate_cannot_be_claimed_positive(basis):
    raw = dict(
        binding=CandidateBinding(basis=basis),
        current=True,
        required_source_read_set=basis.required_source_read_set,
        source_basis_sha256="a" * 64,
        inspection_sha256="b" * 64,
        missing=(),
    )
    for update in (
        {"applicable": True},
        {"result": "pass"},
        {"observation_complete": True},
        {"capabilities": {"effectiveness_decide": True}},
    ):
        with pytest.raises(ValidationError):
            CandidateInspect(**{**raw, **update})


def test_fake_full_observation_port_always_requires_integration():
    with pytest.raises(DomainError) as raised:
        require_effectiveness_bridge()
    assert (raised.value.reason, raised.value.status) == ("INTEGRATION_REQUIRED", 503)


@pytest.mark.parametrize("problem", ["product", "project", "private", "revision"])
def test_owner_exact_scope_and_acl_survive_fixed_ref(monkeypatch, basis, context, problem):
    selected = output(basis)
    row = SimpleNamespace(
        tenant_id=basis.scope.tenant_id,
        product_id=basis.scope.product_id,
        id=selected.ref.id,
        revision=1,
        owner_id=basis.owner_id,
        visibility="category",
        project_id=basis.scope.project_id,
        status="planned",
        required_source_read_set=basis.required_source_read_set,
    )
    if problem == "product":
        row.product_id = uuid4()
    elif problem == "project":
        row.project_id = uuid4()
    elif problem == "private":
        row.visibility, row.owner_id = "private", uuid4()
    else:
        row.revision = 2
    monkeypatch.setattr(service, "_owner", lambda *a: (row, {"status": "planned"}))
    with pytest.raises(DomainError) as raised:
        service._reading(None, context, basis.scope.product_id, basis, selected.ref)
    assert raised.value.status == 403


def test_output_without_readable_source_is_not_a_fact(monkeypatch, basis, context):
    selected = output(basis)
    row = SimpleNamespace(
        tenant_id=basis.scope.tenant_id,
        product_id=basis.scope.product_id,
        id=selected.ref.id,
        revision=1,
        project_id=basis.scope.project_id,
        owner_id=basis.owner_id,
        visibility="category",
        status="planned",
    )
    monkeypatch.setattr(service, "_owner", lambda *a: (row, {"status": "planned"}))
    with pytest.raises(DomainError) as raised:
        service._reading(None, context, basis.scope.product_id, basis, selected.ref)
    assert raised.value.reason == "INTEGRATION_REQUIRED"


def test_resolution_retains_unknown_fulfillment(monkeypatch, basis, context):
    patch_reads(monkeypatch, basis)
    selected = output(basis)
    monkeypatch.setattr(service, "_reading", lambda *a: selected)
    resolved = service.resolve_followup_outputs(
        None, context, basis.scope.product_id, basis, basis.actions[0].action_id, (selected.ref,)
    )
    assert resolved.action_fulfilled is None
    assert {m.code for m in resolved.missing} == {
        "ACTION_NOT_COMPLETED",
        "ACTION_FULFILLMENT_PORT_MISSING",
    }
    assert resolved.outputs[0].meaning == "planned"
    assert resolved.resolution_sha256 != "0" * 64


def test_resolution_private_output_intersects_audience(monkeypatch, basis, context):
    patch_reads(monkeypatch, basis)
    selected = output(basis).model_copy(update={"visibility": "private"})
    monkeypatch.setattr(service, "_reading", lambda *a: selected)
    resolved = service.resolve_followup_outputs(
        None, context, basis.scope.product_id, basis, basis.actions[0].action_id, (selected.ref,)
    )
    assert resolved.visibility == "private" and resolved.owner_id == context.requester_id


def test_resolution_rereads_after_owner_io(monkeypatch, basis, context):
    patch_reads(monkeypatch, basis)
    first = output(basis)
    second = first.model_copy(update={"owner_basis_sha256": "b" * 64})
    readings = iter((first, second))
    monkeypatch.setattr(service, "_reading", lambda *a: next(readings))
    with pytest.raises(DomainError) as raised:
        service.resolve_followup_outputs(
            None, context, basis.scope.product_id, basis, basis.actions[0].action_id, (first.ref,)
        )
    assert raised.value.reason == "SOURCE_STALE"


def test_complete_readset_limit_is_not_truncated(basis):
    extra = [SourceRead(artifact_id=uuid4(), expected_revision=1) for _ in range(20)]
    result = service._reads(basis.required_source_read_set, extra)
    assert len(result) == len(basis.required_source_read_set) + len(extra)
    assert {v.artifact_id for v in extra} <= {v.artifact_id for v in result}


def test_basis_version_only_addition_is_distinct_from_semantic_change(basis):
    later = basis.model_copy(update={"issue_revision": 5, "issue_version_id": uuid4()})
    assert service._basis_material(later) == service._basis_material(basis)
    changed = later.model_copy(update={"root_cause_sha256": "f" * 64})
    assert service._basis_material(changed) != service._basis_material(basis)


def test_link_intent_keeps_action_and_exact_owner_refs(basis):
    selected = output(basis)
    raw = dict(
        issue_id=basis.issue_id,
        expected_issue_revision=basis.issue_revision,
        capa_id=basis.capa_id,
        action_id=basis.actions[0].action_id,
        output_refs=(selected.ref,),
        reason="Record exact investigation output",
    )
    first = FollowupLinkPayload(**raw, confirmation_token="a" * 24)
    second = FollowupLinkPayload(**raw, confirmation_token="b" * 24)
    assert commands.semantic(first) == commands.semantic(second)
    assert commands.semantic(first) != commands.semantic(
        first.model_copy(update={"action_id": uuid4()})
    )


def test_common_proof_missing_is_fail_closed_before_qualification(monkeypatch, basis, context):
    monkeypatch.setattr(service.quality, "_human", lambda *a, **k: None)
    selected = output(basis)
    payload = FollowupLinkPayload(
        issue_id=basis.issue_id,
        expected_issue_revision=4,
        capa_id=basis.capa_id,
        action_id=basis.actions[0].action_id,
        output_refs=(selected.ref,),
        reason="Exact output",
    )
    session = SimpleNamespace(get_bind=lambda: SimpleNamespace())
    product = SimpleNamespace(id=basis.scope.product_id)
    command = SimpleNamespace(operation=commands.OPERATION, product_id=product.id)
    with pytest.raises(DomainError) as raised:
        commands._load(session, context, command, product, payload)
    assert (raised.value.reason, raised.value.status) == ("INTEGRATION_REQUIRED", 503)


def test_unconfigured_professional_matrix_is_not_a_false_qualification(monkeypatch, basis, context):
    monkeypatch.setattr(
        commands.professional,
        "assess",
        lambda *a, **k: {
            "reason_codes": ["PROFESSIONAL_OPERATION_NOT_CONFIGURED"],
            "qualified": None,
        },
    )
    with pytest.raises(DomainError) as raised:
        commands._authority(None, context, basis.scope.product_id, basis)
    assert (raised.value.reason, raised.value.status) == ("INTEGRATION_REQUIRED", 503)


def test_future_inspection_clock_cannot_be_a_current_proof():
    with pytest.raises(DomainError) as raised:
        service._at(datetime.now(UTC) + timedelta(days=1))
    assert raised.value.reason == "INVALID_TIME"


@pytest.mark.parametrize("proof", [None, True, False, "b9cec78b-5ad8-46fb-8c12-14aed52f4795"])
def test_apply_rejects_non_uuid_common_proof(monkeypatch, basis, context, proof):
    bound, payload, product, command = apply_fixture(monkeypatch, basis, context, proof)
    with pytest.raises(DomainError) as raised:
        commands.apply(None, context, command, product, payload)
    assert raised.value.reason == "INTEGRATION_REQUIRED"
    assert bound.proof_callback(None, context, command, product, payload) == proof


def apply_fixture(monkeypatch, basis, context, proof):
    selected = output(basis)
    resolved = ResolvedOutputs(
        basis=basis,
        action_id=basis.actions[0].action_id,
        outputs=(selected,),
        visibility="category",
        owner_id=basis.owner_id,
        required_source_read_set=basis.required_source_read_set,
        source_basis_sha256="a" * 64,
        resolution_sha256="b" * 64,
    )
    bound = commands.Bound(resolved, {}, {}, (), [], {}, "category", lambda *args: proof)
    payload = FollowupLinkPayload(
        issue_id=basis.issue_id,
        expected_issue_revision=basis.issue_revision,
        capa_id=basis.capa_id,
        action_id=basis.actions[0].action_id,
        output_refs=(selected.ref,),
        reason="Actual fixed output",
        confirmation_token="a" * 24,
    )
    product = SimpleNamespace(id=basis.scope.product_id)
    command = SimpleNamespace(operation=commands.OPERATION, product_id=product.id)
    monkeypatch.setattr(commands, "_load", lambda *a, **k: bound)
    monkeypatch.setattr(commands, "_new_write", lambda *a, **k: None)
    monkeypatch.setattr(commands, "_refresh", lambda *a, **k: None)
    return bound, payload, product, command


def test_apply_records_actual_proof_reference_without_token_or_issue_write(
    monkeypatch, basis, context
):
    proof = uuid4()
    _, payload, product, command = apply_fixture(monkeypatch, basis, context, proof)
    row, family, visibility = commands.apply(None, context, command, product, payload)
    assert family == "capa_remediation_link" and visibility == "category"
    assert row.input_snapshot["shared_proof"] == {"id": str(proof), "tier": "T1"}
    assert "confirmation_token" not in row.input_snapshot
    assert (
        row.issue_version_id == basis.issue_version_id
        and row.issue_revision == basis.issue_revision
    )
    assert row.output_snapshot["action_fulfilled"] is None


def test_expiry_during_other_owner_reads_is_not_a_current_link_proof(monkeypatch):
    instant = datetime.now(UTC)
    monkeypatch.setattr(service, "now", lambda: instant)
    authority = {
        "valid_until": None,
        "roles": ["quality"],
        "synthetic": True,
        "operation": commands.OPERATION,
        "purpose": "review",
        "fact_refs": [
            {
                "kind": kind,
                "role": "quality",
                "nature": "synthetic",
                "state": "active",
                "operations": [commands.OPERATION],
                "purposes": ["review"],
                "valid_from": (instant - timedelta(days=1)).isoformat(),
                "valid_until": instant.isoformat(),
            }
            for kind in ("duty", "qualification")
        ],
    }
    publication = {
        "id": "policy",
        "revision": 1,
        "valid_until": None,
        "source_basis": [
            {
                "id": "policy",
                "revision": 1,
                "state": "active",
                "valid_from": (instant - timedelta(days=1)).isoformat(),
                "valid_until": (instant + timedelta(days=1)).isoformat(),
            }
        ],
    }
    with pytest.raises(DomainError) as raised:
        commands._deadlines(authority, publication)
    assert raised.value.reason == "SOURCE_STALE"


@pytest.mark.parametrize(
    "changed", ["authority_snapshot", "policy_snapshot", "source_basis", "required_source_read_set"]
)
def test_original_replay_cannot_hide_epoch_aba_or_readset_drift(
    monkeypatch, basis, context, changed
):
    bound, payload, _, _ = apply_fixture(monkeypatch, basis, context, uuid4())
    row = SimpleNamespace(
        input_snapshot={
            **commands.semantic(payload),
            "shared_proof": {"id": str(uuid4()), "tier": "T1"},
        },
        resolution_sha256=bound.resolution.resolution_sha256,
        authority_snapshot=bound.authority,
        policy_snapshot=bound.policy,
        source_basis=bound.source_basis,
        required_source_read_set=bound.reads,
    )
    commands._guard_saved(row, payload, bound)
    setattr(row, changed, [{"epoch": 2}] if changed == "required_source_read_set" else {"epoch": 2})
    with pytest.raises(DomainError) as raised:
        commands._guard_saved(row, payload, bound)
    assert raised.value.reason == "SOURCE_STALE"


def test_unmapped_candidate_exposes_all_real_gaps(monkeypatch, basis, context):
    patch_reads(monkeypatch, basis)
    monkeypatch.setattr(service.quality, "_row", lambda *a, **k: object())
    monkeypatch.setattr(service.quality, "_snapshot", lambda *a: SimpleNamespace(failures=()))
    candidate = service.inspect_candidate(
        None, context, basis.scope.product_id, CandidateBinding(basis=basis), at=datetime.now(UTC)
    )
    assert (
        candidate.applicable
        is candidate.independently_verified
        is candidate.observation_complete
        is None
    )
    assert candidate.result == "indeterminate" and not any(candidate.capabilities.values())
    assert {m.failure_id for m in candidate.missing if m.code == "FAILURE_NOT_MAPPED"} == set(
        basis.failure_ids
    )
    assert {m.dimension for m in candidate.missing} >= {
        "root_cause",
        "completion",
        "mapping",
        "applicability",
        "independence",
        "observation",
        "policy",
    }


@pytest.mark.parametrize("bad", ["old_run", "sample", "item", "planned_measurement"])
def test_planned_mapping_cannot_invent_actual_measurement_or_scope(
    monkeypatch, basis, context, bad
):
    patch_reads(monkeypatch, basis)
    sample_id, actual_id, run_id = uuid4(), uuid4(), uuid4()
    run_ref = OutputRef(kind="verification_run", id=uuid4(), revision=1)
    selected = output(
        basis,
        kind="verification_run",
        snapshot={
            "run": {
                "samples": [
                    {
                        "id": str(sample_id),
                        "revision": 1,
                        "actual_configuration": {"id": str(actual_id), "revision": 1},
                    }
                ],
                "coverage": [{"sample_id": str(sample_id), "item_id": "inspection"}],
            },
            "source_nature": None,
            "retained": None,
        },
    ).model_copy(update={"ref": run_ref, "logical_id": run_id})
    monkeypatch.setattr(service, "_reading", lambda *a: selected)
    monkeypatch.setattr(service.quality, "_row", lambda *a, **k: object())
    monkeypatch.setattr(
        service.quality,
        "_snapshot",
        lambda *a: SimpleNamespace(
            failures=(
                SimpleNamespace(run=SimpleNamespace(id=run_id if bad == "old_run" else uuid4())),
            )
        ),
    )
    mapping = FailurePairMapping(
        failure_id="failure-a",
        run=run_ref,
        sample_id=uuid4() if bad == "sample" else sample_id,
        sample_revision=1,
        actual_configuration_id=actual_id,
        actual_configuration_revision=1,
        item_id="other" if bad == "item" else "inspection",
        measurement_id=uuid4() if bad == "planned_measurement" else None,
    )
    with pytest.raises(DomainError) as raised:
        service.inspect_candidate(
            None,
            context,
            basis.scope.product_id,
            CandidateBinding(basis=basis, mappings=(mapping,)),
            at=datetime.now(UTC),
        )
    assert (
        raised.value.reason
        == {
            "old_run": "ORIGINAL_FAILURE_RUN",
            "sample": "FORBIDDEN_SCOPE",
            "item": "FORBIDDEN_SCOPE",
            "planned_measurement": "MEASUREMENT_WITHOUT_EXECUTION",
        }[bad]
    )
