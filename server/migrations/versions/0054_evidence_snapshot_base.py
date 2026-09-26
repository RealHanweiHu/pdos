"""research source and evidence snapshot base (vNext V2-7, C8)

Revision ID: 0054_evidence_snapshot_base
Revises: 0053_meeting_contract
Create Date: 2026-08-28 10:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054_evidence_snapshot_base"
down_revision: str | Sequence[str] | None = "0053_meeting_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The body of a snapshot is what a citation points at. Allowing it to be
# UPDATEd would let a conclusion keep its reference while the evidence beneath
# it changed — the exact failure "快照不可静默覆盖" exists to prevent. Only the
# linkage columns (supersession, conflict) may move after capture.
_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION cehub_evidence.evidence_snapshots_reject_body_update()
RETURNS trigger AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.source_id IS DISTINCT FROM OLD.source_id
        OR NEW.url IS DISTINCT FROM OLD.url
        OR NEW.captured_at IS DISTINCT FROM OLD.captured_at
        OR NEW.captured_by_user_id IS DISTINCT FROM OLD.captured_by_user_id
        OR NEW.content_digest IS DISTINCT FROM OLD.content_digest
        OR NEW.content_ref IS DISTINCT FROM OLD.content_ref
        OR NEW.content_language IS DISTINCT FROM OLD.content_language
        OR NEW.source_version IS DISTINCT FROM OLD.source_version
        OR NEW.trust_tier IS DISTINCT FROM OLD.trust_tier
        OR NEW.taint IS DISTINCT FROM OLD.taint
        OR NEW.byte_size IS DISTINCT FROM OLD.byte_size
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION
            'evidence snapshot % is immutable; capture a new snapshot and set '
            'superseded_by_id instead', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_IMMUTABILITY_TRIGGER = """
CREATE TRIGGER evidence_snapshots_immutable
BEFORE UPDATE ON cehub_evidence.evidence_snapshots
FOR EACH ROW EXECUTE FUNCTION
    cehub_evidence.evidence_snapshots_reject_body_update();
"""


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema("cehub_evidence"))

    op.create_table(
        "research_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("license_note", sa.Text(), nullable=True),
        sa.Column("allowed_use", sa.String(length=24), nullable=False),
        sa.Column("collection_frequency", sa.String(length=16), nullable=False),
        sa.Column("retention_policy", sa.String(length=16), nullable=False),
        sa.Column("trust_tier", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
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
            "allowed_use IN ('internal_analysis', 'internal_citation', 'redistribution')",
            name=op.f("ck_research_sources_allowed_use_allowed"),
        ),
        sa.CheckConstraint(
            "base_url IS NULL OR base_url ~ '^https?://'",
            name=op.f("ck_research_sources_base_url_is_http"),
        ),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_research_sources_name_nonblank")),
        sa.CheckConstraint(
            "collection_frequency IN ('on_demand', 'daily', 'weekly', 'monthly', 'event_driven')",
            name=op.f("ck_research_sources_collection_frequency_allowed"),
        ),
        sa.CheckConstraint(
            "retention_policy IN ('standard', 'extended', 'minimal')",
            name=op.f("ck_research_sources_retention_policy_allowed"),
        ),
        sa.CheckConstraint(
            "source_type IN ('file', 'internal_system') OR base_url IS NOT NULL",
            name=op.f("ck_research_sources_remote_source_requires_base_url"),
        ),
        sa.CheckConstraint(
            "source_type IN ('web', 'api', 'file', 'internal_system')",
            name=op.f("ck_research_sources_source_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name=op.f("ck_research_sources_status_allowed"),
        ),
        sa.CheckConstraint(
            "trust_tier IN ('official', 'public', 'community', 'unknown')",
            name=op.f("ck_research_sources_trust_tier_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_research_sources_tenant_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_research_sources_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_sources")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_research_sources_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_research_sources_tenant_name"),
        schema="cehub_evidence",
    )

    op.create_table(
        "evidence_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("content_ref", sa.String(length=512), nullable=False),
        sa.Column(
            "content_language",
            sa.String(length=16),
            server_default=sa.text("'zh-CN'"),
            nullable=False,
        ),
        sa.Column("source_version", sa.String(length=128), nullable=True),
        sa.Column("trust_tier", sa.String(length=16), nullable=False),
        sa.Column("taint", sa.String(length=24), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("freshness_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column("conflicts_with_id", sa.Uuid(), nullable=True),
        sa.Column("conflict_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(conflicts_with_id IS NULL AND conflict_note IS NULL) OR "
            "(conflicts_with_id IS NOT NULL AND btrim(conflict_note) <> '')",
            name=op.f("ck_evidence_snapshots_conflict_pair_consistent"),
        ),
        sa.CheckConstraint(
            "btrim(content_ref) <> ''",
            name=op.f("ck_evidence_snapshots_content_ref_nonblank"),
        ),
        sa.CheckConstraint("byte_size > 0", name=op.f("ck_evidence_snapshots_byte_size_positive")),
        sa.CheckConstraint(
            "conflicts_with_id IS NULL OR conflicts_with_id <> id",
            name=op.f("ck_evidence_snapshots_conflicts_with_not_self"),
        ),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_evidence_snapshots_content_digest_sha256"),
        ),
        sa.CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id",
            name=op.f("ck_evidence_snapshots_superseded_by_not_self"),
        ),
        sa.CheckConstraint(
            "taint IN ('untrusted_external', 'internal', 'verified')",
            name=op.f("ck_evidence_snapshots_taint_allowed"),
        ),
        sa.CheckConstraint(
            "trust_tier IN ('official', 'public', 'community', 'unknown')",
            name=op.f("ck_evidence_snapshots_trust_tier_allowed"),
        ),
        sa.CheckConstraint(
            "url IS NULL OR url ~ '^https?://'",
            name=op.f("ck_evidence_snapshots_url_is_http"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "captured_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_evidence_snapshots_tenant_capturer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            [
                "cehub_evidence.research_sources.tenant_id",
                "cehub_evidence.research_sources.id",
            ],
            name="fk_evidence_snapshots_tenant_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_evidence_snapshots_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_snapshots")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_evidence_snapshots_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_id",
            "content_digest",
            "source_version",
            name="uq_evidence_snapshots_tenant_source_digest",
        ),
        schema="cehub_evidence",
    )
    op.create_index(
        "ix_evidence_snapshots_tenant_captured",
        "evidence_snapshots",
        ["tenant_id", "captured_at"],
        unique=False,
        schema="cehub_evidence",
    )
    op.create_index(
        "ix_evidence_snapshots_tenant_source",
        "evidence_snapshots",
        ["tenant_id", "source_id"],
        unique=False,
        schema="cehub_evidence",
    )
    # Self-referencing FKs are issued as their own ALTERs: a use_alter
    # constraint declared inside create_table never reaches the database.
    op.create_foreign_key(
        "fk_evidence_snapshots_tenant_superseded_by",
        "evidence_snapshots",
        "evidence_snapshots",
        ["tenant_id", "superseded_by_id"],
        ["tenant_id", "id"],
        source_schema="cehub_evidence",
        referent_schema="cehub_evidence",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_evidence_snapshots_tenant_conflicts_with",
        "evidence_snapshots",
        "evidence_snapshots",
        ["tenant_id", "conflicts_with_id"],
        ["tenant_id", "id"],
        source_schema="cehub_evidence",
        referent_schema="cehub_evidence",
        ondelete="RESTRICT",
    )

    op.execute(_IMMUTABILITY_FUNCTION)
    op.execute(_IMMUTABILITY_TRIGGER)


def downgrade() -> None:
    connection = op.get_bind()
    snapshots = connection.execute(
        sa.text("SELECT count(*) FROM cehub_evidence.evidence_snapshots")
    ).scalar_one()
    if snapshots:
        raise RuntimeError(
            "refusing downgrade while evidence snapshots exist; "
            "every agent conclusion citing one would lose its ground truth"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS evidence_snapshots_immutable ON cehub_evidence.evidence_snapshots"
    )
    op.execute("DROP FUNCTION IF EXISTS cehub_evidence.evidence_snapshots_reject_body_update()")
    op.drop_constraint(
        "fk_evidence_snapshots_tenant_conflicts_with",
        "evidence_snapshots",
        schema="cehub_evidence",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_evidence_snapshots_tenant_superseded_by",
        "evidence_snapshots",
        schema="cehub_evidence",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_evidence_snapshots_tenant_source",
        table_name="evidence_snapshots",
        schema="cehub_evidence",
    )
    op.drop_index(
        "ix_evidence_snapshots_tenant_captured",
        table_name="evidence_snapshots",
        schema="cehub_evidence",
    )
    op.drop_table("evidence_snapshots", schema="cehub_evidence")
    op.drop_table("research_sources", schema="cehub_evidence")
    op.execute(sa.schema.DropSchema("cehub_evidence"))
