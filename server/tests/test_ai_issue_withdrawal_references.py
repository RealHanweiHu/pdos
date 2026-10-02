"""Pure SQL-contract and orchestration checks; no database or model execution."""

import json
import re
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import JSON, Column, ForeignKey, Table, Uuid
from sqlalchemy.dialects.postgresql import dialect

from app.db.schema import metadata, tables
from app.domain import ai_issue_withdrawal_references as guard


def application() -> dict[str, Any]:
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "project_id": uuid4(),
        "issue_id": uuid4(),
        "created_at": datetime.now(UTC),
        "issue_event_row_id": 71,
        "output_event_row_id": 73,
        "receipt": MappingProxyType({"source_case_after": {"id": str(uuid4())}}),
    }


def queries(app: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    return guard._queries(app["tenant_id"], app["project_id"], app["issue_id"], app)


def sql(statement: Any) -> str:
    return str(statement.compile(dialect=dialect()))  # type: ignore[no-untyped-call]


def call(c: Any, app: dict[str, Any]) -> str | None:
    return guard.withdrawal_reference(c, app["tenant_id"], app["project_id"], app["issue_id"], app)


def test_all_issue_foreign_keys_are_probed_including_historical_and_fmea() -> None:
    exact, _ = queries(application())
    compiled = [sql(item) for item in exact]
    for table in metadata.tables.values():
        for fk in table.foreign_key_constraints:
            if fk.referred_table is not tables.issues:
                continue
            assert any(
                all(str(element.parent) in text for element in fk.elements) for text in compiled
            )
    for name in ("quality_issue_links", "fmea_revision_candidates", "issue_intake_corrections"):
        assert any(getattr(tables, name).fullname in text for text in compiled)


def test_scope_and_exclusions_are_exact_not_timestamp_or_origin_based() -> None:
    app = application()
    for t in (tables.events, tables.audit_log, tables.ai_issue_applications, tables.test_cases):
        clauses = guard._exclusions(t, app["tenant_id"], app["project_id"], app["issue_id"], app)
        text = " ".join(sql(clause) for clause in clauses)
        assert "origin" not in text
        assert "created_at" not in text
        if t is tables.audit_log:
            assert "cehub_event.events.id IN" in text
            assert "cehub_event.events.tenant_id =" in text
            assert "cehub_event.events.project_id =" in text
            assert "cehub_audit.audit_log.event_id IS NULL" in text
        if t is tables.events:
            assert clauses[0].right.value == [71, 73]
        if t is tables.test_cases:
            assert str(clauses[0].right.value) == app["receipt"]["source_case_after"]["id"]
    assert not guard._exclusions(
        tables.ai_issue_withdrawal_receipts,
        app["tenant_id"],
        app["project_id"],
        app["issue_id"],
        app,
    )


def test_all_tenant_json_and_unbound_identities_have_scoped_probes() -> None:
    _, uncertain = queries(application())
    compiled = [sql(item) for item in uncertain]
    for t in metadata.tables.values():
        if "tenant_id" not in t.c:
            continue
        for col in t.c:
            if isinstance(col.type, JSON):
                matches = [text for text in compiled if f"CAST({sql(col)}" in text]
                assert matches, str(col)
                assert all(f"{t.fullname}.tenant_id =" in text for text in matches)
                if "project_id" in t.c and t is not tables.audit_log:
                    # Consumer project is not necessarily the source project.
                    assert all(f"{t.fullname}.project_id =" not in text for text in matches)
    # Formal history and output mirrors are protected, not treated as own output.
    assert any("ai_issue_withdrawal_receipts.items" in text for text in compiled)
    assert any("gate" in text for text in compiled)


def test_future_metadata_reference_is_not_silently_missed() -> None:
    t = Table(
        "withdrawal_guard_test_reference",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid),
        Column("project_id", Uuid),
        Column("issue_id", Uuid, ForeignKey("cehub_project.issues.id")),
        Column("snapshot", JSON),
        schema="cehub_project",
    )
    try:
        exact, uncertain = queries(application())
        assert any(t.fullname in sql(item) for item in exact)
        assert any(t.fullname in sql(item) for item in uncertain)
    finally:
        metadata.remove(t)


def test_exact_json_identity_does_not_match_other_ids_or_arbitrary_activity() -> None:
    app = application()
    _, uncertain = queries(app)
    patterns = [
        value
        for item in uncertain
        for value in item.compile().params.values()
        if isinstance(value, str) and value.startswith('"(?:issue:)?')
    ]
    assert patterns
    pattern = patterns[0]
    identity = str(app["issue_id"])
    for value in (
        {"id": identity},
        {identity: "snapshot"},
        {"source_key": f"issue:{identity}"},
        {"created_issue": {"id": identity.upper()}},
    ):
        assert re.search(pattern, json.dumps(value), re.I)
    for value in (
        {"id": str(uuid4())},
        {"title": "later project activity"},
        {"id": identity + "0"},
    ):
        assert not re.search(pattern, json.dumps(value), re.I)


def test_no_reference_checks_every_batch_without_record_truncation() -> None:
    app, c = application(), MagicMock()
    c.execute.return_value.scalar_one_or_none.return_value = None
    exact, uncertain = queries(app)
    assert call(c, app) is None
    assert c.execute.call_count == sum(
        (len(group) + guard._BATCH_SIZE - 1) // guard._BATCH_SIZE for group in (exact, uncertain)
    )
    for invocation in c.execute.call_args_list:
        text = sql(invocation.args[0])
        assert text.count("LIMIT") == 1  # Limit output reasons, never source rows.
        assert "OFFSET" not in text


@pytest.mark.parametrize(
    "reason", [guard.BUSINESS_REFERENCE, guard.UNCLASSIFIED_REFERENCE, guard.SCOPE_UNKNOWN]
)
def test_blocking_reason_is_stable_and_contains_no_private_record(reason: str) -> None:
    app, c = application(), MagicMock()
    c.execute.return_value.scalar_one_or_none.return_value = reason
    assert call(c, app) == reason
    assert c.execute.call_count == 1


def test_incomplete_database_read_propagates_and_cannot_clear_withdrawal() -> None:
    c = MagicMock()
    c.execute.side_effect = RuntimeError("read unavailable")
    with pytest.raises(RuntimeError, match="read unavailable"):
        call(c, application())


def test_wrong_application_binding_fails_without_query() -> None:
    app, c = application(), MagicMock()
    assert (
        guard.withdrawal_reference(c, uuid4(), app["project_id"], app["issue_id"], app)
        == guard.SCOPE_UNKNOWN
    )
    c.execute.assert_not_called()


def test_known_contracts_and_actual_test_execution_path_are_present() -> None:
    exact, _ = queries(application())
    text = "\n".join(sql(item) for item in exact)
    for marker in (
        "meeting_agenda_items.source_entity_id",
        "knowledge_candidate_jobs.source_id",
        "test_runs.test_case_id",
        "test_cases.related_issue_id",
        "fmea_versions.body",
        "change_impact_scope_versions.snapshot",
        "decisions.evidence_refs",
    ):
        assert marker in text
    assert "@>" in text


def test_source_test_run_predicate_preserves_preexisting_upstream_history() -> None:
    app = application()
    exact, _ = queries(app)
    query = next(item for item in exact if "cehub_quality.test_runs" in sql(item))
    text = sql(query)
    assert "test_runs.created_at >" in text
    assert "test_runs.updated_at >" in text
    assert "test_runs.test_case_id !=" in text
    assert app["created_at"] in query.compile().params.values()
    assert app["receipt"]["source_case_after"]["id"] in {
        str(value) for value in query.compile().params.values()
    }


def test_unknown_reference_in_last_batch_cannot_be_skipped() -> None:
    app, c = application(), MagicMock()
    exact, uncertain = queries(app)
    count = sum(
        (len(group) + guard._BATCH_SIZE - 1) // guard._BATCH_SIZE for group in (exact, uncertain)
    )
    c.execute.return_value.scalar_one_or_none.side_effect = [None] * (count - 1) + [
        guard.UNCLASSIFIED_REFERENCE
    ]
    assert call(c, app) == guard.UNCLASSIFIED_REFERENCE
    assert c.execute.call_count == count


def test_issue_fk_scope_comes_from_real_target_not_consumer_project() -> None:
    app = application()
    exact, _ = queries(app)
    decision_fk = next(item for item in exact if "cehub_project.decisions.issue_id =" in sql(item))
    compiled = sql(decision_fk)
    assert "cehub_project.decisions.tenant_id =" in compiled
    assert "cehub_project.decisions.project_id =" not in compiled
    assert app["issue_id"] in decision_fk.compile().params.values()
    own_scope_fk = next(
        item for item in exact if "cehub_cost.cost_gap_cases.issue_id =" in sql(item)
    )
    assert "cehub_cost.cost_gap_cases.project_id =" in sql(own_scope_fk)


def test_cross_project_json_projection_checks_exact_issue_within_tenant() -> None:
    app = application()
    _, uncertain = queries(app)
    for table in (
        tables.supply_share_grants,
        tables.cross_project_schedule_proposals,
        tables.project_intake_proposals,
    ):
        probe = next(item for item in uncertain if f"CAST({table.fullname}." in sql(item))
        compiled = sql(probe)
        assert f"{table.fullname}.tenant_id =" in compiled
        for column in (
            "project_id",
            "recipient_project_id",
            "source_project_id",
            "predecessor_project_id",
            "successor_project_id",
        ):
            assert f"{table.fullname}.{column} =" not in compiled
        assert any(str(app["issue_id"]) in str(value) for value in probe.compile().params.values())
