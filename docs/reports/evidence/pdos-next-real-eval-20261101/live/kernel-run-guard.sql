CREATE OR REPLACE FUNCTION public.kernel_run_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
    DECLARE s agent_sessions; BEGIN
      IF TG_OP='UPDATE' THEN
        IF NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id OR NEW.session_id<>OLD.session_id
        OR NEW.requester_id<>OLD.requester_id OR NEW.writer_id<>OLD.writer_id
        OR NEW.category_id IS DISTINCT FROM OLD.category_id
        OR NEW.product_id IS DISTINCT FROM OLD.product_id OR NEW.proposal_id IS DISTINCT FROM OLD.proposal_id
        OR NEW.project_id IS DISTINCT FROM OLD.project_id
        OR NEW.goal<>OLD.goal OR NEW.trigger<>OLD.trigger OR NEW.intent_key<>OLD.intent_key
        OR NEW.intent_digest<>OLD.intent_digest OR NEW.private_context IS DISTINCT FROM OLD.private_context
        OR NEW.data_categories IS DISTINCT FROM OLD.data_categories
        OR NEW.customer_identities IS DISTINCT FROM OLD.customer_identities
        OR NEW.cancel_epoch<OLD.cancel_epoch OR ((OLD.state IN ('completed','partial','failed','cancelled') AND NEW IS DISTINCT FROM OLD AND
          (NEW.reverted_at IS NULL OR (to_jsonb(NEW)-ARRAY['cancel_epoch','reverted_at','reverted_by','revert_receipt_id'])
          IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['cancel_epoch','reverted_at','reverted_by','revert_receipt_id'])))
          OR (OLD.reverted_at IS NOT NULL AND NEW IS DISTINCT FROM OLD))
        THEN RAISE EXCEPTION 'Kernel run binding immutable'; END IF;
      ELSE
        SELECT * INTO s FROM agent_sessions WHERE tenant_id=NEW.tenant_id AND id=NEW.session_id;
        IF s.id IS NULL OR s.owner_id<>NEW.requester_id OR s.category_id IS DISTINCT FROM NEW.category_id
        OR s.product_id IS DISTINCT FROM NEW.product_id OR COALESCE((SELECT b.proposal_id FROM public.agent_session_bindings b WHERE b.tenant_id=s.tenant_id AND b.session_id=s.id), s.proposal_id) IS DISTINCT FROM NEW.proposal_id
        OR s.project_id IS DISTINCT FROM NEW.project_id
        OR NOT EXISTS(SELECT 1 FROM principals WHERE tenant_id=NEW.tenant_id AND id=NEW.writer_id
                      AND kind='agent' AND active) THEN RAISE EXCEPTION 'Kernel run scope invalid'; END IF;
      END IF;
      IF NEW.held_tokens<0 OR NEW.used_tokens<0 OR NEW.token_limit<1 OR NEW.cancel_epoch<0
      OR NEW.state NOT IN ('queued','running','waiting_input','completed','partial','failed','cancelled')
      THEN RAISE EXCEPTION 'Kernel state invalid'; END IF;
      RETURN NEW;
    END $function$
