"""Offline service schema and proof-boundary checks; never installed evidence."""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from pdos_next.domain.automations import service_storage as storage
from pdos_next.models import Base


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Service storage declaration checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def test_three_new_tables_only_and_no_installer_or_installed_function_replacements():
    assert [table.name for table in storage.TABLES] == [
        "automation_service_grants",
        "automation_causal_chains",
        "automation_service_attempts",
    ]
    assert storage.upgrade_sql() == storage.upgrade_sql()
    assert storage.downgrade_sql() == storage.downgrade_sql()
    assert not hasattr(storage, "install") and not hasattr(storage, "uninstall")
    sql = "\n".join(storage.upgrade_sql())
    assert "CREATE OR REPLACE" not in sql
    assert "CREATE FUNCTION public.kernel_" not in sql
    assert "ALTER TABLE public.automation_rule_currents" not in sql
    for statement in storage.upgrade_sql():
        assert not text(statement)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", statement)


def test_actual_foreign_relations_and_all_typed_guard_columns_exist():
    relations = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|ON|TABLE)\s+public\.([a-z_]+)\b", re.I)
    for sql in storage.upgrade_sql():
        for match in relations.finditer(sql):
            if not sql[match.end() :].lstrip().startswith("("):
                assert match.group(1) in Base.metadata.tables
    for sql, aliases in (
        (
            storage.GRANT_ATOM,
            {
                "g": "automation_service_grants",
                "v": "automation_rule_versions",
                "r": "action_receipts",
                "c": "confirmations",
            },
        ),
        (
            storage.CHAIN_ATOM,
            {"chain": "automation_causal_chains", "g": "automation_service_grants"},
        ),
        (
            storage.ATTEMPT_ATOM,
            {
                "a": "automation_service_attempts",
                "g": "automation_service_grants",
                "v": "automation_rule_versions",
                "chain": "automation_causal_chains",
                "parent_attempt": "automation_service_attempts",
                "r": "agent_runs",
            },
        ),
    ):
        for alias, table in aliases.items():
            assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", sql)) <= set(
                Base.metadata.tables[table].c.keys()
            )


def test_scope_bound_grant_and_deduplicated_attempt_have_exact_foreign_keys():
    grant, chain, attempt = storage.TABLES
    grant_fks = {tuple(c.name for c in fk.columns) for fk in grant.foreign_key_constraints}
    assert ("tenant_id", "category_id", "owner_id", "rule_id", "published_version_id") in grant_fks
    attempt_fks = {tuple(c.name for c in fk.columns) for fk in attempt.foreign_key_constraints}
    assert (
        "tenant_id",
        "category_id",
        "owner_id",
        "rule_id",
        "published_version_id",
        "writer_id",
        "service_grant_id",
    ) in attempt_fks
    assert ("tenant_id", "chain_id") in attempt_fks  # Root chains may span owners.
    assert not any("owner_id" in key and "chain_id" in key for key in attempt_fks)
    for table, columns in (
        (grant, ("tenant_id", "published_version_id")),
        (attempt, ("tenant_id", "service_grant_id", "trigger_key")),
        (attempt, ("tenant_id", "run_id")),
    ):
        assert any(
            tuple(c.name for c in constraint.columns) == columns
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        )
    assert chain.c.max_depth.nullable is False
    assert grant.c.expires_at.nullable and grant.c.expires_at.default is None


def test_service_grant_is_real_named_activation_not_a_declaration_or_new_command():
    sql = storage.GRANT_ATOM
    for fragment in (
        "public.assert_automation_members(t,v.id)",
        "v.action<>'activate' OR v.state<>'active'",
        "'ai.automation.activate'::varchar,'automation_rule'::varchar",
        "c.consumed IS DISTINCT FROM true",
        "c.snapshot IS DISTINCT FROM v.command->'review'",
        "g.owner_id IS DISTINCT FROM public.scope_actor()",
        "g.owner_id IS DISTINCT FROM public.scope_requester()",
        "a.active AND a.kind='agent')<>1",
        "gx IS DISTINCT FROM vx OR gx IS DISTINCT FROM rx OR gx IS DISTINCT FROM cx",
    ):
        assert fragment in sql
    assert (
        "g.expires_at IS DISTINCT FROM (v.spec#>>'{trigger_config,expires_at}')::timestamptz" in sql
    )
    assert "timedelta" not in sql and "interval '" not in sql
    assert "INSERT INTO public.action_receipts" not in sql


def test_availability_requires_actual_agent_delegator_current_publish_and_explicit_expiry():
    assert "service_writer=public.scope_actor()" in storage.IDENTITY
    assert "service_owner=public.scope_requester()" in storage.IDENTITY
    assert "service_owner<>service_writer" in storage.IDENTITY
    assert "a.kind='agent'" in storage.IDENTITY
    assert "active" not in storage.IDENTITY
    assert "a.active AND a.kind='agent')=1" in storage.AVAILABLE
    assert "cur.published_version_id=g.published_version_id" in storage.AVAILABLE
    assert "cur.state='active'" in storage.AVAILABLE
    assert "g.expires_at IS NULL OR at_time<g.expires_at" in storage.AVAILABLE
    assert "public.category_access(t,g.category_id,false)" in storage.AVAILABLE
    assert "category_access(t,g.category_id,true)" not in storage.AVAILABLE


def test_chain_budget_and_depth_are_copied_from_actual_root_grant():
    assert "chain.budget IS DISTINCT FROM v.spec->'budget'" in storage.CHAIN_ATOM
    assert (
        "chain.max_depth IS DISTINCT FROM (v.spec->>'max_cascade_depth')::integer"
        in storage.CHAIN_ATOM
    )
    assert "id=chain.root_grant_id" in storage.CHAIN_ATOM
    assert "a.depth>chain.max_depth" in storage.ATTEMPT_ATOM
    assert (
        "a.depth=0 AND chain.root_grant_id IS DISTINCT FROM a.service_grant_id"
        in storage.ATTEMPT_ATOM
    )
    assert (
        "parent_attempt.run_id=a.parent_run_id AND parent_attempt.state='admitted'"
        in storage.ATTEMPT_ATOM
    )
    assert (
        "parent_attempt.chain_id=a.chain_id AND parent_attempt.depth+1=a.depth"
        in storage.ATTEMPT_ATOM
    )


def test_only_one_queued_terminal_transition_keeps_all_origin_fields_immutable():
    sql = storage.ATTEMPT_GUARD
    assert "NEW.state<>'queued' OR NEW.run_id IS NOT NULL OR NEW.admitted_at IS NOT NULL" in sql
    assert "OLD.state<>'queued' OR NEW.state NOT IN ('admitted','suppressed')" in sql
    assert "ARRAY['state','error_code','run_id','admitted_at']" in sql
    assert "TG_OP='DELETE'" in sql
    assert "NEW.state<>'suppressed'" in sql
    assert "NEW.origin->>'kind' IS DISTINCT FROM 'lifecycle'" in sql
    assert (
        "a.state<>'suppressed' AND NOT public.automation_service_grant_available"
        in storage.ATTEMPT_ATOM
    )
    assert "diagnostic.state='suppressed'" in storage.CHAIN_ATOM
    assert "diagnostic.xmin=chain_xid" in storage.CHAIN_ATOM
    # Suppression records an invalidated grant rather than requiring it to become valid again.
    assert "h.active" not in storage.IDENTITY
    attempt_checks = " ".join(
        str(c.sqltext) for c in storage.TABLES[2].constraints if hasattr(c, "sqltext")
    )
    assert "state='admitted' AND run_id IS NOT NULL AND admitted_at IS NOT NULL" in attempt_checks
    assert "state='suppressed' AND run_id IS NULL AND admitted_at IS NULL" in attempt_checks
    assert "error_code IS NOT NULL" in attempt_checks


def test_admitted_binds_real_new_run_identity_fixed_spec_and_actual_admission_clock():
    sql = storage.ATTEMPT_ATOM
    for fragment in (
        "'automation_service'::varchar,('automation-service:'||a.id)::varchar",
        "v.spec->>'goal',a.request_digest",
        "(v.spec->>'validation_budget_id')::uuid,(v.spec->>'token_limit')::integer",
        "r.product_id IS DISTINCT FROM (v.spec->>'product_id')::uuid",
        "r.proposal_id IS NOT NULL OR r.continued_from_id IS NOT NULL",
        "a.admitted_at<a.created_at OR a.admitted_at<r.created_at",
        "a.admitted_at<a.due_at",
        "ax IS DISTINCT FROM rx",
    ):
        assert fragment in sql
    assert "'automation_manual'" not in sql
    assert "set_config('pdos.actor_id'" not in " ".join(storage.function_sql())


def test_force_rls_keeps_agent_select_only_and_does_not_change_old_current():
    sql = " ".join(storage.policy_sql())
    for table in storage.TABLES:
        assert f'ALTER TABLE public."{table.name}" FORCE ROW LEVEL SECURITY' in sql
        assert f'GRANT SELECT ON public."{table.name}" TO pdos_next_app,pdos_agent' in sql
        assert f'GRANT INSERT ON public."{table.name}" TO pdos_next_app' in sql
    assert "owner_id=public.scope_requester()" in sql
    assert "writer_id=public.scope_actor()" in sql
    assert "GRANT UPDATE(state,error_code,run_id,admitted_at)" in sql
    assert not re.search(r"GRANT (?:INSERT|UPDATE|DELETE)[^;]* TO pdos_agent", sql)
    assert "FOR DELETE" not in sql and "automation_rule_currents" not in sql
    assert "object_audiences" not in sql


def test_private_helpers_are_revoked_and_downgrade_rejects_any_retained_history():
    upgrade = "\n".join(storage.upgrade_sql())
    for signature in storage.signatures():
        assert (
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,pdos_next_app,pdos_agent"
            in upgrade
        )
    for invalid in ("bad-role", "x;DROP TABLE principals", "", '"owner"'):
        with pytest.raises(ValueError):
            storage.upgrade_sql(invalid)
    down = "\n".join(storage.downgrade_sql())
    assert down.startswith("LOCK TABLE")
    assert down.index("downgrade refused") < down.index("DROP TABLE")
    assert "DELETE FROM" not in down and "TRUNCATE" not in down
    assert "automation_rule_versions" not in down and "agent_runs" not in down
