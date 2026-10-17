"""Offline installer/real metadata contracts; no PostgreSQL or RLS attestation.

Pure checks resolve actual FK targets and dispatch the exact PostgreSQL SQL to a
recording connection. The root checkpoint owns execution, roles and concurrent
CAS; inspecting a deferred trigger is not evidence that PostgreSQL enforced it.
"""

import re

import pytest
from sqlalchemy import UniqueConstraint, text
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import AddConstraint, DropConstraint

from pdos_next import models
from pdos_next.domain.manufacturing_trials import native_storage_schema as storage
from pdos_next.domain.manufacturing_trials.native_models import BINDING


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Native storage checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def compact(value):
    return " ".join(value.split())


def test_real_postgresql_ddl_resolves_all_foreign_keys_and_installs_the_current_cycle_last():
    statements = storage.table_sql()
    assert statements == storage.table_sql()
    create_positions = {}
    for table in storage.TABLES:
        create_positions[table.name] = next(
            index
            for index, sql in enumerate(statements)
            if f"CREATE TABLE {table.name} " in compact(sql)
        )
        assert "TIMESTAMP WITH TIME ZONE" in statements[create_positions[table.name]]
        for foreign in table.foreign_key_constraints:
            remote = foreign.referred_table
            target = tuple(element.column.name for element in foreign.elements)
            unique = {tuple(remote.primary_key.columns.keys())}
            unique.update(
                tuple(value.columns.keys())
                for value in remote.constraints
                if isinstance(value, UniqueConstraint)
            )
            assert target in unique, (table.name, remote.name, target)
            assert all(element.column.table is remote for element in foreign.elements)
            if foreign.use_alter:
                added = str(AddConstraint(foreign).compile(dialect=dialect()))
                assert statements.index(added) > max(create_positions.values())
                assert "DEFERRABLE INITIALLY DEFERRED" in added
                assert foreign.name == "fk_native_pilot_current_observation"
    root, current, observation = storage.TABLES
    latest = next(value for value in current.foreign_key_constraints if value.use_alter)
    assert tuple(latest.column_keys) == (*BINDING, "pilot_id", "latest_observation_id", "revision")
    assert tuple(element.column.name for element in latest.elements) == (
        *BINDING,
        "pilot_id",
        "id",
        "revision",
    )
    previous = next(
        value
        for value in observation.foreign_key_constraints
        if "previous_observation_id" in value.column_keys
    )
    assert tuple(previous.column_keys) == (
        *BINDING,
        "pilot_id",
        "previous_observation_id",
        "pilot_revision_before",
    )
    assert previous.deferrable and previous.initially == "DEFERRED"
    for field in ("shared_proof_id", "receipt_id"):
        for table in (root, observation):
            fk = next(
                value for value in table.foreign_key_constraints if field in value.column_keys
            )
            assert fk.deferrable and fk.initially == "DEFERRED"


def test_driver_dispatch_preserves_postgresql_literals_and_never_creates_a_transaction_or_role():
    class Connection:
        def __init__(self):
            self.calls = []

        def exec_driver_sql(self, statement, *, execution_options):
            self.calls.append((statement, execution_options))

    connection = Connection()
    storage.install(connection)
    assert tuple(sql for sql, _ in connection.calls) == storage.install_sql()
    assert all(options == {"no_parameters": True} for _, options in connection.calls)
    for sql in (*storage.install_sql(), *storage.uninstall_sql()):
        assert not text(sql)._bindparams, sql
        assert not re.search(r"\b(?:COMMIT|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)
    connection.calls.clear()
    storage.uninstall(connection)
    assert tuple(sql for sql, _ in connection.calls) == storage.uninstall_sql()


def test_all_new_guard_relations_and_typed_row_fields_exist_in_actual_metadata():
    tables = models.Base.metadata.tables
    relation = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|ON|TABLE)\s+public\.([a-z_]+)\b", re.I)
    for sql in storage.install_sql():
        for match in relation.finditer(sql):
            if not sql[match.end() :].lstrip().startswith("("):
                assert match.group(1) in tables, match.group(1)
    root, _, observation = storage.TABLES
    cases = (
        (storage.ROOT_ATOM, {"v": root}),
        (storage.OBSERVATION_ATOM, {"v": observation, "root": root, "previous": observation}),
        (
            storage.PHYSICAL,
            {
                "r": root,
                "b": tables["builds"],
                "l": tables["build_lots"],
                "a": tables["actual_configurations"],
                "e": tables["engineering_configurations"],
                "p": tables["process_revisions"],
                "pub": tables["manufacturing_baseline_publications"],
            },
        ),
    )
    for sql, bindings in cases:
        for variable, table in bindings.items():
            used = set(re.findall(rf"\b{variable}\.([a-z_]+)\b", sql))
            assert used <= set(table.c.keys()), (variable, table.name, used - set(table.c.keys()))
    # The RECORD has one of two real descriptors; each explicit kind branch
    # assembles that row's body before entering the common field checks.
    shared = set(root.c.keys()) | set(observation.c.keys())
    used = set(re.findall(r"\bv\.([a-z_]+)\b", storage.COMMON_ATOM))
    assert used <= shared | {"tx"}


def test_deferred_reciprocal_edges_cover_real_subjects_current_proof_and_all_common_members():
    edges = {}
    for sql in storage.trigger_sql():
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
        "native_pilot_runs": ("INSERT", "require_native_pilot_root"),
        "native_pilot_observations": ("INSERT", "require_native_pilot_observation"),
        "native_pilot_currents": ("INSERT OR UPDATE", "require_native_pilot_current"),
        "confirmations": ("UPDATE", "require_native_pilot_transition"),
        **{
            table: ("INSERT", "require_native_pilot_member")
            for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        },
    }
    assert "OLD.consumed IS DISTINCT FROM false" in storage.PROOF
    assert "NEW.consumed IS DISTINCT FROM true" in storage.PROOF
    assert "to_jsonb(NEW)-'consumed'" in storage.PROOF
    assert "NEW.expires_at IS NULL" in storage.PROOF
    assert (
        "native_pilot_runs" in storage.TRANSITION
        and "native_pilot_observations" in storage.TRANSITION
    )


def test_common_t1_group_uses_product_proof_revision_and_keeps_the_original_key_private():
    members = compact(storage.MEMBERS)
    assert "v.product_id,v.operation,v.shared_proof_revision" in members
    assert "c.expires_at IS NULL" in members and "r.created_at<c.expires_at" in members
    assert "r.confirmation_id" in members and "v.shared_proof_id" in members
    assert "c.snapshot IS DISTINCT FROM v.input_snapshot->'review'" in members
    assert "encode(sha256(convert_to(k.key,'UTF8')),'hex')" in members
    assert "k.actor_id=v.actor_id AND k.digest=v.request_digest" in members
    assert "command ? 'idempotency_key'" in members
    assert "(command->'payload') ? 'confirmation_token'" in members
    for sql in (members, storage.MEMBER_TARGET):
        assert "scope_actor" not in sql and "capture_authority_time_current" not in sql
        assert "native_pilot_currents" not in sql
    atom = compact(storage.COMMON_ATOM)
    assert "p.revision=v.shared_proof_revision" in atom
    assert "command->>'expected_revision' IS DISTINCT FROM v.shared_proof_revision::text" in atom
    assert "command->'payload' IS DISTINCT FROM semantic" in atom
    assert "review->'after' IS DISTINCT FROM body" in atom
    assert "vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM rx" in atom
    assert "k.xmin=vx" in atom
    assert "jsonb::text" not in atom


def test_immutable_root_and_observation_cas_do_not_rewrite_initial_material():
    triggers = "\n".join(storage.trigger_sql())
    for table in (storage.TABLES[0], storage.TABLES[2]):
        assert f"native_pilot_immutable BEFORE UPDATE OR DELETE ON public.{table.name}" in triggers
    pointer = compact(storage.CURRENT_GUARD)
    assert "ARRAY['revision','epoch','latest_observation_id']" in pointer
    assert "NEW.revision=OLD.revision+1 AND NEW.epoch=OLD.epoch+1" in pointer
    assert "v.pilot_revision_before=OLD.revision" in pointer
    assert "v.previous_observation_id IS NOT DISTINCT FROM OLD.latest_observation_id" in pointer
    assert "v.owner_id=NEW.owner_id AND v.visibility=NEW.visibility" in pointer
    observation = compact(storage.OBSERVATION_ATOM)
    assert "v.pilot_revision_before=1" in observation and "v.revision<>2" in observation
    assert "previous.visibility,previous.revision" in observation
    assert "v.visibility,v.pilot_revision_before" in observation
    assert "old_input IS DISTINCT FROM new_input" in observation
    assert (
        "(v.fixed_scope-'pilot_revision') IS DISTINCT FROM (previous.fixed_scope-'pilot_revision')"
        in observation
    )
    assert "current_row.revision-1" in storage.CURRENT_ATOM
    assert "current_row.revision<>current_row.epoch" in storage.CURRENT_ATOM


def test_raw_original_binding_allows_unknown_statistics_and_never_self_grants_start_or_release():
    assert "IF v.statistics_basis IS NULL THEN" in storage.ROOT_ATOM
    assert "IF v.fixed_scope IS NULL THEN" in storage.OBSERVATION_ATOM
    assert "IF v.projection IS NOT NULL THEN" in storage.OBSERVATION_ATOM
    assert "coalesce(root.statistics_basis,'null'::jsonb)" in storage.OBSERVATION_ATOM
    assert "pdos-pilot-statistics-declaration-v1" in storage.ROOT_ATOM
    assert "pdos-pilot-result-values-v1" in storage.OBSERVATION_ATOM
    assert "(v.record->'observed')-'source'" in storage.OBSERVATION_ATOM
    assert "x.value-'source'-'disposition'" in storage.OBSERVATION_ATOM
    assert "encode(sha256(convert_to(line,'UTF8')),'hex')" in storage.SOURCE_LINE
    assert "native_pilot_source_line(t,category,product,src)::jsonb" in storage.ORIGINAL
    assert "v.source_basis->'artifact_sources'" in storage.COMMON_ATOM
    assert "sec.epoch::text=x->>'security_epoch'" in storage.COMMON_ATOM
    assert "a.revision::text=x->>'revision'" in storage.COMMON_ATOM
    assert "a.status='active' AND x->>'status'='active'" in storage.COMMON_ATOM
    assert (
        "'start_authorized',false,'manufacturing_release',null,'external_delivery',false"
        in compact(storage.COMMON_ATOM)
    )
    assert "process_capability' IS DISTINCT FROM 'NOT_ASSESSED'" in storage.OBSERVATION_ATOM
    assert "factory_qualification' IS DISTINCT FROM 'NOT_ASSESSED'" in storage.OBSERVATION_ATOM
    assert "b.type=" not in storage.PHYSICAL  # Actual owner does not impose a Build-type gate.


def test_rls_inherits_actual_parent_readers_and_exposes_no_private_request_or_definer_rpc():
    policies = "\n".join(storage.policy_sql())
    for table in storage.TABLES:
        assert f'ALTER TABLE public."{table.name}" FORCE ROW LEVEL SECURITY' in policies
        assert f'GRANT SELECT,INSERT ON public."{table.name}" TO pdos_next_app' in policies
    assert "a.object_type='native_pilot_runs'" in policies
    assert "public.scope_actor()=public.scope_requester()" in policies
    assert "public.direct_source_set_visible" in policies
    assert (
        'GRANT UPDATE(revision,epoch,latest_observation_id) ON public."native_pilot_currents"'
        in policies
    )
    assert "request_keys" not in policies
    for signature, sql in storage.FUNCTION_SQL.items():
        assert "SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp" in sql
        assert (
            f"REVOKE ALL ON FUNCTION public.{signature} "
            "FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            in storage.install_sql()
        )
    assert not any("GRANT EXECUTE" in sql for sql in storage.install_sql())


def test_downgrade_refuses_retained_history_and_drops_the_cycle_before_tables():
    statements = storage.uninstall_sql()
    assert statements[0].startswith("LOCK TABLE public.native_pilot_runs,")
    refusal = statements[1]
    for table in storage.TABLES:
        assert f"EXISTS(SELECT 1 FROM public.{table.name})" in refusal
    assert "public.confirmations" in refusal and "public.action_receipts" in refusal
    assert "downgrade refused" in refusal
    first_drop = next(index for index, sql in enumerate(statements) if sql.startswith("DROP TABLE"))
    for table in storage.TABLES:
        for fk in table.foreign_key_constraints:
            if fk.use_alter:
                assert (
                    statements.index(str(DropConstraint(fk).compile(dialect=dialect())))
                    < first_drop
                )
    assert not any("CASCADE" in sql for sql in statements)
