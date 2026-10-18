"""Offline external waiting DDL/finite guard declarations, never a DB substitute."""

import re

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, text
from sqlalchemy.engine import Engine

from pdos_next import models as registered_models  # noqa: F401 -- standalone registry
from pdos_next.domain.external_wait import storage_schema as storage
from pdos_next.domain.external_wait.models import (
    CURRENT,
    EVENT,
    OPERATION,
    SUBJECT,
    WAIT,
    ExternalWaitCurrent,
    ExternalWaitVersion,
)
from pdos_next.domain.work_management import g0_storage
from pdos_next.domain.work_management import storage_schema as predecessor


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("External wait declarations must never connect")

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
    # Offline structural predecessors, not a claim about installed DB versions.
    declarations = {
        name
        + "("
        + ",".join(part.split()[-1] for part in args.split(",") if part)
        + ")": predecessor._function(name, args, body, returns)
        for name, args, body, returns in predecessor.functions()
    }
    declarations.update(g0_storage.upgraded_functions(declarations))
    return declarations


def test_actual_metadata_compiles_and_all_fk_targets_are_unique():
    assert {value.name for value in storage.TABLES} == {WAIT, CURRENT}
    for table in storage.TABLES:
        for reference in table.foreign_key_constraints:
            remote = reference.referred_table
            assert tuple(value.column.name for value in reference.elements) in {
                tuple(remote.primary_key.columns.keys()),
                *_uniques(remote),
            }
    ddl = "\n".join(storage.table_sql())
    assert "CREATE TABLE external_wait_versions" in ddl
    assert "CREATE TABLE external_wait_currents" in ddl


def test_stable_wait_identity_and_exact_single_step_predecessor_are_separate():
    version, current = storage.TABLES
    assert ("tenant_id", "product_id", "wait_id", "revision") in _uniques(version)
    assert ("tenant_id", "product_id", "wait_id") in _uniques(current)
    assert "revision=1 AND wait_id=id AND action='create' AND state='open'" in _checks(version)
    assert "previous_revision=revision-1" in _checks(version)
    prior = next(ref for ref in version.foreign_key_constraints if "previous_id" in ref.column_keys)
    assert {"project_id", "owner_id", "visibility", "wait_id"} <= set(prior.column_keys)
    exact = next(ref for ref in current.foreign_key_constraints if "version_id" in ref.column_keys)
    assert {"project_id", "owner_id", "visibility", "wait_id", "revision"} <= set(exact.column_keys)
    assert ExternalWaitVersion(state="closed").status == "closed"


def test_only_registered_t0_operation_uses_nonempty_real_original_reads():
    version = ExternalWaitVersion.__table__
    assert (OPERATION, SUBJECT, EVENT) == (
        "work.external_wait.record",
        "external_wait",
        "external_wait.recorded",
    )
    checks = _checks(version)
    assert "operation='work.external_wait.record' AND confirmation_id IS NULL" in checks
    assert "jsonb_array_length(sources)>0 AND jsonb_array_length(reads)>0" in checks
    assert "g0_open_item" not in checks
    assert not {"approval_token", "qualified", "effective_delivery", "responsible_id"} & set(
        version.c.keys()
    )
    assert not {"requested_at", "promised_at", "forecast"} & set(version.c.keys())


def test_project_audience_rls_and_write_roles_are_not_expanded():
    sql = "\n".join(storage.policy_sql())
    assert sql.count("FORCE ROW LEVEL SECURITY") == 2
    assert "public.projects p" in sql and "p.owner_id=" in sql and "p.visibility=" in sql
    assert "object_audiences" not in sql
    assert "GRANT UPDATE(version_id,revision,state)" in sql
    assert "TO pdos_agent" not in sql and "FOR DELETE" not in sql
    assert "kind='human'" not in sql  # T0 permits qualified AI; leaf guards own actual facts.


def test_current_requires_same_transaction_version_and_exact_cas():
    assert "NEW.revision=OLD.revision+1" in storage.CURRENT_GUARD
    assert "v.previous_id=OLD.version_id" in storage.CURRENT_GUARD
    assert "v.previous_revision=OLD.revision" in storage.CURRENT_GUARD
    assert "'version_id','revision','state'" in storage.CURRENT_GUARD
    assert "vx IS DISTINCT FROM cx" in storage.CURRENT_ATOM
    assert ExternalWaitCurrent.__table__.c.version_id.nullable is False


def test_common_extension_reuses_original_artifact_and_g0_guards_unchanged(definitions):
    values = storage.upgraded_common_functions(definitions)
    write = values[storage.WRITE_SIGNATURE]
    original = definitions[storage.WRITE_SIGNATURE]
    marker = " IF jsonb_typeof(v.source_basis->'artifacts')"
    assert write.split(marker, 1)[1] == original.split(marker, 1)[1]
    assert g0_storage.WRITE_EXTENSION in write
    assert "public.assert_work_task_g0_source(t,target)" in write
    assert "v.operation NOT IN ('work.task.create','work.external_wait.record')" in write
    assert (
        "v.operation IN ('work.task.create','work.external_wait.record') AND v.actor_id<>" in write
    )
    assert "coalesce(r.agent_run_id,r.run_id) IS NOT NULL" in write
    assert "v.confirmation_id IS NOT NULL" in write
    assert "ELSE SELECT xmin INTO vx FROM public.project_status_updates" in write


def test_common_members_use_real_wait_state_fixed_refs_and_registered_event(definitions):
    value = storage.upgraded_common_functions(definitions)[storage.MEMBERS_SIGNATURE]
    assert "SELECT * INTO STRICT v FROM public.external_wait_versions" in value
    assert "kind IN ('work_task','external_wait') THEN v.body->>'state'" in value
    assert (
        "jsonb_build_object('wait_id',v.wait_id,'state',v.state,'project_id',v.project_id)" in value
    )
    assert "WHEN 'work.external_wait.record' THEN 'external_wait.recorded'" in value
    assert "IF v.operation NOT IN ('work.task.create','work.external_wait.record')" in value
    for required in (
        "r.result IS DISTINCT FROM expected_result",
        "coalesce(r.agent_run_id,r.run_id,v.command_id)",
        "Work fact original common group mismatch",
        "c.consumed IS DISTINCT FROM true",
    ):
        assert required in value


def test_shared_immutability_scope_adds_wait_without_changing_confirmation_policy(definitions):
    values = storage.upgraded_common_functions(definitions)
    assert set(values) == set(storage.COMMON_SIGNATURES)
    assert not {"protect_work_confirmation()", "require_work_confirmation()"} & set(values)
    for signature in ("protect_work_receipt()", "protect_work_member()", "require_work_member()"):
        assert "'work.external_wait.record'" in values[signature]
        assert "'external_wait'" in values[signature]
    assert (
        "'delivered_at','lease_id','lease_until','attempts','last_error'"
        in values["protect_work_member()"]
    )


def test_common_patch_requires_known_actual_predecessors_and_is_not_repeatable(definitions):
    with pytest.raises(ValueError, match="Missing actual captured function"):
        storage.upgraded_common_functions({})
    upgraded = storage.upgraded_common_functions(definitions)
    with pytest.raises(ValueError, match="already present"):
        storage.upgraded_common_functions(upgraded)
    definitions[storage.WRITE_SIGNATURE] = definitions[storage.WRITE_SIGNATURE].replace(
        "v.operation<>'work.task.create' AND", "false AND", 1
    )
    with pytest.raises(ValueError, match="one exact anchor"):
        storage.upgraded_common_functions(definitions)


def test_waiting_action_is_bound_to_current_prior_and_only_explicit_fields_can_change():
    sql = storage.WAIT_ATOM
    assert "PERFORM public.assert_work_management_write(t,target,'external_wait')" in sql
    assert "vx IS DISTINCT FROM cx" in sql
    assert "cur.wait_id,cur.version_id,cur.revision,cur.state" in sql
    assert "jsonb_build_object('id',v.wait_id,'revision',prior.revision)" in sql
    assert "record->>'action' IS DISTINCT FROM v.action" in sql
    assert "expected=prior.body||jsonb_build_object('revision',v.revision)" in sql
    assert "IF v.body IS DISTINCT FROM expected" in sql
    assert "expected=expected||(record-'action')" not in sql
    assert "'target',record->'target','request_content',record->'request_content'" in sql
    assert "v.requester_id::text NOT IN (prior.body->>'responsible_id',p.owner_id::text)" in sql
    assert "prior.state='closed' AND v.action='reopen'" in sql
    assert "prior.state='open' AND v.action<>'reopen'" in sql


def test_recorded_delivery_needs_real_human_not_an_artifact_or_reported_claim():
    sql = storage.WAIT_ATOM
    assert "human_actor=v.actor_id=v.requester_id AND receipt.run_id IS NULL" in sql
    assert "receipt.agent_run_id IS NULL" in sql and "h.kind='human' AND h.active" in sql
    assert "CASE WHEN human_actor THEN 'human_recorded' ELSE 'source_claim' END" in sql
    assert "entry->>'status'='effective' OR prior.body->'delivery'->>'status'='effective'" in sql
    assert "NOT human_actor OR entry->>'time_basis' IS DISTINCT FROM 'human_recorded'" in sql
    assert "entry->>'status'='effective' AND (entry->>'at')::timestamptz IS NULL" in sql
    assert "(entry->>'recorded_at')::timestamptz IS DISTINCT FROM v.created_at" in sql
    assert "(entry->>'at')::timestamptz>(entry->>'recorded_at')::timestamptz" in sql
    assert "(entry->>'at')::timestamptz<(prior.body->'initiation'->>'at')::timestamptz" in sql
    assert "'sources',payload->'sources'" in sql
    assert "'promised_at',entry->'promised_at'" in sql
    assert not re.search(r"\b(?:UPDATE\s+\w+\s+SET|INSERT\s+INTO|DELETE\s+FROM)\b", sql)


def test_transfer_request_retains_responsibility_until_exact_target_person_accepts():
    sql = storage.WAIT_ATOM
    assert "'from_id',prior.body->'responsible_id'" in sql
    assert "(entry->>'requested_at')::timestamptz IS DISTINCT FROM v.created_at" in sql
    assert "record->'request_id' IS DISTINCT FROM entry->'request_id'" in sql
    assert "entry->'from_id' IS DISTINCT FROM prior.body->'responsible_id'" in sql
    assert "NOT human_actor OR entry->>'to_id' IS DISTINCT FROM v.requester_id::text" in sql
    assert "expected=expected||jsonb_build_object('responsible_id',entry->'to_id')" in sql
    assert sql.count("jsonb_build_object('responsible_id'") == 1
    assert "JOIN public.grants g ON g.tenant_id=h.tenant_id AND g.principal_id=h.id" in sql
    assert "g.can_write AND (g.expires_at IS NULL OR v.created_at<g.expires_at)" in sql


def test_calendar_uses_fixed_native_json_and_actual_current_resource_without_repinning_old_clock():
    sql = storage.CALENDAR_ATOM
    assert "cal->'ref' IS DISTINCT FROM ref" in sql
    assert (
        "'tenant_id',t,'category_id',v.category_id,'product_id',v.product_id,'project_id',v.project_id"
        in sql
    )
    assert "(v.source_basis->'artifacts') @> (cal#>'{material,source_basis,artifacts}')" in sql
    assert "pp.input_snapshot->'calendar'=cal->'source_calendar'" in sql
    assert "pl.id::text=ref->>'id' AND pl.revision::text=ref->>'revision'" in sql
    assert "res->'calendar'=cal->'source_calendar'" in sql
    assert "live.id=ptr.fact_id AND live.revision=ptr.fact_revision" in sql
    assert "actual->>'lifecycle'='active'" in sql
    assert "actual->'calendar'->>'calendar_id'=res->'calendar'->>'calendar_id'" in sql
    assert "asset.kind='resource' AND asset.data->>'state'='active'" in sql
    assert "cal->'current'" not in sql  # Advancing a source is not withdrawing an adopted calendar.
    assert "BEGIN\n SELECT" in sql and "RETURN;" in sql


def test_new_sql_columns_exist_in_actual_registered_tables():
    aliases = {
        "v": WAIT,
        "prior": WAIT,
        "cur": CURRENT,
        "p": "projects",
        "receipt": "action_receipts",
    }
    for alias, table in aliases.items():
        assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", storage.WAIT_ATOM)) <= {
            *registered_models.Base.metadata.tables[table].c.keys(),
            "xmin",
        }
    for alias, table in {
        "v": WAIT,
        "pl": "plan_revisions",
        "pp": "plan_proposals",
        "link": "project_product_links",
        "fixed": "build_operational_facts",
        "live": "build_operational_facts",
        "ptr": "build_operational_current",
        "asset": "operational_asset_sentinels",
    }.items():
        assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", storage.CALENDAR_ATOM)) <= set(
            registered_models.Base.metadata.tables[table].c.keys()
        )


def test_complete_declarations_keep_history_and_have_no_installer_or_extra_common_triggers(
    definitions,
):
    upgrade, downgrade = storage.upgrade_sql(definitions), storage.downgrade_sql(definitions)
    assert upgrade == storage.upgrade_sql(definitions)
    assert downgrade == storage.downgrade_sql(definitions)
    assert not hasattr(storage, "install") and not hasattr(storage, "execute")
    assert len(storage.trigger_sql()) == 4
    assert all("ON public.external_wait_" in sql for sql in storage.trigger_sql())
    assert "public.reject_work_mutation()" in storage.trigger_sql()[0]
    assert downgrade[0].startswith("LOCK TABLE")
    down = "\n".join(downgrade)
    assert down.index("downgrade refused") < down.index("DROP TABLE")
    assert "DELETE FROM" not in down and "TRUNCATE" not in down
    for sql in (*upgrade, *downgrade):
        assert not text(sql)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)
