# Local PostgreSQL bootstrap

The scripts in `init/` run only when Docker creates a fresh local PostgreSQL volume. They
create the isolated `pdos_test` database and enable pgvector in both local databases.

Schema changes do not belong here. Alembic remains the only schema migration entrypoint.
