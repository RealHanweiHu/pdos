"""Offline command declarations, schema columns and original-proof boundaries."""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from pdos_next.domain.automations import service_commands_sql as commands
from pdos_next.domain.automations import service_models  # noqa: F401
from pdos_next.models import Base


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Service command declaration checks must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def test_exact_private_functions_without_a_connection_or_installer():
    assert commands.signatures() == (
        "automation_service_stop(uuid,text)",
        "assert_automation_service_run(uuid,uuid)",
        "automation_service_start(uuid)",
        "require_automation_service_run()",
    )
    assert commands.upgrade_sql() == commands.upgrade_sql()
    assert not hasattr(commands, "install") and not hasattr(commands, "uninstall")
    for sql in commands.upgrade_sql():
        assert not text(sql)._bindparams
        assert "CREATE OR REPLACE" not in sql
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)
        assert (
            "SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp" in sql
            or not sql.startswith("CREATE FUNCTION")
        )


def test_every_written_column_exists_and_insert_supplies_required_sql_columns():
    inserts = re.compile(r"INSERT INTO public\.([a-z_]+)\(([^)]+)\)", re.I)
    found = set()
    for sql in (commands.START, commands.STOP):
        for match in inserts.finditer(sql):
            table_name, columns = match.groups()
            table = Base.metadata.tables[table_name]
            supplied = columns.split(",")
            assert len(supplied) == len(set(supplied))
            assert set(supplied) <= set(table.c.keys())
            required = {c.name for c in table.c if not c.nullable and c.server_default is None}
            assert required <= set(supplied)
            found.add(table_name)
    assert found == {
        "agent_sessions",
        "agent_runs",
        "agent_run_events",
        "automation_causal_chains",
        "automation_service_attempts",
    }
    for table, fields in re.findall(r"UPDATE public\.([a-z_]+) SET (.*?) WHERE", commands.START):
        assert set(re.findall(r"(?:^|,)([a-z_]+)=", fields)) <= set(
            Base.metadata.tables[table].c.keys()
        )


def test_guard_aliases_match_actual_metadata_instead_of_fabricated_security_columns():
    for sql, aliases in (
        (
            commands.START,
            {
                "a": "automation_service_attempts",
                "g": "automation_service_grants",
                "v": "automation_rule_versions",
                "chain": "automation_causal_chains",
                "cur": "automation_rule_currents",
                "wallet": "agent_validation_budgets",
                "product": "products",
                "call": "agent_tool_calls",
                "access": "grants",
            },
        ),
        (
            commands.RUN_ATOM,
            {
                "r": "agent_runs",
                "a": "automation_service_attempts",
                "g": "automation_service_grants",
                "v": "automation_rule_versions",
                "session": "agent_sessions",
            },
        ),
    ):
        for alias, table in aliases.items():
            assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", sql)) <= set(
                Base.metadata.tables[table].c.keys()
            )


def test_start_real_identity_and_category_chain_current_attempt_lock_order():
    sql = commands.START
    assert "public.automation_service_identity(t,g.owner_id,g.writer_id)" in sql
    assert (
        "g.category_id IS DISTINCT FROM nullif(current_setting('pdos.category_id',true),'')::uuid"
        in sql
    )
    assert (
        sql.index("FROM public.categories WHERE")
        < sql.index("FROM public.automation_causal_chains WHERE")
        < sql.index("FROM public.automation_rule_currents WHERE")
        < sql.index("id=attempt_id FOR UPDATE")
    )
    assert "set_config(" not in sql and "SET LOCAL ROLE" not in sql
    assert "FOR SHARE" in sql
    assert "hashtextextended('automation-chain:'||a.chain_id::text,0)" in sql
    assert "hashtextextended('automation-budget:'||t::text||':'||g.rule_id::text,0)" in sql
    assert "authority_count<>2" in sql
    assert "point<access.expires_at" in sql


def test_terminal_replay_precedes_available_limits_and_does_not_make_another_run():
    sql = commands.START
    assert sql.index("IF a.state='admitted'") < sql.index("point=clock_timestamp()")
    assert "PERFORM public.assert_automation_service_run(t,a.run_id); RETURN a.run_id" in sql
    assert "ELSIF a.state='suppressed' THEN RETURN NULL" in sql
    assert sql.index("public.automation_service_grant_available(t,g.id,point)") < sql.index(
        "INSERT INTO public.agent_runs"
    )
    assert "cur.published_version_id IS DISTINCT FROM g.published_version_id" in sql
    assert "g.expires_at IS NOT NULL AND point>=g.expires_at" in sql
    assert "origin->>'kind'='lifecycle'" in sql


def test_counts_cooldown_future_due_and_real_cross_owner_parent_are_checked():
    sql = commands.START
    assert "cur.admitted_count>=(v.spec->>'max_runs')::integer" in sql
    assert "point<a.due_at" in sql
    assert "cur.last_admitted_at+make_interval(secs=>(v.spec->>'cooldown_seconds')::integer)" in sql
    assert "parent.chain_id=a.chain_id AND parent.depth+1=a.depth" in sql
    assert "parent.state='admitted' AND parent.rule_id=g.rule_id" in sql
    assert "error_code='SELF_TRIGGERED'" in sql
    assert "a.depth>chain.max_depth" in sql
    assert "error_code='CASCADE_DEPTH_EXCEEDED'" in sql
    assert "parent.owner_id=g.owner_id" not in sql


def test_wallet_rule_union_and_root_chain_read_actual_metered_call_metadata():
    sql = commands.START
    for fragment in (
        "wallet.requester_id<>g.owner_id OR NOT wallet.active",
        "call.cost_state='reserved' THEN call.cost_reserved_micro_usd "
        "ELSE call.cost_charged_micro_usd",
        "call.cost_state='reserved' THEN call.input_token_reservation "
        "ELSE call.actual_input_tokens",
        "call.cost_state='reserved' THEN call.output_token_reservation "
        "ELSE call.actual_output_tokens",
        "UNION SELECT manual.run_id FROM public.automation_trigger_occurrences",
        "member.chain_id=chain.id AND member.state='admitted'",
        "call.cost_state<>'unmetered'",
        "error_code='CHAIN_BUDGET_EXHAUSTED'",
        "public.automation_service_stop(g.id,'MODEL_BUDGET_EXHAUSTED')",
    ):
        assert fragment in sql
    assert "call.result" not in sql and "call.execution_binding" not in sql
    assert "source_basis" not in sql


def test_start_uses_real_bootstrap_taint_and_the_existing_session_checkpoint_protocol():
    sql = commands.START
    assert "private_value=product.visibility<>'category'" in sql
    assert "audience.principal_id=g.owner_id" in sql
    assert (
        "'automation_service',v.spec->>'goal','automation-service:'||a.id,a.request_digest" in sql
    )
    assert '\'{"checkpoint_layout":"session-run-ns/v1"}\'::jsonb' in sql
    assert "'[{\"" not in sql
    assert "'[\"internal\"]'::jsonb,'[]'::jsonb" in sql
    assert '\'{"type":"accepted","status":"queued"}\'::jsonb' in sql
    assert "SET state='admitted',run_id=new_run_id,admitted_at=point" in sql
    assert "SET admitted_count=admitted_count+1,last_admitted_at=point" in sql
    assert "UPDATE public.automation_rule_versions" not in sql


def test_stop_has_only_fixed_reasons_one_original_diagnostic_and_no_business_effect():
    assert set(commands.STOP_REASONS) == {
        "GOAL_REACHED",
        "SCOPE_INVALID",
        "EXPIRED",
        "SUPERSEDED",
        "MAX_RUNS",
        "MODEL_BUDGET_EXHAUSTED",
    }
    sql = commands.STOP
    assert "stop_reason IS NULL OR stop_reason NOT IN" in sql
    assert "trigger_key='lifecycle:stop'" in sql
    assert sql.index("RETURN prior.id") < sql.index("INSERT INTO public.automation_causal_chains")
    assert "'kind','lifecycle','reason',stop_reason" in sql
    assert "SET state='suppressed',error_code=stop_reason" in sql
    assert "public.automation_service_identity(t,g.owner_id,g.writer_id)" in sql
    assert "automation_service_grant_available" not in sql
    assert "INSERT INTO public.agent_runs" not in sql
    assert "automation_rule_currents" not in sql
    assert "set_config(" not in sql


def test_run_reciprocal_preserves_history_and_only_checks_same_transaction_on_creation():
    assert "state='admitted'" in commands.RUN_ATOM
    assert "v.confirmation_id IS NULL" in commands.RUN_ATOM
    assert "session.owner_id" in commands.RUN_ATOM
    assert "automation_service_grant_available" not in commands.RUN_ATOM
    assert "xmin" not in commands.RUN_ATOM
    assert "IF TG_OP='INSERT' THEN" in commands.RUN_TARGET
    assert commands.RUN_TARGET.index("IF TG_OP='INSERT' THEN") < commands.RUN_TARGET.index(
        "ax IS DISTINCT FROM rx"
    )
    assert "AFTER INSERT OR UPDATE ON public.agent_runs DEFERRABLE INITIALLY DEFERRED" in " ".join(
        commands.trigger_sql()
    )


def test_only_app_executes_narrow_commands_and_history_blocks_downgrade():
    sql = "\n".join(commands.authorization_sql())
    assert "GRANT EXECUTE ON FUNCTION public.automation_service_start(uuid) TO pdos_next_app" in sql
    assert (
        "GRANT EXECUTE ON FUNCTION public.automation_service_stop(uuid,text) TO pdos_next_app"
        in sql
    )
    assert "TO pdos_agent" not in sql and "TO pdos_next_dispatch" not in sql
    assert "GRANT EXECUTE ON FUNCTION public.assert_" not in sql
    for invalid in ("bad-role", "x;DROP TABLE principals", "", '"owner"'):
        with pytest.raises(ValueError):
            commands.authorization_sql(invalid)
    down = "\n".join(commands.downgrade_sql())
    assert down.startswith("LOCK TABLE")
    assert down.index("downgrade refused") < down.index("DROP TRIGGER")
    assert "DELETE FROM" not in down and "TRUNCATE" not in down and "DROP TABLE" not in down
