"""Add bounded standing authority for local recurring meeting generation."""

import sqlalchemy as sa
from alembic import op

revision = "0273_meeting_generation_policy"
down_revision = "0272_meeting_recurrence_start"
branch_labels = None
depends_on = None

DDL = (
    "\nCREATE TABLE cehub_project.meeting_generation_policies (\n\tid UUI"
    "D NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL"
    ", \n\trecurrence_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tst"
    "atus VARCHAR(16) NOT NULL, \n\torganizer_user_id UUID NOT NULL, \n\to"
    "rganizer_auth_version INTEGER NOT NULL, \n\tactive_from DATE NOT NU"
    "LL, \n\tactive_until DATE NOT NULL, \n\tlead_days SMALLINT NOT NULL, "
    "\n\trecurrence_digest VARCHAR(64) NOT NULL, \n\trecurrence_snapshot J"
    "SONB NOT NULL, \n\tnext_check_at TIMESTAMP WITH TIME ZONE, \n\tlast_s"
    "can_at TIMESTAMP WITH TIME ZONE, \n\tfailure_count SMALLINT DEFAULT"
    " 0 NOT NULL, \n\tlast_error_code VARCHAR(64), \n\tcreated_at TIMESTAM"
    "P WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE "
    "NOT NULL, \n\tCONSTRAINT pk_meeting_generation_policies PRIMARY KEY"
    " (id), \n\tCONSTRAINT uq_meeting_generation_recurrence UNIQUE (tena"
    "nt_id, recurrence_id), \n\tCONSTRAINT fk_meeting_generation_recurre"
    "nce FOREIGN KEY(tenant_id, project_id, recurrence_id) REFERENCES "
    "cehub_project.meeting_recurrences (tenant_id, project_id, id) ON "
    "DELETE RESTRICT, \n\tCONSTRAINT fk_meeting_generation_organizer FOR"
    "EIGN KEY(tenant_id, organizer_user_id) REFERENCES cehub_core.user"
    "s (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_meeting_gen"
    "eration_policies_versions CHECK (version>0 AND organizer_auth_ver"
    "sion>=0), \n\tCONSTRAINT ck_meeting_generation_policies_status CHEC"
    "K (status IN ('enabled','paused','attention')), \n\tCONSTRAINT ck_m"
    "eeting_generation_policies_dates CHECK (active_until>=active_from"
    " AND active_until-active_from<=366), \n\tCONSTRAINT ck_meeting_gene"
    "ration_policies_limits CHECK (lead_days BETWEEN 1 AND 60 AND fail"
    "ure_count BETWEEN 0 AND 3), \n\tCONSTRAINT ck_meeting_generation_po"
    "licies_next_check CHECK ((status='enabled')=(next_check_at IS NOT"
    " NULL)), \n\tCONSTRAINT ck_meeting_generation_policies_snapshot CHE"
    "CK (recurrence_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(recurre"
    "nce_snapshot)='object' AND recurrence_snapshot ?& ARRAY['id','pro"
    "ject_id','tenant_id'] AND recurrence_snapshot->>'id'=recurrence_i"
    "d::text AND recurrence_snapshot->>'project_id'=project_id::text A"
    "ND recurrence_snapshot->>'tenant_id'=tenant_id::text)\n)\n\n"
)
GUARD = (
    "CREATE FUNCTION cehub_project.guard_meeting_generation_policy() R"
    "ETURNS trigger\nLANGUAGE plpgsql SET search_path=pg_catalog AS $$\n"
    "BEGIN\n PERFORM 1 FROM cehub_project.projects WHERE tenant_id=NEW."
    "tenant_id AND id=NEW.project_id FOR UPDATE;\n IF TG_OP='UPDATE' TH"
    "EN\n  IF (NEW.id,NEW.tenant_id,NEW.project_id,NEW.recurrence_id,NE"
    "W.created_at)\n      IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.pr"
    "oject_id,OLD.recurrence_id,OLD.created_at)\n     OR NEW.version NO"
    "T IN (OLD.version,OLD.version+1) THEN\n   RAISE EXCEPTION 'Generat"
    "ion policy must preserve identity and advance at most one version"
    "' USING ERRCODE='23514';\n  END IF;\n  IF NEW.version=OLD.version A"
    "ND (\n      (to_jsonb(NEW)-ARRAY['status','next_check_at','last_sc"
    "an_at','failure_count','last_error_code','updated_at'])\n      IS "
    "DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','next_check_at','last"
    "_scan_at','failure_count','last_error_code','updated_at'])\n      "
    "OR (OLD.status<>'enabled' AND NEW.status<>OLD.status)) THEN\n   RA"
    "ISE EXCEPTION 'Policy configuration changes require a new version"
    "' USING ERRCODE='23514';\n  END IF;\n ELSIF NEW.version<>1 THEN\n  R"
    "AISE EXCEPTION 'Generation policy must start at version one' USIN"
    "G ERRCODE='23514';\n END IF;\n IF NEW.status='enabled' AND (TG_OP='"
    "INSERT' OR NEW.version<>OLD.version) THEN\n  IF NOT EXISTS(SELECT "
    "1 FROM cehub_project.meeting_recurrences r\n      JOIN cehub_proje"
    "ct.projects p ON p.tenant_id=r.tenant_id AND p.id=r.project_id\n  "
    "    JOIN cehub_core.tenants t ON t.id=r.tenant_id\n      JOIN cehu"
    "b_project.project_members m ON m.tenant_id=p.tenant_id AND m.proj"
    "ect_id=p.id\n      JOIN cehub_core.users u ON u.tenant_id=m.tenant"
    "_id AND u.id=m.user_id\n      WHERE r.tenant_id=NEW.tenant_id AND "
    "r.project_id=NEW.project_id AND r.id=NEW.recurrence_id\n       AND"
    " r.status='active' AND p.status NOT IN ('completed','archived') A"
    "ND t.status='active'\n       AND u.id=NEW.organizer_user_id AND u."
    "is_active\n       AND u.role IN ('owner','admin','project_manager'"
    ") AND u.auth_version=NEW.organizer_auth_version) THEN\n   RAISE EX"
    "CEPTION 'Enabled policy requires an active named project organize"
    "r and recurrence' USING ERRCODE='23514';\n  END IF;\n END IF;\n RETU"
    "RN NEW;\nEND $$;\nCREATE TRIGGER meeting_generation_policy_guard BE"
    "FORE INSERT OR UPDATE ON cehub_project.meeting_generation_policie"
    "s\nFOR EACH ROW EXECUTE FUNCTION cehub_project.guard_meeting_gener"
    "ation_policy();"
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_meeting_recurrences_project_id",
        "meeting_recurrences",
        ["tenant_id", "project_id", "id"],
        schema="cehub_project",
    )
    op.execute(DDL)
    op.execute(
        "CREATE INDEX ix_meeting_generation_due ON cehub_project.meeting_generation_policies "
        "(next_check_at, id) WHERE status='enabled'"
    )
    op.execute(GUARD)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.meeting_generation_policies)"))
        .scalar_one()
    ):
        raise RuntimeError("Generation policies and their audit history must be retained")
    op.drop_table("meeting_generation_policies", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_meeting_generation_policy()")
    op.drop_constraint(
        "uq_meeting_recurrences_project_id",
        "meeting_recurrences",
        schema="cehub_project",
        type_="unique",
    )
