"""Read actual order inputs and registered selection material; never save a decision."""

from types import SimpleNamespace
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, ValidationError, model_validator
from sqlalchemy import select

from pdos_next import change_controlled_owner as controlled
from pdos_next import change_controlled_store as models
from pdos_next import change_selection_service as selection
from pdos_next import field_change_selection as field
from pdos_next.change_controlled_schemas import FieldIntentTarget, FieldSelectionMaterial
from pdos_next.change_implementation_owner import common_group
from pdos_next.change_order_service import _one, current_fixed, snapshot
from pdos_next.contracts import Command
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution import service as change
from pdos_next.domain.change_execution.graph import OwnerReader
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.schema_base import StrictModel
from pdos_next.schemas.change_control.contracts import PlanItem
from pdos_next.schemas.verification.contracts import SourceRef


class SelectionMaterialInput(StrictModel):
    change_id: UUID
    expected_change_revision: int = Field(strict=True, ge=1)
    source: SourceRef | None = None
    field_intent: FieldIntentTarget | None = None
    item: PlanItem | None = None
    status: Literal["applicable", "not_applicable", "unknown"] | None = None
    valid_until: AwareDatetime | None = None
    reason: str | None = Field(default=None, min_length=3, max_length=2000)

    @model_validator(mode="after")
    def exact_input(self):
        draft = {"field_intent", "item", "status", "valid_until", "reason"}
        if self.source is not None:
            if self.model_fields_set & draft:
                raise ValueError("Registered material and future-plan drafting are separate inputs")
        elif "source" in self.model_fields_set or any(
            getattr(self, key) is None for key in ("field_intent", "item", "status", "reason")
        ):
            raise ValueError("Declare an exact future Field intent or choose registered material")
        return self


def _missing(error):
    if error.status in {401, 403} or (error.status >= 500 and error.status != 503):
        raise error
    return {"code": error.code, "detail": error.message}


def _current(s, ctx, pid, change_id):
    change._human(s, ctx, pid)
    _, row = current_fixed(s, ctx, pid, change_id)
    request = snapshot(row)
    scope, purpose = change._scope_seed(s, ctx, pid, (*request.roots, *request.references))
    controlled.require(scope == request.scope, "FORBIDDEN_SCOPE", 403)
    controlled._project(s, ctx, scope)
    controlled._source_guard(
        s,
        ctx,
        pid,
        row.visibility,
        row.owner_id,
        row.required_source_read_set,
        tuple(SourceRef.model_validate(source) for source in row.sources),
    )
    return row, request, purpose


def _objects(s, ctx, pid, request):
    reader = OwnerReader(s, ctx, pid, request.scope, request.audience, change._issue_loader(s))
    for ref in (*request.roots, *request.references):
        controlled.require(reader.resolve(ref).current, "RECHECK_REQUIRED")
    if not request.assessments:
        return []
    assessment = request.assessments[-1]
    graph = assessment.graph
    controlled.require(
        graph.scope == request.scope and graph.audience == request.audience,
        "FORBIDDEN_SCOPE",
        403,
    )
    nodes = {node.ref.identity: node for node in graph.nodes}
    options = []
    for impact in assessment.known:
        node = impact.node
        controlled.require(nodes.get(node.ref.identity) == node, "INTEGRITY_MISMATCH")
        controlled.require(reader.resolve(node.ref).current, "RECHECK_REQUIRED")
        options.append(
            {
                "ref": node.ref.model_dump(mode="json"),
                "label": node.label,
                "source": node.source.model_dump(mode="json"),
            }
        )
    return options


def _actions(s, ctx, pid, row, request, purpose):
    issue_ids = dict.fromkeys(
        ref.id for ref in (*request.roots, *request.references) if ref.kind in {"issue", "capa"}
    )
    actions = []
    if not issue_ids:
        return actions
    loader = change._issue_loader(s)
    for issue_id in issue_ids:
        issue_row, typed = loader(s, ctx, pid, issue_id)
        view = typed.model_dump(mode="json") if hasattr(typed, "model_dump") else typed
        controlled.require(
            (issue_row.tenant_id, issue_row.product_id, issue_row.project_id)
            == (ctx.tenant_id, pid, request.scope.project_id)
            and view["purpose"] == purpose,
            "FORBIDDEN_SCOPE",
            403,
        )
        controlled.require(
            issue_row.visibility != "private"
            or (row.visibility == "private" and issue_row.owner_id == row.owner_id),
            "AUDIENCE_USE_FORBIDDEN",
            403,
        )
        controlled.require(
            view["is_current"] is True and view["source_status"] == "current",
            "RECHECK_REQUIRED",
        )
        capa = view["issue"].get("capa")
        if capa is None:
            continue
        for action in capa["actions"]:
            actions.append(
                {
                    "issue_id": str(issue_id),
                    "issue_revision": issue_row.revision,
                    "capa_id": capa["id"],
                    "action_id": action["id"],
                    "executor_id": action["executor_id"],
                    "text": action["text"],
                    "kind": action["kind"],
                    "completion": action["completion"],
                }
            )
    return actions


def _selection_record(s, ctx, pid, row, request, purpose, fact):
    controlled.require(
        (fact.owner_id, fact.visibility, fact.purpose, fact.change_id)
        == (row.owner_id, row.visibility, purpose, request.id),
        "AUDIENCE_USE_FORBIDDEN",
        403,
    )
    try:
        material = field.parse_material(fact.material)
    except (ValidationError, ValueError):
        raise DomainError("INTEGRITY_MISMATCH", "保存的逐项适用材料无法核对。") from None
    if isinstance(material, FieldSelectionMaterial):
        controlled.require(
            fact.basis_kind == "field_intent"
            and (
                fact.feedback_id,
                fact.feedback_version_id,
                fact.feedback_revision,
                fact.feedback_sha256,
                fact.executor_id,
            )
            == (
                material.feedback.id,
                material.feedback_version_id,
                material.feedback.revision,
                material.feedback_sha256,
                material.executor_id,
            )
            and all(
                getattr(fact, key) is None
                for key in (
                    "issue_id",
                    "issue_version_id",
                    "issue_revision",
                    "capa_id",
                    "action_id",
                    "action_sha256",
                )
            ),
            "INTEGRITY_MISMATCH",
        )
    controlled.require(
        material.scope == request.scope
        and material.purpose == purpose
        and material.change_id == request.id
        and material.item.id == fact.item_id
        and digest(material.item) == fact.item_sha256
        and digest(material) == fact.material_sha256
        and material.decider_id == fact.actor_id
        and material.status == fact.status
        and material.valid_until == fact.valid_until
        and material.nature == fact.nature
        and (
            isinstance(material, FieldSelectionMaterial)
            or (material.issue_id, material.capa_id, material.action_id, material.action_sha256)
            == (fact.issue_id, fact.capa_id, fact.action_id, fact.action_sha256)
        ),
        "INTEGRITY_MISMATCH",
    )
    value = {
        "id": str(fact.id),
        "revision": fact.revision,
        "item": material.item.model_dump(mode="json"),
        "status": fact.status,
        "valid_until": fact.valid_until.isoformat() if fact.valid_until else None,
        "source": fact.source,
        "receipt_id": None,
        "current": True,
        "source_status": "needs_recheck",
        "missing": [],
        "basis_kind": getattr(fact, "basis_kind", "capa_action"),
        "material_sha256": fact.material_sha256,
        **(
            {
                "feedback": material.feedback.model_dump(mode="json"),
                "feedback_version_id": str(material.feedback_version_id),
                "feedback_sha256": material.feedback_sha256,
                "intent_id": str(material.item.intent.id),
            }
            if isinstance(material, FieldSelectionMaterial)
            else {
                "issue_id": str(fact.issue_id),
                "capa_id": str(fact.capa_id),
                "action_id": str(fact.action_id),
            }
        ),
        "executor_id": str(material.executor_id),
    }
    try:
        original, _ = controlled.original(
            s, ctx, pid, SourceRef.model_validate(fact.source), field.SelectionMaterialReader
        )
        controlled.require(original == material, "SOURCE_STALE")
        controlled.original_authority(s, ctx, pid, fact)
        actual = controlled._source_guard(
            s,
            ctx,
            pid,
            fact.visibility,
            fact.owner_id,
            fact.required_source_read_set,
            tuple(SourceRef.model_validate(source) for source in fact.sources),
        )
        controlled.require(controlled.same(actual, fact.source_basis), "SOURCE_STALE")
        group = common_group(
            s,
            ctx,
            pid,
            fact,
            operation=models.SELECTION_OPERATION,
            event=models.SELECTION_EVENT,
            actor=fact.actor_id,
        )
        proof = SimpleNamespace(
            **{**fact.__dict__, "material_sha256": fact.confirmation_material_sha256}
        )
        controlled._atom_proof(s, ctx, pid, proof, group)
        value["receipt_id"] = str(group["receipt"]["id"])
        controlled.require(
            controlled.deadline_current(fact.valid_until, controlled.clock()), "RECHECK_REQUIRED"
        )
        if fact.status == "applicable":
            controlled.selection_callback(
                s,
                ctx,
                pid,
                scope=request.scope,
                purpose=purpose,
                item=material.item,
                request=request,
            )
        value["source_status"] = "current"
    except DomainError as error:
        value["missing"].append(_missing(error))
    return value


def order_context(s, ctx, pid, change_id):
    from pdos_next.change_build_adoption import DEVELOPMENT_BUILD_ADOPTION_CONDITION

    row, request, purpose = _current(s, ctx, pid, change_id)
    objects = _objects(s, ctx, pid, request)
    actions = _actions(s, ctx, pid, row, request, purpose)
    field_options = field.options(s, ctx, pid, request)
    missing, policy = [], None
    try:
        actual = controlled.policy_callback(
            s, ctx, pid, scope=request.scope, purpose=purpose, request=request
        ).model_dump(mode="json")
        policy = {
            "current": True,
            **{
                key: actual[key]
                for key in ("required_disciplines", "valid_from", "valid_until", "nature", "source")
            },
        }
    except DomainError as error:
        missing.append(_missing(error))
    pointers = list(
        s.scalars(
            select(models.ChangeSelectionCurrent)
            .where(
                models.ChangeSelectionCurrent.tenant_id == ctx.tenant_id,
                models.ChangeSelectionCurrent.product_id == pid,
                models.ChangeSelectionCurrent.project_id == request.scope.project_id,
                models.ChangeSelectionCurrent.change_id == request.id,
            )
            .order_by(models.ChangeSelectionCurrent.item_id)
        )
    )
    selections = []
    for pointer in pointers:
        current, fact = controlled.selection_pointer(
            s, ctx, pid, request.scope, request.id, pointer.item_id
        )
        controlled.require(current is not None and current.id == pointer.id, "SOURCE_STALE")
        value = _selection_record(s, ctx, pid, row, request, purpose, fact)
        selections.append(value)
        missing.extend(value["missing"])
    if not actions and not field_options:
        missing.append({"code": "INTEGRATION_REQUIRED", "detail": "关联问题尚无实际CAPA措施。"})
    if not request.assessments:
        missing.append({"code": "RECHECK_REQUIRED", "detail": "尚无当前固定影响评估。"})
    if not selections:
        missing.append({"code": "INTEGRATION_REQUIRED", "detail": "尚无当前具名逐项适用结论。"})
    return {
        "change": {
            "id": str(row.id),
            "change_id": str(row.change_id),
            "revision": row.revision,
            "project_id": str(row.project_id),
            "visibility": row.visibility,
            "status": row.status,
            "request": request.model_dump(mode="json"),
            "purpose": purpose,
        },
        "policy": policy,
        "actions": actions,
        "field_basis_options": field_options,
        "adoption_condition": DEVELOPMENT_BUILD_ADOPTION_CONDITION,
        "old_builds": [
            {"ref": value["ref"], "label": value["label"]}
            for value in objects
            if value["ref"]["kind"] == "build"
        ],
        "executor_options": field.executor_options(s, ctx) if field_options else [],
        "selections": selections,
        "object_options": objects,
        "missing": missing,
    }


def selection_material(s, ctx, pid, data):
    row, request, purpose = _current(s, ctx, pid, data.change_id)
    controlled.require(row.revision == data.expected_change_revision, "VERSION_CONFLICT")
    if data.source is None:
        return _field_material_draft(s, ctx, pid, row, request, purpose, data)
    material, _ = controlled.original(s, ctx, pid, data.source, field.SelectionMaterialReader)
    controlled.require(
        material.scope == request.scope
        and material.purpose == purpose
        and material.change_id == request.id
        and material.decider_id == ctx.requester_id,
        "ACTION_INTENT_SCOPE_MISMATCH",
        403,
    )
    is_field = isinstance(material, FieldSelectionMaterial)
    actions = [] if is_field else _actions(s, ctx, pid, row, request, purpose)
    action = (
        None
        if is_field
        else next(
            (
                value
                for value in actions
                if (value["issue_id"], value["capa_id"], value["action_id"], value["executor_id"])
                == tuple(
                    str(value)
                    for value in (
                        material.issue_id,
                        material.capa_id,
                        material.action_id,
                        material.executor_id,
                    )
                )
            ),
            None,
        )
    )
    controlled.require(is_field or action is not None, "ACTION_INTENT_REQUIRED", 422)
    _, prior = controlled.selection_pointer(
        s, ctx, pid, request.scope, request.id, material.item.id
    )
    payload = models.SelectionPayload(
        change_id=request.id,
        expected_change_revision=row.revision,
        visibility=row.visibility,
        item=material.item,
        action=FieldIntentTarget(
            kind="field_intent", feedback=material.feedback, executor_id=material.executor_id
        )
        if is_field
        else models.ActionTarget(
            issue_id=material.issue_id,
            expected_issue_revision=action["issue_revision"],
            capa_id=material.capa_id,
            action_id=material.action_id,
        ),
        status=material.status,
        source=data.source,
        valid_until=material.valid_until,
        reason=material.reason,
        expected_previous_id=prior.id if prior else None,
        expected_previous_revision=prior.revision if prior else None,
    )
    product = _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid)
    command = Command(
        command_id=uuid4(),
        idempotency_key=f"selection-material:{uuid4()}",
        operation=models.SELECTION_OPERATION,
        category_id=ctx.category_id,
        product_id=pid,
        expected_revision=product.revision,
        payload=payload.model_dump(mode="json", exclude={"approval_token"}),
    )
    prepared = selection.inputs(s, ctx, pid, command)
    prepared["command"]["payload"].pop("approval_token", None)
    return {
        "command": prepared["command"],
        "material": material.model_dump(mode="json"),
        "required_source_read_set": prepared["required_source_read_set"],
    }


def _field_material_draft(s, ctx, pid, row, request, purpose, data):
    policy = controlled.policy_callback(
        s, ctx, pid, scope=request.scope, purpose=purpose, request=request
    )
    authority, _ = controlled.authority(
        s, ctx, pid, request.scope, models.SELECTION_OPERATION, purpose
    )
    controlled.require(
        data.item.discipline in authority["roles"]
        and data.item.discipline in policy.required_disciplines,
        "FORBIDDEN_DISCIPLINE",
        403,
    )
    controlled.require(
        policy.nature != "real" or authority.get("synthetic") is False, "NATURE_MISMATCH", 403
    )
    known = (
        {value.node.ref.identity for value in request.assessments[-1].known}
        if request.assessments
        else set()
    )
    controlled.require(
        all(
            ref.identity in known for ref in (*data.item.selection.objects, *data.item.intent.basis)
        ),
        "PLAN_SCOPE_MISMATCH",
        422,
    )
    controlled.exact_units(data.item)
    basis, _ = field.load_basis(
        s, ctx, pid, data.field_intent, data.item, request, request.scope, purpose, policy.nature
    )
    _, object_reads, object_sources = controlled.objects(s, ctx, pid, request, data.item)
    reads = controlled._reads(
        row.required_source_read_set,
        basis.required_source_read_set,
        object_reads,
        policy.required_source_read_set,
        authority["required_source_read_set"],
    )
    sources = tuple(
        dict.fromkeys((*request.sources, policy.source, *basis.sources, *object_sources))
    )
    controlled._source_guard(s, ctx, pid, row.visibility, row.owner_id, reads, sources)
    material = field.material_for(
        ctx,
        request,
        data.item,
        data.field_intent,
        basis,
        status=data.status,
        valid_until=data.valid_until,
        reason=data.reason,
    )
    content = controlled.canonical(material.model_dump(mode="json"))
    return {
        "stage": "material_draft",
        "material": material.model_dump(mode="json"),
        "material_content": content,
        "material_visibility": row.visibility,
        "required_source_read_set": reads,
        "artifact_payload": {
            "title": f"Field变更计划：{request.title[:60]}",
            "content": content,
            "source_label": "服务端形成的具名未来计划，待T2确认",
            "visibility": row.visibility,
        },
    }
