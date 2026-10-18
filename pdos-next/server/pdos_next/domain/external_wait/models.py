"""External waiting facts keep their own stable identity and exact Current."""

from uuid import UUID

from sqlalchemy import CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.domain.work_management.models import (
    BINDING,
    Base,
    _Fact,
    _fact,
    _fk,
    _Scope,
    _scope,
)

WAIT = "external_wait_versions"
CURRENT = "external_wait_currents"
OPERATION = "work.external_wait.record"
SUBJECT = "external_wait"
EVENT = "external_wait.recorded"
ACTIONS = (
    "create",
    "details",
    "initiate",
    "delivery",
    "commitment",
    "reply",
    "close",
    "reopen",
    "transfer_request",
    "transfer_accept",
    "transfer_cancel",
)


class ExternalWaitVersion(_Fact, Base):
    __tablename__ = WAIT
    wait_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16))

    @property
    def status(self):
        return self.state

    __table_args__ = (
        *_fact(),
        UniqueConstraint("tenant_id", "product_id", "wait_id", "revision"),
        UniqueConstraint(*BINDING, "wait_id", "id", "revision"),
        _fk(
            (*BINDING, "wait_id", "previous_id", "previous_revision"),
            WAIT,
            (*BINDING, "wait_id", "id", "revision"),
        ),
        CheckConstraint(
            "(revision=1 AND wait_id=id AND action='create' AND state='open' "
            "AND previous_id IS NULL AND previous_revision IS NULL) OR "
            "(revision>1 AND action<>'create' AND previous_id IS NOT NULL AND previous_id<>id "
            "AND previous_revision=revision-1)",
            name="external_wait_version_chain",
        ),
        CheckConstraint(
            "operation='work.external_wait.record' AND confirmation_id IS NULL",
            name="external_wait_t0_only",
        ),
        CheckConstraint("state IN ('open','closed')", name="external_wait_state"),
        CheckConstraint(
            "action IN (" + ",".join(repr(value) for value in ACTIONS) + ")",
            name="external_wait_action",
        ),
    )


class ExternalWaitCurrent(_Scope, Base):
    __tablename__ = CURRENT
    wait_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "wait_id"),
        _fk(
            (*BINDING, "wait_id", "version_id", "revision"),
            WAIT,
            (*BINDING, "wait_id", "id", "revision"),
        ),
        CheckConstraint(
            "revision>0 AND state IN ('open','closed')", name="external_wait_current_state"
        ),
    )
