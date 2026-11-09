"""Human sign-in: passwords, one-time invitation links, throttling and revocable sessions.

D214/D86/D192 (P78). The runtime roles keep separate duties:

- ``pdos_next_auth`` has no tenant scope before sign-in. It reaches credentials,
  invitations and the throttle ledger only through the SECURITY DEFINER functions
  below, which hold the lifetime and throttle policy themselves (no caller-supplied
  limits).
- ``pdos_next_app`` manages accounts inside a tenant transaction, and only while the
  actor is an active human tenant administrator. It never reads a password hash or
  an invitation token hash, can only clear a password, and can never write its own
  administrator row or deactivate itself.
- ``pdos_agent`` and ``pdos_next_dispatch`` get nothing.
"""

TENANT = "tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid"
ADMIN = "public.account_administrator()"
RUNTIME_ROLES = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"

# Session policy lives in the database so a caller cannot choose a laxer one.
SESSION_DAYS = 7
IDLE_SECONDS = 12 * 3600
LOGIN_FAILURES = 5
SOURCE_FAILURES = 30
WINDOW_MINUTES = 15
SESSION = (
    "INSERT INTO public.login_sessions(token_hash,tenant_id,principal_id,expires_at,revoked,"
    "origin,issued_at,idle_timeout_seconds) VALUES ({hash},{tenant},{principal},"
    f"now()+interval '{SESSION_DAYS} days',false,'password',now(),{IDLE_SECONDS})"
)
EVENT = (
    "INSERT INTO public.account_events(id,tenant_id,created_at,subject_id,actor_id,kind,detail) "
    "VALUES (gen_random_uuid(),{tenant},now(),{principal},{principal},{kind},{detail})"
)
ATTEMPT = (
    "INSERT INTO public.sign_in_attempts(id,created_at,login_key,source_key,succeeded) "
    "VALUES (gen_random_uuid(),now(),p_login_key,p_source_key,{succeeded})"
)

TABLE_SQL = [
    "ALTER TABLE public.login_sessions ADD COLUMN origin VARCHAR(16) DEFAULT 'tool' NOT NULL",
    "ALTER TABLE public.login_sessions ADD COLUMN issued_at TIMESTAMP WITH TIME ZONE "
    "DEFAULT now() NOT NULL",
    "ALTER TABLE public.login_sessions ADD COLUMN last_seen_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE public.login_sessions ADD COLUMN idle_timeout_seconds INTEGER",
    "ALTER TABLE public.login_sessions ADD CONSTRAINT login_session_origin "
    "CHECK (origin IN ('tool','password'))",
    "ALTER TABLE public.login_sessions ADD CONSTRAINT login_session_idle "
    "CHECK (idle_timeout_seconds IS NULL OR idle_timeout_seconds > 0)",
    "ALTER TABLE public.login_sessions ADD CONSTRAINT login_session_password_idle "
    "CHECK (origin <> 'password' OR idle_timeout_seconds IS NOT NULL)",
    "CREATE INDEX ix_login_sessions_principal ON public.login_sessions (tenant_id, principal_id)",
    """CREATE TABLE public.human_credentials (
 principal_id UUID NOT NULL, login_name VARCHAR(64) NOT NULL, password_hash VARCHAR(255),
 password_changed_at TIMESTAMP WITH TIME ZONE, created_by UUID NOT NULL,
 id UUID NOT NULL, tenant_id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (id), UNIQUE (tenant_id, id), UNIQUE (tenant_id, principal_id), UNIQUE (login_name),
 FOREIGN KEY (tenant_id, principal_id) REFERENCES public.principals (tenant_id, id),
 FOREIGN KEY (tenant_id, created_by) REFERENCES public.principals (tenant_id, id),
 CONSTRAINT human_credential_login_shape CHECK (login_name ~ '^[a-z0-9][a-z0-9._-]{2,63}$'),
 CONSTRAINT human_credential_password_shape
  CHECK (password_hash IS NULL OR password_hash LIKE 'scrypt$%'),
 CONSTRAINT human_credential_password_time
  CHECK ((password_hash IS NULL) = (password_changed_at IS NULL))
)""",
    "CREATE INDEX ix_human_credentials_tenant_id ON public.human_credentials (tenant_id)",
    """CREATE TABLE public.account_invitations (
 principal_id UUID NOT NULL, purpose VARCHAR(16) NOT NULL, token_hash VARCHAR(64) NOT NULL,
 expires_at TIMESTAMP WITH TIME ZONE NOT NULL, used_at TIMESTAMP WITH TIME ZONE,
 revoked_at TIMESTAMP WITH TIME ZONE, created_by UUID NOT NULL,
 id UUID NOT NULL, tenant_id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (id), UNIQUE (tenant_id, id), UNIQUE (token_hash),
 FOREIGN KEY (tenant_id, principal_id) REFERENCES public.principals (tenant_id, id),
 FOREIGN KEY (tenant_id, created_by) REFERENCES public.principals (tenant_id, id),
 CONSTRAINT account_invitation_purpose CHECK (purpose IN ('invite','reset')),
 CONSTRAINT account_invitation_token_hash CHECK (token_hash ~ '^[0-9a-f]{64}$'),
 CONSTRAINT account_invitation_single_end CHECK (used_at IS NULL OR revoked_at IS NULL),
 CONSTRAINT account_invitation_72_hours
  CHECK (expires_at > created_at AND expires_at <= created_at + interval '72 hours')
)""",
    "CREATE INDEX ix_account_invitations_tenant_id ON public.account_invitations (tenant_id)",
    "CREATE INDEX ix_account_invitations_principal "
    "ON public.account_invitations (tenant_id, principal_id)",
    """CREATE TABLE public.account_events (
 subject_id UUID NOT NULL, actor_id UUID NOT NULL, kind VARCHAR(40) NOT NULL, detail JSONB NOT NULL,
 id UUID NOT NULL, tenant_id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (id), UNIQUE (tenant_id, id),
 FOREIGN KEY (tenant_id, subject_id) REFERENCES public.principals (tenant_id, id),
 FOREIGN KEY (tenant_id, actor_id) REFERENCES public.principals (tenant_id, id),
 CONSTRAINT account_event_kind CHECK (kind IN ('account.create','invitation.issue',
  'invitation.accept','password.reset','password.set','account.deactivate',
  'account.reactivate','sessions.revoke','administrator.grant','administrator.revoke',
  'sign_in','sign_out')),
 CONSTRAINT account_event_detail CHECK (jsonb_typeof(detail) = 'object')
)""",
    "CREATE INDEX ix_account_events_tenant_id ON public.account_events (tenant_id)",
    "CREATE INDEX ix_account_events_subject ON public.account_events (tenant_id, subject_id)",
    """CREATE TABLE public.sign_in_attempts (
 id UUID NOT NULL, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 login_key VARCHAR(64) NOT NULL, source_key VARCHAR(64) NOT NULL, succeeded BOOLEAN NOT NULL,
 PRIMARY KEY (id),
 CONSTRAINT sign_in_attempt_keys
  CHECK (login_key ~ '^[0-9a-f]{64}$' AND source_key ~ '^[0-9a-f]{64}$')
)""",
    "CREATE INDEX ix_sign_in_attempts_login ON public.sign_in_attempts (login_key, created_at)",
    "CREATE INDEX ix_sign_in_attempts_source ON public.sign_in_attempts (source_key, created_at)",
]

ADMIN_FUNCTION = f"""CREATE FUNCTION public.account_administrator() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT public.scope_actor() IS NOT NULL AND public.scope_actor()=public.scope_requester()
  AND EXISTS(SELECT 1 FROM public.tenant_administrators a JOIN public.principals p
   ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
   WHERE a.{TENANT} AND a.principal_id=public.scope_actor()
    AND a.active AND p.active AND p.kind='human')
$$"""

SELF_OR_ADMIN = f"{TENANT} AND (principal_id=public.scope_actor() OR {ADMIN})"
SECURITY_SQL = [
    ADMIN_FUNCTION,
    "REVOKE ALL ON FUNCTION public.account_administrator() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.account_administrator() TO pdos_next_app",
]
for table in ("human_credentials", "account_invitations", "account_events", "sign_in_attempts"):
    SECURITY_SQL += [
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner_internal ON public.{table} TO pdos_next_owner "
        "USING (true) WITH CHECK (true)",
        f"REVOKE ALL ON public.{table} FROM {RUNTIME_ROLES}",
    ]
SECURITY_SQL += [
    # Credentials: the app sees whether a password exists, never the hash, and can
    # only clear it. Setting a password belongs to auth_invitation_accept.
    f"CREATE POLICY account_read ON public.human_credentials FOR SELECT TO pdos_next_app "
    f"USING ({SELF_OR_ADMIN})",
    f"CREATE POLICY account_create ON public.human_credentials FOR INSERT TO pdos_next_app "
    f"WITH CHECK ({TENANT} AND {ADMIN} AND created_by=public.scope_actor() "
    "AND password_hash IS NULL)",
    f"CREATE POLICY account_password_clear ON public.human_credentials FOR UPDATE "
    f"TO pdos_next_app USING ({TENANT} AND {ADMIN}) "
    f"WITH CHECK ({TENANT} AND {ADMIN} AND password_hash IS NULL)",
    "GRANT SELECT (id,tenant_id,created_at,principal_id,login_name,password_changed_at,"
    "created_by) ON public.human_credentials TO pdos_next_app",
    "GRANT INSERT ON public.human_credentials TO pdos_next_app",
    "GRANT UPDATE (password_hash,password_changed_at) ON public.human_credentials TO pdos_next_app",
    # Invitations: administrators issue and revoke; only the token holder uses one.
    f"CREATE POLICY invitation_read ON public.account_invitations FOR SELECT TO pdos_next_app "
    f"USING ({TENANT} AND {ADMIN})",
    f"CREATE POLICY invitation_issue ON public.account_invitations FOR INSERT TO pdos_next_app "
    f"WITH CHECK ({TENANT} AND {ADMIN} AND created_by=public.scope_actor() "
    "AND used_at IS NULL AND revoked_at IS NULL)",
    f"CREATE POLICY invitation_revoke ON public.account_invitations FOR UPDATE "
    f"TO pdos_next_app USING ({TENANT} AND {ADMIN}) "
    f"WITH CHECK ({TENANT} AND {ADMIN} AND used_at IS NULL AND revoked_at IS NOT NULL)",
    "GRANT SELECT (id,tenant_id,created_at,principal_id,purpose,expires_at,used_at,revoked_at,"
    "created_by) ON public.account_invitations TO pdos_next_app",
    "GRANT INSERT ON public.account_invitations TO pdos_next_app",
    "GRANT UPDATE (revoked_at) ON public.account_invitations TO pdos_next_app",
    # Events: append-only; administrators append and read, a person reads their own.
    f"CREATE POLICY account_event_read ON public.account_events FOR SELECT TO pdos_next_app "
    f"USING ({TENANT} AND (subject_id=public.scope_actor() OR {ADMIN}))",
    f"CREATE POLICY account_event_append ON public.account_events FOR INSERT "
    f"TO pdos_next_app WITH CHECK ({TENANT} AND {ADMIN} AND actor_id=public.scope_actor())",
    "GRANT SELECT,INSERT ON public.account_events TO pdos_next_app",
    "CREATE TRIGGER account_events_append_only BEFORE UPDATE OR DELETE ON public.account_events "
    "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    # Sessions: the auth role keeps its existing lookup; the app may revoke its own
    # sessions, or anyone's in the tenant when it is an administrator.
    "ALTER TABLE public.login_sessions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.login_sessions FORCE ROW LEVEL SECURITY",
    "CREATE POLICY owner_internal ON public.login_sessions TO pdos_next_owner "
    "USING (true) WITH CHECK (true)",
    "CREATE POLICY auth_lookup ON public.login_sessions FOR SELECT TO pdos_next_auth USING (true)",
    f"CREATE POLICY account_session_read ON public.login_sessions FOR SELECT TO pdos_next_app "
    f"USING ({SELF_OR_ADMIN})",
    f"CREATE POLICY account_session_revoke ON public.login_sessions FOR UPDATE "
    f"TO pdos_next_app USING ({SELF_OR_ADMIN}) WITH CHECK ({TENANT} AND revoked)",
    "GRANT SELECT (tenant_id,principal_id,expires_at,revoked,origin,issued_at,last_seen_at,"
    "idle_timeout_seconds) ON public.login_sessions TO pdos_next_app",
    "GRANT UPDATE (revoked) ON public.login_sessions TO pdos_next_app",
    # Administrator rows: the existing kernel_scope policy lets a person reach their own
    # row, so the restrictive policies below are what forbid self-elevation (P78).
    f"CREATE POLICY account_admin_read ON public.tenant_administrators FOR SELECT "
    f"TO pdos_next_app USING ({TENANT} AND {ADMIN})",
    f"CREATE POLICY account_admin_grant ON public.tenant_administrators FOR INSERT "
    f"TO pdos_next_app WITH CHECK ({TENANT} AND {ADMIN} "
    "AND principal_id IS DISTINCT FROM public.scope_actor())",
    f"CREATE POLICY account_admin_change ON public.tenant_administrators FOR UPDATE "
    f"TO pdos_next_app USING ({TENANT} AND {ADMIN} "
    "AND principal_id IS DISTINCT FROM public.scope_actor()) "
    f"WITH CHECK ({TENANT} AND {ADMIN} AND principal_id IS DISTINCT FROM public.scope_actor())",
    "CREATE POLICY account_admin_not_self ON public.tenant_administrators AS RESTRICTIVE "
    f"FOR INSERT TO pdos_next_app WITH CHECK ({ADMIN} "
    "AND principal_id IS DISTINCT FROM public.scope_actor())",
    "CREATE POLICY account_admin_not_self_change ON public.tenant_administrators AS RESTRICTIVE "
    f"FOR UPDATE TO pdos_next_app USING (true) WITH CHECK ({ADMIN} "
    "AND principal_id IS DISTINCT FROM public.scope_actor())",
    "GRANT INSERT, UPDATE (active) ON public.tenant_administrators TO pdos_next_app",
    # Nobody deactivates themselves (P78).
    "CREATE POLICY account_not_self_deactivate ON public.principals AS RESTRICTIVE "
    "FOR UPDATE TO pdos_next_app USING (true) "
    "WITH CHECK (active OR id IS DISTINCT FROM public.scope_actor())",
]

DEFINER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp"
FUNCTIONS = {
    "auth_sign_in_lookup(text,text,text)": f"""CREATE FUNCTION public.auth_sign_in_lookup(
 p_login text, p_login_key text, p_source_key text)
 RETURNS TABLE(throttled boolean, found_tenant uuid, found_principal uuid, found_hash text)
 {DEFINER} AS $$
DECLARE since timestamptz := now() - interval '{WINDOW_MINUTES} minutes'; last_ok timestamptz;
BEGIN
 SELECT max(a.created_at) INTO last_ok FROM public.sign_in_attempts a
  WHERE a.login_key=p_login_key AND a.succeeded AND a.created_at>=since;
 IF (SELECT count(*) FROM public.sign_in_attempts a WHERE a.login_key=p_login_key
      AND NOT a.succeeded AND a.created_at>=GREATEST(since, COALESCE(last_ok, since)))
      >= {LOGIN_FAILURES}
  OR (SELECT count(*) FROM public.sign_in_attempts a WHERE a.source_key=p_source_key
      AND NOT a.succeeded AND a.created_at>=since) >= {SOURCE_FAILURES} THEN
  RETURN QUERY SELECT true, NULL::uuid, NULL::uuid, NULL::text;
  RETURN;
 END IF;
 RETURN QUERY SELECT false, c.tenant_id, c.principal_id, c.password_hash::text
  FROM public.human_credentials c JOIN public.principals p
   ON p.tenant_id=c.tenant_id AND p.id=c.principal_id
  WHERE c.login_name=p_login AND c.password_hash IS NOT NULL AND p.active AND p.kind='human';
 IF NOT FOUND THEN RETURN QUERY SELECT false, NULL::uuid, NULL::uuid, NULL::text; END IF;
END $$""",
    "auth_sign_in_failed(text,text)": f"""CREATE FUNCTION public.auth_sign_in_failed(
 p_login_key text, p_source_key text) RETURNS void
 {DEFINER} AS $$
BEGIN
 DELETE FROM public.sign_in_attempts WHERE created_at < now() - interval '1 day';
 {ATTEMPT.format(succeeded="false")};
END $$""",
    "auth_sign_in_issue(text,text,uuid,uuid,text,text)": f"""CREATE FUNCTION
 public.auth_sign_in_issue(p_login_key text, p_source_key text, p_tenant uuid,
 p_principal uuid, p_hash text, p_token_hash text)
 RETURNS TABLE(session_expires timestamptz, session_idle integer)
 {DEFINER} AS $$
BEGIN
 IF p_token_hash !~ '^[0-9a-f]{{64}}$' THEN
  RAISE EXCEPTION 'Invalid session material' USING ERRCODE='22023';
 END IF;
 -- The verified hash must still be current: a reset or deactivation in between wins.
 -- Lock order is person, then credential, the same as every administrator action.
 PERFORM 1 FROM public.principals p
  WHERE p.tenant_id=p_tenant AND p.id=p_principal AND p.active AND p.kind='human' FOR SHARE;
 IF FOUND THEN
  PERFORM 1 FROM public.human_credentials c
   WHERE c.tenant_id=p_tenant AND c.principal_id=p_principal AND c.password_hash=p_hash
   FOR SHARE;
 END IF;
 IF NOT FOUND THEN
  {ATTEMPT.format(succeeded="false")};
  RETURN;
 END IF;
 {SESSION.format(hash="p_token_hash", tenant="p_tenant", principal="p_principal")};
 {ATTEMPT.format(succeeded="true")};
 {EVENT.format(tenant="p_tenant", principal="p_principal", kind="'sign_in'", detail="'{}'::jsonb")};
 RETURN QUERY SELECT now() + interval '{SESSION_DAYS} days', {IDLE_SECONDS};
END $$""",
    "auth_session_touch(text)": f"""CREATE FUNCTION public.auth_session_touch(p_token_hash text)
 RETURNS void {DEFINER} AS $$
BEGIN
 UPDATE public.login_sessions SET last_seen_at=now()
  WHERE token_hash=p_token_hash AND NOT revoked AND idle_timeout_seconds IS NOT NULL
   AND COALESCE(last_seen_at, issued_at) < now() - interval '60 seconds';
END $$""",
    "auth_session_end(text)": f"""CREATE FUNCTION public.auth_session_end(p_token_hash text)
 RETURNS boolean {DEFINER} AS $$
DECLARE t uuid; p uuid;
BEGIN
 UPDATE public.login_sessions SET revoked=true WHERE token_hash=p_token_hash AND NOT revoked
  RETURNING tenant_id, principal_id INTO t, p;
 IF NOT FOUND THEN RETURN false; END IF;
 {EVENT.format(tenant="t", principal="p", kind="'sign_out'", detail="'{}'::jsonb")};
 RETURN true;
END $$""",
    "auth_invitation_view(text)": """CREATE FUNCTION public.auth_invitation_view(p_token_hash text)
 RETURNS TABLE(invitation_state text, invitation_purpose text, person_name text,
  person_login text, invitation_expires timestamptz)
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 RETURN QUERY SELECT s.state, i.purpose::text,
   CASE WHEN s.state='valid' THEN p.name::text END,
   CASE WHEN s.state='valid' THEN c.login_name::text END, i.expires_at
  FROM public.account_invitations i
  JOIN public.principals p ON p.tenant_id=i.tenant_id AND p.id=i.principal_id
  JOIN public.human_credentials c ON c.tenant_id=i.tenant_id AND c.principal_id=i.principal_id
  CROSS JOIN LATERAL (SELECT CASE WHEN i.used_at IS NOT NULL THEN 'used'
   WHEN i.revoked_at IS NOT NULL THEN 'revoked'
   WHEN NOT p.active OR p.kind<>'human' THEN 'inactive'
   WHEN i.expires_at <= now() THEN 'expired' ELSE 'valid' END AS state) s
  WHERE i.token_hash=p_token_hash;
END $$""",
    "auth_invitation_accept(text,text,text)": f"""CREATE FUNCTION public.auth_invitation_accept(
 p_token_hash text, p_password_hash text, p_session_hash text)
 RETURNS TABLE(invitation_state text, session_tenant uuid, session_principal uuid,
  session_expires timestamptz, session_idle integer)
 {DEFINER} AS $$
DECLARE i public.account_invitations%ROWTYPE; person_ready boolean; state text;
BEGIN
 IF p_password_hash NOT LIKE 'scrypt$%' OR p_session_hash !~ '^[0-9a-f]{{64}}$' THEN
  RAISE EXCEPTION 'Invalid sign-in material' USING ERRCODE='22023';
 END IF;
 SELECT * INTO i FROM public.account_invitations a WHERE a.token_hash=p_token_hash;
 IF NOT FOUND THEN
  RETURN QUERY SELECT 'missing'::text, NULL::uuid, NULL::uuid, NULL::timestamptz, NULL::integer;
  RETURN;
 END IF;
 -- Lock the person first, then the link: the same order as deactivation and reset,
 -- so a concurrent administrator action either finishes first or waits.
 SELECT p.active AND p.kind='human' INTO person_ready FROM public.principals p
  WHERE p.tenant_id=i.tenant_id AND p.id=i.principal_id FOR UPDATE;
 SELECT * INTO i FROM public.account_invitations a WHERE a.id=i.id FOR UPDATE;
 state := CASE WHEN i.used_at IS NOT NULL THEN 'used' WHEN i.revoked_at IS NOT NULL THEN 'revoked'
  WHEN NOT COALESCE(person_ready, false) THEN 'inactive'
  WHEN i.expires_at <= now() THEN 'expired' END;
 IF state IS NOT NULL THEN
  RETURN QUERY SELECT state, NULL::uuid, NULL::uuid, NULL::timestamptz, NULL::integer;
  RETURN;
 END IF;
 UPDATE public.account_invitations SET used_at=now() WHERE id=i.id;
 UPDATE public.account_invitations SET revoked_at=now()
  WHERE tenant_id=i.tenant_id AND principal_id=i.principal_id AND id<>i.id
   AND used_at IS NULL AND revoked_at IS NULL;
 UPDATE public.human_credentials SET password_hash=p_password_hash, password_changed_at=now()
  WHERE tenant_id=i.tenant_id AND principal_id=i.principal_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Invitation has no credential' USING ERRCODE='23503'; END IF;
 UPDATE public.login_sessions SET revoked=true
  WHERE tenant_id=i.tenant_id AND principal_id=i.principal_id AND NOT revoked;
 {SESSION.format(hash="p_session_hash", tenant="i.tenant_id", principal="i.principal_id")};
 {
        EVENT.format(
            tenant="i.tenant_id",
            principal="i.principal_id",
            kind="CASE WHEN i.purpose='invite' THEN 'invitation.accept' ELSE 'password.set' END",
            detail="jsonb_build_object('invitation_id', i.id)",
        )
    };
 RETURN QUERY SELECT 'accepted'::text, i.tenant_id, i.principal_id,
  now() + interval '{SESSION_DAYS} days', {IDLE_SECONDS};
END $$""",
}
FUNCTION_SQL = []
for signature, body in FUNCTIONS.items():
    FUNCTION_SQL += [
        body,
        f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC",
        f"GRANT EXECUTE ON FUNCTION public.{signature} TO pdos_next_auth",
    ]

UP_SQL = TABLE_SQL + SECURITY_SQL + FUNCTION_SQL

HISTORY_SQL = """DO $human_sign_in_history$
BEGIN
 IF EXISTS(SELECT 1 FROM public.human_credentials)
  OR EXISTS(SELECT 1 FROM public.account_invitations)
  OR EXISTS(SELECT 1 FROM public.account_events)
  OR EXISTS(SELECT 1 FROM public.login_sessions WHERE origin='password') THEN
  RAISE EXCEPTION 'Human sign-in history exists; preserve it before downgrading s0_0856'
   USING ERRCODE='23514';
 END IF;
END $human_sign_in_history$"""

DOWN_SQL = [
    HISTORY_SQL,
    *(f"DROP FUNCTION public.{signature}" for signature in FUNCTIONS),
    "DROP POLICY account_not_self_deactivate ON public.principals",
    *(
        f"DROP POLICY {name} ON public.tenant_administrators"
        for name in (
            "account_admin_read",
            "account_admin_grant",
            "account_admin_change",
            "account_admin_not_self",
            "account_admin_not_self_change",
        )
    ),
    "REVOKE INSERT, UPDATE ON public.tenant_administrators FROM pdos_next_app",
    *(
        f"DROP POLICY {name} ON public.login_sessions"
        for name in (
            "owner_internal",
            "auth_lookup",
            "account_session_read",
            "account_session_revoke",
        )
    ),
    "REVOKE SELECT, UPDATE ON public.login_sessions FROM pdos_next_app",
    "ALTER TABLE public.login_sessions NO FORCE ROW LEVEL SECURITY",
    "ALTER TABLE public.login_sessions DISABLE ROW LEVEL SECURITY",
    "DROP TABLE public.sign_in_attempts",
    "DROP TABLE public.account_events",
    "DROP TABLE public.account_invitations",
    "DROP TABLE public.human_credentials",
    "DROP FUNCTION public.account_administrator()",
    "DROP INDEX public.ix_login_sessions_principal",
    "ALTER TABLE public.login_sessions DROP CONSTRAINT login_session_password_idle",
    "ALTER TABLE public.login_sessions DROP CONSTRAINT login_session_idle",
    "ALTER TABLE public.login_sessions DROP CONSTRAINT login_session_origin",
    "ALTER TABLE public.login_sessions DROP COLUMN idle_timeout_seconds",
    "ALTER TABLE public.login_sessions DROP COLUMN last_seen_at",
    "ALTER TABLE public.login_sessions DROP COLUMN issued_at",
    "ALTER TABLE public.login_sessions DROP COLUMN origin",
]
