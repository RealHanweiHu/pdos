"""Verification attention query invariants; no Session, DB or business emulator."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import union_all
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, Cast, Label
from sqlalchemy.sql.selectable import Select

from pdos_next import models as registered_models  # noqa: F401 -- standalone model registry
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.personal_attention_verification import queries
from pdos_next.schemas.verification.contracts import Acceptance, Coverage, Measurement


def _compile(value, *, literals=True):
    return value.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": literals})


def _levels(query):
    pending = query.get_final_froms()[0].element
    assignments = pending.get_final_froms()[0].element
    return pending, assignments


def _equal(query, left, right):
    left, right = left.__clause_element__(), right.__clause_element__()
    return any(
        isinstance(node, BinaryExpression)
        and node.operator is operators.eq
        and (
            (node.left.compare(left) and node.right.compare(right))
            or (node.left.compare(right) and node.right.compare(left))
        )
        for node in visitors.iterate(query)
    )


@pytest.fixture
def ctx():
    return SimpleNamespace(tenant_id=uuid4(), requester_id=uuid4())


def test_sources_are_compatible_read_only_metadata_selects(ctx):
    sources = queries(ctx)
    assert isinstance(sources, tuple) and len(sources) == 2
    assert all(isinstance(query, Select) for query in sources)
    assert tuple(sources[0].selected_columns.keys()) == tuple(sources[1].selected_columns.keys())
    compiled = str(_compile(union_all(*sources)))
    assert "UNION ALL" in compiled and "WITH ORDINALITY" in compiled
    assert str(ctx.tenant_id) in compiled and str(ctx.requester_id) in compiled
    assert "FOR UPDATE" not in compiled
    assert all(query._for_update_arg is None for query in sources)
    for query in sources:
        for node in visitors.iterate(query):
            if not isinstance(node, Select):
                continue
            for value in node.selected_columns:
                while isinstance(value, (Label, Cast)):
                    value = value.element if isinstance(value, Label) else value.clause
                assert not value.compare(FormalVerificationRequest.request_snapshot)
                assert not value.compare(VerificationRunVersion.run_snapshot)


@pytest.mark.parametrize("index", [0, 1])
def test_latest_assignment_precedes_person_filter_and_cannot_resurrect_old_owner(ctx, index):
    query = queries(ctx)[index]
    pending, assignments = _levels(query)
    # A later assignment to someone else or to null must suppress this person's
    # earlier entry. Filtering the ranked input by self would resurrect that entry.
    assignment_parameters = _compile(assignments, literals=False).params
    assert str(ctx.requester_id) not in assignment_parameters.values()
    assert ctx.requester_id not in assignment_parameters.values()
    pending_parameters = _compile(pending, literals=False).params
    assert str(ctx.requester_id) in pending_parameters.values()
    assert "last_assignment = 1" in str(_compile(pending))
    other = SimpleNamespace(tenant_id=ctx.tenant_id, requester_id=uuid4())
    assert assignments.compare(_levels(queries(other)[index])[1])

    window = assignments.selected_columns.last_assignment.element
    partition = tuple(window.partition_by)
    assert len(partition) == 4
    assert "tenant_id" in str(partition[0])
    assert ("request_id" if index == 0 else "run_id") in str(partition[1])
    assert "sample_id" in str(_compile(partition[2]))
    assert "item_id" in str(_compile(partition[3]))
    assert len(tuple(window.order_by)) == 1
    assert str(tuple(window.order_by)[0]).endswith(".position DESC")


@pytest.mark.parametrize("index", [0, 1])
def test_source_identity_and_count_are_stable_across_revision_and_queue(ctx, index):
    query = queries(ctx)[index]
    pending, assignments = _levels(query)
    expected_kind = "verification_handoff_return" if index == 0 else "verification_result_return"
    key = str(_compile(query.selected_columns.key))
    assert f"'{expected_kind}:'" in key
    assert ".source_id" in key and ".revision" not in key and ".queue" not in key
    assert str(_compile(query.selected_columns.kind)).startswith(f"CAST('{expected_kind}'")
    assert "'receive'" in str(_compile(query.selected_columns.queue))
    assert "'named_return_owner'" in str(_compile(query.selected_columns.responsibility))
    assert "'project'" in str(_compile(query.selected_columns.target))
    for name in ("epoch", "due_at", "valid_until", "owner_id", "visibility"):
        assert "CAST(NULL AS" in str(_compile(query.selected_columns[name]))
    # Multiple unresolved pairs are one source-stage item, not separate claims.
    assert "count(*)" in str(_compile(pending.selected_columns.coverage_count))
    assert {column.key for column in pending._group_by_clauses} == {
        column.key for column in assignments.selected_columns
    } - {"next_owner", "last_assignment"}
    details = str(_compile(query.selected_columns.details))
    assert "coverage_count" in details and "build_id" in details
    assert "request_snapshot" not in details and "run_snapshot" not in details


def test_handoff_uses_exact_current_request_and_cumulative_actual_acceptances(ctx):
    query = queries(ctx)[0]
    request, current = FormalVerificationRequest, FormalVerificationCurrent
    for name in ("tenant_id", "category_id", "product_id", "request_id"):
        assert _equal(query, getattr(current, name), getattr(request, name))
    assert _equal(query, current.request_version_id, request.id)
    assert _equal(query, current.request_revision, request.revision)
    sql = str(_compile(query))
    assert "status IN ('offered', 'accepted', 'scheduled', 'executing')" in sql
    assert "request_snapshot['offered_coverage']" in sql
    assert "NOT (EXISTS" in sql and "request_snapshot['acceptances']" in sql
    assert "handoff_accepted.value['coverage']" in sql
    assert "handoff_accepted_coverage.value ->> 'sample_id'" in sql
    assert "handoff_accepted_coverage.value ->> 'item_id'" in sql
    assert "request_snapshot['returns']" in sql


def test_results_use_exact_current_run_and_separate_current_request(ctx):
    query = queries(ctx)[1]
    run, current = VerificationRunVersion, VerificationRunCurrent
    request, request_current = FormalVerificationRequest, FormalVerificationCurrent
    for name in ("tenant_id", "category_id", "product_id", "request_id", "run_id"):
        assert _equal(query, getattr(current, name), getattr(run, name))
    assert _equal(query, current.run_version_id, run.id)
    assert _equal(query, current.run_revision, run.revision)
    for name in ("tenant_id", "category_id", "product_id", "request_id"):
        assert _equal(query, getattr(request_current, name), getattr(run, name))
    assert _equal(query, request.id, request_current.request_version_id)
    assert _equal(query, request.revision, request_current.request_revision)
    assert _equal(query, request.project_id, run.project_id)
    assert _equal(query, request.build_id, run.build_id)
    # The Run retains its originating request version as that Request advances.
    assert not _equal(query, run.request_version_id, request.id)
    sql = str(_compile(query))
    assert "verification_run_versions.status = 'running'" in sql
    assert "verification_formal_requests.status != 'disposed'" in sql


def test_missing_measurement_is_not_a_pass_or_result_state_predicate(ctx):
    # Frozen source schema: acceptance coverage is an array; each measurement
    # has one coverage object. Expanding the latter as an array would fail on PG.
    assert Acceptance.model_fields["coverage"].annotation == tuple[Coverage, ...]
    assert Measurement.model_fields["coverage"].annotation is Coverage
    sql = str(_compile(queries(ctx)[1]))
    assert "run_snapshot['partial_returns']" in sql and "value['pending_coverage']" in sql
    assert "run_snapshot['coverage']" in sql and "run_snapshot['measurements']" in sql
    assert "NOT (EXISTS" in sql
    assert "results_measurement.value['coverage']" in sql
    assert "((results_measurement.value['coverage']) ->> 'sample_id')" in sql
    assert "((results_measurement.value['coverage']) ->> 'item_id')" in sql
    assert "jsonb_typeof(results_measurement.value['coverage'])" not in sql
    assert "computed_results" not in sql and "'pass'" not in sql and "'failed'" not in sql


@pytest.mark.parametrize("index", [0, 1])
def test_absent_return_arrays_or_named_owner_never_supply_an_inferred_assignment(ctx, index):
    sql = str(_compile(queries(ctx)[index]))
    assert "CASE WHEN (jsonb_typeof(" in sql and "ELSE CAST('[]' AS JSONB)" in sql
    assert "value ->> 'next_owner_id'" in sql
    assert "coalesce" not in sql.lower()
    assert "professional" not in sql and "owner_id =" not in sql
    assert "transaction_timestamp" not in sql
