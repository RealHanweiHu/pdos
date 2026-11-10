"""Quality holds, spot checks and evaluation sets for pilot T0 (P41-8, P42, P109–P110).

- ``agent_skill_quality_holds``: one row per qualification decision and reason when a
  P41 threshold is crossed or a spot check finds a critical error. Written only by
  ``kernel_skill_quality_hold``, which recomputes the facts itself, so neither a caller
  nor the AI identity can invent one. A hold stops T0 for that qualification decision;
  only a new named ``ai.skill.qualify`` (a new decision id) clears it.
- ``agent_skill_spot_checks``: the named human's mark on a sampled T0 run
  (correct / ordinary error / critical error, P42's five critical kinds).
- ``agent_skill_eval_sets``: a frozen, versioned case list per tenant × skill package
  (evaluation rubric §5.2). Registration grants nothing; review batches may cite it.

All three are append-only, invisible and unwritable to the AI identity, and readable
by current human tenant administrators only. Ordinary spot-check errors count into the
modification rate (P42), so the T0 facts function is replaced to include them.
"""

# SQL statements retain their reviewable clauses.
# ruff: noqa: E501

from migrations.schema_s0_0890 import UP_SQL as UP_0890

ROLES = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
CRITICAL_KINDS = '["scope","fabrication","override","red_line","commitment_baseline"]'
HOLD = "kernel_skill_quality_hold(uuid,varchar,varchar,uuid,integer,numeric)"
OPEN = "kernel_skill_open_hold(uuid,varchar)"
TENANT = "nullif(current_setting('pdos.tenant_id',true),'')::uuid"
# Lock-free so that READ ONLY snapshots can list the rows.
ADMIN = (
    f"tenant_id={TENANT} AND scope_actor() IS NOT NULL AND scope_actor()=scope_requester() "
    "AND EXISTS(SELECT 1 FROM tenant_administrators a JOIN principals p "
    "ON p.tenant_id=a.tenant_id AND p.id=a.principal_id WHERE a.tenant_id={table}.tenant_id "
    "AND a.principal_id=scope_actor() AND a.active AND p.active AND p.kind='human')"
)

FACTS_0890 = next(sql for sql in UP_0890 if "kernel_skill_t0_facts(p_tenant" in sql)
ORDINARY = """     AND h.agent_run_id IS NULL AND h.operation<>'ai.run.revert')
   OR EXISTS(
     SELECT 1 FROM public.agent_skill_spot_checks sc
     WHERE sc.tenant_id=c.tenant_id AND sc.run_id=c.run_id
     AND sc.outcome='ordinary_error') AS w_changed"""
FACTS_ANCHOR = "     AND h.agent_run_id IS NULL AND h.operation<>'ai.run.revert') AS w_changed"
assert FACTS_0890.count(FACTS_ANCHOR) == 1
FACTS_WITH_SPOT_CHECKS = FACTS_0890.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1).replace(
    FACTS_ANCHOR, ORDINARY
)
FACTS_RESTORE = FACTS_0890.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _policies(table, owner):
    read = ADMIN.format(table=table)
    return (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"REVOKE ALL ON {table} FROM {ROLES}",
        f"CREATE POLICY owner_internal ON {table} TO pdos_next_owner USING(true) WITH CHECK(true)",
        f"CREATE POLICY skill_record_read ON {table} FOR SELECT TO pdos_next_app USING ({read})",
        f"GRANT SELECT ON {table} TO pdos_next_app",
        *(
            (
                f"CREATE POLICY skill_record_append ON {table} FOR INSERT TO pdos_next_app "
                f"WITH CHECK ({read} AND {owner}=scope_actor() AND kernel_admin_authorized())",
                f"GRANT INSERT ON {table} TO pdos_next_app",
            )
            if owner
            else ()
        ),
        f"CREATE TRIGGER skill_record_append_only BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION kernel_append_only()",
    )


UP_SQL = (
    """CREATE TABLE agent_skill_spot_checks(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,
  created_at timestamptz NOT NULL,reviewed_by uuid NOT NULL,skill_key varchar(160) NOT NULL,
  qualification_id uuid NOT NULL,skill_version varchar(160) NOT NULL,
  model_version varchar(200) NOT NULL,run_id uuid NOT NULL,outcome varchar(16) NOT NULL,
  critical_kinds jsonb NOT NULL,note varchar(2000) NOT NULL,receipt_id uuid NOT NULL,
  UNIQUE(tenant_id,id),UNIQUE(tenant_id,qualification_id,run_id),
  FOREIGN KEY(tenant_id,reviewed_by) REFERENCES principals(tenant_id,id),
  FOREIGN KEY(tenant_id,qualification_id) REFERENCES agent_skill_qualifications(tenant_id,id),
  FOREIGN KEY(tenant_id,run_id) REFERENCES agent_runs(tenant_id,id),
  CONSTRAINT skill_spot_check_receipt_fk FOREIGN KEY(tenant_id,receipt_id)
    REFERENCES action_receipts(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT skill_spot_check_outcome CHECK (outcome IN ('correct','ordinary_error','critical_error')),
  CONSTRAINT skill_spot_check_critical CHECK (jsonb_typeof(critical_kinds)='array'
    AND (outcome='critical_error')=(jsonb_array_length(critical_kinds)>0)
    AND critical_kinds <@ '"""
    + CRITICAL_KINDS
    + """'::jsonb),
  CONSTRAINT skill_spot_check_note CHECK (outcome='correct' OR char_length(btrim(note))>0))""",
    "CREATE INDEX ix_agent_skill_spot_checks_tenant_id ON agent_skill_spot_checks(tenant_id)",
    "CREATE INDEX ix_skill_spot_checks_run ON agent_skill_spot_checks(tenant_id,run_id)",
    """CREATE TABLE agent_skill_quality_holds(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,
  created_at timestamptz NOT NULL,skill_key varchar(160) NOT NULL,qualification_id uuid NOT NULL,
  skill_version varchar(160) NOT NULL,model_version varchar(200) NOT NULL,
  reason varchar(32) NOT NULL,threshold jsonb NOT NULL,metrics jsonb NOT NULL,
  basis_run_ids uuid[] NOT NULL,spot_check_id uuid,owner_id uuid,triggered_by uuid NOT NULL,
  UNIQUE(tenant_id,id),UNIQUE(tenant_id,qualification_id,reason),
  FOREIGN KEY(tenant_id,qualification_id) REFERENCES agent_skill_qualifications(tenant_id,id),
  FOREIGN KEY(tenant_id,spot_check_id) REFERENCES agent_skill_spot_checks(tenant_id,id),
  FOREIGN KEY(tenant_id,owner_id) REFERENCES principals(tenant_id,id),
  FOREIGN KEY(tenant_id,triggered_by) REFERENCES principals(tenant_id,id),
  CONSTRAINT skill_quality_hold_reason CHECK (reason IN
    ('withdrawal','modification','framework_check','critical_spot_check')),
  CONSTRAINT skill_quality_hold_spot_check CHECK
    ((reason='critical_spot_check')=(spot_check_id IS NOT NULL)))""",
    "CREATE INDEX ix_agent_skill_quality_holds_tenant_id ON agent_skill_quality_holds(tenant_id)",
    """CREATE TABLE agent_skill_eval_sets(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,
  created_at timestamptz NOT NULL,registered_by uuid NOT NULL,skill_key varchar(160) NOT NULL,
  version integer NOT NULL,title varchar(200) NOT NULL,cases jsonb NOT NULL,
  case_count integer NOT NULL,cases_sha256 varchar(64) NOT NULL,receipt_id uuid NOT NULL,
  UNIQUE(tenant_id,id),UNIQUE(tenant_id,skill_key,version),
  FOREIGN KEY(tenant_id,registered_by) REFERENCES principals(tenant_id,id),
  CONSTRAINT skill_eval_set_receipt_fk FOREIGN KEY(tenant_id,receipt_id)
    REFERENCES action_receipts(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT skill_eval_set_shape CHECK (version>0 AND case_count BETWEEN 1 AND 60
    AND jsonb_typeof(cases)='array' AND jsonb_array_length(cases)=case_count
    AND cases_sha256 ~ '^[0-9a-f]{64}$' AND char_length(btrim(title)) BETWEEN 1 AND 200))""",
    "CREATE INDEX ix_agent_skill_eval_sets_tenant_id ON agent_skill_eval_sets(tenant_id)",
    "ALTER TABLE agent_skill_review_batches ADD COLUMN eval_set_id uuid",
    "ALTER TABLE agent_skill_review_batches ADD CONSTRAINT skill_review_eval_set_fk "
    "FOREIGN KEY(tenant_id,eval_set_id) REFERENCES agent_skill_eval_sets(tenant_id,id)",
    *_policies("agent_skill_spot_checks", "reviewed_by"),
    *_policies("agent_skill_eval_sets", "registered_by"),
    *_policies("agent_skill_quality_holds", None),
    # Same receipt atom as case reviews (s0_0766): the named person's own consumed
    # confirmation, receipt, audit and outbox event, never a run identity.
    """CREATE FUNCTION kernel_skill_record_atom() RETURNS trigger LANGUAGE plpgsql
  SECURITY DEFINER SET search_path=public,pg_temp AS $$
  DECLARE v_operation text; v_person uuid; v_event text;
  BEGIN
    IF TG_TABLE_NAME='agent_skill_spot_checks' THEN
      v_operation='ai.skill.spot_check.record'; v_event='ai.skill_spot_checked';
      v_person=NEW.reviewed_by;
    ELSE
      v_operation='ai.skill.eval_set.register'; v_event='ai.skill_eval_set_registered';
      v_person=(to_jsonb(NEW)->>'registered_by')::uuid;
      IF NEW.version<>(SELECT count(*) FROM agent_skill_eval_sets s
        WHERE s.tenant_id=NEW.tenant_id AND s.skill_key=NEW.skill_key) THEN
        RAISE EXCEPTION 'Evaluation set versions are contiguous'; END IF;
    END IF;
    IF NOT EXISTS(SELECT 1 FROM action_receipts r JOIN audit_entries a ON a.receipt_id=r.id AND a.tenant_id=r.tenant_id
      JOIN outbox_events o ON o.receipt_id=r.id AND o.tenant_id=r.tenant_id
      JOIN confirmations c ON c.id=r.confirmation_id AND c.tenant_id=r.tenant_id
      WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND r.operation=v_operation
      AND r.actor_id=v_person AND r.requester_id=v_person AND r.agent_run_id IS NULL AND r.run_id IS NULL
      AND r.subject_id=NEW.id AND r.subject_revision=1 AND c.consumed AND c.actor_id=v_person
      AND c.operation=v_operation AND o.type=v_event)
    THEN RAISE EXCEPTION 'Human skill quality record receipt atom required'; END IF;
    RETURN NEW;
  END $$""",
    "CREATE CONSTRAINT TRIGGER skill_record_atom AFTER INSERT ON agent_skill_spot_checks "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kernel_skill_record_atom()",
    "CREATE CONSTRAINT TRIGGER skill_record_atom AFTER INSERT ON agent_skill_eval_sets "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kernel_skill_record_atom()",
    f"REVOKE ALL ON FUNCTION kernel_skill_record_atom() FROM {ROLES}",
    FACTS_WITH_SPOT_CHECKS,
    f"""CREATE FUNCTION public.{HOLD.split("(")[0]}(p_tenant uuid,p_skill varchar,
 p_reason varchar,p_spot_check uuid,p_window integer,p_limit numeric)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $hold$
DECLARE e public.tenant_skill_enablements; spot public.agent_skill_spot_checks;
  hold uuid; owner uuid; sample integer; hit integer; runs uuid[];
BEGIN
 IF p_tenant IS DISTINCT FROM {TENANT} OR public.scope_actor() IS NULL THEN
  RAISE EXCEPTION 'Tenant scope required' USING ERRCODE='42501'; END IF;
 SELECT * INTO e FROM public.tenant_skill_enablements t
  WHERE t.tenant_id=p_tenant AND t.skill_key=p_skill FOR UPDATE;
 IF e.id IS NULL OR e.qualification_id IS NULL OR e.reviewed_at IS NULL
  OR e.qualification_revoked THEN RETURN NULL; END IF;
 SELECT h.id INTO hold FROM public.agent_skill_quality_holds h
  WHERE h.tenant_id=p_tenant AND h.qualification_id=e.qualification_id AND h.reason=p_reason;
 IF hold IS NOT NULL THEN RETURN hold; END IF;
 IF p_reason='critical_spot_check' THEN
  SELECT * INTO spot FROM public.agent_skill_spot_checks s
   WHERE s.tenant_id=p_tenant AND s.id=p_spot_check AND s.skill_key=p_skill
   AND s.qualification_id=e.qualification_id AND s.outcome='critical_error';
  IF spot.id IS NULL THEN RAISE EXCEPTION 'Recorded critical spot check required'; END IF;
  sample:=1; hit:=1; runs:=ARRAY[spot.run_id];
 ELSIF p_reason IN ('withdrawal','modification') AND p_spot_check IS NULL THEN
  IF p_window IS NULL OR p_window<1 OR p_window>500 OR p_limit IS NULL OR p_limit<0 THEN
   RAISE EXCEPTION 'Threshold window and limit required'; END IF;
  SELECT count(*) FILTER (WHERE f.fact=CASE WHEN p_reason='withdrawal' THEN 'run' ELSE 'write' END),
   count(*) FILTER (WHERE f.fact=CASE WHEN p_reason='withdrawal' THEN 'run' ELSE 'write' END
    AND CASE WHEN p_reason='withdrawal' THEN f.withdrawn ELSE f.changed END),
   COALESCE(array_agg(DISTINCT f.run_id) FILTER (
    WHERE f.fact=CASE WHEN p_reason='withdrawal' THEN 'run' ELSE 'write' END
    AND CASE WHEN p_reason='withdrawal' THEN f.withdrawn ELSE f.changed END),'{{}}'::uuid[])
  INTO sample,hit,runs
  FROM public.kernel_skill_t0_facts(p_tenant,p_skill,e.qualified_skill_version,
   e.qualified_model_version,e.reviewed_at,p_window,p_window) f;
  IF sample<p_window OR sample=0 THEN
   RAISE EXCEPTION 'Recorded facts do not fill this window'; END IF;
  IF hit::numeric/sample<=p_limit THEN
   RAISE EXCEPTION 'Recorded facts do not cross this threshold'; END IF;
 ELSE
  RAISE EXCEPTION 'Unsupported quality hold reason';
 END IF;
 SELECT q.decided_by INTO owner FROM public.agent_skill_qualifications q
  JOIN public.principals p ON p.tenant_id=q.tenant_id AND p.id=q.decided_by AND p.active
  WHERE q.tenant_id=p_tenant AND q.id=e.qualification_id;
 INSERT INTO public.agent_skill_quality_holds(id,tenant_id,created_at,skill_key,
  qualification_id,skill_version,model_version,reason,threshold,metrics,basis_run_ids,
  spot_check_id,owner_id,triggered_by)
 VALUES (gen_random_uuid(),p_tenant,now(),p_skill,e.qualification_id,
  e.qualified_skill_version,e.qualified_model_version,p_reason,
  CASE WHEN p_reason='critical_spot_check' THEN '{{}}'::jsonb
   ELSE jsonb_build_object('window',p_window,'limit',p_limit) END,
  jsonb_build_object('sample',sample,'count',hit),runs,p_spot_check,owner,public.scope_actor())
 ON CONFLICT (tenant_id,qualification_id,reason) DO NOTHING RETURNING id INTO hold;
 IF hold IS NULL THEN
  SELECT h.id INTO hold FROM public.agent_skill_quality_holds h
   WHERE h.tenant_id=p_tenant AND h.qualification_id=e.qualification_id AND h.reason=p_reason;
 END IF;
 RETURN hold;
END $hold$""",
    f"""CREATE FUNCTION public.{OPEN.split("(")[0]}(p_tenant uuid,p_skill varchar)
RETURNS varchar LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $open$
 SELECT h.reason FROM public.agent_skill_quality_holds h
 JOIN public.tenant_skill_enablements e ON e.tenant_id=h.tenant_id
  AND e.skill_key=h.skill_key AND e.qualification_id=h.qualification_id
 WHERE h.tenant_id=p_tenant AND h.skill_key=p_skill AND p_tenant={TENANT}
 ORDER BY h.created_at,h.id LIMIT 1
$open$""",
    *(f"REVOKE ALL ON FUNCTION public.{name} FROM {ROLES}" for name in (HOLD, OPEN)),
    *(f"GRANT EXECUTE ON FUNCTION public.{name} TO pdos_next_app" for name in (HOLD, OPEN)),
)

DOWN_SQL = (
    f"DROP FUNCTION public.{OPEN}",
    f"DROP FUNCTION public.{HOLD}",
    FACTS_RESTORE,
    "DROP TRIGGER skill_record_atom ON agent_skill_eval_sets",
    "DROP TRIGGER skill_record_atom ON agent_skill_spot_checks",
    "DROP FUNCTION kernel_skill_record_atom()",
    "ALTER TABLE agent_skill_review_batches DROP CONSTRAINT skill_review_eval_set_fk",
    "ALTER TABLE agent_skill_review_batches DROP COLUMN eval_set_id",
    "DROP TABLE agent_skill_quality_holds",
    "DROP TABLE agent_skill_eval_sets",
    "DROP TABLE agent_skill_spot_checks",
)
