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
from sqlalchemy.orm import Session

from pdos_next.contracts import Command
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.professional_authority.service import authority_time_current
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
from pdos_next.request_proof import batch_read, command_inputs_once, snapshot_get, snapshot_scalar
from pdos_next.schemas.verification.contracts import (
    Coverage,
    ExecutionConditions,
    RunPlan,
    RunStart,
    SchedulePromise,
    TestRun,
)
from pdos_next.service import digest, require_access, source_for

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
category_lifecycle_fence = True

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
    row = snapshot_get(s, model, identity, scope_id=product_id)
    if row is None or row.tenant_id != ctx.tenant_id or row.product_id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "测试办理对象不在当前可见型号范围。", 403)
    return row


def _current(s, ctx, product_id, run_id, *, lock=False):
    q = select(VerificationRunCurrent).where(
        VerificationRunCurrent.tenant_id == ctx.tenant_id,
        VerificationRunCurrent.product_id == product_id,
    )
    q = q.where(VerificationRunCurrent.run_id == run_id)
    pointer = snapshot_scalar(
        s,
        (VerificationRunCurrent, product_id, run_id),
        q,
        lock=lock,
        scope_id=product_id,
    )
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


def _currents_for_request(s, ctx, product_id, request_id, *, lock=False):
    from pdos_next.request_proof import snapshot_rows

    query = (
        select(VerificationRunCurrent)
        .where(
            VerificationRunCurrent.tenant_id == ctx.tenant_id,
            VerificationRunCurrent.product_id == product_id,
            VerificationRunCurrent.request_id == request_id,
        )
        .order_by(VerificationRunCurrent.run_id)
    )
    pointers = snapshot_rows(
        s,
        (VerificationRunCurrent, "request", product_id, request_id, lock),
        query.with_for_update() if lock else query,
        scope_id=product_id,
    )
    result = []
    for pointer in pointers:
        row = _row(s, ctx, product_id, VerificationRunVersion, pointer.run_version_id)
        if (row.run_id, row.request_id, row.revision) != (
            pointer.run_id,
            pointer.request_id,
            pointer.run_revision,
        ):
            raise DomainError("INTEGRITY_MISMATCH", "Run当前指针无法核对。")
        result.append((pointer, row))
    return result


def _promise(s, ctx, product_id, run_id):
    fact = snapshot_scalar(
        s,
        (VerificationLaunchFact, "promise", product_id, run_id),
        select(VerificationLaunchFact).where(
            VerificationLaunchFact.tenant_id == ctx.tenant_id,
            VerificationLaunchFact.product_id == product_id,
            VerificationLaunchFact.run_id == run_id,
            VerificationLaunchFact.operation == "verification.schedule.promise",
        ),
        scope_id=product_id,
    )
    if fact is not None:
        value = PromisePayload.model_validate(fact.input_snapshot)
        if (
            value.run_id != fact.run_id
            or value.request_id != fact.request_id
            or value.expected_run_revision != fact.run_revision
            or digest(fact.kernel_event) != fact.snapshot_sha256
        ):
            raise DomainError("INTEGRITY_MISMATCH", "Run具名承诺的固定事实无法核对。")
    return fact


def _promise_view(fact):
    return (
        {
            "id": str(fact.id),
            "at": fact.input_snapshot["at"],
            "recorded_at": fact.created_at.isoformat(),
            "sources": fact.sources,
            "reason": fact.reason,
        }
        if fact
        else None
    )


def _version(s, ctx, product_id, run_id, revision):
    row = snapshot_scalar(
        s,
        (VerificationRunVersion, "version", product_id, run_id, revision),
        select(VerificationRunVersion).where(
            VerificationRunVersion.tenant_id == ctx.tenant_id,
            VerificationRunVersion.product_id == product_id,
            VerificationRunVersion.run_id == run_id,
            VerificationRunVersion.revision == revision,
        ),
        scope_id=product_id,
    )
    if row is None:
        raise DomainError("VERSION_CONFLICT", "固定Run版本不存在。")
    return row


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
    if not pairs(coverage) <= pairs(accepted_coverage(request)):
        raise DomainError("INVALID_COVERAGE", "Run须明确选取实际已接收的样件/测试项。", 422)


def _fixed_plan(value):
    # Both closed DTOs validate first. Compare every fixed field by canonical
    # value, not Pydantic's nominal base/subclass identity for exact references.
    return value.model_dump(
        mode="json",
        include={"window", "executor_id", "equipment", "calibration", "environment", "conditions"},
    )


def _binding(row, request, run_id, plan, methods, coverage):
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
            for c in coverage
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
    direct_contract: bool = False
    direct_authority_stamp: object = None
    direct_sources: tuple = ()
    direct_prepared: dict | None = None
    direct_watermark: dict | None = None
    direct_material_sha256: str | None = None


def _close_start_boundary(s, ctx, bound, *, check_deadlines=True):
    """The v2 Start owner closes its own IO without changing legacy v1 gates."""
    if getattr(bound, "direct_contract", False):
        _direct_close(s, ctx, bound)
        return
    if getattr(bound, "fingerprint_runtime", None) is None:
        return
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow
    from pdos_next.domain.test_resources import service as resources

    resources._same_fingerprint_runtime(s, bound.fingerprint_runtime)
    _same_uow(s, bound.caller_uow, ctx, bound.caller_digest)
    if not check_deadlines:
        return  # Qualification failures retain the existing explicit _guards code.
    clock = now()  # No owner IO after these real expiry checks.
    if not authority_time_current(bound.physical.authority, clock) or resources.expired(
        bound.resources, clock
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


def _prefetch_formal_parents(s, ctx, product_id, request, methods):
    """Read exact method parents together; their original guards still run later."""
    if (
        not isinstance(s, Session)
        or not s.info.get("read_snapshot")
        or not s.in_transaction()
        or s.new
        or s.dirty
        or s.deleted
        or not methods
    ):
        return
    scope = (ctx.tenant_id, product_id, request.scope.project_id, request.id)

    def parent(row):
        if (
            row is not None
            and (
                row.tenant_id,
                row.product_id,
                row.project_id,
                row.request_id,
            )
            == scope
        ):
            return row.request_version_id
        return None

    identities = {parent(row) for row in methods.values()} - {None}
    if not identities:
        return
    for doc in request.documents:
        if (
            doc.id.startswith(PROFESSIONAL_PREFIX)
            and doc.source
            and doc.source.kind == "domain"
            and doc.source.position == METHOD_POSITION
        ):
            row = snapshot_get(s, MethodApplicability, doc.source.id, scope_id=product_id)
            identities.add(parent(row))
    identities.discard(None)
    if len(identities) > 1:
        # batch_read keeps the RLS-loaded ORM rows alive in this same RR Session.
        # _row/_snapshot, actual/planned binding, sources and qualification checks
        # retain their existing order; this read supplies no successful proof.
        batch_read(s, FormalVerificationRequest, identities)


@command_inputs_once
def _load(s, ctx, command, product, payload, *, require_reads=True, verify_event=True):
    if isinstance(payload, StartPayload):
        return _load_start_direct(
            s,
            ctx,
            command,
            product,
            payload,
            require_reads=require_reads,
            verify_event=verify_event,
        )
    write = not getattr(s, "info", {}).get("read_snapshot", False)
    _human(s, ctx, product.id, write=write)
    require_access(s, ctx, product.id, write=True, lock=write)
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "开测不在服务器绑定产品。", 403)
    # Parent/pointer gates precede every global resource and sample gate. Historical
    # replays still lock the actual current parent, without applying a premature CAS.
    _, current_request = front._current(s, ctx, product.id, payload.request_id, lock=write)
    row = (
        current_request
        if current_request is not None
        and current_request.revision == payload.expected_request_revision
        else front._version(
            s, ctx, product.id, payload.request_id, payload.expected_request_revision
        )
    )
    request = front._snapshot(row)
    _, current_run = _current(s, ctx, product.id, payload.run_id, lock=write)
    identity = select(VerificationRunIdentity).where(
        VerificationRunIdentity.tenant_id == ctx.tenant_id,
        VerificationRunIdentity.product_id == product.id,
        VerificationRunIdentity.id == payload.run_id,
    )
    snapshot_scalar(
        s,
        (VerificationRunIdentity, product.id, payload.run_id),
        identity,
        lock=write,
        scope_id=product.id,
    )
    build = front._build(s, ctx, product.id, request.build.id)
    _, _, _, reads = front._linked(s, ctx, product.id, build, new_consumption=True)
    authority = front._assess(
        s, ctx, product.id, build.project_id, command.operation, request.purpose, write=write
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
        run_row = (
            current_run
            if current_run is not None
            and current_run.run_id == payload.run_id
            and current_run.revision == payload.expected_run_revision
            else _version(s, ctx, product.id, payload.run_id, payload.expected_run_revision)
        )
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
        write=write,
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
        value = physical._inspect(s, ctx, product.id, request, sample, write=write)
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
        expected = _binding(origin, origin_request, payload.run_id, plan, methods, coverage)
    else:
        binding = expected = _binding(row, request, payload.run_id, plan, methods, coverage)
    if binding != expected:
        raise DomainError("SOURCE_CHANGED", "Run原已接收范围、配置或实际方法固定版本已漂移。")
    _prefetch_formal_parents(s, ctx, product.id, request, methods)
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
    if row.visibility == "category" and (
        private
        or any(v["visibility"] != "category" for v in inspected.values())
        or fact.visibility != "category"
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
    if getattr(bound, "direct_contract", False):
        _direct_close(s, ctx, bound)
        return
    p, a = bound.physical, bound.physical.authority
    if (
        a["authorized"] is not True
        or a["qualified"] is not True
        or a["subject_id"] != str(ctx.requester_id)
        or not authority_time_current(a, now())
    ):
        raise DomainError(
            "QUALIFICATION_REQUIRED", "当前本人缺少本Run用途的品质/测试职责及资格。", 403
        )
    expected = {"quality", "test"} if isinstance(payload, StartPayload) else {"quality"}
    if not set(a["roles"]) & expected:
        raise DomainError("FORBIDDEN_OPERATION", "该操作缺少对应专业职责。", 403)
    physical._execution(s, ctx, product.id, p.build)
    selected_items = {pair.item_id for pair in bound.binding.pairs}
    for doc in p.base.documents:
        if (
            doc.id.startswith(PROFESSIONAL_PREFIX)
            and doc.source
            and set(doc.item_ids) & selected_items
        ):
            row = snapshot_get(s, MethodApplicability, doc.source.id, scope_id=product.id)
            if row is None or doc.source.kind != "domain" or doc.source.position != METHOD_POSITION:
                raise DomainError("SOURCE_UNAVAILABLE", "固定计划专业方法不存在。")
            if getattr(bound, "direct_contract", False):
                front._method_check(s, ctx, product.id, row, p.base, prospective=True)
            else:
                physical._bound_method_check(s, ctx, product.id, p, row)
    samples = {sample.id: sample for sample in p.base.samples}
    for c in bound.binding.pairs:
        value = p.samples[c.sample.id]
        if value["availability"] != "ready":
            raise DomainError("SAMPLE_UNAVAILABLE", "暂缓或未知实物不能计划/承诺/开测。")
        physical._bound_actual_check(
            s, ctx, product.id, p, samples[c.sample.id], value, p.methods[(c.sample.id, c.item_id)]
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
    write = not getattr(s, "info", {}).get("read_snapshot", False)
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号版本已变化，请重新读取。")
    request_pointer, current = front._current(s, ctx, product.id, payload.request_id, lock=write)
    if (
        current is None
        or current.id != bound.physical.previous.id
        or current.revision != payload.expected_request_revision
    ):
        raise DomainError("VERSION_CONFLICT", "正式请求当前版本已变化。")
    run_pointer, current_run = _current(s, ctx, product.id, payload.run_id, lock=write)
    if isinstance(payload, PlanPayload):
        identity = s.scalar(
            select(VerificationRunIdentity).where(
                VerificationRunIdentity.tenant_id == ctx.tenant_id,
                VerificationRunIdentity.product_id == product.id,
                VerificationRunIdentity.id == payload.run_id,
            )
        )
        if (
            current.status not in {"accepted", "scheduled", "executing"}
            or identity is not None
            or current_run is not None
        ):
            raise DomainError("INVALID_STATE", "已接收范围可计划新的Run；不能覆盖已有Run身份。")
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
            promise = _promise(s, ctx, product.id, payload.run_id)
            if (
                current.status not in {"scheduled", "executing"}
                or promise is None
                or promise.request_id != payload.request_id
                or promise.run_version_id != bound.run_row.id
                or promise.input_snapshot["expected_plan_sha256"] != bound.run_row.plan_sha256
            ):
                raise DomainError("INVALID_STATE", "实际开测须先有本Run固定计划的具名承诺。")
            if not bound.plan.window.start <= now() < bound.plan.window.finish:
                raise DomainError("INVALID_EVENT_TIME", "当前时间须在固定执行窗口内。", 422)
        elif (
            current.status not in {"accepted", "scheduled", "executing"}
            or _promise(s, ctx, product.id, payload.run_id) is not None
            or payload.at.occurred_at < now()
            or payload.at.occurred_at != bound.plan.window.start
        ):
            raise DomainError(
                "INVALID_STATE", "只能对本Run承诺固定窗口的未来开始，已有承诺须保留。"
            )
    return request_pointer, run_pointer


def _payload_kernel(payload, plan):
    if isinstance(payload, PlanPayload):
        return RunPlan(run_id=payload.run_id, coverage=payload.coverage)
    if isinstance(payload, StartPayload):
        return RunStart(at=payload.at, execution=_execution(plan))
    return SchedulePromise(
        run_id=payload.run_id, expected_run_revision=payload.expected_run_revision, at=payload.at
    )


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
        if source.kind == "artifact" and (
            source in refs
            or (getattr(bound, "direct_contract", False) and source in bound.direct_sources)
        ):
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
        if getattr(bound, "direct_contract", False):
            return all(
                (sample.id, pair.item_id) in p.methods
                for pair in bound.binding.pairs
                if pair.sample.id == sample.id
            )
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
                if error.reason in {"SOURCE_STALE", "ACTUAL_METHOD_UNKNOWN"}:
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
            or pairs(coverage) != {(v.sample.id, v.item_id) for v in bound.binding.pairs}
            or pairs(destructive) != expected_destructive
            or execution != _execution(bound.plan)
            or {v.id for v in samples} != {v.sample.id for v in bound.binding.pairs}
        ):
            raise DomainError("INTEGRITY_MISMATCH", "内部资源/样件占用不匹配本次固定开测确认。")
        if getattr(bound, "direct_contract", False):
            bound.reservation = resources.stage_start_prepared_direct(
                s,
                ctx,
                product.id,
                bound.binding,
                bound.plan.resource_fact_id,
                bound.plan.expected_resource_fact_revision,
                prepared=bound.direct_prepared,
                intent_digest=_intent(ctx, command, payload),
                accepted_confirmation=True,
                verified_actual_start=payload.at,
                close_current=lambda: _direct_close(s, ctx, bound),
            )
            bound.reserved_dependency_proof = bound.dependency_proof
            return
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
            getattr(mutation.request.timeline, key) != getattr(p.base.timeline, key)
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
        if getattr(bound, "direct_contract", False):
            raw.update(
                execution_proof_contract=_DIRECT_START_CONTRACT,
                direct_watermark=bound.direct_watermark,
                direct_source_basis=bound.source_basis,
                direct_material_sha256=bound.direct_material_sha256,
            )
        if resource_proof is not None:
            raw.update(
                resource_fingerprint_version=bound.fingerprint_version,
                resource_dependency_proof=resource_proof,
            )
        if getattr(bound, "direct_contract", False):
            from pdos_next.domain.test_resources.retained import direct_execution_sha256

            raw["direct_execution_sha256"] = direct_execution_sha256(raw)
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
        "promise": None,
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


def _saved_effects(s, ctx, product_id, row, *, fresh=False):
    """Observed own committed effects; no claim about current qualification/free capacity."""
    from pdos_next.domain.build_operational_facts.models import ResourceOccupancy
    from pdos_next.domain.test_resources import service as resources
    from pdos_next.domain.test_resources.models import SampleRunUsage, TestResourceReservation

    saved = row.input_snapshot.get("reservation")
    query = select(TestResourceReservation).where(
        TestResourceReservation.tenant_id == ctx.tenant_id,
        TestResourceReservation.product_id == product_id,
        TestResourceReservation.run_id == row.run_id,
    )
    from pdos_next.database import require_context

    if isinstance(s, Session):
        require_context(s, ctx)
    if not fresh and resources._owned_read_snapshot(s, product_id):
        proof = snapshot_scalar(
            s, (TestResourceReservation, product_id, row.run_id), query, scope_id=product_id
        )
    else:
        proof = s.scalar(query.execution_options(populate_existing=True))
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
    canonical_rr = not fresh and resources._canonical_rr(s)
    if canonical_rr:
        occupied = sorted(
            resources._own_occupancies(s, ctx, product_id, row.run_id),
            key=lambda value: value.resource_id,
        )
        usages = sorted(
            resources._own_usages(s, ctx, product_id, row.run_id),
            key=lambda value: value.sample_id,
        )
    else:
        query = (
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
        )
        occupied = resources._owned_rows(s, ctx, product_id, query, fresh=fresh)
        query = (
            select(SampleRunUsage)
            .where(
                SampleRunUsage.tenant_id == ctx.tenant_id,
                SampleRunUsage.product_id == product_id,
                SampleRunUsage.project_id == row.project_id,
                SampleRunUsage.build_id == row.build_id,
                SampleRunUsage.run_id == row.run_id,
            )
            .order_by(SampleRunUsage.sample_id)
        )
        usages = resources._owned_rows(s, ctx, product_id, query, fresh=fresh)
    # A wide shared collection must never silently hide wrong-scope own rows.
    # Match every predicate from the original two SELECTs before exposing IDs.
    scope = (ctx.tenant_id, product_id, row.project_id, row.build_id)
    if canonical_rr and (
        any(
            (value.tenant_id, value.product_id, value.project_id, value.build_id) != scope
            or (value.owner_kind, value.owner_execution_id) != ("test_run", row.run_id)
            for value in occupied
        )
        or any(
            (value.tenant_id, value.product_id, value.project_id, value.build_id) != scope
            or value.run_id != row.run_id
            for value in usages
        )
    ):
        raise DomainError("RUN_RESERVATION_MISSING", "原Run完整归属集合出现范围不一致。")
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
    if before_run:
        promise = _promise(s, ctx, product.id, payload.run_id)
        before_run["promise"] = _promise_view(promise)
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
        after_run["promise"] = before_run["promise"] if before_run else None
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
            "proposed_promise": {
                "run_id": str(payload.run_id),
                "at": payload.at.model_dump(mode="json"),
                "reason": payload.reason,
            }
            if isinstance(payload, PromisePayload) and not isinstance(payload, StartPayload)
            else None,
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
        if error.reason in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE"}:
            raise
        blockers.append({"code": error.reason, "detail": error.message})
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
    from pdos_next.domain.sample_handoff.service import preload_current, read_context_for
    from pdos_next.domain.test_resources import service as resources

    _human(s, ctx, product_id)
    product = snapshot_get(s, Product, product_id, scope_id=product_id)
    if product is None or product.tenant_id != ctx.tenant_id:
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
        query.order_by(FormalVerificationRequest.created_at, FormalVerificationRequest.id)
    ).all()
    run_rows = s.scalars(
        runs_query.order_by(VerificationRunVersion.created_at, VerificationRunVersion.id)
    ).all()
    resource_views = resources.list_resources(s, ctx, product_id, build_id=build_id)[
        "resource_facts"
    ]
    result = {
        "requests": [],
        "runs": [],
        "current_by_request": {},
        "current_by_run": {},
        "runs_by_request": {},
        "resource_facts": resource_views,
        "reference_samples": [],
        "capabilities": {key: False for key in OPERATIONS},
        "blockers": [],
        "has_more": False,
        "unavailable_count": 0,
    }
    current_requests, pointers, samples = {}, {}, {}
    read_context = read_context_for(s, ctx, product_id)
    for row in rows:
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
                if s.info.get("read_snapshot"):
                    from pdos_next.request_proof import batch_read

                    sample_ids = {sample.id for sample in request.samples}
                    batch_read(s, SampleUnit, sample_ids)
                    preload_current(s, ctx, product_id, sample_ids)
                view["authority"] = {}
                view["current_evaluation"] = "not_evaluated_current"
                current_requests[row.request_id] = (row, request, view)
                result["current_by_request"][str(row.request_id)] = {
                    "request_version_id": str(pointer.request_version_id),
                    "revision": pointer.request_revision,
                }
                current_runs = _currents_for_request(s, ctx, product_id, row.request_id)
                result["runs_by_request"][str(row.request_id)] = [
                    str(run.run_id) for _, run in current_runs
                ]
                pointers.update({run.run_id: (pointer, run) for pointer, run in current_runs})
                if source_status == "current" and request.status in {
                    "accepted",
                    "scheduled",
                    "executing",
                }:
                    view["authority"]["run_plan"] = front._assess(
                        s, ctx, product_id, row.project_id, OPERATIONS["run_plan"], request.purpose
                    )
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
                            coverage=tuple(
                                Coverage(sample_id=pair.sample.id, item_id=pair.item_id)
                                for pair in binding.pairs
                            ),
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
                            view["blockers"].append({"code": error.reason, "detail": error.message})
                    if not view["capabilities"]["run_plan"] and not view["blockers"]:
                        view["blockers"].append(
                            {
                                "code": "RESOURCE_FACT_REQUIRED",
                                "detail": "尚无所选已接收范围的当前可信测试资源事实。",
                            }
                        )
                for sample in request.samples:
                    key = (row.request_id, sample.id)
                    if key in samples:
                        continue
                    sample_row = snapshot_get(s, SampleUnit, sample.id, scope_id=product_id)
                    if (
                        sample_row is not None
                        and sample_row.tenant_id == ctx.tenant_id
                        and sample_row.product_id == product_id
                        and sample_row.build_id == row.build_id
                    ):
                        sample_view, _, _ = physical._sample_view(
                            s, ctx, product_id, request, sample_row, read_context=read_context
                        )
                        samples[key] = {**sample_view, "request_id": str(row.request_id)}
            result["requests"].append(view)
        except DomainError as error:
            if error.status != 403:
                result["unavailable_count"] += 1
    for row in run_rows:
        try:
            source_status = _read_evidence(s, ctx, product_id, row)
            run, plan = _snapshot(row)
            pointer, current = pointers.get(row.run_id, (None, None))
            is_current = current is not None and current.id == row.id
            view = _run_view(row, run, current=is_current)
            promise = _promise(s, ctx, product_id, row.run_id)
            # A planned historical version must not claim a later promise existed then.
            view["promise"] = (
                _promise_view(promise)
                if promise and (is_current or promise.created_at <= row.created_at)
                else None
            )
            if run.status == "running":
                try:
                    view.update(_saved_effects(s, ctx, product_id, row))
                except DomainError as error:
                    if error.status == 403:
                        raise
                    view["blockers"].append({"code": error.reason, "detail": error.message})
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
                    eligible = (
                        run.status == "planned"
                        and request.status in {"accepted", "scheduled", "executing"}
                        and (promise is None if key == "schedule_promise" else promise is not None)
                    )
                    if not eligible or source_status != "current":
                        continue
                    view["authority"][key] = front._assess(
                        s, ctx, product_id, row.project_id, OPERATIONS[key], request.purpose
                    )
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
                        view["blockers"].append({"code": error.reason, "detail": error.message})
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


_DIRECT_START_CONTRACT = "s0-direct-v1"
_DIRECT_START_MATERIAL = "s0.minimal-test-run-start.v1"


@dataclass
class _DirectStartPhase:
    bound: Bound
    pointers: tuple
    mutation: object
    material: dict
    review: dict


def _direct_authority_stamp(s, assessment):
    """Only current executor issuer entries; old signers and other scopes are absent."""
    engine = s.get_bind()
    registry = getattr(engine, "_pdos_professional_issuers", {})
    epochs = getattr(engine, "_pdos_professional_issuer_epochs", {})
    from pdos_next.domain.professional_authority import service as professional

    values = []
    scope = assessment["scope"]
    for ref in assessment["fact_refs"]:
        issuer = registry.get(ref["issuer_key"])
        try:
            professional._issuer(
                engine,
                issuer,
                UUID(scope["tenant_id"]),
                UUID(scope["product_id"]),
                UUID(scope["project_id"]),
            )
        except DomainError as exc:
            raise DomainError("SOURCE_STALE", "当前执行者签发入口已变化。") from exc
        if (
            issuer.version != ref["issuer_version"]
            or issuer.epoch != ref["issuer_epoch"]
            or epochs.get(ref["issuer_key"]) != ref["issuer_epoch"]
        ):
            raise DomainError("SOURCE_STALE", "当前执行者签发入口已变化。")
        values.append((ref["issuer_key"], issuer, issuer.epoch))
    return tuple(values)


def _direct_close(s, ctx, bound):
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow

    _same_uow(s, bound.caller_uow, ctx, bound.caller_digest)
    from pdos_next.domain.professional_authority import service as professional

    person, grant = professional._subject_access(
        s, ctx, bound.physical.base.scope.product_id, ctx.requester_id
    )
    clock = now()
    if (
        person is None
        or grant is None
        or person.active is not True
        or person.kind != "human"
        or grant.can_write is not True
        or (grant.expires_at is not None and grant.expires_at <= clock)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "当前执行者授权已失效。", 403)
    if (
        bound.direct_authority_stamp != _direct_authority_stamp(s, bound.physical.authority)
        or not authority_time_current(bound.physical.authority, clock)
        or not bound.plan.window.start <= clock < bound.plan.window.finish
    ):
        raise DomainError("SOURCE_STALE", "当前执行者资格或本次实际执行窗口已变化。")


def _direct_start_references(request_row, request, run, plan, payload):
    """Select just references actually consumed by the Start rule, not inherited reads."""
    wanted = [payload.at.source]
    wanted += [
        ref
        for item in run.items
        for ref in (
            item.drawing,
            item.method,
            item.criterion_source,
            item.criterion.source if item.criterion else None,
        )
        if ref
    ]
    wanted += [
        doc.source
        for doc in request.documents
        if doc.source and set(doc.item_ids) & {c.item_id for c in run.coverage}
    ]
    declared = physical._merge_refs(
        request_row.sources,
        [v.model_dump(mode="json") for v in payload.sources],
        [plan.equipment.model_dump(mode="json"), plan.calibration.model_dump(mode="json")],
    )
    refs = physical._merge_refs(
        [v.model_dump(mode="json") for v in payload.sources],
        [plan.equipment.model_dump(mode="json"), plan.calibration.model_dump(mode="json")],
    )
    for source in wanted:
        if source.kind != "artifact":
            continue
        matches = [
            ref
            for ref in declared
            if physical.event_source(
                SimpleNamespace(**{**ref, "artifact_id": UUID(ref["artifact_id"])})
            )
            == source
        ]
        if not matches:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "直接文档来源缺少原固定引用。")
        refs = physical._merge_refs(refs, matches)
    return refs, wanted


def _direct_start_summaries(s, ctx, pid, request, binding, *, write):
    from pdos_next.domain.build_execution.models import SampleUnit
    from pdos_next.domain.sample_handoff import service as readiness

    samples, methods, watermarks = {}, {}, {"samples": [], "methods": []}
    for pair in sorted(binding.pairs, key=lambda p: (p.sample.id.bytes, p.item_id)):
        sample = pair.sample
        if sample.id not in samples:
            unit = _row(s, ctx, pid, SampleUnit, sample.id)
            pointer, fact = readiness._current(s, ctx, pid, sample.id, lock=write)
            if (
                fact is None
                or (
                    unit.project_id,
                    unit.build_id,
                    unit.revision,
                    unit.actual_configuration_id,
                    fact.project_id,
                    fact.build_id,
                    fact.sample_revision,
                    fact.actual_configuration_id,
                    fact.actual_configuration_revision,
                    fact.purpose,
                    fact.status,
                )
                != (
                    binding.project_id,
                    binding.build_id,
                    sample.revision,
                    sample.actual_configuration.id,
                    binding.project_id,
                    binding.build_id,
                    sample.revision,
                    sample.actual_configuration.id,
                    sample.actual_configuration.revision,
                    binding.purpose,
                    "ready",
                )
                or unit.availability == "hold"
                or not readiness._visible(fact, ctx)
            ):
                raise DomainError("SAMPLE_UNAVAILABLE", "直接实物版本或本用途Current就绪已变化。")
            fixed = fact.fixed_snapshot
            if (
                fixed["sample"]["id"] != str(unit.id)
                or fixed["sample"]["revision"] != unit.revision
                or fixed["actual_configuration"]["id"] != str(sample.actual_configuration.id)
                or fixed["actual_configuration"]["revision"] != sample.actual_configuration.revision
                or fixed["build"]["id"] != str(binding.build_id)
            ):
                raise DomainError("INTEGRITY_MISMATCH", "就绪摘要未绑定本次固定实际配置。")
            clocks = {
                "occurred_at": fact.occurred_at.isoformat(),
                "received_at": fact.received_at.isoformat(),
                "original_timezone": fact.occurred_timezone,
            }
            summary = deepcopy(fixed)
            summary.update(
                availability="ready",
                purpose=binding.purpose,
                visibility=fact.visibility,
                clocks=clocks,
                facts_revision=digest([str(fact.id), fact.revision, fact.snapshot_sha256]),
                current_readiness={
                    "id": str(fact.id),
                    "revision": fact.revision,
                    "state": fact.status,
                    "purpose": fact.purpose,
                    "clocks": clocks,
                    "source_ref": {
                        "kind": "domain",
                        "id": str(fact.id),
                        "revision": fact.revision,
                        "position": "sample-readiness",
                    },
                },
            )
            samples[sample.id] = summary
            watermarks["samples"].append(
                [
                    str(ctx.tenant_id),
                    str(pid),
                    str(binding.project_id),
                    str(binding.build_id),
                    str(unit.id),
                    unit.revision,
                    str(sample.actual_configuration.id),
                    sample.actual_configuration.revision,
                    str(pointer.id),
                    str(fact.id),
                    fact.revision,
                    fact.snapshot_sha256,
                    fact.status,
                    fact.purpose,
                    unit.availability,
                ]
            )
        pointer, row = physical._method_pointer(
            s, ctx, pid, request.id, sample.id, pair.item_id, lock=write
        )
        if (
            row is None
            or row.status != "applicable"
            or (
                row.id,
                row.revision,
                row.snapshot_sha256,
                row.project_id,
                row.build_id,
                row.sample_revision,
                row.actual_configuration_id,
                row.actual_configuration_revision,
            )
            != (
                pair.method_id,
                pair.method_revision,
                pair.method_sha256,
                binding.project_id,
                binding.build_id,
                sample.revision,
                sample.actual_configuration.id,
                sample.actual_configuration.revision,
            )
        ):
            raise DomainError("ACTUAL_METHOD_UNKNOWN", "直接实际方法Current或固定适用版本已变化。")
        item = next(v for v in request.items if v.id == pair.item_id)
        if (
            row.method_digest != digest(item.model_dump(mode="json"))
            or row.snapshot_sha256 != digest(row.assessment_snapshot)
            or row.assessment_snapshot["sample"] != sample.model_dump(mode="json")
            or row.assessment_snapshot["fixed_item"] != item.model_dump(mode="json")
            or row.assessment_snapshot["actual_configuration"]
            != samples[sample.id]["actual_configuration"]
        ):
            raise DomainError("INTEGRITY_MISMATCH", "直接实际方法摘要无法核对。")
        methods[(sample.id, pair.item_id)] = row
        watermarks["methods"].append(
            [
                str(ctx.tenant_id),
                str(pid),
                str(request.id),
                str(sample.id),
                pair.item_id,
                str(pointer.id),
                str(row.id),
                row.revision,
                row.snapshot_sha256,
                row.method_digest,
                row.status,
            ]
        )
    return samples, methods, watermarks


def _load_start_direct(
    s, ctx, command, product, payload, *, require_reads=True, verify_event=True, owner_material=None
):
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow
    from pdos_next.domain.configurations.schemas import DefinitionReference
    from pdos_next.domain.quality_execution.evidence import refs_from_exact
    from pdos_next.domain.test_resources import service as resources
    from pdos_next.source_current import direct_source_basis

    caller_uow, caller_digest = _uow(s), digest(vars(ctx))
    write = not s.info.get("read_snapshot", False)
    _human(s, ctx, product.id, write=write)
    require_access(s, ctx, product.id, write=True, lock=write)
    if command.operation != "test.run.start" or command.product_id != product.id:
        raise DomainError("FORBIDDEN_SCOPE", "直接开测阶段未绑定服务器操作及产品。", 403)
    row = front._version(s, ctx, product.id, payload.request_id, payload.expected_request_revision)
    request = front._snapshot(row)
    run_row = _version(s, ctx, product.id, payload.run_id, payload.expected_run_revision)
    run, plan = _snapshot(run_row)
    if (
        run.request_id != request.id
        or run.build != request.build
        or run_row.plan_sha256 != payload.expected_plan_sha256
    ):
        raise DomainError("SOURCE_CHANGED", "固定Run或计划版本已变化。")
    binding = TestPlanBinding.model_validate(run_row.input_snapshot["plan_binding"])
    _full_coverage(request, run.coverage)
    if (
        binding.run_id != run.id
        or binding.request_id != request.id
        or binding.build_id != request.build.id
        or binding.project_id != request.scope.project_id
        or binding.purpose != request.purpose
        or _fixed_plan(binding) != _fixed_plan(plan)
        or {(p.sample.id, p.item_id) for p in binding.pairs} != pairs(run.coverage)
    ):
        raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "固定Run绑定范围无法核对。")
    refs, wanted = _direct_start_references(row, request, run, plan, payload)
    reads = _merge_reads(refs)
    if require_reads:
        supplied = {str(v.artifact_id): v.expected_revision for v in command.source_read_set}
        if any(supplied.get(v["artifact_id"]) != v["expected_revision"] for v in reads):
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "须固定本次直接消费来源的版本。")
    # Preserve DefinitionReference's existing substring locator semantics while
    # supplying the common source port with the actual complete original line.
    canonical = refs_from_exact(
        s, ctx, product.id, tuple(DefinitionReference.model_validate(v) for v in refs)
    )
    basis, private = direct_source_basis(s, ctx, product, canonical, reads)
    if verify_event:
        _event(s, ctx, product.id, request, plan, payload, refs, actual=True)
    authority = front._assess(
        s,
        ctx,
        product.id,
        request.scope.project_id,
        command.operation,
        request.purpose,
        write=write,
    )
    if (
        authority["authorized"] is not True
        or authority["qualified"] is not True
        or authority["subject_id"] != str(ctx.requester_id)
        or not set(authority["roles"]) & {"quality", "test"}
        or not authority_time_current(authority, now())
        or binding.executor_id != ctx.requester_id
    ):
        raise DomainError("QUALIFICATION_REQUIRED", "当前执行者未满足本次具名开测资格。", 403)
    authority_stamp = _direct_authority_stamp(s, authority)
    # No external Source/Original IO follows the direct Current/capacity reads.
    build = front._build(s, ctx, product.id, request.build.id)
    samples, methods, current = _direct_start_summaries(
        s, ctx, product.id, request, binding, write=write
    )
    for doc in request.documents:
        if (
            doc.source
            and doc.id.startswith(PROFESSIONAL_PREFIX)
            and set(doc.item_ids) & {c.item_id for c in run.coverage}
        ):
            fixed = _row(s, ctx, product.id, MethodApplicability, doc.source.id)
            if doc.source.kind != "domain" or doc.source.position != METHOD_POSITION:
                raise DomainError("SOURCE_UNAVAILABLE", "固定专业适用来源不匹配。")
            # prospective checks are purely the original immutable hash/scope
            # checks; Start does not re-evaluate the historical reviewer.
            front._method_check(s, ctx, product.id, fixed, request, prospective=True)
    p = physical.Bound(
        row, request, build, authority, refs, reads, basis, samples, methods, row.visibility, now()
    )
    bound = Bound(
        p,
        run_row,
        run,
        plan,
        binding,
        None,
        None,
        basis,
        fingerprint_version=resources._FINGERPRINT_V2,
        caller_uow=caller_uow,
        caller_digest=caller_digest,
        direct_contract=True,
        direct_authority_stamp=authority_stamp,
        direct_sources=tuple(wanted),
    )
    pointers = _new_write(s, ctx, command, product, payload, bound)
    rp, vp = pointers
    current.update(
        request=[
            str(ctx.tenant_id),
            str(product.id),
            str(request.scope.project_id),
            str(request.build.id),
            str(rp.id),
            str(row.id),
            row.revision,
            row.snapshot_sha256,
        ],
        run=[
            str(ctx.tenant_id),
            str(product.id),
            str(request.scope.project_id),
            str(request.build.id),
            str(vp.id),
            str(run_row.id),
            run_row.revision,
            run_row.snapshot_sha256,
            run_row.plan_sha256,
        ],
        executor=authority["facts_revision"],
        sources=basis,
        product_revision=product.revision,
    )
    if owner_material is None:
        prepared = resources.prepare_start_direct(
            s,
            ctx,
            product.id,
            binding,
            plan.resource_fact_id,
            plan.expected_resource_fact_revision,
            authority=authority,
            samples=samples,
            source_basis=basis,
            reads=reads,
            verified_actual_start=payload.at if verify_event else None,
        )
    else:
        prepared = deepcopy(owner_material["resource"])
        _fact, data, _assets, _sentinels, resource_watermark = resources._direct_start_inputs(
            s,
            ctx,
            product.id,
            binding,
            plan.resource_fact_id,
            plan.expected_resource_fact_revision,
            write=write,
        )
        if prepared["watermark"] != resource_watermark or prepared["data"] != data.model_dump(
            mode="json"
        ):
            raise DomainError("RESOURCE_FACTS_CHANGED", "确认后直接资源或容量水位已变化。")
    current["resource"] = prepared["watermark"]
    bound.resources = resources.BoundTestResources.model_validate(prepared["bundle"])
    bound.dependency_proof = resources._verify_stored_fingerprint_v2(prepared["dependency_proof"])
    bound.direct_prepared, bound.direct_watermark = prepared, current
    if row.visibility == "category" and (
        private
        or prepared["visibility"] != "category"
        or any(v["visibility"] != "category" for v in samples.values())
    ):
        raise DomainError("FORBIDDEN_SCOPE", "私有直接来源或样件不能扩大到共享请求。", 403)
    _direct_close(s, ctx, bound)
    return bound


def prepare_preview(s, ctx, command, product, payload):
    bound = _load_start_direct(s, ctx, command, product, payload)
    k = _kernel(s, ctx, command, product, payload, bound, lambda _: None)
    value = _payload_kernel(payload, bound.plan)
    preview, mutation = k._prepare(
        authority_dto(bound.physical.authority, ctx.requester_id, now()),
        _invocation(command, payload, value),
        value,
    )
    if not preview.allowed:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "固定开测直接资料不完整。")
    material = {
        "schema_version": _DIRECT_START_MATERIAL,
        "operation": command.operation,
        "scope": {
            "tenant_id": str(ctx.tenant_id),
            "category_id": str(ctx.category_id),
            "product_id": str(product.id),
            "requester_id": str(ctx.requester_id),
        },
        "intent_digest": _intent(ctx, command, payload),
        "direct_watermark": bound.direct_watermark,
        "request_version_id": str(bound.physical.previous.id),
        "run_version_id": str(bound.run_row.id),
        "resource": bound.direct_prepared,
        "prepared_mutation": mutation.model_dump(mode="json"),
        "source_basis": bound.source_basis,
    }
    material["material_sha256"] = digest(material)
    bound.direct_material_sha256 = material["material_sha256"]
    report = bound.resources.report.model_dump(mode="json")
    report["checked_at"] = None
    report["checked_at_basis"] = "server_direct_watermark_on_confirm"
    review = {
        "operation": command.operation,
        "effect": EFFECT,
        "before": {
            "request": {
                "id": str(bound.physical.previous.id),
                "request_id": str(bound.physical.base.id),
                "revision": bound.physical.base.revision,
                "status": bound.physical.base.status,
                "request_snapshot": bound.physical.base.model_dump(mode="json"),
            },
            "run": _run_view(bound.run_row, bound.run),
        },
        "after": {
            "request": mutation.request.model_dump(mode="json"),
            "run": mutation.run.model_dump(mode="json"),
            "resource_report": report,
            "sample_usage": [v.model_dump(mode="json") for v in bound.resources.sample_usage],
            "occupancy_effect": "stage_formal_and_sample_use_in_caller_uow",
        },
        "authority": bound.physical.authority,
        "required_source_read_set": bound.physical.reads,
        "resource_report": report,
        "reason": payload.reason,
    }
    _direct_close(s, ctx, bound)
    return _DirectStartPhase(
        bound, _new_write(s, ctx, command, product, payload, bound), mutation, material, review
    )


def preview_prepared(s, ctx, command, product, payload, phase):
    if phase.material["intent_digest"] != _intent(ctx, command, payload):
        raise DomainError("INTEGRITY_MISMATCH", "开测预览阶段意图已变化。")
    _direct_close(s, ctx, phase.bound)
    return deepcopy(phase.review)


def encode_prepared(phase):
    return deepcopy(phase.material)


def prepare_confirmed(s, ctx, command, product, payload, owner_material):
    from pdos_next.domain.verification.ports import Mutation

    if (
        type(owner_material) is not dict
        or owner_material.get("schema_version") != _DIRECT_START_MATERIAL
        or owner_material.get("operation") != command.operation
        or owner_material.get("intent_digest") != _intent(ctx, command, payload)
        or owner_material.get("scope")
        != {
            "tenant_id": str(ctx.tenant_id),
            "category_id": str(ctx.category_id),
            "product_id": str(product.id),
            "requester_id": str(ctx.requester_id),
        }
    ):
        raise DomainError("CONFIRMATION_REQUIRED", "缺少服务器保存的本次开测预览材料。", 403)
    if owner_material.get("material_sha256") != digest(
        {key: value for key, value in owner_material.items() if key != "material_sha256"}
    ):
        raise DomainError("INTEGRITY_MISMATCH", "服务器预览开测材料摘要不能核对。")
    bound = _load_start_direct(s, ctx, command, product, payload, owner_material=owner_material)
    bound.direct_material_sha256 = owner_material["material_sha256"]
    if (
        bound.direct_watermark != owner_material["direct_watermark"]
        or str(bound.physical.previous.id) != owner_material["request_version_id"]
        or str(bound.run_row.id) != owner_material["run_version_id"]
    ):
        raise DomainError("SOURCE_STALE", "预览后的直接Current版本或水位已变化。")
    mutation = Mutation.model_validate(owner_material["prepared_mutation"])
    if (
        mutation.operation != command.operation
        or mutation.request_before_revision != bound.physical.base.revision
        or mutation.run_before_revision != bound.run.revision
        or mutation.request.id != bound.physical.base.id
        or mutation.run.id != bound.run.id
        or mutation.run.status != "running"
        or mutation.run.coverage != bound.run.coverage
        or mutation.run.execution != _execution(bound.plan)
        or mutation.run.actual_start.occurred_at != payload.at.occurred_at
        or mutation.run.actual_start.source != payload.at.source
    ):
        raise DomainError("INTEGRITY_MISMATCH", "保存的预览变化未精确绑定本次开测。")
    return _DirectStartPhase(
        bound,
        _new_write(s, ctx, command, product, payload, bound),
        mutation,
        deepcopy(owner_material),
        {},
    )


def apply_confirmed(s, ctx, command, product, payload, phase):
    from pdos_next.domain.test_resources import service as resources
    from pdos_next.domain.verification.ports import Mutation

    bound = phase.bound
    if phase.material["intent_digest"] != _intent(ctx, command, payload):
        raise DomainError("INTEGRITY_MISMATCH", "确认消费后开测意图不能替换。")
    _direct_close(s, ctx, bound)
    bound.reservation = resources.stage_start_prepared_direct(
        s,
        ctx,
        product.id,
        bound.binding,
        bound.plan.resource_fact_id,
        bound.plan.expected_resource_fact_revision,
        prepared=bound.direct_prepared,
        intent_digest=_intent(ctx, command, payload),
        accepted_confirmation=True,
        verified_actual_start=payload.at,
        close_current=lambda: _direct_close(s, ctx, bound),
    )
    bound.reserved_dependency_proof = bound.dependency_proof
    raw = phase.mutation.model_dump(mode="json")
    clock = now().isoformat()
    raw["run"]["actual_start"]["received_at"] = clock
    if bound.physical.base.timeline.actual_start is None:
        raw["request"]["timeline"]["actual_start"]["received_at"] = clock
    for event in raw["events"]:
        event["at"]["received_at"] = clock
    row = _record(
        s, ctx, command, product, payload, bound, phase.pointers, Mutation.model_validate(raw)
    )
    _direct_close(s, ctx, bound)
    return row, "test_run", bound.physical.visibility
