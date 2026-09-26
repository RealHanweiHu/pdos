"""Evidence-backed immutable replacement of historical decision content."""

import sqlalchemy as sa
from alembic import op

revision = "0244_decision_history_amendments"
down_revision = "0243_decision_source_corrections"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_project.decision_intake_amendments (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    source_row_id UUID NOT NULL,
    source_revision INTEGER NOT NULL,
    previous_decision_id UUID NOT NULL,
    replacement_decision_id UUID NOT NULL,
    request_id UUID NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    impact_note TEXT NOT NULL,
    changes JSONB NOT NULL,
    before_snapshot JSONB NOT NULL,
    after_snapshot JSONB NOT NULL,
    evidence JSONB NOT NULL,
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_decision_intake_amendments PRIMARY KEY (id),
    CONSTRAINT uq_decision_amendment_request UNIQUE (tenant_id, source_row_id, request_id),
    CONSTRAINT uq_decision_amendment_replacement UNIQUE (tenant_id, replacement_decision_id),
    CONSTRAINT fk_decision_intake_amendments_tenant_id_decision_intake_rows FOREIGN
    KEY(tenant_id, project_id, source_row_id) REFERENCES cehub_project.decision_intake_rows
    (tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_decision_intake_amendments_tenant_id_decision_intake_8c51 FOREIGN
    KEY(tenant_id, source_row_id, source_revision) REFERENCES
    cehub_project.decision_intake_corrections (tenant_id, source_row_id, revision) ON DELETE
    RESTRICT,
    CONSTRAINT fk_decision_amendment_previous FOREIGN KEY(tenant_id, project_id,
    previous_decision_id) REFERENCES cehub_project.decisions (tenant_id, project_id, id) ON
    DELETE RESTRICT,
    CONSTRAINT fk_decision_amendment_replacement FOREIGN KEY(tenant_id, project_id,
    replacement_decision_id) REFERENCES cehub_project.decisions (tenant_id, project_id, id) ON
    DELETE RESTRICT,
    CONSTRAINT fk_decision_intake_amendments_tenant_id_users FOREIGN KEY(tenant_id,
    created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_decision_intake_amendments_replacement CHECK (source_revision>0 AND
    previous_decision_id<>replacement_decision_id),
    CONSTRAINT ck_decision_intake_amendments_reason CHECK (request_digest ~ '^[0-9a-f]{64}$' AND
    btrim(reason)<>'' AND btrim(impact_note)<>''),
    CONSTRAINT ck_decision_intake_amendments_snapshots CHECK (jsonb_typeof(changes)='object' AND
    changes<>'{}'::jsonb AND jsonb_typeof(before_snapshot)='object' AND
    jsonb_typeof(after_snapshot)='object'),
    CONSTRAINT ck_decision_intake_amendments_evidence CHECK (jsonb_typeof(evidence)='array' AND
    jsonb_array_length(evidence) BETWEEN 1 AND 10)
)

;
CREATE INDEX ix_decision_amendment_history ON cehub_project.decision_intake_amendments
    (tenant_id, source_row_id, source_revision);
"""

OLD_GUARD = """
    CREATE OR REPLACE FUNCTION cehub_project.guard_historical_decision_source() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
      IF NEW.historical_source IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM cehub_project.decision_intake_rows r
        WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.decision_id=NEW.id
          AND r.id::text=NEW.historical_source->>'source_row_id'
          AND r.document_id::text=NEW.historical_source->>'document_id'
          AND r.created_by_user_id::text=NEW.historical_source->>'reviewed_by_user_id'
          AND r.review_note=NEW.historical_source->>'review_note'
          AND r.created_snapshot->'historical_source'=NEW.historical_source
      ) THEN RAISE EXCEPTION 'Historical decision requires matching reviewed original'; END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_historical_decision_source() FROM PUBLIC;
"""

NEW_GUARD = """
    CREATE OR REPLACE FUNCTION cehub_project.guard_historical_decision_source() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
      IF NEW.historical_source IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM cehub_project.decision_intake_rows r
        WHERE r.tenant_id=NEW.tenant_id AND r.project_id=NEW.project_id AND r.decision_id=NEW.id
          AND r.id::text=NEW.historical_source->>'source_row_id'
          AND r.document_id::text=NEW.historical_source->>'document_id'
          AND r.created_by_user_id::text=NEW.historical_source->>'reviewed_by_user_id'
          AND r.review_note=NEW.historical_source->>'review_note'
          AND r.created_snapshot->'historical_source'=NEW.historical_source
      ) AND NOT EXISTS (
        SELECT 1 FROM cehub_project.decision_intake_amendments a
        JOIN cehub_project.decision_intake_rows r
          ON r.tenant_id=a.tenant_id AND r.project_id=a.project_id AND r.id=a.source_row_id
        WHERE a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id
          AND a.replacement_decision_id=NEW.id
          AND a.id::text=NEW.historical_source->>'amendment_id'
          AND a.previous_decision_id::text=NEW.historical_source->>'replaces_decision_id'
          AND r.id::text=NEW.historical_source->>'source_row_id'
          AND r.document_id::text=NEW.historical_source->>'document_id'
          AND a.created_by_user_id::text=NEW.historical_source->>'reviewed_by_user_id'
          AND a.reason=NEW.historical_source->>'review_note'
          AND a.after_snapshot->'historical_source'=NEW.historical_source
      ) THEN RAISE EXCEPTION 'Historical decision requires reviewed original or amendment'; END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_historical_decision_source() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(NEW_GUARD)
    op.execute("""
      CREATE FUNCTION cehub_project.guard_decision_history_amendment() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog AS $$
      BEGIN
        IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Historical amendments are immutable'; END IF;
        IF NOT EXISTS (
          SELECT 1 FROM cehub_project.decision_intake_corrections h
          JOIN cehub_project.decisions previous_decision
            ON previous_decision.tenant_id=h.tenant_id AND previous_decision.project_id=h.project_id
            AND previous_decision.id=NEW.previous_decision_id
          JOIN cehub_project.decisions replacement
            ON replacement.tenant_id=h.tenant_id AND replacement.project_id=h.project_id
            AND replacement.id=NEW.replacement_decision_id
          WHERE h.tenant_id=NEW.tenant_id AND h.project_id=NEW.project_id
            AND h.source_row_id=NEW.source_row_id AND h.revision=NEW.source_revision
            AND h.action='reassign' AND h.previous_decision_id=NEW.previous_decision_id
            AND h.target_decision_id=NEW.replacement_decision_id
            AND h.previous_issue_id IS NOT DISTINCT FROM h.target_issue_id
            AND h.created_by_user_id=NEW.created_by_user_id
            AND h.reason=NEW.reason AND h.impact_note=NEW.impact_note
            AND previous_decision.decision_kind='historical_record'
            AND previous_decision.historical_source->>'source_row_id'=NEW.source_row_id::text
            AND replacement.decision_kind='historical_record'
            AND replacement.historical_source->>'amendment_id'=NEW.id::text
            AND replacement.historical_source->>'replaces_decision_id'=previous_decision.id::text
            AND NEW.before_snapshot=h.before_snapshot->'decision'
            AND NEW.after_snapshot=h.after_snapshot->'decision'
        ) THEN RAISE EXCEPTION 'Amendment must match the reviewed source transition'; END IF;
        RETURN NEW;
      END $$;
      REVOKE ALL ON FUNCTION cehub_project.guard_decision_history_amendment() FROM PUBLIC;
      CREATE TRIGGER guard_decision_history_amendment BEFORE INSERT OR UPDATE OR DELETE
        ON cehub_project.decision_intake_amendments FOR EACH ROW
        EXECUTE FUNCTION cehub_project.guard_decision_history_amendment();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.decision_intake_amendments)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard historical content amendments")
    op.execute(OLD_GUARD)
    op.drop_table("decision_intake_amendments", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_decision_history_amendment()")
