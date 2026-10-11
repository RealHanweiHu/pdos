"""Exact source positions, immutable contents and current original-security basis."""

import re
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, inspect, or_, select, tuple_
from sqlalchemy.orm import Session

from pdos_next.database import require_context
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Category, OriginalSecurity, Receipt, Run
from pdos_next.request_proof import request_proof, scope_is_held, snapshot_scalar
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest, source_for

from .schemas import SourceRead

POSITION = re.compile(r"^line:([1-9][0-9]*);quote_sha256:([0-9a-f]{64})$")
NATIVE_RAW_FIELDS = (
    "id",
    "tenant_id",
    "category_id",
    "product_id",
    "revision",
    "original_id",
    "status",
    "content",
    "content_hash",
    "owner_id",
    "visibility",
)


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
    return [{"artifact_id": k, "expected_revision": v} for k, v in sorted(values.items())]


def _checked_sources(s, ctx, pid, reads):
    for read in merge_reads(reads):
        row = source_for(s, ctx, pid, UUID(read["artifact_id"]), read["expected_revision"])
        if row.tenant_id != ctx.tenant_id or row.content_hash != digest(row.content):
            raise DomainError("INTEGRITY_MISMATCH", "来源范围或不可变内容摘要不一致。")
        yield row


def _snapshot_proof(s, ctx, pid):
    if not isinstance(s, Session) or not s.info.get("read_snapshot"):
        return None
    require_context(s, ctx)
    if s.get_transaction() is None or not scope_is_held(s, pid):
        return None
    return request_proof(s)


def _batch_artifact_rows(s, ctx, pid, reads, proof):
    """Share only complete RLS-read raw sources in this pristine RR owner."""
    scope = s.info.get("scope")
    if (
        s.is_active is not True
        or s.info.get("read_snapshot") is not True
        or not isinstance(scope, tuple)
        or len(scope) != 4
        or ctx.category_id is None
        or scope != (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
        or not reads
    ):
        return
    if _snapshot_proof(s, ctx, pid) is not proof:
        raise DomainError("INVALID_READ_CONTEXT", "来源读取快照已经变化。")
    owner = (s.get_transaction(), proof.mutation_epoch, digest(vars(ctx)), scope)
    owner_key = ("quality-artifact-raw-scope",)
    previous = proof.read_rows.get(owner_key)
    if previous is not None and previous != owner:
        raise DomainError("INVALID_READ_CONTEXT", "原始来源行不能跨事务身份复用。")
    identities = {UUID(read["artifact_id"]) for read in reads}
    missing = set()
    existing = {}
    for identity in identities:
        source_key = (
            ctx.tenant_id,
            ctx.actor_id,
            ctx.requester_id,
            ctx.category_id,
            pid,
            identity,
        )
        raw = (
            proof.read_rows.get((Artifact, identity))
            or proof.sources.get(source_key)
            or proof.source_rows.get(source_key)
        )
        if raw is None:
            missing.add(identity)
        else:
            existing[identity] = raw
    rows = (
        list(
            s.scalars(
                select(Artifact)
                .where(
                    Artifact.tenant_id == ctx.tenant_id,
                    Artifact.category_id == ctx.category_id,
                    Artifact.product_id.is_(None) | (Artifact.product_id == pid),
                    Artifact.id.in_(missing),
                )
                .order_by(Artifact.id)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        if missing
        else []
    )
    if (
        _snapshot_proof(s, ctx, pid) is not proof
        or (s.get_transaction(), proof.mutation_epoch, digest(vars(ctx)), s.info.get("scope"))
        != owner
    ):
        raise DomainError("INVALID_READ_CONTEXT", "原始来源读取期间事务或身份已变化。")
    actual = {row.id: row for row in rows}
    proof.read_rows.update({(Artifact, identity): raw for identity, raw in existing.items()})
    proof.read_rows.update({(Artifact, identity): actual.get(identity) for identity in missing})
    # This marker binds only raw rows. No authority, sources, current flag or
    # registration verdict is manufactured; every original guard follows below.
    proof.read_rows[owner_key] = owner


def _batch_native_registrations(s, ctx, pid, rows, proof):
    """Fill exact scalar keys with actual rows only in a clean RR transaction."""
    if _snapshot_proof(s, ctx, pid) is not proof:
        raise DomainError("INVALID_READ_CONTEXT", "来源读取快照已经变化。")
    missing = {
        (row.product_id, row.id, row.revision): (
            "scope-scalar",
            pid,
            (Receipt, "artifact-registration", row.id, row.revision),
        )
        for row in rows
        if not row.original_id
        and ("scope-scalar", pid, (Receipt, "artifact-registration", row.id, row.revision))
        not in proof.scalar_rows
    }
    if not missing:
        return
    grouped = {}
    for product_id, artifact_id, revision in missing:
        grouped.setdefault(product_id, []).append((artifact_id, revision))
    epoch = proof.mutation_epoch
    receipts = list(
        s.scalars(
            select(Receipt)
            .where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.operation == "evidence.artifact.register",
                Receipt.subject_type == "artifact",
                or_(
                    *(
                        and_(
                            Receipt.product_id.is_not_distinct_from(product_id),
                            tuple_(Receipt.subject_id, Receipt.subject_revision).in_(identities),
                        )
                        for product_id, identities in grouped.items()
                    )
                ),
            )
            .execution_options(populate_existing=True)
        )
    )
    if _snapshot_proof(s, ctx, pid) is not proof or proof.mutation_epoch != epoch:
        raise DomainError("INVALID_READ_CONTEXT", "来源读取快照已经变化。")
    actual = {}
    for receipt in receipts:
        actual.setdefault(
            (receipt.product_id, receipt.subject_id, receipt.subject_revision), receipt
        )
    for identity, key in missing.items():
        proof.scalar_rows[key] = (False, actual.get(identity))


def _writer_native_context(s, ctx, pid):
    if (
        not isinstance(s, Session)
        or s.is_active is not True
        or s.info.get("read_snapshot")
        or s.get_transaction() is None
        or s.new
        or s.dirty
        or s.deleted
    ):
        return None
    require_context(s, ctx)
    scope = s.info.get("scope")
    if (
        pid is None
        or ctx.category_id is None
        or scope != (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
        or not scope_is_held(s, pid)
    ):
        return None
    proof = request_proof(s)
    if pid not in proof.scope_locks:
        return None
    owner = (s.get_transaction(), proof.mutation_epoch, digest(vars(ctx)), scope, pid)
    previous = proof.read_rows.get(("quality-native-writer-scope", pid))
    if previous is not None and previous != owner:
        raise DomainError("INVALID_READ_CONTEXT", "登记原始行不能跨事务身份复用。")
    return proof, owner


def _writer_native_rows(s, ctx, pid, reads, proof):
    rows = []
    for read in reads:
        identity = UUID(read["artifact_id"])
        key = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id, pid, identity)
        row = (
            proof.sources.get(key)
            or proof.source_rows.get(key)
            or proof.read_rows.get((Artifact, identity))
        )
        if (
            not isinstance(row, Artifact)
            or inspect(row).unloaded.intersection(NATIVE_RAW_FIELDS)
            or proof.read_rows.get((Artifact, ("locked", identity))) is not True
            or row.id != identity
            or row.tenant_id != ctx.tenant_id
            or row.category_id != ctx.category_id
            or row.product_id not in (None, pid)
            or row.revision != read["expected_revision"]
            or (row.product_id is None and (Category, ctx.category_id) not in proof.scope_locks)
        ):
            # Missing/wrong/unlocked later raw material does not preempt the
            # current source's receipt guard or the next real source_for call.
            return None
        rows.append(row)
    return rows


def _native_rows_seal(rows):
    return digest([{name: getattr(row, name) for name in NATIVE_RAW_FIELDS} for row in rows])


def _batch_writer_native_registrations(s, ctx, pid, reads):
    """Lazy raw receipt read after the current source's real checks, never eager proof."""
    context = _writer_native_context(s, ctx, pid)
    if context is None:
        return
    proof, owner = context
    rows = _writer_native_rows(s, ctx, pid, reads, proof)
    if rows is None:
        return
    seal = _native_rows_seal(rows)
    missing = {
        (row.product_id, row.id, row.revision): (
            "scope-scalar",
            pid,
            (Receipt, "artifact-registration", row.id, row.revision),
        )
        for row in rows
        if not row.original_id
        and ("scope-scalar", pid, (Receipt, "artifact-registration", row.id, row.revision))
        not in proof.scalar_rows
    }
    grouped = {}
    for product_id, identity, revision in missing:
        grouped.setdefault(product_id, []).append((identity, revision))
    receipts = (
        list(
            s.scalars(
                select(Receipt)
                .where(
                    Receipt.tenant_id == ctx.tenant_id,
                    Receipt.category_id == ctx.category_id,
                    Receipt.operation == "evidence.artifact.register",
                    Receipt.subject_type == "artifact",
                    or_(
                        *(
                            and_(
                                Receipt.product_id.is_not_distinct_from(product_id),
                                tuple_(Receipt.subject_id, Receipt.subject_revision).in_(
                                    identities
                                ),
                            )
                            for product_id, identities in grouped.items()
                        )
                    ),
                )
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        if missing
        else []
    )
    fresh = _writer_native_context(s, ctx, pid)
    fresh_rows = _writer_native_rows(s, ctx, pid, reads, proof) if fresh is not None else None
    if (
        fresh is None
        or fresh[0] is not proof
        or fresh[1] != owner
        or fresh_rows is None
        or _native_rows_seal(fresh_rows) != seal
    ):
        raise DomainError("INVALID_READ_CONTEXT", "登记读取期间事务、范围或原始行已经变化。")
    actual = {}
    for receipt in receipts:
        actual.setdefault(
            (receipt.product_id, receipt.subject_id, receipt.subject_revision), receipt
        )
    for identity, key in missing.items():
        proof.scalar_rows[key] = (False, actual.get(identity))
    proof.read_rows[("quality-native-writer-scope", pid)] = owner


def source_basis(s, ctx, pid, reads):
    reads = merge_reads(reads)  # Conflicts fail before any snapshot or source SQL.
    rows = _checked_sources(s, ctx, pid, reads)
    proof = _snapshot_proof(s, ctx, pid)
    if proof is not None:
        _batch_artifact_rows(s, ctx, pid, reads, proof)
        # Check every declared source's access/content before reading receipts.
        # Writers and fake sessions keep the original lazy per-source ordering.
        rows = list(rows)
        _batch_native_registrations(s, ctx, pid, rows, proof)
    basis, private, writer_native_read = [], False, False
    for row in rows:
        # Raw cached rows never bypass the per-source immutable-content guard.
        if proof is not None and (
            row.tenant_id != ctx.tenant_id or row.content_hash != digest(row.content)
        ):
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
            safety = snapshot_scalar(
                s,
                (OriginalSecurity, "quality-source", row.id, row.original_id),
                select(OriginalSecurity).where(
                    OriginalSecurity.tenant_id == ctx.tenant_id,
                    OriginalSecurity.product_id.is_not_distinct_from(row.product_id),
                    OriginalSecurity.original_id == row.original_id,
                ),
                scope_id=pid,
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
            if proof is None and not writer_native_read:
                writer_native_read = True
                _batch_writer_native_registrations(s, ctx, pid, reads)
            receipt = snapshot_scalar(
                s,
                (Receipt, "artifact-registration", row.id, row.revision),
                select(Receipt).where(
                    Receipt.tenant_id == ctx.tenant_id,
                    Receipt.product_id.is_not_distinct_from(row.product_id),
                    Receipt.operation == "evidence.artifact.register",
                    Receipt.subject_type == "artifact",
                    Receipt.subject_id == row.id,
                    Receipt.subject_revision == row.revision,
                ),
                scope_id=pid,
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
