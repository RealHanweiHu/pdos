"""Agreement registration requires the named T2 receipt and atom; append-only facts."""

from alembic import op

revision = "s0_0701"
down_revision = "s0_0700"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION kernel_agreement_atom() RETURNS trigger LANGUAGE plpgsql
      SECURITY DEFINER SET search_path=public,pg_temp AS $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM action_receipts r JOIN audit_entries a ON a.receipt_id=r.id
        JOIN outbox_events o ON o.receipt_id=r.id
        WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id
        AND r.operation='provider.agreement.register' AND r.actor_id=NEW.registered_by
        AND r.requester_id=NEW.registered_by AND r.run_id IS NULL
        AND r.subject_id=NEW.id AND r.subject_revision=NEW.revision
        AND r.result->>'tier'='T2' AND r.result->>'decision'='批准'
        AND a.tenant_id=r.tenant_id AND o.tenant_id=r.tenant_id
        AND o.type='provider.agreement_registered')
      THEN RAISE EXCEPTION 'Named agreement receipt atom required'; END IF;
      RETURN NEW; END $$""")
    op.execute("REVOKE ALL ON FUNCTION kernel_agreement_atom() FROM PUBLIC,pdos_agent")
    op.execute("""CREATE CONSTRAINT TRIGGER kernel_agreement_atom AFTER INSERT
      ON provider_data_agreements DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION kernel_agreement_atom()""")


def downgrade():
    op.execute("DROP TRIGGER kernel_agreement_atom ON provider_data_agreements")
    op.execute("DROP FUNCTION kernel_agreement_atom()")
