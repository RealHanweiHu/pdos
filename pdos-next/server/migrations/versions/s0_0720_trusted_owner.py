"""B8 explicit ordinary owner for the shared schema and trusted RLS helpers.

The deployment administrator provisions pdos_next_owner before migration. This
migration never creates a login or grants runtime membership in the owner role.
"""

from alembic import op
from sqlalchemy import text

revision = "s0_0720"
down_revision = "s0_0719"
branch_labels = None
depends_on = None

RUNTIME_ROLES = ("pdos_next_app", "pdos_next_auth", "pdos_next_dispatch", "pdos_agent")


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def upgrade():
    connection = op.get_bind()
    owner = connection.execute(
        text(
            "SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles "
            "WHERE rolname='pdos_next_owner'"
        )
    ).one_or_none()
    if owner is None or any(owner):
        raise RuntimeError("Pre-provisioned ordinary pdos_next_owner is required")
    for role in RUNTIME_ROLES:
        if connection.scalar(
            text("SELECT pg_has_role(:role,'pdos_next_owner','MEMBER')"), {"role": role}
        ):
            raise RuntimeError("Runtime roles must not inherit the trusted schema owner")

    # The migration identity must already own these objects or have the separately
    # authorized deployment privilege to transfer them. No runtime privilege is added.
    op.execute("ALTER SCHEMA public OWNER TO pdos_next_owner")
    tables = connection.execute(
        text(
            "SELECT relname,relrowsecurity FROM pg_class "
            "WHERE relnamespace='public'::regnamespace AND relkind IN ('r','p') "
            "AND relname NOT IN ('environment_guard','alembic_version') ORDER BY relname"
        )
    ).all()
    for table, rls in tables:
        name = identifier(table)
        op.execute(f"ALTER TABLE public.{name} OWNER TO pdos_next_owner")
        if rls:
            for (policy,) in connection.execute(
                text(
                    "SELECT policyname FROM pg_policies WHERE schemaname='public' "
                    "AND tablename=:table AND permissive='RESTRICTIVE' "
                    "AND roles=ARRAY['public']::name[]"
                ),
                {"table": table},
            ):
                op.execute(
                    f"ALTER POLICY {identifier(policy)} ON public.{name} "
                    f"TO {','.join(RUNTIME_ROLES)}"
                )
            op.execute(
                f"CREATE POLICY owner_internal ON public.{name} TO pdos_next_owner "
                "USING(true) WITH CHECK(true)"
            )
    for signature, definer in connection.execute(
        text(
            "SELECT p.oid::regprocedure::text,p.prosecdef FROM pg_proc p "
            "WHERE p.pronamespace='public'::regnamespace "
            "AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass "
            "AND d.objid=p.oid AND d.deptype='e')"
        )
    ):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO pdos_next_owner")
        if definer:
            op.execute(f"ALTER FUNCTION {signature} SET search_path=pg_catalog,public,pg_temp")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC," + ",".join(RUNTIME_ROLES))


def downgrade():
    # Retain the ordinary owner and its internal policy until the corresponding
    # tables/functions are dropped by the empty-chain downgrade. Reversing a
    # revision must not reintroduce a superuser definer or a writable search path.
    pass
