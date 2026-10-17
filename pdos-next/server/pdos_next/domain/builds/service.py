from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.configurations.service import get_engineering, get_process
from pdos_next.domain.projects.service import _project
from pdos_next.errors import DomainError
from pdos_next.models import Principal, now
from pdos_next.request_proof import snapshot_get

from .models import Build, BuildReadiness
from .schemas import BuildCreatePayload

category_lifecycle_fence = True


def _execution(payload):
    if getattr(payload, "execution_scope", None) is None:
        return None
    from pdos_next.domain.build_start.schemas import BuildAssessmentPayload

    return BuildAssessmentPayload.model_validate(payload.model_dump(mode="json"))


def _build(s, ctx, product_id, build_id, *, write=False):
    row = snapshot_get(s, Build, build_id, scope_id=product_id)
    if (
        not row
        or row.tenant_id != ctx.tenant_id
        or row.product_id != product_id
        or (write and row.owner_id != ctx.requester_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "试制轮次不在当前可用范围。", 403)
    return row


def _linked(s, ctx, product_id, value, *, write=False, new_consumption=False):
    from pdos_next.domain.preproject.baseline import validate_sources
    from pdos_next.request_proof import request_proof

    project, link, definition = _project(s, ctx, product_id, value.project_id, write=write)
    if new_consumption:
        validate_sources(s, ctx, definition)
    proof = request_proof(s)
    key = (
        "build-configurations",
        product_id,
        value.project_id,
        value.engineering_configuration_id,
        value.manufacturing_configuration_id,
        link.definition_id,
    )
    if key in proof.read_rows:
        return proof.read_rows[key]
    _, engineering = get_engineering(s, ctx, product_id, value.engineering_configuration_id)
    _, manufacturing = get_process(s, ctx, product_id, value.manufacturing_configuration_id)
    if str(link.definition_id) != engineering["definition_id"]:
        raise DomainError("CONFIGURATION_MISMATCH", "工程配置须使用该项目固定的型号定义。")
    if manufacturing["engineering_configuration_id"] != engineering["id"]:
        raise DomainError("CONFIGURATION_MISMATCH", "制造配置未关联本轮选择的工程配置版本。")
    reads = {}
    for ref in definition["sources"]:
        reads[ref["artifact_id"]] = {
            "artifact_id": ref["artifact_id"],
            "expected_revision": ref["expected_revision"],
        }
    for view in (engineering, manufacturing):
        for ref in view["required_source_read_set"]:
            previous = reads.get(ref["artifact_id"])
            if previous and previous["expected_revision"] != ref["expected_revision"]:
                raise DomainError("SOURCE_STALE", "所选配置引用了同一来源的不同版本，请先重核。")
            reads[ref["artifact_id"]] = ref
    result = (
        project,
        engineering,
        manufacturing,
        sorted(reads.values(), key=lambda x: x["artifact_id"]),
    )
    proof.read_rows[key] = result
    return result


def validate(s, ctx, command, product, payload):
    execution = _execution(payload)
    if execution is not None:
        from pdos_next.domain.build_start.service import validate as validate_execution

        return validate_execution(s, ctx, command, product, execution)
    from pdos_next.service import source_for

    actor = s.get(Principal, ctx.actor_id)
    if ctx.run_id or ctx.actor_id != ctx.requester_id or actor.kind != "human":
        raise DomainError("NAMED_DECISION_REQUIRED", "当前试制计划由具名本人办理。", 403)
    value = (
        payload
        if isinstance(payload, BuildCreatePayload)
        else _build(s, ctx, product.id, payload.build_id, write=True)
    )
    _, _, _, required = _linked(s, ctx, product.id, value, write=True, new_consumption=True)
    actual = {str(ref.artifact_id): ref.expected_revision for ref in command.source_read_set}
    for ref in required:
        if actual.get(ref["artifact_id"]) != ref["expected_revision"]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "本轮需要项目与双配置的全部固定来源。")
        source_for(s, ctx, product.id, UUID(ref["artifact_id"]), ref["expected_revision"])
    if isinstance(payload, BuildCreatePayload) and payload.previous_build_id:
        previous = _build(s, ctx, product.id, payload.previous_build_id)
        if previous.project_id != payload.project_id:
            raise DomainError("FORBIDDEN_SCOPE", "前轮试制必须在同一产品与项目范围。", 403)


def semantic(payload):
    execution = _execution(payload)
    if execution is not None:
        from pdos_next.domain.build_start.service import semantic as execution_semantic

        return execution_semantic(execution)
    value = payload.model_dump(mode="json")
    value.pop("confirmation_token", None)
    if isinstance(payload, BuildCreatePayload):
        number = format(payload.planned_quantity, "f")
        value["planned_quantity"] = number.rstrip("0").rstrip(".") if "." in number else number
    return value


def _visibility(s, ctx, product_id, payload, project, engineering, manufacturing):
    private = any(view["visibility"] != "category" for view in (engineering, manufacturing))
    if payload.previous_build_id:
        private |= _build(s, ctx, product_id, payload.previous_build_id).visibility != "category"
    return "private" if private or project.visibility != "category" else "category"


def preview_view(s, ctx, command, product, payload):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围版本已经变化。")
    validate(s, ctx, command, product, payload)
    project, engineering, manufacturing, _ = _linked(
        s, ctx, product.id, payload, write=True, new_consumption=True
    )
    return {
        "operation": command.operation,
        **semantic(payload),
        "project_name": project.name,
        "project_revision": project.revision,
        "owner_id": str(ctx.requester_id),
        "visibility": _visibility(s, ctx, product.id, payload, project, engineering, manufacturing),
        "engineering_configuration": engineering,
        "manufacturing_configuration": manufacturing,
        "effect": "固定本轮计划数量、工程与制造配置；保存准备中的试制计划，尚未开工或正式放行。",
    }


def apply(s, ctx, command, product, payload):
    execution = _execution(payload)
    if execution is not None:
        from pdos_next.domain.build_start.service import apply as apply_execution

        return apply_execution(s, ctx, command, product, execution)
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围版本已经变化。")
    if isinstance(payload, BuildCreatePayload):
        project, engineering, manufacturing, _ = _linked(
            s, ctx, product.id, payload, write=True, new_consumption=True
        )
        if project.revision != payload.expected_project_revision:
            raise DomainError("VERSION_CONFLICT", "项目范围已变化，请重新核对试制计划。")
        values = semantic(payload)
        for key in (
            "project_id",
            "engineering_configuration_id",
            "manufacturing_configuration_id",
            "previous_build_id",
            "planned_start",
            "planned_end",
            "planned_quantity",
        ):
            values[key] = getattr(payload, key)
        values.pop("expected_project_revision")
        row = Build(
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            owner_id=ctx.requester_id,
            project_revision=project.revision,
            visibility=_visibility(
                s, ctx, product.id, payload, project, engineering, manufacturing
            ),
            **values,
        )
        return row, "build", row.visibility
    from .readiness import compute_readiness

    build = _build(s, ctx, product.id, payload.build_id, write=True)
    if build.revision != payload.expected_build_revision:
        raise DomainError("VERSION_CONFLICT", "试制轮次版本已变化，请重新核对。")
    _, engineering, manufacturing, _ = _linked(
        s, ctx, product.id, build, write=True, new_consumption=True
    )
    snapshot = readiness_snapshot(build, engineering, manufacturing)
    row = BuildReadiness(
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        build_id=build.id,
        build_revision=build.revision,
        owner_id=ctx.requester_id,
        visibility=build.visibility,
        result=compute_readiness(snapshot),
    )
    return row, "build_readiness", row.visibility


def readiness_snapshot(build, engineering, manufacturing):
    # Only fixed, authorized server-loaded objects enter the pure engine.
    bom = engineering["bom"]
    return {
        "as_of": now().isoformat(),
        "build": {
            "id": str(build.id),
            "revision": build.revision,
            "created_at": build.created_at.isoformat(),
            "quantity": str(build.planned_quantity),
            "unit": build.unit,
            "source_state": "current",
            "metadata": {
                "name": build.name,
                "type": build.type,
                "purpose": build.purpose,
                "project_id": str(build.project_id),
                "project_revision": build.project_revision,
                "owner_id": str(build.owner_id),
                "visibility": build.visibility,
                "verification_objectives": build.verification_objectives,
                "disposition_plan": build.disposition_plan,
                "planned_start": build.planned_start.isoformat() if build.planned_start else None,
                "planned_end": build.planned_end.isoformat() if build.planned_end else None,
                "previous_build_id": str(build.previous_build_id)
                if build.previous_build_id
                else None,
            },
        },
        "engineering_configuration": {
            "id": engineering["id"],
            "revision": engineering["revision"],
            "created_at": engineering["created_at"],
            "definition_id": engineering["definition_id"],
            "source_state": "current",
            "metadata": {key: value for key, value in engineering.items() if key != "bom"},
            "bom": {
                "id": bom["id"],
                "revision": bom["revision"],
                "created_at": bom["created_at"],
                "source_state": "current",
                "metadata": {key: value for key, value in bom.items() if key != "lines"},
                "lines": [
                    {
                        **{
                            key: line.get(key)
                            for key in (
                                "key",
                                "part_id",
                                "quantity",
                                "unit",
                                "loss_rate",
                                "critical",
                            )
                        },
                        "metadata": {"part": line.get("part"), "notes": line.get("notes")},
                    }
                    for line in bom["lines"]
                ],
            },
        },
        "manufacturing_configuration": {
            "id": manufacturing["id"],
            "revision": manufacturing["revision"],
            "created_at": manufacturing["created_at"],
            "source_state": "current",
            "metadata": {key: value for key, value in manufacturing.items() if key != "operations"},
            "operations": manufacturing["operations"],
        },
    }


def list_builds(s, ctx, product_id, *, project_id=None):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id)
    query = select(Build).where(Build.product_id == product_id)
    if project_id is not None:
        _project(s, ctx, product_id, project_id)
        query = query.where(Build.project_id == project_id)
    rows = s.scalars(query.order_by(Build.created_at.desc(), Build.id)).all()
    items, unavailable = [], 0
    for row in rows:
        try:
            project, engineering, manufacturing, reads = _linked(s, ctx, product_id, row)
        except DomainError as error:
            if error.reason not in {"SOURCE_UNAVAILABLE", "SOURCE_STALE", "FORBIDDEN_SCOPE"}:
                raise
            unavailable += 1
            continue
        readiness = s.scalar(
            select(BuildReadiness).where(
                BuildReadiness.build_id == row.id,
                BuildReadiness.build_revision == row.revision,
            )
        )
        current_basis = all(
            view["source_status"] == "current" for view in (engineering, manufacturing)
        )
        items.append(
            {
                "id": str(row.id),
                "revision": row.revision,
                "status": row.status,
                "source_status": "current" if current_basis else "needs_recheck",
                "name": row.name,
                "type": row.type,
                "purpose": row.purpose,
                "owner_id": str(row.owner_id),
                "visibility": row.visibility,
                "project_id": str(row.project_id),
                "project_name": project.name,
                "project_revision": row.project_revision,
                "planned_quantity": str(row.planned_quantity),
                "unit": row.unit,
                "planned_start": row.planned_start.isoformat() if row.planned_start else None,
                "planned_end": row.planned_end.isoformat() if row.planned_end else None,
                "verification_objectives": row.verification_objectives,
                "disposition_plan": row.disposition_plan,
                "previous_build_id": str(row.previous_build_id) if row.previous_build_id else None,
                "engineering_configuration": engineering,
                "manufacturing_configuration": manufacturing,
                "required_source_read_set": reads,
                "created_at": row.created_at.isoformat(),
                "readiness": {
                    "id": str(readiness.id),
                    "revision": readiness.revision,
                    "status": readiness.status,
                    "is_current": current_basis,
                    "result": readiness.result,
                }
                if readiness
                else None,
            }
        )
    return {"items": items, "unavailable_count": unavailable, "has_more": False}
