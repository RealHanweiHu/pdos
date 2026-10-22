"""Human T1 draft snapshots with pinned scope, sources and independent revision series."""

from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Principal
from pdos_next.request_proof import batch_read

from .models import BomLine, BomRevision, EngineeringConfiguration, PartIdentity, ProcessRevision
from .schemas import (
    EngineeringBomRevisePayload,
    EngineeringConfigurationCreatePayload,
    NpiProcessRevisePayload,
)

category_lifecycle_fence = True

PAYLOAD_MODELS = {
    EngineeringBomRevisePayload: (BomRevision, "bom_revision"),
    EngineeringConfigurationCreatePayload: (EngineeringConfiguration, "engineering_configuration"),
    NpiProcessRevisePayload: (ProcessRevision, "process_revision"),
}


def _human(s, ctx, product_id, *, write=False):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id, write=write, lock=write)
    actor = s.get(Principal, ctx.actor_id)
    if ctx.run_id is not None or ctx.actor_id != ctx.requester_id or actor.kind != "human":
        raise DomainError("NAMED_DECISION_REQUIRED", "配置草稿由当前具名本人办理。", 403)


def _row(s, ctx, product_id, model, identity):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id)
    row = batch_read(s, model, [identity]).get(identity)
    if not row or row.tenant_id != ctx.tenant_id or row.product_id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "固定配置或物料不在当前授权型号范围。", 403)
    return row


def _merge_reads(*groups):
    reads = {}
    for group in groups:
        for reference in group:
            identity = str(reference["artifact_id"])
            revision = reference["expected_revision"]
            if identity in reads and reads[identity] != revision:
                raise DomainError("SOURCE_STALE", "固定对象引用了同一来源的不同版本。", 422)
            reads[identity] = revision
    return [
        {"artifact_id": identity, "expected_revision": reads[identity]}
        for identity in sorted(reads)
    ]


def _source_state(s, ctx, product_id, reads, cache=None):
    from pdos_next.original_security import source_status
    from pdos_next.service import require_access

    category_id = ctx.category_id or require_access(s, ctx, product_id).category_id
    cache = {} if cache is None else cache
    identities = [UUID(reference["artifact_id"]) for reference in reads]
    cache.update(batch_read(s, Artifact, identities))
    current = True
    for reference in reads:
        identity = UUID(reference["artifact_id"])
        if identity not in cache:
            cache[identity] = s.get(Artifact, identity)
        source = cache[identity]
        if (
            not source
            or source.tenant_id != ctx.tenant_id
            or source.category_id != category_id
            or source.product_id not in (None, product_id)
        ):
            raise DomainError(
                "SOURCE_UNAVAILABLE",
                "来源权限需要重核，配置派生内容暂时隐藏。",
                403,
            )
        state_key = (identity, source.revision, source.status)
        if state_key not in cache:
            cache[state_key] = source_status(s, source)
        current &= (
            cache[state_key] == "active" and source.revision == reference["expected_revision"]
        )
    return "current" if current else "needs_recheck"


def _base_view(s, ctx, product_id, row, cache=None):
    state = _source_state(s, ctx, product_id, row.required_source_read_set, cache)
    result = {
        "id": str(row.id),
        "product_id": str(row.product_id),
        "revision": row.revision,
        "name": row.name,
        "status": row.status,
        "visibility": row.visibility,
        "owner_id": str(row.owner_id),
        "created_at": row.created_at.isoformat(),
        "sources": deepcopy(row.sources),
        "required_source_read_set": deepcopy(row.required_source_read_set),
        "source_status": state,
    }
    if not isinstance(row, PartIdentity):
        result.update(
            {
                "series_id": str(row.series_id),
                "previous_id": str(row.previous_id) if row.previous_id else None,
                "expected_previous_revision": row.expected_previous_revision,
                "reason": row.reason,
            }
        )
    return result


def _part_view(s, ctx, product_id, row, cache=None):
    result = _base_view(s, ctx, product_id, row, cache)
    result.update(
        {
            field: deepcopy(getattr(row, field))
            for field in (
                "internal_number",
                "erp_number",
                "customer_number",
                "mapping_version",
                "external_design_refs",
            )
        }
    )
    result["external_verification"] = "not_checked"
    result["mapping_status"] = "declared" if row.mapping_version else "unknown"
    return result


def _decimal(value):
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _bom_view(s, ctx, product_id, row, cache=None):
    from pdos_next.request_proof import snapshot_rows

    cache = {} if cache is None else cache
    parts, lines = {}, []
    stored_lines = snapshot_rows(
        s,
        (BomLine, product_id, row.id),
        select(BomLine)
        .where(
            BomLine.tenant_id == ctx.tenant_id,
            BomLine.product_id == product_id,
            BomLine.bom_id == row.id,
        )
        .order_by(BomLine.key),
        scope_id=product_id,
    )
    stored_parts = batch_read(s, PartIdentity, [line.part_id for line in stored_lines])
    all_reads = [*row.required_source_read_set]
    for part in stored_parts.values():
        if part is not None:
            all_reads.extend(part.required_source_read_set)
    cache.update(batch_read(s, Artifact, [UUID(ref["artifact_id"]) for ref in all_reads]))
    result = _base_view(s, ctx, product_id, row, cache)
    for line in stored_lines:
        if line.part_id not in parts:
            part = _row(s, ctx, product_id, PartIdentity, line.part_id)
            parts[line.part_id] = _part_view(s, ctx, product_id, part, cache)
        part_view = parts[line.part_id]
        if part_view["revision"] != line.part_revision:
            raise DomainError("VERSION_CONFLICT", "固定物料身份版本不一致。")
        lines.append(
            {
                "key": line.key,
                "part_id": str(line.part_id),
                "expected_part_revision": line.part_revision,
                "part": deepcopy(part_view),
                "quantity": _decimal(line.quantity),
                "unit": line.unit,
                "loss_rate": _decimal(line.loss_rate),
                "critical": line.critical,
                "notes": line.notes,
            }
        )
        if part_view["source_status"] != "current":
            result["source_status"] = "needs_recheck"
    result["lines"] = lines
    return result


def get_bom(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    row = _row(s, ctx, product_id, BomRevision, identity)
    return row, _bom_view(s, ctx, product_id, row)


def _definition(s, ctx, product_id, identity):
    from pdos_next.domain.products.definitions import definition_view
    from pdos_next.domain.products.models import DefinitionRevision

    row = _row(s, ctx, product_id, DefinitionRevision, identity)
    return row, definition_view(s, ctx, row)


def get_engineering(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    row = _row(s, ctx, product_id, EngineeringConfiguration, identity)
    cache = {}
    result = _base_view(s, ctx, product_id, row, cache)
    definition, defined = _definition(s, ctx, product_id, row.definition_id)
    bom = _row(s, ctx, product_id, BomRevision, row.bom_id)
    bom_view = _bom_view(s, ctx, product_id, bom, cache)
    if definition.revision != row.definition_revision or bom.revision != row.bom_revision:
        raise DomainError("VERSION_CONFLICT", "工程配置固定版本不一致。")
    result.update(
        {
            "definition_id": str(row.definition_id),
            "definition_revision": row.definition_revision,
            "definition": {
                key: defined[key]
                for key in (
                    "id",
                    "revision",
                    "title",
                    "status",
                    "visibility",
                    "source_status",
                )
            },
            "bom_id": str(row.bom_id),
            "bom_revision": row.bom_revision,
            "bom": bom_view,
            "design_versions": deepcopy(row.design_versions),
            "external_verification": "not_checked",
        }
    )
    if defined["source_status"] != "current" or bom_view["source_status"] != "current":
        result["source_status"] = "needs_recheck"
    return row, result


def get_process(s, ctx, product_id, identity):
    _human(s, ctx, product_id)
    row = _row(s, ctx, product_id, ProcessRevision, identity)
    result = _base_view(s, ctx, product_id, row)
    engineering, engineered = get_engineering(s, ctx, product_id, row.engineering_configuration_id)
    if engineering.revision != row.engineering_revision:
        raise DomainError("VERSION_CONFLICT", "制造配置固定工程版本不一致。")
    result.update(
        {
            "engineering_configuration_id": str(row.engineering_configuration_id),
            "engineering_revision": row.engineering_revision,
            "engineering_configuration": {
                key: engineered[key]
                for key in (
                    "id",
                    "revision",
                    "name",
                    "status",
                    "definition_id",
                    "bom_id",
                    "source_status",
                )
            },
            "site": row.site,
            "line": row.line,
            "operations": deepcopy(row.operations),
            "external_verification": "not_checked",
            "qualification_status": "unknown",
        }
    )
    if engineered["source_status"] != "current":
        result["source_status"] = "needs_recheck"
    return row, result


def _version(row, expected):
    if row.revision != expected:
        raise DomainError("VERSION_CONFLICT", "固定对象与所选版本不一致。")


def _no_wider(row, visibility):
    if row.visibility != "category" and visibility == "category":
        raise DomainError("FORBIDDEN_SCOPE", "私人固定对象不能扩大为共享配置。", 403)


def _external_references(payload):
    references = []
    if isinstance(payload, EngineeringBomRevisePayload):
        references = [
            ref for line in payload.lines if line.part for ref in line.part.external_design_refs
        ]
    elif isinstance(payload, EngineeringConfigurationCreatePayload):
        references = [
            ref
            for ref in (payload.mechanical, payload.electronic, payload.firmware)
            if ref is not None
        ]
    else:
        references = [operation.sop for operation in payload.operations if operation.sop]
    return [reference.basis for reference in references if reference.basis is not None]


def _inputs(s, ctx, product_id, payload):
    model, _ = PAYLOAD_MODELS[type(payload)]
    result = {"previous": None, "definition": None, "bom": None, "engineering": None, "parts": {}}
    refs = [
        reference.model_dump(mode="json")
        for reference in [*payload.sources, *_external_references(payload)]
    ]
    read_groups = [refs]
    if payload.previous_id:
        previous = _row(s, ctx, product_id, model, payload.previous_id)
        if previous.owner_id != ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "配置修订由该草稿负责人办理。", 403)
        _version(previous, payload.expected_previous_revision)
        _no_wider(previous, payload.visibility)
        read_groups.append(previous.required_source_read_set)
        result["previous"] = previous
    if isinstance(payload, EngineeringBomRevisePayload):
        for line in payload.lines:
            if line.part_id is None or line.part_id in result["parts"]:
                continue
            part = _row(s, ctx, product_id, PartIdentity, line.part_id)
            _no_wider(part, payload.visibility)
            result["parts"][part.id] = (part, _part_view(s, ctx, product_id, part))
            read_groups.append(part.required_source_read_set)
        for line in payload.lines:
            if line.part_id is not None:
                _version(result["parts"][line.part_id][0], line.expected_part_revision)
    elif isinstance(payload, EngineeringConfigurationCreatePayload):
        definition, defined = _definition(s, ctx, product_id, payload.definition_id)
        bom, bom_view = get_bom(s, ctx, product_id, payload.bom_id)
        _version(definition, payload.expected_definition_revision)
        _version(bom, payload.expected_bom_revision)
        _no_wider(definition, payload.visibility)
        _no_wider(bom, payload.visibility)
        result["definition"], result["bom"] = defined, bom_view
        read_groups.extend((defined["sources"], bom_view["required_source_read_set"]))
    else:
        engineering, engineered = get_engineering(
            s, ctx, product_id, payload.engineering_configuration_id
        )
        _version(engineering, payload.expected_engineering_revision)
        _no_wider(engineering, payload.visibility)
        keys = {line["key"] for line in engineered["bom"]["lines"]}
        if any(
            key not in keys for operation in payload.operations for key in operation.bom_line_keys
        ):
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "工序须关联当前固定BOM中的真实行。", 422)
        result["engineering"] = engineered
        read_groups.append(engineered["required_source_read_set"])
    result["references"], result["reads"] = refs, _merge_reads(*read_groups)
    return result


def _checked_inputs(s, ctx, command, product, payload):
    from pdos_next.domain.preproject.baseline import validate_sources
    from pdos_next.service import source_for

    _human(s, ctx, product.id, write=True)
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "配置不在当前型号范围。", 403)
    inputs = _inputs(s, ctx, product.id, payload)
    definition = inputs["definition"]
    if definition is None and inputs["engineering"] is not None:
        engineering = inputs["engineering"]
        row, definition = _definition(s, ctx, product.id, UUID(engineering["definition_id"]))
        _version(row, engineering["definition_revision"])
    if definition is not None:
        validate_sources(s, ctx, definition)
    supplied = {str(read.artifact_id): read.expected_revision for read in command.source_read_set}
    sources = {}
    for required in inputs["reads"]:
        identity = required["artifact_id"]
        if supplied.get(identity) != required["expected_revision"]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "配置需要全部固定来源的明确版本。")
        sources[identity] = source_for(
            s, ctx, product.id, UUID(identity), required["expected_revision"]
        )
        _no_wider(sources[identity], payload.visibility)
    for reference in inputs["references"]:
        source = sources[reference["artifact_id"]]
        lines = source.content.splitlines()
        if reference["line"] > len(lines) or reference["quote"] not in lines[reference["line"] - 1]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "引用须在指定原文行精确定位。")
    return inputs


def validate(s, ctx, command, product, payload):
    # Scope and source checks precede idempotent return; advancing the series does not.
    _checked_inputs(s, ctx, command, product, payload)


def _advance(s, ctx, product_id, payload, previous):
    if previous is None:
        return
    model, _ = PAYLOAD_MODELS[type(payload)]
    latest = s.scalar(
        select(model)
        .where(
            model.tenant_id == ctx.tenant_id,
            model.product_id == product_id,
            model.series_id == previous.series_id,
        )
        .order_by(model.revision.desc())
        .limit(1)
    )
    if not latest or latest.id != previous.id:
        raise DomainError("VERSION_CONFLICT", "此系列已有新草稿，请读取最新版本后追加修订。")


def _new_write(s, ctx, command, product, payload, inputs):
    if product.revision != command.expected_revision:
        raise DomainError("VERSION_CONFLICT", "型号范围已变化，请重新读取。")
    _advance(s, ctx, product.id, payload, inputs["previous"])
    if not isinstance(payload, EngineeringBomRevisePayload):
        return
    numbers = [
        line.part.internal_number
        for line in payload.lines
        if line.part is not None and line.part.internal_number is not None
    ]
    if len(set(numbers)) != len(numbers):
        raise DomainError(
            "DUPLICATE_PART_IDENTITY",
            "本次重复声明同一内部物料编号，请固定复用同一物料身份。",
        )
    if not numbers:
        return
    existing = s.scalars(
        select(PartIdentity).where(
            PartIdentity.tenant_id == ctx.tenant_id,
            PartIdentity.product_id == product.id,
            PartIdentity.internal_number.in_(numbers),
        )
    ).all()
    if any(row.visibility == "private" and row.owner_id != ctx.requester_id for row in existing):
        raise DomainError("FORBIDDEN_SCOPE", "本次物料身份无法办理，请核对授权与声明范围。", 403)
    if existing:
        raise DomainError(
            "DUPLICATE_PART_IDENTITY",
            "内部编号已有可见物料身份，请选择已有物料ID和固定版本。",
        )


def semantic(payload):
    result = payload.model_dump(mode="json")
    result.pop("confirmation_token", None)
    result["sources"] = sorted(
        result["sources"],
        key=lambda ref: (
            ref["artifact_id"],
            ref["expected_revision"],
            ref["line"],
            ref["quote"],
        ),
    )
    for collection in ("lines", "operations"):
        if collection not in result:
            continue
        result[collection] = sorted(result[collection], key=lambda item: item["key"])
        for item in result[collection]:
            for field in ("quantity", "loss_rate", "cycle_time_minutes"):
                if item.get(field) is not None:
                    item[field] = _decimal(Decimal(item[field]))
            for field in ("depends_on", "bom_line_keys"):
                if field in item:
                    item[field] = sorted(item[field])
    return result


def _after(s, ctx, product, payload, inputs):
    previous = inputs["previous"]
    result = {
        "id": None,
        "product_id": str(product.id),
        "name": payload.name,
        "status": "draft",
        "visibility": payload.visibility,
        "owner_id": str(ctx.requester_id),
        "revision": previous.revision + 1 if previous else 1,
        "series_id": str(previous.series_id) if previous else None,
        "previous_id": str(previous.id) if previous else None,
        "expected_previous_revision": payload.expected_previous_revision,
        "created_at": None,
        "reason": payload.reason,
        "source_status": "current",
        "sources": [ref.model_dump(mode="json") for ref in payload.sources],
        "required_source_read_set": inputs["reads"],
    }
    if isinstance(payload, EngineeringBomRevisePayload):
        lines = []
        for line in sorted(payload.lines, key=lambda item: item.key):
            part_view = (
                inputs["parts"][line.part_id][1]
                if line.part_id
                else {
                    "id": None,
                    "revision": 1,
                    "status": "draft",
                    "name": line.part.name,
                    **line.part.model_dump(mode="json"),
                    "external_verification": "not_checked",
                    "mapping_status": "declared" if line.part.mapping_version else "unknown",
                }
            )
            lines.append(
                {
                    "key": line.key,
                    "part_id": str(line.part_id) if line.part_id else None,
                    "expected_part_revision": line.expected_part_revision,
                    "part": deepcopy(part_view),
                    "quantity": _decimal(line.quantity),
                    "unit": line.unit,
                    "loss_rate": _decimal(line.loss_rate),
                    "critical": line.critical,
                    "notes": line.notes,
                }
            )
        result["lines"] = lines
    elif isinstance(payload, EngineeringConfigurationCreatePayload):
        result.update(
            {
                "definition_id": str(payload.definition_id),
                "definition_revision": payload.expected_definition_revision,
                "definition": {
                    key: inputs["definition"][key]
                    for key in (
                        "id",
                        "revision",
                        "title",
                        "status",
                        "source_status",
                    )
                },
                "bom_id": str(payload.bom_id),
                "bom_revision": payload.expected_bom_revision,
                "bom": inputs["bom"],
                "design_versions": {
                    field: getattr(payload, field).model_dump(mode="json")
                    if getattr(payload, field)
                    else None
                    for field in ("mechanical", "electronic", "firmware")
                },
            }
        )
    else:
        result.update(
            {
                "engineering_configuration_id": str(payload.engineering_configuration_id),
                "engineering_revision": payload.expected_engineering_revision,
                "engineering_configuration": {
                    key: inputs["engineering"][key]
                    for key in (
                        "id",
                        "revision",
                        "name",
                        "definition_id",
                        "bom_id",
                        "source_status",
                    )
                },
                "site": payload.site,
                "line": payload.line,
                "operations": [
                    operation.model_dump(mode="json")
                    for operation in sorted(payload.operations, key=lambda item: item.key)
                ],
                "qualification_status": "unknown",
            }
        )
    result["external_verification"] = "not_checked"
    return result


def preview_view(s, ctx, command, product, payload):
    inputs = _checked_inputs(s, ctx, command, product, payload)
    _new_write(s, ctx, command, product, payload, inputs)
    previous = inputs["previous"]
    before = None
    if previous:
        getter = (
            get_bom
            if isinstance(payload, EngineeringBomRevisePayload)
            else (
                get_engineering
                if isinstance(payload, EngineeringConfigurationCreatePayload)
                else get_process
            )
        )
        before = getter(s, ctx, product.id, previous.id)[1]
    return {
        "operation": command.operation,
        "name": payload.name,
        "visibility": payload.visibility,
        "before": before,
        "after": _after(s, ctx, product, payload, inputs),
        "reason": payload.reason,
        "effect": "追加不可变配置草稿并固定物料、版本与来源；不构成批准、试制资格或正式放行。",
    }


def apply(s, ctx, command, product, payload):
    inputs = _checked_inputs(s, ctx, command, product, payload)
    previous = inputs["previous"]
    _new_write(s, ctx, command, product, payload, inputs)
    model, subject_type = PAYLOAD_MODELS[type(payload)]
    identity = uuid4()
    values = {
        "id": identity,
        "tenant_id": ctx.tenant_id,
        "product_id": product.id,
        "owner_id": ctx.requester_id,
        "name": payload.name,
        "status": "draft",
        "visibility": payload.visibility,
        "revision": previous.revision + 1 if previous else 1,
        "series_id": previous.series_id if previous else identity,
        "previous_id": previous.id if previous else None,
        "expected_previous_revision": payload.expected_previous_revision,
        "reason": payload.reason,
        "sources": [reference.model_dump(mode="json") for reference in payload.sources],
        "required_source_read_set": inputs["reads"],
    }
    if isinstance(payload, EngineeringConfigurationCreatePayload):
        values.update(
            {
                "definition_id": payload.definition_id,
                "definition_revision": payload.expected_definition_revision,
                "bom_id": payload.bom_id,
                "bom_revision": payload.expected_bom_revision,
                "design_versions": {
                    field: getattr(payload, field).model_dump(mode="json")
                    if getattr(payload, field)
                    else None
                    for field in ("mechanical", "electronic", "firmware")
                },
            }
        )
    elif isinstance(payload, NpiProcessRevisePayload):
        values.update(
            {
                "engineering_configuration_id": payload.engineering_configuration_id,
                "engineering_revision": payload.expected_engineering_revision,
                "site": payload.site,
                "line": payload.line,
                "operations": semantic(payload)["operations"],
            }
        )
    row = model(**values)
    s.add(row)
    s.flush()
    if isinstance(payload, EngineeringBomRevisePayload):
        for line in payload.lines:
            part_id = line.part_id
            if part_id is None:
                part_id = uuid4()
                s.add(
                    PartIdentity(
                        id=part_id,
                        tenant_id=ctx.tenant_id,
                        product_id=product.id,
                        owner_id=ctx.requester_id,
                        status="draft",
                        visibility=payload.visibility,
                        revision=1,
                        sources=values["sources"],
                        required_source_read_set=inputs["reads"],
                        **line.part.model_dump(mode="json"),
                    )
                )
                s.flush()
            s.add(
                BomLine(
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    bom_id=row.id,
                    key=line.key,
                    part_id=part_id,
                    part_revision=line.expected_part_revision or 1,
                    quantity=line.quantity,
                    unit=line.unit,
                    loss_rate=line.loss_rate,
                    critical=line.critical,
                    notes=line.notes,
                )
            )
        s.flush()
    return row, subject_type, row.visibility


def list_configurations(s, ctx, product_id):
    _human(s, ctx, product_id)
    result = {
        "boms": [],
        "engineering": [],
        "processes": [],
        "unavailable_count": 0,
        "has_more": False,
    }
    for key, model, getter in (
        ("boms", BomRevision, get_bom),
        ("engineering", EngineeringConfiguration, get_engineering),
        ("processes", ProcessRevision, get_process),
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
                if error.code not in {"SOURCE_UNAVAILABLE", "FORBIDDEN_SCOPE"}:
                    raise
                result["unavailable_count"] += 1
    return result
