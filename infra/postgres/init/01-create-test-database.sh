#!/usr/bin/env bash
set -euo pipefail

psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
SELECT 'CREATE DATABASE pdos_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'pdos_test')
\gexec
SQL
