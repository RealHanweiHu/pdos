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

from app.db.namespaces import AI_SCHEMA, AUDIT_SCHEMA, CORE_SCHEMA, EVENT_SCHEMA, PROJECT_SCHEMA

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
    CheckConstraint("btrim(code) <> ''", name="code_nonblank"),
    CheckConstraint("btrim(name) <> ''", name="name_nonblank"),
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
    CheckConstraint("btrim(code) <> ''", name="code_nonblank"),
    CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
    CheckConstraint(
        "jsonb_typeof(acceptance_criteria) = 'array'",
        name="acceptance_criteria_array",
    ),
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
    Index("ix_requirements_tenant_updated", "tenant_id", "updated_at", "id"),
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
        "status IN ('draft', 'evaluating', 'approved', 'rejected', 'converted')",
        name="status_allowed",
    ),
    CheckConstraint("btrim(code) <> ''", name="code_nonblank"),
    CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
    CheckConstraint("jsonb_typeof(business_case) = 'object'", name="business_case_object"),
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
    UniqueConstraint(
        "tenant_id",
        "requirement_id",
        name="uq_development_cases_tenant_requirement",
    ),
    Index("ix_development_cases_tenant_status", "tenant_id", "status"),
    Index("ix_development_cases_tenant_updated", "tenant_id", "updated_at", "id"),
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
    CheckConstraint("btrim(code) <> ''", name="code_nonblank"),
    CheckConstraint("btrim(name) <> ''", name="name_nonblank"),
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
    CheckConstraint("btrim(code) <> ''", name="code_nonblank"),
    CheckConstraint("btrim(name) <> ''", name="name_nonblank"),
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
    CheckConstraint("btrim(code) <> ''", name="code_nonblank"),
    CheckConstraint("btrim(name) <> ''", name="name_nonblank"),
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
    UniqueConstraint(
        "tenant_id",
        "development_case_id",
        name="uq_projects_tenant_development_case",
    ),
    UniqueConstraint("tenant_id", "workflow_id", name="uq_projects_tenant_workflow"),
    Index("ix_projects_tenant_status", "tenant_id", "status"),
    Index("ix_projects_tenant_updated", "tenant_id", "updated_at", "id"),
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
    Column("workflow_id", Uuid),
    Column("stage_id", Uuid),
    Column("parent_task_id", Uuid),
    Column("assignee_user_id", Uuid),
    Column("title", String(512), nullable=False),
    Column("description", Text),
    Column("status", String(32), nullable=False, server_default=text("'todo'")),
    Column("blocked_reason", Text),
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
    CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
    CheckConstraint(
        "(status = 'blocked' AND blocked_reason IS NOT NULL AND btrim(blocked_reason) <> '') "
        "OR (status <> 'blocked' AND blocked_reason IS NULL)",
        name="blocked_reason_consistent",
    ),
    CheckConstraint(
        "(status = 'done' AND completed_at IS NOT NULL) "
        "OR (status <> 'done' AND completed_at IS NULL)",
        name="completion_consistent",
    ),
    CheckConstraint(
        "(workflow_id IS NULL AND stage_id IS NULL) "
        "OR (workflow_id IS NOT NULL AND stage_id IS NOT NULL)",
        name="stage_pair_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_tasks_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "project_id"],
        [
            f"{PROJECT_SCHEMA}.projects.tenant_id",
            f"{PROJECT_SCHEMA}.projects.workflow_id",
            f"{PROJECT_SCHEMA}.projects.id",
        ],
        name="fk_tasks_tenant_project_workflow",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "stage_id"],
        [
            f"{PROJECT_SCHEMA}.stages.tenant_id",
            f"{PROJECT_SCHEMA}.stages.workflow_id",
            f"{PROJECT_SCHEMA}.stages.id",
        ],
        name="fk_tasks_tenant_workflow_stage",
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
    Index("ix_tasks_tenant_project_updated", "tenant_id", "project_id", "updated_at", "id"),
    schema=PROJECT_SCHEMA,
)

task_dependencies = Table(
    "task_dependencies",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("task_id", Uuid, nullable=False),
    Column("depends_on_task_id", Uuid, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("task_id <> depends_on_task_id", name="no_self_reference"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "task_id"],
        [
            f"{PROJECT_SCHEMA}.tasks.tenant_id",
            f"{PROJECT_SCHEMA}.tasks.project_id",
            f"{PROJECT_SCHEMA}.tasks.id",
        ],
        name="fk_task_dependencies_tenant_project_task",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "depends_on_task_id"],
        [
            f"{PROJECT_SCHEMA}.tasks.tenant_id",
            f"{PROJECT_SCHEMA}.tasks.project_id",
            f"{PROJECT_SCHEMA}.tasks.id",
        ],
        name="fk_task_dependencies_tenant_project_predecessor",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "task_id",
        "depends_on_task_id",
        name="uq_task_dependencies_tenant_project_edge",
    ),
    Index(
        "ix_task_dependencies_tenant_project_predecessor",
        "tenant_id",
        "project_id",
        "depends_on_task_id",
    ),
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
    Column("workflow_id", Uuid),
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
    CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
    CheckConstraint(
        "(status = 'closed' AND closed_at IS NOT NULL) "
        "OR (status <> 'closed' AND closed_at IS NULL)",
        name="closed_at_consistent",
    ),
    CheckConstraint(
        "(workflow_id IS NULL AND stage_id IS NULL) "
        "OR (workflow_id IS NOT NULL AND stage_id IS NOT NULL)",
        name="stage_pair_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_issues_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "project_id"],
        [
            f"{PROJECT_SCHEMA}.projects.tenant_id",
            f"{PROJECT_SCHEMA}.projects.workflow_id",
            f"{PROJECT_SCHEMA}.projects.id",
        ],
        name="fk_issues_tenant_project_workflow",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "stage_id"],
        [
            f"{PROJECT_SCHEMA}.stages.tenant_id",
            f"{PROJECT_SCHEMA}.stages.workflow_id",
            f"{PROJECT_SCHEMA}.stages.id",
        ],
        name="fk_issues_tenant_workflow_stage",
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
    Index("ix_issues_tenant_project_updated", "tenant_id", "project_id", "updated_at", "id"),
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
    CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
    CheckConstraint(
        "(status = 'closed' AND closed_at IS NOT NULL) "
        "OR (status <> 'closed' AND closed_at IS NULL)",
        name="closed_at_consistent",
    ),
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
    Index("ix_risks_tenant_project_updated", "tenant_id", "project_id", "updated_at", "id"),
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

tenant_model_settings = Table(
    "tenant_model_settings",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("provider", String(32), nullable=False, server_default=text("'minimax'")),
    Column("model", String(128), nullable=False, server_default=text("'MiniMax-M2.7'")),
    Column(
        "daily_token_budget",
        BigInteger,
        nullable=False,
        server_default=text("2000000"),
    ),
    Column("updated_by_user_id", Uuid),
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
        "provider IN ('minimax', 'deepseek', 'glm', 'openai', 'anthropic')",
        name="provider_allowed",
    ),
    CheckConstraint("btrim(model) <> ''", name="model_nonblank"),
    CheckConstraint(
        "daily_token_budget BETWEEN 1 AND 1000000000",
        name="daily_budget_range",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "updated_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_tenant_model_settings_tenant_updater",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", name="uq_tenant_model_settings_tenant_id"),
    schema=AI_SCHEMA,
)

agent_dispatcher_cursors = Table(
    "agent_dispatcher_cursors",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("consumer_key", String(64), nullable=False),
    Column("last_event_row_id", BigInteger, nullable=False, server_default=text("0")),
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
    CheckConstraint("btrim(consumer_key) <> ''", name="consumer_key_nonblank"),
    CheckConstraint("last_event_row_id >= 0", name="last_event_nonnegative"),
    UniqueConstraint(
        "tenant_id",
        "consumer_key",
        name="uq_agent_dispatcher_cursors_tenant_consumer",
    ),
    schema=AI_SCHEMA,
)

agent_subscriptions = Table(
    "agent_subscriptions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("agent_key", String(64), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'active'")),
    Column(
        "consecutive_failure_count",
        SmallInteger,
        nullable=False,
        server_default=text("0"),
    ),
    Column("failure_threshold", SmallInteger, nullable=False, server_default=text("3")),
    Column("paused_reason", String(256)),
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
        "agent_key IN ('project_intelligence', 'knowledge_lite')",
        name="agent_key_allowed",
    ),
    CheckConstraint("status IN ('active', 'paused')", name="status_allowed"),
    CheckConstraint(
        "consecutive_failure_count >= 0",
        name="failure_count_nonnegative",
    ),
    CheckConstraint(
        "failure_threshold BETWEEN 1 AND 20",
        name="failure_threshold_range",
    ),
    CheckConstraint(
        "(status = 'active' AND paused_reason IS NULL) OR "
        "(status = 'paused' AND paused_reason IS NOT NULL AND btrim(paused_reason) <> '')",
        name="pause_reason_consistent",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_agent_subscriptions_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "id",
        "agent_key",
        name="uq_agent_subscriptions_tenant_id_agent",
    ),
    UniqueConstraint(
        "tenant_id",
        "agent_key",
        name="uq_agent_subscriptions_tenant_agent",
    ),
    schema=AI_SCHEMA,
)

agent_runs = Table(
    "agent_runs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("subscription_id", Uuid, nullable=False),
    Column("agent_key", String(64), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'debouncing'")),
    Column("window_started_at", DateTime(timezone=True), nullable=False),
    Column("window_ended_at", DateTime(timezone=True), nullable=False),
    Column("first_event_row_id", BigInteger, nullable=False),
    Column("last_event_row_id", BigInteger, nullable=False),
    Column("event_count", Integer, nullable=False),
    Column("event_row_ids", json_type, nullable=False),
    Column("context_version", String(64), nullable=False, server_default=text("'run-context-v1'")),
    Column("run_context", json_type, nullable=False, server_default=text("'{}'::jsonb")),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("error_code", String(64)),
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
        "agent_key IN ('project_intelligence', 'knowledge_lite')",
        name="agent_key_allowed",
    ),
    CheckConstraint(
        "status IN ('debouncing', 'queued', 'running', 'succeeded', 'degraded', 'failed')",
        name="status_allowed",
    ),
    CheckConstraint("window_started_at <= window_ended_at", name="window_order"),
    CheckConstraint(
        "CASE WHEN jsonb_typeof(event_row_ids) = 'array' THEN "
        "event_count > 0 AND first_event_row_id > 0 "
        "AND last_event_row_id >= first_event_row_id "
        "AND jsonb_array_length(event_row_ids) = event_count "
        "AND (event_row_ids->>0)::bigint = first_event_row_id "
        "AND (event_row_ids->>(event_count - 1))::bigint = last_event_row_id "
        "ELSE false END",
        name="event_bounds_consistent",
    ),
    CheckConstraint("jsonb_typeof(event_row_ids) = 'array'", name="event_ids_array"),
    CheckConstraint("jsonb_typeof(run_context) = 'object'", name="context_object"),
    CheckConstraint("btrim(context_version) <> ''", name="context_version_nonblank"),
    CheckConstraint(
        "(status IN ('debouncing', 'queued') AND started_at IS NULL AND completed_at IS NULL) "
        "OR (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL) "
        "OR (status IN ('succeeded', 'degraded', 'failed') "
        "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
        name="lifecycle_consistent",
    ),
    CheckConstraint(
        "(status IN ('degraded', 'failed') AND error_code IS NOT NULL "
        "AND btrim(error_code) <> '') OR "
        "(status NOT IN ('degraded', 'failed') AND error_code IS NULL)",
        name="error_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_agent_runs_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "subscription_id", "agent_key"],
        [
            f"{AI_SCHEMA}.agent_subscriptions.tenant_id",
            f"{AI_SCHEMA}.agent_subscriptions.id",
            f"{AI_SCHEMA}.agent_subscriptions.agent_key",
        ],
        name="fk_agent_runs_tenant_subscription_agent",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_agent_runs_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "id",
        "agent_key",
        name="uq_agent_runs_tenant_project_id_agent",
    ),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "agent_key",
        "window_started_at",
        name="uq_agent_runs_tenant_project_agent_window",
    ),
    Index("ix_agent_runs_tenant_status_created", "tenant_id", "status", "created_at", "id"),
    Index("ix_agent_runs_tenant_project_created", "tenant_id", "project_id", "created_at", "id"),
    Index("ix_agent_runs_tenant_agent_created", "tenant_id", "agent_key", "created_at", "id"),
    schema=AI_SCHEMA,
)

model_invocations = Table(
    "model_invocations",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid),
    Column("run_id", Uuid),
    Column("request_id", String(128)),
    Column("agent_key", String(64), nullable=False),
    Column("agent_tier", String(32), nullable=False, server_default=text("'default'")),
    Column("prompt_version", String(128), nullable=False),
    Column("provider", String(32), nullable=False),
    Column("model", String(128), nullable=False),
    Column("model_version", String(128)),
    Column("protocol", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("input_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("output_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("total_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("cache_read_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("cache_creation_tokens", BigInteger, nullable=False, server_default=text("0")),
    Column("latency_ms", Integer, nullable=False, server_default=text("0")),
    Column(
        "normalized_cost_microusd",
        BigInteger,
        nullable=False,
        server_default=text("0"),
    ),
    Column("structured_attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("error_code", String(64)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "provider IN ('minimax', 'deepseek', 'glm', 'openai', 'anthropic')",
        name="provider_allowed",
    ),
    CheckConstraint(
        "protocol IN ('openai-compatible', 'anthropic-native')",
        name="protocol_allowed",
    ),
    CheckConstraint(
        "agent_tier IN ('default', 'extraction', 'reasoning')",
        name="agent_tier_allowed",
    ),
    CheckConstraint(
        "status IN ('succeeded', 'provider_error', 'schema_error', 'budget_exceeded')",
        name="status_allowed",
    ),
    CheckConstraint("btrim(agent_key) <> ''", name="agent_key_nonblank"),
    CheckConstraint("btrim(prompt_version) <> ''", name="prompt_version_nonblank"),
    CheckConstraint("btrim(model) <> ''", name="model_nonblank"),
    CheckConstraint(
        "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0 "
        "AND total_tokens = input_tokens + output_tokens",
        name="token_totals_consistent",
    ),
    CheckConstraint(
        "cache_read_tokens >= 0 AND cache_creation_tokens >= 0",
        name="cache_tokens_nonnegative",
    ),
    CheckConstraint("latency_ms >= 0", name="latency_nonnegative"),
    CheckConstraint("normalized_cost_microusd >= 0", name="cost_nonnegative"),
    CheckConstraint(
        "structured_attempts BETWEEN 0 AND 3",
        name="structured_attempts_range",
    ),
    CheckConstraint(
        "(status = 'succeeded' AND error_code IS NULL) OR "
        "(status <> 'succeeded' AND error_code IS NOT NULL AND btrim(error_code) <> '')",
        name="error_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_model_invocations_tenant_project",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id",
        "id",
        name="uq_model_invocations_tenant_id_id",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        [f"{AI_SCHEMA}.agent_runs.tenant_id", f"{AI_SCHEMA}.agent_runs.id"],
        name="fk_model_invocations_tenant_run",
        ondelete="RESTRICT",
    ),
    Index("ix_model_invocations_tenant_created", "tenant_id", "created_at", "id"),
    Index(
        "ix_model_invocations_tenant_agent_created",
        "tenant_id",
        "agent_key",
        "created_at",
        "id",
    ),
    Index(
        "ix_model_invocations_tenant_project_created",
        "tenant_id",
        "project_id",
        "created_at",
        "id",
    ),
    schema=AI_SCHEMA,
)

findings = Table(
    "findings",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("run_id", Uuid, nullable=False),
    Column("model_invocation_id", Uuid, nullable=False),
    Column("agent_key", String(64), nullable=False),
    Column("finding_type", String(64), nullable=False),
    Column("origin_key", String(128), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'pending_review'")),
    Column("title", String(512), nullable=False),
    Column("summary", Text, nullable=False),
    Column("proposed_payload", json_type, nullable=False),
    Column("accepted_payload", json_type),
    Column("evidence_event_ids", json_type, nullable=False),
    Column("confidence_basis_points", SmallInteger, nullable=False),
    Column("preflight_version", String(64), nullable=False),
    Column("reviewed_by_user_id", Uuid),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("review_comment", Text),
    Column("applied_by_user_id", Uuid),
    Column("applied_at", DateTime(timezone=True)),
    Column("applied_entity_type", String(64)),
    Column("applied_entity_id", Uuid),
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
    CheckConstraint("finding_type IN ('risk_suggestion')", name="type_allowed"),
    CheckConstraint(
        "status IN ('pending_review', 'accepted', 'rejected', 'applied')",
        name="status_allowed",
    ),
    CheckConstraint("btrim(origin_key) <> ''", name="origin_key_nonblank"),
    CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
    CheckConstraint("btrim(summary) <> ''", name="summary_nonblank"),
    CheckConstraint("btrim(preflight_version) <> ''", name="preflight_version_nonblank"),
    CheckConstraint("jsonb_typeof(proposed_payload) = 'object'", name="proposed_payload_object"),
    CheckConstraint(
        "accepted_payload IS NULL OR jsonb_typeof(accepted_payload) = 'object'",
        name="accepted_payload_object",
    ),
    CheckConstraint(
        "jsonb_typeof(evidence_event_ids) = 'array' AND jsonb_array_length(evidence_event_ids) > 0",
        name="evidence_event_ids_array",
    ),
    CheckConstraint(
        "confidence_basis_points BETWEEN 0 AND 10000",
        name="confidence_range",
    ),
    CheckConstraint(
        "(status = 'pending_review' AND reviewed_by_user_id IS NULL "
        "AND reviewed_at IS NULL AND accepted_payload IS NULL) OR "
        "(status = 'accepted' AND reviewed_by_user_id IS NOT NULL "
        "AND reviewed_at IS NOT NULL AND accepted_payload IS NOT NULL) OR "
        "(status = 'rejected' AND reviewed_by_user_id IS NOT NULL "
        "AND reviewed_at IS NOT NULL AND accepted_payload IS NULL) OR "
        "(status = 'applied' AND reviewed_by_user_id IS NOT NULL "
        "AND reviewed_at IS NOT NULL AND accepted_payload IS NOT NULL)",
        name="review_lifecycle_consistent",
    ),
    CheckConstraint(
        "(status <> 'applied' AND applied_by_user_id IS NULL AND applied_at IS NULL "
        "AND applied_entity_type IS NULL AND applied_entity_id IS NULL) OR "
        "(status = 'applied' AND applied_by_user_id IS NOT NULL AND applied_at IS NOT NULL "
        "AND applied_entity_type = 'risk' AND applied_entity_id IS NOT NULL "
        "AND reviewed_at < applied_at)",
        name="apply_lifecycle_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "run_id", "agent_key"],
        [
            f"{AI_SCHEMA}.agent_runs.tenant_id",
            f"{AI_SCHEMA}.agent_runs.project_id",
            f"{AI_SCHEMA}.agent_runs.id",
            f"{AI_SCHEMA}.agent_runs.agent_key",
        ],
        name="fk_findings_tenant_project_run_agent",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "model_invocation_id"],
        [
            f"{AI_SCHEMA}.model_invocations.tenant_id",
            f"{AI_SCHEMA}.model_invocations.id",
        ],
        name="fk_findings_tenant_model_invocation",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "reviewed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_findings_tenant_reviewer",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "applied_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_findings_tenant_applier",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_findings_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "id",
        name="uq_findings_tenant_project_id",
    ),
    UniqueConstraint(
        "tenant_id",
        "run_id",
        "origin_key",
        name="uq_findings_tenant_run_origin",
    ),
    Index("ix_findings_tenant_status_created", "tenant_id", "status", "created_at", "id"),
    Index("ix_findings_tenant_project_status", "tenant_id", "project_id", "status", "id"),
    schema=AI_SCHEMA,
)

finding_actions = Table(
    "finding_actions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("finding_id", Uuid, nullable=False),
    Column("action", String(32), nullable=False),
    Column("actor_user_id", Uuid),
    Column("from_status", String(32)),
    Column("to_status", String(32), nullable=False),
    Column("detail", json_type, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "action IN ('created', 'accepted', 'rejected', 'applied')",
        name="action_allowed",
    ),
    CheckConstraint(
        "(action = 'created' AND actor_user_id IS NULL AND from_status IS NULL "
        "AND to_status = 'pending_review') OR "
        "(action IN ('accepted', 'rejected') AND actor_user_id IS NOT NULL "
        "AND from_status = 'pending_review' AND to_status = action) OR "
        "(action = 'applied' AND actor_user_id IS NOT NULL "
        "AND from_status = 'accepted' AND to_status = 'applied')",
        name="transition_consistent",
    ),
    CheckConstraint("jsonb_typeof(detail) = 'object'", name="detail_object"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "finding_id"],
        [
            f"{AI_SCHEMA}.findings.tenant_id",
            f"{AI_SCHEMA}.findings.project_id",
            f"{AI_SCHEMA}.findings.id",
        ],
        name="fk_finding_actions_tenant_project_finding",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "actor_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_finding_actions_tenant_actor",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id",
        "finding_id",
        "action",
        name="uq_finding_actions_tenant_finding_action",
    ),
    Index(
        "ix_finding_actions_tenant_finding_created",
        "tenant_id",
        "finding_id",
        "created_at",
        "id",
    ),
    schema=AI_SCHEMA,
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
    task_dependencies: Table
    issues: Table
    risks: Table
    decisions: Table
    tenant_model_settings: Table
    agent_dispatcher_cursors: Table
    agent_subscriptions: Table
    agent_runs: Table
    model_invocations: Table
    findings: Table
    finding_actions: Table
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
    task_dependencies=task_dependencies,
    issues=issues,
    risks=risks,
    decisions=decisions,
    tenant_model_settings=tenant_model_settings,
    agent_dispatcher_cursors=agent_dispatcher_cursors,
    agent_subscriptions=agent_subscriptions,
    agent_runs=agent_runs,
    model_invocations=model_invocations,
    findings=findings,
    finding_actions=finding_actions,
    events=events,
    audit_log=audit_log,
)
