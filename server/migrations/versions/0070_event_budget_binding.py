"""Freeze approved event-run budgets in the run creation transaction."""

from collections.abc import Sequence
from importlib import import_module

from alembic import op

revision: str = "0070_event_budget_binding"
down_revision: str | Sequence[str] | None = "0069_import_mapping_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Immutable approved N0-02 profiles; never read mutable application files at upgrade.
FREEZE = r"""
CREATE FUNCTION cehub_ai.freeze_event_run_budget() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $body$
DECLARE
    profile_key text := nullif(current_setting('pdos.event_budget_profile', true), '');
    frozen_profile jsonb;
    frozen_digest text;
    lineage_id uuid := gen_random_uuid();
    created timestamptz;
BEGIN
    IF profile_key IS NULL THEN RETURN NEW; END IF;
    IF NEW.status <> 'debouncing' OR NEW.subscription_id IS NULL
       OR NEW.request_id IS NOT NULL OR NEW.requested_by_user_id IS NOT NULL THEN
        RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='BUDGET_EVENT_CREATION_REQUIRED';
    END IF;
    CASE profile_key
        WHEN 'short' THEN
            frozen_profile := '{
  "active_seconds": 120,
  "include_retries_and_seats": true,
  "input_token_limit": 16000,
  "key": "short",
  "lease_seconds": 60,
  "lifetime_seconds": 86400,
  "lineage_parallel_calls": 1,
  "lineage_token_limit": 60000,
  "max_backoff_seconds": 8,
  "min_safety_tokens": 1024,
  "model_call_limit": 3,
  "monetary_limit_microusd": null,
  "next_tool_token_reserve": 2048,
  "output_token_reserve": 2000,
  "renew_seconds": 20,
  "resume_resets_budget": false,
  "tenant_parallel_lineages": 2,
  "tool_call_limit": 8,
  "transient_attempt_limit": 2,
  "version": "candidate.v2",
  "wait_consumes_active_budget": false,
  "window_safety_percent": 5
}'::jsonb;
            frozen_digest := 'fbdccbd869de0ee879922adb8b15e52b9f2c748ac202bd5e782e5fd479508ac5';
        WHEN 'work_package' THEN
            frozen_profile := '{
  "active_seconds": 600,
  "include_retries_and_seats": true,
  "input_token_limit": 32000,
  "key": "work_package",
  "lease_seconds": 60,
  "lifetime_seconds": 604800,
  "lineage_parallel_calls": 1,
  "lineage_token_limit": 240000,
  "max_backoff_seconds": 8,
  "min_safety_tokens": 1024,
  "model_call_limit": 6,
  "monetary_limit_microusd": null,
  "next_tool_token_reserve": 2048,
  "output_token_reserve": 6000,
  "renew_seconds": 20,
  "resume_resets_budget": false,
  "tenant_parallel_lineages": 2,
  "tool_call_limit": 20,
  "transient_attempt_limit": 2,
  "version": "candidate.v2",
  "wait_consumes_active_budget": false,
  "window_safety_percent": 5
}'::jsonb;
            frozen_digest := '38d3921b2d6fee664cd52fc798a43b69fc690907fd87024c3fbf85a685bfc9b4';
        WHEN 'research_discussion' THEN
            frozen_profile := '{
  "active_seconds": 900,
  "include_retries_and_seats": true,
  "input_token_limit": 32000,
  "key": "research_discussion",
  "lease_seconds": 60,
  "lifetime_seconds": 604800,
  "lineage_parallel_calls": 1,
  "lineage_token_limit": 360000,
  "max_backoff_seconds": 8,
  "min_safety_tokens": 1024,
  "model_call_limit": 10,
  "monetary_limit_microusd": null,
  "next_tool_token_reserve": 2048,
  "output_token_reserve": 4000,
  "renew_seconds": 20,
  "resume_resets_budget": false,
  "tenant_parallel_lineages": 2,
  "tool_call_limit": 40,
  "transient_attempt_limit": 2,
  "version": "candidate.v2",
  "wait_consumes_active_budget": false,
  "window_safety_percent": 5
}'::jsonb;
            frozen_digest := '818336b24a1cbf1158a590e25fa8c99a757cc09414987ff3db352898eedbb5fc';
        ELSE RAISE EXCEPTION USING ERRCODE='22023', MESSAGE='BUDGET_APPROVED_PROFILE_REQUIRED';
    END CASE;
    created := clock_timestamp();
    INSERT INTO cehub_ai.budget_lineages
        (id, tenant_id, profile, profile_digest, created_at, absolute_deadline)
    VALUES (lineage_id, NEW.tenant_id, frozen_profile, frozen_digest, created,
            created + make_interval(secs => (frozen_profile->>'lifetime_seconds')::int));
    INSERT INTO cehub_ai.budget_run_links (tenant_id, run_id, lineage_id, created_at)
    VALUES (NEW.tenant_id, NEW.id, lineage_id, created);
    RETURN NEW;
END;
$body$;
REVOKE ALL ON FUNCTION cehub_ai.freeze_event_run_budget() FROM PUBLIC;
CREATE TRIGGER freeze_event_run_budget AFTER INSERT ON cehub_ai.agent_runs
FOR EACH ROW EXECUTE FUNCTION cehub_ai.freeze_event_run_budget();
"""


PREVIOUS_OPEN = import_module("migrations.versions.0065_mixed_call_admission").GUARDED_OPEN
BOUND_OPEN = PREVIOUS_OPEN.replace(
    "    -- Both sides use the same tenant lock",
    """    IF wanted_mode = 'legacy' AND EXISTS (
        SELECT 1 FROM cehub_ai.budget_run_links
        WHERE tenant_id = wanted_tenant AND run_id = wanted_run
    ) THEN
        RETURN QUERY SELECT NULL::uuid, 'MODEL_CALL_BUDGET_REQUIRED'::text; RETURN;
    END IF;
    -- Both sides use the same tenant lock""",
)


def upgrade() -> None:
    op.execute(FREEZE)
    op.execute(BOUND_OPEN)


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
        IF EXISTS (SELECT 1 FROM cehub_ai.budget_run_links) THEN
            RAISE EXCEPTION 'cannot remove event budget binding with persistent budget history';
        END IF;
    END $body$;""")
    op.execute("DROP TRIGGER freeze_event_run_budget ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION cehub_ai.freeze_event_run_budget()")
    op.execute(PREVIOUS_OPEN)
