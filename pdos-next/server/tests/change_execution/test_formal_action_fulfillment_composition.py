"""Actual formal action-owner composition with explicit no-connect IO substitutes.

The saved classification uses the real producer DTOs. Both fulfillment readers,
their proof checks, refresh and source/UOW guards execute; lower approval,
implementation and original-byte IO remain the substitutes in ``actual``.
These pure checks grant no qualification or persisted/live acceptance.
"""

# ruff: noqa: F811 - imported fixtures register the no-connect source/UOW environment
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next import capa_applicability_owner as owner
from pdos_next.domain.quality_followup.schemas import CompletionAssessment, OwnerImplementationProof
from pdos_next.errors import DomainError

from .test_action_fulfillment_owner import (  # noqa: F401 - explicit shared fixture registration
    action_work,
    actual,
    no_connection,
    work,
)

MISSING_CLASSIFICATION = "CURRENT_ACTION_CLASSIFICATION_OWNER_REQUIRED"


@pytest.fixture
def formal_action(actual):
    v = actual.v
    completion = v.action.completion
    # This is the exact saved shape emitted by FormalChangeCompletionOwner, not
    # an ActualActionAttestation or a substitute for the current adapter read.
    saved = CompletionAssessment(
        scope=v.anchor.origin.scope,
        issue_id=v.anchor.origin.issue_id,
        capa_id=v.anchor.origin.issue.capa.id,
        action_id=v.binding.action_id,
        executor_id=v.binding.executor_id,
        purpose=v.anchor.origin.purpose,
        basis_sha256=actual.basis.basis_sha256,
        action_sha256=v.binding.action_sha256,
        completion_sha256=v.binding.completion_sha256,
        event_source=completion.at.source.model_dump(mode="json"),
        policy_basis_sha256="d" * 64,
        allowed=True,
        current=True,
        classification="formal_change",
        nature=v.anchor.origin.nature,
        sources=(actual.source.model_dump(mode="json"),),
        owner_proofs=(
            OwnerImplementationProof(
                kind="approved_change_implementation",
                id=actual.row.id,
                revision=actual.row.revision,
                receipt_id=uuid4(),
                sha256=owner.digest(actual.executed.material),
                status="implemented",
                current=True,
            ),
        ),
        required_source_read_set=v.anchor.origin.required_source_read_set,
        valid_until=actual.executed.valid_until,
        proof_sha256="0" * 64,
    )
    saved = saved.model_copy(
        update={
            "proof_sha256": owner.digest(saved.model_dump(mode="json", exclude={"proof_sha256"}))
        }
    )
    v.row["source_basis"]["completion_assessments"] = [saved.model_dump(mode="json")]
    actual.reader = owner.ActualActionFulfillmentOwner(implementation_owner=actual.adapter)
    actual.saved_assessment = saved
    return actual


def read(actual, reader=None):
    v = actual.v
    return (reader or actual.reader).read(
        v.work.s,
        v.work.ctx,
        v.work.pid,
        actual.selection,
        anchor=v.anchor,
        candidate=None,
        rule=v.rule,
        observations=(),
    )


def test_formal_completion_is_rechecked_by_composed_owner_before_classification_is_current(
    formal_action, monkeypatch
):
    a = formal_action
    original, checked = owner.ActualActionFulfillmentOwner._check, []

    def check(*args):
        original(*args)
        checked.append(args[-1])

    monkeypatch.setattr(owner.ActualActionFulfillmentOwner, "_check", staticmethod(check))
    result = read(a)
    assert result.value.classification == "formal_change"
    assert result.value.conclusion == "applicable"
    assert result.value.owner_refs == (a.source,)
    assert result.owner_material["saved_classification"] == a.saved_assessment.model_dump(
        mode="json"
    )
    assert result.owner_material["fulfillment"]["kind"] == "approved_change_action_fulfillment_v1"
    assert MISSING_CLASSIFICATION not in result.missing
    assert MISSING_CLASSIFICATION not in result.value.owner_material["missing"]
    late = a.reader.refresh(
        a.v.work.s,
        a.v.work.ctx,
        a.v.work.pid,
        a.selection,
        result,
        anchor=a.v.anchor,
        candidate=None,
        rule=a.v.rule,
        observations=(),
    )
    assert late.value == result.value and late.owner_material == result.owner_material
    assert len(checked) == 4 and all(type(v) is owner.ActualActionAttestation for v in checked)
    assert set(a.reads) == {"implementation", "intent", "implementation_refresh", "intent_refresh"}
    assert not a.v.work.s.new and not a.v.work.s.dirty and not a.v.work.s.deleted


def test_saved_formal_completion_without_installed_adapter_cannot_prove_fulfillment(formal_action):
    with pytest.raises(DomainError) as error:
        read(formal_action, owner.ActualActionFulfillmentOwner())
    assert error.value.reason == "ACTION_FULFILLMENT_OWNER_REQUIRED"
    assert not formal_action.reads


def test_unknown_fulfillment_keeps_current_formal_classification_missing(formal_action):
    a = formal_action
    a.selection = a.selection.model_copy(update={"conclusion": "unknown"})
    result = read(a)
    assert result.value.classification == result.value.conclusion == "unknown"
    assert set(result.missing) == {MISSING_CLASSIFICATION, "ACTION_FULFILLMENT_UNDETERMINED"}
    assert not a.reads


def test_saved_completion_assessment_cannot_impersonate_live_fulfillment_attestation(formal_action):
    a = formal_action
    a.reader.implementation_owner = SimpleNamespace(
        read=lambda *args, **kwargs: a.saved_assessment,
        refresh=lambda *args, **kwargs: pytest.fail("Invalid proof must fail its first check"),
    )
    with pytest.raises(DomainError) as error:
        read(a)
    assert error.value.reason == "ACTION_FULFILLMENT_OWNER_REQUIRED"


@pytest.mark.parametrize("drift", ["caller", "material"])
def test_late_proof_scope_or_material_drift_cannot_clear_classification(
    formal_action, monkeypatch, drift
):
    a = formal_action
    original = a.adapter.refresh

    def refresh(*args, **kwargs):
        proof = original(*args, **kwargs)
        if drift == "caller":
            ctx = a.v.work.ctx
            return replace(proof, caller=owner.Context(ctx.tenant_id, uuid4(), uuid4()))
        return replace(proof, owner_material={**proof.owner_material, "changed": True})

    monkeypatch.setattr(a.adapter, "refresh", refresh)
    with pytest.raises(DomainError) as error:
        read(a)
    assert error.value.reason == (
        "ACTION_FULFILLMENT_OWNER_REQUIRED" if drift == "caller" else "SOURCE_STALE"
    )


def test_current_implementation_source_drift_rejects_composed_formal_proof(
    formal_action, monkeypatch
):
    a, calls = formal_action, []

    def source_guard(*args, **kwargs):
        calls.append(True)
        return {"source": "before" if len(calls) == 1 else "after"}

    from pdos_next import change_action_fulfillment_owner as adapter

    monkeypatch.setattr(adapter.controlled, "_source_guard", source_guard)
    with pytest.raises(DomainError) as error:
        read(a)
    assert error.value.reason == "SOURCE_STALE"
    assert len(calls) == 2
