"""Live paired Formal output owner, without a new truth or write/receipt path.

Only the stable OutputReading is stored in a remediation link. The registered
handle and its live gates belong to this caller's phase/UOW and are never JSON.
"""

# Initialize the actual common registry before importing its domain children.
# ruff: noqa: I001
from pdos_next.service import Context, digest

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary, ref as weakref

from sqlalchemy import select

from pdos_next import paired_output_bridge, quality_result_bridge
from pdos_next.domain.capa_effectiveness import paired, paired_storage
from pdos_next.domain.capa_verification.schemas import (
    FollowupBasis,
    Missing,
    OutputReading,
    OutputRef,
    SourceRead,
)
from pdos_next.domain.quality_execution import evidence
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError

ATTRIBUTE = "_pdos_paired_followup_owner"
PAIRED_FORMAL_OPERATIONS = frozenset(
    {
        "verification.schedule.promise",
        "test.run.start",
        "test.results.import",
        "test.run.review",
        "test.disposition.decide",
    }
)
_OMIT_DISPLAY = frozenset(
    {
        "authority",
        "capabilities",
        "checked_at",
        "created_at",
        "blockers",
        "identified_count",
        "remaining_unit_count",
        "build_observed_unit_count",
        "over_planned_quantity",
    }
)


def _now():
    return datetime.now(UTC)


def _require(allowed, code="SOURCE_STALE", status=409):
    if allowed is not True:
        raise DomainError(code, "真实配对输出、当前权限或固定材料无法完整核对。", status)


def _wire(value):
    return value.model_dump(mode="json")


@dataclass(frozen=True, eq=False)
class PairedFollowupRead:
    output: OutputReading
    receipt_id: UUID
    pair_read: paired.ServerPairRead
    structure: paired.StructuralPairProof
    host_gate: paired.HostGateProof


@dataclass(frozen=True)
class _HandleBinding:
    uow: tuple
    caller_sha256: str
    product_id: UUID
    basis_sha256: str
    selected: OutputRef
    runtime: dict
    result_sha256: str
    write: bool


def _handle_sha(value):
    return digest(
        {
            "output": _wire(value.output),
            "receipt_id": str(value.receipt_id),
            "pair_binding": _wire(value.pair_read.binding),
            "pair_material": _wire(value.pair_read.material),
            "structure": _wire(value.structure),
            "gate": {
                "issuer": id(value.host_gate.issued_by),
                "session": id(value.host_gate.session),
                "transaction": id(value.host_gate.transaction),
                "nested_transaction": id(value.host_gate.nested_transaction),
                "caller_id": str(value.host_gate.caller_id),
                "scope": _wire(value.host_gate.scope),
                "structural_sha256": value.host_gate.structural_sha256,
                "stamps": [(v.kind, v.basis_sha256) for v in value.host_gate.stamps],
                "checked_at": value.host_gate.checked_at.isoformat(),
                "valid_until": value.host_gate.valid_until.isoformat()
                if value.host_gate.valid_until
                else None,
                "time_constraints": [
                    bound.isoformat() for bound in value.host_gate.time_constraints
                ],
                "needs_review": value.host_gate.needs_review,
            },
        }
    )


def _many(s, model, *where):
    return list(
        s.scalars(select(model).where(*where).limit(2).execution_options(populate_existing=True))
    )


def _only(rows, code):
    _require(len(rows) == 1, code, 503)
    return rows[0]


def _selected_request(s, ctx, pid, basis, selected):
    row = _only(
        _many(
            s,
            FormalVerificationRequest,
            FormalVerificationRequest.tenant_id == ctx.tenant_id,
            FormalVerificationRequest.product_id == pid,
            FormalVerificationRequest.id == selected.id,
            FormalVerificationRequest.revision == selected.revision,
        ),
        "PAIR_FORMAL_MISSING",
    )
    _require(row.project_id == basis.scope.project_id, "FORBIDDEN_SCOPE", 403)
    _require(
        row.visibility != "private" or row.owner_id == ctx.requester_id,
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(row.purpose == basis.purpose, "PAIR_SCOPE_MISMATCH", 403)
    _require(row.operation in PAIRED_FORMAL_OPERATIONS, "PAIR_NOT_REQUIRED", 503)
    # The actual selected output fact identifies its Run. Other Runs under the
    # same request neither substitute for it nor make its identity ambiguous.
    fact = paired_storage._output_fact(s, ctx, pid, row)
    pointer = _only(
        _many(
            s,
            VerificationRunCurrent,
            VerificationRunCurrent.tenant_id == ctx.tenant_id,
            VerificationRunCurrent.product_id == pid,
            VerificationRunCurrent.request_id == row.request_id,
            VerificationRunCurrent.run_id == fact.run_id,
        ),
        "PAIR_CURRENT_MISSING_OR_AMBIGUOUS",
    )
    identity = _only(
        _many(
            s,
            VerificationRunIdentity,
            VerificationRunIdentity.tenant_id == ctx.tenant_id,
            VerificationRunIdentity.product_id == pid,
            VerificationRunIdentity.request_id == row.request_id,
            VerificationRunIdentity.id == fact.run_id,
        ),
        "PAIR_RUN_MISSING_OR_AMBIGUOUS",
    )
    run = _only(
        _many(
            s,
            VerificationRunVersion,
            VerificationRunVersion.tenant_id == ctx.tenant_id,
            VerificationRunVersion.product_id == pid,
            VerificationRunVersion.id == pointer.run_version_id,
            VerificationRunVersion.revision == pointer.run_revision,
            VerificationRunVersion.run_id == pointer.run_id,
        ),
        "PAIR_CURRENT_MISSING_OR_AMBIGUOUS",
    )
    _require(
        (identity.id, identity.project_id, identity.build_id, identity.request_id)
        == (run.run_id, row.project_id, row.build_id, row.request_id)
        and (run.project_id, run.build_id, run.request_id)
        == (row.project_id, row.build_id, row.request_id)
        and (identity.owner_id, identity.visibility) == (run.owner_id, run.visibility),
        "PAIR_SCOPE_MISMATCH",
        403,
    )
    _require(
        run.visibility != "private" or run.owner_id == ctx.requester_id,
        "FORBIDDEN_SCOPE",
        403,
    )
    return row


def _fixed_view(s, ctx, pid, basis, selected, read):
    row, view = front.get_request(s, ctx, pid, selected.id, assess_capabilities=False)
    _require(
        (row.tenant_id, row.product_id, row.project_id, row.id, row.revision)
        == (ctx.tenant_id, pid, basis.scope.project_id, selected.id, selected.revision)
        and row.purpose == basis.purpose
        and row.request_id == read.binding.request_id
        and row.build_id == read.binding.build.id
        and row.build_revision == read.binding.build.revision,
        "PAIR_SCOPE_MISMATCH",
        403,
    )
    _require(
        row.visibility != "private" or row.owner_id == ctx.requester_id,
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(view["is_current"] is True, "PAIR_CURRENT_MISMATCH")
    reads = tuple(
        SourceRead.model_validate(v)
        for v in evidence.merge_reads(
            row.required_source_read_set,
            *(v["required_source_read_set"] for v in view["method_assessments"]),
            *(v["required_source_read_set"] for v in view["window_proposals"]),
            read.material.request_after.reads,
            read.material.run_after.reads,
            read.material.fact.reads,
            read.material.projection.reads if read.material.projection else (),
        )
    )
    snapshot = {key: deepcopy(value) for key, value in view.items() if key not in _OMIT_DISPLAY}
    snapshot["required_source_read_set"] = [_wire(v) for v in reads]
    return row, snapshot, reads


class PairedFollowupOwner:
    """Startup-configured adapter; no positive cache or anonymous gate issuer."""

    def __init__(self, engine, paired_owner, *, epoch=1):
        _require(
            isinstance(paired_owner, paired_output_bridge.LivePairedOwner)
            and type(epoch) is int
            and epoch > 0,
            "INTEGRATION_REQUIRED",
            503,
        )
        self._engine = engine
        self._owner = paired_owner
        self._configuration_id = str(uuid4())
        self._epoch = epoch
        self._handles = WeakKeyDictionary()

    @property
    def runtime(self):
        # This bridge helper only reads this actual engine's in-process owner
        # registry. The facade is NOT a Session/UOW or a source/ACL proof.
        registry = SimpleNamespace(get_bind=lambda: self._engine)
        return {
            "schema_version": "paired-followup-owner-v1",
            "configuration_id": self._configuration_id,
            "epoch": self._epoch,
            "paired_owner_identity": str(id(self._owner)),
            "owners_runtime_sha256": quality_result_bridge._runtime_stamp(registry),
        }

    def _runtime(self, s):
        _require(
            s.get_bind() is self._engine and getattr(self._engine, ATTRIBUTE, None) is self,
            "PAIR_OWNER_CONFIGURATION_CHANGED",
            503,
        )
        return {
            "configuration": self.runtime,
            "owners": deepcopy(quality_result_bridge._runtime_stamp(s)),
        }

    def _input(self, s, ctx, pid, basis, selected, write):
        _require(
            isinstance(ctx, Context)
            and ctx.actor_id == ctx.requester_id
            and ctx.run_id is None
            and type(write) is bool,
            "FORBIDDEN_SCOPE",
            403,
        )
        basis = FollowupBasis.model_validate(
            basis.model_dump(mode="python") if isinstance(basis, FollowupBasis) else basis
        )
        selected = OutputRef.model_validate(
            selected.model_dump(mode="python") if isinstance(selected, OutputRef) else selected
        )
        _require(
            selected.kind == "verification_request"
            and selected.key is None
            and (basis.scope.tenant_id, basis.scope.product_id) == (ctx.tenant_id, pid),
            "PAIR_SCOPE_MISMATCH",
            403,
        )
        return basis, selected, paired_storage._uow(s), digest(vars(ctx)), self._runtime(s)

    def _live_pair(self, s, ctx, pid, basis, selected, write, uow, caller, runtime):
        selected_formal = paired.FormalRef(id=selected.id, revision=selected.revision)
        read = self._owner.read(s, ctx, pid, selected_formal, at=_now(), write=write)
        first = None
        for phase in range(2):
            paired_storage._guard_uow(s, uow, ctx, caller)
            _require(isinstance(read, paired.ServerPairRead), "INTEGRATION_REQUIRED", 503)
            _require(
                read.binding.scope == basis.scope
                and read.binding.purpose == basis.purpose
                and read.binding.caller_id == ctx.requester_id
                and read.binding.output_ref == selected_formal,
                "PAIR_SCOPE_MISMATCH",
                403,
            )
            check = paired.verify_paired_material(read.binding, read.material, at=_now())
            if check.proof is None:
                raise DomainError(check.missing[0].code, check.missing[0].detail, 503)
            row, snapshot, reads = _fixed_view(s, ctx, pid, basis, selected, read)
            source_basis, private = evidence.source_basis(s, ctx, pid, reads)
            _require(not private or row.visibility == "private", "FORBIDDEN_SCOPE", 403)
            # The actual owner independently rechecks all bytes/qualification/
            # retained/current/issuer sources after this fixed-child read IO.
            started = _now()
            gate = self._owner.attest(s, ctx, pid, read, check.proof, at=started, write=write)
            paired_storage._guard_uow(s, uow, ctx, caller)
            missing = paired._validate_gate(
                self._owner, s, ctx, read, check.proof, gate, started, _now()
            )
            if missing is not None:
                raise DomainError(missing.code, missing.detail, 503)
            _require(self._runtime(s) == runtime)
            stable = (
                check.proof.material_sha256,
                tuple(sorted((v.kind, v.basis_sha256) for v in gate.stamps)),
                gate.valid_until,
                gate.time_constraints,
                gate.needs_review,
                digest(snapshot),
                digest(source_basis),
            )
            if phase == 1:
                _require(stable == first)
                return read, check.proof, gate, snapshot, reads, source_basis
            first = stable
            read = self._owner.refresh(s, ctx, pid, read, at=_now(), write=write)
        raise AssertionError("bounded two-phase paired owner")

    def _finish(self, s, ctx, pid, gate, uow, caller, runtime, *, write):
        # Last SQL is before the real clock; configuration/runtime also remain
        # identical after current caller ACL re-read. No commit/flush is allowed.
        paired_storage._acl(s, ctx, pid, write=write)
        _require(self._runtime(s) == runtime)
        paired_storage._guard_uow(s, uow, ctx, caller)
        checked = _now()
        _require(
            gate.checked_at <= checked
            and (gate.valid_until is None or checked < gate.valid_until)
            and all(checked < value for value in gate.time_constraints),
            "PAIR_LIVE_PROOF_EXPIRED",
        )

    def read(self, s, ctx, product_id, basis, selected, *, write=False):
        basis, selected, uow, caller, runtime = self._input(
            s, ctx, product_id, basis, selected, write
        )
        with s.no_autoflush:
            paired_storage._acl(s, ctx, product_id, write=write)
            _selected_request(s, ctx, product_id, basis, selected)
            read, structure, gate, snapshot, reads, source_basis = self._live_pair(
                s, ctx, product_id, basis, selected, write, uow, caller, runtime
            )
            # All values in this material are actual immutable rows/common group.
            # PairBinding's caller and the live HostGate never enter the snapshot.
            snapshot["paired_material"] = _wire(read.material)
            state = "current" if snapshot["source_status"] == "current" else "needs_recheck"
            missing = (
                (
                    Missing(
                        dimension="source",
                        code="SOURCE_STALE",
                        detail="正式输出固定子来源当前需要重核。",
                        output_ref=selected,
                    ),
                )
                if state != "current"
                else ()
            )
            output = OutputReading(
                ref=selected,
                logical_id=read.binding.request_id,
                project_id=read.binding.scope.project_id,
                owner_id=read.material.request_after.owner_id,
                visibility=read.material.request_after.visibility,
                title=snapshot["title"],
                status=snapshot["status"],
                meaning=structure.meaning,
                source_status=state,
                snapshot=snapshot,
                required_source_read_set=reads,
                owner_basis_sha256=digest(
                    {"ref": _wire(selected), "snapshot": snapshot, "source_basis": source_basis}
                ),
                missing=missing,
            )
            _require(
                read.material.receipt is not None
                and structure.receipt_id == read.material.receipt.id,
                "PAIR_RECEIPT_MISSING",
                503,
            )
            handle = PairedFollowupRead(output, structure.receipt_id, read, structure, gate)
            self._finish(s, ctx, product_id, gate, uow, caller, runtime, write=write)
            binding = _HandleBinding(
                uow,
                caller,
                product_id,
                digest(_wire(basis)),
                selected,
                runtime,
                _handle_sha(handle),
                write,
            )
            registry = self._handles.setdefault(s, {})
            identity = id(handle)
            registry[identity] = (
                weakref(handle, lambda _: registry.pop(identity, None)),
                binding,
            )
            return handle

    def refresh(self, s, ctx, product_id, basis, selected, previous, *, write=False):
        _require(isinstance(previous, PairedFollowupRead), "PAIR_HANDLE_UNBOUND", 503)
        item = self._handles.get(s, {}).get(id(previous))
        _require(item is not None and item[0]() is previous, "PAIR_HANDLE_UNBOUND", 503)
        saved = item[1]
        _require(
            (previous.host_gate.valid_until is None or _now() < previous.host_gate.valid_until)
            and all(_now() < value for value in previous.host_gate.time_constraints),
            "PAIR_LIVE_PROOF_EXPIRED",
        )
        basis, selected, uow, caller, runtime = self._input(
            s, ctx, product_id, basis, selected, write
        )
        paired_storage._guard_uow(s, saved.uow, ctx, saved.caller_sha256)
        _require(
            saved.product_id == product_id
            and saved.basis_sha256 == digest(_wire(basis))
            and saved.selected == selected
            and saved.write == write
            and saved.runtime == runtime
            and saved.result_sha256 == _handle_sha(previous),
            "PAIR_HANDLE_UNBOUND",
            503,
        )
        fresh = self.read(s, ctx, product_id, basis, selected, write=write)
        _require(
            fresh.output == previous.output
            and fresh.receipt_id == previous.receipt_id
            and fresh.structure == previous.structure
            and tuple(sorted((v.kind, v.basis_sha256) for v in fresh.host_gate.stamps))
            == tuple(sorted((v.kind, v.basis_sha256) for v in previous.host_gate.stamps))
            and fresh.host_gate.valid_until == previous.host_gate.valid_until
            and fresh.host_gate.time_constraints == previous.host_gate.time_constraints
            and fresh.host_gate.needs_review == previous.host_gate.needs_review,
        )
        self._finish(s, ctx, product_id, fresh.host_gate, uow, caller, runtime, write=write)
        return fresh


def configure(engine, paired_owner):
    """Explicit trusted startup only; no source/qualification publication."""
    old = getattr(engine, ATTRIBUTE, None)
    epoch = old.runtime["epoch"] + 1 if isinstance(old, PairedFollowupOwner) else 1
    owner = PairedFollowupOwner(engine, paired_owner, epoch=epoch)
    setattr(engine, ATTRIBUTE, owner)
    return owner


def configured(s):
    owner = getattr(s.get_bind(), ATTRIBUTE, None)
    return owner if isinstance(owner, PairedFollowupOwner) else None
