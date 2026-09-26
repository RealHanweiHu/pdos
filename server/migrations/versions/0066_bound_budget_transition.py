"""Private transitions for a service-reserved model attempt, scoped to one run."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066_bound_budget_transition"
down_revision: str | Sequence[str] | None = "0065_mixed_call_admission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSITION = r"""
CREATE FUNCTION cehub_ai.transition_bound_model_budget(
    wanted_tenant uuid, wanted_run uuid, wanted_attempt uuid,
    wanted_action text, evidence_body text
) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog AS $body$
DECLARE
    prior cehub_ai.budget_journal%ROWTYPE;
    next_row cehub_ai.budget_journal%ROWTYPE;
    event_time timestamptz;
    evidence jsonb;
    evidence_ref text;
    field text;
    total bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('pdos-budget:' || wanted_tenant::text, 0));
    event_time := clock_timestamp();
    IF wanted_action IS NULL OR wanted_action NOT IN ('dispatch', 'unknown', 'cancel', 'settle')
       OR (wanted_action <> 'settle' AND evidence_body IS NOT NULL) THEN
        RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO prior FROM cehub_ai.budget_journal
      WHERE tenant_id = wanted_tenant AND attempt_id = wanted_attempt
        AND run_id = wanted_run ORDER BY revision DESC LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'BUDGET_ATTEMPT_NOT_FOUND' USING ERRCODE = '22023';
    END IF;
    IF prior.call_kind <> 'model' OR prior.request_binding IS NULL THEN
        RAISE EXCEPTION 'BUDGET_REQUEST_BINDING_REQUIRED' USING ERRCODE = '22023';
    END IF;
    next_row := prior;
    IF wanted_action = 'dispatch' THEN
        IF prior.dispatched_at IS NOT NULL THEN
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.reservation_status <> 'reserved' THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        PERFORM 1 FROM cehub_ai.agent_runs
          WHERE tenant_id = wanted_tenant AND id = wanted_run AND status = 'running'
          FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'BUDGET_RUN_NOT_RUNNING' USING ERRCODE = '22023';
        END IF;
        -- Waiting for the run row must not preserve an earlier valid deadline.
        event_time := clock_timestamp();
        PERFORM 1 FROM cehub_ai.budget_lineages
          WHERE tenant_id = wanted_tenant AND id = prior.lineage_id
            AND absolute_deadline > event_time;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'BUDGET_LINEAGE_EXPIRED' USING ERRCODE = '22023';
        END IF;
        next_row.dispatched_at := event_time;
    ELSIF wanted_action = 'unknown' THEN
        IF prior.reservation_status = 'unknown' THEN
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.reservation_status <> 'reserved' OR prior.dispatched_at IS NULL THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        next_row.reservation_status := 'unknown';
    ELSIF wanted_action = 'cancel' THEN
        IF prior.reservation_status = 'cancelled_before_dispatch' THEN
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.reservation_status <> 'reserved' OR prior.dispatched_at IS NOT NULL THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        next_row.reservation_status := 'cancelled_before_dispatch';
        next_row.held_tokens := 0;
        next_row.charged_tokens := 0;
    ELSE
        IF evidence_body IS NULL OR octet_length(evidence_body) > 64000 THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_REQUIRED' USING ERRCODE = '22023';
        END IF;
        BEGIN
            evidence := evidence_body::jsonb;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END;
        IF jsonb_typeof(evidence) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END IF;
        IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(evidence) key)
            IS DISTINCT FROM ARRAY['cache_creation_tokens','cache_read_tokens','error_code',
                 'input_tokens','model_version','output_tokens','request_digest','request_id']
            OR evidence->>'request_digest' IS DISTINCT FROM prior.request_binding->>'request_digest'
        THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END IF;
        FOREACH field IN ARRAY ARRAY['input_tokens','output_tokens',
            'cache_read_tokens','cache_creation_tokens'] LOOP
            IF jsonb_typeof(evidence->field) IS DISTINCT FROM 'number'
               OR (evidence->>field) !~ '^[0-9]{1,18}$' THEN
                RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        FOREACH field IN ARRAY ARRAY['request_id','model_version','error_code'] LOOP
            IF jsonb_typeof(evidence->field) NOT IN ('string', 'null') THEN
                RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
            END IF;
        END LOOP;
        IF (evidence->>'cache_read_tokens')::bigint + (evidence->>'cache_creation_tokens')::bigint
            > (evidence->>'input_tokens')::bigint THEN
            RAISE EXCEPTION 'BUDGET_SETTLEMENT_EVIDENCE_CONFLICT' USING ERRCODE = '22023';
        END IF;
        total := (evidence->>'input_tokens')::bigint + (evidence->>'output_tokens')::bigint;
        evidence_ref := 'provider-usage.v1:sha256:' ||
            encode(sha256(convert_to(evidence_body, 'UTF8')), 'hex');
        IF prior.reservation_status = 'settled' THEN
            IF prior.usage_evidence IS DISTINCT FROM evidence THEN
                RAISE EXCEPTION 'BUDGET_SETTLEMENT_CONFLICT' USING ERRCODE = '22023';
            END IF;
            RETURN jsonb_build_object('row', to_jsonb(prior), 'changed', false,
                                      'dispatch_granted', false);
        END IF;
        IF prior.dispatched_at IS NULL
           OR prior.reservation_status NOT IN ('reserved', 'unknown') THEN
            RAISE EXCEPTION 'BUDGET_TRANSITION_INVALID' USING ERRCODE = '22023';
        END IF;
        next_row.reservation_status := 'settled';
        next_row.charged_tokens := total;
        next_row.held_tokens := 0;
        next_row.reconciliation_ref := evidence_ref;
        next_row.provider_request_id := evidence->>'request_id';
        next_row.usage_evidence := evidence;
    END IF;
    next_row.id := gen_random_uuid();
    next_row.revision := prior.revision + 1;
    next_row.created_at := event_time;
    INSERT INTO cehub_ai.budget_journal SELECT next_row.*;
    RETURN jsonb_build_object('row', to_jsonb(next_row), 'changed', true,
                              'dispatch_granted', wanted_action = 'dispatch');
END
$body$;
REVOKE ALL ON FUNCTION
    cehub_ai.transition_bound_model_budget(uuid, uuid, uuid, text, text) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(TRANSITION)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM cehub_ai.budget_journal "
                "WHERE request_binding IS NOT NULL AND revision > 1)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("refusing downgrade: bound budget transitions exist")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.agent_transition_model_budget(uuid, text, text)")
    op.execute("DROP FUNCTION cehub_ai.transition_bound_model_budget(uuid, uuid, uuid, text, text)")
