"""Candidate bridge for a verified discussion, preparation, then fixed request.

Integration points are ``resolve_draft`` before a continuation needs input,
``record`` after an actual model tool response, and ``read`` before displaying
or adopting a candidate. This module never executes or previews a command.
Preparation retains its T1 preview; request creation retains its existing T0
qualification or ordinary human command path. Events are not business records.
"""

from copy import deepcopy
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field, ValidationError
from sqlalchemy import func, select

from pdos_next.agent_kernel.bindings import ModelBinding, WriteSource, execution_key
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.execution import (
    check_run_binding,
    scope_for_run,
    validate_skill_load,
    verify_source,
)
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.contracts import PAYLOADS, Command
from pdos_next.database import require_context
from pdos_next.domain.builds.service import _build, _linked
from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.verification_execution import service as preparation_service
from pdos_next.domain.verification_execution.schemas import (
    PreparationItem,
    PreparationRecordPayload,
    Text,
)
from pdos_next.domain.verification_front.schemas import RequestCreatePayload
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Receipt
from pdos_next.schemas.verification.contracts import BuildRef, ConfigurationRef
from pdos_next.service import digest, require_access

PREPARATION = "verification.preparation.record"
REQUEST = "verification.request.create"
EVENT = "verification_candidate"
SKILL = "test_verification"


class DraftItem(PreparationItem):
    feature: Text | None = None
    sample_count: int | None = Field(default=None, ge=1, le=10_000, strict=True)


class PreparationDraft(PreparationRecordPayload):
    request_id: UUID | None = None
    expected_request_revision: int = Field(default=0, ge=0, strict=True)
    build_id: UUID | None = None
    expected_build_revision: int | None = Field(default=None, ge=1, strict=True)
    title: Text | None = None
    purpose: Text | None = None
    return_form: Text | None = None
    reason: Text | None = None
    items: tuple[DraftItem, ...] = ()
    sources: tuple[DefinitionReference, ...] = ()


def resolve_draft(arguments, *, request_id, selection=None):
    """Keep missing business facts explicit; never guess one sample or a method.

    ``request_id`` is the server's stable new-request identity. ``selection`` is
    an explicit BuildRef selection, subsequently reloaded by ``record``. Its
    scope and revisions do not establish any read or write authority here.
    """
    request_id = UUID(str(request_id))
    draft = PreparationDraft.model_validate(arguments)
    chosen = BuildRef.model_validate(selection) if selection is not None else None
    if draft.confirmation_token is not None or draft.expected_request_revision != 0:
        raise DomainError("INVALID_PAYLOAD", "此入口只准备新的复验请求，不携带确认令牌。", 422)
    if draft.request_id not in {None, request_id}:
        raise DomainError("INVALID_PAYLOAD", "请求身份不等于服务器固定的新请求。", 422)
    if chosen is not None and (
        draft.build_id not in {None, chosen.id}
        or draft.expected_build_revision not in {None, chosen.revision}
    ):
        raise DomainError("VERSION_CONFLICT", "草稿与明确选择的Build版本不一致。")
    missing = [field for field in ("title", "purpose", "return_form", "reason")
               if getattr(draft, field) is None]
    if chosen is None:
        missing.append("build_and_configurations")
    if not draft.items:
        missing.append("items")
    for item in draft.items:
        for field in ("feature", "sample_count"):
            if getattr(item, field) is None:
                missing.append(f"items.{item.id}.{field}")
    if not draft.sources:
        missing.append("execution_sources")
    unconfirmed = []
    for item in draft.items:
        if item.method is None:
            unconfirmed.append(f"items.{item.id}.method")
        if item.criterion is None and (
            item.criterion_text is None or item.criterion_source is None
        ):
            unconfirmed.append(f"items.{item.id}.criterion")
    questions = []
    groups = (
        ([field for field in missing if field == "build_and_configurations"],
         "build_selection", "请选择本次复验的Build，并确认其工程和制造配置版本。"),
        ([field for field in missing if field.endswith(".sample_count")],
         "sample_count", "请明确各测试项的样本数，不能用默认数量代替。"),
        ([field for field in missing if field != "build_and_configurations"
          and not field.endswith(".sample_count")],
         "preparation_details", "请补充复验目标、返回形式、测试项或可核对的原文资料。"),
    )
    for fields, identity, question in groups:
        if fields:
            questions.append({"id": identity, "question": question,
                              "why": "缺少：" + "、".join(fields), "options": [],
                              "recommended": None, "allow_free_text": True, "depends_on": []})
    result = {"status": "needs_input" if missing else "ready", "missing": missing,
              "unconfirmed": unconfirmed, "questions": questions, "arguments": None}
    if not missing:
        raw = draft.model_dump(mode="json")
        raw.update(request_id=str(request_id), build_id=str(chosen.id),
                   expected_build_revision=chosen.revision)
        result["arguments"] = PreparationRecordPayload.model_validate(raw).model_dump(mode="json")
    return result


def _reject(message="复验候选与实际运行、来源或回执无法核对。"):
    raise DomainError("FORBIDDEN_SCOPE", message, 403)


def _run(session, ctx, run_id, *, creating=False):
    require_context(session, ctx)
    if session.info.get("scope") != (
        ctx.tenant_id, ctx.requester_id, ctx.requester_id, ctx.category_id,
    ) or ctx.actor_id != ctx.requester_id or ctx.agent_run_id or ctx.run_id:
        _reject("复验候选须由本次运行的本人事务读取和准备。")
    query = select(AgentRun).where(
        AgentRun.tenant_id == ctx.tenant_id, AgentRun.id == run_id,
    )
    run = session.scalar(query.with_for_update() if creating else query)
    if (not run or run.requester_id != ctx.requester_id or run.category_id != ctx.category_id
        or run.category_id is None or run.product_id is None or run.project_id is None
        or run.trigger in {"automation_manual", "automation_service"}):
        _reject()
    check_run_binding(run, scope_for_run(run), for_write=creating)
    principal = session.get(Principal, ctx.requester_id)
    if not principal or not principal.active or principal.kind != "human":
        _reject()
    return run


def _target(session, ctx, run, selection):
    selected = BuildRef.model_validate(selection)
    product = require_access(session, ctx, run.product_id)
    build = _build(session, ctx, run.product_id, selected.id)
    project, engineering, manufacturing, reads = _linked(
        session, ctx, run.product_id, build, new_consumption=True,
    )
    actual = BuildRef(
        id=build.id, revision=build.revision, product_id=build.product_id,
        project_id=build.project_id,
        engineering_configuration=ConfigurationRef(
            id=engineering["id"], revision=engineering["revision"],
        ),
        manufacturing_configuration=ConfigurationRef(
            id=manufacturing["id"], revision=manufacturing["revision"],
        ),
    )
    if (actual != selected or actual.product_id != run.product_id
        or actual.project_id != run.project_id or product.category_id != run.category_id):
        raise DomainError("VERSION_CONFLICT", "请重新明确选择当前Build与固定双配置。")
    return product, build, project, actual, reads


def _command(run, operation, arguments, key, product_revision):
    return Command(
        command_id=uuid5(NAMESPACE_URL, key), idempotency_key=key, operation=operation,
        category_id=run.category_id, product_id=run.product_id,
        expected_revision=product_revision, source_read_set=DomainCommands._artifact_reads(run),
        payload=PAYLOADS[operation].model_validate(arguments).model_dump(mode="json"),
    )


def _model_binding(call, run, source, operation, arguments):
    """Replay comparison over the persisted model row, not a provider call label."""
    if (not call or call.id != source.model_call_id or call.tenant_id != run.tenant_id
        or call.run_id != run.id or call.tool != "model" or call.state != "completed"
        or call.error_code is not None or not isinstance(call.result, dict)):
        _reject()
    try:
        binding = ModelBinding.model_validate(call.execution_binding)
    except ValidationError:
        _reject()
    if (binding.isolation != "main" or binding.cancel_epoch != run.cancel_epoch
        or source.skill not in binding.loaded_skills or source.skill.key != SKILL):
        _reject()
    calls = call.result.get("calls", [])
    if source.response_index >= len(calls):
        _reject()
    actual = calls[source.response_index]
    if (not isinstance(actual, dict) or actual.get("name") != operation
        or digest(actual.get("arguments")) != digest(arguments)):
        _reject()
    return digest(call.execution_binding)


def preparation_binding(command, receipt, preparation):
    """Pure binding over an actual immutable T1 receipt and reloaded domain row.

    The common T1 owner enforces confirmation; older valid T1 receipts do not
    necessarily carry a confirmation_id. Do not invent a stronger receipt shape.
    """
    payload = PreparationRecordPayload.model_validate(command.payload)
    if (receipt is None or preparation is None or receipt.operation != PREPARATION
        or receipt.tenant_id != preparation.tenant_id
        or receipt.category_id != command.category_id or receipt.product_id != command.product_id
        or receipt.command_id != command.command_id
        or receipt.subject_type != "verification_preparation"
        or receipt.subject_id != preparation.id or receipt.subject_revision != preparation.revision
        or receipt.requester_id != preparation.owner_id
        or preparation.product_id != command.product_id
        or preparation.request_id != payload.request_id
        or preparation.build_id != payload.build_id
        or preparation.build_revision != payload.expected_build_revision
        or preparation.revision != payload.expected_request_revision + 1
        or preparation.input_snapshot != preparation_service.semantic(payload)
        or digest(preparation.request_snapshot) != preparation.snapshot_sha256):
        _reject("准备记录没有该候选对应的实际固定回执与内容。")
    return {"receipt_id": str(receipt.id), "preparation_id": str(preparation.id),
            "expected_preparation_revision": preparation.revision,
            "preparation_sha256": preparation.snapshot_sha256}


def _request_binding(payload, preparation, run, selected):
    if (payload.preparation_id != preparation.id
        or payload.expected_preparation_revision != preparation.revision
        or payload.preparation_sha256 != preparation.snapshot_sha256
        or preparation.project_id != run.project_id or preparation.build_id != selected.id
        or preparation.build_revision != selected.revision):
        _reject()


def _view(event):
    command = event.body["command"]
    preparation = command["operation"] == PREPARATION
    return {"event_id": str(event.id), "state": "candidate", "requires_human": True,
            "operation_tier": "T1" if preparation else "T0", "command": command,
            "next_action": "preview" if preparation else "confirm_human_command",
            "source_proof": event.body["source_proof"],
            "preparation": event.body.get("preparation")}


def read(session, ctx, run_id, event_id):
    """Recheck current authority without previewing, executing, or calling a model."""
    from .action_sources import recheck

    run = _run(session, ctx, run_id)
    event = session.get(AgentEvent, event_id)
    body = event.body if event else {}
    frozen = {key: value for key, value in body.items() if key != "digest"}
    if (not event or event.tenant_id != run.tenant_id or event.run_id != run.id
        or body.get("type") != EVENT or body.get("cancel_epoch") != run.cancel_epoch
        or body.get("digest") != digest(frozen)):
        _reject()
    command = Command.model_validate(body["command"])
    source = WriteSource.model_validate(body["source"])
    validate_skill_load(session, scope_for_run(run), source.skill)
    if (command.operation not in {PREPARATION, REQUEST} or command.category_id != run.category_id
        or command.product_id != run.product_id
        or command.idempotency_key != execution_key(
            run.id, source.model_call_id, source.response_index,
        )
        or command.command_id != uuid5(NAMESPACE_URL, command.idempotency_key)
        or body["model_binding_digest"] != _model_binding(
            session.get(AgentToolCall, source.model_call_id), run, source,
            command.operation, body["arguments"],
        )):
        _reject()
    _product, _build_row, _project, selected, _reads = _target(
        session, ctx, run, body["selection"],
    )
    if command.payload != PAYLOADS[command.operation].model_validate(
        body["arguments"],
    ).model_dump(mode="json"):
        _reject()
    if command.operation == REQUEST:
        parent_id = UUID(body["parent_event_id"])
        parent_event = session.get(AgentEvent, parent_id)
        if (not parent_event or parent_event.body.get("command", {}).get("operation") != PREPARATION
            or parent_event.body.get("parent_event_id") is not None):
            _reject()
        parent = read(session, ctx, run.id, parent_id)
        prep = body["preparation"]
        row, _ = preparation_service.get_preparation(
            session, ctx, run.product_id, UUID(prep["preparation_id"]),
        )
        actual = preparation_binding(Command.model_validate(parent["command"]),
                                     session.get(Receipt, UUID(prep["receipt_id"])), row)
        if actual != prep:
            _reject()
        _request_binding(RequestCreatePayload.model_validate(command.payload), row, run, selected)
    proof = recheck(session, ctx, run, body["source_proof"], preparation_id=(
        UUID(body["preparation"]["preparation_id"]) if command.operation == REQUEST else None
    ))
    if proof != body["source_proof"]:
        raise DomainError("SOURCE_STALE", "候选来源或目标范围已变化，请重新准备。")
    return _view(event)


def record(session, ctx, run_id, *, operation, arguments, source, selection, owner,
           citation_ids=(), parent_event_id=None, preparation_receipt_id=None):
    """Record a candidate for an actual disclosed model response under a Run lock.

    The host supplies WriteSource from its completed model ledger. The human
    action session owns source audience checks and current Build loading. Root
    integration must call ``read`` again before presenting/adopting the command.
    """
    from .action_sources import capture, recheck

    if (operation not in {PREPARATION, REQUEST} or not isinstance(source, WriteSource)
        or source.skill.key != SKILL):
        _reject()
    selected_citations = sorted({str(UUID(str(value))) for value in citation_ids})
    if operation == PREPARATION and not selected_citations:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "继续处理须保留已核对的讨论来源。")
    run = _run(session, ctx, run_id, creating=True)
    scope = scope_for_run(run)
    spec = owner.registry.get(operation)
    verify_source(session, scope, run, spec, arguments, source, catalog=owner.catalog,
                  registry=owner.registry, route=owner.route(session, scope), prepare_only=True)
    binding_digest = _model_binding(session.get(AgentToolCall, source.model_call_id), run,
                                    source, operation, arguments)
    product, _build_row, _project, selected, required = _target(session, ctx, run, selection)
    key = execution_key(run.id, source.model_call_id, source.response_index)
    previous = session.scalar(select(AgentEvent).where(
        AgentEvent.run_id == run.id, AgentEvent.body["type"].astext == EVENT,
        AgentEvent.body["intent_key"].astext == key,
    ))
    if previous is not None:
        if (previous.body["arguments"] != arguments
            or previous.body["selection"] != selected.model_dump(mode="json")
            or previous.body["citation_ids"] != selected_citations
            or previous.body.get("parent_event_id")
            != (str(parent_event_id) if parent_event_id else None)
            or (previous.body.get("preparation") or {}).get("receipt_id")
            != (str(preparation_receipt_id) if preparation_receipt_id else None)):
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "同一工具候选绑定的实质已变化。")
        return read(session, ctx, run.id, previous.id)
    command = _command(run, operation, arguments, key, product.revision)
    pinned = {str(ref.artifact_id): ref.expected_revision for ref in command.source_read_set}
    if any(pinned.get(str(ref["artifact_id"])) != ref["expected_revision"] for ref in required):
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "运行须携带所选Build与双配置的固定资料。")
    prep = None
    if operation == PREPARATION:
        payload = PreparationRecordPayload.model_validate(command.payload)
        if (payload.confirmation_token is not None or payload.expected_request_revision != 0
            or payload.build_id != selected.id
            or payload.expected_build_revision != selected.revision
            or parent_event_id or preparation_receipt_id):
            _reject()
        references = preparation_service._references(payload)
        proof = capture(session, ctx, run, selected_citations, product_id=run.product_id,
                        build_id=selected.id, execution_references=references)
    else:
        if not parent_event_id or not preparation_receipt_id or citation_ids:
            _reject("建立请求须引用本桥已确认的准备候选与实际回执。")
        parent = read(session, ctx, run.id, parent_event_id)
        if parent["command"]["operation"] != PREPARATION:
            _reject()
        receipt = session.get(Receipt, preparation_receipt_id)
        if receipt is None or receipt.operation != PREPARATION:
            _reject()
        row, _ = preparation_service.get_preparation(
            session, ctx, run.product_id, receipt.subject_id,
        )
        if receipt.requester_id != run.requester_id or row.owner_id != run.requester_id:
            _reject()
        prep = preparation_binding(Command.model_validate(parent["command"]), receipt, row)
        payload = RequestCreatePayload.model_validate(command.payload)
        _request_binding(payload, row, run, selected)
        proof = recheck(session, ctx, run, parent["source_proof"], preparation_id=row.id)
    if any(pinned.get(str(ref["artifact_id"])) != ref["expected_revision"]
           for ref in proof["read_set"]):
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "候选依据须属于运行已绑定的固定资料。")
    body = {"type": EVENT, "version": 1, "intent_key": key, "cancel_epoch": run.cancel_epoch,
            "command": command.model_dump(mode="json"), "arguments": deepcopy(arguments),
            "selection": selected.model_dump(mode="json"), "source": source.model_dump(mode="json"),
            "model_binding_digest": binding_digest, "source_proof": proof,
            "citation_ids": selected_citations,
            "parent_event_id": str(parent_event_id) if parent_event_id else None,
            "preparation": prep}
    body["digest"] = digest(body)
    sequence = session.scalar(select(func.coalesce(func.max(AgentEvent.sequence), 0))
                              .where(AgentEvent.run_id == run.id)) + 1
    event = AgentEvent(id=uuid4(), tenant_id=run.tenant_id, run_id=run.id, sequence=sequence,
                       body=body)
    session.add(event)
    session.flush()
    return _view(event)
