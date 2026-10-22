"""Explicit internal RLS access for a non-superuser migration/definer owner.

The caller must verify its target and use the table owner's connection. Runtime roles
must never inherit this owner. This does not provision a production account or database.
"""

from psycopg import sql


def configure(connection):
    name, superuser, bypass = connection.execute(
        "SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
    ).fetchone()
    if name != "pdos_next_owner" or superuser or bypass:
        raise RuntimeError("Explicit NOSUPERUSER NOBYPASSRLS owner connection required")
    # PUBLIC restrictive policies also constrain SECURITY DEFINER owners. Preserve
    # their predicate for every runtime role, and give only the isolated owner its
    # explicit internal policy. Otherwise recursive ACL helpers cannot read their roots.
    for table, policy in connection.execute(
        "SELECT tablename,policyname FROM pg_policies WHERE schemaname='public' "
        "AND permissive='RESTRICTIVE' AND roles=ARRAY['public']::name[]"
    ).fetchall():
        connection.execute(
            sql.SQL(
                "ALTER POLICY {} ON {} TO pdos_next_app,pdos_next_auth,"
                "pdos_next_dispatch,pdos_agent"
            ).format(sql.Identifier(policy), sql.Identifier(table))
        )
    for (table,) in connection.execute(
        "SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace "
        "AND relkind='r' AND relrowsecurity"
    ).fetchall():
        connection.execute(
            sql.SQL("DROP POLICY IF EXISTS owner_internal ON {};").format(sql.Identifier(table))
        )
        connection.execute(
            sql.SQL(
                "CREATE POLICY owner_internal ON {} TO pdos_next_owner USING(true) WITH CHECK(true)"
            ).format(sql.Identifier(table))
        )
    connection.execute(
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC,pdos_next_app,pdos_next_auth,"
        "pdos_next_dispatch,pdos_agent"
    )
    # Explicit pg_temp last prevents temporary relation shadowing inside trusted
    # definers. The schema itself is writable only by the isolated owner.
    for (signature,) in connection.execute(
        "SELECT p.oid::regprocedure::text FROM pg_proc p "
        "WHERE p.pronamespace='public'::regnamespace AND p.prosecdef"
    ).fetchall():
        connection.execute(
            sql.SQL("ALTER FUNCTION {} SET search_path=pg_catalog,public,pg_temp").format(
                sql.SQL(signature)
            )
        )
