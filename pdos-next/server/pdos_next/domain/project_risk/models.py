"""Internal follow-up versions belong to one existing native G0 risk."""

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

FOLLOWUP = "project_risk_followups"
CURRENT = "project_risk_followup_currents"
OPERATION = "work.risk.followup.record"
SUBJECT = "risk_followup"
EVENT = "risk.followup_recorded"
ACTIONS = ("close", "reopen")
EFFECT = "仅登记原G0具名跟进人的内部风险跟进结果；不改变任务、规格、专业批准或放行。"


class ProjectRiskFollowup(_Fact, Base):
    __tablename__ = FOLLOWUP
    risk_id: Mapped[UUID]
    g0_decision_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))

    @property
    def status(self):
        return self.state

    __table_args__ = (
        *_fact(),
        UniqueConstraint("tenant_id", "product_id", "risk_id", "revision"),
        UniqueConstraint(*BINDING, "risk_id", "g0_decision_id", "id", "revision"),
        _fk(
            (*BINDING, "risk_id", "g0_decision_id", "previous_id", "previous_revision"),
            FOLLOWUP,
            (*BINDING, "risk_id", "g0_decision_id", "id", "revision"),
        ),
        _fk(("risk_id",), "project_open_items", ("id",), name="risk_followup_g0_item_fk"),
        _fk(
            ("tenant_id", "category_id", "g0_decision_id"),
            "proposal_decisions",
            ("tenant_id", "category_id", "id"),
            name="risk_followup_g0_decision_fk",
        ),
        CheckConstraint(
            "(revision=1 AND action='close' AND state='closed' AND previous_id IS NULL "
            "AND previous_revision IS NULL) OR (revision>1 AND previous_id IS NOT NULL "
            "AND previous_id<>id AND previous_revision=revision-1)",
            name="risk_followup_chain",
        ),
        CheckConstraint(
            "operation='work.risk.followup.record' AND confirmation_id IS NOT NULL "
            "AND writer_id=actor_id AND actor_id=requester_id",
            name="risk_followup_t1_only",
        ),
        CheckConstraint(
            "(action='close' AND state='closed') OR (action='reopen' AND state='open')",
            name="risk_followup_state",
        ),
    )


class ProjectRiskFollowupCurrent(_Scope, Base):
    __tablename__ = CURRENT
    risk_id: Mapped[UUID]
    g0_decision_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))

    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "risk_id"),
        _fk(
            (*BINDING, "risk_id", "g0_decision_id", "version_id", "revision"),
            FOLLOWUP,
            (*BINDING, "risk_id", "g0_decision_id", "id", "revision"),
        ),
        CheckConstraint(
            "revision>0 AND state IN ('open','closed')", name="risk_followup_current_state"
        ),
    )
