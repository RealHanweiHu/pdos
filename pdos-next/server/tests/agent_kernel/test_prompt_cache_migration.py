"""0853 refuses unknown hardened predecessors before DDL; no database IO."""

from hashlib import sha256

import pytest

from migrations import schema_s0_0853 as ddl
from migrations.versions import s0_0853_agreement_prompt_cache as migration

PREDECESSOR_SHA256 = "0b3a964b390e77ab24e9654f768e1b0145e1020dff5a79ab6732180de65632ac"


def test_predecessor_is_the_exact_reviewed_canonical_backup_and_cache_keeps_hardening():
    assert sha256(ddl.PREVIOUS_ATOM.encode()).hexdigest() == PREDECESSOR_SHA256
    for sql in (ddl.PREVIOUS_ATOM, ddl.CACHE_ATOM):
        assert "SET search_path TO 'pg_catalog', 'public', 'pg_temp'" in sql
        assert "SECURITY DEFINER" in sql
        assert "ALTER FUNCTION" not in sql and "GRANT" not in sql
    before, after = ddl.PREVIOUS_ATOM.split("AS $function$", 1)
    assert ddl.CACHE_ATOM.split("AS $function$", 1)[0] == before
    assert ddl.PREVIOUS_FUNCTIONS == {"kernel_agreement_atom()": ddl.PREVIOUS_ATOM}
    assert ddl.NATIVE_FUNCTIONS == {"kernel_agreement_atom()": ddl.CACHE_ATOM}
    assert ddl.CACHE_ATOM.endswith(after[after.index("      THEN RAISE EXCEPTION"):])


class Connection:
    def __init__(self, definition, *, apply=True):
        self.definition, self.events, self.apply = definition, [], apply

    def scalar(self, statement, values):
        assert str(statement) == "SELECT pg_get_functiondef(to_regprocedure(:signature))"
        assert values == {"signature": "public.kernel_agreement_atom()"}
        self.events.append(("check", self.definition))
        return self.definition

    def exec_driver_sql(self, statement, execution_options):
        assert execution_options == {"no_parameters": True}
        self.events.append(("ddl", statement))
        if self.apply and statement in (ddl.CACHE_ATOM, ddl.PREVIOUS_ATOM):
            self.definition = statement


def bind(monkeypatch, connection):
    monkeypatch.setattr(migration, "administrative_migrator", lambda: None)
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)


@pytest.mark.parametrize("direction,before,after,statements", [
    (migration.upgrade, ddl.PREVIOUS_ATOM, ddl.CACHE_ATOM, ddl.UP_SQL),
    (migration.downgrade, ddl.CACHE_ATOM, ddl.PREVIOUS_ATOM, ddl.DOWN_SQL),
])
def test_both_directions_validate_canonical_function_before_and_after_all_ddl(
    monkeypatch, direction, before, after, statements,
):
    connection = Connection(before)
    bind(monkeypatch, connection)
    direction()
    assert connection.events == [
        ("check", before), *[("ddl", sql) for sql in statements], ("check", after),
    ]


@pytest.mark.parametrize("direction", [migration.upgrade, migration.downgrade])
@pytest.mark.parametrize("change", ["search_path", "additional_guard"])
def test_unknown_existing_definition_is_refused_before_lock_column_or_replacement(
    monkeypatch, direction, change,
):
    unknown = (ddl.PREVIOUS_ATOM.replace("'pg_catalog', ", "")
               if change == "search_path" else ddl.PREVIOUS_ATOM.replace(
                   "AND r.run_id IS NULL", "AND r.run_id IS NULL AND r.agent_run_id IS NULL",
               ))
    connection = Connection(unknown)
    bind(monkeypatch, connection)
    with pytest.raises(RuntimeError, match="requires reviewed function"):
        direction()
    assert connection.events == [("check", unknown)]


@pytest.mark.parametrize("direction,before", [
    (migration.upgrade, ddl.PREVIOUS_ATOM), (migration.downgrade, ddl.CACHE_ATOM),
])
def test_ddl_that_does_not_produce_the_expected_definition_fails_postcondition(
    monkeypatch, direction, before,
):
    connection = Connection(before, apply=False)
    bind(monkeypatch, connection)
    with pytest.raises(RuntimeError, match="requires reviewed function"):
        direction()
    assert connection.events[-1] == ("check", before)
    assert any(kind == "ddl" for kind, _value in connection.events)
