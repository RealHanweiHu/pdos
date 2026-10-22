"""Retained exact Start evidence, without a new execution or reservation.

The evaluation clock comes only from the immutable original Start row. Current
ACL, pointers, issuer epochs, source safety and physical/usage epochs are still
read today. The old window becoming past does not erase its performed history.
"""

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.domain.build_operational_facts.service import digest
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.measurement_evidence.verifier import fixed_run_sha256
from pdos_next.domain.supply_execution.service import _human
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_handoff import service as physical
from pdos_next.domain.verification_launch import service as launch
from pdos_next.errors import DomainError
from pdos_next.models import now
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


def _one(s, ctx, model, *where, scope_id=None, fresh=False):
    query = (
        select(model)
        .where(*where)
        .limit(2)
        .execution_options(populate_existing=True, autoflush=False)
    )
    held = False
    if isinstance(s, Session):
        from pdos_next.database import require_context
        from pdos_next.request_proof import scope_is_held

        require_context(s, ctx)
        if s.is_active is True and s.in_transaction():
            # The reader itself rejects a dirty RR transaction; a command with
            # pending ORM state falls back to its original actual SQL.
            held = scope_is_held(s, scope_id)
    if held and not fresh:
        from pdos_next.request_proof import snapshot_rows

        # The same exact dependency is checked repeatedly by retained and
        # result owners. RR fixes its rows; the actual Product gate fences all
        # writes to these pointers/facts. Only exact raw rows are shared, while
        # every caller still checks the complete fact, hash and binding.
        compiled = query.compile()
        key = (
            model,
            digest(vars(ctx)),
            digest(s.info.get("scope")),
            str(compiled),
            json.dumps(compiled.params, sort_keys=True, default=str),
        )
        rows = snapshot_rows(s, key, query, scope_id=scope_id)
    else:
        rows = list(s.scalars(query))
    _require(len(rows) == 1, "FORBIDDEN_SCOPE")
    return rows[0]


def _caller(s, ctx, product_id, *, write):
    _require(
        isinstance(ctx, Context) and ctx.actor_id == ctx.requester_id and ctx.run_id is None,
        "NAMED_DECISION_REQUIRED",
    )
    from pdos_next.domain.professional_authority.service import _subject_access
    from pdos_next.service import require_access

    product = require_access(s, ctx, product_id, write=write, lock=write)
    person, grant = _subject_access(s, ctx, product_id, ctx.requester_id)
    _require(person is not None and grant is not None, "FORBIDDEN_SCOPE")
    _require(
        person.active is True and person.kind == "human" and (not write or grant.can_write is True),
        "FORBIDDEN_SCOPE",
    )
    # This is the *current consumer* deadline, not the historical execution
    # window or the old professional qualification's natural end.
    _require((grant.expires_at is None or grant.expires_at > now()), "FORBIDDEN_SCOPE")
    stamp = digest(
        {
            "product": [
                product.id,
                product.tenant_id,
                product.category_id,
                product.visibility,
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
                grant.category_id,
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


def _fixed_dependency(s, ctx, product_id, binding, bundle, *, fresh=False):
    # Refresh real pointer/fact identities before delegating all original
    # scope/current/hash checks to the actual resource owner.
    if not fresh and (
        resources._canonical_rr(s) or resources._held_owner_scope(s, ctx, product_id) is not None
    ):
        pointers = resources._current_rows(s, ctx, product_id, binding.run_id)
        _require(len(pointers) == 1, "FORBIDDEN_SCOPE")
    else:
        _one(
            s,
            ctx,
            TestResourceCurrent,
            TestResourceCurrent.tenant_id == ctx.tenant_id,
            TestResourceCurrent.product_id == product_id,
            TestResourceCurrent.run_id == binding.run_id,
            scope_id=product_id,
            fresh=fresh,
        )
    _one(
        s,
        ctx,
        TestResourceFact,
        TestResourceFact.tenant_id == ctx.tenant_id,
        TestResourceFact.product_id == product_id,
        TestResourceFact.id == bundle.fact_ref.id,
        TestResourceFact.revision == bundle.fact_ref.revision,
        scope_id=product_id,
        fresh=fresh,
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
    # Some command owners request read permission while already holding their
    # writer's Product gate. Their final SQL must stay actual as well.
    terminal_fresh = write or (isinstance(s, Session) and s.info.get("read_snapshot") is not True)
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
    if (
        type(getattr(run_row, "input_snapshot", None)) is dict
        and run_row.input_snapshot.get("execution_proof_contract") == _DIRECT_EXECUTION_CONTRACT
    ):
        return _inspect_retained_direct(
            s, ctx, product_id, run_row, result, checked_at=checked_at, write=write
        )
    try:
        captured_uow = _uow(s)
        with s.no_autoflush, resources._maker_fact_scope(s):
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
                type(original.input_snapshot) is dict
                and original.input_snapshot.get("execution_proof_contract")
                == _DIRECT_EXECUTION_CONTRACT
            ):
                # A result cannot strip the server contract to select legacy proof.
                return _inspect_retained_direct(
                    s,
                    ctx,
                    product_id,
                    run_row,
                    result,
                    checked_at=checked_at,
                    write=write,
                    original=original,
                )
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
                ctx,
                TestResourceFact,
                TestResourceFact.tenant_id == ctx.tenant_id,
                TestResourceFact.product_id == product_id,
                TestResourceFact.id == plan.resource_fact_id,
                TestResourceFact.revision == plan.expected_resource_fact_revision,
                scope_id=product_id,
            )
            _require(
                maker_fact.project_id == binding.project_id and maker_fact.run_id == binding.run_id
            )
            resources._remember_maker_fact(
                s,
                ctx,
                product_id,
                binding.run_id,
                maker_fact,
                identity=plan.resource_fact_id,
                revision=plan.expected_resource_fact_revision,
            )
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
            effects = (
                launch._saved_effects(s, ctx, product_id, original, fresh=True)
                if terminal_fresh
                else launch._saved_effects(s, ctx, product_id, original)
            )
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
                # Raw text/Connection writes in this very transaction do not
                # trigger the ORM proof invalidators and do not wait on our own
                # Product gate. Keep both final row reads actual for a writer.
                _require(
                    _fixed_dependency(s, ctx, product_id, binding, bundle, fresh=terminal_fresh)
                    == fixed
                )
            fresh_stamp, deadline = _caller(s, ctx, product_id, write=write)
            _require(fresh_stamp == caller_stamp, "SOURCE_STALE")
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
            _require(deadline is None or final_clock < deadline, "FORBIDDEN_SCOPE")
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
        result["reason_codes"] = [error.reason]
    except (KeyError, TypeError, ValueError):
        result["reason_codes"] = ["RUN_START_PROOF_INVALID"]
    return result


_DIRECT_EXECUTION_CONTRACT = "s0-direct-v1"
_DIRECT_EXECUTION_KEYS = (
    "execution_proof_contract",
    "direct_material_sha256",
    "plan_binding",
    "resource_facts_revision",
    "reservation",
    "resource_fingerprint_version",
    "resource_dependency_proof",
    "direct_watermark",
    "direct_source_basis",
)


def direct_execution_sha256(raw):
    """Seal fixed server Start material; never a current authority proof."""
    _require(type(raw) is dict, "RUN_START_PROOF_INVALID")
    return digest({key: raw[key] for key in _DIRECT_EXECUTION_KEYS})


def _direct_material(original, run_row):
    raw = original.input_snapshot
    _require(type(raw) is dict and type(run_row.input_snapshot) is dict, "RUN_START_PROOF_INVALID")
    _require(
        raw.get("execution_proof_contract") == _DIRECT_EXECUTION_CONTRACT, "RUN_START_PROOF_INVALID"
    )
    seal = direct_execution_sha256(raw)
    _require(raw.get("direct_execution_sha256") == seal, "RUN_START_PROOF_INVALID")
    _require(
        run_row.input_snapshot.get("direct_execution_sha256") == seal
        and all(run_row.input_snapshot.get(key) == raw[key] for key in _DIRECT_EXECUTION_KEYS),
        "RUN_START_PROOF_INVALID",
    )
    preview_hash = raw["direct_material_sha256"]
    _require(
        type(preview_hash) is str
        and len(preview_hash) == 64
        and all(c in "0123456789abcdef" for c in preview_hash),
        "RUN_START_PROOF_INVALID",
    )
    return seal


def _direct_sources(s, ctx, product_id, original):
    from pdos_next.domain.professional_authority.schemas import DefinitionReference
    from pdos_next.domain.quality_execution.evidence import merge_reads, refs_from_exact
    from pdos_next.source_current import direct_source_basis

    refs = refs_from_exact(
        s, ctx, product_id, tuple(DefinitionReference.model_validate(v) for v in original.sources)
    )
    reads = merge_reads(original.required_source_read_set)
    basis, _ = direct_source_basis(s, ctx, product_id, refs, reads)
    _require(
        reads
        == merge_reads(
            [
                {"artifact_id": entry["id"], "expected_revision": entry["revision"]}
                for entry in basis
            ]
        ),
        "RUN_START_PROOF_INVALID",
    )
    _require(
        basis == original.source_basis == original.input_snapshot["direct_source_basis"],
        "SOURCE_STALE",
    )
    return reads, basis


def _direct_runtime(s, *, originals):
    from pdos_next import original_security, source_current
    from pdos_next import originals as original_owner
    from pdos_next import service as common
    from pdos_next.domain.quality_execution import evidence

    ports = (
        launch._snapshot,
        launch._saved_start_fingerprint,
        launch._saved_effects,
        resources._verify_stored_fingerprint_v2,
        resources._fact_hash,
        evidence.refs_from_exact,
        evidence.check_source,
        evidence.source_basis,
        evidence.source_for,
        common.source_for,
        source_current.direct_source_basis,
        original_owner.require_original,
        original_security.require_safe,
    )
    # No historical professional/resource issuer registry participates. These
    # are only the actual consumed ports and direct-source security runtime.
    return (
        s.get_bind(),
        tuple((value, getattr(value, "__code__", None)) for value in ports),
        getattr(s.get_bind(), "_pdos_security_runtime", None) if originals else None,
    )


def _direct_caller(s, ctx, product_id, *, write, fresh=False):
    if fresh:
        from pdos_next.models import Grant, Principal, Product

        product = _one(
            s,
            ctx,
            Product,
            Product.tenant_id == ctx.tenant_id,
            Product.id == product_id,
            scope_id=product_id,
            fresh=True,
        )
        rows = list(
            s.execute(
                select(Principal, Grant)
                .join(
                    Grant,
                    (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
                )
                .where(
                    Principal.tenant_id == ctx.tenant_id,
                    Principal.id == ctx.requester_id,
                    Grant.category_id == product.category_id,
                )
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        _require(len(rows) == 1, "FORBIDDEN_SCOPE")
        person, grant = rows[0]
        _require(
            person.active is True
            and person.kind == "human"
            and (not write or grant.can_write is True)
            and (grant.expires_at is None or grant.expires_at > now()),
            "FORBIDDEN_SCOPE",
        )
        # Refresh the actual mapped rows used by the original access cache;
        # this reader never saves a new positive authority conclusion.
    return _caller(s, ctx, product_id, write=write)


def _direct_fixed_fact(s, ctx, product_id, original, plan, binding, proof, *, fresh=False):
    from .schemas import TestResourceFactInput

    fact = _one(
        s,
        ctx,
        TestResourceFact,
        TestResourceFact.tenant_id == ctx.tenant_id,
        TestResourceFact.product_id == product_id,
        TestResourceFact.id == plan.resource_fact_id,
        TestResourceFact.revision == plan.expected_resource_fact_revision,
        scope_id=product_id,
        fresh=fresh,
    )
    data = TestResourceFactInput.model_validate(fact.data)
    _require(
        (
            fact.project_id,
            fact.build_id,
            fact.run_id,
            fact.request_id,
            fact.accepted_request_id,
            fact.accepted_request_revision,
        )
        == (
            binding.project_id,
            binding.build_id,
            binding.run_id,
            binding.request_id,
            binding.accepted_request_id,
            binding.accepted_request_revision,
        )
        and fact.binding == binding.model_dump(mode="json")
        and data.binding == binding
        and resources._fact_hash(fact) == fact.fact_sha256 == proof["material"]["fact"]
        and resources._visible(fact, ctx)
        and proof["material"]["issuer"]
        == {
            "key": fact.issuer_key,
            "scope": {
                "tenant_id": str(ctx.tenant_id),
                "product_id": str(product_id),
                "project_id": str(binding.project_id),
            },
            "version": fact.issuer_version,
            "nature": fact.nature,
            "epoch": fact.issuer_epoch,
        }
        and proof["material"]["issuer_epochs"] == {fact.issuer_key: fact.issuer_epoch}
        and proof["material"]["authority"] == original.authority_snapshot,
    )
    watermark = original.input_snapshot["direct_watermark"]["resource"]["resource"]
    _require(
        watermark
        == [
            str(ctx.tenant_id),
            str(product_id),
            str(binding.project_id),
            str(binding.build_id),
            str(binding.run_id),
            str(binding.request_id),
            str(fact.id),
            fact.revision,
            proof["material"]["epoch"],
            fact.fact_sha256,
        ]
    )
    # No current pointer, old signer, natural historical TTL or free capacity
    # can reinterpret these physically fixed execution facts.
    return fact, data


def _direct_own_effects(
    s, ctx, product_id, original, binding, request, reservation, saved, reads, *, fresh
):
    from pdos_next.domain.build_operational_facts.models import ResourceOccupancy
    from pdos_next.domain.quality_execution.evidence import merge_reads

    from .models import SampleRunUsage

    occupied = resources._owned_rows(
        s,
        ctx,
        product_id,
        select(ResourceOccupancy).where(
            ResourceOccupancy.tenant_id == ctx.tenant_id,
            ResourceOccupancy.owner_kind == "test_run",
            ResourceOccupancy.owner_execution_id == binding.run_id,
        ),
        fresh=fresh,
    )
    usages = resources._owned_rows(
        s,
        ctx,
        product_id,
        select(SampleRunUsage).where(
            SampleRunUsage.tenant_id == ctx.tenant_id,
            SampleRunUsage.product_id == product_id,
            SampleRunUsage.run_id == binding.run_id,
        ),
        fresh=fresh,
    )
    _require(
        len(occupied) == len(request.uses)
        and len({row.id for row in occupied}) == len(saved.occupancy_ids)
        and {row.id for row in occupied} == set(saved.occupancy_ids),
        "RUN_RESERVATION_MISSING",
    )
    actual = {
        (
            row.tenant_id,
            row.product_id,
            row.project_id,
            row.build_id,
            row.owner_kind,
            row.owner_execution_id,
            row.test_run_id,
            row.build_start_id,
            row.asset_id,
            row.resource_id,
            row.resource_revision,
            row.units,
            row.window_start,
            row.window_finish,
            row.intent_digest,
            digest(row.reservation),
        )
        for row in occupied
    }
    expected = {
        (
            ctx.tenant_id,
            product_id,
            binding.project_id,
            binding.build_id,
            "test_run",
            binding.run_id,
            binding.run_id,
            None,
            use.resource.id,
            use.resource.id,
            use.resource.revision,
            use.units,
            binding.window.start,
            binding.window.finish,
            original.intent_digest,
            reservation.reservation_sha256,
        )
        for use in request.uses
    }
    _require(actual == expected, "RUN_RESERVATION_MISSING")
    _require(
        len(usages) == len({p.sample.id for p in binding.pairs})
        and len({row.id for row in usages}) == len(saved.sample_usage_ids)
        and {row.id for row in usages} == set(saved.sample_usage_ids),
        "RUN_SAMPLE_USAGE_MISSING",
    )
    for identity in {pair.sample.id for pair in binding.pairs}:
        matches = [row for row in usages if row.sample_id == identity]
        _require(len(matches) == 1, "RUN_SAMPLE_USAGE_MISSING")
        row = matches[0]
        pairs = [pair for pair in binding.pairs if pair.sample.id == identity]
        sample, destructive = pairs[0].sample, any(pair.destructive for pair in pairs)
        _require(
            (
                row.tenant_id,
                row.product_id,
                row.project_id,
                row.build_id,
                row.run_id,
                row.owner_id,
                row.visibility,
                row.revision,
                row.intent_digest,
                row.sample_revision,
                row.actual_configuration_id,
                row.actual_configuration_revision,
                row.window_start,
                row.window_finish,
                row.destructive,
                row.state,
            )
            == (
                ctx.tenant_id,
                product_id,
                binding.project_id,
                binding.build_id,
                binding.run_id,
                original.writer_id,
                original.visibility,
                1,
                original.intent_digest,
                sample.revision,
                sample.actual_configuration.id,
                sample.actual_configuration.revision,
                binding.window.start,
                binding.window.finish,
                destructive,
                "consumed" if destructive else "reserved",
            )
            and row.coverage
            == [{"sample_id": str(pair.sample.id), "item_id": pair.item_id} for pair in pairs]
            and row.source_basis
            == {
                "actual_start": {
                    key: original.run_snapshot["actual_start"][key]
                    for key in ("occurred_at", "original_timezone", "source", "effective_at")
                },
                "pairs": [pair.model_dump(mode="json") for pair in pairs],
                "facts_revision": saved.facts_revision,
            }
            and merge_reads(row.required_source_read_set) == reads,
            "RUN_SAMPLE_USAGE_MISSING",
        )
    _require(merge_reads(reservation.required_source_read_set) == reads, "RUN_RESERVATION_MISSING")
    return digest(
        {
            "occupied": [
                {
                    key: getattr(row, key)
                    for key in (
                        "id",
                        "tenant_id",
                        "product_id",
                        "project_id",
                        "build_id",
                        "owner_execution_id",
                        "owner_kind",
                        "build_start_id",
                        "test_run_id",
                        "asset_id",
                        "resource_id",
                        "resource_revision",
                        "units",
                        "window_start",
                        "window_finish",
                        "intent_digest",
                        "reservation",
                    )
                }
                for row in sorted(occupied, key=lambda row: row.resource_id.bytes)
            ],
            "usage": [
                {
                    key: getattr(row, key)
                    for key in (
                        "id",
                        "tenant_id",
                        "product_id",
                        "project_id",
                        "build_id",
                        "run_id",
                        "sample_id",
                        "sample_revision",
                        "actual_configuration_id",
                        "actual_configuration_revision",
                        "owner_id",
                        "visibility",
                        "revision",
                        "destructive",
                        "state",
                        "window_start",
                        "window_finish",
                        "coverage",
                        "intent_digest",
                        "source_basis",
                        "required_source_read_set",
                    )
                }
                for row in sorted(usages, key=lambda row: row.sample_id.bytes)
            ],
        }
    )


def _inspect_retained_direct(
    s, ctx, product_id, run_row, result, *, checked_at, write, original=None
):
    """Current consumer of fixed execution, without historical closure reproof."""
    from pdos_next.database import require_context

    from .models import TestResourceReservation

    try:
        captured, caller = _uow(s), digest(vars(ctx))
        require_context(s, ctx)
        terminal_fresh = write or s.info.get("read_snapshot") is not True
        with s.no_autoflush:
            _human(s, ctx, product_id, write=write)
            caller_stamp, _ = _direct_caller(s, ctx, product_id, write=write)
            current_run, _ = launch._snapshot(run_row)
            _require(current_run.status != "planned", "RUN_NOT_STARTED")
            original = original or launch._version(s, ctx, product_id, current_run.id, 2)
            saved_run, plan = launch._snapshot(original)
            _require(
                original.operation == "test.run.start"
                and saved_run.actual_start is not None
                and original.created_at is not None
                and original.created_at <= checked_at,
                "RUN_START_PROOF_INVALID",
            )
            seal = _direct_material(original, run_row)
            binding = TestPlanBinding.model_validate(original.input_snapshot["plan_binding"])
            _require(
                binding.run_id == current_run.id
                and binding.executor_id == original.writer_id
                and current_run.request_id == saved_run.request_id
                and run_row.request_version_id == original.request_version_id
                and run_row.request_revision == original.request_revision
                and run_row.execution_plan == original.execution_plan
                and current_run.actual_start == saved_run.actual_start
                and fixed_run_sha256(current_run, plan) == fixed_run_sha256(saved_run, plan)
                and binding.window.start <= original.created_at < binding.window.finish,
                "RUN_START_PROOF_INVALID",
            )
            reservation = _one(
                s,
                ctx,
                TestResourceReservation,
                TestResourceReservation.tenant_id == ctx.tenant_id,
                TestResourceReservation.product_id == product_id,
                TestResourceReservation.run_id == binding.run_id,
                scope_id=product_id,
            )
            version, proof = launch._saved_start_fingerprint(
                s, ctx, product_id, original, reservation=reservation
            )
            _require(version == _FINGERPRINT_V2 and proof is not None, "RUN_START_PROOF_INVALID")
            fact, data = _direct_fixed_fact(s, ctx, product_id, original, plan, binding, proof)
            request = resources._request(binding, data)
            saved = _reservation_result(ctx, product_id, original, binding, request, reservation)
            originals = any(
                "original" in entry for entry in original.input_snapshot["direct_source_basis"]
            )
            runtime = _direct_runtime(s, originals=originals)
            reads, basis = _direct_sources(s, ctx, product_id, original)
            effects = launch._saved_effects(s, ctx, product_id, original, fresh=terminal_fresh)
            _effect_ids(saved, effects)
            own = _direct_own_effects(
                s,
                ctx,
                product_id,
                original,
                binding,
                request,
                reservation,
                saved,
                reads,
                fresh=terminal_fresh,
            )
            final_reads, final_basis = _direct_sources(s, ctx, product_id, original)
            _require(final_reads == reads and final_basis == basis, "SOURCE_STALE")
            # Non-RR terminal owner rows are actual after source IO. RR keeps its
            # real snapshot; every binding/hash/current consumer check reruns.
            if terminal_fresh:
                reservation = _one(
                    s,
                    ctx,
                    TestResourceReservation,
                    TestResourceReservation.tenant_id == ctx.tenant_id,
                    TestResourceReservation.product_id == product_id,
                    TestResourceReservation.run_id == binding.run_id,
                    scope_id=product_id,
                    fresh=True,
                )
                fresh_fact, _ = _direct_fixed_fact(
                    s, ctx, product_id, original, plan, binding, proof, fresh=True
                )
                _require(fresh_fact.fact_sha256 == fact.fact_sha256)
            _require(
                _direct_own_effects(
                    s,
                    ctx,
                    product_id,
                    original,
                    binding,
                    request,
                    reservation,
                    saved,
                    reads,
                    fresh=terminal_fresh,
                )
                == own
            )
            final_saved = _reservation_result(
                ctx, product_id, original, binding, request, reservation
            )
            _effect_ids(final_saved, effects)
            # Initial actual owner inspection already checked source and row
            # binding. The terminal pass is pure, after the last source IO and
            # actual own-row refresh; it cannot reopen historical issuer IO.
            final_version, final_proof = _saved_fingerprint(original)
            owned_version, owned_proof = resources._reservation_fingerprint(reservation)
            _require(owned_version == final_version and owned_proof == final_proof)
            _require(
                reservation.fact_id == fact.id
                and reservation.fact_revision == fact.revision
                and reservation.owner_id == original.writer_id
                and reservation.visibility == original.visibility
            )
            _require(
                final_version == version
                and final_proof == proof
                and _direct_material(original, run_row) == seal,
                "RUN_START_PROOF_INVALID",
            )
            fresh_stamp, deadline = _direct_caller(
                s, ctx, product_id, write=write, fresh=terminal_fresh
            )
            _require(fresh_stamp == caller_stamp, "SOURCE_STALE")
            _require(_direct_runtime(s, originals=originals) == runtime, "SOURCE_STALE")
            require_context(s, ctx)
            _same_uow(s, captured, ctx, caller)
            final_clock = now()
            _require(deadline is None or final_clock < deadline, "FORBIDDEN_SCOPE")
            result.update(
                current=True,
                required_source_read_set=reads,
                source_basis=basis,
                facts_revision=proof["facts_revision"],
                original_start_intent=original.intent_digest,
                original_start_version_id=str(original.id),
                original_start_revision=original.revision,
                saved_start_at=original.created_at.isoformat(),
                actual_start=saved_run.actual_start.model_dump(mode="json"),
                plan_binding=binding.model_dump(mode="json"),
                reservation=original.input_snapshot["reservation"],
                occupancy=effects["occupancy"],
                sample_usage=effects["sample_usage"],
                source_nature=fact.nature,
                execution_window_elapsed=final_clock >= binding.window.finish,
            )
    except DomainError as error:
        result["reason_codes"] = [error.reason]
    except (KeyError, TypeError, ValueError):
        result["reason_codes"] = ["RUN_START_PROOF_INVALID"]
    return result
