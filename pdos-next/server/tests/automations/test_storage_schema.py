"""Offline storage-contract checks; no installed-schema or runtime claims."""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from pdos_next.domain.automations import storage_schema as storage
from pdos_next.domain.automations.models import AutomationRuleVersion
from pdos_next.models import Base


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Automation declaration checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def test_sql_is_deterministic_offline_and_uses_only_the_three_new_tables():
    assert storage.upgrade_sql() == storage.upgrade_sql()
    assert storage.downgrade_sql() == storage.downgrade_sql()
    assert [table.name for table in storage.TABLES] == [
        "automation_rule_versions",
        "automation_rule_currents",
        "automation_trigger_occurrences",
    ]
    assert not hasattr(storage, "install") and not hasattr(storage, "uninstall")
    for sql in (*storage.upgrade_sql(), *storage.downgrade_sql()):
        assert not text(sql)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)


def test_sql_references_existing_relations_and_actual_column_names():
    relations = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|ON|TABLE)\s+public\.([a-z_]+)\b", re.I)
    for sql in storage.upgrade_sql():
        for match in relations.finditer(sql):
            if not sql[match.end() :].lstrip().startswith("("):
                assert match.group(1) in Base.metadata.tables
    for sql, aliases in (
        (
            storage.MEMBERS,
            {
                "v": "automation_rule_versions",
                "r": "action_receipts",
                "c": "confirmations",
            },
        ),
        (
            storage.VERSION_ATOM,
            {"v": "automation_rule_versions", "cur": "automation_rule_currents"},
        ),
        (
            storage.OCCURRENCE_ATOM,
            {
                "o": "automation_trigger_occurrences",
                "v": "automation_rule_versions",
                "cur": "automation_rule_currents",
                "r": "agent_runs",
                "b": "agent_validation_budgets",
            },
        ),
    ):
        for alias, table in aliases.items():
            assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", sql)) <= set(
                Base.metadata.tables[table].c.keys()
            )


def test_fact_and_current_foreign_keys_include_scope_owner_and_fixed_version():
    for table in storage.TABLES:
        assert {"tenant_id", "category_id", "owner_id"} <= set(table.c.keys())
    current = storage.TABLES[1]
    pointers = {
        tuple(column.name for column in constraint.columns)
        for constraint in current.foreign_key_constraints
    }
    assert ("tenant_id", "category_id", "owner_id", "rule_id", "version_id", "revision") in pointers
    assert ("tenant_id", "category_id", "owner_id", "rule_id", "published_version_id") in pointers
    occurrence = storage.TABLES[2]
    assert any(
        tuple(column.name for column in constraint.columns) == ("tenant_id", "run_id")
        for constraint in occurrence.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )
    assert AutomationRuleVersion(state="draft").status == "draft"


def test_common_group_is_exact_reciprocal_and_same_transaction():
    assert "r.result IS DISTINCT FROM jsonb_build_object" in storage.MEMBERS
    assert "'rule_id',v.rule_id,'state',current_state" in storage.MEMBERS
    assert "r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL" in storage.MEMBERS
    assert "e.correlation_id=v.command_id" in storage.MEMBERS
    assert "convert_to(k.key,'UTF8')" in storage.MEMBERS
    assert "vx IS DISTINCT FROM rx OR vx IS DISTINCT FROM cx" in storage.VERSION_ATOM
    assert "k.xmin=vx" in storage.VERSION_ATOM
    triggers = " ".join(storage.trigger_sql())
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        assert f"AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED" in triggers
    assert "r.operation NOT IN" in storage.MEMBER_TARGET
    assert "r.subject_type<>'automation_rule'" in storage.MEMBER_TARGET


def test_t1_consumes_only_its_actual_category_confirmation():
    assert "c.subject_type,c.subject_id" in storage.MEMBERS
    assert "'category'::varchar,v.category_id" in storage.MEMBERS
    assert "c.snapshot IS DISTINCT FROM v.command->'review'" in storage.MEMBERS
    assert "OLD.consumed IS DISTINCT FROM false" in storage.PROOF
    assert "NEW.consumed IS DISTINCT FROM true" in storage.PROOF
    assert "v.confirmation_id=NEW.id AND v.operation=NEW.operation)<>1" in storage.PROOF_TARGET
    assert "cx IS DISTINCT FROM vx" in storage.VERSION_ATOM
    assert "T2" not in storage.PROOF and "qualification" not in storage.VERSION_ATOM


def test_edit_publish_pause_and_resume_keep_exact_history_and_counters():
    sql = storage.CURRENT_GUARD
    assert "NEW.revision<>OLD.revision+1" in sql
    assert "v.previous_id IS DISTINCT FROM OLD.version_id" in sql
    assert "coalesce(OLD.draft_version_id,OLD.published_version_id)" in sql
    assert "v.spec IS DISTINCT FROM prior.spec" in sql
    assert "NEW.published_version_id IS DISTINCT FROM OLD.published_version_id" in sql
    assert "NEW.draft_version_id IS DISTINCT FROM OLD.draft_version_id" in sql
    assert "'version_id','revision','state','draft_version_id','published_version_id'" in sql
    assert "NEW.admitted_count<>OLD.admitted_count+1" in sql
    assert "cur.admitted_count IS DISTINCT FROM count_actual" in storage.CURRENT_ATOM
    assert "cur.last_admitted_at IS DISTINCT FROM last_actual" in storage.CURRENT_ATOM


def test_manual_occurrence_binds_a_new_real_human_run_and_exact_saved_spec():
    sql = storage.OCCURRENCE_ATOM
    for fragment in (
        "p.kind='human' AND p.active",
        "'automation_manual'::varchar",
        "('automation:'||o.intent_key)::varchar",
        "o.request_digest",
        "v.spec->>'goal'",
        "(v.spec->>'validation_budget_id')::uuid",
        "(v.spec->>'token_limit')::integer",
        "r.product_id IS DISTINCT FROM (v.spec->>'product_id')::uuid",
        "r.read_sources IS DISTINCT FROM '[]'::jsonb",
        "b.requester_id<>o.owner_id OR NOT b.active",
        "count_actual>(v.spec->>'max_runs')::integer",
        "v.spec->>'cooldown_seconds'",
        "ox IS DISTINCT FROM rx OR ox IS DISTINCT FROM cx",
    ):
        assert fragment in sql
    assert "b.limit_micro_usd" not in sql  # Rule limits need not equal its larger wallet.
    assert "requester_id=scope_actor" not in sql  # No service-to-human impersonation branch.


def test_network_mcp_and_cross_object_capabilities_stay_explicitly_disabled():
    for field, value in (
        ("trigger_kind", "'manual'"),
        ("allow_network", "'false'::jsonb"),
        ("mcp_tools", "'[]'::jsonb"),
        ("cross_object_write", "'false'::jsonb"),
    ):
        operator = "->>" if field == "trigger_kind" else "->"
        assert f"v.spec{operator}'{field}' IS DISTINCT FROM {value}" in storage.VERSION_ATOM
    assert "mcp_tool_grants" not in " ".join(storage.upgrade_sql())


def test_force_rls_owner_human_writes_and_agent_read_only():
    sql = " ".join(storage.policy_sql())
    for table in storage.TABLES:
        assert f'ALTER TABLE public."{table.name}" FORCE ROW LEVEL SECURITY' in sql
        assert f'GRANT SELECT ON public."{table.name}" TO pdos_next_app,pdos_agent' in sql
        assert f'GRANT INSERT ON public."{table.name}" TO pdos_next_app' in sql
    assert "owner_id=public.scope_requester()" in sql
    assert "owner_id=public.scope_actor()" in sql
    assert "h.kind='human'" in sql
    assert (
        "GRANT UPDATE(version_id,revision,state,draft_version_id,published_version_id,"
        "admitted_count,last_admitted_at)" in sql
    )
    assert not re.search(r"GRANT (?:INSERT|UPDATE|DELETE)[^;]* TO pdos_agent", sql)
    assert "FOR DELETE" not in sql
    assert "request_keys" not in sql and "object_audiences" not in sql


def test_roles_are_parameters_only_as_valid_identifiers_and_down_retains_history():
    custom = " ".join(storage.upgrade_sql("local_app", "local_agent"))
    assert "TO local_app,local_agent" in custom
    for invalid in ("x;DROP TABLE principals", '"owner"', "bad-role", ""):
        with pytest.raises(ValueError):
            storage.upgrade_sql(invalid)
    down = "\n".join(storage.downgrade_sql())
    assert down.startswith("LOCK TABLE")
    assert down.index("downgrade refused") < down.index("DROP TABLE")
    assert "DELETE FROM" not in down and "TRUNCATE" not in down
    assert "Automation facts are immutable" in " ".join(storage.function_sql())
