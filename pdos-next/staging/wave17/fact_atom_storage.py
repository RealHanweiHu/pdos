"""Read the exact persisted common group; no current-evidence attestation.

This module is not mounted. SQL constraints and real consumption hooks for the
new fact targets do not exist in the public candidate yet. A returned FactAtom
describes stored associations, and cannot replace the seven owner gates.
"""

# Initialize the common registry before staged domain imports.
# ruff: noqa: I001

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pdos_next.service import Context, digest

import fact_storage_models  # noqa: F401 -- staged registration, never public import
from fact_storage_codec import body_payload_sha256, decode_fact_body
from facts import AuditBinding, FactAtom, FixedRef, OutboxBinding, canonical_reads, json_value
from pdos_next.errors import DomainError
from pdos_next.models import (
    Audit,
    Base,
    Confirmation,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
)
from pdos_next.schemas.verification.contracts import Scope
from sqlalchemy import select
from sqlalchemy.orm import Session, SessionTransaction

Kind = Literal["rule", "observation", "review"]
SPECS = {
    "rule": (
        "capa_verification_rule_facts",
        "quality.capa.verification.rule.import",
        "host_import",
        "capa_verification_rule",
        "CapaVerificationRulePublished",
        "published",
    ),
    "observation": (
        "capa_observation_facts",
        "quality.capa.observation.record",
        "T1",
        "capa_observation",
        "CapaObservationRecorded",
        "recorded",
    ),
    "review": (
        "capa_named_verification_reviews",
        "quality.capa.verification.review",
        "T2",
        "capa_named_verification_review",
        "CapaVerificationReviewed",
        "reviewed",
    ),
}


@dataclass(frozen=True)
class StoredAtomRead:
    atom: FactAtom
    group_sha256: str
    current_evidence_authorized: Literal[False] = False
    same_uow_consumption_attested: Literal[False] = False


def _require(condition, code):
    if not condition:
        raise DomainError(code, "事实的实际原子出处或读取范围尚不能完整核对。", 503)


def _uow(s):
    _require(isinstance(s, Session) and s.is_active is True, "FACT_ACTIVE_SESSION_REQUIRED")
    chain, seen = [], set()
    # SQLAlchemy's public root getter walks parent links itself. Check a bounded
    # real ancestry first, so a corrupt cycle cannot hang that getter.
    node = s._transaction
    while node is not None:
        _require(
            isinstance(node, SessionTransaction)
            and id(node) not in seen
            and len(chain) < 128
            and node.session is s
            and node.is_active is True,
            "FACT_ACTIVE_TRANSACTION_CHAIN_REQUIRED",
        )
        seen.add(id(node))
        chain.append(node)
        node = node.parent
    _require(bool(chain), "FACT_ACTIVE_TRANSACTION_REQUIRED")
    root = s.get_transaction()
    nested = s.get_nested_transaction()
    expected_nested = next((v for v in chain if v.nested), None)
    _require(
        chain[-1] is root and root.parent is None and nested is expected_nested,
        "FACT_TRANSACTION_ROOT_MISMATCH",
    )
    return tuple(chain), s.get_bind()


def _same_uow(s, captured, ctx, caller):
    current = _uow(s)
    _require(
        len(captured[0]) == len(current[0])
        and all(a is b for a, b in zip(captured[0], current[0], strict=True))
        and captured[1] is current[1]
        and digest(vars(ctx)) == caller,
        "FACT_CALLER_UOW_CHANGED",
    )


def _one(s, model, *where):
    rows = list(
        s.scalars(
            select(model)
            .where(*where)
            .limit(2)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    _require(len(rows) == 1, "FACT_EXACT_GROUP_ROW_MISSING")
    return rows[0]


def _acl(s, ctx, product_id):
    _require(
        isinstance(ctx, Context) and ctx.actor_id == ctx.requester_id and ctx.run_id is None,
        "FACT_ACTUAL_NAMED_CALLER_REQUIRED",
    )
    _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == product_id)
    person = _one(s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.actor_id)
    grant = _one(
        s,
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.product_id == product_id,
        Grant.principal_id == ctx.actor_id,
    )
    # The final Grant query can outlive a clock sampled before this IO.
    if person.kind != "human" or person.active is not True or grant.expires_at <= datetime.now(UTC):
        raise DomainError("FORBIDDEN_SCOPE", "当前本人不能读取这份事实。", 403)


def _proof(s, row, operation, tier):
    fields = (
        "shared_proof_id",
        "shared_proof_revision",
        "proof_consumed_at",
        "proof_expires_at",
        "token_sha256",
        "material_sha256",
    )
    if tier == "host_import":
        _require(all(row[key] is None for key in fields), "FACT_IMPORT_HAS_PUBLIC_PROOF")
        return None
    _require(all(row[key] is not None for key in fields), "FACT_SAVED_PROOF_INCOMPLETE")
    proof = _one(
        s,
        Confirmation,
        Confirmation.tenant_id == row["tenant_id"],
        Confirmation.product_id == row["product_id"],
        Confirmation.id == row["shared_proof_id"],
    )
    _require(
        proof.consumed is True
        and proof.actor_id == row["actor_id"]
        and proof.subject_id == row["product_id"]
        and proof.operation == operation
        and proof.revision == row["shared_proof_revision"]
        and proof.token_hash == row["token_sha256"]
        and proof.payload_digest == row["material_sha256"]
        and proof.expires_at == row["proof_expires_at"]
        and proof.created_at <= row["proof_consumed_at"] <= row["created_at"] < proof.expires_at,
        "FACT_SAVED_PROOF_BINDING_MISMATCH",
    )
    return {
        "id": proof.id,
        "revision": proof.revision,
        "operation": proof.operation,
        "actor_id": proof.actor_id,
        "subject_id": proof.subject_id,
        "created_at": proof.created_at,
        "consumed_at": row["proof_consumed_at"],
        "expires_at": proof.expires_at,
        "token_sha256": proof.token_hash,
        "material_sha256": proof.payload_digest,
        "snapshot_sha256": digest(proof.snapshot),
    }


def read_fact_atom(s, ctx, product_id, *, kind: Kind, fact_id: UUID, revision: int):
    """Read exact immutable fact/group under the real caller, with bounded SQL.

    Does not read Rule/Observation Current, source bytes or professional owners.
    Does not infer a historic false-to-true transition from consumed=True.
    All current-evidence and same-UOW attestations remain explicitly false.
    """
    _require(kind in SPECS, "FACT_KIND_NOT_SUPPORTED")
    _require(type(revision) is int and revision > 0, "FACT_REVISION_REQUIRED")
    _require(isinstance(ctx, Context), "FACT_ACTUAL_NAMED_CALLER_REQUIRED")
    captured, caller = _uow(s), digest(vars(ctx))
    _acl(s, ctx, product_id)
    table_name, operation, tier, subject, event_name, status = SPECS[kind]
    table = Base.metadata.tables[table_name]
    rows = list(
        s.execute(
            select(table)
            .where(
                table.c.tenant_id == ctx.tenant_id,
                table.c.product_id == product_id,
                table.c.id == fact_id,
                table.c.revision == revision,
            )
            .limit(2)
            .execution_options(autoflush=False)
        ).mappings()
    )
    _require(len(rows) == 1, "FACT_EXACT_VERSION_MISSING")
    row = rows[0]
    if row["visibility"] == "private" and row["owner_id"] != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "私有事实仅允许原合法受众读取。", 403)
    _require(
        row["operation"] == operation
        and row["tier"] == tier
        and row["actor_id"] == row["requester_id"] == row["writer_id"]
        and row["status"] == status,
        "FACT_SAVED_WRITER_OR_OPERATION_MISMATCH",
    )
    body = decode_fact_body(row["fact_body"]).body
    _require(
        body.kind == kind
        and body.ref == FixedRef(id=fact_id, revision=revision)
        and body.scope
        == Scope(tenant_id=ctx.tenant_id, product_id=product_id, project_id=row["project_id"])
        and body.issue_id == row["issue_id"]
        and body.capa_id == row["capa_id"]
        and body.owner_id == row["owner_id"]
        and body.visibility == row["visibility"]
        and body.purpose == row["purpose"]
        and body.nature == row["nature"]
        and body.created_at == row["created_at"]
        and body_payload_sha256(row["fact_body"]) == row["payload_sha256"]
        and digest([json_value(v) for v in canonical_reads(body.required_source_read_set)])
        == row["read_set_sha256"],
        "FACT_STORED_BODY_BINDING_MISMATCH",
    )
    writer = _one(
        s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == row["writer_id"]
    )
    _require(writer.kind == "human", "FACT_SAVED_NAMED_WRITER_REQUIRED")
    receipt = _one(
        s,
        Receipt,
        Receipt.tenant_id == ctx.tenant_id,
        Receipt.product_id == product_id,
        Receipt.operation == operation,
        Receipt.subject_type == subject,
        Receipt.subject_id == fact_id,
        Receipt.subject_revision == revision,
    )
    _require(
        receipt.actor_id == receipt.requester_id == row["actor_id"]
        and receipt.command_id == row["command_id"]
        and receipt.run_id is None
        and receipt.visibility == row["visibility"]
        and receipt.intent_digest == row["intent_digest"]
        and receipt.result.get("id") == str(fact_id)
        and type(receipt.result.get("revision")) is int
        and receipt.result.get("revision") == revision
        and receipt.result.get("status") == status
        and receipt.result.get("fact_kind") == kind
        and receipt.result.get("payload_sha256") == row["payload_sha256"],
        "FACT_RECEIPT_BINDING_MISMATCH",
    )
    _require(
        isinstance(receipt.request_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", receipt.request_digest) is not None
        and row["created_at"] <= receipt.created_at <= datetime.now(UTC),
        "FACT_ORIGINAL_RECEIPT_CLOCK_OR_DIGEST_INVALID",
    )
    key = list(
        s.scalars(
            select(RequestKey)
            .where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.actor_id == receipt.actor_id,
                RequestKey.receipt_id == receipt.id,
                RequestKey.digest == receipt.request_digest,
            )
            .limit(1)
            .execution_options(autoflush=False)
        )
    )
    _require(bool(key), "FACT_ORIGINAL_REQUEST_KEY_MISSING")
    audit = _one(s, Audit, Audit.tenant_id == ctx.tenant_id, Audit.receipt_id == receipt.id)
    outbox = _one(s, Outbox, Outbox.tenant_id == ctx.tenant_id, Outbox.receipt_id == receipt.id)
    _require(
        audit.actor_id == receipt.actor_id
        and audit.operation == operation
        and outbox.actor_id == receipt.actor_id
        and outbox.type == event_name
        and outbox.subject_id == fact_id
        and outbox.subject_revision == revision
        and outbox.schema_version == 1
        and outbox.correlation_id == receipt.command_id,
        "FACT_AUDIT_OUTBOX_BINDING_MISMATCH",
    )
    saved_proof = _proof(s, row, operation, tier)
    group = {
        "schema_version": "pdos-capa-fact-transaction-group-v1",
        "scope": {
            "tenant_id": ctx.tenant_id,
            "product_id": product_id,
            "project_id": row["project_id"],
        },
        "fact": {"id": fact_id, "revision": revision},
        "operation": operation,
        "tier": tier,
        "payload_sha256": row["payload_sha256"],
        "read_set_sha256": row["read_set_sha256"],
        "received_at": row["created_at"],
        "receipt": {
            "id": receipt.id,
            "command_id": receipt.command_id,
            "actor_id": receipt.actor_id,
            "requester_id": receipt.requester_id,
            "request_digest": receipt.request_digest,
            "intent_digest": receipt.intent_digest,
            "created_at": receipt.created_at,
            "result": receipt.result,
        },
        "audit": {"id": audit.id, "operation": audit.operation, "actor_id": audit.actor_id},
        "outbox": {"id": outbox.id, "type": outbox.type, "correlation_id": outbox.correlation_id},
        "proof": saved_proof,
    }
    group_sha = digest(group)
    ref = FixedRef(id=fact_id, revision=revision)
    atom = FactAtom(
        scope=Scope(tenant_id=ctx.tenant_id, product_id=product_id, project_id=row["project_id"]),
        operation=operation,
        tier=tier,
        fact=ref,
        actor_id=receipt.actor_id,
        requester_id=receipt.requester_id,
        actor_kind="human",
        command_id=receipt.command_id,
        receipt_id=receipt.id,
        receipt_subject=ref,
        receipt_subject_type=subject,
        receipt_operation=operation,
        receipt_actor_id=receipt.actor_id,
        payload_sha256=row["payload_sha256"],
        read_set_sha256=row["read_set_sha256"],
        proof_id=row["shared_proof_id"],
        invocation_decision_id=row["shared_proof_id"] if tier == "T2" else None,
        token_sha256=row["token_sha256"],
        material_sha256=row["material_sha256"],
        consumed_at=row["proof_consumed_at"],
        transaction_proof_id=row["shared_proof_id"] if saved_proof else receipt.id,
        transaction_proof_sha256=group_sha,
        audit=AuditBinding(
            id=audit.id, receipt_id=receipt.id, actor_id=audit.actor_id, operation=operation
        ),
        outbox=OutboxBinding(
            id=outbox.id,
            receipt_id=receipt.id,
            correlation_id=outbox.correlation_id,
            effect=event_name,
        ),
        received_at=row["created_at"],
    )
    _acl(s, ctx, product_id)
    _same_uow(s, captured, ctx, caller)
    return StoredAtomRead(atom=atom, group_sha256=group_sha)
