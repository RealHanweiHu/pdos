"""meeting / agenda / transcript contract (vNext V2-1)

Revision ID: 0053_meeting_contract
Revises: 0052_evidence_based_gate
Create Date: 2026-08-28 09:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053_meeting_contract"
down_revision: str | Sequence[str] | None = "0052_evidence_based_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'scheduled'"),
            nullable=False,
        ),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organizer_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=24),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        sa.Column("external_provider", sa.String(length=24), nullable=True),
        sa.Column("external_meeting_id", sa.String(length=256), nullable=True),
        sa.Column("external_join_url", sa.String(length=1024), nullable=True),
        sa.Column("external_bound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_bound_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "retention_policy",
            sa.String(length=16),
            server_default=sa.text("'standard'"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_reason", sa.String(length=512), nullable=True),
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
            "actual_end_at IS NULL OR actual_end_at >= actual_start_at",
            name=op.f("ck_meetings_actual_window_ordered"),
        ),
        sa.CheckConstraint(
            "actual_end_at IS NULL OR actual_start_at IS NOT NULL",
            name=op.f("ck_meetings_actual_end_requires_start"),
        ),
        sa.CheckConstraint("btrim(title) <> ''", name=op.f("ck_meetings_title_nonblank")),
        sa.CheckConstraint(
            "cancelled_reason IS NULL OR status = 'cancelled'",
            name=op.f("ck_meetings_cancelled_reason_only_when_cancelled"),
        ),
        sa.CheckConstraint(
            "deleted_at IS NULL OR archived_at IS NOT NULL",
            name=op.f("ck_meetings_delete_requires_archive"),
        ),
        sa.CheckConstraint(
            "(external_provider IS NULL AND external_meeting_id IS NULL "
            "AND external_join_url IS NULL AND external_bound_at IS NULL "
            "AND external_bound_by_user_id IS NULL) OR "
            "(external_provider IS NOT NULL AND external_meeting_id IS NOT NULL "
            "AND external_join_url IS NOT NULL AND external_bound_at IS NOT NULL "
            "AND external_bound_by_user_id IS NOT NULL)",
            name=op.f("ck_meetings_external_binding_complete"),
        ),
        sa.CheckConstraint(
            "external_join_url IS NULL OR external_join_url ~ '^https://'",
            name=op.f("ck_meetings_external_join_url_https"),
        ),
        sa.CheckConstraint(
            "external_provider IS NULL OR external_provider IN ('dingtalk', 'tencent_meeting')",
            name=op.f("ck_meetings_external_provider_allowed"),
        ),
        sa.CheckConstraint(
            "meeting_type IN ('weekly', 'material', 'special', 'technical_review', "
            "'decision_checkpoint', 'pilot_review', 'project_retrospective')",
            name=op.f("ck_meetings_meeting_type_allowed"),
        ),
        sa.CheckConstraint(
            "retention_policy IN ('standard', 'extended', 'minimal')",
            name=op.f("ck_meetings_retention_policy_allowed"),
        ),
        sa.CheckConstraint(
            "scheduled_end_at > scheduled_start_at",
            name=op.f("ck_meetings_scheduled_window_ordered"),
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'dingtalk', 'tencent_meeting', 'agent_drafted')",
            name=op.f("ck_meetings_source_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'in_progress', 'completed', 'cancelled')",
            name=op.f("ck_meetings_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "external_bound_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_meetings_tenant_external_binder",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organizer_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_meetings_tenant_organizer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["cehub_project.projects.tenant_id", "cehub_project.projects.id"],
            name="fk_meetings_tenant_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_meetings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meetings")),
        sa.UniqueConstraint(
            "tenant_id",
            "external_provider",
            "external_meeting_id",
            name="uq_meetings_tenant_external",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_meetings_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "project_id", "id", name="uq_meetings_tenant_project_id"),
        schema="cehub_project",
    )
    op.create_index(
        "ix_meetings_tenant_project_start",
        "meetings",
        ["tenant_id", "project_id", "scheduled_start_at"],
        unique=False,
        schema="cehub_project",
    )
    op.create_index(
        "ix_meetings_tenant_status",
        "meetings",
        ["tenant_id", "status"],
        unique=False,
        schema="cehub_project",
    )

    op.create_table(
        "meeting_participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("participation", sa.String(length=16), nullable=False),
        sa.Column(
            "attendance",
            sa.String(length=16),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attendance IN ('unknown', 'attended', 'absent')",
            name=op.f("ck_meeting_participants_attendance_allowed"),
        ),
        sa.CheckConstraint(
            "participation IN ('organizer', 'required', 'optional')",
            name=op.f("ck_meeting_participants_participation_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meeting_id"],
            ["cehub_project.meetings.tenant_id", "cehub_project.meetings.id"],
            name="fk_meeting_participants_tenant_meeting",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_meeting_participants_tenant_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_meeting_participants_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_participants")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_meeting_participants_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "meeting_id",
            "user_id",
            name="uq_meeting_participants_tenant_member",
        ),
        schema="cehub_project",
    )

    op.create_table(
        "meeting_agenda_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("item_kind", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=True),
        sa.Column("source_entity_id", sa.Uuid(), nullable=True),
        sa.Column("carried_from_item_id", sa.Uuid(), nullable=True),
        sa.Column(
            "resolution_status",
            sa.String(length=16),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(source_kind IS NULL AND source_entity_id IS NULL) OR "
            "(source_kind IS NOT NULL AND source_entity_id IS NOT NULL)",
            name=op.f("ck_meeting_agenda_items_source_pair_consistent"),
        ),
        sa.CheckConstraint(
            "btrim(title) <> ''", name=op.f("ck_meeting_agenda_items_title_nonblank")
        ),
        sa.CheckConstraint(
            "carried_from_item_id IS NULL OR carried_from_item_id <> id",
            name=op.f("ck_meeting_agenda_items_carried_from_not_self"),
        ),
        sa.CheckConstraint(
            "item_kind IN ('topic', 'review', 'decision', 'information', 'exception')",
            name=op.f("ck_meeting_agenda_items_item_kind_allowed"),
        ),
        sa.CheckConstraint("position >= 1", name=op.f("ck_meeting_agenda_items_position_positive")),
        sa.CheckConstraint(
            "resolution_status IN ('open', 'closed', 'carried_over')",
            name=op.f("ck_meeting_agenda_items_resolution_status_allowed"),
        ),
        sa.CheckConstraint(
            "source_kind IN ('task', 'issue', 'risk', 'decision', 'gate', "
            "'requirement', 'change_request', 'finding', 'test_run') "
            "OR source_kind IS NULL",
            name=op.f("ck_meeting_agenda_items_source_kind_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meeting_id"],
            ["cehub_project.meetings.tenant_id", "cehub_project.meetings.id"],
            name="fk_meeting_agenda_items_tenant_meeting",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_meeting_agenda_items_tenant_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_meeting_agenda_items_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_agenda_items")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_meeting_agenda_items_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "meeting_id",
            "position",
            name="uq_meeting_agenda_items_tenant_position",
        ),
        schema="cehub_project",
    )
    op.create_index(
        "ix_meeting_agenda_items_tenant_meeting",
        "meeting_agenda_items",
        ["tenant_id", "meeting_id"],
        unique=False,
        schema="cehub_project",
    )
    # Self-referencing FK is issued as its own ALTER: a use_alter constraint
    # declared inside create_table never reaches the database.
    op.create_foreign_key(
        "fk_meeting_agenda_items_tenant_carried_from",
        "meeting_agenda_items",
        "meeting_agenda_items",
        ["tenant_id", "carried_from_item_id"],
        ["tenant_id", "id"],
        source_schema="cehub_project",
        referent_schema="cehub_project",
        ondelete="RESTRICT",
    )

    op.create_table(
        "meeting_transcripts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=24),
            server_default=sa.text("'manual_upload'"),
            nullable=False,
        ),
        sa.Column(
            "language",
            sa.String(length=16),
            server_default=sa.text("'zh-CN'"),
            nullable=False,
        ),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column(
            "speaker_labeled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "btrim(storage_key) <> ''",
            name=op.f("ck_meeting_transcripts_storage_key_nonblank"),
        ),
        sa.CheckConstraint("byte_size > 0", name=op.f("ck_meeting_transcripts_byte_size_positive")),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_meeting_transcripts_content_digest_sha256"),
        ),
        sa.CheckConstraint(
            "segment_count >= 0",
            name=op.f("ck_meeting_transcripts_segment_count_non_negative"),
        ),
        sa.CheckConstraint(
            "source IN ('manual_upload', 'dingtalk_export', 'tencent_meeting_export')",
            name=op.f("ck_meeting_transcripts_source_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meeting_id"],
            ["cehub_project.meetings.tenant_id", "cehub_project.meetings.id"],
            name="fk_meeting_transcripts_tenant_meeting",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "uploaded_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_meeting_transcripts_tenant_uploader",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_meeting_transcripts_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_transcripts")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_meeting_transcripts_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "meeting_id",
            "content_digest",
            name="uq_meeting_transcripts_tenant_meeting_digest",
        ),
        schema="cehub_project",
    )
    op.create_index(
        "ix_meeting_transcripts_tenant_meeting",
        "meeting_transcripts",
        ["tenant_id", "meeting_id"],
        unique=False,
        schema="cehub_project",
    )

    op.create_table(
        "meeting_transcript_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("speaker_label", sa.String(length=128), nullable=True),
        sa.Column("speaker_user_id", sa.Uuid(), nullable=True),
        sa.Column("started_offset_ms", sa.Integer(), nullable=False),
        sa.Column("ended_offset_ms", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "btrim(content) <> ''",
            name=op.f("ck_meeting_transcript_segments_content_nonblank"),
        ),
        sa.CheckConstraint(
            "ended_offset_ms IS NULL OR ended_offset_ms >= started_offset_ms",
            name=op.f("ck_meeting_transcript_segments_offset_window_ordered"),
        ),
        sa.CheckConstraint(
            "sequence >= 1", name=op.f("ck_meeting_transcript_segments_sequence_positive")
        ),
        sa.CheckConstraint(
            "speaker_user_id IS NULL OR speaker_label IS NOT NULL",
            name=op.f("ck_meeting_transcript_segments_speaker_user_requires_label"),
        ),
        sa.CheckConstraint(
            "started_offset_ms >= 0",
            name=op.f("ck_meeting_transcript_segments_started_offset_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "speaker_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_meeting_transcript_segments_tenant_speaker",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "transcript_id"],
            [
                "cehub_project.meeting_transcripts.tenant_id",
                "cehub_project.meeting_transcripts.id",
            ],
            name="fk_meeting_transcript_segments_tenant_transcript",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["cehub_core.tenants.id"],
            name=op.f("fk_meeting_transcript_segments_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meeting_transcript_segments")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_meeting_transcript_segments_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "transcript_id",
            "sequence",
            name="uq_meeting_transcript_segments_tenant_sequence",
        ),
        schema="cehub_project",
    )
    op.create_index(
        "ix_meeting_transcript_segments_tenant_transcript",
        "meeting_transcript_segments",
        ["tenant_id", "transcript_id"],
        unique=False,
        schema="cehub_project",
    )


def downgrade() -> None:
    connection = op.get_bind()
    transcripts = connection.execute(
        sa.text("SELECT count(*) FROM cehub_project.meeting_transcripts")
    ).scalar_one()
    if transcripts:
        raise RuntimeError(
            "refusing downgrade while meeting transcripts exist; "
            "the spoken record behind every minutes citation would be lost"
        )
    op.drop_index(
        "ix_meeting_transcript_segments_tenant_transcript",
        table_name="meeting_transcript_segments",
        schema="cehub_project",
    )
    op.drop_table("meeting_transcript_segments", schema="cehub_project")
    op.drop_index(
        "ix_meeting_transcripts_tenant_meeting",
        table_name="meeting_transcripts",
        schema="cehub_project",
    )
    op.drop_table("meeting_transcripts", schema="cehub_project")
    op.drop_constraint(
        "fk_meeting_agenda_items_tenant_carried_from",
        "meeting_agenda_items",
        schema="cehub_project",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_meeting_agenda_items_tenant_meeting",
        table_name="meeting_agenda_items",
        schema="cehub_project",
    )
    op.drop_table("meeting_agenda_items", schema="cehub_project")
    op.drop_table("meeting_participants", schema="cehub_project")
    op.drop_index("ix_meetings_tenant_status", table_name="meetings", schema="cehub_project")
    op.drop_index(
        "ix_meetings_tenant_project_start",
        table_name="meetings",
        schema="cehub_project",
    )
    op.drop_table("meetings", schema="cehub_project")
