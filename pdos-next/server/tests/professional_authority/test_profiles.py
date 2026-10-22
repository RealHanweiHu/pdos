"""Server-only profile configuration; no SQL, imports of facts or qualifications."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pdos_next.domain.professional_authority import service as authority
from pdos_next.errors import DomainError


def profile(**changes):
    return {
        "tenant_id": str(uuid4()),
        "product_id": str(uuid4()),
        "project_id": str(uuid4()),
        "key": "explicit-second-scope",
        "version": "v1",
        **changes,
    }


def state(engine):
    return {
        name: deepcopy(getattr(engine, name, None))
        for name in (
            "_pdos_professional_synthetic",
            "_pdos_professional_issuer_epochs",
        )
    }, dict(getattr(engine, "_pdos_professional_issuers", {}))


def test_json_profiles_retain_old_scope_identity_and_do_not_grant_a_person():
    engine = SimpleNamespace()
    tenant, product = uuid4(), uuid4()
    old = authority.configure_local_synthetic(
        engine, tenant_id=tenant, product_id=product, enabled=True
    )
    profiles = [
        profile(
            tenant_id=str(tenant),
            product_id=str(product),
            project_id=None,
            key=old.key,
            version=old.version,
        ),
        profile(),
    ]
    previous_epochs = dict(engine._pdos_professional_issuer_epochs)
    issuers = authority.configure_local_synthetic_profiles(engine, profiles, enabled=True)
    assert issuers[0] is old and issuers[0].epoch == previous_epochs[old.key]
    new = issuers[1]
    assert isinstance(new.tenant_id, UUID) and isinstance(new.project_id, UUID)
    assert authority._issuer(engine, old, tenant, product, uuid4()) is old
    with pytest.raises(DomainError, match="签发依据"):
        authority._issuer(engine, new, tenant, product, uuid4())
    assert not hasattr(engine, "facts")  # Registration does not import professional facts.


def test_optional_project_and_native_uuids_preserve_product_wide_contract():
    engine = SimpleNamespace()
    value = profile(tenant_id=uuid4(), product_id=uuid4())
    value.pop("project_id")
    (issuer,) = authority.configure_local_synthetic_profiles(engine, [value], enabled=True)
    assert issuer.project_id is None
    assert authority._issuer(engine, issuer, issuer.tenant_id, issuer.product_id, uuid4()) is issuer


@pytest.mark.parametrize("enabled", [False, None, 1, "true"])
def test_enablement_is_explicit_and_invalid_batch_never_changes_mode(enabled):
    engine = SimpleNamespace(_pdos_professional_synthetic=False)
    before = state(engine)
    with pytest.raises(ValueError):
        authority.configure_local_synthetic_profiles(engine, [profile()], enabled=enabled)
    assert state(engine) == before


@pytest.mark.parametrize("profiles", [[], {}, "profile", (profile(),), [profile()] * 21])
def test_only_explicit_bounded_nonempty_lists_are_accepted(profiles):
    engine = SimpleNamespace()
    with pytest.raises(ValueError):
        authority.configure_local_synthetic_profiles(engine, profiles, enabled=True)
    assert state(engine) == state(SimpleNamespace())


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": True},
        {"product_id": 1},
        {"project_id": "not-a-uuid"},
        {"key": ""},
        {"key": "x" * 101},
        {"version": "x" * 101},
        {"profile_id": "caller-choice"},
    ],
)
def test_all_profiles_are_validated_before_any_registry_publication(changes):
    engine = SimpleNamespace(_pdos_professional_synthetic=False)
    before = state(engine)
    with pytest.raises(ValueError):
        authority.configure_local_synthetic_profiles(
            engine, [profile(key="valid-first"), profile(**changes)], enabled=True
        )
    assert state(engine) == before


@pytest.mark.parametrize("duplicate", ["key", "scope"])
def test_duplicate_keys_or_scope_do_not_silently_select_first(duplicate):
    engine = SimpleNamespace()
    first = profile()
    second = (
        profile(key=first["key"])
        if duplicate == "key"
        else {
            **first,
            "key": "different-key",
        }
    )
    with pytest.raises(ValueError):
        authority.configure_local_synthetic_profiles(engine, [first, second], enabled=True)
    assert not hasattr(engine, "_pdos_professional_issuers")


@pytest.mark.parametrize("field", ["tenant_id", "product_id", "project_id"])
def test_existing_key_cannot_be_rebound_and_batch_is_atomic(field):
    engine = SimpleNamespace()
    initial = profile()
    (old,) = authority.configure_local_synthetic_profiles(engine, [initial], enabled=True)
    before = state(engine)
    changed = {**initial, field: str(uuid4())}
    with pytest.raises(ValueError):
        authority.configure_local_synthetic_profiles(
            engine, [profile(key="new-first"), changed], enabled=True
        )
    assert state(engine) == before
    assert engine._pdos_professional_issuers[old.key] is old


def test_explicit_single_rotation_keeps_other_scope_and_invalidates_only_its_old_issuer():
    engine = SimpleNamespace()
    first, second = profile(key="first"), profile(key="second")
    old_first, old_second = authority.configure_local_synthetic_profiles(
        engine, [first, second], enabled=True
    )
    new_first = authority.configure_local_synthetic(
        engine,
        tenant_id=old_first.tenant_id,
        product_id=old_first.product_id,
        project_id=old_first.project_id,
        key=old_first.key,
        version="v2",
        enabled=True,
    )
    assert new_first.epoch == old_first.epoch + 1
    assert engine._pdos_professional_issuers["second"] is old_second
    with pytest.raises(DomainError) as error:
        authority._issuer(
            engine, old_first, old_first.tenant_id, old_first.product_id, old_first.project_id
        )
    assert error.value.reason == "TRUSTED_ISSUER_REQUIRED"
    assert (
        authority._issuer(
            engine, old_second, old_second.tenant_id, old_second.product_id, old_second.project_id
        )
        is old_second
    )


def test_disabled_issuer_reenable_is_not_aba_and_opaque_issuer_remains_immutable():
    engine = SimpleNamespace()
    value = profile()
    (old,) = authority.configure_local_synthetic_profiles(engine, [value], enabled=True)
    authority.disable_issuer(engine, old.key)
    (new,) = authority.configure_local_synthetic_profiles(engine, [value], enabled=True)
    assert new.epoch > old.epoch
    with pytest.raises(AttributeError):
        new.product_id = old.tenant_id
    with pytest.raises(DomainError):
        authority._issuer(engine, old, old.tenant_id, old.product_id, old.project_id)


def test_legacy_single_profile_cannot_overwrite_old_scope_or_flip_mode_on_failure():
    engine = SimpleNamespace()
    old = authority.configure_local_synthetic(
        engine, tenant_id=uuid4(), product_id=uuid4(), enabled=True
    )
    before = state(engine)
    with pytest.raises(ValueError):
        authority.configure_issuer(
            engine, key=old.key, version="v1", tenant_id=uuid4(), product_id=uuid4()
        )
    assert state(engine) == before
    with pytest.raises(ValueError):
        authority.configure_local_synthetic(
            engine, tenant_id=old.tenant_id, product_id=uuid4(), enabled=True
        )
    assert state(engine) == before


def test_real_profile_still_disables_synthetic_authority_mode():
    engine = SimpleNamespace()
    (synthetic,) = authority.configure_local_synthetic_profiles(engine, [profile()], enabled=True)
    authority.configure_issuer(
        engine, key="real-host-root", version="v1", tenant_id=uuid4(), product_id=uuid4()
    )
    assert authority.profile(engine)["synthetic_enabled"] is False
    with pytest.raises(DomainError) as error:
        authority._issuer(
            engine, synthetic, synthetic.tenant_id, synthetic.product_id, synthetic.project_id
        )
    assert error.value.reason == "SYNTHETIC_AUTHORITY_NOT_ALLOWED"


@pytest.mark.parametrize("epoch", [True, 0, -1, "1"])
def test_corrupt_epoch_never_revives_historical_issuer(epoch):
    engine = SimpleNamespace()
    value = profile()
    (old,) = authority.configure_local_synthetic_profiles(engine, [value], enabled=True)
    engine._pdos_professional_issuer_epochs[old.key] = epoch
    before = state(engine)
    with pytest.raises(ValueError):
        authority.configure_local_synthetic_profiles(engine, [value], enabled=True)
    assert state(engine) == before
    with pytest.raises(ValueError):
        authority.configure_local_synthetic_profiles(
            engine, [{**value, "version": "v2"}], enabled=True
        )
    assert state(engine) == before


def test_plural_version_conflict_never_rotates_an_existing_scope():
    engine = SimpleNamespace()
    value = profile()
    (old,) = authority.configure_local_synthetic_profiles(engine, [value], enabled=True)
    before = state(engine)
    with pytest.raises(ValueError):
        authority.configure_local_synthetic_profiles(
            engine, [profile(key="new-first"), {**value, "version": "v2"}], enabled=True
        )
    assert state(engine) == before and engine._pdos_professional_issuers[old.key] is old
