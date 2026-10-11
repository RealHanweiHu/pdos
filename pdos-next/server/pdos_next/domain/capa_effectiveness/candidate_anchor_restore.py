"""Startup-owned restoration from a real unconsumed persistent Confirmation.

No payload anchor, current qualification grant, consumption, flush, commit or
public registration. Fresh original bytes are always read by the actual owner.
"""

from pdos_next.clock import earliest_deadline
from pdos_next.database import category_for_product


# Initialize actual registry before importing domain children.
# ruff: noqa: I001
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from types import ModuleType
from uuid import UUID
from weakref import WeakKeyDictionary, ref

from pdos_next.service import Context, digest, material_digest

from . import anchor
from . import anchor_owner
from . import anchor_storage
from . import candidate_commands as commands
from . import fact_atom_storage as guards
from . import fact_consumption as consumption
from pdos_next.contracts import Command
from pdos_next.domain.capa_verification import service as followup
from pdos_next.domain.capa_verification.schemas import CandidateBinding, CandidateInspect
from pdos_next.domain.quality_execution import evidence
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Grant, Principal, Product
from pdos_next.quality_result_bridge import _runtime_stamp
from pydantic import ValidationError
from sqlalchemy import select

OPERATION = commands.OPERATION
_ACTUAL_SEMANTIC = commands.semantic
_ACTUAL_PAYLOAD = commands.CandidateRecordPayload
REVIEW_KEYS = frozenset(
    {
        "operation",
        "payload_semantic",
        "stable_anchor",
        "binding",
        "inspection",
        "raw_source_basis",
        "required_source_read_set",
        "sources",
        "authority_snapshot",
        "policy_snapshot",
        "owner_id",
        "visibility",
        "current_issue_revision",
    }
)
PROOF_COLUMNS = tuple(c.key for c in Confirmation.__table__.columns)


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class RestoredCandidateAnchor:
    anchor: anchor.StableCapaAnchor
    reviewed_snapshot: dict
    proof_id: UUID
    proof_revision: int
    proof_sha256: str
    material_sha256: str
    command_sha256: str
    payload_semantic: dict
    current_issue_revision: int
    session: object
    uow: tuple
    runtime_binding: str
    checked_at: datetime
    expires_at: datetime


def _require(condition, code="CANDIDATE_ANCHOR_RESTORE_REQUIRED", status=503):
    if not condition:
        raise DomainError(code, "缺真实未消费确认的完整原锚材料或当前恢复绑定。", status)


def _clock():
    return datetime.now(UTC)


def _runtime(s):
    engine = s.get_bind()
    registry = getattr(engine, "_pdos_quality_policy_issuers", {})
    return digest(
        {
            "result": _runtime_stamp(s),
            "policy_epochs": getattr(engine, "_pdos_quality_policy_epochs", {}),
            "policy_issuers": {k: [id(v), v.epoch] for k, v in registry.items()},
            "anchor_owner": id(anchor_owner.read_anchor_from_actual_owner),
            "source_owner": id(evidence.source_basis),
            "positions": id(evidence.refs_from_exact),
            "line_check": id(evidence.check_source),
        }
    )


def _proof(s, proof):
    state = consumption._proof_state(s, proof)
    _require(not set(PROOF_COLUMNS) & state.unloaded, "FACT_LOADED_CONFIRMATION_REQUIRED")
    _require(
        proof.consumed is False
        and proof not in s.dirty
        and not any(state.attrs[k].history.has_changes() for k in PROOF_COLUMNS),
        "CANDIDATE_UNCONSUMED_CLEAN_PROOF_REQUIRED",
    )
    return {k: deepcopy(getattr(proof, k)) for k in PROOF_COLUMNS}


def _db_proof(s, ctx, pid, proof_id):
    # Scalar columns bypass identity-map/dirty snapshot reuse. No populate of
    # the supplied ORM row can overwrite dirty fields before we compare them.
    table = Confirmation.__table__
    query = (
        select(*(table.c[k] for k in PROOF_COLUMNS))
        .where(
            table.c.tenant_id == ctx.tenant_id,
            table.c.product_id == pid,
            table.c.id == proof_id,
        )
        .limit(2)
        .execution_options(autoflush=False)
    )
    values = list(s.execute(query).mappings())
    _require(
        len(values) == 1 and set(values[0]) == set(PROOF_COLUMNS), "FACT_EXACT_GROUP_ROW_MISSING"
    )
    return deepcopy(dict(values[0]))


def _caller(s, ctx, command):
    product = guards._one(
        s, Product, Product.tenant_id == ctx.tenant_id, Product.id == command.product_id
    )
    person = guards._one(
        s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.actor_id
    )
    grant = guards._one(
        s,
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.category_id == category_for_product(command.product_id),
        Grant.principal_id == ctx.actor_id,
    )
    _require(
        person.kind == "human" and person.active is True and grant.can_write is True,
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        type(product.revision) is int and product.revision == command.expected_revision,
        "VERSION_CONFLICT",
        409,
    )
    return (
        product.id,
        product.tenant_id,
        product.revision,
        getattr(product, "lifecycle_epoch", None),
        person.id,
        person.kind,
        person.active,
        person.access_epoch,
        grant.id,
        grant.access_epoch,
        grant.can_write,
        grant.expires_at,
    ), grant.expires_at


def _deadline(value):
    _require(
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None,
        "CANDIDATE_PROOF_CLOCK_REQUIRED",
    )
    return value.astimezone(UTC)


def _stable_anchor(value):
    return {
        "origin": value.origin.model_dump(mode="json"),
        "failures": [anchor.stable_failure_material(v) for v in value.failures],
        "sources": anchor.json_value(value.origin_sources),
        "reads": anchor.json_value(value.origin_required_source_read_set),
        "safety": anchor.json_value(value.origin_source_basis),
        "material_sha256": value.material_sha256,
        "stable_failure_material_sha256": value.stable_failure_material_sha256,
        "origin_source_basis_sha256": value.origin_source_basis_sha256,
    }


def _snapshot(raw, payload, command):
    _require(
        isinstance(raw, dict) and set(raw) == REVIEW_KEYS, "CANDIDATE_REVIEW_SNAPSHOT_REQUIRED"
    )
    _require(
        raw["operation"] == OPERATION and raw["payload_semantic"] == commands.semantic(payload),
        "CANDIDATE_REVIEW_MATERIAL_CHANGED",
        409,
    )
    try:
        saved = anchor.StableCapaAnchor.model_validate(deepcopy(raw["stable_anchor"]))
        binding = CandidateBinding.model_validate(deepcopy(raw["binding"]))
        inspection = CandidateInspect.model_validate(deepcopy(raw["inspection"]))
        sources, reads, _ = anchor.source_closure(
            raw["sources"], raw["required_source_read_set"], raw["raw_source_basis"]
        )
        owner_id = UUID(raw["owner_id"])
    except (ValidationError, TypeError, ValueError, KeyError):
        raise DomainError(
            "CANDIDATE_REVIEW_SNAPSHOT_REQUIRED", "原确认缺完整严格typed原锚/候选材料。", 503
        ) from None
    _require(
        saved.model_dump(mode="json") == raw["stable_anchor"]
        and binding.model_dump(mode="json") == raw["binding"]
        and inspection.model_dump(mode="json") == raw["inspection"],
        "CANDIDATE_REVIEW_MATERIAL_CHANGED",
        409,
    )
    _require(
        type(raw["current_issue_revision"]) is int
        and raw["current_issue_revision"] == payload.expected_issue_revision,
        "VERSION_CONFLICT",
        409,
    )
    commands.check_candidate_request(
        payload, binding, current_issue_revision=raw["current_issue_revision"]
    )
    origin, basis = saved.origin, binding.basis
    _require(
        (
            basis.scope,
            basis.issue_id,
            basis.issue_version_id,
            basis.issue_revision,
            basis.capa_id,
            basis.purpose,
            basis.owner_id,
            basis.visibility,
            basis.nature,
        )
        == (
            origin.scope,
            payload.issue_id,
            origin.ref.id,
            raw["current_issue_revision"],
            payload.capa_id,
            origin.purpose,
            origin.owner_id,
            origin.visibility,
            origin.nature,
        )
        and owner_id == origin.owner_id
        and raw["visibility"] == payload.visibility == origin.visibility,
        "CANDIDATE_AUDIENCE_OR_ORIGIN_MISMATCH",
        409,
    )
    _require(
        inspection.binding == binding
        and inspection.candidate_ref is None
        and inspection.required_source_read_set == reads
        and anchor.canonical_reads(command.source_read_set) == reads
        and set(saved.origin_required_source_read_set) <= set(reads)
        and set(saved.origin_sources) <= set(sources)
        and set(basis.required_source_read_set) <= set(reads)
        and set(basis.sources) <= set(sources),
        "CANDIDATE_REVIEW_MATERIAL_CHANGED",
        409,
    )
    _require(
        inspection.source_basis_sha256 == digest(raw["raw_source_basis"])
        and inspection.inspection_sha256
        == digest(
            inspection.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
        ),
        "CANDIDATE_REVIEW_MATERIAL_CHANGED",
        409,
    )
    basis_reads = {str(v.artifact_id): v.expected_revision for v in basis.required_source_read_set}
    subset = [v for v in raw["raw_source_basis"] if basis_reads.get(v["id"]) == v["revision"]]
    _require(
        len(subset) == len(basis_reads)
        and digest(subset) == basis.source_basis_sha256
        and digest(basis.model_dump(mode="json", exclude={"basis_sha256"})) == basis.basis_sha256,
        "CANDIDATE_REVIEW_MATERIAL_CHANGED",
        409,
    )
    _require(
        isinstance(raw["authority_snapshot"], dict) and isinstance(raw["policy_snapshot"], dict),
        "CANDIDATE_REVIEW_SNAPSHOT_REQUIRED",
    )
    return saved, binding, sources, reads


class CandidateAnchorRestoreHost:
    """Explicit trusted startup module; no client or generic JSON owner."""

    def __init__(self, module):
        self.module = module
        self._configured_module = module
        self._issued = WeakKeyDictionary()
        self._module()

    def _module(self):
        _require(
            isinstance(self.module, ModuleType)
            and self.module is self._configured_module
            and getattr(self.module, "OPERATION", None) == OPERATION
            and commands.semantic is _ACTUAL_SEMANTIC
            and getattr(self.module, "semantic", None) is _ACTUAL_SEMANTIC
            and commands.CandidateRecordPayload is _ACTUAL_PAYLOAD
            and getattr(self.module, "CandidateRecordPayload", None) is _ACTUAL_PAYLOAD,
            "CANDIDATE_ACTUAL_SEMANTIC_OWNER_REQUIRED",
        )

    def _phase(self, s, ctx, uow, caller, stamp):
        self._module()
        guards._same_uow(s, uow, ctx, caller)
        _require(_runtime(s) == stamp, "SOURCE_STALE", 409)

    def _read(self, s, ctx, command, payload, proof):
        self._module()
        _require(
            isinstance(ctx, Context)
            and isinstance(command, Command)
            and ctx.actor_id == ctx.requester_id
            and ctx.run_id is None
            and command.operation == OPERATION,
            "FORBIDDEN_SCOPE",
            403,
        )
        payload = commands._payload(payload)
        _require(commands._payload(command.payload) == payload, "FACT_COMMAND_PAYLOAD_MISMATCH")
        _require(isinstance(payload.confirmation_token, str), "FACT_PUBLIC_PROOF_TOKEN_REQUIRED")
        uow, caller = guards._uow(s), digest(vars(ctx))
        stamp = _runtime(s)
        with s.no_autoflush:
            loaded = _proof(s, proof)
            stored = _db_proof(s, ctx, command.product_id, proof.id)
            _require(stored == loaded, "CANDIDATE_PERSISTED_PROOF_CHANGED", 409)
            material = material_digest(ctx, command, payload, self.module)
            _require(
                (
                    proof.tenant_id,
                    proof.product_id,
                    proof.actor_id,
                    proof.subject_id,
                    proof.operation,
                    proof.revision,
                )
                == (
                    ctx.tenant_id,
                    command.product_id,
                    ctx.actor_id,
                    command.product_id,
                    OPERATION,
                    command.expected_revision,
                )
                and type(proof.revision) is int
                and proof.revision > 0
                and proof.token_hash == digest(payload.confirmation_token)
                and proof.payload_digest == material,
                "CANDIDATE_PROOF_BINDING_MISMATCH",
                409,
            )
            before_caller, before_until = _caller(s, ctx, command)
            saved, binding, sources, reads = _snapshot(stored["snapshot"], payload, command)
            _require(
                saved.origin.scope.tenant_id == ctx.tenant_id
                and saved.origin.scope.product_id == command.product_id,
                "FORBIDDEN_SCOPE",
                403,
            )
            created, expires = _deadline(proof.created_at), _deadline(proof.expires_at)
            _require(created >= saved.origin.created_at, "CANDIDATE_PROOF_CLOCK_REQUIRED")
            _require(
                created <= _clock() < expires and (before_until is None or _clock() < before_until),
                "CANDIDATE_PROOF_EXPIRED",
                409,
            )
            # Fresh anchor is never an argument/client DTO. Real owner re-reads
            # exact original bytes, saved Start/consumption and source closure.
            fresh = anchor_owner.read_anchor_from_actual_owner(
                s, ctx, command.product_id, payload.issue_id, saved.origin.ref
            )
            self._phase(s, ctx, uow, caller, stamp)
            _require(
                fresh.needs_lineage_owner is False
                and fresh.origin_descriptor.needs_lineage_owner is False
                and fresh.origin_descriptor.current.ref == saved.origin.ref
                and fresh.origin_descriptor.current.ref.revision == payload.expected_issue_revision,
                "CANDIDATE_LINEAGE_OWNER_REQUIRED",
                503,
            )
            _require(_stable_anchor(saved) == _stable_anchor(fresh.anchor), "SOURCE_STALE", 409)
            exact = evidence.refs_from_exact(s, ctx, command.product_id, payload.sources)
            _require(set(exact) <= set(sources), "CANDIDATE_REVIEW_MATERIAL_CHANGED", 409)
            # Structured original reports were checked by the actual fresh
            # bridge. Additional named/manual sources require exact full lines.
            for value in sources:
                if value not in saved.origin_sources:
                    evidence.check_source(s, ctx, command.product_id, value)
            raw, private = evidence.source_basis(s, ctx, command.product_id, reads)
            _require(raw == stored["snapshot"]["raw_source_basis"], "SOURCE_STALE", 409)
            _require(
                not private or saved.origin.visibility == "private",
                "CANDIDATE_AUDIENCE_MISMATCH",
                403,
            )
            self._phase(s, ctx, uow, caller, stamp)
            row, issue = anchor_storage._version(
                s,
                ctx,
                command.product_id,
                payload.issue_id,
                saved.origin.ref,
                saved.origin.scope.project_id,
            )
            _require(issue == saved.origin.issue, "SOURCE_STALE", 409)
            basis_reads = {
                str(v.artifact_id): v.expected_revision
                for v in binding.basis.required_source_read_set
            }
            basis_sources = [v for v in raw if basis_reads.get(v["id"]) == v["revision"]]
            _require(
                followup.basis_from_issue(
                    row,
                    issue,
                    sources=binding.basis.sources,
                    reads=binding.basis.required_source_read_set,
                    source_basis=basis_sources,
                )
                == binding.basis,
                "CANDIDATE_REVIEW_MATERIAL_CHANGED",
                409,
            )
            _require(
                anchor_storage._current(s, ctx, command.product_id, row)
                == fresh.origin_descriptor.current
                and anchor_storage._project(s, ctx, command.product_id, row.project_id)
                == fresh.origin_descriptor.project,
                "SOURCE_STALE",
                409,
            )
            # ALL owner/byte IO is finished. Independently scalar-read the real
            # persisted proof, then Product/Principal/Grant; never dirty ORM JSON.
            after = _db_proof(s, ctx, command.product_id, proof.id)
            _require(
                after == stored and _proof(s, proof) == stored,
                "CANDIDATE_PERSISTED_PROOF_CHANGED",
                409,
            )
            after_caller, after_until = _caller(s, ctx, command)
            _require(after_caller == before_caller, "SOURCE_STALE", 409)
            self._phase(s, ctx, uow, caller, stamp)
            checked_at = _clock()  # Last real clock, after final Grant SQL.
            _require(
                created <= checked_at < earliest_deadline(expires, before_until, after_until),
                "CANDIDATE_PROOF_EXPIRED",
                409,
            )
            _require(checked_at >= fresh.checked_at, "SOURCE_STALE", 409)
            return RestoredCandidateAnchor(
                saved,
                deepcopy(stored["snapshot"]),
                proof.id,
                proof.revision,
                digest(stored),
                material,
                digest(command.model_dump(mode="json")),
                commands.semantic(payload),
                payload.expected_issue_revision,
                s,
                uow,
                stamp,
                checked_at,
                earliest_deadline(expires, after_until),
            )

    def restore(self, s, ctx, command, payload, proof):
        restored = self._read(s, ctx, command, payload, proof)
        self._issued[restored] = (
            ref(s),
            proof,
            digest(vars(ctx)),
            _seal(restored),
            restored.uow,
            restored.runtime_binding,
        )
        return restored

    def require_restored(self, s, ctx, command, payload, proof, restored):
        state = (
            self._issued.get(restored) if isinstance(restored, RestoredCandidateAnchor) else None
        )
        _require(
            state is not None and state[0]() is s and state[1] is proof and restored.session is s,
            "CANDIDATE_RESTORED_OWNER_REQUIRED",
        )
        _require(
            state[2] == digest(vars(ctx))
            and state[3] == _seal(restored)
            and restored.uow is state[4]
            and restored.runtime_binding == state[5],
            "CANDIDATE_RESTORED_BINDING_CHANGED",
            409,
        )
        self._phase(s, ctx, state[4], state[2], state[5])
        fresh = self._read(s, ctx, command, payload, proof)
        _require(
            fresh.command_sha256 == restored.command_sha256
            and fresh.payload_semantic == restored.payload_semantic
            and fresh.proof_sha256 == restored.proof_sha256
            and fresh.material_sha256 == restored.material_sha256
            and fresh.anchor.model_dump(mode="json") == restored.anchor.model_dump(mode="json")
            and fresh.reviewed_snapshot == restored.reviewed_snapshot,
            "CANDIDATE_RESTORED_BINDING_CHANGED",
            409,
        )
        _require(state[3] == _seal(restored), "CANDIDATE_RESTORED_BINDING_CHANGED", 409)
        return restored


def _seal(restored):
    return digest(
        {
            "anchor": restored.anchor.model_dump(mode="json"),
            "review": restored.reviewed_snapshot,
            "proof_id": restored.proof_id,
            "proof_revision": restored.proof_revision,
            "proof_sha256": restored.proof_sha256,
            "material": restored.material_sha256,
            "command": restored.command_sha256,
            "payload": restored.payload_semantic,
            "current_issue_revision": restored.current_issue_revision,
            "runtime": restored.runtime_binding,
            "checked_at": restored.checked_at,
            "expires_at": restored.expires_at,
        }
    )
