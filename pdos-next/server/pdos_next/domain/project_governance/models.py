from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class GovernanceEvent(Row, Base):
    __tablename__ = "project_governance_events"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[UUID | None]
    operation: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    body: Mapped[dict] = mapped_column(JSONB)
    review: Mapped[dict] = mapped_column(JSONB)
    command_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    confirmation_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "project_id", "revision"),
        UniqueConstraint("tenant_id", "command_id"),
        UniqueConstraint("tenant_id", "receipt_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id"],
            ["projects.tenant_id", "projects.product_id", "projects.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "previous_id"],
            ["project_governance_events.tenant_id", "project_governance_events.id"],
        ),
        ForeignKeyConstraint(["tenant_id", "actor_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "confirmation_id"],
            ["confirmations.tenant_id", "confirmations.id"],
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "revision>0 AND status='recorded' AND visibility IN ('private','category','audience')"
        ),
    )
