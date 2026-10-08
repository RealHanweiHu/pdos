"""Current proposal, immutable document history and named investment decisions."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


def define_proposal_tables(metadata: MetaData) -> tuple[Table, Table, Table]:
    proposals = Table(
        "product_proposals",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("market_space_id", Uuid, nullable=False),
        Column("product_line_id", Uuid),
        Column("owner_user_id", Uuid, nullable=False),
        Column("request_id", Uuid, nullable=False),
        Column("request_digest", String(64), nullable=False),
        Column("title", String(512), nullable=False),
        Column("entry_kind", String(32), nullable=False),
        Column("brief", Text, nullable=False),
        Column("baseline_product_id", Uuid),
        Column("source_file_ids", JSONB, nullable=False),
        Column("evidence_ids", JSONB, nullable=False),
        Column("category_context", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("target_regions", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
        Column("document", JSONB, nullable=False),
        Column("state", String(32), nullable=False, server_default="draft"),
        Column("reviewer_user_id", Uuid),
        Column("submitted_version", Integer),
        Column("version", Integer, nullable=False, server_default="1"),
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
        UniqueConstraint(
            "tenant_id", "market_space_id", "id", name="uq_product_proposals_space_id"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_product_proposals_tenant_id"),
        UniqueConstraint(
            "tenant_id", "owner_user_id", "request_id", name="uq_product_proposals_request"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "market_space_id"],
            ["cehub_product.market_spaces.tenant_id", "cehub_product.market_spaces.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_product_proposals_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewer_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            name="fk_product_proposals_reviewer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "market_space_id", "product_line_id"],
            [
                "cehub_product.product_nodes.tenant_id",
                "cehub_product.product_nodes.market_space_id",
                "cehub_product.product_nodes.id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("entry_kind IN ('odm','new_product','iteration')", name="entry_kind"),
        CheckConstraint(
            "state IN ('draft','in_review','approved','returned','declined')", name="state"
        ),
        CheckConstraint("version>0 AND btrim(title)<>''", name="bounds"),
        schema="cehub_product",
    )
    revisions = Table(
        "product_proposal_revisions",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("proposal_id", Uuid, nullable=False),
        Column("version", Integer, nullable=False),
        Column("actor_user_id", Uuid, nullable=False),
        Column("ai_run_id", Uuid),
        Column("origin", String(16), nullable=False),
        Column("document", JSONB, nullable=False),
        Column("source_catalog", JSONB, nullable=False),
        Column("document_digest", String(64), nullable=False),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        UniqueConstraint("tenant_id", "proposal_id", "version"),
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["cehub_product.product_proposals.tenant_id", "cehub_product.product_proposals.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ai_run_id"],
            ["cehub_ai.agent_runs.tenant_id", "cehub_ai.agent_runs.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("origin IN ('human','ai_assisted') AND version>0", name="origin"),
        schema="cehub_product",
    )
    decisions = Table(
        "product_proposal_decisions",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("proposal_id", Uuid, nullable=False),
        Column("proposal_version", Integer, nullable=False),
        Column("actor_user_id", Uuid, nullable=False),
        Column("outcome", String(16), nullable=False),
        Column("selected_option", String(16)),
        Column("rationale", Text, nullable=False),
        Column("accepted_unknowns", Text, nullable=False),
        Column("snapshot", JSONB, nullable=False),
        Column("snapshot_digest", String(64), nullable=False),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        UniqueConstraint("tenant_id", "proposal_id", "proposal_version"),
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["cehub_product.product_proposals.tenant_id", "cehub_product.product_proposals.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("outcome IN ('approved','returned','declined')", name="outcome"),
        schema="cehub_product",
    )
    return proposals, revisions, decisions
