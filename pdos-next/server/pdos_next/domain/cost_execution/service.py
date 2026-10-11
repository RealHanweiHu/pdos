"""Common-transaction cost inputs and projections; facts never approve procurement."""

import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.domain.configurations.service import _decimal, _merge_reads
from pdos_next.domain.supply_cost.adapters import cost_candidate
from pdos_next.domain.supply_cost.read_models import binding_view, projection_view
from pdos_next.domain.supply_cost.rules import (
    basis_binding,
    projection_freshness,
    require_binding,
    require_current,
    require_scope,
)
from pdos_next.domain.supply_execution.service import (
    _bound,
    _build,
    _human,
    _linked,
    _metadata,
    _read_evidence,
    _row,
    _rule,
    _sources,
    _visibility,
)
from pdos_next.engines.supply_cost.common import SnapshotRef, digest
from pdos_next.engines.supply_cost.dto import ExchangeRate, PriceSnapshot, ProcessSnapshot
from pdos_next.errors import DomainError
from pdos_next.models import Product, now
from pdos_next.schemas.supply_cost.dto import BoundDemand, CostInputs, CostProjection, Freshness

from .models import CostCapture, CostCurrent, CostEstimate, CostInputSnapshot
from .schemas import CostCaptureInput, InputsRecordPayload

INPUTS_EFFECT = (
    "人工保存整版成本口径、报价、工艺数量及汇率观察与前版差异；"
    "未知保持未知，不替代采购批准、供应承诺或实际成本。"
)
ESTIMATE_EFFECT = "按固定试制需求确定性估算成本与缺项；不批准预算、采购或付款。"


def _current(s, ctx, product_id, build_id, *, lock=False):
    query = select(CostCurrent).where(
        CostCurrent.tenant_id == ctx.tenant_id,
        CostCurrent.product_id == product_id,
        CostCurrent.build_id == build_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    if pointer is None:
        return None, None
    row, _ = _row(s, ctx, product_id, CostInputSnapshot, pointer.input_id)
    if row.revision != pointer.input_revision:
        raise DomainError("INTEGRITY_MISMATCH", "成本当前指针与固定输入不一致。")
    return pointer, row


def _input_dto(row):
    value = CostInputs.model_validate(row.inputs)
    if (
        value.input_id != str(row.id)
        or value.revision != row.revision
        or digest(value) != (row.inputs_sha256)
    ):
        raise DomainError("INTEGRITY_MISMATCH", "固定成本输入摘要无法核对。")
    return value


def _prepared(row):
    value = CostInputs.model_validate(row.proposed_inputs["inputs"])
    previous_id = row.proposed_inputs["previous_input_id"]
    previous_revision = row.proposed_inputs["previous_revision"]
    if (
        value.input_id != str(row.input_id)
        or ((previous_id is None) != (previous_revision is None))
        or value.revision != (previous_revision + 1 if previous_revision else 1)
    ):
        raise DomainError("INTEGRITY_MISMATCH", "成本捕获的固定身份或前版不一致。")
    return value, previous_id, previous_revision


def _references(data):
    refs = [*data.sources]
    for item in (*data.prices, *data.rates):
        refs.extend(item.sources)
    if data.process:
        refs.extend(data.process.sources)
        for operation in data.process.operations:
            refs.extend(operation.sources)
    values = {json.dumps(ref.model_dump(mode="json"), sort_keys=True): ref for ref in refs}
    return [values[key].model_dump(mode="json") for key in sorted(values)]


def _normalized_input(data):
    raw = data.model_dump(mode="json")

    def normalize(row, decimals=()):
        for field in decimals:
            if row[field] is not None:
                number = Decimal(row[field])
                row[field] = "0" if number == 0 else _decimal(number)
        if "sources" in row:
            row["sources"].sort(
                key=lambda ref: (
                    ref["artifact_id"],
                    ref["expected_revision"],
                    ref["line"],
                    ref["quote"],
                )
            )

    normalize(raw)
    normalize(raw["cost_scope"], ("nre_volume",))
    for price in raw["prices"]:
        normalize(
            price, ("amount", "price_quantity", "tax_rate", "minimum_quantity", "maximum_quantity")
        )
    for rate in raw["rates"]:
        normalize(rate, ("rate",))
    if raw["process"]:
        normalize(raw["process"])
        for operation in raw["process"]["operations"]:
            normalize(operation, ("quantity_per_product", "loss_rate"))
        raw["process"]["operations"].sort(key=lambda row: row["operation_id"])
    for field, identity in (
        ("prices", "price_id"),
        ("rates", "rate_id"),
        ("material_prices", "bom_item_id"),
    ):
        raw[field].sort(key=lambda row: row[identity])
    raw["nre_price_ids"].sort()
    if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > 1_000_000:
        raise DomainError("INVALID_PAYLOAD", "成本草稿超过本轮1MB上限，请收敛记录与引用。", 422)
    return raw


def _bindings(data, bound, captured_at):
    items = {line.item_id: line.material_id for line in bound.demand.lines}
    materials = {identity for identity in items.values() if identity is not None}
    operations = set(bound.manufacturing_operation_ids or ())
    prices = {price.price_id: price for price in data.prices}
    for price in data.prices:
        if (price.subject_kind == "material" and price.subject_id not in materials) or (
            price.subject_kind == "process" and price.subject_id not in operations
        ):
            raise DomainError("FORBIDDEN_SCOPE", "价格须绑定固定BOM物料或制造工序。", 403)
    for mapping in data.material_prices:
        price = prices.get(mapping.price_id)
        if (
            mapping.bom_item_id not in items
            or price is None
            or price.subject_kind != "material"
            or price.subject_id != items[mapping.bom_item_id]
        ):
            raise DomainError("FORBIDDEN_SCOPE", "BOM行的价格与固定物料身份不一致。", 403)
    for identity in data.nre_price_ids:
        if identity not in prices or prices[identity].subject_kind != "nre":
            raise DomainError("FORBIDDEN_SCOPE", "NRE选择须指向本版有来源的NRE价格。", 403)
    if data.process is not None:
        if bound.manufacturing_operation_ids is None:
            raise DomainError("PROCESS_MAPPING_UNCONNECTED", "固定制造工序映射尚未接通。")
        if {row.operation_id for row in data.process.operations} != operations:
            raise DomainError("PROCESS_MAPPING_MISMATCH", "工艺输入须完整对应所有固定制造工序。")
        for operation in data.process.operations:
            if operation.price_id is None:
                continue
            price = prices.get(operation.price_id)
            if (
                price is None
                or price.subject_kind != "process"
                or price.subject_id != operation.operation_id
            ):
                raise DomainError("FORBIDDEN_SCOPE", "工序价格须绑定该固定工序。", 403)
    if any(rate.observed_at > captured_at for rate in data.rates):
        raise DomainError("INVALID_EVENT_TIME", "汇率实际观察不能记录未来时间。", 422)


def _proposed(data, bound, refs, input_id, captured_at, previous):
    from pdos_next.service import digest as content_digest

    binding = _rule(basis_binding, bound, captured_at)
    revision = previous.revision + 1 if previous is not None else 1
    raw = data.model_dump(mode="json")

    def fact_ref(identity, fact, observed_at):
        # Hash the complete set of evidence, rather than choosing one quote as authority.
        return SnapshotRef(
            source_id=f"cost-fact:{input_id}:{identity}",
            version=str(revision),
            sha256=content_digest(
                {
                    "fact": fact,
                    "sources": [refs[key].model_dump(mode="json") for key in sorted(refs)],
                }
            ),
            captured_at=observed_at,
            state="current",
        )

    prices = tuple(
        PriceSnapshot(
            **price.model_dump(exclude={"sources"}),
            ref=refs[f"artifact:{price.sources[0].artifact_id}"],
        )
        for price in data.prices
    )
    process = None
    if data.process is not None:
        process = ProcessSnapshot(
            ref=fact_ref("process", raw["process"], captured_at),
            assumption=data.process.assumption,
            operations=tuple(
                row.model_dump(exclude={"sources"}) for row in data.process.operations
            ),
        )
    rates = tuple(
        ExchangeRate(
            **rate.model_dump(exclude={"sources", "observed_at"}),
            ref=fact_ref(f"rate:{rate.rate_id}", raw["rates"][index], rate.observed_at),
        )
        for index, rate in enumerate(data.rates)
    )
    return CostInputs(
        input_id=str(input_id),
        revision=revision,
        scope=bound.scope,
        binding=binding,
        ref=SnapshotRef(
            source_id=f"cost-input:{input_id}",
            version=str(revision),
            sha256=content_digest(
                {
                    "input": raw,
                    "binding": binding.model_dump(mode="json"),
                    "sources": [refs[key].model_dump(mode="json") for key in sorted(refs)],
                }
            ),
            captured_at=captured_at,
            state="current",
        ),
        cost_scope=data.cost_scope,
        prices=prices,
        material_prices=tuple(data.material_prices),
        process=process,
        rates=rates,
        nre_price_ids=tuple(data.nre_price_ids),
    )


def _capture_payload(row):
    _, previous_id, previous_revision = _prepared(row)
    return {
        "build_id": str(row.build_id),
        "expected_build_revision": row.build_revision,
        "capture_id": str(row.id),
        "expected_capture_revision": row.revision,
        "expected_previous_input_id": previous_id,
        "expected_previous_revision": previous_revision,
        "reason": row.reason,
    }


def _capture_view(s, ctx, product_id, row):
    state = _read_evidence(s, ctx, product_id, row)
    applied = s.scalar(
        select(CostInputSnapshot.id).where(
            CostInputSnapshot.tenant_id == ctx.tenant_id,
            CostInputSnapshot.product_id == product_id,
            CostInputSnapshot.capture_id == row.id,
        )
    )
    return {
        "id": str(row.id),
        "revision": row.revision,
        "build_revision": row.build_revision,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "applied_input_id": str(applied) if applied is not None else None,
        "input_snapshot": deepcopy(row.input_snapshot),
        "source_status": state,
        "inputs_record_payload": _capture_payload(row),
        **_metadata(row),
    }


def prepare_capture(s, ctx, product_id, data: CostCaptureInput):
    from pdos_next.database import require_context
    from pdos_next.service import digest as request_digest

    require_context(s, ctx)
    raw = _normalized_input(data)
    data = CostCaptureInput.model_validate(raw)
    references = _references(data)
    fingerprint = request_digest(raw)
    existing = s.scalar(
        select(CostCapture).where(
            CostCapture.tenant_id == ctx.tenant_id,
            CostCapture.product_id == product_id,
            CostCapture.owner_id == ctx.requester_id,
            CostCapture.capture_key == data.capture_key,
        )
    )
    if existing is not None:
        _human(s, ctx, product_id)
        if existing.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "相同捕获编号对应了不同成本内容。")
        view = _capture_view(s, ctx, product_id, existing)
        return {
            "capture": view,
            "inputs_record_payload": view["inputs_record_payload"],
            "required_source_read_set": view["required_source_read_set"],
        }
    product = s.scalar(select(Product).where(Product.id == product_id).with_for_update())
    _human(s, ctx, product_id, write=True)
    build = _build(s, ctx, product_id, data.build_id, write=True)
    existing = s.scalar(
        select(CostCapture).where(
            CostCapture.tenant_id == ctx.tenant_id,
            CostCapture.product_id == product_id,
            CostCapture.owner_id == ctx.requester_id,
            CostCapture.capture_key == data.capture_key,
        )
    )
    if existing is not None:
        if existing.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "相同捕获编号对应了不同成本内容。")
        view = _capture_view(s, ctx, product_id, existing)
        return {
            "capture": view,
            "inputs_record_payload": view["inputs_record_payload"],
            "required_source_read_set": view["required_source_read_set"],
        }
    if (
        data.expected_product_revision != product.revision
        or data.expected_build_revision != build.revision
    ):
        raise DomainError("VERSION_CONFLICT", "产品或试制版本已变化，请重读后再捕获。")
    captured_at = now()
    bound = _bound(s, ctx, product_id, build, captured_at)
    _, previous = _current(s, ctx, product_id, build.id, lock=True)
    _, _, _, planned_reads = _linked(s, ctx, product_id, build, write=True)
    reads = _merge_reads(
        planned_reads, references, previous.required_source_read_set if previous else []
    )
    refs, private = _sources(s, ctx, product_id, reads, references)
    if build.visibility == "category" and private:
        raise DomainError("FORBIDDEN_SCOPE", "私人成本来源须先建立相符的私人试制范围。", 403)
    if previous is not None:
        _rule(require_scope, bound.scope, _input_dto(previous).scope)
    _bindings(data, bound, captured_at)
    input_id = uuid4()
    proposed = _proposed(data, bound, refs, input_id, captured_at, previous)
    row = CostCapture(
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
        input_id=input_id,
        created_at=captured_at,
        input_snapshot=raw,
        bound_demand=bound.model_dump(mode="json"),
        proposed_inputs={
            "inputs": proposed.model_dump(mode="json"),
            "previous_input_id": str(previous.id) if previous else None,
            "previous_revision": previous.revision if previous else None,
        },
        sources=references,
        required_source_read_set=reads,
    )
    s.add(row)
    s.flush()
    view = _capture_view(s, ctx, product_id, row)
    return {
        "capture": view,
        "inputs_record_payload": view["inputs_record_payload"],
        "required_source_read_set": reads,
    }


def _inputs(s, ctx, command, product, payload):
    _human(s, ctx, product.id, write=True)
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "成本命令不在当前型号范围。", 403)
    if isinstance(payload, InputsRecordPayload):
        row, build = _row(s, ctx, product.id, CostCapture, payload.capture_id, write=True)
    else:
        row, build = _row(s, ctx, product.id, CostInputSnapshot, payload.cost_input_id)
    if build.id != payload.build_id:
        raise DomainError("FORBIDDEN_SCOPE", "成本命令不属于该固定试制轮次。", 403)
    _linked(s, ctx, product.id, build)
    supplied = {str(ref.artifact_id): ref.expected_revision for ref in command.source_read_set}
    for ref in row.required_source_read_set:
        if supplied.get(ref["artifact_id"]) != ref["expected_revision"]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "需要成本输入与双配置的全部固定来源。")
    _, private = _sources(s, ctx, product.id, row.required_source_read_set, row.sources)
    if build.visibility == "category" and private:
        raise DomainError("FORBIDDEN_SCOPE", "私人来源不能扩大到品类共享试制范围。", 403)
    return row, build


def validate(s, ctx, command, product, payload):
    # Current authorization precedes receipt dedup; new-write versions follow it.
    _inputs(s, ctx, command, product, payload)


def semantic(payload):
    raw = payload.model_dump(mode="json")
    raw.pop("confirmation_token", None)
    return raw


def _new_write(s, ctx, command, product, payload, row, build):
    if (
        command.expected_revision != product.revision
        or payload.expected_build_revision != build.revision
    ):
        raise DomainError("VERSION_CONFLICT", "产品或试制版本已变化，请重新读取。")
    as_of = now()
    pointer, previous = _current(s, ctx, product.id, build.id, lock=True)
    if isinstance(payload, InputsRecordPayload):
        if (
            row.revision != payload.expected_capture_revision
            or row.build_revision != build.revision
        ):
            raise DomainError("VERSION_CONFLICT", "成本来源草稿固定版本不一致。")
        value, previous_id, previous_revision = _prepared(row)
        if (
            previous_id
            != (
                str(payload.expected_previous_input_id)
                if payload.expected_previous_input_id
                else None
            )
            or previous_revision != payload.expected_previous_revision
        ):
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "前版指针不属于该固定成本捕获。")
        if (str(previous.id) if previous else None) != previous_id or (
            previous.revision if previous else None
        ) != previous_revision:
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "成本当前输入已变化，请重新捕获与核对。")
        if (
            s.scalar(
                select(CostInputSnapshot.id).where(
                    CostInputSnapshot.tenant_id == ctx.tenant_id,
                    CostInputSnapshot.product_id == product.id,
                    CostInputSnapshot.capture_id == row.id,
                )
            )
            is not None
        ):
            raise DomainError("CAPTURE_ALREADY_APPLIED", "此成本捕获已应用，不能另建重复快照。")
        bound = _bound(s, ctx, product.id, build, as_of)
        _rule(require_binding, _rule(basis_binding, bound, as_of), value.binding)
        for ref in (
            value.ref,
            *(price.ref for price in value.prices),
            *(rate.ref for rate in value.rates),
            *((value.process.ref,) if value.process else ()),
        ):
            _rule(require_current, ref, as_of)
    else:
        if (
            row.revision != payload.expected_cost_input_revision
            or row.build_revision != build.revision
        ):
            raise DomainError("VERSION_CONFLICT", "成本输入固定版本不一致。")
        if previous is None or previous.id != row.id:
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "须按本轮当前成本输入计算。")
        bound = _bound(s, ctx, product.id, build, as_of)
        value = _rule(cost_candidate, bound, _input_dto(row), as_of)
    return bound, pointer, previous, value, as_of


def _validity(value, as_of):
    # Only categorical changes enter confirmation scope; advancing now alone does not.
    prices, rates = [], []
    for price in value.prices:
        state = (
            "estimate"
            if price.stage == "estimate"
            else (
                "validity_unknown"
                if price.valid_from is None or price.valid_until is None
                else "expired"
                if as_of >= price.valid_until
                else "not_yet_valid"
                if as_of < price.valid_from
                else "valid"
            )
        )
        prices.append({"price_id": price.price_id, "state": state})
    for rate in value.rates:
        state = (
            "unknown"
            if rate.rate is None
            else "purpose_mismatch"
            if rate.purpose != value.cost_scope.rate_purpose
            else "aged_out"
            if as_of - rate.ref.captured_at > timedelta(days=value.cost_scope.max_rate_age_days)
            else "valid"
        )
        rates.append({"rate_id": rate.rate_id, "state": state})
    return {"prices": prices, "rates": rates}


def _comparison(previous, row, value):
    old = previous.input_snapshot if previous else {}
    new = row.input_snapshot
    deltas = []
    for field, label in (
        ("cost_scope", "成本口径"),
        ("material_prices", "BOM价格选择"),
        ("process", "每合格产品工艺依据"),
        ("nre_price_ids", "NRE选择"),
        ("sources", "成本口径来源"),
    ):
        if old.get(field) != new.get(field):
            deltas.append(
                {
                    "path": field,
                    "label": label,
                    "before": deepcopy(old.get(field)),
                    "after": deepcopy(new.get(field)),
                }
            )
    for field, key, label in (("prices", "price_id", "价格"), ("rates", "rate_id", "实际汇率观察")):
        before = {item[key]: item for item in old.get(field, [])}
        after = {item[key]: item for item in new[field]}
        for identity in sorted(before.keys() | after.keys()):
            if before.get(identity) != after.get(identity):
                deltas.append(
                    {
                        "path": f"{field}.{identity}",
                        "label": label,
                        "before": deepcopy(before.get(identity)),
                        "after": deepcopy(after.get(identity)),
                    }
                )
    return {
        "before_input_id": str(previous.id) if previous else None,
        "before_revision": previous.revision if previous else None,
        "after_input_id": value.input_id,
        "after_revision": value.revision,
        "deltas": deltas,
    }


def _input_view(
    row,
    value,
    bound,
    freshness,
    source_status,
    *,
    comparison=None,
    previous_id=None,
    previous_revision=None,
    as_of=None,
):
    return {
        "id": value.input_id,
        "revision": value.revision,
        "sha256": digest(value),
        "captured_at": value.ref.captured_at.isoformat(),
        "previous_input_id": previous_id,
        "previous_revision": previous_revision,
        **{
            key: value.model_dump(mode="json")[key]
            for key in (
                "cost_scope",
                "prices",
                "material_prices",
                "process",
                "rates",
                "nre_price_ids",
            )
        },
        "binding": _rule(binding_view, value.binding, bound.basis),
        "freshness": freshness.state,
        "freshness_reasons": list(freshness.reasons),
        "source_status": source_status,
        "input_snapshot": deepcopy(row.input_snapshot),
        "comparison": deepcopy(comparison),
        "validity": _validity(value, as_of or now()),
        **_metadata(row),
    }


def preview_view(s, ctx, command, product, payload):
    row, build = _inputs(s, ctx, command, product, payload)
    if not isinstance(payload, InputsRecordPayload):
        raise DomainError("FORBIDDEN_SCOPE", "确定性成本计算无需人工确认。", 403)
    bound, _, previous, value, as_of = _new_write(s, ctx, command, product, payload, row, build)
    before = (
        _input_view(
            previous,
            _input_dto(previous),
            BoundDemand.model_validate(previous.bound_demand),
            Freshness(state="historical", reasons=()),
            "current",
            comparison=previous.comparison,
            previous_id=str(previous.previous_input_id) if previous.previous_input_id else None,
            previous_revision=previous.previous_revision,
            as_of=as_of,
        )
        if previous
        else None
    )
    _, previous_id, previous_revision = _prepared(row)
    after = _input_view(
        row,
        value,
        bound,
        Freshness(state="current", reasons=()),
        "current",
        comparison=_comparison(previous, row, value),
        previous_id=previous_id,
        previous_revision=previous_revision,
        as_of=as_of,
    )
    after["reason"], after["capture_id"] = payload.reason, str(row.id)
    return {
        "operation": command.operation,
        "name": build.name,
        "effect": INPUTS_EFFECT,
        "before": before,
        "after": after,
        "reason": payload.reason,
    }


def apply(s, ctx, command, product, payload):
    row, build = _inputs(s, ctx, command, product, payload)
    bound, pointer, previous, value, as_of = _new_write(
        s, ctx, command, product, payload, row, build
    )
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
    if isinstance(payload, InputsRecordPayload):
        _, previous_id, previous_revision = _prepared(row)
        saved = CostInputSnapshot(
            id=UUID(value.input_id),
            revision=value.revision,
            capture_id=row.id,
            previous_input_id=UUID(previous_id) if previous_id else None,
            previous_revision=previous_revision,
            inputs=value.model_dump(mode="json"),
            inputs_sha256=digest(value),
            input_snapshot=row.input_snapshot,
            comparison=_comparison(previous, row, value),
            sources=row.sources,
            reason=payload.reason,
            **common,
        )
        s.add(saved)
        s.flush()
        if pointer is None:
            pointer = CostCurrent(
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                build_id=build.id,
                input_id=saved.id,
                input_revision=saved.revision,
            )
            s.add(pointer)
        else:
            pointer.input_id, pointer.input_revision = saved.id, saved.revision
        s.flush()
        return saved, "cost_inputs", saved.visibility
    saved = CostEstimate(
        id=uuid4(),
        revision=1,
        cost_input_id=row.id,
        cost_input_revision=row.revision,
        as_of=as_of,
        projection=value.model_dump(mode="json"),
        projection_sha256=digest(value),
        reason=ESTIMATE_EFFECT,
        **common,
    )
    s.add(saved)
    s.flush()
    return saved, "cost_estimate", saved.visibility


def _freshness(s, ctx, product_id, row, value, current):
    state = _read_evidence(s, ctx, product_id, row)
    build = _build(s, ctx, product_id, row.build_id)
    try:
        as_of = now()
        live = _bound(s, ctx, product_id, build, as_of)
        if isinstance(value, CostProjection):
            freshness = _rule(
                projection_freshness,
                value,
                live,
                as_of,
                cost=_input_dto(current) if current else None,
            )
        else:
            reasons = []
            if value.binding != _rule(basis_binding, live, as_of):
                reasons.append("fixed_basis_changed")
            if current is None or current.id != row.id:
                reasons.append("cost_inputs_superseded")
            try:
                _rule(require_current, value.ref, as_of)
            except DomainError as error:
                reasons.append(error.code)
            freshness = Freshness(
                state="historical"
                if current is None or current.id != row.id
                else "requires_recalculation"
                if reasons
                else "current",
                reasons=tuple(sorted(set(reasons))),
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
    return freshness, state


def get_input(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    row, _ = _row(s, ctx, product_id, CostInputSnapshot, identity)
    value = _input_dto(row)
    _, current = _current(s, ctx, product_id, row.build_id)
    freshness, state = _freshness(s, ctx, product_id, row, value, current)
    view = _input_view(
        row,
        value,
        BoundDemand.model_validate(row.bound_demand),
        freshness,
        state,
        comparison=row.comparison,
        previous_id=str(row.previous_input_id) if row.previous_input_id else None,
        previous_revision=row.previous_revision,
    )
    return row, view


def get_estimate(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    row, _ = _row(s, ctx, product_id, CostEstimate, identity)
    value = CostProjection.model_validate(row.projection)
    if (
        digest(value) != row.projection_sha256
        or value.cost_input_id != str(row.cost_input_id)
        or value.cost_input_revision != row.cost_input_revision
    ):
        raise DomainError("INTEGRITY_MISMATCH", "成本估算投影摘要无法核对。")
    _, current = _current(s, ctx, product_id, row.build_id)
    freshness, state = _freshness(s, ctx, product_id, row, value, current)
    view = projection_view(
        value,
        record_id=str(row.id),
        revision=row.revision,
        created_at=row.created_at,
        freshness=freshness,
    )
    view.update(
        {
            **_metadata(row),
            "cost_input_id": str(row.cost_input_id),
            "cost_input_revision": row.cost_input_revision,
            "source_status": state,
        }
    )
    return row, view


def list_costs(s, ctx, product_id):
    _human(s, ctx, product_id)
    result = {
        "captures": [],
        "inputs": [],
        "estimates": [],
        "current_by_build": {},
        "has_more": False,
        "unavailable_count": 0,
    }
    for key, model, getter in (
        (
            "captures",
            CostCapture,
            lambda s, ctx, pid, rid: (
                None,
                _capture_view(s, ctx, pid, _row(s, ctx, pid, CostCapture, rid)[0]),
            ),
        ),
        ("inputs", CostInputSnapshot, get_input),
        ("estimates", CostEstimate, get_estimate),
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
    for item in result["inputs"]:
        pointer, current = _current(s, ctx, product_id, UUID(item["build_id"]))
        if current is not None and str(current.id) == item["id"]:
            result["current_by_build"][item["build_id"]] = {
                "input_id": str(pointer.input_id),
                "revision": pointer.input_revision,
            }
    return result
