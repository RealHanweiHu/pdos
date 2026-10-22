"""P27: allow a named human owner to review G0 in an admitted pilot tenant."""

# ruff: noqa: E501 -- preserve reviewed SQL literals

from alembic import op

from migrations.versions.s0_0778_native_pilot import ordinary_owner

revision = "s0_0812"
down_revision = "s0_0811"
branch_labels = None
depends_on = None


def _reviewer(enable):
    # Preserve the currently installed function, including all actor/ACL checks.
    bind = op.get_bind()
    original = "x.owner_id<>sub.reviewer_id"
    pilot = "(x.owner_id<>sub.reviewer_id OR EXISTS(SELECT 1 FROM public.tenant_pilot_admissions pa WHERE pa.tenant_id=t AND pa.active))"
    body = bind.exec_driver_sql(
        "SELECT pg_get_functiondef('public.m3_reviewer(uuid,uuid,uuid)'::regprocedure)"
    ).scalar_one()
    before, after = (original, pilot) if enable else (pilot, original)
    if body.count(before) != 1:
        raise RuntimeError("Unexpected G0 reviewer function; inspect before migrating")
    bind.exec_driver_sql(body.replace(before, after))


def upgrade():
    ordinary_owner()
    op.execute("ALTER TABLE proposal_submissions DROP CONSTRAINT proposal_submissions_check")
    op.execute(
        "ALTER TABLE proposal_submissions ADD CONSTRAINT proposal_submissions_check CHECK(revision>0 AND option_count>=0)"
    )
    op.execute("ALTER TABLE proposal_decisions DROP CONSTRAINT proposal_decisions_check")
    op.execute("""
CREATE FUNCTION public.guard_g0_pilot_self_review() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE reviewer uuid;
BEGIN
 reviewer=COALESCE((to_jsonb(NEW)->>'reviewer_id')::uuid,(to_jsonb(NEW)->>'decided_by')::uuid);
 IF reviewer=NEW.owner_id THEN
  PERFORM 1 FROM public.tenant_pilot_admissions WHERE tenant_id=NEW.tenant_id AND active FOR SHARE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'G0 owner review requires an active pilot tenant' USING ERRCODE='23514';
  END IF;
  IF public.scope_actor() IS DISTINCT FROM reviewer OR public.scope_requester() IS DISTINCT FROM reviewer
   OR NOT EXISTS(SELECT 1 FROM public.principals p JOIN public.grants g
    ON g.tenant_id=p.tenant_id AND g.principal_id=p.id
    WHERE p.tenant_id=NEW.tenant_id AND p.id=reviewer AND p.kind='human' AND p.active
     AND g.category_id=NEW.category_id AND g.product_manager AND (g.expires_at IS NULL OR g.expires_at>now())) THEN
   RAISE EXCEPTION 'G0 owner review requires the named human product manager' USING ERRCODE='42501';
  END IF;
 END IF;
 RETURN NEW;
END $$
""")
    for table in ("proposal_submissions", "proposal_decisions"):
        op.execute(
            f"CREATE TRIGGER g0_pilot_self_review BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION public.guard_g0_pilot_self_review()"
        )
    op.execute(
        "REVOKE ALL ON FUNCTION public.guard_g0_pilot_self_review() FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
    )
    _reviewer(True)
    _atom(True)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    ordinary_owner()
    if (
        op.get_bind()
        .exec_driver_sql(
            "SELECT EXISTS(SELECT 1 FROM proposal_submissions WHERE reviewer_id=owner_id)"
        )
        .scalar_one()
    ):
        raise RuntimeError("Pilot self-review history exists; preserve it instead of downgrading")
    _atom(False)
    _reviewer(False)
    for table in ("proposal_submissions", "proposal_decisions"):
        op.execute(f"DROP TRIGGER g0_pilot_self_review ON {table}")
    op.execute("DROP FUNCTION public.guard_g0_pilot_self_review()")
    op.execute("ALTER TABLE proposal_submissions DROP CONSTRAINT proposal_submissions_check")
    op.execute(
        "ALTER TABLE proposal_submissions ADD CONSTRAINT proposal_submissions_check CHECK(reviewer_id<>owner_id AND revision>0 AND option_count>=0)"
    )
    op.execute(
        "ALTER TABLE proposal_decisions ADD CONSTRAINT proposal_decisions_check CHECK(decided_by<>owner_id)"
    )
    op.execute("SET LOCAL ROLE NONE")


def _atom(enable):
    bind = op.get_bind()
    original = "OR NEW.owner_id=NEW.reviewer_id THEN"
    pilot = "OR (NEW.owner_id=NEW.reviewer_id AND NOT EXISTS(SELECT 1 FROM public.tenant_pilot_admissions pa WHERE pa.tenant_id=NEW.tenant_id AND pa.active)) THEN"
    body = bind.exec_driver_sql(
        "SELECT pg_get_functiondef('public.m3_atom_guard()'::regprocedure)"
    ).scalar_one()
    before, after = (original, pilot) if enable else (pilot, original)
    if body.count(before) != 1:
        raise RuntimeError("Unexpected G0 receipt guard; inspect before migrating")
    bind.exec_driver_sql(body.replace(before, after))
