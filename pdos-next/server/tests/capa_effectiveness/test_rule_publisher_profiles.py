"""Actual dispatcher/registry guards; delegated owner evidence is an explicit substitute.

No connection or Rule publication occurs. Dispatch success never proves actual
anchor/bytes/current professional gates, native evidence or saved business facts.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_next import capa_rule_publisher as rules
from pdos_next.capa_fact_owner import ActualFactOwner
from pdos_next.errors import DomainError
from pdos_next.service import Context


def profile(**changes):
    return {
        "tenant_id": str(uuid4()),
        "product_id": str(uuid4()),
        "project_id": str(uuid4()),
        "issuer_key": "explicit-rule-second",
        "issuer_version": "v1",
        **changes,
    }


def binding(issuer, engine):
    actor = uuid4()
    return SimpleNamespace(get_bind=lambda: engine), Context(issuer.tenant_id, actor, actor)


@pytest.fixture
def marker(monkeypatch):
    calls = []
    monkeypatch.setattr(rules, "verify_test_target", lambda engine: calls.append(engine))
    return calls


def rejects(code, callback):
    with pytest.raises(DomainError) as error:
        callback()
    assert error.value.reason == code


def test_legacy_return_type_and_marker_guard_are_preserved(marker):
    engine = SimpleNamespace()
    publisher = rules.configure_local_profile(engine, profile())
    assert type(publisher) is rules.RegisteredSyntheticRulePublisher
    assert marker == [engine]
    s, ctx = binding(publisher.issuer, engine)
    rule = SimpleNamespace(
        scope=SimpleNamespace(project_id=publisher.issuer.project_id),
        issuer=publisher._current_issuer(
            s, ctx, publisher.issuer.product_id, publisher.issuer.project_id
        ),
        nature="synthetic",
    )
    assert publisher.current(s, ctx, publisher.issuer.product_id, rule) == rule.issuer


def test_plural_reuses_identical_old_issuer_without_changing_fact_epoch(marker):
    engine = SimpleNamespace()
    old_profile = profile(issuer_key="old-rule-root")
    old = rules.configure_local_profile(engine, old_profile)
    dispatcher = rules.configure_local_profiles(engine, [old_profile, profile()])
    assert dispatcher._publishers[0].issuer is old.issuer
    assert old.issuer.epoch == 1
    assert len(engine._pdos_capa_rule_issuers) == 2
    assert marker == [engine, engine]


@pytest.mark.parametrize("profiles", [[], {}, "profile", (profile(),), [profile()] * 21])
def test_profile_list_is_bounded_before_marker_or_mutation(marker, profiles):
    engine = SimpleNamespace()
    with pytest.raises(ValueError):
        rules.configure_local_profiles(engine, profiles)
    assert marker == [] and vars(engine) == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": True},
        {"product_id": 1},
        {"project_id": None},
        {"issuer_key": ""},
        {"issuer_key": "x" * 101},
        {"issuer_version": " x "},
        {"profile_id": "caller-selection"},
    ],
)
def test_partial_bad_batch_never_publishes_a_registry(marker, changes):
    engine = SimpleNamespace()
    with pytest.raises((ValueError, DomainError)):
        rules.configure_local_profiles(
            engine, [profile(issuer_key="valid-first"), profile(**changes)]
        )
    assert marker == [] and vars(engine) == {}


@pytest.mark.parametrize("duplicate", ["key", "product"])
def test_duplicate_key_or_same_product_projects_are_rejected(marker, duplicate):
    engine = SimpleNamespace()
    first = profile()
    second = (
        profile(issuer_key=first["issuer_key"])
        if duplicate == "key"
        else {
            **first,
            "issuer_key": "alternate-project",
            "project_id": str(uuid4()),
        }
    )
    with pytest.raises(ValueError):
        rules.configure_local_profiles(engine, [first, second])
    assert vars(engine) == {} and marker == []


@pytest.mark.parametrize("field", ["tenant_id", "product_id", "project_id"])
def test_existing_key_conflict_is_atomic_and_cannot_expand_private_scope(marker, field):
    engine = SimpleNamespace()
    value = profile()
    old = rules.configure_local_profile(engine, value)
    registry, epochs = engine._pdos_capa_rule_issuers, engine._pdos_capa_rule_issuer_epochs
    with pytest.raises(ValueError):
        rules.configure_local_profiles(
            engine, [profile(issuer_key="first-new"), {**value, field: str(uuid4())}]
        )
    assert engine._pdos_capa_rule_issuers is registry
    assert engine._pdos_capa_rule_issuer_epochs is epochs
    assert engine._pdos_capa_rule_issuers[old.issuer.key] is old.issuer
    assert len(marker) == 1


def test_marker_failure_leaves_all_registries_and_dispatcher_untouched(monkeypatch):
    engine = SimpleNamespace()

    def reject(_):
        raise RuntimeError("Unverified isolated target")

    monkeypatch.setattr(rules, "verify_test_target", reject)
    with pytest.raises(RuntimeError):
        rules.configure_local_profiles(engine, [profile()])
    assert vars(engine) == {}


def test_context_drives_exact_dispatch_and_no_caller_profile_selection(marker, monkeypatch):
    engine = SimpleNamespace()
    dispatcher = rules.configure_local_profiles(engine, [profile(issuer_key="first"), profile()])
    seen = []

    def owner_read(self, s, ctx, pid, payload):
        assert self._current_issuer(s, ctx, pid, self.issuer.project_id).nature == "synthetic"
        seen.append((self.issuer, ctx, pid, payload))
        return SimpleNamespace(valid_until=datetime.now(UTC) + timedelta(minutes=1))

    monkeypatch.setattr(rules.RegisteredSyntheticRulePublisher, "read", owner_read)
    for publisher in dispatcher._publishers:
        s, ctx = binding(publisher.issuer, engine)
        payload = SimpleNamespace(profile_id="cannot-select-other-profile")
        dispatcher.read(s, ctx, publisher.issuer.product_id, payload)
        assert seen[-1] == (publisher.issuer, ctx, publisher.issuer.product_id, payload)
    s, ctx = binding(dispatcher._publishers[0].issuer, engine)
    rejects("FACT_RULE_PROFILE_SCOPE_UNAVAILABLE", lambda: dispatcher.read(s, ctx, uuid4(), None))
    wrong_tenant = Context(uuid4(), ctx.actor_id, ctx.requester_id)
    rejects(
        "FACT_RULE_PROFILE_SCOPE_UNAVAILABLE",
        lambda: dispatcher.read(s, wrong_tenant, dispatcher._publishers[0].issuer.product_id, None),
    )
    assert len(seen) == 2


def test_rule_project_must_match_the_selected_actual_issuer(marker):
    engine = SimpleNamespace()
    dispatcher = rules.configure_local_profiles(engine, [profile()])
    issuer = dispatcher._publishers[0].issuer
    s, ctx = binding(issuer, engine)
    rule = SimpleNamespace(scope=SimpleNamespace(project_id=uuid4()))
    rejects("FORBIDDEN_SCOPE", lambda: dispatcher.current(s, ctx, issuer.product_id, rule))


def test_unbound_engine_and_ai_context_cannot_use_the_dispatcher(marker):
    engine = SimpleNamespace()
    dispatcher = rules.configure_local_profiles(engine, [profile()])
    issuer = dispatcher._publishers[0].issuer
    s, ctx = binding(issuer, SimpleNamespace())
    rejects("FACT_RULE_PROFILE_CHANGED", lambda: dispatcher.read(s, ctx, issuer.product_id, None))
    s, ctx = binding(issuer, engine)
    ai = Context(ctx.tenant_id, uuid4(), ctx.requester_id, uuid4())
    rejects("FORBIDDEN_SCOPE", lambda: dispatcher.read(s, ai, issuer.product_id, None))


def test_runtime_stamp_changes_for_any_issuer_rotation_and_configuration_aba(marker):
    engine = SimpleNamespace()
    first, second = profile(issuer_key="first"), profile()
    dispatcher = rules.configure_local_profiles(engine, [first, second])
    s, ctx = binding(dispatcher._publishers[0].issuer, engine)
    owner = ActualFactOwner(publisher=dispatcher)
    before = owner.runtime_stamp(s)
    rules.configure_local_profile(engine, {**second, "issuer_version": "v2"})
    assert owner.runtime_stamp(s) != before
    second_version = dispatcher.epoch
    rules.configure_local_profile(engine, second)
    assert dispatcher.epoch != second_version
    assert engine._pdos_capa_rule_issuers[second["issuer_key"]].epoch == 3
    replacement = rules.configure_local_profiles(engine, [first, second])
    assert replacement.epoch != dispatcher.epoch
    rejects(
        "FACT_RULE_PROFILE_CHANGED",
        lambda: dispatcher.read(s, ctx, dispatcher._publishers[0].issuer.product_id, None),
    )


def test_removed_then_reconfigured_issuer_never_reuses_old_epoch(marker):
    engine = SimpleNamespace()
    value = profile()
    old = rules.configure_local_profile(engine, value)
    engine._pdos_capa_rule_issuers = {}
    new = rules.configure_local_profile(engine, value)
    assert new.issuer.epoch == old.issuer.epoch + 1
    s, ctx = binding(new.issuer, engine)
    rejects(
        "FACT_ISSUER_REVOKED",
        lambda: old._current_issuer(s, ctx, new.issuer.product_id, new.issuer.project_id),
    )


def test_delegated_owner_io_reconfiguration_invalidates_phase(marker, monkeypatch):
    engine = SimpleNamespace()
    value = profile()
    dispatcher = rules.configure_local_profiles(engine, [value])
    issuer = dispatcher._publishers[0].issuer
    s, ctx = binding(issuer, engine)

    def changed(*_):
        rules.configure_local_profiles(engine, [value])
        return SimpleNamespace(valid_until=datetime.now(UTC) + timedelta(minutes=1))

    monkeypatch.setattr(dispatcher._publishers[0], "read", changed)
    rejects("FACT_RULE_PROFILE_CHANGED", lambda: dispatcher.read(s, ctx, issuer.product_id, None))


def test_fresh_clock_after_delegated_io_rejects_expired_material(marker, monkeypatch):
    engine = SimpleNamespace()
    dispatcher = rules.configure_local_profiles(engine, [profile()])
    issuer = dispatcher._publishers[0].issuer
    s, ctx = binding(issuer, engine)
    cutoff = datetime(2026, 10, 3, 12, tzinfo=UTC)
    clock = [cutoff - timedelta(microseconds=1)]

    class Clock:
        @staticmethod
        def now(zone):
            return clock[0]

    def slow_owner(*_):
        clock[0] = cutoff
        return SimpleNamespace(valid_until=cutoff)

    monkeypatch.setattr(rules, "datetime", Clock)
    monkeypatch.setattr(dispatcher._publishers[0], "read", slow_owner)
    rejects("RULE_NOT_CURRENT", lambda: dispatcher.read(s, ctx, issuer.product_id, None))


def test_delegation_returns_original_material_without_runtime_or_profile_json(marker, monkeypatch):
    engine = SimpleNamespace()
    dispatcher = rules.configure_local_profiles(engine, [profile()])
    issuer = dispatcher._publishers[0].issuer
    s, ctx = binding(issuer, engine)
    material = SimpleNamespace(
        valid_until=datetime.now(UTC) + timedelta(minutes=1),
        inspection={"production_qualified": False},
    )
    monkeypatch.setattr(dispatcher._publishers[0], "read", lambda *_: material)
    assert dispatcher.read(s, ctx, issuer.product_id, None) is material
    assert set(vars(material)) == {"valid_until", "inspection"}
    assert material.inspection["production_qualified"] is False


def test_plural_version_conflict_never_rotates_a_retained_rule_issuer(marker):
    engine = SimpleNamespace()
    value = profile()
    old = rules.configure_local_profile(engine, value)
    registry, epochs = engine._pdos_capa_rule_issuers, engine._pdos_capa_rule_issuer_epochs
    with pytest.raises(ValueError):
        rules.configure_local_profiles(
            engine, [profile(issuer_key="new-first"), {**value, "issuer_version": "v2"}]
        )
    assert engine._pdos_capa_rule_issuers is registry
    assert engine._pdos_capa_rule_issuer_epochs is epochs
    assert engine._pdos_capa_rule_issuers[old.issuer.key] is old.issuer
    assert len(marker) == 1


def test_current_rechecks_configuration_after_all_delegated_io(marker, monkeypatch):
    engine = SimpleNamespace()
    value = profile()
    dispatcher = rules.configure_local_profiles(engine, [value])
    issuer = dispatcher._publishers[0].issuer
    s, ctx = binding(issuer, engine)

    def changed(*_):
        rules.configure_local_profiles(engine, [value])
        return object()

    monkeypatch.setattr(dispatcher._publishers[0], "current", changed)
    rejects(
        "FACT_RULE_PROFILE_CHANGED", lambda: dispatcher.current(s, ctx, issuer.product_id, None)
    )
