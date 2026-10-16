"""Durable human candidates over actual prepared content and common receipts."""

from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from pdos_next.contracts import PAYLOADS, Command
from pdos_next.domain.preproject.access import fail, proposal
from pdos_next.domain.preproject.models import PreparedCandidate
from pdos_next.domain.preproject.provenance import CONTENT_OPERATIONS, content
from pdos_next.errors import DomainError
from pdos_next.models import Receipt, RequestKey
from pdos_next.service import receipt_view, require_access, source_for

from .execution import check_run_binding
from .models import AgentEvent, AgentRun


def record(session, scope, command, intent_key):
    """Called inside candidate preparation, never from model output or a read API."""
    if command.operation not in CONTENT_OPERATIONS:
        fail("NAMED_DECISION_REQUIRED", "named_decision_only", "此候选须到具名决定入口办理。", 403)
    run = session.scalar(select(AgentRun).where(AgentRun.id == scope.run_id).with_for_update())
    check_run_binding(run, scope)
    candidate = session.scalar(
        select(PreparedCandidate).where(
            PreparedCandidate.tenant_id == scope.tenant_id,
            PreparedCandidate.run_id == run.id,
            PreparedCandidate.operation == command.operation,
            PreparedCandidate.candidate_digest == command.payload["candidate_digest"],
        )
    )
    if candidate is None or candidate.payload != content(
        PAYLOADS[command.operation].model_validate(command.payload)
    ):
        fail("FORBIDDEN_SCOPE", "candidate_binding_invalid", "候选没有实际准备记录。", 403)
    previous = session.scalar(
        select(AgentEvent).where(
            AgentEvent.tenant_id == scope.tenant_id,
            AgentEvent.run_id == run.id,
            AgentEvent.body["type"].astext == "domain_candidate",
            AgentEvent.body["intent_key"].astext == intent_key,
        )
    )
    frozen = command.model_dump(mode="json")
    if previous is not None:
        if previous.body["command"] != frozen:
            fail("DUPLICATE_INTENT_CONFLICT", "candidate_command_changed", "原候选命令已变化。")
        return previous.id
    identity = uuid4()
    session.add(
        AgentEvent(
            id=identity,
            tenant_id=scope.tenant_id,
            run_id=run.id,
            sequence=session.scalar(
                select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                    AgentEvent.run_id == run.id,
                )
            )
            + 1,
            body={
                "type": "domain_candidate",
                "intent_key": intent_key,
                "candidate_id": str(candidate.id),
                "cancel_epoch": run.cancel_epoch,
                "command": frozen,
            },
        )
    )
    session.flush()
    return identity


def _bound(event, candidate, run):
    try:
        command = Command.model_validate(event.body["command"])
        payload = PAYLOADS[command.operation].model_validate(command.payload)
        if (
            command.operation not in CONTENT_OPERATIONS
            or command.category_id != run.category_id
            or command.product_id != run.product_id
            or candidate is None
            or candidate.run_id != run.id
            or candidate.category_id != run.category_id
            or candidate.requester_id != run.requester_id
            or candidate.operation != command.operation
            or candidate.candidate_digest != payload.candidate_digest
            or payload.prepared_by_run_id != run.id
            or candidate.payload != content(payload)
        ):
            return None
        return command
    except (KeyError, TypeError, ValueError, ValidationError):
        return None


def _snapshot_bound(event, run):
    from .snapshot_command import OPERATION, SnapshotRegister

    try:
        command = Command.model_validate(event.body["command"])
        payload = SnapshotRegister.model_validate(command.payload)
        if (
            command.operation == OPERATION
            and event.run_id == run.id
            and command.category_id == run.category_id
            and command.product_id == run.product_id
            and payload.prepared_event_id == event.id
            and payload.confirmation_token is None
        ):
            return command
    except (ValidationError, KeyError, TypeError, ValueError):
        pass
    return None


def _pending_visible(session, ctx, run, command, event):
    if run.proposal_id is not None:
        proposal(session, ctx, run.proposal_id)
    for reference in command.source_read_set:
        source_for(session, ctx, run.product_id, reference.artifact_id, reference.expected_revision)
    if command.operation == "research.snapshot.register":
        from .snapshot_command import _proof, _verify_candidate_source

        if run.state not in {"queued", "running", "waiting_input", "completed", "partial"}:
            raise DomainError("SOURCE_UNAVAILABLE", "原运行当前不能采用快照候选。")
        _verify_candidate_source(session, run, event)
        proof = _proof(
            session,
            run,
            UUID(command.payload["snapshot_id"]),
            read_call_id=UUID(event.body["read_call_id"]),
        )
        if proof.snapshot_digest != event.body["snapshot_digest"]:
            raise DomainError("SOURCE_UNAVAILABLE", "原研究快照内容已变化。")
        return {
            "title": proof.snapshot.title,
            "url": proof.snapshot.final_url,
            "visibility": proof.visibility,
            "retrieved_at": proof.snapshot.retrieved_at.isoformat(),
        }
    elif command.operation == "platform.link.create":
        from pdos_next.domain.products.platforms import target

        variant = command.payload.get("variant_id")
        target(session, ctx, run.product_id, UUID(variant) if variant else None)
    elif command.operation == "product.definition.item.patch":
        from pdos_next.domain.products.models import DefinitionRevision

        row = session.get(DefinitionRevision, UUID(command.payload["definition_id"]))
        if row is None or row.category_id != ctx.category_id or row.product_id != run.product_id:
            fail("NOT_FOUND", "definition_not_found", "定义不存在或不可读。", 404)


def read(session, ctx, run, *, after=0, page_size=50):
    """One ordinary read snapshot. Reading never previews, writes, or resumes inference."""
    require_access(session, ctx, run.product_id)
    if run.requester_id != ctx.requester_id or run.category_id != ctx.category_id:
        fail("FORBIDDEN_SCOPE", "candidate_run_mismatch", "候选不在本人当前运行范围。", 403)
    rows = list(
        session.scalars(
            select(AgentEvent)
            .where(
                AgentEvent.tenant_id == ctx.tenant_id,
                AgentEvent.run_id == run.id,
                AgentEvent.sequence > after,
                AgentEvent.body["type"].astext.in_(["domain_candidate", "snapshot_candidate"]),
            )
            .order_by(AgentEvent.sequence)
            .limit(page_size + 1)
        )
    )
    page = rows[:page_size]
    identities = [
        UUID(event.body["candidate_id"])
        for event in page
        if event.body["type"] == "domain_candidate"
    ]
    candidates = {
        row.id: row
        for row in session.scalars(
            select(PreparedCandidate).where(
                PreparedCandidate.tenant_id == ctx.tenant_id,
                PreparedCandidate.run_id == run.id,
                PreparedCandidate.id.in_(identities),
            )
        )
    }
    commands = {
        event.id: (
            _snapshot_bound(event, run)
            if event.body["type"] == "snapshot_candidate"
            else _bound(event, candidates.get(UUID(event.body["candidate_id"])), run)
        )
        for event in page
    }
    keys = {
        row.key: row
        for row in session.scalars(
            select(RequestKey).where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.actor_id == ctx.actor_id,
                RequestKey.key.in_([cmd.idempotency_key for cmd in commands.values() if cmd]),
            )
        )
    }
    receipts = {
        row.id: row
        for row in session.scalars(
            select(Receipt).where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.id.in_([key.receipt_id for key in keys.values()]),
            )
        )
    }
    items = []
    for event in page:
        command = commands[event.id]
        item = {
            "event_id": str(event.id),
            "sequence": event.sequence,
            "operation": command.operation if command else None,
            "command_id": str(command.command_id) if command else None,
            "idempotency_key": command.idempotency_key if command else None,
            "state": "unavailable",
            "command": None,
            "receipt": None,
        }
        if command:
            key = keys.get(command.idempotency_key)
            receipt = receipts.get(key.receipt_id) if key else None
            if receipt and (
                receipt.agent_run_id == run.id
                and receipt.requester_id == ctx.requester_id
                and receipt.category_id == run.category_id
                and receipt.product_id == run.product_id
                and receipt.operation == command.operation
                and (
                    command.operation != "research.snapshot.register"
                    or receipt.subject_type == "public_web_snapshot"
                    and str(receipt.subject_id) == command.payload["snapshot_id"]
                )
            ):
                item.update(state="adopted", receipt=receipt_view(receipt))
            elif key is not None:
                pass  # A hidden/changed receipt never becomes a fresh write opportunity.
            elif (
                run.reverted_at
                or run.state == "cancelled"
                or event.body["cancel_epoch"] != run.cancel_epoch
            ):
                item["state"] = "cancelled"
            else:
                try:
                    summary = _pending_visible(session, ctx, run, command, event)
                    item.update(state="pending", command=command.model_dump(mode="json"))
                    if summary is not None:
                        item["summary"] = summary
                except DomainError:
                    pass
        items.append(item)
    return {
        "run_id": str(run.id),
        "items": items,
        "next_cursor": page[-1].sequence if len(rows) > page_size else None,
    }
