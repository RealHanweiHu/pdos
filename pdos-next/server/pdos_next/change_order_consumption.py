"""Candidate Change common-consumer hook, never a consumer or qualification owner.

Bind before the trusted common consumer changes its persistent Confirmation.
Capture immediately after its False -> True assignment, before SQL/autoflush.
No method performs SQL, assigns consumed, flushes, commits, or creates a proof.
"""

# Initialize the actual common registry before the staged dependencies.
# ruff: noqa: I001

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID

from pdos_next.service import Context, digest, material_digest
from pdos_next.domain.capa_effectiveness import fact_atom_storage as storage
from pdos_next.domain.capa_effectiveness.facts import canonical_reads, json_value
from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.clock import proof_deadline_current
from pdos_next.models import Confirmation
from sqlalchemy import inspect

TIERS = MappingProxyType(
    {
        "change.order.prepare": "T1",
        "change.order.approve": "T2",
        "change.implementation.record": "T1",
        "change.effectivity.record": "T1",
        "change.verification.record": "T2",
        "change.close": "T2",
    }
)

FIELDS = (
    "id",
    "tenant_id",
    "product_id",
    "actor_id",
    "subject_id",
    "operation",
    "revision",
    "token_hash",
    "payload_digest",
    "snapshot",
    "created_at",
    "expires_at",
)


def _require(condition, code="FACT_LIVE_CONSUMPTION_REQUIRED"):
    if not condition:
        raise DomainError(code, "缺本次真实共同消费、原材料或活动事务绑定。", 503)


def _proof_state(s, proof):
    _require(isinstance(proof, Confirmation), "FACT_PERSISTENT_CONFIRMATION_REQUIRED")
    state = inspect(proof)
    _require(
        state.persistent is True
        and state.session is s
        and not state.deleted
        and proof not in s.deleted,
        "FACT_PERSISTENT_CONFIRMATION_REQUIRED",
    )
    # Accessing expired attributes could perform IO. This hook must never load
    # them and must be called with the actual common consumer's loaded object.
    _require(not (set(FIELDS) | {"consumed"}) & state.unloaded, "FACT_LOADED_CONFIRMATION_REQUIRED")
    return state


def _proof_digest(proof):
    return digest({field: getattr(proof, field) for field in FIELDS})


def _material(ctx, command, payload, module):
    _require(isinstance(ctx, Context) and isinstance(command, Command))
    _require(ctx.actor_id == ctx.requester_id and ctx.run_id is None)
    _require(
        type(payload).model_validate(command.payload) == payload, "FACT_COMMAND_PAYLOAD_MISMATCH"
    )
    semantic = module.semantic(payload)
    _require(isinstance(semantic, dict), "FACT_DOMAIN_SEMANTIC_REQUIRED")
    # Exactly the common execute formula for these domain operations. Domain
    # semantic alone is a different digest and cannot replace this value.
    common_intent = digest(
        {
            "operation": command.operation,
            "category": command.category_id,
            "product": command.product_id,
            "payload": semantic,
            "named_actor": ctx.requester_id,
            "source_revision": None,
            "private_owner": ctx.requester_id
            if getattr(payload, "visibility", "private") == "private"
            else None,
        }
    )
    token = getattr(
        payload,
        "approval_token" if TIERS[command.operation] == "T2" else "confirmation_token",
        None,
    )
    _require(isinstance(token, str) and bool(token), "FACT_PUBLIC_PROOF_TOKEN_REQUIRED")
    return (
        digest(vars(ctx)),
        digest(command.model_dump(mode="json")),
        material_digest(ctx, command, payload, module),
        common_intent,
        digest([json_value(v) for v in canonical_reads(command.source_read_set)]),
        digest(token),
    )


@dataclass(frozen=True)
class _Binding:
    host: object
    session: object
    uow: tuple
    module: object
    command_id: UUID
    operation: str
    proof: Confirmation
    proof_sha256: str
    materials: tuple[str, ...]


@dataclass(frozen=True)
class LiveConsumption:
    """A host-issued in-memory marker; it is not a persisted transaction proof."""

    proof_id: UUID
    proof_revision: int
    tier: str
    consumed_at: datetime
    expires_at: datetime | None
    token_sha256: str
    material_sha256: str
    read_set_sha256: str
    common_intent_sha256: str

    def storage_columns(self):
        return {
            "shared_proof_id": self.proof_id,
            "shared_proof_revision": self.proof_revision,
            "proof_consumed_at": self.consumed_at,
            "proof_expires_at": self.expires_at,
            "token_sha256": self.token_sha256,
            "material_sha256": self.material_sha256,
            "read_set_sha256": self.read_set_sha256,
            "intent_digest": self.common_intent_sha256,
        }


class ConsumptionHost:
    """Trusted startup configuration, not a JSON/client-defined operation map.

    Each mapped object must be the same actual module used by common execute.
    Public startup has not installed this host or added its operation allowlist.
    """

    def __init__(self, modules):
        _require(bool(modules) and set(modules) <= set(TIERS), "FACT_HOST_REGISTRY_REQUIRED")
        _require(
            all(callable(getattr(v, "semantic", None)) for v in modules.values()),
            "FACT_HOST_REGISTRY_REQUIRED",
        )
        self.modules = MappingProxyType(dict(modules))
        self._state_key = object()

    def _module(self, command, module):
        _require(
            self.modules.get(command.operation) is module and module is not None,
            "FACT_HOST_REGISTRY_MISMATCH",
        )

    def bind_before_transition(self, s, ctx, command, payload, module, proof, *, reviewed_snapshot):
        self._module(command, module)
        state = _proof_state(s, proof)
        uow = storage._uow(s)
        materials = _material(ctx, command, payload, module)
        _require(
            proof.consumed is False
            and not state.attrs.consumed.history.has_changes()
            and (
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
                command.operation,
                command.expected_revision,
            )
            and proof.token_hash == materials[5]
            and proof.payload_digest == materials[2]
            and isinstance(proof.snapshot, dict)
            and isinstance(reviewed_snapshot, dict)
            and digest(proof.snapshot) == digest(reviewed_snapshot),
            "FACT_UNCONSUMED_MATERIAL_BINDING_REQUIRED",
        )
        _require(
            type(proof.revision) is int and proof.revision > 0 and isinstance(proof.id, UUID),
            "FACT_EXACT_CONFIRMATION_REQUIRED",
        )
        binding = _Binding(
            self,
            s,
            uow,
            module,
            command.command_id,
            command.operation,
            proof,
            _proof_digest(proof),
            materials,
        )
        self._bucket(s, uow)["bindings"][id(binding)] = binding
        return binding

    def _bucket(self, s, uow):
        bucket = s.info.get(self._state_key)
        if bucket is None or bucket["uow"][0] != uow[0] or bucket["uow"][1] is not uow[1]:
            bucket = {"uow": uow, "bindings": {}, "markers": {}, "commands": {}}
            s.info[self._state_key] = bucket
        return bucket

    def _bound(self, s, ctx, command, payload, module, proof, binding):
        self._module(command, module)
        _require(
            isinstance(binding, _Binding)
            and binding.host is self
            and binding.session is s
            and binding.proof is proof
            and binding.command_id == command.command_id
            and binding.operation == command.operation
            and binding.module is module
        )
        storage._same_uow(s, binding.uow, ctx, binding.materials[0])
        bucket = s.info.get(self._state_key)
        _require(bucket is not None and bucket["bindings"].get(id(binding)) is binding)
        state = _proof_state(s, proof)
        _require(
            _material(ctx, command, payload, module) == binding.materials
            and _proof_digest(proof) == binding.proof_sha256,
            "FACT_CONSUMPTION_MATERIAL_CHANGED",
        )
        return state, bucket

    def capture_after_transition(self, s, ctx, command, payload, module, proof, *, binding):
        consumed_at = datetime.now(UTC)  # First action after actual assignment; no IO first.
        state, bucket = self._bound(s, ctx, command, payload, module, proof, binding)
        history = state.attrs.consumed.history
        _require(
            proof.consumed is True
            and tuple(history.deleted) == (False,)
            and tuple(history.added) == (True,),
            "FACT_ACTUAL_FALSE_TRUE_REQUIRED",
        )
        _require(
            isinstance(proof.created_at, datetime)
            and proof.created_at.utcoffset() is not None
            and proof.created_at <= consumed_at
            and proof_deadline_current(TIERS[command.operation], proof.expires_at, consumed_at),
            "FACT_CONSUMPTION_CLOCK_INVALID",
        )
        old = bucket["markers"].get(proof.id)
        command_proof = bucket["commands"].get(command.command_id)
        _require(
            command_proof is None or command_proof == proof.id, "FACT_COMMAND_ALREADY_CONSUMED"
        )
        if old is not None:
            _require(old[0] is binding, "FACT_PROOF_ALREADY_BOUND")
            return old[1]  # Idempotent hook, retains the first actual clock.
        marker = LiveConsumption(
            proof.id,
            proof.revision,
            TIERS[command.operation],
            consumed_at,
            proof.expires_at,
            binding.materials[5],
            binding.materials[2],
            binding.materials[4],
            binding.materials[3],
        )
        bucket["markers"][proof.id] = (binding, marker)
        bucket["commands"][command.command_id] = proof.id
        return marker

    def require_live(self, s, ctx, command, payload, module, proof, *, binding, marker):
        """Call after ALL actual owner IO. This method itself performs no IO.

        Caller/source/issuer/qualification refresh is the real writer's duty.
        A fresh real expiry check here does not prove a COMMIT-clock guarantee.
        """
        _, bucket = self._bound(s, ctx, command, payload, module, proof, binding)
        saved = bucket["markers"].get(proof.id)
        _require(
            saved is not None
            and saved[0] is binding
            and saved[1] is marker
            and proof.consumed is True,
            "FACT_ACTUAL_FALSE_TRUE_REQUIRED",
        )
        _require(
            marker.consumed_at <= datetime.now(UTC)
            and proof_deadline_current(
                TIERS[command.operation], proof.expires_at, datetime.now(UTC)
            ),
            "FACT_CONSUMPTION_CLOCK_INVALID",
        )
        storage._same_uow(s, binding.uow, ctx, binding.materials[0])
        return marker
