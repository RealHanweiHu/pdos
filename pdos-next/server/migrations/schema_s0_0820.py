"""Adopted project stages and named decisions."""
# ruff: noqa: E501
TABLE_SQL = ["\nCREATE TABLE project_governance_events (\n\tproduct_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n\towner_id UUID NOT NULL, \n\tactor_id UUID NOT NULL, \n\tvisibility VARCHAR(16) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tprevious_id UUID, \n\toperation VARCHAR(80) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tbody JSONB NOT NULL, \n\treview JSONB NOT NULL, \n\tcommand_id UUID NOT NULL, \n\treceipt_id UUID NOT NULL, \n\tconfirmation_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcategory_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, project_id, revision), \n\tUNIQUE (tenant_id, command_id), \n\tUNIQUE (tenant_id, receipt_id), \n\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n\tFOREIGN KEY(tenant_id, previous_id) REFERENCES project_governance_events (tenant_id, id), \n\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE INITIALLY DEFERRED, \n\tFOREIGN KEY(tenant_id, confirmation_id) REFERENCES confirmations (tenant_id, id) DEFERRABLE INITIALLY DEFERRED, \n\tCHECK (revision>0 AND status='recorded' AND visibility IN ('private','category','audience'))\n)\n\n", 'CREATE INDEX ix_project_governance_events_tenant_id ON project_governance_events (tenant_id)', 'CREATE INDEX ix_project_governance_events_category_id ON project_governance_events (category_id)']
DEADLINE_OPERATIONS = ['ai.skill.qualify', 'build.engineering.authorize', 'build.manufacturing.authorize', 'change.close', 'change.order.approve', 'change.selection.decide', 'change.verification.record', 'integration.handoff.authorize', 'knowledge.rule.publish', 'mcp.connector.allow', 'npi.manufacturing_baseline.publish', 'proposal.g0.decide', 'quality.capa.verification.review', 'quality.issue.root_cause.decide', 'release.engineering.approve', 'release.exception.decide', 'release.exception.withdraw', 'release.manufacturing.approve', 'test.disposition.decide', 'test.run.review', 'work.baseline.approve', 'work.stage.decide']
READ = "category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM projects p WHERE p.tenant_id=project_governance_events.tenant_id AND p.id=project_governance_events.project_id AND p.product_id=project_governance_events.product_id)"
WRITE = READ + " AND actor_id=scope_actor() AND scope_actor()=scope_requester() AND EXISTS(SELECT 1 FROM principals h WHERE h.tenant_id=project_governance_events.tenant_id AND h.id=scope_actor() AND h.kind='human') AND EXISTS(SELECT 1 FROM projects p WHERE p.tenant_id=project_governance_events.tenant_id AND p.id=project_governance_events.project_id AND p.owner_id=scope_requester())"
SCHEMA_SQL = TABLE_SQL + [
 "ALTER TABLE project_governance_events ENABLE ROW LEVEL SECURITY",
 "ALTER TABLE project_governance_events FORCE ROW LEVEL SECURITY",
 "CREATE POLICY owner_internal ON project_governance_events TO pdos_next_owner USING(true) WITH CHECK(true)",
 f"CREATE POLICY governance_read ON project_governance_events FOR SELECT TO pdos_next_app USING({READ})",
 f"CREATE POLICY governance_append ON project_governance_events FOR INSERT TO pdos_next_app WITH CHECK({WRITE})",
 "REVOKE ALL ON project_governance_events FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
 "GRANT SELECT,INSERT ON project_governance_events TO pdos_next_app",
 "CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON project_governance_events FOR EACH ROW EXECUTE FUNCTION protect_next_snapshot()",
 "CREATE TRIGGER a_bind_category BEFORE INSERT ON project_governance_events FOR EACH ROW EXECUTE FUNCTION bind_model_category()",
 "CREATE TRIGGER category_lifecycle_clock BEFORE INSERT ON project_governance_events FOR EACH ROW EXECUTE FUNCTION category_lifecycle_clock()",
 "CREATE TRIGGER lifecycle_reference BEFORE INSERT ON project_governance_events FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()",
 """CREATE FUNCTION guard_project_governance_append() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
 DECLARE previous project_governance_events; p projects;
 BEGIN
 SELECT * INTO STRICT p FROM projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
 SELECT * INTO previous FROM project_governance_events WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id ORDER BY revision DESC LIMIT 1;
 IF NEW.revision<>coalesce(previous.revision,0)+1 OR NEW.previous_id IS DISTINCT FROM previous.id OR NEW.owner_id<>p.owner_id OR NEW.actor_id<>p.owner_id OR NEW.visibility<>p.visibility OR NEW.category_id<>p.category_id OR NEW.product_id<>p.product_id THEN
  RAISE EXCEPTION 'Governance scope or predecessor mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
 END $$""",
 "CREATE TRIGGER append_guard BEFORE INSERT ON project_governance_events FOR EACH ROW EXECUTE FUNCTION guard_project_governance_append()",
 """CREATE FUNCTION assert_project_governance_receipt() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 DECLARE r action_receipts; c confirmations; rx xid; ownx xid;
 BEGIN
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 SELECT * INTO STRICT c FROM confirmations WHERE tenant_id=NEW.tenant_id AND id=NEW.confirmation_id;
 SELECT xmin INTO rx FROM action_receipts WHERE id=r.id;
 SELECT xmin INTO ownx FROM project_governance_events WHERE id=NEW.id;
 IF rx IS DISTINCT FROM ownx OR ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision)
 IS DISTINCT FROM ROW(NEW.category_id,NEW.product_id,NEW.command_id,NEW.confirmation_id,NEW.actor_id,NEW.actor_id,NEW.operation,'project_governance'::varchar,NEW.id,NEW.revision)
 OR c.operation<>NEW.operation OR c.actor_id<>NEW.actor_id OR c.product_id<>NEW.product_id OR NOT c.consumed OR c.snapshot IS DISTINCT FROM NEW.review
 OR NOT EXISTS(SELECT 1 FROM audit_entries WHERE tenant_id=NEW.tenant_id AND receipt_id=r.id AND actor_id=NEW.actor_id)
 OR NOT EXISTS(SELECT 1 FROM outbox_events WHERE tenant_id=NEW.tenant_id AND receipt_id=r.id AND subject_id=NEW.id)
 THEN RAISE EXCEPTION 'Governance requires same-transaction receipt, named confirmation and audit' USING ERRCODE='23514'; END IF;
 RETURN NULL;
 END $$""",
 "REVOKE ALL ON FUNCTION assert_project_governance_receipt() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
 "CREATE CONSTRAINT TRIGGER receipt_atom AFTER INSERT ON project_governance_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION assert_project_governance_receipt()",
 "ALTER TABLE confirmations DROP CONSTRAINT ck_confirmations_decision_deadline",
 "ALTER TABLE confirmations ADD CONSTRAINT ck_confirmations_decision_deadline CHECK(expires_at IS NOT NULL OR operation IN ("+','.join(repr(op) for op in DEADLINE_OPERATIONS)+"))",
]
DOWNGRADE_SQL = ["DROP TABLE project_governance_events", "DROP FUNCTION guard_project_governance_append()", "DROP FUNCTION assert_project_governance_receipt()",
 "ALTER TABLE confirmations DROP CONSTRAINT ck_confirmations_decision_deadline",
 "ALTER TABLE confirmations ADD CONSTRAINT ck_confirmations_decision_deadline CHECK(expires_at IS NOT NULL OR operation IN ("+','.join(repr(op) for op in DEADLINE_OPERATIONS if op not in {'work.baseline.approve','work.stage.decide'})+"))"]
