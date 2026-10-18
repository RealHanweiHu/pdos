"""Offline metadata checks for immutable Field facts and their finite SQL owners."""

import re

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.engine import Engine

from pdos_next import models as registered_models
from pdos_next.domain.field_feedback import storage
from pdos_next.domain.field_feedback.models import (
    CURRENT,
    FEEDBACK,
    RESPONSE,
    FieldFeedbackVersion,
    FieldResponseRecord,
)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Field storage declarations never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def checks(table):
    return " ".join(
        str(value.sqltext) for value in table.constraints if isinstance(value, CheckConstraint)
    )


def unique_targets(table):
    return {
        tuple(table.primary_key.columns.keys()),
        *(
            tuple(value.columns.keys())
            for value in table.constraints
            if isinstance(value, UniqueConstraint)
        ),
    }


def test_metadata_compiles_with_real_foreign_key_targets_and_no_scope_fabrication():
    assert {table.name for table in storage.TABLES} == {FEEDBACK, CURRENT, RESPONSE}
    for table in storage.TABLES:
        assert table.c.product_id.nullable and table.c.project_id.nullable
        assert not table.c.category_id.nullable
        assert "project_id IS NULL OR product_id IS NOT NULL" in checks(table)
        for reference in table.foreign_key_constraints:
            assert tuple(value.column.name for value in reference.elements) in unique_targets(
                reference.referred_table
            )
    ddl = storage.table_sql()
    assert sum(statement.lstrip().startswith("CREATE TABLE") for statement in ddl) == 3
    assert not storage.drop_cycle_sql()


@pytest.mark.parametrize(
    ("body", "status"),
    (
        (None, "unknown"),
        ({"location": None}, "unknown"),
        ({"location": {"state": "known"}}, "located"),
    ),
)
def test_feedback_status_preserves_unknown_and_never_invents_completed(body, status):
    assert FieldFeedbackVersion(body=body).status == status
    assert FieldResponseRecord().status == "recorded"


def test_independent_response_is_fixed_to_one_parent_and_has_no_current_to_invalidate_change():
    table = FieldResponseRecord.__table__
    references = [
        reference
        for reference in table.foreign_key_constraints
        if reference.referred_table.name == FEEDBACK
    ]
    assert len(references) == 1
    assert tuple(references[0].columns.keys()) == (
        "tenant_id",
        "category_id",
        "feedback_id",
        "feedback_version_id",
        "feedback_revision",
    )
    assert "revision=1 AND feedback_revision>0 AND confirmation_id IS NOT NULL" in checks(table)
    assert not any("response_current" in value.name for value in storage.TABLES)
    assert "UPDATE public.field_feedback_currents" not in storage.RESPONSE_ATOM


def test_sql_uses_columns_that_exist_on_actual_registered_owner_models():
    bodies = (
        (storage.MEMBERS_ATOM, {"r": "action_receipts", "proof": "confirmations"}),
        (
            storage.COMMON_ATOM,
            {"a": "artifact_versions", "o": "uploaded_originals", "sec": "original_security"},
        ),
        (storage.CURRENT_ATOM, {"cur": CURRENT, "fixed": FEEDBACK}),
        (
            storage.FEEDBACK_ATOM,
            {
                "v": FEEDBACK,
                "prior": FEEDBACK,
                "cur": CURRENT,
                "engineering": "engineering_configurations",
                "manufacturing": "process_revisions",
                "link": "project_product_links",
                "lot": "build_lots",
                "actual": "actual_configurations",
            },
        ),
        (
            storage.RESPONSE_ATOM,
            {
                "v": RESPONSE,
                "parent": FEEDBACK,
                "cur": CURRENT,
                "native_receipt": "action_receipts",
            },
        ),
    )
    for body, aliases in bodies:
        for alias, table_name in aliases.items():
            known = set(registered_models.Base.metadata.tables[table_name].c.keys()) | {"xmin"}
            used = set(re.findall(rf"\b{alias}\.([a-z_][a-z0-9_]*)", body))
            assert used <= known, (table_name, sorted(used - known))


def test_read_helpers_do_not_recurse_into_receipts_and_current_has_only_location_update_grants():
    policies = "\n".join(storage.policy_sql())
    assert "public.action_receipts" not in policies
    assert "FOR DELETE" not in policies and "TO pdos_agent" not in policies
    assert "GRANT UPDATE(version_id,revision,product_id,project_id)" in policies
    assert "field_feedback_currents" not in next(
        value for value in storage.policy_sql() if '"field_response_records" FOR SELECT' in value
    )
    helper = storage.receipt_visibility_sql()[0]
    assert "SECURITY INVOKER" in helper
    assert helper.index("IF kind NOT IN") < helper.index("FROM public.field_feedback_versions")


def test_performed_response_checks_fresh_sources_without_requiring_old_report_active():
    # The new action's evidence and any newly adopted native result content are
    # checked. Parent history enters ACL provenance, not the new command read set.
    common = storage.COMMON_ATOM
    assert "ELSE envelope->'payload'->'sources' END" in common
    assert "jsonb_array_elements(result->'direct_content_refs')" in common
    assert "Field historical source hash or actual audience changed" in common
    historical = common.split("FOR basis IN", 1)[1].split("active_sources=", 1)[0]
    assert "status='active'" not in historical
    assert "original_security" not in historical


def test_full_ddl_guards_t1_consumption_and_original_common_members_without_extra_approval_role():
    sql = "\n".join(storage.upgrade_sql())
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "public.confirmations" in sql and "public.request_keys" in sql
    assert "Consumed Field T1 proof requires exactly one new fact" in sql
    assert "Field T1 requires its actual consumed human confirmation" in sql
    assert "professional_authority" not in sql and "qualification" not in sql
    assert "Field history retained; downgrade refused" in "\n".join(storage.downgrade_sql())


def test_json_containment_operands_are_parenthesized_independently_of_operator_precedence():
    # PostgreSQL's generic @> operator shares precedence with JSON ->. A right
    # chain without parentheses can become (jsonb @> jsonb) -> key and fail only
    # when that deferred branch first runs. Reject that unsafe SQL shape.
    for name, _arguments, body, _returns in storage.functions():
        assert not re.search(r"(?<!\)) @>|@> (?!\()", body), name
