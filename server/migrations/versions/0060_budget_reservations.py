"""Append-only lineage links and token reservation history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060_budget_reservations"
down_revision: str | Sequence[str] | None = "0059_invocation_cost_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DDL = (
    """CREATE TABLE cehub_ai.budget_lineages (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    profile JSONB NOT NULL,
    profile_digest VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    absolute_deadline TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_budget_lineages PRIMARY KEY (id),
    CONSTRAINT uq_budget_lineages_tenant_id UNIQUE (tenant_id, id),
    CONSTRAINT ck_budget_lineages_deadline_order CHECK (absolute_deadline > created_at),
    CONSTRAINT ck_budget_lineages_profile_shape CHECK (jsonb_typeof(profile) = 'object'
AND length(profile_digest) = 64),
    CONSTRAINT fk_budget_lineages_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES
cehub_core.tenants (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE cehub_ai.budget_run_links (
    tenant_id UUID NOT NULL,
    run_id UUID NOT NULL,
    lineage_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_budget_run_links PRIMARY KEY (tenant_id, run_id),
    CONSTRAINT fk_budget_run_links_tenant_id_agent_runs FOREIGN KEY(tenant_id, run_id)
REFERENCES cehub_ai.agent_runs (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_budget_run_links_tenant_id_budget_lineages FOREIGN KEY(tenant_id,
lineage_id) REFERENCES cehub_ai.budget_lineages (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT uq_budget_run_links_lineage_run UNIQUE (tenant_id, lineage_id, run_id)
)""",
    """CREATE TABLE cehub_ai.budget_journal (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    lineage_id UUID NOT NULL,
    run_id UUID NOT NULL,
    attempt_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    call_kind VARCHAR(16) NOT NULL,
    input_tokens BIGINT NOT NULL,
    output_tokens BIGINT NOT NULL,
    policy_version VARCHAR(128) NOT NULL,
    reservation_status VARCHAR(32) NOT NULL,
    reserved_tokens BIGINT NOT NULL,
    charged_tokens BIGINT,
    held_tokens BIGINT NOT NULL,
    price_status VARCHAR(16) DEFAULT 'unknown' NOT NULL,
    rate_card JSONB,
    reserved_cost_microusd BIGINT,
    charged_cost_microusd BIGINT,
    provider_request_id TEXT,
    reconciliation_ref TEXT,
    dispatched_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_budget_journal PRIMARY KEY (id),
    CONSTRAINT fk_budget_journal_tenant_id_budget_run_links FOREIGN KEY(tenant_id,
lineage_id, run_id) REFERENCES cehub_ai.budget_run_links (tenant_id, lineage_id, run_id)
ON DELETE RESTRICT,
    CONSTRAINT uq_budget_journal_attempt_revision UNIQUE (tenant_id, attempt_id,
revision),
    CONSTRAINT ck_budget_journal_call_shape CHECK (revision > 0 AND call_kind IN ('model',
'tool')),
    CONSTRAINT ck_budget_journal_tokens_nonnegative CHECK (input_tokens >= 0 AND
output_tokens >= 0 AND reserved_tokens > 0 AND reserved_tokens = input_tokens +
output_tokens AND held_tokens >= 0 AND (charged_tokens IS NULL OR charged_tokens >= 0)),
    CONSTRAINT ck_budget_journal_unknown_price CHECK (price_status = 'unknown' AND
rate_card IS NULL AND reserved_cost_microusd IS NULL AND charged_cost_microusd IS NULL),
    CONSTRAINT ck_budget_journal_lifecycle CHECK ((reservation_status IN ('reserved',
'unknown') AND held_tokens = reserved_tokens AND charged_tokens IS NULL) OR
(reservation_status = 'settled' AND held_tokens = 0 AND charged_tokens IS NOT NULL AND
dispatched_at IS NOT NULL AND reconciliation_ref IS NOT NULL AND btrim(reconciliation_ref)
<> '') OR (reservation_status = 'cancelled_before_dispatch' AND held_tokens = 0 AND
charged_tokens IS NOT NULL AND charged_tokens = 0 AND dispatched_at IS NULL AND
provider_request_id IS NULL)),
    CONSTRAINT ck_budget_journal_unknown_dispatched CHECK (reservation_status <> 'unknown'
OR dispatched_at IS NOT NULL)
)""",
    """CREATE INDEX ix_budget_journal_tenant_attempt_revision ON cehub_ai.budget_journal
(tenant_id, attempt_id, revision)""",
)


def upgrade() -> None:
    for statement in DDL:
        op.execute(sa.text(statement))
    op.execute(
        sa.text("""
        CREATE FUNCTION cehub_ai.reject_budget_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'budget history is append-only';
        END $$
    """)
    )
    for table in ("budget_lineages", "budget_run_links", "budget_journal"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE "
                f"ON cehub_ai.{table} FOR EACH ROW EXECUTE FUNCTION "
                "cehub_ai.reject_budget_history_mutation()"
            )
        )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_ai.budget_lineages) OR "
                "EXISTS(SELECT 1 FROM cehub_ai.budget_run_links) OR "
                "EXISTS(SELECT 1 FROM cehub_ai.budget_journal)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: budget lineage or reservation evidence exists")
    for table in ("budget_journal", "budget_run_links", "budget_lineages"):
        op.drop_table(table, schema="cehub_ai")
    op.execute(sa.text("DROP FUNCTION cehub_ai.reject_budget_history_mutation()"))
