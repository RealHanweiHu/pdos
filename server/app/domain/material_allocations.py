"""Version-bound supply allocations, partial releases and current kit coverage."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, or_, select, tuple_

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Quantity, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.material_supply_pools import PoolKey, lock_pools
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import _plain, digest

POLICY = "supply.manual_allocation.on_hand_kit.v1"


class MaterialAllocationError(ValueError):
    pass


class AllocationItem(Contract):
    bom_item_id: UUID
    supply_snapshot_id: UUID
    quantity: Quantity = Field(gt=0)


class AllocationSelection(Contract):
    revision_id: UUID
    items: list[AllocationItem] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_items(self) -> "AllocationSelection":
        if len({(item.bom_item_id, item.supply_snapshot_id) for item in self.items}) != len(
            self.items
        ):
            raise ValueError("同一需求与供给快照请合并为一个分配数量")
        return self


class AllocationApply(AllocationSelection):
    request_id: UUID
    expected_digest: Digest
    reason: Text


class ReleaseItem(Contract):
    allocation_id: UUID
    quantity: Quantity = Field(gt=0)


class AllocationRelease(Contract):
    request_id: UUID
    expected_digest: Digest
    items: list[ReleaseItem] = Field(min_length=1, max_length=200)
    reason: Text

    @model_validator(mode="after")
    def unique_items(self) -> "AllocationRelease":
        if len({item.allocation_id for item in self.items}) != len(self.items):
            raise ValueError("同一占用记录只能列一次释放数量")
        return self


def _key(row: Any) -> PoolKey:
    return row["source_system"], row["external_pool_id"], row["external_item_id"]


def _source_query(tenant_id: UUID) -> Any:
    s, b = tables.supply_snapshots, tables.supply_import_batches
    return (
        select(
            *(column for column in s.c if column.name not in {"raw_cells", "contract"}),
            b.c.source_system,
            b.c.source_version,
            b.c.as_of,
            b.c.fresh_until,
            b.c.captured_at,
            b.c.document_id,
            b.c.configuration["coverage"].as_string().label("coverage"),
        )
        .join(b, (b.c.tenant_id == s.c.tenant_id) & (b.c.id == s.c.batch_id))
        .where(s.c.tenant_id == tenant_id)
    )


def _active(
    c: Connection,
    tenant_id: UUID,
    *,
    project_id: UUID | None = None,
    build_id: UUID | None = None,
    keys: list[PoolKey] | None = None,
) -> list[dict[str, Any]]:
    from app.domain.material_movements import balances, received_lots

    a, r = tables.material_supply_allocations, tables.material_allocation_releases
    movements = balances(tenant_id)
    released = (
        select(r.c.allocation_id, func.sum(r.c.quantity).label("released"))
        .where(r.c.tenant_id == tenant_id)
        .group_by(r.c.allocation_id)
        .subquery()
    )
    issued = func.coalesce(movements.c.issued, 0)
    returned = func.coalesce(movements.c.returned, 0)
    scrapped = func.coalesce(movements.c.scrapped, 0)
    remaining = a.c.quantity - func.coalesce(released.c.released, 0) - issued
    query = (
        select(
            a,
            remaining.label("remaining_quantity"),
            issued.label("issued_quantity"),
            returned.label("returned_quantity"),
            scrapped.label("scrapped_quantity"),
            func.coalesce(movements.c.consumed, 0).label("consumed_quantity"),
            (
                func.coalesce(movements.c.consumed, 0)
                - func.coalesce(movements.c.consumed_disposed, 0)
            ).label("net_consumed_quantity"),
            (issued - returned - scrapped).label("received_quantity"),
            func.coalesce(movements.c.qualified_received, 0).label("qualified_received_quantity"),
        )
        .outerjoin(movements, movements.c.allocation_id == a.c.id)
        .outerjoin(released, released.c.allocation_id == a.c.id)
        .where(a.c.tenant_id == tenant_id, or_(remaining > 0, issued > 0))
    )
    if project_id is not None:
        query = query.where(a.c.project_id == project_id)
    if build_id is not None:
        query = query.where(a.c.build_id == build_id)
    if keys is not None:
        if not keys:
            return []
        query = query.where(
            tuple_(a.c.source_system, a.c.external_pool_id, a.c.external_item_id).in_(keys)
        )
    rows = [_plain(dict(row)) for row in c.execute(query.order_by(a.c.id)).mappings()]
    lots = received_lots(c, tenant_id, [UUID(row["id"]) for row in rows])
    for row in rows:
        row["received_lots"] = lots.get(row["id"], [])
    return rows


def _pools(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    keys: list[PoolKey],
    *,
    as_of: datetime | None = None,
) -> dict[PoolKey, dict[str, Any]]:
    observed_at = as_of or datetime.now(UTC)
    if not keys:
        return {}
    s, b = tables.supply_snapshots, tables.supply_import_batches
    rows = c.execute(
        _source_query(tenant_id)
        .where(tuple_(b.c.source_system, s.c.external_pool_id, s.c.external_item_id).in_(keys))
        .distinct(b.c.source_system, s.c.external_pool_id, s.c.external_item_id)
        .order_by(
            b.c.source_system,
            s.c.external_pool_id,
            s.c.external_item_id,
            b.c.as_of.desc(),
            b.c.captured_at.desc(),
            s.c.id.desc(),
        )
    ).mappings()
    latest = {_key(row): dict(row) for row in rows}
    from app.domain.supply_sharing import active_grant_query, shared_source

    grants = {
        row["supply_snapshot_id"]: dict(row)
        for row in c.execute(active_grant_query(tenant_id, project_id, observed_at)).mappings()
    }

    held: dict[PoolKey, list[dict[str, Any]]] = {}
    for row in _active(c, tenant_id, keys=keys):
        held.setdefault(_key(row), []).append(row)
    result: dict[PoolKey, dict[str, Any]] = {}
    for key in keys:
        source = latest.get(key)
        grant = grants.get(source["id"]) if source and source["project_id"] != project_id else None
        if source is None or (source["project_id"] != project_id and grant is None):
            result[key] = {
                "state": "current_source_unreadable",
                "source": None,
                "reserved_quantity": None,
                "available_quantity": None,
                "allocatable": False,
            }
            continue
        allocations = held.get(key, [])
        from app.domain.material_movements import pending_issued

        pending = pending_issued(
            c, tenant_id, [UUID(row["id"]) for row in allocations], source["id"]
        )

        def held_quantity(
            row: dict[str, Any], pending_quantities: dict[str, Decimal] = pending
        ) -> Decimal:
            return Decimal(row["remaining_quantity"]) + pending_quantities.get(
                row["id"], Decimal(0)
            )

        mismatch = any(
            row["unit"] != source["unit"] and held_quantity(row) > 0 for row in allocations
        )
        with localcontext() as context:
            context.prec = 64
            reserved = (
                sum((held_quantity(row) for row in allocations), Decimal(0))
                if not mismatch
                else None
            )
            quantity = source["quantity"]
            state = (
                "stale"
                if source["fresh_until"] <= observed_at
                else "unknown_quantity"
                if quantity is None
                else "unit_conflict"
                if mismatch
                else "overallocated"
                if reserved is not None and reserved > quantity
                else "quality_frozen"
                if source["quality_status"] == "frozen"
                else "current"
            )
            available = (
                max(quantity - reserved, Decimal(0))
                if quantity is not None and reserved is not None
                else None
            )
        if grant is not None:
            grant_held = sum(
                (
                    held_quantity(row)
                    for row in allocations
                    if row.get("supply_grant_id") == str(grant["id"])
                ),
                Decimal(0),
            )
            if available is not None:
                available = min(
                    available, max(Decimal(grant["quantity_limit"]) - grant_held, Decimal(0))
                )
            source = shared_source(source, grant)
        result[key] = _plain(
            {
                "state": state,
                "source": source,
                "reserved_quantity": reserved,
                "pending_issue_quantity": sum(pending.values(), Decimal(0)),
                "available_quantity": available,
                "allocatable": state == "current"
                and (grant is None or grant["quantity_limit"] > 0),
            }
        )
    return result


def _base(c: Connection, context: AuthContext, project_id: UUID, build_id: UUID) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project_id)
    return _base_state(c, context.tenant.id, project_id, build_id)


def _base_state(c: Connection, tenant_id: UUID, project_id: UUID, build_id: UUID) -> dict[str, Any]:
    build = NpiExecutionService._row(
        c, tables.build_batches, tenant_id=tenant_id, project_id=project_id, record_id=build_id
    )
    r = tables.build_material_revisions
    revision = (
        c.execute(
            select(r)
            .where(
                r.c.tenant_id == tenant_id, r.c.project_id == project_id, r.c.build_id == build_id
            )
            .order_by(r.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    active = _active(c, tenant_id, project_id=project_id, build_id=build_id)
    return {
        "build": _plain({key: build[key] for key in ("id", "code", "status", "phase")}),
        "revision": _plain(dict(revision)) if revision else None,
        "allocations": active,
        "release_basis": digest({"build_id": str(build_id), "allocations": active}),
    }


def _selected_sources(
    c: Connection, tenant_id: UUID, project_id: UUID, items: list[AllocationItem]
) -> dict[UUID, dict[str, Any]]:
    from app.domain.supply_sharing import active_grant_query, visible_source_clause

    ids = {item.supply_snapshot_id for item in items}
    s = tables.supply_snapshots
    rows = {
        row["id"]: dict(row)
        for row in c.execute(
            _source_query(tenant_id).where(
                visible_source_clause(tenant_id, project_id), s.c.id.in_(ids)
            )
        ).mappings()
    }
    grants = {
        row["supply_snapshot_id"]: row["id"]
        for row in c.execute(active_grant_query(tenant_id, project_id)).mappings()
    }
    for identity, source in rows.items():
        source["supply_grant_id"] = (
            grants.get(identity) if source["project_id"] != project_id else None
        )
    if set(rows) != ids:
        raise MaterialAllocationError("所选供给快照不在当前项目可读范围内")
    return rows


def _preview(
    c: Connection,
    context: AuthContext,
    project_id: UUID,
    build_id: UUID,
    command: AllocationSelection,
) -> dict[str, Any]:
    base = _base(c, context, project_id, build_id)
    revision = base["revision"]
    if revision is None or revision["id"] != str(command.revision_id):
        raise MaterialAllocationError("批次需求版本已变化，请按最新固定版准备分配")
    if base["build"]["status"] not in {"planned", "in_progress"}:
        raise MaterialAllocationError("已结束或取消批次不能新增计划占用")
    sources = _selected_sources(c, context.tenant.id, project_id, command.items)
    pools = _pools(
        c, context.tenant.id, project_id, sorted({_key(row) for row in sources.values()})
    )
    lines = {row["bom_item_id"]: row for row in revision["lines"]}
    per_line: dict[str, Decimal] = {}
    per_pool: dict[PoolKey, Decimal] = {}
    proposed = []
    with localcontext() as arithmetic:
        arithmetic.prec = 2048
        for row in base["allocations"]:
            if row["revision_id"] == revision["id"]:
                per_line[row["bom_item_id"]] = (
                    per_line.get(row["bom_item_id"], Decimal(0))
                    + Decimal(row["remaining_quantity"])
                    + Decimal(row["received_quantity"])
                )
        for item in command.items:
            line = lines.get(str(item.bom_item_id))
            original = sources[item.supply_snapshot_id]
            pool = pools[_key(original)]
            source = pool["source"]
            if (
                line is None
                or not line["material_reference"]
                or line["material_reference"] != original["external_item_id"]
                or line["unit"] != original["unit"]
            ):
                raise MaterialAllocationError(
                    "须使用与固定BOM物料引用、单位完全一致的供给；缺少映射或替代件先完成工程核对"
                )
            if (
                source is None
                or source["id"] != str(item.supply_snapshot_id)
                or not pool["allocatable"]
            ):
                raise MaterialAllocationError(
                    "所选供给已有新版、过期、冻结、未知或占用冲突，请刷新当前可读快照"
                )
            per_line[str(item.bom_item_id)] = (
                per_line.get(str(item.bom_item_id), Decimal(0)) + item.quantity
            )
            per_pool[_key(original)] = per_pool.get(_key(original), Decimal(0)) + item.quantity
            if per_line[str(item.bom_item_id)] > Decimal(line["required_quantity"]):
                raise MaterialAllocationError(
                    "本次与原有效计划占用之和超过该需求项，先核对或释放原占用"
                )
            if per_pool[_key(original)] > Decimal(pool["available_quantity"]):
                raise MaterialAllocationError("同一供给池余量不足；已计入所有批次的未释放计划占用")
            proposed.append(
                {
                    **item.model_dump(mode="json"),
                    "supply_grant_id": source.get("source_grant_id"),
                    "part_number": line["part_number"],
                    "source_system": source["source_system"],
                    "external_pool_id": source["external_pool_id"],
                    "external_item_id": source["external_item_id"],
                    "unit": source["unit"],
                    "supply_kind": source["supply_kind"],
                    "quality_status": source["quality_status"],
                }
            )
    basis = {
        "policy": POLICY,
        "build": base["build"],
        "revision_id": revision["id"],
        "revision_digest": revision["content_digest"],
        "allocations": base["allocations"],
        "pools": [{"key": key, **pools[key]} for key in sorted(pools)],
        "proposed": proposed,
    }
    return {"digest": digest(basis), "basis": basis, "proposed": proposed}


class MaterialAllocationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID, build_id: UUID) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 2048
            return self.read(c, context, project_id, build_id)

    @staticmethod
    def read(
        c: Connection, context: AuthContext, project_id: UUID, build_id: UUID
    ) -> dict[str, Any]:
        BuildMaterialService._authorize(c, context, project_id)
        return read_material_state(c, context.tenant.id, project_id, build_id)

    def receipt(
        self, context: AuthContext, project_id: UUID, build_id: UUID, receipt_id: UUID
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            BuildMaterialService._authorize(c, context, project_id)
            t = tables.material_allocation_batches
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project_id,
                        t.c.build_id == build_id,
                        t.c.id == receipt_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise MaterialAllocationError("本批次中没有该分配回执")
            return _plain(dict(row))

    def preview(
        self, context: AuthContext, project_id: UUID, build_id: UUID, command: AllocationSelection
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return _preview(c, context, project_id, build_id, command)

    def apply(
        self,
        context: AuthContext,
        project_id: UUID,
        build_id: UUID,
        command: AllocationApply | AllocationRelease,
    ) -> dict[str, Any]:
        action = "release" if isinstance(command, AllocationRelease) else "allocate"
        signature = digest(
            {
                "action": action,
                "project_id": str(project_id),
                "build_id": str(build_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            tenant_id = context.tenant.id
            NpiExecutionService._project(c, tenant_id=tenant_id, project_id=project_id, lock=True)
            BuildMaterialService._authorize(c, context, project_id, write=True)
            t = tables.material_allocation_batches
            receipt = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant_id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if receipt:
                if receipt["request_digest"] != signature:
                    raise MaterialAllocationError("原请求已用于不同分配内容，请核对原回执")
                return _plain(dict(receipt))
            if isinstance(command, AllocationRelease):
                active = {
                    UUID(row["id"]): row
                    for row in _active(c, tenant_id, project_id=project_id, build_id=build_id)
                }
                if any(item.allocation_id not in active for item in command.items):
                    raise MaterialAllocationError("部分占用已释放或不属于本批次，请刷新")
                lock_pools(
                    c, tenant_id, [_key(active[item.allocation_id]) for item in command.items]
                )
                base = _base(c, context, project_id, build_id)
                active = {UUID(row["id"]): row for row in base["allocations"]}
                if base["release_basis"] != command.expected_digest or any(
                    item.quantity > Decimal(active[item.allocation_id]["remaining_quantity"])
                    for item in command.items
                ):
                    raise MaterialAllocationError("待释放数量已变化，请刷新核对剩余占用")
                snapshot = {
                    "policy": POLICY,
                    "before": base["allocations"],
                    "releases": [item.model_dump(mode="json") for item in command.items],
                }
            else:
                sources = _selected_sources(c, tenant_id, project_id, command.items)
                lock_pools(c, tenant_id, [_key(row) for row in sources.values()])
                preview = _preview(c, context, project_id, build_id, command)
                if preview["digest"] != command.expected_digest:
                    raise MaterialAllocationError("需求、供给或其他批次占用已变化，请重新预览")
                snapshot = preview["basis"]
            batch_id = uuid4()
            batch = (
                c.execute(
                    t.insert()
                    .values(
                        id=batch_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        build_id=build_id,
                        action=action,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        basis_digest=command.expected_digest,
                        snapshot=snapshot,
                        reason=command.reason,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            if isinstance(command, AllocationRelease):
                for item in command.items:
                    c.execute(
                        tables.material_allocation_releases.insert().values(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            project_id=project_id,
                            batch_id=batch_id,
                            allocation_id=item.allocation_id,
                            quantity=item.quantity,
                        )
                    )
            else:
                for allocation_item in command.items:
                    source = sources[allocation_item.supply_snapshot_id]
                    c.execute(
                        tables.material_supply_allocations.insert().values(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            project_id=project_id,
                            build_id=build_id,
                            batch_id=batch_id,
                            revision_id=command.revision_id,
                            bom_item_id=allocation_item.bom_item_id,
                            supply_snapshot_id=allocation_item.supply_snapshot_id,
                            supply_grant_id=source["supply_grant_id"],
                            source_system=source["source_system"],
                            external_pool_id=source["external_pool_id"],
                            external_item_id=source["external_item_id"],
                            unit=source["unit"],
                            quantity=allocation_item.quantity,
                        )
                    )
            result = _plain(dict(batch))
            NpiExecutionService._record_change(
                c,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=batch_id,
                record_type="material_allocation",
                action=action,
                before=None,
                after=result,
            )
            return result


def read_material_state(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    build_id: UUID,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Internal scoped projection; callers enforce user or existing runtime scope."""
    from app.domain.supply_sharing import visible_source_clause

    observed_at = as_of or datetime.now(UTC)
    base = _base_state(c, tenant_id, project_id, build_id)
    revision = base["revision"]
    s, b = tables.supply_snapshots, tables.supply_import_batches
    references = (
        {row["material_reference"] for row in revision["lines"] if row["material_reference"]}
        if revision
        else set()
    )
    candidates = (
        list(
            c.execute(
                _source_query(tenant_id)
                .where(
                    visible_source_clause(tenant_id, project_id),
                    s.c.external_item_id.in_(references),
                )
                .distinct(b.c.source_system, s.c.external_pool_id, s.c.external_item_id)
                .order_by(
                    b.c.source_system,
                    s.c.external_pool_id,
                    s.c.external_item_id,
                    b.c.as_of.desc(),
                    b.c.captured_at.desc(),
                    s.c.id.desc(),
                )
                .limit(501)
            ).mappings()
        )
        if references
        else []
    )
    keys = sorted(
        {_key(row) for row in candidates[:500]} | {_key(row) for row in base["allocations"]}
    )
    pools = _pools(c, tenant_id, project_id, keys, as_of=observed_at)
    rows = []
    for line in revision["lines"] if revision else []:
        allocations = [
            row
            for row in base["allocations"]
            if row["revision_id"] == revision["id"] and row["bom_item_id"] == line["bom_item_id"]
        ]
        qualified, expected, unverified = Decimal(0), Decimal(0), Decimal(0)
        issues = []
        for allocation in allocations:
            pool = pools[_key(allocation)]
            source = pool["source"]
            amount = Decimal(allocation["remaining_quantity"])
            if (
                pool["state"] != "current"
                or source is None
                or source["quality_status"] != "released"
                or (
                    allocation.get("supply_grant_id")
                    and allocation["supply_grant_id"] != source.get("source_grant_id")
                )
            ):
                unverified += amount
                issues.append(
                    pool["state"]
                    if pool["state"] != "current"
                    else "share_no_longer_valid"
                    if allocation.get("supply_grant_id")
                    and source
                    and allocation["supply_grant_id"] != source.get("source_grant_id")
                    else "quality_unknown"
                )
            elif source["supply_kind"] == "on_hand":
                qualified += amount
            else:
                expected += amount
        issued_good = sum(
            (Decimal(row["qualified_received_quantity"]) for row in allocations), Decimal(0)
        )
        received = sum((Decimal(row["received_quantity"]) for row in allocations), Decimal(0))
        required = Decimal(line["required_quantity"])
        matching = [
            pool
            for key, pool in pools.items()
            if key[2] == line["material_reference"]
            and pool["source"]
            and pool["source"]["unit"] == line["unit"]
        ]
        if not allocations:
            issues.extend(pool["state"] for pool in matching if pool["state"] != "current")
        status = (
            "ready"
            if qualified + issued_good >= required
            else "mapping_missing"
            if not line["material_reference"]
            else "source_review"
            if issues
            else "awaiting_arrival"
            if expected
            else "source_missing"
            if not matching
            else "awaiting_allocation"
        )
        rows.append(
            {
                **line,
                "qualified_allocated": str(qualified),
                "qualified_issued": str(issued_good),
                "received_quantity": str(received),
                "expected_allocated": str(expected),
                "unverified_allocated": str(unverified),
                "remaining_need": str(max(required - qualified - issued_good, Decimal(0))),
                "status": status,
                "issues": sorted(set(issues)),
            }
        )
    original_ids = {UUID(row["supply_snapshot_id"]) for row in base["allocations"]}
    original_sources = (
        [
            dict(row)
            for row in c.execute(
                _source_query(tenant_id).where(
                    s.c.project_id == project_id, s.c.id.in_(original_ids)
                )
            ).mappings()
        ]
        if original_ids
        else []
    )
    critical = [row for row in rows if row["critical"]]
    totals = {
        "line_count": len(rows),
        "ready_count": sum(row["status"] == "ready" for row in rows),
        "critical_count": len(critical),
        "critical_ready_count": sum(row["status"] == "ready" for row in critical),
    }
    t = tables.material_allocation_batches
    history = [
        dict(row)
        for row in c.execute(
            select(t.c.id, t.c.action, t.c.created_at, t.c.created_by_user_id, t.c.reason)
            .where(
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
                t.c.build_id == build_id,
            )
            .order_by(t.c.created_at.desc(), t.c.id)
            .limit(20)
        ).mappings()
    ]
    return _plain(
        {
            **base,
            "lines": rows,
            "allocation_sources": original_sources,
            "totals": totals,
            "pools": [{**value, "pool_key": list(key)} for key, value in pools.items()],
            "pool_limit_reached": len(candidates) > 500,
            "history": history,
            "as_of": observed_at,
            "policy": POLICY,
        }
    )
