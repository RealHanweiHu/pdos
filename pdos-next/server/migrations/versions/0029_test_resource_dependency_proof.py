"""Versioned full resource proof, preserving every legacy Start and reservation."""

# ruff: noqa: E501 - keep the frozen SQL expressions readable and unchanged.

from alembic import op
from sqlalchemy import Column, String, text
from sqlalchemy.dialects.postgresql import JSONB

revision = "next_0029"
down_revision = "next_0028"
branch_labels = None
depends_on = None

PROOF_CHECK = (
    "((fingerprint_version IS NULL AND dependency_proof IS NULL) OR "
    "(fingerprint_version='test-resource-dependency-v2' "
    "AND jsonb_typeof(dependency_proof)='object' "
    "AND dependency_proof ?& ARRAY['schema_version','material','facts_revision'] "
    "AND dependency_proof-ARRAY['schema_version','material','facts_revision']='{}'::jsonb "
    "AND dependency_proof->>'schema_version'=fingerprint_version "
    "AND jsonb_typeof(dependency_proof->'facts_revision')='string' "
    "AND dependency_proof->>'facts_revision'=facts_revision "
    "AND facts_revision ~ '^[a-f0-9]{64}$' "
    "AND jsonb_typeof(dependency_proof->'material')='object' "
    "AND (dependency_proof->'material') ?& ARRAY["
    "'binding','fact','epoch','issuer','issuer_epochs','assets','sample_epochs',"
    "'samples','authority','source_basis','proofs','checks'] "
    "AND (dependency_proof->'material')-ARRAY["
    "'binding','fact','epoch','issuer','issuer_epochs','assets','sample_epochs',"
    "'samples','authority','source_basis','proofs','checks']='{}'::jsonb "
    "AND jsonb_typeof(dependency_proof->'material'->'authority')='object' "
    "AND jsonb_typeof(dependency_proof->'material'->'source_basis')='object')) IS TRUE"
)

ATOM_SQL = """
CREATE FUNCTION require_test_resource_dependency_atom() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE rid uuid; original verification_run_versions%ROWTYPE;
 saved test_resource_reservations%ROWTYPE; rec action_receipts%ROWTYPE;
 inserted jsonb;
BEGIN
 rid := NEW.run_id;
 inserted := to_jsonb(NEW);
 IF TG_TABLE_NAME='verification_run_versions' AND inserted->>'operation'='test.run.plan' THEN
   RETURN NULL;
 END IF;
 SELECT * INTO saved FROM test_resource_reservations
 WHERE tenant_id=NEW.tenant_id AND run_id=rid;
 SELECT * INTO original FROM verification_run_versions
 WHERE tenant_id=NEW.tenant_id AND run_id=rid AND revision=2 AND operation='test.run.start';
 IF saved.fingerprint_version IS NULL AND saved.dependency_proof IS NULL THEN
   IF original.input_snapshot ?| ARRAY['resource_fingerprint_version','resource_dependency_proof']
     OR (TG_TABLE_NAME='verification_run_versions'
         AND (inserted->'input_snapshot') ?| ARRAY['resource_fingerprint_version','resource_dependency_proof']) THEN
     RAISE EXCEPTION 'Explicit dependency version cannot fall back to legacy storage';
   END IF;
   RETURN NULL;
 END IF;
 IF saved.id IS NULL OR original.id IS NULL
   OR saved.fingerprint_version IS DISTINCT FROM 'test-resource-dependency-v2'
   OR original.input_snapshot->>'resource_fingerprint_version' IS DISTINCT FROM saved.fingerprint_version
   OR original.input_snapshot->'resource_dependency_proof' IS DISTINCT FROM saved.dependency_proof
   OR original.input_snapshot->>'resource_facts_revision' IS DISTINCT FROM saved.facts_revision
   OR original.input_snapshot->'reservation'->>'facts_revision' IS DISTINCT FROM saved.facts_revision
   OR original.input_snapshot->'reservation'->>'reservation_id' IS DISTINCT FROM saved.id::text
   OR original.input_snapshot->'reservation'->>'owner_run_id' IS DISTINCT FROM saved.run_id::text
   OR saved.dependency_proof->'material'->'binding'->>'run_id' IS DISTINCT FROM saved.run_id::text
   OR saved.dependency_proof->'material'->'binding'->>'project_id' IS DISTINCT FROM saved.project_id::text
   OR saved.dependency_proof->'material'->'binding'->>'build_id' IS DISTINCT FROM saved.build_id::text
   OR saved.dependency_proof->'material'->'authority'->'scope'->>'tenant_id' IS DISTINCT FROM saved.tenant_id::text
   OR saved.dependency_proof->'material'->'authority'->'scope'->>'product_id' IS DISTINCT FROM saved.product_id::text THEN
   RAISE EXCEPTION 'Versioned dependency requires the exact immutable Start and saved reservation';
 END IF;
 IF TG_TABLE_NAME='verification_run_versions' AND (
   inserted->'input_snapshot'->>'resource_fingerprint_version' IS DISTINCT FROM saved.fingerprint_version
   OR inserted->'input_snapshot'->'resource_dependency_proof' IS DISTINCT FROM saved.dependency_proof
   OR inserted->'input_snapshot'->>'resource_facts_revision' IS DISTINCT FROM saved.facts_revision
   OR inserted->'input_snapshot'->'reservation' IS DISTINCT FROM original.input_snapshot->'reservation') THEN
   RAISE EXCEPTION 'Run successor must preserve the original full resource proof';
 END IF;
 PERFORM assert_test_run_atom(NEW.tenant_id,rid);
 SELECT * INTO rec FROM action_receipts WHERE tenant_id=NEW.tenant_id
   AND product_id=original.product_id AND subject_type='test_run'
   AND subject_id=original.id AND subject_revision=original.revision
   AND operation='test.run.start' AND actor_id=original.writer_id
   AND requester_id=original.writer_id;
 IF rec.id IS NULL
   OR NOT EXISTS(SELECT 1 FROM request_keys k WHERE k.tenant_id=rec.tenant_id
     AND k.receipt_id=rec.id AND k.actor_id=rec.actor_id AND k.digest=rec.request_digest)
   OR NOT EXISTS(SELECT 1 FROM audit_entries a WHERE a.tenant_id=rec.tenant_id
     AND a.receipt_id=rec.id AND a.actor_id=rec.actor_id AND a.operation=rec.operation)
   OR NOT EXISTS(SELECT 1 FROM outbox_events o WHERE o.tenant_id=rec.tenant_id
     AND o.receipt_id=rec.id AND o.actor_id=rec.actor_id AND o.subject_id=original.id
     AND o.subject_revision=original.revision AND o.type='test.run_started') THEN
   RAISE EXCEPTION 'Versioned Start requires its common receipt, request key, audit and outbox atom';
 END IF;
 RETURN NULL;
END $$
"""


def upgrade():
    op.execute(
        "LOCK TABLE test_resource_reservations,verification_run_versions IN SHARE ROW EXCLUSIVE MODE"
    )
    if op.get_bind().scalar(text("SELECT version_num FROM alembic_version")) != down_revision:
        raise RuntimeError("Resource proof upgrade requires the exact installed head28")
    op.add_column("test_resource_reservations", Column("fingerprint_version", String(64)))
    op.add_column(
        "test_resource_reservations", Column("dependency_proof", JSONB(none_as_null=True))
    )
    op.create_check_constraint(
        "test_resource_dependency_version_complete", "test_resource_reservations", PROOF_CHECK
    )
    op.execute(ATOM_SQL)
    for table in ("test_resource_reservations", "verification_run_versions"):
        op.execute(
            f'CREATE CONSTRAINT TRIGGER test_resource_dependency_required AFTER INSERT ON "{table}" '
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION require_test_resource_dependency_atom()"
        )


def downgrade():
    op.execute(
        "LOCK TABLE test_resource_reservations,verification_run_versions IN SHARE ROW EXCLUSIVE MODE"
    )
    used = op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM test_resource_reservations WHERE fingerprint_version IS NOT NULL "
            "OR dependency_proof IS NOT NULL) OR EXISTS(SELECT 1 FROM verification_run_versions "
            "WHERE input_snapshot ?| ARRAY['resource_fingerprint_version','resource_dependency_proof'])"
        )
    )
    if used:
        raise RuntimeError(
            "Saved versioned resource proof must be retained; destructive downgrade unavailable"
        )
    for table in ("verification_run_versions", "test_resource_reservations"):
        op.execute(f'DROP TRIGGER test_resource_dependency_required ON "{table}"')
    op.execute("DROP FUNCTION require_test_resource_dependency_atom()")
    op.drop_constraint(
        "test_resource_dependency_version_complete", "test_resource_reservations", type_="check"
    )
    op.drop_column("test_resource_reservations", "dependency_proof")
    op.drop_column("test_resource_reservations", "fingerprint_version")
