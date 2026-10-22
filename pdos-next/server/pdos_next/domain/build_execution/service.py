"""Record external observations and physical identities without authorizing Build execution."""

from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select

from pdos_next.database import category_for_product
from pdos_next.domain.configurations.service import (
    _merge_reads,
    _source_state,
    get_engineering,
    get_process,
)
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, now
from pdos_next.request_proof import snapshot_get, snapshot_scalar

from .comparison import compare_configurations
from .models import ActualConfiguration, BuildLot, SampleAllocation, SampleUnit
from .schemas import ActualConfigurationPayload, OutputPayload, SampleAllocatePayload

SUBJECTS = {
    ActualConfigurationPayload: (ActualConfiguration, "actual_configuration"),
    OutputPayload: (BuildLot, "build_lot"),
    SampleAllocatePayload: (SampleAllocation, "sample_allocation"),
}
EFFECT = (
    "只记录实际配置、外部已发生产出或单件身份；保留原计划与未知准备条件，"
    "不批准开工、放行、品质接收、测试预约或样件消耗。"
)


def _human(s, ctx, product_id, *, write=False):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id, write=write, lock=write)
    actor = s.get(Principal, ctx.actor_id)
    if ctx.run_id is not None or ctx.actor_id != ctx.requester_id or actor.kind != "human":
        raise DomainError("NAMED_DECISION_REQUIRED", "本轮实际观察由当前具名本人记录。", 403)


def _row(s, ctx, product_id, model, identity, *, write=False):
    if not write:
        row = snapshot_get(s, model, identity, scope_id=product_id)
        if row is None or row.tenant_id != ctx.tenant_id or row.product_id != product_id:
            raise DomainError("FORBIDDEN_SCOPE", "实物记录不在当前可见型号范围。", 403)
        return row
    row = snapshot_scalar(
        s,
        (model, product_id, identity),
        select(model).where(
            model.id == identity,
            model.product_id == product_id,
            model.tenant_id == ctx.tenant_id,
        ),
        scope_id=product_id,
    )
    if not row or (write and row.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "本轮观察或样件不在当前可用范围。", 403)
    return row


def _build_context(s, ctx, product_id, build_id, *, write=False):
    from pdos_next.domain.builds.service import _build, _linked

    build = _build(s, ctx, product_id, build_id, write=write)
    project, engineering, manufacturing, reads = _linked(s, ctx, product_id, build, write=write)
    return build, project, engineering, manufacturing, reads


def _visibility(s, ctx, product_id, rows, reads):
    from pdos_next.models import Artifact

    private = any(
        row.visibility != "category"
        if not isinstance(row, dict)
        else row["visibility"] != "category"
        for row in rows
    )
    for read in reads:
        source = s.get(Artifact, UUID(read["artifact_id"]))
        if not source or source.product_id != product_id or source.tenant_id != ctx.tenant_id:
            raise DomainError("SOURCE_UNAVAILABLE", "固定来源权限需要重核。", 403)
        private |= source.visibility != "category"
    return "private" if private else "category"


def _comparison(s, ctx, product_id, build_id, engineering_id, manufacturing_id, *, write=False):
    build, project, planned_engineering, planned_manufacturing, planned_reads = _build_context(
        s,
        ctx,
        product_id,
        build_id,
        write=write,
    )
    engineering, actual_engineering = get_engineering(s, ctx, product_id, engineering_id)
    manufacturing, actual_manufacturing = get_process(s, ctx, product_id, manufacturing_id)
    if actual_manufacturing["engineering_configuration_id"] != actual_engineering["id"]:
        raise DomainError("CONFIGURATION_MISMATCH", "实际制造配置必须关联所选实际工程版本。")
    reads = _merge_reads(
        planned_reads,
        actual_engineering["required_source_read_set"],
        actual_manufacturing["required_source_read_set"],
    )
    return {
        "build": build,
        "project": project,
        "engineering_row": engineering,
        "manufacturing_row": manufacturing,
        "planned": {
            "engineering_configuration": planned_engineering,
            "manufacturing_configuration": planned_manufacturing,
        },
        "actual": {
            "engineering_configuration": actual_engineering,
            "manufacturing_configuration": actual_manufacturing,
        },
        "differences": compare_configurations(
            planned_engineering, planned_manufacturing, actual_engineering, actual_manufacturing
        ),
        "reads": reads,
        "visibility": _visibility(
            s, ctx, product_id, [build, project, actual_engineering, actual_manufacturing], reads
        ),
    }


def compare(
    s, ctx, product_id, build_id, engineering_configuration_id, manufacturing_configuration_id
):
    _human(s, ctx, product_id)
    value = _comparison(
        s, ctx, product_id, build_id, engineering_configuration_id, manufacturing_configuration_id
    )
    build = value["build"]
    return {
        "build": {
            "id": str(build.id),
            "revision": build.revision,
            "name": build.name,
            "project_id": str(build.project_id),
            "unit": build.unit,
            "planned_quantity": str(build.planned_quantity),
            "status": build.status,
        },
        "planned": value["planned"],
        "actual": value["actual"],
        "differences": value["differences"],
        "required_source_read_set": value["reads"],
        "source_status": _source_state(s, ctx, product_id, value["reads"]),
        "visibility": value["visibility"],
        "authorization_status": "not_authorized",
        "qualification_status": "unknown",
    }


def _actual_context(s, ctx, product_id, identity, *, write=False):
    row = _row(s, ctx, product_id, ActualConfiguration, identity, write=write)
    value = _comparison(
        s,
        ctx,
        product_id,
        row.build_id,
        row.actual_engineering_configuration_id,
        row.actual_manufacturing_configuration_id,
        write=write,
    )
    build = value["build"]
    if (
        row.project_id != build.project_id
        or row.planned_engineering_configuration_id != build.engineering_configuration_id
        or row.planned_manufacturing_configuration_id != build.manufacturing_configuration_id
        or row.actual_engineering_revision != value["engineering_row"].revision
        or row.actual_manufacturing_revision != value["manufacturing_row"].revision
    ):
        raise DomainError("CONFIGURATION_MISMATCH", "实际快照与固定轮次及配置范围不一致。")
    value["reads"] = _merge_reads(value["reads"], row.required_source_read_set)
    value["actual_row"] = row
    return value


def _base_view(s, ctx, product_id, row):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "product_id": str(row.product_id),
        "project_id": str(row.project_id),
        "build_id": str(row.build_id),
        "build_revision": row.build_revision,
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "reason": row.reason,
        "sources": deepcopy(row.sources),
        "required_source_read_set": deepcopy(row.required_source_read_set),
        "source_status": _source_state(s, ctx, product_id, row.required_source_read_set),
        "qualification_status": "unknown",
        "authorization_status": "not_authorized",
        "observation_route": "external_observation",
        "verification_status": "not_checked",
    }


def get_actual_configuration(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    value = _actual_context(s, ctx, product_id, identity)
    row = value["actual_row"]
    result = _base_view(s, ctx, product_id, row)
    result.update(
        {
            "planned": value["planned"],
            "actual": value["actual"],
            "planned_engineering_configuration_id": str(row.planned_engineering_configuration_id),
            "planned_manufacturing_configuration_id": str(
                row.planned_manufacturing_configuration_id
            ),
            "actual_engineering_configuration_id": str(row.actual_engineering_configuration_id),
            "actual_engineering_revision": row.actual_engineering_revision,
            "actual_manufacturing_configuration_id": str(row.actual_manufacturing_configuration_id),
            "actual_manufacturing_revision": row.actual_manufacturing_revision,
            "observed_at": row.observed_at.isoformat(),
            "differences": deepcopy(row.differences),
            "build_name": value["build"].name,
            "plan_status": value["build"].status,
        }
    )
    return row, result


def _identified_count(s, ctx, product_id, lot_id):
    return (
        s.scalar(
            select(func.count())
            .select_from(SampleUnit)
            .where(
                SampleUnit.tenant_id == ctx.tenant_id,
                SampleUnit.product_id == product_id,
                SampleUnit.lot_id == lot_id,
            )
        )
        or 0
    )


def _build_observed_count(s, ctx, product_id, build_id, unit):
    return (
        s.scalar(
            select(func.sum(BuildLot.observed_unit_count)).where(
                BuildLot.tenant_id == ctx.tenant_id,
                BuildLot.product_id == product_id,
                BuildLot.build_id == build_id,
                BuildLot.unit == unit,
            )
        )
        or 0
    )


def _lot_context(s, ctx, product_id, identity, *, write=False):
    lot = _row(s, ctx, product_id, BuildLot, identity, write=write)
    value = _actual_context(s, ctx, product_id, lot.actual_configuration_id, write=write)
    actual, build = value["actual_row"], value["build"]
    if (
        lot.build_id != build.id
        or lot.project_id != build.project_id
        or lot.actual_configuration_revision != actual.revision
    ):
        raise DomainError("CONFIGURATION_MISMATCH", "产出批次与实际配置范围不一致。")
    value["reads"] = _merge_reads(value["reads"], lot.required_source_read_set)
    value["lot"] = lot
    return value


def get_lot(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    value = _lot_context(s, ctx, product_id, identity)
    row, build = value["lot"], value["build"]
    count = _identified_count(s, ctx, product_id, row.id)
    observed = _build_observed_count(s, ctx, product_id, build.id, row.unit)
    result = _base_view(s, ctx, product_id, row)
    result.update(
        {
            "actual_configuration_id": str(row.actual_configuration_id),
            "actual_configuration_revision": row.actual_configuration_revision,
            "lot_label": row.lot_label,
            "observed_unit_count": row.observed_unit_count,
            "unit": row.unit,
            "identified_count": count,
            "remaining_unit_count": row.observed_unit_count - count,
            "build_observed_unit_count": observed,
            "planned_quantity": str(build.planned_quantity),
            "over_planned_quantity": Decimal(observed) > build.planned_quantity,
            "plan_status": build.status,
            "build_name": build.name,
            "observation": {
                "system": row.observation_system,
                "external_id": row.observation_external_id,
                "nature": row.observation_nature,
                "occurred_at": row.occurred_at.isoformat(),
                "received_at": row.received_at.isoformat(),
            },
            "quality_status": "unknown",
        }
    )
    return row, result


def get_sample(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    row = _row(s, ctx, product_id, SampleUnit, identity)
    value = _lot_context(s, ctx, product_id, row.lot_id)
    return row, sample_view(s, ctx, product_id, row, value)


def sample_view(s, ctx, product_id, row, value):
    """Render a Sample after its consumer ACL and full physical chain are checked."""
    result = _base_view(s, ctx, product_id, row)
    result.update(
        {
            "label": row.label,
            "lot_id": str(row.lot_id),
            "allocation_id": str(row.allocation_id),
            "actual_configuration_id": str(row.actual_configuration_id),
            "actual_configuration_revision": value["actual_row"].revision,
            **{
                field: getattr(row, field)
                for field in (
                    "operation_key",
                    "cavity",
                    "custodian_label",
                    "location",
                    "destination",
                    "availability",
                )
            },
            "custodian_id": str(row.custodian_id) if row.custodian_id else None,
            "reservation": None,
            "consumption": None,
            "observation_nature": value["lot"].observation_nature,
        }
    )
    return result


def get_allocation(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    row = _row(s, ctx, product_id, SampleAllocation, identity)
    _lot_context(s, ctx, product_id, row.lot_id)
    result = _base_view(s, ctx, product_id, row)
    samples = s.scalars(
        select(SampleUnit)
        .where(
            SampleUnit.tenant_id == ctx.tenant_id,
            SampleUnit.product_id == product_id,
            SampleUnit.allocation_id == row.id,
        )
        .order_by(SampleUnit.label)
    ).all()
    result.update(
        {
            "lot_id": str(row.lot_id),
            "actual_configuration_id": str(row.actual_configuration_id),
            "unit_count": row.unit_count,
            "sample_ids": [str(sample.id) for sample in samples],
            "samples": [
                {"id": str(sample.id), "label": sample.label, "availability": sample.availability}
                for sample in samples
            ],
        }
    )
    return row, result


def _inputs(s, ctx, product_id, payload):
    if isinstance(payload, ActualConfigurationPayload):
        value = _comparison(
            s,
            ctx,
            product_id,
            payload.build_id,
            payload.actual_engineering_configuration_id,
            payload.actual_manufacturing_configuration_id,
            write=True,
        )
    elif isinstance(payload, OutputPayload):
        value = _actual_context(s, ctx, product_id, payload.actual_configuration_id, write=True)
        if value["build"].id != payload.build_id:
            raise DomainError("FORBIDDEN_SCOPE", "实际配置不属于本轮Build。", 403)
    else:
        value = _lot_context(s, ctx, product_id, payload.lot_id, write=True)
    references = [reference.model_dump(mode="json") for reference in payload.sources]
    if isinstance(payload, ActualConfigurationPayload):
        references.extend(
            reference.model_dump(mode="json")
            for difference in payload.differences
            for reference in difference.sources
        )
    value["reads"] = _merge_reads(value["reads"], references)
    value["references"] = references
    rows = [value["build"], value["project"], *value["actual"].values()]
    for key in ("actual_row", "lot"):
        if key in value:
            rows.append(value[key])
    value["visibility"] = _visibility(s, ctx, product_id, rows, value["reads"])
    return value


def _checked_inputs(s, ctx, command, product, payload):
    from pdos_next.service import source_for

    _human(s, ctx, product.id, write=True)
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "产出观察不在当前型号范围。", 403)
    value = _inputs(s, ctx, product.id, payload)
    supplied = {str(read.artifact_id): read.expected_revision for read in command.source_read_set}
    lines = {}
    for reference in value["reads"]:
        identity = reference["artifact_id"]
        if supplied.get(identity) != reference["expected_revision"]:
            raise DomainError(
                "MISSING_REQUIRED_EVIDENCE", "需要计划、实际配置与事实的全部固定来源。"
            )
        source = source_for(s, ctx, product.id, UUID(identity), reference["expected_revision"])
        lines[identity] = source.content.splitlines()
    for reference in value["references"]:
        content = lines[reference["artifact_id"]]
        if (
            reference["line"] > len(content)
            or reference["quote"] not in content[reference["line"] - 1]
        ):
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "观察事实与差异须在指定原文行精确定位。")
    return value


def validate(s, ctx, command, product, payload):
    # Current scope and evidence precede replay. All new-write conditions follow replay.
    _checked_inputs(s, ctx, command, product, payload)


def _version(row, expected):
    if row.revision != expected:
        raise DomainError("VERSION_CONFLICT", "固定对象已变化，请核对实际版本。")


def _duplicate(s, ctx, product_id, model, condition, code, message):
    rows = s.scalars(
        select(model).where(
            model.tenant_id == ctx.tenant_id,
            model.product_id == product_id,
            condition,
        )
    ).all()
    if rows:
        raise DomainError(code, message)


def _new_write(s, ctx, command, product, payload, value):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围已变化，请重新读取。")
    if isinstance(payload, ActualConfigurationPayload):
        _version(value["build"], payload.expected_build_revision)
        _version(value["engineering_row"], payload.expected_actual_engineering_revision)
        _version(value["manufacturing_row"], payload.expected_actual_manufacturing_revision)
        if payload.observed_at > now():
            raise DomainError("INVALID_EVENT_TIME", "实际配置的观察时间不得在未来。", 422)
        if {item.path for item in payload.differences} != {
            difference["path"] for difference in value["differences"]
        }:
            raise DomainError(
                "CONFIGURATION_DIFFERENCE_REQUIRED",
                "须逐项解释实际比较中的全部差异并给出来源。",
                422,
            )
    elif isinstance(payload, OutputPayload):
        _version(value["build"], payload.expected_build_revision)
        _version(value["actual_row"], payload.expected_actual_configuration_revision)
        if payload.unit != value["build"].unit:
            raise DomainError(
                "UNIT_MISMATCH", "观察单位须与本轮离散单位完全一致，不作隐式换算。", 422
            )
        if payload.observation.occurred_at > now():
            raise DomainError(
                "INVALID_EVENT_TIME", "只能记录已发生的外部产出，不能把预测登记为实际。", 422
            )
        _duplicate(
            s,
            ctx,
            product.id,
            BuildLot,
            or_(
                BuildLot.lot_label == payload.lot_label,
                (BuildLot.observation_system == payload.observation.system)
                & (BuildLot.observation_external_id == payload.observation.external_id),
            ),
            "DUPLICATE_OBSERVATION",
            "同一批次标签或外部产出事件不能重复登记。",
        )
    else:
        lot = value["lot"]
        _version(lot, payload.expected_lot_revision)
        count = _identified_count(s, ctx, product.id, lot.id)
        if count + len(payload.samples) > lot.observed_unit_count:
            raise DomainError("OUTPUT_QUANTITY_EXCEEDED", "样件件数超过本批已观察的真实产出限额。")
        _duplicate(
            s,
            ctx,
            product.id,
            SampleUnit,
            SampleUnit.label.in_([sample.label for sample in payload.samples]),
            "DUPLICATE_SAMPLE_IDENTITY",
            "同一实物标签已建立身份，不能重复有效分配。",
        )
        operations = {
            operation["key"]
            for operation in value["actual"]["manufacturing_configuration"]["operations"]
        }
        for sample in payload.samples:
            if sample.operation_key is not None and sample.operation_key not in operations:
                raise DomainError("CONFIGURATION_MISMATCH", "样件来源工序不在本批实际制造配置。")
            if sample.custodian_id is None:
                continue
            principal = s.get(Principal, sample.custodian_id)
            grant = s.scalar(
                select(Grant)
                .where(
                    Grant.tenant_id == ctx.tenant_id,
                    Grant.category_id == category_for_product(product.id),
                    Grant.principal_id == sample.custodian_id,
                    (Grant.expires_at.is_(None) | (Grant.expires_at > now())),
                )
                .with_for_update()
            )
            if (
                not principal
                or principal.tenant_id != ctx.tenant_id
                or not principal.active
                or principal.kind != "human"
                or not grant
            ):
                raise DomainError("FORBIDDEN_SCOPE", "本系统保管者须为当前型号有效人类成员。", 403)


def semantic(payload):
    value = payload.model_dump(mode="json")
    value.pop("confirmation_token", None)
    value["sources"] = sorted(
        value["sources"],
        key=lambda ref: (
            ref["artifact_id"],
            ref["expected_revision"],
            ref["line"],
            ref["quote"],
        ),
    )
    if "differences" in value:
        value["differences"] = sorted(
            value["differences"], key=lambda difference: difference["path"]
        )
        for difference in value["differences"]:
            difference["sources"] = sorted(
                difference["sources"],
                key=lambda ref: (
                    ref["artifact_id"],
                    ref["expected_revision"],
                    ref["line"],
                    ref["quote"],
                ),
            )
    if "samples" in value:
        value["samples"] = sorted(value["samples"], key=lambda sample: sample["label"])
    return value


def _differences(payload, value):
    explanations = {item.path: item for item in payload.differences}
    return [
        {
            **deepcopy(difference),
            "reason": explanations[difference["path"]].reason,
            "sources": [
                reference.model_dump(mode="json")
                for reference in explanations[difference["path"]].sources
            ],
        }
        for difference in value["differences"]
    ]


def _after(s, ctx, product, payload, value):
    build = value["build"]
    result = {
        "id": None,
        "revision": 1,
        "product_id": str(product.id),
        "project_id": str(build.project_id),
        "build_id": str(build.id),
        "build_revision": build.revision,
        "owner_id": str(ctx.requester_id),
        "visibility": value["visibility"],
        "created_at": None,
        "reason": payload.reason,
        "sources": [reference.model_dump(mode="json") for reference in payload.sources],
        "required_source_read_set": value["reads"],
        "source_status": "current",
        "qualification_status": "unknown",
        "authorization_status": "not_authorized",
        "observation_route": "external_observation",
        "verification_status": "not_checked",
        "plan_status": build.status,
    }
    if isinstance(payload, ActualConfigurationPayload):
        result.update(
            {
                "status": "recorded",
                "planned": value["planned"],
                "actual": value["actual"],
                "planned_engineering_configuration_id": str(build.engineering_configuration_id),
                "planned_manufacturing_configuration_id": str(build.manufacturing_configuration_id),
                "actual_engineering_configuration_id": str(
                    payload.actual_engineering_configuration_id
                ),
                "actual_engineering_revision": payload.expected_actual_engineering_revision,
                "actual_manufacturing_configuration_id": str(
                    payload.actual_manufacturing_configuration_id
                ),
                "actual_manufacturing_revision": payload.expected_actual_manufacturing_revision,
                "observed_at": payload.observed_at.isoformat(),
                "differences": _differences(payload, value),
            }
        )
    elif isinstance(payload, OutputPayload):
        observed_before = _build_observed_count(s, ctx, product.id, build.id, payload.unit)
        observed_after = observed_before + payload.observed_unit_count
        result.update(
            {
                "status": "observed",
                "actual_configuration_id": str(payload.actual_configuration_id),
                "actual_configuration_revision": value["actual_row"].revision,
                "lot_label": payload.lot_label,
                "observed_unit_count": payload.observed_unit_count,
                "unit": payload.unit,
                "identified_count": 0,
                "remaining_unit_count": payload.observed_unit_count,
                "build_observed_unit_count_before": observed_before,
                "build_observed_unit_count_after": observed_after,
                "build_observed_unit_count": observed_after,
                "planned_quantity": str(build.planned_quantity),
                "over_planned_quantity": Decimal(observed_after) > build.planned_quantity,
                "observation": {**payload.observation.model_dump(mode="json"), "received_at": None},
                "quality_status": "unknown",
            }
        )
    else:
        count = _identified_count(s, ctx, product.id, value["lot"].id)
        result.update(
            {
                "status": "identified",
                "lot_id": str(value["lot"].id),
                "actual_configuration_id": str(value["actual_row"].id),
                "unit_count": len(payload.samples),
                "identified_count_before": count,
                "remaining_unit_count_after": value["lot"].observed_unit_count
                - count
                - len(payload.samples),
                "samples": [
                    {
                        **sample.model_dump(mode="json"),
                        "id": None,
                        "reservation": None,
                        "consumption": None,
                    }
                    for sample in sorted(payload.samples, key=lambda item: item.label)
                ],
            }
        )
    return result


def preview_view(s, ctx, command, product, payload):
    value = _checked_inputs(s, ctx, command, product, payload)
    _new_write(s, ctx, command, product, payload, value)
    name = (
        value["build"].name
        if isinstance(payload, ActualConfigurationPayload)
        else (payload.lot_label if isinstance(payload, OutputPayload) else value["lot"].lot_label)
    )
    return {
        "operation": command.operation,
        "name": name,
        "effect": EFFECT,
        "before": None,
        "after": _after(s, ctx, product, payload, value),
        "reason": payload.reason,
    }


def apply(s, ctx, command, product, payload):
    value = _checked_inputs(s, ctx, command, product, payload)
    _new_write(s, ctx, command, product, payload, value)
    build = value["build"]
    values = {
        "id": uuid4(),
        "tenant_id": ctx.tenant_id,
        "product_id": product.id,
        "project_id": build.project_id,
        "build_id": build.id,
        "build_revision": build.revision,
        "owner_id": ctx.requester_id,
        "visibility": value["visibility"],
        "revision": 1,
        "reason": payload.reason,
        "sources": [ref.model_dump(mode="json") for ref in payload.sources],
        "required_source_read_set": value["reads"],
    }
    if isinstance(payload, ActualConfigurationPayload):
        values.update(
            {
                "planned_engineering_configuration_id": build.engineering_configuration_id,
                "planned_manufacturing_configuration_id": build.manufacturing_configuration_id,
                "actual_engineering_configuration_id": payload.actual_engineering_configuration_id,
                "actual_engineering_revision": value["engineering_row"].revision,
                "actual_manufacturing_configuration_id": (
                    payload.actual_manufacturing_configuration_id
                ),
                "actual_manufacturing_revision": value["manufacturing_row"].revision,
                "observed_at": payload.observed_at,
                "differences": _differences(payload, value),
            }
        )
    elif isinstance(payload, OutputPayload):
        received = now()
        values.update(
            {
                "actual_configuration_id": value["actual_row"].id,
                "actual_configuration_revision": value["actual_row"].revision,
                "lot_label": payload.lot_label,
                "observed_unit_count": payload.observed_unit_count,
                "unit": payload.unit,
                "observation_system": payload.observation.system,
                "observation_external_id": payload.observation.external_id,
                "observation_nature": payload.observation.nature,
                "occurred_at": payload.observation.occurred_at,
                "received_at": received,
                "created_at": received,
            }
        )
    else:
        values.update(
            {
                "lot_id": value["lot"].id,
                "actual_configuration_id": value["actual_row"].id,
                "unit_count": len(payload.samples),
            }
        )
    model, subject_type = SUBJECTS[type(payload)]
    row = model(**values)
    s.add(row)
    s.flush()
    if isinstance(payload, SampleAllocatePayload):
        samples = []
        for sample in sorted(payload.samples, key=lambda item: item.label):
            unit = SampleUnit(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                project_id=build.project_id,
                build_id=build.id,
                build_revision=build.revision,
                owner_id=ctx.requester_id,
                visibility=value["visibility"],
                revision=1,
                reason=payload.reason,
                sources=values["sources"],
                required_source_read_set=value["reads"],
                lot_id=value["lot"].id,
                allocation_id=row.id,
                actual_configuration_id=value["actual_row"].id,
                **sample.model_dump(),
            )
            s.add(unit)
            samples.append(str(unit.id))
        s.flush()
        row.action_result = {"sample_ids": samples, "unit_count": len(samples)}
    return row, subject_type, row.visibility


def list_execution(s, ctx, product_id):
    _human(s, ctx, product_id)
    result = {
        "actual_configurations": [],
        "lots": [],
        "allocations": [],
        "samples": [],
        "unavailable_count": 0,
        "has_more": False,
        "authorization_status": "not_authorized",
        "qualification_status": "unknown",
    }
    for key, model, getter in (
        ("actual_configurations", ActualConfiguration, get_actual_configuration),
        ("lots", BuildLot, get_lot),
        ("allocations", SampleAllocation, get_allocation),
        ("samples", SampleUnit, get_sample),
    ):
        rows = s.scalars(
            select(model)
            .where(
                model.tenant_id == ctx.tenant_id,
                model.product_id == product_id,
            )
            .order_by(model.created_at.desc(), model.id)
        ).all()

        for row in rows:
            try:
                result[key].append(getter(s, ctx, product_id, row.id)[1])
            except DomainError as error:
                if error.reason not in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE", "SOURCE_STALE"}:
                    raise
                result["unavailable_count"] += 1
    return result
