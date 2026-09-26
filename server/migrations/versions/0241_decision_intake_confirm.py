"""Register historical decisions, original rows and immutable human receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0241_decision_intake_confirm"
down_revision = "0240_decision_intake_previews"
branch_labels = None
depends_on = None

DDL = """
ALTER TABLE cehub_project.decisions ADD COLUMN historical_source JSONB;
ALTER TABLE cehub_project.decisions DROP CONSTRAINT ck_decisions_decision_kind_allowed;
ALTER TABLE cehub_project.decisions ADD CONSTRAINT ck_decisions_historical_record CHECK
    ((historical_source IS NULL AND decision_kind <> 'historical_record') OR (historical_source
    IS NOT NULL AND jsonb_typeof(historical_source)='object' AND historical_source ?&
    ARRAY['source_row_id','document_id','reviewed_by_user_id','review_note'] AND
    decision_kind='historical_record' AND project_id IS NOT NULL AND decided_by_user_id IS NULL
    AND approver_user_id IS NULL AND owner_user_id IS NULL AND gate_id IS NULL AND issue_id IS
    NULL AND requirement_id IS NULL AND development_case_id IS NULL AND source_finding_id IS
    NULL AND follow_up_state='none' AND follow_up_task_id IS NULL AND follow_up_audit_id IS
    NULL));
ALTER TABLE cehub_project.decisions ADD CONSTRAINT ck_decisions_decision_kind_allowed CHECK
    (decision_kind IN ('requirement_to_development_case', 'gate_review', 'ecr_approval',
    'ecn_effectivity', 'technical_choice', 'supplier_choice', 'process_decision',
    'debate_brief', 'rebaseline', 'definition_release', 'ccr_response', 'historical_record'));
ALTER TABLE cehub_project.decisions ADD CONSTRAINT uq_decisions_tenant_project_id UNIQUE
    (tenant_id, project_id, id);

CREATE TABLE cehub_ai.decision_intake_batches (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    preview_id UUID NOT NULL,
    created_by_user_id UUID NOT NULL,
    request_id UUID NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    results JSONB NOT NULL,
    review_note TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_decision_intake_batches PRIMARY KEY (id),
    CONSTRAINT ck_decision_intake_batches_review_note CHECK (btrim(review_note)<>''),
    CONSTRAINT uq_decision_intake_batch_request UNIQUE (tenant_id, preview_id, request_id),
    CONSTRAINT fk_decision_intake_batches_tenant_id_decision_intake_previews FOREIGN
    KEY(tenant_id, project_id, preview_id) REFERENCES cehub_ai.decision_intake_previews
    (tenant_id, project_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_decision_intake_batches_tenant_id_users FOREIGN KEY(tenant_id,
    created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_decision_intake_batches_digest CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_decision_intake_batches_results CHECK (jsonb_typeof(results)='array' AND
    jsonb_array_length(results) BETWEEN 1 AND 200)
)

;

CREATE TABLE cehub_project.decision_intake_rows (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    project_id UUID NOT NULL,
    preview_id UUID NOT NULL,
    decision_id UUID NOT NULL,
    document_id UUID NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL,
    locator TEXT NOT NULL,
    input_digest VARCHAR(64) NOT NULL,
    source_snapshot JSONB NOT NULL,
    created_snapshot JSONB NOT NULL,
    review_note TEXT NOT NULL,
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_decision_intake_rows PRIMARY KEY (id),
    CONSTRAINT uq_decision_intake_row_project UNIQUE (tenant_id, project_id, id),
    CONSTRAINT uq_decision_intake_original_row UNIQUE (tenant_id, project_id, source_sha256,
    locator),
    CONSTRAINT fk_decision_intake_rows_tenant_id_decision_intake_previews FOREIGN KEY(tenant_id,
    project_id, preview_id) REFERENCES cehub_ai.decision_intake_previews (tenant_id, project_id,
    id) ON DELETE RESTRICT,
    CONSTRAINT fk_decision_intake_rows_tenant_id_decisions FOREIGN KEY(tenant_id, project_id,
    decision_id) REFERENCES cehub_project.decisions (tenant_id, project_id, id) ON DELETE
    RESTRICT,
    CONSTRAINT fk_decision_intake_rows_tenant_id_documents FOREIGN KEY(tenant_id, project_id,
    document_id) REFERENCES cehub_project.documents (tenant_id, project_id, id) ON DELETE
    RESTRICT,
    CONSTRAINT fk_decision_intake_rows_tenant_id_users FOREIGN KEY(tenant_id,
    created_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_decision_intake_rows_digests CHECK (source_sha256 ~ '^[0-9a-f]{64}$' AND
    input_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_decision_intake_rows_snapshots CHECK (jsonb_typeof(source_snapshot)='object'
    AND jsonb_typeof(created_snapshot)='object'),
    CONSTRAINT ck_decision_intake_rows_locator CHECK (btrim(locator)<>''),
    CONSTRAINT ck_decision_intake_rows_review_note CHECK (btrim(review_note)<>'')
)

;
CREATE INDEX ix_decision_intake_decision ON cehub_project.decision_intake_rows (tenant_id,
    project_id, decision_id);
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute("""
    CREATE FUNCTION cehub_ai.guard_decision_intake_immutable() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN RAISE EXCEPTION 'Historical decision provenance is immutable'; END $$;
    REVOKE ALL ON FUNCTION cehub_ai.guard_decision_intake_immutable() FROM PUBLIC;
    CREATE TRIGGER guard_decision_intake_immutable BEFORE UPDATE OR DELETE
      ON cehub_ai.decision_intake_batches FOR EACH ROW
      EXECUTE FUNCTION cehub_ai.guard_decision_intake_immutable();
    CREATE TRIGGER guard_decision_intake_immutable BEFORE UPDATE OR DELETE
      ON cehub_project.decision_intake_rows FOR EACH ROW
      EXECUTE FUNCTION cehub_ai.guard_decision_intake_immutable();

    CREATE FUNCTION cehub_project.guard_historical_decision_update() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
      IF OLD.historical_source IS NOT NULL THEN
        RAISE EXCEPTION 'Historical decision is immutable';
      END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      IF NEW.historical_source IS NOT NULL THEN
        RAISE EXCEPTION 'Cannot turn an existing decision into historical provenance';
      END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_historical_decision_update() FROM PUBLIC;
    CREATE TRIGGER guard_historical_decision_update BEFORE UPDATE OR DELETE
      ON cehub_project.decisions FOR EACH ROW
      EXECUTE FUNCTION cehub_project.guard_historical_decision_update();

    CREATE FUNCTION cehub_project.guard_historical_decision_source() RETURNS trigger
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
    CREATE CONSTRAINT TRIGGER guard_historical_decision_source AFTER INSERT
      ON cehub_project.decisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION cehub_project.guard_historical_decision_source();

    CREATE FUNCTION cehub_project.guard_decision_intake_source() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM cehub_project.decisions d
        WHERE d.tenant_id=NEW.tenant_id AND d.project_id=NEW.project_id AND d.id=NEW.decision_id
          AND d.historical_source->>'source_row_id'=NEW.id::text
          AND d.historical_source->>'document_id'=NEW.document_id::text
          AND d.historical_source->>'reviewed_by_user_id'=NEW.created_by_user_id::text
          AND d.historical_source->>'review_note'=NEW.review_note
      ) THEN RAISE EXCEPTION 'Decision source must match its historical record'; END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_decision_intake_source() FROM PUBLIC;
    CREATE TRIGGER guard_decision_intake_source BEFORE INSERT ON cehub_project.decision_intake_rows
      FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_decision_intake_source();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
      SELECT EXISTS(SELECT 1 FROM cehub_project.decisions WHERE historical_source IS NOT NULL)
        OR EXISTS(SELECT 1 FROM cehub_ai.decision_intake_batches)
        OR EXISTS(SELECT 1 FROM cehub_project.decision_intake_rows)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard historical decision provenance")
    op.drop_table("decision_intake_rows", schema="cehub_project")
    op.drop_table("decision_intake_batches", schema="cehub_ai")
    op.execute("DROP FUNCTION cehub_project.guard_decision_intake_source()")
    op.execute("DROP FUNCTION cehub_ai.guard_decision_intake_immutable()")
    op.execute("DROP TRIGGER guard_historical_decision_source ON cehub_project.decisions")
    op.execute("DROP FUNCTION cehub_project.guard_historical_decision_source()")
    op.execute("DROP TRIGGER guard_historical_decision_update ON cehub_project.decisions")
    op.execute("DROP FUNCTION cehub_project.guard_historical_decision_update()")
    op.execute("ALTER TABLE cehub_project.decisions DROP CONSTRAINT ck_decisions_historical_record")
    op.execute("ALTER TABLE cehub_project.decisions DROP CONSTRAINT uq_decisions_tenant_project_id")
    op.execute(
        "ALTER TABLE cehub_project.decisions DROP CONSTRAINT ck_decisions_decision_kind_allowed"
    )
    op.execute("""
      ALTER TABLE cehub_project.decisions ADD CONSTRAINT ck_decisions_decision_kind_allowed
      CHECK (decision_kind IN ('requirement_to_development_case', 'gate_review', 'ecr_approval',
        'ecn_effectivity', 'technical_choice', 'supplier_choice',
        'process_decision', 'debate_brief',
        'rebaseline', 'definition_release', 'ccr_response'))
    """)
    op.drop_column("decisions", "historical_source", schema="cehub_project")
