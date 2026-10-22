"""Pure SQL declarations and atom edges, without PostgreSQL execution."""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from pdos_next.domain.release_exceptions import storage_schema as storage
from pdos_next.models import Base


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Exception SQL inspection must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def test_sql_generation_is_deterministic_and_has_no_connection_execution_path():
    assert storage.upgrade_sql() == storage.upgrade_sql() == storage.install_sql()
    assert storage.downgrade_sql() == storage.uninstall_sql()
    assert not hasattr(storage, "install") and not hasattr(storage, "uninstall")
    for sql in (*storage.upgrade_sql(), *storage.downgrade_sql()):
        assert not text(sql)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)


def test_guard_relations_and_typed_record_fields_match_existing_metadata():
    relation = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|ON|TABLE)\s+public\.([a-z_]+)\b", re.I)
    tables = Base.metadata.tables
    for sql in storage.upgrade_sql():
        for match in relation.finditer(sql):
            if not sql[match.end() :].lstrip().startswith("("):
                assert match.group(1) in tables, match.group(1)
    for body, aliases in (
        (
            storage.MEMBERS,
            {"v": "release_exception_decisions", "r": "action_receipts", "c": "confirmations"},
        ),
        (storage.WRITE_ATOM, {"v": "release_exception_decisions"}),
        (
            storage.AUTHORITY,
            {
                "v": "release_exception_decisions",
                "f": "professional_authority_facts",
                "cur": "professional_authority_current",
            },
        ),
        (
            storage.DECISION_ATOM,
            {
                "v": "release_exception_decisions",
                "p": "release_packages",
                "f": "release_policy_facts",
                "prior": "release_exception_decisions",
                "cur": "release_exception_currents",
            },
        ),
        (
            storage.CURRENT_ATOM,
            {"v": "release_exception_decisions", "cur": "release_exception_currents"},
        ),
    ):
        for variable, table in aliases.items():
            assert set(re.findall(rf"\b{variable}\.([a-z_]+)\b", body)) <= set(
                tables[table].c.keys()
            )


def test_both_t2_original_common_groups_keep_named_signer_and_optional_deadline():
    assert "release.exception.decide" in storage.OPERATIONS
    assert "release.exception.withdraw" in storage.OPERATIONS
    assert "release.exception_decided" in storage.MEMBERS
    assert "release.exception_withdrawn" in storage.MEMBERS
    assert "'release_exception'::varchar" in storage.MEMBERS
    assert "c.expires_at IS NULL OR v.created_at<c.expires_at" in storage.MEMBERS
    assert "r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL" in storage.MEMBERS
    assert "vx IS DISTINCT FROM rx OR vx IS DISTINCT FROM cx" in storage.WRITE_ATOM
    assert "OLD.consumed IS DISTINCT FROM false" in storage.PROOF
    assert "NEW.consumed IS DISTINCT FROM true" in storage.PROOF
    assert "(to_jsonb(NEW)-'consumed')" in storage.PROOF


def test_shared_tail_deferred_edges_close_receipts_audits_events_keys_and_proof():
    edges = {}
    for sql in storage.trigger_sql():
        if "CREATE CONSTRAINT TRIGGER" in sql:
            match = re.search(
                r"AFTER (.+?) ON public\.(\w+) (.+) EXECUTE FUNCTION public\.(\w+)\(\)", sql
            )
            assert match
            event, table, mode, function = match.groups()
            assert mode == "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
            edges[table] = (event, function)
    assert edges == {
        "release_exception_decisions": ("INSERT", "require_release_exception_decision"),
        "release_exception_currents": ("INSERT OR UPDATE", "require_release_exception_current"),
        "confirmations": ("UPDATE", "require_release_exception_transition"),
        **{
            name: ("INSERT", "require_release_exception_member")
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys")
        },
    }
    assert "e.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id)" in storage.MEMBERS
    assert "'delivered_at','lease_id','lease_until','attempts','last_error'" in storage.MEMBER_GUARD
    assert "r.subject_type IS DISTINCT FROM 'release_exception'" in storage.MEMBER_TARGET


def test_direct_source_read_set_and_flat_security_basis_bind_real_metadata():
    sql = storage.WRITE_ATOM
    assert "(command->'source_read_set') @> v.required_source_read_set" in sql
    assert "v.required_source_read_set @> (command->'source_read_set')" in sql
    assert "basis=v.source_basis->'artifact_sources'->(ref->>'artifact_id')" in sql
    for field in (
        "sha256",
        "owner_id",
        "visibility",
        "original_revision",
        "original_sha256",
        "original_owner_id",
        "original_visibility",
        "security_epoch",
    ):
        assert f"basis->>'{field}'" in sql
    assert "sec.source_state='active' AND sec.disposition='active'" in sql
    assert "k.xmin=vx" in sql and "original_key_sha256" in sql


def test_new_approval_alone_requires_current_package_policy_and_waivable_checks():
    common, approval = storage.DECISION_ATOM.split("IF v.action='approved' THEN", 1)
    approval, withdrawal = approval.split("\n ELSE\n", 1)
    for name in ("release_package_currents", "release_policy_currents"):
        assert name in approval and name not in common and name not in withdrawal
        assert name not in storage.MEMBERS and name not in " ".join(storage.policy_sql())
    assert "f.status<>'active'" in approval
    assert "check_value->'non_waivable' IS DISTINCT FROM 'false'::jsonb" in approval
    assert "policy_rule->'waivable' IS DISTINCT FROM 'true'::jsonb" in approval
    assert "v.expiry IS DISTINCT FROM prior.expiry" in withdrawal
    assert "v.created_at>=v.expiry" not in withdrawal
    assert "prior.actor_id" not in withdrawal


def test_current_cas_and_retained_history_cannot_replace_the_original_signature():
    assert (
        "OLD.action='approved' AND OLD.epoch=1 AND NEW.action='withdrawn'" in storage.CURRENT_GUARD
    )
    assert (
        "v.previous_id=OLD.decision_id AND v.previous_revision=OLD.decision_revision"
        in storage.CURRENT_GUARD
    )
    assert "NEW.epoch=OLD.epoch+1" in storage.CURRENT_GUARD
    triggers = " ".join(storage.trigger_sql())
    assert "BEFORE UPDATE OR DELETE ON public.release_exception_decisions" in triggers
    assert "BEFORE INSERT OR UPDATE OR DELETE ON public.release_exception_currents" in triggers
    down = "\n".join(storage.downgrade_sql())
    assert down.startswith("LOCK TABLE")
    assert down.index("downgrade refused") < down.index("DROP TABLE")
    assert "DELETE FROM" not in down and "TRUNCATE" not in down


def test_forced_rls_inherits_package_audience_without_private_key_or_authority_reads():
    sql = "\n".join(storage.policy_sql())
    for table in storage.TABLES:
        assert f'ALTER TABLE public."{table.name}" FORCE ROW LEVEL SECURITY' in sql
        assert f'CREATE POLICY owner_internal ON public."{table.name}" TO pdos_next_owner' in sql
        assert f'REVOKE ALL ON public."{table.name}" FROM PUBLIC,pdos_next_app,pdos_agent,' in sql
    assert (
        "public.release_packages" in sql
        and "p.owner_id=release_exception_decisions.owner_id" in sql
    )
    assert "object_audiences" not in sql
    assert "TO pdos_agent" not in sql and "FOR DELETE" not in sql
    assert "h.kind='human' AND h.active" in sql
    assert "GRANT UPDATE(decision_id,decision_revision,action,epoch)" in sql
    for private in ("request_keys", "confirmations", "professional_authority"):
        assert private not in sql


def test_actual_authority_facts_match_scope_duty_qualification_and_current_watermark():
    for field in (
        "fact_sha256",
        "issuer_key",
        "issuer_version",
        "nature",
        "operations",
        "purposes",
        "valid_from",
        "valid_until",
    ):
        assert f"f.{field}" in storage.AUTHORITY
    assert "cur.epoch::text=ref->>'epoch'" in storage.AUTHORITY
    assert "ARRAY['duty','qualification']" in storage.AUTHORITY
    assert "role_name IN ('engineering','manufacturing','quality')" in storage.AUTHORITY
    assert "f->>'role'=role_name" in storage.AUTHORITY
    assert "v.discipline" not in storage.AUTHORITY
    assert "capture_authority_time_current(auth,v.created_at)" in storage.AUTHORITY
    assert "policy_version='" not in " ".join(storage.upgrade_sql())
