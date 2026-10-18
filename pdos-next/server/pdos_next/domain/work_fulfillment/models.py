"""Independent recipient review facts over fixed promises and actual submissions."""

from uuid import UUID

from sqlalchemy import CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.domain.work_management.models import (
    BINDING,
    COMMITMENT,
    TASK,
    _Fact,
    _fact,
    _fk,
    _Scope,
    _scope,
)
from pdos_next.models import Base

REVIEW = "work_commitment_reviews"
CURRENT = "work_commitment_review_currents"
OPERATION = "work.commitment.review"
EVENT = "commitment.reviewed"
SUBJECT = "work_commitment_review"
REVIEW_BINDING = (*BINDING, "commitment_id")


class WorkCommitmentReview(_Fact, Base):
    __tablename__ = REVIEW
    commitment_id: Mapped[UUID]
    commitment_revision: Mapped[int] = mapped_column(Integer)
    series_id: Mapped[UUID]
    task_id: Mapped[UUID]
    task_revision: Mapped[int] = mapped_column(Integer)
    task_version_id: Mapped[UUID]
    submission_id: Mapped[UUID]
    submission_revision: Mapped[int] = mapped_column(Integer)
    promisor_id: Mapped[UUID]
    recipient_id: Mapped[UUID]
    previous_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))

    @property
    def status(self):
        return self.state

    __table_args__ = (
        *_fact(),
        UniqueConstraint("tenant_id", "product_id", "commitment_id", "revision"),
        UniqueConstraint(*REVIEW_BINDING, "id", "revision"),
        UniqueConstraint(*REVIEW_BINDING, "id", "revision", "state"),
        _fk(
            (
                *BINDING,
                "task_id",
                "promisor_id",
                "recipient_id",
                "series_id",
                "commitment_id",
                "commitment_revision",
            ),
            COMMITMENT,
            (*BINDING, "task_id", "promisor_id", "recipient_id", "series_id", "id", "revision"),
        ),
        *(
            _fk(
                (*BINDING, "task_id", row_id, revision),
                TASK,
                (*BINDING, "task_id", "id", "revision"),
            )
            for row_id, revision in (
                ("task_version_id", "task_revision"),
                ("submission_id", "submission_revision"),
            )
        ),
        _fk(
            (*REVIEW_BINDING, "previous_id", "previous_revision"),
            REVIEW,
            (*REVIEW_BINDING, "id", "revision"),
        ),
        CheckConstraint(
            "operation='work.commitment.review' AND confirmation_id IS NOT NULL "
            "AND actor_id=requester_id AND actor_id=recipient_id"
        ),
        CheckConstraint("commitment_revision>0 AND task_revision>0 AND submission_revision>0"),
        CheckConstraint(
            "(revision=1 AND previous_id IS NULL AND previous_revision IS NULL) OR "
            "(revision>1 AND previous_id IS NOT NULL AND previous_id<>id "
            "AND previous_revision=revision-1)"
        ),
        CheckConstraint(
            "(decision='accepted' AND state='fulfilled') OR (decision='returned' AND state='open')"
        ),
    )


class WorkCommitmentReviewCurrent(_Scope, Base):
    __tablename__ = CURRENT
    commitment_id: Mapped[UUID]
    version_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        *_scope(),
        UniqueConstraint("tenant_id", "product_id", "commitment_id"),
        _fk(
            (*REVIEW_BINDING, "version_id", "revision", "state"),
            REVIEW,
            (*REVIEW_BINDING, "id", "revision", "state"),
        ),
        CheckConstraint("revision>0 AND state IN ('open','fulfilled')"),
    )
