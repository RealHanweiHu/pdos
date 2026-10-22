"""Staged/no-connect explicit profile dispatch, not professional qualification.

Registration and dispatch use the actual bootstrap registry. The raw evidence
ports are explicit substitutes; no actual source or database grant is claimed.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_next import quality_followup_bootstrap as bootstrap
from pdos_next import quality_followup_integration as integration
from pdos_next.domain.quality_followup.service import _runtime
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import Context
from quality_followup_bootstrap.test_pure import work as legacy_work  # noqa: F401
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def profile(scope):
    return {
        **scope.model_dump(mode="json"),
        "entries": [
            {
                "issue_id": str(uuid4()),
                "capa_id": str(uuid4()),
                "action_id": str(uuid4()),
                "executor_id": str(uuid4()),
                "purpose": "Exact synthetic investigation",
                "action_sha256": "a" * 64,
                "classification": "investigation",
                "nature": "synthetic",
                "source": {
                    "id": str(uuid4()),
                    "revision": 1,
                    "kind": "artifact",
                    "position": "line:1;quote_sha256:" + "b" * 64,
                },
                "valid_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        ],
    }


@pytest.fixture(autouse=True)
def forbid_database(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("owned profile tests must not connect")

    monkeypatch.setattr(Engine, "connect", forbidden)


@pytest.fixture
def host(monkeypatch):
    engine = create_engine("postgresql+psycopg://unused/never_connect")

    @event.listens_for(engine, "do_connect")
    def no_connect(*args):
        raise AssertionError("no target DB access permitted")

    s = Session(engine)
    s.begin()
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    actor = uuid4()
    ctx = Context(scope.tenant_id, actor, actor)
    value = SimpleNamespace(
        engine=engine, s=s, scope=scope, ctx=ctx, verifications=[], calls=[], on_assess=None
    )
    monkeypatch.setattr(bootstrap, "verify_test_target", value.verifications.append)

    def assess(actual, supplied_engine, session, context, pid, basis, *args):
        assert supplied_engine is engine and session.get_bind() is engine
        assert (context.tenant_id, pid, basis.scope.project_id) == bootstrap._scope(actual.data)
        assert basis.scope.tenant_id == context.tenant_id and basis.scope.product_id == pid
        value.calls.append((actual, session, context, basis))
        if value.on_assess:
            value.on_assess()
        return SimpleNamespace(actual_configured=actual, evidence_unverified=True)

    monkeypatch.setattr(bootstrap, "_assess", assess)
    yield value
    s.close()
    engine.dispose()


def callback(host):
    return _runtime(host.s).assess_action_completion


def invoke(host, *, scope=None, ctx=None, session=None, product_id=None):
    scope = host.scope if scope is None else scope
    ctx = host.ctx if ctx is None else ctx
    return callback(host)(
        host.s if session is None else session,
        ctx,
        scope.product_id if product_id is None else product_id,
        SimpleNamespace(scope=scope),
        object(),
        object(),
        policy_snapshot={},
        observation=object(),
    )


def assert_error(code, call):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == code


def test_integration_and_bootstrap_use_one_actual_package_namespace():
    assert Path(integration.__file__).parent == Path(bootstrap.__file__).parent
    assert Path(integration.__file__).parent.name == "pdos_next"


def test_old_single_profile_keeps_real_exact_bootstrap_contract(legacy_work):  # noqa: F811
    v = legacy_work
    integration.configure_integration(v.engine, synthetic_completion_profile=v.profile)
    result = _runtime(v.s).assess_action_completion(
        v.s,
        v.ctx,
        v.basis.scope.product_id,
        v.basis,
        v.action,
        v.completion,
        policy_snapshot=v.policy,
        observation=v.observation,
    )
    assert result.classification == "investigation" and result.owner_proofs == ()
    assert result.sources[0].id == v.artifact.id
    assert v.state.checks == 2 and v.state.targets == [v.engine]


def test_none_retains_original_unconfigured_assessment(host):
    integration.configure_integration(host.engine)
    assert callback(host) is None and not host.verifications


@pytest.mark.parametrize("provided", [[], (), {}, "profile", 1, [None], [{}], [object()]])
def test_plural_requires_nonempty_bounded_explicit_valid_list_before_registration(host, provided):
    assert_error(
        "COMPLETION_PROFILE_CONFIG_INVALID",
        lambda: integration.configure_integration(
            host.engine, synthetic_completion_profiles=provided
        ),
    )
    assert not host.verifications
    assert not hasattr(host.engine, "_pdos_quality_completion_profiles")


def test_duplicate_scope_is_rejected_even_in_large_configuration(host):
    assert_error(
        "COMPLETION_PROFILE_CONFLICT",
        lambda: integration.configure_integration(
            host.engine, synthetic_completion_profiles=[profile(host.scope)] * 21
        ),
    )
    assert not host.verifications


def test_single_and_plural_cannot_be_mixed_even_when_same_profile(host):
    p = profile(host.scope)
    assert_error(
        "COMPLETION_PROFILE_CONFIG_INVALID",
        lambda: integration.configure_integration(
            host.engine, synthetic_completion_profile=p, synthetic_completion_profiles=[p]
        ),
    )
    assert not host.verifications


def test_whole_batch_invalid_later_item_cannot_publish_earlier_scope(host):
    good = profile(host.scope)
    bad = profile(host.scope.model_copy(update={"project_id": uuid4()}))
    bad["entries"][0]["source"]["position"] = "not a controlled full line"
    assert_error(
        "COMPLETION_PROFILE_CONFIG_INVALID",
        lambda: integration.configure_integration(
            host.engine, synthetic_completion_profiles=[good, bad]
        ),
    )
    assert not host.verifications and not hasattr(host.engine, "_pdos_quality_completion_profiles")


def test_duplicate_scope_is_ambiguous_even_if_both_values_identical(host):
    p = profile(host.scope)
    assert_error(
        "COMPLETION_PROFILE_CONFLICT",
        lambda: integration.configure_integration(
            host.engine, synthetic_completion_profiles=[p, deepcopy(p)]
        ),
    )
    assert not host.verifications


def test_duplicate_exact_action_issuance_key_cannot_register(host):
    p = profile(host.scope)
    p["entries"].append(deepcopy(p["entries"][0]))
    assert_error(
        "COMPLETION_PROFILE_CONFIG_INVALID",
        lambda: integration.configure_integration(host.engine, synthetic_completion_profiles=[p]),
    )
    assert not host.verifications


@pytest.mark.parametrize("difference", ["tenant_id", "product_id", "project_id"])
def test_profile_selected_only_by_actual_context_product_and_server_basis_scope(host, difference):
    other_scope = host.scope.model_copy(update={difference: uuid4()})
    profiles = [profile(host.scope), profile(other_scope)]
    integration.configure_integration(host.engine, synthetic_completion_profiles=profiles)
    first = invoke(host)
    other_ctx = Context(other_scope.tenant_id, host.ctx.actor_id, host.ctx.actor_id)
    second = invoke(host, scope=other_scope, ctx=other_ctx)
    assert (
        first.actual_configured
        is host.engine._pdos_quality_completion_profiles[
            bootstrap._scope(bootstrap.CompletionProfile.model_validate(profiles[0]))
        ]
    )
    assert (
        second.actual_configured
        is host.engine._pdos_quality_completion_profiles[
            bootstrap._scope(bootstrap.CompletionProfile.model_validate(profiles[1]))
        ]
    )
    assert first.actual_configured is not second.actual_configured
    assert len(host.calls) == 2 and all(v is host.engine for v in host.verifications)


@pytest.mark.parametrize("change", ["source", "purpose", "action", "expiry"])
def test_existing_scope_conflict_rejects_entire_batch_and_preserves_old_profile(host, change):
    old = profile(host.scope)
    integration.configure_integration(host.engine, synthetic_completion_profile=old)
    before = dict(host.engine._pdos_quality_completion_profiles)
    epochs = dict(host.engine._pdos_quality_completion_profile_epochs)
    altered = deepcopy(old)
    if change == "source":
        altered["entries"][0]["source"]["id"] = str(uuid4())
    elif change == "purpose":
        altered["entries"][0]["purpose"] = "different purpose"
    elif change == "action":
        altered["entries"][0]["action_sha256"] = "c" * 64
    else:
        altered["entries"][0]["valid_until"] = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    new = profile(host.scope.model_copy(update={"project_id": uuid4()}))
    count = len(host.verifications)
    assert_error(
        "COMPLETION_PROFILE_CONFLICT",
        lambda: integration.configure_integration(
            host.engine, synthetic_completion_profiles=[new, altered]
        ),
    )
    assert host.engine._pdos_quality_completion_profiles == before
    assert host.engine._pdos_quality_completion_profile_epochs == epochs
    assert len(host.verifications) == count


def test_adding_scope_preserves_actual_old_profile_object_epoch_and_old_callback(host):
    old = profile(host.scope)
    integration.configure_integration(host.engine, synthetic_completion_profile=old)
    old_callback = callback(host)
    key = bootstrap._scope(bootstrap.CompletionProfile.model_validate(old))
    previous = host.engine._pdos_quality_completion_profiles[key]
    epoch = host.engine._pdos_quality_completion_profile_epochs[key]
    other = profile(host.scope.model_copy(update={"project_id": uuid4()}))
    integration.configure_integration(host.engine, synthetic_completion_profiles=[old, other])
    assert host.engine._pdos_quality_completion_profiles[key] is previous
    assert host.engine._pdos_quality_completion_profile_epochs[key] == epoch
    assert invoke(host).actual_configured is previous
    old_result = old_callback(
        host.s,
        host.ctx,
        host.scope.product_id,
        SimpleNamespace(scope=host.scope),
        object(),
        object(),
        policy_snapshot={},
        observation=object(),
    )
    assert old_result.actual_configured is previous


def test_current_plural_whitelist_does_not_automatically_select_unlisted_old_scope(host):
    old = profile(host.scope)
    integration.configure_integration(host.engine, synthetic_completion_profile=old)
    previous = dict(host.engine._pdos_quality_completion_profiles)
    other = profile(host.scope.model_copy(update={"project_id": uuid4()}))
    integration.configure_integration(host.engine, synthetic_completion_profiles=[other])
    assert_error("COMPLETION_PROFILE_SCOPE_MISSING", lambda: invoke(host))
    assert all(host.engine._pdos_quality_completion_profiles[k] is v for k, v in previous.items())
    assert not host.calls


def test_unknown_project_scope_never_falls_back_to_first_profile(host):
    integration.configure_integration(
        host.engine, synthetic_completion_profiles=[profile(host.scope)]
    )
    other = host.scope.model_copy(update={"project_id": uuid4()})
    assert_error("COMPLETION_PROFILE_SCOPE_MISSING", lambda: invoke(host, scope=other))
    assert not host.calls


@pytest.mark.parametrize("change", ["tenant", "product", "actor", "run", "context_dto", "engine"])
def test_actual_session_and_caller_binding_precedes_scope_dispatch(host, change):
    integration.configure_integration(
        host.engine, synthetic_completion_profiles=[profile(host.scope)]
    )
    ctx, scope, session = host.ctx, host.scope, host.s
    if change == "tenant":
        ctx = Context(uuid4(), ctx.actor_id, ctx.actor_id)
    elif change == "product":
        scope = scope.model_copy(update={"product_id": uuid4()})
    elif change == "actor":
        ctx = Context(ctx.tenant_id, uuid4(), ctx.requester_id)
    elif change == "run":
        ctx = Context(ctx.tenant_id, ctx.actor_id, ctx.requester_id, uuid4())
    elif change == "context_dto":
        ctx = SimpleNamespace(**vars(ctx))
    else:
        session = SimpleNamespace(get_bind=lambda: object())
    assert_error(
        "FORBIDDEN_SCOPE",
        lambda: invoke(
            host, scope=scope, ctx=ctx, session=session, product_id=host.scope.product_id
        ),
    )
    assert not host.calls


@pytest.mark.parametrize("change", ["disable", "replace", "epoch"])
def test_selected_actual_profile_revocation_or_epoch_drift_during_io_fails_closed(host, change):
    p = profile(host.scope)
    integration.configure_integration(host.engine, synthetic_completion_profiles=[p])
    key = bootstrap._scope(bootstrap.CompletionProfile.model_validate(p))

    def drift():
        if change == "disable":
            bootstrap.disable_local_profile(host.engine, **host.scope.model_dump())
        elif change == "replace":
            bootstrap.configure_local_profile(host.engine, p)
        else:
            host.engine._pdos_quality_completion_profile_epochs[key] += 1

    host.on_assess = drift
    assert_error("SOURCE_STALE", lambda: invoke(host))


def test_source_or_issuer_owner_refusal_is_not_replaced_by_profile_presence(host, monkeypatch):
    integration.configure_integration(
        host.engine, synthetic_completion_profiles=[profile(host.scope)]
    )

    def refuse(*args):
        raise DomainError("SOURCE_UNAVAILABLE", "explicit actual source refusal")

    monkeypatch.setattr(bootstrap, "_assess", refuse)
    assert_error("SOURCE_UNAVAILABLE", lambda: invoke(host))


def test_multi_profile_does_not_enable_any_professional_synthetic_switch(host):
    integration.configure_integration(
        host.engine, synthetic_completion_profiles=[profile(host.scope)]
    )
    assert not hasattr(host.engine, "_pdos_professional_synthetic")
    assert not hasattr(host.engine, "_pdos_professional_issuers")


def test_plural_more_than_twenty_distinct_scopes_dispatches_complete_set(host):
    scopes = [host.scope] + [
        host.scope.model_copy(update={"project_id": uuid4()}) for _ in range(20)
    ]
    integration.configure_integration(
        host.engine, synthetic_completion_profiles=[profile(scope) for scope in scopes]
    )
    assert len(host.engine._pdos_quality_completion_profiles) == 21
    assert bootstrap._scope(invoke(host, scope=scopes[-1]).actual_configured.data) == (
        scopes[-1].tenant_id,
        scopes[-1].product_id,
        scopes[-1].project_id,
    )


def test_plural_dispatches_existing_real_bootstrap_source_checks_without_positive_fulfillment(
    legacy_work,  # noqa: F811 - imported pytest fixture
):
    v = legacy_work
    other = deepcopy(v.profile)
    other["project_id"] = str(uuid4())
    integration.configure_integration(v.engine, synthetic_completion_profiles=[v.profile, other])
    result = _runtime(v.s).assess_action_completion(
        v.s,
        v.ctx,
        v.basis.scope.product_id,
        v.basis,
        v.action,
        v.completion,
        policy_snapshot=v.policy,
        observation=v.observation,
    )
    assert result.classification == "investigation" and result.owner_proofs == ()
    assert result.profile_epoch == 1 and v.state.checks == 2


def test_malformed_existing_registry_binding_is_rejected_before_new_scope_registration(host):
    old = profile(host.scope)
    integration.configure_integration(host.engine, synthetic_completion_profile=old)
    key = bootstrap._scope(bootstrap.CompletionProfile.model_validate(old))
    host.engine._pdos_quality_completion_profiles[key] = None
    other = profile(host.scope.model_copy(update={"project_id": uuid4()}))
    before = dict(host.engine._pdos_quality_completion_profiles)
    count = len(host.verifications)
    assert_error(
        "COMPLETION_PROFILE_CONFLICT",
        lambda: integration.configure_integration(
            host.engine, synthetic_completion_profiles=[other, old]
        ),
    )
    assert host.engine._pdos_quality_completion_profiles == before
    assert len(host.verifications) == count


def test_second_new_scope_real_target_failure_restores_old_profiles_epochs_and_runtime(
    host, monkeypatch
):
    old = profile(host.scope)
    integration.configure_integration(host.engine, synthetic_completion_profile=old)
    registry = host.engine._pdos_quality_completion_profiles
    epochs = host.engine._pdos_quality_completion_profile_epochs
    original_profiles, original_epochs = dict(registry), dict(epochs)
    old_callback = callback(host)
    runtime = host.engine._pdos_quality_followup
    views = host.engine._pdos_quality_followup_views
    link_proof = host.engine._pdos_capa_link_consumed_proof
    additions = [profile(host.scope.model_copy(update={"project_id": uuid4()})) for _ in range(2)]
    additions_keys = [
        bootstrap._scope(bootstrap.CompletionProfile.model_validate(value)) for value in additions
    ]
    verified = []
    failure = RuntimeError("explicit second new scope target refusal")

    def verify(engine):
        verified.append(engine)
        if len(verified) == 3:
            # First real registrar completed and published its copied maps.
            assert additions_keys[0] in engine._pdos_quality_completion_profiles
            raise failure

    monkeypatch.setattr(bootstrap, "verify_test_target", verify)
    with pytest.raises(RuntimeError) as error:
        integration.configure_integration(
            host.engine, synthetic_completion_profiles=[old, *additions]
        )
    assert error.value is failure and verified == [host.engine] * 3
    assert host.engine._pdos_quality_completion_profiles is registry
    assert host.engine._pdos_quality_completion_profile_epochs is epochs
    assert registry == original_profiles and epochs == original_epochs
    assert all(registry[key] is value for key, value in original_profiles.items())
    assert all(key not in registry and key not in epochs for key in additions_keys)
    assert host.engine._pdos_quality_followup is runtime
    assert host.engine._pdos_quality_followup_views is views
    assert host.engine._pdos_capa_link_consumed_proof is link_proof
    assert callback(host) is old_callback
    assert invoke(host).actual_configured is next(iter(original_profiles.values()))


@pytest.mark.parametrize("present", [(False, False), (True, False), (False, True), (True, True)])
def test_second_scope_target_failure_restores_exact_attribute_presence(host, monkeypatch, present):
    names = (
        "_pdos_quality_completion_profiles",
        "_pdos_quality_completion_profile_epochs",
    )
    originals = [{}, {}]
    for name, is_present, original in zip(names, present, originals, strict=True):
        if is_present:
            setattr(host.engine, name, original)
    scopes = [host.scope, host.scope.model_copy(update={"project_id": uuid4()})]
    first_key = bootstrap._scope(bootstrap.CompletionProfile.model_validate(profile(scopes[0])))
    verified = []

    def verify(engine):
        verified.append(engine)
        if len(verified) == 3:
            assert first_key in engine._pdos_quality_completion_profiles
            raise DomainError("SOURCE_UNAVAILABLE", "second scope actual target failure", 503)

    monkeypatch.setattr(bootstrap, "verify_test_target", verify)
    assert_error(
        "SOURCE_UNAVAILABLE",
        lambda: integration.configure_integration(
            host.engine, synthetic_completion_profiles=[profile(scope) for scope in scopes]
        ),
    )
    assert verified == [host.engine] * 3
    for name, is_present, original in zip(names, present, originals, strict=True):
        assert hasattr(host.engine, name) is is_present
        if is_present:
            assert getattr(host.engine, name) is original and original == {}
    assert not hasattr(host.engine, "_pdos_quality_followup")
    assert not hasattr(host.engine, "_pdos_quality_followup_views")
    assert not hasattr(host.engine, "_pdos_capa_link_consumed_proof")


@pytest.mark.parametrize("failure_kind", ["exception", "invalid_registered_result"])
def test_post_publication_registration_failure_rolls_back_both_maps(
    host, monkeypatch, failure_kind
):
    old = profile(host.scope)
    integration.configure_integration(host.engine, synthetic_completion_profile=old)
    registry = host.engine._pdos_quality_completion_profiles
    epochs = host.engine._pdos_quality_completion_profile_epochs
    runtime = host.engine._pdos_quality_followup
    registered = []
    actual_configure = bootstrap.configure_local_profile
    additions = [profile(host.scope.model_copy(update={"project_id": uuid4()})) for _ in range(2)]
    failure = RuntimeError("explicit registrar failure after publication")

    def configure(engine, value):
        result = actual_configure(engine, value)
        registered.append(bootstrap._scope(value))
        if len(registered) == 2:
            if failure_kind == "exception":
                raise failure
            engine._pdos_quality_completion_profiles[registered[-1]] = None
        return result

    monkeypatch.setattr(bootstrap, "configure_local_profile", configure)
    if failure_kind == "exception":
        with pytest.raises(RuntimeError) as error:
            integration.configure_integration(
                host.engine, synthetic_completion_profiles=[old, *additions]
            )
        assert error.value is failure
    else:
        assert_error(
            "COMPLETION_PROFILE_CONFLICT",
            lambda: integration.configure_integration(
                host.engine, synthetic_completion_profiles=[old, *additions]
            ),
        )
    assert len(registered) == 2
    assert host.engine._pdos_quality_completion_profiles is registry
    assert host.engine._pdos_quality_completion_profile_epochs is epochs
    assert host.engine._pdos_quality_followup is runtime
    assert all(key not in registry and key not in epochs for key in registered)
