"""0854 changes only the NULL-safe DTO kind admission; no database IO."""

from hashlib import sha256

import pytest

from migrations import schema_s0_0854 as ddl
from migrations.versions import s0_0854_project_context_v2_sources as migration

PREDECESSOR_SHA256 = "11833a14bff95f15b5d471eb1ae82355b47c934c4570948d6ce41b14a149a9fa"


def test_reviewed_predecessor_has_one_exact_null_safe_admission_delta():
    assert migration.revision == "s0_0854" and migration.down_revision == "s0_0853"
    assert sha256(ddl.PREVIOUS_GATE.encode()).hexdigest() == PREDECESSOR_SHA256
    assert ddl.NATIVE_GATE.count(ddl.NATIVE_KIND) == 1
    assert ddl.NATIVE_GATE.replace(ddl.NATIVE_KIND, ddl.PREVIOUS_KIND, 1) == ddl.PREVIOUS_GATE
    # IS DISTINCT FROM treats a missing/JSON-null kind as rejected by both
    # branches; no SQL UNKNOWN can bypass the enclosing trigger IF.
    assert ddl.NATIVE_KIND == (
        "(r.versions#>>'{project_current_context,kind}' IS DISTINCT FROM 'project-current-facts/v1'"
        "\n   AND r.versions#>>'{project_current_context,kind}'"
        " IS DISTINCT FROM 'project-current-facts/v2')"
    )
    assert ddl.PREVIOUS_FUNCTIONS == {ddl.SIGNATURE: ddl.PREVIOUS_GATE}
    assert ddl.NATIVE_FUNCTIONS == {ddl.SIGNATURE: ddl.NATIVE_GATE}
    for definition in (ddl.PREVIOUS_GATE, ddl.NATIVE_GATE):
        assert "SET search_path TO 'pg_catalog', 'public', 'pg_temp'" in definition
        assert "SECURITY DEFINER" in definition


def test_downgrade_retains_only_v2_footprints_the_actual_old_guard_would_reject():
    assert "IF jsonb_array_length(native)>0 AND" in ddl.PREVIOUS_GATE
    assert ddl.DOWN_SQL == (ddl.LOCK_SQL, ddl.RETAINED_V2_SQL, ddl.PREVIOUS_GATE)
    assert (
        "WHERE r.versions#>>'{project_current_context,kind}'='project-current-facts/v2'"
        "\n   AND jsonb_array_length(coalesce("
        "\n    r.versions#>'{project_current_context,source_proof}','[]'::jsonb))>0"
    ) in ddl.RETAINED_V2_SQL
    assert "native_project_context_v2_history_retained" in ddl.RETAINED_V2_SQL
    # No rewrite/delete of retained Runs, table/column/RLS changes, or runtime
    # grants: their existing native source gate and history fences stay in force.
    sql = "\n".join((*ddl.UP_SQL, *ddl.DOWN_SQL))
    for forbidden in ("UPDATE public.agent_runs", "DELETE FROM", "ALTER TABLE", "ALTER POLICY",
                      "GRANT ", "ALTER OWNER", "CREATE ROLE", "DISABLE TRIGGER"):
        assert forbidden not in sql


class Connection:
    def __init__(self, definition, *, apply=True):
        self.definition, self.events, self.apply = definition, [], apply

    def scalar(self, statement, values):
        assert str(statement) == "SELECT pg_get_functiondef(to_regprocedure(:signature))"
        assert values == {"signature": "public." + ddl.SIGNATURE}
        self.events.append(("check", self.definition))
        return self.definition

    def exec_driver_sql(self, statement, execution_options):
        assert execution_options == {"no_parameters": True}
        self.events.append(("ddl", statement))
        if self.apply and statement in (ddl.PREVIOUS_GATE, ddl.NATIVE_GATE):
            self.definition = statement


def bind(monkeypatch, connection):
    monkeypatch.setattr(migration, "administrative_migrator",
                        lambda: connection.events.append(("role", "administrative")))
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)


@pytest.mark.parametrize("direction,before,after,statements", [
    (migration.upgrade, ddl.PREVIOUS_GATE, ddl.NATIVE_GATE, ddl.UP_SQL),
    (migration.downgrade, ddl.NATIVE_GATE, ddl.PREVIOUS_GATE, ddl.DOWN_SQL),
])
def test_both_directions_check_exact_function_before_and_after_locked_ddl(
    monkeypatch, direction, before, after, statements,
):
    connection = Connection(before)
    bind(monkeypatch, connection)
    direction()
    assert connection.events == [
        ("role", "administrative"), ("check", before),
        *[("ddl", sql) for sql in statements], ("check", after),
    ]


@pytest.mark.parametrize("direction,expected", [
    (migration.upgrade, ddl.PREVIOUS_GATE), (migration.downgrade, ddl.NATIVE_GATE),
])
@pytest.mark.parametrize("change", ["search_path", "requester", "source_hash"])
def test_unknown_guard_is_refused_before_any_lock_or_replacement(
    monkeypatch, direction, expected, change,
):
    fragments = {
        "search_path": ("'pg_catalog', ", ""),
        "requester": ("r.requester_id::text", "r.writer_id::text"),
        "source_hash": ("a.content_hash IS DISTINCT FROM", "a.content_hash IS NOT DISTINCT FROM"),
    }
    unknown = expected.replace(*fragments[change])
    assert unknown != expected
    connection = Connection(unknown)
    bind(monkeypatch, connection)
    with pytest.raises(RuntimeError, match="requires reviewed function"):
        direction()
    assert connection.events == [("role", "administrative"), ("check", unknown)]


@pytest.mark.parametrize("direction,before", [
    (migration.upgrade, ddl.PREVIOUS_GATE), (migration.downgrade, ddl.NATIVE_GATE),
])
def test_unsuccessful_function_replacement_is_rejected_by_postcondition(
    monkeypatch, direction, before,
):
    connection = Connection(before, apply=False)
    bind(monkeypatch, connection)
    with pytest.raises(RuntimeError, match="requires reviewed function"):
        direction()
    assert connection.events[-1] == ("check", before)
    assert any(kind == "ddl" for kind, _ in connection.events)
