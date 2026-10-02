"""Recovery on real PostgreSQL; execute only on a newly assigned exclusive test DB.

No migrations, cleanup, SQL/auth/domain doubles or external ERP. The only patch is
an audit fault after actual SQL. Canonical Issue closure integration belongs to the
coordinator and is explicitly asserted before its joint scenarios.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Generator, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from functools import partial
from inspect import signature, unwrap
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text, update

from app.db.schema import tables
from app.domain.issues import IssueCloseNotVerifierError, IssueService, IssueUpdate
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_allocations import (
    AllocationRelease,
    MaterialAllocationError,
    MaterialAllocationService,
)
from app.domain.material_coverage import CoverageSelection, MaterialCoverageService
from app.domain.material_exceptions import (
    ExceptionCreate,
    ExceptionReview,
    MaterialClosureReference,
    MaterialExceptionService,
    validate_material_issue_closure,
)
from app.domain.material_movements import (
    MaterialMovementService,
    MaterialReconciliationService,
    MovementApply,
    MovementDraft,
    ReconciliationDraft,
    ReconciliationSelection,
)
from app.domain.npi_execution import NpiExecutionService
from app.domain.supply_sharing import ShareDecision, ShareOffer, SupplySharingService
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft, WrittenEventAudit
from tests.test_parallel_supply_postgres import (
    BuildDemand,
    allocate,
    counts,
    freeze_demand,
    publish_calendar,
    seed_supply_and_accept_share,
)
from tests.test_supplier_replies_postgres import (
    SupplyPostgresScope,
    isolated_postgres_url,
    postgres_engine,
)
from tests.test_supplier_replies_postgres import (
    supply_postgres_scope as base_scope,
)


@pytest.fixture
def recovery_scope() -> Iterator[SupplyPostgresScope]:
    # Both guards execute BEFORE advancing the base generator or opening an Engine.
    isolated_postgres_url()
    assert os.getenv("PDOS_MATERIAL_RECOVERY_TEST_ISOLATED") == "1", (
        "Coordinator must explicitly assign and verify the exclusive recovery test database"
    )
    generator = cast(Callable[[], Generator[SupplyPostgresScope, None, None]], unwrap(base_scope))()
    try:
        yield next(generator)
    finally:
        generator.close()


def capture(
    s: SupplyPostgresScope,
    quantity: int,
    sequence: int,
    *,
    quality: str = "released",
    expired: bool = False,
) -> UUID:
    """Only synthetic captured source registrations, with real source SQL guards."""
    document = s.document_for(s.project, f"synthetic-ERP-balance-{sequence}.xlsx")
    batch, snapshot = uuid4(), uuid4()
    as_of = s.now + timedelta(seconds=sequence - 30)
    fresh_until = s.now - timedelta(seconds=10) if expired else s.now + timedelta(days=1)
    with s.engine.begin() as c:
        digest = c.execute(
            select(tables.documents.c.sha256).where(
                tables.documents.c.tenant_id == s.owner.tenant.id,
                tables.documents.c.id == document,
            )
        ).scalar_one()
        c.execute(
            tables.supply_import_batches.insert().values(
                id=batch,
                tenant_id=s.owner.tenant.id,
                project_id=s.project,
                document_id=document,
                document_digest=digest,
                source_system="synthetic-postgres",
                source_version=str(uuid4()),
                as_of=as_of,
                fresh_until=fresh_until,
                captured_at=s.now,
                configuration={"coverage": "synthetic single pool"},
                content_digest="b" * 64,
                created_by_user_id=s.owner.user.id,
                request_id=uuid4(),
                request_digest="c" * 64,
                reason="Authorized synthetic fixture; no real ERP call",
                row_count=1,
                ignored_rows=[],
            )
        )
        c.execute(
            tables.supply_snapshots.insert().values(
                id=snapshot,
                tenant_id=s.owner.tenant.id,
                project_id=s.project,
                batch_id=batch,
                external_pool_id="POOL-1",
                external_item_id="MAT-01",
                quantity=quantity,
                unit="pcs",
                availability="known",
                supply_kind="on_hand",
                quality_status=quality,
                source_row=2,
                raw_cells={"A2": "MAT-01"},
                contract={
                    "id": str(snapshot),
                    "tenant_id": str(s.owner.tenant.id),
                    "scope": {"kind": "project", "ref_id": str(s.project)},
                    "source_system": "synthetic-postgres",
                    "external_item_id": "MAT-01",
                    "unit": "pcs",
                    "availability": "known",
                    "quantity": str(quantity),
                    "as_of": as_of.isoformat(),
                    "fresh_until": fresh_until.isoformat(),
                    "sources": [{"ref_id": str(document), "digest": digest}],
                },
            )
        )
    return snapshot


def coverage(s: SupplyPostgresScope, demand: BuildDemand) -> dict[str, Any]:
    return MaterialCoverageService(s.engine).preview(
        s.owner, demand.project, demand.build, CoverageSelection()
    )


def exception(s: SupplyPostgresScope, demand: BuildDemand) -> tuple[UUID, UUID]:
    observed = coverage(s, demand)
    command = ExceptionCreate.model_validate(
        dict(
            request_id=uuid4(),
            material_key=observed["materials"][0]["material_key"],
            expected_digest=observed["digest"],
            selection=CoverageSelection(),
            title="Synthetic original supply exception",
            severity="high",
            reason="Original fixed demand exceeds assigned qualified stock",
        )
    )
    service = MaterialExceptionService(s.engine)
    saved = service.create(s.owner, demand.project, demand.build, command)
    assert service.create(s.owner, demand.project, demand.build, command)["id"] == saved["id"]
    before = counts(s, tables.material_exceptions, tables.issues, tables.events, tables.audit_log)
    with pytest.raises(MaterialAllocationError, match="已有异常"):
        service.create(
            s.owner,
            demand.project,
            demand.build,
            ExceptionCreate.model_validate({**command.model_dump(), "request_id": uuid4()}),
        )
    assert (
        counts(s, tables.material_exceptions, tables.issues, tables.events, tables.audit_log)
        == before
    )
    return UUID(saved["id"]), UUID(saved["issue_id"])


def review_command(
    s: SupplyPostgresScope, demand: BuildDemand, identity: UUID, disposition: str
) -> ExceptionReview:
    detail = MaterialExceptionService(s.engine).get(s.owner, demand.project, identity)
    return ExceptionReview.model_validate(
        dict(
            request_id=uuid4(),
            expected_version=detail["latest"]["version"],
            expected_digest=detail["current"]["digest"],
            selection=detail["current"]["basis"]["selection"],
            disposition=disposition,
            reason="Named current-source recovery check",
        )
    )


def movement(
    s: SupplyPostgresScope,
    demand: BuildDemand,
    allocation: str,
    *,
    kind: str = "issued",
    parent: UUID | None = None,
    quantity: int = 2,
) -> dict[str, Any]:
    # Between capture sequence 1 and 3, so the new balance can reflect this movement.
    draft = MovementDraft.model_validate(
        dict(
            kind=kind,
            allocation_id=allocation,
            parent_id=parent,
            quantity=quantity,
            occurred_at=s.now - timedelta(seconds=28),
            transaction_reference=f"SYNTHETIC-{kind}:{uuid4()}",
            evidence_id=s.document,
            reason="Actual synthetic movement row, no ERP write",
        )
    )
    service = MaterialMovementService(s.engine)
    observed = service.preview(s.owner, demand.project, demand.build, draft)
    return service.apply(
        s.owner,
        demand.project,
        demand.build,
        MovementApply.model_validate(
            {**draft.model_dump(), "request_id": uuid4(), "expected_digest": observed["digest"]}
        ),
    )


def before_reconciliation(
    s: SupplyPostgresScope,
) -> tuple[BuildDemand, UUID, UUID, dict[str, Any], UUID]:
    demand = freeze_demand(s, s.project, publish_calendar(s))
    original = capture(s, 4, 1)
    allocate(s, s.owner, demand, original, 4)
    identity, issue = exception(s, demand)
    state = MaterialAllocationService(s.engine).get(s.owner, demand.project, demand.build)
    issued = movement(s, demand, state["allocations"][0]["id"])
    current = coverage(s, demand)
    assert not current["kit"]["ready"]
    assert Decimal(current["materials"][0]["qualified_issued"]) == 2
    command = review_command(s, demand, identity, "follow_up")
    MaterialExceptionService(s.engine).review(s.owner, demand.project, identity, command)
    updated = capture(s, 6, 3)  # Two received units + six in ERP balance can cover eight.
    return demand, identity, issue, issued, updated


def reconciliation_command(
    s: SupplyPostgresScope, issued: dict[str, Any], source: UUID, *, actor: Any = None
) -> ReconciliationDraft:
    selection = ReconciliationSelection(
        supply_snapshot_id=source,
        outcome="confirmed",
        evidence_id=s.document,
        reason="Original transaction included in the new ERP balance",
    )
    observed = MaterialReconciliationService(s.engine).preview(
        actor or s.owner, s.project, UUID(issued["id"]), selection
    )
    assert observed["eligible"]
    return ReconciliationDraft.model_validate(
        {
            **selection.model_dump(),
            "request_id": uuid4(),
            "expected_version": observed["basis"]["previous_version"],
            "expected_digest": observed["digest"],
        }
    )


def restored(
    s: SupplyPostgresScope,
) -> tuple[BuildDemand, UUID, UUID, dict[str, Any], UUID, MaterialClosureReference]:
    demand, identity, issue, issued, source = before_reconciliation(s)
    service = MaterialReconciliationService(s.engine)
    command = reconciliation_command(s, issued, source)
    saved = service.apply(s.owner, s.project, UUID(issued["id"]), command)
    assert service.apply(s.owner, s.project, UUID(issued["id"]), command)["id"] == saved["id"]
    state = MaterialAllocationService(s.engine).get(s.owner, demand.project, demand.build)
    assert Decimal(state["pools"][0]["pending_issue_quantity"]) == 0
    assert Decimal(state["pools"][0]["available_quantity"]) == 4
    allocate(s, s.owner, demand, source, 4)
    assert coverage(s, demand)["kit"]["ready"]
    command_review = review_command(s, demand, identity, "supply_ready")
    reviews = MaterialExceptionService(s.engine)
    saved_review = reviews.review(s.owner, demand.project, identity, command_review)
    assert (
        reviews.review(s.owner, demand.project, identity, command_review)["id"]
        == saved_review["id"]
    )
    detail = reviews.get(s.owner, demand.project, identity)
    assert detail["exception"]["issue_id"] == str(issue)
    assert detail["issue"]["status"] == "open"
    assert detail["closure"]["ready"]
    assert counts(s, tables.material_exceptions, tables.issues) == (1, 1)
    return (
        demand,
        identity,
        issue,
        issued,
        source,
        MaterialClosureReference.model_validate(detail["closure"]["reference"]),
    )


def check_reference(
    s: SupplyPostgresScope, demand: BuildDemand, issue: UUID, reference: MaterialClosureReference
) -> dict[str, Any]:
    with s.engine.begin() as c:
        NpiExecutionService._project(
            c, tenant_id=s.owner.tenant.id, project_id=demand.project, lock=True
        )
        return validate_material_issue_closure(
            c,
            tenant_id=s.owner.tenant.id,
            project_id=demand.project,
            issue_id=issue,
            actor_user_id=s.peer.user.id,
            expected_sources=[reference],
        )


def prepare_verification(s: SupplyPostgresScope, demand: BuildDemand, issue: UUID) -> None:
    service = IssueService(s.engine)
    service.update(
        tenant_id=s.owner.tenant.id,
        actor_user_id=s.owner.user.id,
        project_id=demand.project,
        issue_id=issue,
        patch=IssueUpdate(
            changes={
                "owner_user_id": s.engineer.user.id,
                "verifier_user_id": s.peer.user.id,
                "target_date": s.now.date() + timedelta(days=1),
                "closure_criteria": "Qualified supply covers fixed demand; named review is current",
                "root_cause": "Synthetic shortage",
                "resolution": "Named reconciliation and assigned stock",
            }
        ),
    )
    for actor, status in ((s.owner, "analysis"), (s.owner, "action"), (s.engineer, "verification")):
        service.transition(
            tenant_id=s.owner.tenant.id,
            actor_user_id=actor.user.id,
            project_id=demand.project,
            issue_id=issue,
            to_status=status,
        )


def close_original(
    s: SupplyPostgresScope, demand: BuildDemand, issue: UUID, reference: MaterialClosureReference
) -> Any:
    assert "material_closures" in signature(IssueService.transition).parameters, (
        "Coordinator must integrate typed current-source guard in the canonical Issue transaction"
    )
    with s.engine.connect() as c:
        updated_at = c.execute(
            select(tables.issues.c.updated_at).where(
                tables.issues.c.tenant_id == s.owner.tenant.id, tables.issues.c.id == issue
            )
        ).scalar_one()
    extra: dict[str, Any] = {"material_closures": [reference]}
    return IssueService(s.engine).transition(
        tenant_id=s.owner.tenant.id,
        actor_user_id=s.peer.user.id,
        project_id=demand.project,
        issue_id=issue,
        to_status="closed",
        expected_updated_at=updated_at,
        closure_evidence_ref=f"material_exception:{reference.exception_id}:review:{reference.review_id}",
        comment="Named four-eye verification of original recovery",
        **extra,
    )


def test_shortage_partial_arrival_new_balance_recovery_and_original_issue_close(
    recovery_scope: SupplyPostgresScope,
) -> None:
    s = recovery_scope
    demand, identity, issue, _, _, reference = restored(s)
    assert check_reference(s, demand, issue, reference)["sources"][0]["review_id"] == str(
        reference.review_id
    )
    prepare_verification(s, demand, issue)
    assert "material_closures" in signature(IssueService.transition).parameters, (
        "Coordinator must integrate the typed current-source closure contract"
    )
    extra: dict[str, Any] = {"material_closures": [reference]}
    with pytest.raises(IssueCloseNotVerifierError):
        IssueService(s.engine).transition(
            tenant_id=s.owner.tenant.id,
            actor_user_id=s.owner.user.id,
            project_id=demand.project,
            issue_id=issue,
            to_status="closed",
            closure_evidence_ref="No substitution for named verifier",
            **extra,
        )
    closed = close_original(s, demand, issue, reference)
    assert closed.id == issue and closed.status == "closed"
    assert counts(s, tables.material_exceptions, tables.issues) == (1, 1)
    detail = MaterialExceptionService(s.engine).get(s.owner, demand.project, identity)
    assert [row["version"] for row in detail["history"]] == [3, 2, 1]
    with s.engine.connect() as c:
        audit = (
            c.execute(
                select(tables.audit_log).where(
                    tables.audit_log.c.tenant_id == s.owner.tenant.id,
                    tables.audit_log.c.action == "issue.transition",
                    tables.audit_log.c.after_snapshot["status"].as_string() == "closed",
                )
            )
            .mappings()
            .one()
        )
        assert str(reference.review_id) in str(audit["context"])


@pytest.mark.parametrize(
    "drift", ["freeze", "expired", "document", "confirmation_evidence", "return"]
)
def test_old_recovery_reference_rejects_changed_supply_without_issue_or_audit_write(
    recovery_scope: SupplyPostgresScope,
    drift: str,
) -> None:
    s = recovery_scope
    demand, _, issue, issued, source, reference = restored(s)
    prepare_verification(s, demand, issue)
    if drift in {"freeze", "expired"}:
        capture(
            s,
            6,
            4,
            quality="frozen" if drift == "freeze" else "released",
            expired=drift == "expired",
        )
    elif drift == "confirmation_evidence":
        with s.engine.begin() as c:
            c.execute(
                update(tables.documents)
                .where(
                    tables.documents.c.tenant_id == s.owner.tenant.id,
                    tables.documents.c.id == s.document,
                )
                .values(sha256="f" * 64)
            )
    elif drift == "document":
        with s.engine.begin() as c:
            batch = c.execute(
                select(tables.supply_snapshots.c.batch_id).where(
                    tables.supply_snapshots.c.tenant_id == s.owner.tenant.id,
                    tables.supply_snapshots.c.id == source,
                )
            ).scalar_one()
            document = c.execute(
                select(tables.supply_import_batches.c.document_id).where(
                    tables.supply_import_batches.c.tenant_id == s.owner.tenant.id,
                    tables.supply_import_batches.c.id == batch,
                )
            ).scalar_one()
            c.execute(
                update(tables.documents)
                .where(
                    tables.documents.c.tenant_id == s.owner.tenant.id,
                    tables.documents.c.id == document,
                )
                .values(sha256="f" * 64)
            )
    else:
        movement(
            s,
            demand,
            issued["allocation_id"],
            kind="returned",
            parent=UUID(issued["id"]),
            quantity=1,
        )
    before = counts(s, tables.events, tables.audit_log, tables.material_exception_reviews)
    with pytest.raises(MaterialAllocationError):
        check_reference(s, demand, issue, reference)
    with pytest.raises(MaterialAllocationError):
        close_original(s, demand, issue, reference)
    assert counts(s, tables.events, tables.audit_log, tables.material_exception_reviews) == before
    with s.engine.connect() as c:
        assert (
            c.execute(
                select(tables.issues.c.status).where(
                    tables.issues.c.tenant_id == s.owner.tenant.id, tables.issues.c.id == issue
                )
            ).scalar_one()
            == "verification"
        )


def test_two_connections_confirm_new_balance_once(recovery_scope: SupplyPostgresScope) -> None:
    s = recovery_scope
    demand, _, _, issued, source = before_reconciliation(s)
    command, ready = reconciliation_command(s, issued, source), Barrier(2)
    before = counts(s, tables.material_movement_reconciliations, tables.events, tables.audit_log)

    def submit() -> tuple[int, str]:
        engine = postgres_engine(s.url, pool_size=1)
        try:
            with engine.connect() as c:
                pid = int(c.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.wait(timeout=10)
            result = MaterialReconciliationService(engine).apply(
                s.owner, s.project, UUID(issued["id"]), command
            )
            return pid, result["id"]
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        values = [future.result(timeout=30) for future in futures]
    assert values[0][0] != values[1][0] and values[0][1] == values[1][1]
    assert counts(
        s, tables.material_movement_reconciliations, tables.events, tables.audit_log
    ) == tuple(n + 1 for n in before)
    pool = MaterialAllocationService(s.engine).get(s.owner, demand.project, demand.build)["pools"][
        0
    ]
    assert Decimal(pool["reserved_quantity"]) == 2 and Decimal(pool["available_quantity"]) == 4


@pytest.mark.parametrize("drift", ["reviewer", "permission", "source", "evidence"])
def test_balance_preview_binding_rejects_drift_without_partial_reconciliation(
    recovery_scope: SupplyPostgresScope,
    drift: str,
) -> None:
    s = recovery_scope
    _, _, _, issued, source = before_reconciliation(s)
    actor = s.peer if drift == "permission" else s.owner
    command = reconciliation_command(s, issued, source, actor=actor)
    if drift == "reviewer":
        actor = s.peer
    elif drift == "permission":
        with s.engine.begin() as c:
            c.execute(
                delete(tables.project_members).where(
                    tables.project_members.c.tenant_id == s.owner.tenant.id,
                    tables.project_members.c.project_id == s.project,
                    tables.project_members.c.user_id == actor.user.id,
                )
            )
    elif drift == "source":
        capture(s, 6, 4)
    else:
        with s.engine.begin() as c:
            c.execute(
                update(tables.documents)
                .where(
                    tables.documents.c.tenant_id == s.owner.tenant.id,
                    tables.documents.c.id == s.document,
                )
                .values(sha256="f" * 64)
            )
    before = counts(s, tables.material_movement_reconciliations, tables.events, tables.audit_log)
    with pytest.raises((MaterialAllocationError, KnowledgeAccessError)):
        MaterialReconciliationService(s.engine).apply(actor, s.project, UUID(issued["id"]), command)
    assert (
        counts(s, tables.material_movement_reconciliations, tables.events, tables.audit_log)
        == before
    )


@pytest.mark.parametrize("operation", ["reconciliation", "review", "closure"])
def test_real_recovery_audit_failure_rolls_back_and_same_request_recovers(
    recovery_scope: SupplyPostgresScope,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    s = recovery_scope
    if operation == "reconciliation":
        _, _, _, issued, source = before_reconciliation(s)
        command = reconciliation_command(s, issued, source)
        action: Callable[[], Any] = partial(
            MaterialReconciliationService(s.engine).apply,
            s.owner,
            s.project,
            UUID(issued["id"]),
            command,
        )
    else:
        demand, identity, issue, _, _, reference = restored(s)
        if operation == "review":
            review = review_command(s, demand, identity, "supply_ready")
            action = partial(
                MaterialExceptionService(s.engine).review, s.owner, demand.project, identity, review
            )
        else:
            prepare_verification(s, demand, issue)
            action = partial(close_original, s, demand, issue, reference)
    observed_tables = (
        tables.material_movement_reconciliations,
        tables.material_exception_reviews,
        tables.events,
        tables.audit_log,
    )
    before = counts(s, *observed_tables)
    original = EventAuditWriter.record

    def fault(self: EventAuditWriter, event: EventDraft, audit: AuditDraft) -> WrittenEventAudit:
        original(self, event, audit)
        raise RuntimeError("Injected recovery audit failure after real SQL")

    with monkeypatch.context() as patch:
        patch.setattr(EventAuditWriter, "record", fault)
        with pytest.raises(RuntimeError, match="Injected recovery audit failure"):
            action()
    assert counts(s, *observed_tables) == before
    if operation == "closure":
        with s.engine.connect() as c:
            assert (
                c.execute(
                    select(tables.issues.c.status).where(
                        tables.issues.c.tenant_id == s.owner.tenant.id, tables.issues.c.id == issue
                    )
                ).scalar_one()
                == "verification"
            )
    action()


def test_revoked_share_requires_current_grant_reallocation_and_original_recheck(
    recovery_scope: SupplyPostgresScope,
) -> None:
    s = recovery_scope
    demand = freeze_demand(s, s.other_project, publish_calendar(s))
    source = seed_supply_and_accept_share(s)
    allocate(s, s.peer, demand, source, 8)
    identity, issue = exception(s, demand)
    service = MaterialExceptionService(s.engine)
    service.review(
        s.owner, demand.project, identity, review_command(s, demand, identity, "supply_ready")
    )
    reference = MaterialClosureReference.model_validate(
        service.get(s.owner, demand.project, identity)["closure"]["reference"]
    )
    with s.engine.connect() as c:
        grant = (
            c.execute(
                select(tables.supply_share_grants).where(
                    tables.supply_share_grants.c.tenant_id == s.owner.tenant.id
                )
            )
            .mappings()
            .one()
        )
    sharing = SupplySharingService(s.engine)
    sharing.decide(
        s.owner,
        s.project,
        grant["id"],
        ShareDecision(
            request_id=uuid4(),
            expected_version=1,
            outcome="revoked",
            reason="Synthetic sharing revoked",
        ),
    )
    with pytest.raises(MaterialAllocationError):
        check_reference(s, demand, issue, reference)
    assert not coverage(s, demand)["kit"]["ready"]
    preview = sharing.options(s.owner, s.project, source)
    new = sharing.offer(
        s.owner,
        s.project,
        source,
        ShareOffer.model_validate(
            dict(
                request_id=uuid4(),
                expected_digest=preview["digest"],
                recipient_project_id=demand.project,
                recipient_user_id=s.peer.user.id,
                quantity_limit="12",
                expires_at=s.now + timedelta(hours=1),
                reason="New independently accepted authorization",
            )
        ),
    )
    sharing.decide(
        s.peer,
        demand.project,
        UUID(new["id"]),
        ShareDecision(
            request_id=uuid4(),
            expected_version=0,
            outcome="accepted",
            reason="Accept new exact source authorization",
        ),
    )
    assert not coverage(s, demand)["kit"]["ready"]  # Old allocation still binds the revoked grant.
    allocation_service = MaterialAllocationService(s.engine)
    state = allocation_service.get(s.peer, demand.project, demand.build)
    allocation_service.apply(
        s.peer,
        demand.project,
        demand.build,
        AllocationRelease.model_validate(
            dict(
                request_id=uuid4(),
                expected_digest=state["release_basis"],
                items=[dict(allocation_id=state["allocations"][0]["id"], quantity="8")],
                reason="Release revoked-grant allocation before reallocation under current grant",
            )
        ),
    )
    allocate(s, s.peer, demand, source, 8)
    service.review(
        s.owner, demand.project, identity, review_command(s, demand, identity, "supply_ready")
    )
    current = service.get(s.owner, demand.project, identity)
    fresh = MaterialClosureReference.model_validate(current["closure"]["reference"])
    assert current["closure"]["ready"] and fresh.review_id != reference.review_id
    assert check_reference(s, demand, issue, fresh)["sources"]
    with pytest.raises(MaterialAllocationError):
        check_reference(s, demand, issue, reference)
    assert counts(s, tables.material_exceptions, tables.issues) == (1, 1)
