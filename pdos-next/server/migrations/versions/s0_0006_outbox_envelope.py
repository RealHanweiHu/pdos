"""Immutable event envelope; delivery bookkeeping does not re-prove business atoms."""

from alembic import op

revision = "s0_0006"
down_revision = "s0_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
      CREATE FUNCTION protect_outbox_envelope() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF ROW(NEW.id,NEW.tenant_id,NEW.category_id,NEW.receipt_id,NEW.type,NEW.subject_id,
          NEW.subject_revision,NEW.schema_version,NEW.actor_id,NEW.correlation_id,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.category_id,OLD.receipt_id,OLD.type,
          OLD.subject_id,OLD.subject_revision,OLD.schema_version,OLD.actor_id,OLD.correlation_id,OLD.created_at)
        THEN RAISE EXCEPTION 'event envelope is immutable'; END IF;
        RETURN NEW;
      END $$
    """)
    op.execute("REVOKE EXECUTE ON FUNCTION protect_outbox_envelope() FROM PUBLIC,pdos_agent")
    op.execute(
        "CREATE TRIGGER envelope_immutable BEFORE UPDATE ON outbox_events "
        "FOR EACH ROW EXECUTE FUNCTION protect_outbox_envelope()"
    )
    for trigger, function in (("coverage_atom", "require_change_coverage_atom"),):
        op.execute(f"DROP TRIGGER {trigger} ON outbox_events")
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {trigger} AFTER INSERT ON outbox_events "
            f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {function}()"
        )


def downgrade():
    for trigger, function in (("coverage_atom", "require_change_coverage_atom"),):
        op.execute(f"DROP TRIGGER {trigger} ON outbox_events")
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {trigger} AFTER INSERT OR UPDATE ON outbox_events "
            f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    op.execute("DROP TRIGGER envelope_immutable ON outbox_events")
    op.execute("DROP FUNCTION protect_outbox_envelope()")
