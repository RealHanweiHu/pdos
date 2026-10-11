"""Pure owned-effect snapshot checks; all SQL seams are explicit and unbound."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next.domain.test_resources import retained, service
from pdos_next.domain.test_resources.models import SampleRunUsage
from pdos_next.domain.test_resources.models import TestResourceCurrent as ResourceCurrent
from pdos_next.domain.test_resources.models import TestResourceFact as ResourceFact
from pdos_next.domain.test_resources.schemas import TestPlanBinding as Binding
from pdos_next.domain.verification_launch import service as launch
from pdos_next.errors import DomainError
from pdos_next.request_proof import request_proof
from pdos_next.schemas.resource_readiness.contracts import ResourceUse
from pdos_next.service import Context


@pytest.fixture
def reads(monkeypatch):
    actor = uuid4()
    ctx = Context(uuid4(), actor, actor, category_id=uuid4())
    with Session() as session:
        session.begin()
        session.info["read_snapshot"] = True
        session.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
        value = SimpleNamespace(
            session=session,
            ctx=ctx,
            product=uuid4(),
            run=uuid4(),
            rows=[SimpleNamespace(id=uuid4()) for _ in range(32)],
            calls=[],
        )

        def scalars(query):
            value.calls.append(query)
            return list(value.rows)

        monkeypatch.setattr(session, "scalars", scalars)
        try:
            yield value
        finally:
            # Pending-row cases must never flush an intentionally unbound Session.
            session.rollback()


def query(value, *, run=None, product=None):
    return select(SampleRunUsage).where(
        SampleRunUsage.tenant_id == value.ctx.tenant_id,
        SampleRunUsage.product_id == (product or value.product),
        SampleRunUsage.run_id == (run or value.run),
    )


def load(value, statement=None, **options):
    return service._owned_rows(
        value.session,
        value.ctx,
        value.product,
        query(value) if statement is None else statement,
        **options,
    )


def test_clean_rr_reuses_all_exact_owned_rows_without_a_limit(reads):
    assert load(reads) == reads.rows
    assert load(reads) == reads.rows
    assert len(reads.calls) == 1 and reads.calls[0]._limit_clause is None


def test_same_shape_different_run_or_product_never_borrows_rows(reads):
    load(reads)
    run, product = uuid4(), uuid4()
    for statement in (query(reads, run=run), query(reads, product=product)):
        reads.rows = [SimpleNamespace(id=uuid4())]
        assert load(reads, statement) == reads.rows
        assert load(reads, statement) == reads.rows
    assert len(reads.calls) == 3


def test_narrow_and_broad_or_ordered_queries_keep_separate_results(reads):
    narrow = query(reads)
    broad = select(SampleRunUsage).where(
        SampleRunUsage.tenant_id == reads.ctx.tenant_id, SampleRunUsage.run_id == reads.run
    )
    for statement in (narrow, broad, narrow.order_by(SampleRunUsage.sample_id)):
        load(reads, statement)
        load(reads, statement)
    assert len(reads.calls) == 3


def test_empty_owned_set_is_fixed_only_in_this_read_transaction(reads):
    reads.rows = []
    assert load(reads) == load(reads) == []
    assert len(reads.calls) == 1


@pytest.mark.parametrize("mode", ["unheld_writer", "wrong_scope_gate", "no_transaction", "fake"])
def test_unheld_or_non_transactional_writer_always_executes_fresh_queries(reads, mode):
    load(reads)
    options = {}
    if mode == "unheld_writer":
        options["write"] = True
    elif mode == "wrong_scope_gate":
        reads.session.info["read_snapshot"] = False
        request_proof(reads.session).scope_locks.add(uuid4())
    elif mode == "no_transaction":
        reads.session.rollback()
    else:
        reads.session = SimpleNamespace(
            info={"read_snapshot": True},
            scalars=lambda statement: reads.calls.append(statement) or list(reads.rows),
        )
    for _ in range(2):
        reads.rows = [SimpleNamespace(id=uuid4())]
        assert load(reads, **options) == reads.rows
    assert len(reads.calls) == 3


@pytest.mark.parametrize("write", [False, True])
def test_clean_held_writer_reuses_complete_exact_own_rows(reads, write):
    reads.session.info["read_snapshot"] = False
    request_proof(reads.session).scope_locks.add(reads.product)
    assert load(reads, write=write) == reads.rows
    assert load(reads, write=write) == reads.rows
    assert len(reads.calls) == 1 and reads.calls[0]._limit_clause is None


def test_held_writer_cannot_share_under_a_different_product_gate(reads):
    reads.session.info["read_snapshot"] = False
    request_proof(reads.session).scope_locks.add(reads.product)
    load(reads, write=True)
    other = uuid4()
    for _ in range(2):
        reads.rows = [SimpleNamespace(id=uuid4())]
        assert (
            service._owned_rows(
                reads.session, reads.ctx, other, query(reads, product=other), write=True
            )
            == reads.rows
        )
    assert len(reads.calls) == 3


@pytest.mark.parametrize("mode", ["rr", "held_writer"])
@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
def test_pending_orm_state_cannot_reuse_preceding_rows(reads, pending, mode):
    if mode == "held_writer":
        reads.session.info["read_snapshot"] = False
        request_proof(reads.session).scope_locks.add(reads.product)
    load(reads)
    row = SampleRunUsage(id=uuid4(), state="reserved")
    if pending != "new":
        make_transient_to_detached(row)
    reads.session.add(row)
    if pending == "dirty":
        row.state = "consumed"
    elif pending == "deleted":
        reads.session.delete(row)
    for _ in range(2):
        reads.rows = [SimpleNamespace(id=uuid4())]
        assert load(reads) == reads.rows
    assert len(reads.calls) == 3


def test_new_root_transaction_rereads_the_same_exact_query(reads):
    load(reads)
    reads.session.rollback()
    with reads.session.begin():
        reads.rows = [SimpleNamespace(id=uuid4())]
        assert load(reads) == reads.rows
        assert load(reads) == reads.rows
    assert len(reads.calls) == 2


@pytest.mark.parametrize("mode", ["rr", "held_writer"])
def test_other_actor_cannot_borrow_the_transaction_read_set(reads, mode):
    if mode == "held_writer":
        reads.session.info["read_snapshot"] = False
        request_proof(reads.session).scope_locks.add(reads.product)
    load(reads)
    reads.ctx = Context(reads.ctx.tenant_id, uuid4(), uuid4(), category_id=reads.ctx.category_id)
    with pytest.raises(DomainError) as caught:
        load(reads)
    assert caught.value.reason == "FORBIDDEN_SCOPE" and len(reads.calls) == 1


def test_fresh_owned_rows_force_actual_complete_read_after_untracked_change(reads):
    reads.session.info["read_snapshot"] = False
    request_proof(reads.session).scope_locks.add(reads.product)
    first = load(reads, write=True)
    proof = request_proof(reads.session)
    epoch = proof.mutation_epoch
    # Simulate a raw SQL callback changing the DB result without an ORM event.
    reads.rows = [*first, SimpleNamespace(id=uuid4())]
    assert load(reads, write=True) == first
    assert proof.mutation_epoch == epoch
    assert load(reads, write=True, fresh=True) == reads.rows
    assert load(reads, write=True, fresh=True) == reads.rows
    assert len(reads.calls) == 3
    assert all(statement._limit_clause is None for statement in reads.calls)
    assert reads.calls[-1].get_execution_options()["populate_existing"] is True


@pytest.fixture
def proof(reads, monkeypatch):
    start = datetime(2026, 10, 8, 12, tzinfo=UTC)
    sample, configuration, executor, build = uuid4(), uuid4(), uuid4(), uuid4()
    reference = {"artifact_id": str(uuid4()), "expected_revision": 1, "line": 1, "quote": "proof"}
    binding = Binding.model_validate(
        {
            "run_id": reads.run,
            "request_id": uuid4(),
            "accepted_request_id": uuid4(),
            "accepted_request_revision": 1,
            "build_id": build,
            "project_id": uuid4(),
            "purpose": "fixed own execution",
            "executor_id": executor,
            "window": {
                "start": start,
                "finish": start + timedelta(hours=1),
                "original_timezone": "UTC",
            },
            "environment": "controlled room",
            "conditions": "fixed conditions",
            "equipment": reference,
            "calibration": reference,
            "pairs": [
                {
                    "sample": {
                        "id": sample,
                        "revision": 1,
                        "build_id": build,
                        "actual_configuration": {"id": configuration, "revision": 1},
                    },
                    "item_id": "strength",
                    "method_id": uuid4(),
                    "method_revision": 1,
                    "method_sha256": "a" * 64,
                    "destructive": False,
                }
            ],
        }
    )
    use = ResourceUse.model_validate(
        {"resource": {"id": executor, "revision": 1, "kind": "person"}, "units": "1"}
    )
    data = SimpleNamespace(required_uses=(use,))
    request = service._request(binding, data)
    scope = {
        "tenant_id": reads.ctx.tenant_id,
        "product_id": reads.product,
        "project_id": binding.project_id,
    }
    resource = {
        "ref": use.resource,
        "scope": scope,
        "source": {"id": uuid4(), "revision": 1, "kind": "domain", "position": "own proof"},
        "purposes": [binding.purpose],
        "operation_ids": [service.OPERATION],
        "lifecycle": "active",
        "facts": [],
        "maintenance": [],
        "capacity": "1",
        "occupancy_revision": 1,
    }
    reservation = service.Reservation.model_validate(
        {
            "id": binding.run_id,
            "revision": 1,
            "scope": scope,
            "request": request,
            "semantic_digest": "b" * 64,
            "state": "formal",
            "fixed_resources": [resource],
            "report": {
                "status": "READY",
                "capacity_status": "checked",
                "checks": [],
                "fixed_resources": [resource],
                "input_digest": "b" * 64,
                "checked_at": start,
            },
            "events": [{"kind": "formal", "at": start, "actor_id": reads.ctx.actor_id}],
        }
    ).model_dump(mode="json")
    existing = SimpleNamespace(
        binding=binding.model_dump(mode="json"),
        visibility="category",
        owner_id=reads.ctx.requester_id,
        reservation=reservation,
        reservation_sha256=service.digest(reservation),
        intent_digest="saved-intent",
    )
    occupancy = SimpleNamespace(
        id=uuid4(),
        tenant_id=reads.ctx.tenant_id,
        owner_kind="test_run",
        owner_execution_id=binding.run_id,
        resource_id=executor,
        resource_revision=1,
        units=Decimal("1"),
        window_start=start,
        window_finish=binding.window.finish,
        intent_digest=existing.intent_digest,
        product_id=reads.product,
        project_id=binding.project_id,
        build_id=binding.build_id,
        test_run_id=binding.run_id,
        reservation=reservation,
    )
    usage = SimpleNamespace(
        id=uuid4(),
        tenant_id=reads.ctx.tenant_id,
        run_id=binding.run_id,
        sample_id=sample,
        product_id=reads.product,
        project_id=binding.project_id,
        build_id=binding.build_id,
        intent_digest=existing.intent_digest,
        sample_revision=1,
        actual_configuration_id=configuration,
        actual_configuration_revision=1,
        window_start=start,
        window_finish=binding.window.finish,
        destructive=False,
        state="reserved",
        source_basis={"pairs": [pair.model_dump(mode="json") for pair in binding.pairs]},
        coverage=[
            {"sample_id": str(pair.sample.id), "item_id": pair.item_id} for pair in binding.pairs
        ],
        required_source_read_set=[reference],
    )
    reads.rows = [occupancy]
    source_checks = []
    monkeypatch.setattr(
        service, "_sources", lambda _s, _ctx, _pid, refs: source_checks.append(refs)
    )
    return SimpleNamespace(
        reads=reads,
        binding=binding,
        data=data,
        existing=existing,
        occupancy=occupancy,
        usage=usage,
        source_checks=source_checks,
    )


def prove(value, **options):
    return service._own_proof(
        value.reads.session,
        value.reads.ctx,
        value.reads.product,
        value.binding,
        value.data,
        value.existing,
        [value.usage],
        **options,
    )


def test_reused_own_rows_still_check_the_complete_source_read_set(proof, monkeypatch):
    prove(proof)
    prove(proof)
    assert proof.source_checks == [proof.usage.required_source_read_set] * 2
    assert len(proof.reads.calls) == 1

    def revoked(*_):
        raise DomainError("FORBIDDEN_SCOPE", "Exact source audience revoked", 403)

    monkeypatch.setattr(service, "_sources", revoked)
    with pytest.raises(DomainError) as caught:
        prove(proof)
    assert caught.value.reason == "FORBIDDEN_SCOPE" and len(proof.reads.calls) == 1


@pytest.mark.parametrize(
    "owner,field,value,reason",
    [
        ("occupancy", "units", Decimal("2"), "RUN_RESERVATION_MISSING"),
        ("occupancy", "resource_revision", 2, "RUN_RESERVATION_MISSING"),
        ("occupancy", "project_id", None, "RUN_RESERVATION_MISSING"),
        ("occupancy", "reservation", {}, "RUN_RESERVATION_MISSING"),
        ("usage", "sample_revision", 2, "RUN_SAMPLE_USAGE_MISSING"),
        ("usage", "destructive", True, "RUN_SAMPLE_USAGE_MISSING"),
        ("usage", "actual_configuration_revision", 2, "RUN_SAMPLE_USAGE_MISSING"),
        ("usage", "source_basis", {"pairs": []}, "RUN_SAMPLE_USAGE_MISSING"),
    ],
)
def test_reused_rows_never_replace_full_owned_identity_checks(proof, owner, field, value, reason):
    prove(proof)
    setattr(getattr(proof, owner), field, value)
    with pytest.raises(DomainError) as caught:
        prove(proof)
    assert caught.value.reason == reason and len(proof.reads.calls) == 1


def test_own_proof_writer_rechecks_real_rows_even_after_snapshot_read(proof):
    prove(proof)
    proof.reads.rows = []
    with pytest.raises(DomainError) as caught:
        prove(proof, write=True)
    assert caught.value.reason == "RUN_RESERVATION_MISSING" and len(proof.reads.calls) == 2


@pytest.fixture
def saved(proof, monkeypatch):
    row = SimpleNamespace(
        operation="test.run.start",
        run_id=proof.binding.run_id,
        project_id=proof.binding.project_id,
        build_id=proof.binding.build_id,
        input_snapshot={
            "plan_binding": proof.existing.binding,
            "reservation": {
                "occupancy_ids": [str(proof.occupancy.id)],
                "sample_usage_ids": [str(proof.usage.id)],
            },
            "resource_facts_revision": "c" * 64,
        },
    )

    class Rows(list):
        def all(self):
            return list(self)

    def scalar(statement):
        assert statement.column_descriptions[0]["entity"] is service.TestResourceReservation
        proof.reads.calls.append(statement)
        return proof.existing

    def scalars(statement):
        model = statement.column_descriptions[0]["entity"]
        proof.reads.calls.append(statement)
        if model is service.ResourceOccupancy:
            if service._canonical_rr(proof.reads.session):
                assert list(statement._order_by_clauses) == []
                assert statement.compile().params == {
                    "tenant_id_1": proof.reads.ctx.tenant_id,
                    "owner_kind_1": "test_run",
                    "owner_execution_id_1": proof.binding.run_id,
                }
            else:
                assert list(statement._order_by_clauses) == [service.ResourceOccupancy.resource_id]
            return Rows([proof.occupancy])
        assert model is SampleRunUsage
        if service._canonical_rr(proof.reads.session):
            assert list(statement._order_by_clauses) == []
            assert statement.compile().params == {
                "tenant_id_1": proof.reads.ctx.tenant_id,
                "product_id_1": proof.reads.product,
                "run_id_1": proof.binding.run_id,
            }
        else:
            assert list(statement._order_by_clauses) == [SampleRunUsage.sample_id]
        return Rows([proof.usage])

    evidence_checks, fingerprint_checks = [], []
    monkeypatch.setattr(proof.reads.session, "scalar", scalar)
    monkeypatch.setattr(proof.reads.session, "scalars", scalars)
    monkeypatch.setattr(
        launch, "_read_evidence", lambda _s, _ctx, _pid, value: evidence_checks.append(value)
    )
    monkeypatch.setattr(
        launch,
        "_saved_start_fingerprint",
        lambda _s, _ctx, _pid, value, *, reservation: fingerprint_checks.append(
            (value, reservation)
        ),
    )
    return SimpleNamespace(
        proof=proof, row=row, evidence_checks=evidence_checks, fingerprint_checks=fingerprint_checks
    )


def effects(value, **options):
    reads = value.proof.reads
    return launch._saved_effects(reads.session, reads.ctx, reads.product, value.row, **options)


def test_saved_effects_share_exact_rr_reads_and_keep_each_proof_check(saved):
    first = effects(saved)
    assert effects(saved) == first
    assert effects(saved) == first
    proof, reads = saved.proof, saved.proof.reads
    assert len(reads.calls) == 3
    assert saved.evidence_checks == [proof.existing, proof.usage] * 3
    assert saved.fingerprint_checks == [(saved.row, proof.existing)] * 3
    assert (
        service._reservation(reads.session, reads.ctx, reads.product, proof.binding)
        is proof.existing
    )
    assert len(reads.calls) == 3


def test_saved_effects_scope_held_writer_shares_exact_three_reads(saved):
    reads = saved.proof.reads
    reads.session.info["read_snapshot"] = False
    request_proof(reads.session).scope_locks.add(reads.product)
    assert effects(saved) == effects(saved)
    assert len(reads.calls) == 3
    assert service._reservation(reads.session, reads.ctx, reads.product, saved.proof.binding)
    assert len(reads.calls) == 3


def test_saved_effects_explicit_fresh_writer_rereads_all_three_sets(saved):
    reads = saved.proof.reads
    reads.session.info["read_snapshot"] = False
    request_proof(reads.session).scope_locks.add(reads.product)
    assert effects(saved) == effects(saved)
    assert len(reads.calls) == 3
    assert effects(saved, fresh=True) == effects(saved, fresh=True)
    assert len(reads.calls) == 9
    assert all(q.get_execution_options()["populate_existing"] is True for q in reads.calls[-6:])
    assert saved.evidence_checks == [saved.proof.existing, saved.proof.usage] * 4
    assert saved.fingerprint_checks == [(saved.row, saved.proof.existing)] * 4


@pytest.mark.parametrize("changed", ["reservation", "occupancy", "usage"])
def test_terminal_fresh_effects_detect_untracked_database_result_changes(
    saved, monkeypatch, changed
):
    reads = saved.proof.reads
    reads.session.info["read_snapshot"] = False
    request_proof(reads.session).scope_locks.add(reads.product)
    first = effects(saved)
    epoch = request_proof(reads.session).mutation_epoch
    original_scalar, original_scalars = reads.session.scalar, reads.session.scalars

    def scalar(statement):
        selected = original_scalar(statement)
        if changed == "reservation":
            return None
        return selected

    def scalars(statement):
        selected = original_scalars(statement)
        model = statement.column_descriptions[0]["entity"]
        if changed == "occupancy" and model is service.ResourceOccupancy:
            return [*selected, SimpleNamespace(id=uuid4())]
        if changed == "usage" and model is SampleRunUsage:
            return []
        return selected

    monkeypatch.setattr(reads.session, "scalar", scalar)
    monkeypatch.setattr(reads.session, "scalars", scalars)
    assert effects(saved) == first and len(reads.calls) == 3
    assert request_proof(reads.session).mutation_epoch == epoch
    with pytest.raises(DomainError) as caught:
        effects(saved, fresh=True)
    assert caught.value.reason == "RUN_RESERVATION_MISSING"
    assert len(reads.calls) == (4 if changed == "reservation" else 6)


def test_saved_effects_cached_rows_still_reject_changed_own_id_set(saved):
    effects(saved)
    saved.row.input_snapshot["reservation"]["occupancy_ids"].append(str(uuid4()))
    with pytest.raises(DomainError) as caught:
        effects(saved)
    assert caught.value.reason == "RUN_RESERVATION_MISSING"
    assert len(saved.proof.reads.calls) == 3


def test_saved_effects_cached_reservation_still_checks_its_complete_hash(saved):
    effects(saved)
    saved.proof.existing.reservation["semantic_digest"] = "d" * 64
    with pytest.raises(DomainError) as caught:
        effects(saved)
    assert caught.value.reason == "RUN_RESERVATION_MISSING"
    assert len(saved.proof.reads.calls) == 3


def test_saved_effects_reuse_never_skips_current_source_access(saved, monkeypatch):
    effects(saved)

    def revoked(*_):
        raise DomainError("FORBIDDEN_SCOPE", "Saved source audience revoked", 403)

    monkeypatch.setattr(launch, "_read_evidence", revoked)
    with pytest.raises(DomainError) as caught:
        effects(saved)
    assert caught.value.reason == "FORBIDDEN_SCOPE" and len(saved.proof.reads.calls) == 3


@pytest.fixture
def current_rows(proof, monkeypatch):
    """Real mapped rows and issuer registration; only SQL transport is substituted."""
    reads, binding = proof.reads, proof.binding
    engine = SimpleNamespace()
    issuer = service.configure_issuer(
        engine,
        key="canonical-resource-owner",
        version="v1",
        tenant_id=reads.ctx.tenant_id,
        product_id=reads.product,
        project_id=binding.project_id,
    )
    fields = {attribute.key: None for attribute in ResourceFact.__mapper__.column_attrs}
    fields.update(
        id=uuid4(),
        tenant_id=reads.ctx.tenant_id,
        category_id=reads.ctx.category_id,
        created_at=binding.window.start,
        product_id=reads.product,
        project_id=binding.project_id,
        build_id=binding.build_id,
        run_id=binding.run_id,
        request_id=binding.request_id,
        accepted_request_id=binding.accepted_request_id,
        accepted_request_revision=binding.accepted_request_revision,
        owner_id=reads.ctx.requester_id,
        visibility="category",
        issuer_key=issuer.key,
        issuer_version=issuer.version,
        issuer_epoch=issuer.epoch,
        nature=issuer.nature,
        revision=1,
        external_id="canonical-resource-owner",
        series_id=uuid4(),
        state="active",
        valid_from=binding.window.start,
        valid_until=binding.window.finish,
        binding=binding.model_dump(mode="json"),
        data={},
        sources=[],
        required_source_read_set=[],
        source_basis={},
        reason="exact original resource owner",
    )
    fact = ResourceFact(**fields)
    fact.fact_sha256 = service._fact_hash(fact)
    # Keep the actual immutable row in this real Session's identity map, as the
    # earlier maker selection does. It is clean and cannot flush on teardown.
    make_transient_to_detached(fact)
    reads.session.add(fact)
    pointer = ResourceCurrent(
        id=uuid4(),
        tenant_id=reads.ctx.tenant_id,
        category_id=reads.ctx.category_id,
        product_id=reads.product,
        project_id=binding.project_id,
        build_id=binding.build_id,
        request_id=binding.request_id,
        run_id=binding.run_id,
        fact_id=fact.id,
        fact_revision=fact.revision,
        epoch=1,
    )
    value = SimpleNamespace(
        reads=reads,
        binding=binding,
        engine=engine,
        issuer=issuer,
        fact=fact,
        pointer=pointer,
        pointers=[pointer],
        bundle=SimpleNamespace(
            fact_ref=SimpleNamespace(
                id=fact.id,
                revision=fact.revision,
                sha256=fact.fact_sha256,
                epoch=pointer.epoch,
                nature=fact.nature,
            )
        ),
    )

    def scalars(statement):
        reads.calls.append(statement)
        model = statement.column_descriptions[0]["entity"]
        assert model in {ResourceCurrent, ResourceFact}
        return list(value.pointers) if model is ResourceCurrent else [fact]

    monkeypatch.setattr(reads.session, "scalars", scalars)
    monkeypatch.setattr(reads.session, "get_bind", lambda: engine)
    return value


def dependency(value, **options):
    reads = value.reads
    return retained._fixed_dependency(
        reads.session, reads.ctx, reads.product, value.binding, value.bundle, **options
    )


def test_rr_current_and_retained_share_complete_unique_pointer_rows(current_rows):
    value, reads = current_rows, current_rows.reads
    assert service._current(reads.session, reads.ctx, reads.product, reads.run) == (
        value.pointer,
        value.fact,
    )
    first = dependency(value)
    assert dependency(value) == first
    assert first.fact_id == value.fact.id and first.issuer_epoch == value.issuer.epoch
    selected = [query.column_descriptions[0]["entity"] for query in reads.calls]
    assert selected == [ResourceCurrent, ResourceFact]
    assert reads.calls[0]._limit_clause is None
    assert reads.calls[0].compile().params == {
        "tenant_id_1": reads.ctx.tenant_id,
        "product_id_1": reads.product,
        "run_id_1": reads.run,
    }


@pytest.mark.parametrize("count", [0, 2])
def test_canonical_current_complete_collection_keeps_retained_uniqueness(current_rows, count):
    value, reads = current_rows, current_rows.reads
    value.pointers = [value.pointer] * count
    assert len(service._current_rows(reads.session, reads.ctx, reads.product, reads.run)) == count
    with pytest.raises(DomainError) as caught:
        dependency(value)
    assert caught.value.reason == "FORBIDDEN_SCOPE" and len(reads.calls) == 1


@pytest.mark.parametrize("change", ["fact_hash", "scope", "issuer"])
def test_canonical_current_rows_never_replace_full_fact_or_issuer_guards(current_rows, change):
    value, reads = current_rows, current_rows.reads
    dependency(value)
    if change == "fact_hash":
        value.fact.binding["environment"] = "changed without changing the stored hash"
    elif change == "scope":
        value.pointer.project_id = uuid4()
    else:
        service.disable_issuer(value.engine, value.issuer.key)
    assert not reads.session.dirty
    with pytest.raises(DomainError) as caught:
        dependency(value)
    expected = "TRUSTED_ISSUER_REQUIRED" if change == "issuer" else "INTEGRITY_MISMATCH"
    assert caught.value.reason == expected and len(reads.calls) == 2


def _writer_owner(value):
    reads = value.reads
    reads.session.info["read_snapshot"] = False
    request_proof(reads.session).scope_locks.add(reads.product)


def _maker(value, *, remember=True):
    reads = value.reads
    row = retained._one(
        reads.session,
        reads.ctx,
        ResourceFact,
        ResourceFact.tenant_id == reads.ctx.tenant_id,
        ResourceFact.product_id == reads.product,
        ResourceFact.id == value.fact.id,
        ResourceFact.revision == value.fact.revision,
        scope_id=reads.product,
    )
    if not remember:
        return row
    service._remember_maker_fact(
        reads.session,
        reads.ctx,
        reads.product,
        reads.run,
        row,
        identity=value.fact.id,
        revision=value.fact.revision,
    )
    return row


def test_held_writer_maker_and_complete_current_reuse_keeps_both_terminal_reads(current_rows):
    value, reads = current_rows, current_rows.reads
    _writer_owner(value)
    with service._maker_fact_scope(reads.session):
        assert _maker(value) is value.fact
        assert service._current(reads.session, reads.ctx, reads.product, reads.run) == (
            value.pointer,
            value.fact,
        )
        first = dependency(value)
        assert dependency(value) == first
        selected = [q.column_descriptions[0]["entity"] for q in reads.calls]
        assert selected == [ResourceFact, ResourceCurrent]
        assert reads.calls[1]._limit_clause is None
        assert (ResourceFact, value.fact.id) not in request_proof(reads.session).read_rows
        assert dependency(value, fresh=True) == first
        assert [q.column_descriptions[0]["entity"] for q in reads.calls[2:]] == [
            ResourceCurrent,
            ResourceFact,
        ]
        assert all(q._limit_clause is not None for q in reads.calls[2:])
    assert service._MAKER_FACT_STAGE not in reads.session.info


@pytest.mark.parametrize("count", [0, 2])
def test_held_writer_complete_current_reuse_keeps_exact_uniqueness(current_rows, count):
    value, reads = current_rows, current_rows.reads
    _writer_owner(value)
    value.pointers = [value.pointer] * count
    with service._maker_fact_scope(reads.session):
        assert (
            len(service._current_rows(reads.session, reads.ctx, reads.product, reads.run)) == count
        )
        with pytest.raises(DomainError) as caught:
            dependency(value)
    assert caught.value.reason == "FORBIDDEN_SCOPE"
    assert len(reads.calls) == 1 and reads.calls[0]._limit_clause is None


@pytest.mark.parametrize("change", ["gate", "scope", "dirty", "epoch", "savepoint", "caller"])
def test_held_maker_and_current_cannot_cross_owner_boundaries(current_rows, change):
    value, reads = current_rows, current_rows.reads
    _writer_owner(value)
    nested = None
    with service._maker_fact_scope(reads.session):
        _maker(value)
        service._current(reads.session, reads.ctx, reads.product, reads.run)
        if change == "gate":
            request_proof(reads.session).scope_locks = {uuid4()}
        elif change == "scope":
            reads.session.info.pop("scope")
        elif change == "dirty":
            reads.session.add(ResourceCurrent(id=uuid4(), epoch=1))
        elif change == "epoch":
            request_proof(reads.session).mutation_epoch += 1
        elif change == "savepoint":
            nested = reads.session.begin_nested()
        else:
            reads.ctx = replace(reads.ctx, run_id=uuid4())
        try:
            assert service._current(reads.session, reads.ctx, reads.product, reads.run) == (
                value.pointer,
                value.fact,
            )
            assert [q.column_descriptions[0]["entity"] for q in reads.calls[2:]] == [
                ResourceCurrent,
                ResourceFact,
            ]
        finally:
            if nested is not None:
                nested.rollback()


def test_maker_fact_does_not_escape_stage_or_skip_lock_upgrade(current_rows):
    value, reads = current_rows, current_rows.reads
    _writer_owner(value)
    with service._maker_fact_scope(reads.session):
        _maker(value)
        service._current(reads.session, reads.ctx, reads.product, reads.run)
        service._current(reads.session, reads.ctx, reads.product, reads.run, lock=True)
        assert reads.calls[2]._for_update_arg is not None
        assert reads.calls[3]._for_update_arg is None
        # The lock-upgrade reader keeps its ordinary raw fact entry; clear it
        # to make the next owner's SQL independent of that preceding reader.
        request_proof(reads.session).read_rows.pop((ResourceFact, value.fact.id), None)
    with service._maker_fact_scope(reads.session):
        service._current(reads.session, reads.ctx, reads.product, reads.run)
    assert [q.column_descriptions[0]["entity"] for q in reads.calls[4:]] == [
        ResourceCurrent,
        ResourceFact,
    ]


def test_borrowed_maker_stage_is_not_a_fake_session_read_proof(current_rows):
    value, reads = current_rows, current_rows.reads
    _writer_owner(value)
    with service._maker_fact_scope(reads.session):
        _maker(value)
        service._current(reads.session, reads.ctx, reads.product, reads.run)
        fake = SimpleNamespace(
            info=reads.session.info,
            get_transaction=reads.session.get_transaction,
            scalars=reads.session.scalars,
        )
        assert service._current(fake, reads.ctx, reads.product, reads.run) == (
            value.pointer,
            value.fact,
        )
    assert [q.column_descriptions[0]["entity"] for q in reads.calls[2:]] == [
        ResourceCurrent,
        ResourceFact,
    ]


@pytest.mark.parametrize("missing", ["identity", "revision", "run", "product", "column", "session"])
def test_maker_registration_requires_exact_complete_same_session_row(current_rows, missing):
    from sqlalchemy.orm.attributes import set_committed_value

    value, reads = current_rows, current_rows.reads
    _writer_owner(value)
    with service._maker_fact_scope(reads.session):
        row = _maker(value, remember=False)
        identity, revision, run, pid = row.id, row.revision, reads.run, reads.product
        reason = row.reason
        if missing == "identity":
            identity = uuid4()
        elif missing == "revision":
            revision += 1
        elif missing == "run":
            run = uuid4()
        elif missing == "product":
            pid = uuid4()
        elif missing == "column":
            reads.session.expire(row, ["reason"])
        else:
            reads.session.expunge(row)
        service._remember_maker_fact(
            reads.session, reads.ctx, pid, run, row, identity=identity, revision=revision
        )
        if missing == "column":
            # Restore the transport's actual complete row for the fallback SQL.
            set_committed_value(row, "reason", reason)
        assert service._current(reads.session, reads.ctx, reads.product, reads.run) == (
            value.pointer,
            value.fact,
        )
    assert [q.column_descriptions[0]["entity"] for q in reads.calls] == [
        ResourceFact,
        ResourceCurrent,
        ResourceFact,
    ]


def test_held_owner_current_root_and_context_cannot_borrow_complete_rows(current_rows):
    value, reads = current_rows, current_rows.reads
    _writer_owner(value)
    service._current_rows(reads.session, reads.ctx, reads.product, reads.run)
    other = replace(reads.ctx, actor_id=uuid4(), requester_id=uuid4())
    with pytest.raises(DomainError) as caught:
        service._current_rows(reads.session, other, reads.product, reads.run)
    assert caught.value.reason == "FORBIDDEN_SCOPE" and len(reads.calls) == 1
    reads.session.rollback()
    with reads.session.begin():
        request_proof(reads.session).scope_locks.add(reads.product)
        service._current_rows(reads.session, reads.ctx, reads.product, reads.run)
    assert len(reads.calls) == 2


@pytest.mark.parametrize("change", ["fact_hash", "scope", "issuer"])
def test_held_maker_raw_row_never_replaces_complete_owner_guards(current_rows, change):
    value, reads = current_rows, current_rows.reads
    _writer_owner(value)
    with service._maker_fact_scope(reads.session):
        _maker(value)
        dependency(value)
        if change == "fact_hash":
            value.fact.binding["environment"] = "changed after the real maker read"
        elif change == "scope":
            value.pointer.project_id = uuid4()
        else:
            service.disable_issuer(value.engine, value.issuer.key)
        with pytest.raises(DomainError) as caught:
            dependency(value)
    expected = "TRUSTED_ISSUER_REQUIRED" if change == "issuer" else "INTEGRITY_MISMATCH"
    assert caught.value.reason == expected and len(reads.calls) == 2


def test_canonical_rr_saved_and_owner_checks_share_complete_wide_rows(saved):
    proof, reads = saved.proof, saved.proof.reads
    prove(proof)
    usage = service._own_usages(reads.session, reads.ctx, reads.product, proof.binding.run_id)
    assert usage == [proof.usage]
    first = effects(saved)
    prove(proof)
    assert effects(saved) == first
    models = [query.column_descriptions[0]["entity"] for query in reads.calls]
    assert models == [service.ResourceOccupancy, SampleRunUsage, service.TestResourceReservation]
    assert all(query._limit_clause is None for query in reads.calls)
    assert first["occupancy"][0]["id"] == str(proof.occupancy.id)
    assert first["sample_usage"][0]["id"] == str(proof.usage.id)
    assert proof.source_checks == [proof.usage.required_source_read_set] * 2
    assert saved.evidence_checks == [proof.existing, proof.usage] * 2


@pytest.mark.parametrize("owner", ["occupancy", "usage"])
def test_canonical_rr_saved_effects_reject_extra_wrong_scope_owned_rows(saved, monkeypatch, owner):
    proof, reads = saved.proof, saved.proof.reads
    extra = SimpleNamespace(**vars(getattr(proof, owner)))
    extra.id, extra.project_id = uuid4(), uuid4()
    identity_key = "occupancy_ids" if owner == "occupancy" else "sample_usage_ids"
    # Even an ID named by the supplied saved envelope must not hide a wrong
    # scope row from the complete collection. The production scope guard runs.
    saved.row.input_snapshot["reservation"][identity_key].append(str(extra.id))
    original_scalars = reads.session.scalars

    def scalars(statement):
        rows = original_scalars(statement)
        model = statement.column_descriptions[0]["entity"]
        changed = service.ResourceOccupancy if owner == "occupancy" else SampleRunUsage
        return [*rows, extra] if model is changed else rows

    monkeypatch.setattr(reads.session, "scalars", scalars)
    with pytest.raises(DomainError) as caught:
        effects(saved)
    assert caught.value.reason == "RUN_RESERVATION_MISSING" and len(reads.calls) == 3
