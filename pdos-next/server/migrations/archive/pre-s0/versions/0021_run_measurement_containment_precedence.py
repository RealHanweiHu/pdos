"""Parenthesize both JSON operands of the retained-measurement containment guard."""

# ruff: noqa: E501 -- frozen predecessor/successor SQL kept byte exact.
from alembic import op

revision = "next_0021"
down_revision = "next_0020"
branch_labels = None
depends_on = None

OLD_SQL = """CREATE OR REPLACE FUNCTION public.protect_verification_run_binding()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
      DECLARE identity verification_run_identities%ROWTYPE; prior verification_run_versions%ROWTYPE;
      BEGIN
        SELECT * INTO identity FROM verification_run_identities WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
        IF identity.id IS NULL OR ROW(NEW.product_id,NEW.project_id,NEW.build_id,NEW.request_id,NEW.owner_id,NEW.visibility)
          IS DISTINCT FROM ROW(identity.product_id,identity.project_id,identity.build_id,identity.request_id,identity.owner_id,identity.visibility)
          OR NEW.run_snapshot->>'id'<>NEW.run_id::text OR (NEW.run_snapshot->>'revision')::int<>NEW.revision OR NEW.run_snapshot->>'status'<>NEW.status THEN
          RAISE EXCEPTION 'Run version must retain exact identity and snapshot'; END IF;
        IF NEW.revision>1 THEN
          SELECT * INTO prior FROM verification_run_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.previous_run_version_id;
          IF prior.id IS NULL OR ROW(NEW.request_version_id,NEW.request_revision,NEW.plan_sha256,NEW.execution_plan)
            IS DISTINCT FROM ROW(prior.request_version_id,prior.request_revision,prior.plan_sha256,prior.execution_plan)
            OR NEW.run_snapshot->'coverage' IS DISTINCT FROM prior.run_snapshot->'coverage'
            OR NEW.run_snapshot->'items' IS DISTINCT FROM prior.run_snapshot->'items'
            OR NEW.run_snapshot->'samples' IS DISTINCT FROM prior.run_snapshot->'samples'
            OR NEW.previous_revision<>prior.revision OR NEW.revision<>prior.revision+1
            OR NEW.run_snapshot->'scope' IS DISTINCT FROM prior.run_snapshot->'scope'
            OR NEW.run_snapshot->'build' IS DISTINCT FROM prior.run_snapshot->'build'
            OR NEW.run_snapshot->>'request_id' IS DISTINCT FROM prior.run_snapshot->>'request_id'
            OR NEW.input_snapshot->'plan_binding' IS DISTINCT FROM prior.input_snapshot->'plan_binding'
            OR (NEW.revision>2 AND (
              NEW.run_snapshot->'actual_start' IS DISTINCT FROM prior.run_snapshot->'actual_start'
              OR NEW.run_snapshot->'execution' IS DISTINCT FROM prior.run_snapshot->'execution'
              OR NEW.input_snapshot->'reservation' IS DISTINCT FROM prior.input_snapshot->'reservation'
              OR NOT COALESCE(NEW.run_snapshot->'measurements' @> prior.run_snapshot->'measurements',false)))
     THEN RAISE EXCEPTION 'Started Run cannot rewrite fixed plan or coverage'; END IF;
        END IF;
        IF NEW.status='running' AND ((NEW.run_snapshot->'actual_start'->>'occurred_at')::timestamptz>clock_timestamp()
          OR (NEW.run_snapshot->'actual_start'->>'occurred_at')::timestamptz<(NEW.execution_plan->'window'->>'start')::timestamptz
          OR (NEW.run_snapshot->'actual_start'->>'occurred_at')::timestamptz>=(NEW.execution_plan->'window'->>'finish')::timestamptz) THEN
          RAISE EXCEPTION 'Actual test start must lie within fixed resource window'; END IF;
        RETURN NEW;
      END $function$
"""
NEW_SQL = """CREATE OR REPLACE FUNCTION public.protect_verification_run_binding()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
      DECLARE identity verification_run_identities%ROWTYPE; prior verification_run_versions%ROWTYPE;
      BEGIN
        SELECT * INTO identity FROM verification_run_identities WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
        IF identity.id IS NULL OR ROW(NEW.product_id,NEW.project_id,NEW.build_id,NEW.request_id,NEW.owner_id,NEW.visibility)
          IS DISTINCT FROM ROW(identity.product_id,identity.project_id,identity.build_id,identity.request_id,identity.owner_id,identity.visibility)
          OR NEW.run_snapshot->>'id'<>NEW.run_id::text OR (NEW.run_snapshot->>'revision')::int<>NEW.revision OR NEW.run_snapshot->>'status'<>NEW.status THEN
          RAISE EXCEPTION 'Run version must retain exact identity and snapshot'; END IF;
        IF NEW.revision>1 THEN
          SELECT * INTO prior FROM verification_run_versions WHERE tenant_id=NEW.tenant_id AND id=NEW.previous_run_version_id;
          IF prior.id IS NULL OR ROW(NEW.request_version_id,NEW.request_revision,NEW.plan_sha256,NEW.execution_plan)
            IS DISTINCT FROM ROW(prior.request_version_id,prior.request_revision,prior.plan_sha256,prior.execution_plan)
            OR NEW.run_snapshot->'coverage' IS DISTINCT FROM prior.run_snapshot->'coverage'
            OR NEW.run_snapshot->'items' IS DISTINCT FROM prior.run_snapshot->'items'
            OR NEW.run_snapshot->'samples' IS DISTINCT FROM prior.run_snapshot->'samples'
            OR NEW.previous_revision<>prior.revision OR NEW.revision<>prior.revision+1
            OR NEW.run_snapshot->'scope' IS DISTINCT FROM prior.run_snapshot->'scope'
            OR NEW.run_snapshot->'build' IS DISTINCT FROM prior.run_snapshot->'build'
            OR NEW.run_snapshot->>'request_id' IS DISTINCT FROM prior.run_snapshot->>'request_id'
            OR NEW.input_snapshot->'plan_binding' IS DISTINCT FROM prior.input_snapshot->'plan_binding'
            OR (NEW.revision>2 AND (
              NEW.run_snapshot->'actual_start' IS DISTINCT FROM prior.run_snapshot->'actual_start'
              OR NEW.run_snapshot->'execution' IS DISTINCT FROM prior.run_snapshot->'execution'
              OR NEW.input_snapshot->'reservation' IS DISTINCT FROM prior.input_snapshot->'reservation'
              OR NOT COALESCE((NEW.run_snapshot->'measurements') @> (prior.run_snapshot->'measurements'),false)))
     THEN RAISE EXCEPTION 'Started Run cannot rewrite fixed plan or coverage'; END IF;
        END IF;
        IF NEW.status='running' AND ((NEW.run_snapshot->'actual_start'->>'occurred_at')::timestamptz>clock_timestamp()
          OR (NEW.run_snapshot->'actual_start'->>'occurred_at')::timestamptz<(NEW.execution_plan->'window'->>'start')::timestamptz
          OR (NEW.run_snapshot->'actual_start'->>'occurred_at')::timestamptz>=(NEW.execution_plan->'window'->>'finish')::timestamptz) THEN
          RAISE EXCEPTION 'Actual test start must lie within fixed resource window'; END IF;
        RETURN NEW;
      END $function$
"""


def upgrade():
    op.execute(NEW_SQL)


def downgrade():
    op.execute(OLD_SQL)
