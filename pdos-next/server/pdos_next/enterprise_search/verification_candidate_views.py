"""Ordinary candidate-list projection for the native verification preparation."""

from pydantic import ValidationError
from sqlalchemy import select

from pdos_next.contracts import Command
from pdos_next.domain.verification_execution.service import get_preparation
from pdos_next.errors import DomainError
from pdos_next.models import Receipt, RequestKey
from pdos_next.schemas.verification.contracts import BuildRef
from pdos_next.service import receipt_view

from . import verification_candidates as bridge


def item(session, ctx, run, event):
    value = {
        "event_id": str(event.id), "sequence": event.sequence,
        "kind": "verification_preparation", "operation": bridge.PREPARATION,
        "command_id": None, "idempotency_key": None, "state": "unavailable",
        "command": None, "receipt": None, "preparation": None,
        "target": None, "basis_count": 0,
    }
    if (run.reverted_at or run.state == "cancelled"
        or event.body.get("cancel_epoch") != run.cancel_epoch):
        value["state"] = "cancelled"
        return value
    try:
        view = bridge.read(session, ctx, run.id, event.id)
        command = Command.model_validate(view["command"])
        if command.operation != bridge.PREPARATION:
            return value
        target = BuildRef.model_validate(event.body["selection"])
        proof = view["source_proof"]
        key = session.scalar(select(RequestKey).where(
            RequestKey.tenant_id == ctx.tenant_id, RequestKey.actor_id == ctx.actor_id,
            RequestKey.key == command.idempotency_key,
        ))
        receipt = session.get(Receipt, key.receipt_id) if key else None
        preparation = None
        if key is not None:
            if (receipt is None or receipt.tenant_id != ctx.tenant_id
                or receipt.command_id != command.command_id
                or receipt.requester_id != ctx.requester_id
                or receipt.category_id != run.category_id or receipt.product_id != run.product_id
                or receipt.operation != bridge.PREPARATION):
                return value
            row, _reading = get_preparation(
                session, ctx, run.product_id, receipt.subject_id, include_capabilities=False,
            )
            preparation = bridge.preparation_binding(command, receipt, row)
        value.update(
            command_id=str(command.command_id), idempotency_key=command.idempotency_key,
            state="adopted" if receipt else "pending", command=command.model_dump(mode="json"),
            receipt=receipt_view(receipt) if receipt else None, preparation=preparation,
            target=target.model_dump(mode="json"),
            basis_count=len(proof["discussion_sources"]) + len(proof["execution_sources"]),
        )
    except (DomainError, KeyError, TypeError, ValueError, ValidationError):
        # The list remains readable while the native owner explains a fresh
        # preview failure. No failed/hidden receipt becomes a fresh candidate.
        pass
    return value
