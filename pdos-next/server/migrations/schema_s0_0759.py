"""Tenant-shared platforms and audience-scoped append-only applicability."""
# ruff: noqa: E501 -- frozen SQL retains the reviewed representation.

from migrations.schema_s0_0754 import CANDIDATE_POLICY as PREVIOUS_CANDIDATE_POLICY

TABLE_SQL = (
    "CREATE TABLE platforms (\n\tcode TEXT NOT NULL, \n\tname TEXT NOT NULL, \n\tdescription TEXT NOT NULL, \n\torigin TEXT NOT NULL, \n\twriter_id UUID NOT NULL, \n\trun_id UUID, \n\tconfirmed_by UUID NOT NULL, \n\tprepared_candidate_id UUID, \n\treceipt_id UUID NOT NULL, \n\tconfirmation_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, code), \n\tCHECK (length(code)>0 AND length(name)>0), \n\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, confirmed_by) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tFOREIGN KEY(tenant_id, prepared_candidate_id) REFERENCES proposal_prepared_candidates (tenant_id, id), \n\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE INITIALLY DEFERRED, \n\tFOREIGN KEY(tenant_id, confirmation_id) REFERENCES confirmations (tenant_id, id), \n\tCHECK (origin IN ('human','ai_draft')), \n\tCHECK ((origin='human' AND run_id IS NULL AND prepared_candidate_id IS NULL) OR (origin='ai_draft' AND run_id IS NOT NULL AND prepared_candidate_id IS NOT NULL))\n)",
    'CREATE INDEX ix_platforms_tenant_id ON platforms (tenant_id)',
    "CREATE TABLE platform_product_links (\n\tproduct_id UUID NOT NULL, \n\tplatform_id UUID NOT NULL, \n\tvariant_id UUID, \n\ttarget_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\taction TEXT NOT NULL, \n\tcompatibility TEXT, \n\tplatform_version TEXT, \n\treason TEXT NOT NULL, \n\torigin TEXT NOT NULL, \n\twriter_id UUID NOT NULL, \n\trun_id UUID, \n\tconfirmed_by UUID NOT NULL, \n\tprepared_candidate_id UUID, \n\treceipt_id UUID NOT NULL, \n\tconfirmation_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcategory_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, category_id, product_id, platform_id, target_id, version), \n\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, id), \n\tFOREIGN KEY(tenant_id, product_id, variant_id) REFERENCES product_variants (tenant_id, product_id, id), \n\tFOREIGN KEY(tenant_id, platform_id) REFERENCES platforms (tenant_id, id), \n\tCHECK (target_id=coalesce(variant_id,product_id) AND version>0), \n\tCHECK (action IN ('attach','detach') AND length(reason)>0), \n\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, confirmed_by) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tFOREIGN KEY(tenant_id, prepared_candidate_id) REFERENCES proposal_prepared_candidates (tenant_id, id), \n\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE INITIALLY DEFERRED, \n\tFOREIGN KEY(tenant_id, confirmation_id) REFERENCES confirmations (tenant_id, id), \n\tCHECK (origin IN ('human','ai_draft')), \n\tCHECK ((origin='human' AND run_id IS NULL AND prepared_candidate_id IS NULL) OR (origin='ai_draft' AND run_id IS NOT NULL AND prepared_candidate_id IS NOT NULL))\n)",
    'CREATE INDEX ix_platform_links_platform ON platform_product_links (tenant_id, platform_id)',
    'CREATE INDEX ix_platform_product_links_category_id ON platform_product_links (category_id)',
    'CREATE INDEX ix_platform_product_links_tenant_id ON platform_product_links (tenant_id)',
    'CREATE TABLE platform_link_current (\n\ttenant_id UUID NOT NULL, \n\tproduct_id UUID NOT NULL, \n\tplatform_id UUID NOT NULL, \n\ttarget_id UUID NOT NULL, \n\tcategory_id UUID NOT NULL, \n\tcurrent_version INTEGER NOT NULL, \n\tattached BOOLEAN NOT NULL, \n\tPRIMARY KEY (tenant_id, product_id, platform_id, target_id), \n\tFOREIGN KEY(tenant_id, category_id, product_id, platform_id, target_id, current_version) REFERENCES platform_product_links (tenant_id, category_id, product_id, platform_id, target_id, version) DEFERRABLE INITIALLY DEFERRED\n)',
)

# Fixed table-specific policies; helpers retain the ordinary owner's pinned path.
TENANT = "tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid"
HUMAN = "scope_actor()=scope_requester() AND EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND p.id=scope_actor() AND p.kind='human' AND p.active)"
SHARED = f"{TENANT} AND EXISTS(SELECT 1 FROM categories c WHERE c.tenant_id=platforms.tenant_id AND category_access(c.tenant_id,c.id))"
SHARED_WRITE = f"{TENANT} AND {HUMAN} AND EXISTS(SELECT 1 FROM categories c WHERE c.tenant_id=platforms.tenant_id AND c.status='active' AND category_access(c.tenant_id,c.id,true))"


def scoped(table, writing=False):
    target = f"{table}.target_id"
    return (
        f"{TENANT} AND category_access(tenant_id,category_id,{str(writing).lower()}) "
        f"AND EXISTS(SELECT 1 FROM products p WHERE p.tenant_id={table}.tenant_id "
        f"AND p.category_id={table}.category_id AND p.id={table}.product_id) "
        f"AND ({target}={table}.product_id OR EXISTS(SELECT 1 FROM product_variants v "
        f"WHERE v.tenant_id={table}.tenant_id AND v.category_id={table}.category_id "
        f"AND v.product_id={table}.product_id AND v.id={target}))"
        + (
            f" AND {HUMAN} AND EXISTS(SELECT 1 FROM categories c WHERE c.tenant_id={table}.tenant_id "
            f"AND c.id={table}.category_id AND c.status='active')"
            if writing else ""
        )
    )


POLICY_SQL = []
for table in ("platforms", "platform_product_links", "platform_link_current"):
    POLICY_SQL.extend((
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner_internal ON {table} TO pdos_next_owner USING (true) WITH CHECK (true)",
        f"CREATE POLICY platform_read ON {table} FOR SELECT TO pdos_next_app,pdos_agent USING ({SHARED if table == 'platforms' else scoped(table)})",
        f"CREATE POLICY platform_insert ON {table} FOR INSERT TO pdos_next_app WITH CHECK ({SHARED_WRITE if table == 'platforms' else scoped(table,True)})",
        f"GRANT SELECT ON {table} TO pdos_next_app,pdos_agent",
        f"GRANT INSERT ON {table} TO pdos_next_app",
        f"REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON {table} FROM pdos_agent",
    ))
POLICY_SQL.extend((
    f"CREATE POLICY platform_update ON platform_link_current FOR UPDATE TO pdos_next_app USING ({scoped('platform_link_current',True)}) WITH CHECK ({scoped('platform_link_current',True)})",
    "GRANT UPDATE ON platform_link_current TO pdos_next_app",
))

GUARD_SQL = (
    """CREATE FUNCTION m3_platform_atom() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO pg_catalog,public,pg_temp AS $body$
    DECLARE r action_receipts; c confirmations; latest platform_product_links; rx xid;
    BEGIN
      IF TG_TABLE_NAME='platforms' THEN
        IF NOT EXISTS(SELECT 1 FROM platform_product_links l WHERE l.tenant_id=NEW.tenant_id
          AND l.platform_id=NEW.id AND l.receipt_id=NEW.receipt_id AND l.confirmation_id=NEW.confirmation_id
          AND l.origin=NEW.origin AND l.writer_id=NEW.writer_id AND l.confirmed_by=NEW.confirmed_by
          AND l.run_id IS NOT DISTINCT FROM NEW.run_id
          AND l.prepared_candidate_id IS NOT DISTINCT FROM NEW.prepared_candidate_id
          AND l.action='attach' AND l.version=1
          AND l.xmin=(SELECT p.xmin FROM platforms p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.id)) THEN
          RAISE EXCEPTION 'platform must be created with its link transaction' USING ERRCODE='23514';
        END IF;
        RETURN NULL;
      END IF;
      SELECT l.* INTO STRICT latest FROM platform_product_links l WHERE l.tenant_id=NEW.tenant_id
        AND l.product_id=NEW.product_id AND l.platform_id=NEW.platform_id AND l.target_id=NEW.target_id
        ORDER BY l.version DESC LIMIT 1;
      IF NOT EXISTS(SELECT 1 FROM platform_link_current p WHERE p.tenant_id=latest.tenant_id
        AND p.category_id=latest.category_id AND p.product_id=latest.product_id AND p.platform_id=latest.platform_id
        AND p.target_id=latest.target_id AND p.current_version=latest.version AND p.attached=(latest.action='attach')) THEN
        RAISE EXCEPTION 'platform current must match latest immutable version' USING ERRCODE='23514';
      END IF;
      IF TG_TABLE_NAME='platform_link_current' THEN RETURN NULL; END IF;
      SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
      SELECT * INTO STRICT c FROM confirmations WHERE tenant_id=NEW.tenant_id AND id=NEW.confirmation_id;
      SELECT xmin INTO rx FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=r.id;
      IF r.operation IS DISTINCT FROM 'platform.link.create' OR r.subject_type IS DISTINCT FROM 'platform_link'
        OR r.category_id IS DISTINCT FROM NEW.category_id OR r.product_id IS DISTINCT FROM NEW.product_id
        OR r.subject_id IS DISTINCT FROM NEW.id OR r.subject_revision IS DISTINCT FROM NEW.version
        OR r.confirmation_id IS DISTINCT FROM NEW.confirmation_id
        OR r.requester_id IS DISTINCT FROM NEW.confirmed_by OR r.actor_id IS DISTINCT FROM r.requester_id
        OR r.actor_id IS DISTINCT FROM scope_actor() OR r.requester_id IS DISTINCT FROM scope_requester()
        OR r.run_id IS NOT NULL OR r.agent_run_id IS DISTINCT FROM NEW.run_id
        OR NOT c.consumed OR c.operation IS DISTINCT FROM r.operation OR c.actor_id IS DISTINCT FROM r.requester_id
        OR c.subject_type IS DISTINCT FROM 'product' OR c.subject_id IS DISTINCT FROM NEW.product_id
        OR c.category_id IS DISTINCT FROM NEW.category_id OR c.product_id IS DISTINCT FROM NEW.product_id
        OR c.expires_at IS NULL OR r.created_at>c.expires_at
        OR rx IS DISTINCT FROM (SELECT xmin FROM platform_product_links WHERE id=NEW.id AND tenant_id=NEW.tenant_id)
        OR rx IS DISTINCT FROM (SELECT xmin FROM confirmations WHERE id=c.id AND tenant_id=NEW.tenant_id)
        OR NOT EXISTS(SELECT 1 FROM audit_entries a WHERE a.tenant_id=NEW.tenant_id AND a.category_id=NEW.category_id
          AND a.receipt_id=r.id AND a.actor_id=r.actor_id AND a.operation=r.operation AND a.xmin=rx)
        OR NOT EXISTS(SELECT 1 FROM outbox_events e WHERE e.tenant_id=NEW.tenant_id AND e.category_id=NEW.category_id
          AND e.receipt_id=r.id AND e.type='platform.linked' AND e.subject_id=NEW.id
          AND e.subject_revision=NEW.version AND e.actor_id=r.actor_id AND e.xmin=rx) THEN
        RAISE EXCEPTION 'platform link receipt confirmation audit event must commit together' USING ERRCODE='23514';
      END IF;
      IF (NEW.origin='human' AND NEW.writer_id IS DISTINCT FROM NEW.confirmed_by)
        OR (NEW.origin='ai_draft' AND NOT EXISTS(SELECT 1 FROM proposal_prepared_candidates p JOIN agent_runs ar
          ON ar.tenant_id=p.tenant_id AND ar.id=p.run_id WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.prepared_candidate_id
          AND p.category_id=NEW.category_id AND p.operation=r.operation AND p.run_id=NEW.run_id
          AND p.writer_id=NEW.writer_id AND p.requester_id=NEW.confirmed_by
          AND ar.product_id=NEW.product_id AND ar.proposal_id IS NULL
          AND ar.writer_id=NEW.writer_id AND ar.requester_id=NEW.confirmed_by
          AND ar.reverted_at IS NULL AND ar.state<>'cancelled')) THEN
        RAISE EXCEPTION 'platform link provenance mismatch' USING ERRCODE='23514';
      END IF;
      IF NEW.version>1 AND NOT EXISTS(SELECT 1 FROM platform_product_links l WHERE l.tenant_id=NEW.tenant_id
        AND l.product_id=NEW.product_id AND l.platform_id=NEW.platform_id AND l.target_id=NEW.target_id
        AND l.version=NEW.version-1) THEN
        RAISE EXCEPTION 'platform link version gap' USING ERRCODE='23514';
      END IF;
      IF NEW.action='detach' AND NOT EXISTS(SELECT 1 FROM platform_product_links l WHERE l.tenant_id=NEW.tenant_id
        AND l.product_id=NEW.product_id AND l.platform_id=NEW.platform_id AND l.target_id=NEW.target_id
        AND l.version=NEW.version-1 AND l.action='attach') THEN
        RAISE EXCEPTION 'platform detach needs attached predecessor' USING ERRCODE='23514';
      END IF;
      RETURN NULL;
    END $body$""",
    "REVOKE ALL ON FUNCTION m3_platform_atom() FROM PUBLIC",
    """CREATE FUNCTION m3_platform_current_guard() RETURNS trigger LANGUAGE plpgsql
    SET search_path TO pg_catalog,public,pg_temp AS $body$
    BEGIN
      IF TG_OP='UPDATE' AND (to_jsonb(NEW)-ARRAY['current_version','attached'])=(to_jsonb(OLD)-ARRAY['current_version','attached'])
        AND NEW.current_version=OLD.current_version+1 THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'platform current only advances one version' USING ERRCODE='23514';
    END $body$""",
    "REVOKE ALL ON FUNCTION m3_platform_current_guard() FROM PUBLIC",
    "CREATE TRIGGER platform_current_monotonic BEFORE UPDATE OR DELETE ON platform_link_current FOR EACH ROW EXECUTE FUNCTION m3_platform_current_guard()",
    *(
        f"CREATE CONSTRAINT TRIGGER {table}_atom AFTER INSERT {'OR UPDATE' if table == 'platform_link_current' else ''} ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION m3_platform_atom()"
        for table in ("platforms", "platform_product_links", "platform_link_current")
    ),
    *(
        f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION m3_append_only()"
        for table in ("platforms", "platform_product_links")
    ),
)

PREVIOUS_OPERATIONS = "'proposal.create','proposal.item.patch','proposal.question.create','category.knowledge.add','category.knowledge.withdraw','category.knowledge.promote','category.parameter.publish','product.definition.item.patch'"
CANDIDATE_POLICY = PREVIOUS_CANDIDATE_POLICY.replace(
    "proposal_prepared_candidates.operation<>'product.definition.item.patch'",
    "proposal_prepared_candidates.operation NOT IN ('product.definition.item.patch','platform.link.create')",
).replace(
    "   ))",
    """    OR (proposal_prepared_candidates.operation='platform.link.create'
      AND ar.product_id IS NOT NULL AND ar.proposal_id IS NULL
      AND EXISTS(SELECT 1 FROM products product WHERE product.tenant_id=ar.tenant_id
        AND product.category_id=ar.category_id AND product.id=ar.product_id
        AND product.id::text=proposal_prepared_candidates.payload->>'product_id'))
   ))""",
)
SCHEMA_SQL = (
    *TABLE_SQL, *POLICY_SQL, *GUARD_SQL,
    "ALTER TABLE proposal_prepared_candidates DROP CONSTRAINT proposal_prepared_candidates_operation_check",
    f"ALTER TABLE proposal_prepared_candidates ADD CONSTRAINT proposal_prepared_candidates_operation_check CHECK (operation IN ({PREVIOUS_OPERATIONS},'platform.link.create'))",
    CANDIDATE_POLICY,
)
DOWNGRADE_SQL = (
    """DO $body$ BEGIN
      IF EXISTS(SELECT 1 FROM platforms) OR EXISTS(SELECT 1 FROM platform_product_links)
        OR EXISTS(SELECT 1 FROM proposal_prepared_candidates WHERE operation='platform.link.create') THEN
        RAISE EXCEPTION 'platform history must be preserved; downgrade refused'; END IF;
    END $body$""",
    PREVIOUS_CANDIDATE_POLICY,
    "ALTER TABLE proposal_prepared_candidates DROP CONSTRAINT proposal_prepared_candidates_operation_check",
    f"ALTER TABLE proposal_prepared_candidates ADD CONSTRAINT proposal_prepared_candidates_operation_check CHECK (operation IN ({PREVIOUS_OPERATIONS}))",
    "DROP TABLE platform_link_current", "DROP TABLE platform_product_links", "DROP TABLE platforms",
    "DROP FUNCTION m3_platform_current_guard()", "DROP FUNCTION m3_platform_atom()",
)
