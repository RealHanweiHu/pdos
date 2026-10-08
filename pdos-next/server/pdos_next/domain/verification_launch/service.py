"""Fixed accepted Run plans and actual starts, using the delivered verification kernel.

Only the caller's Session is used. Resources, sample usage, both version pointers
and common receipt/audit/outbox share one transaction. A plan or a promise has
zero occupancy; no default scanner, professional qualification or resource fact.
"""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.contracts import Command
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.supply_execution.service import _human, _read_evidence, _sources
from pdos_next.domain.test_resources.schemas import TestPairBinding, TestPlanBinding
from pdos_next.domain.verification.handlers import semantic_digest
from pdos_next.domain.verification.ports import Invocation
from pdos_next.domain.verification.rules import (
    accepted_coverage,
    check_coverage,
    compute_results,
    document_gaps,
    pairs,
)
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.adapters import (
    METHOD_POSITION,
    PROFESSIONAL_PREFIX,
    authority_dto,
)
from pdos_next.domain.verification_front.models import (
    FormalVerificationRequest,
    MethodApplicability,
)
from pdos_next.domain.verification_handoff import service as physical
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Product, now
from pdos_next.schemas.verification.contracts import (
    ExecutionConditions,
    RunPlan,
    RunStart,
    SchedulePromise,
    TestRun,
)
from pdos_next.service import digest, source_for

from .adapters import LaunchCommands, LaunchSamples, kernel
from .models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from .schemas import ExecutionPlan, PlanPayload, PromisePayload, StartPayload

OPERATIONS = {
    "run_plan": "test.run.plan",
    "schedule_promise": "verification.schedule.promise",
    "run_start": "test.run.start",
}
PAYLOADS = {
    "test.run.plan": PlanPayload,
    "verification.schedule.promise": PromisePayload,
    "test.run.start": StartPayload,
}
EFFECT = "固定已接收范围与完整测试窗口；仅实际开测同事务占用资源/样件，不生成结果或专业处置。"
deduplicate_subject = {"verification_request", "test_run"}


def semantic(payload):
    value = payload.model_dump(mode="json", exclude={"confirmation_token"})
    value["sources"].sort(key=lambda ref: json.dumps(ref, sort_keys=True))
    if "coverage" in value:
        value["coverage"].sort(key=lambda ref: (ref["sample_id"], ref["item_id"]))
    if len(json.dumps(value, ensure_ascii=False).encode()) > 1_000_000:
        raise DomainError("INVALID_PAYLOAD", "开测输入超过1MB上限。", 422)
    return value


def request_subject(payload):
    return payload.run_id if isinstance(payload, StartPayload) else payload.request_id


def replay_subject_type(payload):
    return (
        "verification_request"
        if isinstance(payload, PromisePayload) and not isinstance(payload, StartPayload)
        else "test_run"
    )


def _intent(ctx, command, payload):
    return digest(
        {"operation": command.operation, "actor": ctx.requester_id, "payload": semantic(payload)}
    )


def _row(s, ctx, product_id, model, identity):
    row = s.scalar(
        select(model).where(
            model.tenant_id == ctx.tenant_id, model.product_id == product_id, model.id == identity
        )
    )
    if row is None or (row.visibility == "private" and row.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "测试办理对象不在当前可见产品范围。", 403)
    return row


def _current(s, ctx, product_id, run_id=None, *, request_id=None, lock=False):
    q = select(VerificationRunCurrent).where(
        VerificationRunCurrent.tenant_id == ctx.tenant_id,
        VerificationRunCurrent.product_id == product_id,
    )
    q = (
        q.where(VerificationRunCurrent.run_id == run_id)
        if run_id
        else q.where(VerificationRunCurrent.request_id == request_id)
    )
    pointer = s.scalar(q.with_for_update() if lock else q)
    if pointer is None:
        return None, None
    row = _row(s, ctx, product_id, VerificationRunVersion, pointer.run_version_id)
    if (row.run_id, row.request_id, row.revision) != (
        pointer.run_id,
        pointer.request_id,
        pointer.run_revision,
    ):
        raise DomainError("INTEGRITY_MISMATCH", "Run当前指针无法核对。")
    return pointer, row


def _version(s, ctx, product_id, run_id, revision):
    identity = s.scalar(
        select(VerificationRunVersion.id).where(
            VerificationRunVersion.tenant_id == ctx.tenant_id,
            VerificationRunVersion.product_id == product_id,
            VerificationRunVersion.run_id == run_id,
            VerificationRunVersion.revision == revision,
        )
    )
    if identity is None:
        raise DomainError("VERSION_CONFLICT", "固定Run版本不存在。")
    return _row(s, ctx, product_id, VerificationRunVersion, identity)


def _snapshot(row):
    run = TestRun.model_validate(row.run_snapshot)
    plan = ExecutionPlan.model_validate(row.execution_plan)
    if (
        digest(run.model_dump(mode="json")) != row.snapshot_sha256
        or digest(plan.model_dump(mode="json")) != row.plan_sha256
        or (
            run.id,
            run.revision,
            run.request_id,
            run.request_revision,
            run.scope.tenant_id,
            run.scope.product_id,
            run.scope.project_id,
            run.build.id,
            run.build.revision,
            run.status,
        )
        != (
            row.run_id,
            row.revision,
            row.request_id,
            row.request_revision,
            row.tenant_id,
            row.product_id,
            row.project_id,
            row.build_id,
            row.build_revision,
            row.status,
        )
        or run.status not in {"planned", "running", "results_pending", "reviewed", "disposed"}
    ):
        raise DomainError("INTEGRITY_MISMATCH", "Run固定计划、快照或未提交结果边界无法核对。")
    expected = _execution(plan)
    if (run.status == "planned" and (run.actual_start or run.execution)) or (
        run.status != "planned" and (run.actual_start is None or run.execution != expected)
    ):
        raise DomainError("INTEGRITY_MISMATCH", "Run开始事实与固定执行条件不一致。")
    final = run.status in {"results_pending", "reviewed", "disposed"}
    if run.status == "planned":
        invalid = (
            run.result != "pending"
            or run.measurements
            or run.computed_results
            or run.partial_returns
            or run.actual_end
            or run.preliminary_result
            or run.final_result
            or run.professional_conclusion
            or run.disposition
        )
    else:
        invalid = (
            (run.actual_end is not None) != final
            or (run.final_result is not None) != final
            or (run.professional_conclusion is not None) != (run.status in {"reviewed", "disposed"})
            or (run.disposition is not None) != (run.status == "disposed")
        )
        if run.measurements or final:
            computed, result = compute_results(run, run.measurements, final=final)
            invalid |= run.computed_results != computed or run.result != result
        else:
            invalid |= bool(run.computed_results) or run.result != "pending"
    if invalid:
        raise DomainError("INTEGRITY_MISMATCH", "Run原测量、确定性结果或结果办理状态不能核对。")
    return run, plan


def _execution(plan):
    return ExecutionConditions(
        equipment=physical.event_source(plan.equipment),
        calibration=physical.event_source(plan.calibration),
        environment=plan.environment,
        conditions=plan.conditions,
        executor_id=plan.executor_id,
    )


def _full_coverage(request, coverage):
    check_coverage(request, coverage)
    if pairs(coverage) != pairs(accepted_coverage(request)):
        raise DomainError(
            "INVALID_COVERAGE", "本版一个Run必须精确覆盖全部已接收范围，未接收缺项继续保留。", 422
        )


def _fixed_plan(value):
    # Both closed DTOs validate first. Compare every fixed field by canonical
    # value, not Pydantic's nominal base/subclass identity for exact references.
    return value.model_dump(
        mode="json",
        include={"window", "executor_id", "equipment", "calibration", "environment", "conditions"},
    )


def _binding(row, request, run_id, plan, methods):
    samples = {sample.id: sample for sample in request.samples}
    items = {item.id: item for item in request.items}
    return TestPlanBinding(
        run_id=run_id,
        request_id=request.id,
        accepted_request_id=row.id,
        accepted_request_revision=row.revision,
        build_id=request.build.id,
        project_id=request.scope.project_id,
        purpose=request.purpose,
        executor_id=plan.executor_id,
        window=plan.window,
        environment=plan.environment,
        conditions=plan.conditions,
        equipment=plan.equipment.model_dump(mode="json"),
        calibration=plan.calibration.model_dump(mode="json"),
        pairs=tuple(
            TestPairBinding(
                sample=samples[c.sample_id],
                item_id=c.item_id,
                method_id=methods[(c.sample_id, c.item_id)].id,
                method_revision=methods[(c.sample_id, c.item_id)].revision,
                method_sha256=methods[(c.sample_id, c.item_id)].snapshot_sha256,
                destructive=items[c.item_id].destructive,
            )
            for c in accepted_coverage(request)
        ),
    )


@dataclass
class Bound:
    physical: physical.Bound
    run_row: object
    run: object
    plan: ExecutionPlan
    binding: TestPlanBinding
    resources: object
    original: object
    source_basis: dict
    reservation: object = None
    proofs: dict = field(default_factory=dict)
    fingerprint_version: str | None = None
    dependency_proof: dict | None = None
    reserved_dependency_proof: dict | None = None
    saved_start: object = None
    fingerprint_runtime: object = None
    caller_uow: object = None
    caller_digest: str | None = None


def _close_start_boundary(s, ctx, bound, *, check_deadlines=True):
    """The v2 Start owner closes its own IO without changing legacy v1 gates."""
    if getattr(bound, "fingerprint_runtime", None) is None:
        return
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow
    from pdos_next.domain.test_resources import service as resources

    resources._same_fingerprint_runtime(s, bound.fingerprint_runtime)
    _same_uow(s, bound.caller_uow, ctx, bound.caller_digest)
    if not check_deadlines:
        return  # Qualification failures retain the existing explicit _guards code.
    clock = now()  # No owner IO after these real expiry checks.
    authority_until = datetime.fromisoformat(bound.physical.authority["valid_until"])
    if clock >= authority_until or (
        bound.resources.valid_until is not None and clock >= bound.resources.valid_until
    ):
        raise DomainError("SOURCE_STALE", "具名资格或资源在新开测核对期间到期。")


def _collected_resource_proof(resources, collected, facts_revision):
    """A private producer record has no meaning without its actual owning rows."""
    if type(collected) is not list or len(collected) != 1:
        raise DomainError("RESOURCE_FINGERPRINT_MATERIAL_INVALID", "缺少唯一完整资源凭证。")
    record = resources._verify_stored_fingerprint_v2(collected[0])
    if record["facts_revision"] != facts_revision:
        raise DomainError("RESOURCE_FACTS_CHANGED", "完整资源凭证与本次资源摘要不一致。")
    return record


def _saved_start_fingerprint(s, ctx, product_id, row, *, reservation=None):
    """Dispatch only from the immutable Start and its real reservation owner."""
    from pdos_next.domain.test_resources import service as resources
    from pdos_next.domain.test_resources.schemas import TestReservationResult

    raw = row.input_snapshot
    if type(raw) is not dict or row.operation != "test.run.start":
        raise DomainError("RUN_START_PROOF_INVALID", "资源版本必须来自原实际开测。")
    try:
        binding = TestPlanBinding.model_validate(raw["plan_binding"])
        saved = TestReservationResult.model_validate(raw["reservation"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("RUN_START_PROOF_INVALID", "原开测固定资源证明不完整。") from exc
    if reservation is None:
        reservation = resources._reservation(s, ctx, product_id, binding)
    if (
        reservation is None
        or reservation.tenant_id != ctx.tenant_id
        or reservation.product_id != product_id
        or reservation.project_id != row.project_id
        or reservation.build_id != row.build_id
        or reservation.run_id != row.run_id
        or binding.run_id != row.run_id
        or binding.project_id != row.project_id
        or binding.build_id != row.build_id
        or reservation.owner_id != row.writer_id
        or reservation.visibility != row.visibility
        or reservation.state != "formal"
        or reservation.intent_digest != row.intent_digest
        or reservation.binding != raw["plan_binding"]
        or saved.owner_run_id != row.run_id
        or saved.reservation_id != reservation.id
        or raw.get("resource_facts_revision") != saved.facts_revision
        or saved.facts_revision != reservation.facts_revision
    ):
        raise DomainError("RUN_RESERVATION_MISSING", "原开测与正式资源凭证不能一一核对。")
    _read_evidence(s, ctx, product_id, reservation)
    version_key = "resource_fingerprint_version" in raw
    proof_key = "resource_dependency_proof" in raw
    if not version_key and not proof_key:
        if reservation.fingerprint_version is not None or reservation.dependency_proof is not None:
            raise DomainError("RESOURCE_FINGERPRINT_MATERIAL_INVALID", "旧开测不能推断新凭证版本。")
        return resources._FINGERPRINT_V1, None
    if (
        not version_key
        or not proof_key
        or raw["resource_fingerprint_version"] != resources._FINGERPRINT_V2
        or reservation.fingerprint_version != resources._FINGERPRINT_V2
    ):
        raise DomainError("RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED", "原资源版本不能回退。", 503)
    record = resources._verify_stored_fingerprint_v2(raw["resource_dependency_proof"])
    owned = resources._verify_stored_fingerprint_v2(reservation.dependency_proof)
    if (
        record != owned
        or record["facts_revision"] != saved.facts_revision
        or record["material"]["binding"] != resources._fingerprint_json(binding)
    ):
        raise DomainError(
            "RESOURCE_FINGERPRINT_MATERIAL_INVALID", "原开测完整凭证与实际保存不一致。"
        )
    return resources._FINGERPRINT_V2, record


def _start_reservation_proof(s, ctx, command, product_id, payload, bound):
    """Check the producer, result and same-UOW row before saving the new Start."""
    from pdos_next.domain.test_resources import service as resources

    if (
        bound.fingerprint_version != resources._FINGERPRINT_V2
        or bound.reservation is None
        or bound.dependency_proof is None
        or bound.reserved_dependency_proof is None
        or bound.reservation.replayed
    ):
        raise DomainError("INTEGRITY_MISMATCH", "新开测缺少同事务v2正式资源凭证。")
    expected = resources._verify_stored_fingerprint_v2(bound.dependency_proof)
    saved = resources._verify_stored_fingerprint_v2(bound.reserved_dependency_proof)
    row = resources._reservation(s, ctx, product_id, bound.binding)
    if (
        row is None
        or row.fingerprint_version != resources._FINGERPRINT_V2
        or resources._verify_stored_fingerprint_v2(row.dependency_proof) != saved
        or expected != saved
        or saved["facts_revision"] != bound.resources.facts_revision
        or saved["facts_revision"] != bound.reservation.facts_revision
        or saved["facts_revision"] != row.facts_revision
        or bound.reservation.owner_run_id != payload.run_id
        or bound.reservation.reservation_id != row.id
        or row.run_id != payload.run_id
        or row.owner_id != ctx.requester_id
        or row.visibility != bound.physical.visibility
        or row.state != "formal"
        or row.fact_id != bound.plan.resource_fact_id
        or row.fact_revision != bound.plan.expected_resource_fact_revision
        or row.intent_digest != _intent(ctx, command, payload)
        or row.tenant_id != ctx.tenant_id
        or row.product_id != product_id
        or row.project_id != bound.binding.project_id
        or row.build_id != bound.binding.build_id
    ):
        raise DomainError("INTEGRITY_MISMATCH", "新开测摘要、完整资源材料或实际归属不一致。")
    return deepcopy(saved)


def _load(s, ctx, command, product, payload, *, require_reads=True, verify_event=True):
    _human(s, ctx, product.id, write=True)
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "开测不在服务器绑定产品。", 403)
    row = front._version(s, ctx, product.id, payload.request_id, payload.expected_request_revision)
    request = front._snapshot(row)
    # Parent/pointer gates precede every global resource and sample gate. Historical
    # replays still lock the actual current parent, without applying a premature CAS.
    front._current(s, ctx, product.id, payload.request_id, lock=True)
    _current(s, ctx, product.id, request_id=payload.request_id, lock=True)
    identity = select(VerificationRunIdentity).where(
        VerificationRunIdentity.tenant_id == ctx.tenant_id,
        VerificationRunIdentity.product_id == product.id,
        VerificationRunIdentity.id == payload.run_id,
    )
    s.scalar(identity.with_for_update())
    build = front._build(s, ctx, product.id, request.build.id)
    _, _, _, reads = front._linked(s, ctx, product.id, build)
    authority = front._assess(
        s, ctx, product.id, build.project_id, command.operation, request.purpose, write=True
    )
    original = s.scalar(
        select(VerificationLaunchFact).where(
            VerificationLaunchFact.tenant_id == ctx.tenant_id,
            VerificationLaunchFact.product_id == product.id,
            VerificationLaunchFact.operation == command.operation,
            VerificationLaunchFact.intent_digest == _intent(ctx, command, payload),
        )
    )
    run_row = None
    run = None
    if isinstance(payload, PlanPayload):
        plan, coverage = payload.execution_plan, payload.coverage
    else:
        run_row = _version(s, ctx, product.id, payload.run_id, payload.expected_run_revision)
        run, plan = _snapshot(run_row)
        if (
            run.request_id != request.id
            or run.build != request.build
            or run_row.plan_sha256 != payload.expected_plan_sha256
        ):
            raise DomainError("SOURCE_CHANGED", "固定Run、计划摘要或请求范围已变化。")
        coverage = run.coverage
    _full_coverage(request, coverage)
    from pdos_next.domain.test_resources import service as resources
    from pdos_next.domain.test_resources.models import TestResourceFact

    fact = _row(s, ctx, product.id, TestResourceFact, plan.resource_fact_id)
    if fact.revision != plan.expected_resource_fact_revision:
        raise DomainError("SOURCE_CHANGED", "测试资源事实固定版本不一致。")
    declared_binding = TestPlanBinding.model_validate(fact.binding)
    if (
        declared_binding.run_id != payload.run_id
        or declared_binding.request_id != request.id
        or declared_binding.build_id != request.build.id
        or declared_binding.project_id != request.scope.project_id
        or declared_binding.purpose != request.purpose
        or _fixed_plan(declared_binding) != _fixed_plan(plan)
    ):
        raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "资源事实未绑定精确计划与服务器范围。")
    resources.lock_binding_assets(
        s,
        ctx,
        product.id,
        declared_binding,
        plan.resource_fact_id,
        plan.expected_resource_fact_revision,
        write=True,
    )
    refs = physical._merge_refs(
        row.sources,
        [ref.model_dump(mode="json") for ref in payload.sources],
        [plan.equipment.model_dump(mode="json"), plan.calibration.model_dump(mode="json")],
        run_row.sources if run_row else [],
    )
    reads = _merge_reads(
        reads,
        row.required_source_read_set,
        refs,
        authority["required_source_read_set"],
        run_row.required_source_read_set if run_row else [],
    )
    inspected, methods = {}, {}
    selected = {c.sample_id for c in coverage}
    for sample in sorted((v for v in request.samples if v.id in selected), key=lambda v: str(v.id)):
        value = physical._inspect(s, ctx, product.id, request, sample, write=True)
        inspected[sample.id] = value
        refs = physical._merge_refs(refs, value["source_refs"])
        reads = _merge_reads(reads, value["required_source_read_set"], refs)
    for c in coverage:
        _, method = physical._method_pointer(s, ctx, product.id, request.id, c.sample_id, c.item_id)
        if method is None:
            raise DomainError("ACTUAL_METHOD_UNKNOWN", "Run各实际样件/测试项须有独立方法适用事实。")
        methods[(c.sample_id, c.item_id)] = method
        refs = physical._merge_refs(refs, method.sources)
        reads = _merge_reads(reads, method.required_source_read_set, refs)
    if run_row:
        binding = TestPlanBinding.model_validate(run_row.input_snapshot["plan_binding"])
        origin = front._row(s, ctx, product.id, binding.accepted_request_id)
        origin_request = front._snapshot(origin)
        expected = _binding(origin, origin_request, payload.run_id, plan, methods)
    else:
        binding = expected = _binding(row, request, payload.run_id, plan, methods)
    if binding != expected:
        raise DomainError("SOURCE_CHANGED", "Run原已接收范围、配置或实际方法固定版本已漂移。")
    # Preparation/inputs may lock and read, but must not initialize usage or occupancy.
    # Only the private accepted Start callback creates those records.
    kwargs = {"at": now(), "write": False}
    fingerprint_version, dependency_proof, saved_start = None, None, None
    fingerprint_runtime, caller_uow, caller_digest = None, None, None
    collected = []
    if original and isinstance(payload, StartPayload):
        kwargs["own_intent"] = original.intent_digest
        saved_start = _row(s, ctx, product.id, VerificationRunVersion, original.run_version_id)
        fingerprint_version, dependency_proof = _saved_start_fingerprint(
            s, ctx, product.id, saved_start
        )
    if isinstance(payload, StartPayload):
        # The server chooses v2 only for a genuinely new Start. A saved Start's
        # real owner determines replay version; no payload flag can select one.
        if fingerprint_version is None:
            fingerprint_version = resources._FINGERPRINT_V2
        if fingerprint_version == resources._FINGERPRINT_V2:
            from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow

            fingerprint_runtime = resources._fingerprint_runtime(s)
            caller_uow, caller_digest = _uow(s), digest(vars(ctx))
        kwargs["_fingerprint_version"] = fingerprint_version
        if fingerprint_version == resources._FINGERPRINT_V2:
            kwargs["_fingerprint_collector"] = collected
        if verify_event:
            _event(s, ctx, product.id, request, plan, payload, refs, actual=True)
        # Only command paths can supply a host-verified actual event. Read probes
        # evaluate the planned window without claiming a performed start.
        if verify_event:
            kwargs["verified_actual_start"] = payload.at
    bundle = resources.load_bundle(
        s,
        ctx,
        product.id,
        binding,
        plan.resource_fact_id,
        plan.expected_resource_fact_revision,
        **kwargs,
    )
    if bundle.binding != binding:
        raise DomainError("INTEGRITY_MISMATCH", "资源事实没有精确绑定Run计划。")
    if fingerprint_version == resources._FINGERPRINT_V2:
        current_proof = _collected_resource_proof(resources, collected, bundle.facts_revision)
        if dependency_proof is not None and current_proof != dependency_proof:
            raise DomainError("RESOURCE_FACTS_CHANGED", "原开测的完整资源依赖已变化。")
        dependency_proof = current_proof
    refs = physical._merge_refs(refs, fact.sources)
    reads = _merge_reads(
        reads,
        fact.required_source_read_set,
        [read.model_dump(mode="json") for read in bundle.required_source_read_set],
        refs,
    )
    basis, private = physical._basis(s, ctx, product.id, reads, refs)
    if row.visibility == "product" and (
        private
        or any(v["visibility"] == "private" for v in inspected.values())
        or fact.visibility == "private"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "私有测试实物、资源与来源不能扩大到共享请求。", 403)
    if require_reads:
        supplied = {str(ref.artifact_id): ref.expected_revision for ref in command.source_read_set}
        if any(supplied.get(read["artifact_id"]) != read["expected_revision"] for read in reads):
            raise DomainError(
                "MISSING_REQUIRED_EVIDENCE",
                "须固定请求、实物、方法、资源与具名资格的完整来源读集。",
            )
    p = physical.Bound(
        row,
        request,
        build,
        authority,
        refs,
        reads,
        basis,
        inspected,
        methods,
        row.visibility,
        now(),
    )
    bound = Bound(
        p,
        run_row,
        run,
        plan,
        binding,
        bundle,
        original,
        basis,
        fingerprint_version=fingerprint_version,
        dependency_proof=dependency_proof,
        saved_start=saved_start,
        fingerprint_runtime=fingerprint_runtime,
        caller_uow=caller_uow,
        caller_digest=caller_digest,
    )
    _close_start_boundary(s, ctx, bound, check_deadlines=False)
    return bound


def _event(s, ctx, product_id, request, plan, payload, refs, *, actual):
    if payload.at.source.kind != "artifact" or payload.at.source not in {
        physical.event_source(SimpleNamespace(**{**ref, "artifact_id": UUID(ref["artifact_id"])}))
        for ref in refs
    }:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "承诺/开测时点须精确引用本次固定原文。")
    reference = next(
        ref
        for ref in refs
        if physical.event_source(
            SimpleNamespace(**{**ref, "artifact_id": UUID(ref["artifact_id"])})
        )
        == payload.at.source
    )
    source = source_for(
        s, ctx, product_id, UUID(reference["artifact_id"]), reference["expected_revision"]
    )

    def unique_object(entries):
        value = {}
        for key, entry in entries:
            if key in value:
                raise ValueError("Ambiguous duplicate event key")
            value[key] = entry
        return value

    try:
        event = json.loads(
            source.content.splitlines()[reference["line"] - 1], object_pairs_hook=unique_object
        )
        if not isinstance(event, dict) or not isinstance(event.get("occurred_at"), str):
            raise ValueError("Event time must be an explicit aware string")
        event_at = datetime.fromisoformat(event["occurred_at"])
        if event_at.tzinfo is None or event_at.utcoffset() is None:
            raise ValueError("Event time must carry an offset")
        event = {**event, "occurred_at": event_at.astimezone(UTC)}
    except (ValueError, IndexError, TypeError, AttributeError):
        raise DomainError(
            "INVALID_EVENT_EVIDENCE", "事件须在精确整行JSON核对固定身份与实际时点。", 422
        ) from None
    expected = {
        "request_id": str(request.id),
        "run_id": str(payload.run_id),
        "purpose": request.purpose,
        "operation": "test.run.start" if actual else "verification.schedule.promise",
        "occurred_at": payload.at.occurred_at,
        "executor_id": str(plan.executor_id),
    }
    if event != expected or payload.at.effective_at is not None:
        raise DomainError(
            "INVALID_EVENT_EVIDENCE", "事件原值与固定Run/用途/执行者/时点不一致。", 422
        )
    if not plan.window.start <= payload.at.occurred_at < plan.window.finish:
        raise DomainError("INVALID_EVENT_TIME", "承诺/开测时点须位于固定完整窗口内。", 422)
    if actual and payload.at.occurred_at > now():
        raise DomainError("INVALID_EVENT_TIME", "实际开测不能发生于未来。", 422)


def _guards(s, ctx, command, product, payload, bound, *, verify_event=True):
    p, a = bound.physical, bound.physical.authority
    if (
        a["authorized"] is not True
        or a["qualified"] is not True
        or a["subject_id"] != str(ctx.requester_id)
        or not a.get("valid_until")
        or datetime.fromisoformat(a["valid_until"]) <= now()
    ):
        raise DomainError(
            "QUALIFICATION_REQUIRED", "当前本人缺少本Run用途的品质/测试职责及资格。", 403
        )
    expected = {"quality", "test"} if isinstance(payload, StartPayload) else {"quality"}
    if not set(a["roles"]) & expected:
        raise DomainError("FORBIDDEN_OPERATION", "该操作缺少对应专业职责。", 403)
    physical._execution(s, ctx, product.id, p.build)
    for doc in p.base.documents:
        if doc.id.startswith(PROFESSIONAL_PREFIX) and doc.source:
            row = s.get(MethodApplicability, doc.source.id)
            if row is None or doc.source.kind != "domain" or doc.source.position != METHOD_POSITION:
                raise DomainError("SOURCE_UNAVAILABLE", "固定计划专业方法不存在。")
            physical._bound_method_check(s, ctx, product.id, p, row)
    samples = {sample.id: sample for sample in p.base.samples}
    for c in accepted_coverage(p.base):
        value = p.samples[c.sample_id]
        if value["availability"] != "ready":
            raise DomainError("SAMPLE_UNAVAILABLE", "暂缓或未知实物不能计划/承诺/开测。")
        physical._bound_actual_check(
            s, ctx, product.id, p, samples[c.sample_id], value, p.methods[(c.sample_id, c.item_id)]
        )
    if bound.resources.report.status != "READY":
        raise DomainError("RESOURCE_NOT_READY", "完整测试资源、资格、窗口或样件使用未就绪。")
    if verify_event and isinstance(payload, PromisePayload):
        _event(
            s,
            ctx,
            product.id,
            p.base,
            bound.plan,
            payload,
            p.references,
            actual=isinstance(payload, StartPayload),
        )
    if isinstance(payload, StartPayload) and bound.plan.executor_id != ctx.requester_id:
        raise DomainError("NAMED_DECISION_REQUIRED", "实际开测须固定计划中的当前本人执行。", 403)
    if bound.run_row:
        fixed_basis, _ = physical._basis(
            s, ctx, product.id, bound.run_row.required_source_read_set, bound.run_row.sources
        )
        if (
            fixed_basis != bound.run_row.source_basis
            or not front._recheck(
                s, ctx, product.id, bound.run_row.project_id, bound.run_row.authority_snapshot
            )["current"]
        ):
            raise DomainError("SOURCE_STALE", "固定Run原计划的具名资格与来源已变化。")
    if bound.original:
        previous_basis, _ = physical._basis(
            s, ctx, product.id, bound.original.required_source_read_set, bound.original.sources
        )
        if (
            previous_basis != bound.original.source_basis
            or not front._recheck(
                s, ctx, product.id, bound.original.project_id, bound.original.authority_snapshot
            )["current"]
        ):
            raise DomainError("SOURCE_STALE", "原开测办理的来源或原签发资格已变化。")
        if isinstance(payload, StartPayload):
            from pdos_next.domain.test_resources import service as resources

            bound.resources = resources.recheck_running(
                s,
                ctx,
                product.id,
                bound.binding,
                bound.plan.resource_fact_id,
                bound.plan.expected_resource_fact_revision,
                intent_digest=bound.original.intent_digest,
            )
            version, record = _saved_start_fingerprint(s, ctx, product.id, bound.saved_start)
            if (
                version != bound.fingerprint_version
                or record != bound.dependency_proof
                or bound.resources.facts_revision
                != bound.saved_start.input_snapshot["resource_facts_revision"]
            ):
                raise DomainError("RESOURCE_FACTS_CHANGED", "原开测的资源身份在重核后不一致。")
    _close_start_boundary(s, ctx, bound)


def validate(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _guards(s, ctx, command, product, payload, bound)


def _new_write(s, ctx, command, product, payload, bound):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "产品版本已变化，请重新读取。")
    request_pointer, current = front._current(s, ctx, product.id, payload.request_id, lock=True)
    if (
        current is None
        or current.id != bound.physical.previous.id
        or current.revision != payload.expected_request_revision
    ):
        raise DomainError("VERSION_CONFLICT", "正式请求当前版本已变化。")
    run_pointer, current_run = _current(
        s, ctx, product.id, request_id=payload.request_id, lock=True
    )
    if isinstance(payload, PlanPayload):
        identity = s.scalar(
            select(VerificationRunIdentity).where(
                VerificationRunIdentity.tenant_id == ctx.tenant_id,
                VerificationRunIdentity.product_id == product.id,
                VerificationRunIdentity.request_id == payload.request_id,
            )
        )
        if current.status != "accepted" or identity is not None or current_run is not None:
            raise DomainError("INVALID_STATE", "本版仅已接收请求可首次固定一个Run。")
        if bound.plan.window.start < now():
            raise DomainError(
                "INVALID_EVENT_TIME", "新Run必须完整计划未来窗口，不补造过去计划。", 422
            )
    else:
        if (
            current_run is None
            or current_run.id != bound.run_row.id
            or current_run.revision != payload.expected_run_revision
        ):
            raise DomainError("VERSION_CONFLICT", "Run当前版本已变化。")
        if current_run.status != "planned":
            raise DomainError("INVALID_STATE", "仅尚未开测的固定Run可承诺或开始。")
        if isinstance(payload, StartPayload):
            if current.status != "scheduled" or bound.physical.base.timeline.promised_start is None:
                raise DomainError("INVALID_STATE", "实际开测须先有本Run完整范围的具名承诺。")
            if not bound.plan.window.start <= now() < bound.plan.window.finish:
                raise DomainError("INVALID_EVENT_TIME", "当前时间须在固定执行窗口内。", 422)
        elif (
            current.status != "accepted"
            or payload.at.occurred_at < now()
            or payload.at.occurred_at != bound.plan.window.start
        ):
            raise DomainError("INVALID_STATE", "只能对完整已接收范围承诺固定窗口的未来开始。")
    return request_pointer, run_pointer


def _payload_kernel(payload, plan):
    if isinstance(payload, PlanPayload):
        return RunPlan(run_id=payload.run_id, coverage=payload.coverage)
    if isinstance(payload, StartPayload):
        return RunStart(at=payload.at, execution=_execution(plan))
    return SchedulePromise(at=payload.at)


def _invocation(command, payload, value):
    return Invocation(
        command_id=command.command_id,
        operation=command.operation,
        subject_id=request_subject(payload),
        expected_revision=payload.expected_run_revision
        if isinstance(payload, StartPayload)
        else payload.expected_request_revision,
        semantic_digest=semantic_digest(value),
    )


def _kernel(s, ctx, command, product, payload, bound, save, *, accepted=False):
    from pdos_next.domain.test_resources import service as resources

    p = bound.physical
    refs = {
        physical.event_source(SimpleNamespace(**{**ref, "artifact_id": UUID(ref["artifact_id"])}))
        for ref in p.references
    }

    def check_source(scope, source, purpose):
        if scope != p.base.scope:
            raise DomainError("FORBIDDEN_SCOPE", "开测来源不在固定服务器范围。", 403)
        if source.kind == "artifact" and source in refs:
            return
        if source.kind == "domain" and source.position == METHOD_POSITION:
            row = s.get(MethodApplicability, source.id)
            if row is None or source.revision != 1:
                raise DomainError("SOURCE_UNAVAILABLE", "原专业方法不存在。")
            physical._bound_method_check(s, ctx, product.id, p, row)
            return
        if source.kind == "domain" and source.position == "actual-sample":
            expected = next((v for v in p.base.samples if v.id == source.id), None)
            if expected and source.id in p.samples and source.revision == expected.revision:
                return
        if source.kind == "domain" and source.position == "sample-readiness":
            if any(
                v.get("current_readiness")
                and v["current_readiness"].get("source_ref") == source.model_dump(mode="json")
                for v in p.samples.values()
            ):
                return
        raise DomainError("SOURCE_UNAVAILABLE", "来源不是本次服务器已核对的固定事实。")

    def applicable(sample):
        covers = [v for v in bound.binding.pairs if v.sample.id == sample.id]
        for pair in covers:
            try:
                physical._bound_actual_check(
                    s,
                    ctx,
                    product.id,
                    p,
                    sample,
                    p.samples[sample.id],
                    p.methods[(sample.id, pair.item_id)],
                )
            except DomainError as error:
                if error.code in {"SOURCE_STALE", "ACTUAL_METHOD_UNKNOWN"}:
                    return False
                raise
        return bool(covers)

    def reserve(scope, run_id, samples, coverage, destructive, execution):
        expected_destructive = {
            (v.sample.id, v.item_id) for v in bound.binding.pairs if v.destructive
        }
        if (
            not accepted
            or not isinstance(payload, StartPayload)
            or scope != p.base.scope
            or run_id != bound.binding.run_id
            or pairs(coverage) != pairs(accepted_coverage(p.base))
            or pairs(destructive) != expected_destructive
            or execution != _execution(bound.plan)
            or {v.id for v in samples} != {v.sample.id for v in bound.binding.pairs}
        ):
            raise DomainError("INTEGRITY_MISMATCH", "内部资源/样件占用不匹配本次固定开测确认。")
        collected = []
        bound.reservation = resources.stage_start(
            s,
            ctx,
            product.id,
            bound.binding,
            bound.plan.resource_fact_id,
            bound.plan.expected_resource_fact_revision,
            expected_facts_revision=bound.resources.facts_revision,
            intent_digest=_intent(ctx, command, payload),
            accepted_confirmation=True,
            verified_actual_start=payload.at,
            _fingerprint_version=bound.fingerprint_version,
            _fingerprint_collector=collected,
        )
        bound.reserved_dependency_proof = _collected_resource_proof(
            resources, collected, bound.reservation.facts_revision
        )
        _start_reservation_proof(s, ctx, command, product.id, payload, bound)

    commands = LaunchCommands(
        authority_dto(p.authority, ctx.requester_id, now()),
        p.base,
        save,
        accepted_confirmation=accepted,
        fixed_run=bound.run,
    )
    samples = LaunchSamples(
        lambda sample: p.samples[sample.id],
        applicable,
        reserve,
        lambda scope, run: resources.recheck_running(
            s,
            ctx,
            product.id,
            bound.binding,
            bound.plan.resource_fact_id,
            bound.plan.expected_resource_fact_revision,
            intent_digest=_intent(ctx, command, payload),
        ),
    )
    return kernel(commands, p.base.build, check_source, samples)


def _record(s, ctx, command, product, payload, bound, pointers, mutation):
    p = bound.physical
    if (
        mutation.request is None
        or mutation.request.status not in {"accepted", "scheduled", "executing"}
        or any(
            getattr(mutation.request.timeline, key) is not None
            for key in ("preliminary_result", "final_result", "disposed")
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "开测不能写入结果或处置。")
    request_pointer, run_pointer = pointers
    next_request = p.previous
    if mutation.request.revision != p.previous.revision:
        raw = deepcopy(p.previous.input_snapshot)
        raw["launch_input"] = semantic(payload)
        next_request = FormalVerificationRequest(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=p.build.project_id,
            build_id=p.build.id,
            build_revision=p.build.revision,
            request_id=p.base.id,
            revision=mutation.request.revision,
            previous_request_id=p.previous.id,
            previous_revision=p.previous.revision,
            owner_id=p.previous.owner_id,
            visibility=p.visibility,
            status=mutation.request.status,
            operation=command.operation,
            preparation_id=p.previous.preparation_id,
            preparation_revision=p.previous.preparation_revision,
            preparation_sha256=p.previous.preparation_sha256,
            purpose=p.base.purpose,
            request_snapshot=mutation.request.model_dump(mode="json"),
            input_snapshot=raw,
            snapshot_sha256=digest(mutation.request.model_dump(mode="json")),
            sources=p.references,
            required_source_read_set=p.reads,
            authority_snapshot=p.authority,
            intent_digest=_intent(ctx, command, payload),
            reason=payload.reason,
            created_at=now(),
        )
        s.add(next_request)
        s.flush()
        request_pointer.request_version_id, request_pointer.request_revision = (
            next_request.id,
            next_request.revision,
        )
    next_run = bound.run_row
    if mutation.run is not None:
        if mutation.run.status == "running" and bound.reservation is None:
            raise DomainError("INTEGRITY_MISMATCH", "实际开始缺少同事务正式资源/样件占用。")
        resource_proof = None
        if mutation.run.status == "running":
            resource_proof = _start_reservation_proof(s, ctx, command, product.id, payload, bound)
        origin = bound.run_row if bound.run_row else p.previous
        origin_id = origin.request_version_id if bound.run_row else origin.id
        origin_revision = origin.request_revision if bound.run_row else origin.revision
        raw = deepcopy(bound.run_row.input_snapshot) if bound.run_row else {}
        raw.update(
            plan_binding=bound.binding.model_dump(mode="json"),
            launch_input=semantic(payload),
            resource_facts_revision=bound.resources.facts_revision,
            reservation=bound.reservation.model_dump(mode="json") if bound.reservation else None,
        )
        if resource_proof is not None:
            raw.update(
                resource_fingerprint_version=bound.fingerprint_version,
                resource_dependency_proof=resource_proof,
            )
        next_run = VerificationRunVersion(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=p.build.project_id,
            build_id=p.build.id,
            build_revision=p.build.revision,
            request_id=p.base.id,
            request_version_id=origin_id,
            request_revision=origin_revision,
            run_id=payload.run_id,
            revision=mutation.run.revision,
            previous_run_version_id=bound.run_row.id if bound.run_row else None,
            previous_revision=bound.run_row.revision if bound.run_row else None,
            owner_id=bound.run_row.owner_id if bound.run_row else ctx.requester_id,
            writer_id=ctx.requester_id,
            visibility=p.visibility,
            status=mutation.run.status,
            operation=command.operation,
            run_snapshot=mutation.run.model_dump(mode="json"),
            execution_plan=bound.plan.model_dump(mode="json"),
            plan_sha256=digest(bound.plan.model_dump(mode="json")),
            input_snapshot=raw,
            snapshot_sha256=digest(mutation.run.model_dump(mode="json")),
            sources=p.references,
            required_source_read_set=p.reads,
            source_basis=bound.source_basis,
            authority_snapshot=p.authority,
            intent_digest=_intent(ctx, command, payload),
            reason=payload.reason,
            created_at=now(),
        )
        s.add(next_run)
        s.flush()
        if run_pointer is None:
            s.add(
                VerificationRunCurrent(
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    request_id=p.base.id,
                    run_id=payload.run_id,
                    run_version_id=next_run.id,
                    run_revision=next_run.revision,
                )
            )
        else:
            run_pointer.run_version_id, run_pointer.run_revision = next_run.id, next_run.revision
    event = mutation.events[0].model_dump(mode="json")
    fact = VerificationLaunchFact(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=p.build.project_id,
        build_id=p.build.id,
        request_id=p.base.id,
        request_version_id=p.previous.id,
        request_revision=p.previous.revision,
        next_request_version_id=next_request.id,
        next_request_revision=next_request.revision,
        run_id=payload.run_id,
        run_version_id=next_run.id,
        run_revision=next_run.revision,
        owner_id=ctx.requester_id,
        visibility=p.visibility,
        revision=1,
        status=mutation.run.status if mutation.run else mutation.request.status,
        operation=command.operation,
        input_snapshot=semantic(payload),
        kernel_event=event,
        sources=p.references,
        required_source_read_set=p.reads,
        source_basis=bound.source_basis,
        authority_snapshot=p.authority,
        intent_digest=_intent(ctx, command, payload),
        snapshot_sha256=digest(event),
        reason=payload.reason,
        created_at=now(),
    )
    s.add(fact)
    s.flush()
    _close_start_boundary(s, ctx, bound)
    return (
        next_request
        if isinstance(payload, PromisePayload) and not isinstance(payload, StartPayload)
        else next_run
    )


def apply(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _guards(s, ctx, command, product, payload, bound)
    pointers = _new_write(s, ctx, command, product, payload, bound)
    if isinstance(payload, PlanPayload):
        s.add(
            VerificationRunIdentity(
                id=payload.run_id,
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                project_id=bound.physical.build.project_id,
                build_id=bound.physical.build.id,
                request_id=payload.request_id,
                owner_id=ctx.requester_id,
                visibility=bound.physical.visibility,
            )
        )
        s.flush()
    recorded = []

    def save(mutation):
        row = _record(s, ctx, command, product, payload, bound, pointers, mutation)
        recorded.append(row)
        return row

    k = _kernel(s, ctx, command, product, payload, bound, save, accepted=True)
    value = _payload_kernel(payload, bound.plan)
    k.execute(_invocation(command, payload, value), value)
    _close_start_boundary(s, ctx, bound)
    return recorded[0], replay_subject_type(payload), bound.physical.visibility


def replay_subject(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _guards(s, ctx, command, product, payload, bound)
    if bound.original is None:
        return None
    if replay_subject_type(payload) == "verification_request":
        row = front._row(s, ctx, product.id, bound.original.next_request_version_id)
    else:
        row = _row(s, ctx, product.id, VerificationRunVersion, bound.original.run_version_id)
    _close_start_boundary(s, ctx, bound)
    return row


def _run_view(row, run, *, current=False, prospective=False, resource_report=None):
    return {
        "id": None if prospective else str(row.id),
        "run_id": str(run.id),
        "revision": run.revision,
        "request_id": str(run.request_id),
        "request_revision": run.request_revision,
        "build": run.build.model_dump(mode="json"),
        "status": run.status,
        "result": run.result,
        "run_snapshot": run.model_dump(mode="json"),
        "execution_plan": row.execution_plan,
        "plan_sha256": row.plan_sha256,
        "sources": row.sources,
        "required_source_read_set": row.required_source_read_set,
        "authority": row.authority_snapshot,
        "source_status": "current",
        "is_current": current,
        "current_evaluation": "not_evaluated_historical",
        "resource_report": resource_report,
        "created_at": None if prospective else row.created_at.isoformat(),
        "occupancy": None if run.status == "running" else [],
        "sample_usage": None if run.status == "running" else [],
        "zero_occupancy": run.status == "planned",
        "capabilities": {"schedule_promise": False, "run_start": False},
        "blockers": [],
    }


def _saved_effects(s, ctx, product_id, row):
    """Observed own committed effects; no claim about current qualification/free capacity."""
    from pdos_next.domain.build_operational_facts.models import ResourceOccupancy
    from pdos_next.domain.test_resources.models import SampleRunUsage, TestResourceReservation

    saved = row.input_snapshot.get("reservation")
    proof = s.scalar(
        select(TestResourceReservation).where(
            TestResourceReservation.tenant_id == ctx.tenant_id,
            TestResourceReservation.product_id == product_id,
            TestResourceReservation.run_id == row.run_id,
        )
    )
    if (
        not saved
        or proof is None
        or proof.binding != row.input_snapshot.get("plan_binding")
        or digest(proof.reservation) != proof.reservation_sha256
    ):
        raise DomainError("RUN_RESERVATION_MISSING", "既有开测占用证明无法核对，不等于零占用。")
    _read_evidence(s, ctx, product_id, proof)
    # Result versions inherit the original Start input unchanged; resolve its
    # actual immutable owner instead of interpreting later operation strings.
    original = (
        row if row.operation == "test.run.start" else _version(s, ctx, product_id, row.run_id, 2)
    )
    _saved_start_fingerprint(s, ctx, product_id, original, reservation=proof)
    if (
        row.input_snapshot.get("resource_facts_revision")
        != original.input_snapshot.get("resource_facts_revision")
        or ("resource_fingerprint_version" in row.input_snapshot)
        != ("resource_fingerprint_version" in original.input_snapshot)
        or ("resource_dependency_proof" in row.input_snapshot)
        != ("resource_dependency_proof" in original.input_snapshot)
        or row.input_snapshot.get("resource_fingerprint_version")
        != original.input_snapshot.get("resource_fingerprint_version")
        or row.input_snapshot.get("resource_dependency_proof")
        != original.input_snapshot.get("resource_dependency_proof")
    ):
        raise DomainError("RUN_START_PROOF_INVALID", "后续结果不能替换原资源凭证。")
    occupied = s.scalars(
        select(ResourceOccupancy)
        .where(
            ResourceOccupancy.tenant_id == ctx.tenant_id,
            ResourceOccupancy.product_id == product_id,
            ResourceOccupancy.project_id == row.project_id,
            ResourceOccupancy.build_id == row.build_id,
            ResourceOccupancy.owner_kind == "test_run",
            ResourceOccupancy.owner_execution_id == row.run_id,
        )
        .order_by(ResourceOccupancy.resource_id)
    ).all()
    usages = s.scalars(
        select(SampleRunUsage)
        .where(
            SampleRunUsage.tenant_id == ctx.tenant_id,
            SampleRunUsage.product_id == product_id,
            SampleRunUsage.project_id == row.project_id,
            SampleRunUsage.build_id == row.build_id,
            SampleRunUsage.run_id == row.run_id,
        )
        .order_by(SampleRunUsage.sample_id)
    ).all()
    if {str(v.id) for v in occupied} != set(saved.get("occupancy_ids", ())) or {
        str(v.id) for v in usages
    } != set(saved.get("sample_usage_ids", ())):
        raise DomainError("RUN_RESERVATION_MISSING", "既有资源/实物使用明细不完整，不等于可用。")
    for use in usages:
        _read_evidence(s, ctx, product_id, use)
    return {
        "occupancy_evaluation": "saved_committed_effects_current_qualification_not_evaluated",
        "occupancy": [
            {
                "id": str(v.id),
                "resource_id": str(v.resource_id),
                "resource_revision": v.resource_revision,
                "units": str(v.units),
                "window_start": v.window_start.isoformat(),
                "window_finish": v.window_finish.isoformat(),
                "owner_kind": "test_run",
            }
            for v in occupied
        ],
        "sample_usage": [
            {
                "id": str(v.id),
                "sample_id": str(v.sample_id),
                "sample_revision": v.sample_revision,
                "actual_configuration_id": str(v.actual_configuration_id),
                "actual_configuration_revision": v.actual_configuration_revision,
                "state": v.state,
                "destructive": v.destructive,
                "coverage": v.coverage,
                "window_start": v.window_start.isoformat(),
                "window_finish": v.window_finish.isoformat(),
            }
            for v in usages
        ],
    }


def preview_view(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _guards(s, ctx, command, product, payload, bound)
    _new_write(s, ctx, command, product, payload, bound)
    p = bound.physical
    before_request = physical._request_view(s, ctx, product.id, p.previous, p.base)
    before_run = _run_view(bound.run_row, bound.run, current=True) if bound.run_row else None
    k = _kernel(s, ctx, command, product, payload, bound, lambda _: None)
    value = _payload_kernel(payload, bound.plan)
    preview, mutation = k._prepare(
        authority_dto(p.authority, ctx.requester_id, now()),
        _invocation(command, payload, value),
        value,
    )
    if not preview.allowed:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "Run资料或样件缺项未满足。")
    after_request = deepcopy(before_request)
    after_request.update(
        id=None if mutation.request.revision != p.base.revision else before_request["id"],
        revision=mutation.request.revision,
        status=mutation.request.status,
        request_snapshot=physical._preview_receives(
            mutation.request.model_dump(mode="json"), p.base.model_dump(mode="json")
        ),
        timeline=physical._preview_receives(
            mutation.request.timeline.model_dump(mode="json"),
            p.base.timeline.model_dump(mode="json"),
        ),
    )
    if mutation.request.revision != p.base.revision:
        after_request.update(
            previous_request_id=before_request["id"],
            previous_revision=p.base.revision,
            reason=payload.reason,
            created_at=None,
            sha256=None,
            zero_occupancy=mutation.request.status != "executing",
        )
    after_run = before_run
    if mutation.run:
        row = SimpleNamespace(
            id=None,
            execution_plan=bound.plan.model_dump(mode="json"),
            plan_sha256=digest(bound.plan.model_dump(mode="json")),
            sources=p.references,
            required_source_read_set=p.reads,
            authority_snapshot=p.authority,
        )
        after_run = _run_view(row, mutation.run, prospective=True)
        after_run["run_snapshot"] = physical._preview_receives(
            after_run["run_snapshot"], bound.run.model_dump(mode="json") if bound.run else {}
        )
    report = bound.resources.report.model_dump(mode="json")
    # The report's complete input_digest excludes only evaluation time in the
    # delivered rule. Keep all fixed facts/epochs/checks, but do not require an
    # execute-time clock to equal the earlier review clock.
    report["checked_at"] = None
    report["checked_at_basis"] = "server_revalidates_on_execute"
    usage = [v.model_dump(mode="json") for v in bound.resources.sample_usage]
    _close_start_boundary(s, ctx, bound)
    return {
        "operation": command.operation,
        "effect": EFFECT,
        "before": {"request": before_request, "run": before_run},
        "after": {
            "request": after_request,
            "run": after_run,
            "resource_report": report,
            "sample_usage": usage,
            "occupancy_effect": "stage_formal_and_sample_use_in_caller_uow"
            if isinstance(payload, StartPayload)
            else "none",
        },
        "authority": p.authority,
        "required_source_read_set": p.reads,
        "resource_report": report,
        "reason": payload.reason,
    }


def inputs(s, ctx, product_id, command: Command):
    if command.product_id != product_id or command.operation not in PAYLOADS:
        raise DomainError("FORBIDDEN_SCOPE", "开测输入不在固定产品/操作范围。", 403)
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    product = s.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == ctx.tenant_id)
    )
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "产品不可见。", 403)
    bound = _load(s, ctx, command, product, payload, require_reads=False)
    blockers = []
    try:
        _guards(s, ctx, command, product, payload, bound)
        _new_write(s, ctx, command, product, payload, bound)
    except DomainError as error:
        if error.code in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
            raise
        blockers.append({"code": error.code, "detail": error.message})
    _close_start_boundary(s, ctx, bound, check_deadlines=not blockers)
    return {
        "operation": command.operation,
        "request_id": str(payload.request_id),
        "run_id": str(payload.run_id),
        "allowed": not blockers,
        "authority": bound.physical.authority,
        "plan_binding": bound.binding.model_dump(mode="json"),
        "resource_report": bound.resources.report.model_dump(mode="json"),
        "required_source_read_set": bound.physical.reads,
        "source_status": "current",
        "blockers": blockers,
    }


def _read_command(ctx, product, operation, payload):
    """An ephemeral read probe is never confirmed, persisted or used by apply."""
    return SimpleNamespace(
        product_id=product.id,
        expected_revision=product.revision,
        operation=operation,
        command_id=uuid4(),
        source_read_set=(),
    )


def _capability(s, ctx, product, operation, payload):
    command = _read_command(ctx, product, operation, payload)
    bound = _load(s, ctx, command, product, payload, require_reads=False, verify_event=False)
    _guards(s, ctx, command, product, payload, bound, verify_event=False)
    _new_write(s, ctx, command, product, payload, bound)
    _close_start_boundary(s, ctx, bound)
    return bound


def list_launch(s, ctx, product_id, *, build_id=None):
    """Current per-row capabilities; historical clocks and plans remain fixed.

    Read probes do not mint confirmation or initialize occupancy/usage. Each probe
    uses a fresh Bound; no proof is reused across operations or requests.
    """
    from pdos_next.domain.build_execution.models import SampleUnit
    from pdos_next.domain.sample_handoff.service import ReadContext
    from pdos_next.domain.test_resources import service as resources

    _human(s, ctx, product_id)
    product = s.scalar(
        select(Product).where(Product.tenant_id == ctx.tenant_id, Product.id == product_id)
    )
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "产品不可见。", 403)
    if build_id is not None:
        build = front._build(s, ctx, product_id, build_id)
        _, _, _, reads = front._linked(s, ctx, product_id, build)
        _sources(s, ctx, product_id, reads)
        build_id = build.id
    query = select(FormalVerificationRequest).where(
        FormalVerificationRequest.tenant_id == ctx.tenant_id,
        FormalVerificationRequest.product_id == product_id,
    )
    runs_query = select(VerificationRunVersion).where(
        VerificationRunVersion.tenant_id == ctx.tenant_id,
        VerificationRunVersion.product_id == product_id,
    )
    if build_id:
        query = query.where(FormalVerificationRequest.build_id == build_id)
        runs_query = runs_query.where(VerificationRunVersion.build_id == build_id)
    rows = s.scalars(
        query.order_by(FormalVerificationRequest.created_at, FormalVerificationRequest.id).limit(
            201
        )
    ).all()
    run_rows = s.scalars(
        runs_query.order_by(VerificationRunVersion.created_at, VerificationRunVersion.id).limit(201)
    ).all()
    resource_views = resources.list_resources(s, ctx, product_id, build_id=build_id)[
        "resource_facts"
    ]
    result = {
        "requests": [],
        "runs": [],
        "current_by_request": {},
        "current_by_run": {},
        "run_by_request": {},
        "resource_facts": resource_views,
        "reference_samples": [],
        "capabilities": {key: False for key in OPERATIONS},
        "blockers": [
            {
                "code": "RESULTS_AND_DISPOSITION_UNCONNECTED",
                "detail": "本闭环只记录固定计划、承诺和实际开测；结果与专业处置尚未接入。",
            }
        ],
        "has_more": len(rows) > 200 or len(run_rows) > 200,
        "unavailable_count": 0,
    }
    current_requests, pointers, samples = {}, {}, {}
    read_context = ReadContext(s, ctx, product_id)
    for row in rows[:200]:
        if row.visibility == "private" and row.owner_id != ctx.requester_id:
            continue
        try:
            source_status = _read_evidence(s, ctx, product_id, row)
            request = front._snapshot(row)
            pointer, current = front._current(s, ctx, product_id, row.request_id)
            is_current = current is not None and current.id == row.id
            view = physical._request_view(s, ctx, product_id, row, request, current=is_current)
            view.update(
                capabilities={"run_plan": False},
                blockers=[],
                current_evaluation="not_evaluated_historical",
                documents_ready=None,
                document_milestone_current=None,
                source_status=source_status,
            )
            if is_current:
                view["authority"] = {
                    "run_plan": front._assess(
                        s, ctx, product_id, row.project_id, OPERATIONS["run_plan"], request.purpose
                    )
                }
                view["current_evaluation"] = "not_evaluated_current"
                current_requests[row.request_id] = (row, request, view)
                result["current_by_request"][str(row.request_id)] = {
                    "request_version_id": str(pointer.request_version_id),
                    "revision": pointer.request_revision,
                }
                run_pointer, fixed_run = _current(s, ctx, product_id, request_id=row.request_id)
                pointers[row.request_id] = (run_pointer, fixed_run)
                if fixed_run:
                    result["run_by_request"][str(row.request_id)] = str(fixed_run.run_id)
                if (
                    source_status == "current"
                    and request.status == "accepted"
                    and fixed_run is None
                ):
                    for fact in resource_views:
                        binding = TestPlanBinding.model_validate(fact["binding"])
                        if (
                            not fact["current"]
                            or fact["source_status"] != "current"
                            or binding.accepted_request_id != row.id
                        ):
                            continue
                        plan = ExecutionPlan(
                            **{
                                name: getattr(binding, name)
                                for name in (
                                    "window",
                                    "executor_id",
                                    "equipment",
                                    "calibration",
                                    "environment",
                                    "conditions",
                                )
                            },
                            resource_fact_id=UUID(fact["id"]),
                            expected_resource_fact_revision=fact["revision"],
                        )
                        payload = PlanPayload(
                            request_id=row.request_id,
                            expected_request_revision=row.revision,
                            run_id=binding.run_id,
                            coverage=accepted_coverage(request),
                            execution_plan=plan,
                            reason="读取当前固定Run能力",
                        )
                        try:
                            bound = _capability(s, ctx, product, OPERATIONS["run_plan"], payload)
                            view["capabilities"]["run_plan"] = True
                            view["resource_report"] = bound.resources.report.model_dump(mode="json")
                            view["required_source_read_set"] = bound.physical.reads
                            view["documents_ready"] = not document_gaps(request)
                            view["document_milestone_current"] = (
                                view["documents_ready"]
                                if request.timeline.documents_complete
                                else None
                            )
                            view["current_evaluation"] = "evaluated_current"
                        except DomainError as error:
                            view["blockers"].append({"code": error.code, "detail": error.message})
                    if not view["capabilities"]["run_plan"] and not view["blockers"]:
                        view["blockers"].append(
                            {
                                "code": "RESOURCE_FACT_REQUIRED",
                                "detail": "尚无精确全范围、当前可信测试资源事实。",
                            }
                        )
                for sample in request.samples:
                    key = (row.request_id, sample.id)
                    if key in samples:
                        continue
                    sample_row = s.scalar(
                        select(SampleUnit).where(
                            SampleUnit.tenant_id == ctx.tenant_id,
                            SampleUnit.product_id == product_id,
                            SampleUnit.build_id == row.build_id,
                            SampleUnit.id == sample.id,
                        )
                    )
                    if sample_row:
                        sample_view, _, _ = physical._sample_view(
                            s, ctx, product_id, request, sample_row, read_context=read_context
                        )
                        samples[key] = {**sample_view, "request_id": str(row.request_id)}
            result["requests"].append(view)
        except DomainError as error:
            if error.status != 403:
                result["unavailable_count"] += 1
    for row in run_rows[:200]:
        if row.visibility == "private" and row.owner_id != ctx.requester_id:
            continue
        try:
            source_status = _read_evidence(s, ctx, product_id, row)
            run, plan = _snapshot(row)
            pointer, current = pointers.get(row.request_id, (None, None))
            is_current = current is not None and current.id == row.id
            view = _run_view(row, run, current=is_current)
            if run.status == "running":
                try:
                    view.update(_saved_effects(s, ctx, product_id, row))
                except DomainError as error:
                    if error.status == 403:
                        raise
                    view["blockers"].append({"code": error.code, "detail": error.message})
            view["source_status"] = source_status
            view["authority_snapshot"] = view["authority"]
            view["authority"] = {}
            if is_current and row.request_id in current_requests:
                result["current_by_run"][str(run.id)] = {
                    "run_version_id": str(pointer.run_version_id),
                    "revision": pointer.run_revision,
                }
                request_row, request, _ = current_requests[row.request_id]
                for key, cls in (("schedule_promise", PromisePayload), ("run_start", StartPayload)):
                    view["authority"][key] = front._assess(
                        s, ctx, product_id, row.project_id, OPERATIONS[key], request.purpose
                    )
                    eligible = run.status == "planned" and (
                        request.status == "accepted"
                        if key == "schedule_promise"
                        else request.status == "scheduled"
                    )
                    if not eligible or source_status != "current":
                        continue
                    at = plan.window.start if key == "schedule_promise" else now()
                    payload = cls(
                        request_id=request.id,
                        expected_request_revision=request_row.revision,
                        run_id=run.id,
                        expected_run_revision=run.revision,
                        expected_plan_sha256=row.plan_sha256,
                        at={
                            "occurred_at": at,
                            "original_timezone": plan.window.original_timezone,
                            "source": physical.event_source(plan.equipment),
                        },
                        reason="读取当前固定Run能力",
                    )
                    try:
                        bound = _capability(s, ctx, product, OPERATIONS[key], payload)
                        view["capabilities"][key] = True
                        view["resource_report"] = bound.resources.report.model_dump(mode="json")
                        view["required_source_read_set"] = bound.physical.reads
                        view["current_evaluation"] = "evaluated_current"
                    except DomainError as error:
                        view["blockers"].append({"code": error.code, "detail": error.message})
            result["runs"].append(view)
        except DomainError as error:
            if error.status != 403:
                result["unavailable_count"] += 1
    result["reference_samples"] = list(samples.values())
    for fact in resource_views:
        executor = UUID(fact["binding"]["executor_id"])
        fact["executor_label"] = s.scalar(
            select(Principal.name).where(
                Principal.tenant_id == ctx.tenant_id,
                Principal.id == executor,
                Principal.active.is_(True),
            )
        )
    for key in OPERATIONS:
        result["capabilities"][key] = any(
            v["capabilities"].get(key, False) for v in result["requests"] + result["runs"]
        )
    return result
