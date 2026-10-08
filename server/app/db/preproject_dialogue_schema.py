# ruff: noqa: E501
"""Immutable, human-confirmed applications of private dialogue candidates."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


def define_preproject_confirmations(metadata: MetaData) -> Table:
    return Table(
        "preproject_confirmations",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("conversation_id", Uuid, nullable=False),
        Column("message_id", Uuid, nullable=False),
        Column("run_id", Uuid, nullable=False),
        Column("actor_user_id", Uuid, nullable=False),
        Column("goal", String(16), nullable=False),
        Column("candidate_digest", String(64), nullable=False),
        Column("category_id", Uuid, nullable=False),
        Column("proposal_id", Uuid),
        Column("public_data", JSONB, nullable=False),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        UniqueConstraint("tenant_id", "message_id", name="uq_preproject_confirmation_message"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["cehub_product.market_spaces.tenant_id", "cehub_product.market_spaces.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"], ["cehub_core.users.tenant_id", "cehub_core.users.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["cehub_ai.agent_runs.tenant_id", "cehub_ai.agent_runs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["cehub_ai.conversations.tenant_id", "cehub_ai.conversations.id"],
        ),
        ForeignKeyConstraint(["message_id"], ["cehub_ai.conversation_messages.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["cehub_product.product_proposals.tenant_id", "cehub_product.product_proposals.id"],
        ),
        CheckConstraint(
            "goal IN ('category','proposal') AND candidate_digest ~ '^[a-f0-9]{64}$' AND ((goal='category' AND proposal_id IS NULL) OR (goal='proposal' AND proposal_id IS NOT NULL))",
            name="application_shape",
        ),
        schema="cehub_ai",
    )
