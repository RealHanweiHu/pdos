"""Versioned plan revisions and typed resource demand snapshots."""
SCHEMA_SQL = [
    "ALTER TABLE plan_proposals ADD COLUMN base_plan_id uuid",
    "ALTER TABLE plan_proposals ADD COLUMN resource_demands jsonb NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE plan_proposals ADD CONSTRAINT fk_plan_proposal_base FOREIGN KEY(tenant_id,product_id,project_id,base_plan_id) REFERENCES plan_revisions(tenant_id,product_id,project_id,id)",
    "ALTER TABLE plan_proposals ADD CONSTRAINT plan_demand_array CHECK(jsonb_typeof(resource_demands)='array')",
    """CREATE FUNCTION guard_plan_revision_base() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
    DECLARE p projects; candidate plan_proposals; latest integer;
    BEGIN
      SELECT * INTO STRICT p FROM projects WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPDATE;
      IF TG_TABLE_NAME='plan_proposals' THEN
        IF NEW.project_revision<>p.revision OR NEW.base_plan_id IS DISTINCT FROM p.current_plan_id THEN
          RAISE EXCEPTION 'Plan candidate requires current project and base plan' USING ERRCODE='23514';
        END IF;
      ELSE
        SELECT * INTO STRICT candidate FROM plan_proposals WHERE tenant_id=NEW.tenant_id AND id=NEW.proposal_id;
        SELECT coalesce(max(revision),0) INTO latest FROM plan_revisions WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id;
        IF NEW.revision<>latest+1 OR candidate.project_revision<>p.revision OR candidate.base_plan_id IS DISTINCT FROM p.current_plan_id OR NEW.forecast IS DISTINCT FROM candidate.forecast THEN
          RAISE EXCEPTION 'Plan application requires fresh immutable candidate and sequential revision' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$""",
    "CREATE TRIGGER revision_base BEFORE INSERT ON plan_proposals FOR EACH ROW EXECUTE FUNCTION guard_plan_revision_base()",
    "CREATE TRIGGER revision_base BEFORE INSERT ON plan_revisions FOR EACH ROW EXECUTE FUNCTION guard_plan_revision_base()",
]
DOWNGRADE_SQL = [
    "DROP TRIGGER revision_base ON plan_proposals", "DROP TRIGGER revision_base ON plan_revisions",
    "DROP FUNCTION guard_plan_revision_base()", "ALTER TABLE plan_proposals DROP COLUMN base_plan_id",
    "ALTER TABLE plan_proposals DROP COLUMN resource_demands",
]
