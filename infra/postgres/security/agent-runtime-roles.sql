-- PDOS S2-2b login-role bootstrap.
-- Run once per database cluster as the RDS administrator. This script is
-- idempotent and intentionally creates no passwords.

BEGIN;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pdos_worker') THEN
        CREATE ROLE pdos_worker LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pdos_agent') THEN
        CREATE ROLE pdos_agent LOGIN;
    END IF;
END
$roles$;

ALTER ROLE pdos_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
ALTER ROLE pdos_agent LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

DO $connect$
BEGIN
    EXECUTE 'GRANT CONNECT ON DATABASE ' || quote_ident(current_database()) ||
        ' TO pdos_worker, pdos_agent';
END
$connect$;

COMMIT;
