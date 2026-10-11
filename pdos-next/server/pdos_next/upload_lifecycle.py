"""Durable upload reservation and named terminal decision; exceptions prove nothing."""

from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.models import (
    Principal,
    Product,
    Receipt,
    RequestKey,
    UploadAttempt,
    UploadedOriginal,
    now,
)
from pdos_next.object_storage import ObjectRef
from pdos_next.originals import object_reference, upload_contents
from pdos_next.service import digest, require_access


def exact_reference(document):
    return ObjectRef(
        UUID(document["id"]),
        document["version"],
        document["content_sha256"],
        document["size_bytes"],
        document["media_type"],
        document["server_storage_key"],
    )


def reference_document(reference):
    value = reference.as_dict(include_storage_key=True)
    value.pop("scan_status")
    return value


def named(s, ctx, product_id):
    product = require_access(s, ctx, product_id, write=True, lock=True)
    if product_id is not None:
        product = s.scalar(select(Product).where(Product.id == product_id).with_for_update())
    actor = s.get(Principal, ctx.actor_id)
    if ctx.run_id or ctx.agent_run_id or ctx.actor_id != ctx.requester_id or actor.kind != "human":
        raise DomainError("NAMED_DECISION_REQUIRED", "上传登记需要具名本人办理。", 403)
    return product


def reserve(s, ctx, product_id, data):
    require_access(s, ctx, product_id)
    content, media, request, fingerprint = upload_contents(data)
    key = s.scalar(
        select(RequestKey).where(
            RequestKey.actor_id == ctx.actor_id, RequestKey.key == data.idempotency_key
        )
    )
    if key:
        receipt = s.get(Receipt, key.receipt_id)
        if (
            key.digest != fingerprint
            or not receipt
            or receipt.product_id != product_id
            or receipt.operation != "evidence.original.upload"
        ):
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原上传请求对应不同范围或内容。")
        return None
    intent = digest(
        ["evidence.original.upload", ctx.category_id, product_id, ctx.requester_id, request]
    )
    if s.scalar(
        select(Receipt.id).where(
            Receipt.category_id == ctx.category_id,
            Receipt.product_id == product_id,
            Receipt.intent_digest == intent,
        )
    ):
        return None
    product = named(s, ctx, product_id)
    previous = s.scalar(
        select(UploadAttempt).where(
            UploadAttempt.owner_id == ctx.requester_id,
            UploadAttempt.request_key == data.idempotency_key,
        )
    )
    if previous:
        if previous.product_id != product_id or previous.request_digest != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原上传请求对应不同内容。")
        if previous.status == "abandoned":
            raise DomainError("UPLOAD_CLOSED", "此上传已具名终止，不能继续登记。")
        return previous.id
    equivalent = s.scalar(
        select(UploadAttempt).where(
            UploadAttempt.product_id == product_id,
            UploadAttempt.owner_id == ctx.requester_id,
            UploadAttempt.request_digest == fingerprint,
            UploadAttempt.status == "reserved",
        )
    )
    if equivalent:
        return equivalent.id
    if product.revision != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "型号范围已变化。")
    from hashlib import sha256

    object_id, content_hash = uuid4(), sha256(content).hexdigest()
    reference = ObjectRef(
        object_id,
        1,
        content_hash,
        len(content),
        media,
        f"originals/{object_id.hex}/v1/{content_hash}",
    )
    row = UploadAttempt(
        id=object_id,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product_id,
        owner_id=ctx.requester_id,
        request_key=data.idempotency_key,
        request_digest=fingerprint,
        reference=reference_document(reference),
        title=data.title,
        filename=data.filename,
    )
    s.add(row)
    s.flush()
    return row.id


def require_reserved(s, ctx, product_id, attempt, fingerprint, reference=None):
    s.refresh(attempt)
    if (
        attempt.category_id != ctx.category_id
        or attempt.product_id != product_id
        or attempt.owner_id != ctx.requester_id
        or attempt.request_digest != fingerprint
        or attempt.status != "reserved"
        or (reference is not None and exact_reference(attempt.reference) != reference)
    ):
        raise DomainError("UPLOAD_CLOSED", "上传登记已关闭或不属于当前请求。")


def _row(s, ctx, product_id, object_id):
    named(s, ctx, product_id)
    row = s.get(UploadAttempt, object_id)
    if not row or row.product_id != product_id or row.owner_id != ctx.requester_id:
        raise DomainError("SOURCE_UNAVAILABLE", "上传登记不在当前本人范围。", 403)
    return row


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def validate(s, ctx, command, product, payload):
    _row(s, ctx, product.id, payload.object_id)
    if command.source_read_set:
        raise DomainError("INVALID_PAYLOAD", "终止上传不接受额外来源。", 422)


def preview_view(s, ctx, command, product, payload):
    row = _row(s, ctx, product.id, payload.object_id)
    if command.expected_revision != product.revision or row.revision != payload.expected_revision:
        raise DomainError("VERSION_CONFLICT", "上传或产品已变化。")
    if row.status != "reserved" or s.get(UploadedOriginal, row.id):
        raise DomainError("REGISTERED_ORIGINAL", "已登记或已终止的上传不能再次终止。")
    return {
        "before": {
            "id": str(row.id),
            "title": row.title,
            "status": row.status,
            "revision": row.revision,
        },
        "after": {"status": "abandoned", "reason": payload.reason},
        "effect": "关闭这个未完成上传的后续登记；已有字节继续保留，隔离仍需独立核对与确认。",
    }


def apply(s, ctx, command, product, payload):
    preview_view(s, ctx, command, product, payload)
    row = _row(s, ctx, product.id, payload.object_id)
    row.status, row.terminal_at, row.reason = "abandoned", now(), payload.reason
    row.revision += 1
    return row, "upload_attempt", "private"


def reconcile_terminal(s, ctx, product_id, attempt_id, store):
    """Only a committed reservation state is positive terminal evidence for the journal."""
    row = _row(s, ctx, product_id, attempt_id)
    reference = exact_reference(row.reference)
    if row.status == "committed":
        original = s.get(UploadedOriginal, row.id)
        if not original or object_reference(original) != reference:
            raise DomainError("BINDING_MISMATCH", "原件登记与上传身份不一致。")
        store.mark_registered(row.id, reference)
    elif row.status == "abandoned":
        if s.get(UploadedOriginal, row.id):
            raise DomainError("REGISTERED_ORIGINAL", "登记原件受保护。")
        store.mark_aborted(
            row.id,
            reference,
            terminal_evidence_ref=f"upload-attempt:{row.id}:revision:{row.revision}",
            reason_code="NAMED_ABANDONMENT",
        )
