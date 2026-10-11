"""Require every new Project to be the actual output of a named G0 approval.

These additive guards leave existing source-less rows available to downstream
operations. Only INSERT invokes the transaction-bound G0 derivation assertion;
ordinary project updates retain their existing rules.
"""

SCHEMA_SQL = [
    """
CREATE FUNCTION public.m3_project_g0_insert_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
 actual projects;
 decision proposal_decisions;
 proposal proposals;
 expected_trigger_type text;
 expected_trigger_id uuid;
BEGIN
 SELECT * INTO STRICT actual FROM projects
  WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.id;
 IF actual.g0_decision_id IS NULL THEN
  RAISE EXCEPTION 'new project requires actual approved G0 decision' USING ERRCODE='23514';
 END IF;
 SELECT * INTO decision FROM proposal_decisions
  WHERE tenant_id=actual.tenant_id AND category_id=actual.category_id
   AND id=actual.g0_decision_id;
 -- The predecessor assertion returns early for non-approved decisions and
 -- follows decision.created_project_id. Check the reverse edge first.
 IF decision.id IS NULL OR decision.outcome IS DISTINCT FROM 'approved'
  OR decision.created_project_id IS DISTINCT FROM actual.id
  OR decision.created_product_id IS DISTINCT FROM actual.product_id
  OR decision.project_owner_id IS DISTINCT FROM actual.owner_id THEN
  RAISE EXCEPTION 'project must be the exact approved G0 output' USING ERRCODE='23514';
 END IF;
 SELECT * INTO proposal FROM proposals
  WHERE tenant_id=actual.tenant_id AND category_id=actual.category_id
   AND id=decision.proposal_id;
 IF proposal.id IS NULL THEN
  RAISE EXCEPTION 'project G0 proposal is unavailable' USING ERRCODE='23514';
 END IF;
 expected_trigger_type=CASE
  WHEN proposal.baseline_product_id IS NOT NULL THEN 'parent_product'
  WHEN proposal.entry_kind='customer_request' THEN 'customer_request'
  ELSE 'proposal' END;
 expected_trigger_id=coalesce(proposal.baseline_product_id,proposal.id);
 IF actual.trigger_type IS DISTINCT FROM expected_trigger_type
  OR actual.trigger_id IS DISTINCT FROM expected_trigger_id
  OR NOT EXISTS (
   SELECT 1 FROM project_product_links link
   JOIN definition_revisions definition
    ON definition.tenant_id=link.tenant_id AND definition.category_id=link.category_id
     AND definition.product_id=link.product_id AND definition.id=link.definition_id
   WHERE link.tenant_id=actual.tenant_id AND link.category_id=actual.category_id
    AND link.project_id=actual.id AND link.product_id=actual.product_id
    AND link.definition_id=decision.created_definition_id
    AND link.definition_revision=definition.revision
    AND link.variant_id IS NOT DISTINCT FROM decision.created_variant_id
    AND definition.variant_id IS NOT DISTINCT FROM decision.created_variant_id
    AND definition.g0_decision_id=decision.id
  ) THEN
  RAISE EXCEPTION 'project origin and fixed definition must match actual G0' USING ERRCODE='23514';
 END IF;
 -- This existing assertion owns the named actor, receipt, transaction,
 -- product/variant derivation, frozen submission and definition checks.
 PERFORM m3_g0_derivation_assert(actual.tenant_id,actual.category_id,decision.id);
 RETURN NULL;
END;
$function$
""",
    """
CREATE FUNCTION public.m3_project_source_identity_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id
  OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
  OR NEW.category_id IS DISTINCT FROM OLD.category_id
  OR NEW.product_id IS DISTINCT FROM OLD.product_id
  OR NEW.g0_decision_id IS DISTINCT FROM OLD.g0_decision_id
  OR NEW.trigger_type IS DISTINCT FROM OLD.trigger_type
  OR NEW.trigger_id IS DISTINCT FROM OLD.trigger_id THEN
  RAISE EXCEPTION 'project source identity is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$function$
""",
    """
REVOKE ALL ON FUNCTION public.m3_project_g0_insert_guard(),
 public.m3_project_source_identity_guard()
 FROM PUBLIC, pdos_next_app, pdos_next_auth, pdos_next_dispatch, pdos_agent
""",
    """
CREATE CONSTRAINT TRIGGER m3_project_g0_insert
 AFTER INSERT ON public.projects DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION public.m3_project_g0_insert_guard()
""",
    """
CREATE TRIGGER m3_project_source_identity
 BEFORE UPDATE ON public.projects
 FOR EACH ROW EXECUTE FUNCTION public.m3_project_source_identity_guard()
""",
]

DOWNGRADE_SQL = [
    "DROP TRIGGER m3_project_source_identity ON public.projects",
    "DROP TRIGGER m3_project_g0_insert ON public.projects",
    "DROP FUNCTION public.m3_project_source_identity_guard()",
    "DROP FUNCTION public.m3_project_g0_insert_guard()",
]
