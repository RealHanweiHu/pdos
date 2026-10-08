"""Database-owned dependency enumeration watermark, separate from command effects."""

from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class ChangeDependencyClock(Row, Base):
    __tablename__ = "change_dependency_clocks"
    product_id: Mapped[UUID]
    epoch: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        CheckConstraint("epoch > 0", name="change_dependency_epoch_positive"),
    )
