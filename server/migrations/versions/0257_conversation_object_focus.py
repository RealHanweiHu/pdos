"""Fix work-card scope and evidence on immutable private messages."""

from alembic import op

revision = "0257_conversation_object_focus"
down_revision = "0256_decision_reference_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""ALTER TABLE cehub_ai.conversation_messages ADD COLUMN object_focus jsonb;
    ALTER TABLE cehub_ai.conversation_messages ADD CONSTRAINT
    ck_conversation_messages_object_focus CHECK
    (object_focus IS NULL OR (action IN ('note','project_query')
    AND jsonb_typeof(object_focus)='object'
    AND object_focus ?& ARRAY['kind','id','digest','fields']
    AND object_focus->>'kind' IN ('task','issue','risk','capa','gate')
    AND jsonb_typeof(object_focus->'fields')='array'
    AND object_focus->>'digest' ~ '^[a-f0-9]{64}$') IS TRUE);""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cehub_ai.conversation_messages WHERE object_focus IS NOT NULL) THEN
      RAISE EXCEPTION 'Work-card conversation source history must be retained';
    END IF;
    END $$;
    ALTER TABLE cehub_ai.conversation_messages DROP COLUMN object_focus;""")
