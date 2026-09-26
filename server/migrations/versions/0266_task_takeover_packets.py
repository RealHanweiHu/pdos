"""Persistent task handoff packets and named reception."""

from alembic import op

revision = "0266_task_takeover_packets"
down_revision = "0265_knowledge_reuse_recovery"
branch_labels = None
depends_on = None

DDL = """

CREATE TABLE cehub_project.task_takeover_packets (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	submission_id UUID, 
	actor_user_id UUID NOT NULL, 
	receiver_user_id UUID NOT NULL, 
	request_id UUID NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	basis JSON NOT NULL, 
	payload JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_task_takeover_packets PRIMARY KEY (id), 
	CONSTRAINT ck_task_takeover_packets_revision_positive CHECK (revision>0), 
        CONSTRAINT ck_task_takeover_packets_action_allowed CHECK (action IN
('submitted','accepted','returned')),
        CONSTRAINT ck_task_takeover_packets_action_consistent CHECK ((action='submitted' AND
submission_id IS NULL AND actor_user_id<>receiver_user_id) OR (action IN ('accepted','returned')
AND submission_id IS NOT NULL AND actor_user_id=receiver_user_id)),
	CONSTRAINT uq_task_takeover_scope UNIQUE (tenant_id, project_id, id), 
	CONSTRAINT uq_task_takeover_revision UNIQUE (tenant_id, task_id, revision), 
	CONSTRAINT uq_task_takeover_request UNIQUE (tenant_id, actor_user_id, request_id), 
        CONSTRAINT fk_task_takeover_task FOREIGN KEY(tenant_id, project_id, task_id) REFERENCES
cehub_project.tasks (tenant_id, project_id, id),
        CONSTRAINT fk_task_takeover_actor FOREIGN KEY(tenant_id, actor_user_id) REFERENCES
cehub_core.users (tenant_id, id),
        CONSTRAINT fk_task_takeover_receiver FOREIGN KEY(tenant_id, receiver_user_id) REFERENCES
cehub_core.users (tenant_id, id),
        CONSTRAINT fk_task_takeover_submission FOREIGN KEY(tenant_id, project_id, submission_id)
REFERENCES cehub_project.task_takeover_packets (tenant_id, project_id, id)
)

;

CREATE FUNCTION cehub_project.guard_task_takeover_packet() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous cehub_project.task_takeover_packets; assigned uuid; task_state text;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'Task takeover packets and receipts are immutable' USING ERRCODE='23514';
 END IF;
 SELECT assignee_user_id,status INTO assigned,task_state FROM cehub_project.tasks
  WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND id=NEW.task_id FOR UPDATE;
 IF assigned IS DISTINCT FROM NEW.receiver_user_id OR task_state IN ('done','skipped') THEN
  RAISE EXCEPTION 'Handoff requires the current active task recipient' USING ERRCODE='23514';
 END IF;
 SELECT * INTO previous FROM cehub_project.task_takeover_packets
  WHERE tenant_id=NEW.tenant_id AND task_id=NEW.task_id ORDER BY revision DESC LIMIT 1;
 IF NEW.revision<>COALESCE(previous.revision,0)+1 THEN
  RAISE EXCEPTION 'Handoff version must continue its task history' USING ERRCODE='23514';
 END IF;
 IF NEW.action<>'submitted' AND (previous.id IS DISTINCT FROM NEW.submission_id
    OR previous.action<>'submitted' OR previous.receiver_user_id<>NEW.actor_user_id
    OR previous.basis::jsonb IS DISTINCT FROM NEW.basis::jsonb) THEN
  RAISE EXCEPTION 'Receipt must reference the latest original handoff' USING ERRCODE='23514';
 END IF;
 IF NEW.action='accepted' AND NOT (NEW.payload::jsonb->'checked_sections' @>
  '["goal","constraints","confirmed_facts","open_items","next_steps"]'::jsonb) THEN
  RAISE EXCEPTION 'Every handoff section requires named verification' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.guard_task_takeover_packet() FROM PUBLIC;
CREATE TRIGGER guard_task_takeover_packet BEFORE INSERT OR UPDATE OR DELETE
 ON cehub_project.task_takeover_packets FOR EACH ROW
 EXECUTE FUNCTION cehub_project.guard_task_takeover_packet();

CREATE FUNCTION cehub_project.require_task_takeover_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE packet cehub_project.task_takeover_packets;
BEGIN
 IF NEW.status<>'done' OR OLD.status='done' THEN RETURN NEW; END IF;
 SELECT * INTO packet FROM cehub_project.task_takeover_packets
  WHERE tenant_id=NEW.tenant_id AND task_id=NEW.id ORDER BY revision DESC LIMIT 1;
 IF NOT FOUND THEN RETURN NEW; END IF;
 IF packet.action<>'accepted' OR packet.receiver_user_id IS DISTINCT FROM NEW.assignee_user_id
  OR ROW(NEW.title,NEW.description,NEW.due_date,NEW.expected_output) IS DISTINCT FROM
   ROW(packet.basis->'task'->>'title',packet.basis->'task'->>'description',
    (packet.basis->'task'->>'due_date')::date,packet.basis->'task'->>'expected_output') THEN
  RAISE EXCEPTION 'Current task handoff must be received before completion' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION cehub_project.require_task_takeover_receipt() FROM PUBLIC;
CREATE TRIGGER require_task_takeover_receipt BEFORE UPDATE OF status ON cehub_project.tasks
 FOR EACH ROW EXECUTE FUNCTION cehub_project.require_task_takeover_receipt();

"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    import sqlalchemy as sa

    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.task_takeover_packets)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to erase handoff packets and receipts")
    op.execute("DROP TRIGGER require_task_takeover_receipt ON cehub_project.tasks")
    op.execute("DROP FUNCTION cehub_project.require_task_takeover_receipt()")
    op.drop_table("task_takeover_packets", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_task_takeover_packet()")
