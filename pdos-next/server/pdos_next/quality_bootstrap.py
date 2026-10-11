"""Explicit marked-host synthetic policy profiles; no automatic scope or qualification."""

import json
from copy import deepcopy
from uuid import UUID

from pdos_next.domain.quality_execution.policy import configure_local_synthetic
from pdos_next.safety import verify_test_target

_KEYS = {"tenant_id", "product_id", "project_id", "issuer_key", "issuer_version"}
_REGISTRY = "_pdos_quality_policy_issuers"
_CONFIGURATIONS = "_pdos_quality_bootstrap_profiles"


def _profile(profile, *, strict_names=False):
    if not isinstance(profile, dict) or set(profile) != _KEYS:
        raise ValueError("Local quality policy profile requires an exact host-owned scope")
    tenant, product, project = (UUID(profile[k]) for k in ("tenant_id", "product_id", "project_id"))
    key, version = profile["issuer_key"], profile["issuer_version"]
    if any(type(v) is not str or not v.strip() or len(v) > 100 for v in (key, version)):
        raise ValueError("Policy issuer name/version must contain 1..100 characters")
    if strict_names and any(v.strip() != v for v in (key, version)):
        raise ValueError("Batch issuer name/version must be exact")
    material = json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return tenant, product, project, key, version, material


def _register(engine, profile, values):
    tenant, product, project, key, version, material = values
    issuer = configure_local_synthetic(
        engine,
        tenant_id=tenant,
        product_id=product,
        project_id=project,
        key=key,
        version=version,
        enabled=True,
        test_marker_verified=True,
    )
    configured = dict(getattr(engine, _CONFIGURATIONS, {}))
    configured[key] = {"canonical": material, "issuer": issuer}
    setattr(engine, _CONFIGURATIONS, configured)
    return issuer


_ABSENT = object()
_EPOCHS = "_pdos_quality_policy_epochs"
_CONFIGURATION_ATTRIBUTES = (_REGISTRY, _EPOCHS, _CONFIGURATIONS)


def _configuration_state(engine):
    registry = getattr(engine, _REGISTRY, {})
    epochs = getattr(engine, _EPOCHS, {})
    configured = getattr(engine, _CONFIGURATIONS, {})
    if any(type(value) is not dict for value in (registry, epochs, configured)):
        raise ValueError("Issuer registry, epochs and trusted metadata must be dictionaries")
    if any(type(value) is not int or value < 1 for value in epochs.values()):
        raise ValueError("Every existing issuer epoch must be a strict positive integer")
    return registry, epochs, configured


def _register_batch(engine, prepared):
    """Publish startup configuration atomically, including unexpected factory failure.

    Preserve existing dictionary/issuer/callback identities and absence. Domain
    factories copy registry/epoch dictionaries; metadata rows are retained too
    so an injected failing registrar cannot leave an in-place partial change.
    No database transaction, business proof or session cache is involved.
    """
    snapshots = []
    for name in _CONFIGURATION_ATTRIBUTES:
        original = getattr(engine, name, _ABSENT)
        contents = dict(original) if isinstance(original, dict) else None
        rows = (
            tuple((row, dict(row)) for row in original.values() if isinstance(row, dict))
            if name == _CONFIGURATIONS and isinstance(original, dict)
            else ()
        )
        snapshots.append((name, original, contents, rows))
    try:
        return tuple(
            live if live is not None else _register(engine, profile, values)
            for profile, values, live in prepared
        )
    except BaseException:
        for name, original, contents, rows in snapshots:
            if original is _ABSENT:
                if hasattr(engine, name):
                    delattr(engine, name)
            else:
                for row, old_contents in rows:
                    row.clear()
                    row.update(old_contents)
                if contents is not None:
                    original.clear()
                    original.update(contents)
                setattr(engine, name, original)
        raise


def configure_local_profile(engine, profile):
    """Legacy explicit single configuration, also recorded for safe later batch reuse."""
    values = _profile(profile)
    verify_test_target(engine)
    return _register(engine, profile, values)


def configure_local_profiles(engine, profiles):
    """Register a fully validated finite list; preserve every identical live old issuer."""
    if type(profiles) is not list or not profiles:
        raise ValueError(
            "Profiles must be an explicit nonempty JSON list with named explicit scopes"
        )
    prepared, scopes, keys = [], set(), set()
    registry, epochs, configured = _configuration_state(engine)
    for entry in profiles:
        profile = deepcopy(entry)
        values = _profile(profile, strict_names=True)
        tenant, product, project, key, version, material = values
        scope = tenant, product, project
        if key in keys or scope in scopes:
            raise ValueError("Issuer keys and exact policy scopes cannot repeat")
        keys.add(key)
        scopes.add(scope)
        previous, live = configured.get(key), registry.get(key)
        if previous is not None or live is not None or key in epochs:
            if (
                type(previous) is not dict
                or set(previous) != {"canonical", "issuer"}
                or previous["canonical"] != material
                or previous["issuer"] is not live
                or live is None
                or type(getattr(live, "epoch", None)) is not int
                or live.epoch < 1
                or epochs.get(key) != live.epoch
                or (live.tenant_id, live.product_id, live.project_id, live.key, live.version)
                != (tenant, product, project, key, version)
            ):
                raise ValueError("An existing policy scope/version must not be replaced")
        prepared.append((profile, values, live))
    verify_test_target(engine)
    return _register_batch(engine, prepared)
