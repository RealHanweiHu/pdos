"""Named MCP admission and versioned grants retain atomic immutable control history."""
# ruff: noqa: E501 -- SQL clauses are kept reviewable.

from alembic import op
from sqlalchemy import text

from migrations.schema_s0_0717 import CONFIRMATION_DEADLINE
from migrations.versions.s0_0762_category_source_consumers import ordinary_owner

revision = "s0_0770"
down_revision = "s0_0769"
branch_labels = None
depends_on = None

CONNECTOR_FIELDS = ("key", "endpoint", "secret_ref", "tools", "active", "admitted_by", "revision")
GRANT_FIELDS = (
    "connector_id",
    "tool",
    "skill_key",
    "automation_rule_id",
    "active",
    "explicit_external_write",
    "connector_binding_digest",
    "authorized_by",
    "revision",
)


def deadline(add):
    expression = CONFIRMATION_DEADLINE.replace(
        "operation IN (", "operation IN ('ai.skill.qualify',"
    )
    if add:
        expression = expression.replace("operation IN (", "operation IN ('mcp.connector.allow',")
    op.execute("ALTER TABLE confirmations DROP CONSTRAINT ck_confirmations_decision_deadline")
    op.execute(
        f"ALTER TABLE confirmations ADD CONSTRAINT ck_confirmations_decision_deadline CHECK ({expression})"
    )


def upgrade():
    ordinary_owner()
    op.execute("""CREATE TABLE mcp_control_records(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,
      created_at timestamptz NOT NULL,operation varchar(80) NOT NULL,subject_id uuid NOT NULL,
      subject_revision integer NOT NULL,decided_by uuid NOT NULL,after_snapshot jsonb NOT NULL,
      reason varchar(4000) NOT NULL,receipt_id uuid NOT NULL,UNIQUE(tenant_id,id),
      FOREIGN KEY(tenant_id,decided_by) REFERENCES principals(tenant_id,id),
      CONSTRAINT mcp_control_receipt_fk FOREIGN KEY(tenant_id,receipt_id) REFERENCES action_receipts(tenant_id,id)
        DEFERRABLE INITIALLY DEFERRED)""")
    op.execute("CREATE INDEX ix_mcp_control_records_tenant_id ON mcp_control_records(tenant_id)")
    op.execute(
        "CREATE INDEX ix_mcp_control_subject ON mcp_control_records(tenant_id,subject_id,created_at,id)"
    )
    for table, stem in [("mcp_connectors", "mcp_connector"), ("mcp_tool_grants", "mcp_grant")]:
        for column in ("receipt_id", "control_record_id"):
            op.execute(f"ALTER TABLE {table} ADD COLUMN {column} uuid")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {stem}_receipt_fk FOREIGN KEY(tenant_id,receipt_id) REFERENCES action_receipts(tenant_id,id) DEFERRABLE INITIALLY DEFERRED"
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {stem}_control_fk FOREIGN KEY(tenant_id,control_record_id) REFERENCES mcp_control_records(tenant_id,id) DEFERRABLE INITIALLY DEFERRED"
        )
    op.execute("ALTER TABLE mcp_tool_grants ADD COLUMN active boolean NOT NULL DEFAULT true")
    op.execute("ALTER TABLE mcp_tool_grants ADD COLUMN revision integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE mcp_tool_grants ADD COLUMN connector_binding_digest varchar(64)")
    op.execute("ALTER TABLE mcp_tool_grants ADD UNIQUE(tenant_id,id)")
    op.execute("CREATE INDEX ix_mcp_grants_connector ON mcp_tool_grants(tenant_id,connector_id,id)")
    op.execute(
        "CREATE INDEX ix_mcp_grants_current ON mcp_tool_grants(tenant_id,connector_id,tool,expires_at) WHERE active IS TRUE"
    )
    op.execute("ALTER TABLE mcp_control_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mcp_control_records FORCE ROW LEVEL SECURITY")
    predicate = """tenant_id=NULLIF(current_setting('pdos.tenant_id',true),'')::uuid
      AND scope_actor()=scope_requester() AND EXISTS(SELECT 1 FROM tenant_administrators a
        JOIN principals p ON p.tenant_id=a.tenant_id AND p.id=a.principal_id
        WHERE a.tenant_id=mcp_control_records.tenant_id AND a.principal_id=scope_actor()
        AND a.active AND p.active AND p.kind='human')"""
    op.execute(
        f"CREATE POLICY mcp_control_read ON mcp_control_records FOR SELECT USING ({predicate})"
    )
    op.execute(
        f"CREATE POLICY mcp_control_append ON mcp_control_records FOR INSERT WITH CHECK ({predicate} AND decided_by=scope_actor() AND kernel_admin_authorized())"
    )
    op.execute(
        "REVOKE ALL ON mcp_control_records FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch"
    )
    op.execute("GRANT SELECT,INSERT ON mcp_control_records TO pdos_next_app")
    op.execute(
        "CREATE TRIGGER mcp_control_append_only BEFORE UPDATE OR DELETE ON mcp_control_records FOR EACH ROW EXECUTE FUNCTION kernel_append_only()"
    )
    op.execute("""CREATE FUNCTION kernel_mcp_control_atom() RETURNS trigger LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$
      DECLARE event_name text;
      BEGIN
        event_name=CASE NEW.operation WHEN 'mcp.connector.allow' THEN 'mcp.connector_allowed'
          WHEN 'mcp.tool.grant' THEN 'mcp.tool_granted' ELSE NULL END;
        IF event_name IS NULL OR NOT EXISTS(SELECT 1 FROM action_receipts r
          JOIN audit_entries a ON a.tenant_id=r.tenant_id AND a.receipt_id=r.id
          JOIN outbox_events o ON o.tenant_id=r.tenant_id AND o.receipt_id=r.id
          JOIN confirmations c ON c.tenant_id=r.tenant_id AND c.id=r.confirmation_id
          WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND r.operation=NEW.operation
          AND r.subject_id=NEW.subject_id AND r.subject_revision=NEW.subject_revision
          AND r.actor_id=NEW.decided_by AND r.requester_id=NEW.decided_by
          AND r.agent_run_id IS NULL AND r.run_id IS NULL AND c.consumed
          AND c.actor_id=NEW.decided_by AND c.operation=NEW.operation AND o.type=event_name)
          THEN RAISE EXCEPTION 'Human MCP control receipt atom required'; END IF;
        RETURN NEW;
      END $$""")
    op.execute(
        "CREATE CONSTRAINT TRIGGER mcp_control_atom AFTER INSERT ON mcp_control_records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kernel_mcp_control_atom()"
    )
    connector = ",".join(f"'{key}',to_jsonb(NEW)->'{key}'" for key in CONNECTOR_FIELDS)
    grant = ",".join(f"'{key}',to_jsonb(NEW)->'{key}'" for key in GRANT_FIELDS)
    op.execute(f"""CREATE FUNCTION kernel_mcp_management_guard() RETURNS trigger LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$
      DECLARE expected_operation text; actual_snapshot jsonb;
      BEGIN
        IF scope_actor() IS NULL OR pg_has_role(session_user,'pdos_next_owner','MEMBER') THEN RETURN NEW; END IF;
        IF TG_OP='UPDATE' AND NEW.revision<>OLD.revision+1 THEN RAISE EXCEPTION 'MCP revision must advance once'; END IF;
        IF TG_OP='INSERT' AND NEW.revision<>1 THEN RAISE EXCEPTION 'MCP initial revision required'; END IF;
        IF TG_TABLE_NAME='mcp_connectors' THEN
          expected_operation='mcp.connector.allow'; actual_snapshot=jsonb_build_object({connector});
          IF TG_OP='UPDATE' AND NEW.key IS DISTINCT FROM OLD.key THEN RAISE EXCEPTION 'MCP identity immutable'; END IF;
        ELSE
          expected_operation='mcp.tool.grant'; actual_snapshot=jsonb_build_object({grant});
          IF TG_OP='UPDATE' AND (NEW.connector_id IS DISTINCT FROM OLD.connector_id OR NEW.tool IS DISTINCT FROM OLD.tool
            OR NEW.skill_key IS DISTINCT FROM OLD.skill_key OR NEW.automation_rule_id IS DISTINCT FROM OLD.automation_rule_id)
            THEN RAISE EXCEPTION 'MCP grant target immutable'; END IF;
        END IF;
        IF NOT EXISTS(SELECT 1 FROM mcp_control_records c WHERE c.tenant_id=NEW.tenant_id
          AND c.id=NEW.control_record_id AND c.subject_id=NEW.id AND c.subject_revision=NEW.revision
          AND c.decided_by=scope_actor() AND c.receipt_id=NEW.receipt_id AND c.operation=expected_operation
          AND (CASE WHEN TG_TABLE_NAME='mcp_connectors' THEN c.after_snapshot
                    ELSE c.after_snapshot-'expires_at' END)=actual_snapshot
          AND (TG_TABLE_NAME='mcp_connectors' OR (c.after_snapshot->>'expires_at')::timestamptz=(to_jsonb(NEW)->>'expires_at')::timestamptz))
          THEN RAISE EXCEPTION 'Current human MCP control required'; END IF;
        RETURN NEW;
      END $$""")
    for table in ("mcp_connectors", "mcp_tool_grants"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER mcp_management_guard AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kernel_mcp_management_guard()"
        )
    for name in ("kernel_mcp_control_atom()", "kernel_mcp_management_guard()"):
        op.execute(
            f"REVOKE ALL ON FUNCTION {name} FROM PUBLIC,pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch"
        )
    deadline(True)
    op.execute("SET LOCAL ROLE NONE")


def downgrade():
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM mcp_control_records UNION ALL SELECT 1 FROM confirmations WHERE operation='mcp.connector.allow' AND expires_at IS NULL)"
        )
    ):
        raise RuntimeError(
            "Preserve MCP admission, grants and named proof history; downgrade refused"
        )
    ordinary_owner()
    deadline(False)
    for table, stem in [("mcp_connectors", "mcp_connector"), ("mcp_tool_grants", "mcp_grant")]:
        op.execute(f"DROP TRIGGER mcp_management_guard ON {table}")
        for name in (f"{stem}_receipt_fk", f"{stem}_control_fk"):
            op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        for column in ("receipt_id", "control_record_id"):
            op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    op.execute("DROP FUNCTION kernel_mcp_management_guard()")
    op.execute("DROP TABLE mcp_control_records")
    op.execute("DROP FUNCTION kernel_mcp_control_atom()")
    op.execute("DROP INDEX ix_mcp_grants_current")
    op.execute("DROP INDEX ix_mcp_grants_connector")
    op.execute("ALTER TABLE mcp_tool_grants DROP CONSTRAINT mcp_tool_grants_tenant_id_id_key")
    for column in ("active", "revision", "connector_binding_digest"):
        op.execute(f"ALTER TABLE mcp_tool_grants DROP COLUMN {column}")
    op.execute("SET LOCAL ROLE NONE")
