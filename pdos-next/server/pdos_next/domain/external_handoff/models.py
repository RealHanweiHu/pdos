"""Uninstalled handoff facts and their Current projection.

Authorization and its single fixed delivery intent share one T2 common group.
An intent is not a send. Actual sent/accepted/effective outcomes are separate
immutable receipt originals, ordered by a CAS-protected local sequence.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row

from .constants import AUTHORIZE, RECEIPT_RECORD

AUTHORIZATION = "external_handoff_authorizations"
INTENT = "external_delivery_intents"
RECEIPT = "external_receipts"
CURRENT = "external_handoff_currents"
SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
BINDING = (*SCOPE, "owner_id", "visibility")
HANDOFF = (*BINDING, "handoff_id", "handoff_revision")
INTENT_BINDING = (*HANDOFF, "intent_id", "intent_revision")
PROJECTION_FIELDS = (
    "status",
    "sent",
    "accepted",
    "effective",
    "delivery_unknown",
    "rejected",
    "failed",
    "conflict",
    "network_send",
)


def projection_snapshot(reading):
    """Normalize a fold result, excluding history owned by immutable receipts.

    This is a shape conversion, never an attestation that its stages occurred.
    The actual owner must supply ``rules.fold`` over actual sequence-ordered
    receipts. It must not accept this helper's input from a public command.
    """
    from .schemas import HandoffReading

    if isinstance(reading, HandoffReading):
        value = reading
    else:
        value = HandoffReading.model_validate({"history": (), **dict(reading)})
    return value.model_dump(mode="json", exclude={"history"})


def initial_projection():
    """The initial authorized projection records no external outcome."""
    return projection_snapshot(
        {
            "status": "authorized",
            **{
                stage: {
                    "stage": stage,
                    "state": "not_recorded",
                    "active": (),
                    "covered_scopes": (),
                    "mismatches": (),
                }
                for stage in ("sent", "accepted", "effective")
            },
            "delivery_unknown": False,
            "rejected": False,
            "failed": False,
            "conflict": False,
            "network_send": False,
        }
    )


def delivery_intent_snapshot(handoff, authorization):
    """Fix the exact authorized packet; this shape does not dispatch it."""
    from .schemas import AuthorizationPlan, VersionRef

    ref = VersionRef.model_validate(handoff)
    plan = AuthorizationPlan.model_validate(authorization)
    declaration = plan.declaration.model_dump(mode="json", exclude={"approval_token"})
    return {
        "handoff": ref.model_dump(mode="json"),
        **{
            key: declaration[key]
            for key in (
                "package",
                "engineering_decision",
                "manufacturing_decision",
                "subject_config",
                "release_scope",
                "purpose",
                "destination",
                "external_id",
                "manifest",
                "mappings",
            )
        },
        "manifest_sha256": plan.manifest_sha256,
        "mappings_sha256": plan.mappings_sha256,
        "content_sha256": plan.content_sha256,
        "network_send": False,
    }


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{key}" for key in remote], **options)


def _scope():
    return (
        _fk(
            ("tenant_id", "category_id", "product_id"),
            "products",
            ("tenant_id", "category_id", "id"),
        ),
        _fk(
            ("tenant_id", "product_id", "project_id"),
            "projects",
            ("tenant_id", "product_id", "id"),
        ),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
        CheckConstraint("visibility IN ('private','category','audience')"),
    )


def _common():
    return (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "product_id", "id", "revision"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "product_id", "actor_id", "operation", "intent_digest"),
        *(
            _fk(("tenant_id", field), "principals", ("tenant_id", "id"))
            for field in ("writer_id", "actor_id", "requester_id")
        ),
        _fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("revision=1 AND writer_id=actor_id"),
        CheckConstraint(
            "jsonb_typeof(body)='object' AND jsonb_typeof(material_snapshot)='object' "
            "AND jsonb_typeof(input_snapshot)='object' AND jsonb_typeof(source_basis)='object' "
            "AND jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0 "
            "AND jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0"
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND intent_digest ~ '^[a-f0-9]{64}$' "
            "AND request_digest ~ '^[a-f0-9]{64}$'"
        ),
        CheckConstraint("network_send=false"),
    )


def _projection(column):
    keys = ",".join(f"'{value}'" for value in PROJECTION_FIELDS)
    expression = (
        f"jsonb_typeof({column})='object' AND {column} ?& ARRAY[{keys}] "
        f"AND NOT({column} ? 'history') "
        f"AND {column}->>'status' IN ('authorized','sent','acknowledged','reconciled') "
        f"AND {column}->'network_send'='false'::jsonb AND "
        + " AND ".join(
            f"jsonb_typeof({column}->'{name}')='boolean'"
            for name in ("delivery_unknown", "rejected", "failed", "conflict")
        )
        + " AND "
        + " AND ".join(
            f"{column}->'{stage}'->>'stage'='{stage}' "
            f"AND {column}->'{stage}'->>'state' IN "
            "('not_recorded','succeeded','partial','unknown','rejected','failed','conflict') "
            f"AND jsonb_typeof({column}->'{stage}'->'active')='array' "
            f"AND jsonb_typeof({column}->'{stage}'->'covered_scopes')='array' "
            f"AND jsonb_typeof({column}->'{stage}'->'mismatches')='array'"
            for stage in ("sent", "accepted", "effective")
        )
    )
    return CheckConstraint(f"COALESCE(({expression}),false)")


class _Recorded(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[UUID]
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    material_snapshot: Mapped[dict] = mapped_column(JSONB)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    network_send: Mapped[bool] = mapped_column(Boolean, default=False)


class ExternalHandoffAuthorization(_Recorded, Base):
    __tablename__ = AUTHORIZATION
    operation: Mapped[str] = mapped_column(String(80), default=AUTHORIZE)
    write_tier: Mapped[str] = mapped_column(String(4), default="T2")
    status: Mapped[str] = mapped_column(String(16), default="authorized")
    purpose: Mapped[str] = mapped_column(Text)
    package_id: Mapped[UUID]
    package_revision: Mapped[int] = mapped_column(Integer)
    engineering_decision_id: Mapped[UUID]
    engineering_decision_revision: Mapped[int] = mapped_column(Integer)
    manufacturing_decision_id: Mapped[UUID]
    manufacturing_decision_revision: Mapped[int] = mapped_column(Integer)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    mappings_sha256: Mapped[str] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64))
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    shared_proof_id: Mapped[UUID]
    shared_proof_revision: Mapped[int] = mapped_column(Integer)
    proof_consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str] = mapped_column(String(64))
    material_sha256: Mapped[str] = mapped_column(String(64))
    read_set_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        *_common(),
        UniqueConstraint(*BINDING, "id", "revision"),
        UniqueConstraint("tenant_id", "shared_proof_id"),
        *(
            _fk(
                ("tenant_id", "product_id", f"{prefix}_id", f"{prefix}_revision"),
                target,
                ("tenant_id", "product_id", "id", "revision"),
            )
            for prefix, target in (
                ("package", "release_packages"),
                ("engineering_decision", "release_decisions"),
                ("manufacturing_decision", "release_decisions"),
            )
        ),
        _fk(
            ("tenant_id", "shared_proof_id"),
            "confirmations",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(f"operation='{AUTHORIZE}' AND write_tier='T2' AND status='authorized'"),
        CheckConstraint(
            "actor_id=requester_id AND engineering_decision_id<>manufacturing_decision_id"
        ),
        CheckConstraint(
            "package_revision>0 AND engineering_decision_revision>0 "
            "AND manufacturing_decision_revision>0 AND shared_proof_revision>0"
        ),
        CheckConstraint(
            "proof_consumed_at<=created_at AND "
            "(proof_expires_at IS NULL OR created_at<proof_expires_at)"
        ),
        CheckConstraint(
            "manifest_sha256 ~ '^[a-f0-9]{64}$' AND mappings_sha256 ~ '^[a-f0-9]{64}$' "
            "AND content_sha256 ~ '^[a-f0-9]{64}$' AND token_sha256 ~ '^[a-f0-9]{64}$' "
            "AND material_sha256 ~ '^[a-f0-9]{64}$' AND read_set_sha256 ~ '^[a-f0-9]{64}$'"
        ),
    )


class ExternalDeliveryIntent(Row, Base):
    __tablename__ = INTENT
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    handoff_id: Mapped[UUID]
    handoff_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="authorized")
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    authorization_sha256: Mapped[str] = mapped_column(String(64))
    destination: Mapped[dict] = mapped_column(JSONB)
    external_id: Mapped[str] = mapped_column(Text)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    mappings_sha256: Mapped[str] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64))
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    network_send: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(*SCOPE, "handoff_id", "handoff_revision"),
        UniqueConstraint(*HANDOFF, "id", "revision"),
        _fk(
            (*BINDING, "handoff_id", "handoff_revision"),
            AUTHORIZATION,
            (*BINDING, "id", "revision"),
        ),
        _fk(
            ("tenant_id", "receipt_id"),
            "action_receipts",
            ("tenant_id", "id"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "revision=1 AND handoff_revision=1 AND status='authorized' AND network_send=false"
        ),
        CheckConstraint(
            "jsonb_typeof(body)='object' AND jsonb_typeof(destination)='object' "
            "AND length(external_id)>0"
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND authorization_sha256 ~ '^[a-f0-9]{64}$' "
            "AND manifest_sha256 ~ '^[a-f0-9]{64}$' AND mappings_sha256 ~ '^[a-f0-9]{64}$' "
            "AND content_sha256 ~ '^[a-f0-9]{64}$'"
        ),
    )


class ExternalReceipt(_Recorded, Base):
    __tablename__ = RECEIPT
    handoff_id: Mapped[UUID]
    handoff_revision: Mapped[int] = mapped_column(Integer)
    intent_id: Mapped[UUID]
    intent_revision: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    previous_receipt_id: Mapped[UUID | None]
    previous_receipt_revision: Mapped[int | None] = mapped_column(Integer)
    previous_sequence: Mapped[int | None] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(80), default=RECEIPT_RECORD)
    write_tier: Mapped[str] = mapped_column(String(4), default="T0")
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    original: Mapped[dict] = mapped_column(JSONB)
    source: Mapped[dict] = mapped_column(JSONB)
    issuer_snapshot: Mapped[dict] = mapped_column(JSONB)
    stage: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(16))
    destination: Mapped[dict] = mapped_column(JSONB)
    external_id: Mapped[str] = mapped_column(Text)
    external_receipt_id: Mapped[str] = mapped_column(Text)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    release_scope: Mapped[dict] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reconciles_id: Mapped[UUID | None]
    reconciles_revision: Mapped[int | None] = mapped_column(Integer)
    projection_after: Mapped[dict] = mapped_column(JSONB)
    projection_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        *_common(),
        UniqueConstraint(*SCOPE, "handoff_id", "intent_id", "sequence"),
        UniqueConstraint(*INTENT_BINDING, "id", "revision"),
        UniqueConstraint(*INTENT_BINDING, "id", "revision", "sequence"),
        UniqueConstraint("tenant_id", "reconciles_id", "reconciles_revision"),
        _fk((*HANDOFF, "intent_id", "intent_revision"), INTENT, (*HANDOFF, "id", "revision")),
        _fk(
            (
                *INTENT_BINDING,
                "previous_receipt_id",
                "previous_receipt_revision",
                "previous_sequence",
            ),
            RECEIPT,
            (*INTENT_BINDING, "id", "revision", "sequence"),
            deferrable=True,
            initially="DEFERRED",
        ),
        _fk(
            (*INTENT_BINDING, "reconciles_id", "reconciles_revision"),
            RECEIPT,
            (*INTENT_BINDING, "id", "revision"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(f"operation='{RECEIPT_RECORD}' AND write_tier='T0' AND status='recorded'"),
        CheckConstraint("handoff_revision=1 AND intent_revision=1 AND sequence>0"),
        CheckConstraint(
            "(sequence=1 AND previous_receipt_id IS NULL AND previous_receipt_revision IS NULL "
            "AND previous_sequence IS NULL) "
            "OR (sequence>1 AND previous_receipt_id IS NOT NULL AND previous_receipt_id<>id "
            "AND previous_receipt_revision=1 AND previous_sequence>0 "
            "AND sequence=previous_sequence+1)"
        ),
        CheckConstraint(
            "(reconciles_id IS NULL AND reconciles_revision IS NULL) OR "
            "(reconciles_id IS NOT NULL AND reconciles_id<>id AND reconciles_revision=1 "
            "AND outcome<>'unknown')"
        ),
        CheckConstraint(
            "stage IN ('sent','accepted','effective') "
            "AND outcome IN ('succeeded','unknown','rejected','failed')"
        ),
        CheckConstraint("occurred_at<=received_at AND received_at<=created_at"),
        CheckConstraint(
            "jsonb_typeof(original)='object' AND jsonb_typeof(source)='object' "
            "AND jsonb_typeof(issuer_snapshot)='object' AND jsonb_typeof(destination)='object' "
            "AND jsonb_typeof(release_scope)='object' AND length(external_id)>0 "
            "AND length(external_receipt_id)>0"
        ),
        CheckConstraint(
            "manifest_sha256 ~ '^[a-f0-9]{64}$' AND projection_sha256 ~ '^[a-f0-9]{64}$'"
        ),
        _projection("projection_after"),
    )


class ExternalHandoffCurrent(Row, Base):
    __tablename__ = CURRENT
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    handoff_id: Mapped[UUID]
    handoff_revision: Mapped[int] = mapped_column(Integer)
    intent_id: Mapped[UUID]
    intent_revision: Mapped[int] = mapped_column(Integer)
    receipt_count: Mapped[int] = mapped_column(Integer, default=0)
    latest_receipt_id: Mapped[UUID | None]
    latest_receipt_revision: Mapped[int | None] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    projection: Mapped[dict] = mapped_column(JSONB)
    projection_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        *_scope(),
        UniqueConstraint(*SCOPE, "handoff_id", "handoff_revision"),
        _fk((*HANDOFF, "intent_id", "intent_revision"), INTENT, (*HANDOFF, "id", "revision")),
        _fk(
            (*INTENT_BINDING, "latest_receipt_id", "latest_receipt_revision", "receipt_count"),
            RECEIPT,
            (*INTENT_BINDING, "id", "revision", "sequence"),
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "handoff_revision=1 AND intent_revision=1 AND receipt_count>=0 "
            "AND epoch=receipt_count+1"
        ),
        CheckConstraint(
            "(receipt_count=0 AND latest_receipt_id IS NULL "
            "AND latest_receipt_revision IS NULL) OR "
            "(receipt_count>0 AND latest_receipt_id IS NOT NULL AND latest_receipt_revision=1)"
        ),
        CheckConstraint("projection_sha256 ~ '^[a-f0-9]{64}$'"),
        _projection("projection"),
    )
