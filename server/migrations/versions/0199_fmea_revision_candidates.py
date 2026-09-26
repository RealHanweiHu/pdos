"""Deterministic FMEA review inputs and immutable human dispositions."""

import sqlalchemy as sa
from alembic import op

revision = "0199_fmea_revision_candidates"
down_revision = "0198_quality_operation_receipts"
branch_labels = None
depends_on = None
DDL = """

CREATE TABLE cehub_quality.fmea_revision_candidates (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        issue_id UUID NOT NULL,
        input_digest VARCHAR(64) NOT NULL,
        snapshot JSONB NOT NULL,
        source_event_row_id BIGINT,
        created_by_user_id UUID,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_fmea_revision_candidates PRIMARY KEY (id),
        CONSTRAINT uq_fmea_candidate_scope UNIQUE (tenant_id, project_id, id),
        CONSTRAINT uq_fmea_candidate_input UNIQUE (tenant_id, project_id, issue_id,
input_digest),
        CONSTRAINT fk_fmea_revision_candidates_tenant_id_issues FOREIGN KEY(tenant_id,
project_id, issue_id) REFERENCES cehub_project.issues (tenant_id, project_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_fmea_revision_candidates_tenant_id_events FOREIGN KEY(tenant_id,
source_event_row_id) REFERENCES cehub_event.events (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_fmea_revision_candidates_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_fmea_revision_candidates_shape CHECK (input_digest ~ '^[a-f0-9]{64}$' AND
jsonb_typeof(snapshot)='object')
)

;
CREATE INDEX ix_fmea_candidate_project ON cehub_quality.fmea_revision_candidates (tenant_id,
project_id, created_at, id);

CREATE TABLE cehub_quality.fmea_candidate_dispositions (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        candidate_id UUID NOT NULL,
        action VARCHAR(32) NOT NULL,
        reason TEXT NOT NULL,
        request_id UUID NOT NULL,
        request_digest VARCHAR(64) NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        entry_id UUID,
        version_id UUID,
        excluded_sources JSONB NOT NULL,
        CONSTRAINT pk_fmea_candidate_dispositions PRIMARY KEY (id),
        CONSTRAINT uq_fmea_candidate_disposition UNIQUE (candidate_id),
        CONSTRAINT uq_fmea_candidate_disposition_request UNIQUE (tenant_id, created_by_user_id,
request_id),
        CONSTRAINT fk_fmea_candidate_dispositions_tenant_id_fmea_revision__58b9 FOREIGN
KEY(tenant_id, project_id, candidate_id) REFERENCES cehub_quality.fmea_revision_candidates
(tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_fmea_candidate_dispositions_tenant_id_fmea_versions FOREIGN KEY(tenant_id,
project_id, entry_id, version_id) REFERENCES cehub_quality.fmea_versions (tenant_id, project_id,
entry_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_fmea_candidate_dispositions_tenant_id_users FOREIGN KEY(tenant_id,
created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_fmea_candidate_dispositions_shape CHECK (request_digest ~ '^[a-f0-9]{64}$'
AND btrim(reason)<>'' AND jsonb_typeof(excluded_sources)='array' AND ((action='draft_created'
AND entry_id IS NOT NULL AND version_id IS NOT NULL) OR (action='not_applicable' AND entry_id IS
NULL AND version_id IS NULL)))
)

;
"""


def upgrade() -> None:
    op.execute(DDL)
    for name in ("fmea_revision_candidates", "fmea_candidate_dispositions"):
        op.execute(
            f"CREATE TRIGGER protect_{name} BEFORE UPDATE OR DELETE ON cehub_quality.{name} "
            "FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_quality.{name} FROM PUBLIC")


def downgrade() -> None:
    for name in ("fmea_candidate_dispositions", "fmea_revision_candidates"):
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM cehub_quality.{name})"))
            .scalar()
        ):
            raise RuntimeError("Refusing to discard FMEA candidate history")
    op.drop_table("fmea_candidate_dispositions", schema="cehub_quality")
    op.drop_table("fmea_revision_candidates", schema="cehub_quality")
