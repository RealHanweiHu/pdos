"""Current original safety and immutable worker facts; no public clean-result endpoint."""

import asyncio
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.dispatch.context import event_context
from pdos_next.errors import DomainError
from pdos_next.evidence_security.rules import bind_request, parsing_gate
from pdos_next.evidence_security.types import (
    ScanBinding,
    ScanConfiguration,
    ScanLimits,
    ScannerIdentity,
    ScanPolicy,
    ScanReceipt,
    ScanRequest,
    ScanStatus,
)
from pdos_next.models import (
    Artifact,
    Grant,
    OriginalScanRequest,
    OriginalScanResult,
    OriginalSecurity,
    Principal,
    Product,
    Receipt,
    RequestKey,
    UploadedOriginal,
    now,
)
from pdos_next.object_storage import ObjectRef


@dataclass(frozen=True)
class SecurityRuntime:
    configuration: ScanConfiguration
    scanner: object
    parser: object


def configure(engine, runtime):
    # Installed by the trusted process entry point or an explicit test fixture only.
    engine._pdos_security_runtime = runtime


def runtime_for(s):
    return getattr(s.get_bind(), "_pdos_security_runtime", None)


def encoded(value):
    return json.loads(
        json.dumps(
            asdict(value), default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v)
        )
    )


def decoded_request(value):
    binding = dict(value["binding"])
    reference = dict(binding.pop("object_ref"))
    reference["id"] = UUID(reference["id"])
    for key in ("tenant_id", "product_id", "category_id", "requester_id"):
        binding[key] = UUID(binding[key]) if binding.get(key) else None
    policy = dict(value["policy"])
    policy["limits"] = ScanLimits(**policy["limits"])
    return ScanRequest(
        UUID(value["request_id"]),
        ScanBinding(ObjectRef(**reference), **binding),
        ScannerIdentity(**value["scanner"]),
        ScanPolicy(**policy),
        datetime.fromisoformat(value["requested_at"]),
    )


def decoded_receipt(value, request):
    # Reconstruct the stored binding independently; do not repair a mismatching receipt.
    bound = decoded_request(
        {**encoded(request), "binding": value["binding"], "scanner": value["scanner"]}
    )
    return ScanReceipt(
        UUID(value["request_id"]),
        bound.binding,
        bound.scanner,
        value["policy_digest"],
        ScanStatus(value["status"]),
        datetime.fromisoformat(value["started_at"]),
        datetime.fromisoformat(value["completed_at"]),
        value.get("error_code"),
    )


def security_row(s, original, *, lock=True):
    from pdos_next.request_proof import request_proof

    proof = request_proof(s)
    key = (OriginalSecurity, ("original", original.id))
    lock_key = (OriginalSecurity, ("locked", original.id))
    if key in proof.read_rows and (not lock or proof.read_rows.get(lock_key)):
        return proof.read_rows[key]
    query = select(OriginalSecurity).where(
        OriginalSecurity.original_id == original.id,
        OriginalSecurity.product_id == original.product_id,
    )
    row = s.scalar(query.with_for_update() if lock else query)
    if not row:
        raise DomainError("ORIGINAL_SECURITY_UNAVAILABLE", "原件安全记录待核对。", 409)
    proof.read_rows[key] = row
    proof.read_rows[lock_key] = lock
    return row


class Guard:
    def __init__(self, s, original, state, requester_id, *, lock=True):
        self.s, self.original, self.state, self.requester = s, original, state, requester_id
        self.lock = lock

    def current_configuration(self):
        runtime = runtime_for(self.s)
        if runtime is None:
            raise DomainError("SCANNER_UNAVAILABLE", "扫描服务尚未配置。", 503)
        return runtime.configuration

    def bind_for_scan(self, object_ref):
        from pdos_next.originals import object_reference
        from pdos_next.service import Context, digest, require_access

        row, state = self.original, self.state
        scope = self.s.info.get("scope")
        if not scope or not scope[1] or not scope[2]:
            raise DomainError("FORBIDDEN_SCOPE", "扫描证明缺少当前请求身份。", 403)
        ctx = Context(*scope[:3], category_id=scope[3])
        from pdos_next.request_proof import request_proof

        require_access(self.s, ctx, row.product_id, lock=self.lock)
        proof = request_proof(self.s)
        authority = proof.authority[
            (ctx.tenant_id, row.category_id, ctx.actor_id, ctx.requester_id)
        ]
        held = {principal.id: (principal, grant) for principal, grant in authority["rows"]}
        if self.requester in held:
            principal, grant = held[self.requester]
        else:
            key = (Grant, ("scan-requester", row.category_id, self.requester))
            if key not in proof.read_rows:
                proof.read_rows[key] = self.s.execute(
                    select(Principal, Grant)
                    .join(Grant, Grant.principal_id == Principal.id)
                    .where(
                        Principal.id == self.requester,
                        Principal.tenant_id == row.tenant_id,
                        Grant.category_id == row.category_id,
                        Grant.tenant_id == row.tenant_id,
                    )
                ).first()
            pair = proof.read_rows[key]
            if pair is None:
                raise DomainError("FORBIDDEN_SCOPE", "扫描来源授权需要重核。", 403)
            principal, grant = pair
        source_key = (Artifact, ("original", row.id))
        if source_key not in proof.read_rows:
            source = next(
                (
                    source
                    for source in (
                        *proof.sources.values(),
                        *proof.source_rows.values(),
                        *self.s.identity_map.values(),
                    )
                    if isinstance(source, Artifact) and source.original_id == row.id
                ),
                None,
            )
            proof.read_rows[source_key] = source or self.s.scalar(
                select(Artifact).where(Artifact.original_id == row.id)
            )
        source = proof.read_rows[source_key]
        active = (
            state.source_state == "active"
            and state.disposition == "active"
            and (not source or source.status == "active")
        )
        if object_ref != object_reference(row):
            active = False
        return ScanBinding(
            object_reference(row),
            row.tenant_id,
            row.product_id,
            self.requester,
            state.epoch,
            digest(
                [
                    grant.id,
                    grant.can_write,
                    grant.expires_at,
                    grant.access_epoch,
                    principal.active,
                    principal.access_epoch,
                ]
            ),
            digest([row.owner_id, row.visibility, state.source_state, state.disposition]),
            active,
            category_id=row.category_id,
        )

    def is_current(self, binding):
        try:
            return binding == self.bind_for_scan(binding.object_ref) and binding.source_active
        except DomainError:
            return False


def decision(s, original, state, *, lock=False):
    from pdos_next.request_proof import batch_read, request_proof

    record = (
        batch_read(s, OriginalScanRequest, [state.current_request_id])[state.current_request_id]
        if state.current_request_id
        else None
    )
    if not record:
        return None, None, None
    request = decoded_request(record.binding)
    proof = request_proof(s)
    key = (OriginalScanResult, ("request", record.id))
    if key not in proof.read_rows:
        proof.read_rows[key] = s.scalar(
            select(OriginalScanResult).where(OriginalScanResult.request_id == record.id)
        )
    stored = proof.read_rows[key]
    receipt = decoded_receipt(stored.result, request) if stored else None
    return (
        parsing_gate(
            request, receipt, Guard(s, original, state, record.requester_id, lock=lock), now=now()
        ),
        record,
        stored,
    )


def require_safe(s, ctx, original, *, lock=True):
    from pdos_next.service import require_access

    require_access(s, ctx, original.product_id, lock=lock)
    state = security_row(s, original, lock=lock)
    gate, _, _ = decision(s, original, state, lock=lock)
    if (
        not gate
        or not gate.allow_parse
        or state.source_state != "active"
        or state.disposition != "active"
    ):
        raise DomainError(
            "ORIGINAL_SECURITY_BLOCKED", "原件尚无当前有效的安全扫描，或来源已失效。", 409
        )
    return state.epoch, state.current_request_id


def view(s, original, ctx=None, store=None):
    from pdos_next.service import require_access

    state = security_row(s, original, lock=False)
    gate, record, result = decision(s, original, state)
    write = False
    if ctx:
        try:
            require_access(s, ctx, original.product_id, write=True)
            write = (
                ctx.actor_id == ctx.requester_id and s.get(Principal, ctx.actor_id).kind == "human"
            )
        except DomainError:
            pass
    status = gate.state.value if gate else "not_scanned"
    reasons = list(gate.reasons) if gate else ["SCAN_REQUIRED"]
    if runtime_for(s) is None:
        status, reasons = "unavailable", ["SCANNER_UNAVAILABLE"]
    elif record and not result and gate and gate.state.value == "not_scanned":
        status = "scanning"
    if state.source_state != "active":
        status, reasons = "stale", ["SOURCE_WITHDRAWN"]
    scan = None
    if record:
        req = decoded_request(record.binding)
        scan = {
            "id": str(record.id),
            "status": result.status if result else "requested",
            **asdict(req.scanner),
            "policy_version": req.policy.version,
            "requested_at": req.requested_at.isoformat(),
            "completed_at": result.result["completed_at"] if result else None,
            "error_code": result.result.get("error_code") if result else None,
        }
    journal_state = "unknown"
    if store and hasattr(store, "inspect"):
        try:
            journal_state = str(store.inspect(original.id).state)
        except Exception:
            journal_state = "unknown"
    return {
        "state": status,
        "reasons": reasons,
        "epoch": state.epoch,
        "source_state": state.source_state,
        "scan": scan,
        "capabilities": {
            "scan": write
            and state.source_state == "active"
            and state.disposition == "active"
            and runtime_for(s) is not None,
            "download": bool(gate and gate.allow_parse),
            "withdraw": write and state.source_state == "active",
        },
        "lifecycle": {
            "disposition": state.disposition,
            "registered": True,
            "protection_reasons": ["REGISTERED_ORIGINAL", "REFERENCE_COVERAGE_UNPROVEN"],
            "journal_state": journal_state,
            "physical_actions_available": False,
        },
    }


def source_status(s, source):
    if source.status != "active" or not source.original_id:
        return source.status
    from pdos_next.service import Context

    original = s.get(UploadedOriginal, source.original_id)
    if not original:
        return "unavailable"
    try:
        scope = s.info.get("scope")
        if not scope or not scope[1] or not scope[2]:
            return "unavailable"
        require_safe(s, Context(*scope[:3], category_id=scope[3]), original, lock=False)
    except DomainError:
        return "stale"
    return "active"


def request_scan(s, ctx, product_id, original_id, *, expected_epoch, idempotency_key):
    from pdos_next.originals import object_reference, require_original
    from pdos_next.service import append_receipt, digest, receipt_view, require_access

    require_access(s, ctx, product_id)
    fingerprint = digest(["scan", product_id, original_id, expected_epoch])
    key = s.scalar(
        select(RequestKey).where(
            RequestKey.actor_id == ctx.actor_id, RequestKey.key == idempotency_key
        )
    )
    if key:
        if key.digest != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "相同请求编号对应不同扫描。")
        return receipt_view(s.get(Receipt, key.receipt_id))
    product = require_access(s, ctx, product_id, write=True, lock=True)
    if product_id is not None:
        product = s.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if (
        ctx.run_id
        or ctx.actor_id != ctx.requester_id
        or s.get(Principal, ctx.actor_id).kind != "human"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "此入口只接收具名人员的扫描请求。", 403)
    original = require_original(s, ctx, product_id, original_id, lock=True)
    state = security_row(s, original)
    guard = Guard(s, original, state, ctx.requester_id)
    if not guard.bind_for_scan(object_reference(original)).source_active:
        raise DomainError("SOURCE_UNAVAILABLE", "原件已撤回或生命周期状态不允许扫描。", 409)
    if state.epoch != expected_epoch:
        raise DomainError("VERSION_CONFLICT", "原件安全状态已变化，请刷新后重试。")
    configuration = guard.current_configuration()
    req = bind_request(
        guard,
        object_reference(original),
        request_id=uuid4(),
        scanner=configuration.scanner,
        policy=configuration.policy,
        now=now(),
    )
    # The locked current facts were just authorized. Reserve the next epoch in
    # the request, then advance its pointer once, in this same transaction.
    req = replace(req, binding=replace(req.binding, original_revision=state.epoch + 1))
    record = OriginalScanRequest(
        id=req.request_id,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product_id,
        original_id=original.id,
        requester_id=ctx.requester_id,
        revision=state.epoch + 1,
        binding=encoded(req),
    )
    s.add(record)
    s.flush()
    state.epoch += 1
    state.current_request_id = record.id
    original.scan_status = "not_scanned"
    command = Command(
        category_id=ctx.category_id,
        command_id=uuid4(),
        idempotency_key=idempotency_key,
        operation="evidence.original.scan.request",
        product_id=product_id,
        expected_revision=product.revision,
        payload={"original_id": str(original.id)},
    )
    receipt = append_receipt(
        s,
        ctx,
        command,
        "original_scan_request",
        record,
        fingerprint,
        digest(["scan", req.request_id]),
        original.visibility,
    )
    s.add(
        RequestKey(
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            key=idempotency_key,
            digest=fingerprint,
            receipt_id=receipt.id,
        )
    )
    return receipt_view(receipt)


def queue_uploaded(engine, reference):

    ctx = event_context(reference)
    tenant, original_id = UUID(reference["tenant_id"]), UUID(reference["subject_id"])
    product_id = UUID(reference["product_id"]) if reference.get("product_id") else None
    with tenant_session(
        engine,
        tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as s:
        from pdos_next.service import require_access

        require_access(s, ctx, product_id)
        original = s.get(UploadedOriginal, original_id)
        if not original or original.product_id != product_id:
            raise DomainError("SOURCE_UNAVAILABLE", "待扫描原件不可用。", 403)
        state = security_row(s, original)
        if state.current_request_id:
            return {"status": "requested", "request_id": str(state.current_request_id)}
        receipt = request_scan(
            s,
            ctx,
            product_id,
            original_id,
            expected_epoch=state.epoch,
            idempotency_key=f"initial-scan:{original_id}",
        )
        return {"status": "requested", "request_id": receipt["subject_id"]}


def scan_requested(engine, reference):
    from pdos_next.originals import require_original
    from pdos_next.service import append_receipt, digest

    ctx = event_context(reference)
    tenant, request_id = UUID(reference["tenant_id"]), UUID(reference["subject_id"])
    product_id = UUID(reference["product_id"]) if reference.get("product_id") else None
    with tenant_session(
        engine,
        tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as s:
        from pdos_next.service import require_access

        require_access(s, ctx, product_id)
        record = s.get(OriginalScanRequest, request_id)
        if not record or record.product_id != product_id:
            raise DomainError("SOURCE_UNAVAILABLE", "扫描请求不可用。", 403)
        request = decoded_request(record.binding)
        if record.requester_id != ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "扫描范围信封与具名请求不符。", 403)
        original = require_original(s, ctx, product_id, record.original_id, lock=True)
        state = security_row(s, original)
        guard = Guard(s, original, state, record.requester_id)
        if state.current_request_id != request_id or not guard.is_current(request.binding):
            return {"status": "stale", "original_id": str(original.id)}
        runtime = runtime_for(s)
        if not runtime or runtime.configuration != ScanConfiguration(
            request.scanner, request.policy
        ):
            return {"status": "unavailable", "original_id": str(original.id)}
        previous = s.scalar(
            select(OriginalScanResult).where(OriginalScanResult.request_id == request_id)
        )
        if previous:
            return {"status": previous.status, "original_id": str(original.id)}
    result = asyncio.run(runtime.scanner.scan(request))
    with tenant_session(
        engine,
        tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as s:
        from pdos_next.service import require_access

        require_access(s, ctx, product_id)
        original = require_original(s, ctx, product_id, request.binding.object_ref.id, lock=True)
        state = security_row(s, original)
        guard = Guard(s, original, state, ctx.requester_id)
        if state.current_request_id != request_id or not guard.is_current(request.binding):
            return {"status": "stale", "original_id": str(original.id)}
        if guard.current_configuration() != ScanConfiguration(request.scanner, request.policy):
            return {"status": "stale", "original_id": str(original.id)}
        if (
            result.request_id != request.request_id
            or result.binding != request.binding
            or result.scanner != request.scanner
            or result.policy_digest != request.policy.digest
        ):
            raise DomainError("SCAN_BASIS_CHANGED", "扫描回执与原请求不符，未提交结果。")
        previous = s.scalar(
            select(OriginalScanResult).where(OriginalScanResult.request_id == request_id)
        )
        if previous:
            return {"status": previous.status, "original_id": str(original.id)}
        gate = parsing_gate(request, result, guard, now=now())
        if gate.state.value == "stale" and result.status == ScanStatus.CLEAN:
            return {"status": "stale", "original_id": str(original.id)}
        stored = OriginalScanResult(
            id=uuid4(),
            tenant_id=tenant,
            category_id=ctx.category_id,
            product_id=product_id,
            original_id=original.id,
            request_id=request_id,
            revision=state.epoch,
            status=result.status.value,
            result=encoded(result),
        )
        s.add(stored)
        original.scan_status = result.status.value
        s.flush()
        command = Command(
            category_id=ctx.category_id,
            command_id=uuid4(),
            idempotency_key=f"scan-result:{request_id}",
            operation="evidence.original.scan.record",
            product_id=product_id,
            expected_revision=original.revision,
            payload={"request_id": str(request_id)},
        )
        append_receipt(
            s,
            ctx,
            command,
            "original_scan_result",
            stored,
            digest(stored.result),
            digest(["scan-result", request_id]),
            original.visibility,
        )
        return {"status": stored.status, "original_id": str(original.id)}
