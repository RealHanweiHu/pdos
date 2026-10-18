"""Narrow metadata dispatch and shared causal reservations, with no source content."""

# ruff: noqa: E501 -- SQL predicates remain readable as atomic clauses.

from .service_storage import _function

ACTIVE = """
 SELECT g.tenant_id,g.category_id,g.owner_id,g.writer_id,g.id FROM public.automation_service_grants g
 JOIN public.automation_rule_currents cur ON cur.tenant_id=g.tenant_id AND cur.rule_id=g.rule_id
 WHERE g.tenant_id=t AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND cur.state='active' AND cur.published_version_id=g.published_version_id
  AND NOT EXISTS(SELECT 1 FROM public.automation_service_attempts stopped WHERE stopped.tenant_id=t
   AND stopped.service_grant_id=g.id AND stopped.origin->>'kind'='lifecycle' AND stopped.state='suppressed')
 ORDER BY g.created_at,g.id
"""
# Includes expired/revoked grants once, so their technical stop is durably recorded.
EVENT_TARGETS = """
 SELECT g.tenant_id,g.category_id,g.owner_id,g.writer_id,g.id FROM public.automation_service_grants g
 JOIN public.automation_rule_currents cur ON cur.tenant_id=g.tenant_id AND cur.rule_id=g.rule_id
 JOIN public.automation_rule_versions v ON v.tenant_id=g.tenant_id AND v.id=g.published_version_id
 JOIN public.outbox_events e ON e.tenant_id=g.tenant_id AND e.category_id=g.category_id
 JOIN public.action_receipts receipt ON receipt.tenant_id=e.tenant_id AND receipt.id=e.receipt_id
 WHERE g.tenant_id=t AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND e.id=event_ref AND e.lease_id=lease_ref AND e.lease_until>statement_timestamp() AND e.delivered_at IS NULL
  AND e.schema_version=1 AND cur.state='active' AND cur.published_version_id=g.published_version_id
  AND v.spec->>'trigger_kind'='domain_event' AND (v.spec#>'{trigger_config,event_types}') ? e.type
  AND ((v.spec#>>'{trigger_config,subject_id}') IS NULL OR (v.spec#>>'{trigger_config,subject_id}')::uuid=e.subject_id)
  AND (v.spec->>'product_id' IS NULL OR (v.spec->>'product_id')::uuid=receipt.product_id)
  AND NOT EXISTS(SELECT 1 FROM public.automation_service_attempts stopped WHERE stopped.tenant_id=t
    AND stopped.service_grant_id=g.id AND stopped.origin->>'kind'='lifecycle' AND stopped.state='suppressed')
 ORDER BY g.id
"""
PENDING = """
 SELECT r.tenant_id,r.category_id,CASE WHEN r.trigger='automation_service' THEN r.writer_id ELSE r.requester_id END,
  r.requester_id,r.id FROM public.agent_runs r
 WHERE r.tenant_id=t AND t=nullif(current_setting('pdos.tenant_id',true),'')::uuid
  AND r.state='queued' AND r.reverted_at IS NULL
  AND (r.trigger<>'automation_service' OR EXISTS(SELECT 1 FROM public.automation_service_attempts a
   JOIN public.automation_service_grants g ON g.tenant_id=a.tenant_id AND g.id=a.service_grant_id
   WHERE a.tenant_id=t AND a.run_id=r.id AND a.state='admitted' AND a.owner_id=r.requester_id AND a.writer_id=r.writer_id))
 ORDER BY r.created_at,r.id LIMIT LEAST(GREATEST(page_limit,1),200)
"""
PARENT = """
DECLARE g public.automation_service_grants; e public.outbox_events;
BEGIN
 SELECT * INTO STRICT g FROM public.automation_service_grants WHERE id=grant_ref AND tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid;
 IF NOT public.automation_service_identity(g.tenant_id,g.owner_id,g.writer_id)
  OR NOT public.category_access(g.tenant_id,g.category_id,false) THEN RAISE EXCEPTION 'Service event scope invalid'; END IF;
 SELECT * INTO STRICT e FROM public.outbox_events WHERE id=event_ref AND tenant_id=g.tenant_id AND category_id=g.category_id;
 -- Metadata only, and only after the source receipt is visible to the caller.
 IF NOT EXISTS(SELECT 1 FROM public.action_receipts receipt WHERE receipt.tenant_id=g.tenant_id AND receipt.id=e.receipt_id
  AND (receipt.visibility='category' OR receipt.requester_id=g.owner_id OR EXISTS(
   SELECT 1 FROM public.object_audiences audience WHERE audience.tenant_id=g.tenant_id AND audience.category_id=g.category_id
    AND audience.object_type='action_receipts' AND audience.subject_id=receipt.id AND audience.owner_id=receipt.requester_id AND audience.principal_id=g.owner_id))
  AND (receipt.product_id IS NULL OR EXISTS(SELECT 1 FROM public.products product WHERE product.tenant_id=g.tenant_id
   AND product.id=receipt.product_id AND product.category_id=g.category_id AND (product.visibility='category' OR product.owner_id=g.owner_id OR EXISTS(
    SELECT 1 FROM public.object_audiences audience WHERE audience.tenant_id=g.tenant_id AND audience.category_id=g.category_id
    AND audience.object_type='products' AND audience.subject_id=product.id AND audience.owner_id=product.owner_id AND audience.principal_id=g.owner_id)))))
 THEN RAISE EXCEPTION 'Service event receipt unavailable'; END IF;
 RETURN QUERY SELECT a.chain_id,a.depth,a.run_id,a.rule_id FROM public.action_receipts r
 JOIN public.automation_service_attempts a ON a.tenant_id=r.tenant_id AND a.run_id=r.agent_run_id AND a.state='admitted'
 WHERE r.tenant_id=g.tenant_id AND r.id=e.receipt_id;
END
"""
CHAIN_RESERVE = """
DECLARE a public.automation_service_attempts; chain public.automation_causal_chains; used_cost numeric; used_in numeric; used_out numeric; used_calls bigint;
BEGIN
 SELECT * INTO STRICT a FROM public.automation_service_attempts WHERE run_id=run_ref
  AND tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND state='admitted';
 IF NOT public.automation_service_identity(a.tenant_id,a.owner_id,a.writer_id)
  OR NOT public.category_access(a.tenant_id,a.category_id,false)
  OR NOT EXISTS(SELECT 1 FROM public.agent_runs r WHERE r.tenant_id=a.tenant_id AND r.id=run_ref
    AND r.requester_id=a.owner_id AND r.writer_id=a.writer_id AND r.trigger='automation_service')
  OR extra_cost<0 OR extra_in<0 OR extra_out<0 THEN RAISE EXCEPTION 'Service chain reservation requires actual Run identity'; END IF;
 PERFORM 1 FROM public.categories WHERE tenant_id=a.tenant_id AND id=a.category_id FOR UPDATE;
 PERFORM pg_advisory_xact_lock(hashtextextended('automation-chain:'||a.chain_id,0));
 SELECT * INTO STRICT chain FROM public.automation_causal_chains WHERE tenant_id=a.tenant_id AND id=a.chain_id;
 SELECT coalesce(sum(CASE WHEN c.cost_state='reserved' THEN c.cost_reserved_micro_usd ELSE c.cost_charged_micro_usd END),0),
  coalesce(sum(CASE WHEN c.cost_state='reserved' THEN c.input_token_reservation ELSE c.actual_input_tokens END),0),
  coalesce(sum(CASE WHEN c.cost_state='reserved' THEN c.output_token_reservation ELSE c.actual_output_tokens END),0),count(*)
 INTO used_cost,used_in,used_out,used_calls FROM public.agent_tool_calls c
 JOIN public.automation_service_attempts child ON child.tenant_id=c.tenant_id AND child.run_id=c.run_id
 WHERE child.tenant_id=a.tenant_id AND child.chain_id=a.chain_id AND child.state='admitted' AND c.cost_state<>'unmetered';
 RETURN used_cost+extra_cost<=(chain.budget->>'limit_micro_usd')::bigint
  AND used_in+extra_in<=(chain.budget->>'input_token_limit')::bigint
  AND used_out+extra_out<=(chain.budget->>'output_token_limit')::bigint
  AND used_calls+1<=(chain.budget->>'call_limit')::bigint;
END
"""


def definitions():
    refs = "TABLE(tenant_id uuid,category_id uuid,owner_id uuid,writer_id uuid,grant_id uuid)"
    return (
        _function("automation_active_grants", "t uuid", ACTIVE, refs, language="sql"),
        _function(
            "automation_event_targets",
            "t uuid,event_ref uuid,lease_ref uuid",
            EVENT_TARGETS,
            refs,
            language="sql",
        ),
        _function(
            "kernel_pending_run_references",
            "t uuid,page_limit integer",
            PENDING,
            "TABLE(tenant_id uuid,category_id uuid,actor_id uuid,requester_id uuid,run_id uuid)",
            language="sql",
        ),
        _function(
            "automation_event_parent",
            "grant_ref uuid,event_ref uuid",
            PARENT,
            "TABLE(chain_id uuid,depth integer,run_id uuid,rule_id uuid)",
        ),
        _function(
            "automation_chain_reserve",
            "run_ref uuid,extra_cost bigint,extra_in bigint,extra_out bigint",
            CHAIN_RESERVE,
            "boolean",
        ),
    )


SIGNATURES = (
    "automation_active_grants(uuid)",
    "automation_event_targets(uuid,uuid,uuid)",
    "kernel_pending_run_references(uuid,integer)",
    "automation_event_parent(uuid,uuid)",
    "automation_chain_reserve(uuid,bigint,bigint,bigint)",
)


def upgrade_sql():
    return (
        *definitions(),
        *(
            f"REVOKE ALL ON FUNCTION public.{name} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            for name in SIGNATURES
        ),
        *(
            f"GRANT EXECUTE ON FUNCTION public.{name} TO pdos_next_dispatch"
            for name in SIGNATURES[:3]
        ),
        *(
            f"GRANT EXECUTE ON FUNCTION public.{name} TO pdos_next_app,pdos_agent"
            for name in SIGNATURES[3:]
        ),
    )


def downgrade_sql():
    return tuple(f"DROP FUNCTION public.{name}" for name in reversed(SIGNATURES))
