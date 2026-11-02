"""Allow explicitly scoped Runs and preserve prior request result clocks."""

import sqlalchemy as sa
from alembic import op

revision = "s0_0773"
down_revision = "s0_0772"
branch_labels = None
depends_on = None

REQUEST_TABLE = "verification_formal_requests"
HANDOFF_TABLE = "verification_handoff_facts"
OLD_HANDOFF_STATUS = "status IN ('offered','accepted')"
NEW_HANDOFF_STATUS = "status IN ('offered','accepted','scheduled','executing')"
REQUEST_UNIQUES = (
    (
        "verification_run_identities",
        "verification_run_identities_tenant_id_product_id_request_id_key",
        "ix_verification_run_identities_request",
    ),
    (
        "verification_current_runs",
        "verification_current_runs_tenant_id_product_id_request_id_key",
        "ix_verification_current_runs_request",
    ),
)
OLD_STATE_OPERATIONS = (
    "(status<>'scheduled' OR operation='verification.schedule.promise') AND "
    "(status<>'executing' OR operation IN ('test.run.start','test.results.import',"
    "'test.run.review','test.disposition.decide')) AND "
    "(status<>'reported' OR operation IN ('test.results.import','test.run.review',"
    "'test.disposition.decide')) AND "
    "(status<>'disposed' OR operation='test.disposition.decide')"
)
NEW_STATE_OPERATIONS = (
    "(status<>'scheduled' OR operation IN ('verification.schedule.promise',"
    "'verification.handoff.accept','verification.handoff.return')) AND "
    "(status<>'executing' OR operation IN ('verification.schedule.promise',"
    "'verification.handoff.accept','verification.handoff.return',"
    "'test.run.start','test.results.import',"
    "'test.run.review','test.disposition.decide')) AND "
    "(status<>'reported' OR operation IN ('test.results.import','test.run.review',"
    "'test.disposition.decide')) AND "
    "(status<>'disposed' OR operation='test.disposition.decide')"
)
OLD_START_CLOCKS = (
    "operation <> 'test.run.start' OR COALESCE("
    "request_snapshot->'timeline'->'preliminary_result'='null'::jsonb AND "
    "request_snapshot->'timeline'->'final_result'='null'::jsonb AND "
    "request_snapshot->'timeline'->'disposed'='null'::jsonb, false)"
)

CLOCK_GUARD = """CREATE FUNCTION public.verification_request_result_clock_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE
  previous public.verification_formal_requests%ROWTYPE;
  clock_name text;
  expected_clock jsonb;
BEGIN
  IF NEW.operation IN ('test.results.import','test.run.review','test.disposition.decide') THEN
    RETURN NEW;
  END IF;
  IF NEW.revision > 1 THEN
    SELECT * INTO previous FROM public.verification_formal_requests p
      WHERE p.tenant_id=NEW.tenant_id AND p.category_id=NEW.category_id
        AND p.product_id=NEW.product_id AND p.project_id=NEW.project_id
        AND p.build_id=NEW.build_id AND p.request_id=NEW.request_id
        AND p.id=NEW.previous_request_id AND p.revision=NEW.previous_revision;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Non-result request requires its exact previous scope'
        USING ERRCODE='23514';
    END IF;
  END IF;
  FOREACH clock_name IN ARRAY ARRAY['preliminary_result','final_result','disposed'] LOOP
    expected_clock := CASE WHEN NEW.revision=1 THEN 'null'::jsonb
      ELSE previous.request_snapshot->'timeline'->clock_name END;
    IF NEW.request_snapshot->'timeline'->clock_name IS DISTINCT FROM expected_clock THEN
      RAISE EXCEPTION 'Non-result operation must preserve prior request result clocks'
        USING ERRCODE='23514';
    END IF;
  END LOOP;
  RETURN NEW;
END $$"""


def _state_constraint():
    """Resolve the baseline's unnamed check without assuming PostgreSQL suffixes."""
    candidates = [
        row["name"]
        for row in sa.inspect(op.get_bind()).get_check_constraints(REQUEST_TABLE)
        if all(
            token in row["sqltext"]
            for token in ("status", "operation", "scheduled", "executing", "reported", "disposed")
        )
    ]
    if len(candidates) != 1:
        raise RuntimeError("Expected the one verification request state/operation constraint")
    return candidates[0]


def _replace_state_constraint(expression):
    name = _state_constraint()
    op.drop_constraint(name, REQUEST_TABLE, type_="check")
    op.create_check_constraint(name, REQUEST_TABLE, expression)


def _replace_handoff_status(expression):
    candidates = [
        row["name"]
        for row in sa.inspect(op.get_bind()).get_check_constraints(HANDOFF_TABLE)
        if all(token in row["sqltext"] for token in ("status", "offered", "accepted"))
    ]
    if len(candidates) != 1:
        raise RuntimeError("Expected the one verification handoff status constraint")
    name = candidates[0]
    op.drop_constraint(name, HANDOFF_TABLE, type_="check")
    op.create_check_constraint(name, HANDOFF_TABLE, expression)


def upgrade():
    for table, constraint, index in REQUEST_UNIQUES:
        op.drop_constraint(constraint, table, type_="unique")
        op.create_index(index, table, ["tenant_id", "product_id", "request_id"])
    _replace_state_constraint(NEW_STATE_OPERATIONS)
    _replace_handoff_status(NEW_HANDOFF_STATUS)
    op.drop_constraint("ck_test_start_no_result_clocks", REQUEST_TABLE, type_="check")
    op.execute(CLOCK_GUARD)
    op.execute(
        "REVOKE ALL ON FUNCTION public.verification_request_result_clock_guard() "
        "FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch"
    )
    op.execute(
        "CREATE TRIGGER verification_request_result_clocks BEFORE INSERT "
        "ON verification_formal_requests FOR EACH ROW "
        "EXECUTE FUNCTION public.verification_request_result_clock_guard()"
    )


def downgrade():
    # Every new semantic shape must be representable by the old host. Keep all
    # immutable facts; an incompatible history makes downgrade explicitly fail.
    op.execute(
        "LOCK TABLE verification_run_identities,verification_current_runs,"
        "verification_formal_requests,verification_run_versions,verification_handoff_facts "
        "IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM verification_run_identities
          GROUP BY tenant_id,product_id,request_id HAVING count(*)>1)
        OR EXISTS (SELECT 1 FROM verification_current_runs
          GROUP BY tenant_id,product_id,request_id HAVING count(*)>1)
        OR EXISTS (SELECT 1 FROM verification_formal_requests
          WHERE NOT ({OLD_STATE_OPERATIONS}) OR NOT ({OLD_START_CLOCKS}))
        OR EXISTS (SELECT 1 FROM verification_handoff_facts
          WHERE NOT ({OLD_HANDOFF_STATUS})) THEN
        RAISE EXCEPTION 'Scoped verification history requires s0_0773'
          USING ERRCODE='23514';
      END IF;
      IF EXISTS (
        SELECT 1 FROM verification_run_versions v
        JOIN verification_formal_requests origin ON origin.tenant_id=v.tenant_id
          AND origin.product_id=v.product_id AND origin.request_id=v.request_id
          AND origin.id=v.request_version_id AND origin.revision=v.request_revision
        JOIN verification_current_formal_requests p ON p.tenant_id=v.tenant_id
          AND p.product_id=v.product_id AND p.request_id=v.request_id
        JOIN verification_formal_requests latest ON latest.tenant_id=p.tenant_id
          AND latest.product_id=p.product_id AND latest.request_id=p.request_id
          AND latest.id=p.request_version_id AND latest.revision=p.request_revision
        CROSS JOIN LATERAL (
          SELECT COALESCE(jsonb_agg(DISTINCT c.value),'[]'::jsonb) AS coverage
          FROM jsonb_array_elements(origin.request_snapshot->'acceptances') a
          CROSS JOIN LATERAL jsonb_array_elements(a.value->'coverage') c
        ) accepted_origin
        CROSS JOIN LATERAL (
          SELECT COALESCE(jsonb_agg(DISTINCT c.value),'[]'::jsonb) AS coverage
          FROM jsonb_array_elements(latest.request_snapshot->'acceptances') a
          CROSS JOIN LATERAL jsonb_array_elements(a.value->'coverage') c
        ) accepted_latest
        WHERE (
          (v.run_snapshot->'coverage') @> accepted_origin.coverage
          AND accepted_origin.coverage @> (v.run_snapshot->'coverage')
          AND (v.run_snapshot->'coverage') @> accepted_latest.coverage
          AND accepted_latest.coverage @> (v.run_snapshot->'coverage')) IS NOT TRUE
      ) THEN
        RAISE EXCEPTION 'Partial accepted Run coverage requires s0_0773'
          USING ERRCODE='23514';
      END IF;
    END $$""")
    op.execute("DROP TRIGGER verification_request_result_clocks ON verification_formal_requests")
    op.execute("DROP FUNCTION public.verification_request_result_clock_guard()")
    op.create_check_constraint("ck_test_start_no_result_clocks", REQUEST_TABLE, OLD_START_CLOCKS)
    _replace_state_constraint(OLD_STATE_OPERATIONS)
    _replace_handoff_status(OLD_HANDOFF_STATUS)
    for table, constraint, index in reversed(REQUEST_UNIQUES):
        op.drop_index(index, table_name=table)
        op.create_unique_constraint(constraint, table, ["tenant_id", "product_id", "request_id"])
