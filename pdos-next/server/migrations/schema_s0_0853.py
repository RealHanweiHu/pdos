"""Typed named agreement cache permission, preserving existing unknown decisions."""

# Exact pg_get_functiondef from the reviewed pre-0853 backup, including the
# subsequent search_path hardening. Never substitute the original 0701 source.
PREVIOUS_ATOM = """CREATE OR REPLACE FUNCTION public.kernel_agreement_atom()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM action_receipts r JOIN audit_entries a ON a.receipt_id=r.id
        JOIN outbox_events o ON o.receipt_id=r.id
        WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id
        AND r.operation='provider.agreement.register' AND r.actor_id=NEW.registered_by
        AND r.requester_id=NEW.registered_by AND r.run_id IS NULL
        AND r.subject_id=NEW.id AND r.subject_revision=NEW.revision
        AND r.result->>'tier'='T2' AND r.result->>'decision'='批准'
        AND a.tenant_id=r.tenant_id AND o.tenant_id=r.tenant_id
        AND o.type='provider.agreement_registered')
      THEN RAISE EXCEPTION 'Named agreement receipt atom required'; END IF;
      RETURN NEW; END $function$
"""

CACHE_ATOM = PREVIOUS_ATOM.replace(
    "AND o.type='provider.agreement_registered')",
    """AND o.type='provider.agreement_registered'
        AND ((NEW.prompt_cache_allowed IS NULL AND NOT (r.result ? 'prompt_cache_allowed'))
          OR (NEW.prompt_cache_allowed IS NOT NULL
            AND r.result->'prompt_cache_allowed'=to_jsonb(NEW.prompt_cache_allowed))))""",
)

PREVIOUS_FUNCTIONS = {"kernel_agreement_atom()": PREVIOUS_ATOM}
NATIVE_FUNCTIONS = {"kernel_agreement_atom()": CACHE_ATOM}

UP_SQL = (
    "LOCK TABLE public.provider_data_agreements IN ACCESS EXCLUSIVE MODE",
    "ALTER TABLE public.provider_data_agreements ADD COLUMN prompt_cache_allowed boolean",
    CACHE_ATOM,
)

DOWN_SQL = (
    "LOCK TABLE public.provider_data_agreements IN ACCESS EXCLUSIVE MODE",
    """DO $$ BEGIN
IF EXISTS(SELECT 1 FROM public.provider_data_agreements WHERE prompt_cache_allowed IS NOT NULL)
THEN RAISE EXCEPTION 'Retained named prompt cache decisions prohibit downgrade'; END IF;
END $$""",
    PREVIOUS_ATOM,
    "ALTER TABLE public.provider_data_agreements DROP COLUMN prompt_cache_allowed",
)
