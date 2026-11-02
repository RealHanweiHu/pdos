import os

from alembic import context
from pdos_next.core.models import Base
from sqlalchemy import create_engine

engine = create_engine(os.environ["MIGRATION_DATABASE_URL"])
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        # Verified environment identity belongs to the local harness, not business schema.
        include_object=lambda obj, name, kind, reflected, compare: (
            not (kind == "table" and name == "environment_guard")
        ),
    )
    with context.begin_transaction():
        context.run_migrations()
