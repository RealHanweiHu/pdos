"""Compile the actual owner scope query; row audiences remain PostgreSQL RLS."""

import re
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.domain.capa_verification.schemas import OutputRef
from pdos_next.errors import DomainError
from pdos_next.quality_followup_integration import PAIRED_FORMAL_OPERATIONS, request_options
from pdos_next.quality_followup_views import ViewRuntime, configure_output_options

TENANT = UUID("11111111-2222-4333-8444-555555555555")
PRODUCT = UUID("abcdefab-2222-4333-8444-555555555555")
PROJECT = UUID("22222222-3333-4444-8555-666666666666")
ACTOR = UUID("33333333-4444-4555-8666-777777777777")
OTHER = UUID("44444444-5555-4666-8777-888888888888")


class ReadOnlySession:
    """Record actual Select objects only; no connection, writes or fake row filtering."""

    def __init__(self, rows=(), runs=()):
        self.rows = tuple(rows)
        self.runs = tuple(runs)
        self.queries = []

    def scalars(self, query):
        self.queries.append(query)
        return iter(self.rows if len(self.queries) == 1 else self.runs)


@pytest.fixture
def selection():
    return SimpleNamespace(
        ctx=SimpleNamespace(tenant_id=TENANT, requester_id=ACTOR),
        product=PRODUCT,
        basis=SimpleNamespace(
            scope=SimpleNamespace(tenant_id=TENANT, product_id=PRODUCT, project_id=PROJECT)
        ),
    )


def compiled_query(selection):
    session = ReadOnlySession()
    assert request_options(session, selection.ctx, selection.product, selection.basis) == ()
    assert len(session.queries) == 2
    sql = str(
        session.queries[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    return " ".join(sql.lower().split())


def test_real_query_keeps_exact_current_scope_and_reader_visibility(selection):
    sql = compiled_query(selection)
    for equality in (
        "verification_current_formal_requests.tenant_id = verification_formal_requests.tenant_id",
        "verification_current_formal_requests.product_id = verification_formal_requests.product_id",
        "verification_current_formal_requests.request_id = verification_formal_requests.request_id",
        "verification_current_formal_requests.request_version_id = verification_formal_requests.id",
        "verification_current_formal_requests.request_revision = "
        "verification_formal_requests.revision",
    ):
        assert equality in sql
    for column, value in (
        ("tenant_id", TENANT),
        ("product_id", PRODUCT),
        ("project_id", PROJECT),
    ):
        assert f"verification_formal_requests.{column} = '{value}'" in sql
    assert "verification_formal_requests.owner_id =" not in sql
    assert "order by verification_formal_requests.created_at desc" in sql
    assert "limit" not in sql


def test_direct_canonical_receipt_exists_filters_before_order(selection):
    sql = compiled_query(selection)
    exists_at = sql.index("exists (select")
    order_at = sql.index("order by")
    assert exists_at < order_at and "limit" not in sql
    receipt_scope = sql[exists_at:order_at]
    # Test the actual correlated SQL, not whether an in-memory fake would qualify a row.
    for receipt_column, formal_column in (
        ("tenant_id", "tenant_id"),
        ("product_id", "product_id"),
        ("subject_id", "id"),
        ("subject_revision", "revision"),
        ("operation", "operation"),
    ):
        assert (
            f"action_receipts.{receipt_column} = verification_formal_requests.{formal_column}"
            in receipt_scope
        )
    assert "action_receipts.subject_type = 'verification_request'" in receipt_scope
    # JSON id/revision must be bound to this exact row, beyond the Receipt FK fields.
    assert re.search(
        r"action_receipts\.result\s*->>\s*'id'\)?\s*=\s*"
        r"cast\(verification_formal_requests\.id\s+as\s+text\)",
        receipt_scope,
    ), receipt_scope
    assert re.search(
        r"action_receipts\.result(?:\['revision'\]|\s*->\s*'revision')\)?\s*=\s*"
        r"to_jsonb\(verification_formal_requests\.revision\)",
        receipt_scope,
    ), receipt_scope
    assert "to_jsonb" in receipt_scope  # A JSON string revision must not qualify as a number.
    assert "subject_type = 'test_run'" not in receipt_scope


def test_returned_output_refs_use_saved_version_rows_not_logical_request_ids(selection):
    rows = (
        SimpleNamespace(id=OTHER, revision=1, request_id=PROJECT),
        SimpleNamespace(id=ACTOR, revision=7, request_id=TENANT),
    )
    session = ReadOnlySession(rows)
    values = request_options(session, selection.ctx, selection.product, selection.basis)
    assert isinstance(values, tuple)
    assert values == (
        OutputRef(kind="verification_request", id=OTHER, revision=1),
        OutputRef(kind="verification_request", id=ACTOR, revision=7),
    )
    assert all(value.key is None for value in values)
    assert len(session.queries) == 2


def test_empty_verified_selection_returns_no_guessed_historical_or_run_ref(selection):
    session = ReadOnlySession()
    assert request_options(session, selection.ctx, selection.product, selection.basis) == ()
    assert len(session.queries) == 2


def test_real_view_configuration_preserves_explicit_paired_owner_bridge_gap(selection):
    engine = SimpleNamespace()
    missing = (
        (
            "PAIRED_FORMAL_OWNER_PROOF_NOT_CONFIGURED",
            "开测与结果办理派生版尚缺对应owner桥；不能借旧Current。",
        ),
    )
    configure_output_options(engine, request_options, missing=missing)
    runtime = engine._pdos_quality_followup_views
    assert isinstance(runtime, ViewRuntime)
    assert runtime.output_options is request_options
    assert runtime.missing == missing
    session = ReadOnlySession()
    assert runtime.output_options(session, selection.ctx, selection.product, selection.basis) == ()
    assert len(session.queries) == 2
    configure_output_options(engine, request_options)
    assert engine._pdos_quality_followup_views.missing == ()


@pytest.mark.parametrize("field", ["tenant_id", "product_id"])
def test_basis_scope_mismatch_is_rejected_before_even_constructing_a_query(selection, field):
    setattr(selection.basis.scope, field, OTHER)
    session = ReadOnlySession()
    with pytest.raises(DomainError) as failure:
        request_options(session, selection.ctx, selection.product, selection.basis)
    assert failure.value.reason == "FORBIDDEN_SCOPE"
    assert failure.value.status == 403
    assert session.queries == []


def test_actual_run_current_query_binds_every_pointer_and_exact_receipt(selection):
    session = ReadOnlySession()
    request_options(session, selection.ctx, selection.product, selection.basis)
    sql = " ".join(
        str(
            session.queries[1].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        .lower()
        .split()
    )
    for current_column, row_column in (
        ("tenant_id", "tenant_id"),
        ("product_id", "product_id"),
        ("request_id", "request_id"),
        ("run_id", "run_id"),
        ("run_version_id", "id"),
        ("run_revision", "revision"),
    ):
        assert (
            f"verification_current_runs.{current_column} = verification_run_versions.{row_column}"
        ) in sql
    for column, value in (
        ("tenant_id", TENANT),
        ("product_id", PRODUCT),
        ("project_id", PROJECT),
    ):
        assert f"verification_run_versions.{column} = '{value}'" in sql
    assert "verification_run_versions.owner_id =" not in sql
    assert "action_receipts.subject_type = 'test_run'" in sql
    assert "action_receipts.operation = verification_run_versions.operation" in sql
    assert "to_jsonb(verification_run_versions.revision)" in sql
    assert "action_receipts.subject_id = verification_run_versions.id" in sql
    assert "action_receipts.subject_revision = verification_run_versions.revision" in sql
    assert "limit" not in sql


def test_run_options_use_immutable_versions_and_do_not_relabel_formal_rows(selection):
    session = ReadOnlySession(
        (SimpleNamespace(id=OTHER, revision=1),), (SimpleNamespace(id=ACTOR, revision=6),)
    )
    assert request_options(session, selection.ctx, selection.product, selection.basis) == (
        OutputRef(kind="verification_request", id=OTHER, revision=1),
        OutputRef(kind="verification_run", id=ACTOR, revision=6),
    )


def test_combined_owner_scope_never_silently_truncates_the_21st_run(selection):
    session = ReadOnlySession(runs=(SimpleNamespace(id=OTHER, revision=1),) * 21)
    refs = request_options(session, selection.ctx, selection.product, selection.basis)
    assert len(refs) == 21 and all(ref.kind == "verification_run" for ref in refs)


def test_supported_advanced_current_formals_require_the_distinct_owner_family(selection):
    sql = compiled_query(selection)
    assert "or verification_formal_requests.operation in" in sql
    assert PAIRED_FORMAL_OPERATIONS == (
        "verification.schedule.promise",
        "test.run.start",
        "test.results.import",
        "test.run.review",
        "test.disposition.decide",
    )
    for operation in PAIRED_FORMAL_OPERATIONS:
        assert f"'{operation}'" in sql
    assert "'test.run.plan'" not in sql
    assert "'quality.capa.followup.link'" not in sql


def test_current_formal_bound_never_silently_truncates_the_21st_row(selection):
    session = ReadOnlySession(rows=(SimpleNamespace(id=OTHER, revision=1),) * 21)
    refs = request_options(session, selection.ctx, selection.product, selection.basis)
    assert len(refs) == 21 and all(ref.kind == "verification_request" for ref in refs)
