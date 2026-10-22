"""Inspect exact SQL and typed relations without opening a PostgreSQL connection."""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from pdos_next import models
from pdos_next.domain.release import policy_storage_schema as storage
from pdos_next.domain.release.policy_models import EVENT, OPERATION, SUBJECT


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Policy SQL inspection must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def test_generators_are_deterministic_and_cannot_connect_install_or_change_role():
    assert storage.upgrade_sql() == storage.upgrade_sql()
    assert storage.downgrade_sql() == storage.downgrade_sql()
    assert not hasattr(storage, "install") and not hasattr(storage, "uninstall")
    for sql in (*storage.upgrade_sql(), *storage.downgrade_sql()):
        assert not text(sql)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)


def test_every_guard_relation_and_typed_row_field_has_an_actual_metadata_owner():
    tables = models.Base.metadata.tables
    relations = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|ON|TABLE)\s+public\.([a-z_]+)\b", re.I)
    for sql in storage.upgrade_sql():
        for match in relations.finditer(sql):
            if not sql[match.end() :].lstrip().startswith("("):
                assert match.group(1) in tables, match.group(1)
    for sql, bindings in (
        (storage.MEMBERS, {"v": tables["release_policy_facts"], "r": tables["action_receipts"]}),
        (
            storage.ATOM,
            {
                "v": tables["release_policy_facts"],
                "cur": tables["release_policy_currents"],
                "a": tables["artifact_versions"],
            },
        ),
        (storage.CURRENT_ATOM, {"cur": tables["release_policy_currents"]}),
    ):
        for variable, table in bindings.items():
            assert set(re.findall(rf"\b{variable}\.([a-z_]+)\b", sql)) <= set(table.c.keys())


def test_deferred_edges_close_fact_current_and_every_common_tail_without_confirmation():
    edges = {}
    for sql in storage.trigger_sql():
        if "CREATE CONSTRAINT TRIGGER" not in sql:
            continue
        match = re.search(
            r"AFTER (.+?) ON public\.(\w+) (.+) EXECUTE FUNCTION public\.(\w+)\(\)", sql
        )
        assert match
        event, table, mode, function = match.groups()
        assert mode == "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
        edges[table] = (event, function)
    assert edges == {
        "release_policy_facts": ("INSERT", "require_release_policy_atom"),
        "release_policy_currents": ("INSERT OR UPDATE", "require_release_policy_current"),
        **{
            table: ("INSERT", "require_release_policy_member")
            for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        },
    }
    assert "public.confirmations" not in "\n".join(storage.upgrade_sql())
    assert "r.confirmation_id IS NOT NULL" in storage.MEMBERS
    assert "coalesce(r.agent_run_id,r.run_id,v.command_id)" in storage.MEMBERS
    assert "x.xmin IS DISTINCT FROM vx" in storage.ATOM and "k.xmin=vx" in storage.ATOM


def test_raw_key_stays_private_and_host_rls_is_exactly_scoped_to_native_policy_group():
    policies = storage.policy_sql()
    common = [
        sql
        for sql in policies
        if "CREATE POLICY" in sql
        and any(
            f"ON public.{table} " in sql
            for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        )
    ]
    assert len(common) == 4
    for sql in common:
        assert OPERATION in sql and SUBJECT in sql
        assert "FOR INSERT TO pdos_next_app" in sql
        assert "public.category_access(tenant_id,category_id,true)" in sql
    assert EVENT in next(sql for sql in common if "public.outbox_events" in sql)
    assert not any("request_keys" in sql and "FOR SELECT" in sql for sql in policies)
    assert "convert_to(k.key,'UTF8')" in storage.MEMBERS
    assert "original_key_sha256" in storage.MEMBERS


def test_new_write_binds_actual_source_line_security_and_real_professional_current():
    sql = storage.ATOM
    assert "line::jsonb IS DISTINCT FROM v.material" in sql
    assert "encode(sha256(convert_to(line,'UTF8')),'hex')" in sql
    assert "basis=v.source_basis->(ref->>'artifact_id')" in sql
    assert "sec.source_state='active' AND sec.disposition='active'" in sql
    assert "f.fact_sha256=ref->>'fact_sha256'" in sql
    assert "p.fact_id=f.id AND p.fact_revision=f.revision" in sql
    assert "ARRAY['duty','qualification']" in sql
    assert "auth->'synthetic' IS DISTINCT FROM to_jsonb(v.nature='synthetic')" in sql
    assert "v.created_at<v.valid_from" not in sql
    assert "v.created_at>=v.valid_until" not in sql
    assert not re.search(r"->\s*'[^']+'\s*@>", sql)


def test_forced_rls_retains_ordinary_owner_and_no_agent_direct_write():
    sql = "\n".join(storage.policy_sql())
    for table in storage.TABLES:
        assert f'ALTER TABLE public."{table.name}" FORCE ROW LEVEL SECURITY' in sql
        assert f'CREATE POLICY owner_internal ON public."{table.name}" TO pdos_next_owner' in sql
        assert f'REVOKE ALL ON public."{table.name}" FROM PUBLIC,pdos_next_app,pdos_agent,' in sql
    assert "TO pdos_agent" not in sql
    assert 'GRANT UPDATE(fact_id,revision,epoch) ON public."release_policy_currents"' in sql
    assert "FOR DELETE" not in sql


def test_monotonic_current_append_only_history_and_downgrade_history_refusal():
    triggers = "\n".join(storage.trigger_sql())
    assert "BEFORE UPDATE OR DELETE ON public.release_policy_facts" in triggers
    assert "NEW.revision=OLD.revision+1 AND NEW.epoch=OLD.epoch+1" in storage.CURRENT_GUARD
    assert "f.previous_id=OLD.fact_id AND f.previous_revision=OLD.revision" in storage.CURRENT_GUARD
    assert "NEW.fact_id=NEW.series_id" in storage.CURRENT_GUARD
    sql = "\n".join(storage.downgrade_sql())
    assert sql.startswith("LOCK TABLE")
    assert sql.index("downgrade refused") < sql.index("DROP TABLE")
    assert "DELETE FROM" not in sql and "TRUNCATE" not in sql
