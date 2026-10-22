"""Authorized-read presentation mappers for the independent React components.

Callers first authorize every snapshot/projection with the server scope. These
functions only format supplied immutable values; they do not read current data,
infer source facts, or change freshness. Historical views need the EXACT original
Build basis, never today's quantities presented under an old snapshot heading.
"""

import json
from datetime import datetime

from pdos_next.engines.supply_cost.common import digest
from pdos_next.engines.supply_cost.dto import FixedBasis
from pdos_next.schemas.supply_cost.dto import (
    BasisBinding,
    CostProjection,
    CoverageProjection,
    Freshness,
    SupplyReconciliation,
    SupplySnapshot,
)

from .errors import SupplyBusinessError
from .rules import canonical_supply


def binding_view(binding: BasisBinding, basis: FixedBasis) -> dict:
    if digest(basis) != binding.basis_sha256 or basis.build.build_id != binding.build_id:
        raise SupplyBusinessError(
            "FIXED_INPUT_MISMATCH", "Display basis is not the stored fixed basis"
        )
    return {
        "basis_sha256": binding.basis_sha256,
        "demand_sha256": binding.demand.sha256,
        "basis": basis.model_dump(mode="json"),
        "manufacturing_configuration": binding.manufacturing_configuration.model_dump(mode="json"),
    }


def projection_view(
    projection: CoverageProjection | CostProjection,
    *,
    record_id: str,
    revision: int,
    created_at: datetime,
    freshness: Freshness,
) -> dict:
    return {
        "id": record_id,
        "revision": str(revision),
        "created_at": created_at.isoformat(),
        "freshness": freshness.state,
        "freshness_reasons": list(freshness.reasons),
        "result": projection.result.model_dump(mode="json"),
    }


def _record(row, kind: str):
    pool = getattr(row, "pool", None)
    record = {
        "record_kind": kind,
        "record_id": row.record_id,
        "material_id": pool.material_id if pool else row.material_id,
        "quantity": row.model_dump(mode="json").get(
            "quantity", row.model_dump(mode="json").get("affected_quantity")
        ),
        "unit": row.unit,
        "source_id": row.ref.source_id,
        "source_revision": row.ref.version,
        "quality": getattr(row, "quality", "unknown"),
        "availability": getattr(row, "availability", "unknown"),
        "note": row.note,
        "source": row.ref.model_dump(mode="json"),
        "recorded_at": getattr(row, "received_at", row.ref.captured_at).isoformat(),
    }
    if pool:
        record["pool_id"] = pool.pool_id
    if hasattr(row, "supplier_id"):
        record["supplier_id"] = row.supplier_id
    if hasattr(row, "expected_at"):
        record["expected_at"] = row.expected_at.isoformat() if row.expected_at else None
    if hasattr(row, "commitment_id"):
        record["commitment_id"] = row.commitment_id
    return record


def _flatten(value, path="") -> dict:
    if not isinstance(value, dict):
        return {path or "value": value}
    result = {}
    for key, child in value.items():
        result.update(_flatten(child, f"{path}.{key}" if path else key))
    return result


_LABELS = {
    "quantity": "来源数量",
    "affected_quantity": "质量分区数量",
    "unit": "单位",
    "quality": "质量状态",
    "availability": "可用状态",
    "stage": "供给阶段",
    "ref.version": "来源版本",
    "ref.sha256": "来源内容摘要",
    "note": "来源说明",
    "expected_at": "预计到达",
    "received_at": "实际到达",
    "supplier_id": "供方",
    "build_id": "占用 Build",
    "bom_item_id": "占用 BOM 项",
    "commitment_id": "承诺关联",
    "value": "记录",
    "ref.valid_until": "来源有效期",
    "ref.state": "来源有效性",
}


def _text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def reconciliation_view(value: SupplyReconciliation) -> dict | None:
    if value.previous is None:
        return None
    deltas = []
    for delta in value.deltas:
        before, after = _flatten(delta.before), _flatten(delta.after)
        for field in sorted(before.keys() | after.keys()):
            if before.get(field) == after.get(field):
                continue
            deltas.append(
                {
                    "record_key": f"{delta.entity} · {delta.identity}",
                    "field": _LABELS.get(field, field),
                    "before": _text(before.get(field)),
                    "after": _text(after.get(field)),
                    # No cross-unit or unknown subtraction in a display mapper.
                    "difference": None,
                    "unit": None,
                }
            )
    return {
        "id": value.current.snapshot_id,
        "before_snapshot_id": value.previous.snapshot_id,
        "before_revision": str(value.previous.revision),
        "before_sha256": value.previous_sha256,
        "after_snapshot_id": value.current.snapshot_id,
        "after_revision": str(value.current.revision),
        "after_sha256": value.current_sha256,
        "deltas": deltas,
        "reasons": ["来源、配置、余额或占用变化后，齐套和成本须按新的固定依据重核。"],
    }


def snapshot_view(
    snapshot: SupplySnapshot,
    basis: FixedBasis,
    freshness: Freshness,
    reconciliation: SupplyReconciliation | None = None,
) -> dict:
    snapshot = canonical_supply(snapshot)
    if reconciliation is not None and reconciliation.current != snapshot:
        raise SupplyBusinessError(
            "SNAPSHOT_VERSION_CONFLICT", "Reconciliation belongs to another snapshot"
        )
    records = []
    for name, kind in (
        ("commitments", "commitment"),
        ("in_transit", "in_transit"),
        ("receipts", "receipt"),
        ("restrictions", "restriction"),
    ):
        records.extend(_record(row, kind) for row in getattr(snapshot, name))
    for pool in snapshot.pools:
        if pool.stage != "on_hand":
            continue
        records.append(
            {
                "record_kind": "inventory",
                "record_id": json.dumps(
                    [pool.key.source_system, pool.key.pool_id, pool.key.material_id],
                    ensure_ascii=False,
                ),
                "material_id": pool.key.material_id,
                "quantity": pool.model_dump(mode="json")["quantity"],
                "unit": pool.unit,
                "source_id": pool.ref.source_id,
                "source_revision": pool.ref.version,
                "pool_id": pool.key.pool_id,
                "quality": pool.quality,
                "availability": pool.availability,
                "note": "当前物理池库存余额，独立于累计到货记录。",
                "source": pool.ref.model_dump(mode="json"),
                "recorded_at": pool.ref.captured_at.isoformat(),
            }
        )
    refs = [
        snapshot.ref,
        snapshot.binding.build,
        snapshot.binding.bom,
        snapshot.binding.engineering_configuration,
        snapshot.binding.manufacturing_configuration,
        snapshot.binding.demand,
        *snapshot.binding.source_read_set,
    ]
    for name in ("commitments", "in_transit", "receipts", "restrictions", "pools", "reservations"):
        refs.extend(row.ref for row in getattr(snapshot, name))
    sources = {digest(ref): ref.model_dump(mode="json") for ref in refs}
    return {
        "id": snapshot.snapshot_id,
        "revision": str(snapshot.revision),
        "sha256": digest(snapshot),
        "captured_at": snapshot.ref.captured_at.isoformat(),
        "freshness": freshness.state,
        "freshness_reasons": list(freshness.reasons),
        "binding": binding_view(snapshot.binding, basis),
        "source_refs": [sources[key] for key in sorted(sources)],
        "scope_complete": snapshot.supply_scope_complete,
        "records": records,
        "pools": [row.model_dump(mode="json") for row in snapshot.pools],
        "reservations": [row.model_dump(mode="json") for row in snapshot.reservations],
        "reconciliation": reconciliation_view(reconciliation) if reconciliation else None,
    }
