"""Pure, diagnostic-only comparison of one exact legacy resource dependency.

The supplied material comes from the real private _load collector. This module
does not read owners, change an Engine, return a resource bundle or grant current.
"""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as diagnostic_field
from datetime import datetime
from decimal import Decimal
from re import fullmatch
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError

from pdos_next.domain.build_operational_facts.schemas import DecisionInput, DecisionProof
from pdos_next.domain.build_operational_facts.service import digest
from pdos_next.domain.test_resources.schemas import TestPlanBinding
from pdos_next.engines.supply_cost.common import SnapshotRef
from pdos_next.errors import DomainError
from pdos_next.schemas.resource_readiness.contracts import Check, ResourceRef

MATERIAL_KEYS = frozenset(
    {
        "binding",
        "fact",
        "epoch",
        "issuer",
        "issuer_epochs",
        "assets",
        "sample_epochs",
        "samples",
        "authority",
        "source_basis",
        "proofs",
        "checks",
    }
)
AUTHORITY_KEYS = frozenset(
    {
        "scope",
        "subject_id",
        "operation",
        "purpose",
        "authorized",
        "roles",
        "qualified",
        "reason_codes",
        "fact_refs",
        "facts_revision",
        "valid_until",
        "synthetic",
        "required_source_read_set",
    }
)
ROLES = {"engineering", "manufacturing", "quality"}


def _require(value, code="INVALID_RESOURCE_FINGERPRINT_MATERIAL", *, status=409):
    if not value:
        raise DomainError(code, "资源指纹诊断材料或当前宿主依赖无法精确核对。", status)


def _keys(value, names):
    _require(type(value) is dict and set(value) == set(names))


def _revision(value, *, optional=False):
    _require((optional and value is None) or (type(value) is int and value > 0))


def _hash(value):
    _require(type(value) is str and fullmatch(r"[a-f0-9]{64}", value) is not None)


def _text(value, limit=2000):
    _require(type(value) is str and 0 < len(value) <= limit and value == value.strip())


def _uuid(value):
    _require(type(value) in (UUID, str))
    try:
        parsed = value if type(value) is UUID else UUID(value)
    except ValueError:
        _require(False)
    _require(type(value) is UUID or str(parsed) == value)
    return parsed


def _instant(value, *, optional=False):
    if value is None and optional:
        return
    _require(type(value) in (datetime, str))
    try:
        parsed = datetime.fromisoformat(value) if type(value) is str else value
    except ValueError:
        _require(False)
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None)


def _list(value, maximum=None, *, minimum=0):
    # Collection completeness is an owner responsibility, not a business hard cap.
    _require(type(value) is list and minimum <= len(value))


def _safe_values(value):
    """Refuse default=str fallbacks and binary floats before hashing any material."""
    if isinstance(value, BaseModel):
        _safe_values(value.model_dump(mode="python"))
    elif type(value) is dict:
        _require(all(type(key) is str for key in value))
        for child in value.values():
            _safe_values(child)
    elif type(value) in (tuple, list):
        for child in value:
            _safe_values(child)
    elif type(value) is Decimal:
        _require(value.is_finite())
    elif type(value) is datetime:
        _instant(value)
    else:
        _require(value is None or type(value) in (str, int, bool, UUID))


def _same_shape(raw, parsed):
    """Keep actual dumped defaults/children; validation must not fill missing keys."""
    if type(parsed) is dict:
        _keys(raw, parsed)
        for key in parsed:
            _same_shape(raw[key], parsed[key])
    elif type(parsed) in (tuple, list):
        _require(type(raw) in (tuple, list) and len(raw) == len(parsed))
        for left, right in zip(raw, parsed, strict=True):
            _same_shape(left, right)


def _typed(value, cls):
    _require(isinstance(value, cls) or type(value) is dict)
    raw = value.model_dump(mode="python") if isinstance(value, cls) else value
    try:
        parsed = cls.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        _require(False)
    _same_shape(raw, parsed.model_dump(mode="python"))
    return parsed


def _authority(value, binding):
    _keys(value, AUTHORITY_KEYS)
    _keys(value["scope"], {"tenant_id", "product_id", "project_id"})
    for item in value["scope"].values():
        _uuid(item)
    _require(_uuid(value["scope"]["project_id"]) == binding.project_id)
    _require(_uuid(value["subject_id"]) == binding.executor_id)
    _require(value["operation"] == "test.run.start" and value["purpose"] == binding.purpose)
    _require(type(value["authorized"]) is bool and type(value["synthetic"]) is bool)
    _require(value["qualified"] is None or type(value["qualified"]) is bool)
    _list(value["roles"], 3)
    _require(all(type(role) is str and role in ROLES for role in value["roles"]))
    _require(len(set(value["roles"])) == len(value["roles"]))
    _list(value["reason_codes"], 1000)
    for code in value["reason_codes"]:
        _text(code, 160)
    _hash(value["facts_revision"])
    _instant(value["valid_until"], optional=True)
    _list(value["fact_refs"], 128)
    for ref in value["fact_refs"]:
        _keys(
            ref,
            {
                "id",
                "revision",
                "epoch",
                "kind",
                "role",
                "nature",
                "issuer_key",
                "issuer_version",
                "series_id",
                "fact_sha256",
                "issuer_epoch",
                "state",
                "operations",
                "purposes",
                "valid_from",
                "valid_until",
            },
        )
        _uuid(ref["id"])
        _require(ref["state"] in {"active", "withdrawn", "revoked", "unknown"})
        for name in ("operations", "purposes"):
            _list(ref[name], 1000)
            for item in ref[name]:
                _text(item)
        _instant(ref["valid_from"])
        _instant(ref["valid_until"])
        _revision(ref["revision"])
        _revision(ref["epoch"])
        _uuid(ref["series_id"])
        _hash(ref["fact_sha256"])
        _revision(ref["issuer_epoch"], optional=True)
        _require(
            type(ref["kind"]) is str
            and ref["kind"] in {"duty", "qualification"}
            and type(ref["role"]) is str
            and ref["role"] in ROLES
        )
        _require(type(ref["nature"]) is str and ref["nature"] in {"real", "synthetic"})
        _text(ref["issuer_key"], 100)
        _text(ref["issuer_version"], 100)
    _list(value["required_source_read_set"], 20)
    ids = []
    for read in value["required_source_read_set"]:
        _keys(read, {"artifact_id", "expected_revision"})
        ids.append(_uuid(read["artifact_id"]))
        _revision(read["expected_revision"])
    _require(len(ids) == len(set(ids)))


def _source_basis(value):
    # Current provenance is independent of the current reader's ACL stamp.
    has_access = "access" in value
    _keys(
        value,
        {"refs", "security", "fixed_readset_security"} | ({"access"} if has_access else set()),
    )
    _list(value["refs"], 40)
    identities = []
    for ref in value["refs"]:
        _require(type(ref) is dict)
        parsed = _typed(ref, SnapshotRef)
        prefix, separator, identity = parsed.source_id.partition(":")
        _require(separator == ":" and prefix in {"artifact", "original"})
        _uuid(identity)
        _require(parsed.version.isdigit() and int(parsed.version) > 0)
        _instant(ref["captured_at"])
        _instant(ref["valid_until"], optional=True)
        identities.append(parsed.source_id)
    _require(len(identities) == len(set(identities)))
    for name, keys, epoch_key in (
        (
            "security",
            {"original_id", "security_epoch", "source_state", "disposition"},
            "security_epoch",
        ),
        (
            "fixed_readset_security",
            {"artifact_id", "original_id", "epoch", "source_state", "disposition"},
            "epoch",
        ),
    ):
        _list(value[name], 20)
        for entry in value[name]:
            _keys(entry, keys)
            _uuid(entry["original_id"])
            if "artifact_id" in entry:
                _uuid(entry["artifact_id"])
            _revision(entry[epoch_key], optional=True)
            for field in ("source_state", "disposition"):
                if entry[field] is not None:
                    _text(entry[field], 100)
    if has_access:
        _keys(value["access"], {"principal_id", "principal_epoch", "grant_id", "grant_epoch"})
        for key in ("principal_id", "grant_id"):
            _uuid(value["access"][key])
        for key in ("principal_epoch", "grant_epoch"):
            _revision(value["access"][key])


def validate_material(material):
    """Validate the frozen twelve-key producer schema without replacing its values."""
    _keys(material, MATERIAL_KEYS)
    _safe_values(material)
    binding = _typed(material["binding"], TestPlanBinding)
    _hash(material["fact"])
    _revision(material["epoch"])
    _list(material["issuer"], 4, minimum=4)
    _require(len(material["issuer"]) == 4)
    key, version, epoch, available = material["issuer"]
    _text(key, 100)
    _text(version, 100)
    _revision(epoch)
    _require(type(available) is bool)
    _require(type(material["issuer_epochs"]) is dict and bool(material["issuer_epochs"]))
    for name, revision in material["issuer_epochs"].items():
        _text(name, 100)
        _revision(revision)
    _require(material["issuer_epochs"].get(key) == epoch)
    _list(material["assets"], 100, minimum=1)
    asset_ids = []
    for asset in material["assets"]:
        _keys(asset, {"id", "revision", "sha256", "epoch"})
        asset_ids.append(_uuid(asset["id"]))
        _revision(asset["revision"])
        _hash(asset["sha256"])
        _revision(asset["epoch"])
    _require(len(asset_ids) == len(set(asset_ids)))
    samples = {pair.sample.id for pair in binding.pairs}
    for name in ("sample_epochs", "samples"):
        _require(type(material[name]) is dict)
        _require({_uuid(identity) for identity in material[name]} == samples)
        for value in material[name].values():
            _revision(value) if name == "sample_epochs" else _hash(value)
    _authority(material["authority"], binding)
    _source_basis(material["source_basis"])
    _list(material["proofs"], 10000)
    for entry in material["proofs"]:
        _keys(entry, {"resource", "decision", "proof"})
        resource = _typed(entry["resource"], ResourceRef)
        _require(resource.id in asset_ids)
        _require(type(entry["decision"]) is dict)
        _typed(entry["decision"], DecisionInput)
        for field in ("valid_from", "valid_until"):
            _instant(entry["decision"][field], optional=True)
        if entry["proof"] is not None:
            _require(type(entry["proof"]) is dict)
            _typed(entry["proof"], DecisionProof)
            _instant(entry["proof"]["valid_until"], optional=True)
    _list(material["checks"], 50000)
    for value in material["checks"]:
        _typed(value, Check)
    return binding


# The built-in pure validator only reads its arguments; replacements need isolation.
_READ_ONLY_MATERIAL_VALIDATOR = (validate_material, validate_material.__code__)


@dataclass(frozen=True)
class FixedIssuerDependency:
    """Exact actual fact and live issuer scope, to be rechecked by the real owner."""

    tenant_id: UUID
    product_id: UUID
    project_id: UUID
    fact_id: UUID
    fact_revision: int
    fact_sha256: str
    current_epoch: int
    issuer_key: str
    issuer_version: str
    issuer_epoch: int
    issuer_project_id: UUID | None
    nature: Literal["real", "synthetic"]


@dataclass(frozen=True)
class FingerprintDiagnostic:
    current_facts_revision: str
    original_saved_facts_revision: str
    candidate_facts_revision: str
    candidate_matches_saved: bool
    current_matches_saved: bool
    registry_entries: int
    mode: Literal["diagnostic_legacy_single_dependency"] = diagnostic_field(
        default="diagnostic_legacy_single_dependency", init=False
    )
    authorization_attested: Literal[False] = diagnostic_field(default=False, init=False)
    retained_current_attested: Literal[False] = diagnostic_field(default=False, init=False)
    source_or_qualification_attested: Literal[False] = diagnostic_field(default=False, init=False)


def diagnose_legacy_single_dependency(
    collected,
    *,
    fixed: FixedIssuerDependency,
    original_saved_facts_revision: str,
    reservation_saved_facts_revision: str,
    original_reservation_facts_revision: str,
    verify_fixed_issuer: Callable[[FixedIssuerDependency], None] | None = None,
):
    """Compare exactly one candidate; never search a map or return an affirmative bundle.

    The callback is a trusted Root owner, not a DTO boolean. It must recheck the
    actual configured Engine/fact/pointer/issuer and caller/UOW/runtime binding.
    Pure callers cannot prove those facts; the return is always diagnostic only.
    """
    _keys(collected, {"material", "facts_revision"})
    _require(type(fixed) is FixedIssuerDependency)
    _require(callable(verify_fixed_issuer), "INTEGRATION_REQUIRED", status=503)
    for value in (
        collected["facts_revision"],
        original_saved_facts_revision,
        reservation_saved_facts_revision,
        original_reservation_facts_revision,
    ):
        _hash(value)
    _require(
        original_saved_facts_revision
        == reservation_saved_facts_revision
        == original_reservation_facts_revision,
        "ORIGINAL_RESOURCE_PROOF_MISMATCH",
    )
    material = deepcopy(collected["material"])
    binding = validate_material(material)
    current = digest(material)
    _require(current == collected["facts_revision"], "CURRENT_RESOURCE_FINGERPRINT_MISMATCH")
    for value in (fixed.tenant_id, fixed.product_id, fixed.project_id, fixed.fact_id):
        _require(type(value) is UUID)
    if fixed.issuer_project_id is not None:
        _require(
            type(fixed.issuer_project_id) is UUID and fixed.issuer_project_id == fixed.project_id
        )
    for value in (fixed.fact_revision, fixed.current_epoch, fixed.issuer_epoch):
        _revision(value)
    _hash(fixed.fact_sha256)
    _require(type(fixed.nature) is str and fixed.nature in {"real", "synthetic"})
    _require(
        binding.project_id == fixed.project_id
        and material["fact"] == fixed.fact_sha256
        and material["epoch"] == fixed.current_epoch
        and material["issuer"] == [fixed.issuer_key, fixed.issuer_version, fixed.issuer_epoch, True]
        and _uuid(material["authority"]["scope"]["tenant_id"]) == fixed.tenant_id
        and _uuid(material["authority"]["scope"]["product_id"]) == fixed.product_id,
        "FIXED_ISSUER_DEPENDENCY_MISMATCH",
    )
    fixed_sha = digest(vars(fixed))
    _require(verify_fixed_issuer(fixed) is None, "INVALID_FIXED_ISSUER_OWNER_RESULT")
    candidate = deepcopy(material)
    candidate["issuer_epochs"] = {fixed.issuer_key: fixed.issuer_epoch}
    candidate_sha = digest(candidate)
    _require(verify_fixed_issuer(fixed) is None, "INVALID_FIXED_ISSUER_OWNER_RESULT")
    # The owner callback must not replace the collector record while we compare.
    validate_material(collected["material"])
    _require(
        digest(collected["material"]) == current
        and collected["facts_revision"] == current
        and digest(vars(fixed)) == fixed_sha,
        "COLLECTED_RESOURCE_MATERIAL_CHANGED",
    )
    return FingerprintDiagnostic(
        current_facts_revision=current,
        original_saved_facts_revision=original_saved_facts_revision,
        candidate_facts_revision=candidate_sha,
        candidate_matches_saved=candidate_sha == original_saved_facts_revision,
        current_matches_saved=current == original_saved_facts_revision,
        registry_entries=len(material["issuer_epochs"]),
    )
