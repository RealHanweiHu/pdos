"""Outbound copies of real deterministic summary Runs; no inbound Message is fabricated."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row

from .models import link


class SummaryDelivery(Row, Base):
    __tablename__ = "dingtalk_summary_deliveries"
    category_id: Mapped[UUID] = mapped_column()
    owner_id: Mapped[UUID]
    run_id: Mapped[UUID]
    attempt_id: Mapped[UUID]
    service_grant_id: Mapped[UUID]
    published_version_id: Mapped[UUID]
    application_id: Mapped[UUID]
    application_revision: Mapped[int] = mapped_column(Integer)
    binding_id: Mapped[UUID]
    binding_epoch: Mapped[int] = mapped_column(Integer)
    cancel_epoch: Mapped[int] = mapped_column(Integer)
    summary_sha256: Mapped[str] = mapped_column(String(64))
    source_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)))
    request_key: Mapped[UUID]
    payload: Mapped[dict] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24))
    p26: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    provider_receipt: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    send_attempt_id: Mapped[UUID | None]
    send_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "run_id"),
        UniqueConstraint("tenant_id", "request_key"),
        link("category_id", "categories"),
        link("owner_id", "principals"),
        link("run_id", "agent_runs"),
        link("attempt_id", "automation_service_attempts"),
        link("service_grant_id", "automation_service_grants"),
        link("published_version_id", "automation_rule_versions"),
        link("application_id", "dingtalk_applications"),
        link("binding_id", "dingtalk_account_bindings"),
        CheckConstraint("application_revision>0 AND binding_epoch>0 AND cancel_epoch>=0"),
        CheckConstraint("summary_sha256 ~ '^[a-f0-9]{64}$' AND payload_sha256 ~ '^[a-f0-9]{64}$'"),
        CheckConstraint(
            "state IN ('planned','sending','delivered','unknown','blocked','cancelled')"
        ),
        CheckConstraint(
            "attempts>=0 AND (state NOT IN ('sending','delivered','unknown') OR p26 IS NOT NULL)"
        ),
        CheckConstraint("jsonb_typeof(payload)='object' AND payload->>'target_kind'='direct'"),
    )
