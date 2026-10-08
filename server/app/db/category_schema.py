"""Shared category parameters and knowledge; independent reusable technical platforms."""

# ruff: noqa: E501
from typing import Any

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


def define_category_tables(metadata: MetaData) -> tuple[Table, Table, Table, Table, Table]:
    def base(name: str, category: bool = True) -> list[Any]:
        columns: list[Any] = [
            Column("id", Uuid, primary_key=True),
            Column("tenant_id", Uuid, nullable=False),
        ]
        if category:
            columns += [
                Column("market_space_id", Uuid, nullable=False),
                Column("product_line_id", Uuid, nullable=False),
            ]
        columns += [
            Column("actor_user_id", Uuid, nullable=False),
            Column("request_id", Uuid, nullable=False),
            Column("request_digest", String(64), nullable=False),
            Column(
                "created_at",
                DateTime(timezone=True),
                nullable=False,
                server_default=text("CURRENT_TIMESTAMP"),
            ),
            UniqueConstraint("tenant_id", "request_id", name=f"uq_category_{name}_request"),
            UniqueConstraint("tenant_id", "id", name=f"uq_category_{name}_identity"),
            ForeignKeyConstraint(
                ["tenant_id", "actor_user_id"],
                ["cehub_core.users.tenant_id", "cehub_core.users.id"],
                ondelete="RESTRICT",
            ),
        ]
        if category:
            columns += [
                ForeignKeyConstraint(
                    ["tenant_id", "market_space_id", "product_line_id"],
                    [
                        "cehub_product.product_nodes.tenant_id",
                        "cehub_product.product_nodes.market_space_id",
                        "cehub_product.product_nodes.id",
                    ],
                    name=f"fk_category_{name}_line",
                    ondelete="RESTRICT",
                )
            ]
        return columns

    parameters = Table(
        "category_parameters",
        metadata,
        *base("parameters"),
        Column("parameter_id", Uuid, nullable=False),
        Column("version", Integer, nullable=False),
        Column("key", String(64), nullable=False),
        Column("label", String(128), nullable=False),
        Column("unit", String(64), nullable=False),
        Column("conditions", Text, nullable=False),
        Column("direction", String(32), nullable=False),
        Column("verification_method", Text, nullable=False),
        Column("acceptance_criterion", Text, nullable=False),
        Column("reason", Text, nullable=False),
        UniqueConstraint(
            "tenant_id", "parameter_id", "version", name="uq_category_parameters_revision"
        ),
        UniqueConstraint(
            "tenant_id",
            "product_line_id",
            "key",
            "version",
            name="uq_category_parameters_key_version",
        ),
        CheckConstraint(
            "version>0 AND direction IN ('higher','lower','target','neutral') AND btrim(key)<>'' AND btrim(label)<>'' AND btrim(unit)<>'' AND btrim(conditions)<>''",
            name="parameter_bounds",
        ),
        schema="cehub_product",
    )
    knowledge = Table(
        "category_knowledge",
        metadata,
        *base("knowledge"),
        Column("kind", String(32), nullable=False),
        Column("title", String(256), nullable=False),
        Column("body", Text, nullable=False),
        Column("regions", JSONB, nullable=False),
        Column("source_refs", JSONB, nullable=False),
        Column("origin", String(32), nullable=False),
        CheckConstraint(
            "kind IN ('scene','voice','regulation','general_requirement') AND origin IN ('human_shared','human_anonymized') AND btrim(title)<>'' AND btrim(body)<>'' AND jsonb_typeof(regions)='array' AND jsonb_typeof(source_refs)='array'",
            name="knowledge_shape",
        ),
        schema="cehub_product",
    )
    proofs = Table(
        "category_promotion_proofs",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("knowledge_id", Uuid, nullable=False),
        Column("proposal_id", Uuid, nullable=False),
        Column("proposal_version", Integer, nullable=False),
        Column("source_digest", String(64), nullable=False),
        Column("actor_user_id", Uuid, nullable=False),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_id"],
            ["cehub_product.category_knowledge.tenant_id", "cehub_product.category_knowledge.id"],
            ondelete="RESTRICT",
        ),
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
        schema="cehub_product",
    )
    platforms = Table(
        "technical_platforms",
        metadata,
        *base("platforms", False),
        Column("code", String(128), nullable=False),
        Column("name", String(256), nullable=False),
        Column("description", Text, nullable=False),
        UniqueConstraint("tenant_id", "code", name="uq_technical_platforms_code"),
        schema="cehub_product",
    )
    links = Table(
        "product_platform_links",
        metadata,
        *base("links"),
        Column("product_id", Uuid, nullable=False),
        Column("platform_id", Uuid, nullable=False),
        Column("version", Integer, nullable=False),
        Column("action", String(16), nullable=False),
        Column("reason", Text, nullable=False),
        CheckConstraint(
            "version>0 AND action IN ('attach','detach') AND btrim(reason)<>''", name="link_shape"
        ),
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "platform_id",
            "version",
            name="uq_product_platform_links_revision",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "market_space_id", "product_id"],
            [
                "cehub_product.product_nodes.tenant_id",
                "cehub_product.product_nodes.market_space_id",
                "cehub_product.product_nodes.id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "platform_id"],
            ["cehub_product.technical_platforms.tenant_id", "cehub_product.technical_platforms.id"],
            ondelete="RESTRICT",
        ),
        schema="cehub_product",
    )
    return parameters, knowledge, proofs, platforms, links
