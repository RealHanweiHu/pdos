"""Automatic inactivity archive and repeatable, immutable restore history."""

from alembic import op

revision = "0258_finding_auto_archive"
down_revision = "0257_conversation_object_focus"
branch_labels = None
depends_on = None

BASE = (
    "(action='created' AND actor_user_id IS NULL AND from_status IS NULL "
    "AND to_status='pending_review') OR "
    "(action IN ('accepted','rejected') AND actor_user_id IS NOT NULL "
    "AND from_status='pending_review' AND to_status=action) OR "
    "(action='applied' AND actor_user_id IS NOT NULL "
    "AND from_status='accepted' AND to_status='applied') OR "
    "(action='restored' AND actor_user_id IS NOT NULL "
    "AND from_status='archived' AND to_status='pending_review') OR "
)


def swap(expression: str) -> None:
    op.execute(
        "ALTER TABLE cehub_ai.finding_actions "
        "DROP CONSTRAINT ck_finding_actions_transition_consistent"
    )
    op.create_check_constraint(
        op.f("ck_finding_actions_transition_consistent"),
        "finding_actions",
        expression,
        schema="cehub_ai",
    )


def upgrade() -> None:
    swap(
        BASE + "(action='archived' AND (actor_user_id IS NOT NULL OR "
        "(detail->>'automatic'='true' AND detail->>'policy'='finding-inactivity-v1') IS TRUE) "
        "AND from_status='pending_review' AND to_status='archived')"
    )
    op.execute("""ALTER TABLE cehub_ai.finding_actions
    DROP CONSTRAINT uq_finding_actions_tenant_finding_action;
    CREATE UNIQUE INDEX uq_finding_actions_terminal ON cehub_ai.finding_actions
    (tenant_id,finding_id,action) WHERE action NOT IN ('archived','restored');
    CREATE INDEX ix_findings_pending_activity ON cehub_ai.findings
    (tenant_id,project_id,updated_at,id) WHERE status='pending_review';""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_ai.finding_actions WHERE action='archived'
      AND actor_user_id IS NULL) OR EXISTS
      (SELECT 1 FROM cehub_ai.finding_actions GROUP BY tenant_id,finding_id,action
       HAVING count(*)>1) THEN
      RAISE EXCEPTION 'Automatic and repeat archive history must be retained';
    END IF;
    END $$;
    DROP INDEX cehub_ai.ix_findings_pending_activity;
    DROP INDEX cehub_ai.uq_finding_actions_terminal;
    ALTER TABLE cehub_ai.finding_actions ADD CONSTRAINT uq_finding_actions_tenant_finding_action
    UNIQUE(tenant_id,finding_id,action);""")
    swap(
        BASE + "(action='archived' AND actor_user_id IS NOT NULL "
        "AND from_status='pending_review' AND to_status='archived')"
    )
