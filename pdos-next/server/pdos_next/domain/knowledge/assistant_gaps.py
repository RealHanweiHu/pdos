"""Only explicitly shared question/answer facts leave a private conversation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text

from pdos_next.agent_kernel.models import AgentEvent, AgentRun
from pdos_next.agent_kernel.work_state import user_goal
from pdos_next.category_scope import category_scope
from pdos_next.clock import now
from pdos_next.database import tenant_session
from pdos_next.domain.preproject.access import human, proposal
from pdos_next.errors import DomainError
from pdos_next.models import Category, Principal
from pdos_next.service import Context, digest, require_access

from .assistant_models import KnowledgeGapAttribution, KnowledgeGapSubmission
from .assistant_sources import answer_body, bound_proof, recheck, require


def recipient(session, ctx):
    human(session, ctx)
    category_scope(session, ctx)
    category = session.get(Category, ctx.category_id)
    person = session.get(Principal, category.owner_id)
    require(
        person is not None and person.active and person.kind == "human",
        "当前品类负责人暂不可用。",
        "SOURCE_UNAVAILABLE",
        403,
    )
    return {
        "id": str(person.id),
        "name": person.name,
        "category_id": str(category.id),
        "category_name": category.name,
    }


def _run(session, ctx, identity):
    run = session.get(AgentRun, identity)
    require(
        run is not None
        and run.tenant_id == ctx.tenant_id
        and (run.category_id == ctx.category_id or run.category_id is None)
        and run.requester_id == ctx.requester_id
        and run.state in {"completed", "partial"}
        and run.reverted_at is None,
        "请从当前品类本人的实际回答发起补充请求。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require_access(session, ctx, run.product_id, write=False)
    if run.project_id:
        from pdos_next.agent_kernel.project_scope import require_project

        require_project(session, ctx, run.project_id, run.product_id)
    if run.proposal_id:
        proposal(session, ctx, run.proposal_id)
    return run


def preview(session, ctx, data, *, engine):
    target, run = recipient(session, ctx), _run(session, ctx, data.run_id)
    require(
        (data.kind == "shared_feedback") == (data.feedback_id is not None),
        "请选择本人实际反馈或直接提交补充请求。",
        "VALIDATION_FAILED",
        422,
    )
    proof, answer = [], None
    if data.kind == "shared_feedback":
        feedback = session.get(AgentEvent, data.feedback_id)
        require(
            feedback is not None
            and feedback.run_id == run.id
            and feedback.body.get("type") == "run_feedback"
            and feedback.body.get("recorded_by") == str(ctx.requester_id),
            "只能分享本人的实际反馈回答。",
            "FORBIDDEN_SCOPE",
            403,
        )
        from pdos_next.agent_kernel.execution import scope_for_run
        from pdos_next.enterprise_search import assistant_ledger as ledger
        from pdos_next.enterprise_search.assistant_answer import checked_sources

        actual = checked_sources(session, run)
        issued, _ = ledger.carried(session, scope_for_run(run))
        from .assistant_sources import FIELDS

        proof = [{field: issued[cid][field] for field in FIELDS} for cid in actual]
        bound, _bound_rows = bound_proof(session, run, category_id=ctx.category_id)
        proof = list(
            {(ref["source_type"], ref["source_id"]): ref for ref in [*proof, *bound]}.values()
        )
        require(
            all(ref["category_id"] == str(ctx.category_id) for ref in proof),
            "本回答含其他品类来源。请在目标品类重新查询后分享同品类反馈。",
            "FORBIDDEN_SCOPE",
            403,
        )
        # The recipient is the current real category owner, never a browser member list.
        # This read-only projection does not expose or grant the private Run to them.
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=UUID(target["id"]),
            requester_id=UUID(target["id"]),
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as reading:
            recipient_ctx = Context(
                ctx.tenant_id, UUID(target["id"]), UUID(target["id"]), category_id=ctx.category_id
            )
            require_access(reading, recipient_ctx, run.product_id, write=False)
            if run.project_id:
                from pdos_next.agent_kernel.project_scope import require_project

                require_project(reading, recipient_ctx, run.project_id, run.product_id)
            if run.proposal_id:
                proposal(reading, recipient_ctx, run.proposal_id)
            recheck(reading, proof)
        answer = answer_body(run)
        require(bool(answer), "原反馈尚无可分享的回答正文。", "MISSING_REQUIRED_EVIDENCE", 422)
    from pdos_next.domain.preproject.models import Proposal
    from pdos_next.domain.projects.models import Project
    from pdos_next.models import Product

    product = session.get(Product, run.product_id) if run.product_id else None
    project = session.get(Project, run.project_id) if run.project_id else None
    original = session.get(Proposal, run.proposal_id) if run.proposal_id else None
    value = {
        "kind": data.kind,
        "run_id": str(run.id),
        "feedback_id": str(data.feedback_id) if data.feedback_id else None,
        "question": user_goal(run.goal),
        "answer": answer,
        "search_scope": {
            "category_id": str(ctx.category_id),
            "origin_category_id": str(run.category_id) if run.category_id else None,
            "category_name": target["category_name"],
            "product_name": product.name if product else None,
            "project_name": project.name if project else None,
            "proposal_title": original.title if original else None,
            "product_id": str(run.product_id) if run.product_id else None,
            "project_id": str(run.project_id) if run.project_id else None,
            "proposal_id": str(run.proposal_id) if run.proposal_id else None,
        },
        "recipient": target,
    }
    return {**value, "preview_digest": digest(value)}, proof


def submit(session, ctx, data, *, engine):
    human(session, ctx)
    category_scope(session, ctx)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"knowledge-gap:{ctx.tenant_id}:{ctx.requester_id}:{data.request_key}"},
    )
    fingerprint = digest(data.model_dump(mode="json", exclude={"request_key"}))
    prior = session.scalar(
        select(KnowledgeGapSubmission).where(
            KnowledgeGapSubmission.owner_id == ctx.requester_id,
            KnowledgeGapSubmission.request_key == data.request_key,
        )
    )
    if prior is not None:
        require(
            prior.request_sha256 == fingerprint,
            "原请求编号对应不同分享。",
            "DUPLICATE_INTENT_CONFLICT",
        )
        return submission_receipt(prior)
    value, proof = preview(session, ctx, data, engine=engine)
    require(
        data.preview_digest == value["preview_digest"],
        "接收人或分享内容已变化，请读回最新内容。",
        "VERSION_CONFLICT",
    )
    row = KnowledgeGapSubmission(
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        owner_id=ctx.requester_id,
        recipient_id=UUID(value["recipient"]["id"]),
        run_id=data.run_id,
        feedback_id=data.feedback_id,
        request_key=data.request_key,
        request_sha256=fingerprint,
        kind=data.kind,
        question=value["question"],
        answer=value["answer"],
        search_scope=value["search_scope"],
        source_proof=proof,
    )
    session.add(row)
    session.flush()
    return submission_receipt(row)


def submission_receipt(row):
    return {
        "id": str(row.id),
        "state": "shared",
        "recipient_id": str(row.recipient_id),
        "request_key": str(row.request_key),
        "run_id": str(row.run_id),
        "kind": row.kind,
        "feedback_id": str(row.feedback_id) if row.feedback_id else None,
    }


def recover(session, ctx, data):
    """Read only the actual owner's exact submitted request; never submit on a miss."""
    human(session, ctx)
    category_scope(session, ctx)
    row = session.scalar(
        select(KnowledgeGapSubmission).where(
            KnowledgeGapSubmission.category_id == ctx.category_id,
            KnowledgeGapSubmission.owner_id == ctx.requester_id,
            KnowledgeGapSubmission.request_key == data.request_key,
        )
    )
    require(
        row is not None, "尚未查到原请求；可稍后再次读取，或明确重试同一原请求。", "NOT_FOUND", 404
    )
    require(
        row.request_sha256 == digest(data.model_dump(mode="json", exclude={"request_key"})),
        "原请求编号对应不同分享，请核对原记录。",
        "DUPLICATE_INTENT_CONFLICT",
    )
    return submission_receipt(row)


def manager(session, ctx):
    target = recipient(session, ctx)
    require(
        target["id"] == str(ctx.requester_id),
        "此汇总由当前品类负责人读取。",
        "FORBIDDEN_SCOPE",
        403,
    )
    return target


def week_bounds(value):
    try:
        start = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        require(False, "请选择有效周一日期。", "VALIDATION_FAILED", 422)
    require(start.weekday() == 0, "周报按固定周一至周日汇总。", "VALIDATION_FAILED", 422)
    return start, start + timedelta(days=7)


def weekly(session, ctx, week):
    manager(session, ctx)
    start, end = week_bounds(week)
    rows = session.scalars(
        select(KnowledgeGapSubmission)
        .where(
            KnowledgeGapSubmission.category_id == ctx.category_id,
            KnowledgeGapSubmission.created_at >= start,
            KnowledgeGapSubmission.created_at < end,
        )
        .order_by(KnowledgeGapSubmission.created_at, KnowledgeGapSubmission.id)
    ).all()
    items = []
    for row in rows:
        try:
            recheck(session, row.source_proof)
        except DomainError:
            continue
        marked = session.scalar(
            select(KnowledgeGapAttribution)
            .where(
                KnowledgeGapAttribution.submission_id == row.id,
            )
            .order_by(KnowledgeGapAttribution.created_at.desc(), KnowledgeGapAttribution.id.desc())
        )
        # No requester name/id, private feedback comment, source quotes or other turns.
        items.append(
            {
                "id": str(row.id),
                "kind": row.kind,
                "question": row.question,
                "answer": row.answer,
                "search_scope": row.search_scope,
                "reason": marked.reason if marked else None,
            }
        )
    counts = (
        session.execute(
            text("SELECT * FROM knowledge_weekly_lookup_stats(:tenant,:category,:start,:finish)"),
            {"tenant": ctx.tenant_id, "category": ctx.category_id, "start": start, "finish": end},
        )
        .mappings()
        .one()
    )
    return {
        "week": week,
        "items": items,
        "lookup_rate": dict(counts),
        "as_of": now().isoformat(),
    }


def attribute(session, ctx, data):
    manager(session, ctx)
    submission = session.get(KnowledgeGapSubmission, data.submission_id)
    require(
        submission is not None and submission.category_id == ctx.category_id,
        "这条已分享请求当前不可读。",
        "FORBIDDEN_SCOPE",
        403,
    )
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"knowledge-attribution:{ctx.tenant_id}:{ctx.requester_id}:{data.request_key}"},
    )
    prior = session.scalar(
        select(KnowledgeGapAttribution).where(
            KnowledgeGapAttribution.actor_id == ctx.requester_id,
            KnowledgeGapAttribution.request_key == data.request_key,
        )
    )
    if prior:
        require(
            (prior.submission_id, prior.reason) == (data.submission_id, data.reason),
            "原请求编号对应不同归因。",
            "DUPLICATE_INTENT_CONFLICT",
        )
        return {"id": str(prior.id), "reason": prior.reason}
    row = KnowledgeGapAttribution(
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        actor_id=ctx.requester_id,
        submission_id=data.submission_id,
        request_key=data.request_key,
        reason=data.reason,
    )
    session.add(row)
    session.flush()
    return {"id": str(row.id), "reason": row.reason}
