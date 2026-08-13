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
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db.namespaces import (
    AI_SCHEMA,
    AUDIT_SCHEMA,
    CORE_SCHEMA,
    COST_SCHEMA,
    EVENT_SCHEMA,
    MEMORY_SCHEMA,
    PRODUCT_SCHEMA,
    PROJECT_SCHEMA,
    QUALITY_SCHEMA,
)
from app.db.vector import Vector

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

documents = Table(
    "documents",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("uploaded_by_user_id", Uuid, nullable=False),
    Column("object_key", String(1024), nullable=False),
    Column("filename", String(512), nullable=False),
    Column("media_type", String(128), nullable=False),
    Column("classification", String(32), nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("extraction_status", String(32), nullable=False),
    Column("fragment_count", Integer, nullable=False, server_default=text("0")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("btrim(object_key) <> ''", name="object_key_nonblank"),
    CheckConstraint("btrim(filename) <> ''", name="filename_nonblank"),
    CheckConstraint("btrim(media_type) <> ''", name="media_type_nonblank"),
    CheckConstraint(
        "classification IN ('internal', 'confidential', 'restricted')",
        name="classification_allowed",
    ),
    CheckConstraint(
        "extraction_status IN ('extracted', 'ocr_required')",
        name="extraction_status_allowed",
    ),
    CheckConstraint("size_bytes > 0", name="size_positive"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
    CheckConstraint("fragment_count >= 0", name="fragment_count_nonnegative"),
    CheckConstraint(
        "(extraction_status = 'extracted' AND fragment_count > 0) OR "
        "(extraction_status = 'ocr_required' AND fragment_count = 0)",
        name="extraction_fragment_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_documents_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "uploaded_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_documents_tenant_uploader",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_documents_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_documents_tenant_project_id"),
    UniqueConstraint("tenant_id", "object_key", name="uq_documents_tenant_object_key"),
    Index("ix_documents_tenant_project_created", "tenant_id", "project_id", "created_at", "id"),
    schema=PROJECT_SCHEMA,
)

external_file_references = Table(
    "external_file_references",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("uploaded_by_user_id", Uuid),
    Column("source_system", String(64), nullable=False),
    Column("source_id", String(128), nullable=False),
    Column("source_hash", String(64), nullable=False),
    Column("object_key", String(1024), nullable=False),
    Column("source_url", String(1024)),
    Column("filename", String(512), nullable=False),
    Column("media_type", String(128), nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("classification", String(32), nullable=False),
    Column("stage_code", String(64)),
    Column("task_source_id", String(128)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("btrim(source_system) <> ''", name="source_system_nonblank"),
    CheckConstraint("btrim(source_id) <> ''", name="source_id_nonblank"),
    CheckConstraint("source_hash ~ '^[0-9a-f]{64}$'", name="source_hash_hex"),
    CheckConstraint("btrim(object_key) <> ''", name="object_key_nonblank"),
    CheckConstraint("btrim(filename) <> ''", name="filename_nonblank"),
    CheckConstraint("btrim(media_type) <> ''", name="media_type_nonblank"),
    CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
    CheckConstraint(
        "classification IN ('internal', 'confidential', 'restricted')",
        name="classification_allowed",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_external_file_references_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "uploaded_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_external_file_references_tenant_uploader",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_external_file_references_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "source_system",
        "source_id",
        name="uq_external_file_references_tenant_source",
    ),
    Index(
        "ix_external_file_references_tenant_project_created",
        "tenant_id",
        "project_id",
        "created_at",
        "id",
    ),
    schema=PROJECT_SCHEMA,
)

document_fragments = Table(
    "document_fragments",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("document_id", Uuid, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("locator", String(256), nullable=False),
    Column("text", Text, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("ordinal > 0", name="ordinal_positive"),
    CheckConstraint("btrim(locator) <> ''", name="locator_nonblank"),
    CheckConstraint("btrim(text) <> ''", name="text_nonblank"),
    CheckConstraint("char_length(text) <= 20000", name="text_size"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "document_id"],
        [
            f"{PROJECT_SCHEMA}.documents.tenant_id",
            f"{PROJECT_SCHEMA}.documents.project_id",
            f"{PROJECT_SCHEMA}.documents.id",
        ],
        name="fk_document_fragments_tenant_project_document",
        ondelete="CASCADE",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_document_fragments_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "document_id",
        "ordinal",
        name="uq_document_fragments_tenant_document_ordinal",
    ),
    Index(
        "ix_document_fragments_tenant_project_document",
        "tenant_id",
        "project_id",
        "document_id",
        "ordinal",
    ),
    schema=PROJECT_SCHEMA,
)

specifications = Table(
    "specifications",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("code", String(64), nullable=False),
    Column("title", String(512), nullable=False),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("content", json_type, nullable=False, server_default=text("'{}'::jsonb")),
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
    CheckConstraint("btrim(code) <> ''", name="code_nonblank"),
    CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
    CheckConstraint("version > 0", name="version_positive"),
    CheckConstraint("jsonb_typeof(content) = 'object'", name="content_object"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_specifications_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_specifications_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_specifications_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "id",
        name="uq_specifications_tenant_project_id",
    ),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "code",
        "version",
        name="uq_specifications_tenant_project_code_version",
    ),
    Index(
        "ix_specifications_tenant_project_updated",
        "tenant_id",
        "project_id",
        "updated_at",
        "id",
    ),
    schema=PRODUCT_SCHEMA,
)

development_boms = Table(
    "development_boms",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("specification_id", Uuid),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("bom_type", String(32), nullable=False),
    Column("code", String(64), nullable=False),
    Column("name", String(256), nullable=False),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("notes", Text),
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
    CheckConstraint("bom_type IN ('ebom', 'prototype', 'cost')", name="type_allowed"),
    CheckConstraint("btrim(code) <> ''", name="code_nonblank"),
    CheckConstraint("btrim(name) <> ''", name="name_nonblank"),
    CheckConstraint("version > 0", name="version_positive"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_development_boms_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "specification_id"],
        [
            f"{PRODUCT_SCHEMA}.specifications.tenant_id",
            f"{PRODUCT_SCHEMA}.specifications.project_id",
            f"{PRODUCT_SCHEMA}.specifications.id",
        ],
        name="fk_development_boms_tenant_project_specification",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_development_boms_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_development_boms_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "id",
        name="uq_development_boms_tenant_project_id",
    ),
    UniqueConstraint(
        "tenant_id",
        "id",
        "bom_type",
        name="uq_development_boms_tenant_id_type",
    ),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "code",
        "version",
        name="uq_development_boms_tenant_project_code_version",
    ),
    Index(
        "ix_development_boms_tenant_project_type",
        "tenant_id",
        "project_id",
        "bom_type",
        "updated_at",
        "id",
    ),
    schema=PRODUCT_SCHEMA,
)

development_bom_items = Table(
    "development_bom_items",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("bom_id", Uuid, nullable=False),
    Column("parent_item_id", Uuid),
    Column("line_number", Integer, nullable=False),
    Column("part_number", String(128), nullable=False),
    Column("description", String(512), nullable=False),
    Column("quantity", Numeric(18, 6), nullable=False),
    Column("unit", String(32), nullable=False),
    Column("material_reference", String(256)),
    Column("attributes", json_type, nullable=False, server_default=text("'{}'::jsonb")),
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
    CheckConstraint("line_number > 0", name="line_number_positive"),
    CheckConstraint("btrim(part_number) <> ''", name="part_number_nonblank"),
    CheckConstraint("btrim(description) <> ''", name="description_nonblank"),
    CheckConstraint("quantity > 0", name="quantity_positive"),
    CheckConstraint("btrim(unit) <> ''", name="unit_nonblank"),
    CheckConstraint("parent_item_id IS NULL OR parent_item_id <> id", name="parent_not_self"),
    CheckConstraint("jsonb_typeof(attributes) = 'object'", name="attributes_object"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "bom_id"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.project_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
        ],
        name="fk_development_bom_items_tenant_project_bom",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "bom_id", "parent_item_id"],
        [
            f"{PRODUCT_SCHEMA}.development_bom_items.tenant_id",
            f"{PRODUCT_SCHEMA}.development_bom_items.bom_id",
            f"{PRODUCT_SCHEMA}.development_bom_items.id",
        ],
        name="fk_development_bom_items_tenant_bom_parent",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_development_bom_items_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "bom_id",
        "id",
        name="uq_development_bom_items_tenant_bom_id",
    ),
    UniqueConstraint(
        "tenant_id",
        "bom_id",
        "line_number",
        name="uq_development_bom_items_tenant_bom_line",
    ),
    Index(
        "ix_development_bom_items_tenant_bom_parent",
        "tenant_id",
        "bom_id",
        "parent_item_id",
        "line_number",
    ),
    schema=PRODUCT_SCHEMA,
)

erp_bom_references = Table(
    "erp_bom_references",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("bom_id", Uuid),
    Column("reference_type", String(32), nullable=False),
    Column("source_system", String(64), nullable=False),
    Column("external_id", String(256), nullable=False),
    Column("external_url", String(2048)),
    Column("metadata", json_type, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint(
        "reference_type IN ('mbom', 'routing', 'production_version')",
        name="type_allowed",
    ),
    CheckConstraint("btrim(source_system) <> ''", name="source_system_nonblank"),
    CheckConstraint("btrim(external_id) <> ''", name="external_id_nonblank"),
    CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_erp_bom_references_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "bom_id"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.project_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
        ],
        name="fk_erp_bom_references_tenant_project_bom",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_erp_bom_references_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "source_system",
        "reference_type",
        "external_id",
        name="uq_erp_bom_references_tenant_source_type_external",
    ),
    Index(
        "ix_erp_bom_references_tenant_project_type",
        "tenant_id",
        "project_id",
        "reference_type",
        "id",
    ),
    schema=PRODUCT_SCHEMA,
)

cost_bom_items = Table(
    "cost_bom_items",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("bom_id", Uuid, nullable=False),
    Column("bom_type", String(32), nullable=False),
    Column("bom_item_id", Uuid, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("unit_cost", Numeric(18, 4), nullable=False),
    Column("cost_category", String(64)),
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
    CheckConstraint("bom_type = 'cost'", name="cost_bom_only"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_like"),
    CheckConstraint("unit_cost >= 0", name="unit_cost_nonnegative"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "bom_id"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.project_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
        ],
        name="fk_cost_bom_items_tenant_project_bom",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "bom_id", "bom_type"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
            f"{PRODUCT_SCHEMA}.development_boms.bom_type",
        ],
        name="fk_cost_bom_items_tenant_bom_type",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "bom_id", "bom_item_id"],
        [
            f"{PRODUCT_SCHEMA}.development_bom_items.tenant_id",
            f"{PRODUCT_SCHEMA}.development_bom_items.bom_id",
            f"{PRODUCT_SCHEMA}.development_bom_items.id",
        ],
        name="fk_cost_bom_items_tenant_bom_item",
        ondelete="CASCADE",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_cost_bom_items_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "bom_item_id",
        name="uq_cost_bom_items_tenant_bom_item",
    ),
    Index(
        "ix_cost_bom_items_tenant_project_bom",
        "tenant_id",
        "project_id",
        "bom_id",
        "bom_item_id",
    ),
    schema=COST_SCHEMA,
)

build_batches = Table(
    "build_batches",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("workflow_id", Uuid, nullable=False),
    Column("stage_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("phase", String(8), nullable=False),
    Column("code", String(64), nullable=False),
    Column("planned_quantity", Integer, nullable=False),
    Column("completed_quantity", Integer, nullable=False, server_default=text("0")),
    Column("status", String(32), nullable=False, server_default=text("'planned'")),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("notes", Text),
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
    CheckConstraint("phase IN ('evt', 'dvt', 'pvt')", name="phase_allowed"),
    CheckConstraint("btrim(code) <> ''", name="code_nonblank"),
    CheckConstraint(
        "planned_quantity > 0 AND completed_quantity BETWEEN 0 AND planned_quantity",
        name="quantities_valid",
    ),
    CheckConstraint(
        "status IN ('planned', 'in_progress', 'completed', 'cancelled')", name="status_allowed"
    ),
    CheckConstraint(
        "(status = 'planned' AND started_at IS NULL AND completed_at IS NULL) OR "
        "(status = 'in_progress' AND started_at IS NOT NULL AND completed_at IS NULL) OR "
        "(status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
        "AND completed_quantity > 0) OR (status = 'cancelled' AND completed_at IS NULL)",
        name="lifecycle_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "project_id"],
        [
            f"{PROJECT_SCHEMA}.projects.tenant_id",
            f"{PROJECT_SCHEMA}.projects.workflow_id",
            f"{PROJECT_SCHEMA}.projects.id",
        ],
        name="fk_build_batches_tenant_workflow_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "stage_id"],
        [
            f"{PROJECT_SCHEMA}.stages.tenant_id",
            f"{PROJECT_SCHEMA}.stages.workflow_id",
            f"{PROJECT_SCHEMA}.stages.id",
        ],
        name="fk_build_batches_tenant_workflow_stage",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_build_batches_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_build_batches_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_build_batches_tenant_project_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "phase",
        "code",
        name="uq_build_batches_tenant_project_phase_code",
    ),
    Index(
        "ix_build_batches_tenant_project_phase_status", "tenant_id", "project_id", "phase", "status"
    ),
    schema=PRODUCT_SCHEMA,
)

samples = Table(
    "samples",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("build_batch_id", Uuid, nullable=False),
    Column("parent_sample_id", Uuid),
    Column("prototype_bom_id", Uuid),
    Column("prototype_bom_type", String(32), nullable=False, server_default=text("'prototype'")),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("serial_number", String(128), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'built'")),
    Column(
        "built_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column("notes", Text),
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
    CheckConstraint("btrim(serial_number) <> ''", name="serial_nonblank"),
    CheckConstraint(
        "status IN ('built', 'testing', 'accepted', 'scrapped')", name="status_allowed"
    ),
    CheckConstraint("parent_sample_id IS NULL OR parent_sample_id <> id", name="parent_not_self"),
    CheckConstraint("prototype_bom_type = 'prototype'", name="prototype_bom_only"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "build_batch_id"],
        [
            f"{PRODUCT_SCHEMA}.build_batches.tenant_id",
            f"{PRODUCT_SCHEMA}.build_batches.project_id",
            f"{PRODUCT_SCHEMA}.build_batches.id",
        ],
        name="fk_samples_tenant_project_build",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "parent_sample_id"],
        [
            f"{PRODUCT_SCHEMA}.samples.tenant_id",
            f"{PRODUCT_SCHEMA}.samples.project_id",
            f"{PRODUCT_SCHEMA}.samples.id",
        ],
        name="fk_samples_tenant_project_parent",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "prototype_bom_id"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.project_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
        ],
        name="fk_samples_tenant_project_bom",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "prototype_bom_id", "prototype_bom_type"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
            f"{PRODUCT_SCHEMA}.development_boms.bom_type",
        ],
        name="fk_samples_tenant_bom_type",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_samples_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_samples_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_samples_tenant_project_id"),
    UniqueConstraint("tenant_id", "serial_number", name="uq_samples_tenant_serial"),
    Index("ix_samples_tenant_project_build", "tenant_id", "project_id", "build_batch_id", "id"),
    schema=PRODUCT_SCHEMA,
)

sample_signoffs = Table(
    "sample_signoffs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("requested_by_user_id", Uuid, nullable=False),
    Column("responded_by_user_id", Uuid),
    Column("phase", String(8), nullable=False),
    Column("title", String(512), nullable=False),
    Column("signoff_type", String(32), nullable=False),
    Column("audience", String(32), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'pending'")),
    Column("due_date", Date),
    Column("response_note", Text),
    Column("responded_at", DateTime(timezone=True)),
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
    CheckConstraint("phase IN ('evt', 'dvt', 'pvt')", name="phase_allowed"),
    CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
    CheckConstraint(
        "signoff_type IN ('evt_sample', 'dvt_sample', 'pvt_sample', "
        "'golden_sample', 'first_article', 'other')",
        name="type_allowed",
    ),
    CheckConstraint("audience IN ('internal', 'supplier', 'customer')", name="audience_allowed"),
    CheckConstraint(
        "status IN ('pending', 'approved', 'rejected', 'waived')", name="status_allowed"
    ),
    CheckConstraint(
        "(status = 'pending' AND responded_by_user_id IS NULL AND responded_at IS NULL) OR "
        "(status <> 'pending' AND responded_by_user_id IS NOT NULL AND responded_at IS NOT NULL)",
        name="response_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_sample_signoffs_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "requested_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_sample_signoffs_tenant_requester",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "responded_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_sample_signoffs_tenant_responder",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_sample_signoffs_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_sample_signoffs_tenant_project_id"),
    Index(
        "ix_sample_signoffs_tenant_project_phase_status",
        "tenant_id",
        "project_id",
        "phase",
        "status",
    ),
    schema=QUALITY_SCHEMA,
)

sample_signoff_samples = Table(
    "sample_signoff_samples",
    metadata,
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("signoff_id", Uuid, nullable=False),
    Column("sample_id", Uuid, nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "signoff_id"],
        [
            f"{QUALITY_SCHEMA}.sample_signoffs.tenant_id",
            f"{QUALITY_SCHEMA}.sample_signoffs.project_id",
            f"{QUALITY_SCHEMA}.sample_signoffs.id",
        ],
        name="fk_sample_signoff_samples_tenant_project_signoff",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "sample_id"],
        [
            f"{PRODUCT_SCHEMA}.samples.tenant_id",
            f"{PRODUCT_SCHEMA}.samples.project_id",
            f"{PRODUCT_SCHEMA}.samples.id",
        ],
        name="fk_sample_signoff_samples_tenant_project_sample",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id",
        "signoff_id",
        "sample_id",
        name="uq_sample_signoff_samples_tenant_signoff_sample",
    ),
    Index(
        "ix_sample_signoff_samples_tenant_project_sample", "tenant_id", "project_id", "sample_id"
    ),
    schema=QUALITY_SCHEMA,
)

test_plans = Table(
    "test_plans",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("workflow_id", Uuid, nullable=False),
    Column("stage_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("phase", String(8), nullable=False),
    Column("title", String(512), nullable=False),
    Column("scope", Text),
    Column("sample_size", Integer, nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'draft'")),
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
    CheckConstraint("phase IN ('evt', 'dvt', 'pvt')", name="phase_allowed"),
    CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
    CheckConstraint("sample_size > 0", name="sample_size_positive"),
    CheckConstraint("status IN ('draft', 'active', 'completed')", name="status_allowed"),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "project_id"],
        [
            f"{PROJECT_SCHEMA}.projects.tenant_id",
            f"{PROJECT_SCHEMA}.projects.workflow_id",
            f"{PROJECT_SCHEMA}.projects.id",
        ],
        name="fk_test_plans_tenant_workflow_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "stage_id"],
        [
            f"{PROJECT_SCHEMA}.stages.tenant_id",
            f"{PROJECT_SCHEMA}.stages.workflow_id",
            f"{PROJECT_SCHEMA}.stages.id",
        ],
        name="fk_test_plans_tenant_workflow_stage",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_test_plans_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_test_plans_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_test_plans_tenant_project_id"),
    Index(
        "ix_test_plans_tenant_project_phase_status", "tenant_id", "project_id", "phase", "status"
    ),
    schema=QUALITY_SCHEMA,
)

test_cases = Table(
    "test_cases",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("plan_id", Uuid, nullable=False),
    Column("related_issue_id", Uuid),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("title", String(512), nullable=False),
    Column("category", String(64), nullable=False),
    Column("acceptance_criteria", Text, nullable=False),
    Column("method", Text),
    Column("severity", String(16), nullable=False, server_default=text("'major'")),
    Column("status", String(32), nullable=False, server_default=text("'planned'")),
    Column("result_notes", Text),
    Column("executed_by_user_id", Uuid),
    Column("executed_at", DateTime(timezone=True)),
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
        "btrim(title) <> '' AND btrim(category) <> '' AND btrim(acceptance_criteria) <> ''",
        name="required_text_nonblank",
    ),
    CheckConstraint("severity IN ('minor', 'major', 'critical')", name="severity_allowed"),
    CheckConstraint(
        "status IN ('planned', 'passed', 'failed', 'blocked', 'waived')", name="status_allowed"
    ),
    CheckConstraint(
        "(status = 'planned' AND executed_by_user_id IS NULL AND executed_at IS NULL) OR "
        "(status <> 'planned' AND executed_by_user_id IS NOT NULL "
        "AND executed_at IS NOT NULL)",
        name="execution_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "plan_id"],
        [
            f"{QUALITY_SCHEMA}.test_plans.tenant_id",
            f"{QUALITY_SCHEMA}.test_plans.project_id",
            f"{QUALITY_SCHEMA}.test_plans.id",
        ],
        name="fk_test_cases_tenant_project_plan",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "related_issue_id"],
        [
            f"{PROJECT_SCHEMA}.issues.tenant_id",
            f"{PROJECT_SCHEMA}.issues.project_id",
            f"{PROJECT_SCHEMA}.issues.id",
        ],
        name="fk_test_cases_tenant_project_issue",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_test_cases_tenant_creator",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "executed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_test_cases_tenant_executor",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_test_cases_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_test_cases_tenant_project_id"),
    Index(
        "ix_test_cases_tenant_project_plan_status", "tenant_id", "project_id", "plan_id", "status"
    ),
    schema=QUALITY_SCHEMA,
)

test_case_samples = Table(
    "test_case_samples",
    metadata,
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("test_case_id", Uuid, nullable=False),
    Column("sample_id", Uuid, nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "test_case_id"],
        [
            f"{QUALITY_SCHEMA}.test_cases.tenant_id",
            f"{QUALITY_SCHEMA}.test_cases.project_id",
            f"{QUALITY_SCHEMA}.test_cases.id",
        ],
        name="fk_test_case_samples_tenant_project_case",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "sample_id"],
        [
            f"{PRODUCT_SCHEMA}.samples.tenant_id",
            f"{PRODUCT_SCHEMA}.samples.project_id",
            f"{PRODUCT_SCHEMA}.samples.id",
        ],
        name="fk_test_case_samples_tenant_project_sample",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id", "test_case_id", "sample_id", name="uq_test_case_samples_tenant_case_sample"
    ),
    Index("ix_test_case_samples_tenant_project_sample", "tenant_id", "project_id", "sample_id"),
    schema=QUALITY_SCHEMA,
)

test_reports = Table(
    "test_reports",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("plan_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("reviewed_by_user_id", Uuid),
    Column("report_number", String(128), nullable=False),
    Column("title", String(512), nullable=False),
    Column("result", String(32), nullable=False),
    Column("review_status", String(32), nullable=False, server_default=text("'pending'")),
    Column("summary", Text, nullable=False),
    Column("review_note", Text),
    Column("reviewed_at", DateTime(timezone=True)),
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
        "btrim(report_number) <> '' AND btrim(title) <> '' AND btrim(summary) <> ''",
        name="required_text_nonblank",
    ),
    CheckConstraint("result IN ('pass', 'fail', 'conditional')", name="result_allowed"),
    CheckConstraint(
        "review_status IN ('pending', 'approved', 'rejected')", name="review_status_allowed"
    ),
    CheckConstraint(
        "(review_status = 'pending' AND reviewed_by_user_id IS NULL "
        "AND reviewed_at IS NULL) OR (review_status <> 'pending' "
        "AND reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
        name="review_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "plan_id"],
        [
            f"{QUALITY_SCHEMA}.test_plans.tenant_id",
            f"{QUALITY_SCHEMA}.test_plans.project_id",
            f"{QUALITY_SCHEMA}.test_plans.id",
        ],
        name="fk_test_reports_tenant_project_plan",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_test_reports_tenant_creator",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "reviewed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_test_reports_tenant_reviewer",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_test_reports_tenant_id_id"),
    UniqueConstraint(
        "tenant_id", "project_id", "report_number", name="uq_test_reports_tenant_project_number"
    ),
    Index(
        "ix_test_reports_tenant_project_plan_review",
        "tenant_id",
        "project_id",
        "plan_id",
        "review_status",
    ),
    schema=QUALITY_SCHEMA,
)

certifications = Table(
    "certifications",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("owner_user_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("certificate_type", String(48), nullable=False),
    Column("certificate_number", String(256)),
    Column("issuing_body", String(256)),
    Column("target_markets", json_type, nullable=False, server_default=text("'[]'::jsonb")),
    Column("status", String(32), nullable=False, server_default=text("'draft'")),
    Column("is_required", Boolean, nullable=False, server_default=text("false")),
    Column("valid_from", Date),
    Column("valid_until", Date),
    Column("evidence_reference", Text),
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
        "certificate_type IN ('un38_3', 'msds', 'battery_safety', 'product_safety', "
        "'component_safety', 'market_access', 'regulatory_compliance')",
        name="type_allowed",
    ),
    CheckConstraint("status IN ('draft', 'valid', 'expired', 'revoked')", name="status_allowed"),
    CheckConstraint("jsonb_typeof(target_markets) = 'array'", name="target_markets_array"),
    CheckConstraint(
        "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
        name="validity_order",
    ),
    CheckConstraint(
        "status <> 'valid' OR (certificate_number IS NOT NULL "
        "AND btrim(certificate_number) <> '' AND valid_until IS NOT NULL)",
        name="valid_has_identity_and_expiry",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_certifications_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "owner_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_certifications_tenant_owner",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_certifications_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_certifications_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_certifications_tenant_project_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "certificate_type",
        "certificate_number",
        name="uq_certifications_tenant_project_type_number",
    ),
    Index(
        "ix_certifications_tenant_project_status_expiry",
        "tenant_id",
        "project_id",
        "status",
        "valid_until",
    ),
    schema=QUALITY_SCHEMA,
)

certification_expiry_alerts = Table(
    "certification_expiry_alerts",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("certification_id", Uuid, nullable=False),
    Column("valid_until", Date, nullable=False),
    Column("lead_days", Integer, nullable=False),
    Column("recipient_user_id", Uuid, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("lead_days IN (0, 30, 90)", name="lead_days_allowed"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "certification_id"],
        [
            f"{QUALITY_SCHEMA}.certifications.tenant_id",
            f"{QUALITY_SCHEMA}.certifications.project_id",
            f"{QUALITY_SCHEMA}.certifications.id",
        ],
        name="fk_cert_alerts_tenant_project_certification",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "recipient_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_cert_alerts_tenant_recipient",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_id",
        "certification_id",
        "valid_until",
        "lead_days",
        name="uq_cert_alerts_tenant_cert_expiry_lead",
    ),
    Index("ix_cert_alerts_tenant_project_created", "tenant_id", "project_id", "created_at", "id"),
    schema=QUALITY_SCHEMA,
)

complaints = Table(
    "complaints",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("customer_id", Uuid),
    Column("reported_by_user_id", Uuid, nullable=False),
    Column("owner_user_id", Uuid, nullable=False),
    Column("closed_by_user_id", Uuid),
    Column("code", String(64), nullable=False),
    Column("title", String(512), nullable=False),
    Column("description", Text, nullable=False),
    Column("source", String(32), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'open'")),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("reported_at", DateTime(timezone=True), nullable=False),
    Column("customer_reference", String(128)),
    Column("affected_scope", Text),
    Column("document_refs", json_type, nullable=False, server_default=text("'[]'::jsonb")),
    Column("resolution_summary", Text),
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
        "source IN ('customer', 'field', 'rma', 'internal')",
        name="source_allowed",
    ),
    CheckConstraint(
        "severity IN ('critical', 'high', 'medium', 'low')",
        name="severity_allowed",
    ),
    CheckConstraint(
        "status IN ('open', 'triaged', 'investigating', 'resolved', 'closed')",
        name="status_allowed",
    ),
    CheckConstraint(
        "btrim(code) <> '' AND btrim(title) <> '' AND btrim(description) <> ''",
        name="required_text_nonblank",
    ),
    CheckConstraint("reported_at >= occurred_at", name="reported_after_occurrence"),
    CheckConstraint("jsonb_typeof(document_refs) = 'array'", name="document_refs_array"),
    CheckConstraint(
        "(status IN ('open', 'triaged', 'investigating') AND resolution_summary IS NULL) OR "
        "(status IN ('resolved', 'closed') AND resolution_summary IS NOT NULL "
        "AND btrim(resolution_summary) <> '')",
        name="resolution_consistent",
    ),
    CheckConstraint(
        "(status = 'closed' AND closed_by_user_id IS NOT NULL AND closed_at IS NOT NULL) OR "
        "(status <> 'closed' AND closed_by_user_id IS NULL AND closed_at IS NULL)",
        name="closure_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_complaints_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "customer_id"],
        [f"{CORE_SCHEMA}.customers.tenant_id", f"{CORE_SCHEMA}.customers.id"],
        name="fk_complaints_tenant_customer",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "reported_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_complaints_tenant_reporter",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "owner_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_complaints_tenant_owner",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "closed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_complaints_tenant_closer",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_complaints_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_complaints_tenant_project_id"),
    UniqueConstraint("tenant_id", "code", name="uq_complaints_tenant_code"),
    Index(
        "ix_complaints_tenant_project_status",
        "tenant_id",
        "project_id",
        "status",
        "severity",
        "updated_at",
    ),
    schema=QUALITY_SCHEMA,
)

nonconformance_reports = Table(
    "nonconformance_reports",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("complaint_id", Uuid, nullable=False),
    Column("owner_user_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("preventive_disposition_approved_by_user_id", Uuid),
    Column("closed_by_user_id", Uuid),
    Column("code", String(64), nullable=False),
    Column("nonconformity", Text, nullable=False),
    Column("requirement_reference", Text, nullable=False),
    Column("severity", String(16), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'open'")),
    Column("target_date", Date, nullable=False),
    Column("containment_action", Text),
    Column("containment_completed_at", DateTime(timezone=True)),
    Column("affected_quantity", Integer),
    Column("affected_scope", Text),
    Column("preventive_not_applicable_reason", Text),
    Column("preventive_disposition_approved_at", DateTime(timezone=True)),
    Column("effectiveness_criteria", Text),
    Column("observation_due_at", DateTime(timezone=True)),
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
        "severity IN ('critical', 'high', 'medium', 'low')",
        name="severity_allowed",
    ),
    CheckConstraint(
        "status IN ('open', 'containment', 'root_cause', 'action', 'verification', 'closed')",
        name="status_allowed",
    ),
    CheckConstraint(
        "btrim(code) <> '' AND btrim(nonconformity) <> '' AND btrim(requirement_reference) <> ''",
        name="required_text_nonblank",
    ),
    CheckConstraint(
        "affected_quantity IS NULL OR affected_quantity >= 0",
        name="affected_quantity_nonnegative",
    ),
    CheckConstraint(
        "(containment_action IS NULL AND containment_completed_at IS NULL) OR "
        "(containment_action IS NOT NULL AND btrim(containment_action) <> '' "
        "AND containment_completed_at IS NOT NULL)",
        name="containment_consistent",
    ),
    CheckConstraint(
        "(preventive_not_applicable_reason IS NULL "
        "AND preventive_disposition_approved_by_user_id IS NULL "
        "AND preventive_disposition_approved_at IS NULL) OR "
        "(preventive_not_applicable_reason IS NOT NULL "
        "AND btrim(preventive_not_applicable_reason) <> '' "
        "AND preventive_disposition_approved_by_user_id IS NOT NULL "
        "AND preventive_disposition_approved_at IS NOT NULL)",
        name="preventive_disposition_consistent",
    ),
    CheckConstraint(
        "(effectiveness_criteria IS NULL AND observation_due_at IS NULL) OR "
        "(effectiveness_criteria IS NOT NULL AND btrim(effectiveness_criteria) <> '' "
        "AND observation_due_at IS NOT NULL)",
        name="effectiveness_plan_consistent",
    ),
    CheckConstraint(
        "(status = 'closed' AND closed_by_user_id IS NOT NULL AND closed_at IS NOT NULL) OR "
        "(status <> 'closed' AND closed_by_user_id IS NULL AND closed_at IS NULL)",
        name="closure_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "complaint_id"],
        [
            f"{QUALITY_SCHEMA}.complaints.tenant_id",
            f"{QUALITY_SCHEMA}.complaints.project_id",
            f"{QUALITY_SCHEMA}.complaints.id",
        ],
        name="fk_ncrs_tenant_project_complaint",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "owner_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_ncrs_tenant_owner",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_ncrs_tenant_creator",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "preventive_disposition_approved_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_ncrs_tenant_preventive_approver",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "closed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_ncrs_tenant_closer",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_ncrs_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_ncrs_tenant_project_id"),
    UniqueConstraint("tenant_id", "code", name="uq_ncrs_tenant_code"),
    Index(
        "ix_ncrs_tenant_project_status",
        "tenant_id",
        "project_id",
        "status",
        "severity",
        "target_date",
    ),
    schema=QUALITY_SCHEMA,
)

root_cause_analyses = Table(
    "root_cause_analyses",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("ncr_id", Uuid, nullable=False),
    Column("analyst_user_id", Uuid, nullable=False),
    Column("approved_by_user_id", Uuid),
    Column("version", Integer, nullable=False),
    Column("method", String(32), nullable=False),
    Column("analysis", Text, nullable=False),
    Column("root_cause", Text, nullable=False),
    Column("evidence_refs", json_type, nullable=False, server_default=text("'[]'::jsonb")),
    Column("status", String(32), nullable=False, server_default=text("'draft'")),
    Column("approved_at", DateTime(timezone=True)),
    Column("superseded_at", DateTime(timezone=True)),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("version > 0", name="version_positive"),
    CheckConstraint(
        "method IN ('5why', 'fishbone', '8d', 'other')",
        name="method_allowed",
    ),
    CheckConstraint(
        "status IN ('draft', 'approved', 'superseded')",
        name="status_allowed",
    ),
    CheckConstraint(
        "btrim(analysis) <> '' AND btrim(root_cause) <> ''",
        name="required_text_nonblank",
    ),
    CheckConstraint("jsonb_typeof(evidence_refs) = 'array'", name="evidence_refs_array"),
    CheckConstraint(
        "approved_by_user_id IS NULL OR approved_by_user_id <> analyst_user_id",
        name="four_eyes",
    ),
    CheckConstraint(
        "(status = 'draft' AND approved_by_user_id IS NULL AND approved_at IS NULL "
        "AND superseded_at IS NULL) OR "
        "(status = 'approved' AND approved_by_user_id IS NOT NULL "
        "AND approved_at IS NOT NULL AND superseded_at IS NULL) OR "
        "(status = 'superseded' AND approved_by_user_id IS NOT NULL "
        "AND approved_at IS NOT NULL AND superseded_at IS NOT NULL)",
        name="lifecycle_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "ncr_id"],
        [
            f"{QUALITY_SCHEMA}.nonconformance_reports.tenant_id",
            f"{QUALITY_SCHEMA}.nonconformance_reports.project_id",
            f"{QUALITY_SCHEMA}.nonconformance_reports.id",
        ],
        name="fk_root_causes_tenant_project_ncr",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "analyst_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_root_causes_tenant_analyst",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "approved_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_root_causes_tenant_approver",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_root_causes_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_root_causes_tenant_project_id"),
    UniqueConstraint(
        "tenant_id",
        "ncr_id",
        "version",
        name="uq_root_causes_tenant_ncr_version",
    ),
    Index(
        "ix_root_causes_tenant_ncr_status",
        "tenant_id",
        "ncr_id",
        "status",
        "version",
    ),
    schema=QUALITY_SCHEMA,
)

capa_actions = Table(
    "capa_actions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("ncr_id", Uuid, nullable=False),
    Column("owner_user_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("action_type", String(32), nullable=False),
    Column("description", Text, nullable=False),
    Column("due_date", Date, nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'planned'")),
    Column("completion_summary", Text),
    Column("evidence_refs", json_type, nullable=False, server_default=text("'[]'::jsonb")),
    Column("started_at", DateTime(timezone=True)),
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
        "action_type IN ('corrective', 'preventive')",
        name="type_allowed",
    ),
    CheckConstraint(
        "status IN ('planned', 'in_progress', 'completed')",
        name="status_allowed",
    ),
    CheckConstraint("btrim(description) <> ''", name="description_nonblank"),
    CheckConstraint("jsonb_typeof(evidence_refs) = 'array'", name="evidence_refs_array"),
    CheckConstraint(
        "(status = 'planned' AND started_at IS NULL AND completed_at IS NULL "
        "AND completion_summary IS NULL) OR "
        "(status = 'in_progress' AND started_at IS NOT NULL AND completed_at IS NULL "
        "AND completion_summary IS NULL) OR "
        "(status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
        "AND completion_summary IS NOT NULL AND btrim(completion_summary) <> '' "
        "AND jsonb_array_length(evidence_refs) > 0)",
        name="lifecycle_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "ncr_id"],
        [
            f"{QUALITY_SCHEMA}.nonconformance_reports.tenant_id",
            f"{QUALITY_SCHEMA}.nonconformance_reports.project_id",
            f"{QUALITY_SCHEMA}.nonconformance_reports.id",
        ],
        name="fk_capa_actions_tenant_project_ncr",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "owner_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_capa_actions_tenant_owner",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_capa_actions_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_capa_actions_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_capa_actions_tenant_project_id"),
    Index(
        "ix_capa_actions_tenant_ncr_status",
        "tenant_id",
        "ncr_id",
        "status",
        "due_date",
    ),
    schema=QUALITY_SCHEMA,
)

effectiveness_reviews = Table(
    "effectiveness_reviews",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("ncr_id", Uuid, nullable=False),
    Column("reviewer_user_id", Uuid, nullable=False),
    Column("review_number", Integer, nullable=False),
    Column("criteria", Text, nullable=False),
    Column("observation_due_at", DateTime(timezone=True), nullable=False),
    Column("actual_result", Text, nullable=False),
    Column("result", String(32), nullable=False),
    Column("evidence_refs", json_type, nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("review_number > 0", name="review_number_positive"),
    CheckConstraint(
        "result IN ('effective', 'ineffective')",
        name="result_allowed",
    ),
    CheckConstraint(
        "btrim(criteria) <> '' AND btrim(actual_result) <> ''",
        name="required_text_nonblank",
    ),
    CheckConstraint(
        "jsonb_typeof(evidence_refs) = 'array' AND jsonb_array_length(evidence_refs) > 0",
        name="evidence_refs_nonempty_array",
    ),
    CheckConstraint("reviewed_at >= observation_due_at", name="observation_completed"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "ncr_id"],
        [
            f"{QUALITY_SCHEMA}.nonconformance_reports.tenant_id",
            f"{QUALITY_SCHEMA}.nonconformance_reports.project_id",
            f"{QUALITY_SCHEMA}.nonconformance_reports.id",
        ],
        name="fk_effectiveness_reviews_tenant_project_ncr",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "reviewer_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_effectiveness_reviews_tenant_reviewer",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_effectiveness_reviews_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "id",
        name="uq_effectiveness_reviews_tenant_project_id",
    ),
    UniqueConstraint(
        "tenant_id",
        "ncr_id",
        "review_number",
        name="uq_effectiveness_reviews_tenant_ncr_number",
    ),
    Index(
        "ix_effectiveness_reviews_tenant_ncr_created",
        "tenant_id",
        "ncr_id",
        "review_number",
    ),
    schema=QUALITY_SCHEMA,
)

engineering_change_requests = Table(
    "engineering_change_requests",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("requested_by_user_id", Uuid, nullable=False),
    Column("analyzed_by_user_id", Uuid),
    Column("approved_by_user_id", Uuid),
    Column("approval_decision_id", Uuid),
    Column("code", String(64), nullable=False),
    Column("title", String(512), nullable=False),
    Column("reason", Text, nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'request'")),
    Column("impact_analysis", json_type),
    Column("approval_note", Text),
    Column("analyzed_at", DateTime(timezone=True)),
    Column("approved_at", DateTime(timezone=True)),
    Column("cancelled_at", DateTime(timezone=True)),
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
        "btrim(code) <> '' AND btrim(title) <> '' AND btrim(reason) <> ''",
        name="required_text_nonblank",
    ),
    CheckConstraint(
        "status IN ('request', 'impact_analysis', 'approval', 'approved', 'rejected', 'cancelled')",
        name="status_allowed",
    ),
    CheckConstraint(
        "impact_analysis IS NULL OR jsonb_typeof(impact_analysis) = 'object'", name="impact_object"
    ),
    CheckConstraint(
        "(status IN ('request', 'impact_analysis') AND approval_decision_id IS NULL "
        "AND approved_by_user_id IS NULL AND approved_at IS NULL) OR "
        "(status = 'approval' AND impact_analysis IS NOT NULL AND analyzed_by_user_id IS NOT NULL "
        "AND analyzed_at IS NOT NULL AND approval_decision_id IS NULL) OR "
        "(status IN ('approved', 'rejected') AND impact_analysis IS NOT NULL "
        "AND approval_decision_id IS NOT NULL AND approved_by_user_id IS NOT NULL "
        "AND approved_at IS NOT NULL) OR (status = 'cancelled' AND cancelled_at IS NOT NULL)",
        name="lifecycle_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_ecrs_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "requested_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_ecrs_tenant_requester",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "analyzed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_ecrs_tenant_analyzer",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "approved_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_ecrs_tenant_approver",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "approval_decision_id"],
        [f"{PROJECT_SCHEMA}.decisions.tenant_id", f"{PROJECT_SCHEMA}.decisions.id"],
        name="fk_ecrs_tenant_approval_decision",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_ecrs_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_ecrs_tenant_project_id"),
    UniqueConstraint("tenant_id", "project_id", "code", name="uq_ecrs_tenant_project_code"),
    Index("ix_ecrs_tenant_project_status", "tenant_id", "project_id", "status", "updated_at"),
    schema=PRODUCT_SCHEMA,
)

ecr_affected_boms = Table(
    "ecr_affected_boms",
    metadata,
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("ecr_id", Uuid, nullable=False),
    Column("bom_id", Uuid, nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "ecr_id"],
        [
            f"{PRODUCT_SCHEMA}.engineering_change_requests.tenant_id",
            f"{PRODUCT_SCHEMA}.engineering_change_requests.project_id",
            f"{PRODUCT_SCHEMA}.engineering_change_requests.id",
        ],
        name="fk_ecr_boms_tenant_project_ecr",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "bom_id"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.project_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
        ],
        name="fk_ecr_boms_tenant_project_bom",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "ecr_id", "bom_id", name="uq_ecr_boms_tenant_ecr_bom"),
    Index("ix_ecr_boms_tenant_project_bom", "tenant_id", "project_id", "bom_id"),
    schema=PRODUCT_SCHEMA,
)

engineering_change_notices = Table(
    "engineering_change_notices",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("ecr_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("effectivity_decided_by_user_id", Uuid),
    Column("effectivity_decision_id", Uuid),
    Column("released_bom_id", Uuid),
    Column("released_bom_type", String(32)),
    Column("code", String(64), nullable=False),
    Column("title", String(512), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'ecn'")),
    Column("implementation_plan", json_type, nullable=False, server_default=text("'{}'::jsonb")),
    Column("effectivity", json_type),
    Column("effectivity_decided_at", DateTime(timezone=True)),
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
    CheckConstraint("btrim(code) <> '' AND btrim(title) <> ''", name="required_text_nonblank"),
    CheckConstraint(
        "status IN ('ecn', 'effectivity_decision', 'erp_handoff', 'cancelled')",
        name="status_allowed",
    ),
    CheckConstraint(
        "jsonb_typeof(implementation_plan) = 'object'", name="implementation_plan_object"
    ),
    CheckConstraint(
        "effectivity IS NULL OR jsonb_typeof(effectivity) = 'object'", name="effectivity_object"
    ),
    CheckConstraint(
        "released_bom_type IS NULL OR released_bom_type = 'ebom'", name="released_bom_ebom_only"
    ),
    CheckConstraint(
        "(status IN ('ecn', 'effectivity_decision') AND effectivity_decision_id IS NULL) OR "
        "(status IN ('erp_handoff', 'cancelled') AND effectivity_decision_id IS NOT NULL "
        "AND effectivity_decided_by_user_id IS NOT NULL AND effectivity_decided_at IS NOT NULL)",
        name="lifecycle_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "ecr_id"],
        [
            f"{PRODUCT_SCHEMA}.engineering_change_requests.tenant_id",
            f"{PRODUCT_SCHEMA}.engineering_change_requests.project_id",
            f"{PRODUCT_SCHEMA}.engineering_change_requests.id",
        ],
        name="fk_ecns_tenant_project_ecr",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "released_bom_id"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.project_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
        ],
        name="fk_ecns_tenant_project_bom",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "released_bom_id", "released_bom_type"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
            f"{PRODUCT_SCHEMA}.development_boms.bom_type",
        ],
        name="fk_ecns_tenant_bom_type",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_ecns_tenant_creator",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "effectivity_decided_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_ecns_tenant_effectivity_decider",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "effectivity_decision_id"],
        [f"{PROJECT_SCHEMA}.decisions.tenant_id", f"{PROJECT_SCHEMA}.decisions.id"],
        name="fk_ecns_tenant_effectivity_decision",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_ecns_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_ecns_tenant_project_id"),
    UniqueConstraint("tenant_id", "ecr_id", name="uq_ecns_tenant_ecr"),
    UniqueConstraint("tenant_id", "project_id", "code", name="uq_ecns_tenant_project_code"),
    Index("ix_ecns_tenant_project_status", "tenant_id", "project_id", "status", "updated_at"),
    schema=PRODUCT_SCHEMA,
)

erp_handoffs = Table(
    "erp_handoffs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("ecn_id", Uuid, nullable=False),
    Column("source_bom_id", Uuid, nullable=False),
    Column("prepared_by_user_id", Uuid, nullable=False),
    Column("ready_by_user_id", Uuid),
    Column("status", String(32), nullable=False, server_default=text("'pending'")),
    Column("source_system", String(64), nullable=False, server_default=text("'pdos'")),
    Column("target_system", String(64), nullable=False),
    Column("source_bom_snapshot", json_type, nullable=False),
    Column("effectivity_snapshot", json_type, nullable=False),
    Column("ready_at", DateTime(timezone=True)),
    Column("external_reference", String(256)),
    Column("last_error", Text),
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
        "status IN ('pending', 'ready', 'queued', 'sent', 'confirmed', 'failed')",
        name="status_allowed",
    ),
    CheckConstraint(
        "btrim(source_system) <> '' AND btrim(target_system) <> ''", name="systems_nonblank"
    ),
    CheckConstraint(
        "jsonb_typeof(source_bom_snapshot) = 'object' "
        "AND jsonb_typeof(effectivity_snapshot) = 'object'",
        name="snapshots_object",
    ),
    CheckConstraint(
        "(status = 'pending' AND ready_at IS NULL AND ready_by_user_id IS NULL) OR "
        "(status <> 'pending' AND ready_at IS NOT NULL AND ready_by_user_id IS NOT NULL)",
        name="ready_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "ecn_id"],
        [
            f"{PRODUCT_SCHEMA}.engineering_change_notices.tenant_id",
            f"{PRODUCT_SCHEMA}.engineering_change_notices.project_id",
            f"{PRODUCT_SCHEMA}.engineering_change_notices.id",
        ],
        name="fk_erp_handoffs_tenant_project_ecn",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "source_bom_id"],
        [
            f"{PRODUCT_SCHEMA}.development_boms.tenant_id",
            f"{PRODUCT_SCHEMA}.development_boms.project_id",
            f"{PRODUCT_SCHEMA}.development_boms.id",
        ],
        name="fk_erp_handoffs_tenant_project_bom",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "prepared_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_erp_handoffs_tenant_preparer",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "ready_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_erp_handoffs_tenant_ready_actor",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_erp_handoffs_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_erp_handoffs_tenant_project_id"),
    UniqueConstraint("tenant_id", "ecn_id", name="uq_erp_handoffs_tenant_ecn"),
    Index(
        "ix_erp_handoffs_tenant_project_status", "tenant_id", "project_id", "status", "updated_at"
    ),
    schema=PRODUCT_SCHEMA,
)

deliverable_check_templates = Table(
    "deliverable_check_templates",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("asset_schema_version", Integer, nullable=False),
    Column("template_versions", json_type, nullable=False),
    Column("check_item_key", String(256), nullable=False),
    Column("deliverable_name", String(512), nullable=False),
    Column("requirement", Text, nullable=False),
    Column("source", String(64), nullable=False),
    Column("bindings", json_type, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
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
    CheckConstraint("asset_schema_version > 0", name="schema_version_positive"),
    CheckConstraint(
        "btrim(check_item_key) <> '' AND btrim(deliverable_name) <> '' "
        "AND btrim(requirement) <> '' AND btrim(source) <> ''",
        name="required_text_nonblank",
    ),
    CheckConstraint("jsonb_typeof(template_versions) = 'array'", name="versions_array"),
    CheckConstraint("jsonb_typeof(bindings) = 'array'", name="bindings_array"),
    CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_hex"),
    UniqueConstraint("tenant_id", "id", name="uq_check_templates_tenant_id_id"),
    UniqueConstraint("tenant_id", "check_item_key", name="uq_check_templates_tenant_item_key"),
    Index(
        "ix_check_templates_tenant_schema",
        "tenant_id",
        "asset_schema_version",
        "check_item_key",
    ),
    schema=PROJECT_SCHEMA,
)

project_check_items = Table(
    "project_check_items",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("workflow_id", Uuid, nullable=False),
    Column("stage_id", Uuid, nullable=False),
    Column("template_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("completed_by_user_id", Uuid),
    Column("binding_key", String(512), nullable=False),
    Column("phase_id", String(64), nullable=False),
    Column("phase_code", String(32), nullable=False),
    Column("phase_name", String(256), nullable=False),
    Column("task_id", String(256), nullable=False),
    Column("task_name", String(512), nullable=False),
    Column("deliverable_name", String(512), nullable=False),
    Column("requirement", Text, nullable=False),
    Column("is_gate", Boolean, nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'pending'")),
    Column("evidence_reference", String(2048)),
    Column("completion_note", Text),
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
        "btrim(binding_key) <> '' AND btrim(phase_id) <> '' AND btrim(phase_code) <> '' "
        "AND btrim(phase_name) <> '' AND btrim(task_id) <> '' AND btrim(task_name) <> '' "
        "AND btrim(deliverable_name) <> '' AND btrim(requirement) <> ''",
        name="required_text_nonblank",
    ),
    CheckConstraint("status IN ('pending', 'completed', 'not_applicable')", name="status_allowed"),
    CheckConstraint(
        "(status = 'pending' AND completed_by_user_id IS NULL AND completed_at IS NULL) OR "
        "(status IN ('completed', 'not_applicable') AND completed_by_user_id IS NOT NULL "
        "AND completed_at IS NOT NULL)",
        name="completion_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "project_id"],
        [
            f"{PROJECT_SCHEMA}.projects.tenant_id",
            f"{PROJECT_SCHEMA}.projects.workflow_id",
            f"{PROJECT_SCHEMA}.projects.id",
        ],
        name="fk_project_check_items_tenant_workflow_project",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id", "stage_id"],
        [
            f"{PROJECT_SCHEMA}.stages.tenant_id",
            f"{PROJECT_SCHEMA}.stages.workflow_id",
            f"{PROJECT_SCHEMA}.stages.id",
        ],
        name="fk_project_check_items_tenant_workflow_stage",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "template_id"],
        [
            f"{PROJECT_SCHEMA}.deliverable_check_templates.tenant_id",
            f"{PROJECT_SCHEMA}.deliverable_check_templates.id",
        ],
        name="fk_project_check_items_tenant_template",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_project_check_items_tenant_creator",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "completed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_project_check_items_tenant_completer",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_project_check_items_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "template_id",
        "binding_key",
        name="uq_project_check_items_tenant_project_template_binding",
    ),
    Index(
        "ix_project_check_items_tenant_project_stage_status",
        "tenant_id",
        "project_id",
        "stage_id",
        "status",
        "is_gate",
    ),
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

gate_history_records = Table(
    "gate_history_records",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("gate_id", Uuid, nullable=False),
    Column("reviewed_by_user_id", Uuid),
    Column("source_system", String(64), nullable=False),
    Column("source_id", String(128), nullable=False),
    Column("source_hash", String(64), nullable=False),
    Column("round_number", Integer, nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=False),
    Column("participants", Text),
    Column("decision", String(32), nullable=False),
    Column("conditions", Text),
    Column("notes", Text),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("btrim(source_system) <> ''", name="source_system_nonblank"),
    CheckConstraint("btrim(source_id) <> ''", name="source_id_nonblank"),
    CheckConstraint("source_hash ~ '^[0-9a-f]{64}$'", name="source_hash_hex"),
    CheckConstraint("round_number > 0", name="round_number_positive"),
    CheckConstraint(
        "decision IN ('approved', 'conditional', 'rejected')",
        name="decision_allowed",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "gate_id"],
        [
            f"{PROJECT_SCHEMA}.gates.tenant_id",
            f"{PROJECT_SCHEMA}.gates.project_id",
            f"{PROJECT_SCHEMA}.gates.id",
        ],
        name="fk_gate_history_records_tenant_project_gate",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "reviewed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_gate_history_records_tenant_reviewer",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_gate_history_records_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "source_system",
        "source_id",
        name="uq_gate_history_records_tenant_source",
    ),
    Index(
        "ix_gate_history_records_tenant_project_gate_round",
        "tenant_id",
        "project_id",
        "gate_id",
        "round_number",
    ),
    schema=PROJECT_SCHEMA,
)

gate_signoff_rounds = Table(
    "gate_signoff_rounds",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("gate_id", Uuid, nullable=False),
    Column("round_number", Integer, nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'open'")),
    Column("policy_version", String(64), nullable=False),
    Column("requirements", json_type, nullable=False),
    Column("risk_snapshot", json_type, nullable=False, server_default=text("'{}'::jsonb")),
    Column("readiness_snapshot", json_type),
    Column("opened_by_user_id", Uuid, nullable=False),
    Column(
        "opened_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    Column("superseded_by_user_id", Uuid),
    Column("superseded_at", DateTime(timezone=True)),
    Column("supersede_reason", Text),
    Column("completed_by_user_id", Uuid),
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
    CheckConstraint("round_number > 0", name="round_number_positive"),
    CheckConstraint("status IN ('open', 'superseded', 'completed')", name="status_allowed"),
    CheckConstraint("btrim(policy_version) <> ''", name="policy_version_nonblank"),
    CheckConstraint("jsonb_typeof(requirements) = 'object'", name="requirements_object"),
    CheckConstraint("jsonb_typeof(risk_snapshot) = 'object'", name="risk_snapshot_object"),
    CheckConstraint(
        "readiness_snapshot IS NULL OR jsonb_typeof(readiness_snapshot) = 'object'",
        name="readiness_snapshot_object",
    ),
    CheckConstraint(
        "(status = 'open' AND superseded_at IS NULL AND completed_at IS NULL) OR "
        "(status = 'superseded' AND superseded_at IS NOT NULL "
        "AND superseded_by_user_id IS NOT NULL AND completed_at IS NULL) OR "
        "(status = 'completed' AND completed_at IS NOT NULL "
        "AND completed_by_user_id IS NOT NULL AND readiness_snapshot IS NOT NULL)",
        name="lifecycle_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "gate_id"],
        [
            f"{PROJECT_SCHEMA}.gates.tenant_id",
            f"{PROJECT_SCHEMA}.gates.project_id",
            f"{PROJECT_SCHEMA}.gates.id",
        ],
        name="fk_gate_rounds_tenant_project_gate",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "opened_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_gate_rounds_tenant_opener",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "superseded_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_gate_rounds_tenant_superseder",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "completed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_gate_rounds_tenant_completer",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_gate_rounds_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "gate_id",
        "id",
        name="uq_gate_rounds_tenant_project_gate_id",
    ),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "gate_id",
        "round_number",
        name="uq_gate_rounds_tenant_project_gate_number",
    ),
    Index(
        "uq_gate_rounds_one_open",
        "tenant_id",
        "project_id",
        "gate_id",
        unique=True,
        postgresql_where=text("status = 'open'"),
    ),
    Index(
        "ix_gate_rounds_tenant_project_gate_number",
        "tenant_id",
        "project_id",
        "gate_id",
        "round_number",
    ),
    schema=PROJECT_SCHEMA,
)

gate_signoffs = Table(
    "gate_signoffs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("gate_id", Uuid, nullable=False),
    Column("round_id", Uuid, nullable=False),
    Column("slot", String(32), nullable=False),
    Column("requirement", String(32), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'pending'")),
    Column("signed_by_user_id", Uuid),
    Column("signer_role", String(32)),
    Column("signed_at", DateTime(timezone=True)),
    Column("note", Text),
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
    CheckConstraint("slot IN ('product', 'engineering', 'quality')", name="slot_allowed"),
    CheckConstraint(
        "requirement IN ('required', 'conditional', 'not_applicable')",
        name="requirement_allowed",
    ),
    CheckConstraint(
        "status IN ('pending', 'approved', 'conditional', 'rejected', 'not_applicable')",
        name="status_allowed",
    ),
    CheckConstraint(
        "(status = 'pending' AND signed_by_user_id IS NULL AND signed_at IS NULL) OR "
        "(status = 'not_applicable' AND requirement = 'not_applicable' "
        "AND signed_by_user_id IS NULL AND signed_at IS NULL) OR "
        "(status IN ('approved', 'conditional', 'rejected') "
        "AND signed_by_user_id IS NOT NULL AND signer_role IS NOT NULL "
        "AND signed_at IS NOT NULL)",
        name="signature_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "gate_id", "round_id"],
        [
            f"{PROJECT_SCHEMA}.gate_signoff_rounds.tenant_id",
            f"{PROJECT_SCHEMA}.gate_signoff_rounds.project_id",
            f"{PROJECT_SCHEMA}.gate_signoff_rounds.gate_id",
            f"{PROJECT_SCHEMA}.gate_signoff_rounds.id",
        ],
        name="fk_gate_signoffs_tenant_project_gate_round",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "signed_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_gate_signoffs_tenant_signer",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_gate_signoffs_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "gate_id",
        "round_id",
        "slot",
        name="uq_gate_signoffs_tenant_round_slot",
    ),
    Index(
        "ix_gate_signoffs_tenant_project_gate_round",
        "tenant_id",
        "project_id",
        "gate_id",
        "round_id",
    ),
    schema=PROJECT_SCHEMA,
)

gate_signoff_additions = Table(
    "gate_signoff_additions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("gate_id", Uuid, nullable=False),
    Column("slot", String(32), nullable=False),
    Column("requirement", String(32), nullable=False),
    Column("reason", Text, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("added_by_user_id", Uuid, nullable=False),
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
    CheckConstraint("slot IN ('product', 'engineering', 'quality')", name="slot_allowed"),
    CheckConstraint("requirement IN ('conditional', 'required')", name="requirement_allowed"),
    CheckConstraint("btrim(reason) <> ''", name="reason_nonblank"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "gate_id"],
        [
            f"{PROJECT_SCHEMA}.gates.tenant_id",
            f"{PROJECT_SCHEMA}.gates.project_id",
            f"{PROJECT_SCHEMA}.gates.id",
        ],
        name="fk_gate_additions_tenant_project_gate",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "added_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_gate_additions_tenant_actor",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_gate_additions_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "gate_id",
        "slot",
        name="uq_gate_additions_tenant_gate_slot",
    ),
    schema=PROJECT_SCHEMA,
)

gate_grandfather_exemptions = Table(
    "gate_grandfather_exemptions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("gate_id", Uuid, nullable=False),
    Column("requirement_key", String(128), nullable=False),
    Column("policy_version", String(64), nullable=False),
    Column("reason", Text, nullable=False),
    Column("approved_by_user_id", Uuid, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("btrim(requirement_key) <> ''", name="requirement_key_nonblank"),
    CheckConstraint("btrim(policy_version) <> ''", name="policy_version_nonblank"),
    CheckConstraint("btrim(reason) <> ''", name="reason_nonblank"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "gate_id"],
        [
            f"{PROJECT_SCHEMA}.gates.tenant_id",
            f"{PROJECT_SCHEMA}.gates.project_id",
            f"{PROJECT_SCHEMA}.gates.id",
        ],
        name="fk_gate_grandfather_tenant_project_gate",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "approved_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_gate_grandfather_tenant_approver",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_gate_grandfather_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "gate_id",
        "policy_version",
        "requirement_key",
        name="uq_gate_grandfather_tenant_gate_policy_key",
    ),
    Index(
        "ix_gate_grandfather_tenant_project_gate",
        "tenant_id",
        "project_id",
        "gate_id",
        "created_at",
    ),
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
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_issues_tenant_project_id"),
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

memories = Table(
    "memories",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("source_finding_id", Uuid),
    Column("source_ncr_id", Uuid),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("verified_by_user_id", Uuid),
    Column("archived_by_user_id", Uuid),
    Column("title", String(512), nullable=False),
    Column("content", Text, nullable=False),
    Column("applicability", Text),
    Column("tags", json_type, nullable=False, server_default=text("'[]'::jsonb")),
    Column("source_refs", json_type, nullable=False, server_default=text("'[]'::jsonb")),
    Column("content_sha256", String(64), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'draft'")),
    Column("verified_at", DateTime(timezone=True)),
    Column("archived_at", DateTime(timezone=True)),
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
    CheckConstraint("status IN ('draft', 'verified', 'archived')", name="status_allowed"),
    CheckConstraint("btrim(title) <> '' AND btrim(content) <> ''", name="required_text_nonblank"),
    CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_hex"),
    CheckConstraint("jsonb_typeof(tags) = 'array'", name="tags_array"),
    CheckConstraint("jsonb_typeof(source_refs) = 'array'", name="source_refs_array"),
    CheckConstraint(
        "source_finding_id IS NULL OR source_ncr_id IS NULL",
        name="source_mutually_exclusive",
    ),
    CheckConstraint(
        "verified_by_user_id IS NULL OR verified_by_user_id <> created_by_user_id",
        name="verification_four_eyes",
    ),
    CheckConstraint(
        "(status = 'draft' AND verified_by_user_id IS NULL AND verified_at IS NULL "
        "AND archived_by_user_id IS NULL AND archived_at IS NULL) OR "
        "(status = 'verified' AND verified_by_user_id IS NOT NULL AND verified_at IS NOT NULL "
        "AND archived_by_user_id IS NULL AND archived_at IS NULL) OR "
        "(status = 'archived' AND verified_by_user_id IS NOT NULL AND verified_at IS NOT NULL "
        "AND archived_by_user_id IS NOT NULL AND archived_at IS NOT NULL)",
        name="lifecycle_consistent",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id"],
        [f"{PROJECT_SCHEMA}.projects.tenant_id", f"{PROJECT_SCHEMA}.projects.id"],
        name="fk_memories_tenant_project",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "source_finding_id"],
        [
            f"{AI_SCHEMA}.findings.tenant_id",
            f"{AI_SCHEMA}.findings.project_id",
            f"{AI_SCHEMA}.findings.id",
        ],
        name="fk_memories_tenant_project_finding",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "source_ncr_id"],
        [
            f"{QUALITY_SCHEMA}.nonconformance_reports.tenant_id",
            f"{QUALITY_SCHEMA}.nonconformance_reports.project_id",
            f"{QUALITY_SCHEMA}.nonconformance_reports.id",
        ],
        name="fk_memories_tenant_project_ncr",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_memories_tenant_creator",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "verified_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_memories_tenant_verifier",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "archived_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_memories_tenant_archiver",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_memories_tenant_id_id"),
    UniqueConstraint("tenant_id", "project_id", "id", name="uq_memories_tenant_project_id"),
    UniqueConstraint("tenant_id", "source_finding_id", name="uq_memories_tenant_finding"),
    UniqueConstraint("tenant_id", "source_ncr_id", name="uq_memories_tenant_ncr"),
    Index("ix_memories_tenant_project_status", "tenant_id", "project_id", "status", "updated_at"),
    schema=MEMORY_SCHEMA,
)

memory_embeddings = Table(
    "memory_embeddings",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("project_id", Uuid, nullable=False),
    Column("memory_id", Uuid, nullable=False),
    Column("created_by_user_id", Uuid, nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model", String(256), nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("content_sha256", String(64), nullable=False),
    Column("embedding", Vector(), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("btrim(provider) <> '' AND btrim(model) <> ''", name="route_nonblank"),
    CheckConstraint("dimensions BETWEEN 1 AND 4096", name="dimensions_range"),
    CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_hex"),
    ForeignKeyConstraint(
        ["tenant_id", "project_id", "memory_id"],
        [
            f"{MEMORY_SCHEMA}.memories.tenant_id",
            f"{MEMORY_SCHEMA}.memories.project_id",
            f"{MEMORY_SCHEMA}.memories.id",
        ],
        name="fk_memory_embeddings_tenant_project_memory",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "created_by_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_memory_embeddings_tenant_creator",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_memory_embeddings_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "memory_id",
        "provider",
        "model",
        "dimensions",
        "content_sha256",
        name="uq_memory_embeddings_route_content",
    ),
    Index(
        "ix_memory_embeddings_tenant_project_route",
        "tenant_id",
        "project_id",
        "provider",
        "model",
        "dimensions",
    ),
    schema=MEMORY_SCHEMA,
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

finding_quality_controls = Table(
    "finding_quality_controls",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("agent_key", String(64), nullable=False),
    Column("finding_type", String(64), nullable=False),
    Column("status", String(32), nullable=False, server_default=text("'active'")),
    Column("minimum_review_count", SmallInteger, nullable=False, server_default=text("5")),
    Column(
        "acceptance_threshold_basis_points",
        SmallInteger,
        nullable=False,
        server_default=text("5000"),
    ),
    Column("reviewed_count", Integer, nullable=False, server_default=text("0")),
    Column("accepted_count", Integer, nullable=False, server_default=text("0")),
    Column("applied_count", Integer, nullable=False, server_default=text("0")),
    Column("last_evaluated_at", DateTime(timezone=True)),
    Column("narrowed_at", DateTime(timezone=True)),
    Column("narrowed_reason", String(256)),
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
        "(agent_key = 'project_intelligence' AND finding_type IN "
        "('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR "
        "(agent_key = 'knowledge_lite' AND finding_type = 'knowledge_draft')",
        name="type_allowed",
    ),
    CheckConstraint("status IN ('active', 'narrowed')", name="status_allowed"),
    CheckConstraint(
        "minimum_review_count BETWEEN 1 AND 1000",
        name="minimum_reviews_range",
    ),
    CheckConstraint(
        "acceptance_threshold_basis_points BETWEEN 0 AND 10000",
        name="threshold_range",
    ),
    CheckConstraint(
        "reviewed_count >= 0 AND accepted_count BETWEEN 0 AND reviewed_count "
        "AND applied_count BETWEEN 0 AND accepted_count",
        name="counts_consistent",
    ),
    CheckConstraint(
        "(status = 'active' AND narrowed_at IS NULL AND narrowed_reason IS NULL) OR "
        "(status = 'narrowed' AND narrowed_at IS NOT NULL "
        "AND narrowed_reason IS NOT NULL AND btrim(narrowed_reason) <> '')",
        name="narrowing_consistent",
    ),
    UniqueConstraint(
        "tenant_id",
        "agent_key",
        "finding_type",
        name="uq_finding_quality_controls_tenant_agent_type",
    ),
    Index(
        "ix_finding_quality_controls_tenant_status",
        "tenant_id",
        "status",
        "agent_key",
        "finding_type",
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
    CheckConstraint(
        "(agent_key = 'project_intelligence' AND finding_type IN "
        "('risk_suggestion', 'blocker_alert', 'gate_readiness_anomaly')) OR "
        "(agent_key = 'knowledge_lite' AND finding_type = 'knowledge_draft')",
        name="type_allowed",
    ),
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
        "AND applied_entity_type IN ('risk', 'memory') AND applied_entity_id IS NOT NULL "
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

migration_runs = Table(
    "migration_runs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("actor_user_id", Uuid, nullable=False),
    Column("source_system", String(64), nullable=False),
    Column("source_schema", String(64), nullable=False),
    Column("source_fingerprint", String(64), nullable=False),
    Column("selected_project_ids", json_type, nullable=False),
    Column("status", String(32), nullable=False),
    Column("stats", json_type, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("source_system = 'cehub-v3'", name="source_system_allowed"),
    CheckConstraint("btrim(source_schema) <> ''", name="source_schema_nonblank"),
    CheckConstraint("source_fingerprint ~ '^[0-9a-f]{64}$'", name="source_fingerprint_hex"),
    CheckConstraint("jsonb_typeof(selected_project_ids) = 'array'", name="project_ids_array"),
    CheckConstraint("status = 'completed'", name="status_allowed"),
    CheckConstraint("jsonb_typeof(stats) = 'object'", name="stats_object"),
    ForeignKeyConstraint(
        ["tenant_id", "actor_user_id"],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name="fk_migration_runs_tenant_actor",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_migration_runs_tenant_id_id"),
    Index("ix_migration_runs_tenant_created", "tenant_id", "created_at", "id"),
    schema=AUDIT_SCHEMA,
)

migration_mappings = Table(
    "migration_mappings",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "tenant_id",
        Uuid,
        ForeignKey(f"{CORE_SCHEMA}.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("run_id", Uuid, nullable=False),
    Column("source_system", String(64), nullable=False),
    Column("entity_type", String(32), nullable=False),
    Column("source_id", String(128), nullable=False),
    Column("target_id", Uuid, nullable=False),
    Column("source_hash", String(64), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    CheckConstraint("source_system = 'cehub-v3'", name="source_system_allowed"),
    CheckConstraint(
        "entity_type IN ('user', 'project', 'task', 'gate_review', 'file_reference')",
        name="entity_type_allowed",
    ),
    CheckConstraint("btrim(source_id) <> ''", name="source_id_nonblank"),
    CheckConstraint("source_hash ~ '^[0-9a-f]{64}$'", name="source_hash_hex"),
    ForeignKeyConstraint(
        ["tenant_id", "run_id"],
        [f"{AUDIT_SCHEMA}.migration_runs.tenant_id", f"{AUDIT_SCHEMA}.migration_runs.id"],
        name="fk_migration_mappings_tenant_run",
        ondelete="RESTRICT",
    ),
    UniqueConstraint("tenant_id", "id", name="uq_migration_mappings_tenant_id_id"),
    UniqueConstraint(
        "tenant_id",
        "source_system",
        "entity_type",
        "source_id",
        name="uq_migration_mappings_tenant_source_entity",
    ),
    Index(
        "ix_migration_mappings_tenant_target",
        "tenant_id",
        "entity_type",
        "target_id",
    ),
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
    documents: Table
    external_file_references: Table
    document_fragments: Table
    specifications: Table
    development_boms: Table
    development_bom_items: Table
    erp_bom_references: Table
    cost_bom_items: Table
    build_batches: Table
    samples: Table
    sample_signoffs: Table
    sample_signoff_samples: Table
    test_plans: Table
    test_cases: Table
    test_case_samples: Table
    test_reports: Table
    certifications: Table
    certification_expiry_alerts: Table
    complaints: Table
    nonconformance_reports: Table
    root_cause_analyses: Table
    capa_actions: Table
    effectiveness_reviews: Table
    memories: Table
    memory_embeddings: Table
    engineering_change_requests: Table
    ecr_affected_boms: Table
    engineering_change_notices: Table
    erp_handoffs: Table
    deliverable_check_templates: Table
    project_check_items: Table
    workflows: Table
    stages: Table
    gates: Table
    gate_history_records: Table
    gate_signoff_rounds: Table
    gate_signoffs: Table
    gate_signoff_additions: Table
    gate_grandfather_exemptions: Table
    tasks: Table
    task_dependencies: Table
    issues: Table
    risks: Table
    decisions: Table
    tenant_model_settings: Table
    agent_dispatcher_cursors: Table
    agent_subscriptions: Table
    agent_runs: Table
    finding_quality_controls: Table
    model_invocations: Table
    findings: Table
    finding_actions: Table
    events: Table
    audit_log: Table
    migration_runs: Table
    migration_mappings: Table


tables = Tables(
    tenants=tenants,
    users=users,
    customers=customers,
    requirements=requirements,
    development_cases=development_cases,
    projects=projects,
    project_members=project_members,
    documents=documents,
    external_file_references=external_file_references,
    document_fragments=document_fragments,
    specifications=specifications,
    development_boms=development_boms,
    development_bom_items=development_bom_items,
    erp_bom_references=erp_bom_references,
    cost_bom_items=cost_bom_items,
    build_batches=build_batches,
    samples=samples,
    sample_signoffs=sample_signoffs,
    sample_signoff_samples=sample_signoff_samples,
    test_plans=test_plans,
    test_cases=test_cases,
    test_case_samples=test_case_samples,
    test_reports=test_reports,
    certifications=certifications,
    certification_expiry_alerts=certification_expiry_alerts,
    complaints=complaints,
    nonconformance_reports=nonconformance_reports,
    root_cause_analyses=root_cause_analyses,
    capa_actions=capa_actions,
    effectiveness_reviews=effectiveness_reviews,
    memories=memories,
    memory_embeddings=memory_embeddings,
    engineering_change_requests=engineering_change_requests,
    ecr_affected_boms=ecr_affected_boms,
    engineering_change_notices=engineering_change_notices,
    erp_handoffs=erp_handoffs,
    deliverable_check_templates=deliverable_check_templates,
    project_check_items=project_check_items,
    workflows=workflows,
    stages=stages,
    gates=gates,
    gate_history_records=gate_history_records,
    gate_signoff_rounds=gate_signoff_rounds,
    gate_signoffs=gate_signoffs,
    gate_signoff_additions=gate_signoff_additions,
    gate_grandfather_exemptions=gate_grandfather_exemptions,
    tasks=tasks,
    task_dependencies=task_dependencies,
    issues=issues,
    risks=risks,
    decisions=decisions,
    tenant_model_settings=tenant_model_settings,
    agent_dispatcher_cursors=agent_dispatcher_cursors,
    agent_subscriptions=agent_subscriptions,
    agent_runs=agent_runs,
    finding_quality_controls=finding_quality_controls,
    model_invocations=model_invocations,
    findings=findings,
    finding_actions=finding_actions,
    events=events,
    audit_log=audit_log,
    migration_runs=migration_runs,
    migration_mappings=migration_mappings,
)
