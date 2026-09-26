"""Bind named reviewers and assignment receipts to immutable Gate rounds."""

import sqlalchemy as sa
from alembic import op

revision = "0285_gate_named_signers"
down_revision = "0284_template_generation_v7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION cehub_project.guard_gate_named_assignment() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    DECLARE a jsonb; s record; p cehub_core.users;
    BEGIN
      a := NEW.routing_snapshot->'assignment';
      IF a IS NULL THEN RETURN NEW; END IF;
      IF jsonb_typeof(a) IS DISTINCT FROM 'object'
        OR jsonb_typeof(a->'signers') IS DISTINCT FROM 'object'
        OR coalesce(a->>'request_id','') !~ '^[a-f0-9-]{36}$'
        OR coalesce(a->>'request_digest','') !~ '^[a-f0-9]{64}$'
        OR btrim(coalesce(a->>'reason',''))='' THEN
        RAISE EXCEPTION 'Named Gate assignment requires a fixed request and reason';
      END IF;
      FOR s IN SELECT key,value FROM jsonb_each(a->'signers') LOOP
        IF s.key NOT IN ('product','engineering','quality')
          OR coalesce(NEW.requirements->>s.key,'not_applicable')='not_applicable' THEN
          RAISE EXCEPTION 'Named Gate slot must be applicable';
        END IF;
        SELECT u.* INTO p FROM cehub_core.users u
        JOIN cehub_project.project_members m ON m.tenant_id=u.tenant_id AND m.user_id=u.id
        WHERE u.tenant_id=NEW.tenant_id AND m.project_id=NEW.project_id
          AND u.id=(s.value->>'user_id')::uuid AND u.is_active FOR SHARE OF u,m;
        IF NOT FOUND OR p.role IS DISTINCT FROM s.value->>'role'
          OR p.display_name IS DISTINCT FROM s.value->>'display_name'
          OR NOT (p.role IN ('owner','admin') OR
            (s.key='product' AND p.role='project_manager') OR
            (s.key='engineering' AND p.role='engineer') OR
            (s.key='quality' AND p.role='quality')) THEN
          RAISE EXCEPTION 'Named Gate reviewer must be a qualified active project member';
        END IF;
      END LOOP;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_gate_named_assignment() FROM PUBLIC;
    CREATE TRIGGER guard_gate_named_assignment BEFORE INSERT
      ON cehub_project.gate_signoff_rounds FOR EACH ROW
      EXECUTE FUNCTION cehub_project.guard_gate_named_assignment();

    CREATE FUNCTION cehub_project.guard_gate_named_signoff() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    DECLARE r cehub_project.gate_signoff_rounds; expected jsonb; actual_role text;
    BEGIN
      SELECT * INTO r FROM cehub_project.gate_signoff_rounds
        WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id
          AND gate_id=NEW.gate_id AND id=NEW.round_id;
      IF NOT (r.routing_snapshot ? 'assignment') THEN RETURN NEW; END IF;
      IF r.status<>'open' THEN
        RAISE EXCEPTION 'Historical named Gate signatures are immutable';
      END IF;
      expected := r.routing_snapshot->'assignment'->'signers'->NEW.slot;
      IF expected IS NULL OR NEW.signed_by_user_id IS NULL THEN RETURN NEW; END IF;
      IF NEW.signed_by_user_id::text IS DISTINCT FROM expected->>'user_id' THEN
        RAISE EXCEPTION 'Only the named Gate reviewer may sign';
      END IF;
      SELECT u.role INTO actual_role FROM cehub_core.users u
        JOIN cehub_project.project_members m ON m.tenant_id=u.tenant_id AND m.user_id=u.id
        WHERE u.tenant_id=NEW.tenant_id AND m.project_id=NEW.project_id
          AND u.id=NEW.signed_by_user_id AND u.is_active FOR SHARE OF u,m;
      IF NOT FOUND OR actual_role IS DISTINCT FROM NEW.signer_role
        OR NOT (actual_role IN ('owner','admin') OR
          (NEW.slot='product' AND actual_role='project_manager') OR
          (NEW.slot='engineering' AND actual_role='engineer') OR
          (NEW.slot='quality' AND actual_role='quality')) THEN
        RAISE EXCEPTION 'Named Gate reviewer is no longer qualified';
      END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_gate_named_signoff() FROM PUBLIC;
    CREATE TRIGGER guard_gate_named_signoff BEFORE INSERT OR UPDATE
      ON cehub_project.gate_signoffs FOR EACH ROW
      EXECUTE FUNCTION cehub_project.guard_gate_named_signoff();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.gate_signoff_rounds
          WHERE routing_snapshot ? 'assignment')
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to remove named Gate signing rules while history exists")
    op.execute("""
        DROP TRIGGER guard_gate_named_signoff ON cehub_project.gate_signoffs;
        DROP FUNCTION cehub_project.guard_gate_named_signoff();
        DROP TRIGGER guard_gate_named_assignment ON cehub_project.gate_signoff_rounds;
        DROP FUNCTION cehub_project.guard_gate_named_assignment();
    """)
