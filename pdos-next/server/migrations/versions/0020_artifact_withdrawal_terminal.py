"""A withdrawn source version cannot regain authority through status ABA."""

from alembic import op

revision = "next_0020"
down_revision = "next_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
      CREATE FUNCTION protect_retained_artifact_state() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF OLD.status='withdrawn' AND NEW.status IS DISTINCT FROM OLD.status THEN
          RAISE EXCEPTION 'Withdrawn source version is terminal; a new source needs a new identity';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER retained_source_state BEFORE UPDATE OF status ON artifact_versions
        FOR EACH ROW EXECUTE FUNCTION protect_retained_artifact_state();
    """)


def downgrade():
    op.execute("DROP TRIGGER retained_source_state ON artifact_versions")
    op.execute("DROP FUNCTION protect_retained_artifact_state()")
