"""Server-owned immutable links from a private conversation to its saved proposal."""

from sqlalchemy import select

from pdos_next.errors import DomainError

from .models import AgentRun, AgentSession, AgentSessionBinding


def current_proposal_id(session, conversation):
    bound = session.scalar(
        select(AgentSessionBinding.proposal_id).where(
            AgentSessionBinding.tenant_id == conversation.tenant_id,
            AgentSessionBinding.session_id == conversation.id,
        )
    )
    return bound if bound is not None else conversation.proposal_id


def bind_saved_proposal(session, ctx, receipt, proposal):
    if receipt.agent_run_id is None:
        return
    run = session.get(AgentRun, receipt.agent_run_id)
    if (
        run is None
        or run.requester_id != ctx.requester_id
        or run.category_id != ctx.category_id
        or receipt.operation != "proposal.create"
        or receipt.subject_type != "proposal"
        or receipt.subject_id != proposal.id
        or receipt.requester_id != ctx.requester_id
        or receipt.category_id != ctx.category_id
        or proposal.created_by_run_id != run.id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "提案保存回执没有可核对的原会话。")
    conversation = session.scalar(
        select(AgentSession).where(AgentSession.id == run.session_id).with_for_update()
    )
    if (
        conversation is None
        or conversation.owner_id != ctx.requester_id
        or conversation.category_id != run.category_id
        or conversation.product_id != run.product_id
        or conversation.project_id != run.project_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "提案保存范围与原会话不一致。")
    current = current_proposal_id(session, conversation)
    if current is not None and current != proposal.id:
        raise DomainError("VERSION_CONFLICT", "当前会话已绑定其他提案，请新建对话。")
    active_continuation = session.scalar(
        select(AgentRun.id).where(
            AgentRun.tenant_id == ctx.tenant_id,
            AgentRun.session_id == conversation.id,
            AgentRun.proposal_id.is_(None),
            AgentRun.state.in_(["queued", "running", "waiting_input"]),
            AgentRun.id != run.id,
        )
    )
    if active_continuation is not None:
        raise DomainError("VERSION_CONFLICT", "当前会话还有进行中的续聊，请先结束后再保存提案。")
    existing = session.scalar(
        select(AgentSessionBinding).where(
            AgentSessionBinding.tenant_id == ctx.tenant_id,
            AgentSessionBinding.session_id == conversation.id,
        )
    )
    if existing is not None:
        if existing.proposal_id != proposal.id or existing.receipt_id != receipt.id:
            raise DomainError("VERSION_CONFLICT", "当前会话已有其他提案绑定，请核对原回执。")
        return
    session.add(
        AgentSessionBinding(
            tenant_id=ctx.tenant_id,
            session_id=conversation.id,
            owner_id=ctx.requester_id,
            category_id=ctx.category_id,
            proposal_id=proposal.id,
            receipt_id=receipt.id,
        )
    )
    session.flush()
