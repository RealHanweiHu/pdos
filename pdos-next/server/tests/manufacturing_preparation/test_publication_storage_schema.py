"""Offline PostgreSQL storage-contract checks, never a migrated/RLS acceptance.

These checks exercise actual metadata/DDL and migration dispatch without a
connection. PostgreSQL execution, concurrent CAS and role enforcement remain
root's isolated-database checkpoint; structural checks cannot prove those.
"""

import re

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.engine import Engine

from pdos_next import models
from pdos_next.domain.manufacturing_baseline import publication_storage_schema as storage


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Owned offline schema checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def compact(value):
    return " ".join(value.split())


def test_actual_postgresql_ddl_resolves_every_foreign_key_to_real_unique_metadata():
    sql = storage.table_sql()
    assert all(statement.strip() for statement in sql)
    assert sql == storage.table_sql()
    for table in storage.TABLES:
        create = next(q for q in sql if f"CREATE TABLE {table.name} " in compact(q))
        assert "TIMESTAMP WITH TIME ZONE" in create
        assert "JSONB" in create or table.name != storage.TABLES[0].name
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            columns = tuple(element.column for element in constraint.elements)
            remote = columns[0].table
            assert all(column.table is remote for column in columns)
            identity = tuple(column.name for column in columns)
            unique = [tuple(remote.primary_key.columns.keys())]
            unique.extend(
                tuple(value.columns.keys())
                for value in remote.constraints
                if isinstance(value, UniqueConstraint)
            )
            assert identity in unique, (table.name, identity, remote.name)


def test_fixed_scope_t2_nullable_deadline_and_unknown_release_are_physical():
    ledger, current, documents = storage.TABLES
    assert ledger.c.proof_expires_at.nullable
    assert set(current.c) >= {current.c.version_id, current.c.revision, current.c.epoch}
    checks = compact(
        " ".join(str(c.sqltext) for c in ledger.constraints if isinstance(c, CheckConstraint))
    )
    assert "write_tier='T2'" in checks and "status='published'" in checks
    assert "actor_id=requester_id AND writer_id=actor_id" in checks
    assert "proof_expires_at IS NULL OR created_at<proof_expires_at" in checks
    assert "qualification'='unknown'" in checks and "manufacturing_release'='null'::jsonb" in checks
    for field, parent in (("receipt_id", "action_receipts"), ("shared_proof_id", "confirmations")):
        fk = next(
            c
            for c in ledger.constraints
            if isinstance(c, ForeignKeyConstraint) and field in c.column_keys
        )
        assert fk.referred_table.name == parent
        assert fk.deferrable is True and fk.initially == "DEFERRED"
    document_fk = next(
        c
        for c in documents.constraints
        if isinstance(c, ForeignKeyConstraint) and "document_id" in c.column_keys
    )
    assert tuple(document_fk.column_keys) == (
        "tenant_id",
        "product_id",
        "project_id",
        "document_kind",
        "document_id",
        "document_revision",
        "process_id",
        "process_revision",
        "operation_key",
    )
    assert all(not documents.c[name].nullable for name in document_fk.column_keys)


def test_every_qualified_sql_relation_names_an_actual_current_table():
    # Catches typos in guards that PostgreSQL's CREATE FUNCTION defers until use.
    # Function names are excluded by requiring relation-introducing SQL keywords.
    tables = set(models.Base.metadata.tables)
    relation = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|ON|TABLE)\s+public\.([a-z_]+)\b", re.I)
    for sql in storage.install_sql():
        names = {
            match.group(1)
            for match in relation.finditer(sql)
            if not sql[match.end() :].lstrip().startswith("(")
        }
        assert names <= tables, names


def test_driver_dispatch_keeps_postgresql_casts_and_json_free_from_bind_parameters():
    class RecordingConnection:
        def __init__(self):
            self.calls = []

        def exec_driver_sql(self, statement, *, execution_options):
            self.calls.append((statement, execution_options))

    connection = RecordingConnection()
    storage.install(connection)
    installed = [statement for statement, _ in connection.calls]
    assert tuple(installed) == storage.install_sql()
    assert all(options == {"no_parameters": True} for _, options in connection.calls)
    for statement in (*installed, *storage.uninstall_sql()):
        assert not text(statement)._bindparams
    assert not any(re.search(r"\b(?:COMMIT|SET\s+(?:LOCAL\s+)?ROLE)\b", sql) for sql in installed)


def test_reciprocal_group_trigger_edges_are_deferred_and_proof_is_transition_only():
    triggers = storage.trigger_sql()
    edges = {}
    for sql in triggers:
        if "CREATE CONSTRAINT TRIGGER" not in sql:
            continue
        match = re.search(
            r"AFTER (.+?) ON public\.(\w+) (.+) EXECUTE FUNCTION public\.(\w+)\(\)", sql
        )
        assert match, sql
        event, table, mode, function = match.groups()
        assert mode == "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
        edges[table] = (event, function)
    assert edges == {
        "manufacturing_baseline_publications": ("INSERT", "require_manufacturing_publication_atom"),
        "manufacturing_publication_documents": (
            "INSERT",
            "require_manufacturing_publication_document",
        ),
        "confirmations": ("UPDATE", "require_manufacturing_publication_transition"),
        **{
            name: ("INSERT", "require_manufacturing_publication_member")
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        },
    }
    proof = compact(storage.PROOF)
    assert "OLD.consumed IS DISTINCT FROM false" in proof
    assert "NEW.consumed IS DISTINCT FROM true" in proof
    assert "to_jsonb(NEW)-'consumed'" in proof
    assert "NEW.operation='npi.manufacturing_baseline.publish'" in storage.TRANSITION
    assert "shared_proof_id=NEW.id" in storage.TRANSITION


def test_original_key_is_raw_utf8_hash_and_saved_group_stays_historical():
    members = compact(storage.MEMBERS)
    assert "encode(sha256(convert_to(k.key,'UTF8')),'hex')" in members
    assert "command ? 'idempotency_key'" in members
    assert "(command->'payload') ? 'approval_token'" in members
    assert "k.actor_id=v.actor_id" in members and "k.digest=v.request_digest" in members
    assert "r.confirmation_id" in members and "v.shared_proof_id" in members
    assert "c.snapshot IS DISTINCT FROM v.input_snapshot->'review'" in members
    assert "c.expires_at IS NULL OR r.created_at<c.expires_at" in members
    assert "professional_authority_current" not in members
    assert "manufacturing_publication_currents" not in members
    assert "scope_actor" not in members and "clock_timestamp" not in members


def test_new_publication_binds_real_sources_current_authority_and_atomic_members():
    atom = compact(storage.ATOM)
    for clause in (
        "v.actor_id IS DISTINCT FROM public.scope_actor()",
        "v.requester_id IS DISTINCT FROM public.scope_requester()",
        "vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM rx",
        "plan->'scope' IS DISTINCT FROM jsonb_build_object",
        "command->'payload' IS DISTINCT FROM v.input_snapshot->'semantic'",
        "public.original_security sec",
        "a.revision::text=x->>'revision'",
        "a.status='active' AND x->>'status'='active'",
        "cur.fact_id=f.id AND cur.fact_revision=f.revision",
        "cur.epoch::text=ref->>'epoch'",
        "public.capture_authority_time_current(v.authority_snapshot,v.created_at)",
        "child.body=doc->'body' AND child.body_sha256=doc->>'body_sha256'",
        "(v.visibility='private' OR child.visibility<>'private')",
    ):
        assert clause in atom
    assert "jsonb::text" not in atom  # Python's JSON digest is never reconstructed this way.
    assert "interval" not in atom.lower()  # No invented aggregate publication TTL.


def test_current_cas_and_document_link_cannot_rewrite_fixed_history():
    current = compact(storage.CURRENT_GUARD)
    assert "NEW.revision=OLD.revision+1 AND NEW.epoch=OLD.epoch+1" in current
    assert "v.previous_id=OLD.version_id AND v.previous_revision=OLD.revision" in current
    assert "ARRAY['version_id','revision','epoch']" in current
    assert "TG_OP='INSERT'" in current and "NEW.revision=1 AND NEW.epoch=1" in current
    link = storage.FUNCTION_SQL["require_manufacturing_publication_document()"]
    assert "d.publication_id=v.id AND d.xmin=v.xmin" in link
    trigger_sql = "\n".join(storage.trigger_sql())
    assert (
        "publication_immutable BEFORE UPDATE OR DELETE "
        "ON public.manufacturing_baseline_publications" in trigger_sql
    )
    assert (
        "publication_immutable BEFORE UPDATE OR DELETE "
        "ON public.manufacturing_publication_documents" in trigger_sql
    )
    assert "'delivered_at','lease_id','lease_until','attempts','last_error'" in storage.MEMBER_GUARD


def test_forced_rls_inherits_actual_parent_audiences_without_request_key_exposure():
    policies = storage.policy_sql()
    for table in storage.TABLES:
        assert f'ALTER TABLE public."{table.name}" FORCE ROW LEVEL SECURITY' in policies
    read = next(q for q in policies if "publication_read" in q and storage.TABLES[0].name in q)
    for table in ("products", "projects", "manufacturing_preparation_versions"):
        assert f"FROM public.{table}" in read
    assert "direct_source_set_visible" in read
    assert "request_keys" not in read and "SECURITY DEFINER" not in read
    grants = "\n".join(q for q in policies if q.startswith("GRANT "))
    assert "TO pdos_agent" not in grants
    assert "GRANT UPDATE(version_id,revision,epoch)" in grants
    for sql in storage.FUNCTION_SQL.values():
        assert "SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp" in sql
        assert sql.rstrip().endswith(";\n$publication$")
    revoked = "\n".join(q for q in storage.install_sql() if q.startswith("REVOKE ALL ON FUNCTION"))
    assert all(f"public.{signature}" in revoked for signature in storage.FUNCTION_SQL)


def test_uninstall_refuses_even_preview_history_before_removing_only_new_family():
    statements = storage.uninstall_sql()
    assert statements[0].startswith("LOCK TABLE ") and "ACCESS EXCLUSIVE MODE" in statements[0]
    guard = statements[1]
    for table in storage.TABLES:
        assert f"EXISTS(SELECT 1 FROM public.{table.name})" in guard
    assert "FROM public.confirmations WHERE operation='npi.manufacturing_baseline.publish'" in guard
    assert "downgrade refused" in guard
    assert not any("CASCADE" in statement for statement in statements)
    drops = [q for q in statements if q.startswith("DROP TABLE ")]
    assert drops == [f"DROP TABLE public.{table.name}" for table in reversed(storage.TABLES)]
    assert not any("ALTER FUNCTION" in q or "CREATE OR REPLACE" in q for q in storage.install_sql())
