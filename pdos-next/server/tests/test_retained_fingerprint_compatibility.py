"""No-connect retained boundary cases, with explicit SQL/source/owner substitutes.

Real SQLAlchemy Session/transaction and typed persisted shapes are exercised;
this is not proof of actual PG, bytes, qualification or saved consumption.
"""

# ruff: noqa: F811 -- imported fixture arguments intentionally share the registration name

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_fingerprint_compatibility import materials  # noqa: F401 -- fixture reuse

from pdos_next.domain.build_operational_facts.service import digest
from pdos_next.domain.resource_readiness.rules import semantic_digest
from pdos_next.domain.test_resources import retained
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.models import TestResourceCurrent as Current
from pdos_next.domain.test_resources.models import TestResourceFact as Fact
from pdos_next.domain.test_resources.schemas import TestReservationResult as Result
from pdos_next.domain.verification_launch.schemas import ExecutionPlan
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product
from pdos_next.schemas.resource_readiness.contracts import (
    ReadinessReport,
    Reservation,
    ReservationRequest,
    ResourceSnapshot,
)
from pdos_next.schemas.verification.contracts import Scope, TimeFact
from pdos_next.schemas.verification.contracts import TestRun as Run
from pdos_next.service import Context


def uid(n):
    return UUID(int=n)


@pytest.fixture
def work(materials, monkeypatch):
    old, fresh, fixed = materials
    binding = old["binding"]
    clock = SimpleNamespace(at=datetime(2026, 10, 3, 14, tzinfo=UTC))
    monkeypatch.setattr(retained, "now", lambda: clock.at)
    monkeypatch.setattr(resources, "now", lambda: clock.at)
    engine = create_engine("sqlite://")
    monkeypatch.setattr(engine, "connect", lambda *a, **k: pytest.fail("Database access forbidden"))
    issuer = resources.configure_local_synthetic(
        engine,
        key=fixed.issuer_key,
        version=fixed.issuer_version,
        tenant_id=fixed.tenant_id,
        product_id=fixed.product_id,
        project_id=fixed.project_id,
        enabled=True,
        test_marker_verified=True,
    )
    resources.configure_local_synthetic(
        engine,
        key="new-unrelated-key",
        tenant_id=uid(90),
        product_id=uid(91),
        enabled=True,
        test_marker_verified=True,
    )
    ctx = Context(fixed.tenant_id, binding.executor_id, binding.executor_id, category_id=uid(500))
    session = Session(bind=engine)
    session.begin()
    source = {"id": uid(30), "revision": 1, "kind": "artifact", "position": "line:1"}
    actual = TimeFact(
        occurred_at=binding.window.start,
        received_at=binding.window.start,
        actor_id=ctx.actor_id,
        original_timezone="UTC",
        source=source,
    )
    run = Run(
        id=binding.run_id,
        revision=2,
        scope=Scope(
            tenant_id=ctx.tenant_id, product_id=fixed.product_id, project_id=binding.project_id
        ),
        request_id=binding.request_id,
        request_revision=6,
        build={
            "id": binding.build_id,
            "revision": 1,
            "product_id": fixed.product_id,
            "project_id": binding.project_id,
            "engineering_configuration": {"id": uid(60), "revision": 1},
            "manufacturing_configuration": {"id": uid(61), "revision": 1},
        },
        items=[{"id": "strength", "feature": "fixed-strength", "sample_count": 1}],
        samples=[binding.pairs[0].sample],
        coverage=[{"sample_id": binding.pairs[0].sample.id, "item_id": "strength"}],
        status="running",
        actual_start=actual,
    )
    plan = ExecutionPlan(
        window=binding.window,
        executor_id=binding.executor_id,
        equipment=binding.equipment.model_dump(mode="json"),
        calibration=binding.calibration.model_dump(mode="json"),
        environment=binding.environment,
        conditions=binding.conditions,
        resource_fact_id=fixed.fact_id,
        expected_resource_fact_revision=1,
    )
    request = ReservationRequest(
        reservation_id=binding.run_id,
        owner_run_id=binding.run_id,
        intent_key="exact-original",
        purpose=binding.purpose,
        operation_id="test.run.start",
        window=binding.window,
        uses=[
            {"resource": {"id": uid(14), "revision": 1, "kind": "equipment"}, "units": "1"},
            {"resource": {"id": uid(6), "revision": 1, "kind": "person"}, "units": "1"},
        ],
    )
    snapshots = tuple(
        ResourceSnapshot(
            ref=use.resource,
            scope=run.scope,
            source=source,
            purposes=(binding.purpose,),
            operation_ids=("test.run.start",),
            lifecycle="active",
            capacity="1",
            occupancy_revision=1,
        )
        for use in request.uses
    )
    report = ReadinessReport(
        status="READY",
        capacity_status="checked",
        checks=[],
        fixed_resources=snapshots,
        input_digest="a" * 64,
        checked_at=binding.window.start,
    )
    kernel = Reservation(
        id=binding.run_id,
        revision=1,
        scope=run.scope,
        request=request,
        semantic_digest=semantic_digest(request),
        state="formal",
        fixed_resources=snapshots,
        report=report,
        events=[{"kind": "formal", "at": binding.window.start, "actor_id": ctx.actor_id}],
    )
    encoded = kernel.model_dump(mode="json")
    saved = Result(
        owner_run_id=binding.run_id,
        reservation_id=kernel.id,
        occupancy_ids=(uid(40), uid(41)),
        sample_usage_ids=(uid(42),),
        facts_revision=digest(old),
    ).model_dump(mode="json")
    original = SimpleNamespace(
        id=uid(45),
        revision=2,
        operation="test.run.start",
        run_id=binding.run_id,
        project_id=binding.project_id,
        created_at=binding.window.start + timedelta(seconds=1),
        request_version_id=uid(3),
        request_revision=6,
        execution_plan=plan.model_dump(mode="json"),
        intent_digest="b" * 64,
        required_source_read_set=[{"artifact_id": str(uid(30)), "expected_revision": 1}],
        sources=[binding.equipment.model_dump(mode="json")],
        source_basis={"fixed": "source-basis"},
        authority_snapshot=deepcopy(old["authority"]),
        input_snapshot={
            "plan_binding": binding.model_dump(mode="json"),
            "resource_facts_revision": digest(old),
            "reservation": saved,
        },
    )
    existing = SimpleNamespace(
        id=kernel.id,
        revision=1,
        state="formal",
        tenant_id=ctx.tenant_id,
        product_id=fixed.product_id,
        project_id=binding.project_id,
        build_id=binding.build_id,
        run_id=binding.run_id,
        intent_digest=original.intent_digest,
        binding=binding.model_dump(mode="json"),
        reservation=encoded,
        reservation_sha256=digest(encoded),
        facts_revision=digest(old),
    )
    # Actual _current validates the real row hash and pointer binding, but its
    # bounded SQL selection below is substituted; no imported fact is claimed.
    fields = {key: None for key in resources._HASH_FIELDS}
    fields.update(
        tenant_id=ctx.tenant_id,
        product_id=fixed.product_id,
        project_id=binding.project_id,
        build_id=binding.build_id,
        run_id=binding.run_id,
        request_id=binding.request_id,
        accepted_request_id=binding.accepted_request_id,
        accepted_request_revision=5,
        owner_id=ctx.actor_id,
        visibility="private",
        issuer_key=issuer.key,
        issuer_version=issuer.version,
        issuer_epoch=issuer.epoch,
        nature=issuer.nature,
        revision=1,
        external_id="fixed",
        series_id=uid(50),
        state="active",
        valid_from=binding.window.start - timedelta(hours=1),
        valid_until=binding.window.finish,
        binding=binding.model_dump(mode="json"),
        data={},
        sources=[],
        required_source_read_set=[],
        source_basis={},
        reason="fixed",
    )
    fields["id"] = fixed.fact_id
    fact = Fact(**fields)
    fact.fact_sha256 = resources._fact_hash(fact)
    pointer = Current(
        id=uid(51),
        tenant_id=ctx.tenant_id,
        product_id=fixed.product_id,
        project_id=binding.project_id,
        build_id=binding.build_id,
        request_id=binding.request_id,
        run_id=binding.run_id,
        fact_id=fact.id,
        fact_revision=1,
        epoch=1,
    )
    old["fact"] = fresh["fact"] = fact.fact_sha256
    saved["facts_revision"] = existing.facts_revision = digest(old)
    original.input_snapshot["resource_facts_revision"] = digest(old)
    product = Product(
        id=fixed.product_id,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        revision=1,
        lifecycle_epoch=1,
        status="draft",
        owner_id=ctx.actor_id,
    )
    person = Principal(
        id=ctx.actor_id, tenant_id=ctx.tenant_id, kind="human", active=True, access_epoch=1
    )
    grant = Grant(
        id=uid(52),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        principal_id=ctx.actor_id,
        can_write=True,
        access_epoch=1,
        expires_at=clock.at + timedelta(hours=3),
    )
    rows = {Current: pointer, Fact: fact, Product: product, Principal: person, Grant: grant}
    people, grants = {ctx.actor_id: person}, {ctx.actor_id: grant}
    query_reads, query_hooks = {}, []

    def selected(query):
        model = query.column_descriptions[0]["entity"]
        params = query.compile().params
        if model is Principal:
            return people[params["id_1"]]
        if model is Grant:
            person_id = params["principal_id_1"]
            query_reads[person_id] = query_reads.get(person_id, 0) + 1
            for hook in query_hooks:
                hook(person_id, query_reads[person_id])
            return grants[person_id]
        return rows[model]

    def scalars(query):
        return [selected(query)]

    monkeypatch.setattr(session, "scalars", scalars)
    monkeypatch.setattr(session, "scalar", selected)
    monkeypatch.setattr(session, "get", lambda model, key: rows[model])
    # Explicit substitutes for the public authority ports; this fixture never connects.
    from pdos_next import service as public_service
    from pdos_next.domain.professional_authority import service as professional

    def public_access(s, current_ctx, product_id, *, write=False, lock=False):
        assert s is session and product_id == product.id
        if (
            current_ctx.category_id != product.category_id
            or not person.active
            or (grant.expires_at is not None and grant.expires_at <= clock.at)
            or (write and not grant.can_write)
        ):
            raise DomainError("FORBIDDEN_SCOPE", "Explicit fixture authority revoked")
        return product

    def subject_access(s, current_ctx, product_id, subject_id):
        assert s is session and product_id == product.id
        current_grant = selected(select(Grant).where(Grant.principal_id == subject_id))
        return people[subject_id], current_grant

    monkeypatch.setattr(public_service, "require_access", public_access)
    monkeypatch.setattr(professional, "_subject_access", subject_access)
    monkeypatch.setattr(retained, "_human", lambda *a, **k: None)
    monkeypatch.setattr(retained.launch, "_version", lambda *a, **k: original)
    monkeypatch.setattr(retained.launch, "_snapshot", lambda row: (run, plan))
    historical = {"current": True, "facts_revision": "c" * 64}
    owner_io = SimpleNamespace(load=0, basis=0, authority=0, effect=0, hook=None)

    def basis(*args):
        owner_io.basis += 1
        return deepcopy(original.source_basis), False

    monkeypatch.setattr(retained.physical, "_basis", basis)

    def recheck(*args, **kwargs):
        owner_io.authority += 1
        if owner_io.hook:
            owner_io.hook(owner_io.authority)
        return deepcopy(historical)

    monkeypatch.setattr(retained.front, "_recheck", recheck)
    bundle = SimpleNamespace(
        report=report,
        facts_revision=digest(fresh),
        fact_ref=SimpleNamespace(
            id=fact.id, revision=1, epoch=1, sha256=fact.fact_sha256, nature="synthetic"
        ),
        required_source_read_set=(),
        nature="synthetic",
    )

    def load(*args, **kwargs):
        owner_io.load += 1
        assert kwargs["write"] is False and kwargs["retained"] is True
        assert kwargs["own_intent"] == original.intent_digest
        assert kwargs["verified_actual_start"] == actual
        assert kwargs["at"] == original.created_at
        collector = kwargs["_fingerprint_collector"]
        assert type(collector) is list and collector == []
        bundle.facts_revision = digest(fresh)
        collector.append({"material": deepcopy(fresh), "facts_revision": bundle.facts_revision})
        return bundle, None, request, None, None, None, existing

    monkeypatch.setattr(resources, "_load", load)
    effects = {
        "occupancy": [{"id": str(uid(40))}, {"id": str(uid(41))}],
        "sample_usage": [{"id": str(uid(42))}],
    }

    def saved_effects(*a, fresh=False):
        assert a[0] is session and session.info.get("read_snapshot") is not True
        assert fresh is True  # This real non-RR Session requires terminal fresh SQL.
        owner_io.effect += 1
        return deepcopy(effects)

    monkeypatch.setattr(retained.launch, "_saved_effects", saved_effects)
    work = SimpleNamespace(
        s=session,
        ctx=ctx,
        pid=fixed.product_id,
        row=original,
        old=old,
        fresh=fresh,
        original=original,
        existing=existing,
        bundle=bundle,
        issuer=issuer,
        effects=effects,
        grant=grant,
        person=person,
        clock=clock,
        io=owner_io,
        historical=historical,
        fact=fact,
        pointer=pointer,
        request=request,
        people=people,
        grants=grants,
        query_reads=query_reads,
        query_hooks=query_hooks,
    )
    yield work
    if session.in_transaction():
        session.rollback()
    session.close()
    engine.dispose()


def inspect(work):
    return retained.inspect_retained_execution(work.s, work.ctx, work.pid, work.row)


def denied(work, code):
    result = inspect(work)
    assert result["current"] is False and result["reason_codes"] == [code], result
    return result


def test_exact_single_dependency_keeps_saved_full_proof_and_one_load(work):
    original = deepcopy(work.original.input_snapshot)
    registry = work.s.get_bind()._pdos_test_resource_issuer_epochs.copy()
    result = inspect(work)
    assert result["current"] is True and result["reason_codes"] == [], result
    assert result["facts_revision"] == digest(work.old) != work.bundle.facts_revision
    assert result["reservation"] == original["reservation"]
    assert work.original.input_snapshot == original
    assert work.s.get_bind()._pdos_test_resource_issuer_epochs == registry
    assert work.io.load == work.io.effect == 1
    assert work.io.basis == work.io.authority == 2
    assert result["execution_window_elapsed"] is True  # History is not a new Start permission.


def test_no_mismatch_preserves_original_path_even_with_two_saved_keys(work):
    # Change the exact saved basis to the full two-key material, without guessing.
    sha = digest(work.fresh)
    work.original.input_snapshot["resource_facts_revision"] = sha
    work.original.input_snapshot["reservation"]["facts_revision"] = sha
    work.existing.facts_revision = sha
    result = inspect(work)
    assert result["current"] is True and result["facts_revision"] == sha, result


@pytest.mark.parametrize("field", ["resource_dependency_proof", "resource_fingerprint_version"])
def test_explicit_version_even_null_never_uses_legacy_fallback(work, field):
    work.original.input_snapshot[field] = None
    denied(work, "INTEGRATION_REQUIRED")


def test_previously_saved_two_keys_do_not_search_subsets(work):
    old = deepcopy(work.old)
    old["issuer_epochs"]["previous-other-key"] = 1
    sha = digest(old)
    work.original.input_snapshot["resource_facts_revision"] = sha
    work.original.input_snapshot["reservation"]["facts_revision"] = sha
    work.existing.facts_revision = sha
    denied(work, "RETAINED_EXECUTION_CHANGED")


@pytest.mark.parametrize("change", ["asset", "sample", "fact", "authority", "source", "check"])
def test_single_dependency_cannot_erase_other_material_changes(work, change):
    if change == "asset":
        work.fresh["assets"][0]["epoch"] += 1
    elif change == "sample":
        work.fresh["sample_epochs"][str(uid(7))] += 1
    elif change == "fact":
        work.fresh["fact"] = "d" * 64
    elif change == "authority":
        work.fresh["authority"]["qualified"] = False
    elif change == "source":
        work.fresh["source_basis"]["access"]["grant_epoch"] += 1
    else:
        work.fresh["checks"].append(
            {
                "resource": None,
                "code": "changed",
                "status": "UNKNOWN",
                "detail": "Actual new check",
                "source": None,
            }
        )
    result = inspect(work)
    assert result["current"] is False and result["reason_codes"], result


@pytest.mark.parametrize("field", ["resource_facts_revision", "result", "existing"])
def test_three_original_saved_fingerprints_must_all_match(work, field):
    if field == "resource_facts_revision":
        work.original.input_snapshot[field] = "d" * 64
    elif field == "result":
        work.original.input_snapshot["reservation"]["facts_revision"] = "d" * 64
    else:
        work.existing.facts_revision = "d" * 64
    denied(work, "RETAINED_EXECUTION_CHANGED")


@pytest.mark.parametrize(
    "change",
    [
        "kernel_hash",
        "kernel_body",
        "reservation_id",
        "owner_run",
        "occupancy",
        "usage",
        "duplicate",
    ],
)
def test_original_kernel_result_and_actual_effect_id_mismatch_is_rejected(work, change):
    if change == "kernel_hash":
        work.existing.reservation_sha256 = "d" * 64
    elif change == "kernel_body":
        work.existing.reservation["semantic_digest"] = "d" * 64
        work.existing.reservation_sha256 = digest(work.existing.reservation)
    elif change == "reservation_id":
        work.original.input_snapshot["reservation"]["reservation_id"] = str(uid(99))
    elif change == "owner_run":
        work.original.input_snapshot["reservation"]["owner_run_id"] = str(uid(99))
    elif change == "occupancy":
        work.effects["occupancy"][0]["id"] = str(uid(99))
    elif change == "usage":
        work.effects["sample_usage"][0]["id"] = str(uid(99))
    else:
        work.original.input_snapshot["reservation"]["occupancy_ids"] = [str(uid(40)), str(uid(40))]
    denied(work, "RETAINED_EXECUTION_CHANGED")


@pytest.mark.parametrize("status", ["UNKNOWN", "BLOCKED"])
def test_unknown_or_blocked_report_precedes_fingerprint_recovery(work, status):
    work.bundle.report = work.bundle.report.model_copy(update={"status": status})
    denied(work, "RETAINED_EXECUTION_CHANGED")
    assert work.io.effect == 0


@pytest.mark.parametrize("epoch", [True, 2])
def test_current_epoch_map_must_match_real_opaque_fixed_issuer(work, epoch):
    work.s.get_bind()._pdos_test_resource_issuer_epochs[work.issuer.key] = epoch
    denied(work, "RETAINED_EXECUTION_CHANGED")


def test_actual_issuer_disable_restore_aba_cannot_reuse_old_fact(work):
    engine = work.s.get_bind()
    resources.disable_issuer(engine, work.issuer.key)
    restored = resources.configure_local_synthetic(
        engine,
        key=work.issuer.key,
        version=work.issuer.version,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.fact.project_id,
        enabled=True,
        test_marker_verified=True,
    )
    assert restored.epoch > work.issuer.epoch
    denied(work, "RETAINED_EXECUTION_CHANGED")


@pytest.mark.parametrize(
    "change",
    ["caller_expiry", "caller_epoch", "issuer_epoch", "issuer_scope", "authority", "source", "uow"],
)
def test_post_all_owner_io_change_never_returns_affirmative(work, change, monkeypatch):
    def hook(round):
        if round != 2:
            return
        if change == "caller_expiry":
            work.clock.at = work.grant.expires_at
        elif change == "caller_epoch":
            work.person.access_epoch += 1
        elif change == "issuer_epoch":
            work.s.get_bind()._pdos_test_resource_issuer_epochs[work.issuer.key] += 1
        elif change == "issuer_scope":
            resources.disable_issuer(work.s.get_bind(), work.issuer.key)
        elif change == "authority":
            work.historical["current"] = False
        elif change == "source":
            monkeypatch.setattr(retained.physical, "_basis", lambda *a: ({"changed": True}, False))
            work.s.get_bind()._pdos_security_runtime = object()
        else:
            work.s.rollback()
            work.s.begin()

    work.io.hook = hook
    result = inspect(work)
    assert result["current"] is False and result["reason_codes"], result


def test_fake_session_and_inactive_real_uow_are_not_proof(work):
    fake = SimpleNamespace(get_bind=lambda: work.s.get_bind(), no_autoflush=work.s.no_autoflush)
    result = retained.inspect_retained_execution(fake, work.ctx, work.pid, work.row)
    assert result["current"] is False and result["reason_codes"] == ["FACT_ACTIVE_SESSION_REQUIRED"]
    work.s.rollback()
    denied(work, "FACT_ACTIVE_TRANSACTION_REQUIRED")


@pytest.mark.parametrize("field", ["resource_dependency_proof", "resource_fingerprint_version"])
def test_explicit_version_with_same_sha_is_still_missing_owner(work, field):
    sha = digest(work.fresh)
    work.original.input_snapshot["resource_facts_revision"] = sha
    work.original.input_snapshot["reservation"]["facts_revision"] = sha
    work.existing.facts_revision = sha
    work.original.input_snapshot[field] = None
    denied(work, "INTEGRATION_REQUIRED")
    assert work.io.load == work.io.effect == 0


def add_live_reader(work, identity, *, expires_at=None):
    work.people[identity] = Principal(
        id=identity, tenant_id=work.ctx.tenant_id, kind="human", active=True, access_epoch=1
    )
    work.grants[identity] = Grant(
        id=uid(identity.int + 100),
        tenant_id=work.ctx.tenant_id,
        category_id=work.ctx.category_id,
        principal_id=identity,
        can_write=False,
        access_epoch=1,
        expires_at=expires_at or work.clock.at + timedelta(hours=3),
    )


def different_signer_and_maker(work):
    add_live_reader(work, uid(80), expires_at=work.clock.at + timedelta(seconds=1))
    add_live_reader(work, uid(90))
    work.original.authority_snapshot["subject_id"] = str(uid(80))
    work.fact.owner_id = uid(90)
    work.fact.visibility = "category"
    work.fact.fact_sha256 = resources._fact_hash(work.fact)
    work.old["fact"] = work.fresh["fact"] = work.fact.fact_sha256
    work.bundle.fact_ref.sha256 = work.fact.fact_sha256
    sha = digest(work.old)
    work.original.input_snapshot["resource_facts_revision"] = sha
    work.original.input_snapshot["reservation"]["facts_revision"] = sha
    work.existing.facts_revision = sha


def test_retained_read_checks_consumer_access_and_keeps_fixed_signer_maker_provenance(work):
    different_signer_and_maker(work)
    result = inspect(work)
    assert result["current"] is True, result
    assert work.query_reads == {uid(6): 2}


def test_original_signer_grant_expiry_does_not_erase_historical_qualification(work):
    different_signer_and_maker(work)
    work.clock.at = work.grants[uid(80)].expires_at
    result = inspect(work)
    assert result["current"] is True, result
    assert uid(80) not in work.query_reads and uid(90) not in work.query_reads
    assert work.clock.at < work.grants[uid(6)].expires_at


def test_fact_maker_grant_expiry_is_independent_of_current_consumer(work, monkeypatch):
    different_signer_and_maker(work)
    work.grants[uid(80)].expires_at = work.clock.at + timedelta(hours=3)
    work.grants[uid(90)].expires_at = work.clock.at + timedelta(seconds=1)
    same_uow = retained._same_uow

    def finish(*args):
        same_uow(*args)
        work.clock.at = work.grants[uid(90)].expires_at

    monkeypatch.setattr(retained, "_same_uow", finish)
    result = inspect(work)
    assert result["current"] is True, result
    assert work.clock.at < work.grants[uid(6)].expires_at


def test_fact_maker_access_epoch_change_does_not_rewrite_signed_provenance(work):
    different_signer_and_maker(work)
    work.io.hook = lambda round: (
        setattr(work.grants[uid(90)], "access_epoch", 2) if round == 2 else None
    )
    result = inspect(work)
    assert result["current"] is True, result
    assert work.grants[uid(90)].access_epoch == 2 and uid(90) not in work.query_reads
