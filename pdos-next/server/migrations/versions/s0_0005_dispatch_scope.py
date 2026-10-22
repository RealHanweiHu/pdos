"""Metadata-only dispatcher; private jobs carry persisted category and principal scope."""

from alembic import op

revision = "s0_0005"
down_revision = "s0_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE inbox_deliveries ALTER COLUMN product_id DROP NOT NULL")
    op.execute(
        "CREATE POLICY event_audience ON inbox_deliveries AS RESTRICTIVE "
        "USING (EXISTS(SELECT 1 FROM outbox_events e WHERE e.id=inbox_deliveries.event_id "
        "AND e.tenant_id=inbox_deliveries.tenant_id))"
    )
    op.execute("""
      CREATE FUNCTION claim_domain_events(tid uuid, batch_limit integer)
      RETURNS TABLE(event_id uuid,tenant_id uuid,category_id uuid,product_id uuid,
        subject_id uuid,subject_revision integer,event_type varchar,schema_version integer,
        correlation_id uuid,lease_id uuid,actor_id uuid,requester_id uuid)
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE e public.outbox_events%ROWTYPE; r public.action_receipts%ROWTYPE; lease uuid;
      BEGIN
        IF tid IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
          OR session_user<>'pdos_next_dispatch' THEN RAISE EXCEPTION 'dispatcher scope required'; END IF;
        IF batch_limit<1 OR batch_limit>100 THEN RAISE EXCEPTION 'invalid delivery batch'; END IF;
        FOR e IN SELECT o.* FROM public.outbox_events o WHERE o.tenant_id=tid
          AND o.delivered_at IS NULL AND (o.lease_until IS NULL OR o.lease_until<=statement_timestamp())
          ORDER BY o.created_at,o.id LIMIT batch_limit FOR UPDATE SKIP LOCKED LOOP
          SELECT a.* INTO STRICT r FROM public.action_receipts a WHERE a.id=e.receipt_id AND a.tenant_id=tid;
          lease=gen_random_uuid();
          UPDATE public.outbox_events o SET lease_id=lease,lease_until=statement_timestamp()+interval '30 seconds',
            attempts=o.attempts+1 WHERE o.id=e.id AND o.tenant_id=tid;
          INSERT INTO public.inbox_deliveries(id,tenant_id,category_id,product_id,event_id,
            consumer,status,created_at) VALUES(gen_random_uuid(),tid,e.category_id,r.product_id,e.id,
            'temporal-work-v1','pending',statement_timestamp()) ON CONFLICT DO NOTHING;
          RETURN QUERY SELECT e.id,tid,e.category_id,r.product_id,e.subject_id,e.subject_revision,
            e.type,e.schema_version,e.correlation_id,lease,r.actor_id,r.requester_id;
        END LOOP;
      END $$
    """)
    op.execute("""
      CREATE FUNCTION finish_domain_delivery(tid uuid,eid uuid,lease uuid,wid varchar,unknown_result boolean)
      RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE e public.outbox_events%ROWTYPE;
      BEGIN
        IF tid IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
          OR session_user<>'pdos_next_dispatch' THEN RAISE EXCEPTION 'dispatcher scope required'; END IF;
        SELECT o.* INTO e FROM public.outbox_events o WHERE o.id=eid AND o.tenant_id=tid FOR UPDATE;
        IF NOT FOUND OR e.lease_id IS DISTINCT FROM lease OR e.delivered_at IS NOT NULL THEN RETURN false; END IF;
        IF unknown_result THEN
          UPDATE public.outbox_events SET last_error='DELIVERY_UNKNOWN' WHERE id=eid AND tenant_id=tid;
        ELSE
          UPDATE public.outbox_events SET delivered_at=statement_timestamp(),lease_until=NULL,last_error=NULL
            WHERE id=eid AND tenant_id=tid;
          UPDATE public.inbox_deliveries SET status=CASE WHEN wid IS NULL THEN 'ignored' ELSE 'received' END,
            workflow_id=wid,received_at=statement_timestamp() WHERE tenant_id=tid AND event_id=eid
            AND consumer='temporal-work-v1';
        END IF;
        RETURN true;
      END $$
    """)
    for signature in (
        "claim_domain_events(uuid,integer)",
        "finish_domain_delivery(uuid,uuid,uuid,varchar,boolean)",
    ):
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC,pdos_agent,pdos_next_app")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_dispatch")


def downgrade():
    op.execute("DROP FUNCTION finish_domain_delivery(uuid,uuid,uuid,varchar,boolean)")
    op.execute("DROP FUNCTION claim_domain_events(uuid,integer)")
    op.execute("DROP POLICY event_audience ON inbox_deliveries")
    op.execute("ALTER TABLE inbox_deliveries ALTER COLUMN product_id SET NOT NULL")
