"""Narrow shared-UOW callbacks; no qualification, receipt, commit or completion default.

The common consumer calls record_consumed_confirmation immediately after its
validated False->True transition, before flushing it. A marker is tied to the
actual Session and transaction objects, not merely a historical consumed bool.
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import inspect, select

from pdos_next.clock import proof_deadline_current
from pdos_next.domain.quality_execution.evidence import merge_reads, union_sources
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.quality_followup import service as followup
from pdos_next.domain.quality_issues.rules import issue_sources
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Principal, now
from pdos_next.schemas.quality_issues.contracts import Issue
from pdos_next.service import digest, material_digest

LINK = "quality.capa.followup.link"
OP_TIERS = {followup.ROOT_CAUSE: "T2", followup.COMPLETE: "T1", LINK: "T1"}
_MARKERS = object()


@dataclass(frozen=True)
class _Consumed:
    session: object
    transaction: object
    nested_transaction: object
    command_id: UUID
    context_digest: str
    command_digest: str
    material_digest: str
    semantic_digest: str
    read_digest: str
    confirmation_id: UUID
    confirmation_digest: str
    operation: str
    tier: str


def configure_host(engine):
    """Install append/proof assertions; completion assessment stays unavailable."""
    followup.configure_followup(
        engine,
        append_issue=append_issue,
        consumed_proof=require_consumed_proof,
        assess_action_completion=None,
    )


def expired_confirmation_recovery(s, ctx, command, product, payload, module):
    """Only common execute calls this after all receipt paths under its Product lock.

    A missing or consumed proof never authorizes renewal. This read adds no fact,
    does not consume a proof, and does not authorize the subsequent preview/save.
    """
    if (
        command.operation not in OP_TIERS
        or ctx.run_id is not None
        or ctx.actor_id != ctx.requester_id
        or product.tenant_id != ctx.tenant_id
        or product.id != command.product_id
        or product.revision != command.expected_revision
    ):
        return None
    token = getattr(
        payload, "approval_token" if OP_TIERS[command.operation] == "T2" else "confirmation_token"
    )
    if not token:
        return None
    proof = s.scalar(
        select(Confirmation)
        .where(
            Confirmation.tenant_id == ctx.tenant_id,
            Confirmation.actor_id == ctx.actor_id,
            Confirmation.product_id == product.id,
            Confirmation.subject_id == product.id,
            Confirmation.operation == command.operation,
            Confirmation.token_hash == digest(token),
        )
        .with_for_update()
    )
    if (
        proof is None
        or proof.consumed is not False
        or proof_deadline_current(OP_TIERS[command.operation], proof.expires_at, now())
        or proof.revision != product.revision
        or proof.payload_digest != material_digest(ctx, command, payload, module)
    ):
        return None
    current = s.scalar(
        select(QualityIssueCurrent)
        .where(
            QualityIssueCurrent.tenant_id == ctx.tenant_id,
            QualityIssueCurrent.product_id == product.id,
            QualityIssueCurrent.issue_id == payload.issue_id,
            QualityIssueCurrent.issue_revision == payload.expected_issue_revision,
        )
        .with_for_update()
    )
    if current is None:
        return None
    safe_command = command.model_dump(mode="json")
    safe_command["payload"] = {
        key: value
        for key, value in safe_command["payload"].items()
        if key not in {"confirmation_token", "approval_token"}
    }
    return {"state": "not_saved_expired_proof", "command": safe_command}


def _module(operation):
    if operation in followup.PAYLOADS:
        return followup
    if operation == LINK:
        from pdos_next.domain.capa_verification import commands

        return commands
    raise DomainError("FORBIDDEN_OPERATION", "此共同证明不属于品质后续开放操作。", 403)


def _transaction(s):
    transaction = s.get_transaction()
    if transaction is None or transaction.is_active is not True:
        raise DomainError("INTEGRATION_REQUIRED", "共同消费须在实际活动事务内。", 503)
    nested = s.get_nested_transaction()
    if nested is not None and nested.is_active is not True:
        raise DomainError("INTEGRATION_REQUIRED", "共同消费子事务不可用。", 503)
    return transaction, nested


def _context(ctx):
    if ctx.run_id is not None or ctx.actor_id != ctx.requester_id:
        raise DomainError("NAMED_DECISION_REQUIRED", "品质后续须具名本人办理。", 403)
    return digest(
        {
            "tenant": ctx.tenant_id,
            "actor": ctx.actor_id,
            "requester": ctx.requester_id,
            "run": ctx.run_id,
            "cancel_epoch": ctx.cancel_epoch,
        }
    )


def _principal(s, ctx):
    actor = s.execute(
        select(Principal.tenant_id, Principal.kind, Principal.active).where(
            Principal.id == ctx.actor_id
        )
    ).one_or_none()
    if actor is None or tuple(actor) != (ctx.tenant_id, "human", True):
        raise DomainError("NAMED_DECISION_REQUIRED", "具名本人当前身份不可用。", 403)


def _command(command, payload, module):
    expected = _module(command.operation)
    if module is not expected:
        raise DomainError("INTEGRITY_MISMATCH", "共同证明绑定的领域模块不一致。")
    token = getattr(
        payload,
        "approval_token" if OP_TIERS[command.operation] == "T2" else "confirmation_token",
        None,
    )
    if not isinstance(token, str) or not token:
        raise DomainError("NAMED_APPROVAL_REQUIRED", "共同实际办理证明缺失。")
    if command.payload != payload.model_dump(mode="json", exclude_unset=True):
        # Common prepared payload may include explicitly serialized defaults;
        # compare the full validated DTO instead of deleting any fields.
        validated = type(payload).model_validate(command.payload)
        if validated != payload:
            raise DomainError("INTEGRITY_MISMATCH", "共同证明载荷与原命令不一致。")
    raw = command.model_dump(mode="json")
    raw["payload"] = module.semantic(payload)
    raw["token_hash"] = digest(token)
    return digest(raw), digest(token)


def _confirmation_material(row):
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "product_id": row.product_id,
        "actor_id": row.actor_id,
        "subject_id": row.subject_id,
        "operation": row.operation,
        "revision": row.revision,
        "token_hash": row.token_hash,
        "payload_digest": row.payload_digest,
        "snapshot": row.snapshot,
        "expires_at": row.expires_at,
        "consumed": row.consumed,
    }


def _check_confirmation(row, ctx, command, token_hash, material):
    if (
        not isinstance(row, Confirmation)
        or not isinstance(row.id, UUID)
        or (
            row.tenant_id,
            row.product_id,
            row.actor_id,
            row.subject_id,
            row.operation,
            row.revision,
        )
        != (
            ctx.tenant_id,
            command.product_id,
            ctx.actor_id,
            command.product_id,
            command.operation,
            command.expected_revision,
        )
        or row.token_hash != token_hash
        or row.payload_digest != material
        or row.consumed is not True
        or not isinstance(row.snapshot, dict)
        or not proof_deadline_current(OP_TIERS[command.operation], row.expires_at, now())
    ):
        raise DomainError("NAMED_APPROVAL_REQUIRED", "共同实际已消费证明绑定或有效期不能核对。")


def record_consumed_confirmation(s, ctx, command, payload, module, confirmation):
    """Record ONLY the real common consumer's unflushed False->True transition.

    The caller has already validated the material/snapshot, then assigned True.
    This method does not consume or mint a proof. A historical consumed row or
    a detached/transient fabricated object cannot establish provenance.
    """
    transaction, nested = _transaction(s)
    context = _context(ctx)
    command_hash, token_hash = _command(command, payload, module)
    material = material_digest(ctx, command, payload, module)
    _check_confirmation(confirmation, ctx, command, token_hash, material)
    state = inspect(confirmation)
    history = state.attrs.consumed.history
    if (
        state.session is not s
        or state.persistent is not True
        or tuple(history.deleted) != (False,)
        or tuple(history.added) != (True,)
    ):
        raise DomainError("NAMED_APPROVAL_REQUIRED", "须由本事务实际消费共同证明后立即记录。")
    marker = _Consumed(
        s,
        transaction,
        nested,
        command.command_id,
        context,
        command_hash,
        material,
        digest(module.semantic(payload)),
        digest(merge_reads(command.source_read_set)),
        confirmation.id,
        digest(_confirmation_material(confirmation)),
        command.operation,
        OP_TIERS[command.operation],
    )
    # Purge ended/rolled-back transaction markers; no cross-transaction cache.
    markers = {
        key: value
        for key, value in s.info.get(_MARKERS, {}).items()
        if value.transaction is transaction and value.nested_transaction is nested
    }
    old = markers.get(command.command_id)
    if old is not None and old != marker:
        raise DomainError("INTEGRITY_MISMATCH", "同一命令的实际消费证明发生变化。")
    markers[command.command_id] = marker
    s.info[_MARKERS] = markers
    return confirmation.id


def _live_marker(s, ctx, marker):
    transaction, nested = _transaction(s)
    if (
        not isinstance(marker, _Consumed)
        or marker.session is not s
        or marker.transaction is not transaction
        or marker.nested_transaction is not nested
        or marker.context_digest != _context(ctx)
    ):
        raise DomainError("NAMED_APPROVAL_REQUIRED", "没有本次同事务实际已消费的证明。")


def _locked_confirmation(s, marker):
    row = s.scalar(
        select(Confirmation)
        .where(Confirmation.id == marker.confirmation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or digest(_confirmation_material(row)) != marker.confirmation_digest:
        raise DomainError("SOURCE_STALE", "共同实际证明记录已改变。")
    if not proof_deadline_current(marker.tier, row.expires_at, now()):
        raise DomainError("NAMED_APPROVAL_REQUIRED", "共同实际证明已过有效期。")
    return row


def require_consumed_proof(s, ctx, command, payload, *, tier):
    """Assert a common proof; never consume again, mint an ID or run preview."""
    module = _module(command.operation)
    marker = s.info.get(_MARKERS, {}).get(command.command_id)
    _live_marker(s, ctx, marker)
    command_hash, token_hash = _command(command, payload, module)
    if (
        tier != OP_TIERS[command.operation]
        or marker.tier != tier
        or marker.operation != command.operation
        or marker.command_digest != command_hash
        or marker.material_digest != material_digest(ctx, command, payload, module)
        or marker.read_digest != digest(merge_reads(command.source_read_set))
    ):
        raise DomainError("NAMED_APPROVAL_REQUIRED", "证明分级或本次命令实质绑定不一致。")
    _principal(s, ctx)
    row = _locked_confirmation(s, marker)
    _check_confirmation(row, ctx, command, token_hash, marker.material_digest)
    return row.id


def _append_proof(s, ctx, product, operation, input_snapshot, reads, source_basis):
    proof = source_basis.get("shared_proof", {})
    try:
        identity = UUID(proof["id"])
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise DomainError("NAMED_APPROVAL_REQUIRED", "问题追加缺共同实际证明。") from exc
    matching = [
        marker
        for marker in s.info.get(_MARKERS, {}).values()
        if marker.confirmation_id == identity and marker.operation == operation
    ]
    if len(matching) != 1:
        raise DomainError("NAMED_APPROVAL_REQUIRED", "问题追加未绑定本事务唯一实际证明。")
    marker = matching[0]
    _live_marker(s, ctx, marker)
    if (
        marker.semantic_digest != digest(input_snapshot)
        or marker.read_digest != digest(reads)
        or proof.get("tier") != OP_TIERS.get(operation)
    ):
        raise DomainError("NAMED_APPROVAL_REQUIRED", "问题追加意图/读集与实际证明不一致。")
    _principal(s, ctx)
    confirmation = _locked_confirmation(s, marker)
    if (confirmation.product_id, confirmation.revision) != (product.id, product.revision):
        raise DomainError("VERSION_CONFLICT", "共同证明产品水位已变化。")
    return confirmation


def append_issue(
    s,
    ctx,
    product,
    before_row,
    mutation,
    *,
    operation,
    authority,
    policy_snapshot,
    required_source_read_set,
    source_basis,
    input_snapshot,
    intent_digest,
    expected_issue_revision,
):
    """Append one existing Issue, same Session; no receipt/commit/second aggregate."""
    if operation not in followup.PAYLOADS:
        raise DomainError("FORBIDDEN_OPERATION", "此追加接口只开放具名根因与本人完成。", 403)
    if len(mutation.changes) != 1 or mutation.insert_ids or mutation.deliveries:
        raise DomainError("INTEGRITY_MISMATCH", "后续仅可追加现有一个问题版。")
    before = Issue.model_validate(before_row.issue_snapshot)
    after = mutation.changes[0]
    if (
        not isinstance(before_row, QualityIssueVersion)
        or digest(before.model_dump(mode="json")) != before_row.snapshot_sha256
        or (
            before_row.tenant_id,
            before_row.product_id,
            before_row.project_id,
            before_row.issue_id,
            before_row.revision,
            before_row.status,
        )
        != (
            ctx.tenant_id,
            product.id,
            before.scope.project_id,
            before.id,
            before.revision,
            before.status,
        )
        or before.scope.tenant_id != ctx.tenant_id
        or before.scope.product_id != product.id
        or after.scope != before.scope
        or after.id != before.id
        or after.revision != before.revision + 1
        or expected_issue_revision != before.revision
        or input_snapshot.get("issue_id") != str(before.id)
        or input_snapshot.get("expected_issue_revision") != before.revision
        or after.audience != before.audience
        or intent_digest
        != digest(
            {
                "operation": operation,
                "actor": str(ctx.requester_id),
                "product": str(product.id),
                "payload": input_snapshot,
            }
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "问题追加不能改变固定身份、范围、前版或受众。")
    state = inspect(before_row)
    if state.session is not s or state.persistent is not True:
        raise DomainError("INTEGRITY_MISMATCH", "问题前版须是本Session真实已保存的原版本。")
    expected_audience = (
        f"private:{before_row.owner_id}"
        if before_row.visibility == "private"
        else f"category:{before_row.category_id}"
    )
    if before.audience != (expected_audience,) or (
        before_row.visibility == "private" and before_row.owner_id != ctx.requester_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "固定问题受众不在本人范围。", 403)
    reads = merge_reads(required_source_read_set)
    if not reads:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "后续完整读集不能为空。")
    confirmation = _append_proof(s, ctx, product, operation, input_snapshot, reads, source_basis)
    review = confirmation.snapshot
    reviewed = review.get("read_basis", {})
    original_basis = {
        key: value
        for key, value in source_basis.items()
        if key not in {"shared_proof", "completion_observations"}
    }
    if (
        review.get("before", {}).get(str(before.id)) != before.model_dump(mode="json")
        or review.get("after", {}).get(str(after.id)) != followup._preview_issue(after, before)
        or digest(reviewed.get("authority")) != digest(authority)
        or digest(reviewed.get("policy")) != digest(policy_snapshot)
        or digest(reviewed.get("source_basis")) != digest(original_basis)
        or merge_reads(reviewed.get("read_set", [])) != reads
    ):
        raise DomainError("CONFIRMATION_SCOPE_CHANGED", "追加聚合/依据与共同实质预览不一致。")
    pointer = s.scalar(
        select(QualityIssueCurrent)
        .where(
            QualityIssueCurrent.tenant_id == ctx.tenant_id,
            QualityIssueCurrent.product_id == product.id,
            QualityIssueCurrent.project_id == before_row.project_id,
            QualityIssueCurrent.issue_id == before.id,
        )
        .with_for_update()
    )
    if pointer is None or (pointer.issue_version_id, pointer.issue_revision) != (
        before_row.id,
        before.revision,
    ):
        raise DomainError("VERSION_CONFLICT", "后续保存前问题前版已改变。")
    sources = union_sources(
        before_row.sources,
        issue_sources(after),
        source_basis.get("followup_basis", {}).get("sources", []),
        policy_snapshot.get("sources", []),
        *(value.get("sources", []) for value in source_basis.get("completion_assessments", [])),
    )
    expected_reads = {(r["artifact_id"], r["expected_revision"]) for r in reads}
    actual_reads = {
        (value["id"], value["revision"]) for value in source_basis.get("artifact_sources", [])
    }
    if actual_reads != expected_reads or any(
        source.kind == "artifact" and (str(source.id), source.revision) not in expected_reads
        for source in sources
    ):
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "保存来源与完整已核读集不能逐项核对。")
    if before_row.visibility != "private" and any(
        value.get("visibility") == "private" for value in source_basis["artifact_sources"]
    ):
        raise DomainError("FORBIDDEN_SCOPE", "私有后续来源不能扩大原问题受众。", 403)
    raw = after.model_dump(mode="json")
    row = QualityIssueVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=before_row.project_id,
        issue_id=before.id,
        revision=after.revision,
        previous_issue_version_id=before_row.id,
        previous_revision=before.revision,
        owner_id=before_row.owner_id,
        writer_id=ctx.requester_id,
        visibility=before_row.visibility,
        purpose=before_row.purpose,
        status=after.status,
        operation=operation,
        issue_snapshot=raw,
        snapshot_sha256=digest(raw),
        input_snapshot=deepcopy(input_snapshot),
        authority_snapshot=deepcopy(authority),
        policy_snapshot=deepcopy(policy_snapshot),
        sources=[source.model_dump(mode="json") for source in sources],
        required_source_read_set=deepcopy(reads),
        source_basis=deepcopy(source_basis),
        intent_digest=intent_digest,
        reason=input_snapshot["text"]
        if operation == followup.ROOT_CAUSE
        else "具名本人记录措施实际完成",
    )
    s.add(row)
    s.flush()
    pointer.issue_version_id, pointer.issue_revision, pointer.epoch = (
        row.id,
        row.revision,
        pointer.epoch + 1,
    )
    row.action_result = {
        "issue_id": str(row.issue_id),
        "capa_id": str(after.capa.id) if after.capa else None,
    }
    s.flush()
    return row
