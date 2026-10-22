"""Offline metadata and SQL contracts; no installed-database claim."""

# ruff: noqa: I001 -- Load the shared metadata registry before child declarations.
import re

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, text
from sqlalchemy.engine import Engine

from pdos_next.models import Base
from pdos_next.domain.work_fulfillment import storage_sql as storage
from pdos_next.domain.work_fulfillment.models import (
    WorkCommitmentReview,
    WorkCommitmentReviewCurrent,
)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Fulfillment declaration checks never connect")

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


def test_two_tables_compile_with_real_fixed_scope_and_unique_fk_targets():
    assert len(storage.TABLES) == 2
    assert len(storage.table_sql()) >= 2
    for table in storage.TABLES:
        for reference in table.foreign_key_constraints:
            remote = reference.referred_table
            assert tuple(value.column.name for value in reference.elements) in {
                tuple(remote.primary_key.columns.keys()),
                *_uniques(remote),
            }, (table.name, remote.name)
    version, current = storage.TABLES
    assert ("tenant_id", "product_id", "commitment_id", "revision") in _uniques(version)
    assert ("tenant_id", "product_id", "commitment_id") in _uniques(current)
    promise = next(
        fk for fk in version.foreign_key_constraints if "commitment_revision" in fk.column_keys
    )
    assert {"series_id", "promisor_id", "recipient_id", "owner_id", "visibility"} <= set(
        promise.column_keys
    )
    assert "actor_id=recipient_id" in _checks(version)
    assert WorkCommitmentReview(state="fulfilled").status == "fulfilled"
    assert not {"promised_at", "actual_at", "expires_at", "closed_at"} & set(version.c.keys())
    assert WorkCommitmentReviewCurrent.__table__ is current


def test_declarations_are_deterministic_parameter_free_and_have_no_executor():
    assert storage.upgrade_sql() == storage.upgrade_sql()
    assert storage.downgrade_sql() == storage.downgrade_sql()
    assert not hasattr(storage, "install") and not hasattr(storage, "uninstall")
    for sql in (*storage.upgrade_sql(), *storage.downgrade_sql()):
        assert not text(sql)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", sql)
    assert "work.task.review" not in " ".join(storage.upgrade_sql())


def test_sql_relations_and_row_fields_match_actual_metadata():
    relations = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|ON|TABLE)\s+public\.([a-z_]+)\b", re.I)
    for sql in storage.upgrade_sql():
        for match in relations.finditer(sql):
            if not sql[match.end() :].lstrip().startswith("("):
                assert match.group(1) in Base.metadata.tables
    for sql, aliases in (
        (
            storage.MEMBERS,
            {"v": "work_commitment_reviews", "r": "action_receipts", "c": "confirmations"},
        ),
        (storage.WRITE_ATOM, {"v": "work_commitment_reviews", "p": "projects"}),
        (
            storage.REVIEW_ATOM,
            {
                "v": "work_commitment_reviews",
                "prior": "work_commitment_reviews",
                "promise": "work_commitment_versions",
                "promise_cur": "work_commitment_currents",
                "task": "work_task_versions",
                "task_cur": "work_task_currents",
                "submission": "work_task_versions",
                "cur": "work_commitment_review_currents",
            },
        ),
    ):
        unquoted = re.sub(r"'(?:''|[^'])*'", "''", sql)
        for alias, table in aliases.items():
            assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", unquoted)) <= set(
                Base.metadata.tables[table].c.keys()
            )


def test_exact_original_t1_and_common_members_are_reciprocally_atomic():
    assert "r.result IS DISTINCT FROM expected_result" in storage.MEMBERS
    assert (
        "'commitment_id',v.commitment_id,'task_id',v.task_id,'recipient_id',v.recipient_id,'project_id',v.project_id"
        in storage.MEMBERS
    )
    assert "e.type='commitment.reviewed'" in storage.MEMBERS
    assert "coalesce(r.agent_run_id,r.run_id,v.command_id)" in storage.MEMBERS
    assert "c.snapshot IS DISTINCT FROM v.command->'review'" in storage.MEMBERS
    assert "vx IS DISTINCT FROM rx OR vx IS DISTINCT FROM cx" in storage.WRITE_ATOM
    assert "k.xmin=vx" in storage.WRITE_ATOM
    assert "convert_to(k.key,'UTF8')" in storage.WRITE_ATOM
    assert "OLD.consumed IS DISTINCT FROM false" in storage.PROOF
    assert "NEW.consumed IS DISTINCT FROM true" in storage.PROOF
    assert "<>1" in storage.TRANSITION
    triggers = " ".join(storage.trigger_sql())
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        assert f"AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED" in triggers
    assert "T2" not in " ".join(storage.function_sql())


def test_promise_recipient_actual_submission_and_all_outcomes_are_fixed():
    sql = storage.REVIEW_ATOM
    assert "promise_cur.version_id,promise_cur.revision" in sql
    assert "task_cur.version_id,task_cur.revision" in sql
    assert "submission.action IS DISTINCT FROM 'submit'" in sql
    assert "submission.actor_id IS DISTINCT FROM v.promisor_id" in sql
    assert "submission.body->'submission' IS DISTINCT FROM task.body->'submission'" in sql
    assert "v.actor_id<>v.recipient_id" in storage.WRITE_ATOM
    assert "count(DISTINCT check_item->>'key')" in sql
    assert "jsonb_array_elements_text(promise.outcome_keys)" in sql
    assert "result_item->>'status'='present'" in sql
    assert "jsonb_array_length(result_item->'sources')>0" in sql
    assert "check_item->>'decision' IN ('rejected','unknown')" in sql
    assert "task.state='completed'" not in sql
    assert "actual_at" not in sql and "promised_at" not in sql
    assert "ARRAY['actor_id','recorded_at']" in sql


def test_history_is_append_only_current_is_single_step_and_fulfilled_is_terminal():
    checks = _checks(storage.TABLES[0])
    assert "previous_revision=revision-1" in checks
    assert "decision='accepted' AND state='fulfilled'" in checks
    assert "decision='returned' AND state='open'" in checks
    assert "OLD.state='open' AND NEW.revision=OLD.revision+1" in storage.CURRENT_GUARD
    assert (
        "v.previous_id=OLD.version_id AND v.previous_revision=OLD.revision" in storage.CURRENT_GUARD
    )
    assert "prior.state IS DISTINCT FROM 'open'" in storage.REVIEW_ATOM
    assert "same-transaction immutable fact" in storage.CURRENT_ATOM
    assert "facts are immutable" in " ".join(storage.function_sql())
    assert not re.search(
        r"\bUPDATE\s+public\.work_(?:task|commitment)_(?:versions|currents)\b",
        " ".join(storage.function_sql()),
        re.I,
    )


def test_project_audience_and_direct_sources_are_preserved_without_ai_dml():
    policy = " ".join(storage.policy_sql())
    for table in storage.TABLES:
        assert f'ALTER TABLE public."{table.name}" FORCE ROW LEVEL SECURITY' in policy
        assert (
            f'REVOKE ALL ON public."{table.name}" FROM PUBLIC,pdos_next_app,pdos_agent,' in policy
        )
    assert "public.projects p" in policy and "p.owner_id=" in policy and "p.visibility=" in policy
    assert "scope_category" not in policy and "object_audiences" not in policy
    assert "TO pdos_agent" not in policy and "FOR DELETE" not in policy
    assert "GRANT UPDATE(version_id,revision,state)" in policy
    sql = storage.WRITE_ATOM
    assert "jsonb_array_elements(v.sources)" in sql
    assert "a.content_hash=basis->>'hash'" in sql
    assert "sec.epoch::text=basis->'original'->>'epoch'" in sql
    assert "r.id::text=basis->'registration'->>'receipt_id'" in sql
    assert "jsonb_array_length(v.source_basis->'artifacts')" not in sql
    assert "a.content" not in sql.replace("a.content_hash", "")


def test_downgrade_refuses_retained_business_and_common_history_before_dropping():
    down = "\n".join(storage.downgrade_sql())
    assert down.startswith("LOCK TABLE")
    assert down.index("downgrade refused") < down.index("DROP TABLE")
    assert "public.confirmations WHERE operation='work.commitment.review'" in down
    assert "subject_type='work_commitment_review'" in down
    assert "DELETE FROM" not in down and "TRUNCATE" not in down
