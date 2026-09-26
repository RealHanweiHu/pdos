"""Original-text notice scans and deduplicated deterministic review candidates."""

from alembic import op

revision = "0315_supplier_notice_scans"
down_revision = "0314_supplier_notice_watches"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_supplier.supplier_notice_scans (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
watch_id UUID NOT NULL,
watch_revision_id UUID NOT NULL,
subscription_id UUID NOT NULL,
snapshot_id UUID NOT NULL,
collection_run_id UUID NOT NULL,
policy_version VARCHAR(80) NOT NULL,
request_id UUID NOT NULL,
request_digest VARCHAR(64) NOT NULL,
source_snapshot JSONB NOT NULL,
outcome VARCHAR(16) NOT NULL,
matches JSONB NOT NULL,
full_part_hits INTEGER NOT NULL,
truncated BOOLEAN NOT NULL,
coverage TEXT NOT NULL,
created_by_user_id UUID NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_supplier_notice_scans PRIMARY KEY (id),
CONSTRAINT uq_supplier_notice_scan_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_notice_scan_input UNIQUE (watch_revision_id, snapshot_id, policy_version),
CONSTRAINT uq_notice_scan_request UNIQUE (tenant_id, created_by_user_id, request_id),
CONSTRAINT fk_supplier_notice_scans_tenant_id_supplier_notice_watches FOREIGN KEY(tenant_id,
project_id, watch_id) REFERENCES cehub_supplier.supplier_notice_watches (tenant_id, project_id,
id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_notice_scans_tenant_id_supplier_notice_watc_b327 FOREIGN KEY(tenant_id,
project_id, watch_revision_id) REFERENCES cehub_supplier.supplier_notice_watch_revisions
(tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_notice_scans_tenant_id_research_subscriptions FOREIGN KEY(tenant_id,
subscription_id) REFERENCES cehub_evidence.research_subscriptions (tenant_id, id) ON DELETE
RESTRICT,
CONSTRAINT fk_supplier_notice_scans_tenant_id_evidence_snapshots FOREIGN KEY(tenant_id,
snapshot_id) REFERENCES cehub_evidence.evidence_snapshots (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_notice_scans_tenant_id_research_collection_runs FOREIGN KEY(tenant_id,
collection_run_id) REFERENCES cehub_evidence.research_collection_runs (tenant_id, id) ON DELETE
RESTRICT,
CONSTRAINT fk_supplier_notice_scans_tenant_id_users FOREIGN KEY(tenant_id, created_by_user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supplier_notice_scans_shape CHECK (outcome IN ('matched','no_match') AND
full_part_hits>=0 AND jsonb_typeof(matches)='array' AND jsonb_array_length(matches)<=50 AND
(outcome='matched')=(jsonb_array_length(matches)>0) AND jsonb_typeof(source_snapshot)='object'
AND request_digest ~ '^[a-f0-9]{64}$')
)

;

CREATE TABLE cehub_supplier.supplier_notice_candidates (
id UUID NOT NULL,
tenant_id UUID NOT NULL,
project_id UUID NOT NULL,
watch_id UUID NOT NULL,
first_scan_id UUID NOT NULL,
watch_revision_id UUID NOT NULL,
snapshot_id UUID NOT NULL,
origin_digest VARCHAR(64) NOT NULL,
scope_digest VARCHAR(64) NOT NULL,
evidence JSONB NOT NULL,
state VARCHAR(24) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
CONSTRAINT pk_supplier_notice_candidates PRIMARY KEY (id),
CONSTRAINT uq_notice_candidate_scope UNIQUE (tenant_id, project_id, id),
CONSTRAINT uq_notice_candidate_origin UNIQUE (watch_id, origin_digest),
CONSTRAINT fk_supplier_notice_candidates_tenant_id_supplier_notice_watches FOREIGN
KEY(tenant_id, project_id, watch_id) REFERENCES cehub_supplier.supplier_notice_watches
(tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_notice_candidates_tenant_id_supplier_notice_scans FOREIGN KEY(tenant_id,
project_id, first_scan_id) REFERENCES cehub_supplier.supplier_notice_scans (tenant_id,
project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_notice_candidates_tenant_id_supplier_notice_e6c1 FOREIGN KEY(tenant_id,
project_id, watch_revision_id) REFERENCES cehub_supplier.supplier_notice_watch_revisions
(tenant_id, project_id, id) ON DELETE RESTRICT,
CONSTRAINT fk_supplier_notice_candidates_tenant_id_evidence_snapshots FOREIGN KEY(tenant_id,
snapshot_id) REFERENCES cehub_evidence.evidence_snapshots (tenant_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_supplier_notice_candidates_shape CHECK (origin_digest ~ '^[a-f0-9]{64}$' AND
scope_digest ~ '^[a-f0-9]{64}$' AND jsonb_typeof(evidence)='object' AND state='pending_review')
)

;
"""
GUARDS = """
CREATE FUNCTION cehub_supplier.guard_notice_scan() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE w cehub_supplier.supplier_notice_watches%ROWTYPE;
DECLARE r cehub_supplier.supplier_notice_watch_revisions%ROWTYPE;
DECLARE body text;
DECLARE m jsonb;
DECLARE q jsonb;
BEGIN
SELECT * INTO w FROM cehub_supplier.supplier_notice_watches
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.watch_id;
SELECT * INTO r FROM cehub_supplier.supplier_notice_watch_revisions
WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.watch_revision_id;
IF w.id IS NULL OR NOT w.active OR r.watch_id<>w.id OR r.version<>w.version
OR NEW.subscription_id<>w.subscription_id
OR NEW.policy_version<>'supplier-notice-literal-v1'
OR NEW.source_snapshot->'watch_revision'->>'id' IS DISTINCT FROM r.id::text
OR NEW.source_snapshot->'watch_source' IS DISTINCT FROM r.snapshot
OR NEW.source_snapshot->'snapshot'->>'id' IS DISTINCT FROM NEW.snapshot_id::text
OR NOT EXISTS(SELECT 1 FROM cehub_evidence.research_collection_runs x
JOIN cehub_evidence.research_subscriptions s ON s.tenant_id=x.tenant_id AND s.id=x.subscription_id
JOIN cehub_evidence.evidence_snapshots e ON e.tenant_id=x.tenant_id AND e.id=x.snapshot_id
JOIN cehub_evidence.research_sources rs ON rs.tenant_id=e.tenant_id AND rs.id=e.source_id
WHERE x.tenant_id=NEW.tenant_id AND x.id=NEW.collection_run_id AND x.status='completed'
AND x.subscription_id=NEW.subscription_id AND x.snapshot_id=NEW.snapshot_id
AND s.status='active' AND rs.status='active'
AND s.last_snapshot_id=e.id AND s.source_id=e.source_id
AND e.superseded_by_id IS NULL AND e.conflicts_with_id IS NULL
AND (e.freshness_expires_at IS NULL OR e.freshness_expires_at>NEW.created_at)) THEN
RAISE EXCEPTION 'Notice scan requires current mapping and actual collection receipt'; END IF;
SELECT ec.body INTO body FROM cehub_evidence.evidence_contents ec
JOIN cehub_evidence.evidence_snapshots e ON e.tenant_id=ec.tenant_id
AND e.content_digest=ec.content_digest WHERE e.tenant_id=NEW.tenant_id AND e.id=NEW.snapshot_id;
IF body IS NULL THEN RAISE EXCEPTION 'Snapshot original text is required'; END IF;
FOR m IN SELECT * FROM jsonb_array_elements(NEW.matches) LOOP
IF (m->>'part_start')::integer<0 OR (m->>'part_end')::integer<=(m->>'part_start')::integer
OR substring(body FROM (m->>'part_start')::integer+1
FOR (m->>'part_end')::integer-(m->>'part_start')::integer) IS DISTINCT FROM m->>'part'
OR (m->>'marker_start')::integer<0 OR
substring(body FROM (m->>'marker_start')::integer+1
FOR (m->>'marker_end')::integer-(m->>'marker_start')::integer) IS DISTINCT FROM m->>'marker'
THEN RAISE EXCEPTION 'Notice match must quote exact original part and marker'; END IF;
FOR q IN SELECT * FROM jsonb_array_elements(m->'quotes') LOOP
IF (q->>'start')::integer<0 OR (q->>'end')::integer<=(q->>'start')::integer
OR substring(body FROM (q->>'start')::integer+1
FOR (q->>'end')::integer-(q->>'start')::integer) IS DISTINCT FROM q->>'text' THEN
RAISE EXCEPTION 'Notice citation must retain original text positions'; END IF;
END LOOP;
END LOOP;
RETURN NEW;
END $$;
CREATE TRIGGER guard_notice_scan BEFORE INSERT ON cehub_supplier.supplier_notice_scans
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.guard_notice_scan();

CREATE FUNCTION cehub_supplier.guard_notice_candidate() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE s cehub_supplier.supplier_notice_scans%ROWTYPE;
BEGIN
SELECT * INTO s FROM cehub_supplier.supplier_notice_scans WHERE id=NEW.first_scan_id
AND tenant_id=NEW.tenant_id AND project_id=NEW.project_id;
IF s.id IS NULL OR s.watch_id<>NEW.watch_id OR s.watch_revision_id<>NEW.watch_revision_id
OR s.snapshot_id<>NEW.snapshot_id
OR s.source_snapshot->>'scope_digest' IS DISTINCT FROM NEW.scope_digest
OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(s.matches) m
WHERE m->>'candidate_id'=NEW.id::text AND m-'candidate_id'-'created'=NEW.evidence) THEN
RAISE EXCEPTION 'Notice candidate requires exact persisted match receipt'; END IF;
RETURN NEW;
END $$;
CREATE TRIGGER guard_notice_candidate BEFORE INSERT ON cehub_supplier.supplier_notice_candidates
FOR EACH ROW EXECUTE FUNCTION cehub_supplier.guard_notice_candidate();

CREATE FUNCTION cehub_supplier.require_notice_candidates() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.matches) m
WHERE NOT EXISTS(SELECT 1 FROM cehub_supplier.supplier_notice_candidates c
WHERE c.tenant_id=NEW.tenant_id AND c.project_id=NEW.project_id AND c.watch_id=NEW.watch_id
AND c.id::text=m->>'candidate_id' AND c.scope_digest=NEW.source_snapshot->>'scope_digest')) THEN
RAISE EXCEPTION 'Match receipt must commit with all candidate identities'; END IF;
RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER require_notice_candidates AFTER INSERT ON
cehub_supplier.supplier_notice_scans DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION cehub_supplier.require_notice_candidates();
REVOKE ALL ON FUNCTION cehub_supplier.guard_notice_scan() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.guard_notice_candidate() FROM PUBLIC;
REVOKE ALL ON FUNCTION cehub_supplier.require_notice_candidates() FROM PUBLIC;

"""


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_research_collection_run_scope",
        "research_collection_runs",
        ["tenant_id", "id"],
        schema="cehub_evidence",
    )
    op.execute(DDL)
    op.execute(GUARDS)
    for table in ("supplier_notice_scans", "supplier_notice_candidates"):
        op.execute(
            f"CREATE TRIGGER protect_{table} BEFORE UPDATE OR DELETE ON cehub_supplier.{table} "
            "FOR EACH ROW EXECUTE FUNCTION cehub_ai.protect_checkpoint_history()"
        )
        op.execute(f"REVOKE ALL ON cehub_supplier.{table} FROM PUBLIC")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
IF EXISTS(SELECT 1 FROM cehub_supplier.supplier_notice_scans) THEN
RAISE EXCEPTION 'Notice scan and candidate history requires retention'; END IF;
END $$;
DROP TRIGGER require_notice_candidates ON cehub_supplier.supplier_notice_scans;
DROP TABLE cehub_supplier.supplier_notice_candidates;
DROP TABLE cehub_supplier.supplier_notice_scans;
DROP FUNCTION cehub_supplier.require_notice_candidates();
DROP FUNCTION cehub_supplier.guard_notice_candidate();
DROP FUNCTION cehub_supplier.guard_notice_scan();
""")
    op.drop_constraint(
        "uq_research_collection_run_scope", "research_collection_runs", schema="cehub_evidence"
    )
