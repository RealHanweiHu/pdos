"""B7 actual tenant model metadata, administrator writes and COMMON T1 atom."""

from alembic import op

from migrations.schema_s0_0719 import DDL, TABLES

revision = "s0_0719"
down_revision = "s0_0718"
branch_labels = None
depends_on = None

SQL = """
CREATE FUNCTION kernel_model_configuration_access(tid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT tid=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
  AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=tid
    AND p.id=public.scope_actor() AND p.active)
  AND EXISTS(SELECT 1 FROM public.principals p WHERE p.tenant_id=tid
    AND p.id=public.scope_requester() AND p.active AND p.kind='human')
$$;
CREATE FUNCTION kernel_model_configuration_lock(tid uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE actual integer; BEGIN
 IF NOT COALESCE(public.kernel_model_configuration_access(tid),false) THEN
  RAISE EXCEPTION 'Current model metadata scope required'; END IF;
 SELECT revision INTO actual FROM public.model_configuration_heads WHERE tenant_id=tid FOR SHARE;
 RETURN actual;
END $$;
CREATE FUNCTION kernel_model_configuration_provision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$ BEGIN
 INSERT INTO public.model_configuration_heads(tenant_id,revision) VALUES(NEW.tenant_id,0)
 ON CONFLICT(tenant_id) DO NOTHING;
 RETURN NEW;
END $$;
INSERT INTO model_configuration_heads(tenant_id,revision)
 SELECT DISTINCT tenant_id,0 FROM principals;
CREATE TRIGGER model_configuration_provision AFTER INSERT ON principals
 FOR EACH ROW EXECUTE FUNCTION kernel_model_configuration_provision();

ALTER TABLE model_configuration_heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_configuration_heads FORCE ROW LEVEL SECURITY;
ALTER TABLE model_configuration_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_configuration_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY model_configuration_read ON model_configuration_heads FOR SELECT
 USING (kernel_model_configuration_access(tenant_id));
CREATE POLICY model_configuration_write ON model_configuration_heads FOR UPDATE
 USING (kernel_model_configuration_access(tenant_id) AND kernel_admin_authorized())
 WITH CHECK (kernel_model_configuration_access(tenant_id) AND kernel_admin_authorized());
CREATE POLICY model_configuration_read ON model_configuration_versions FOR SELECT
 USING (kernel_model_configuration_access(tenant_id));
CREATE POLICY model_configuration_write ON model_configuration_versions FOR INSERT
 WITH CHECK (kernel_model_configuration_access(tenant_id) AND kernel_admin_authorized()
   AND created_by=scope_actor());
GRANT SELECT ON model_configuration_heads,model_configuration_versions TO pdos_next_app;
GRANT UPDATE(revision) ON model_configuration_heads TO pdos_next_app;
GRANT INSERT ON model_configuration_versions TO pdos_next_app;

CREATE FUNCTION kernel_model_configuration_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.action_receipts r
   JOIN public.confirmations c ON c.tenant_id=r.tenant_id AND c.category_id=r.category_id
   JOIN public.audit_entries a ON a.tenant_id=r.tenant_id AND a.receipt_id=r.id
   JOIN public.outbox_events o ON o.tenant_id=r.tenant_id AND o.receipt_id=r.id
   WHERE r.tenant_id=NEW.tenant_id AND r.subject_id=NEW.id AND r.subject_revision=NEW.revision
    AND r.operation='model.configuration.save' AND r.subject_type='model_configuration'
    AND r.actor_id=NEW.created_by AND r.requester_id=NEW.created_by
    AND r.run_id IS NULL AND r.agent_run_id IS NULL AND r.product_id IS NULL
    AND r.visibility='private' AND r.result->>'requires_requalification'='true'
    AND r.result->>'status'=CASE WHEN NEW.enabled THEN 'enabled' ELSE 'disabled' END
    AND c.operation=r.operation AND c.actor_id=NEW.created_by AND c.consumed
    AND c.subject_type='category' AND c.subject_id=r.category_id
    AND c.created_at<=r.created_at AND r.created_at<c.expires_at
    AND c.snapshot->>'binding_digest'=NEW.binding_digest
    AND c.snapshot->'metadata'=NEW.public_metadata
    AND (c.snapshot->>'next_revision')::integer=NEW.revision
    AND (c.snapshot->>'enabled')::boolean=NEW.enabled
    AND a.category_id=r.category_id AND a.actor_id=r.actor_id AND a.operation=r.operation
    AND o.category_id=r.category_id AND o.actor_id=r.actor_id
    AND o.type='model.configuration_saved' AND o.subject_id=NEW.id
    AND o.subject_revision=NEW.revision)
 THEN RAISE EXCEPTION 'Confirmed model configuration receipt atom required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.model_configuration_heads h
    WHERE h.tenant_id=NEW.tenant_id AND h.revision=NEW.revision)
 THEN RAISE EXCEPTION 'Exact current model configuration head required'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER model_configuration_atom AFTER INSERT ON model_configuration_versions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kernel_model_configuration_atom();
CREATE TRIGGER model_configuration_immutable BEFORE UPDATE OR DELETE ON model_configuration_versions
 FOR EACH ROW EXECUTE FUNCTION kernel_append_only();
CREATE FUNCTION kernel_model_configuration_head_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGIN
 IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.revision<>OLD.revision+1 THEN
  RAISE EXCEPTION 'Model metadata head requires monotonic CAS'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.model_configuration_versions v
  WHERE v.tenant_id=NEW.tenant_id AND v.revision=NEW.revision) THEN
  RAISE EXCEPTION 'Model metadata head requires retained version'; END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER model_configuration_head AFTER UPDATE ON model_configuration_heads
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 EXECUTE FUNCTION kernel_model_configuration_head_guard();
REVOKE ALL ON FUNCTION kernel_model_configuration_access(uuid),
 kernel_model_configuration_lock(uuid),
 kernel_model_configuration_provision(),kernel_model_configuration_atom(),
 kernel_model_configuration_head_guard() FROM PUBLIC,pdos_agent;
GRANT EXECUTE ON FUNCTION kernel_model_configuration_access(uuid),
 kernel_model_configuration_lock(uuid)
 TO pdos_next_app;
"""


def upgrade():
    for statement in DDL:
        op.execute(statement)
    op.execute(SQL)


def downgrade():
    op.execute("DROP TRIGGER model_configuration_provision ON principals")
    for name in reversed(TABLES):
        op.execute(f'DROP TABLE "{name}"')
    for signature in (
        "kernel_model_configuration_atom()",
        "kernel_model_configuration_head_guard()",
        "kernel_model_configuration_provision()",
        "kernel_model_configuration_lock(uuid)",
        "kernel_model_configuration_access(uuid)",
    ):
        op.execute(f"DROP FUNCTION {signature}")
