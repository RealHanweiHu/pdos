"""Offline SQL shape and deferred common-group closure, not installed evidence."""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from pdos_next.domain.work_management import storage_schema as storage
from pdos_next.models import Base


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Work SQL declaration checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def test_declarations_are_deterministic_and_have_no_install_executor():
    assert storage.upgrade_sql() == storage.upgrade_sql()
    assert storage.downgrade_sql() == storage.downgrade_sql()
    assert not hasattr(storage, "install") and not hasattr(storage, "uninstall")
    for sql in (*storage.upgrade_sql(), *storage.downgrade_sql()):
        assert not text(sql)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)


def test_all_guard_relations_and_typed_fields_exist_in_real_metadata():
    relations = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|ON|TABLE)\s+public\.([a-z_]+)\b", re.I)
    for sql in storage.upgrade_sql():
        for match in relations.finditer(sql):
            if not sql[match.end() :].lstrip().startswith("("):
                assert match.group(1) in Base.metadata.tables
    for sql, aliases in (
        (
            storage.TASK_ATOM,
            {"v": "work_task_versions", "prior": "work_task_versions", "cur": "work_task_currents"},
        ),
        (
            storage.COMMITMENT_ATOM,
            {
                "v": "work_commitment_versions",
                "task": "work_task_versions",
                "cur": "work_commitment_currents",
            },
        ),
        (storage.STATUS_ATOM, {"v": "project_status_updates"}),
    ):
        for alias, table in aliases.items():
            assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", sql)) <= set(
                Base.metadata.tables[table].c.keys()
            )


def test_common_group_keeps_result_extensions_actual_original_key_and_same_transaction():
    assert "expected_result" in storage.MEMBERS
    assert "'task_id',v.task_id,'state',v.state,'project_id',v.project_id" in storage.MEMBERS
    assert "'task_id',v.task_id,'recipient_id',v.recipient_id" in storage.MEMBERS
    assert "r.result IS DISTINCT FROM expected_result" in storage.MEMBERS
    assert "coalesce(r.agent_run_id,r.run_id,v.command_id)" in storage.MEMBERS
    assert "convert_to(k.key,'UTF8')" in storage.MEMBERS
    assert "k.xmin=vx" in storage.WRITE_ATOM
    assert "vx IS DISTINCT FROM rx" in storage.WRITE_ATOM
    assert "c.snapshot IS DISTINCT FROM v.command->'review'" in storage.MEMBERS


def test_t0_create_has_no_confirmation_and_t1_consumption_is_reciprocal():
    assert "work.task.create" not in storage.T1
    assert "v.operation<>'work.task.create'" in storage.MEMBERS
    assert "OLD.consumed IS DISTINCT FROM false" in storage.PROOF
    assert "NEW.consumed IS DISTINCT FROM true" in storage.PROOF
    assert "amount<>1" in storage.TRANSITION
    assert "T2" not in storage.PROOF and "qualification" not in storage.WRITE_ATOM
    triggers = " ".join(storage.trigger_sql())
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        assert f"AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED" in triggers


def test_project_audience_is_inherited_with_no_per_row_copy_or_fixed_category_context():
    sql = " ".join(storage.policy_sql())
    for table in storage.TABLES:
        assert f'ALTER TABLE public."{table.name}" FORCE ROW LEVEL SECURITY' in sql
        assert f'REVOKE ALL ON public."{table.name}" FROM PUBLIC,pdos_next_app,pdos_agent,' in sql
    assert "public.projects p" in sql and "p.owner_id=" in sql and "p.visibility=" in sql
    assert "object_audiences" not in sql and "scope_category" not in sql
    assert "TO pdos_agent" not in sql and "FOR DELETE" not in sql
    assert "request_keys" not in sql and "confirmations" not in sql
    assert "GRANT UPDATE(version_id,revision,state)" in sql
    assert "GRANT UPDATE(version_id,revision)" in sql


def test_exact_cas_append_history_and_empty_only_downgrade():
    sql = " ".join(storage.function_sql())
    assert "NEW.revision=OLD.revision+1" in sql
    assert "v.previous_id=OLD.version_id" in sql and "v.replaces_id=OLD.version_id" in sql
    assert "Work facts are immutable" in sql
    assert "Task action cannot replace fixed base or other facts" in storage.TASK_ATOM
    down = "\n".join(storage.downgrade_sql())
    assert down.startswith("LOCK TABLE")
    assert down.index("downgrade refused") < down.index("DROP TABLE")
    assert "DELETE FROM" not in down and "TRUNCATE" not in down


def test_direct_sources_bind_metadata_without_requiring_historical_basis_in_current_reads():
    sql = storage.WRITE_ATOM
    assert "jsonb_array_elements(v.sources)" in sql
    assert "v.source_basis->'artifacts'" in sql
    assert "a.content_hash=basis->>'hash'" in sql
    assert "sec.epoch::text=basis->'original'->>'epoch'" in sql
    assert "r.id::text=basis->'registration'->>'receipt_id'" in sql
    assert "jsonb_array_length(v.source_basis->'artifacts')" not in sql
    assert "a.content" not in sql.replace("a.content_hash", "")
