"""Real development projects and fixed first plans, isolated from legacy business tables."""

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


def product_fk():
    return ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"])


def project_fk():
    return ForeignKeyConstraint(
        ["tenant_id", "product_id", "project_id"],
        ["projects.tenant_id", "projects.product_id", "projects.id"],
    )


def plan_fk():
    return ForeignKeyConstraint(
        ["tenant_id", "product_id", "project_id", "plan_id"],
        [
            "plan_revisions.tenant_id",
            "plan_revisions.product_id",
            "plan_revisions.project_id",
            "plan_revisions.id",
        ],
    )


class Project(Row, Base):
    __tablename__ = "projects"
    product_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    current_plan_id: Mapped[UUID | None]
    trigger_type: Mapped[str | None] = mapped_column(Text)
    trigger_id: Mapped[UUID | None]
    g0_decision_id: Mapped[UUID | None]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "g0_decision_id"],
            [
                "proposal_decisions.tenant_id",
                "proposal_decisions.category_id",
                "proposal_decisions.id",
            ],
            name="m3_project_decision_fk",
        ),
        UniqueConstraint("tenant_id", "product_id", "id"),
        product_fk(),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "id", "current_plan_id"],
            [
                "plan_revisions.tenant_id",
                "plan_revisions.product_id",
                "plan_revisions.project_id",
                "plan_revisions.id",
            ],
            name="fk_project_current_plan",
            use_alter=True,
        ),
        CheckConstraint("visibility IN ('private','category','audience') AND status = 'active'"),
        CheckConstraint("revision > 0"),
    )


class ProjectProductLink(Row, Base):
    __tablename__ = "project_product_links"
    product_id: Mapped[UUID]
    variant_id: Mapped[UUID | None] = mapped_column()
    project_id: Mapped[UUID]
    definition_id: Mapped[UUID]
    definition_revision: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        Index(
            "m3_project_model_scope",
            "tenant_id",
            "project_id",
            "product_id",
            unique=True,
            postgresql_where=variant_id.is_(None),
        ),
        Index(
            "m3_project_variant_scope",
            "tenant_id",
            "project_id",
            "product_id",
            "variant_id",
            unique=True,
            postgresql_where=variant_id.is_not(None),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.product_id", "product_variants.id"],
            name="m3_project_variant_fk",
        ),
        project_fk(),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        CheckConstraint("definition_revision > 0"),
    )


class PlanProposal(Row, Base):
    __tablename__ = "plan_proposals"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    project_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    forecast: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "project_id", "id"),
        UniqueConstraint("tenant_id", "project_id", "revision"),
        project_fk(),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("status = 'proposed' AND revision > 0 AND project_revision > 0"),
        CheckConstraint("visibility IN ('private','category','audience')"),
    )


class PlanRevision(Row, Base):
    __tablename__ = "plan_revisions"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    proposal_id: Mapped[UUID]
    owner_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="applied")
    visibility: Mapped[str] = mapped_column(String(16))
    forecast: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "project_id", "id"),
        UniqueConstraint("tenant_id", "project_id", "revision"),
        UniqueConstraint("tenant_id", "proposal_id"),
        project_fk(),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "proposal_id"],
            [
                "plan_proposals.tenant_id",
                "plan_proposals.product_id",
                "plan_proposals.project_id",
                "plan_proposals.id",
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint("status = 'applied' AND revision > 0"),
        CheckConstraint("visibility IN ('private','category','audience')"),
    )


class ProjectWorkPackage(Row, Base):
    __tablename__ = "project_work_packages"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    plan_id: Mapped[UUID]
    discipline: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "plan_id", "discipline"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "plan_id", "id"),
        plan_fk(),
        CheckConstraint("discipline IN ('engineering','npi')"),
    )


class ProjectTask(Row, Base):
    __tablename__ = "project_tasks"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    plan_id: Mapped[UUID]
    work_package_id: Mapped[UUID]
    key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    forecast: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "plan_id", "key"),
        UniqueConstraint("tenant_id", "product_id", "project_id", "plan_id", "id"),
        plan_fk(),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "project_id", "plan_id", "work_package_id"],
            [
                "project_work_packages.tenant_id",
                "project_work_packages.product_id",
                "project_work_packages.project_id",
                "project_work_packages.plan_id",
                "project_work_packages.id",
            ],
        ),
    )


class TaskDependency(Row, Base):
    __tablename__ = "task_dependencies"
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    plan_id: Mapped[UUID]
    task_id: Mapped[UUID]
    predecessor_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("tenant_id", "task_id", "predecessor_id"),
        *[
            ForeignKeyConstraint(
                ["tenant_id", "product_id", "project_id", "plan_id", column],
                [
                    "project_tasks.tenant_id",
                    "project_tasks.product_id",
                    "project_tasks.project_id",
                    "project_tasks.plan_id",
                    "project_tasks.id",
                ],
            )
            for column in ("task_id", "predecessor_id")
        ],
        CheckConstraint("task_id <> predecessor_id"),
    )
