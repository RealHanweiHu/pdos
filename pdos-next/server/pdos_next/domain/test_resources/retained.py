"""Retained exact Start evidence, without a new execution or reservation.

The evaluation clock comes only from the immutable original Start row. Current
ACL, pointers, issuer epochs, source safety and physical/usage epochs are still
read today. The old window becoming past does not erase its performed history.
"""

from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.build_operational_facts.service import digest
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.measurement_evidence.verifier import fixed_run_sha256
from pdos_next.domain.supply_execution.service import _human
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_handoff import service as physical
from pdos_next.domain.verification_launch import service as launch
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product, now
from pdos_next.schemas.resource_readiness.contracts import Reservation
from pdos_next.service import Context

from . import service as resources
from .fingerprint_compatibility import FixedIssuerDependency, diagnose_legacy_single_dependency
from .models import TestResourceCurrent, TestResourceFact
from .schemas import TestPlanBinding, TestReservationResult

_FINGERPRINT_V2 = "test-resource-dependency-v2"


def _require(condition, code="RETAINED_EXECUTION_CHANGED"):
    if not condition:
        raise DomainError(code, "原执行的完整固定证明或当前读取依据无法核对。")


def _uow(s):
    # Reuse the actual active Session/root/SAVEPOINT ancestry reader. Import at
    # call time: retained is itself imported by the common registry at startup.
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow as actual_uow

    return actual_uow(s)


def _same_uow(s, captured, ctx, caller):
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow as actual_same_uow

    actual_same_uow(s, captured, ctx, caller)


def _one(s, model, *where):
    rows = list(
        s.scalars(
            select(model)
            .where(*where)
            .limit(2)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    _require(len(rows) == 1, "FORBIDDEN_SCOPE")
    return rows[0]


def _caller(s, ctx, product_id, *, write):
    _require(
        isinstance(ctx, Context) and ctx.actor_id == ctx.requester_id and ctx.run_id is None,
        "NAMED_DECISION_REQUIRED",
    )
    product = _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == product_id)
    person = _one(s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.actor_id)
    grant = _one(
        s,
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.product_id == product_id,
        Grant.principal_id == ctx.actor_id,
    )
    _require(
        person.active is True and person.kind == "human" and (not write or grant.can_write is True),
        "FORBIDDEN_SCOPE",
    )
    # This is the *current consumer* deadline, not the historical execution
    # window or the old professional qualification's natural end.
    _require(grant.expires_at is not None and grant.expires_at > now(), "FORBIDDEN_SCOPE")
    stamp = digest(
        {
            "product": [
                product.id,
                product.tenant_id,
                product.revision,
                product.lifecycle_epoch,
                product.status,
                product.owner_id,
            ],
            "person": [
                person.id,
                person.tenant_id,
                person.active,
                person.kind,
                person.access_epoch,
            ],
            "grant": [
                grant.id,
                grant.tenant_id,
                grant.product_id,
                grant.principal_id,
                grant.can_write,
                grant.expires_at,
                grant.access_epoch,
            ],
        }
    )
    return stamp, grant.expires_at


def _runtime(s):
    # quality_result_bridge imports retained itself; resolve its actual complete
    # registry/security/store/bridge stamp lazily after startup is initialized.
    from pdos_next.quality_result_bridge import _runtime_stamp

    return _runtime_stamp(s)


def _fixed_dependency(s, ctx, product_id, binding, bundle):
    # Refresh real pointer/fact identities before delegating all original
    # scope/current/hash checks to the actual resource owner.
    _one(
        s,
        TestResourceCurrent,
        TestResourceCurrent.tenant_id == ctx.tenant_id,
        TestResourceCurrent.product_id == product_id,
        TestResourceCurrent.run_id == binding.run_id,
    )
    _one(
        s,
        TestResourceFact,
        TestResourceFact.tenant_id == ctx.tenant_id,
        TestResourceFact.product_id == product_id,
        TestResourceFact.id == bundle.fact_ref.id,
        TestResourceFact.revision == bundle.fact_ref.revision,
    )
    pointer, fact = resources._current(s, ctx, product_id, binding.run_id)
    _require(
        pointer is not None
        and fact is not None
        and fact.id == bundle.fact_ref.id
        and fact.revision == bundle.fact_ref.revision
        and fact.fact_sha256 == bundle.fact_ref.sha256
        and pointer.epoch == bundle.fact_ref.epoch
        and fact.project_id == binding.project_id
        and fact.state == "active"
        and resources._visible(fact, ctx)
        and fact.nature == bundle.fact_ref.nature
        and fact.binding == binding.model_dump(mode="json")
    )
    issuer = getattr(s.get_bind(), "_pdos_test_resource_issuers", {}).get(fact.issuer_key)
    issuer = resources._issuer(s, ctx, product_id, binding.project_id, issuer)
    epochs = getattr(s.get_bind(), "_pdos_test_resource_issuer_epochs", {})
    _require(
        type(epochs) is dict
        and type(epochs.get(fact.issuer_key)) is int
        and type(fact.issuer_epoch) is int
        and type(issuer.epoch) is int
        and epochs[fact.issuer_key] == fact.issuer_epoch == issuer.epoch
        and issuer.epoch > 0
        and issuer.key == fact.issuer_key
        and issuer.version == fact.issuer_version
        and issuer.nature == fact.nature
    )
    return FixedIssuerDependency(
        tenant_id=ctx.tenant_id,
        product_id=product_id,
        project_id=binding.project_id,
        fact_id=fact.id,
        fact_revision=fact.revision,
        fact_sha256=fact.fact_sha256,
        current_epoch=pointer.epoch,
        issuer_key=issuer.key,
        issuer_version=issuer.version,
        issuer_epoch=issuer.epoch,
        issuer_project_id=issuer.project_id,
        nature=issuer.nature,
    )


def _reservation_result(ctx, product_id, original, binding, request, existing):
    saved = TestReservationResult.model_validate(original.input_snapshot["reservation"])
    kernel = Reservation.model_validate(existing.reservation)
    from pdos_next.domain.resource_readiness.rules import semantic_digest

    _require(
        saved.owner_run_id == binding.run_id
        and saved.reservation_id == existing.id == kernel.id
        and kernel.revision == existing.revision
        and kernel.state == existing.state == "formal"
        and kernel.scope.tenant_id == ctx.tenant_id
        and kernel.scope.product_id == product_id
        and kernel.scope.project_id == binding.project_id
        and kernel.request == request
        and kernel.semantic_digest == semantic_digest(request)
        and existing.tenant_id == ctx.tenant_id
        and existing.product_id == product_id
        and existing.project_id == binding.project_id
        and existing.build_id == binding.build_id
        and existing.run_id == binding.run_id
        and existing.intent_digest == original.intent_digest
        and existing.binding == binding.model_dump(mode="json")
        and digest(existing.reservation) == existing.reservation_sha256
        and digest(kernel.model_dump(mode="json")) == existing.reservation_sha256
        and original.input_snapshot["resource_facts_revision"]
        == saved.facts_revision
        == existing.facts_revision
    )
    _require(
        len(saved.occupancy_ids) == len(set(saved.occupancy_ids))
        and len(saved.sample_usage_ids) == len(set(saved.sample_usage_ids))
    )
    return saved


def _effect_ids(saved, effects):
    occupied = [UUID(value["id"]) for value in effects["occupancy"]]
    used = [UUID(value["id"]) for value in effects["sample_usage"]]
    _require(
        len(occupied) == len(set(occupied)) == len(saved.occupancy_ids)
        and set(occupied) == set(saved.occupancy_ids)
        and len(used) == len(set(used)) == len(saved.sample_usage_ids)
        and set(used) == set(saved.sample_usage_ids)
    )


def _legacy_revision(s, ctx, product_id, original, binding, bundle, existing, saved, collected):
    _require(
        "resource_dependency_proof" not in original.input_snapshot
        and "resource_fingerprint_version" not in original.input_snapshot
    )
    _require(len(collected) == 1)
    fixed = _fixed_dependency(s, ctx, product_id, binding, bundle)

    def verify(value):
        _require(_fixed_dependency(s, ctx, product_id, binding, bundle) == value)

    diagnostic = diagnose_legacy_single_dependency(
        collected[0],
        fixed=fixed,
        original_saved_facts_revision=original.input_snapshot["resource_facts_revision"],
        reservation_saved_facts_revision=existing.facts_revision,
        original_reservation_facts_revision=saved.facts_revision,
        verify_fixed_issuer=verify,
    )
    _require(
        diagnostic.current_facts_revision == bundle.facts_revision
        and diagnostic.candidate_matches_saved is True
    )
    # Preserve the originally saved identity. Never re-seal the original Start,
    # reservation/result, source, fact, issuer map or full failure proof.
    return diagnostic.original_saved_facts_revision, fixed


def _saved_fingerprint(original):
    """Select only the explicit saved schema, without inferring from a hash."""
    snapshot = original.input_snapshot
    _require(type(snapshot) is dict)
    present = (
        "resource_fingerprint_version" in snapshot,
        "resource_dependency_proof" in snapshot,
    )
    if not any(present):
        return None, None
    version = snapshot.get("resource_fingerprint_version")
    if not all(present) or type(version) is not str or version != _FINGERPRINT_V2:
        raise DomainError("INTEGRATION_REQUIRED", "明确保存版本缺少对应完整资源证明宿主。", 503)
    verifier = getattr(resources, "_verify_stored_fingerprint_v2", None)
    if not callable(verifier):
        raise DomainError("INTEGRATION_REQUIRED", "明确保存版本缺少完整资源证明核对端口。", 503)
    proof = verifier(snapshot["resource_dependency_proof"])
    _require(
        proof["schema_version"] == version
        and proof["facts_revision"] == snapshot["resource_facts_revision"]
    )
    return version, proof


def _versioned_revision(original, binding, bundle, existing, collected, version, proof, fixed):
    """Match all stored owners and this single load; never reconstruct a saved proof."""
    fresh_version, fresh_proof = _saved_fingerprint(original)
    _require(fresh_version == version and fresh_proof == proof)
    _require(
        getattr(existing, "fingerprint_version", None) == version
        and type(getattr(existing, "dependency_proof", None)) is dict
        and len(collected) == 1
    )
    verifier = resources._verify_stored_fingerprint_v2
    stored = verifier(existing.dependency_proof)
    current = verifier(collected[0])
    _require(
        proof == stored == current
        and proof["facts_revision"] == existing.facts_revision == bundle.facts_revision
        and proof["material"]["binding"] == resources._fingerprint_json(binding)
        and proof["material"]["fact"] == bundle.fact_ref.sha256
        and proof["material"]["epoch"] == bundle.fact_ref.epoch
        and proof["material"]["issuer"]
        == {
            "key": fixed.issuer_key,
            "scope": {
                "tenant_id": str(fixed.tenant_id),
                "product_id": str(fixed.product_id),
                "project_id": str(fixed.issuer_project_id)
                if fixed.issuer_project_id is not None
                else None,
            },
            "version": fixed.issuer_version,
            "nature": fixed.nature,
            "epoch": fixed.issuer_epoch,
        }
    )
    return proof["facts_revision"]


def inspect_retained_execution(s, ctx, product_id, run_row, *, at=None, write=False):
    """Return affirmative retained evidence only after the whole original proof matches."""
    checked_at = resources._at(at)
    result = {
        "current": False,
        "reason_codes": [],
        "required_source_read_set": [],
        "source_basis": None,
        "facts_revision": None,
        "original_start_intent": None,
        "plan_binding": None,
        "reservation": None,
        "occupancy": [],
        "sample_usage": [],
        "nature": "retained_execution_evidence_not_current_execution_permission",
        "checked_at": checked_at.isoformat(),
    }
    try:
        captured_uow = _uow(s)
        with s.no_autoflush:
            _human(s, ctx, product_id, write=write)
            caller = digest(vars(ctx))
            caller_stamp, _ = _caller(s, ctx, product_id, write=write)
            runtime = _runtime(s)
            current_run, _ = launch._snapshot(run_row)
            if current_run.status == "planned":
                raise DomainError("RUN_NOT_STARTED", "尚未实际开测，不能形成历史执行证明。")
            original = launch._version(s, ctx, product_id, current_run.id, 2)
            saved_run, plan = launch._snapshot(original)
            if (
                original.operation != "test.run.start"
                or saved_run.actual_start is None
                or original.created_at is None
                or original.created_at > checked_at
            ):
                raise DomainError("RUN_START_PROOF_INVALID", "原始开测身份或保存时点无法核对。")
            fingerprint_version, dependency_proof = _saved_fingerprint(original)
            binding = TestPlanBinding.model_validate(original.input_snapshot["plan_binding"])
            if (
                binding.run_id != current_run.id
                or current_run.request_id != saved_run.request_id
                or run_row.request_version_id != original.request_version_id
                or run_row.request_revision != original.request_revision
                or run_row.execution_plan != original.execution_plan
                or current_run.actual_start != saved_run.actual_start
                or fixed_run_sha256(current_run, plan) != fixed_run_sha256(saved_run, plan)
            ):
                raise DomainError(
                    "RUN_START_PROOF_INVALID", "当前结果不能改写原接收范围、计划或实际开始。"
                )
            if not binding.window.start <= original.created_at < binding.window.finish:
                raise DomainError("RUN_START_PROOF_INVALID", "保存的实际开测不在原完整执行窗口。")
            maker_fact = _one(
                s,
                TestResourceFact,
                TestResourceFact.tenant_id == ctx.tenant_id,
                TestResourceFact.product_id == product_id,
                TestResourceFact.id == plan.resource_fact_id,
                TestResourceFact.revision == plan.expected_resource_fact_revision,
            )
            _require(
                maker_fact.project_id == binding.project_id and maker_fact.run_id == binding.run_id
            )
            reader_ids = {
                ctx.requester_id,
                UUID(original.authority_snapshot["subject_id"]),
                maker_fact.owner_id,
            }
            live_readers = {ctx.requester_id: (ctx, caller_stamp)}
            for person_id in sorted(reader_ids - {ctx.requester_id}, key=str):
                reader = Context(ctx.tenant_id, person_id, person_id)
                reader_stamp, _ = _caller(s, reader, product_id, write=False)
                live_readers[person_id] = (reader, reader_stamp)
            basis, _ = physical._basis(
                s, ctx, product_id, original.required_source_read_set, original.sources
            )
            if basis != original.source_basis:
                raise DomainError("SOURCE_STALE", "原开测来源、安全或访问 epoch 已改变。")
            historical = front._recheck(
                s,
                ctx,
                product_id,
                original.project_id,
                original.authority_snapshot,
                at=original.created_at,
            )
            if not historical["current"]:
                raise DomainError("SOURCE_STALE", "原开测人的职责、资格或签发 epoch 已改变。")
            # The full existing evaluator checks current pointer/issuer/physical epochs,
            # exact own occupancy and sample usage, with qualification at the saved
            # Start clock. No sentinel is created and no reserve/stage method is called.
            collected = []
            fingerprint_options = (
                {"_fingerprint_version": fingerprint_version} if fingerprint_version else {}
            )
            bundle, _, request, _, _, _, reservation = resources._load(
                s,
                ctx,
                product_id,
                binding,
                plan.resource_fact_id,
                plan.expected_resource_fact_revision,
                at=original.created_at,
                write=False,
                retained=True,
                retained_authority=original.authority_snapshot,
                verified_actual_start=saved_run.actual_start,
                own_intent=original.intent_digest,
                _fingerprint_collector=collected,
                **fingerprint_options,
            )
            if (
                reservation is None
                or reservation.intent_digest != original.intent_digest
                or bundle.report.status not in {"READY", "READY_WITH_CONDITIONS"}
            ):
                raise DomainError(
                    "RETAINED_EXECUTION_CHANGED", "原执行依据或消费归属已变化，结果须待重核。"
                )
            saved = _reservation_result(ctx, product_id, original, binding, request, reservation)
            retained_revision, fixed = bundle.facts_revision, None
            if fingerprint_version is not None:
                fixed = _fixed_dependency(s, ctx, product_id, binding, bundle)
                retained_revision = _versioned_revision(
                    original,
                    binding,
                    bundle,
                    reservation,
                    collected,
                    fingerprint_version,
                    dependency_proof,
                    fixed,
                )
            else:
                _require(
                    getattr(reservation, "fingerprint_version", None) is None
                    and getattr(reservation, "dependency_proof", None) is None
                )
            if (
                fingerprint_version is None
                and retained_revision != original.input_snapshot["resource_facts_revision"]
            ):
                retained_revision, fixed = _legacy_revision(
                    s, ctx, product_id, original, binding, bundle, reservation, saved, collected
                )
            effects = launch._saved_effects(s, ctx, product_id, original)
            _effect_ids(saved, effects)
            # Effects/source readers may perform IO or invoke live callbacks. Recheck
            # the original current safety/issuer evidence after *all* those reads.
            final_basis, _ = physical._basis(
                s, ctx, product_id, original.required_source_read_set, original.sources
            )
            _require(final_basis == basis, "SOURCE_STALE")
            final_authority = front._recheck(
                s,
                ctx,
                product_id,
                original.project_id,
                original.authority_snapshot,
                at=original.created_at,
            )
            _require(
                final_authority.get("current") is True and final_authority == historical,
                "SOURCE_STALE",
            )
            if fixed is not None:
                _require(_fixed_dependency(s, ctx, product_id, binding, bundle) == fixed)
            deadlines = []
            for person_id in sorted(live_readers, key=str):
                reader, stamp = live_readers[person_id]
                fresh_stamp, deadline = _caller(
                    s, reader, product_id, write=write if reader is ctx else False
                )
                _require(fresh_stamp == stamp, "SOURCE_STALE")
                deadlines.append(deadline)
            _require(_runtime(s) == runtime, "SOURCE_STALE")
            _same_uow(s, captured_uow, ctx, caller)
            if fingerprint_version is not None:
                # Pure validation after all owner/caller IO catches a changed saved
                # JSON/row/result/collector. The final access clock follows it.
                final_saved = _reservation_result(
                    ctx, product_id, original, binding, request, reservation
                )
                _effect_ids(final_saved, effects)
                _require(
                    _versioned_revision(
                        original,
                        binding,
                        bundle,
                        reservation,
                        collected,
                        fingerprint_version,
                        dependency_proof,
                        fixed,
                    )
                    == retained_revision
                )
            final_clock = now()  # No IO after these current-access expiry boundaries.
            _require(all(final_clock < deadline for deadline in deadlines), "FORBIDDEN_SCOPE")
            result.update(
                current=True,
                required_source_read_set=_merge_reads(
                    original.required_source_read_set,
                    [v.model_dump(mode="json") for v in bundle.required_source_read_set],
                ),
                source_basis=basis,
                facts_revision=retained_revision,
                original_start_intent=original.intent_digest,
                original_start_version_id=str(original.id),
                original_start_revision=original.revision,
                saved_start_at=original.created_at.isoformat(),
                actual_start=saved_run.actual_start.model_dump(mode="json"),
                plan_binding=binding.model_dump(mode="json"),
                reservation=original.input_snapshot["reservation"],
                occupancy=effects["occupancy"],
                sample_usage=effects["sample_usage"],
                source_nature=bundle.nature,
                execution_window_elapsed=final_clock >= binding.window.finish,
            )
    except DomainError as error:
        result["reason_codes"] = [error.code]
    except (KeyError, TypeError, ValueError):
        result["reason_codes"] = ["RUN_START_PROOF_INVALID"]
    return result
