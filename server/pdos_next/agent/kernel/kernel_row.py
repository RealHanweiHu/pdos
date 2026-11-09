"""Shared identity columns for Agent kernel tables.

Kept apart from ``models`` so that the table modules the registry loads after it
can take this mixin while ``models`` is still loading (D303).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.core.clock import now


class KernelRow:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
