"""Bootstrap bounds and source/runtime drift with explicit fake native provenance."""

import json
from copy import deepcopy
from datetime import timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from quality_followup.test_pure import completion, issue, line
from quality_issues.helpers import NOW, uid

from pdos_next import quality_followup_bootstrap as bootstrap
from pdos_next.domain.quality_followup import service
from pdos_next.domain.quality_followup.ports import Runtime
from pdos_next.domain.quality_followup.schemas import CompletionFact
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest


def code(expected, callback):
    with pytest.raises(DomainError) as error:
        callback()
    assert error.value.reason == expected


@pytest.fixture
def work(monkeypatch):
    fixed, completed = issue(), completion()
    ctx = Context(fixed.scope.tenant_id, uid("executor"), uid("executor"))
    engine = SimpleNamespace()
    session = SimpleNamespace(get_bind=lambda: engine)
    action = fixed.capa.actions[0]
    action_sha = digest(action.model_dump(mode="json", exclude={"completion"}))
    basis = SimpleNamespace(
        scope=fixed.scope,
        issue_id=fixed.id,
        capa_id=fixed.capa.id,
        purpose="investigation",
        nature="synthetic",
        basis_sha256="1" * 64,
        actions=(SimpleNamespace(action_id=action.id, action_sha256=action_sha),),
    )
    observed = CompletionFact.model_validate(line(completed))
    publication = {
        **fixed.scope.model_dump(mode="json"),
        "issue_id": str(fixed.id),
        "capa_id": str(fixed.capa.id),
        "action_id": str(action.id),
        "executor_id": str(ctx.requester_id),
        "purpose": basis.purpose,
        "action_sha256": action_sha,
        "classification": "investigation",
        "nature": "synthetic",
        "valid_until": (NOW + timedelta(minutes=10)).isoformat(),
    }
    artifact = SimpleNamespace(
        id=uid("classification"),
        revision=1,
        content=json.dumps(publication),
        status="active",
        owner_id=ctx.requester_id,
        visibility="private",
    )
    artifact.content_hash = digest(artifact.content)
    source = {
        "kind": "artifact",
        "id": str(artifact.id),
        "revision": 1,
        "position": f"line:1;quote_sha256:{sha256(artifact.content.encode()).hexdigest()}",
    }
    profile = {
        **fixed.scope.model_dump(mode="json"),
        "entries": [
            {k: v for k, v in publication.items() if k not in type(fixed.scope).model_fields}
        ],
    }
    profile["entries"][0]["source"] = source
    state = SimpleNamespace(
        at=NOW,
        targets=[],
        checks=0,
        on_read=None,
        source_kind="registered_native_text",
        receipt_id=uid("actual-synthetic-registration"),
    )
    monkeypatch.setattr(bootstrap, "now", lambda: state.at)
    monkeypatch.setattr(service, "now", lambda: state.at)
    monkeypatch.setattr(
        bootstrap, "verify_test_target", lambda target: state.targets.append(target)
    )

    def check_source(_s, _ctx, product, ref):
        state.checks += 1
        if artifact.status != "active":
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic withdrawal")
        if ref.position != f"line:1;quote_sha256:{sha256(artifact.content.encode()).hexdigest()}":
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "Synthetic whole-line hash mismatch")
        if artifact.content_hash != digest(artifact.content) or state.receipt_id is None:
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic native provenance missing")
        if product != fixed.scope.product_id or _ctx.requester_id != ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "Synthetic current ACL denied", 403)
        raw = {
            "id": str(artifact.id),
            "revision": artifact.revision,
            "hash": artifact.content_hash,
            "status": artifact.status,
            "owner_id": str(artifact.owner_id),
            "visibility": artifact.visibility,
            "source_kind": state.source_kind,
            "registration": {
                "receipt_id": str(state.receipt_id),
                "actor_id": str(ctx.actor_id),
                "requester_id": str(ctx.requester_id),
                "run_id": None,
            },
        }
        return [{"artifact_id": str(artifact.id), "expected_revision": 1}], [raw], True

    def source_for(*_args):
        if state.on_read:
            state.on_read()
        return artifact

    monkeypatch.setattr(bootstrap, "check_source", check_source)
    monkeypatch.setattr(bootstrap, "source_for", source_for)
    return SimpleNamespace(
        issue=fixed,
        ctx=ctx,
        engine=engine,
        s=session,
        action=action,
        completion=completed,
        basis=basis,
        observation=observed,
        publication=publication,
        artifact=artifact,
        profile=profile,
        state=state,
        policy={
            "nature": "synthetic",
            "id": "policy-id",
            "revision": 1,
            "valid_until": None,
            "source_basis": [
                {
                    "id": "policy-id",
                    "revision": 1,
                    "state": "active",
                    "valid_from": (NOW - timedelta(hours=1)).isoformat(),
                    "valid_until": (NOW + timedelta(hours=1)).isoformat(),
                }
            ],
        },
    )


def callback(work):
    return bootstrap.configure_local_profile(work.engine, work.profile)


def assess(work, verifier):
    return verifier(
        work.s,
        work.ctx,
        work.basis.scope.product_id,
        work.basis,
        work.action,
        work.completion,
        policy_snapshot=work.policy,
        observation=work.observation,
    )


def publication(work, raw):
    work.artifact.content = raw if isinstance(raw, str) else json.dumps(raw)
    work.artifact.content_hash = digest(work.artifact.content)
    work.profile["entries"][0]["source"]["position"] = (
        f"line:1;quote_sha256:{sha256(work.artifact.content.encode()).hexdigest()}"
    )


def test_configuration_verifies_target_itself_and_does_not_install_runtime_or_grants(work):
    verifier = callback(work)
    assert callable(verifier) and work.state.targets == [work.engine]
    assert not hasattr(work.engine, "_pdos_quality_followup")
    assert not hasattr(work.engine, "_pdos_professional_issuers")


def test_unverified_target_cannot_install_any_profile(work, monkeypatch):
    def deny(_engine):
        raise RuntimeError("Actual target was not verified")

    monkeypatch.setattr(bootstrap, "verify_test_target", deny)
    with pytest.raises(RuntimeError, match="not verified"):
        callback(work)
    assert not hasattr(work.engine, "_pdos_quality_completion_profiles")


@pytest.mark.parametrize("change", ["extra", "formal", "real", "domain", "duplicate"])
def test_host_profile_is_closed_finite_synthetic_and_investigation_only(work, change):
    entry = work.profile["entries"][0]
    if change == "extra":
        entry["approved"] = True
    elif change == "formal":
        entry["classification"] = "formal_change"
    elif change == "real":
        entry["nature"] = "real"
    elif change == "domain":
        entry["source"]["kind"] = "domain"
    else:
        work.profile["entries"].append(deepcopy(entry))
    with pytest.raises(ValidationError):
        callback(work)
    assert work.state.targets == []


def test_exact_source_publication_and_real_observation_produce_full_typed_host_assessment(work):
    value = assess(work, callback(work))
    assert isinstance(value, bootstrap.SyntheticCompletionAssessment)
    assert value.classification == "investigation" and value.nature == "synthetic"
    assert value.allowed is True and value.current is True and value.owner_proofs == ()
    assert value.valid_until is None
    assert value.time_constraints == (
        bootstrap.CompletionProfile.model_validate(work.profile).entries[0].valid_until,
    )
    assert value.classification_source_basis[0].registration.receipt_id == work.state.receipt_id
    assert value.proof_sha256 == digest(value.model_dump(mode="json", exclude={"proof_sha256"}))
    assert value.profile_sha256 == digest(
        bootstrap.CompletionProfile.model_validate(work.profile).model_dump(mode="json")
    )
    assert work.state.checks == 2


def test_frozen_a_assessment_keeps_full_subclass_fields_and_hash(work):
    verifier = callback(work)
    runtime = Runtime(lambda *_a: None, lambda *_a: uuid4(), verifier)
    value = service._assessment(
        work.s,
        work.ctx,
        work.basis.scope.product_id,
        runtime,
        work.basis,
        work.policy,
        work.issue,
        work.completion,
        work.observation,
        write=True,
    )
    assert isinstance(value, bootstrap.SyntheticCompletionAssessment)
    assert "classification_source_basis" in value.model_dump(mode="json")
    assert value.proof_sha256 == digest(value.model_dump(mode="json", exclude={"proof_sha256"}))


@pytest.mark.parametrize(
    "change", ["extra", "duplicate", "ordinary_event", "wrong_action", "naive", "numeric", "nan"]
)
def test_classification_line_must_match_exact_closed_bindings_not_ordinary_completion(work, change):
    raw = deepcopy(work.publication)
    if change == "extra":
        raw["grant"] = True
    elif change == "duplicate":
        raw = json.dumps(raw)[:-1] + ',"classification":"investigation"}'
    elif change == "ordinary_event":
        raw = line(work.completion)
    elif change == "wrong_action":
        raw["action_id"] = str(uuid4())
    elif change == "naive":
        raw["valid_until"] = "2026-10-03T11:00:00"
    elif change == "numeric":
        raw["valid_until"] = 1234567890
    else:
        raw = json.dumps(raw).replace('"investigation"', "NaN", 1)
    publication(work, raw)
    code("MISSING_REQUIRED_EVIDENCE", lambda: assess(work, callback(work)))


@pytest.mark.parametrize("change", ["hash", "withdrawal", "receipt", "private_actor", "original"])
def test_current_source_hash_acl_native_provenance_and_original_boundary_remain_hard(work, change):
    verifier = callback(work)
    expected = "SOURCE_UNAVAILABLE"
    if change == "hash":
        work.artifact.content += " changed"
        expected = "MISSING_REQUIRED_EVIDENCE"
    elif change == "withdrawal":
        work.artifact.status = "withdrawn"
    elif change == "receipt":
        work.state.receipt_id = None
    elif change == "private_actor":
        other = uid("other-caller")
        work.ctx = Context(work.ctx.tenant_id, other, other)
        expected = "INTEGRATION_REQUIRED"
    else:
        work.state.source_kind = "uploaded_original"
        expected = "INTEGRATION_REQUIRED"
    code(expected, lambda: assess(work, verifier))


@pytest.mark.parametrize(
    "change", ["purpose", "project", "tenant", "real_basis", "action", "observation"]
)
def test_classification_scope_action_nature_and_real_event_are_bound(work, change):
    verifier = callback(work)
    expected = "INTEGRATION_REQUIRED"
    if change == "purpose":
        work.basis.purpose = "another-purpose"
    elif change == "project":
        work.basis.scope = work.basis.scope.model_copy(update={"project_id": uuid4()})
        expected = "FORBIDDEN_SCOPE"
    elif change == "tenant":
        work.ctx = Context(uuid4(), work.ctx.actor_id, work.ctx.requester_id)
        expected = "FORBIDDEN_SCOPE"
    elif change == "real_basis":
        work.basis.nature = "real"
    elif change == "action":
        work.basis.actions[0].action_sha256 = "0" * 64
        expected = "ACTION_COMPLETION_UNVERIFIED"
    else:
        work.observation = None
        expected = "ACTION_COMPLETION_UNVERIFIED"
    code(expected, lambda: assess(work, verifier))


def test_deadline_is_fixed_not_renewed_by_now_and_offset_source_is_same_instant(work):
    raw = deepcopy(work.publication)
    raw["valid_until"] = (
        bootstrap.CompletionProfile.model_validate(work.profile)
        .entries[0]
        .valid_until.astimezone(timezone(timedelta(hours=-7)))
        .isoformat()
    )
    publication(work, raw)
    verifier = callback(work)
    first = assess(work, verifier)
    work.state.at += timedelta(minutes=1)
    second = assess(work, verifier)
    assert second == first and second.valid_until == first.valid_until
    work.state.at = min(first.time_constraints)
    code("ACTION_COMPLETION_UNVERIFIED", lambda: assess(work, verifier))


@pytest.mark.parametrize("change", ["disable", "replace", "source_basis", "expiry"])
def test_io_window_runtime_provenance_and_deadline_drift_block_positive_result(work, change):
    verifier = callback(work)
    hit = False

    def during_read():
        nonlocal hit
        if hit:
            return
        hit = True
        if change == "disable":
            bootstrap.disable_local_profile(work.engine, **work.basis.scope.model_dump())
        elif change == "replace":
            callback(work)
        elif change == "source_basis":
            work.state.receipt_id = uuid4()
        else:
            work.state.at = NOW + timedelta(minutes=10)

    work.state.on_read = during_read
    code(
        "ACTION_COMPLETION_UNVERIFIED" if change == "expiry" else "SOURCE_STALE",
        lambda: assess(work, verifier),
    )
