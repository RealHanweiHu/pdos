"""Host transaction adapters; manual source facts never unlock inventory or Build release."""

import json
from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.domain.configurations.service import _decimal, _merge_reads, _source_state
from pdos_next.domain.supply_cost.adapters import coverage_candidate
from pdos_next.domain.supply_cost.errors import SupplyBusinessError
from pdos_next.domain.supply_cost.read_models import projection_view, snapshot_view
from pdos_next.domain.supply_cost.rules import (
    basis_binding,
    canonical_supply,
    projection_freshness,
    reconcile,
    require_binding,
    require_current,
    require_scope,
    snapshot_freshness,
)
from pdos_next.engines.supply_cost.common import SnapshotRef, digest
from pdos_next.engines.supply_cost.dto import PoolKey, SupplyPool
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Principal, Product, now
from pdos_next.schemas.supply_cost.dto import (
    BoundDemand,
    CoverageProjection,
    Freshness,
    QualityRestriction,
    ReceiptObservation,
    Scope,
    SupplyCommitment,
    SupplyReconciliation,
    TransitObservation,
)
from pdos_next.schemas.supply_cost.dto import (
    SupplySnapshot as SnapshotDTO,
)

from .models import KitProjection, SupplyCapture, SupplyCurrent, SupplySnapshot
from .schemas import SnapshotRecordPayload, SupplyCaptureInput

SNAPSHOT_EFFECT = (
    "人工保存整份外部供给来源快照及前版差异；仅库存行表达当前池余额，"
    "承诺、在途和到货不累加库存。完整占用范围未核验，品质与可用性不放行。"
)
KIT_EFFECT = "确定性计算固定需求的齐套与短缺；不预约库存、不批准替代或开工。"


def _build(*args, **kwargs):
    from pdos_next.domain.builds.service import _build as load_build

    return load_build(*args, **kwargs)


def _linked(*args, **kwargs):
    from pdos_next.domain.builds.service import _linked as load_links

    return load_links(*args, **kwargs)


def _rule(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except SupplyBusinessError as error:
        raise DomainError(error.code, "固定需求、来源或快照范围不能一致核对，请重核。") from None


def _human(s, ctx, product_id, *, write=False):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id, write=write, lock=write)
    principal = s.get(Principal, ctx.actor_id)
    if ctx.run_id is not None or ctx.actor_id != ctx.requester_id or principal.kind != "human":
        raise DomainError("NAMED_DECISION_REQUIRED", "供给来源与计算由当前具名本人办理。", 403)


def _row(s, ctx, product_id, model, identity, *, write=False):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id, write=write, lock=write)
    row = s.scalar(
        select(model).where(
            model.id == identity,
            model.product_id == product_id,
            model.tenant_id == ctx.tenant_id,
        )
    )
    if row is None or (write and row.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "供给来源或投影不在当前可用范围。", 403)
    build = _build(s, ctx, product_id, row.build_id, write=write)
    if row.project_id != build.project_id:
        raise DomainError("FORBIDDEN_SCOPE", "供给来源不属于本轮项目。", 403)
    return row, build


def _scope(ctx, product_id, build):
    return Scope(
        tenant_id=str(ctx.tenant_id),
        category_id=str(build.category_id),
        product_id=str(product_id),
        project_id=str(build.project_id),
        audience=(
            f"private:{build.owner_id}"
            if build.visibility == "private"
            else f"audience:build:{build.id}"
            if build.visibility == "audience"
            else f"category:{build.category_id}"
        ),
    )


def _bound(s, ctx, product_id, build, as_of):
    from pdos_next.domain.builds.demand import DatabaseBuildDemandPort

    return DatabaseBuildDemandPort(ctx).load(
        s,
        _scope(ctx, product_id, build),
        str(build.id),
        build.revision,
        as_of,
    )


def _current(s, ctx, product_id, build_id, *, lock=False):
    query = select(SupplyCurrent).where(
        SupplyCurrent.tenant_id == ctx.tenant_id,
        SupplyCurrent.product_id == product_id,
        SupplyCurrent.build_id == build_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    if pointer is None:
        return None, None
    row, _ = _row(s, ctx, product_id, SupplySnapshot, pointer.snapshot_id)
    if row.revision != pointer.snapshot_revision:
        raise DomainError("INTEGRITY_MISMATCH", "供给当前指针与固定快照不一致。")
    return pointer, row


def _snapshot(row):
    value = SnapshotDTO.model_validate(row.snapshot)
    if (
        value.snapshot_id != str(row.id)
        or value.revision != row.revision
        or digest(value) != (row.snapshot_sha256)
    ):
        raise DomainError("INTEGRITY_MISMATCH", "固定供给快照摘要无法核对。")
    return value


def _references(data):
    return [reference.model_dump(mode="json") for row in data.records for reference in row.sources]


def _sources(s, ctx, product_id, reads, references=()):
    from pdos_next.originals import object_reference, require_original
    from pdos_next.request_proof import batch_read, request_proof
    from pdos_next.service import digest as content_digest
    from pdos_next.service import source_for

    proof = request_proof(s)
    batch_read(s, Artifact, [UUID(str(read["artifact_id"])) for read in reads])
    writing = any(entry["locked"] for entry in proof.authority.values())

    values, private, lines = {}, False, {}
    for read in reads:
        source = source_for(
            s, ctx, product_id, UUID(read["artifact_id"]), read["expected_revision"]
        )
        if source.tenant_id != ctx.tenant_id or source.content_hash != content_digest(
            source.content
        ):
            raise DomainError("INTEGRITY_MISMATCH", "来源内容摘要无法核对。")
        private |= source.visibility != "category"
        lines[str(source.id)] = source.content.splitlines()
        ref = SnapshotRef(
            source_id=f"artifact:{source.id}",
            version=str(source.revision),
            sha256=source.content_hash,
            captured_at=source.created_at,
            state="current",
        )
        values[ref.source_id] = ref
        if source.original_id is not None:
            original = require_original(s, ctx, product_id, source.original_id, lock=writing)
            if original.tenant_id != ctx.tenant_id or original.status != "parsed":
                raise DomainError("SOURCE_UNAVAILABLE", "来源原件的解析状态不可用。")
            try:
                object_reference(original)
            except (TypeError, ValueError, AttributeError):
                raise DomainError("INTEGRITY_MISMATCH", "来源原件私有对象身份无法核对。") from None
            private |= original.visibility != "category"
            ref = SnapshotRef(
                source_id=f"original:{original.id}",
                version=str(original.revision),
                sha256=original.content_hash,
                captured_at=max(source.created_at, original.created_at),
                state="current",
            )
            values[ref.source_id] = ref
    for reference in references:
        content = lines.get(reference["artifact_id"], [])
        if (
            reference["line"] > len(content)
            or reference["quote"] not in content[reference["line"] - 1]
        ):
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "供给事实须在指定原文行精确定位。")
    return values, private


def _visibility(build, sources_private, previous=None):
    return (
        "private"
        if (
            build.visibility == "private"
            or sources_private
            or (previous is not None and previous.visibility == "private")
        )
        else build.visibility
    )


def _proposed(data, bound, refs, snapshot_id, captured_at, previous):
    from pdos_next.service import digest as content_digest

    commitments, transit, receipts, restrictions, pools = [], [], [], [], []
    for row in data.records:
        reference = refs[f"artifact:{row.sources[0].artifact_id}"]
        material = str(row.material_id)
        common = {
            "record_id": row.record_id,
            "ref": reference,
            "quantity": row.quantity,
            "unit": row.unit,
            "note": row.note,
        }
        if row.record_kind == "commitment":
            commitments.append(
                SupplyCommitment(
                    **common,
                    supplier_id=row.supplier_id,
                    material_id=material,
                    expected_at=row.expected_at,
                )
            )
            continue
        pool = PoolKey(source_system=row.source_system, pool_id=row.pool_id, material_id=material)
        if row.record_kind == "inventory":
            pools.append(
                SupplyPool(
                    key=pool,
                    ref=reference,
                    stage="on_hand",
                    quantity=row.quantity,
                    unit=row.unit,
                    quality=row.quality,
                    availability=row.availability,
                )
            )
        elif row.record_kind == "in_transit":
            transit.append(TransitObservation(**common, pool=pool, commitment_id=row.commitment_id))
        elif row.record_kind == "receipt":
            receipts.append(
                ReceiptObservation(
                    **common,
                    pool=pool,
                    commitment_id=row.commitment_id,
                    received_at=row.received_at,
                )
            )
        else:
            restrictions.append(
                QualityRestriction(
                    record_id=row.record_id,
                    ref=reference,
                    pool=pool,
                    quality=row.quality,
                    availability=row.availability,
                    affected_quantity=row.quantity,
                    unit=row.unit,
                    note=row.note,
                )
            )
    binding = _rule(basis_binding, bound, captured_at)
    revision = previous.revision + 1 if previous is not None else 1
    raw = {
        "input": data.model_dump(mode="json"),
        "binding": binding.model_dump(mode="json"),
        "sources": [refs[key].model_dump(mode="json") for key in sorted(refs)],
    }
    result = SnapshotDTO(
        snapshot_id=str(snapshot_id),
        revision=revision,
        scope=bound.scope,
        binding=binding,
        ref=SnapshotRef(
            source_id=f"supply:{snapshot_id}",
            version=str(revision),
            sha256=content_digest(raw),
            captured_at=captured_at,
            state="current",
        ),
        previous_snapshot_id=str(previous.id) if previous is not None else None,
        previous_revision=previous.revision if previous is not None else None,
        commitments=tuple(commitments),
        in_transit=tuple(transit),
        receipts=tuple(receipts),
        restrictions=tuple(restrictions),
        pools=tuple(pools),
        reservations=(),
        supply_scope_complete=False,
        note=data.reason,
    )
    return _rule(canonical_supply, result)


def _capture_payload(row):
    proposed = SnapshotDTO.model_validate(row.proposed_snapshot)
    return {
        "build_id": str(row.build_id),
        "expected_build_revision": row.build_revision,
        "capture_id": str(row.id),
        "expected_capture_revision": row.revision,
        "expected_previous_snapshot_id": proposed.previous_snapshot_id,
        "expected_previous_revision": proposed.previous_revision,
        "reason": row.reason,
    }


def _read_evidence(s, ctx, product_id, row):
    from pdos_next.originals import require_original

    state = _source_state(s, ctx, product_id, row.required_source_read_set)
    for read in row.required_source_read_set:
        source = s.get(Artifact, UUID(read["artifact_id"]))
        if row.visibility == "category" and source.visibility != "category":
            state = "needs_recheck"
        if source.original_id is not None:
            original = require_original(s, ctx, product_id, source.original_id)
            if original.status != "parsed" or (
                row.visibility == "category" and original.visibility != "category"
            ):
                state = "needs_recheck"
    return state


def _capture_view(s, ctx, product_id, row):
    source_state = _read_evidence(s, ctx, product_id, row)
    applied = s.scalar(
        select(SupplySnapshot.id).where(
            SupplySnapshot.tenant_id == ctx.tenant_id,
            SupplySnapshot.product_id == product_id,
            SupplySnapshot.capture_id == row.id,
        )
    )
    return {
        "id": str(row.id),
        "revision": row.revision,
        "build_id": str(row.build_id),
        "build_revision": row.build_revision,
        "project_id": str(row.project_id),
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "applied_snapshot_id": str(applied) if applied is not None else None,
        "reason": row.reason,
        "input_snapshot": deepcopy(row.input_snapshot),
        "required_source_read_set": deepcopy(row.required_source_read_set),
        "source_status": source_state,
        "snapshot_record_payload": _capture_payload(row),
    }


def _normalized_input(data):
    raw = data.model_dump(mode="json")
    for record in raw["records"]:
        if record["quantity"] is not None:
            quantity = Decimal(record["quantity"])
            record["quantity"] = "0" if quantity == 0 else _decimal(quantity)
        record["sources"].sort(
            key=lambda ref: (
                ref["artifact_id"],
                ref["expected_revision"],
                ref["line"],
                ref["quote"],
            )
        )
    raw["records"].sort(key=lambda record: (record["record_kind"], record["record_id"]))
    if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > 1_000_000:
        raise DomainError("INVALID_PAYLOAD", "来源草稿超过本轮1MB上限，请收敛记录与引用。", 422)
    return raw


def prepare_capture(s, ctx, product_id, data: SupplyCaptureInput):
    from pdos_next.database import require_context
    from pdos_next.service import digest as request_digest

    require_context(s, ctx)
    raw = _normalized_input(data)
    data = SupplyCaptureInput.model_validate(raw)
    references = _references(data)
    fingerprint = request_digest(raw)
    existing = s.scalar(
        select(SupplyCapture).where(
            SupplyCapture.tenant_id == ctx.tenant_id,
            SupplyCapture.product_id == product_id,
            SupplyCapture.owner_id == ctx.requester_id,
            SupplyCapture.capture_key == data.capture_key,
        )
    )
    if existing is not None:
        _human(s, ctx, product_id)
        if existing.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "相同捕获编号对应了不同内容。")
        view = _capture_view(s, ctx, product_id, existing)
        return {
            "capture": view,
            "snapshot_record_payload": view["snapshot_record_payload"],
            "required_source_read_set": view["required_source_read_set"],
        }
    product = s.scalar(select(Product).where(Product.id == product_id).with_for_update())
    _human(s, ctx, product_id, write=True)
    build = _build(s, ctx, product_id, data.build_id, write=True)
    existing = s.scalar(
        select(SupplyCapture).where(
            SupplyCapture.tenant_id == ctx.tenant_id,
            SupplyCapture.product_id == product_id,
            SupplyCapture.owner_id == ctx.requester_id,
            SupplyCapture.capture_key == data.capture_key,
        )
    )
    if existing is not None:
        if existing.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "相同捕获编号对应了不同内容。")
        view = _capture_view(s, ctx, product_id, existing)
        return {
            "capture": view,
            "snapshot_record_payload": view["snapshot_record_payload"],
            "required_source_read_set": view["required_source_read_set"],
        }
    if data.expected_product_revision != product.revision or data.expected_build_revision != (
        build.revision
    ):
        raise DomainError("VERSION_CONFLICT", "产品或试制版本已变化，请重读后再捕获。")
    captured_at = now()
    bound = _bound(s, ctx, product_id, build, captured_at)
    _, previous = _current(s, ctx, product_id, build.id, lock=True)
    _, _, _, planned_reads = _linked(s, ctx, product_id, build, write=True)
    reads = _merge_reads(
        planned_reads, references, previous.required_source_read_set if previous is not None else []
    )
    refs, private = _sources(s, ctx, product_id, reads, references)
    if build.visibility == "category" and private:
        raise DomainError("FORBIDDEN_SCOPE", "私人来源须先建立相符的私人试制范围。", 403)
    if previous is not None:
        _rule(require_scope, bound.scope, _snapshot(previous).scope)
    materials = {line.material_id for line in bound.demand.lines if line.material_id is not None}
    for record in data.records:
        if str(record.material_id) not in materials:
            raise DomainError(
                "FORBIDDEN_SCOPE", "供给物料须绑定本次固定需求中的真实物料身份。", 403
            )
        if record.received_at is not None and record.received_at > captured_at:
            raise DomainError("INVALID_EVENT_TIME", "实际到货不能记录未来时间。", 422)
    snapshot_id = uuid4()
    proposed = _proposed(data, bound, refs, snapshot_id, captured_at, previous)
    # Run the existing reconciliation now, so malformed/differently ordered capture cannot be saved.
    _rule(reconcile, _snapshot(previous) if previous is not None else None, proposed)
    row = SupplyCapture(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product_id,
        project_id=build.project_id,
        build_id=build.id,
        build_revision=build.revision,
        owner_id=ctx.requester_id,
        visibility=_visibility(build, private, previous),
        reason=data.reason,
        revision=1,
        capture_key=data.capture_key,
        request_sha256=fingerprint,
        snapshot_id=snapshot_id,
        created_at=captured_at,
        input_snapshot=raw,
        bound_demand=bound.model_dump(mode="json"),
        proposed_snapshot=proposed.model_dump(mode="json"),
        sources=references,
        required_source_read_set=reads,
    )
    s.add(row)
    s.flush()
    view = _capture_view(s, ctx, product_id, row)
    return {
        "capture": view,
        "snapshot_record_payload": view["snapshot_record_payload"],
        "required_source_read_set": reads,
    }


def _inputs(s, ctx, command, product, payload):
    _human(s, ctx, product.id, write=True)
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "供给命令不在当前型号范围。", 403)
    if isinstance(payload, SnapshotRecordPayload):
        row, build = _row(s, ctx, product.id, SupplyCapture, payload.capture_id, write=True)
    else:
        row, build = _row(s, ctx, product.id, SupplySnapshot, payload.supply_snapshot_id)
    if build.id != payload.build_id:
        raise DomainError("FORBIDDEN_SCOPE", "供给命令不属于该固定试制轮次。", 403)
    _linked(s, ctx, product.id, build)
    supplied = {str(ref.artifact_id): ref.expected_revision for ref in command.source_read_set}
    for ref in row.required_source_read_set:
        if supplied.get(ref["artifact_id"]) != ref["expected_revision"]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "需要供给与双配置的全部固定来源。")
    _, private = _sources(s, ctx, product.id, row.required_source_read_set, row.sources)
    if build.visibility == "category" and private:
        raise DomainError("FORBIDDEN_SCOPE", "私人来源不能扩大到品类共享试制范围。", 403)
    return row, build


def validate(s, ctx, command, product, payload):
    # Current rights and original evidence precede receipt replay; new-write guards do not.
    _inputs(s, ctx, command, product, payload)


def semantic(payload):
    value = payload.model_dump(mode="json")
    value.pop("confirmation_token", None)
    return value


def _new_write(s, ctx, command, product, payload, row, build):
    if command.expected_revision != product.revision or payload.expected_build_revision != (
        build.revision
    ):
        raise DomainError("VERSION_CONFLICT", "产品或试制版本已变化，请重新读取。")
    as_of = now()
    pointer, previous = _current(s, ctx, product.id, build.id, lock=True)
    if isinstance(payload, SnapshotRecordPayload):
        if (
            row.revision != payload.expected_capture_revision
            or row.build_revision != build.revision
        ):
            raise DomainError("VERSION_CONFLICT", "来源草稿固定版本不一致。")
        proposed = SnapshotDTO.model_validate(row.proposed_snapshot)
        if row.snapshot_id != UUID(proposed.snapshot_id):
            raise DomainError("INTEGRITY_MISMATCH", "来源草稿的固定快照身份不一致。")
        if (
            proposed.previous_snapshot_id
            != (
                str(payload.expected_previous_snapshot_id)
                if payload.expected_previous_snapshot_id
                else None
            )
            or proposed.previous_revision != payload.expected_previous_revision
        ):
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "前版指针不属于该固定捕获。")
        if (
            str(previous.id) if previous is not None else None
        ) != proposed.previous_snapshot_id or (
            previous.revision if previous is not None else None
        ) != proposed.previous_revision:
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "供给当前快照已变化，请重新捕获与核对。")
        if (
            s.scalar(
                select(SupplySnapshot.id).where(
                    SupplySnapshot.tenant_id == ctx.tenant_id,
                    SupplySnapshot.product_id == product.id,
                    SupplySnapshot.capture_id == row.id,
                )
            )
            is not None
        ):
            raise DomainError("CAPTURE_ALREADY_APPLIED", "此来源捕获已应用，不能另建重复快照。")
        bound = _bound(s, ctx, product.id, build, as_of)
        _rule(require_binding, _rule(basis_binding, bound, as_of), proposed.binding)
        for ref in (
            proposed.ref,
            *(pool.ref for pool in proposed.pools),
            *(
                record.ref
                for group in (
                    proposed.commitments,
                    proposed.in_transit,
                    proposed.receipts,
                    proposed.restrictions,
                )
                for record in group
            ),
        ):
            _rule(require_current, ref, as_of)
        value = _rule(reconcile, _snapshot(previous) if previous is not None else None, proposed)
    else:
        if row.revision != payload.expected_supply_revision or row.build_revision != build.revision:
            raise DomainError("VERSION_CONFLICT", "供给快照固定版本不一致。")
        if previous is None or previous.id != row.id:
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "须按本轮当前供给快照计算齐套。")
        bound = _bound(s, ctx, product.id, build, as_of)
        value = _rule(coverage_candidate, bound, _snapshot(row), (), as_of)
    return bound, pointer, previous, value, as_of


def preview_view(s, ctx, command, product, payload):
    row, build = _inputs(s, ctx, command, product, payload)
    if not isinstance(payload, SnapshotRecordPayload):
        raise DomainError("FORBIDDEN_SCOPE", "确定性齐套计算无需人工确认。", 403)
    bound, _, previous, value, _ = _new_write(s, ctx, command, product, payload, row, build)
    current = value.current
    before = (
        snapshot_view(
            value.previous,
            BoundDemand.model_validate(previous.bound_demand).basis,
            Freshness(state="historical", reasons=()),
        )
        if previous
        else None
    )
    after = snapshot_view(current, bound.basis, Freshness(state="current", reasons=()), value)
    after.update(
        {
            "build_id": str(build.id),
            "project_id": str(build.project_id),
            "owner_id": str(row.owner_id),
            "visibility": row.visibility,
            "reason": payload.reason,
            "required_source_read_set": row.required_source_read_set,
            "input_snapshot": deepcopy(row.input_snapshot),
            "sources": deepcopy(row.sources),
            "capture_id": str(row.id),
            "previous_snapshot_id": current.previous_snapshot_id,
            "previous_revision": current.previous_revision,
        }
    )
    return {
        "operation": command.operation,
        "name": build.name,
        "effect": SNAPSHOT_EFFECT,
        "before": before,
        "after": after,
        "reason": payload.reason,
    }


def apply(s, ctx, command, product, payload):
    row, build = _inputs(s, ctx, command, product, payload)
    bound, pointer, _, value, as_of = _new_write(s, ctx, command, product, payload, row, build)
    common = {
        "tenant_id": ctx.tenant_id,
        "product_id": product.id,
        "project_id": build.project_id,
        "build_id": build.id,
        "build_revision": build.revision,
        "owner_id": ctx.requester_id,
        "visibility": row.visibility,
        "required_source_read_set": row.required_source_read_set,
        "bound_demand": bound.model_dump(mode="json"),
        "created_at": as_of,
    }
    if isinstance(payload, SnapshotRecordPayload):
        current = value.current
        saved = SupplySnapshot(
            id=UUID(current.snapshot_id),
            revision=current.revision,
            capture_id=row.id,
            previous_snapshot_id=(
                UUID(current.previous_snapshot_id) if current.previous_snapshot_id else None
            ),
            previous_revision=current.previous_revision,
            snapshot=current.model_dump(mode="json"),
            snapshot_sha256=digest(current),
            reconciliation=value.model_dump(mode="json"),
            sources=row.sources,
            reason=payload.reason,
            **common,
        )
        s.add(saved)
        s.flush()
        if pointer is None:
            pointer = SupplyCurrent(
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                build_id=build.id,
                snapshot_id=saved.id,
                snapshot_revision=saved.revision,
            )
            s.add(pointer)
        else:
            pointer.snapshot_id, pointer.snapshot_revision = saved.id, saved.revision
        s.flush()
        return saved, "supply_snapshot", saved.visibility
    saved = KitProjection(
        id=uuid4(),
        revision=1,
        supply_snapshot_id=row.id,
        supply_revision=row.revision,
        as_of=as_of,
        projection=value.model_dump(mode="json"),
        projection_sha256=digest(value),
        reason=KIT_EFFECT,
        **common,
    )
    s.add(saved)
    s.flush()
    return saved, "supply_coverage", saved.visibility


def _metadata(row):
    result = {
        "build_id": str(row.build_id),
        "project_id": str(row.project_id),
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "reason": row.reason,
        "required_source_read_set": deepcopy(row.required_source_read_set),
    }
    if hasattr(row, "sources"):
        result["sources"] = deepcopy(row.sources)
    return result


def _freshness(s, ctx, product_id, row, value, current):
    state = _read_evidence(s, ctx, product_id, row)
    build = _build(s, ctx, product_id, row.build_id)
    try:
        live = _bound(s, ctx, product_id, build, now())
        if isinstance(value, SnapshotDTO):
            freshness = _rule(
                snapshot_freshness,
                value,
                live,
                now(),
                current_snapshot=_snapshot(current) if current else None,
                historical=current is None or current.id != row.id,
            )
        else:
            freshness = _rule(
                projection_freshness,
                value,
                live,
                now(),
                supply=_snapshot(current) if current else None,
                alternates=(),
            )
    except DomainError as error:
        if error.status == 403 or error.code not in {
            "SOURCE_STALE",
            "SOURCE_UNAVAILABLE",
            "DEMAND_SNAPSHOT_INCOMPLETE",
            "VERSION_CONFLICT",
            "PORT_UNCONNECTED",
        }:
            raise
        freshness = Freshness(state="requires_recalculation", reasons=(error.code,))
    if state != "current":
        freshness = Freshness(
            state="requires_recalculation",
            reasons=tuple(sorted({*freshness.reasons, "source_changed"})),
        )
    return freshness


def get_snapshot(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    row, _ = _row(s, ctx, product_id, SupplySnapshot, identity)
    value = _snapshot(row)
    _, current = _current(s, ctx, product_id, row.build_id)
    freshness = _freshness(s, ctx, product_id, row, value, current)
    original_bound = BoundDemand.model_validate(row.bound_demand)
    view = snapshot_view(
        value,
        original_bound.basis,
        freshness,
        SupplyReconciliation.model_validate(row.reconciliation),
    )
    view.update(_metadata(row))
    return row, view


def get_kit(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    row, _ = _row(s, ctx, product_id, KitProjection, identity)
    value = CoverageProjection.model_validate(row.projection)
    if digest(value) != row.projection_sha256:
        raise DomainError("INTEGRITY_MISMATCH", "齐套投影摘要无法核对。")
    _, current = _current(s, ctx, product_id, row.build_id)
    view = projection_view(
        value,
        record_id=str(row.id),
        revision=row.revision,
        created_at=row.created_at,
        freshness=_freshness(s, ctx, product_id, row, value, current),
    )
    view.update({**_metadata(row), "supply_snapshot_id": str(row.supply_snapshot_id)})
    return row, view


def list_supply(s, ctx, product_id):
    _human(s, ctx, product_id)
    result = {
        "captures": [],
        "snapshots": [],
        "kits": [],
        "current_by_build": {},
        "has_more": False,
        "unavailable_count": 0,
        "inventory_scope_complete": False,
        "qualification_status": "unknown",
    }
    for key, model, getter in (
        (
            "captures",
            SupplyCapture,
            lambda s, ctx, pid, rid: (
                None,
                _capture_view(s, ctx, pid, _row(s, ctx, pid, SupplyCapture, rid)[0]),
            ),
        ),
        ("snapshots", SupplySnapshot, get_snapshot),
        ("kits", KitProjection, get_kit),
    ):
        rows = s.scalars(
            select(model)
            .where(
                model.tenant_id == ctx.tenant_id,
                model.product_id == product_id,
            )
            .order_by(model.created_at.desc(), model.id)
            .limit(101)
        ).all()
        result["has_more"] |= len(rows) > 100
        for row in rows[:100]:
            try:
                result[key].append(getter(s, ctx, product_id, row.id)[1])
            except DomainError as error:
                if error.status != 403:
                    raise
                result["unavailable_count"] += 1
    for snapshot in result["snapshots"]:
        pointer, current = _current(s, ctx, product_id, UUID(snapshot["build_id"]))
        if current is not None and str(current.id) == snapshot["id"]:
            result["current_by_build"][snapshot["build_id"]] = {
                "snapshot_id": str(pointer.snapshot_id),
                "revision": pointer.snapshot_revision,
            }
    return result
