"""Exact request-local bridge reuse; all database/object IO is an explicit seam."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import Session
from verification_results.test_pure import execute, import_payload, report
from verification_results.test_pure import work as result_work

from pdos_next import quality_result_bridge as bridge
from pdos_next import service as common
from pdos_next.contracts import Command
from pdos_next.domain.verification_front.adapters import METHOD_POSITION, professional_documents
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_results import service as results
from pdos_next.domain.verification_results.models import (
    MeasurementImportCapture,
    MeasurementRecord,
)
from pdos_next.domain.verification_results.models import TestResultProjection as ResultProjection
from pdos_next.errors import DomainError
from pdos_next.models import Category, Grant, Outbox, Principal, Product, Receipt
from pdos_next.request_proof import request_proof
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import EVENTS, Context, digest


@pytest.fixture
def archive(monkeypatch):
    seed = result_work.__wrapped__()
    content, binding, _, measurements = report(seed, ("3", "4"))
    seed.proved = [measurement.id for measurement in measurements]
    execute(seed, import_payload(seed, measurements, True), "test.results.import")
    run, plan, scope = seed.run, seed.plan, seed.run.scope
    # The front IO seam represents the precise archived request revision selected
    # by the Run, independently of the current request pointer.
    request = seed.request.model_copy(
        update={
            "revision": run.request_revision,
            "status": "accepted",
            "documents": professional_documents(
                seed.request.items,
                seed.request.documents,
                {
                    item.id: SourceRef(
                        id=uuid4(), revision=1, kind="domain", position=METHOD_POSITION
                    )
                    for item in seed.request.items
                },
            ),
            "timeline": seed.request.timeline.model_copy(
                update={
                    "promised_start": None,
                    "actual_start": None,
                    "preliminary_result": None,
                    "final_result": None,
                    "disposed": None,
                }
            ),
        }
    )
    reads = [{"artifact_id": str(binding.report.id), "expected_revision": 1}]
    common = dict(
        tenant_id=scope.tenant_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        build_id=run.build.id,
        build_revision=run.build.revision,
        request_id=run.request_id,
        revision=run.revision,
        visibility="private",
        owner_id=seed.actor,
        sources=[],
        required_source_read_set=reads,
    )
    row = SimpleNamespace(
        **common,
        id=uuid4(),
        run_id=run.id,
        request_revision=run.request_revision,
        status=run.status,
        run_snapshot=run.model_dump(mode="json"),
        snapshot_sha256=digest(run.model_dump(mode="json")),
        execution_plan=plan.model_dump(mode="json"),
        plan_sha256=digest(plan.model_dump(mode="json")),
    )
    request_row = SimpleNamespace(
        **{**common, "revision": request.revision},
        id=uuid4(),
        status=request.status,
        operation="verification.handoff.accept",
        request_snapshot=request.model_dump(mode="json"),
        snapshot_sha256=digest(request.model_dump(mode="json")),
    )
    projected = {attribute.key: None for attribute in ResultProjection.__mapper__.column_attrs}
    projected.update(
        **{key: value for key, value in common.items() if key in projected and key != "revision"},
        revision=1,
        id=uuid4(),
        run_id=run.id,
        status="computed",
        run_version_id=row.id,
        run_revision=row.revision,
        run_sha256=row.snapshot_sha256,
        basis_sha256=results._basis_sha(run, plan),
        rules_version=results.RULES_VERSION,
        rules_sha256=results.RULES_SHA256,
        input_snapshot=results._projection_basis(run, plan),
        result=run.result,
        computed_results=[value.model_dump(mode="json") for value in run.computed_results],
        source_basis={},
    )
    projection = ResultProjection(**projected)
    capture = SimpleNamespace(id=uuid4())
    records = [
        SimpleNamespace(
            id=measurement.id,
            capture_id=capture.id,
            run_id=run.id,
            request_id=run.request_id,
            build_id=run.build.id,
            project_id=scope.project_id,
            measurement=measurement.model_dump(mode="json"),
            measurement_sha256=digest(measurement.model_dump(mode="json")),
            verified_observation=bridge.verify_measurement(
                content, binding, measurement, run
            ).model_dump(mode="json"),
            sources=[],
            required_source_read_set=reads,
        )
        for measurement in measurements
    ]
    operation = "test.result.compute"
    receipt = SimpleNamespace(
        id=uuid4(),
        tenant_id=scope.tenant_id,
        product_id=scope.product_id,
        operation=operation,
        subject_type="test_result_projection",
        subject_id=projection.id,
        subject_revision=projection.revision,
        actor_id=seed.actor,
        command_id=uuid4(),
    )
    event = SimpleNamespace(
        id=uuid4(),
        receipt_id=receipt.id,
        type=EVENTS[operation],
        subject_id=receipt.subject_id,
        subject_revision=receipt.subject_revision,
        actor_id=receipt.actor_id,
        correlation_id=receipt.command_id,
        schema_version=1,
    )
    state = SimpleNamespace(
        runtime="runtime-1",
        caller="consumer-1",
        expired=False,
        source_current=True,
        basis={},
        after_bytes=None,
        retained_calls=[],
        byte_calls=[],
        event_calls=[],
        scalar_calls=[],
        rows_calls=[],
        content=content,
        retained={
            "current": True,
            "reason_codes": [],
            "required_source_read_set": reads,
            "source_nature": "synthetic",
            "execution": "immutable-retained-execution",
        },
    )

    def scalar(query):
        model = query.column_descriptions[0]["entity"]
        params = query.compile().params
        state.scalar_calls.append((model, dict(params)))
        if model is Outbox:
            return event if params["id_1"] == event.id else None
        if model is Receipt:
            return receipt if params["id_1"] == receipt.id else None
        if model is MeasurementImportCapture:
            return capture if params["id_1"] == capture.id else None
        if model is ResultProjection:
            return projection.id if params["basis_sha256_1"] == projection.basis_sha256 else None
        raise AssertionError(model)

    def scalars(query):
        model = query.column_descriptions[0]["entity"]
        params = query.compile().params
        state.rows_calls.append((model, dict(params)))
        assert model is MeasurementRecord
        assert params["tenant_id_1"] == scope.tenant_id
        assert params["product_id_1"] == scope.product_id
        assert params["run_id_1"] == run.id
        assert set(params["id_1"]) == {measurement.id for measurement in run.measurements}
        return records

    def human(*_args, **_kwargs):
        return None

    def caller(*_args, **_kwargs):
        if state.expired:
            raise DomainError("FORBIDDEN_SCOPE", "Current consumer expired", 403)
        return state.caller, None

    def retained(*_args, **kwargs):
        state.retained_calls.append(kwargs["write"])
        return deepcopy(state.retained)

    def report_bytes(*_args):
        state.byte_calls.append(capture.id)
        if state.after_bytes:
            state.after_bytes()
        return state.content, binding

    def load(_s, _ctx, _pid, model, identity):
        if model is ResultProjection and identity == projection.id:
            return projection
        if model is VerificationRunVersion and identity == row.id:
            return row
        raise DomainError("FORBIDDEN_SCOPE", "Wrong archived row", 403)

    real_event = bridge._event_run

    def select_event(*args):
        state.event_calls.append(args[-1])
        return real_event(*args)

    monkeypatch.setattr(bridge.launch, "_human", human)
    monkeypatch.setattr(bridge.launch, "_row", load)
    monkeypatch.setattr(bridge.launch, "_version", lambda *_: row)
    monkeypatch.setattr(bridge.results, "_row", load)
    monkeypatch.setattr(bridge.front, "_version", lambda *_: request_row)
    monkeypatch.setattr(
        bridge.launch, "_read_evidence", lambda *_: "current" if state.source_current else "stale"
    )
    monkeypatch.setattr(bridge, "_runtime_stamp", lambda *_: state.runtime)
    monkeypatch.setattr(bridge, "retained_caller", caller)
    monkeypatch.setattr(bridge, "inspect_retained_execution", retained)
    monkeypatch.setattr(bridge, "_event_run", select_event)
    monkeypatch.setattr(results, "_report_for_capture", report_bytes)
    monkeypatch.setattr(bridge.physical, "_basis", lambda *_: (deepcopy(state.basis), False))
    with Session() as session:
        session.begin()
        session.info.update(
            read_snapshot=True, scope=(scope.tenant_id, seed.actor, seed.actor, None)
        )
        monkeypatch.setattr(session, "scalar", scalar)
        monkeypatch.setattr(session, "scalars", scalars)
        value = SimpleNamespace(
            session=session,
            ctx=Context(scope.tenant_id, seed.actor, seed.actor),
            product_id=scope.product_id,
            run=run,
            plan=plan,
            row=row,
            request_row=request_row,
            projection=projection,
            event=event,
            receipt=receipt,
            records=records,
            capture=capture,
            state=state,
        )
        try:
            yield value
        finally:
            session.rollback()


def select(archive, index=0, *, write=False, event=True, measurement_id=None):
    return bridge.fixed_failure_result(
        archive.session,
        archive.ctx,
        archive.product_id,
        run_id=archive.run.id,
        measurement_id=measurement_id or archive.records[index].id,
        event_id=archive.event.id if event else None,
        run_revision=archive.row.revision,
        write=write,
    )


def hold_command_gate(archive, monkeypatch, *, product_id=None, category_only=False):
    """Run the actual common gate; only database responses use explicit IO seams."""
    category_id = archive.ctx.category_id or uuid4()
    archive.ctx = replace(archive.ctx, category_id=category_id)
    archive.session.info["scope"] = (
        archive.ctx.tenant_id,
        archive.ctx.actor_id,
        archive.ctx.requester_id,
        category_id,
    )
    product = Product(
        id=product_id or archive.product_id,
        tenant_id=archive.ctx.tenant_id,
        category_id=category_id,
        owner_id=archive.ctx.requester_id,
        name="Synthetic model gate",
        purpose="Exact bridge writer gate",
        revision=1,
        lifecycle_epoch=1,
        status="draft",
        visibility="category",
    )
    category = Category(
        id=category_id,
        tenant_id=archive.ctx.tenant_id,
        owner_id=archive.ctx.requester_id,
        name="Synthetic category gate",
        purpose="Category-only gate is insufficient for a model",
        revision=1,
        lifecycle_epoch=1,
    )
    principal = Principal(
        id=archive.ctx.requester_id,
        tenant_id=archive.ctx.tenant_id,
        name="Synthetic writer",
        kind="human",
        active=True,
        access_epoch=1,
    )
    grant = Grant(
        id=uuid4(),
        tenant_id=archive.ctx.tenant_id,
        category_id=category_id,
        principal_id=principal.id,
        can_write=True,
        expires_at=None,
        access_epoch=1,
    )
    command = Command(
        command_id=uuid4(),
        idempotency_key="pure-common-gate",
        category_id=category_id,
        product_id=None if category_only else product.id,
        expected_revision=1,
        operation="evidence.artifact.register" if category_only else "quality.issue.create",
        payload={},
    )
    original_scalar = archive.session.scalar
    gates = []

    def get(model, identity):
        values = {Product: product, Category: category, Principal: principal}
        row = values[model]
        assert row.id == identity
        return row

    def execute(query):
        assert query.column_descriptions[0]["entity"] is Principal
        assert query.column_descriptions[1]["entity"] is Grant
        assert query._for_update_arg is not None and query._for_update_arg.read
        return SimpleNamespace(all=lambda: [(principal, grant)])

    def scalar(query):
        model = query.column_descriptions[0]["entity"]
        if model in {Product, Category}:
            row = product if model is Product else category
            assert query.compile().params["id_1"] == row.id
            assert query._for_update_arg is not None and not query._for_update_arg.read
            gates.append((model, row.id))
            return row
        return original_scalar(query)

    with monkeypatch.context() as io:
        io.setattr(archive.session, "get", get)
        io.setattr(archive.session, "execute", execute)
        io.setattr(archive.session, "scalar", scalar)
        held = common.command_scope(archive.session, archive.ctx, command, lock=True)
    assert gates == ([(Category, category_id)] if category_only else [(Product, product.id)])
    assert held.category_id == category_id
    return held


def test_same_precise_run_reuses_only_initial_retained_and_rechecks_bytes_and_owner(archive):
    first, second = select(archive), select(archive, 1)
    assert first.measurement_id != second.measurement_id
    assert first.verified.run == second.verified.run == archive.run
    assert first.current and second.current
    assert archive.state.retained_calls == [False, False, False]
    assert archive.state.byte_calls == [archive.capture.id, archive.capture.id]
    assert archive.state.event_calls == [archive.event.id, archive.event.id]
    assert len(archive.state.rows_calls) == 1
    assert (
        len([call for call in archive.state.scalar_calls if call[0] is MeasurementImportCapture])
        == 1
    )
    bridge.recheck_fixed_failure_result(archive.session, archive.ctx, archive.product_id, first)
    assert archive.state.retained_calls == [False] * 4
    assert archive.state.event_calls == [archive.event.id] * 3
    assert archive.state.byte_calls == [archive.capture.id] * 2


def test_exact_archived_version_without_event_resolves_real_projection_before_reuse(archive):
    select(archive)
    value = select(archive, 1, event=False)
    assert value.event_id is None and value.projection_id == archive.projection.id
    assert archive.state.retained_calls == [False] * 3
    assert len([call for call in archive.state.scalar_calls if call[0] is ResultProjection]) == 1
    assert archive.state.byte_calls == [archive.capture.id] * 2


@pytest.mark.parametrize("mode", ["writer", "ordinary"])
def test_writer_and_non_snapshot_keep_full_initial_and_terminal_retained(archive, mode):
    archive.session.info["read_snapshot"] = mode != "ordinary"
    select(archive, write=mode == "writer")
    select(archive, 1, write=mode == "writer")
    assert archive.state.retained_calls == [mode == "writer"] * 4
    assert archive.state.byte_calls == [archive.capture.id] * 2
    if mode == "ordinary":
        assert len(archive.state.rows_calls) == 2


@pytest.mark.parametrize("change", ["retained", "runtime", "source", "bytes"])
def test_prepared_run_cannot_survive_external_changes_during_next_byte_read(archive, change):
    select(archive)

    def change_during_read():
        if change == "retained":
            archive.state.retained["current"] = False
        elif change == "runtime":
            archive.state.runtime = "runtime-2"
        elif change == "source":
            archive.state.basis = {"different": "current-source"}
        else:
            archive.state.content = archive.state.content.replace(b'"3"', b'"9"', 1)

    archive.state.after_bytes = change_during_read
    with pytest.raises(DomainError) as error:
        select(archive, 1)
    assert error.value.reason == ("REPORT_HASH_MISMATCH" if change == "bytes" else "SOURCE_STALE")
    assert archive.state.byte_calls == [archive.capture.id] * 2


@pytest.mark.parametrize(
    "change,reason",
    [
        ("caller", "FORBIDDEN_SCOPE"),
        ("event", "FAILURE_EVENT_UNAVAILABLE"),
        ("selected", "FAILURE_CONTEXT_MISSING"),
        ("measurement", "INTEGRITY_MISMATCH"),
        ("projection", "RESULT_BASIS_CHANGED"),
        ("read_evidence", "SOURCE_STALE"),
    ],
)
def test_each_selection_keeps_current_consumer_and_exact_fact_guards(archive, change, reason):
    select(archive)
    measurement_id = None
    if change == "caller":
        archive.state.expired = True
    elif change == "event":
        archive.event.schema_version = 2
    elif change == "selected":
        measurement_id = uuid4()
    elif change == "measurement":
        archive.records[0].measurement_sha256 = "0" * 64
    elif change == "projection":
        archive.projection.rules_sha256 = "0" * 64
    else:
        archive.state.source_current = False
    with pytest.raises(DomainError) as error:
        select(archive, 1, measurement_id=measurement_id)
    assert error.value.reason == reason


@pytest.mark.parametrize(
    "boundary",
    ["runtime", "caller", "ctx", "scope", "run", "request", "projection", "epoch", "transaction"],
)
def test_prepared_basis_is_bound_to_complete_actual_context_and_transaction(archive, boundary):
    select(archive)
    ctx = archive.ctx
    if boundary == "runtime":
        archive.state.runtime = "runtime-2"
    elif boundary == "caller":
        archive.state.caller = "consumer-2"
    elif boundary == "ctx":
        ctx = replace(ctx, requester_id=uuid4())
    elif boundary == "scope":
        archive.session.info["scope"] = (
            archive.ctx.tenant_id,
            archive.ctx.actor_id,
            archive.ctx.requester_id,
            uuid4(),
        )
    elif boundary == "run":
        archive.row.id = uuid4()
    elif boundary == "request":
        archive.request_row.snapshot_sha256 = "1" * 64
    elif boundary == "projection":
        archive.projection.revision += 1
    elif boundary == "epoch":
        request_proof(archive.session).mutation_epoch += 1
    else:
        archive.session.rollback()
        archive.session.begin()
    context = bridge._prepare_context(
        archive.session,
        ctx,
        archive.product_id,
        archive.row,
        archive.run,
        archive.plan,
        archive.request_row,
        archive.state.runtime,
        write=False,
    )
    prepared, _ = bridge._prepared_retained(
        archive.session,
        ctx,
        archive.product_id,
        archive.run,
        archive.projection.basis_sha256,
        archive.projection,
        context,
    )
    assert prepared is None


def test_raw_capture_query_keeps_exact_parent_and_missing_capture_guard(archive):
    select(archive)
    foreign = deepcopy(archive.records[0])
    foreign.capture_id = uuid4()
    with pytest.raises(DomainError) as error:
        results._measurement_capture(archive.session, archive.ctx, archive.product_id, foreign)
    assert error.value.reason == "INTEGRITY_MISMATCH"
    calls = [
        params for model, params in archive.state.scalar_calls if model is MeasurementImportCapture
    ]
    assert len(calls) == 2 and calls[0]["id_1"] != calls[1]["id_1"]
    for params in calls:
        assert params["tenant_id_1"] == archive.ctx.tenant_id
        assert params["product_id_1"] == archive.product_id
        assert params["run_id_1"] == archive.run.id
        assert params["request_id_1"] == archive.run.request_id
        assert params["build_id_1"] == archive.run.build.id
        assert params["project_id_1"] == archive.run.scope.project_id


def test_session_like_header_cannot_create_prepared_proof(archive):
    fake = SimpleNamespace(info={"read_snapshot": True}, in_transaction=lambda: True)
    assert (
        bridge._prepare_context(
            fake,
            archive.ctx,
            archive.product_id,
            archive.row,
            archive.run,
            archive.plan,
            archive.request_row,
            archive.state.runtime,
            write=False,
        )
        is None
    )


def test_real_orm_projection_seals_every_mapped_field_except_db_derived_rls_column(archive):
    mapper = ResultProjection.__mapper__
    mapped_columns = {column for attribute in mapper.column_attrs for column in attribute.columns}
    unmapped_columns = set(ResultProjection.__table__.columns) - mapped_columns
    assert {column.key for column in unmapped_columns} == {"audience_dependencies"}
    assert isinstance(archive.projection, ResultProjection)
    before = bridge._prepared_key(("actual-projection",), archive.projection)
    values = {
        attribute.key: getattr(archive.projection, attribute.key)
        for attribute in mapper.column_attrs
    }
    assert len(values) == len(ResultProjection.__table__.columns) - 1
    assert before[-1] == digest(values)
    for attribute in mapper.column_attrs:
        original = values[attribute.key]
        try:
            setattr(archive.projection, attribute.key, None if original is not None else "changed")
            after = bridge._prepared_key(("actual-projection",), archive.projection)
            assert before != after, attribute.key
        finally:
            setattr(archive.projection, attribute.key, original)


def test_writer_actual_common_model_gate_shares_raw_rows_and_keeps_all_retained_and_bytes(
    archive, monkeypatch
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    first = select(archive, write=True)
    second = select(archive, 1, write=True)
    bridge.recheck_fixed_failure_result(
        archive.session, archive.ctx, archive.product_id, first, write=True
    )
    assert second.measurement_id != first.measurement_id
    assert archive.state.retained_calls == [True] * 5
    assert archive.state.byte_calls == [archive.capture.id] * 2
    assert archive.state.event_calls == [archive.event.id] * 3
    assert len(archive.state.rows_calls) == 1
    for model in (Outbox, Receipt, MeasurementImportCapture):
        assert len([call for call in archive.state.scalar_calls if call[0] is model]) == 1
    assert not any(
        key[0] == "quality-prepared-run" for key in request_proof(archive.session).scalar_rows
    )


@pytest.mark.parametrize("gate", ["unheld", "wrong_product", "category_only"])
def test_writer_raw_rows_are_not_shared_without_the_same_actual_model_gate(
    archive, monkeypatch, gate
):
    archive.session.info["read_snapshot"] = False
    if gate == "wrong_product":
        hold_command_gate(archive, monkeypatch, product_id=uuid4())
    elif gate == "category_only":
        hold_command_gate(archive, monkeypatch, category_only=True)
    select(archive, write=True)
    select(archive, 1, write=True)
    assert archive.state.retained_calls == [True] * 4
    assert archive.state.byte_calls == [archive.capture.id] * 2
    assert len(archive.state.rows_calls) == 2
    for model in (Outbox, Receipt):
        assert len([call for call in archive.state.scalar_calls if call[0] is model]) == 2


@pytest.mark.parametrize("field", ["tenant_id", "actor_id", "requester_id", "category_id"])
def test_writer_held_rows_cannot_borrow_a_different_transaction_identity(
    archive, monkeypatch, field
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    select(archive, write=True)
    archive.ctx = replace(archive.ctx, **{field: uuid4()})
    with pytest.raises(DomainError) as error:
        select(archive, 1, write=True)
    assert error.value.reason == "FORBIDDEN_SCOPE"
    assert archive.state.byte_calls == [archive.capture.id]
    assert len(archive.state.rows_calls) == 1


@pytest.mark.parametrize("boundary", ["mutation", "rollback", "new_transaction"])
def test_writer_raw_sharing_is_discarded_by_actual_session_mutation_or_transaction_boundary(
    archive, monkeypatch, boundary
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    select(archive, write=True)
    previous = request_proof(archive.session)
    epoch = previous.mutation_epoch
    if boundary == "mutation":
        # The real ORM mutation event invalidates proof before an unbound Session
        # reaches the explicit no-database IO boundary.
        with pytest.raises(UnboundExecutionError):
            archive.session.execute(
                update(Product).where(Product.id == archive.product_id).values(revision=2)
            )
        assert request_proof(archive.session).mutation_epoch == epoch + 1
    else:
        if boundary == "rollback":
            archive.session.rollback()
        else:
            archive.session.commit()
        archive.session.begin()
        hold_command_gate(archive, monkeypatch)
        assert request_proof(archive.session) is not previous
    select(archive, 1, write=True)
    assert archive.state.retained_calls == [True] * 4
    assert archive.state.byte_calls == [archive.capture.id] * 2
    assert len(archive.state.rows_calls) == 2
    for model in (Outbox, Receipt, MeasurementImportCapture):
        assert len([call for call in archive.state.scalar_calls if call[0] is model]) == 2


@pytest.mark.parametrize("state", ["dirty", "inactive"])
def test_writer_gate_is_insufficient_for_a_dirty_or_inactive_actual_session(
    archive, monkeypatch, state
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    if state == "dirty":
        archive.session.add(archive.projection)
        assert archive.session.new
    else:
        archive.session.rollback()
        assert not archive.session.in_transaction()
    assert not results._held_read_session(archive.session, archive.ctx, archive.product_id)
    assert not archive.state.scalar_calls and not archive.state.rows_calls


def test_read_batch_proves_whole_view_once_and_keeps_every_event_and_original_byte(archive):
    with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
        first, second = select(archive), select(archive, 1)
        assert first.measurement_id != second.measurement_id
        assert archive.state.retained_calls == [False]
        batch = archive.session.info[bridge._READ_BATCH]
        assert len(batch.entries) == 1
        for entry in batch.entries.values():
            assert "current" not in json.loads(entry.retained_json)
            assert not isinstance(entry, bridge.FixedQualityResult)
    assert archive.state.retained_calls == [False, False]
    assert archive.state.byte_calls == [archive.capture.id] * 2
    assert archive.state.event_calls == [archive.event.id] * 2
    assert bridge._READ_BATCH not in archive.session.info
    # A new batch, even in the same transaction, gets its own initial/final proof.
    with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
        select(archive)
    assert archive.state.retained_calls == [False] * 4


def test_read_batch_reuses_only_sealed_typed_snapshots_and_revalidates_on_exit(
    archive, monkeypatch
):
    run_calls, request_calls = [], []
    real_run, real_request = bridge.launch._snapshot, bridge.front._snapshot

    def run_snapshot(row):
        run_calls.append(row.id)
        return real_run(row)

    def request_snapshot(row):
        request_calls.append(row.id)
        return real_request(row)

    monkeypatch.setattr(bridge.launch, "_snapshot", run_snapshot)
    monkeypatch.setattr(bridge.front, "_snapshot", request_snapshot)
    with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
        select(archive)
        select(archive, 1)
        assert run_calls == [archive.row.id]
        assert request_calls == [archive.request_row.id]
    assert run_calls == [archive.row.id] * 2
    assert request_calls == [archive.request_row.id] * 2


def test_read_batch_input_refresh_keeps_all_fact_checks_and_defers_only_retained_owner(archive):
    with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
        value = select(archive)
        for _ in range(2):
            value = bridge.recheck_fixed_failure_result(
                archive.session, archive.ctx, archive.product_id, value
            )
        assert value.current and archive.state.retained_calls == [False]
        assert archive.state.event_calls == [archive.event.id] * 3
    assert archive.state.retained_calls == [False] * 2
    assert archive.state.byte_calls == [archive.capture.id]


def test_read_batch_keeps_distinct_archived_versions_even_with_same_logical_run_and_basis(
    archive, monkeypatch
):
    original_row = archive.row
    later_run = archive.run.model_copy(update={"revision": archive.run.revision + 1})
    later_row = deepcopy(original_row)
    later_row.id, later_row.revision = uuid4(), later_run.revision
    later_row.run_snapshot = later_run.model_dump(mode="json")
    later_row.snapshot_sha256 = digest(later_row.run_snapshot)
    later_receipt = deepcopy(archive.receipt)
    later_receipt.id = uuid4()
    later_receipt.operation = "test.results.import"
    later_receipt.subject_type = "test_run"
    later_receipt.subject_id, later_receipt.subject_revision = later_row.id, later_row.revision
    later_event = deepcopy(archive.event)
    later_event.id, later_event.receipt_id = uuid4(), later_receipt.id
    later_event.type = EVENTS[later_receipt.operation]
    later_event.subject_id, later_event.subject_revision = later_row.id, later_row.revision
    real_scalar = archive.session.scalar

    def scalar(query):
        model, identity = query.column_descriptions[0]["entity"], query.compile().params.get("id_1")
        if model is Outbox and identity == later_event.id:
            return later_event
        if model is Receipt and identity == later_receipt.id:
            return later_receipt
        return real_scalar(query)

    def load(_s, _ctx, _pid, model, identity):
        if model is ResultProjection and identity == archive.projection.id:
            return archive.projection
        if model is VerificationRunVersion and identity in {original_row.id, later_row.id}:
            return original_row if identity == original_row.id else later_row
        raise DomainError("FORBIDDEN_SCOPE", "Wrong archived row", 403)

    monkeypatch.setattr(archive.session, "scalar", scalar)
    monkeypatch.setattr(bridge.launch, "_row", load)
    monkeypatch.setattr(bridge.results, "_row", load)
    with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
        first = select(archive)
        later = bridge.fixed_failure_result(
            archive.session,
            archive.ctx,
            archive.product_id,
            run_id=later_run.id,
            run_revision=later_run.revision,
            measurement_id=archive.records[1].id,
            event_id=later_event.id,
        )
        assert first.verified.run.id == later.verified.run.id
        assert first.basis_sha256 == later.basis_sha256
        assert first.run_version_id != later.run_version_id
        assert len(archive.session.info[bridge._READ_BATCH].entries) == 2
        assert archive.state.retained_calls == [False, False]
    assert archive.state.retained_calls == [False] * 4
    assert archive.state.byte_calls == [archive.capture.id] * 2
    assert archive.state.event_calls == [archive.event.id, later_event.id]


@pytest.mark.parametrize(
    "change", ["retained", "caller", "runtime", "source", "row", "request", "projection"]
)
def test_read_batch_terminal_failure_prevents_return_and_discards_owned_material(archive, change):
    escaped = []

    def build_view():
        with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
            value = select(archive)
            if change == "retained":
                archive.state.retained["current"] = False
            elif change == "caller":
                archive.state.expired = True
            elif change == "runtime":
                archive.state.runtime = "runtime-2"
            elif change == "source":
                archive.state.basis = {"different": "source"}
            elif change == "row":
                archive.row.owner_id = uuid4()
            elif change == "request":
                archive.request_row.sources = [{"different": "source"}]
            else:
                archive.projection.rules_sha256 = "0" * 64
            return value

    with pytest.raises(DomainError) as error:
        escaped.append(build_view())
    assert error.value.reason == ("FORBIDDEN_SCOPE" if change == "caller" else "SOURCE_STALE")
    assert not escaped
    assert bridge._READ_BATCH not in archive.session.info


@pytest.mark.parametrize(
    "change,reason",
    [
        ("event", "FAILURE_EVENT_UNAVAILABLE"),
        ("selected", "FAILURE_CONTEXT_MISSING"),
        ("measurement", "INTEGRITY_MISMATCH"),
        ("bytes", "REPORT_HASH_MISMATCH"),
        ("read_evidence", "SOURCE_STALE"),
    ],
)
def test_read_batch_never_skips_each_selection_identity_measurement_or_byte_guards(
    archive, change, reason
):
    with pytest.raises(DomainError) as error:
        with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
            select(archive)
            selected = None
            if change == "event":
                archive.event.schema_version = 2
            elif change == "selected":
                selected = uuid4()
            elif change == "measurement":
                archive.records[0].measurement_sha256 = "0" * 64
            elif change == "bytes":
                archive.state.content = archive.state.content.replace(b'"3"', b'"9"', 1)
            else:
                archive.state.source_current = False
            select(archive, 1, measurement_id=selected)
    assert error.value.reason == reason
    assert bridge._READ_BATCH not in archive.session.info


@pytest.mark.parametrize("mode", ["writer", "ordinary"])
def test_read_batch_does_not_defer_writer_or_non_rr_execution_guards(archive, mode):
    archive.session.info["read_snapshot"] = mode != "ordinary"
    with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
        select(archive, write=mode == "writer")
        select(archive, 1, write=mode == "writer")
    assert archive.state.retained_calls == [mode == "writer"] * 4
    assert archive.state.byte_calls == [archive.capture.id] * 2


def test_read_batch_nested_same_scope_has_one_outer_terminal_proof(archive):
    with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
        select(archive)
        with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
            select(archive, 1)
        assert archive.state.retained_calls == [False]
    assert archive.state.retained_calls == [False, False]


@pytest.mark.parametrize(
    "boundary", ["product", "context", "scope", "epoch", "rollback", "new_transaction", "dirty"]
)
def test_read_batch_rejects_changed_actual_owner_boundaries(archive, boundary):
    with pytest.raises(DomainError) as error:
        with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
            select(archive)
            pid, ctx = archive.product_id, archive.ctx
            if boundary == "product":
                pid = uuid4()
            elif boundary == "context":
                ctx = replace(ctx, requester_id=uuid4())
            elif boundary == "scope":
                archive.session.info["scope"] = (*archive.session.info["scope"][:3], uuid4())
            elif boundary == "epoch":
                with pytest.raises(UnboundExecutionError):
                    archive.session.execute(update(Product).values(revision=2))
            elif boundary == "rollback":
                archive.session.rollback()
            elif boundary == "new_transaction":
                archive.session.commit()
                archive.session.begin()
            else:
                archive.session.add(archive.projection)
            with bridge.read_failure_batch(archive.session, ctx, pid):
                raise AssertionError("Changed owner must not enter")
    assert error.value.reason in {"SOURCE_STALE", "FORBIDDEN_SCOPE"}
    assert archive.state.retained_calls == [False]
    assert bridge._READ_BATCH not in archive.session.info


def test_read_batch_exception_never_runs_or_retains_a_positive_terminal_proof(archive):
    with pytest.raises(ValueError, match="body failed"):
        with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
            select(archive)
            raise ValueError("body failed")
    assert archive.state.retained_calls == [False]
    assert bridge._READ_BATCH not in archive.session.info


def test_read_batch_initial_failure_keeps_original_error_before_measurement_selection(archive):
    archive.state.retained.update(current=False, reason_codes=["FORBIDDEN_SCOPE"])
    with pytest.raises(DomainError) as error:
        with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
            select(archive, measurement_id=uuid4())
    assert error.value.reason == "FORBIDDEN_SCOPE"
    assert archive.state.retained_calls == [False]
    assert not archive.state.rows_calls


def test_read_batch_rechecks_consumer_natural_deadline_after_terminal_owner_io(
    archive, monkeypatch
):
    real_retained = bridge.inspect_retained_execution

    def retained(*args, **kwargs):
        value = real_retained(*args, **kwargs)
        if len(archive.state.retained_calls) == 2:
            archive.state.expired = True
        return value

    monkeypatch.setattr(bridge, "inspect_retained_execution", retained)
    with pytest.raises(DomainError) as error:
        with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
            select(archive)
    assert error.value.reason == "FORBIDDEN_SCOPE"
    assert archive.state.retained_calls == [False, False]


@pytest.mark.parametrize("change", ["event", "projection", "source", "runtime", "caller"])
def test_read_batch_input_refresh_still_enforces_its_full_fact_and_current_guards(archive, change):
    with pytest.raises(DomainError) as error:
        with bridge.read_failure_batch(archive.session, archive.ctx, archive.product_id):
            value = select(archive)
            if change == "event":
                archive.event.schema_version = 2
            elif change == "projection":
                archive.projection.rules_sha256 = "0" * 64
            elif change == "source":
                archive.state.basis = {"different": "source"}
            elif change == "runtime":
                archive.state.runtime = "runtime-2"
            else:
                archive.state.expired = True
            bridge.recheck_fixed_failure_result(
                archive.session, archive.ctx, archive.product_id, value
            )
    assert (
        error.value.reason
        == {
            "event": "FAILURE_EVENT_UNAVAILABLE",
            "projection": "RESULT_BASIS_CHANGED",
            "source": "SOURCE_STALE",
            "runtime": "SOURCE_STALE",
            "caller": "FORBIDDEN_SCOPE",
        }[change]
    )


def test_writer_preparation_uses_real_model_gate_and_one_initial_plus_fresh_terminal_owner(
    archive, monkeypatch
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    with bridge.prepare_failure_batch(archive.session, archive.ctx, archive.product_id):
        first, second = select(archive, write=True), select(archive, 1, write=True)
        refreshed = bridge.recheck_fixed_failure_result(
            archive.session, archive.ctx, archive.product_id, first, write=True
        )
        assert refreshed.current and first.measurement_id != second.measurement_id
        assert archive.session.info[bridge._READ_BATCH].preparation is True
        assert archive.state.retained_calls == [True]
        assert archive.state.byte_calls == [archive.capture.id] * 2
        assert archive.state.event_calls == [archive.event.id] * 3
    assert archive.state.retained_calls == [True, False]
    assert bridge._READ_BATCH not in archive.session.info
    # The later record phase cannot borrow preparation's execution material.
    bridge.recheck_fixed_failure_result(
        archive.session, archive.ctx, archive.product_id, first, write=True
    )
    assert archive.state.retained_calls == [True, False, True]


@pytest.mark.parametrize("gate", ["unheld", "wrong_product", "category_only", "previous_dml"])
def test_writer_preparation_cannot_use_an_unheld_or_already_mutated_gate(
    archive, monkeypatch, gate
):
    archive.session.info["read_snapshot"] = False
    if gate == "wrong_product":
        hold_command_gate(archive, monkeypatch, product_id=uuid4())
    elif gate == "category_only":
        hold_command_gate(archive, monkeypatch, category_only=True)
    elif gate == "previous_dml":
        hold_command_gate(archive, monkeypatch)
        with pytest.raises(UnboundExecutionError):
            archive.session.execute(update(Product).values(revision=2))
        assert request_proof(archive.session).mutation_epoch == 1
    with bridge.prepare_failure_batch(archive.session, archive.ctx, archive.product_id):
        assert bridge._READ_BATCH not in archive.session.info
        select(archive, write=True)
        select(archive, 1, write=True)
    assert archive.state.retained_calls == [True] * 4
    assert archive.state.byte_calls == [archive.capture.id] * 2


@pytest.mark.parametrize(
    "boundary", ["product", "ctx", "scope", "dml", "pending", "rollback", "transaction", "runtime"]
)
def test_writer_preparation_rejects_every_changed_actual_phase_boundary(
    archive, monkeypatch, boundary
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    with pytest.raises(DomainError) as error:
        with bridge.prepare_failure_batch(archive.session, archive.ctx, archive.product_id):
            select(archive, write=True)
            ctx, pid = archive.ctx, archive.product_id
            if boundary == "product":
                pid = uuid4()
            elif boundary == "ctx":
                ctx = replace(ctx, requester_id=uuid4())
            elif boundary == "scope":
                archive.session.info["scope"] = (*archive.session.info["scope"][:3], uuid4())
            elif boundary == "dml":
                with pytest.raises(UnboundExecutionError):
                    archive.session.execute(update(Product).values(revision=2))
            elif boundary == "pending":
                archive.session.add(archive.projection)
            elif boundary == "rollback":
                archive.session.rollback()
            elif boundary == "transaction":
                archive.session.commit()
                archive.session.begin()
                hold_command_gate(archive, monkeypatch)
            else:
                archive.state.runtime = "runtime-2"
            with bridge.prepare_failure_batch(archive.session, ctx, pid):
                raise AssertionError("Changed preparation must not enter")
    assert error.value.reason in {"SOURCE_STALE", "FORBIDDEN_SCOPE"}
    assert archive.state.retained_calls == [True]
    assert bridge._READ_BATCH not in archive.session.info


@pytest.mark.parametrize(
    "change", ["retained", "runtime", "caller", "source", "row", "request", "projection"]
)
def test_writer_preparation_terminal_never_returns_changed_owned_proofs(
    archive, monkeypatch, change
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    with pytest.raises(DomainError) as error:
        with bridge.prepare_failure_batch(archive.session, archive.ctx, archive.product_id):
            select(archive, write=True)
            if change == "retained":
                archive.state.retained["current"] = False
            elif change == "runtime":
                archive.state.runtime = "runtime-2"
            elif change == "caller":
                archive.state.expired = True
            elif change == "source":
                archive.state.basis = {"different": "source"}
            elif change == "row":
                archive.row.owner_id = uuid4()
            elif change == "request":
                archive.request_row.sources = [{"different": "source"}]
            else:
                archive.projection.rules_sha256 = "0" * 64
    assert error.value.reason == ("FORBIDDEN_SCOPE" if change == "caller" else "SOURCE_STALE")
    assert bridge._READ_BATCH not in archive.session.info


def test_writer_preparation_is_separate_from_rr_reading_and_cannot_survive_dirty_entry(
    archive, monkeypatch
):
    with bridge.prepare_failure_batch(archive.session, archive.ctx, archive.product_id):
        assert bridge._READ_BATCH not in archive.session.info
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    archive.session.add(archive.projection)
    with bridge.prepare_failure_batch(archive.session, archive.ctx, archive.product_id):
        assert bridge._READ_BATCH not in archive.session.info


@pytest.mark.parametrize("change", ["runtime", "caller", "error"])
def test_writer_terminal_access_runs_after_real_owner_and_cannot_return_late_invalid_proof(
    archive, monkeypatch, change
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    access_calls, escaped = [], []

    def late_access():
        access_calls.append(True)
        assert archive.state.retained_calls == [True, False]
        if change == "runtime":
            archive.state.runtime = "runtime-2"
        elif change == "caller":
            archive.state.expired = True
        else:
            raise DomainError("SOURCE_STALE", "Access callback rejected current qualification")

    def prepare():
        with bridge.prepare_failure_batch(
            archive.session, archive.ctx, archive.product_id, terminal_access=late_access
        ):
            return select(archive, write=True)

    with pytest.raises(DomainError) as error:
        escaped.append(prepare())
    assert error.value.reason == ("FORBIDDEN_SCOPE" if change == "caller" else "SOURCE_STALE")
    assert access_calls == [True] and not escaped
    assert bridge._READ_BATCH not in archive.session.info


@pytest.mark.parametrize("gate", ["unheld", "previous_dml"])
def test_writer_terminal_access_and_clock_also_run_on_non_reusing_fallback(
    archive, monkeypatch, gate
):
    archive.session.info["read_snapshot"] = False
    if gate == "previous_dml":
        hold_command_gate(archive, monkeypatch)
        with pytest.raises(UnboundExecutionError):
            archive.session.execute(update(Product).values(revision=2))
    calls = []

    def access():
        assert bridge._READ_BATCH not in archive.session.info
        assert archive.state.retained_calls == [True, True]
        calls.append("access")
        return lambda: calls.append("clock")

    with bridge.prepare_failure_batch(
        archive.session, archive.ctx, archive.product_id, terminal_access=access
    ):
        select(archive, write=True)
    assert calls == ["access", "clock"]
    assert archive.state.retained_calls == [True, True]
    assert bridge._READ_BATCH not in archive.session.info


def test_writer_nested_terminal_access_waits_for_outer_and_rechecks_earlier_natural_deadline(
    archive, monkeypatch
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    calls, clock = [], {"expired": False}

    def inner_access():
        assert archive.state.retained_calls == [True, False]
        calls.append("inner_access")

        def final_clock():
            calls.append("inner_clock")
            if clock["expired"]:
                raise DomainError("SOURCE_STALE", "Earlier quality qualification naturally ended")

        return final_clock

    def outer_access():
        calls.append("outer_access")
        clock["expired"] = True
        return lambda: calls.append("outer_clock")

    with pytest.raises(DomainError) as error:
        with bridge.prepare_failure_batch(
            archive.session, archive.ctx, archive.product_id, terminal_access=outer_access
        ):
            select(archive, write=True)
            with bridge.prepare_failure_batch(
                archive.session, archive.ctx, archive.product_id, terminal_access=inner_access
            ):
                select(archive, 1, write=True)
            assert not calls and archive.state.retained_calls == [True]
    assert error.value.reason == "SOURCE_STALE"
    assert calls == ["inner_access", "outer_access", "inner_clock"]
    assert archive.state.retained_calls == [True, False]
    assert bridge._READ_BATCH not in archive.session.info


def test_writer_terminal_callback_is_not_retained_after_body_failure_or_new_batch(
    archive, monkeypatch
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)
    calls = []
    with pytest.raises(ValueError, match="body failed"):
        with bridge.prepare_failure_batch(
            archive.session,
            archive.ctx,
            archive.product_id,
            terminal_access=lambda: calls.append("failed_body_callback"),
        ):
            select(archive, write=True)
            raise ValueError("body failed")
    assert not calls and bridge._READ_BATCH not in archive.session.info
    with bridge.prepare_failure_batch(
        archive.session,
        archive.ctx,
        archive.product_id,
        terminal_access=lambda: calls.append("new_batch_access"),
    ):
        select(archive, write=True)
    assert calls == ["new_batch_access"]
    assert archive.state.retained_calls == [True, True, False]


def test_writer_terminal_callback_cannot_reenter_and_append_unfinalized_failure_material(
    archive, monkeypatch
):
    archive.session.info["read_snapshot"] = False
    hold_command_gate(archive, monkeypatch)

    def reenter():
        with bridge.prepare_failure_batch(archive.session, archive.ctx, archive.product_id):
            raise AssertionError("Terminal callbacks cannot append another preparation")

    with pytest.raises(DomainError) as error:
        with bridge.prepare_failure_batch(
            archive.session, archive.ctx, archive.product_id, terminal_access=reenter
        ):
            select(archive, write=True)
    assert error.value.reason == "SOURCE_STALE"
    assert archive.state.retained_calls == [True, False]
    assert bridge._READ_BATCH not in archive.session.info


def test_quality_scope_seal_tracks_actual_policy_revocation_without_binding_run_bridge():
    from pdos_next.domain.quality_execution import policy
    from pdos_next.domain.quality_execution import service as quality

    engine = SimpleNamespace()
    session = SimpleNamespace(get_bind=lambda: engine)
    scope = SimpleNamespace(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    bound = SimpleNamespace(scope=scope, policy={"id": str(uuid4())})
    issuer = policy.configure_local_synthetic(
        engine,
        tenant_id=scope.tenant_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        enabled=True,
        test_marker_verified=True,
        key="pure-quality-terminal-policy",
    )
    before, run_runtime = (
        quality._policy_issuer_seal(session, bound),
        bridge._runtime_stamp(session),
    )
    policy.disable_issuer(engine, issuer.key)
    assert engine._pdos_quality_policy_epochs[issuer.key] == issuer.epoch + 1
    assert quality._policy_issuer_seal(session, bound) != before
    assert bridge._runtime_stamp(session) == run_runtime
    with pytest.raises(DomainError) as error:
        quality._refresh_access_end(session, bound, before)
    assert error.value.reason == "SOURCE_STALE"


@pytest.mark.parametrize("different", ["tenant_id", "product_id", "project_id"])
def test_quality_scope_seal_does_not_depend_on_other_scope_policy_changes(different):
    from pdos_next.domain.quality_execution import policy
    from pdos_next.domain.quality_execution import service as quality

    engine = SimpleNamespace()
    session = SimpleNamespace(get_bind=lambda: engine)
    scope = dict(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    bound = SimpleNamespace(scope=SimpleNamespace(**scope), policy={"id": str(uuid4())})
    policy.configure_local_synthetic(
        engine,
        **scope,
        enabled=True,
        test_marker_verified=True,
        key="current-quality-scope",
    )
    before = quality._policy_issuer_seal(session, bound)
    unrelated = policy.configure_local_synthetic(
        engine,
        **{**scope, different: uuid4()},
        enabled=True,
        test_marker_verified=True,
        key="unrelated-quality-scope",
    )
    assert quality._policy_issuer_seal(session, bound) == before
    policy.disable_issuer(engine, unrelated.key)
    assert quality._policy_issuer_seal(session, bound) == before


def test_quality_without_policy_does_not_read_or_seal_any_policy_registry():
    from pdos_next.domain.quality_execution import service as quality

    def unexpected_registry():
        raise AssertionError("quality.issue.create has no consumed policy dependency")

    session = SimpleNamespace(get_bind=unexpected_registry)
    bound = SimpleNamespace(scope=object(), policy=None)
    assert quality._policy_issuer_seal(session, bound) is None
