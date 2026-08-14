"""extend durable outbox for ERP handoff execution

Revision ID: 0028_erp_handoff_executor
Revises: 0027_dingtalk_hardening
Create Date: 2026-08-13 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_erp_handoff_executor"
down_revision: str | Sequence[str] | None = "0027_dingtalk_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "integration_outbox",
        sa.Column("erp_handoff_id", sa.Uuid(), nullable=True),
        schema="cehub_event",
    )
    op.add_column(
        "integration_outbox",
        sa.Column("delivery_mode", sa.String(length=16), nullable=True),
        schema="cehub_event",
    )
    op.add_column(
        "integration_outbox",
        sa.Column("payload_digest", sa.String(length=64), nullable=True),
        schema="cehub_event",
    )
    op.drop_constraint(
        op.f("ck_integration_outbox_provider_allowed"),
        "integration_outbox",
        schema="cehub_event",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_integration_outbox_operation_allowed"),
        "integration_outbox",
        schema="cehub_event",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_integration_outbox_provider_allowed"),
        "integration_outbox",
        "provider IN ('dingtalk', 'erp')",
        schema="cehub_event",
    )
    op.create_check_constraint(
        op.f("ck_integration_outbox_operation_allowed"),
        "integration_outbox",
        "(provider = 'dingtalk' AND operation IN ('group_markdown', "
        "'gate_approval_create', 'interactive_card_create', 'interactive_card_update')) OR "
        "(provider = 'erp' AND operation = 'ebom_handoff')",
        schema="cehub_event",
    )
    op.create_check_constraint(
        op.f("ck_integration_outbox_payload_digest_hex"),
        "integration_outbox",
        "payload_digest IS NULL OR payload_digest ~ '^[0-9a-f]{64}$'",
        schema="cehub_event",
    )
    op.create_check_constraint(
        op.f("ck_integration_outbox_provider_payload_consistent"),
        "integration_outbox",
        "(provider = 'dingtalk' AND erp_handoff_id IS NULL "
        "AND delivery_mode IS NULL AND payload_digest IS NULL) OR "
        "(provider = 'erp' AND project_id IS NOT NULL AND erp_handoff_id IS NOT NULL "
        "AND delivery_mode IN ('manual', 'api') AND payload_digest IS NOT NULL)",
        schema="cehub_event",
    )
    op.create_foreign_key(
        "fk_integration_outbox_tenant_project_erp_handoff",
        "integration_outbox",
        "erp_handoffs",
        ["tenant_id", "project_id", "erp_handoff_id"],
        ["tenant_id", "project_id", "id"],
        source_schema="cehub_event",
        referent_schema="cehub_product",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_integration_outbox_tenant_erp_handoff",
        "integration_outbox",
        ["tenant_id", "erp_handoff_id"],
        schema="cehub_event",
    )


def downgrade() -> None:
    connection = op.get_bind()
    erp_rows = connection.execute(
        sa.text("SELECT count(*) FROM cehub_event.integration_outbox WHERE provider = 'erp'")
    ).scalar_one()
    if erp_rows:
        raise RuntimeError("refusing lossy downgrade while ERP handoff outbox rows exist")

    op.drop_constraint(
        "uq_integration_outbox_tenant_erp_handoff",
        "integration_outbox",
        schema="cehub_event",
        type_="unique",
    )
    op.drop_constraint(
        "fk_integration_outbox_tenant_project_erp_handoff",
        "integration_outbox",
        schema="cehub_event",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_integration_outbox_provider_payload_consistent"),
        "integration_outbox",
        schema="cehub_event",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_integration_outbox_payload_digest_hex"),
        "integration_outbox",
        schema="cehub_event",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_integration_outbox_operation_allowed"),
        "integration_outbox",
        schema="cehub_event",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_integration_outbox_provider_allowed"),
        "integration_outbox",
        schema="cehub_event",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_integration_outbox_provider_allowed"),
        "integration_outbox",
        "provider = 'dingtalk'",
        schema="cehub_event",
    )
    op.create_check_constraint(
        op.f("ck_integration_outbox_operation_allowed"),
        "integration_outbox",
        "operation IN ('group_markdown', 'gate_approval_create', "
        "'interactive_card_create', 'interactive_card_update')",
        schema="cehub_event",
    )
    op.drop_column("integration_outbox", "payload_digest", schema="cehub_event")
    op.drop_column("integration_outbox", "delivery_mode", schema="cehub_event")
    op.drop_column("integration_outbox", "erp_handoff_id", schema="cehub_event")
