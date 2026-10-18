"""Offline G0 association DDL/guard contracts, not installed PostgreSQL evidence."""

import re

import pytest
from sqlalchemy import CheckConstraint, text
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateIndex, CreateTable

from pdos_next import models as registered_models  # noqa: F401 -- standalone registry
from pdos_next.domain.preproject.models import ProjectOpenItem
from pdos_next.domain.work_management import g0_storage as g0
from pdos_next.domain.work_management import storage_schema as predecessor
from pdos_next.domain.work_management.models import (
    ProjectStatusUpdate,
    WorkCommitmentVersion,
    WorkTaskVersion,
)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("G0 SQL declarations must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


@pytest.fixture
def definitions():
    # This is the existing declaration as an offline patch fixture. The real
    # migration must supply pg_get_functiondef from its verified predecessor.
    return {
        g0.WRITE_SIGNATURE: predecessor._function(
            "assert_work_management_write",
            "t uuid,target uuid,kind text",
            predecessor.WRITE_ATOM,
            "void",
        ),
        g0.TASK_SIGNATURE: predecessor._function(
            "assert_work_task", "t uuid,target uuid", predecessor.TASK_ATOM, "void"
        ),
    }


def _checks(model):
    return " ".join(
        str(value.sqltext)
        for value in model.__table__.constraints
        if isinstance(value, CheckConstraint)
    )


def test_task_association_is_nullable_paired_and_first_version_uniquely_bound():
    table = WorkTaskVersion.__table__
    assert table.c.g0_open_item_id.nullable and table.c.g0_decision_id.nullable
    assert "(g0_open_item_id IS NULL)=(g0_decision_id IS NULL)" in _checks(WorkTaskVersion)
    assert {"work_task_g0_sources", "work_task_g0_identity"} <= {
        value.name for value in table.constraints if isinstance(value, CheckConstraint)
    }
    assert {"work_task_g0_item_fk", "work_task_g0_decision_fk"} <= {
        value.name for value in table.foreign_key_constraints
    }
    assert any(
        ref.column_keys == ["g0_open_item_id"] and ref.referred_table is ProjectOpenItem.__table__
        for ref in table.foreign_key_constraints
    )
    assert any(
        ref.column_keys == ["tenant_id", "category_id", "g0_decision_id"]
        and ref.referred_table.name == "proposal_decisions"
        for ref in table.foreign_key_constraints
    )
    index = next(
        value for value in table.indexes if value.name == "uq_work_task_g0_open_item_first"
    )
    assert index.unique and tuple(index.columns.keys()) == ("tenant_id", "g0_open_item_id")
    ddl = str(CreateIndex(index).compile(dialect=dialect()))
    assert "WHERE revision=1 AND g0_open_item_id IS NOT NULL" in ddl
    assert "CREATE TABLE work_task_versions" in str(CreateTable(table).compile(dialect=dialect()))


def test_empty_artifact_declaration_is_only_available_to_bound_native_tasks():
    task = _checks(WorkTaskVersion)
    assert "sources='[]'::jsonb AND reads='[]'::jsonb" in task
    assert "g0_open_item_id IS NOT NULL AND g0_decision_id IS NOT NULL" in task
    assert "AND COALESCE(jsonb_typeof(source_basis->'g0_open_item')='object'" in task
    assert "->>'id'=g0_open_item_id::text" in task
    assert "->>'decision_id'=g0_decision_id::text" in task
    assert "->>'digest' ~ '^[a-f0-9]{64}$',false)" in task
    for other in (WorkCommitmentVersion, ProjectStatusUpdate):
        check = _checks(other)
        assert "jsonb_array_length(sources)>0 AND jsonb_array_length(reads)>0" in check
        assert "g0_open_item" not in check and "g0_decision_id" not in other.__table__.c


def test_patch_preserves_actual_predecessor_text_except_two_narrow_changes(definitions):
    values = g0.upgraded_functions(definitions)
    write = values[g0.WRITE_SIGNATURE]
    restored = write.replace(g0.WRITE_ANCHOR + "\n" + g0.WRITE_EXTENSION, g0.WRITE_ANCHOR)
    assert restored == definitions[g0.WRITE_SIGNATURE]
    assert (
        values[g0.TASK_SIGNATURE].replace(g0.BASE_EXTENSION, g0.BASE_ANCHOR)
        == definitions[g0.TASK_SIGNATURE]
    )
    assert write.index("PERFORM public.assert_work_task_g0_source") < write.index(
        "NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)"
    )
    # Every existing artifact/registration/security guard stays byte for byte.
    original_tail = definitions[g0.WRITE_SIGNATURE].split(
        " IF jsonb_typeof(v.source_basis->'artifacts')", 1
    )[1]
    assert write.endswith(original_tail)


@pytest.mark.parametrize("signature", [g0.WRITE_SIGNATURE, g0.TASK_SIGNATURE])
def test_missing_actual_guard_or_owner_contract_refuses_to_generate(definitions, signature):
    with pytest.raises(ValueError, match="Missing actual captured function"):
        g0.upgrade_sql({key: value for key, value in definitions.items() if key != signature})
    definitions[signature] = definitions[signature].replace("SECURITY DEFINER", "", 1)
    with pytest.raises(ValueError, match="owner/search-path"):
        g0.upgrade_sql(definitions)


@pytest.mark.parametrize(
    "signature,anchor",
    [
        (g0.WRITE_SIGNATURE, g0.WRITE_ANCHOR),
        (g0.TASK_SIGNATURE, g0.BASE_ANCHOR),
    ],
)
def test_missing_or_ambiguous_live_anchor_refuses_partial_patch(definitions, signature, anchor):
    original = definitions[signature]
    definitions[signature] = original.replace(anchor, "", 1)
    with pytest.raises(ValueError, match="one exact anchor"):
        g0.upgrade_sql(definitions)
    definitions[signature] = original + "\n" + anchor
    with pytest.raises(ValueError, match="one exact anchor"):
        g0.upgrade_sql(definitions)


def test_already_extended_capture_is_not_silently_extended_twice(definitions):
    with pytest.raises(ValueError, match="already contain"):
        g0.upgrade_sql(g0.upgraded_functions(definitions))


def test_native_guard_checks_actual_scoped_result_and_no_private_document_or_new_authority():
    sql = g0.NATIVE_GUARD
    for field in (
        "tenant_id",
        "category_id",
        "product_id",
        "project_id",
        "g0_decision_id",
    ):
        assert f"x.{field}=" in sql
    assert "x.id=v.g0_open_item_id" in sql and "d.outcome='approved'" in sql
    assert "d.created_project_id=p.id AND d.created_product_id=p.product_id" in sql
    assert "d.id=p.g0_decision_id" in sql and "p.g0_decision_id=v.g0_decision_id" in sql
    assert "(native-'digest') IS DISTINCT FROM expected" in sql
    assert "native->>'digest' IS NULL" in sql and "^[a-f0-9]{64}$" in sql
    assert "v.body->'g0_open_item' IS DISTINCT FROM binding" in sql
    assert "v.command->'envelope'->'payload'->'g0_open_item' IS DISTINCT FROM binding" in sql
    assert "ROW(v.g0_open_item_id,v.g0_decision_id) IS DISTINCT FROM ROW(prior." in sql
    assert "prior.source_basis->'g0_open_item'" in sql
    assert "oi.kind NOT IN ('task','risk')" in sql
    assert not re.search(r"\b(?:UPDATE|INSERT|DELETE)\b", sql)
    assert not any(
        name in sql
        for name in ("frozen_document", "dispositions", "signer_grant_snapshot", "object_audiences")
    )


def test_old_task_missing_nullable_snapshot_key_can_continue_without_changing_other_fields():
    assert (
        "(v.body-allowed-'g0_open_item') IS DISTINCT FROM (prior.body-allowed-'g0_open_item')"
        in (g0.BASE_EXTENSION)
    )
    assert "coalesce(v.body->'g0_open_item','null'::jsonb)" in g0.BASE_EXTENSION
    assert "coalesce(prior.body->'g0_open_item','null'::jsonb)" in g0.BASE_EXTENSION
    assert "allowed=ARRAY['revision','state']" in predecessor.TASK_ATOM
    assert "Task action cannot replace fixed base or other facts" in predecessor.TASK_ATOM


def test_native_source_is_fixed_except_legacy_status_and_builder_has_no_executor(definitions):
    assert "TG_OP='UPDATE'" in g0.OPEN_ITEM_GUARD
    assert "(to_jsonb(NEW)-'status') IS NOT DISTINCT FROM (to_jsonb(OLD)-'status')" in (
        g0.OPEN_ITEM_GUARD
    )
    values = g0.upgrade_sql(definitions)
    assert values == g0.upgrade_sql(definitions)
    assert not hasattr(g0, "install") and not hasattr(g0, "execute")
    assert "BEFORE UPDATE OR DELETE ON public.project_open_items" in "\n".join(values)
    assert "FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch" in values[-1]
    for sql in values:
        assert not text(sql)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)
