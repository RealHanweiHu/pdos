"""Offline risk schema checks; retained DB behavior is verified by the host."""

import re

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, text
from sqlalchemy.engine import Engine

from pdos_next import models as registered_models  # noqa: F401 -- standalone registry
from pdos_next.domain.external_wait import storage_schema as waiting
from pdos_next.domain.project_risk import storage_schema as storage
from pdos_next.domain.project_risk.models import (
    CURRENT,
    EFFECT,
    EVENT,
    FOLLOWUP,
    OPERATION,
    SUBJECT,
    ProjectRiskFollowup,
    ProjectRiskFollowupCurrent,
)
from pdos_next.domain.work_management import g0_storage
from pdos_next.domain.work_management import storage_schema as predecessor


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Risk declarations must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def _uniques(table):
    return {
        tuple(value.columns.keys())
        for value in table.constraints
        if isinstance(value, UniqueConstraint)
    }


def _checks(table):
    return " ".join(
        str(value.sqltext) for value in table.constraints if isinstance(value, CheckConstraint)
    )


@pytest.fixture
def definitions():
    # Reconstruct structural predecessors only; this does not stand in for capture.
    declarations = {
        name
        + "("
        + ",".join(part.split()[-1] for part in args.split(",") if part)
        + ")": predecessor._function(name, args, body, returns)
        for name, args, body, returns in predecessor.functions()
    }
    declarations.update(g0_storage.upgraded_functions(declarations))
    declarations.update(waiting.upgraded_common_functions(declarations))
    return declarations


def test_schema_keeps_native_risk_identity_and_all_fk_targets_exist():
    assert {value.name for value in storage.TABLES} == {FOLLOWUP, CURRENT}
    assert (OPERATION, SUBJECT, EVENT) == (
        "work.risk.followup.record",
        "risk_followup",
        "risk.followup_recorded",
    )
    for table in storage.TABLES:
        for reference in table.foreign_key_constraints:
            remote = reference.referred_table
            assert tuple(value.column.name for value in reference.elements) in {
                tuple(remote.primary_key.columns.keys()),
                *_uniques(remote),
            }
    ddl = "\n".join(storage.table_sql())
    assert "CREATE TABLE project_risk_followups" in ddl
    assert "CREATE TABLE project_risk_followup_currents" in ddl
    assert not {"proposal_id", "approver_id", "waiver_id", "task_id"} & set(
        ProjectRiskFollowup.__table__.c.keys()
    )


def test_no_empty_source_shortcut_and_exact_t1_human_identity():
    checks = _checks(ProjectRiskFollowup.__table__)
    assert "jsonb_array_length(sources)>0 AND jsonb_array_length(reads)>0" in checks
    assert "operation='work.risk.followup.record' AND confirmation_id IS NOT NULL" in checks
    assert "writer_id=actor_id AND actor_id=requester_id" in checks
    assert "(action='close' AND state='closed') OR (action='reopen' AND state='open')" in checks
    assert ProjectRiskFollowup(state="closed").status == "closed"
    assert "g0_open_item" not in checks  # No G0 task exception to actual evidence reads.


def test_chain_and_current_bind_scope_native_decision_and_exact_one_step():
    version, current = storage.TABLES
    assert ("tenant_id", "product_id", "risk_id", "revision") in _uniques(version)
    assert ("tenant_id", "product_id", "risk_id") in _uniques(current)
    assert "revision=1 AND action='close' AND state='closed'" in _checks(version)
    assert "previous_revision=revision-1" in _checks(version)
    for table, column in ((version, "previous_id"), (current, "version_id")):
        reference = next(ref for ref in table.foreign_key_constraints if column in ref.column_keys)
        assert {
            "tenant_id",
            "category_id",
            "product_id",
            "project_id",
            "owner_id",
            "visibility",
            "risk_id",
            "g0_decision_id",
        } <= set(reference.column_keys)
    assert "NEW.revision=OLD.revision+1" in storage.CURRENT_GUARD
    assert "v.previous_id=OLD.version_id" in storage.CURRENT_GUARD
    assert "v.previous_revision=OLD.revision" in storage.CURRENT_GUARD
    assert "vx IS DISTINCT FROM cx" in storage.CURRENT_ATOM
    assert ProjectRiskFollowupCurrent.__table__.c.g0_decision_id.nullable is False


def test_rls_keeps_project_audience_and_human_command_write_boundary():
    sql = "\n".join(storage.policy_sql())
    assert sql.count("FORCE ROW LEVEL SECURITY") == 2
    assert "p.owner_id=" in sql and "p.visibility=" in sql
    assert "public.scope_actor()=public.scope_requester()" in sql
    assert "h.kind='human' AND h.active" in sql
    assert "GRANT UPDATE(version_id,revision,state)" in sql
    assert "TO pdos_agent" not in sql and "FOR DELETE" not in sql
    assert "object_audiences" not in sql


def test_common_patch_preserves_artifact_checks_and_original_task_g0_guard(definitions):
    values = storage.upgraded_common_functions(definitions)
    original, write = definitions[storage.WRITE_SIGNATURE], values[storage.WRITE_SIGNATURE]
    suffix = " IF jsonb_typeof(v.source_basis->'artifacts')"
    assert original.split(suffix, 1)[1] == write.split(suffix, 1)[1]
    assert "IF kind='work_task' THEN PERFORM public.assert_work_task_g0_source(t,target)" in write
    assert "ELSIF kind<>'risk_followup' AND v.source_basis ? 'g0_open_item' THEN" in write
    for required in (
        "v.operation NOT IN ('work.task.create','work.external_wait.record')",
        "v.operation IN ('work.task.create','work.external_wait.record') AND v.actor_id<>",
        "coalesce(r.agent_run_id,r.run_id) IS NOT NULL",
        "v.confirmation_id IS NOT NULL",
        "Work confirmation consumption must share its new fact transaction",
    ):
        assert required in write and required in original
    assert "SELECT xmin INTO vx FROM public.project_risk_followups" in write


def test_common_members_and_confirmation_guard_add_actual_t1_fact(definitions):
    values = storage.upgraded_common_functions(definitions)
    members = values[storage.MEMBERS_SIGNATURE]
    assert "'risk_id',v.risk_id,'decision_id',v.g0_decision_id,'state',v.state" in members
    assert "WHEN 'work.risk.followup.record' THEN 'risk.followup_recorded'" in members
    for retained in (
        "r.result IS DISTINCT FROM expected_result",
        "coalesce(r.agent_run_id,r.run_id,v.command_id)",
        "c.snapshot IS DISTINCT FROM v.command->'review'",
        "c.consumed IS DISTINCT FROM true",
        "IF v.operation NOT IN ('work.task.create','work.external_wait.record')",
    ):
        assert retained in members and retained in definitions[storage.MEMBERS_SIGNATURE]
    proof, consumed = values["protect_work_confirmation()"], values["require_work_confirmation()"]
    assert OPERATION in proof and OPERATION in consumed
    assert "old_scoped AND new_scoped" in proof
    assert "(to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed')" in proof
    assert "UNION ALL SELECT confirmation_id FROM public.project_risk_followups" in consumed
    assert "amount<>1 OR OLD.consumed IS DISTINCT FROM false" in consumed
    for signature in ("protect_work_receipt()", "protect_work_member()", "require_work_member()"):
        assert OPERATION in values[signature] and SUBJECT in values[signature]
    assert (
        "'delivered_at','lease_id','lease_until','attempts','last_error'"
        in values["protect_work_member()"]
    )


def test_unknown_or_reapplied_capture_is_refused(definitions):
    with pytest.raises(ValueError, match="Missing actual captured function"):
        storage.upgraded_common_functions({})
    with pytest.raises(ValueError, match="already present"):
        storage.upgraded_common_functions(storage.upgraded_common_functions(definitions))
    definitions[storage.WRITE_SIGNATURE] = definitions[storage.WRITE_SIGNATURE].replace(
        " ELSIF v.source_basis ? 'g0_open_item' THEN", " ELSIF false THEN", 1
    )
    with pytest.raises(ValueError, match="one exact anchor"):
        storage.upgraded_common_functions(definitions)


def test_native_atom_uses_actual_named_g0_responsibility_without_private_proposal_reads():
    sql = storage.RISK_ATOM
    assert "public.project_open_items" in sql
    assert "oi.kind<>'risk' OR oi.status<>'open'" in sql
    assert "p.g0_decision_id IS DISTINCT FROM oi.g0_decision_id" in sql
    assert "(native-'digest') IS DISTINCT FROM expected_native" in sql
    for actor in ("actor_id", "requester_id", "writer_id"):
        assert f"v.{actor} IS DISTINCT FROM oi.owner_id" in sql
    assert "h.id=oi.owner_id AND h.kind='human' AND h.active" in sql
    assert "receipt.run_id IS NOT NULL OR receipt.agent_run_id IS NOT NULL" in sql
    assert "v.actor_id IS DISTINCT FROM p.owner_id" not in sql
    assert "public.proposals" not in sql and "public.proposal_decisions" not in sql
    assert not re.search(r"\b(?:UPDATE\s+\w+\s+SET|INSERT\s+INTO|DELETE\s+FROM)\b", sql)


def test_internal_result_has_no_task_or_release_side_effect_and_binds_full_review():
    sql = storage.RISK_ATOM
    assert "PERFORM public.assert_work_management_write(t,target,'risk_followup')" in sql
    assert "vx IS DISTINCT FROM cx" in sql
    assert "cur.risk_id,cur.g0_decision_id,cur.version_id,cur.revision,cur.state" in sql
    assert "payload->'risk' IS DISTINCT FROM jsonb_build_object('id',v.risk_id" in sql
    assert "payload->>'action' IS DISTINCT FROM v.action" in sql
    assert EFFECT in sql and "v.command->'review'->>'effect' IS DISTINCT FROM" in sql
    assert "'state',v.state,'summary',payload->'summary'" in sql
    assert "IF v.body IS DISTINCT FROM expected" in sql
    assert "jsonb_build_object('id',prior.id,'revision',prior.revision)" in sql
    assert "v.command->'review'->'before' IS DISTINCT FROM prior.body" in sql
    assert "native IS DISTINCT FROM prior.source_basis->'g0_open_item'" in sql
    assert "prior.state='closed' AND v.action='reopen' AND v.state='open'" in sql
    assert "prior.state='open' AND v.action='close' AND v.state='closed'" in sql


def test_atom_uses_columns_that_exist_on_registered_tables():
    aliases = {
        "v": FOLLOWUP,
        "prior": FOLLOWUP,
        "cur": CURRENT,
        "oi": "project_open_items",
        "p": "projects",
        "receipt": "action_receipts",
    }
    for alias, table in aliases.items():
        assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", storage.RISK_ATOM)) <= {
            *registered_models.Base.metadata.tables[table].c.keys(),
            "xmin",
        }


def test_complete_declarations_are_reversible_only_before_any_proof_history(definitions):
    upgrade, downgrade = storage.upgrade_sql(definitions), storage.downgrade_sql(definitions)
    assert len(storage.trigger_sql()) == 4
    assert all("ON public.project_risk_followup" in value for value in storage.trigger_sql())
    assert "public.reject_work_mutation()" in storage.trigger_sql()[0]
    assert not hasattr(storage, "install") and not hasattr(storage, "execute")
    down = "\n".join(downgrade)
    assert downgrade[0].startswith("LOCK TABLE")
    assert (
        "EXISTS(SELECT 1 FROM public.confirmations WHERE operation='work.risk.followup.record')"
        in down
    )
    assert down.index("downgrade refused") < down.index("DROP TABLE")
    assert "DELETE FROM" not in down and "TRUNCATE" not in down
    for statement in (*upgrade, *downgrade):
        assert not text(statement)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", statement)
