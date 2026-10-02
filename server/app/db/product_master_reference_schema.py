"""Append-only internal references to external ERP/PLM identities."""

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


def define_table(metadata: MetaData) -> Table:
    return Table(
        "product_master_references",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("market_space_id", Uuid, nullable=False),
        Column("product_id", Uuid, nullable=False),
        Column("previous_id", Uuid),
        Column("created_by_user_id", Uuid, nullable=False),
        Column("request_id", Uuid, nullable=False),
        Column("request_digest", String(64), nullable=False),
        Column("context_digest", String(64), nullable=False),
        Column("action", String(16), nullable=False),
        Column("system_kind", String(8), nullable=False),
        Column("source_system", String(128), nullable=False),
        Column("master_kind", String(16), nullable=False),
        Column("external_id", Text, nullable=False),
        Column("external_revision", Text, nullable=False),
        Column("external_as_of", DateTime(timezone=True), nullable=False),
        Column("sources", JSONB, nullable=False),
        Column("reason", Text, nullable=False),
        Column("definition_ref", JSONB, nullable=False),
        Column("product_snapshot", JSONB, nullable=False),
        Column("version", Integer, nullable=False, server_default=text("1")),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        UniqueConstraint(
            "tenant_id", "market_space_id", "product_id", "id", name="uq_master_reference_scope"
        ),
        UniqueConstraint(
            "tenant_id",
            "market_space_id",
            "product_id",
            "request_id",
            name="uq_master_reference_request",
        ),
        UniqueConstraint("tenant_id", "previous_id", name="uq_master_reference_successor"),
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
            ["tenant_id", "market_space_id", "product_id", "previous_id"],
            [
                "cehub_product.product_master_references.tenant_id",
                "cehub_product.product_master_references.market_space_id",
                "cehub_product.product_master_references.product_id",
                "cehub_product.product_master_references.id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["cehub_core.users.tenant_id", "cehub_core.users.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "action IN ('register','correct','withdraw') AND ((action='register' AND "
            "previous_id IS NULL) OR (action<>'register' AND previous_id IS NOT NULL)) AND "
            "previous_id IS DISTINCT FROM id",
            name="master_reference_action",
        ),
        CheckConstraint(
            "(master_kind='material' AND system_kind='erp') OR (master_kind='cad_revision' "
            "AND system_kind='plm') OR (master_kind='product' AND system_kind IN "
            "('erp','plm'))",
            name="master_reference_kind",
        ),
        CheckConstraint(
            "version=1 AND btrim(source_system)<>'' AND btrim(external_id)<>'' AND "
            "btrim(external_revision)<>'' AND btrim(reason)<>''",
            name="master_reference_bounds",
        ),
        CheckConstraint(
            "request_digest ~ '^[a-f0-9]{64}$' AND context_digest ~ '^[a-f0-9]{64}$'",
            name="master_reference_digests",
        ),
        CheckConstraint(
            "jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0 AND "
            "jsonb_typeof(definition_ref)='object' AND "
            "jsonb_typeof(product_snapshot)='object'",
            name="master_reference_json",
        ),
        CheckConstraint(
            "source_system ~ '^[a-zA-Z0-9_.:-]+$' AND length(external_id)<=2048 "
            "AND length(external_revision)<=2048 AND length(reason)<=2048 "
            "AND definition_ref ?& ARRAY['id','version','revision','digest','release_id'] "
            "AND definition_ref->>'digest' ~ '^[a-f0-9]{64}$' "
            "AND product_snapshot ?& ARRAY['id','version','code','name','level','lifecycle']",
            name="master_reference_identity",
        ),
        schema="cehub_product",
    )
