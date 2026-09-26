"""Preserve normalized usage provenance and append-only legacy reconciliation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063_legacy_usage_accounting"
down_revision: str | Sequence[str] | None = "0062_model_budget_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USAGE_EVIDENCE = (
    "(usage_status = 'legacy_unverified' AND input_meter_version = 'legacy_unverified') "
    "OR (input_meter_version = 'normalized_input.v1' AND ((usage_status = 'known' AND "
    "structured_attempts > 0) OR (usage_status IN ('partial', 'unknown') AND "
    "structured_attempts > 0 AND status = 'provider_error') OR (usage_status = "
    "'not_invoked' AND structured_attempts = 0 AND total_tokens = 0 AND cache_read_tokens "
    "= 0 AND cache_creation_tokens = 0)))"
)
DDL = """CREATE TABLE cehub_ai.legacy_usage_resolutions (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    invocation_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    reviewer_user_id UUID NOT NULL,
    evidence_ref TEXT NOT NULL,
    evidence_digest VARCHAR(64) NOT NULL,
    input_tokens BIGINT NOT NULL,
    output_tokens BIGINT NOT NULL,
    cache_read_tokens BIGINT NOT NULL,
    cache_creation_tokens BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_legacy_usage_resolutions PRIMARY KEY (id),
    CONSTRAINT fk_legacy_usage_resolutions_tenant_id_model_invocations FOREIGN KEY(tenant_id,
invocation_id) REFERENCES cehub_ai.model_invocations (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_legacy_usage_resolutions_tenant_id_users FOREIGN KEY(tenant_id,
reviewer_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT uq_legacy_usage_resolution_revision UNIQUE (tenant_id, invocation_id, revision),
    CONSTRAINT ck_legacy_usage_resolutions_evidence_required CHECK (revision > 0 AND
btrim(evidence_ref) <> '' AND length(evidence_digest) = 64),
    CONSTRAINT ck_legacy_usage_resolutions_normalized_usage CHECK (input_tokens >= 0 AND
output_tokens >= 0 AND cache_read_tokens >= 0 AND cache_creation_tokens >= 0 AND input_tokens >=
cache_read_tokens + cache_creation_tokens)
)"""


def upgrade() -> None:
    for column in ("usage_status", "input_meter_version"):
        op.add_column(
            "model_invocations",
            sa.Column(
                column, sa.String(32), nullable=False, server_default=sa.text("'legacy_unverified'")
            ),
            schema="cehub_ai",
        )
    op.create_check_constraint(
        op.f("ck_model_invocations_usage_evidence_consistent"),
        "model_invocations",
        USAGE_EVIDENCE,
        schema="cehub_ai",
    )
    op.execute(DDL)
    op.execute(
        "CREATE TRIGGER legacy_usage_resolutions_append_only BEFORE UPDATE OR DELETE "
        "ON cehub_ai.legacy_usage_resolutions FOR EACH ROW EXECUTE FUNCTION "
        "cehub_ai.reject_budget_history_mutation()"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM cehub_ai.legacy_usage_resolutions) OR "
                "EXISTS (SELECT 1 FROM cehub_ai.model_invocations WHERE usage_status <> "
                "'legacy_unverified' OR input_meter_version <> 'legacy_unverified')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: normalized or reconciled usage evidence exists")
    op.drop_table("legacy_usage_resolutions", schema="cehub_ai")
    op.drop_constraint(
        op.f("ck_model_invocations_usage_evidence_consistent"),
        "model_invocations",
        type_="check",
        schema="cehub_ai",
    )
    for column in ("input_meter_version", "usage_status"):
        op.drop_column("model_invocations", column, schema="cehub_ai")
