"""Read native adoption and Run facts again from their real owners at every phase."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from pdos_next.change_completion_schemas import EffectivityPayload, VerificationPayload
from pdos_next.domain.change_control.rules import digest
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import EffectivityFact, VerificationFact

OPERATIONS = frozenset({"change.effectivity.record", "change.verification.record", "change.close"})


def require(value, code="SOURCE_STALE", status=409):
    if not value:
        raise DomainError(code, "实际采用、固定复测原值或具名复核依据无法核对。", status)


def fact_id(payload, order, actor_id):
    if type(payload) is EffectivityPayload:
        # The same actual native event cannot acquire a new identity by changing
        # selected sample order, command key, actor or Change aggregate revision.
        value = (str(order.id), str(payload.item_id), payload.lot.model_dump(mode="json"))
        kind = "adoption"
    else:
        require(type(payload) is VerificationPayload, "INVALID_PAYLOAD", 422)
        value = (
            str(order.id),
            str(actor_id),
            [m.model_dump(mode="json") for m in payload.mappings],
        )
        kind = "verification"
    return uuid5(NAMESPACE_URL, f"pdos-native-change-{kind}:{digest(value)}")


def read_native(s, ctx, pid, request, order, payload, *, at, identity=None):
    identity = identity or fact_id(payload, order, ctx.actor_id)
    if type(payload) is EffectivityPayload:
        from pdos_next.change_build_adoption import read_adoption

        item = next((v for v in order.plan.items if v.id == payload.item_id), None)
        require(item is not None, "FIXED_REFERENCE_MISMATCH")
        implementation = next(
            (v for v in order.implementations if v.item_id == item.id and v.outcome == "succeeded"),
            None,
        )
        require(implementation is not None, "IMPLEMENTATION_INCOMPLETE")
        return read_adoption(
            s,
            ctx,
            pid,
            request,
            order,
            item,
            implementation,
            fact_id=identity,
            lot_id=payload.lot.id,
            lot_revision=payload.lot.revision,
            sample_refs=payload.sample_refs,
            received_at=None,
        )
    require(type(payload) is VerificationPayload, "INVALID_PAYLOAD", 422)
    from pdos_next.change_run_verification import read_verification

    return read_verification(s, ctx, pid, request, order, payload.mappings, fact_id=identity, at=at)


@dataclass(frozen=True)
class CompletionRead:
    fact: EffectivityFact | VerificationFact
    payload: object
    owner: object
    row: object | None = None


def read_recorded(s, ctx, pid, request, order, fact, operation, *, at):
    from pdos_next.change_order_service import _one
    from pdos_next.change_order_store import ChangeCompletionRecord

    row = _one(
        s,
        ChangeCompletionRecord,
        ChangeCompletionRecord.tenant_id == ctx.tenant_id,
        ChangeCompletionRecord.product_id == pid,
        ChangeCompletionRecord.change_id == request.id,
        ChangeCompletionRecord.order_id == order.id,
        ChangeCompletionRecord.fact_id == fact.id,
        ChangeCompletionRecord.operation == operation,
    )
    require(row.fact_snapshot == fact.model_dump(mode="json"), "INTEGRITY_MISMATCH")
    model = EffectivityPayload if operation == "change.effectivity.record" else VerificationPayload
    payload = model.model_validate(row.native_input)
    require(payload.change_id == request.id and payload.visibility == row.visibility)
    if operation == "change.verification.record":
        require(row.actor_id == fact.verifier_id)
        # The verifier embedded in an old immutable fact is its actual named
        # actor. Read with that identity; the current caller's ACL still owns IO.
        # Owner accepts verifier_id only from this server-checked saved atom.
        from pdos_next.change_run_verification import read_verification

        owner = read_verification(
            s,
            ctx,
            pid,
            request,
            order,
            payload.mappings,
            fact_id=fact.id,
            at=at,
            verifier_id=row.actor_id,
        )
    else:
        owner = read_native(s, ctx, pid, request, order, payload, at=at, identity=fact.id)
    require(owner.fact == fact and owner.source_basis == row.owner_basis, "RECHECK_REQUIRED")
    return CompletionRead(fact, payload, owner, row)
