"""Freeze explicitly qualified event loop policy at run creation."""

from collections.abc import Sequence

from alembic import op

revision: str = "0078_event_loop_binding"
down_revision: str | Sequence[str] | None = "0077_tool_dispatch_intents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = r"""CREATE OR REPLACE FUNCTION cehub_ai.freeze_event_loop_binding()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $body$
DECLARE configured text; binding jsonb;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF NEW.loop_binding IS DISTINCT FROM OLD.loop_binding THEN
   RAISE EXCEPTION 'event loop binding is immutable' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
 END IF;
 IF NEW.loop_binding IS NOT NULL THEN
  RAISE EXCEPTION 'event loop binding must come from creation policy' USING ERRCODE='42501';
 END IF;
 configured:=nullif(current_setting('pdos.event_loop_binding',true),'');
 IF configured IS NULL THEN RETURN NEW; END IF;
 binding:=configured::jsonb;
 IF NEW.status<>'debouncing' OR NEW.request_id IS NOT NULL OR NEW.subscription_id IS NULL
   OR nullif(current_setting('pdos.event_budget_profile',true),'') IS NULL
   OR binding->>'mode' IS DISTINCT FROM 'bounded_tools.v1'
   OR (binding->>'qualification_sha256' ~ '^[a-f0-9]{64}$') IS NOT TRUE
   OR binding#>>'{qualification,status}' IS DISTINCT FROM 'passed'
   OR (binding#>>'{qualification,runtime_digest}' ~ '^[a-f0-9]{64}$') IS NOT TRUE THEN
  RAISE EXCEPTION 'event loop creation policy is invalid' USING ERRCODE='22023';
 END IF;
 NEW.loop_binding:=binding;
 RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.freeze_event_loop_binding() FROM PUBLIC;
"""

READ = r"""CREATE OR REPLACE FUNCTION cehub_ai.read_agent_loop_binding()
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE r cehub_ai.agent_runs%ROWTYPE;
 token uuid:=nullif(current_setting('pdos.agent_lease_token',true),'')::uuid;
BEGIN
 SELECT * INTO r FROM cehub_ai.agent_runs
  WHERE id=nullif(current_setting('pdos.agent_run_id',true),'')::uuid;
 IF NOT FOUND OR NOT cehub_ai.agent_lease_is_current(r.id,token) THEN
  RAISE EXCEPTION 'Agent loop binding lease is invalid' USING ERRCODE='42501';
 END IF;
 RETURN r.loop_binding;
END $body$;
REVOKE ALL ON FUNCTION cehub_ai.read_agent_loop_binding() FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute("ALTER TABLE cehub_ai.agent_runs ADD COLUMN loop_binding jsonb")
    op.execute(FUNCTION)
    op.execute(READ)
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent') THEN
        GRANT EXECUTE ON FUNCTION cehub_ai.read_agent_loop_binding() TO pdos_agent;
      END IF;
    END $body$;""")
    op.execute("""CREATE TRIGGER freeze_event_loop_binding BEFORE INSERT OR UPDATE
      ON cehub_ai.agent_runs FOR EACH ROW EXECUTE FUNCTION cehub_ai.freeze_event_loop_binding();""")


def downgrade() -> None:
    op.execute("""DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM cehub_ai.agent_runs WHERE loop_binding IS NOT NULL) THEN
        RAISE EXCEPTION 'cannot remove persistent event loop binding history';
      END IF;
    END $body$;""")
    op.execute("DROP TRIGGER freeze_event_loop_binding ON cehub_ai.agent_runs")
    op.execute("DROP FUNCTION IF EXISTS cehub_ai.read_agent_loop_binding()")
    op.execute("DROP FUNCTION cehub_ai.freeze_event_loop_binding()")
    op.execute("ALTER TABLE cehub_ai.agent_runs DROP COLUMN loop_binding")
