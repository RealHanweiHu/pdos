"""Staged policy publication/selection atoms, not public registration or qualification."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.change_controlled_schemas import (  # noqa: E402,F401
    BIND,
    POLICY_EVENT,
    POLICY_FAMILY,
    POLICY_OPERATION,
    SELECTION_EVENT,
    SELECTION_FAMILY,
    SELECTION_OPERATION,
    ActionTarget,
    Exact,
    PolicyImport,
    PolicyMaterial,
    SelectionMaterial,
    SelectionPayload,
    UnitBinding,
)
from pdos_next.models import Base, Row


def _scope():
    return (
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id"],
            ["projects.tenant_id", "projects.product_id", "projects.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "visibility IN ('private','category','audience') AND revision > 0 AND epoch > 0"
        ),
    )


def _previous(table, series):
    return ForeignKeyConstraint(
        (*BIND, *series, "previous_id", "previous_revision"),
        (*[f"{table}.{v}" for v in (*BIND, *series)], f"{table}.id", f"{table}.revision"),
        deferrable=True,
        initially="DEFERRED",
    )


class _Fact(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str]
    purpose_sha256: Mapped[str] = mapped_column(String(64))
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    actor_id: Mapped[UUID]
    command_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    intent_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    nature: Mapped[str] = mapped_column(String(16))
    material: Mapped[dict] = mapped_column(JSONB)
    material_sha256: Mapped[str] = mapped_column(String(64))
    source: Mapped[dict] = mapped_column(JSONB)
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def _continuous():
    return CheckConstraint(
        "(revision=1 AND epoch=1 AND previous_id IS NULL AND previous_revision IS NULL) OR "
        "(revision>1 AND previous_id IS NOT NULL AND previous_revision IS NOT NULL "
        "AND previous_id<>id AND revision=previous_revision+1 AND epoch=revision)"
    )


class ChangePolicyFact(_Fact, Base):
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __tablename__ = "controlled_change_policy_facts"
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        *_scope(),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        UniqueConstraint("tenant_id", "product_id", "project_id", "purpose_sha256", "revision"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "id", "revision"),
        UniqueConstraint(*BIND, "id", "revision"),
        _previous(__tablename__, ("purpose_sha256",)),
        UniqueConstraint(*BIND, "purpose_sha256", "id", "revision"),
        _continuous(),
        CheckConstraint(
            "operation='change.policy.import' AND status='published' AND valid_from<valid_until"
        ),
        CheckConstraint("jsonb_array_length(required_source_read_set)>0"),
    )


class ChangeSelectionFact(_Fact, Base):
    __tablename__ = "controlled_change_selection_facts"
    basis_kind: Mapped[str] = mapped_column(
        String(24), default="capa_action", server_default=text("'capa_action'")
    )
    change_id: Mapped[UUID]
    change_version_id: Mapped[UUID]
    change_revision: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[UUID]
    item_sha256: Mapped[str] = mapped_column(String(64))
    intent_id: Mapped[UUID]
    issue_id: Mapped[UUID | None]
    issue_version_id: Mapped[UUID | None]
    issue_revision: Mapped[int | None] = mapped_column(Integer)
    capa_id: Mapped[UUID | None]
    action_id: Mapped[UUID | None]
    action_sha256: Mapped[str | None] = mapped_column(String(64))
    feedback_id: Mapped[UUID | None]
    feedback_version_id: Mapped[UUID | None]
    feedback_revision: Mapped[int | None] = mapped_column(Integer)
    feedback_sha256: Mapped[str | None] = mapped_column(String(64))
    executor_id: Mapped[UUID | None]
    policy_id: Mapped[UUID]
    policy_revision: Mapped[int] = mapped_column(Integer)
    policy_snapshot: Mapped[dict] = mapped_column(JSONB)
    units_snapshot: Mapped[list] = mapped_column(JSONB)
    object_basis: Mapped[dict] = mapped_column(JSONB)
    shared_proof_id: Mapped[UUID]
    shared_proof_revision: Mapped[int] = mapped_column(Integer)
    proof_consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str] = mapped_column(String(64))
    confirmation_material_sha256: Mapped[str] = mapped_column(String(64))
    read_set_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        *_scope(),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        UniqueConstraint(
            "tenant_id", "product_id", "project_id", "change_id", "item_id", "revision"
        ),
        UniqueConstraint(*BIND, "change_id", "item_id", "id", "revision"),
        _previous(__tablename__, ("change_id", "item_id")),
        _continuous(),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "change_id",
                "change_version_id",
                "change_revision",
            ],
            [
                "change_request_versions.tenant_id",
                "change_request_versions.product_id",
                "change_request_versions.project_id",
                "change_request_versions.change_id",
                "change_request_versions.id",
                "change_request_versions.revision",
            ],
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "product_id",
                "project_id",
                "issue_id",
                "issue_version_id",
                "issue_revision",
            ],
            [
                "quality_issue_versions.tenant_id",
                "quality_issue_versions.product_id",
                "quality_issue_versions.project_id",
                "quality_issue_versions.issue_id",
                "quality_issue_versions.id",
                "quality_issue_versions.revision",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "executor_id"],
            ["principals.tenant_id", "principals.id"],
            name="controlled_selection_executor_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "feedback_id", "feedback_version_id", "feedback_revision"],
            [
                "field_feedback_versions.tenant_id",
                "field_feedback_versions.category_id",
                "field_feedback_versions.feedback_id",
                "field_feedback_versions.id",
                "field_feedback_versions.revision",
            ],
            name="controlled_selection_field_feedback_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "policy_id", "policy_revision"],
            [
                "controlled_change_policy_facts.tenant_id",
                "controlled_change_policy_facts.product_id",
                "controlled_change_policy_facts.project_id",
                "controlled_change_policy_facts.id",
                "controlled_change_policy_facts.revision",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "shared_proof_id"],
            ["confirmations.tenant_id", "confirmations.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "operation='change.selection.decide' AND status IN "
            "('applicable','not_applicable','unknown') AND change_revision>0",
            name="controlled_selection_operation",
        ),
        CheckConstraint(
            "basis_kind IN ('capa_action','field_intent')",
            name="controlled_selection_basis_kind",
        ),
        CheckConstraint(
            "(basis_kind='capa_action' AND issue_id IS NOT NULL AND issue_version_id IS NOT NULL "
            "AND issue_revision IS NOT NULL AND issue_revision>0 AND capa_id IS NOT NULL "
            "AND action_id IS NOT NULL AND action_sha256 IS NOT NULL "
            "AND action_sha256 ~ '^[a-f0-9]{64}$' AND feedback_id IS NULL "
            "AND feedback_version_id IS NULL AND feedback_revision IS NULL "
            "AND feedback_sha256 IS NULL AND executor_id IS NULL) OR "
            "(basis_kind='field_intent' AND category_id IS NOT NULL AND feedback_id IS NOT NULL "
            "AND feedback_version_id IS NOT NULL AND feedback_revision IS NOT NULL "
            "AND feedback_revision>0 AND feedback_sha256 IS NOT NULL "
            "AND feedback_sha256 ~ '^[a-f0-9]{64}$' AND executor_id IS NOT NULL "
            "AND issue_id IS NULL AND issue_version_id IS NULL AND issue_revision IS NULL "
            "AND capa_id IS NULL AND action_id IS NULL AND action_sha256 IS NULL)",
            name="controlled_selection_origin_binding",
        ),
        CheckConstraint(
            "proof_consumed_at<=created_at AND "
            "(proof_expires_at IS NULL OR created_at<proof_expires_at) "
            "AND (valid_until IS NULL OR valid_until>created_at)"
        ),
        CheckConstraint("jsonb_array_length(required_source_read_set)>0"),
    )


class _Current(Row):
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    fact_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer)
    purpose_sha256: Mapped[str] = mapped_column(String(64))


class ChangePolicyCurrent(_Current, Base):
    __tablename__ = "controlled_change_policy_currents"
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "project_id", "purpose_sha256"),
        ForeignKeyConstraint(
            [*BIND, "purpose_sha256", "fact_id", "revision"],
            [
                *[f"controlled_change_policy_facts.{v}" for v in (*BIND, "purpose_sha256")],
                "controlled_change_policy_facts.id",
                "controlled_change_policy_facts.revision",
            ],
        ),
    )


class ChangeSelectionCurrent(_Current, Base):
    __tablename__ = "controlled_change_selection_currents"
    change_id: Mapped[UUID]
    item_id: Mapped[UUID]
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "project_id", "change_id", "item_id"),
        ForeignKeyConstraint(
            [*BIND, "change_id", "item_id", "fact_id", "revision"],
            [
                *[
                    f"controlled_change_selection_facts.{v}"
                    for v in (*BIND, "change_id", "item_id")
                ],
                "controlled_change_selection_facts.id",
                "controlled_change_selection_facts.revision",
            ],
        ),
    )
