"""Durable original-input notice matching queue, disabled by default."""

from alembic import op

revision = "0316_supplier_notice_dispatches"
down_revision = "0315_supplier_notice_scans"
branch_labels = None
depends_on = None

DDL = """


CREATE TABLE cehub_supplier.supplier_notice_dispatches (
        id UUID NOT NULL,
        tenant_id UUID NOT NULL,
        project_id UUID NOT NULL,
        watch_id UUID NOT NULL,
        watch_revision_id UUID NOT NULL,
        watch_version INTEGER NOT NULL,
        subscription_id UUID NOT NULL,
        snapshot_id UUID NOT NULL,
        collection_run_id UUID NOT NULL,
        owner_user_id UUID NOT NULL,
        policy_version VARCHAR(80) NOT NULL,
        status VARCHAR(16) NOT NULL,
        attempts INTEGER NOT NULL,
        scan_id UUID,
        last_error_code VARCHAR(80),
        last_error_message TEXT,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT pk_supplier_notice_dispatches PRIMARY KEY (id),
        CONSTRAINT uq_notice_dispatch_input UNIQUE (watch_revision_id, snapshot_id,
policy_version),
        CONSTRAINT fk_supplier_notice_dispatches_tenant_id_supplier_notice_watches FOREIGN
KEY(tenant_id, project_id, watch_id) REFERENCES cehub_supplier.supplier_notice_watches (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_dispatches_tenant_id_supplier_notice_db72 FOREIGN
KEY(tenant_id, project_id, watch_revision_id) REFERENCES
cehub_supplier.supplier_notice_watch_revisions (tenant_id, project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_dispatches_tenant_id_supplier_notice_scans FOREIGN
KEY(tenant_id, project_id, scan_id) REFERENCES cehub_supplier.supplier_notice_scans (tenant_id,
project_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_dispatches_tenant_id_research_subscriptions FOREIGN
KEY(tenant_id, subscription_id) REFERENCES cehub_evidence.research_subscriptions (tenant_id, id)
ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_dispatches_tenant_id_evidence_snapshots FOREIGN
KEY(tenant_id, snapshot_id) REFERENCES cehub_evidence.evidence_snapshots (tenant_id, id) ON DELETE
RESTRICT,
        CONSTRAINT fk_supplier_notice_dispatches_tenant_id_research_collec_d452 FOREIGN
KEY(tenant_id, collection_run_id) REFERENCES cehub_evidence.research_collection_runs (tenant_id,
id) ON DELETE RESTRICT,
        CONSTRAINT fk_supplier_notice_dispatches_tenant_id_users FOREIGN KEY(tenant_id,
owner_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_supplier_notice_dispatches_shape CHECK (status IN
('queued','completed','blocked','cancelled') AND attempts>=0 AND watch_version>0 AND
(status='completed')=(scan_id IS NOT NULL) AND policy_version='supplier-notice-literal-v1')
)

;
CREATE INDEX ix_notice_dispatch_queue ON cehub_supplier.supplier_notice_dispatches (created_at,
id) WHERE status = 'queued';
CREATE FUNCTION cehub_supplier.guard_notice_dispatch() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'notice dispatch history is retained'; END IF;
 IF TG_OP='UPDATE' THEN
  IF
(to_jsonb(NEW)-ARRAY['status','attempts','scan_id','last_error_code','last_error_message','updated_at'])
     IS DISTINCT FROM
(to_jsonb(OLD)-ARRAY['status','attempts','scan_id','last_error_code','last_error_message','updated_at'])
THEN
   RAISE EXCEPTION 'notice dispatch input is immutable';
  END IF;
  IF NOT ((OLD.status='queued' AND NEW.status IN ('completed','blocked','cancelled')
            AND NEW.attempts BETWEEN OLD.attempts AND OLD.attempts+1)
          OR (OLD.status='blocked' AND NEW.status IN ('queued','cancelled')
              AND NEW.attempts=OLD.attempts)) THEN
   RAISE EXCEPTION 'invalid notice dispatch transition';
  END IF;
 ELSE
  IF NEW.status<>'queued' OR NEW.attempts<>0 THEN
   RAISE EXCEPTION 'notice dispatch starts queued';
  END IF;
 END IF;
 IF NOT EXISTS (
  SELECT 1 FROM cehub_supplier.supplier_notice_watch_revisions r
  JOIN cehub_supplier.supplier_notice_watches w ON w.id=r.watch_id
       AND w.tenant_id=r.tenant_id AND w.project_id=r.project_id
  JOIN cehub_evidence.research_collection_runs cr ON cr.id=NEW.collection_run_id
       AND cr.tenant_id=NEW.tenant_id
  JOIN cehub_evidence.evidence_snapshots sn ON sn.id=NEW.snapshot_id
       AND sn.tenant_id=NEW.tenant_id
  JOIN cehub_evidence.research_subscriptions sub ON sub.id=NEW.subscription_id
       AND sub.tenant_id=NEW.tenant_id AND sub.source_id=sn.source_id
  WHERE r.id=NEW.watch_revision_id AND r.tenant_id=NEW.tenant_id
    AND r.project_id=NEW.project_id AND r.watch_id=NEW.watch_id
    AND r.version=NEW.watch_version AND w.owner_user_id=NEW.owner_user_id
    AND r.command->>'subscription_id'=NEW.subscription_id::text
    AND r.command->>'active'='true'
    AND cr.subscription_id=NEW.subscription_id AND cr.snapshot_id=NEW.snapshot_id
    AND cr.status='completed'
 ) THEN RAISE EXCEPTION 'notice dispatch must bind original mapping and collection receipt'; END
IF;
 IF NEW.status='completed' AND NOT EXISTS (
  SELECT 1 FROM cehub_supplier.supplier_notice_scans s
  WHERE s.id=NEW.scan_id AND s.tenant_id=NEW.tenant_id AND s.project_id=NEW.project_id
    AND s.watch_id=NEW.watch_id AND s.watch_revision_id=NEW.watch_revision_id
    AND s.snapshot_id=NEW.snapshot_id AND s.subscription_id=NEW.subscription_id
    AND s.policy_version=NEW.policy_version
 ) THEN RAISE EXCEPTION 'notice dispatch must bind actual original-input scan'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER notice_dispatch_guard BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_supplier.supplier_notice_dispatches FOR EACH ROW
 EXECUTE FUNCTION cehub_supplier.guard_notice_dispatch();
REVOKE ALL ON FUNCTION cehub_supplier.guard_notice_dispatch() FROM PUBLIC;
REVOKE ALL ON cehub_supplier.supplier_notice_dispatches FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cehub_supplier.supplier_notice_dispatches) THEN
        RAISE EXCEPTION 'retain notice dispatch history';
      END IF;
    END $$;
    DROP TABLE cehub_supplier.supplier_notice_dispatches;
    DROP FUNCTION cehub_supplier.guard_notice_dispatch();
    """)
