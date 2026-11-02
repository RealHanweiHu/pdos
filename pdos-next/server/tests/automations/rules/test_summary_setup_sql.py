"""Frozen SQL delta keeps original native authority/proof predicates byte-exact."""

from hashlib import sha256

from migrations import schema_summary_walletless as ddl


def test_start_changes_only_model_wallet_preflight_and_null_wallet_run_value():
    previous = ddl.PREVIOUS_START
    current = ddl.SCHEMA_SQL[1]
    prefix, tail = previous.split(" SELECT * INTO wallet FROM", 1)
    budget, suffix = tail.split(" session_id=gen_random_uuid();", 1)
    prefix = prefix.replace(
        " rule_cost numeric;", " summary_without_wallet boolean=false;\n rule_cost numeric;", 1
    )
    assert current.startswith(prefix)
    assert " SELECT * INTO wallet FROM" + budget in current
    assert current.endswith(
        " session_id=gen_random_uuid();"
        + suffix.replace(
            "wallet.id,0,0", "CASE WHEN summary_without_wallet THEN NULL ELSE wallet.id END,0,0", 1
        )
    )
    # The original wallet gate, budgets and every source/identity/lifecycle/CAS
    # predicate above and below it remain installed for non-summary rules.
    assert "summary_without_wallet=(v.spec->>'validation_budget_id' IS NULL)" in current
    for marker in (
        "jsonb_typeof(v.spec->'personal_summary')",
        "v.spec->'skill_keys'",
        "v.spec->'budget'",
        "v.spec->>'token_limit'",
    ):
        assert marker in current


def test_original_same_snapshot_proof_remains_unchanged_and_adds_only_zero_capacity_refusal():
    original = ddl.PREVIOUS_PROOF
    current = ddl.SCHEMA_SQL[2]
    prefix = original.removesuffix("END;\n$function$\n")
    assert current.startswith(prefix)
    assert " IF r.validation_budget_id IS NULL THEN" in current
    assert "r.held_tokens<>0 OR r.used_tokens<>0" in current
    assert "public.agent_tool_calls c WHERE c.tenant_id=t AND c.run_id=r.id" in current
    assert "session.project_id IS DISTINCT FROM r.project_id" in prefix
    for statement, source in (
        (ddl.PREVIOUS_START, "automation_service_start(uuid)"),
        (ddl.PREVIOUS_PROOF, "assert_automation_service_run(uuid,uuid)"),
    ):
        assert sha256(statement.encode()).hexdigest() in ddl.SCHEMA_SQL[0]
        assert source in ddl.SCHEMA_SQL[0]


def test_sql_call_refusal_uses_actual_published_grant_not_a_caller_mode_or_run_goal():
    sql = ddl.SCHEMA_SQL[3]
    for table in (
        "agent_runs",
        "automation_service_attempts",
        "automation_service_grants",
        "automation_rule_versions",
    ):
        assert "public." + table in sql
    assert "v.confirmation_id IS NOT NULL" in sql
    assert "jsonb_typeof(v.spec->'personal_summary')='object'" in sql
    assert "r.requester_id=g.owner_id AND r.writer_id=g.writer_id" in sql
    assert "v.spec->>'mode'" not in sql and "r.goal" not in sql and "SECURITY DEFINER" in sql
    assert "REVOKE ALL" in ddl.SCHEMA_SQL[4]
    assert "BEFORE INSERT ON public.agent_tool_calls" in ddl.SCHEMA_SQL[5]


def test_downgrade_refuses_real_walletless_history_before_restoring_original_guards():
    assert "Preserve walletless summary rule and Run history" in ddl.DOWNGRADE_SQL[1]
    assert ddl.DOWNGRADE_SQL[-2:] == (ddl.PREVIOUS_PROOF, ddl.PREVIOUS_START)
