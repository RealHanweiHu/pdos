"""Actual source guards on the existing consuming tables; no permission waiver."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from migrations.schema_s0_0827 import TABLES
from pdos_next.lifecycle_access import schema_covered
from pdos_next.lifecycle_catalog import GUARDED


def test_restored_guards_are_enabled_and_keep_original_before_after_timing(engines):
    admin, _app, _auth = engines
    assert set(TABLES) <= set(GUARDED)
    with Session(admin) as session:
        assert schema_covered(session)
        rows = session.execute(
            text(
                "SELECT c.relname,t.tgname,p.proname,pg_get_triggerdef(t.oid),"
                "pg_get_userbyid(c.relowner),c.relrowsecurity,c.relforcerowsecurity "
                "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_proc p ON p.oid=t.tgfoid "
                "WHERE c.relnamespace='public'::regnamespace AND c.relname=ANY(:tables) "
                "AND t.tgname IN ('lifecycle_reference','category_lifecycle_clock') "
                "AND t.tgenabled IN ('O','A')"
            ),
            {"tables": list(TABLES)},
        ).all()
        assert len(rows) == len(TABLES) * 2
        for _table, name, function, definition, owner, rls, forced in rows:
            assert owner == "pdos_next_owner" and rls and forced
            assert "INSERT OR DELETE OR UPDATE" in definition
            if name == "lifecycle_reference":
                assert function == "lifecycle_reference_gate" and " BEFORE " in definition
            else:
                assert function == "category_lifecycle_clock" and " AFTER " in definition


def test_disabled_restored_guard_denies_coverage_and_rollback_restores_it(engines):
    admin, _app, _auth = engines
    # Only this verified isolated fixture, inside a rolled-back DDL transaction.
    with Session(admin) as session:
        try:
            session.execute(
                text(
                    "ALTER TABLE public.external_wait_versions DISABLE TRIGGER lifecycle_reference"
                )
            )
            assert not schema_covered(session)
        finally:
            session.rollback()
        assert schema_covered(session)
