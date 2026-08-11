"""Canonical SQLAlchemy metadata for the implemented PDOS entity slices."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db.namespaces import AUDIT_SCHEMA, CORE_SCHEMA, EVENT_SCHEMA, PROJECT_SCHEMA

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)
json_type = JSON().with_variant(JSONB(), "postgresql")

tenants = Table(
    "tenants",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("slug", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'active'")),
    Column("settings", json_type, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("status IN ('active', 'suspended')", name="status_allowed"),
    UniqueConstraint("slug", name="uq_tenants_slug"),
    schema=CORE_SCHEMA,
)

users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("username", String(64), nullable=False),
    Column("email", String(320)),
    Column("display_name", String(256), nullable=False),
    Column("role", String(32), nullable=False),
    Column("password_hash", String(256)),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("last_signed_in_at", DateTime(timezone=True)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "role IN ('owner', 'admin', 'project_manager', 'engineer', 'quality', "
        "'supplier', 'customer')",
        name="role_allowed",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id_id"),
    UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
    UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    Index("ix_users_tenant_active", "tenant_id", "is_active"),
    schema=CORE_SCHEMA,
)

customers = Table(
    "customers",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("description", Text),
    Column("external_reference", String(256)),
    Column("status", String(32), nullable=False, server_default=text("'active'")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("status IN ('active', 'inactive')", name="status_allowed"),
    UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
    UniqueConstraint("tenant_id", "code", name="uq_customers_tenant_code"),
    Index("ix_customers_tenant_status", "tenant_id", "status"),
    schema=CORE_SCHEMA,
)

requirements = Table(
    "requirements",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("customer_id", Uuid),
    Column("created_by_user_id", Uuid),
    Column("code", String(64), nullable=False),
    Column("title", String(512), nullable=False),
    Column("description", Text),
    Column("source", String(64)),
    Column("status", String(32), nullable=False, server_default=text("'draft'")),
    Column("priority", String(16), nullable=False, server_default=text("'medium'")),
    Column("acceptance_criteria", json_type, nullable=False, server_default=text("'[]'::jsonb")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "status IN ('draft', 'proposed', 'approved', 'rejected', 'converted')",
        name="status_allowed",
    ),
    CheckConstraint("priority IN ('low', 'medium', 'high', 'critical')", name="priority_allowed"),
    ForeignKeyConstraint(
        ["tenant_id", "customer_id"],
        [f"{CORE_SCHEMA}.customers.tenant_id", f"{CORE_SCHEMA}.customers.id"],
        name="fk_requirements_tenant_customer",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_requirements_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_requirements_tenant_id_id"),
    UniqueConstraint("tenant_id", "code", name="uq_requirements_tenant_code"),
    Index("ix_requirements_tenant_status", "tenant_id", "status"),
    schema=PROJECT_SCHEMA,
)

development_cases = Table(
    "development_cases",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("requirement_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid),
    Column("code", String(64), nullable=False),
    Column("title", String(512), nullable=False),
    Column("summary", Text),
    Column("status", String(32), nullable=False, server_default=text("'draft'")),
    Column("business_case", json_type, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "status IN ('draft', 'proposed', 'approved', 'rejected', 'converted')",
        name="status_allowed",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "requirement_id"],
        [f"{PROJECT_SCHEMA}.requirements.tenant_id", f"{PROJECT_SCHEMA}.requirements.id"],
        name="fk_development_cases_tenant_requirement",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_development_cases_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_development_cases_tenant_id_id"),
    UniqueConstraint("tenant_id", "code", name="uq_development_cases_tenant_code"),
    Index("ix_development_cases_tenant_status", "tenant_id", "status"),
    schema=PROJECT_SCHEMA,
)

workflows = Table(
    "workflows",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("description", Text),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("version > 0", name="positive_version"),
    UniqueConstraint("tenant_id", "id", name="uq_workflows_tenant_id_id"),
    UniqueConstraint("tenant_id", "code", "version", name="uq_workflows_tenant_code_version"),
    Index("ix_workflows_tenant_active", "tenant_id", "is_active"),
    schema=PROJECT_SCHEMA,
)

stages = Table(
    "stages",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("workflow_id", Uuid, nullable=False),
    Column("code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("description", Text),
    Column("sequence", Integer, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("sequence > 0", name="positive_sequence"),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id"],
        [f"{PROJECT_SCHEMA}.workflows.tenant_id", f"{PROJECT_SCHEMA}.workflows.id"],
        name="fk_stages_tenant_workflow",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_stages_tenant_id_id"),
    UniqueConstraint("tenant_id", "workflow_id", "id", name="uq_stages_tenant_workflow_id"),
    UniqueConstraint("tenant_id", "workflow_id", "code", name="uq_stages_tenant_workflow_code"),
    UniqueConstraint(
        "tenant_id",
        "workflow_id",
        "sequence",
        name="uq_stages_tenant_workflow_sequence",
    ),
    schema=PROJECT_SCHEMA,
)

projects = Table(
    "projects",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("development_case_id", Uuid),
    Column("customer_id", Uuid),
    Column("workflow_id", Uuid, nullable=False),
    Column("current_stage_id", Uuid),
    Column("owner_user_id", Uuid),
    Column("code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("description", Text),
    Column("status", String(32), nullable=False, server_default=text("'draft'")),
    Column("start_date", Date),
    Column("target_date", Date),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "status IN ('draft', 'proposed', 'approved', 'active', 'on_hold', 'completed', 'archived')",
        name="status_allowed",
    ),
    CheckConstraint(
        "target_date IS NULL OR start_date IS NULL OR target_date >= start_date",
        name="date_order",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "development_case_id"],
        [
            f"{PROJECT_SCHEMA}.development_cases.tenant_id",
            f"{PROJECT_SCHEMA}.development_cases.id",
        ],
        name="fk_projects_tenant_development_case",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "customer_id"],
        [f"{CORE_SCHEMA}.customers.tenant_id", f"{CORE_SCHEMA}.customers.id"],
        name="fk_projects_tenant_customer",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id"],
        [f"{PROJECT_SCHEMA}.workflows.tenant_id", f"{PROJECT_SCHEMA}.workflows.id"],
        name="fk_projects_tenant_workflow",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "current_stage_id"],
        [
            f"{PROJECT_SCHEMA}.stages.tenant_id",
            f"{PROJECT_SCHEMA}.stages.workflow_id",
            f"{PROJECT_SCHEMA}.stages.id",
        ],
        name="fk_projects_tenant_workflow_current_stage",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "owner_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_projects_tenant_owner",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_projects_tenant_id_id"),
    UniqueConstraint("tenant_id", "workflow_id", "id", name="uq_projects_tenant_workflow_id"),
    UniqueConstraint("tenant_id", "code", name="uq_projects_tenant_code"),
    Index("ix_projects_tenant_status", "tenant_id", "status"),
    schema=PROJECT_SCHEMA,
)

project_members = Table(
    "project_members",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("user_id", Uuid, nullable=False),
    Column("added_by_user_id", Uuid, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_project_members_tenant_project",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_project_members_tenant_user",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "added_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_project_members_tenant_added_by",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_project_members_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "user_id",
        name="uq_project_members_tenant_project_user",
    ),
    Index("ix_project_members_tenant_project", "tenant_id", "project_id"),
    Index("ix_project_members_tenant_user", "tenant_id", "user_id"),
    schema=PROJECT_SCHEMA,
)

gates = Table(
    "gates",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("stage_id", Uuid, nullable=False),
    Column("code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'preparing'")),
    Column("review_due_at", DateTime(timezone=True)),
    Column("decided_at", DateTime(timezone=True)),
    Column("decided_by_user_id", Uuid),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "status IN ('preparing', 'reviewing', 'approved', 'rejected')",
        name="status_allowed",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_gates_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "stage_id"],
        [f"{PROJECT_SCHEMA}.stages.tenant_id", f"{PROJECT_SCHEMA}.stages.id"],
        name="fk_gates_tenant_stage",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "decided_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_gates_tenant_decider",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_gates_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_gates_tenant_project_id"),
    UniqueConstraint("tenant_id", "project_id", "code", name="uq_gates_tenant_project_code"),
    Index("ix_gates_tenant_project_status", "tenant_id", "project_id", "status"),
    schema=PROJECT_SCHEMA,
)

tasks = Table(
    "tasks",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("stage_id", Uuid),
    Column("parent_task_id", Uuid),
    Column("assignee_user_id", Uuid),
    Column("title", String(512), nullable=False),
    Column("description", Text),
    Column("status", String(32), nullable=False, server_default=text("'todo'")),
    Column("priority", String(16), nullable=False, server_default=text("'medium'")),
    Column("start_date", Date),
    Column("due_date", Date),
    Column("completed_at", DateTime(timezone=True)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "status IN ('todo', 'in_progress', 'blocked', 'done', 'skipped', 'pending_approval')",
        name="status_allowed",
    ),
    CheckConstraint("priority IN ('low', 'medium', 'high', 'critical')", name="priority_allowed"),
    CheckConstraint(
        "due_date IS NULL OR start_date IS NULL OR due_date >= start_date", name="date_order"
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_tasks_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "stage_id"],
        [f"{PROJECT_SCHEMA}.stages.tenant_id", f"{PROJECT_SCHEMA}.stages.id"],
        name="fk_tasks_tenant_stage",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "parent_task_id"],
        [
            f"{PROJECT_SCHEMA}.tasks.tenant_id",
            f"{PROJECT_SCHEMA}.tasks.project_id",
            f"{PROJECT_SCHEMA}.tasks.id",
        ],
        name="fk_tasks_tenant_project_parent",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "assignee_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_tasks_tenant_assignee",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_tasks_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_tasks_tenant_project_id"),
    Index("ix_tasks_tenant_project_status", "tenant_id", "project_id", "status"),
    Index("ix_tasks_tenant_assignee_status", "tenant_id", "assignee_user_id", "status"),
    Index("ix_tasks_tenant_due_date", "tenant_id", "due_date"),
    schema=PROJECT_SCHEMA,
)

issues = Table(
    "issues",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("stage_id", Uuid),
    Column("owner_user_id", Uuid),
    Column("reported_by_user_id", Uuid),
    Column("title", String(512), nullable=False),
    Column("description", Text),
    Column("status", String(32), nullable=False, server_default=text("'open'")),
    Column("severity", String(16), nullable=False, server_default=text("'medium'")),
    Column("root_cause", Text),
    Column("resolution", Text),
    Column("target_date", Date),
    Column("closed_at", DateTime(timezone=True)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "status IN ('open', 'analysis', 'action', 'verification', 'closed')",
        name="status_allowed",
    ),
    CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="severity_allowed"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_issues_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "stage_id"],
        [f"{PROJECT_SCHEMA}.stages.tenant_id", f"{PROJECT_SCHEMA}.stages.id"],
        name="fk_issues_tenant_stage",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "owner_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_issues_tenant_owner",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "reported_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_issues_tenant_reporter",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_issues_tenant_id_id"),
    Index(
        "ix_issues_tenant_project_status_severity",
        "tenant_id",
        "project_id",
        "status",
        "severity",
    ),
    schema=PROJECT_SCHEMA,
)

risks = Table(
    "risks",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("owner_user_id", Uuid),
    Column("title", String(512), nullable=False),
    Column("description", Text),
    Column("status", String(32), nullable=False, server_default=text("'open'")),
    Column("likelihood", SmallInteger, nullable=False, server_default=text("1")),
    Column("impact", SmallInteger, nullable=False, server_default=text("1")),
    Column("mitigation_plan", Text),
    Column("contingency_plan", Text),
    Column("target_date", Date),
    Column("closed_at", DateTime(timezone=True)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "status IN ('open', 'mitigating', 'watching', 'closed')", name="status_allowed"
    ),
    CheckConstraint("likelihood BETWEEN 1 AND 5", name="likelihood_range"),
    CheckConstraint("impact BETWEEN 1 AND 5", name="impact_range"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_risks_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "owner_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_risks_tenant_owner",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_risks_tenant_id_id"),
    Index("ix_risks_tenant_project_status", "tenant_id", "project_id", "status"),
    Index("ix_risks_tenant_target_date", "tenant_id", "target_date"),
    schema=PROJECT_SCHEMA,
)

decisions = Table(
    "decisions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("requirement_id", Uuid),
    Column("development_case_id", Uuid),
    Column("project_id", Uuid),
    Column("gate_id", Uuid),
    Column("decided_by_user_id", Uuid),
    Column("decision_kind", String(64), nullable=False),
    Column("title", String(512), nullable=False),
    Column("outcome", Text, nullable=False),
    Column("rationale", Text),
    Column(
        "decided_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "requirement_id IS NOT NULL OR development_case_id IS NOT NULL "
        "OR project_id IS NOT NULL OR gate_id IS NOT NULL",
        name="subject_present",
    ),
    CheckConstraint("gate_id IS NULL OR project_id IS NOT NULL", name="gate_requires_project"),
    ForeignKeyConstraint(
        ["tenant_id", "requirement_id"],
        [f"{PROJECT_SCHEMA}.requirements.tenant_id", f"{PROJECT_SCHEMA}.requirements.id"],
        name="fk_decisions_tenant_requirement",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "development_case_id"],
        [
            f"{PROJECT_SCHEMA}.development_cases.tenant_id",
            f"{PROJECT_SCHEMA}.development_cases.id",
        ],
        name="fk_decisions_tenant_development_case",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_decisions_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "gate_id"],
        [
            f"{PROJECT_SCHEMA}.gates.tenant_id",
            f"{PROJECT_SCHEMA}.gates.project_id",
            f"{PROJECT_SCHEMA}.gates.id",
        ],
        name="fk_decisions_tenant_project_gate",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "decided_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_decisions_tenant_decider",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_decisions_tenant_id_id"),
    Index("ix_decisions_tenant_project_decided", "tenant_id", "project_id", "decided_at"),
    schema=PROJECT_SCHEMA,
)

events = Table(
    "events",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid),
    Column("event_id", String(128), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("schema_version", SmallInteger, nullable=False),
    Column("source", String(64), nullable=False),
    Column("entity", String(64), nullable=False),
    Column("entity_id", Uuid, nullable=False),
    Column("payload", json_type, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "timestamp",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("schema_version > 0", name="schema_version_positive"),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_events_tenant_project",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("source", "event_id", name="uq_events_source_event_id"),
    Index("ix_events_tenant_id", "tenant_id", "id"),
    Index("ix_events_tenant_project_id", "tenant_id", "project_id", "id"),
    Index("ix_events_event_type_id", "event_type", "id"),
    schema=EVENT_SCHEMA,
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid),
    Column("actor_user_id", Uuid),
    Column("event_id", String(128), nullable=False),
    Column("action", String(128), nullable=False),
    Column("entity", String(64), nullable=False),
    Column("entity_id", Uuid, nullable=False),
    Column("before_snapshot", json_type),
    Column("after_snapshot", json_type),
    Column("context", json_type, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "timestamp",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "(before_snapshot IS NOT NULL AND jsonb_typeof(before_snapshot) = 'object') "
        "OR (after_snapshot IS NOT NULL AND jsonb_typeof(after_snapshot) = 'object')",
        name="snapshot_present",
    ),
    CheckConstraint(
        "before_snapshot IS NULL OR jsonb_typeof(before_snapshot) = 'object'",
        name="before_snapshot_object",
    ),
    CheckConstraint(
        "after_snapshot IS NULL OR jsonb_typeof(after_snapshot) = 'object'",
        name="after_snapshot_object",
    ),
    CheckConstraint("jsonb_typeof(context) = 'object'", name="context_object"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_audit_log_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "actor_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_audit_log_tenant_actor",
        ondelete="RESTRICT",
    ),
    Index("ix_audit_log_tenant_id", "tenant_id", "id"),
    Index("ix_audit_log_tenant_project_id", "tenant_id", "project_id", "id"),
    Index("ix_audit_log_entity_id", "entity", "entity_id", "id"),
    schema=AUDIT_SCHEMA,
)


@dataclass(frozen=True)
class Tables:
    tenants: Table
    users: Table
    customers: Table
    requirements: Table
    development_cases: Table
    projects: Table
    project_members: Table
    workflows: Table
    stages: Table
    gates: Table
    tasks: Table
    issues: Table
    risks: Table
    decisions: Table
    events: Table
    audit_log: Table


tables = Tables(
    tenants=tenants,
    users=users,
    customers=customers,
    requirements=requirements,
    development_cases=development_cases,
    projects=projects,
    project_members=project_members,
    workflows=workflows,
    stages=stages,
    gates=gates,
    tasks=tasks,
    issues=issues,
    risks=risks,
    decisions=decisions,
    events=events,
    audit_log=audit_log,
)
