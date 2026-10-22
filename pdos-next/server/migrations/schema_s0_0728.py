"""Immutable stored material for the three direct T1 confirmation owners."""

FUNCTION = """CREATE FUNCTION public.protect_direct_confirmation()
RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER
SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  old_scoped boolean := OLD.operation IN
    ('quality.issue.triage','quality.issue.containment.record','test.run.start');
  new_scoped boolean := false;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    new_scoped := NEW.operation IN
      ('quality.issue.triage','quality.issue.containment.record','test.run.start');
  END IF;
  IF NOT (old_scoped OR new_scoped) THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Direct confirmation must be retained' USING ERRCODE = '23514';
  END IF;
  IF NOT (old_scoped AND new_scoped)
    OR (to_jsonb(NEW) - 'consumed') IS DISTINCT FROM (to_jsonb(OLD) - 'consumed')
    OR (NEW.consumed IS DISTINCT FROM OLD.consumed
      AND NOT (OLD.consumed IS FALSE AND NEW.consumed IS TRUE)) THEN
    RAISE EXCEPTION 'Direct confirmation only permits original material and consumption'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END
$function$;
"""

TRIGGER = """CREATE TRIGGER direct_confirmation_immutable
BEFORE UPDATE OR DELETE ON public.confirmations
FOR EACH ROW EXECUTE FUNCTION public.protect_direct_confirmation();
"""

SCHEMA_SQL = (
    FUNCTION,
    "ALTER FUNCTION public.protect_direct_confirmation() OWNER TO pdos_next_owner",
    "REVOKE ALL ON FUNCTION public.protect_direct_confirmation() FROM PUBLIC,pdos_agent",
    TRIGGER,
)
