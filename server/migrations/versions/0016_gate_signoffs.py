"""add Gate rounds, signoffs, tightening, and grandfather audit

Revision ID: 0016_gate_signoffs
Revises: 0015_specification_boms
Create Date: 2026-08-12 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_gate_signoffs"
down_revision: str | Sequence[str] | None = "0015_specification_boms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORE_SCHEMA = "cehub_core"
PROJECT_SCHEMA = "cehub_project"


def _actor_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{CORE_SCHEMA}.users.tenant_id", f"{CORE_SCHEMA}.users.id"],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "gate_signoff_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "risk_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "readiness_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("opened_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("superseded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersede_reason", sa.Text(), nullable=True),
        sa.Column("completed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "round_number > 0",
            name=op.f("ck_gate_signoff_rounds_round_number_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'superseded', 'completed')",
            name=op.f("ck_gate_signoff_rounds_status_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(policy_version) <> ''",
            name=op.f("ck_gate_signoff_rounds_policy_version_nonblank"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(requirements) = 'object'",
            name=op.f("ck_gate_signoff_rounds_requirements_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(risk_snapshot) = 'object'",
            name=op.f("ck_gate_signoff_rounds_risk_snapshot_object"),
        ),
        sa.CheckConstraint(
            "readiness_snapshot IS NULL OR jsonb_typeof(readiness_snapshot) = 'object'",
            name=op.f("ck_gate_signoff_rounds_readiness_snapshot_object"),
        ),
        sa.CheckConstraint(
            "(status = 'open' AND superseded_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'superseded' AND superseded_at IS NOT NULL "
            "AND superseded_by_user_id IS NOT NULL AND completed_at IS NULL) OR "
            "(status = 'completed' AND completed_at IS NOT NULL "
            "AND completed_by_user_id IS NOT NULL AND readiness_snapshot IS NOT NULL)",
            name=op.f("ck_gate_signoff_rounds_lifecycle_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_gate_signoff_rounds_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "gate_id"],
            [
                f"{PROJECT_SCHEMA}.gates.tenant_id",
                f"{PROJECT_SCHEMA}.gates.project_id",
                f"{PROJECT_SCHEMA}.gates.id",
            ],
            name="fk_gate_rounds_tenant_project_gate",
            ondelete="RESTRICT",
        ),
        _actor_fk("opened_by_user_id", "fk_gate_rounds_tenant_opener"),
        _actor_fk("superseded_by_user_id", "fk_gate_rounds_tenant_superseder"),
        _actor_fk("completed_by_user_id", "fk_gate_rounds_tenant_completer"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_signoff_rounds")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_gate_rounds_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "gate_id",
            "id",
            name="uq_gate_rounds_tenant_project_gate_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "gate_id",
            "round_number",
            name="uq_gate_rounds_tenant_project_gate_number",
        ),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "uq_gate_rounds_one_open",
        "gate_signoff_rounds",
        ["tenant_id", "project_id", "gate_id"],
        unique=True,
        schema=PROJECT_SCHEMA,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_gate_rounds_tenant_project_gate_number",
        "gate_signoff_rounds",
        ["tenant_id", "project_id", "gate_id", "round_number"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )

    op.create_table(
        "gate_signoffs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("slot", sa.String(length=32), nullable=False),
        sa.Column("requirement", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("signed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("signer_role", sa.String(length=32), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "slot IN ('product', 'engineering', 'quality')",
            name=op.f("ck_gate_signoffs_slot_allowed"),
        ),
        sa.CheckConstraint(
            "requirement IN ('required', 'conditional', 'not_applicable')",
            name=op.f("ck_gate_signoffs_requirement_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'conditional', 'rejected', 'not_applicable')",
            name=op.f("ck_gate_signoffs_status_allowed"),
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND signed_by_user_id IS NULL AND signed_at IS NULL) OR "
            "(status = 'not_applicable' AND requirement = 'not_applicable' "
            "AND signed_by_user_id IS NULL AND signed_at IS NULL) OR "
            "(status IN ('approved', 'conditional', 'rejected') "
            "AND signed_by_user_id IS NOT NULL AND signer_role IS NOT NULL "
            "AND signed_at IS NOT NULL)",
            name=op.f("ck_gate_signoffs_signature_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_gate_signoffs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        _actor_fk("signed_by_user_id", "fk_gate_signoffs_tenant_signer"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_signoffs")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_gate_signoffs_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "gate_id",
            "round_id",
            "slot",
            name="uq_gate_signoffs_tenant_round_slot",
        ),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_gate_signoffs_tenant_project_gate_round",
        "gate_signoffs",
        ["tenant_id", "project_id", "gate_id", "round_id"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )

    op.create_table(
        "gate_signoff_additions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("slot", sa.String(length=32), nullable=False),
        sa.Column("requirement", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("added_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "slot IN ('product', 'engineering', 'quality')",
            name=op.f("ck_gate_signoff_additions_slot_allowed"),
        ),
        sa.CheckConstraint(
            "requirement IN ('conditional', 'required')",
            name=op.f("ck_gate_signoff_additions_requirement_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(reason) <> ''",
            name=op.f("ck_gate_signoff_additions_reason_nonblank"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_gate_signoff_additions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "gate_id"],
            [
                f"{PROJECT_SCHEMA}.gates.tenant_id",
                f"{PROJECT_SCHEMA}.gates.project_id",
                f"{PROJECT_SCHEMA}.gates.id",
            ],
            name="fk_gate_additions_tenant_project_gate",
            ondelete="RESTRICT",
        ),
        _actor_fk("added_by_user_id", "fk_gate_additions_tenant_actor"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_signoff_additions")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_gate_additions_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "gate_id",
            "slot",
            name="uq_gate_additions_tenant_gate_slot",
        ),
        schema=PROJECT_SCHEMA,
    )

    op.create_table(
        "gate_grandfather_exemptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("gate_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_key", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(requirement_key) <> ''",
            name=op.f("ck_gate_grandfather_exemptions_requirement_key_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(policy_version) <> ''",
            name=op.f("ck_gate_grandfather_exemptions_policy_version_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(reason) <> ''",
            name=op.f("ck_gate_grandfather_exemptions_reason_nonblank"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA}.tenants.id"],
            name=op.f("fk_gate_grandfather_exemptions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "gate_id"],
            [
                f"{PROJECT_SCHEMA}.gates.tenant_id",
                f"{PROJECT_SCHEMA}.gates.project_id",
                f"{PROJECT_SCHEMA}.gates.id",
            ],
            name="fk_gate_grandfather_tenant_project_gate",
            ondelete="RESTRICT",
        ),
        _actor_fk("approved_by_user_id", "fk_gate_grandfather_tenant_approver"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_grandfather_exemptions")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_gate_grandfather_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "gate_id",
            "policy_version",
            "requirement_key",
            name="uq_gate_grandfather_tenant_gate_policy_key",
        ),
        schema=PROJECT_SCHEMA,
    )
    op.create_index(
        "ix_gate_grandfather_tenant_project_gate",
        "gate_grandfather_exemptions",
        ["tenant_id", "project_id", "gate_id", "created_at"],
        unique=False,
        schema=PROJECT_SCHEMA,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO cehub_project.gates
                (id, tenant_id, project_id, stage_id, code, name, status)
            SELECT
                gen_random_uuid(), p.tenant_id, p.id, s.id, s.code,
                s.name || ' Gate', 'preparing'
            FROM cehub_project.projects AS p
            JOIN cehub_project.stages AS s
              ON s.tenant_id = p.tenant_id AND s.workflow_id = p.workflow_id
            WHERE NOT EXISTS (
                SELECT 1 FROM cehub_project.gates AS g
                WHERE g.tenant_id = p.tenant_id
                  AND g.project_id = p.id
                  AND g.stage_id = s.id
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gate_grandfather_tenant_project_gate",
        table_name="gate_grandfather_exemptions",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("gate_grandfather_exemptions", schema=PROJECT_SCHEMA)
    op.drop_table("gate_signoff_additions", schema=PROJECT_SCHEMA)
    op.drop_index(
        "ix_gate_signoffs_tenant_project_gate_round",
        table_name="gate_signoffs",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("gate_signoffs", schema=PROJECT_SCHEMA)
    op.drop_index(
        "ix_gate_rounds_tenant_project_gate_number",
        table_name="gate_signoff_rounds",
        schema=PROJECT_SCHEMA,
    )
    op.drop_index(
        "uq_gate_rounds_one_open",
        table_name="gate_signoff_rounds",
        schema=PROJECT_SCHEMA,
    )
    op.drop_table("gate_signoff_rounds", schema=PROJECT_SCHEMA)
