"""Private, append-only conversation memory; never business or authority facts."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base

from .models import KernelRow


class AgentWorkState(KernelRow, Base):
    __tablename__ = "agent_work_states"
    session_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    run_id: Mapped[UUID | None]
    revision: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(16))
    request_key: Mapped[UUID]
    request_sha256: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "session_id", "revision"),
        UniqueConstraint("tenant_id", "session_id", "request_key"),
        UniqueConstraint("tenant_id", "run_id"),
        ForeignKeyConstraint(
            ["tenant_id", "session_id"], ["agent_sessions.tenant_id", "agent_sessions.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["agent_runs.tenant_id", "agent_runs.id"]),
        CheckConstraint("revision > 0", name="work_state_revision"),
        CheckConstraint("origin IN ('run','human')", name="work_state_origin"),
        CheckConstraint("(origin='run') = (run_id IS NOT NULL)", name="work_state_run_origin"),
        CheckConstraint("jsonb_typeof(body)='object'", name="work_state_body"),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="work_state_request_sha256"),
    )
