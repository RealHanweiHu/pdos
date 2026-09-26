"""Enforce project-creation named-slot requirements on every new Gate round."""

import sqlalchemy as sa
from alembic import op

revision = "0286_gate_required_named_policy"
down_revision = "0285_gate_named_signers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION cehub_project.guard_gate_required_named_policy() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog AS $$
    DECLARE v cehub_project.project_template_versions; stage_code text;
      required jsonb; slot text; policy jsonb;
    BEGIN
      SELECT * INTO v FROM cehub_project.project_template_versions
        WHERE tenant_id=NEW.tenant_id AND project_id=NEW.project_id AND revision=1
          AND status IN ('active','superseded');
      IF NOT FOUND OR v.difference->>'adoption_scope' IS DISTINCT FROM 'project_creation'
        THEN RETURN NEW; END IF;
      SELECT s.code INTO stage_code FROM cehub_project.gates g
        JOIN cehub_project.stages s ON s.tenant_id=g.tenant_id AND s.id=g.stage_id
        WHERE g.tenant_id=NEW.tenant_id AND g.project_id=NEW.project_id AND g.id=NEW.gate_id;
      required := v.snapshot->'named_gate_slots'->stage_code;
      IF required IS NULL OR required='[]'::jsonb THEN RETURN NEW; END IF;
      policy := jsonb_build_object('required_slots',required,'source',jsonb_build_object(
        'project_template_version_id',v.id::text,'template_id',v.template_id,
        'template_version',v.template_version,'template_digest',v.digest));
      IF NEW.routing_snapshot->'assignment'->'required_policy' IS DISTINCT FROM policy THEN
        RAISE EXCEPTION 'Gate round must pin its creation-template named-signer policy';
      END IF;
      FOR slot IN SELECT jsonb_array_elements_text(required) LOOP
        IF coalesce(NEW.routing_snapshot->'assignment'->'signers'->slot->>'user_id','')='' THEN
          RAISE EXCEPTION 'Creation-template required Gate slot must have a named reviewer';
        END IF;
      END LOOP;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION cehub_project.guard_gate_required_named_policy() FROM PUBLIC;
    CREATE TRIGGER guard_gate_required_named_policy BEFORE INSERT
      ON cehub_project.gate_signoff_rounds FOR EACH ROW
      EXECUTE FUNCTION cehub_project.guard_gate_required_named_policy();
    """)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("""
        SELECT EXISTS(SELECT 1 FROM cehub_project.project_template_versions
          WHERE coalesce(snapshot->'named_gate_slots','{}'::jsonb)<>'{}'::jsonb)
    """)
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to remove named-slot policy enforcement for adopted projects")
    op.execute("""
        DROP TRIGGER guard_gate_required_named_policy ON cehub_project.gate_signoff_rounds;
        DROP FUNCTION cehub_project.guard_gate_required_named_policy();
    """)
