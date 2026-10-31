"""A Human T1 receipt is the authority to resume its original personal candidate."""

from uuid import UUID, uuid4

from sqlalchemy import func, select, text

from pdos_next.category_scope import category_scope
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Category, Receipt
from pdos_next.service import Context, digest

from .graph import VerifiedCategoryAdoption
from .models import AgentEvent, AgentInput, AgentRun

ADOPTION = "category_adoption"
ADOPTED = "category_adopted"


def record(session, candidate, receipt):
    """Called after real candidate validation, within the creation transaction."""
    run, event = candidate.run, candidate.event
    answers = {
        "type": ADOPTION,
        "proof_version": 1,
        "candidate_event_id": str(event.id),
        "candidate_digest": event.body["candidate_digest"],
        "receipt_id": str(receipt.id),
        "category_id": str(receipt.category_id),
        "run_id": str(run.id),
        "cancel_epoch": run.cancel_epoch,
    }
    entry = AgentInput(
        id=uuid4(),
        tenant_id=run.tenant_id,
        run_id=run.id,
        requester_id=run.requester_id,
        idempotency_key="category-adoption:" + str(event.id),
        payload_digest=digest(answers),
        answers=answers,
    )
    sequence = (
        session.scalar(
            select(func.max(AgentEvent.sequence)).where(
                AgentEvent.tenant_id == run.tenant_id,
                AgentEvent.run_id == run.id,
            )
        )
        or 0
    )
    adopted = AgentEvent(
        tenant_id=run.tenant_id,
        run_id=run.id,
        sequence=sequence + 1,
        body={**answers, "type": ADOPTED, "input_ref": str(entry.id)},
    )
    receipt.result = {**receipt.result, "adoption_input_ref": str(entry.id)}
    session.add_all([entry, adopted])
    return entry


def resolve(engine, scope, input_ref):
    """Validate under the original Human, whose new category Grant owns the receipt.

    Ordinary answers never acquire the VerifiedCategoryAdoption server type.
    The Agent is given no new category Grant and its original scope stays personal.
    """
    ctx = Context(
        scope.tenant_id, scope.requester_id, scope.requester_id, category_id=scope.category_id
    )
    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as session:
        return _resolve(session, ctx, scope, input_ref, lock_scope=True)


def _resolve(session, ctx, scope, input_ref, *, lock_scope):
    entry = session.get(AgentInput, UUID(str(input_ref)))
    run = session.get(AgentRun, scope.run_id)
    if (
        not entry
        or not run
        or entry.tenant_id != scope.tenant_id
        or entry.run_id != run.id
        or entry.requester_id != scope.requester_id
        or run.requester_id != scope.requester_id
        or run.writer_id != scope.writer_id
        or run.cancel_epoch != scope.cancel_epoch
        or run.reverted_at
        or run.state in {"failed", "cancelled"}
        or digest(entry.answers) != entry.payload_digest
    ):
        raise DomainError("FORBIDDEN_SCOPE", "答复引用与当前本人运行不一致。")
    if entry.answers.get("type") != ADOPTION:
        return entry.answers
    # The private SQL proof is deliberately not executable by the app role.
    # Read only the actual RLS-visible immutable ledger and receipt here.
    body = entry.answers
    try:
        category_id = UUID(body["category_id"])
        category_scope(
            session,
            Context(ctx.tenant_id, ctx.actor_id, ctx.requester_id, category_id=category_id),
            lock=lock_scope,
        )
        receipt = session.get(Receipt, UUID(body["receipt_id"]))
        category = session.get(Category, category_id)
        candidate = session.get(AgentEvent, UUID(body["candidate_event_id"]))
        adopted = session.scalars(
            select(AgentEvent).where(
                AgentEvent.tenant_id == ctx.tenant_id,
                AgentEvent.run_id == run.id,
                AgentEvent.body["type"].astext == ADOPTED,
                AgentEvent.body["input_ref"].astext == str(entry.id),
            )
        ).all()
        expected = {**body, "type": ADOPTED, "input_ref": str(entry.id)}
        if (
            set(body)
            != {
                "type",
                "proof_version",
                "candidate_event_id",
                "candidate_digest",
                "receipt_id",
                "category_id",
                "run_id",
                "cancel_epoch",
            }
            or type(body["proof_version"]) is not int
            or body["proof_version"] != 1
            or type(body["cancel_epoch"]) is not int
            or body["cancel_epoch"] != run.cancel_epoch
            or body["run_id"] != str(run.id)
            or run.category_id is not None
            or not category
            or category.created_by_run_id != run.id
            or category.owner_id != ctx.requester_id
            or not receipt
            or receipt.actor_id != ctx.requester_id
            or receipt.requester_id != ctx.requester_id
            or receipt.operation != "category.create"
            or receipt.category_id != category_id
            or receipt.subject_id != category_id
            or receipt.subject_type != "category"
            or receipt.agent_run_id is not None
            or receipt.result.get("origin") != "ai_draft"
            or receipt.result.get("prepared_by_run_id") != str(run.id)
            or receipt.result.get("category_candidate_event_id") != body["candidate_event_id"]
            or receipt.result.get("candidate_digest") != body["candidate_digest"]
            or receipt.result.get("adoption_input_ref") != str(entry.id)
            or not candidate
            or candidate.run_id != run.id
            or candidate.body.get("type") != "category_candidate"
            or candidate.body.get("candidate_digest") != body["candidate_digest"]
            or candidate.body.get("cancel_epoch") != run.cancel_epoch
            or len(adopted) != 1
            or adopted[0].body != expected
            or entry.idempotency_key != "category-adoption:" + str(candidate.id)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise DomainError(
            "FORBIDDEN_SCOPE", "采用输入缺少实际候选、本人回执或采用记录。"
        ) from None
    return VerifiedCategoryAdoption(
        str(entry.id),
        {
            key: body[key]
            for key in (
                "candidate_event_id",
                "candidate_digest",
                "run_id",
                "receipt_id",
                "category_id",
                "cancel_epoch",
            )
        },
    )


def read_metadata(session, ctx, run, event):
    """Only a real native receipt/adoption input can mark an owned candidate adopted."""
    from pdos_next.database import require_context

    from .execution import scope_for_run

    require_context(session, ctx)
    if (ctx.actor_id != ctx.requester_id or ctx.requester_id != run.requester_id
            or ctx.tenant_id != run.tenant_id or event.tenant_id != run.tenant_id
            or event.run_id != run.id or event.body.get("type") != "category_candidate"):
        raise DomainError("FORBIDDEN_SCOPE", "候选不在本人当前运行范围。", 403)
    entry = session.scalar(select(AgentInput).where(
        AgentInput.tenant_id == run.tenant_id,
        AgentInput.run_id == run.id,
        AgentInput.requester_id == run.requester_id,
        AgentInput.idempotency_key == "category-adoption:" + str(event.id),
    ))
    if entry is None:
        return None
    verified = _resolve(session, ctx, scope_for_run(run), entry.id, lock_scope=False)
    if not isinstance(verified, VerifiedCategoryAdoption):
        raise DomainError("FORBIDDEN_SCOPE", "采用输入缺少实际本人回执。", 403)
    return {
        "operation": "category.create", "state": "adopted",
        "receipt_id": verified.category_adoption["receipt_id"],
    }


def dispatch_reference(engine, event):
    """Technical role receives three UUIDs after actual Outbox/receipt proof."""
    with tenant_session(engine, UUID(event.tenant_id)) as session:
        row = (
            session.execute(
                text("SELECT * FROM kernel_category_adoption_dispatch(:event)"),
                {"event": UUID(event.event_id)},
            )
            .mappings()
            .one_or_none()
        )
    return dict(row) if row else None
