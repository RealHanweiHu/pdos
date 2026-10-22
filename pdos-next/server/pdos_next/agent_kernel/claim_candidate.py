"""Actual AI Claim candidate, one Human T1 confirmation, retained AI writer and Run."""

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from pdos_next.errors import DomainError
from pdos_next.models import Claim, Principal
from pdos_next.request_proof import command_inputs_once

from .bindings import ModelBinding, WriteSource, execution_key
from .execution import verify_source
from .models import AgentEvent, AgentRun, AgentToolCall


def content(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token", "prepared_event_id"})


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def supports_confirmation(command):
    return command.payload.get("prepared_event_id") is not None


def needs_confirmation(payload):
    return payload.prepared_event_id is not None


def prepare(session, scope, spec, arguments, intent_key, bootstrap):
    try:
        prefix, run_id, kind, model_id, index = intent_key.split(":")
        model_id, index = UUID(model_id), int(index)
        if (
            prefix != "agent"
            or kind != "model"
            or run_id != str(scope.run_id)
            or index < 0
            or intent_key != execution_key(scope.run_id, model_id, index)
        ):
            raise ValueError
        model_call = session.get(AgentToolCall, model_id)
        binding = ModelBinding.model_validate(model_call.execution_binding)
    except (ValueError, AttributeError, ValidationError):
        raise DomainError("FORBIDDEN_SCOPE", "候选须绑定实际模型回复。", 403) from None
    run = session.scalar(select(AgentRun).where(AgentRun.id == scope.run_id).with_for_update())
    matching = [
        skill
        for skill in binding.loaded_skills
        if spec.name in bootstrap.catalog._skills[skill.key].operations
    ]
    if not matching:
        raise DomainError("FORBIDDEN_SCOPE", "原模型回复没有加载对应技能。", 403)
    source = WriteSource(skill=matching[0], model_call_id=model_id, response_index=index)
    verify_source(
        session,
        scope,
        run,
        spec,
        arguments,
        source,
        catalog=bootstrap.catalog,
        registry=bootstrap.registry,
        route=bootstrap.route(session, scope),
        prepare_only=True,
    )
    command = bootstrap.commands.command(session, scope, spec.name, arguments, intent_key)
    if command.payload.get("prepared_event_id") or command.payload.get("confirmation_token"):
        raise DomainError("FORBIDDEN_SCOPE", "候选身份和确认由服务器办理。", 403)
    events = session.scalars(select(AgentEvent).where(AgentEvent.run_id == run.id)).all()
    previous = next(
        (
            event
            for event in events
            if event.body.get("type") == "claim_candidate"
            and event.body.get("intent_key") == intent_key
        ),
        None,
    )
    if previous is None:
        identity = uuid4()
        command.payload["prepared_event_id"] = identity
        body = {
            "type": "claim_candidate",
            "intent_key": intent_key,
            "command": command.model_dump(mode="json"),
            "cancel_epoch": run.cancel_epoch,
            "source": source.model_dump(mode="json"),
            "model_binding": binding.model_dump(mode="json"),
        }
        previous = AgentEvent(
            id=identity,
            tenant_id=scope.tenant_id,
            run_id=run.id,
            sequence=session.scalar(
                select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                    AgentEvent.run_id == run.id
                )
            )
            + 1,
            body=body,
        )
        session.add(previous)
        session.flush()
    return {
        "command": previous.body["command"],
        "requires_human": True,
        "write_tier": "T1",
        "state": "candidate",
        "event_id": str(previous.id),
    }


@dataclass(frozen=True)
class PreparedClaim:
    source: object
    run: object | None
    reference: object
    proposal_id: UUID | None
    privacy: str
    visibility: str

    def __iter__(self):
        # Existing callers may still unpack the original (source, run) pair.
        yield self.source
        yield self.run


def _reference(command, payload):
    from pdos_next.domain.preproject.access import fail
    from pdos_next.domain.preproject.schemas import Reference

    if payload.source is not None:
        source = payload.source
        if source.line is None or source.locator != f"line:{source.line}":
            fail("VALIDATION_FAILED", "unsupported_locator", "此来源入口目前只核对 line:N 定位。")
        return Reference(
            type=source.kind,
            id=source.id,
            version=source.version,
            line=source.line,
            quote=source.quote,
        ).model_copy(update={"quote": source.quote})
    reads = {read.artifact_id: read.expected_revision for read in command.source_read_set}
    revision = reads.get(payload.artifact_id)
    if revision is None:
        fail("MISSING_REQUIRED_EVIDENCE", "source_version_required", "须引用原文的明确版本。")
    return Reference(
        type="artifact",
        id=payload.artifact_id,
        version=revision,
        line=payload.line,
        quote=payload.quote,
    )


def _candidate_run(session, ctx, command, scope, payload):
    from pdos_next.domain.preproject.access import fail, human
    from pdos_next.domain.preproject.evidence_schemas import ClaimRecord
    from pdos_next.service import digest

    if ctx.agent_run_id:
        from .execution import command_call, command_run

        if payload.prepared_event_id:
            fail(
                "FORBIDDEN_SCOPE", "server_candidate_binding", "AI 自动执行不能借用人工候选。", 403
            )
        run = command_run(session, ctx, scope.id)
        command_call(session, ctx, command.operation)
        return run
    human(session, ctx)
    if payload.prepared_event_id is None:
        return None
    event = session.get(AgentEvent, payload.prepared_event_id)
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == event.run_id if event else AgentRun.id.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not event
        or event.tenant_id != ctx.tenant_id
        or not run
        or event.body.get("type") != "claim_candidate"
        or run.tenant_id != ctx.tenant_id
        or run.category_id != ctx.category_id
        or run.product_id != scope.id
        or run.requester_id != ctx.requester_id
        or run.cancel_epoch != event.body.get("cancel_epoch")
        or run.reverted_at
        or run.state == "cancelled"
    ):
        fail(
            "FORBIDDEN_SCOPE",
            "candidate_binding_invalid",
            "候选不属于本人、当前范围或有效运行。",
            403,
        )
    actual = event.body["command"]
    original = ClaimRecord.model_validate(actual["payload"])
    if (
        actual["operation"] != command.operation
        or actual.get("category_id") != str(command.category_id)
        or actual.get("product_id") != (str(scope.id) if scope.id else None)
        or content(original) != content(payload)
        or digest(actual["source_read_set"])
        != digest([read.model_dump(mode="json") for read in command.source_read_set])
    ):
        fail(
            "DUPLICATE_INTENT_CONFLICT", "candidate_content_changed", "原候选已绑定不同内容或来源。"
        )
    writer = session.get(Principal, run.writer_id)
    if not writer or not writer.active or writer.kind != "agent":
        fail("FORBIDDEN_SCOPE", "candidate_writer_invalid", "原 AI 署名不可用。", 403)
    return run


def _nature(payload, run, *, session=None, ctx=None):
    from pdos_next.domain.preproject.access import fail

    if run and payload.nature in {"observed", "decided"}:
        fail("FORBIDDEN_SCOPE", "human_fact_required", "AI 不能冒充亲历观察或具名人工决定。", 403)
    if payload.nature == "computed":
        if session is None or ctx is None:
            fail(
                "SOURCE_UNAVAILABLE", "deterministic_proof_required",
                "计算事实须绑定实际计算证明。",
            )
        from .computed_claim import verify_computed_claim

        verify_computed_claim(session, ctx, run, payload)
    if run and payload.nature == "extracted":
        if session is None or ctx is None:
            fail(
                "SOURCE_UNAVAILABLE", "extraction_proof_required",
                "抽取事实须绑定实际抽取证明。",
            )
        from .extracted_claim import verify_extracted_claim

        verify_extracted_claim(session, ctx, run, payload)
    if payload.availability == "not_applicable":
        reason = payload.content.get("text") or payload.statement
        if not isinstance(reason, str) or not reason.strip():
            fail("VALIDATION_FAILED", "not_applicable_reason_required", "不适用须给出依据。")


def _placement(session, ctx, scope, payload, reference, run):
    from pdos_next.domain.preproject.access import fail, proposal
    from pdos_next.domain.preproject.claim_access import source_privacy

    identity = run.proposal_id if run else payload.proposal_id
    if run and payload.proposal_id is not None and payload.proposal_id != identity:
        fail("FORBIDDEN_SCOPE", "proposal_run_mismatch", "提案必须与实际运行绑定一致。", 403)
    if identity:
        proposal(session, ctx, identity, lock=True)
    root = SimpleNamespace(
        source_kind=reference.type,
        artifact_id=reference.id if reference.type == "artifact" else None,
        snapshot_id=reference.id if reference.type == "snapshot" else None,
    )
    private_source = source_privacy(session, ctx, root) == "private"
    if scope.id is not None:
        from pdos_next.models import Product

        parent = session.get(Product, scope.id)
        if not parent or parent.tenant_id != ctx.tenant_id or parent.category_id != ctx.category_id:
            fail("SOURCE_UNAVAILABLE", "source_unreadable", "Claim 所属型号不可读。", 403)
        private_source |= parent.visibility != "category"
    private_run = bool(run and run.private_context)
    if private_run and identity is None:
        fail("FORBIDDEN_SCOPE", "private_context_run", "私有上下文运行必须绑定实际提案。", 403)
    if private_source and identity is None and (run or payload.source is not None):
        fail("FORBIDDEN_SCOPE", "private_context_run", "私有来源 Claim 必须绑定可读提案。", 403)
    private = private_source or private_run
    if private and payload.visibility == "category":
        fail("FORBIDDEN_SCOPE", "private_source_in_shared", "不能扩大来源或私有运行的受众。", 403)
    visibility = payload.visibility or ("audience" if private else "category")
    # S0 callers can keep a public-source fact private; this is a restriction,
    # never permission to enlarge a private source or actual private run.
    privacy = "private" if private or visibility != "category" else "shared"
    return identity, privacy, visibility


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    from pdos_next.domain.preproject.claim_access import load_source

    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前范围版本已变化。")
    run = _candidate_run(session, ctx, command, scope, payload)
    _nature(payload, run, session=session, ctx=ctx)
    reference = _reference(command, payload)
    source = load_source(session, ctx, reference, product_id=scope.id, lock=True)
    identity, privacy, visibility = _placement(session, ctx, scope, payload, reference, run)
    if payload.content.get("parameter_id"):
        from pdos_next.domain.preproject.category_service import check_parameter

        check_parameter(
            session,
            ctx,
            UUID(payload.content["parameter_id"]),
            payload.content["parameter_version"],
            payload.content.get("unit"),
        )
    return PreparedClaim(source, run, reference, identity, privacy, visibility)


def validate(session, ctx, command, scope, payload):
    prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    admitted = prepared(session, ctx, command, scope, payload)
    run = admitted.run
    return {
        "claim": content(payload),
        "payload": semantic(payload),
        "origin": "ai_draft" if run else "human",
        "prepared_by_run_id": str(run.id) if run else None,
        "privacy": admitted.privacy,
        "proposal_id": str(admitted.proposal_id) if admitted.proposal_id else None,
        "effect": "确认登记此来源事实，保留原 AI 署名、运行与依据。",
    }


def apply(session, ctx, command, scope, payload):
    admitted = prepared(session, ctx, command, scope, payload)
    run, reference = admitted.run, admitted.reference
    receipt_id = uuid4()
    statement = payload.statement or payload.content.get("text") or reference.quote
    row = Claim(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=scope.id,
        proposal_id=admitted.proposal_id,
        artifact_id=reference.id if reference.type == "artifact" else None,
        snapshot_id=reference.id if reference.type == "snapshot" else None,
        source_kind=reference.type,
        source_revision=reference.version,
        source_locator=f"line:{reference.line}",
        line=reference.line,
        quote=reference.quote,
        statement=statement,
        nature=payload.nature,
        availability=payload.availability,
        content=payload.content or {"text": statement},
        vendor_claimed=payload.vendor_claimed,
        extraction_ref=payload.extraction_ref,
        privacy=admitted.privacy,
        visibility=admitted.visibility,
        human_owner_id=ctx.requester_id,
        writer_id=run.writer_id if run else ctx.actor_id,
        origin="ai_draft" if run else "human",
        run_id=run.id if run else None,
        confirmed_by=ctx.actor_id if run and payload.prepared_event_id else None,
        prepared_event_id=payload.prepared_event_id,
        receipt_id=receipt_id,
        revision=1,
        status="active",
    )
    row.prepared_receipt_id = receipt_id
    if run:
        row.prepared_by_run_id = run.id
    row.action_result = {
        "origin": row.origin,
        "writer_id": str(row.writer_id),
        "run_id": str(row.run_id) if row.run_id else None,
        "confirmed_by": str(row.confirmed_by) if row.confirmed_by else None,
        "prepared_event_id": str(payload.prepared_event_id) if payload.prepared_event_id else None,
        "privacy": admitted.privacy,
        "proposal_id": str(admitted.proposal_id) if admitted.proposal_id else None,
    }
    return row, "claim", admitted.visibility


def finalize_receipt(session, ctx, command, scope, payload, subject, receipt):
    from .proposal_context import admit_created

    admit_created(session, subject, receipt)
    if payload.prepared_event_id is None:
        return
    run_id = subject.prepared_by_run_id
    sequence = (
        session.scalar(
            select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                AgentEvent.run_id == run_id
            )
        )
        + 1
    )
    session.add(
        AgentEvent(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            run_id=run_id,
            sequence=sequence,
            body={
                "type": "claim_candidate_adopted",
                "prepared_event_id": str(payload.prepared_event_id),
                "receipt_id": str(receipt.id),
            },
        )
    )
    session.flush()
