"""Exact source positions, immutable contents and current original-security basis."""

import re
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.models import OriginalSecurity, Receipt, Run
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest, source_for

from .schemas import SourceRead

POSITION = re.compile(r"^line:([1-9][0-9]*);quote_sha256:([0-9a-f]{64})$")


def merge_reads(*groups):
    values = {}
    for group in groups:
        for item in group:
            value = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            checked = SourceRead.model_validate(value)
            identity, revision = str(checked.artifact_id), checked.expected_revision
            if identity in values and values[identity] != revision:
                raise DomainError("SOURCE_STALE", "同一原件不能绑定两份来源版本。")
            values[identity] = revision
    if len(values) > 20:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "完整品质来源超过读集上限，不能截断。")
    return [{"artifact_id": k, "expected_revision": v} for k, v in sorted(values.items())]


def source_basis(s, ctx, pid, reads):
    basis, private = [], False
    for read in merge_reads(reads):
        row = source_for(s, ctx, pid, UUID(read["artifact_id"]), read["expected_revision"])
        if row.tenant_id != ctx.tenant_id or row.content_hash != digest(row.content):
            raise DomainError("INTEGRITY_MISMATCH", "来源范围或不可变内容摘要不一致。")
        private |= row.visibility == "private"
        entry = {
            "id": str(row.id),
            "revision": row.revision,
            "hash": row.content_hash,
            "status": row.status,
            "owner_id": str(row.owner_id),
            "visibility": row.visibility,
        }
        if row.original_id:
            safety = s.scalar(
                select(OriginalSecurity).where(
                    OriginalSecurity.tenant_id == ctx.tenant_id,
                    OriginalSecurity.product_id == pid,
                    OriginalSecurity.original_id == row.original_id,
                )
            )
            # source_for already enforced exact current original ACL and safe gate.
            if safety is None:
                raise DomainError("SOURCE_UNAVAILABLE", "原件安全事实不可核对。")
            entry["original"] = {
                "id": str(row.original_id),
                "epoch": safety.epoch,
                "source_state": safety.source_state,
                "disposition": safety.disposition,
            }
            entry["source_kind"] = "uploaded_original"
        else:
            receipt = s.scalar(
                select(Receipt).where(
                    Receipt.tenant_id == ctx.tenant_id,
                    Receipt.product_id == pid,
                    Receipt.operation == "evidence.artifact.register",
                    Receipt.subject_type == "artifact",
                    Receipt.subject_id == row.id,
                    Receipt.subject_revision == row.revision,
                )
            )
            if (
                receipt is None
                or receipt.requester_id != row.owner_id
                or receipt.visibility != row.visibility
                or receipt.result.get("id") != str(row.id)
                or receipt.result.get("revision") != row.revision
                or (receipt.run_id is None and receipt.actor_id != receipt.requester_id)
            ):
                raise DomainError("SOURCE_UNAVAILABLE", "原生文本缺少精确登记来源证明。")
            if receipt.run_id is not None:
                origin_run = s.get(Run, receipt.run_id)
                if (
                    origin_run is None
                    or origin_run.tenant_id != ctx.tenant_id
                    or origin_run.product_id != pid
                    or origin_run.requester_id != receipt.requester_id
                    or origin_run.writer_id != receipt.actor_id
                ):
                    raise DomainError("SOURCE_UNAVAILABLE", "原生文本的登记运行归属无法核对。")
            entry["source_kind"] = "registered_native_text"
            entry["registration"] = {
                "receipt_id": str(receipt.id),
                "actor_id": str(receipt.actor_id),
                "requester_id": str(receipt.requester_id),
                "run_id": str(receipt.run_id) if receipt.run_id else None,
            }
        basis.append(entry)
    return basis, private


def check_source(s, ctx, pid, source):
    source = source if isinstance(source, SourceRef) else SourceRef.model_validate(source)
    if source.kind != "artifact":
        raise DomainError("INTEGRATION_REQUIRED", "未绑定的领域证明不能充当品质来源。", 503)
    match = POSITION.fullmatch(source.position)
    if match is None:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "来源须固定整行原文摘要与行号。", 422)
    row = source_for(s, ctx, pid, source.id, source.revision)
    lines = row.content.splitlines()
    index = int(match[1]) - 1
    if index >= len(lines) or sha256(lines[index].encode()).hexdigest() != match[2]:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "固定来源无法定位精确原文行。", 422)
    reads = [{"artifact_id": str(row.id), "expected_revision": row.revision}]
    basis, private = source_basis(s, ctx, pid, reads)
    return reads, basis, private


def refs_from_exact(s, ctx, pid, references):
    sources = []
    for reference in references:
        row = source_for(s, ctx, pid, reference.artifact_id, reference.expected_revision)
        lines = row.content.splitlines()
        index = reference.line - 1
        if index >= len(lines) or reference.quote not in lines[index]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "政策出处必须精确定位原文。", 422)
        sources.append(
            SourceRef(
                id=row.id,
                revision=row.revision,
                kind="artifact",
                position=f"line:{reference.line};quote_sha256:{sha256(lines[index].encode()).hexdigest()}",
            )
        )
    return tuple(sources)


def union_sources(*groups):
    sources = {}
    for group in groups:
        for value in group:
            source = value if isinstance(value, SourceRef) else SourceRef.model_validate(value)
            sources[(str(source.id), source.revision, source.kind, source.position)] = source
    return tuple(sources[k] for k in sorted(sources))
