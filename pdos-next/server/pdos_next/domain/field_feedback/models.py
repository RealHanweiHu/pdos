"""Immutable Field source/location versions and independent performed responses."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row

FEEDBACK = "field_feedback_versions"
CURRENT = "field_feedback_currents"
RESPONSE = "field_response_records"
CREATE = "field.feedback.create"
LOCATE = "field.feedback.locate"
ACTION = "field.feedback.action.record"
LINK = "field.feedback.followup.link"
OPERATIONS = (CREATE, LOCATE, ACTION, LINK)
SUBJECTS = ("field_feedback", "field_response")
EVENTS = {
    CREATE: "field.feedback_created",
    LOCATE: "field.feedback_located",
    ACTION: "field.feedback_action_recorded",
    LINK: "field.feedback_followup_linked",
}


def _fk(local, table, remote, **options):
    return ForeignKeyConstraint(list(local), [f"{table}.{key}" for key in remote], **options)


def _scope():
    return (
        _fk(("tenant_id", "category_id"), "categories", ("tenant_id", "id")),
        _fk(
            ("tenant_id", "category_id", "product_id"),
            "products",
            ("tenant_id", "category_id", "id"),
        ),
        _fk(
            ("tenant_id", "product_id", "project_id"), "projects", ("tenant_id", "product_id", "id")
        ),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
        CheckConstraint("visibility IN ('private','category')"),
        CheckConstraint("project_id IS NULL OR product_id IS NOT NULL"),
    )


def _fact():
    return (
        *_scope(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "category_id", "id", "revision"),
        UniqueConstraint("tenant_id", "receipt_id"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "category_id", "actor_id", "operation", "intent_digest"),
        *(
            _fk(("tenant_id", name), "principals", ("tenant_id", "id"))
            for name in ("writer_id", "actor_id", "requester_id")
        ),
        *(
            _fk(
                ("tenant_id", name),
                table,
                ("tenant_id", "id"),
                deferrable=True,
                initially="DEFERRED",
            )
            for name, table in (
                ("receipt_id", "action_receipts"),
                ("confirmation_id", "confirmations"),
            )
        ),
        CheckConstraint("writer_id=actor_id AND revision>0"),
        CheckConstraint(
            "jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' "
            "AND jsonb_typeof(source_basis)='object' AND jsonb_typeof(sources)='array' "
            "AND jsonb_typeof(reads)='array' AND jsonb_array_length(sources)>0 "
            "AND jsonb_array_length(reads)>0"
        ),
        CheckConstraint(
            "body_sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$' "
            "AND intent_digest ~ '^[a-f0-9]{64}$'"
        ),
    )


class _Scope(Row):
    category_id: Mapped[UUID] = mapped_column(index=True)
    product_id: Mapped[UUID | None]
    project_id: Mapped[UUID | None]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))


class _Fact(_Scope):
    revision: Mapped[int] = mapped_column(Integer)
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    command_id: Mapped[UUID]
    command: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    reads: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    body: Mapped[dict] = mapped_column(JSONB)
    body_sha256: Mapped[str] = mapped_column(String(64))
    intent_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[UUID]
    confirmation_id: Mapped[UUID | None]


class FieldFeedbackVersion(_Fact, Base):
    __tablename__ = FEEDBACK
    feedback_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)

    @property
    def status(self):
        return "located" if self.body and self.body.get("location") else "unknown"

    __table_args__ = (
        *_fact(),
        UniqueConstraint("tenant_id", "category_id", "feedback_id", "revision"),
        UniqueConstraint("tenant_id", "category_id", "feedback_id", "id", "revision"),
        _fk(
            ("tenant_id", "category_id", "feedback_id", "previous_id", "previous_revision"),
            FEEDBACK,
            ("tenant_id", "category_id", "feedback_id", "id", "revision"),
        ),
        CheckConstraint(
            "(revision=1 AND feedback_id=id AND previous_id IS NULL AND previous_revision IS NULL) "
            "OR (revision>1 AND previous_id IS NOT NULL AND previous_id<>id "
            "AND previous_revision=revision-1)",
            name="field_feedback_chain",
        ),
        CheckConstraint(
            "(operation='field.feedback.create' AND revision=1 AND confirmation_id IS NULL) "
            "OR (operation='field.feedback.locate' AND revision>1 AND confirmation_id IS NOT NULL)",
            name="field_feedback_operation",
        ),
    )


class FieldFeedbackCurrent(_Scope, Base):
    __tablename__ = CURRENT
    feedback_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "category_id", "feedback_id"),
        _fk(
            ("tenant_id", "category_id", "feedback_id", "version_id", "revision"),
            FEEDBACK,
            ("tenant_id", "category_id", "feedback_id", "id", "revision"),
        ),
        CheckConstraint("revision>0", name="field_feedback_current_revision"),
    )


class FieldResponseRecord(_Fact, Base):
    __tablename__ = RESPONSE
    feedback_id: Mapped[UUID]
    feedback_version_id: Mapped[UUID]
    feedback_revision: Mapped[int] = mapped_column(Integer)
    response_kind: Mapped[str] = mapped_column(String(24))

    @property
    def status(self):
        return "recorded"

    __table_args__ = (
        *_fact(),
        _fk(
            ("tenant_id", "category_id", "feedback_id", "feedback_version_id", "feedback_revision"),
            FEEDBACK,
            ("tenant_id", "category_id", "feedback_id", "id", "revision"),
        ),
        CheckConstraint("revision=1 AND feedback_revision>0 AND confirmation_id IS NOT NULL"),
        CheckConstraint(
            "(operation='field.feedback.action.record' "
            "AND response_kind IN ('containment','improvement')) "
            "OR (operation='field.feedback.followup.link' AND response_kind='followup')",
            name="field_response_operation",
        ),
    )
