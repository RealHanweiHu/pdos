"""Self-owned account preferences, with human-only writes and runtime reads."""

TABLE_SQL = """CREATE TABLE public.personal_preferences (
 owner_id UUID NOT NULL, revision INTEGER NOT NULL, body JSONB NOT NULL,
 updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
 id UUID NOT NULL, tenant_id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (id), UNIQUE (tenant_id,owner_id),
 FOREIGN KEY (tenant_id,owner_id) REFERENCES public.principals (tenant_id,id),
 CONSTRAINT personal_preferences_revision CHECK (revision > 0),
 CONSTRAINT personal_preferences_body CHECK (jsonb_typeof(body)='object')
)"""

READ_SCOPE = """tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
 AND owner_id=scope_requester()
 AND EXISTS(SELECT 1 FROM public.principals p
   WHERE p.tenant_id=personal_preferences.tenant_id AND p.id=scope_actor() AND p.active)
 AND EXISTS(SELECT 1 FROM public.principals p
   WHERE p.tenant_id=personal_preferences.tenant_id AND p.id=scope_requester()
   AND p.kind='human' AND p.active)"""
WRITE_SCOPE = f"({READ_SCOPE}) AND scope_actor()=scope_requester()"

GUARD_SQL = """CREATE FUNCTION public.guard_personal_preferences() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
 BEGIN
  IF TG_OP='INSERT' THEN
   IF NEW.revision<>1 THEN
    RAISE EXCEPTION 'First preference revision must be one' USING ERRCODE='23514';
   END IF;
  ELSIF ROW(NEW.id,NEW.tenant_id,NEW.owner_id,NEW.created_at)
    IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.owner_id,OLD.created_at)
    OR NEW.revision<>OLD.revision+1 THEN
   RAISE EXCEPTION 'Invalid personal preference transition' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END $$"""

SCHEMA_SQL = [
    TABLE_SQL,
    "CREATE INDEX ix_personal_preferences_tenant_id ON public.personal_preferences (tenant_id)",
    "ALTER TABLE public.personal_preferences ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.personal_preferences FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY preferences_read ON public.personal_preferences FOR SELECT "
    f"TO pdos_next_app USING ({READ_SCOPE})",
    f"CREATE POLICY preferences_insert ON public.personal_preferences FOR INSERT "
    f"TO pdos_next_app WITH CHECK ({WRITE_SCOPE})",
    f"CREATE POLICY preferences_update ON public.personal_preferences FOR UPDATE "
    f"TO pdos_next_app USING ({WRITE_SCOPE}) WITH CHECK ({WRITE_SCOPE})",
    "REVOKE ALL ON public.personal_preferences "
    "FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch,pdos_next_app",
    "GRANT SELECT,INSERT,UPDATE ON public.personal_preferences TO pdos_next_app",
    GUARD_SQL,
    "REVOKE ALL ON FUNCTION public.guard_personal_preferences() FROM PUBLIC,pdos_agent",
    "CREATE TRIGGER personal_preferences_guard BEFORE INSERT OR UPDATE "
    "ON public.personal_preferences FOR EACH ROW "
    "EXECUTE FUNCTION public.guard_personal_preferences()",
]
DOWNGRADE_SQL = [
    "ALTER TABLE public.personal_preferences NO FORCE ROW LEVEL SECURITY",
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.personal_preferences) THEN
     RAISE EXCEPTION 'Personal preferences require s0_0831'; END IF; END $$""",
    "DROP TABLE public.personal_preferences",
    "DROP FUNCTION public.guard_personal_preferences()",
]
