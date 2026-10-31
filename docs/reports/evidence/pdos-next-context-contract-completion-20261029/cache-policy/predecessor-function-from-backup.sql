CREATE FUNCTION public.kernel_agreement_atom() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public', 'pg_temp'
    AS $$ BEGIN
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
      RETURN NEW; END $$;


ALTER FUNCTION public.kernel_agreement_atom() OWNER TO pdos_next_owner;
