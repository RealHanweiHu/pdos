"""Personal reminder preferences and immutable delivery-day quota reservations."""

from alembic import op

revision = "0259_reminder_preferences"
down_revision = "0258_finding_auto_archive"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_event.reminder_preferences (
	tenant_id UUID NOT NULL,
	user_id UUID NOT NULL,
	version INTEGER NOT NULL,
	daily_cap INTEGER,
	quiet_hours VARCHAR(11),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_reminder_preferences PRIMARY KEY (tenant_id, user_id, version),
        CONSTRAINT fk_reminder_preferences_tenant_id_users FOREIGN KEY(tenant_id, user_id)
REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT ck_reminder_preferences_values CHECK (version > 0 AND (daily_cap IS NULL OR
daily_cap BETWEEN 0 AND 1000)),
        CONSTRAINT ck_reminder_preferences_quiet CHECK (quiet_hours IS NULL OR quiet_hours ~
'^([01][0-9]|2[0-3]):[0-5][0-9]-([01][0-9]|2[0-3]):[0-5][0-9]$')
)

;


CREATE TABLE cehub_event.reminder_delivery_reservations (
	tenant_id UUID NOT NULL,
	outbox_id UUID NOT NULL,
	local_day DATE NOT NULL,
	user_id UUID NOT NULL,
	policy JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_reminder_delivery_reservations PRIMARY KEY (tenant_id, outbox_id, local_day),
        CONSTRAINT fk_reminder_delivery_reservations_tenant_id_users FOREIGN KEY(tenant_id,
user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT,
        CONSTRAINT fk_reminder_delivery_reservations_tenant_id_integration_outbox FOREIGN
KEY(tenant_id, outbox_id) REFERENCES cehub_event.integration_outbox (tenant_id, id) ON DELETE
RESTRICT,
	CONSTRAINT ck_reminder_delivery_reservations_policy CHECK (jsonb_typeof(policy)='object')
)

;
CREATE INDEX ix_reminder_delivery_daily ON cehub_event.reminder_delivery_reservations (tenant_id,
user_id, local_day);
"""
GUARD = """

CREATE FUNCTION cehub_event.guard_personal_reminder_history() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Reminder policy and quota history are immutable'; END IF;
 IF TG_TABLE_NAME='reminder_delivery_reservations' THEN
  IF NOT EXISTS (SELECT 1 FROM cehub_event.integration_outbox o
   WHERE o.tenant_id=NEW.tenant_id AND o.id=NEW.outbox_id
   AND o.provider='dingtalk' AND o.operation='reminder_dm'
   AND o.payload->>'recipient_user_id'=NEW.user_id::text)
   OR NEW.local_day<>(NEW.created_at AT TIME ZONE 'Asia/Shanghai')::date THEN
    RAISE EXCEPTION 'Quota must belong to the actual recipient and local delivery day';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_event.guard_personal_reminder_history() FROM PUBLIC;
CREATE TRIGGER guard_reminder_preferences BEFORE UPDATE OR DELETE ON
cehub_event.reminder_preferences
FOR EACH ROW EXECUTE FUNCTION cehub_event.guard_personal_reminder_history();
CREATE TRIGGER guard_reminder_delivery_reservations BEFORE INSERT OR UPDATE OR DELETE ON
cehub_event.reminder_delivery_reservations
FOR EACH ROW EXECUTE FUNCTION cehub_event.guard_personal_reminder_history();

"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_event.reminder_preferences)
      OR EXISTS (SELECT 1 FROM cehub_event.reminder_delivery_reservations) THEN
      RAISE EXCEPTION 'Reminder preference and delivery quota history must be retained';
    END IF;
    END $$;
    DROP TABLE cehub_event.reminder_delivery_reservations;
    DROP TABLE cehub_event.reminder_preferences;
    DROP FUNCTION cehub_event.guard_personal_reminder_history();
    """)
