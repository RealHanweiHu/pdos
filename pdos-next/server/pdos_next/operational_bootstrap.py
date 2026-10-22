"""Finite synthetic operational profiles, explicitly configured by the marked host.

Only startup configuration is retained here. No phase proofs, caller-selected
scope, source authorization or real professional qualifications are cached.
"""

import json
from copy import deepcopy
from datetime import datetime
from uuid import UUID

from pdos_next.domain.build_operational_facts.schemas import DecisionInput, OperationalScope
from pdos_next.safety import verify_test_target
from pdos_next.schemas.resource_readiness.contracts import ResourceRef
from pdos_next.service import digest

DEFAULT_ISSUER_KEY = "synthetic-operational-facts"
DEFAULT_ISSUER_VERSION = "v1"
MAX_PROFILES = 20
_REGISTRY = "_pdos_operational_issuers"
_CONFIGURATIONS = "_pdos_operational_bootstrap_profiles"
_PROFILE_KEYS = {"tenant_id", "product_id", "decisions"}
_SCOPED_KEYS = _PROFILE_KEYS | {"issuer_key", "issuer_version"}


def _canonical(profile, key, version):
    return json.dumps(
        {"profile": profile, "issuer_key": key, "issuer_version": version},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _issuer_name(value):
    if type(value) is not str or not value or value.strip() != value or len(value) > 100:
        raise ValueError("An exact server issuer name/version of 1..100 characters is required")
    return value


def _binding(binding):
    expected = {
        "build_id",
        "build_revision",
        "project_id",
        "scope",
        "engineering_configuration_id",
        "engineering_configuration_revision",
        "manufacturing_configuration_id",
        "manufacturing_configuration_revision",
    }
    if not isinstance(binding, dict) or set(binding) != expected:
        raise ValueError("Exact Build/configuration/scope binding required")
    for name in (
        "build_id",
        "project_id",
        "engineering_configuration_id",
        "manufacturing_configuration_id",
    ):
        UUID(binding[name])
    for name in (
        "build_revision",
        "engineering_configuration_revision",
        "manufacturing_configuration_revision",
    ):
        if type(binding[name]) is not int or binding[name] < 1:
            raise ValueError("Exact positive binding revision required")
    OperationalScope.model_validate(binding["scope"])


def _profile(profile, *, strict_material=False):
    if not isinstance(profile, dict) or set(profile) != _PROFILE_KEYS:
        raise ValueError("Exact host-owned finite operational profile required")
    tenant, product = UUID(profile["tenant_id"]), UUID(profile["product_id"])
    entries = deepcopy(profile["decisions"])
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError("Synthetic operational decision ledger must be bounded")
    ledger = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"binding", "resource", "decision"}:
            raise ValueError("Exact fixed binding/resource/named decision required")
        if strict_material:
            _binding(entry["binding"])
            ResourceRef.model_validate(entry["resource"])
        decision = DecisionInput.model_validate(entry["decision"])
        if decision.named_decision_id is None or decision.valid_until is None:
            raise ValueError("Synthetic named decision needs an ID and expiry")
        key = str(decision.named_decision_id)
        if key in ledger:
            raise ValueError("Synthetic named decision identities cannot repeat")
        ledger[key] = entry
    return tenant, product, ledger


def _register(engine, profile, tenant, product, ledger, key, version):
    from pdos_next.domain.build_operational_facts.service import configure_local_synthetic

    def verify(_session, ctx, binding, resource, decision, at):
        entry = ledger.get(str(decision.named_decision_id))
        proposed = {
            "binding": binding,
            "resource": resource.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
        }
        if ctx.tenant_id != tenant or entry is None or digest(entry) != digest(proposed):
            return None
        expiry = datetime.fromisoformat(entry["decision"]["valid_until"])
        if expiry <= at:
            return None
        return {"current": True, "facts_revision": digest(entry), "valid_until": expiry}

    material = _canonical(profile, key, version)
    issuer = configure_local_synthetic(
        engine,
        tenant_id=tenant,
        product_id=product,
        key=key,
        version=version,
        enabled=True,
        test_marker_verified=True,
        verify_named_decision=verify,
    )
    configured = dict(getattr(engine, _CONFIGURATIONS, {}))
    configured[key] = {"canonical": material, "issuer": issuer}
    setattr(engine, _CONFIGURATIONS, configured)
    return issuer


_ABSENT = object()
_EPOCHS = "_pdos_operational_issuer_epochs"
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
            live
            if live is not None
            else _register(engine, profile, tenant, product, ledger, key, version)
            for profile, tenant, product, ledger, key, version, live in prepared
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
    """Legacy single profile: retain its fields/default issuer and explicit reconfiguration."""
    verify_test_target(engine)
    tenant, product, ledger = _profile(profile)
    return _register(
        engine,
        profile,
        tenant,
        product,
        ledger,
        DEFAULT_ISSUER_KEY,
        DEFAULT_ISSUER_VERSION,
    )


def configure_local_profiles(engine, profiles):
    """Validate ALL explicit scopes before registration; reuse only a proven live configuration.

    Different source material, an unrecorded pre-existing issuer, a revoked issuer
    or any repeated key/scope is a conflict. This is not an issuer-update API.
    """
    if type(profiles) is not list or not 1 <= len(profiles) <= MAX_PROFILES:
        raise ValueError("Profiles must be an explicit nonempty JSON list of at most 20")
    prepared, scopes, keys = [], set(), set()
    registry, epochs, configured = _configuration_state(engine)
    for entry in profiles:
        if not isinstance(entry, dict) or set(entry) != _SCOPED_KEYS:
            raise ValueError("Each scoped profile must explicitly name its issuer/version")
        key, version = _issuer_name(entry["issuer_key"]), _issuer_name(entry["issuer_version"])
        profile = {k: deepcopy(entry[k]) for k in _PROFILE_KEYS}
        tenant, product, ledger = _profile(profile, strict_material=True)
        material = _canonical(profile, key, version)
        scope = (tenant, product)
        if key in keys or scope in scopes:
            raise ValueError("Issuer keys and exact profile scopes cannot repeat")
        scopes.add(scope)
        keys.add(key)
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
                or (
                    live.tenant_id,
                    live.product_id,
                    live.project_id,
                    live.key,
                    live.version,
                    live.nature,
                )
                != (tenant, product, None, key, version, "synthetic")
            ):
                raise ValueError("An existing issuer scope/version/material must not be replaced")
        prepared.append((profile, tenant, product, ledger, key, version, live))
    verify_test_target(engine)
    return _register_batch(engine, prepared)
