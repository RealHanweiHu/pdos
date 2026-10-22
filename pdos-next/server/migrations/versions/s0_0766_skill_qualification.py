"""Private immutable reviews, named qualifications and server-owned pilot admission."""

# SQL statements retain their reviewable clauses.
# ruff: noqa: E501

from alembic import op
from sqlalchemy import text

from migrations.versions.s0_0762_category_source_consumers import ordinary_owner

revision = "s0_0766"
down_revision = "s0_0765"
branch_labels = None
depends_on = None

FIELDS = (
    "pilot",
    "qualification_revoked",
    "qualified_skill_version",
    "qualified_model_version",
    "qualified_skill_digest",
    "qualified_tool_digest",
    "qualified_model_digest",
    "review_case_refs",
    "quality_paused",
    "reviewed_by",
    "qualification_id",
    "quality_review_id",
)


def upgrade():
    ordinary_owner()
    op.execute("""CREATE TABLE tenant_pilot_admissions(tenant_id uuid PRIMARY KEY,
      active boolean NOT NULL DEFAULT false, approval_reference varchar(2000) NOT NULL,
      created_at timestamptz NOT NULL)""")
    op.execute("""CREATE TABLE agent_skill_review_batches(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,
      created_at timestamptz NOT NULL,reviewed_by uuid NOT NULL,skill_key varchar(160) NOT NULL,
      skill_version varchar(160) NOT NULL,skill_digest varchar(64) NOT NULL,tool_digest varchar(64) NOT NULL,
      model_version varchar(200) NOT NULL,model_digest varchar(64) NOT NULL,model_label varchar(200) NOT NULL,
      cases jsonb NOT NULL,receipt_id uuid NOT NULL,UNIQUE(tenant_id,id),
      FOREIGN KEY(tenant_id,reviewed_by) REFERENCES principals(tenant_id,id),
      CONSTRAINT skill_review_receipt_fk FOREIGN KEY(tenant_id,receipt_id) REFERENCES action_receipts(tenant_id,id)
        DEFERRABLE INITIALLY DEFERRED)""")
    op.execute("""CREATE TABLE agent_skill_qualifications(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,
      created_at timestamptz NOT NULL,decided_by uuid NOT NULL,skill_key varchar(160) NOT NULL,
      decision varchar(16) NOT NULL,reason varchar(4000) NOT NULL,after_snapshot jsonb NOT NULL,
      receipt_id uuid NOT NULL,UNIQUE(tenant_id,id),
      FOREIGN KEY(tenant_id,decided_by) REFERENCES principals(tenant_id,id),
      CONSTRAINT skill_decision_receipt_fk FOREIGN KEY(tenant_id,receipt_id) REFERENCES action_receipts(tenant_id,id)
        DEFERRABLE INITIALLY DEFERRED)""")
    for table in ("agent_skill_review_batches", "agent_skill_qualifications"):
        op.execute(f"CREATE INDEX ix_{table}_tenant_id ON {table}(tenant_id)")
    op.execute(
        "CREATE INDEX ix_skill_reviews_owner ON agent_skill_review_batches(tenant_id,reviewed_by,skill_key,created_at,id)"
    )
    op.execute(
        "ALTER TABLE tenant_skill_enablements ALTER COLUMN qualified_model_version TYPE varchar(200)"
    )
    for column in ("qualified_skill_digest", "qualified_tool_digest", "qualified_model_digest"):
        op.execute(f"ALTER TABLE tenant_skill_enablements ADD COLUMN {column} varchar(64)")
    for column in ("qualification_id", "quality_review_id"):
        op.execute(f"ALTER TABLE tenant_skill_enablements ADD COLUMN {column} uuid")
    op.execute(
        "ALTER TABLE tenant_skill_enablements ADD COLUMN quality_paused boolean NOT NULL DEFAULT false"
    )
    for name, column, table in [
        ("skill_qualification_fk", "qualification_id", "agent_skill_qualifications"),
        ("skill_quality_review_fk", "quality_review_id", "agent_skill_review_batches"),
    ]:
        op.execute(
            f"ALTER TABLE tenant_skill_enablements ADD CONSTRAINT {name} FOREIGN KEY(tenant_id,{column}) REFERENCES {table}(tenant_id,id) DEFERRABLE INITIALLY DEFERRED"
        )
    for table, owner in [
        ("tenant_pilot_admissions", None),
        ("agent_skill_review_batches", "reviewed_by"),
        ("agent_skill_qualifications", "decided_by"),
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        predicate = "tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid"
        if owner:
            predicate += f" AND {owner}=scope_actor() AND scope_actor()=scope_requester() AND EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id={table}.tenant_id AND p.id=scope_actor() AND p.active AND p.kind='human')"
        op.execute(f"CREATE POLICY skill_read ON {table} FOR SELECT USING ({predicate})")
        op.execute(
            f"REVOKE ALL ON {table} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch,pdos_next_app"
        )
        op.execute(f"GRANT SELECT ON {table} TO pdos_next_app")
        if owner:
            op.execute(
                f"CREATE POLICY skill_append ON {table} FOR INSERT WITH CHECK ({predicate} AND kernel_admin_authorized())"
            )
            op.execute(f"GRANT INSERT ON {table} TO pdos_next_app")
            op.execute(
                f"CREATE TRIGGER skill_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION kernel_append_only()"
            )
    op.execute("""CREATE FUNCTION kernel_skill_review_atom() RETURNS trigger LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$
      DECLARE operation text; person uuid; event_type text;
      BEGIN
        operation=CASE WHEN TG_TABLE_NAME='agent_skill_review_batches' THEN 'ai.skill.review.record' ELSE 'ai.skill.qualify' END;
        person=COALESCE((to_jsonb(NEW)->>'reviewed_by')::uuid,(to_jsonb(NEW)->>'decided_by')::uuid);
        event_type=CASE WHEN TG_TABLE_NAME='agent_skill_review_batches' THEN 'ai.skill_review_recorded' ELSE 'ai.skill_qualified' END;
        IF NOT EXISTS(SELECT 1 FROM action_receipts r JOIN audit_entries a ON a.receipt_id=r.id AND a.tenant_id=r.tenant_id
          JOIN outbox_events o ON o.receipt_id=r.id AND o.tenant_id=r.tenant_id
          JOIN confirmations c ON c.id=r.confirmation_id AND c.tenant_id=r.tenant_id
          WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND r.operation=operation
          AND r.actor_id=person AND r.requester_id=person AND r.agent_run_id IS NULL AND r.run_id IS NULL
          AND r.subject_id=NEW.id AND r.subject_revision=1 AND c.consumed AND c.actor_id=person
          AND c.operation=operation AND o.type=event_type)
        THEN RAISE EXCEPTION 'Human skill review/decision receipt atom required'; END IF;
        RETURN NEW;
      END $$""")
    for table in ("agent_skill_review_batches", "agent_skill_qualifications"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER skill_atom AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kernel_skill_review_atom()"
        )
    op.execute("""CREATE FUNCTION kernel_pilot_active(tenant uuid) RETURNS boolean LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$ DECLARE admitted boolean; BEGIN
        IF tenant IS DISTINCT FROM NULLIF(current_setting('pdos.tenant_id',true),'')::uuid THEN RETURN false; END IF;
        SELECT active INTO admitted FROM tenant_pilot_admissions WHERE tenant_id=tenant FOR SHARE;
        RETURN COALESCE(admitted,false); END $$""")
    op.execute(
        "REVOKE ALL ON FUNCTION kernel_pilot_active(uuid) FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch"
    )
    op.execute("GRANT EXECUTE ON FUNCTION kernel_pilot_active(uuid) TO pdos_next_app")
    keys = ",".join(f"'{field}',to_jsonb(NEW)->'{field}'" for field in (*FIELDS, "revision"))
    changed = " OR ".join(f"NEW.{field} IS DISTINCT FROM OLD.{field}" for field in FIELDS)
    op.execute(f"""CREATE FUNCTION kernel_skill_qualification_guard() RETURNS trigger LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$
      BEGIN
        IF scope_actor() IS NULL OR pg_has_role(session_user,'pdos_next_owner','MEMBER') THEN RETURN NEW; END IF;
        IF TG_OP='UPDATE' AND NOT ({changed}) THEN RETURN NEW; END IF;
        IF TG_OP='INSERT' AND NEW.qualification_id IS NULL AND NEW.quality_review_id IS NULL
          AND NEW.reviewed_by IS NULL AND NOT NEW.pilot AND NOT NEW.quality_paused
          AND NEW.qualified_skill_digest IS NULL AND NEW.qualified_tool_digest IS NULL
          AND NEW.qualified_model_digest IS NULL AND NEW.qualified_skill_version IS NULL
          AND NEW.qualified_model_version IS NULL AND NEW.review_case_refs='[]'::jsonb
          AND NOT NEW.qualification_revoked THEN RETURN NEW; END IF;
        IF EXISTS(SELECT 1 FROM agent_skill_qualifications q WHERE q.tenant_id=NEW.tenant_id
          AND q.id=NEW.qualification_id AND q.decided_by=scope_actor() AND q.skill_key=NEW.skill_key
          AND q.receipt_id=NEW.receipt_id AND q.after_snapshot=jsonb_build_object({keys}))
          THEN RETURN NEW; END IF;
        IF TG_OP='UPDATE' AND NEW.quality_paused AND NEW.quality_review_id IS DISTINCT FROM OLD.quality_review_id
          AND NEW.revision=OLD.revision+1
          AND (to_jsonb(NEW)-ARRAY['quality_paused','quality_review_id','revision','receipt_id'])=
              (to_jsonb(OLD)-ARRAY['quality_paused','quality_review_id','revision','receipt_id'])
          AND EXISTS(SELECT 1 FROM agent_skill_review_batches b WHERE b.tenant_id=NEW.tenant_id
            AND b.id=NEW.quality_review_id AND b.receipt_id=NEW.receipt_id AND b.reviewed_by=scope_actor()
            AND b.skill_key=NEW.skill_key AND b.skill_digest=NEW.qualified_skill_digest
            AND b.tool_digest=NEW.qualified_tool_digest AND b.model_digest=NEW.qualified_model_digest
            AND EXISTS(SELECT 1 FROM jsonb_array_elements(b.cases) c WHERE c->>'severity'='critical'))
          THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'Named qualification or recorded critical review required';
      END $$""")
    op.execute(
        "CREATE CONSTRAINT TRIGGER skill_qualification_guard AFTER INSERT OR UPDATE ON tenant_skill_enablements DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kernel_skill_qualification_guard()"
    )
    for function in ("kernel_skill_review_atom()", "kernel_skill_qualification_guard()"):
        op.execute(
            f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch"
        )
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM agent_skill_review_batches UNION ALL SELECT 1 FROM agent_skill_qualifications UNION ALL SELECT 1 FROM tenant_pilot_admissions)"
        )
    ):
        raise RuntimeError(
            "Preserve review, decision and pilot history; destructive downgrade refused"
        )
    ordinary_owner()
    op.execute("DROP FUNCTION kernel_pilot_active(uuid)")
    op.execute("DROP TRIGGER skill_qualification_guard ON tenant_skill_enablements")
    op.execute("DROP FUNCTION kernel_skill_qualification_guard()")
    for constraint in ("skill_qualification_fk", "skill_quality_review_fk"):
        op.execute(f"ALTER TABLE tenant_skill_enablements DROP CONSTRAINT {constraint}")
    for column in (
        "qualified_skill_digest",
        "qualified_tool_digest",
        "qualified_model_digest",
        "qualification_id",
        "quality_paused",
        "quality_review_id",
    ):
        op.execute(f"ALTER TABLE tenant_skill_enablements DROP COLUMN {column}")
    op.execute(
        "ALTER TABLE tenant_skill_enablements ALTER COLUMN qualified_model_version TYPE varchar(160)"
    )
    for table in (
        "agent_skill_qualifications",
        "agent_skill_review_batches",
        "tenant_pilot_admissions",
    ):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION kernel_skill_review_atom()")
    op.execute("SET LOCAL ROLE NONE")
