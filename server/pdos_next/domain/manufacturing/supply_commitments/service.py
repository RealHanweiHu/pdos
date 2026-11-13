"""T0 supplier commitments through the common command transaction (F25, AT-20).

A commitment is the supplier's claim. It never adds to a pool balance, a kit
result or an arrival; actual receipts stay in supply snapshots. Writes are T0:
a named person records directly, 小Pai only with a qualified bound run and exact
original lines. The read view shows demand, commitment and actual side by side.
"""

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.core.models import now
from pdos_next.core.service import command_digest, digest
from pdos_next.core.source_current import direct_source_basis
from pdos_next.domain.categories.preproject.access import human
from pdos_next.domain.projects.models import Project
from pdos_next.domain.projects.work.rules import require

from . import rules
from .models import SupplyCommitmentCurrent, SupplyCommitmentVersion
from .schemas import OPERATION, SUBJECT, Snapshot

category_lifecycle_fence = True
semantic = rules.semantic

EFFECT = (
    "只登记供方声称的承诺（数量、日期与原话）及其来源。承诺不计入库存与齐套，"
    "不代表到货、采购订单或供方义务成立；实际到货仍以供给快照的到货记录为准。"
)


@dataclass
class Validated:
    session: object
    transaction: object
    fingerprint: str
    build: object
    project: object
    plan: object
    previous: object
    pointer: object
    sources: list
    reads: list
    source_basis: dict
    review: dict
    at: object
    used: bool = False


def _build(s, ctx, product_id, build_id):
    from pdos_next.domain.builds.service import _build as load_build

    return load_build(s, ctx, product_id, build_id)


def _project(s, ctx, product_id, project_id):
    row = s.scalar(
        select(Project).where(
            Project.tenant_id == ctx.tenant_id,
            Project.product_id == product_id,
            Project.id == project_id,
        )
    )
    require(row is not None, "项目不在当前可用范围。", "FORBIDDEN_SCOPE", 403)
    return row


def _demand(s, ctx, product_id, build, at):
    from pdos_next.domain.manufacturing.supply_execution.service import _bound, _rule

    return _rule(lambda: _bound(s, ctx, product_id, build, at))


def _current(s, ctx, product_id, commitment_id, *, lock=False):
    query = select(SupplyCommitmentCurrent).where(
        SupplyCommitmentCurrent.tenant_id == ctx.tenant_id,
        SupplyCommitmentCurrent.product_id == product_id,
        SupplyCommitmentCurrent.commitment_id == commitment_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    require(pointer is not None, "承诺不在当前可读范围。", "FORBIDDEN_SCOPE", 403)
    row = s.scalar(
        select(SupplyCommitmentVersion).where(
            SupplyCommitmentVersion.tenant_id == ctx.tenant_id,
            SupplyCommitmentVersion.product_id == product_id,
            SupplyCommitmentVersion.id == pointer.version_id,
        )
    )
    require(
        row is not None and row.revision == pointer.revision and row.commitment_id == commitment_id,
        "承诺当前指针与固定版本不一致。",
        "INTEGRITY_MISMATCH",
    )
    require(row.body_sha256 == digest(row.body), "承诺版本摘要无法核对。", "INTEGRITY_MISMATCH")
    return pointer, row


def validate(s, ctx, command, product, payload):
    key = ("supply-commitment", digest(vars(ctx)), command_digest(command))
    cached = s.info.get(key)
    if cached is not None and cached.transaction is s.get_transaction() and not cached.used:
        return cached
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    human_actor = not ctx.agent_run_id and not ctx.run_id
    if human_actor:
        human(s, ctx)
    at = now()
    previous, pointer = None, None
    record = payload.record
    if record.action == "create":
        build = _build(s, ctx, product.id, record.build_id)
        bound = _demand(s, ctx, product.id, build, at)
        materials = {line.material_id for line in bound.demand.lines if line.material_id}
        require(
            str(record.material_id) in materials,
            "承诺物料须是本轮固定需求中的真实物料。",
            "FORBIDDEN_SCOPE",
            403,
        )
        owner_id, visibility = build.owner_id, build.visibility
    else:
        pointer, previous = _current(s, ctx, product.id, payload.commitment.id, lock=True)
        build = _build(s, ctx, product.id, previous.build_id)
        owner_id, visibility = previous.owner_id, previous.visibility
        require(
            (build.owner_id, build.visibility) == (owner_id, visibility),
            "试制轮次的可见范围已变化，原承诺须先按新范围重核。",
            "VERSION_CONFLICT",
        )
    project = _project(s, ctx, product.id, build.project_id)
    refs = sorted(set(payload.sources), key=lambda ref: (str(ref.id), ref.revision, ref.position))
    basis, private = direct_source_basis(s, ctx, product, refs, command.source_read_set)
    require(
        not private or visibility == "private",
        "私有原件不能随承诺扩大到共享的试制轮次。",
        "FORBIDDEN_SCOPE",
        403,
    )
    plan = rules.transition(
        payload,
        current=previous.body if previous else None,
        commitment_id=uuid4() if previous is None else None,
        build=build,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        maintainers={build.owner_id, project.owner_id},
        at=at,
        human_actor=human_actor,
    )
    source_basis = {"artifacts": basis}
    review = {
        "operation": OPERATION,
        "build": {
            "id": str(build.id),
            "revision": build.revision,
            "name": build.name,
            "project_id": str(build.project_id),
        },
        "declaration": semantic(payload),
        "before": previous.body if previous else None,
        "after": plan.model_dump(mode="json"),
        "sources": [ref.model_dump(mode="json") for ref in refs],
        "effect": EFFECT,
    }
    value = Validated(
        s,
        s.get_transaction(),
        command_digest(command),
        build,
        project,
        plan,
        previous,
        pointer,
        review["sources"],
        [r.model_dump(mode="json") for r in command.source_read_set],
        source_basis,
        review,
        at,
    )
    value.owner_id, value.visibility = owner_id, visibility
    s.info[key] = value
    return value


def apply_validated(s, ctx, command, product, payload, value):
    require(
        value.session is s
        and value.transaction is s.get_transaction()
        and value.fingerprint == command_digest(command)
        and not value.used,
        "须使用本事务实际核对过的承诺材料。",
        "INTEGRITY_MISMATCH",
    )
    value.used = True
    envelope = command.model_dump(mode="json", exclude={"idempotency_key"})
    envelope["payload"] = semantic(payload)
    body = value.plan.model_dump(mode="json")
    previous = value.previous
    common = {
        "tenant_id": ctx.tenant_id,
        "category_id": ctx.category_id,
        "product_id": product.id,
        "project_id": value.build.project_id,
        "build_id": value.build.id,
        "owner_id": value.owner_id,
        "visibility": value.visibility,
    }
    row = SupplyCommitmentVersion(
        id=value.plan.commitment_id if previous is None else uuid4(),
        **common,
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation=OPERATION,
        command_id=command.command_id,
        command={
            "envelope": envelope,
            "review": value.review,
            "original_key_sha256": sha256(command.idempotency_key.encode()).hexdigest(),
        },
        body=body,
        body_sha256=digest(body),
        source_basis=value.source_basis,
        sources=value.sources,
        reads=value.reads,
        receipt_id=uuid4(),
        request_digest=command_digest(command),
        intent_digest=digest(
            {
                "operation": OPERATION,
                "category": command.category_id,
                "product": command.product_id,
                "payload": envelope["payload"],
                "named_actor": ctx.requester_id,
            }
        ),
        created_at=value.at,
        commitment_id=value.plan.commitment_id,
        revision=value.plan.revision,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        action=payload.record.action,
        state=value.plan.state,
        material_id=value.plan.material_id,
    )
    s.add(row)
    s.flush([row])
    if value.pointer is None:
        s.add(
            SupplyCommitmentCurrent(
                **common,
                commitment_id=row.commitment_id,
                version_id=row.id,
                revision=row.revision,
                state=row.state,
            )
        )
    else:
        value.pointer.version_id, value.pointer.revision, value.pointer.state = (
            row.id,
            row.revision,
            row.state,
        )
    row.action_result = {
        "commitment_id": str(row.commitment_id),
        "state": row.state,
        "build_id": str(row.build_id),
        "check_at": body["check_at"],
    }
    row.prepared_receipt_id = row.receipt_id
    row._commitment_phase = value
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    value = getattr(subject, "_commitment_phase", None)
    require(
        value is not None
        and value.used
        and value.session is s
        and value.transaction is s.get_transaction()
        and subject.receipt_id == receipt.id
        and subject.body_sha256 == digest(subject.body),
        "承诺缺少本事务共同回执绑定。",
        "INTEGRITY_MISMATCH",
    )
    del subject._commitment_phase


def _source_status(s, ctx, product_id, row):
    from pdos_next.domain.builds.configurations.service import _source_state

    return _source_state(s, ctx, product_id, row.reads) if row.reads else "current"


def _view(s, ctx, product_id, row, at):
    snapshot = Snapshot.model_validate(row.body)
    return {
        "id": str(row.id),
        "commitment_id": str(row.commitment_id),
        "revision": row.revision,
        "action": row.action,
        "state": row.state,
        "build_id": str(row.build_id),
        "project_id": str(row.project_id),
        "material_id": str(row.material_id),
        "visibility": row.visibility,
        "writer_id": str(row.writer_id),
        "requester_id": str(row.requester_id),
        "ai_written": row.actor_id != row.requester_id,
        "receipt_id": str(row.receipt_id),
        "created_at": row.created_at.isoformat(),
        "body": deepcopy(row.body),
        "source_status": _source_status(s, ctx, product_id, row),
        "follow_up": rules.follow_up(snapshot, at=at),
    }


def _history(s, ctx, product_id, commitment_id):
    rows = s.scalars(
        select(SupplyCommitmentVersion)
        .where(
            SupplyCommitmentVersion.tenant_id == ctx.tenant_id,
            SupplyCommitmentVersion.product_id == product_id,
            SupplyCommitmentVersion.commitment_id == commitment_id,
        )
        .order_by(SupplyCommitmentVersion.revision)
    ).all()
    return [
        {
            "id": str(row.id),
            "revision": row.revision,
            "action": row.action,
            "state": row.state,
            "promised_at": row.body.get("promised_at"),
            "quantity": row.body.get("quantity"),
            "unit": row.body.get("unit"),
            "time_basis": row.body.get("time_basis"),
            "recorded_at": row.body.get("recorded_at"),
            "ai_written": row.actor_id != row.requester_id,
        }
        for row in rows
    ]


def _actual(snapshot_row):
    """Per-material actual facts from the current snapshot; nothing is summed across units."""
    from pdos_next.domain.manufacturing.supply_execution.service import _snapshot

    if snapshot_row is None:
        return {}
    value = _snapshot(snapshot_row)
    result = {}

    def add(material_id, kind, quantity, unit):
        bucket = result.setdefault(material_id, {"on_hand": {}, "received": {}})
        totals = bucket[kind]
        if quantity is None or unit is None:
            totals["unknown"] = totals.get("unknown", 0) + 1
            return
        totals[unit] = str(Decimal(totals.get(unit, "0")) + Decimal(quantity))

    for pool in value.pools:
        add(pool.key.material_id, "on_hand", pool.quantity, pool.unit)
    for receipt in value.receipts:
        add(receipt.pool.material_id, "received", receipt.quantity, receipt.unit)
    return result


def build_view(s, ctx, product_id, build_id):
    """Demand, supplier commitments and actual arrivals per fixed BOM line (F25, AT-20)."""
    from pdos_next.core.service import require_access
    from pdos_next.domain.manufacturing.supply_execution.service import _current as supply_current

    require_access(s, ctx, product_id)
    at = now()
    build = _build(s, ctx, product_id, build_id)
    pointers = s.scalars(
        select(SupplyCommitmentCurrent)
        .where(
            SupplyCommitmentCurrent.tenant_id == ctx.tenant_id,
            SupplyCommitmentCurrent.product_id == product_id,
            SupplyCommitmentCurrent.build_id == build.id,
        )
        .order_by(SupplyCommitmentCurrent.created_at, SupplyCommitmentCurrent.id)
        .limit(201)
    ).all()
    commitments = []
    for pointer in pointers[:200]:
        _, row = _current(s, ctx, product_id, pointer.commitment_id)
        view = _view(s, ctx, product_id, row, at)
        view["history"] = _history(s, ctx, product_id, row.commitment_id)
        commitments.append(view)
    try:
        bound = _demand(s, ctx, product_id, build, at)
        demand_lines, demand_status = bound.demand.lines, "current"
    except Exception as error:  # noqa: BLE001 -- show demand as unknown, never as zero
        from pdos_next.errors import DomainError

        if not isinstance(error, DomainError) or error.status == 403:
            raise
        demand_lines, demand_status = (), error.reason
    _, snapshot_row = supply_current(s, ctx, product_id, build.id)
    actual = _actual(snapshot_row)
    lines = []
    for line in demand_lines:
        material = line.material_id
        own = [item for item in commitments if item["material_id"] == material]
        lines.append(
            {
                "item_id": line.item_id,
                "material_id": material,
                "unit": line.unit,
                "required_quantity": str(line.required_quantity)
                if line.required_quantity is not None
                else None,
                "commitments": [item["commitment_id"] for item in own],
                "open_commitments": sum(1 for item in own if item["state"] == "open"),
                "check_due": sum(1 for item in own if item["follow_up"]["check_due"]),
                "actual": actual.get(material, {"on_hand": {}, "received": {}}),
            }
        )
    return {
        "build": {
            "id": str(build.id),
            "revision": build.revision,
            "name": build.name,
            "project_id": str(build.project_id),
            "owner_id": str(build.owner_id),
            "visibility": build.visibility,
        },
        "as_of": at.isoformat(),
        "demand_status": demand_status,
        "lines": lines,
        "commitments": commitments,
        "has_more": len(pointers) > 200,
        "supply_snapshot_id": str(snapshot_row.id) if snapshot_row is not None else None,
        "kit_rule": "承诺不计入库存与齐套；齐套只按供给快照的库存行计算。",
    }


def get_commitment(s, ctx, product_id, commitment_id):
    from pdos_next.core.service import require_access

    require_access(s, ctx, product_id)
    _, row = _current(s, ctx, product_id, UUID(str(commitment_id)))
    _build(s, ctx, product_id, row.build_id)
    view = _view(s, ctx, product_id, row, now())
    view["history"] = _history(s, ctx, product_id, row.commitment_id)
    return view
