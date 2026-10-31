"""Private append-only page feedback. No query, title, text or business receipt."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class SimilarHistoryFeedback(Row, Base):
    __tablename__ = "similar_history_feedback"
    category_id: Mapped[UUID] = mapped_column(index=True)
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    issue_id: Mapped[UUID | None]
    issue_version_id: Mapped[UUID | None]
    issue_revision: Mapped[int | None] = mapped_column(Integer)
    change_id: Mapped[UUID | None]
    change_version_id: Mapped[UUID | None]
    change_revision: Mapped[int | None] = mapped_column(Integer)
    candidate_kind: Mapped[str] = mapped_column(String(16))
    candidate_source_id: Mapped[UUID]
    candidate_revision: Mapped[int] = mapped_column(Integer)
    ranking_version: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(24))
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_id", "request_key"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "issue_version_id"],
            ["quality_issue_versions.tenant_id", "quality_issue_versions.product_id",
             "quality_issue_versions.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "change_id", "change_version_id", "change_revision"],
            ["change_request_versions.tenant_id", "change_request_versions.product_id",
             "change_request_versions.change_id", "change_request_versions.id",
             "change_request_versions.revision"],
            name="similar_history_feedback_change_version_fk",
        ),
        CheckConstraint(
            "(issue_id IS NOT NULL AND issue_version_id IS NOT NULL "
            "AND issue_revision IS NOT NULL AND issue_revision>0 "
            "AND change_id IS NULL AND change_version_id IS NULL AND change_revision IS NULL) "
            "OR (change_id IS NOT NULL AND change_version_id IS NOT NULL "
            "AND change_revision IS NOT NULL AND change_revision>0 "
            "AND issue_id IS NULL AND issue_version_id IS NULL AND issue_revision IS NULL "
            "AND action<>'merge_prepared')",
            name="similar_history_feedback_origin_exact",
        ),
        CheckConstraint("issue_revision>0 AND candidate_revision>0"),
        CheckConstraint("candidate_kind IN ('issue','capa','change')"),
        CheckConstraint("action IN ('opened','not_relevant','merge_prepared')"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'"),
    )
