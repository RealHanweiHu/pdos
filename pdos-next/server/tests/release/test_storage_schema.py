"""SQL dispatch and reciprocal contract inspection, never a database trial."""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from pdos_next import models
from pdos_next.domain.release import storage_schema as storage
from pdos_next.domain.release.schemas import OPERATIONS


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Release storage inspection must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def test_deterministic_sql_generation_has_no_connection_or_transaction_execution_path():
    assert storage.upgrade_sql() == storage.upgrade_sql() == storage.install_sql()
    assert storage.downgrade_sql() == storage.uninstall_sql()
    assert not hasattr(storage, "install") and not hasattr(storage, "uninstall")
    for sql in (*storage.upgrade_sql(), *storage.downgrade_sql()):
        assert not text(sql)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)


def test_every_guard_relation_and_typed_descriptor_is_a_real_model():
    relation = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|ON|TABLE)\s+public\.([a-z_]+)\b", re.I)
    tables = models.Base.metadata.tables
    for sql in storage.upgrade_sql():
        for match in relation.finditer(sql):
            if not sql[match.end() :].lstrip().startswith("("):
                assert match.group(1) in tables, match.group(1)
    cases = (
        (storage.COMMON, {"r": tables["action_receipts"]}),
        (
            storage.PACKAGE,
            {"v": tables["release_packages"], "cur": tables["release_package_currents"]},
        ),
        (
            storage.DECISION_ATOM,
            {
                "v": tables["release_decisions"],
                "p": tables["release_packages"],
                "c": tables["confirmations"],
            },
        ),
        (storage.CURRENT_ATOM, {"cur": tables["release_package_currents"]}),
    )
    for sql, bindings in cases:
        for variable, table in bindings.items():
            assert set(re.findall(rf"\b{variable}\.([a-z_]+)\b", sql)) <= set(table.c.keys())


def test_deferred_edges_close_package_current_decision_proof_and_each_common_tail():
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
        "release_packages": ("INSERT", "require_release_package"),
        "release_package_currents": ("INSERT OR UPDATE", "require_release_current"),
        "release_decisions": ("INSERT", "require_release_decision"),
        "confirmations": ("UPDATE", "require_release_transition"),
        **{
            name: ("INSERT", "require_release_member")
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        },
    }
    assert "c.expires_at IS NULL OR v.created_at<c.expires_at" in storage.MEMBERS
    assert "NEW.expires_at IS NULL" not in storage.PROOF
    assert "OLD.consumed IS DISTINCT FROM false" in storage.PROOF
    assert "NEW.consumed IS DISTINCT FROM true" in storage.PROOF
    assert "to_jsonb(NEW)-'consumed'" in storage.PROOF


def test_real_event_contract_and_t0_no_confirmation_are_preserved():
    for operation, (tier, event) in OPERATIONS.items():
        assert operation in storage.OPERATIONS
        assert event in storage.MEMBERS
        if tier == "T2":
            assert operation in storage.T2
        else:
            assert operation not in storage.T2
    package_branch = storage.MEMBERS.split("ELSIF kind='release_decision'")[0]
    assert "proof=NULL" in package_branch
    assert "FROM public.confirmations" not in package_branch
    assert "public.assert_release_common(t,target,'release_package')" in storage.PACKAGE


def test_direct_read_set_is_order_independent_but_keeps_exact_versions_and_security():
    assert "(command->'source_read_set') @> v.required_source_read_set" in storage.COMMON
    assert "v.required_source_read_set @> (command->'source_read_set')" in storage.COMMON
    assert "jsonb_array_length(command->'source_read_set')" in storage.COMMON
    assert "a.revision::text=ref->>'expected_revision' AND a.status='active'" in storage.COMMON
    assert "sec.source_state='active' AND sec.disposition='active'" in storage.COMMON


def test_private_original_key_is_bound_only_in_write_atoms_and_not_public_read_policy():
    assert "convert_to(k.key,'UTF8')" in storage.MEMBERS
    assert "k.digest=v.request_digest" in storage.MEMBERS
    assert "k.xmin=vx" in storage.COMMON
    assert "original_key_sha256" in storage.COMMON
    assert "request_keys" not in " ".join(storage.policy_sql())
    assert "confirmations" not in " ".join(storage.policy_sql())
    assert "professional_authority" not in " ".join(storage.policy_sql())
    assert "prepared_at',null" in storage.DECISION_ATOM


def test_rls_is_forced_agent_has_no_direct_business_write_and_only_current_advances():
    sql = "\n".join(storage.policy_sql())
    for table in storage.TABLES:
        assert f'ALTER TABLE public."{table.name}" FORCE ROW LEVEL SECURITY' in sql
        assert f'CREATE POLICY owner_internal ON public."{table.name}" TO pdos_next_owner' in sql
        assert f'REVOKE ALL ON public."{table.name}" FROM PUBLIC,pdos_next_app,pdos_agent,' in sql
    assert "TO pdos_agent" not in sql
    assert 'GRANT UPDATE(version_id,revision,epoch) ON public."release_package_currents"' in sql
    assert "FOR DELETE" not in sql
    assert "public.scope_actor()=public.scope_requester()" in sql


def test_mutations_and_empty_history_downgrade_cannot_silently_replace_a_signature():
    sql = "\n".join(storage.trigger_sql())
    for table in ("release_packages", "release_decisions"):
        assert f"BEFORE UPDATE OR DELETE ON public.{table}" in sql
    assert "NEW.revision=OLD.revision+1 AND NEW.epoch=OLD.epoch+1" in storage.CURRENT_GUARD
    assert (
        "v.previous_id=OLD.version_id AND v.previous_revision=OLD.revision" in storage.CURRENT_GUARD
    )
    assert "NEW.version_id=NEW.series_id" in storage.CURRENT_GUARD
    assert "external_received' IS DISTINCT FROM 'false'" in storage.DECISION_ATOM
    downgrade = "\n".join(storage.downgrade_sql())
    assert downgrade.startswith("LOCK TABLE")
    assert downgrade.index("downgrade refused") < downgrade.index("DROP TABLE")
    assert "DELETE FROM" not in downgrade and "TRUNCATE" not in downgrade
