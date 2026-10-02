"""Real supply pool and cost approval transactions on a coordinator-owned pdos_test.

Only source fixtures are seeded directly. Authorization, SQL guards, domain writes,
events and audit remain real; no migration, database cleanup or external ERP call.
"""

# ruff: noqa: F811 -- imported pytest fixture is intentionally used by name

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, func, select, text, update

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService, MaterialFreeze, MaterialSelection
from app.domain.cost_freezes import (
    CostFreezeService,
    FreezeDecide,
    FreezeDecision,
    FreezeDraft,
    FreezeRequest,
)
from app.domain.cost_inputs import CostInputService, InputApply, InputPreview, PriceDraft
from app.domain.cost_rollups import CostRollupService, RollupDraft, RollupSave
from app.domain.material_allocations import (
    AllocationApply,
    AllocationSelection,
    MaterialAllocationError,
    MaterialAllocationService,
)
from app.domain.material_coverage import CoverageSelection, MaterialCoverageService
from app.domain.material_movements import MaterialMovementService, MovementApply, MovementDraft
from app.domain.plan_scenarios import CalendarDraft, PlanScenarioService
from app.domain.product_workspace import ProductWorkError
from app.domain.schedule_nodes import NodeDraft, ScheduleNodeService
from app.domain.supply_sharing import ShareDecision, ShareOffer, SupplySharingService
from tests.test_supplier_replies_postgres import (
    SupplyPostgresScope,
    postgres_engine,
    supply_postgres_scope,  # noqa: F401 -- explicitly reuse the guarded fixture
)


def counts(scope: SupplyPostgresScope, *selected: Table) -> tuple[int, ...]:
    with scope.engine.connect() as c:
        return tuple(
            int(
                c.execute(
                    select(func.count())
                    .select_from(t)
                    .where(t.c.tenant_id == scope.owner.tenant.id)
                ).scalar_one()
            )
            for t in selected
        )


def seed_bom(scope: SupplyPostgresScope, project: UUID, kind: str) -> tuple[UUID, UUID]:
    bom = scope.insert(
        tables.development_boms,
        project_id=project,
        created_by_user_id=scope.owner.user.id,
        bom_type=kind,
        code=f"{kind}-BOM",
        name="Synthetic single material BOM",
    )
    item = scope.insert(
        tables.development_bom_items,
        project_id=project,
        bom_id=bom,
        line_number=1,
        part_number="PART-01",
        description="Synthetic part",
        quantity=Decimal(2) if kind == "cost" else Decimal(1),
        unit="pcs",
        material_reference="MAT-01",
    )
    return bom, item


def publish_calendar(scope: SupplyPostgresScope) -> UUID:
    value = PlanScenarioService(scope.engine).publish_calendar(
        scope.owner,
        CalendarDraft.model_validate(
            dict(
                request_id=uuid4(),
                expected_version=0,
                name="Synthetic supply calendar",
                timezone="UTC",
                working_weekdays=[0, 1, 2, 3, 4],
                intervals=[dict(start_minute=540, end_minute=1020)],
                reason="Isolated supply fixture",
            )
        ),
    )
    return UUID(value["id"])


@dataclass(frozen=True)
class BuildDemand:
    project: UUID
    build: UUID
    item: UUID
    revision: UUID


def freeze_demand(scope: SupplyPostgresScope, project: UUID, calendar: UUID) -> BuildDemand:
    with scope.engine.connect() as c:
        original = (
            c.execute(
                select(tables.projects).where(
                    tables.projects.c.tenant_id == scope.owner.tenant.id,
                    tables.projects.c.id == project,
                )
            )
            .mappings()
            .one()
        )
    build = scope.insert(
        tables.build_batches,
        project_id=project,
        workflow_id=original["workflow_id"],
        stage_id=original["current_stage_id"],
        created_by_user_id=scope.owner.user.id,
        phase="evt",
        code="SUPPLY-BUILD",
        planned_quantity=8,
    )
    bom, item = seed_bom(scope, project, "prototype")
    nodes = ScheduleNodeService(scope.engine)
    source = next(v for v in nodes.get(scope.owner, project)["sources"] if v["id"] == str(build))
    node = nodes.register(
        scope.owner,
        project,
        NodeDraft.model_validate(
            dict(
                request_id=uuid4(),
                node_kind="build",
                source_id=build,
                expected_source_digest=source["source_digest"],
                calendar_version_id=calendar,
            )
        ),
    )
    service = BuildMaterialService(scope.engine)
    draft = MaterialSelection(
        bom_id=bom, need_by_node_id=UUID(node["id"]), critical_item_ids=[item]
    )
    observed = service.preview(scope.owner, project, build, draft)
    saved = service.freeze(
        scope.owner,
        project,
        build,
        MaterialFreeze.model_validate(
            {
                **draft.model_dump(),
                "request_id": uuid4(),
                "expected_digest": observed["digest"],
                "reason": "Fix synthetic Build demand",
            }
        ),
    )
    return BuildDemand(project, build, item, UUID(saved["id"]))


def seed_supply_and_accept_share(scope: SupplyPostgresScope) -> UUID:
    """Register one synthetic captured pool; share this exact row, never copy inventory."""
    batch, snapshot = uuid4(), uuid4()
    with scope.engine.begin() as c:
        document = (
            c.execute(
                select(tables.documents).where(
                    tables.documents.c.tenant_id == scope.owner.tenant.id,
                    tables.documents.c.id == scope.document,
                )
            )
            .mappings()
            .one()
        )
        c.execute(
            tables.supply_import_batches.insert().values(
                id=batch,
                tenant_id=scope.owner.tenant.id,
                project_id=scope.project,
                document_id=scope.document,
                document_digest=document["sha256"],
                source_system="synthetic-postgres",
                source_version=str(uuid4()),
                as_of=scope.now,
                fresh_until=scope.now + timedelta(days=1),
                captured_at=scope.now,
                configuration={"coverage": "synthetic single pool"},
                content_digest="b" * 64,
                created_by_user_id=scope.owner.user.id,
                request_id=uuid4(),
                request_digest="c" * 64,
                reason="Synthetic captured inventory; no real ERP import",
                row_count=1,
                ignored_rows=[],
            )
        )
        c.execute(
            tables.supply_snapshots.insert().values(
                id=snapshot,
                tenant_id=scope.owner.tenant.id,
                project_id=scope.project,
                batch_id=batch,
                external_pool_id="POOL-1",
                external_item_id="MAT-01",
                quantity=Decimal(12),
                unit="pcs",
                availability="known",
                supply_kind="on_hand",
                quality_status="released",
                source_row=2,
                raw_cells={"A2": "MAT-01"},
                contract={
                    "id": str(snapshot),
                    "tenant_id": str(scope.owner.tenant.id),
                    "scope": {"kind": "project", "ref_id": str(scope.project)},
                    "source_system": "synthetic-postgres",
                    "external_item_id": "MAT-01",
                    "unit": "pcs",
                    "availability": "known",
                    "quantity": "12",
                    "as_of": scope.now.isoformat(),
                    "fresh_until": (scope.now + timedelta(days=1)).isoformat(),
                    "sources": [{"ref_id": str(scope.document), "digest": document["sha256"]}],
                },
            )
        )
    service = SupplySharingService(scope.engine)
    observed = service.options(scope.owner, scope.project, snapshot)
    grant = service.offer(
        scope.owner,
        scope.project,
        snapshot,
        ShareOffer.model_validate(
            dict(
                request_id=uuid4(),
                expected_digest=observed["digest"],
                recipient_project_id=scope.other_project,
                recipient_user_id=scope.peer.user.id,
                quantity_limit="12",
                expires_at=scope.now + timedelta(hours=12),
                reason="Synthetic project sharing",
            )
        ),
    )
    action = service.decide(
        scope.peer,
        scope.other_project,
        UUID(grant["id"]),
        ShareDecision(
            request_id=uuid4(),
            expected_version=0,
            outcome="accepted",
            reason="Recipient accepts the original inventory scope",
        ),
    )
    assert action["outcome"] == "accepted"
    return snapshot


def allocation(demand: BuildDemand, source: UUID, quantity: int) -> AllocationSelection:
    return AllocationSelection.model_validate(
        dict(
            revision_id=demand.revision,
            items=[dict(bom_item_id=demand.item, supply_snapshot_id=source, quantity=quantity)],
        )
    )


def allocate(
    scope: SupplyPostgresScope, actor: AuthContext, demand: BuildDemand, source: UUID, quantity: int
) -> dict[str, Any]:
    service = MaterialAllocationService(scope.engine)
    draft = allocation(demand, source, quantity)
    observed = service.preview(actor, demand.project, demand.build, draft)
    return service.apply(
        actor,
        demand.project,
        demand.build,
        AllocationApply.model_validate(
            {
                **draft.model_dump(),
                "request_id": uuid4(),
                "expected_digest": observed["digest"],
                "reason": "Allocate only the original pool",
            }
        ),
    )


def test_two_projects_and_unreconciled_issue_deduct_original_pool_once(
    supply_postgres_scope: SupplyPostgresScope,
) -> None:
    s = supply_postgres_scope
    calendar = publish_calendar(s)
    first, second = (
        freeze_demand(s, s.project, calendar),
        freeze_demand(s, s.other_project, calendar),
    )
    source = seed_supply_and_accept_share(s)
    allocate(s, s.owner, first, source, 6)
    allocate(s, s.peer, second, source, 4)
    service = MaterialAllocationService(s.engine)
    before = service.get(s.peer, second.project, second.build)
    assert len(before["pools"]) == 1
    assert Decimal(before["pools"][0]["reserved_quantity"]) == 10
    assert Decimal(before["pools"][0]["available_quantity"]) == 2
    active = service.get(s.owner, first.project, first.build)["allocations"][0]
    movement = MovementDraft.model_validate(
        dict(
            kind="issued",
            allocation_id=active["id"],
            quantity="2",
            occurred_at=s.now,
            transaction_reference="SYNTHETIC-ISSUE:line-1",
            evidence_id=s.document,
            reason="Synthetic issue awaiting ERP reconciliation",
        )
    )
    movements = MaterialMovementService(s.engine)
    preview = movements.preview(s.owner, first.project, first.build, movement)
    issued = movements.apply(
        s.owner,
        first.project,
        first.build,
        MovementApply.model_validate(
            {**movement.model_dump(), "request_id": uuid4(), "expected_digest": preview["digest"]}
        ),
    )
    assert issued["qualified"] is True
    after = service.get(s.peer, second.project, second.build)
    pool = after["pools"][0]
    assert pool["source"]["id"] == str(source)
    assert Decimal(pool["reserved_quantity"]) == 10
    assert Decimal(pool["pending_issue_quantity"]) == 2
    assert Decimal(pool["available_quantity"]) == 2
    own = service.get(s.owner, first.project, first.build)
    assert Decimal(own["allocations"][0]["remaining_quantity"]) == 4
    assert Decimal(own["lines"][0]["qualified_issued"]) == 2
    before_rejection = counts(
        s, tables.material_allocation_batches, tables.material_supply_allocations
    )
    with pytest.raises(MaterialAllocationError, match="共享来源|余量"):
        service.preview(s.peer, second.project, second.build, allocation(second, source, 3))
    assert (
        counts(s, tables.material_allocation_batches, tables.material_supply_allocations)
        == before_rejection
    )
    allocate(s, s.peer, second, source, 2)
    pool = service.get(s.peer, second.project, second.build)["pools"][0]
    assert Decimal(pool["reserved_quantity"]) == 12
    assert Decimal(pool["available_quantity"]) == 0
    assert counts(s, tables.supply_snapshots, tables.material_movements) == (1, 1)
    for actor, demand in ((s.owner, first), (s.peer, second)):
        coverage = MaterialCoverageService(s.engine).preview(
            actor, demand.project, demand.build, CoverageSelection()
        )
        assert coverage["kit"]["material_count"] == 1
        assert coverage["kit"]["ready"] is False
        assert coverage["kit"]["critical_ready"] is False


def test_two_projects_concurrently_compete_for_one_pool_without_oversubscription(
    supply_postgres_scope: SupplyPostgresScope,
) -> None:
    s = supply_postgres_scope
    calendar = publish_calendar(s)
    first, second = (
        freeze_demand(s, s.project, calendar),
        freeze_demand(s, s.other_project, calendar),
    )
    source, ready = seed_supply_and_accept_share(s), Barrier(2)
    service = MaterialAllocationService(s.engine)
    commands = []
    for actor, demand in ((s.owner, first), (s.peer, second)):
        draft = allocation(demand, source, 8)
        observed = service.preview(actor, demand.project, demand.build, draft)
        commands.append(
            (
                actor,
                demand,
                AllocationApply.model_validate(
                    {
                        **draft.model_dump(),
                        "request_id": uuid4(),
                        "expected_digest": observed["digest"],
                        "reason": "Concurrent claim on the same synthetic pool",
                    }
                ),
            )
        )

    def submit(
        actor: AuthContext, demand: BuildDemand, command: AllocationApply
    ) -> tuple[int, bool]:
        engine = postgres_engine(s.url, pool_size=1)
        try:
            with engine.connect() as c:
                pid = int(c.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.wait(timeout=10)
            try:
                MaterialAllocationService(engine).apply(
                    actor, demand.project, demand.build, command
                )
            except MaterialAllocationError:
                return pid, False
            return pid, True
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit, *command) for command in commands]
        results = [future.result(timeout=30) for future in futures]
    assert results[0][0] != results[1][0]
    assert sum(success for _, success in results) == 1
    assert counts(s, tables.material_allocation_batches, tables.material_supply_allocations) == (
        1,
        1,
    )
    for actor, demand in ((s.owner, first), (s.peer, second)):
        pool = service.get(actor, demand.project, demand.build)["pools"][0]
        assert Decimal(pool["reserved_quantity"]) == 8
        assert Decimal(pool["available_quantity"]) == 4


def price(
    scope: SupplyPostgresScope,
    item: UUID,
    *,
    stage: str = "estimate",
    unit: str = "pcs",
    amount: str = "3",
) -> PriceDraft:
    values: dict[str, Any] = dict(
        stage=stage,
        title="Synthetic material price",
        subsystem="hardware",
        category="material",
        basis="unit",
        currency="CNY",
        amount=amount,
        price_quantity="1",
        unit=unit,
        tax_basis="exclusive",
        freight_basis="included",
        scope_basis="Original Cost BOM",
        bom_item_id=item,
        evidence_id=scope.document,
        source_reference=f"synthetic-price:{item}",
        source_line="line-1",
        location="Sheet1!A2",
        as_of=scope.now.date(),
        reason="Synthetic price",
    )
    if stage == "quote":
        values.update(
            supplier_id=scope.supplier,
            valid_from=scope.now.date(),
            valid_until=(scope.now + timedelta(days=1)).date(),
            minimum_order_quantity="1",
        )
    if stage == "actual":
        values.update(actual_source="erp_snapshot", actual_quantity="1")
    return PriceDraft.model_validate(values)


def save_price(
    scope: SupplyPostgresScope, draft: PriceDraft, *, record: UUID | None = None, version: int = 0
) -> dict[str, Any]:
    identity = record or uuid4()
    service = CostInputService(scope.engine)
    observed = service.preview(scope.owner, scope.project, identity, InputPreview(draft=draft))
    return service.apply(
        scope.owner,
        scope.project,
        identity,
        InputApply(
            draft=draft,
            request_id=uuid4(),
            expected_version=version,
            expected_digest=observed["digest"],
        ),
    )


def save_rollup(
    scope: SupplyPostgresScope, bom: UUID, saved_price: dict[str, Any]
) -> dict[str, Any]:
    draft = RollupDraft.model_validate(
        dict(
            bom_id=bom,
            title="Synthetic bounded cost",
            stage="estimate",
            currency="CNY",
            as_of=scope.now.date(),
            product_quantity="10",
            product_unit="台",
            tax_basis="exclusive",
            freight_basis="included",
            rate_type="spot",
            max_rate_age_days=0,
            nre_policy="separate",
            quantity_basis="Ten products, two parts each",
            scope_basis="Selected Cost BOM material only",
            prices=[dict(input_id=saved_price["id"])],
        )
    )
    service = CostRollupService(scope.engine)
    observed = service.prepare(scope.owner, scope.project, draft)
    return service.save(
        scope.owner,
        scope.project,
        RollupSave(request_id=uuid4(), expected_digest=observed["digest"], draft=draft),
    )


def freeze_draft(scope: SupplyPostgresScope, calculation: dict[str, Any]) -> FreezeDraft:
    return FreezeDraft.model_validate(
        dict(
            rollup_id=calculation["id"],
            expected_calculation_digest=calculation["calculation_digest"],
            approver_user_id=scope.peer.user.id,
            evidence_id=scope.document,
            evidence_location="Synthetic authority p1",
            authority_basis="Named project manager approval",
            accepted_limits="Selected material estimate; no production or ERP actual claim",
            reason="Freeze the exact checked estimate",
        )
    )


@pytest.mark.parametrize("stage", ["estimate", "quote", "actual"])
def test_price_unit_mismatch_cannot_be_saved_in_any_cost_stage(
    supply_postgres_scope: SupplyPostgresScope,
    stage: str,
) -> None:
    s = supply_postgres_scope
    _, item = seed_bom(s, s.project, "cost")
    draft, record = price(s, item, stage=stage, unit="box"), uuid4()
    service = CostInputService(s.engine)
    before = counts(
        s,
        tables.cost_inputs,
        tables.events,
        tables.audit_log,
        tables.cost_freeze_requests,
        tables.cost_freezes,
    )
    with pytest.raises(ProductWorkError, match="计价单位"):
        service.preview(s.owner, s.project, record, InputPreview(draft=draft))
    with pytest.raises(ProductWorkError, match="计价单位"):
        service.apply(
            s.owner,
            s.project,
            record,
            InputApply(
                draft=draft, request_id=uuid4(), expected_version=0, expected_digest="0" * 64
            ),
        )
    assert (
        counts(
            s,
            tables.cost_inputs,
            tables.events,
            tables.audit_log,
            tables.cost_freeze_requests,
            tables.cost_freezes,
        )
        == before
    )


def test_changed_bom_unit_blocks_old_calculation_and_new_gap_from_freeze(
    supply_postgres_scope: SupplyPostgresScope,
) -> None:
    s = supply_postgres_scope
    bom, item = seed_bom(s, s.project, "cost")
    saved_price = save_price(s, price(s, item))
    old = save_rollup(s, bom, saved_price)
    assert old["result"]["complete"] is True
    with s.engine.begin() as c:
        c.execute(
            update(tables.development_bom_items)
            .where(
                tables.development_bom_items.c.tenant_id == s.owner.tenant.id,
                tables.development_bom_items.c.project_id == s.project,
                tables.development_bom_items.c.id == item,
            )
            .values(unit="box")
        )
    service = CostFreezeService(s.engine)
    with pytest.raises(ProductWorkError, match="变化"):
        service.preview(s.owner, s.project, freeze_draft(s, old))
    current = save_rollup(s, bom, saved_price)
    assert current["result"]["complete"] is False
    assert current["result"]["unit_total"] is None
    assert current["result"]["lines"][0]["value"] is None
    assert any("计价单位" in gap for gap in current["result"]["gaps"])
    before = counts(
        s, tables.cost_freeze_requests, tables.cost_freezes, tables.events, tables.audit_log
    )
    draft = freeze_draft(s, current)
    with pytest.raises(ProductWorkError, match="计算缺口"):
        service.preview(s.owner, s.project, draft)
    with pytest.raises(ProductWorkError, match="计算缺口"):
        service.request(
            s.owner,
            s.project,
            FreezeRequest.model_validate(
                {**draft.model_dump(), "request_id": uuid4(), "expected_digest": "0" * 64}
            ),
        )
    assert (
        counts(s, tables.cost_freeze_requests, tables.cost_freezes, tables.events, tables.audit_log)
        == before
    )


def test_correct_units_roll_up_then_named_approval_retains_frozen_cost_after_revision(
    supply_postgres_scope: SupplyPostgresScope,
) -> None:
    s = supply_postgres_scope
    bom, item = seed_bom(s, s.project, "cost")
    draft_price = price(s, item)
    saved_price = save_price(s, draft_price)
    calculation = save_rollup(s, bom, saved_price)
    assert calculation["result"]["complete"] is True
    assert Decimal(calculation["result"]["unit_total"]) == 6
    service, draft = CostFreezeService(s.engine), freeze_draft(s, calculation)
    observed = service.preview(s.owner, s.project, draft)
    requested = service.request(
        s.owner,
        s.project,
        FreezeRequest.model_validate(
            {**draft.model_dump(), "request_id": uuid4(), "expected_digest": observed["digest"]}
        ),
    )
    assert counts(s, tables.cost_freeze_requests, tables.cost_freezes) == (1, 0)
    identity = UUID(requested["id"])
    decision = FreezeDecision(
        action="approve",
        reason="Named approver checked original scope",
        scope_checked=True,
        cost_gap_checked=True,
        nre_checked=True,
    )
    with pytest.raises(ProductWorkError, match="指定的批准人"):
        service.preview_decision(s.owner, s.project, identity, decision)
    observed = service.preview_decision(s.peer, s.project, identity, decision)
    command = FreezeDecide.model_validate(
        {**decision.model_dump(), "request_id": uuid4(), "expected_digest": observed["digest"]}
    )
    approved = service.decide(s.peer, s.project, identity, command)
    assert service.decide(s.peer, s.project, identity, command)["id"] == approved["id"]
    assert counts(s, tables.cost_freeze_decisions, tables.cost_freezes) == (1, 1)
    with s.engine.connect() as c:
        frozen = dict(
            c.execute(
                select(tables.cost_freezes).where(
                    tables.cost_freezes.c.tenant_id == s.owner.tenant.id,
                    tables.cost_freezes.c.project_id == s.project,
                )
            )
            .mappings()
            .one()
        )
    assert frozen["version"] == 1 and frozen["approved_by_user_id"] == s.peer.user.id
    assert frozen["snapshot"]["calculation"]["id"] == calculation["id"]
    assert Decimal(frozen["snapshot"]["calculation"]["result"]["unit_total"]) == 6
    revised = save_price(
        s,
        PriceDraft.model_validate({**draft_price.model_dump(), "amount": "4"}),
        record=UUID(saved_price["record_id"]),
        version=1,
    )
    assert revised["version"] == 2
    assert Decimal(save_rollup(s, bom, revised)["result"]["unit_total"]) == 8
    with s.engine.connect() as c:
        retained = dict(
            c.execute(
                select(tables.cost_freezes).where(
                    tables.cost_freezes.c.tenant_id == s.owner.tenant.id,
                    tables.cost_freezes.c.id == frozen["id"],
                )
            )
            .mappings()
            .one()
        )
    assert retained == frozen
